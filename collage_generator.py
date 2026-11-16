"""High-resolution, mobile-readable collage & leaderboard graphic generator.

Supports parallel tile composition, cached typography/masks, inline vector-rasterized
country flags next to artist names, and single-render multi-format export
(WebP, AVIF, JPG, JXL).
"""

from __future__ import annotations

import functools
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from db import DB_PATH, get_top_albums, get_top_artists, get_top_tracks
from flags import get_flag_rgba

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
CACHE_DIR = os.path.join(STATIC_DIR, "cache")

SUPPORTED_FORMATS = ("webp", "avif", "jpg", "jxl")

OUTPUT_COLLAGE_WEBP = os.path.join(STATIC_DIR, "top_albums_collage_101.webp")
OUTPUT_COLLAGE_AVIF = os.path.join(STATIC_DIR, "top_albums_collage_101.avif")
OUTPUT_ARTISTS_WEBP = os.path.join(STATIC_DIR, "top_50_artists.webp")
OUTPUT_ARTISTS_AVIF = os.path.join(STATIC_DIR, "top_50_artists.avif")
OUTPUT_SONGS_WEBP = os.path.join(STATIC_DIR, "top_50_songs.webp")
OUTPUT_SONGS_AVIF = os.path.join(STATIC_DIR, "top_50_songs.avif")


def _pick_font(*candidates: str) -> str:
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


FONT_BOLD = _pick_font(
    "/usr/share/fonts/TTF/Roboto-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
)
FONT_MEDIUM = _pick_font(
    "/usr/share/fonts/TTF/Roboto-Medium.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/noto/NotoSans-Medium.ttf",
)
FONT_REGULAR = _pick_font(
    "/usr/share/fonts/TTF/Roboto-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
)
FONT_MONO = _pick_font(
    "/usr/share/fonts/TTF/JetBrainsMono-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
)


@functools.lru_cache(maxsize=128)
def get_font(font_path: str, size: int, default_fallback: bool = True):
    try:
        if font_path:
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default() if default_fallback else None


@functools.lru_cache(maxsize=32)
def _get_tile_mask(w: int, h: int, radius: int) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (w, h)], radius=radius, fill=255)
    return mask


