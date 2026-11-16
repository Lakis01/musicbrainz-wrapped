#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PORT="${1:-8080}"

echo "Starting MusicBrainz Wrapped (Unofficial) at http://localhost:${PORT}"
if command -v xdg-open >/dev/null 2>&1; then
    (sleep 1 && xdg-open "http://localhost:${PORT}" >/dev/null 2>&1 || true) &
fi

exec python3 server.py "${PORT}"
