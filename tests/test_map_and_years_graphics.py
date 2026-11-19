"""Tests for World Map & Release Years graphic exports and API endpoints."""

from __future__ import annotations

import io
import json
import os
import re
import threading
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

import collage_generator
import db
import server


def _seed_rich_db(db_path: str) -> None:
    db.init_db(db_path)
    with db.get_connection(db_path) as conn:
        cur = conn.cursor()
        rows = [
            (1760000000, "Artist DE", "Song One", "Album 2024", 300000, 2025, 10, 9, 12, 3, "DE", "Germany", 2024),
            (1760000400, "Artist DE", "Song One", "Album 2024", 300000, 2025, 10, 9, 12, 3, "DE", "Germany", 2024),
            (1760000800, "Artist US", "Song Two", "Album 1998", 240000, 2025, 10, 9, 13, 3, "US", "United States", 1998),
            (1760001200, "Artist GB", "Song Three", "Album 1973", 420000, 2025, 10, 9, 14, 3, "GB", "United Kingdom", 1973),
            (1760001700, "Artist JP", "Song Four", "Album 2012", 260000, 2025, 10, 9, 15, 3, "JP", "Japan", 2012),
            (1760002000, "Artist FR", "Song Five", "Album 2005", 210000, 2025, 10, 9, 16, 3, "FR", "France", 2005),
            (1760002300, "Artist CA", "Song Six", "Album 2021", 190000, 2025, 10, 9, 17, 3, "CA", "Canada", 2021),
        ]
        for idx, (ts, art, trk, rel, dur, yr, mo, dy, hr, dow, cc, cn, ryr) in enumerate(rows, 1):
            cur.execute(
                """
                INSERT INTO listens (listened_at, artist_name, track_name, release_name, duration_ms, year, month, day, hour, day_of_week)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, art, trk, rel, dur, yr, mo, dy, hr, dow),
            )
            cur.execute(
                "INSERT OR IGNORE INTO artists (artist_name, country_code, country_name) VALUES (?, ?, ?)",
                (art, cc, cn),
            )
            cur.execute(
                "INSERT OR IGNORE INTO albums (artist_name, release_name, original_release_year) VALUES (?, ?, ?)",
                (art, rel, ryr),
            )
            cur.execute(
                "INSERT INTO listen_artist_credits (listen_id, artist_name, duration_ms, listened_at) VALUES (?, ?, ?, ?)",
                (idx, art, dur, ts),
            )
        conn.commit()


def test_generate_world_map_image_renders_webp_and_avif_with_pie(tmp_path: Path):
    temp_db = str(tmp_path / "map_test.db")
    _seed_rich_db(temp_db)
    stem = str(tmp_path / "world_map_test")

    out = collage_generator.generate_world_map_image(
        metric="minutes",
        rank_by="metric",
        top_x=5,
        show_pie=True,
        show_flags=True,
        timeframe="all",
        output_path=stem,
        formats=["webp", "avif"],
        db_path=temp_db,
    )

    assert isinstance(out, list) and len(out) == 2
    for path in out:
        assert os.path.exists(path)
        with Image.open(path) as im:
            assert im.width >= 1400
            assert im.height >= 900


def test_overhauled_artists_and_songs_posters_include_top_right_logo_and_small_lists(tmp_path: Path):
    temp_db = str(tmp_path / "poster_test.db")
    db.init_db(temp_db)
    with db.get_connection(temp_db) as conn:
        cur = conn.cursor()
        # Seed 55 artists & tracks to exercise 2-column grid (#4-#50, odd summary card) + #2/#1/#3 podium
        for idx in range(1, 56):
            ts = 1760000000 + idx * 500
            dur = (60 - idx) * 60000 + 180000
            art = f"Band Number {idx:02d}"
            trk = f"Track Title {idx:02d}"
            rel = f"Release {idx:02d}"
            cur.execute(
                "INSERT INTO listens (listened_at, artist_name, track_name, release_name, duration_ms, year, month, day, hour, day_of_week) VALUES (?, ?, ?, ?, ?, 2025, 10, 9, 12, 3)",
                (ts, art, trk, rel, dur),
            )
            cur.execute(
                "INSERT INTO artists (artist_name, country_code, country_name, country_source) VALUES (?, ?, ?, 'test')",
                (art, ["GB", "US", "DE", "CA", "JP"][idx % 5], ["United Kingdom", "United States", "Germany", "Canada", "Japan"][idx % 5]),
            )
            cur.execute(
                "INSERT INTO listen_artist_credits (listen_id, artist_name, duration_ms, listened_at) VALUES (?, ?, ?, ?)",
                (idx, art, dur, ts),
            )
        conn.commit()

    # Top 50 posters (2-column + odd summary slot)
    art_paths = collage_generator.generate_artists_table_image(
        limit=50, metric="minutes", output_path=str(tmp_path / "art_50"), formats=["webp", "avif"], db_path=temp_db
    )
    song_paths = collage_generator.generate_songs_table_image(
        limit=50, metric="minutes", output_path=str(tmp_path / "song_50"), formats=["webp", "avif"], db_path=temp_db
    )
    assert len(art_paths) == 2 and len(song_paths) == 2

    for p in (art_paths[0], song_paths[0]):
        with Image.open(p) as im:
            assert im.width == 1600
            assert im.height > 1200
            # Verify top-right logo corner actually drew textured pixels (non-uniform alpha composited)
            crop = im.crop((1450, 28, 1556, 130)).convert("RGB")
            extrema = crop.getextrema()
            assert any(hi - lo > 40 for lo, hi in extrema)

    # Edge case: small list (limit=2 -> < 3 podium items, 0 rest items)
    art_small = collage_generator.generate_artists_table_image(
        limit=2, metric="plays", output_path=str(tmp_path / "art_2"), formats=["webp"], db_path=temp_db
    )
    song_small = collage_generator.generate_songs_table_image(
        limit=2, metric="plays", output_path=str(tmp_path / "song_2"), formats=["webp"], db_path=temp_db
    )
    assert art_small and os.path.exists(art_small[0])
    assert song_small and os.path.exists(song_small[0])


def test_generate_world_map_handles_artists_rank_no_flags_and_empty_db(tmp_path: Path):
    temp_db = str(tmp_path / "map_empty.db")
    db.init_db(temp_db)
    assert collage_generator.generate_world_map_image(output_path=str(tmp_path / "empty"), formats=["webp"], db_path=temp_db) is None

    _seed_rich_db(temp_db)
    out = collage_generator.generate_world_map_image(
        metric="plays",
        rank_by="artists",
        top_x=999,
        show_pie=False,
        show_flags=False,
        output_path=str(tmp_path / "world_map_all"),
        formats=["webp"],
        db_path=temp_db,
    )
    assert out and os.path.exists(out[0])


def test_generate_release_years_image_renders_active_and_continuous(tmp_path: Path):
    temp_db = str(tmp_path / "years_test.db")
    db.init_db(temp_db)
    assert collage_generator.generate_release_years_image(output_path=str(tmp_path / "empty_y"), formats=["webp"], db_path=temp_db) is None

    _seed_rich_db(temp_db)
    for mode in ("active", "continuous"):
        out = collage_generator.generate_release_years_image(
            metric="minutes",
            mode=mode,
            timeframe="all",
            output_path=str(tmp_path / f"years_{mode}"),
            formats=["webp", "avif"],
            db_path=temp_db,
        )
        assert isinstance(out, list) and len(out) == 2
        for path in out:
            assert os.path.exists(path)
            with Image.open(path) as im:
                assert im.width >= 1400
                assert im.height >= 800


def test_server_generate_map_and_years_endpoints(monkeypatch, tmp_path: Path):
    temp_db = str(tmp_path / "srv_test.db")
    _seed_rich_db(temp_db)
    temp_exports = str(tmp_path / "transient_exports")

    monkeypatch.setattr(collage_generator, "DB_PATH", temp_db)
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    monkeypatch.setattr(server, "TEMP_EXPORT_DIR", temp_exports)

    static_before = set(os.listdir(server.STATIC_DIR))

    import http.server
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.CustomHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        for url in (
            f"http://127.0.0.1:{port}/api/generate-map?metric=minutes&rank_by=metric&top_x=5&pie=1&flags=1&formats=webp",
            f"http://127.0.0.1:{port}/api/generate-years?metric=minutes&mode=active&formats=webp",
        ):
            with urllib.request.urlopen(url, timeout=15) as resp:
                assert resp.status == 200
                payload = json.loads(resp.read().decode("utf-8"))
            assert payload["success"] is True
            dl_url = payload["files"][0]["url"]
            assert dl_url.startswith("/api/download-export/")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{dl_url}", timeout=15) as dl_resp:
                assert dl_resp.status == 200
                with Image.open(io.BytesIO(dl_resp.read())) as im:
                    assert im.width >= 1400
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert set(os.listdir(server.STATIC_DIR)) == static_before


def test_server_generate_all_returns_zip_with_all_five_graphics_and_flags_default_off(monkeypatch, tmp_path: Path):
    temp_db = str(tmp_path / "srv_all.db")
    _seed_rich_db(temp_db)
    temp_exports = str(tmp_path / "transient_all")

    monkeypatch.setattr(collage_generator, "DB_PATH", temp_db)
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    monkeypatch.setattr(server, "TEMP_EXPORT_DIR", temp_exports)

    static_before = set(os.listdir(server.STATIC_DIR))

    import http.server
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.CustomHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        # Omit flags query param to verify default is flags=0 (noflags)
        url = f"http://127.0.0.1:{port}/api/generate-all?formats=webp&pie=1&limit=11"
        with urllib.request.urlopen(url, timeout=30) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["success"] is True
        assert payload["count"] == 5
        dl_url = payload["url"]
        assert dl_url.endswith(".zip")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}{dl_url}", timeout=15) as dl_resp:
            assert dl_resp.status == 200
            assert dl_resp.headers.get("Content-Type") == "application/zip"
            zip_bytes = dl_resp.read()

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            assert len(names) == 5
            for prefix in ("album_collage", "top_50_artists", "top_50_songs", "release_years", "world_map"):
                matched = [n for n in names if n.startswith(prefix) and n.endswith(".webp")]
                assert len(matched) == 1
                if prefix != "release_years":
                    assert "noflags" in matched[0]
                with Image.open(io.BytesIO(zf.read(matched[0]))) as im:
                    assert im.width >= 1400
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert set(os.listdir(server.STATIC_DIR)) == static_before


def test_france_svg_does_not_overlap_great_britain():
    with open(os.path.join(server.STATIC_DIR, "countries_svg.json"), "r", encoding="utf-8") as fp:
        cs = json.load(fp)
    assert "FR" in cs
    fr_rings = []
    for seg in cs["FR"]["path"].split("Z"):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", seg)]
        if len(nums) >= 4:
            xs, ys = nums[0::2], nums[1::2]
            fr_rings.append((min(xs), min(ys), max(xs), max(ys)))

    mainland = [b for b in fr_rings if 485 <= b[0] <= 525 and 115 <= b[1] <= 145]
    assert mainland, "Expected mainland France polygon inside European map coordinates"
    assert min(b[1] for b in mainland) >= 119.0
    assert max(b[3] for b in mainland) >= 140.0
