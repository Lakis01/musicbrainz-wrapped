"""HTTP server and JSON API for the unofficial ListenBrainz Visualizer."""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
import urllib.parse
from typing import Any, Dict, List

from collage_generator import (
    calculate_tiered_limit,
    generate_artists_table_image,
    generate_release_years_image,
    generate_songs_table_image,
    generate_tiered_collage,
    generate_uniform_collage,
    generate_world_map_image,
    get_uniform_grid_dims,
    normalize_formats,
)
from db import (
    DB_PATH,
    get_album_drilldown,
    get_artist_drilldown,
    get_available_time_range,
    get_country_stats,
    get_listening_habits,
    get_overall_stats,
    get_release_years_stats,
    get_top_albums,
    get_top_artists,
    get_top_tracks,
    init_db,
)
from flags import ensure_flag_assets
from importer import (
    IMPORTS_DIR,
    discover_data_dirs,
    get_active_data_dir,
    load_manual_entries,
    read_export_username,
    set_active_data_dir,
    sync_data,
)
from listenbrainz_export import (
    clear_token,
    get_export_job_status,
    get_token_status,
    set_token,
    start_background_export,
)

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMP_EXPORT_DIR = os.path.join(tempfile.gettempdir(), "musicbrainz_wrapped_exports")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


def _prune_transient_exports(max_jobs: int = 12) -> None:
    if not os.path.isdir(TEMP_EXPORT_DIR):
        return
    try:
        entries = [
            os.path.join(TEMP_EXPORT_DIR, name)
            for name in os.listdir(TEMP_EXPORT_DIR)
        ]
        dirs = [p for p in entries if os.path.isdir(p)]
        if len(dirs) <= max_jobs:
            return
        dirs.sort(key=os.path.getmtime)
        for old_dir in dirs[: len(dirs) - max_jobs]:
            shutil.rmtree(old_dir, ignore_errors=True)
    except OSError:
        pass


