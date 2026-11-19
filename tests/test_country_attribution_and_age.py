"""Tests for MBID-based artist country attribution and Spotify-style Listening Age."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import db
import importer


def test_parse_artist_mbids_handles_json_bare_and_csv():
    u1 = "05dffdbe-dc6e-4c8d-a075-50a09c4cb45c"
    u2 = "5b11f4ce-a62d-471e-81fc-a69a8278c7da"
    assert importer.parse_artist_mbids(f'["{u1.upper()}"]') == [u1]
    assert importer.parse_artist_mbids(u1) == [u1]
    assert importer.parse_artist_mbids(f"{u1}, {u2}, invalid-uuid, {u1}") == [u1, u2]
    assert importer.parse_artist_mbids("[]") == []
    assert importer.parse_artist_mbids(None) == []


def test_backfill_artist_mbids_populates_missing_artist_mbid_by_vote(tmp_path: Path):
    temp_db = str(tmp_path / "backfill.db")
    db.init_db(temp_db)
    mbid_a = "05dffdbe-dc6e-4c8d-a075-50a09c4cb45c"
    mbid_b = "5b11f4ce-a62d-471e-81fc-a69a8278c7da"
    mbid_c = "f22942a1-6f70-4f48-866e-238cb2308fbd"

    with db.get_connection(temp_db) as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO listens (listened_at, artist_name, track_name, release_name, duration_ms, artist_mbids)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1760000001, "Architects", "Animals", "FTTWTE", 200000, mbid_a),
                (1760000002, "Architects", "When We Were Young", "Symptoms", 200000, f'["{mbid_a}"]'),
                (1760000003, "Artists Split", "Collab", "Album", 200000, f'["{mbid_b}", "{mbid_c}"]'),
            ],
        )
        cur.executemany(
            "INSERT INTO artists (artist_name) VALUES (?)",
            [("Architects",), ("Artists",), ("Split",)],
        )
        conn.commit()

        # Also check comma/bullet splitting vote
        cur.execute("DELETE FROM listens WHERE artist_name = 'Artists Split'")
        cur.execute("DELETE FROM artists WHERE artist_name IN ('Artists', 'Split')")
        cur.execute(
            """
            INSERT INTO listens (listened_at, artist_name, track_name, release_name, duration_ms, artist_mbids)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1760000004, "Alpha • Beta", "Duet", "Album", 200000, f'["{mbid_b}", "{mbid_c}"]'),
        )
        cur.executemany("INSERT OR IGNORE INTO artists (artist_name) VALUES (?)", [("Alpha",), ("Beta",)])
        conn.commit()

        updated = importer.backfill_artist_mbids(conn)
        assert updated == 3

        rows = {
            r["artist_name"]: r["artist_mbid"]
            for r in cur.execute("SELECT artist_name, artist_mbid FROM artists").fetchall()
        }
        assert rows["Architects"] == mbid_a
        assert rows["Alpha"] == mbid_b
        assert rows["Beta"] == mbid_c


