"""Tests for AVIF clarity/resolution preservation and non-cluttering on-demand exports."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

import collage_generator
import db
import server
import visualize


def _seed_temp_db(db_path: str) -> None:
    db.init_db(db_path)
    with db.get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO listens (listened_at, artist_name, track_name, release_name, duration_ms, year, month, day, hour, day_of_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1760000000, "Test Artist", "Test Song", "Test Album", 240000, 2025, 10, 9, 12, 3),
        )
        cur.execute(
            "INSERT INTO artists (artist_name, country_code, country_name) VALUES (?, ?, ?)",
            ("Test Artist", "DE", "Germany"),
        )
        cur.execute(
            "INSERT INTO albums (artist_name, release_name, original_release_year) VALUES (?, ?, ?)",
            ("Test Artist", "Test Album", 2024),
        )
        cur.execute(
            "INSERT INTO listen_artist_credits (listen_id, artist_name, duration_ms, listened_at) VALUES (?, ?, ?, ?)",
            (1, "Test Artist", 240000, 1760000000),
        )
        conn.commit()


def test_avif_preserves_full_resolution_above_3840(tmp_path: Path):
    canvas = Image.new("RGB", (1800, 4200), (9, 13, 22))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(100, 100), (1700, 4100)], outline=(56, 189, 248), width=4)

    out_path = str(tmp_path / "tall_test.avif")
    collage_generator.save_canvas_image(canvas, out_path, quality=92)

    assert os.path.exists(out_path)
    with Image.open(out_path) as decoded:
        assert decoded.size == (1800, 4200)


def test_avif_uses_sharp_444_chroma_for_colored_text(tmp_path: Path):
    canvas = Image.new("RGB", (600, 200), (9, 13, 22))
    draw = ImageDraw.Draw(canvas)
    for y in range(20, 180, 10):
        draw.line([(20, y), (580, y)], fill=(244, 63, 94), width=1)
        draw.line([(20, y + 4), (580, y + 4)], fill=(56, 189, 248), width=1)

    out_420 = str(tmp_path / "out_420.avif")
    canvas.save(out_420, "AVIF", quality=92, speed=6, subsampling="4:2:0")

    out_default = str(tmp_path / "out_default.avif")
    collage_generator.save_canvas_image(canvas, out_default, quality=92)

    orig = np.asarray(canvas, dtype=np.float32)
    dec_420 = np.asarray(Image.open(out_420).convert("RGB"), dtype=np.float32)
    dec_default = np.asarray(Image.open(out_default).convert("RGB"), dtype=np.float32)

    mse_420 = float(np.mean((orig - dec_420) ** 2))
    mse_default = float(np.mean((orig - dec_default) ** 2))
    assert mse_default < mse_420 * 0.5


def test_visualize_sync_does_not_autogenerate_images(monkeypatch, tmp_path: Path):
    called = []
    monkeypatch.setattr(visualize, "ensure_flag_assets", lambda: 0)
    monkeypatch.setattr(visualize, "get_active_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        visualize,
        "sync_data",
        lambda data_dir=None: {"elapsed_ms": 1.0, "new_scrobbles": 0, "total_listens": 0},
    )
    monkeypatch.setattr(visualize, "get_overall_stats", lambda timeframe="all": {
        "total_minutes": 0, "total_hours": 0, "total_days": 0,
        "total_listens": 0, "avg_daily_minutes": 0,
        "unique_artists": 0, "unique_albums": 0, "unique_tracks": 0,
        "first_listen": None, "last_listen": None,
    })
    monkeypatch.setattr(visualize, "get_top_artists", lambda **kw: [])
    monkeypatch.setattr(visualize, "get_top_albums", lambda **kw: [])
    monkeypatch.setattr(visualize, "get_top_tracks", lambda **kw: [])
    monkeypatch.setattr(visualize, "export_all_visuals", lambda **kw: called.append(kw))
    monkeypatch.setattr(sys, "argv", ["visualize.py", "--sync"])

    visualize.main()
    assert called == []


def test_server_exports_are_transient_and_do_not_clutter_static(monkeypatch, tmp_path: Path):
    temp_db = str(tmp_path / "test.db")
    _seed_temp_db(temp_db)
    temp_exports = str(tmp_path / "transient_exports")

    monkeypatch.setattr(collage_generator, "DB_PATH", temp_db)
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    monkeypatch.setattr(server, "TEMP_EXPORT_DIR", temp_exports, raising=False)

    static_before = set(os.listdir(server.STATIC_DIR))

    import http.server
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.CustomHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        for endpoint in (
            f"http://127.0.0.1:{port}/api/generate-collage?layout=tiered&limit=11&formats=webp",
            f"http://127.0.0.1:{port}/api/generate-table?type=artists&limit=10&formats=webp",
        ):
            with urllib.request.urlopen(endpoint, timeout=15) as resp:
                assert resp.status == 200
                payload = json.loads(resp.read().decode("utf-8"))
            assert payload["success"] is True
            assert len(payload["files"]) == 1
            dl_url = payload["files"][0]["url"]
            assert dl_url.startswith("/api/download-export/")

            with urllib.request.urlopen(f"http://127.0.0.1:{port}{dl_url}", timeout=15) as dl_resp:
                assert dl_resp.status == 200
                cd = dl_resp.headers.get("Content-Disposition", "")
                assert "attachment" in cd
                img_bytes = dl_resp.read()
            with Image.open(io.BytesIO(img_bytes)) as im:
                assert im.width > 100 and im.height > 100

        # Ensure path traversal is rejected
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/download-export/../secret.webp")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=5)
        assert exc_info.value.code in (400, 404)
    finally:
        httpd.shutdown()
        httpd.server_close()

    static_after = set(os.listdir(server.STATIC_DIR))
    assert static_after == static_before
