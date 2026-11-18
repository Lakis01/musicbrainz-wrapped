#!/usr/bin/env python3
"""CLI entry point for ListenBrainz Visualizer (unofficial community tool)."""

from __future__ import annotations

import argparse
import json
import os
import sys

from collage_generator import (
    export_all_visuals,
    generate_artists_table_image,
    generate_release_years_image,
    generate_songs_table_image,
    generate_tiered_collage,
    generate_uniform_collage,
    generate_world_map_image,
    get_uniform_grid_dims,
    normalize_formats,
)
from db import get_overall_stats, get_top_albums, get_top_artists, get_top_tracks
from flags import ensure_flag_assets
from importer import (
    get_active_data_dir,
    load_manual_entries,
    set_active_data_dir,
    sync_data,
)


def update_manual_estimate(acid_arab_mins=None):
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "manual_entries.json")
    entries = load_manual_entries(cfg_path)
    if not entries:
        return

    acid_entry = next((e for e in entries if e.get("id") == "acid_arab_cercle_paris"), None)
    if not acid_entry:
        return

    cur_mins = acid_entry.get("duration_minutes", 120)
    if acid_arab_mins is not None:
        acid_entry["duration_minutes"] = acid_arab_mins
        print(f"Updated manual estimate for Acid Arab - Cercle live set: {acid_arab_mins} mins.")
    elif sys.stdin.isatty():
        try:
            val = input(
                f"\n[Manual Session Tracking]\nCurrent estimate for Acid Arab - Cercle live set: {cur_mins} mins.\n"
                f"Enter new estimate in minutes (or press Enter to keep {cur_mins}m): "
            ).strip()
            if val and val.isdigit():
                acid_entry["duration_minutes"] = int(val)
                print(f"Updated manual estimate to {val} mins.")
        except Exception:
            pass

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="MusicBrainz Wrapped — Unofficial Local Listening History Visualizer (not endorsed by MusicBrainz/ListenBrainz)"
    )
    parser.add_argument("--data-dir", type=str, default=None, help="Path to ListenBrainz export folder or .zip/.tar.gz archive")
    parser.add_argument("--sync", action="store_true", help="Sync latest ListenBrainz export and apply canonicalization")
    parser.add_argument("--manual-acid-arab", type=int, default=None, help="Update manual listening estimate (minutes)")
    parser.add_argument("--metric", choices=["minutes", "plays"], default="minutes", help="Count by listen time (minutes) or play count (plays)")
    parser.add_argument("--limit", type=int, default=30, help="Top N count (default: 30)")
    parser.add_argument("--timeframe", default="all", help="Timeframe (e.g. all, 2026, 2025, 2026-8)")
    parser.add_argument("--formats", default="webp", help="Comma-separated output formats: webp,avif,jpg,jxl (default: webp)")
    parser.add_argument("--flags", dest="show_flags", action="store_true", default=True, help="Include country flags next to artist names (default)")
    parser.add_argument("--no-flags", dest="show_flags", action="store_false", help="Omit country flags from rendered outputs")
    parser.add_argument("--collage", action="store_true", help="Generate album collage image")
    parser.add_argument("--layout", choices=["tiered", "uniform"], default="tiered", help="Collage layout")
    parser.add_argument("--export-all", action="store_true", help="Export Top 101 Collage, Top 50 Artists, and Top 50 Songs")
    parser.add_argument("--webp", action="store_true", help="Alias for --export-all with webp")
    parser.add_argument("--avif", action="store_true", help="Include AVIF when exporting all visuals")
    parser.add_argument("--artists-table", action="store_true", help="Export Top 50 Artists table graphic")
    parser.add_argument("--songs-table", action="store_true", help="Export Top 50 Songs table graphic")
    parser.add_argument("--map-graphic", action="store_true", help="Export World Map graphic")
    parser.add_argument("--years-graphic", action="store_true", help="Export Release Years graphic")
    args = parser.parse_args()

    ensure_flag_assets()

    if args.data_dir:
        active_dir = set_active_data_dir(args.data_dir)
        print(f"Selected data source: {active_dir}")
    else:
        active_dir = get_active_data_dir()

    fmt_list = normalize_formats(args.formats.split(","))
    if args.avif and "avif" not in fmt_list:
        fmt_list.append("avif")

    if args.sync or args.manual_acid_arab is not None:
        update_manual_estimate(args.manual_acid_arab)
        print(f"\nImporting latest listens from {active_dir or '(none found — place export in ./imports/)'}...")
        sync_res = sync_data(data_dir=active_dir)
        print(f"Sync complete in {sync_res['elapsed_ms']} ms ({sync_res['new_scrobbles']} new listens, {sync_res['total_listens']} total).")

    stats = get_overall_stats(timeframe=args.timeframe)
    print("=" * 64)
    print("        MUSICBRAINZ WRAPPED — LISTENING SUMMARY (UNOFFICIAL)")
    print("=" * 64)
    print(f"Total Listening Time:  {stats['total_minutes']:,} minutes ({stats['total_hours']} hours / {stats['total_days']} days)")
    print(f"Total Scrobbles:       {stats['total_listens']:,} plays")
    print(f"Daily Average:         {stats['avg_daily_minutes']} mins/day")
    print(f"Unique Artists:        {stats['unique_artists']:,}")
    print(f"Unique Albums:         {stats['unique_albums']:,}")
    print(f"Unique Tracks:         {stats['unique_tracks']:,}")
    print(f"Date Range:            {stats['first_listen']} -> {stats['last_listen']}")
    print("=" * 64)

    print(f"\n TOP {args.limit} ARTISTS (Ranked by {args.metric.title()})")
    print("-" * 64)
    for a in get_top_artists(limit=args.limit, metric=args.metric, timeframe=args.timeframe):
        c_str = f"[{a['country_code']}]" if a.get("country_code") else ""
        print(f" {a['rank']:2d}. {a['artist_name']:<30} {c_str:<5} | {a['hours_listened']:5.1f}h ({a['minutes_listened']:6.1f}m) | {a['play_count']:3d} plays")

    print(f"\n TOP {args.limit} ALBUMS (Ranked by {args.metric.title()})")
    print("-" * 64)
    for al in get_top_albums(limit=args.limit, metric=args.metric, timeframe=args.timeframe):
        title = f"{al['artist_name']} - {al['release_name']}"
        print(f" {al['rank']:2d}. {title[:35]:<35} | {al['hours_listened']:5.1f}h ({al['minutes_listened']:6.1f}m) | {al['play_count']:3d} plays")

    print(f"\n TOP {args.limit} SONGS (Ranked by {args.metric.title()})")
    print("-" * 64)
    for t in get_top_tracks(limit=args.limit, metric=args.metric, timeframe=args.timeframe):
        song_str = f"{t['artist_name']} - {t['track_name']}"
        print(f" {t['rank']:2d}. {song_str[:35]:<35} | [{t['duration_formatted']}] | {t['minutes_listened']:5.1f}m | {t['play_count']:3d} plays")

    export_all = args.export_all or args.webp or args.avif
    if export_all and not args.sync:
        print(f"\nExporting all graphics ({', '.join(fmt_list)})...")
        out = export_all_visuals(timeframe=args.timeframe, metric=args.metric, formats=fmt_list, show_flags=args.show_flags)
        print("Exported:", out)

    if args.artists_table and not export_all and not args.sync:
        out = generate_artists_table_image(
            limit=50,
            metric=args.metric,
            timeframe=args.timeframe,
            output_path=os.path.join("static", "top_50_artists"),
            show_flags=args.show_flags,
            formats=fmt_list,
        )
        print(f"Artists table graphic saved: {out}")

    if args.songs_table and not export_all and not args.sync:
        out = generate_songs_table_image(
            limit=50,
            metric=args.metric,
            timeframe=args.timeframe,
            output_path=os.path.join("static", "top_50_songs"),
            show_flags=args.show_flags,
            formats=fmt_list,
        )
        print(f"Songs table graphic saved: {out}")

    if args.map_graphic and not export_all and not args.sync:
        out = generate_world_map_image(
            metric=args.metric,
            timeframe=args.timeframe,
            output_path=os.path.join("static", "world_map"),
            show_flags=args.show_flags,
            formats=fmt_list,
        )
        print(f"World map graphic saved: {out}")

    if args.years_graphic and not export_all and not args.sync:
        out = generate_release_years_image(
            metric=args.metric,
            timeframe=args.timeframe,
            output_path=os.path.join("static", "release_years"),
            formats=fmt_list,
        )
        print(f"Release years graphic saved: {out}")

    if args.collage and not export_all and not args.sync:
        print("\nGenerating album compilation collage...")
        stem = os.path.join("static", f"collage_{args.layout}_{args.metric}_{args.timeframe}_{args.limit}")
        if args.layout == "tiered":
            out = generate_tiered_collage(
                limit=args.limit, metric=args.metric, timeframe=args.timeframe, output_path=stem, show_flags=args.show_flags, formats=fmt_list
            )
        else:
            cols, rows = get_uniform_grid_dims(args.limit)
            out = generate_uniform_collage(
                grid_size=(cols, rows),
                metric=args.metric,
                timeframe=args.timeframe,
                output_path=stem,
                show_flags=args.show_flags,
                formats=fmt_list,
            )
        print(f"Collage saved: {out}")


if __name__ == "__main__":
    main()
