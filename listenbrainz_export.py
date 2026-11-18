"""Automated ListenBrainz User Data Export API client and safe credential store."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple

import db
import importer

LISTENBRAINZ_API_BASE = "https://api.listenbrainz.org"
USER_AGENT = "MusicBrainzWrapped/2.0 (https://github.com/Lakis01/musicbrainz_wrapped)"
CONFIG_PATH = importer.CONFIG_PATH
IMPORTS_DIR = importer.IMPORTS_DIR

_SESSION_TOKEN: Optional[str] = None
_JOB_LOCK = threading.Lock()
_JOB_STATE: Dict[str, Any] = {
    "state": "idle",
    "export_id": None,
    "progress": "",
    "filename": None,
    "error": None,
    "sync": None,
    "started_at": None,
    "finished_at": None,
}


def _redact(text: str, token: Optional[str]) -> str:
    msg = str(text)
    if token and token in msg:
        msg = msg.replace(token, "[REDACTED]")
    return msg


def _mask_token(token: Optional[str]) -> str:
    if not token:
        return ""
    if len(token) <= 4:
        return "••••"
    return f"••••{token[-4:]}"


def _load_cfg() -> Dict[str, Any]:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def _save_cfg_secure(cfg: Dict[str, Any]) -> None:
    parent = os.path.dirname(CONFIG_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{CONFIG_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(cfg, fp, indent=2)
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def _resolve_token(explicit_token: Optional[str] = None) -> Tuple[Optional[str], str]:
    if explicit_token is not None and explicit_token.strip():
        return explicit_token.strip(), "provided"
    env_tok = os.environ.get("LISTENBRAINZ_USER_TOKEN", "").strip()
    if env_tok:
        return env_tok, "env"
    if _SESSION_TOKEN:
        return _SESSION_TOKEN, "session"
    saved = str(_load_cfg().get("listenbrainz_user_token") or "").strip()
    if saved:
        return saved, "config"
    return None, "none"


def get_token_status() -> Dict[str, Any]:
    tok, src = _resolve_token()
    return {
        "has_token": bool(tok),
        "source": src,
        "masked": _mask_token(tok),
    }


def set_token(token: str, remember: bool = False) -> Dict[str, Any]:
    global _SESSION_TOKEN
    cleaned = str(token or "").strip()
    if not cleaned or any(c.isspace() or ord(c) < 32 for c in cleaned):
        raise ValueError("Please enter a valid ListenBrainz User Token (no spaces or control characters).")
    if remember:
        cfg = _load_cfg()
        cfg["listenbrainz_user_token"] = cleaned
        _save_cfg_secure(cfg)
        _SESSION_TOKEN = None
    else:
        _SESSION_TOKEN = cleaned
    return get_token_status()


def clear_token() -> Dict[str, Any]:
    global _SESSION_TOKEN
    _SESSION_TOKEN = None
    cfg = _load_cfg()
    if "listenbrainz_user_token" in cfg:
        cfg.pop("listenbrainz_user_token", None)
        _save_cfg_secure(cfg)
    return get_token_status()


class _UrllibTransport:
    """Standard-library HTTP transport for ListenBrainz Export API."""

    def request_json(
        self, method: str, url: str, headers: Dict[str, str], body: Optional[bytes] = None
    ) -> Tuple[int, Dict[str, str], Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", "replace")
                parsed = json.loads(raw) if raw.strip() else {}
                return resp.status, dict(resp.headers.items()), parsed
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            try:
                parsed = json.loads(raw) if raw.strip() else {}
            except Exception:
                parsed = {"error": raw or str(exc)}
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, parsed

    def download_to_file(
        self, url: str, headers: Dict[str, str], dest_path: str
    ) -> Tuple[int, Dict[str, str]]:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp_path = f"{dest_path}.part"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                hdrs = dict(resp.headers.items())
                with open(tmp_path, "wb") as fp:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        fp.write(chunk)
                os.replace(tmp_path, dest_path)
                return resp.status, hdrs
        except urllib.error.HTTPError as exc:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return exc.code, dict(exc.headers.items()) if exc.headers else {}
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise


def _extract_filename_from_headers(headers: Dict[str, str]) -> Optional[str]:
    for k, v in headers.items():
        if k.lower() == "content-disposition":
            m = re.search(r'filename="?([^";]+)"?', v, re.IGNORECASE)
            if m:
                return os.path.basename(m.group(1).strip())
    return None


def _api_headers(token: str, has_body: bool = False) -> Dict[str, str]:
    h = {
        "Authorization": f"Token {token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if has_body:
        h["Content-Type"] = "application/json"
    return h


def run_export_and_sync(
    token: Optional[str] = None,
    transport: Optional[Any] = None,
    imports_dir: str = IMPORTS_DIR,
    db_path: str = db.DB_PATH,
    poll_interval: float = 15.0,
    max_polls: int = 120,
    on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Queue (or resume) a ListenBrainz export, poll, download ZIP, extract into imports/, and sync."""
    resolved_token, _ = _resolve_token(token)
    if not resolved_token:
        raise ValueError("ListenBrainz User Token is not set.")

    client = transport or _UrllibTransport()

    def _emit(step: str, extra: Optional[Dict[str, Any]] = None) -> None:
        if on_progress:
            on_progress(step, extra or {})

    try:
        _emit("requesting", {"progress": "Requesting export job on ListenBrainz..."})
        create_url = f"{LISTENBRAINZ_API_BASE}/1/export/"
        status, hdrs, payload = client.request_json(
            "POST", create_url, _api_headers(resolved_token, has_body=True), b"{}"
        )

        if status == 401:
            raise RuntimeError("ListenBrainz rejected the User Token (401 Unauthorized).")
        if status == 429:
            wait_s = min(60.0, float(hdrs.get("X-RateLimit-Reset-In", "15") or 15))
            if poll_interval > 0:
                time.sleep(wait_s)
            status, hdrs, payload = client.request_json(
                "POST", create_url, _api_headers(resolved_token, has_body=True), b"{}"
            )

        export_obj: Optional[Dict[str, Any]] = None
        if status in (400, 409):
            # Another export may already be waiting/in_progress — inspect existing list
            l_status, _, l_payload = client.request_json(
                "GET", f"{LISTENBRAINZ_API_BASE}/1/export/list", _api_headers(resolved_token), None
            )
            if l_status == 200 and isinstance(l_payload, list):
                for item in l_payload:
                    if isinstance(item, dict) and item.get("status") in ("waiting", "in_progress"):
                        export_obj = item
                        break
            if export_obj is None:
                err_detail = payload.get("error") if isinstance(payload, dict) else str(payload)
                raise RuntimeError(f"ListenBrainz export request rejected ({status}): {err_detail}")
        elif status >= 400:
            err_detail = payload.get("error") if isinstance(payload, dict) else str(payload)
            raise RuntimeError(f"ListenBrainz export request failed ({status}): {err_detail}")
        else:
            export_obj = payload if isinstance(payload, dict) else {}

        export_id = export_obj.get("export_id")
        if export_id is None:
            raise RuntimeError("ListenBrainz did not return an export_id.")

        cur_status = export_obj.get("status", "waiting")
        cur_progress = export_obj.get("progress") or "Export queued on ListenBrainz..."
        _emit(cur_status if cur_status in ("waiting", "in_progress") else "waiting", {
            "export_id": export_id,
            "progress": cur_progress,
        })

        polls = 0
        while cur_status not in ("completed", "failed"):
            if polls >= max_polls:
                raise RuntimeError(f"Timed out waiting for ListenBrainz export #{export_id} to complete.")
            if poll_interval > 0:
                time.sleep(min(45.0, poll_interval * (1.0 + polls * 0.15)))
            polls += 1
            p_status, p_hdrs, p_payload = client.request_json(
                "GET", f"{LISTENBRAINZ_API_BASE}/1/export/{export_id}", _api_headers(resolved_token), None
            )
            if p_status == 401:
                raise RuntimeError("ListenBrainz rejected the User Token (401 Unauthorized).")
            if p_status == 429:
                if poll_interval > 0:
                    time.sleep(min(60.0, float(p_hdrs.get("X-RateLimit-Reset-In", "15") or 15)))
                continue
            if p_status >= 400 or not isinstance(p_payload, dict):
                raise RuntimeError(f"Failed polling export #{export_id} ({p_status}).")
            export_obj = p_payload
            cur_status = export_obj.get("status", "waiting")
            cur_progress = export_obj.get("progress") or f"Status: {cur_status}"
            if cur_status in ("waiting", "in_progress"):
                _emit(cur_status, {"export_id": export_id, "progress": cur_progress})

        if cur_status == "failed":
            raise RuntimeError(f"ListenBrainz export #{export_id} failed: {export_obj.get('progress') or 'Unknown error'}")

        raw_fname = str(export_obj.get("filename") or f"listenbrainz_export_{export_id}.zip")
        safe_fname = os.path.basename(raw_fname) or f"listenbrainz_export_{export_id}.zip"
        if not safe_fname.lower().endswith(".zip"):
            safe_fname += ".zip"
        dest_zip = os.path.join(imports_dir, safe_fname)

        _emit("downloading", {"export_id": export_id, "progress": f"Downloading {safe_fname}...", "filename": safe_fname})
        dl_url = f"{LISTENBRAINZ_API_BASE}/1/export/{export_id}/download"
        dl_status, dl_hdrs = client.download_to_file(dl_url, _api_headers(resolved_token), dest_zip)
        if dl_status >= 400 or not os.path.isfile(dest_zip):
            raise RuntimeError(f"Failed downloading export #{export_id} (HTTP {dl_status}).")

        hdr_name = _extract_filename_from_headers(dl_hdrs)
        if hdr_name and hdr_name.lower().endswith(".zip") and hdr_name != safe_fname:
            renamed = os.path.join(imports_dir, hdr_name)
            os.replace(dest_zip, renamed)
            dest_zip = renamed
            safe_fname = hdr_name

        _emit("extracting", {"export_id": export_id, "progress": f"Extracting {safe_fname} into imports/...", "filename": safe_fname})
        extracted_dir = importer.extract_archive(dest_zip, target_parent=imports_dir)
        if not extracted_dir:
            raise RuntimeError(f"Downloaded archive {safe_fname} did not contain valid ListenBrainz JSONL data.")

        cfg = _load_cfg()
        cfg["data_dir"] = extracted_dir
        cfg["username"] = importer.read_export_username(extracted_dir)
        _save_cfg_secure(cfg)

        _emit("syncing", {"export_id": export_id, "progress": "Importing listens into SQLite & enriching metadata...", "filename": safe_fname})
        sync_res = importer.sync_data(db_path=db_path, data_dir=extracted_dir)

        return {
            "export_id": export_id,
            "archive_path": dest_zip,
            "extracted_dir": extracted_dir,
            "filename": safe_fname,
            "sync": sync_res,
        }
    except Exception as exc:
        raise RuntimeError(_redact(str(exc), resolved_token)) from None


