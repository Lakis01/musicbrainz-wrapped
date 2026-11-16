# MusicBrainz Wrapped (Unofficial)

> **Unofficial Community Project — Disclaimer**  
> This project is **unofficial** and is **not affiliated with, endorsed by, sponsored by, or connected to MusicBrainz, ListenBrainz, or the MetaBrainz Foundation**. Everything runs locally on your own machine.

I originally put this together because I was too impatient waiting for the MusicBrainz / ListenBrainz servers to process and integrate my latest listens into periodic reports—and I wanted a much richer interactive dashboard and visual export studio that I could share with others.

---

## Interactive Localhost Web App + CLI

MusicBrainz Wrapped includes a full **interactive web dashboard** served locally at **`http://localhost:8080`** (no external hosting required—your listening history never leaves your PC) as well as a standalone CLI for terminal summaries and batch image exports.

### Launching the Interactive Website

```bash
pip install -r requirements.txt
./start.sh
# or: python3 server.py
```

Then open **`http://localhost:8080`** in Firefox (or any browser). To explore your stats on your phone over your local network, open `http://<your-computer-ip>:8080`.

Inside the browser you can interactively:
- Switch between **Listen Time** (minutes/hours, default) and **No. of Listens** across every chart, leaderboard, drilldown, and export.
- Filter dynamically by listening year, month, or the dual-thumb **Time Interval** slider.
- Inspect the **Visual Album Compilation**, **Top Artists & Top Songs Wrapped** (Top-3 Podium + proportional metric bars), **Top Albums**, **Unbinned Release Years** (Active Years vs. Full Timeline + spotlight + ledger), **Interactive World Map** (choropleth + hover/tap country stats + configurable Top X Country table + optional Country Pie Chart), and **Listening Habits** (24h clock, weekday rhythm, monthly progression).
- Click any artist, album, or release-year chip to drill down into album and track statistics.

---

## Why Top 101, Top 51, Top 31? (Gapless Grid Math)

In **Tiered Bento** mode, album covers are sized by rank so your favorites stand out without leaving awkward blank slots on the bottom row:

| Tier | Ranks | Layout | Subtotal |
| :--- | :--- | :--- | :---: |
| **Hero Tier** | `#1 – #3` | 1 row × 3 large tiles | **3** |
| **Medium Tier** | `#4 – #11` | 2 rows × 4 medium tiles | **11** |
| **Compact Tier** | `#12+` | *k* rows × 5 compact tiles | `11 + 5k` |

Adding complete 5-tile compact rows gives gapless presets of **Top 11, 16, 21, 26, 31, 41, 51, 76, and 101**—so every generated collage ends on a full, balanced row.

If you prefer **Uniform Grid** mode, the dropdown and CLI automatically adjust to gapless rectangular grids: **Top 9 (3×3)**, **Top 16 (4×4)**, **Top 20 (5×4)**, **Top 25 (5×5)**, **Top 30 (5×6)**, **Top 50 (5×10)**, and **Top 100 (5×20)**.

---

## Key Features

- **Count by Listen Time or No. of Listens**: Global toggle updating all visualizations, rankings, drilldowns, and generated graphics.
- **Inline Country Flags (Default On)**: Self-hosted vector SVG flags rendered **inline next to artist names** across web views and exported posters, with an **Include Flags** toggle (`--flags` / `--no-flags` on CLI).
- **Multi-Format Image Exports (`WebP`, `AVIF`, `JPG`, `JXL`)**: Tick any combination of formats (**WebP** selected by default) to render the collage or Top 50 Artists / Top 50 Songs Wrapped posters once and download all chosen formats.
- **Top Artists & Top Songs Wrapped Visuals**: Top-3 Gold/Silver/Bronze podium cards paired with proportional horizontal metric bars and track length × plays context.
- **World Map & Country Analytics**: Choropleth map (including France, Norway, Taiwan, and Kosovo geometry), hover/tap tooltips with top artists per country, configurable **Top X Countries** table (Top 5 by default), and optional **Country Pie Chart**.
- **Unbinned Individual Release Years**: Every single release year displayed individually (never binned into decades), with Peak Year, Weighted Mean Year, Year Spotlight, and Year-by-Year Ledger.
- **Mobile-Readable UI & Exports**: Full-resolution WebP collages, single-column portrait Top 50 graphics, and responsive phone layouts.

---

## How to Export & Load Your ListenBrainz Data

1. Sign in to ListenBrainz and open **[listenbrainz.org/settings/export/](https://listenbrainz.org/settings/export/)**.
2. Click **Export listens** and download the `.zip` archive (e.g., `listenbrainz_YourName_1794214563.zip`).

Load it using whichever method feels easiest:
1. **Drop into `./imports/`** *(recommended)*: Place the `.zip`/`.tar.gz` archive or extracted folder inside [`imports/`](imports/README.md).
2. **Use the in-app `Data Source` button**:
   - One-click selection from auto-discovered folders (`./imports/`, `~/Documents/Music Library/listenbrainz_*`, `~/Downloads/listenbrainz_*`).
   - Drag-and-drop upload of a `.zip` / `.tar.gz` archive directly in the browser.
   - Or paste any local folder path and click **Load & Sync**.
3. **Or via CLI**:
   ```bash
   python3 visualize.py --sync --data-dir "/path/to/listenbrainz_YourName_1794214563"
   ```

---

## CLI Usage

```bash
# Terminal summary & top 30 by listen time (default)
python3 visualize.py

# Rank by play count for a specific year
python3 visualize.py --metric plays --timeframe 2026 --limit 51

# Export Top 101 Collage, Top 50 Artists, and Top 50 Songs in WebP + JPG
python3 visualize.py --export-all --formats webp,jpg

# Generate a Top 51 collage without country flags
python3 visualize.py --collage --limit 51 --formats webp --no-flags
```

---

## Showcase Exports

| Top 50 Artists Wrapped | Top 50 Songs Wrapped | Top 101 Album Collage |
| :---: | :---: | :---: |
| ![Top 50 Artists Wrapped](static/top_50_artists.webp) | ![Top 50 Songs Wrapped](static/top_50_songs.webp) | ![Top 101 Album Collage](static/top_albums_collage_101.webp) |

---

## Performance & Architecture

- **SQLite Analytics (`db.py`)**: WAL-mode SQLite queries (`listenbrainz.db`) with single-pass aggregations for release years and countries.
- **Parallel Enrichment & Rendering (`importer.py`, `collage_generator.py`)**: `ThreadPoolExecutor` workers parallelize artwork, release-year, and country enrichment, while image exports cache fonts, masks, and gradients and encode ticked formats concurrently from a single canvas render.
- **Lightweight Frontend (`static/`)**: Vanilla HTML5, CSS3, SVG, and ES6+ JavaScript with zero build step and self-hosted SVG flags (`static/flags/`).

---

## License

Released under the [MIT License](LICENSE).
