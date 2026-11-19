"""SQLite analytics storage and query layer for ListenBrainz Visualizer."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "listenbrainz.db")
REMINISCENCE_BUMP_AGE = 18

UNIFIED_COLLABORATIONS = {
    "will ramos & nik nocturnal",
    "will ramos & nik nokturnal",
    "milton nascimento & lô borges",
    "milton nascimento • lô borges",
    "milton nascimento & lo borges",
    "shye ben tzur, jonny greenwood and the rajasthan express",
    "angelo badalamenti • the city of prague philharmonic",
    "eddie money • ronnie spector",
    "evgeny kolobov • novaya opera theatre",
    "kent nagano • orchestre symphonique de montréal",
    "mike perry • shy martin",
    "milleniumkid • jbs",
    "nino rota • livio giorgi",
    "pat enright; harley allen; dan tyminski • the soggy bottom boys",
    "snarky puppy • laura mvula • michelle willis",
    "this wild life • nilu madadi",
    "zedd • maren morris • grey",
}


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def split_artist_names(raw_name: Optional[str]) -> List[str]:
    if not raw_name:
        return []
    clean = raw_name.strip()
    low = clean.lower()

    if low in UNIFIED_COLLABORATIONS:
        return [clean]

    exceptions = {
        "ac/dc", "p.o.d.", "in extremo", "alter bridge", "black sabbath",
        "the beatles", "kids see ghosts", "frank carter & the rattlesnakes",
        "king gizzard & the lizard wizard", "matt skiba and the sekrets",
        "wiener akademie", "berliner philharmoniker", "gothenburg symphony orchestra",
    }
    if low in exceptions:
        return [clean]

    if " with " in clean:
        return [p.strip() for p in clean.split(" with ") if p.strip()]
    if " • " in clean:
        return [p.strip() for p in clean.split(" • ") if p.strip()]
    if " + " in clean:
        return [p.strip() for p in clean.split(" + ") if p.strip()]
    if re.search(r" (feat\.|ft\.|featuring) ", clean, re.IGNORECASE):
        parts = re.split(r" feat\. | ft\. | featuring ", clean, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]

    return [clean]


def init_db(db_path: str = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS listens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listened_at INTEGER NOT NULL,
            artist_name TEXT NOT NULL,
            track_name TEXT NOT NULL,
            release_name TEXT,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            recording_mbid TEXT,
            release_mbid TEXT,
            caa_release_mbid TEXT,
            caa_id TEXT,
            artist_mbids TEXT,
            submission_client TEXT,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            hour INTEGER,
            day_of_week INTEGER,
            original_release_year INTEGER,
            UNIQUE(listened_at, artist_name, track_name)
        )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listens_artist ON listens(artist_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listens_album ON listens(artist_name, release_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listens_track ON listens(artist_name, track_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listens_time ON listens(listened_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listens_year_month ON listens(year, month)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS artists (
            artist_name TEXT PRIMARY KEY,
            artist_mbid TEXT,
            image_url TEXT,
            image_local_path TEXT,
            image_fetched INTEGER DEFAULT 0,
            country_code TEXT,
            country_name TEXT,
            country_fetched INTEGER DEFAULT 0,
            country_source TEXT
        )
        """)
        artist_cols = {c[1] for c in cursor.execute("PRAGMA table_info(artists)").fetchall()}
        if "country_source" not in artist_cols:
            cursor.execute("ALTER TABLE artists ADD COLUMN country_source TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artists_country ON artists(country_code)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist_name TEXT NOT NULL,
            release_name TEXT NOT NULL,
            release_mbid TEXT,
            caa_release_mbid TEXT,
            cover_url TEXT,
            cover_local_path TEXT,
            cover_fetched INTEGER DEFAULT 0,
            original_release_year INTEGER,
            year_fetched INTEGER DEFAULT 0,
            UNIQUE(artist_name, release_name)
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_albums_year ON albums(original_release_year)")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='listen_artist_credits'")
        if cursor.fetchone():
            cols = [c[1] for c in cursor.execute("PRAGMA table_info(listen_artist_credits)").fetchall()]
            if "listened_at" not in cols:
                cursor.execute("DROP TABLE listen_artist_credits")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS listen_artist_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listen_id INTEGER NOT NULL,
            artist_name TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            listened_at INTEGER,
            year INTEGER,
            month INTEGER
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_credits_artist ON listen_artist_credits(artist_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_credits_time ON listen_artist_credits(listened_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_credits_ym ON listen_artist_credits(year, month)")

        conn.commit()


def _build_time_filter(
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    prefix: str = "WHERE",
    table_alias: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    col_prefix = f"{table_alias}." if table_alias else ""

    if start_ts is not None and end_ts is not None:
        return f"{prefix} {col_prefix}listened_at BETWEEN ? AND ?", [int(start_ts), int(end_ts)]
    if start_ts is not None:
        return f"{prefix} {col_prefix}listened_at >= ?", [int(start_ts)]
    if end_ts is not None:
        return f"{prefix} {col_prefix}listened_at <= ?", [int(end_ts)]

    if not timeframe or timeframe == "all":
        return "", []

    if str(timeframe).startswith("ts:"):
        parts = str(timeframe).split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            return f"{prefix} {col_prefix}listened_at BETWEEN ? AND ?", [int(parts[1]), int(parts[2])]

    parts = str(timeframe).split("-")
    if len(parts) == 1 and parts[0].isdigit():
        return f"{prefix} {col_prefix}year = ?", [int(parts[0])]
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{prefix} {col_prefix}year = ? AND {col_prefix}month = ?", [int(parts[0]), int(parts[1])]
    return "", []


def _clean_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if path.startswith("/static/cache/"):
        return "/cache/" + path[len("/static/cache/"):]
    return path


def get_available_time_range(db_path: str = DB_PATH) -> Dict[str, Any]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        r = cursor.execute("SELECT MIN(listened_at), MAX(listened_at) FROM listens WHERE listened_at IS NOT NULL").fetchone()
        min_ts = r[0] or 0
        max_ts = r[1] or 0

        ym_rows = cursor.execute(
            "SELECT DISTINCT year, month FROM listens WHERE year IS NOT NULL ORDER BY year DESC, month DESC"
        ).fetchall()
        years = sorted({row[0] for row in ym_rows if row[0]}, reverse=True)
        months = [f"{row[0]:04d}-{row[1]:02d}" for row in ym_rows if row[0] and row[1]]

        return {
            "min_timestamp": min_ts,
            "max_timestamp": max_ts,
            "min_date": datetime.fromtimestamp(min_ts).strftime("%Y-%m-%d") if min_ts else "",
            "max_date": datetime.fromtimestamp(max_ts).strftime("%Y-%m-%d") if max_ts else "",
            "years": years,
            "months": months,
        }


def get_overall_stats(
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    where_clause, params = _build_time_filter(timeframe, start_ts, end_ts)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        stats_query = f"""
        SELECT
            COUNT(*) AS total_listens,
            COALESCE(SUM(duration_ms), 0) AS total_duration_ms,
            COUNT(DISTINCT artist_name) AS unique_artists,
            COUNT(DISTINCT CASE WHEN release_name IS NOT NULL AND release_name != '' THEN artist_name || ' - ' || release_name END) AS unique_albums,
            COUNT(DISTINCT artist_name || ' - ' || track_name) AS unique_tracks,
            MIN(listened_at) AS first_listen_ts,
            MAX(listened_at) AS last_listen_ts
        FROM listens
        {where_clause}
        """
        row = cursor.execute(stats_query, params).fetchone()

        total_ms = row["total_duration_ms"] or 0
        total_minutes = round(total_ms / 60000.0, 1)
        total_hours = round(total_ms / 3600000.0, 1)
        total_days = round(total_hours / 24.0, 2)

        first_listen = ""
        last_listen = ""
        days_span = 1
        if row["first_listen_ts"]:
            first_listen = datetime.fromtimestamp(row["first_listen_ts"]).strftime("%Y-%m-%d %H:%M")
        if row["last_listen_ts"]:
            last_listen = datetime.fromtimestamp(row["last_listen_ts"]).strftime("%Y-%m-%d %H:%M")

        if row["first_listen_ts"] and row["last_listen_ts"]:
            diff = (row["last_listen_ts"] - row["first_listen_ts"]) / 86400.0
            days_span = max(1, round(diff))

        avg_daily_minutes = round(total_minutes / days_span, 1) if days_span else total_minutes

        return {
            "total_listens": row["total_listens"],
            "total_ms": total_ms,
            "total_minutes": total_minutes,
            "total_hours": total_hours,
            "total_days": total_days,
            "unique_artists": row["unique_artists"],
            "unique_albums": row["unique_albums"],
            "unique_tracks": row["unique_tracks"],
            "first_listen": first_listen,
            "last_listen": last_listen,
            "days_span": days_span,
            "avg_daily_minutes": avg_daily_minutes,
        }


def get_top_artists(
    limit: int = 30,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    where_clause, params = _build_time_filter(timeframe, start_ts, end_ts, table_alias="c")
    order_by = "total_ms DESC, play_count DESC" if metric == "minutes" else "play_count DESC, total_ms DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        query = f"""
        SELECT
            c.artist_name,
            COUNT(*) AS play_count,
            SUM(c.duration_ms) AS total_ms,
            ROUND(SUM(c.duration_ms) / 60000.0, 1) AS minutes_listened,
            ROUND(SUM(c.duration_ms) / 3600000.0, 2) AS hours_listened,
            a.image_url,
            a.image_local_path,
            a.country_code,
            a.country_name
        FROM listen_artist_credits c
        LEFT JOIN artists a ON c.artist_name = a.artist_name
        {where_clause}
        GROUP BY c.artist_name
        ORDER BY {order_by}
        LIMIT ?
        """
        rows = cursor.execute(query, params + [limit]).fetchall()

        result = []
        for rank, r in enumerate(rows, 1):
            result.append({
                "rank": rank,
                "artist_name": r["artist_name"],
                "play_count": r["play_count"],
                "total_ms": r["total_ms"],
                "minutes_listened": r["minutes_listened"],
                "hours_listened": r["hours_listened"],
                "image_url": r["image_url"],
                "image_local_path": _clean_path(r["image_local_path"]),
                "country_code": r["country_code"],
                "country_name": r["country_name"],
            })
        return result


def get_top_albums(
    limit: int = 30,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    where_clause, params = _build_time_filter(timeframe, start_ts, end_ts, table_alias="l")
    order_by = "total_ms DESC, play_count DESC" if metric == "minutes" else "play_count DESC, total_ms DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        query = f"""
        SELECT
            l.artist_name,
            COALESCE(NULLIF(l.release_name, ''), 'Unknown Album') AS release_name,
            COUNT(*) AS play_count,
            SUM(l.duration_ms) AS total_ms,
            ROUND(SUM(l.duration_ms) / 60000.0, 1) AS minutes_listened,
            ROUND(SUM(l.duration_ms) / 3600000.0, 2) AS hours_listened,
            al.cover_url,
            al.cover_local_path,
            al.original_release_year,
            ar.image_url AS artist_image_url,
            ar.image_local_path AS artist_image_local_path,
            ar.country_code,
            ar.country_name
        FROM listens l
        LEFT JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
        LEFT JOIN artists ar ON l.artist_name = ar.artist_name
        {where_clause}
        GROUP BY l.artist_name, l.release_name
        HAVING l.release_name IS NOT NULL AND l.release_name != '' AND l.release_name != 'Unknown Album'
        ORDER BY {order_by}
        LIMIT ?
        """
        rows = cursor.execute(query, params + [limit]).fetchall()

        result = []
        for rank, r in enumerate(rows, 1):
            result.append({
                "rank": rank,
                "artist_name": r["artist_name"],
                "release_name": r["release_name"],
                "play_count": r["play_count"],
                "total_ms": r["total_ms"],
                "minutes_listened": r["minutes_listened"],
                "hours_listened": r["hours_listened"],
                "cover_url": r["cover_url"],
                "cover_local_path": _clean_path(r["cover_local_path"]),
                "original_release_year": r["original_release_year"],
                "artist_image_url": r["artist_image_url"],
                "artist_image_local_path": _clean_path(r["artist_image_local_path"]),
                "country_code": r["country_code"],
                "country_name": r["country_name"],
            })
        return result


def get_top_tracks(
    limit: int = 30,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    where_clause, params = _build_time_filter(timeframe, start_ts, end_ts, table_alias="l")
    manual_filter = "(l.submission_client IS NULL OR l.submission_client != 'manual_session')"
    if where_clause:
        where_clause += f" AND {manual_filter}"
    else:
        where_clause = f"WHERE {manual_filter}"

    order_by = "total_ms DESC, play_count DESC" if metric == "minutes" else "play_count DESC, total_ms DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        query = f"""
        SELECT
            l.artist_name,
            l.track_name,
            COALESCE(NULLIF(l.release_name, ''), 'Single / Unknown') AS release_name,
            COUNT(*) AS play_count,
            SUM(l.duration_ms) AS total_ms,
            ROUND(SUM(l.duration_ms) / 60000.0, 1) AS minutes_listened,
            ROUND(AVG(l.duration_ms) / 1000.0, 0) AS avg_track_duration_sec,
            ar.image_url AS artist_image_url,
            ar.image_local_path AS artist_image_local_path,
            ar.country_code,
            ar.country_name,
            al.cover_url AS album_cover_url,
            al.cover_local_path AS album_cover_local_path,
            al.original_release_year
        FROM listens l
        LEFT JOIN artists ar ON l.artist_name = ar.artist_name
        LEFT JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
        {where_clause}
        GROUP BY l.artist_name, l.track_name
        ORDER BY {order_by}
        LIMIT ?
        """
        rows = cursor.execute(query, params + [limit]).fetchall()

        result = []
        for rank, r in enumerate(rows, 1):
            dur_sec = int(r["avg_track_duration_sec"] or 0)
            mins = dur_sec // 60
            secs = dur_sec % 60
            result.append({
                "rank": rank,
                "artist_name": r["artist_name"],
                "track_name": r["track_name"],
                "release_name": r["release_name"],
                "play_count": r["play_count"],
                "total_ms": r["total_ms"],
                "minutes_listened": r["minutes_listened"],
                "duration_seconds": dur_sec,
                "duration_formatted": f"{mins}:{secs:02d}",
                "original_release_year": r["original_release_year"],
                "artist_image_url": r["artist_image_url"],
                "artist_image_local_path": _clean_path(r["artist_image_local_path"]),
                "country_code": r["country_code"],
                "country_name": r["country_name"],
                "album_cover_url": r["album_cover_url"],
                "album_cover_local_path": _clean_path(r["album_cover_local_path"]),
            })
        return result


def get_artist_drilldown(
    artist_name: str,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    where_l, params_l = _build_time_filter(timeframe, start_ts, end_ts, prefix="AND", table_alias="l")
    order_col = "total_ms DESC, play_count DESC" if metric == "minutes" else "play_count DESC, total_ms DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        art_row = cursor.execute(
            """
            SELECT artist_name, image_url, image_local_path, country_code, country_name
            FROM artists
            WHERE artist_name = ?
            """,
            [artist_name],
        ).fetchone()

        albums_q = f"""
        SELECT
            COALESCE(NULLIF(l.release_name, ''), 'Singles / Unknown') AS release_name,
            al.cover_local_path,
            al.original_release_year,
            COUNT(*) AS play_count,
            SUM(l.duration_ms) AS total_ms,
            ROUND(SUM(l.duration_ms) / 60000.0, 1) AS minutes_listened,
            COUNT(DISTINCT l.track_name) AS track_count
        FROM listens l
        LEFT JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
        WHERE (l.artist_name = ? OR l.id IN (SELECT listen_id FROM listen_artist_credits WHERE artist_name = ?))
        {where_l}
        GROUP BY l.release_name
        ORDER BY {order_col}
        """
        alb_rows = cursor.execute(albums_q, [artist_name, artist_name] + params_l).fetchall()

        songs_q = f"""
        SELECT
            l.track_name,
            COALESCE(NULLIF(l.release_name, ''), 'Single') AS release_name,
            COUNT(*) AS play_count,
            SUM(l.duration_ms) AS total_ms,
            ROUND(SUM(l.duration_ms) / 60000.0, 1) AS minutes_listened,
            ROUND(AVG(l.duration_ms) / 1000.0, 0) AS avg_duration_sec
        FROM listens l
        WHERE (l.artist_name = ? OR l.id IN (SELECT listen_id FROM listen_artist_credits WHERE artist_name = ?))
          AND (l.submission_client IS NULL OR l.submission_client != 'manual_session')
        {where_l}
        GROUP BY l.track_name
        ORDER BY {order_col}
        """
        song_rows = cursor.execute(songs_q, [artist_name, artist_name] + params_l).fetchall()

        total_ms = sum(r["total_ms"] for r in alb_rows)
        total_plays = sum(r["play_count"] for r in alb_rows)
        total_minutes = round(total_ms / 60000.0, 1)
        total_hours = round(total_ms / 3600000.0, 2)

        denom = total_ms if metric == "minutes" else total_plays
        albums = []
        for r in alb_rows:
            val = r["total_ms"] if metric == "minutes" else r["play_count"]
            albums.append({
                "release_name": r["release_name"],
                "cover_local_path": _clean_path(r["cover_local_path"]),
                "original_release_year": r["original_release_year"],
                "play_count": r["play_count"],
                "minutes_listened": r["minutes_listened"],
                "track_count": r["track_count"],
                "percentage": round((val / denom * 100.0), 1) if denom > 0 else 0,
            })

        songs = []
        for rank, r in enumerate(song_rows, 1):
            dur_sec = int(r["avg_duration_sec"] or 0)
            mins = dur_sec // 60
            secs = dur_sec % 60
            val = r["total_ms"] if metric == "minutes" else r["play_count"]
            songs.append({
                "rank": rank,
                "track_name": r["track_name"],
                "release_name": r["release_name"],
                "play_count": r["play_count"],
                "minutes_listened": r["minutes_listened"],
                "duration_formatted": f"{mins}:{secs:02d}",
                "percentage": round((val / denom * 100.0), 1) if denom > 0 else 0,
            })

        return {
            "artist_name": artist_name,
            "image_local_path": _clean_path(art_row["image_local_path"]) if art_row else None,
            "country_code": art_row["country_code"] if art_row else None,
            "country_name": art_row["country_name"] if art_row else None,
            "total_minutes": total_minutes,
            "total_hours": total_hours,
            "play_count": total_plays,
            "album_count": len(albums),
            "song_count": len(songs),
            "albums": albums,
            "songs": songs,
        }


def get_album_drilldown(
    artist_name: str,
    release_name: str,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    where_l, params_l = _build_time_filter(timeframe, start_ts, end_ts, prefix="AND", table_alias="l")
    order_col = "total_ms DESC, play_count DESC" if metric == "minutes" else "play_count DESC, total_ms DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        alb_meta = cursor.execute(
            """
            SELECT cover_url, cover_local_path, original_release_year
            FROM albums
            WHERE artist_name = ? AND release_name = ?
            """,
            [artist_name, release_name],
        ).fetchone()

        art_meta = cursor.execute(
            "SELECT country_code, country_name FROM artists WHERE artist_name = ?",
            [artist_name],
        ).fetchone()

        songs_q = f"""
        SELECT
            l.track_name,
            COUNT(*) AS play_count,
            SUM(l.duration_ms) AS total_ms,
            ROUND(SUM(l.duration_ms) / 60000.0, 1) AS minutes_listened,
            ROUND(AVG(l.duration_ms) / 1000.0, 0) AS avg_duration_sec
        FROM listens l
        WHERE l.artist_name = ? AND l.release_name = ?
        {where_l}
        GROUP BY l.track_name
        ORDER BY {order_col}
        """
        rows = cursor.execute(songs_q, [artist_name, release_name] + params_l).fetchall()

        total_ms = sum(r["total_ms"] for r in rows)
        total_plays = sum(r["play_count"] for r in rows)
        total_minutes = round(total_ms / 60000.0, 1)
        total_hours = round(total_ms / 3600000.0, 2)
        denom = total_ms if metric == "minutes" else total_plays

        songs = []
        for rank, r in enumerate(rows, 1):
            dur_sec = int(r["avg_duration_sec"] or 0)
            mins = dur_sec // 60
            secs = dur_sec % 60
            val = r["total_ms"] if metric == "minutes" else r["play_count"]
            songs.append({
                "rank": rank,
                "track_name": r["track_name"],
                "play_count": r["play_count"],
                "minutes_listened": r["minutes_listened"],
                "duration_formatted": f"{mins}:{secs:02d}",
                "percentage": round((val / denom * 100.0), 1) if denom > 0 else 0,
            })

        return {
            "artist_name": artist_name,
            "country_code": art_meta["country_code"] if art_meta else None,
            "country_name": art_meta["country_name"] if art_meta else None,
            "release_name": release_name,
            "cover_local_path": _clean_path(alb_meta["cover_local_path"]) if alb_meta else None,
            "original_release_year": alb_meta["original_release_year"] if alb_meta else None,
            "total_minutes": total_minutes,
            "total_hours": total_hours,
            "play_count": total_plays,
            "song_count": len(songs),
            "songs": songs,
        }


def get_release_years_stats(
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    """Return unbinned individual release year statistics and summary metrics."""
    where_clause, params = _build_time_filter(timeframe, start_ts, end_ts, table_alias="l")
    join_where = "WHERE al.original_release_year IS NOT NULL AND al.original_release_year > 1900"
    if where_clause:
        join_where += f" AND {where_clause[6:]}"

    order_col = "total_ms DESC, plays DESC" if metric == "minutes" else "plays DESC, total_ms DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # 1. Aggregated stats per individual year
        query = f"""
        SELECT
            al.original_release_year AS release_year,
            COUNT(*) AS play_count,
            SUM(l.duration_ms) AS total_ms,
            ROUND(SUM(l.duration_ms) / 60000.0, 1) AS minutes_listened,
            ROUND(SUM(l.duration_ms) / 3600000.0, 2) AS hours_listened,
            COUNT(DISTINCT l.artist_name || ' - ' || l.release_name) AS album_count,
            COUNT(DISTINCT l.artist_name) AS artist_count
        FROM listens l
        JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
        {join_where}
        GROUP BY al.original_release_year
        ORDER BY al.original_release_year ASC
        """
        rows = cursor.execute(query, params).fetchall()

        # 2. Top albums per year in ONE single query (eliminates N+1 loop & respects timeframe)
        alb_query = f"""
        SELECT
            al.original_release_year AS release_year,
            l.artist_name,
            l.release_name,
            SUM(l.duration_ms) AS total_ms,
            ROUND(SUM(l.duration_ms) / 60000.0, 1) AS minutes,
            COUNT(*) AS plays,
            al.cover_local_path
        FROM listens l
        JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
        {join_where}
        GROUP BY al.original_release_year, l.artist_name, l.release_name
        ORDER BY al.original_release_year ASC, {order_col}
        """
        top_albs_by_year: Dict[int, List[Dict[str, Any]]] = {}
        for ar in cursor.execute(alb_query, params).fetchall():
            yr = int(ar["release_year"])
            bucket = top_albs_by_year.setdefault(yr, [])
            if len(bucket) < 5:
                bucket.append({
                    "artist_name": ar["artist_name"],
                    "release_name": ar["release_name"],
                    "minutes": ar["minutes"],
                    "plays": ar["plays"],
                    "cover_local_path": _clean_path(ar["cover_local_path"]),
                })

        # 3. Overall year coverage for selected timeframe
        cov_query = f"""
        SELECT
            COUNT(*) AS total_listens,
            COALESCE(SUM(l.duration_ms), 0) AS total_ms,
            SUM(CASE WHEN al.original_release_year IS NOT NULL AND al.original_release_year > 1900 THEN 1 ELSE 0 END) AS with_year_plays,
            COALESCE(SUM(CASE WHEN al.original_release_year IS NOT NULL AND al.original_release_year > 1900 THEN l.duration_ms ELSE 0 END), 0) AS with_year_ms
        FROM listens l
        LEFT JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
        {where_clause}
        """
        cov = cursor.execute(cov_query, params).fetchone()

        total_metric_sum = sum(
            (r["total_ms"] if metric == "minutes" else r["play_count"]) for r in rows
        )

        year_data_map: Dict[int, Dict[str, Any]] = {}
        weighted_sum = 0.0
        weighted_denom = 0.0
        peak_row = None
        peak_val = -1

        for r in rows:
            yr = int(r["release_year"])
            val = r["total_ms"] if metric == "minutes" else r["play_count"]
            weighted_sum += yr * val
            weighted_denom += val
            share_pct = round((val / total_metric_sum) * 100.0, 1) if total_metric_sum > 0 else 0.0

            entry = {
                "year": yr,
                "play_count": r["play_count"],
                "total_ms": r["total_ms"],
                "minutes_listened": r["minutes_listened"],
                "hours_listened": r["hours_listened"],
                "album_count": r["album_count"],
                "artist_count": r["artist_count"],
                "share_pct": share_pct,
                "top_albums": top_albs_by_year.get(yr, []),
            }
            year_data_map[yr] = entry
            if val > peak_val:
                peak_val = val
                peak_row = entry

        if year_data_map:
            start_year = min(year_data_map.keys())
            end_year = max(datetime.now().year, max(year_data_map.keys()))
        else:
            start_year = 1960
            end_year = datetime.now().year

        timeline: List[Dict[str, Any]] = []
        for y in range(start_year, end_year + 1):
            if y in year_data_map:
                timeline.append(year_data_map[y])
            else:
                timeline.append({
                    "year": y,
                    "play_count": 0,
                    "total_ms": 0,
                    "minutes_listened": 0.0,
                    "hours_listened": 0.0,
                    "album_count": 0,
                    "artist_count": 0,
                    "share_pct": 0.0,
                    "top_albums": [],
                })

        total_all_ms = cov["total_ms"] or 0
        with_year_ms = cov["with_year_ms"] or 0
        total_all_plays = cov["total_listens"] or 0
        with_year_plays = cov["with_year_plays"] or 0

        cov_pct = (
            round((with_year_ms / total_all_ms) * 100.0, 1)
            if (metric == "minutes" and total_all_ms > 0)
            else (round((with_year_plays / total_all_plays) * 100.0, 1) if total_all_plays > 0 else 0.0)
        )

        weighted_avg_year = round(weighted_sum / weighted_denom, 1) if weighted_denom > 0 else None
        listening_age = (
            max(13, int(round(datetime.now().year - weighted_avg_year + REMINISCENCE_BUMP_AGE)))
            if weighted_avg_year is not None
            else None
        )

        summary = {
            "earliest_year": min(year_data_map.keys()) if year_data_map else None,
            "latest_year": max(year_data_map.keys()) if year_data_map else None,
            "active_years_count": len(year_data_map),
            "peak_year": peak_row["year"] if peak_row else None,
            "peak_minutes": peak_row["minutes_listened"] if peak_row else 0,
            "peak_plays": peak_row["play_count"] if peak_row else 0,
            "weighted_avg_year": weighted_avg_year,
            "listening_age": listening_age,
            "listening_age_anchor": REMINISCENCE_BUMP_AGE,
            "coverage_pct": cov_pct,
            "with_year_hours": round(with_year_ms / 3600000.0, 1),
            "without_year_hours": round(max(0, total_all_ms - with_year_ms) / 3600000.0, 1),
            "with_year_plays": with_year_plays,
            "total_plays": total_all_plays,
        }

        return {"years": timeline, "summary": summary}


def get_country_stats(
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """Return country listening breakdown in a single non-N+1 query pass."""
    where_clause, params = _build_time_filter(timeframe, start_ts, end_ts, prefix="AND", table_alias="c")
    order_by = "total_ms DESC, play_count DESC" if metric == "minutes" else "play_count DESC, total_ms DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        query = f"""
        SELECT
            a.country_code,
            a.country_name,
            COUNT(*) AS play_count,
            SUM(c.duration_ms) AS total_ms,
            ROUND(SUM(c.duration_ms) / 60000.0, 1) AS minutes_listened,
            ROUND(SUM(c.duration_ms) / 3600000.0, 2) AS hours_listened,
            COUNT(DISTINCT c.artist_name) AS artist_count
        FROM listen_artist_credits c
        JOIN artists a ON c.artist_name = a.artist_name
        WHERE a.country_code IS NOT NULL AND a.country_code != '' AND a.country_code != 'XX'
        {where_clause}
        GROUP BY a.country_code
        ORDER BY {order_by}
        """
        rows = cursor.execute(query, params).fetchall()

        # Fetch top artists per country in ONE query (respects active timeframe & metric)
        art_order_by = "total_ms DESC, plays DESC" if metric == "minutes" else "plays DESC, total_ms DESC"
        art_query = f"""
        SELECT
            a.country_code,
            c.artist_name,
            SUM(c.duration_ms) AS total_ms,
            ROUND(SUM(c.duration_ms) / 60000.0, 1) AS minutes,
            COUNT(*) AS plays,
            a.image_local_path
        FROM listen_artist_credits c
        JOIN artists a ON c.artist_name = a.artist_name
        WHERE a.country_code IS NOT NULL AND a.country_code != '' AND a.country_code != 'XX'
        {where_clause}
        GROUP BY a.country_code, c.artist_name
        ORDER BY a.country_code ASC, {art_order_by}
        """
        top_artists_by_country: Dict[str, List[Dict[str, Any]]] = {}
        for ar in cursor.execute(art_query, params).fetchall():
            cc = ar["country_code"]
            bucket = top_artists_by_country.setdefault(cc, [])
            if len(bucket) < 5:
                bucket.append({
                    "artist_name": ar["artist_name"],
                    "minutes": ar["minutes"],
                    "plays": ar["plays"],
                    "image_local_path": _clean_path(ar["image_local_path"]),
                })

        total_metric_sum = sum(
            (r["total_ms"] if metric == "minutes" else r["play_count"]) for r in rows
        )

        result = []
        for rank, r in enumerate(rows, 1):
            code = r["country_code"]
            val = r["total_ms"] if metric == "minutes" else r["play_count"]
            share_pct = round((val / total_metric_sum) * 100.0, 1) if total_metric_sum > 0 else 0.0
            result.append({
                "rank": rank,
                "country_code": code,
                "country_name": r["country_name"],
                "play_count": r["play_count"],
                "total_ms": r["total_ms"],
                "minutes_listened": r["minutes_listened"],
                "hours_listened": r["hours_listened"],
                "artist_count": r["artist_count"],
                "share_pct": share_pct,
                "top_artists": top_artists_by_country.get(code, []),
            })
        return result


def get_listening_habits(
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    where_clause, params = _build_time_filter(timeframe, start_ts, end_ts)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        hourly_query = f"""
        SELECT
            hour,
            COUNT(*) AS play_count,
            ROUND(SUM(duration_ms) / 60000.0, 1) AS minutes_listened
        FROM listens
        {where_clause}
        GROUP BY hour
        ORDER BY hour
        """
        hourly_rows = cursor.execute(hourly_query, params).fetchall()
        hourly = {h: {"play_count": 0, "minutes_listened": 0.0} for h in range(24)}
        for r in hourly_rows:
            if r["hour"] is not None:
                hourly[r["hour"]] = {
                    "play_count": r["play_count"],
                    "minutes_listened": r["minutes_listened"],
                }

        dow_query = f"""
        SELECT
            day_of_week,
            COUNT(*) AS play_count,
            ROUND(SUM(duration_ms) / 60000.0, 1) AS minutes_listened
        FROM listens
        {where_clause}
        GROUP BY day_of_week
        ORDER BY day_of_week
        """
        dow_rows = cursor.execute(dow_query, params).fetchall()
        days_map = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        dow = {i: {"day_name": days_map[i], "play_count": 0, "minutes_listened": 0.0} for i in range(7)}
        for r in dow_rows:
            if r["day_of_week"] is not None and 0 <= r["day_of_week"] < 7:
                dow[r["day_of_week"]]["play_count"] = r["play_count"]
                dow[r["day_of_week"]]["minutes_listened"] = r["minutes_listened"]

        monthly_query = f"""
        SELECT
            printf('%04d-%02d', year, month) AS month_label,
            COUNT(*) AS play_count,
            ROUND(SUM(duration_ms) / 60000.0, 1) AS minutes_listened,
            COUNT(DISTINCT artist_name) AS unique_artists
        FROM listens
        {where_clause}
        GROUP BY year, month
        ORDER BY year, month
        """
        monthly_rows = cursor.execute(monthly_query, params).fetchall()
        monthly = [
            {
                "month": r["month_label"],
                "play_count": r["play_count"],
                "minutes_listened": r["minutes_listened"],
                "unique_artists": r["unique_artists"],
            }
            for r in monthly_rows
            if r["month_label"]
        ]

        return {
            "hourly": hourly,
            "day_of_week": dow,
            "monthly": monthly,
        }