def test_country_enrichment_uses_lb_and_mb_and_replaces_legacy_wrong_countries(monkeypatch, tmp_path: Path):
    temp_db = str(tmp_path / "countries.db")
    db.init_db(temp_db)

    mbid_arch = "05dffdbe-dc6e-4c8d-a075-50a09c4cb45c"
    mbid_nirv = "5b11f4ce-a62d-471e-81fc-a69a8278c7da"
    mbid_aphex = "f22942a1-6f70-4f48-866e-238cb2308fbd"

    with db.get_connection(temp_db) as conn:
        cur = conn.cursor()
        listens = [
            (1760000001, "Architects", "Animals", "For Those That Wish To Exist", 240000, mbid_arch),
            (1760000100, "Nirvana", "Smells Like Teen Spirit", "Nevermind", 300000, f'["{mbid_nirv}"]'),
            (1760000200, "Aphex Twin", "Windowlicker", "Windowlicker", 360000, mbid_aphex),
            (1760000300, "Mystery Homonym", "Track A", "Album A", 200000, None),
        ]
        for idx, (ts, art, trk, rel, dur, mbids) in enumerate(listens, 1):
            cur.execute(
                """
                INSERT INTO listens (listened_at, artist_name, track_name, release_name, duration_ms, artist_mbids)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts, art, trk, rel, dur, mbids),
            )
            cur.execute(
                "INSERT INTO listen_artist_credits (listen_id, artist_name, duration_ms, listened_at) VALUES (?, ?, ?, ?)",
                (idx, art, dur, ts),
            )

        # Seed legacy bogus Wikipedia guesses (country_source IS NULL)
        cur.execute(
            "INSERT INTO artists (artist_name, artist_mbid, country_code, country_name, country_fetched) VALUES (?, ?, 'GR', 'Greece', 1)",
            ("Architects", mbid_arch),
        )
        cur.execute(
            "INSERT INTO artists (artist_name, artist_mbid, country_code, country_name, country_fetched) VALUES (?, ?, 'IN', 'India', 1)",
            ("Nirvana", None),
        )
        cur.execute(
            "INSERT INTO artists (artist_name, artist_mbid, country_code, country_name, country_fetched) VALUES (?, ?, 'US', 'United States', 1)",
            ("Aphex Twin", mbid_aphex),
        )
        cur.execute(
            "INSERT INTO artists (artist_name, artist_mbid, country_code, country_name, country_fetched) VALUES (?, ?, 'GR', 'Greece', 1)",
            ("Dido", None),
        )
        cur.execute(
            "INSERT INTO artists (artist_name, artist_mbid, country_code, country_name, country_fetched) VALUES (?, ?, 'FR', 'France', 1)",
            ("Mystery Homonym", None),
        )
        conn.commit()

        # ListenBrainz returns sovereign names for Architects & Nirvana, but a city ("London") for Aphex Twin
        monkeypatch.setattr(
            importer,
            "_fetch_listenbrainz_artist_metadata_batch",
            lambda mbids: {
                mbid_arch: {"artist_mbid": mbid_arch, "area": "United Kingdom"},
                mbid_nirv: {"artist_mbid": mbid_nirv, "area": "United States"},
                mbid_aphex: {"artist_mbid": mbid_aphex, "area": "London"},
            },
        )
        # MusicBrainz WS2 resolves Aphex Twin city -> GB via country field
        monkeypatch.setattr(
            importer,
            "_fetch_musicbrainz_artist_country_by_mbid",
            lambda mbid: ("GB", "United Kingdom") if mbid == mbid_aphex else None,
        )
        # Ambiguous homonym / unknown search returns no confident country -> clears bogus legacy guesses
        monkeypatch.setattr(
            importer,
            "_search_musicbrainz_artist_country",
            lambda name, rels=(): (None, None, None),
        )

        updated = importer.enrich_all_artist_countries(conn, limit=50, min_plays=1, refresh_legacy=True)
        assert updated == 3

        rows = {
            r["artist_name"]: dict(r)
            for r in cur.execute("SELECT * FROM artists").fetchall()
        }
        assert rows["Architects"]["country_code"] == "GB"
        assert rows["Architects"]["country_name"] == "United Kingdom"
        assert rows["Architects"]["country_source"] == "listenbrainz_mbid"

        assert rows["Nirvana"]["artist_mbid"] == mbid_nirv
        assert rows["Nirvana"]["country_code"] == "US"
        assert rows["Nirvana"]["country_name"] == "United States"
        assert rows["Nirvana"]["country_source"] == "listenbrainz_mbid"

        assert rows["Aphex Twin"]["country_code"] == "GB"
        assert rows["Aphex Twin"]["country_source"] == "musicbrainz_mbid"

        # Bogus legacy guesses with no authoritative match are cleared instead of kept
        assert rows["Dido"]["country_code"] is None
        assert rows["Dido"]["country_source"] == "none"
        assert rows["Mystery Homonym"]["country_code"] is None
        assert rows["Mystery Homonym"]["country_source"] == "none"


def test_listening_age_calculation_in_release_years_stats(tmp_path: Path):
    temp_db = str(tmp_path / "age.db")
    db.init_db(temp_db)
    with db.get_connection(temp_db) as conn:
        cur = conn.cursor()
        # Equal duration (300,000 ms each) for 2000 and 2010 -> exact weighted avg 2005.0
        rows = [
            (1760000001, "Art A", "Song A", "Album 2000", 300000, 2000),
            (1760000301, "Art B", "Song B", "Album 2010", 300000, 2010),
        ]
        for idx, (ts, art, trk, rel, dur, ryr) in enumerate(rows, 1):
            cur.execute(
                "INSERT INTO listens (listened_at, artist_name, track_name, release_name, duration_ms) VALUES (?, ?, ?, ?, ?)",
                (ts, art, trk, rel, dur),
            )
            cur.execute(
                "INSERT INTO albums (artist_name, release_name, original_release_year) VALUES (?, ?, ?)",
                (art, rel, ryr),
            )
            cur.execute(
                "INSERT INTO listen_artist_credits (listen_id, artist_name, duration_ms, listened_at) VALUES (?, ?, ?, ?)",
                (idx, art, dur, ts),
            )
        conn.commit()

    payload = db.get_release_years_stats(metric="minutes", db_path=temp_db)
    summary = payload["summary"]
    assert summary["weighted_avg_year"] == 2005.0
    assert summary["listening_age_anchor"] == db.REMINISCENCE_BUMP_AGE
    expected_age = max(13, int(round(datetime.now().year - 2005.0 + db.REMINISCENCE_BUMP_AGE)))
    assert summary["listening_age"] == expected_age