def _allocate_transient_stem(stem_name: str) -> tuple[str, str]:
    os.makedirs(TEMP_EXPORT_DIR, exist_ok=True)
    _prune_transient_exports()
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(TEMP_EXPORT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return job_id, os.path.join(job_dir, stem_name)


def _format_transient_files(job_id: str, saved_paths: List[str] | None) -> List[Dict[str, str]]:
    files = []
    for p in saved_paths or []:
        fname = os.path.basename(p)
        ext = os.path.splitext(fname)[1].lstrip(".").lower()
        files.append({
            "format": ext,
            "url": f"/api/download-export/{job_id}/{urllib.parse.quote(fname)}",
            "filename": fname,
        })
    return files


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = http.server.SimpleHTTPRequestHandler.extensions_map.copy()
    extensions_map.update({
        ".avif": "image/avif",
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".jxl": "image/jxl",
        ".svg": "image/svg+xml",
        ".json": "application/json",
    })

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        parsed = urllib.parse.urlparse(path).path
        if parsed.startswith("/static/"):
            parsed = parsed[len("/static"):]
        if parsed == "" or parsed == "/":
            parsed = "/index.html"
        rel = parsed.lstrip("/")
        return os.path.join(STATIC_DIR, rel)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_download_export(self, path: str) -> None:
        parts = path[len("/api/download-export/"):].split("/")
        if len(parts) != 2:
            self._send_json({"error": "Invalid export path"}, status=400)
            return
        job_id = urllib.parse.unquote(parts[0])
        filename = urllib.parse.unquote(parts[1])
        if not _SAFE_TOKEN_RE.match(job_id) or not _SAFE_FILENAME_RE.match(filename) or ".." in filename:
            self._send_json({"error": "Invalid export identifier"}, status=400)
            return
        base_real = os.path.realpath(TEMP_EXPORT_DIR)
        file_path = os.path.realpath(os.path.join(TEMP_EXPORT_DIR, job_id, filename))
        if not file_path.startswith(base_real + os.sep) or not os.path.isfile(file_path):
            self._send_json({"error": "Export file not found"}, status=404)
            return
        ext = os.path.splitext(filename)[1].lower()
        ctype = self.extensions_map.get(ext, "application/octet-stream")
        with open(file_path, "rb") as fp:
            data = fp.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        if path.startswith("/api/"):
            self.handle_api_get(path, params)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        if path.startswith("/api/"):
            self.handle_api_post(path, params)
        else:
            self._send_json({"error": "Endpoint not found"}, status=404)

    def _build_config_payload(self) -> Dict[str, Any]:
        active_dir = get_active_data_dir()
        stats = get_overall_stats()
        return {
            "data_dir": active_dir,
            "username": read_export_username(active_dir),
            "imports_dir": IMPORTS_DIR,
            "total_listens": stats.get("total_listens", 0),
            "discovered": discover_data_dirs(),
            "cjxl_available": shutil.which("cjxl") is not None,
            "listenbrainz_token": get_token_status(),
        }

    def handle_api_post(self, path: str, params: Dict[str, List[str]]) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if path == "/api/config":
            try:
                raw = self.rfile.read(length) if length > 0 else b"{}"
                body = json.loads(raw.decode("utf-8"))
                new_path = body.get("data_dir", "").strip()
                if not new_path:
                    self._send_json({"error": "Missing data_dir"}, status=400)
                    return
                resolved = set_active_data_dir(new_path)
                sync_res = sync_data(data_dir=resolved)
                self._send_json({
                    "success": True,
                    "config": self._build_config_payload(),
                    "sync": sync_res,
                })
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=400)
            return

        if path == "/api/upload-export":
            try:
                raw_name = params.get("filename", ["listenbrainz_export.zip"])[0]
                safe_name = os.path.basename(raw_name) or "listenbrainz_export.zip"
                if not safe_name.lower().endswith((".zip", ".tar.gz", ".tgz")):
                    self._send_json({"success": False, "error": "Please upload a .zip or .tar.gz ListenBrainz export archive."}, status=400)
                    return
                if length <= 0 or length > 512 * 1024 * 1024:
                    self._send_json({"success": False, "error": "Invalid archive size."}, status=400)
                    return
                os.makedirs(IMPORTS_DIR, exist_ok=True)
                dest_archive = os.path.join(IMPORTS_DIR, safe_name)
                data = self.rfile.read(length)
                with open(dest_archive, "wb") as fp:
                    fp.write(data)
                resolved = set_active_data_dir(dest_archive)
                sync_res = sync_data(data_dir=resolved)
                self._send_json({
                    "success": True,
                    "config": self._build_config_payload(),
                    "sync": sync_res,
                })
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=400)
            return

        if path == "/api/listenbrainz-token":
            try:
                raw = self.rfile.read(length) if length > 0 else b"{}"
                body = json.loads(raw.decode("utf-8"))
                if body.get("clear"):
                    tok_status = clear_token()
                else:
                    tok = str(body.get("token") or "")
                    remember = bool(body.get("remember", False))
                    tok_status = set_token(tok, remember=remember)
                self._send_json({"success": True, "listenbrainz_token": tok_status})
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=400)
            return

        if path == "/api/listenbrainz-export/start":
            try:
                raw = self.rfile.read(length) if length > 0 else b"{}"
                body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
                tok = body.get("token")
                remember = bool(body.get("remember", False))
                job = start_background_export(token=tok, remember=remember)
                self._send_json({"success": True, "job": job, "listenbrainz_token": get_token_status()})
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=400)
            return

        self._send_json({"error": "Endpoint not found"}, status=404)

    def handle_api_get(self, path: str, params: Dict[str, List[str]]) -> None:
        metric = params.get("metric", ["minutes"])[0]
        if metric not in ("minutes", "plays"):
            metric = "minutes"
        timeframe = params.get("timeframe", ["all"])[0]
        try:
            limit = max(1, min(500, int(params.get("limit", [30])[0])))
        except ValueError:
            limit = 30
        start_ts = int(params.get("start_ts", [0])[0]) if "start_ts" in params and params.get("start_ts", [""])[0].isdigit() else None
        end_ts = int(params.get("end_ts", [0])[0]) if "end_ts" in params and params.get("end_ts", [""])[0].isdigit() else None

        response_data: Any = None

        if path == "/api/config":
            response_data = self._build_config_payload()
        elif path == "/api/listenbrainz-export/status":
            response_data = {"success": True, "job": get_export_job_status(), "listenbrainz_token": get_token_status()}
        elif path == "/api/select-data-source":
            target = params.get("path", [""])[0]
            try:
                resolved = set_active_data_dir(target)
                sync_res = sync_data(data_dir=resolved)
                response_data = {
                    "success": True,
                    "config": self._build_config_payload(),
                    "sync": sync_res,
                }
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=400)
                return
        elif path == "/api/time-range":
            response_data = get_available_time_range()
        elif path == "/api/artist-drilldown":
            artist = params.get("artist", [""])[0]
            response_data = get_artist_drilldown(artist, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/album-drilldown":
            artist = params.get("artist", [""])[0]
            release = params.get("release", [""])[0]
            response_data = get_album_drilldown(artist, release, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/stats":
            response_data = get_overall_stats(timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/top-artists":
            response_data = get_top_artists(limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/top-albums":
            include_plus_one = params.get("plus_one", ["0"])[0] in ("1", "true")
            actual_limit = calculate_tiered_limit(limit) if include_plus_one else limit
            response_data = get_top_albums(limit=actual_limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/top-tracks":
            response_data = get_top_tracks(limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/habits":
            response_data = get_listening_habits(timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/release-years":
            response_data = get_release_years_stats(metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/countries":
            response_data = get_country_stats(metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts)
        elif path == "/api/manual-entries":
            response_data = load_manual_entries()
        elif path == "/api/sync":
            force = params.get("force", ["0"])[0] in ("1", "true")
            target_dir = params.get("data_dir", [None])[0] or get_active_data_dir()
            sync_res = sync_data(data_dir=target_dir, force_refetch=force)
            response_data = {
                "success": True,
                "new_scrobbles": sync_res.get("new_scrobbles", 0),
                "total_listens": sync_res.get("total_listens", 0),
                "elapsed_ms": sync_res.get("elapsed_ms", 0),
                "username": sync_res.get("username"),
                "data_dir": sync_res.get("data_dir"),
                "message": f"Sync completed in {sync_res.get('elapsed_ms', 0)} ms ({sync_res.get('new_scrobbles', 0)} new listens).",
            }
        elif path.startswith("/api/download-export/"):
            self._handle_download_export(path)
            return
        elif path == "/api/generate-collage":
            layout = params.get("layout", ["tiered"])[0]
            raw_formats = params.get("formats", [params.get("format", ["webp"])[0]])[0]
            fmt_list = normalize_formats(raw_formats.split(","))
            show_captions = params.get("captions", ["1"])[0] in ("1", "true", "yes")
            show_flags = params.get("flags", ["1"])[0] in ("1", "true", "yes")
            flag_tag = "flags" if show_flags else "noflags"
            cap_tag = "cap" if show_captions else "nocap"
            stem_name = f"collage_{layout}_{metric}_{timeframe}_{limit}_{cap_tag}_{flag_tag}"
            job_id, stem_path = _allocate_transient_stem(stem_name)

            try:
                if layout == "tiered":
                    saved_paths = generate_tiered_collage(
                        limit=limit,
                        metric=metric,
                        timeframe=timeframe,
                        start_ts=start_ts,
                        end_ts=end_ts,
                        output_path=stem_path,
                        show_captions=show_captions,
                        show_flags=show_flags,
                        formats=fmt_list,
                    )
                else:
                    cols, rows = get_uniform_grid_dims(limit)
                    saved_paths = generate_uniform_collage(
                        grid_size=(cols, rows),
                        metric=metric,
                        timeframe=timeframe,
                        start_ts=start_ts,
                        end_ts=end_ts,
                        output_path=stem_path,
                        show_captions=show_captions,
                        show_flags=show_flags,
                        formats=fmt_list,
                    )
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=500)
                return

            files = _format_transient_files(job_id, saved_paths)
            response_data = {
                "success": bool(files),
                "url": files[0]["url"] if files else None,
                "files": files,
            }
        elif path == "/api/generate-table":
            table_type = params.get("type", ["artists"])[0]
            raw_formats = params.get("formats", [params.get("format", ["webp"])[0]])[0]
            fmt_list = normalize_formats(raw_formats.split(","))
            show_flags = params.get("flags", ["1"])[0] in ("1", "true", "yes")
            flag_tag = "flags" if show_flags else "noflags"
            stem_name = f"table_{table_type}_{metric}_{timeframe}_{limit}_{flag_tag}"
            job_id, stem_path = _allocate_transient_stem(stem_name)

            try:
                if table_type == "artists":
                    saved_paths = generate_artists_table_image(
                        limit=limit,
                        metric=metric,
                        timeframe=timeframe,
                        start_ts=start_ts,
                        end_ts=end_ts,
                        output_path=stem_path,
                        show_flags=show_flags,
                        formats=fmt_list,
                    )
                else:
                    saved_paths = generate_songs_table_image(
                        limit=limit,
                        metric=metric,
                        timeframe=timeframe,
                        start_ts=start_ts,
                        end_ts=end_ts,
                        output_path=stem_path,
                        show_flags=show_flags,
                        formats=fmt_list,
                    )
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=500)
                return

            files = _format_transient_files(job_id, saved_paths)
            response_data = {
                "success": bool(files),
                "url": files[0]["url"] if files else None,
                "files": files,
            }
        elif path == "/api/generate-map":
            raw_formats = params.get("formats", [params.get("format", ["webp"])[0]])[0]
            fmt_list = normalize_formats(raw_formats.split(","))
            show_flags = params.get("flags", ["1"])[0] in ("1", "true", "yes")
            rank_by = params.get("rank_by", ["metric"])[0]
            if rank_by not in ("metric", "artists"):
                rank_by = "metric"
            try:
                top_x = max(1, min(999, int(params.get("top_x", ["5"])[0])))
            except ValueError:
                top_x = 5
            show_pie = params.get("pie", ["0"])[0] in ("1", "true", "yes")
            flag_tag = "flags" if show_flags else "noflags"
            stem_name = f"world_map_{metric}_{rank_by}_{timeframe}_top{top_x}_{flag_tag}"
            job_id, stem_path = _allocate_transient_stem(stem_name)

            try:
                saved_paths = generate_world_map_image(
                    metric=metric,
                    rank_by=rank_by,
                    top_x=top_x,
                    show_pie=show_pie,
                    show_flags=show_flags,
                    timeframe=timeframe,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    output_path=stem_path,
                    formats=fmt_list,
                )
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=500)
                return

            files = _format_transient_files(job_id, saved_paths)
            response_data = {
                "success": bool(files),
                "url": files[0]["url"] if files else None,
                "files": files,
            }
        elif path == "/api/generate-years":
            raw_formats = params.get("formats", [params.get("format", ["webp"])[0]])[0]
            fmt_list = normalize_formats(raw_formats.split(","))
            mode = params.get("mode", ["active"])[0]
            if mode not in ("active", "continuous"):
                mode = "active"
            stem_name = f"release_years_{metric}_{mode}_{timeframe}"
            job_id, stem_path = _allocate_transient_stem(stem_name)

            try:
                saved_paths = generate_release_years_image(
                    metric=metric,
                    mode=mode,
                    timeframe=timeframe,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    output_path=stem_path,
                    formats=fmt_list,
                )
            except Exception as exc:
                self._send_json({"success": False, "error": str(exc)}, status=500)
                return

            files = _format_transient_files(job_id, saved_paths)
            response_data = {
                "success": bool(files),
                "url": files[0]["url"] if files else None,
                "files": files,
            }
        else:
            self._send_json({"error": "Endpoint not found"}, status=404)
            return

        self._send_json(response_data)


def run(port: int = PORT) -> None:
    init_db(DB_PATH)
    ensure_flag_assets()
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    httpd = http.server.ThreadingHTTPServer(("", port), CustomHandler)
    httpd.daemon_threads = True
    print(f"Unofficial MusicBrainz Wrapped running at http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")


if __name__ == "__main__":
    port = PORT
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run(port)