@functools.lru_cache(maxsize=32)
def _get_bottom_gradient(w: int, bar_h: int) -> Image.Image:
    grad = Image.new("RGBA", (w, bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grad)
    for i in range(bar_h):
        ratio = i / float(max(bar_h - 1, 1))
        alpha = int(248 * (ratio ** 1.15))
        draw.line([(0, i), (w, i)], fill=(7, 10, 18, alpha))
    return grad


def normalize_formats(formats: Optional[Sequence[str]]) -> List[str]:
    if not formats:
        return ["webp"]
    out: List[str] = []
    for fmt in formats:
        f = str(fmt).strip().lower().lstrip(".")
        if f == "jpeg":
            f = "jpg"
        if f in SUPPORTED_FORMATS and f not in out:
            out.append(f)
    return out or ["webp"]


def save_canvas_image(canvas: Image.Image, output_path: str, quality: int = 92) -> str:
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    ext = os.path.splitext(output_path)[1].lower()
    rgb_canvas = canvas.convert("RGB") if canvas.mode != "RGB" else canvas

    if ext == ".webp":
        # WebP supports up to 16383x16383 at full native crispness
        w, h = rgb_canvas.size
        if max(w, h) > 16300:
            scale = 16300.0 / max(w, h)
            rgb_canvas = rgb_canvas.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        rgb_canvas.save(output_path, "WEBP", quality=quality, method=4)
    elif ext in (".jpg", ".jpeg"):
        rgb_canvas.save(output_path, "JPEG", quality=quality, optimize=True, subsampling=0)
    elif ext == ".jxl":
        tmp_png = output_path + ".tmp.png"
        rgb_canvas.save(tmp_png, "PNG", compress_level=1)
        try:
            subprocess.run(["cjxl", tmp_png, output_path, "-q", str(quality), "--quiet"], check=True)
        finally:
            if os.path.exists(tmp_png):
                os.remove(tmp_png)
    elif ext == ".avif":
        # Hardware/gallery decoders on Android enforce ~4096px max single-frame dimensions.
        w, h = rgb_canvas.size
        max_dim = max(w, h)
        if max_dim > 3840:
            scale = 3840.0 / max_dim
            export_canvas = rgb_canvas.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
            export_canvas.save(output_path, "AVIF", quality=quality)
        else:
            rgb_canvas.save(output_path, "AVIF", quality=quality)
    else:
        rgb_canvas.save(output_path)
    return output_path


def save_canvas_formats(canvas: Image.Image, base_output_path: str, formats: Sequence[str], quality: int = 92) -> List[str]:
    """Encode an already-rendered canvas into one or more image formats in parallel."""
    fmt_list = normalize_formats(formats)
    stem, _ = os.path.splitext(base_output_path)
    targets = [(fmt, f"{stem}.{fmt}") for fmt in fmt_list]

    if len(targets) == 1:
        save_canvas_image(canvas, targets[0][1], quality=quality)
        return [targets[0][1]]

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as ex:
        futures = [ex.submit(save_canvas_image, canvas, path, quality) for _, path in targets]
        return [f.result() for f in futures]


def get_placeholder_cover(size: int, title: str, artist: str, rank: int) -> Image.Image:
    img = Image.new("RGB", (size, size), color=(20, 26, 42))
    draw = ImageDraw.Draw(img)
    for i in range(size):
        ratio = i / float(max(size - 1, 1))
        draw.line([(0, i), (size, i)], fill=(int(24 + 28 * ratio), int(30 + 16 * ratio), int(48 + 38 * ratio)))

    font_large = get_font(FONT_BOLD, max(18, int(size * 0.16)))
    font_small = get_font(FONT_REGULAR, max(12, int(size * 0.068)))
    draw.text((size // 2, size // 2 - int(size * 0.08)), f"#{rank}", fill=(200, 220, 255), anchor="mm", font=font_large)
    short_artist = (artist[:18] + "…") if len(artist) > 20 else artist
    draw.text((size // 2, size // 2 + int(size * 0.16)), short_artist, fill=(180, 190, 210), anchor="mm", font=font_small)
    return img


def get_placeholder_avatar(size: int, name: str, rank: int) -> Image.Image:
    img = Image.new("RGB", (size, size), color=(28, 36, 56))
    draw = ImageDraw.Draw(img)
    initials = "".join([w[0] for w in name.split()[:2] if w]).upper() or f"#{rank}"
    font = get_font(FONT_BOLD, max(11, int(size * 0.38)))
    draw.text((size // 2, size // 2), initials, fill=(180, 210, 255), anchor="mm", font=font)
    return img


def _resolve_local_asset(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    rel = path.lstrip("/")
    candidates = [
        os.path.join(BASE_DIR, "static", rel) if not rel.startswith("static") else os.path.join(BASE_DIR, rel),
        os.path.join(BASE_DIR, rel),
    ]
    for full_path in candidates:
        if os.path.exists(full_path) and os.path.getsize(full_path) > 500:
            return full_path
    return None


def load_album_image(album_dict: dict, size: int) -> Image.Image:
    full_path = _resolve_local_asset(album_dict.get("cover_local_path"))
    if full_path:
        try:
            with Image.open(full_path) as im:
                return im.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass
    return get_placeholder_cover(size, album_dict.get("release_name", "Unknown"), album_dict.get("artist_name", "Unknown"), album_dict.get("rank", 0))


def load_artist_image(artist_dict: dict, size: int) -> Image.Image:
    full_path = _resolve_local_asset(artist_dict.get("image_local_path"))
    if full_path:
        try:
            with Image.open(full_path) as im:
                return im.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass
    return get_placeholder_avatar(size, artist_dict.get("artist_name", "Unknown"), artist_dict.get("rank", 0))


def calculate_tiered_limit(target_limit) -> int:
    try:
        t = int(target_limit)
    except Exception:
        return 101
    if t == 10:
        return 11
    if t == 20:
        return 21
    if t == 30:
        return 31
    if t == 50:
        return 51
    if t >= 100:
        return 101
    if t in (11, 21, 31, 51, 101):
        return t
    if t > 11:
        comp = t - 11
        rem = comp % 5
        return t if rem == 0 else t + (5 - rem)
    if t > 3:
        med = t - 3
        rem = med % 4
        return t if rem == 0 else t + (4 - rem)
    return t


def _truncate_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if max_w <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_w:
        return text
    cur = text
    while cur and draw.textlength(cur + "…", font=font) > max_w:
        cur = cur[:-1]
    return cur + "…" if cur else ""


def _draw_text_shadow(draw: ImageDraw.ImageDraw, pos: Tuple[int, int], text: str, fill, font) -> None:
    x, y = pos
    draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 190), font=font)
    draw.text((x, y), text, fill=fill, font=font)


def create_album_tile(
    alb: dict,
    tile_size: int,
    tier_type: str = "compact",
    show_captions: bool = True,
    metric: str = "minutes",
    show_flags: bool = True,
) -> Image.Image:
    img = load_album_image(alb, tile_size).convert("RGBA")
    w, h = tile_size, tile_size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    rank = alb.get("rank", 1)
    is_hero = (tier_type == "hero") or (rank in (1, 2, 3))

    # Scale typography proportionally with tile size for mobile & desktop legibility
    scale = max(1.0, tile_size / 300.0)
    badge_font_size = int((20 if tier_type == "hero" else (16 if tier_type == "medium" else 14)) * min(scale, 1.3))
    font_badge = get_font(FONT_BOLD, badge_font_size)
    badge_text = f"#{rank}"

    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad_x = 12 if is_hero else 9
    pad_y = 6 if is_hero else 5
    badge_x, badge_y = 12, 12
    bw = text_w + pad_x * 2
    bh = text_h + pad_y * 2

    if is_hero:
        bg_badge = (79, 70, 229, 240)
        border_badge = (255, 255, 255, 145)
    else:
        bg_badge = (15, 23, 42, 232)
        border_badge = (255, 255, 255, 70)

    draw.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + bw, badge_y + bh)],
        radius=7 if is_hero else 6,
        fill=bg_badge,
        outline=border_badge,
        width=1,
    )
    tx = badge_x + (bw - text_w) // 2
    ty = badge_y + (bh - text_h) // 2 - bbox[1]
    draw.text((tx, ty), badge_text, fill=(255, 255, 255, 255), font=font_badge)

    if show_captions:
        bar_h = max(int(h * (0.32 if is_hero else (0.35 if tier_type == "medium" else 0.39))), 86)
        grad = _get_bottom_gradient(w, bar_h)
        overlay.paste(grad, (0, h - bar_h), grad)

        title = alb.get("release_name", "Unknown")
        year = alb.get("original_release_year")
        title_with_year = f"{title} ({year})" if year else title
        artist = alb.get("artist_name", "Unknown")
        mins = alb.get("minutes_listened", 0)
        hrs = alb.get("hours_listened", mins / 60.0)
        plays = alb.get("play_count", 0)

        if metric == "minutes":
            stat_text = f"{mins:,.1f} mins ({hrs:.2f}h)" if mins < 100 else f"{mins:,.0f} mins ({hrs:.1f}h)"
        else:
            stat_text = f"{plays} plays • {mins:,.0f}m"

        title_size = int((22 if is_hero else (17 if tier_type == "medium" else 15)) * (0.95 if tile_size < 320 else 1.0))
        artist_size = int((17 if is_hero else (14 if tier_type == "medium" else 13)) * (0.95 if tile_size < 320 else 1.0))
        stat_size = int((15 if is_hero else (13 if tier_type == "medium" else 12)) * (0.95 if tile_size < 320 else 1.0))

        font_title = get_font(FONT_BOLD, title_size)
        font_artist = get_font(FONT_MEDIUM, artist_size)
        font_stat = get_font(FONT_BOLD, stat_size)

        pad_lr = 14
        max_text_w = w - pad_lr * 2

        cc = alb.get("country_code")
        has_flag = show_flags and bool(cc) and cc != "XX"
        flag_w = int(artist_size * 1.33)
        flag_h = artist_size
        flag_gap = 6 if has_flag else 0

        line1 = _truncate_text(draw, title_with_year, font_title, max_text_w)
        line2 = _truncate_text(draw, artist, font_artist, max_text_w - (flag_w + flag_gap if has_flag else 0))
        line3 = _truncate_text(draw, stat_text, font_stat, max_text_w)

        pad_bottom = 12
        gap_lines = 4

        bbox3 = draw.textbbox((0, 0), line3, font=font_stat)
        h3 = bbox3[3] - bbox3[1]
        bbox2 = draw.textbbox((0, 0), line2, font=font_artist)
        h2 = bbox2[3] - bbox2[1]
        bbox1 = draw.textbbox((0, 0), line1, font=font_title)
        h1 = bbox1[3] - bbox1[1]

        y3 = h - pad_bottom - h3 - bbox3[1]
        y2 = y3 - gap_lines - h2 - bbox2[1]
        y1 = y2 - gap_lines - h1 - bbox1[1]

        _draw_text_shadow(draw, (pad_lr, y1), line1, (255, 255, 255, 255), font_title)
        _draw_text_shadow(draw, (pad_lr, y2), line2, (226, 232, 240, 255), font_artist)

        if has_flag:
            flag_img = get_flag_rgba(cc, flag_w, flag_h)
            art_w = int(draw.textlength(line2, font=font_artist))
            fx = pad_lr + art_w + flag_gap
            fy = y2 + bbox2[1] + max(0, (h2 - flag_h) // 2)
            overlay.paste(flag_img, (fx, fy), flag_img)

        _draw_text_shadow(draw, (pad_lr, y3), line3, (125, 211, 252, 255), font_stat)

    combined = Image.alpha_composite(img, overlay)
    mask = _get_tile_mask(w, h, 10)
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    tile.paste(combined, (0, 0), mask=mask)
    return tile


draw_caption_overlay = create_album_tile


def generate_tiered_collage(
    limit: int = 101,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    output_path: str = OUTPUT_COLLAGE_WEBP,
    canvas_width: int = 1800,
    show_captions: bool = True,
    show_flags: bool = True,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    actual_limit = calculate_tiered_limit(limit)
    albums = get_top_albums(
        limit=actual_limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not albums:
        return None

    pad = 18
    gap = 10
    inner_width = canvas_width - 2 * pad

    hero_size = (inner_width - 2 * gap) // 3
    med_size = (inner_width - 3 * gap) // 4
    comp_size = (inner_width - 4 * gap) // 5

    rows = []
    if len(albums) > 0:
        rows.append(("hero", hero_size, albums[0 : min(3, len(albums))]))
    if len(albums) > 3:
        med_albs = albums[3 : min(11, len(albums))]
        for r_start in range(0, len(med_albs), 4):
            rows.append(("medium", med_size, med_albs[r_start : r_start + 4]))
    if len(albums) > 11:
        comp_albs = albums[11:]
        for r_start in range(0, len(comp_albs), 5):
            rows.append(("compact", comp_size, comp_albs[r_start : r_start + 5]))

    total_height = pad * 2 + sum(t[1] for t in rows) + max(0, len(rows) - 1) * gap
    canvas = Image.new("RGB", (canvas_width, total_height), color=(9, 13, 22))

    # Build tile jobs and render in parallel
    jobs = []
    cur_y = pad
    for tier_type, tile_size, row_albs in rows:
        cur_x = pad
        for alb in row_albs:
            jobs.append((alb, tile_size, tier_type, cur_x, cur_y))
            cur_x += tile_size + gap
        cur_y += tile_size + gap

    def _build(job):
        alb, tile_size, tier_type, x, y = job
        tile = create_album_tile(
            alb, tile_size, tier_type=tier_type, show_captions=show_captions, metric=metric, show_flags=show_flags
        )
        return tile, x, y

    with ThreadPoolExecutor(max_workers=min(12, max(2, os.cpu_count() or 8))) as ex:
        for tile, x, y in ex.map(_build, jobs):
            canvas.paste(tile, (x, y), mask=tile)

    if formats is not None:
        return save_canvas_formats(canvas, output_path, formats, quality=92)
    save_canvas_image(canvas, output_path, quality=92)
    return output_path


def generate_uniform_collage(
    grid_size: Tuple[int, int] = (5, 6),
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    output_path: str = OUTPUT_COLLAGE_WEBP,
    canvas_width: int = 1800,
    show_captions: bool = True,
    show_flags: bool = True,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    cols, rows_count = grid_size
    limit = cols * rows_count
    albums = get_top_albums(
        limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not albums:
        return None

    pad = 18
    gap = 10
    inner_width = canvas_width - 2 * pad
    tile_size = (inner_width - (cols - 1) * gap) // cols

    actual_rows = (len(albums) + cols - 1) // cols
    total_height = pad * 2 + actual_rows * tile_size + max(0, actual_rows - 1) * gap
    canvas = Image.new("RGB", (canvas_width, total_height), color=(9, 13, 22))

    def _build(item):
        idx, alb = item
        c = idx % cols
        r = idx // cols
        tier = "hero" if cols <= 3 else ("medium" if cols == 4 else "compact")
        tile = create_album_tile(
            alb, tile_size, tier_type=tier, show_captions=show_captions, metric=metric, show_flags=show_flags
        )
        return tile, pad + c * (tile_size + gap), pad + r * (tile_size + gap)

    with ThreadPoolExecutor(max_workers=min(12, max(2, os.cpu_count() or 8))) as ex:
        for tile, x, y in ex.map(_build, enumerate(albums)):
            canvas.paste(tile, (x, y), mask=tile)

    if formats is not None:
        return save_canvas_formats(canvas, output_path, formats, quality=92)
    save_canvas_image(canvas, output_path, quality=92)
    return output_path


def _round_avatar(img: Image.Image) -> Image.Image:
    w, h = img.size
    mask = _get_tile_mask(w, h, w // 2)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img.convert("RGBA"), (0, 0), mask)
    return out


def generate_artists_table_image(
    limit: int = 50,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    output_path: str = OUTPUT_ARTISTS_WEBP,
    show_flags: bool = True,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    """Render mobile-friendly 1-column portrait table with inline flags next to artist names."""
    artists = get_top_artists(
        limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not artists:
        return None

    canvas_w = 1120
    padding = 28
    header_h = 104
    row_h = 58
    num_rows = len(artists)
    canvas_h = header_h + (num_rows * row_h) + (padding * 2)

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(10, 14, 24))
    draw = ImageDraw.Draw(canvas)

    font_title = get_font(FONT_BOLD, 32)
    font_sub = get_font(FONT_REGULAR, 17)
    font_rank = get_font(FONT_BOLD, 17)
    font_name = get_font(FONT_BOLD, 20)
    font_plays = get_font(FONT_MEDIUM, 17)
    font_time = get_font(FONT_BOLD, 19)

    draw.text((padding + 8, padding + 6), f"TOP {len(artists)} ARTISTS", fill=(248, 250, 252), font=font_title)
    metric_label = "Listen Time" if metric == "minutes" else "No. of Listens"
    time_label = f"Timeframe: {timeframe.title() if timeframe else 'All Time'}"
    draw.text(
        (padding + 8, padding + 48),
        f"Ranked by {metric_label}  •  {time_label}  •  Unofficial ListenBrainz Visualizer",
        fill=(148, 163, 184),
        font=font_sub,
    )

    with ThreadPoolExecutor(max_workers=8) as ex:
        avatars = list(ex.map(lambda a: _round_avatar(load_artist_image(a, 42)), artists))

    for idx, art in enumerate(artists):
        row_x = padding
        row_w = canvas_w - padding * 2
        row_y = header_h + padding + idx * row_h

        if idx % 2 == 1:
            draw.rounded_rectangle([(row_x, row_y + 2), (row_x + row_w, row_y + row_h - 2)], radius=8, fill=(18, 25, 42))

        rank = art["rank"]
        rank_bg = (245, 158, 11) if rank == 1 else ((148, 163, 184) if rank == 2 else ((217, 119, 6) if rank == 3 else (30, 41, 59)))
        rank_fg = (0, 0, 0) if rank in (1, 2, 3) else (226, 232, 240)
        draw.rounded_rectangle([(row_x + 12, row_y + 13), (row_x + 56, row_y + 45)], radius=6, fill=rank_bg)
        draw.text((row_x + 34, row_y + 29), f"{rank}", fill=rank_fg, font=font_rank, anchor="mm")

        av = avatars[idx]
        canvas.paste(av, (row_x + 68, row_y + 8), av)

        # Stats on right
        plays_text = f"{art['play_count']:,} plays"
        hrs = art["hours_listened"]
        mins = art["minutes_listened"]
        time_str = f"{hrs:.1f}h" if hrs >= 1.0 else f"{mins:.0f}m"

        plays_x = row_x + row_w - 220
        time_x = row_x + row_w - 24
        draw.text((plays_x, row_y + 29), plays_text, fill=(203, 213, 225), font=font_plays, anchor="lm")
        draw.text((time_x, row_y + 29), time_str, fill=(125, 211, 252), font=font_time, anchor="rm")

        # Artist name + inline country flag right next to artist name (same line)
        name_x = row_x + 126
        cc = art.get("country_code")
        has_flag = show_flags and bool(cc) and cc != "XX"
        flag_w, flag_h = 26, 19
        flag_gap = 10
        max_name_w = (plays_x - 24) - name_x - (flag_w + flag_gap if has_flag else 0)
        name_txt = _truncate_text(draw, art["artist_name"], font_name, max_name_w)
        draw.text((name_x, row_y + 29), name_txt, fill=(248, 250, 252), font=font_name, anchor="lm")

        if has_flag:
            flag_img = get_flag_rgba(cc, flag_w, flag_h)
            name_w = int(draw.textlength(name_txt, font=font_name))
            fx = name_x + name_w + flag_gap
            fy = row_y + (row_h - flag_h) // 2
            canvas.paste(flag_img, (fx, fy), flag_img)

    if formats is not None:
        return save_canvas_formats(canvas, output_path, formats, quality=92)
    save_canvas_image(canvas, output_path, quality=92)
    return output_path


def generate_songs_table_image(
    limit: int = 50,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    output_path: str = OUTPUT_SONGS_WEBP,
    show_flags: bool = True,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    """Render mobile-friendly 1-column portrait songs table with inline flags next to artist."""
    tracks = get_top_tracks(
        limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not tracks:
        return None

    canvas_w = 1120
    padding = 28
    header_h = 104
    row_h = 64
    num_rows = len(tracks)
    canvas_h = header_h + (num_rows * row_h) + (padding * 2)

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(10, 14, 24))
    draw = ImageDraw.Draw(canvas)

    font_title = get_font(FONT_BOLD, 32)
    font_sub = get_font(FONT_REGULAR, 17)
    font_rank = get_font(FONT_BOLD, 17)
    font_song = get_font(FONT_BOLD, 19)
    font_artist = get_font(FONT_MEDIUM, 15)
    font_dur = get_font(FONT_REGULAR, 15)
    font_plays = get_font(FONT_MEDIUM, 17)
    font_time = get_font(FONT_BOLD, 19)

    draw.text((padding + 8, padding + 6), f"TOP {len(tracks)} SONGS", fill=(248, 250, 252), font=font_title)
    metric_label = "Listen Time" if metric == "minutes" else "No. of Listens"
    time_label = f"Timeframe: {timeframe.title() if timeframe else 'All Time'}"
    draw.text(
        (padding + 8, padding + 48),
        f"Ranked by {metric_label}  •  {time_label}  •  Unofficial ListenBrainz Visualizer",
        fill=(148, 163, 184),
        font=font_sub,
    )

    def _load_cov(t):
        return load_album_image(
            {
                "cover_local_path": t.get("album_cover_local_path"),
                "release_name": t.get("release_name"),
                "artist_name": t.get("artist_name"),
                "rank": t["rank"],
            },
            44,
        )

    with ThreadPoolExecutor(max_workers=8) as ex:
        covers = list(ex.map(_load_cov, tracks))

    for idx, t in enumerate(tracks):
        row_x = padding
        row_w = canvas_w - padding * 2
        row_y = header_h + padding + idx * row_h

        if idx % 2 == 1:
            draw.rounded_rectangle([(row_x, row_y + 2), (row_x + row_w, row_y + row_h - 2)], radius=8, fill=(18, 25, 42))

        rank = t["rank"]
        rank_bg = (245, 158, 11) if rank == 1 else ((148, 163, 184) if rank == 2 else ((217, 119, 6) if rank == 3 else (30, 41, 59)))
        rank_fg = (0, 0, 0) if rank in (1, 2, 3) else (226, 232, 240)
        draw.rounded_rectangle([(row_x + 12, row_y + 16), (row_x + 56, row_y + 48)], radius=6, fill=rank_bg)
        draw.text((row_x + 34, row_y + 32), f"{rank}", fill=rank_fg, font=font_rank, anchor="mm")

        canvas.paste(covers[idx], (row_x + 68, row_y + 10))

        dur_x = row_x + row_w - 285
        plays_x = row_x + row_w - 190
        time_x = row_x + row_w - 24

        dur = t.get("duration_formatted") or "3:30"
        draw.text((dur_x, row_y + 32), dur, fill=(148, 163, 184), font=font_dur, anchor="lm")
        draw.text((plays_x, row_y + 32), f"{t['play_count']}p", fill=(203, 213, 225), font=font_plays, anchor="lm")
        draw.text((time_x, row_y + 32), f"{t['minutes_listened']:,.0f}m", fill=(125, 211, 252), font=font_time, anchor="rm")

        text_x = row_x + 126
        max_w = (dur_x - 24) - text_x
        song_title = _truncate_text(draw, t["track_name"], font_song, max_w)
        draw.text((text_x, row_y + 20), song_title, fill=(248, 250, 252), font=font_song, anchor="lm")

        artist_name = t["artist_name"]
        cc = t.get("country_code")
        has_flag = show_flags and bool(cc) and cc != "XX"
        flag_w, flag_h = 20, 15

        # Draw artist name, inline flag right next to artist name, then release name
        art_txt = _truncate_text(draw, artist_name, font_artist, int(max_w * 0.55))
        draw.text((text_x, row_y + 44), art_txt, fill=(203, 213, 225), font=font_artist, anchor="lm")
        cur_x = text_x + int(draw.textlength(art_txt, font=font_artist))

        if has_flag:
            flag_img = get_flag_rgba(cc, flag_w, flag_h)
            cur_x += 7
            canvas.paste(flag_img, (cur_x, row_y + 44 - flag_h // 2), flag_img)
            cur_x += flag_w

        rem_w = (dur_x - 24) - cur_x
        if rem_w > 30:
            rel_txt = _truncate_text(draw, f"  •  {t['release_name']}", font_artist, rem_w)
            draw.text((cur_x, row_y + 44), rel_txt, fill=(148, 163, 184), font=font_artist, anchor="lm")

    if formats is not None:
        return save_canvas_formats(canvas, output_path, formats, quality=92)
    save_canvas_image(canvas, output_path, quality=92)
    return output_path


def export_all_visuals(
    timeframe: Optional[str] = None,
    metric: str = "minutes",
    formats: Optional[Sequence[str]] = None,
    show_flags: bool = True,
    db_path: str = DB_PATH,
) -> Dict[str, List[str]]:
    fmt_list = normalize_formats(formats)
    c_out = generate_tiered_collage(
        limit=101,
        metric=metric,
        timeframe=timeframe,
        output_path=os.path.join(STATIC_DIR, "top_albums_collage_101"),
        canvas_width=1800,
        show_captions=True,
        show_flags=show_flags,
        formats=fmt_list,
        db_path=db_path,
    )
    a_out = generate_artists_table_image(
        limit=50,
        metric=metric,
        timeframe=timeframe,
        output_path=os.path.join(STATIC_DIR, "top_50_artists"),
        show_flags=show_flags,
        formats=fmt_list,
        db_path=db_path,
    )
    s_out = generate_songs_table_image(
        limit=50,
        metric=metric,
        timeframe=timeframe,
        output_path=os.path.join(STATIC_DIR, "top_50_songs"),
        show_flags=show_flags,
        formats=fmt_list,
        db_path=db_path,
    )
    return {
        "collage": c_out or [],
        "artists": a_out or [],
        "songs": s_out or [],
    }


export_all_webp_visuals = export_all_visuals

if __name__ == "__main__":
    print(export_all_visuals(formats=["webp"]))