def get_export_job_status() -> Dict[str, Any]:
    with _JOB_LOCK:
        return dict(_JOB_STATE)


def start_background_export(
    token: Optional[str] = None,
    remember: bool = False,
    transport: Optional[Any] = None,
    imports_dir: str = IMPORTS_DIR,
    db_path: str = db.DB_PATH,
    poll_interval: float = 15.0,
) -> Dict[str, Any]:
    if token is not None and token.strip():
        set_token(token, remember=remember)

    resolved_token, _ = _resolve_token(token)
    if not resolved_token:
        raise ValueError("Please provide your ListenBrainz User Token first.")

    with _JOB_LOCK:
        if _JOB_STATE["state"] in ("requesting", "waiting", "in_progress", "downloading", "extracting", "syncing"):
            return dict(_JOB_STATE)
        _JOB_STATE.update({
            "state": "requesting",
            "export_id": None,
            "progress": "Starting ListenBrainz export request...",
            "filename": None,
            "error": None,
            "sync": None,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
        })
        snapshot = dict(_JOB_STATE)

    def _on_progress(step: str, extra: Dict[str, Any]) -> None:
        with _JOB_LOCK:
            _JOB_STATE["state"] = step
            for key in ("export_id", "progress", "filename"):
                if key in extra and extra[key] is not None:
                    _JOB_STATE[key] = extra[key]

    def _worker() -> None:
        try:
            res = run_export_and_sync(
                token=resolved_token,
                transport=transport,
                imports_dir=imports_dir,
                db_path=db_path,
                poll_interval=poll_interval,
                on_progress=_on_progress,
            )
            with _JOB_LOCK:
                _JOB_STATE.update({
                    "state": "completed",
                    "export_id": res["export_id"],
                    "filename": res["filename"],
                    "sync": res["sync"],
                    "progress": f"Imported {res['sync'].get('total_listens', 0):,} listens ({res['sync'].get('new_scrobbles', 0)} new).",
                    "error": None,
                    "finished_at": datetime.now().isoformat(),
                })
        except Exception as exc:
            with _JOB_LOCK:
                _JOB_STATE.update({
                    "state": "failed",
                    "error": _redact(str(exc), resolved_token),
                    "progress": "Export failed.",
                    "finished_at": datetime.now().isoformat(),
                })

    threading.Thread(target=_worker, daemon=True).start()
    return snapshot
