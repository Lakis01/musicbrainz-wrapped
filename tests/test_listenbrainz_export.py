"""Tests for safe ListenBrainz User Token handling and automated export/download/unzip/sync."""

from __future__ import annotations

import io
import json
import os
import stat
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

import db
import importer
import listenbrainz_export
import server


def _make_sample_export_zip(username: str = "ApiTestUser") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("user.json", json.dumps({"user_id": 123, "username": username}))
        listen_obj = {
            "listened_at": 1761000000,
            "track_metadata": {
                "artist_name": "API Sync Band",
                "track_name": "Auto Downloaded Track",
                "release_name": "API Export Album",
                "additional_info": {"duration_ms": 210000},
            },
        }
        zf.writestr("listens/2026/11.jsonl", json.dumps(listen_obj) + "\n")
    return buf.getvalue()


class _FakeTransport:
    def __init__(self, responses: Dict[Tuple[str, str], List[Any]]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: List[Tuple[str, str, Dict[str, str], Any]] = []

    def request_json(
        self, method: str, url: str, headers: Dict[str, str], body: Optional[bytes] = None
    ) -> Tuple[int, Dict[str, str], Any]:
        self.calls.append((method, url, dict(headers), body))
        key = (method.upper(), url)
        queue = self.responses.get(key)
        if not queue:
            raise AssertionError(f"Unexpected HTTP call: {key}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def download_to_file(
        self, url: str, headers: Dict[str, str], dest_path: str
    ) -> Tuple[int, Dict[str, str]]:
        self.calls.append(("DOWNLOAD", url, dict(headers), dest_path))
        key = ("DOWNLOAD", url)
        queue = self.responses.get(key)
        if not queue:
            raise AssertionError(f"Unexpected DOWNLOAD call: {url}")
        status, hdrs, raw_bytes = queue.pop(0)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as fp:
            fp.write(raw_bytes)
        return status, hdrs


def test_token_storage_masks_preview_and_sets_0600_permissions(monkeypatch, tmp_path: Path):
    cfg_path = str(tmp_path / "config.json")
    monkeypatch.setattr(importer, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(listenbrainz_export, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(listenbrainz_export, "_SESSION_TOKEN", None)
    monkeypatch.delenv("LISTENBRAINZ_USER_TOKEN", raising=False)

    assert listenbrainz_export.get_token_status()["has_token"] is False

    secret = "lb-secret-token-1234567890"
    status = listenbrainz_export.set_token(secret, remember=True)
    assert status["has_token"] is True
    assert status["source"] == "config"
    assert secret not in json.dumps(status)
    assert status["masked"].endswith("7890")
    assert stat.S_IMODE(os.stat(cfg_path).st_mode) == 0o600

    # Env var overrides saved config safely
    monkeypatch.setenv("LISTENBRAINZ_USER_TOKEN", "env-token-abcd")
    env_status = listenbrainz_export.get_token_status()
    assert env_status["source"] == "env"
    assert env_status["masked"].endswith("abcd")
    monkeypatch.delenv("LISTENBRAINZ_USER_TOKEN", raising=False)

    cleared = listenbrainz_export.clear_token()
    assert cleared["has_token"] is False
    assert cleared["source"] == "none"


def test_token_is_redacted_from_errors(monkeypatch, tmp_path: Path):
    secret = "super-secret-lb-token-9999"
    monkeypatch.setattr(listenbrainz_export, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    monkeypatch.setattr(listenbrainz_export, "_SESSION_TOKEN", None)
    monkeypatch.delenv("LISTENBRAINZ_USER_TOKEN", raising=False)

    class _ExplodingTransport:
        def request_json(self, *args, **kwargs):
            raise RuntimeError(f"Auth failure using Token {secret}")

    with pytest.raises(RuntimeError) as exc_info:
        listenbrainz_export.run_export_and_sync(
            token=secret,
            transport=_ExplodingTransport(),
            imports_dir=str(tmp_path / "imports"),
            db_path=str(tmp_path / "lb.db"),
            poll_interval=0.0,
        )
    assert secret not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_export_pipeline_queues_polls_downloads_extracts_and_syncs(monkeypatch, tmp_path: Path):
    imports_dir = str(tmp_path / "imports")
    temp_db = str(tmp_path / "test_lb.db")
    cfg_path = str(tmp_path / "config.json")
    monkeypatch.setattr(importer, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(importer, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(importer, "DB_PATH", temp_db)
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    monkeypatch.setattr(listenbrainz_export, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(listenbrainz_export, "IMPORTS_DIR", imports_dir)

    db.init_db(temp_db)
    zip_bytes = _make_sample_export_zip("ApiTestUser")
    secret = "valid-user-token-4242"

    transport = _FakeTransport({
        ("POST", "https://api.listenbrainz.org/1/export/"): [
            (200, {}, {"export_id": 42, "status": "waiting", "progress": "Queued"})
        ],
        ("GET", "https://api.listenbrainz.org/1/export/42"): [
            (200, {}, {"export_id": 42, "status": "in_progress", "progress": "Compiling..."}),
            (200, {}, {"export_id": 42, "status": "completed", "filename": "listenbrainz_ApiTestUser_42.zip", "progress": "Ready"}),
        ],
        ("DOWNLOAD", "https://api.listenbrainz.org/1/export/42/download"): [
            (200, {"Content-Disposition": 'attachment; filename="listenbrainz_ApiTestUser_42.zip"'}, zip_bytes)
        ],
    })

    # Avoid external MusicBrainz/CoverArt HTTP enrichment and repo manual_entries during unit test
    monkeypatch.setattr(importer, "enrich_all_metadata", lambda *a, **kw: None)
    monkeypatch.setattr(importer, "load_manual_entries", lambda *a, **kw: [])
    monkeypatch.setattr(importer, "load_manual_entries", lambda *a, **kw: [])

    res = listenbrainz_export.run_export_and_sync(
        token=secret,
        transport=transport,
        imports_dir=imports_dir,
        db_path=temp_db,
        poll_interval=0.0,
    )

    assert res["export_id"] == 42
    assert os.path.isfile(res["archive_path"])
    assert os.path.isdir(res["extracted_dir"])
    assert res["sync"]["new_scrobbles"] == 1
    assert res["sync"]["username"] == "ApiTestUser"
    with db.get_connection(temp_db) as conn:
        row = conn.execute("SELECT track_name FROM listens WHERE artist_name = 'API Sync Band'").fetchone()
        assert row is not None and row["track_name"] == "Auto Downloaded Track"
    # Verify Authorization header used exact Token format
    assert transport.calls[0][2]["Authorization"] == f"Token {secret}"


def test_pending_400_conflict_reuses_existing_export_from_list(monkeypatch, tmp_path: Path):
    imports_dir = str(tmp_path / "imports")
    temp_db = str(tmp_path / "test_conflict.db")
    cfg_path = str(tmp_path / "config.json")
    monkeypatch.setattr(importer, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(importer, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(importer, "DB_PATH", temp_db)
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    monkeypatch.setattr(listenbrainz_export, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(listenbrainz_export, "IMPORTS_DIR", imports_dir)
    monkeypatch.setattr(importer, "enrich_all_metadata", lambda *a, **kw: None)
    monkeypatch.setattr(importer, "load_manual_entries", lambda *a, **kw: [])

    db.init_db(temp_db)
    zip_bytes = _make_sample_export_zip("PendingUser")

    transport = _FakeTransport({
        ("POST", "https://api.listenbrainz.org/1/export/"): [
            (400, {}, {"error": "An export is already pending for this user."})
        ],
        ("GET", "https://api.listenbrainz.org/1/export/list"): [
            (200, {}, [{"export_id": 99, "status": "in_progress", "progress": "Running..."}])
        ],
        ("GET", "https://api.listenbrainz.org/1/export/99"): [
            (200, {}, {"export_id": 99, "status": "completed", "filename": "listenbrainz_PendingUser_99.zip", "progress": "Ready"})
        ],
        ("DOWNLOAD", "https://api.listenbrainz.org/1/export/99/download"): [
            (200, {}, zip_bytes)
        ],
    })

    res = listenbrainz_export.run_export_and_sync(
        token="pending-tok-99",
        transport=transport,
        imports_dir=imports_dir,
        db_path=temp_db,
        poll_interval=0.0,
    )
    assert res["export_id"] == 99
    assert res["sync"]["new_scrobbles"] == 1
    with db.get_connection(temp_db) as conn:
        row = conn.execute("SELECT track_name FROM listens WHERE artist_name = 'API Sync Band'").fetchone()
        assert row is not None


def test_server_token_and_export_endpoints_never_leak_token(monkeypatch, tmp_path: Path):
    cfg_path = str(tmp_path / "config.json")
    temp_db = str(tmp_path / "srv_lb.db")
    db.init_db(temp_db)

    monkeypatch.setattr(importer, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(listenbrainz_export, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(listenbrainz_export, "_SESSION_TOKEN", None)
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    monkeypatch.delenv("LISTENBRAINZ_USER_TOKEN", raising=False)

    import http.server
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.CustomHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        secret = "never-leak-this-token-7788"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/listenbrainz-token",
            data=json.dumps({"token": secret, "remember": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            tok_resp = json.loads(resp.read().decode("utf-8"))
        assert tok_resp["listenbrainz_token"]["has_token"] is True
        assert secret not in json.dumps(tok_resp)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=5) as resp:
            cfg_raw = resp.read().decode("utf-8")
        assert secret not in cfg_raw
        cfg_json = json.loads(cfg_raw)
        assert cfg_json["listenbrainz_token"]["has_token"] is True
        assert cfg_json["listenbrainz_token"]["masked"].endswith("7788")
    finally:
        httpd.shutdown()
        httpd.server_close()
