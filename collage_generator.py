"""High-resolution, mobile-readable collage & Wrapped leaderboard graphic generator.

Supports parallel tile composition, cached typography/masks, inline vector-rasterized
country flags next to artist names, gapless tiered/uniform grid presets, Top-3 podium +
proportional bar chart posters, and single-render multi-format export (WebP, AVIF, JPG, JXL).
"""

from __future__ import annotations

import colorsys
import functools
import json
import math
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    pymupdf = None  # type: ignore

from db import (
    DB_PATH,
    get_country_stats,
    get_release_years_stats,
    get_top_albums,
    get_top_artists,
    get_top_tracks,
)
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
OUTPUT_MAP_WEBP = os.path.join(STATIC_DIR, "world_map.webp")
OUTPUT_YEARS_WEBP = os.path.join(STATIC_DIR, "release_years.webp")
LOGO_PATH = os.path.join(STATIC_DIR, "logo.webp")

# Gapless Tiered Bento counts:
# 3 (1x3 hero), 7 (3 + 1x4 med), 11 (3 + 2x4 med), then +5 compact per row:
# 16, 21, 26, 31, 36, 41, 46, 51, 56, 61, 66, 71, 76, 81, 86, 91, 96, 101
GAPLESS_TIERED_COUNTS = (3, 7, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56, 61, 66, 71, 76, 81, 86, 91, 96, 101)


def _pick_font(*candidates: str) -> str:
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


FONT_DISPLAY = _pick_font(
    "/usr/share/fonts/TTF/FiraSans-Heavy.ttf",
    "/usr/share/fonts/TTF/FiraSans-ExtraBold.ttf",
    "/usr/share/fonts/TTF/Roboto-Black.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)
FONT_BOLD = _pick_font(
    "/usr/share/fonts/TTF/FiraSans-Bold.ttf",
    "/usr/share/fonts/TTF/Roboto-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
)
FONT_SEMIBOLD = _pick_font(
    "/usr/share/fonts/TTF/FiraSans-SemiBold.ttf",
    "/usr/share/fonts/TTF/FiraSans-Medium.ttf",
    "/usr/share/fonts/TTF/Roboto-Medium.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)
FONT_MEDIUM = _pick_font(
    "/usr/share/fonts/TTF/FiraSans-Medium.ttf",
    "/usr/share/fonts/TTF/Roboto-Medium.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/noto/NotoSans-Medium.ttf",
)
FONT_REGULAR = _pick_font(
    "/usr/share/fonts/TTF/FiraSans-Regular.ttf",
    "/usr/share/fonts/TTF/Roboto-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
)
FONT_MONO = _pick_font(
    "/usr/share/fonts/TTF/Hack-Bold.ttf",
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
        rgb_canvas.save(
            output_path,
            "AVIF",
            quality=quality,
            speed=6,
            subsampling="4:4:4",
            max_threads=min(8, os.cpu_count() or 4),
        )
    else:
        rgb_canvas.save(output_path)
    return output_path


def save_canvas_formats(canvas: Image.Image, base_output_path: str, formats: Sequence[str], quality: int = 92) -> List[str]:
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
    """Snap any requested limit to the nearest complete gapless Tiered Bento count."""
    try:
        t = int(target_limit)
    except Exception:
        return 101
    if t <= 3:
        return 3
    if t <= 7:
        return 7
    if t <= 11:
        return 11
    if t in GAPLESS_TIERED_COUNTS:
        return t
    comp = t - 11
    rem = comp % 5
    return t if rem == 0 else t + (5 - rem)


def get_uniform_grid_dims(target_limit) -> Tuple[int, int]:
    """Return gapless (cols, rows) dimensions for uniform grids."""
    try:
        t = int(target_limit)
    except Exception:
        t = 30
    mapping = {
        9: (3, 3),
        12: (4, 3),
        16: (4, 4),
        20: (5, 4),
        25: (5, 5),
        30: (5, 6),
        40: (5, 8),
        50: (5, 10),
        75: (5, 15),
        100: (5, 20),
    }
    if t in mapping:
        return mapping[t]
    cols = 4 if t <= 16 and t % 4 == 0 else (3 if t <= 9 and t % 3 == 0 else 5)
    rows = max(1, (t + cols - 1) // cols)
    return (cols, rows)


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
    show_flags: bool = False,
) -> Image.Image:
    img = load_album_image(alb, tile_size).convert("RGBA")
    w, h = tile_size, tile_size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    rank = alb.get("rank", 1)
    is_hero = (tier_type == "hero") or (rank in (1, 2, 3))

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
        bg_badge = (29, 78, 216, 240)
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
            stat_text = f"{plays} listens • {mins:,.0f}m"

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
    show_flags: bool = False,
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
    show_flags: bool = False,
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


def _round_image(img: Image.Image, radius: Optional[int] = None) -> Image.Image:
    w, h = img.size
    rad = (w // 2) if radius is None else radius
    mask = _get_tile_mask(w, h, rad)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img.convert("RGBA"), (0, 0), mask)
    return out


def _draw_metric_bar(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    ratio: float,
    accent_rgb: Tuple[int, int, int] = (59, 130, 246),
    tip_rgb: Tuple[int, int, int] = (56, 189, 248),
) -> None:
    radius = h // 2
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=radius, fill=(24, 34, 54))
    fill_w = max(h, int(w * max(0.0, min(1.0, ratio))))
    if ratio <= 0:
        return
    # Smooth two-tone horizontal gradient fill inside rounded capsule
    bar_img = Image.new("RGBA", (fill_w, h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bar_img)
    for col in range(fill_w):
        t = col / float(max(fill_w - 1, 1))
        r = int(accent_rgb[0] + (tip_rgb[0] - accent_rgb[0]) * t)
        g = int(accent_rgb[1] + (tip_rgb[1] - accent_rgb[1]) * t)
        b = int(accent_rgb[2] + (tip_rgb[2] - accent_rgb[2]) * t)
        bdraw.line([(col, 0), (col, h)], fill=(r, g, b, 255))
    mask = Image.new("L", (fill_w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (fill_w - 1, h - 1)], radius=radius, fill=255)
    canvas.paste(bar_img, (x, y), mask)


PODIUM_STYLES = {
    1: ((245, 158, 11), (253, 224, 71), (20, 26, 44)),   # Gold
    2: ((148, 163, 184), (226, 232, 240), (16, 24, 42)), # Silver
    3: ((217, 119, 6), (251, 146, 60), (18, 24, 42)),    # Bronze
}


@functools.lru_cache(maxsize=8)
def _load_logo_rgba(size: int = 88) -> Optional[Image.Image]:
    if not os.path.exists(LOGO_PATH):
        return None
    try:
        with Image.open(LOGO_PATH) as im:
            logo = im.convert("RGBA")
        logo.thumbnail((size, size), Image.Resampling.LANCZOS)
        pad = 10
        canvas = Image.new("RGBA", (logo.width + pad * 2, logo.height + pad * 2), (0, 0, 0, 0))
        shadow_alpha = logo.getchannel("A").point(lambda v: int(v * 0.55))
        shadow = Image.new("RGBA", logo.size, (2, 6, 23, 0))
        shadow.putalpha(shadow_alpha)
        shadow_pad = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shadow_pad.paste(shadow, (pad, pad + 3))
        shadow_pad = shadow_pad.filter(ImageFilter.GaussianBlur(radius=5))
        canvas.alpha_composite(shadow_pad)
        canvas.alpha_composite(logo, dest=(pad, pad))
        return canvas
    except Exception:
        return None


def _extract_vibrant_color(img: Image.Image, fallback: Tuple[int, int, int]) -> Tuple[int, int, int]:
    try:
        thumb = img.convert("RGB").resize((24, 24), Image.Resampling.BILINEAR)
        best_score = -1.0
        best_rgb = fallback
        pixels = getattr(thumb, "get_flattened_data", thumb.getdata)()
        for r, g, b in pixels:
            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if v < 0.16 or v > 0.94 or s < 0.20:
                continue
            score = s * (1.0 - abs(v - 0.55))
            if score > best_score:
                best_score = score
                ns = max(0.45, min(0.85, s))
                nv = max(0.52, min(0.88, v))
                nr, ng, nb = colorsys.hsv_to_rgb(h, ns, nv)
                best_rgb = (int(nr * 255), int(ng * 255), int(nb * 255))
        return best_rgb
    except Exception:
        return fallback


def _build_ambient_poster_canvas(
    width: int,
    height: int,
    glow_colors: Sequence[Tuple[int, int, int]],
) -> Image.Image:
    stops = [
        (0.00, (7, 10, 19)),
        (0.18, (13, 20, 38)),
        (0.60, (10, 15, 28)),
        (1.00, (6, 9, 17)),
    ]
    strip = Image.new("RGB", (1, height))
    px = strip.load()
    for y in range(height):
        t = y / float(max(1, height - 1))
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                u = (t - t0) / max(1e-6, t1 - t0)
                px[0, y] = (
                    int(c0[0] + (c1[0] - c0[0]) * u),
                    int(c0[1] + (c1[1] - c0[1]) * u),
                    int(c0[2] + (c1[2] - c0[2]) * u),
                )
                break
    base = strip.resize((width, height), Image.Resampling.BILINEAR).convert("RGBA")

    colors = list(glow_colors) or [(59, 130, 246), (56, 189, 248), (139, 92, 246)]
    while len(colors) < 3:
        colors.append(colors[-1])

    sw, sh = max(120, width // 4), max(120, height // 4)
    glow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    # Soft studio-lit ambient orbs behind header & podium + mid-page cool accent
    orbs = [
        (-int(sw * 0.05), -int(sh * 0.04), int(sw * 0.45), int(sh * 0.24), colors[0], 54),
        (int(sw * 0.28), int(sh * 0.04), int(sw * 0.72), int(sh * 0.28), colors[1], 48),
        (int(sw * 0.62), -int(sh * 0.03), int(sw * 1.06), int(sh * 0.24), colors[2], 50),
        (int(sw * 0.20), int(sh * 0.48), int(sw * 0.85), int(sh * 0.78), colors[0], 24),
    ]
    for x0, y0, x1, y1, rgb, alpha in orbs:
        gdraw.ellipse([(x0, y0), (x1, y1)], fill=(rgb[0], rgb[1], rgb[2], alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=38))
    glow_full = glow.resize((width, height), Image.Resampling.BILINEAR)
    base.alpha_composite(glow_full)
    return base


def _draw_glass_card(
    canvas: Image.Image,
    box: Tuple[int, int, int, int],
    radius: int,
    fill_rgba: Tuple[int, int, int, int],
    border_rgba: Tuple[int, int, int, int],
    top_accent_rgb: Optional[Tuple[int, int, int]] = None,
) -> None:
    x0, y0, x1, y1 = box
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(card)
    cdraw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=fill_rgba, outline=border_rgba, width=1)
    if top_accent_rgb is not None:
        inset = max(radius + 2, 16)
        cdraw.rounded_rectangle(
            [(inset, 0), (max(inset + 4, w - inset), 4)],
            radius=2,
            fill=(top_accent_rgb[0], top_accent_rgb[1], top_accent_rgb[2], 235),
        )
    canvas.alpha_composite(card, dest=(x0, y0))


def _make_blurred_card_backdrop(
    src_img: Image.Image,
    w: int,
    h: int,
    radius: int,
    tint_rgb: Tuple[int, int, int],
) -> Image.Image:
    rgb = src_img.convert("RGB").resize((w, w), Image.Resampling.BILINEAR)
    crop = rgb.crop((0, max(0, (w - h) // 3), w, min(w, max(0, (w - h) // 3) + h))).resize(
        (w, h), Image.Resampling.BILINEAR
    )
    blurred = crop.filter(ImageFilter.GaussianBlur(radius=24))
    tint_img = Image.new("RGB", (w, h), tint_rgb)
    tinted = Image.blend(blurred, tint_img, 0.34).convert("RGBA")

    # Smooth vertical fade to transparent in lower 40%
    grad = Image.new("L", (1, h), 0)
    gpx = grad.load()
    fade_end = int(h * 0.68)
    for y in range(h):
        if y >= fade_end:
            gpx[0, y] = 0
        else:
            t = 1.0 - (y / float(max(1, fade_end)))
            gpx[0, y] = int(96 * (t ** 1.4))
    alpha_grad = grad.resize((w, h), Image.Resampling.BILINEAR)
    card_mask = _get_tile_mask(w, h, radius)
    # Intersect gradient fade with rounded card mask
    from PIL import ImageChops
    final_mask = ImageChops.multiply(alpha_grad, card_mask)
    tinted.putalpha(final_mask)
    return tinted


def _paste_circular_with_ring(
    canvas: Image.Image,
    avatar_rgba: Image.Image,
    cx: int,
    cy: int,
    ring_rgb: Tuple[int, int, int],
    ring_w: int = 3,
) -> None:
    sz = avatar_rgba.width
    r = sz // 2
    pad = ring_w + 10
    ring_sz = sz + pad * 2
    overlay = Image.new("RGBA", (ring_sz, ring_sz), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    rc = ring_sz // 2
    odraw.ellipse(
        [(rc - r - ring_w - 3, rc - r - ring_w + 2), (rc + r + ring_w + 3, rc + r + ring_w + 8)],
        fill=(2, 6, 23, 145),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=4))
    odraw = ImageDraw.Draw(overlay)
    odraw.ellipse(
        [(rc - r - ring_w, rc - r - ring_w), (rc + r + ring_w, rc + r + ring_w)],
        fill=(ring_rgb[0], ring_rgb[1], ring_rgb[2], 215),
    )
    odraw.ellipse([(rc - r, rc - r), (rc + r, rc + r)], fill=(12, 18, 32, 255))
    canvas.alpha_composite(overlay, dest=(cx - rc, cy - rc))
    canvas.alpha_composite(avatar_rgba, dest=(cx - r, cy - r))


def _paste_cover_with_shadow(
    canvas: Image.Image,
    cover_rgba: Image.Image,
    x: int,
    y: int,
    radius: int,
    border_rgb: Tuple[int, int, int] = (148, 163, 184),
) -> None:
    w, h = cover_rgba.size
    pad = 12
    sh = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [(pad, pad + 4), (pad + w, pad + h + 4)],
        radius=radius,
        fill=(2, 6, 23, 165),
    )
    sh = sh.filter(ImageFilter.GaussianBlur(radius=6))
    canvas.alpha_composite(sh, dest=(x - pad, y - pad))
    canvas.alpha_composite(cover_rgba, dest=(x, y))
    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(
        [(0, 0), (w - 1, h - 1)],
        radius=radius,
        outline=(border_rgb[0], border_rgb[1], border_rgb[2], 145),
        width=2,
    )
    canvas.alpha_composite(rim, dest=(x, y))


def _draw_poster_header(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    padding: int,
    canvas_w: int,
    title: str,
    subtitle: str,
    accent_rgb: Tuple[int, int, int],
    meta_pill: Optional[str] = None,
) -> int:
    """Render clean editorial header: Title top-left, Logo top-right, divider rule."""
    font_title = get_font(FONT_DISPLAY, 48)
    font_sub = get_font(FONT_MEDIUM, 17)
    font_pill = get_font(FONT_MONO, 13)

    logo = _load_logo_rgba(88)
    logo_space = (logo.width + 24) if logo is not None else 0
    max_title_w = canvas_w - padding * 2 - logo_space

    # Fit title gracefully if very long
    title_sz = 48
    while title_sz > 30 and draw.textlength(title, font=get_font(FONT_DISPLAY, title_sz)) > max_title_w:
        title_sz -= 2
    font_title = get_font(FONT_DISPLAY, title_sz)

    draw.text((padding, padding + 2), title, fill=(248, 250, 252), font=font_title)

    sub_y = padding + 68
    draw.ellipse([(padding, sub_y - 5), (padding + 10, sub_y + 5)], fill=accent_rgb)
    draw.text((padding + 20, sub_y), subtitle, fill=(148, 163, 184), font=font_sub, anchor="lm")

    if meta_pill:
        sub_end_x = padding + 20 + int(draw.textlength(subtitle, font=font_sub)) + 16
        pill_tw = int(draw.textlength(meta_pill, font=font_pill))
        pill_w = pill_tw + 22
        if sub_end_x + pill_w < canvas_w - padding - logo_space:
            _draw_glass_card(
                canvas,
                (sub_end_x, sub_y - 13, sub_end_x + pill_w, sub_y + 13),
                radius=13,
                fill_rgba=(22, 33, 56, 220),
                border_rgba=(accent_rgb[0], accent_rgb[1], accent_rgb[2], 125),
            )
            draw.text((sub_end_x + pill_w // 2, sub_y), meta_pill, fill=(203, 213, 225), font=font_pill, anchor="mm")

    if logo is not None:
        lx = canvas_w - padding - logo.width + 10
        ly = max(8, padding - 6)
        canvas.alpha_composite(logo, dest=(lx, ly))

    div_y = padding + 100
    div_w = canvas_w - padding * 2
    # Gradient hairline divider
    div_img = Image.new("RGBA", (div_w, 2), (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(div_img)
    for col in range(div_w):
        t = col / float(max(1, div_w - 1))
        if t < 0.35:
            u = t / 0.35
            r = int(accent_rgb[0] + (51 - accent_rgb[0]) * u)
            g = int(accent_rgb[1] + (65 - accent_rgb[1]) * u)
            b = int(accent_rgb[2] + (95 - accent_rgb[2]) * u)
            a = int(210 - 95 * u)
        else:
            r, g, b, a = 51, 65, 95, int(115 * (1.0 - (t - 0.35) / 0.65 * 0.65))
        ddraw.point((col, 0), fill=(r, g, b, a))
        ddraw.point((col, 1), fill=(r, g, b, a // 2))
    canvas.alpha_composite(div_img, dest=(padding, div_y))
    return div_y + 22


def _draw_row_gradient_bar(
    canvas: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    ratio: float,
    accent_rgb: Tuple[int, int, int],
    tip_rgb: Tuple[int, int, int],
) -> None:
    radius = max(2, h // 2)
    track = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(track).rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=(26, 37, 60, 220))
    canvas.alpha_composite(track, dest=(x, y))
    if ratio <= 0:
        return
    fill_w = max(h, int(w * max(0.0, min(1.0, ratio))))
    bar_img = Image.new("RGBA", (fill_w, h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bar_img)
    for col in range(fill_w):
        t = col / float(max(1, fill_w - 1))
        r = int(accent_rgb[0] + (tip_rgb[0] - accent_rgb[0]) * t)
        g = int(accent_rgb[1] + (tip_rgb[1] - accent_rgb[1]) * t)
        b = int(accent_rgb[2] + (tip_rgb[2] - accent_rgb[2]) * t)
        bdraw.line([(col, 0), (col, h - 1)], fill=(r, g, b, 255))
    mask = Image.new("L", (fill_w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (fill_w - 1, h - 1)], radius=radius, fill=255)
    bar_img.putalpha(mask)
    canvas.alpha_composite(bar_img, dest=(x, y))


def generate_artists_table_image(
    limit: int = 50,
    metric: str = "minutes",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    output_path: str = OUTPUT_ARTISTS_WEBP,
    show_flags: bool = False,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    """Render editorial Wrapped Top Artists poster with elevated #1 Podium and 2-col ranked cards."""
    artists = get_top_artists(
        limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not artists:
        return None

    is_min = metric == "minutes"
    max_val = max((a["minutes_listened"] if is_min else a["play_count"]) for a in artists) or 1.0

    canvas_w = 1600
    padding = 44
    inner_w = canvas_w - padding * 2
    header_total_h = padding + 122  # matches _draw_poster_header return bottom

    podium_items = artists[: min(3, len(artists))]
    rest_items = artists[len(podium_items) :]

    # Fetch portraits concurrently before compositing so ambient glows use real #1-#3 palette
    def _load_pod_av(a):
        sz = 144 if a["rank"] == 1 and len(podium_items) == 3 else 118
        return load_artist_image(a, sz)

    with ThreadPoolExecutor(max_workers=8) as ex:
        raw_podium = list(ex.map(_load_pod_av, podium_items))
        row_avatars = list(ex.map(lambda a: _round_image(load_artist_image(a, 48)), rest_items))

    podium_avatars = [_round_image(im) for im in raw_podium]
    glow_palette = [
        _extract_vibrant_color(im, fallback)
        for im, fallback in zip(raw_podium, [(245, 158, 11), (56, 189, 248), (139, 92, 246)])
    ]

    podium_area_h = 374 if podium_items else 0
    podium_gap = 28 if rest_items else 0
    two_col = len(rest_items) > 10
    row_h = 74
    row_gap = 10

    if rest_items:
        if two_col:
            left_count = (len(rest_items) + 1) // 2
            list_h = left_count * row_h + max(0, left_count - 1) * row_gap
        else:
            list_h = len(rest_items) * row_h + max(0, len(rest_items) - 1) * row_gap
    else:
        list_h = 0

    canvas_h = header_total_h + podium_area_h + podium_gap + list_h + padding
    canvas = _build_ambient_poster_canvas(canvas_w, canvas_h, glow_palette)
    draw = ImageDraw.Draw(canvas)

    metric_label = "Listen Time" if is_min else "No. of Listens"
    time_label = _format_timeframe_label(timeframe, start_ts, end_ts)
    total_hrs_shown = sum(a["hours_listened"] for a in artists)
    total_plays_shown = sum(a["play_count"] for a in artists)
    unique_cc = len({a["country_code"] for a in artists if a.get("country_code") and a["country_code"] != "XX"})
    meta_pill = (
        f"{total_hrs_shown:,.1f} hrs  •  {unique_cc} countries"
        if (is_min and unique_cc > 0)
        else (f"{total_hrs_shown:,.1f} hrs shown" if is_min else f"{total_plays_shown:,} listens shown")
    )
    podium_y = _draw_poster_header(
        canvas,
        draw,
        padding=padding,
        canvas_w=canvas_w,
        title=f"TOP {len(artists)} ARTISTS",
        subtitle=f"Ranked by {metric_label}  •  Timeframe: {time_label}",
        accent_rgb=(56, 189, 248),
        meta_pill=meta_pill,
    )

    font_podium_rank = get_font(FONT_MONO, 14)
    font_podium_pct = get_font(FONT_MONO, 12)
    font_rank = get_font(FONT_MONO, 15)
    font_name = get_font(FONT_BOLD, 19)
    font_val = get_font(FONT_MONO, 16)
    font_sub_row = get_font(FONT_MONO, 13)
    font_pct = get_font(FONT_MONO, 12)

    # Architectural Podium (#2 Left, #1 Center Elevated, #3 Right when 3 artists)
    if podium_items:
        card_gap = 22
        if len(podium_items) == 3:
            # Order visually as [rank 2, rank 1, rank 3]
            layout_specs = [
                (1, padding, 458, podium_y + 24, 350, 118),
                (0, padding + 458 + card_gap, 552, podium_y, 374, 144),
                (2, padding + 458 + card_gap + 552 + card_gap, 458, podium_y + 24, 350, 118),
            ]
        else:
            cw = (inner_w - card_gap * (len(podium_items) - 1)) // len(podium_items)
            layout_specs = [
                (i, padding + i * (cw + card_gap), cw, podium_y, 360, 132)
                for i in range(len(podium_items))
            ]

        for item_idx, cx, cw, cy, ch, av_sz in layout_specs:
            art = podium_items[item_idx]
            rank = art["rank"]
            is_crown = rank == 1
            accent, tip, card_bg = PODIUM_STYLES.get(rank, ((59, 130, 246), (56, 189, 248), (17, 24, 39)))

            # Glass card base
            _draw_glass_card(
                canvas,
                (cx, cy, cx + cw, cy + ch),
                radius=18,
                fill_rgba=(card_bg[0], card_bg[1], card_bg[2], 235),
                border_rgba=(accent[0], accent[1], accent[2], 145 if is_crown else 95),
                top_accent_rgb=tip,
            )
            # Soft blurred artwork atmosphere inside card top
            backdrop = _make_blurred_card_backdrop(raw_podium[item_idx], cw - 2, ch - 2, radius=17, tint_rgb=accent)
            canvas.alpha_composite(backdrop, dest=(cx + 1, cy + 1))

            # Rank pill top-left & share pill top-right
            val = art["minutes_listened"] if is_min else art["play_count"]
            ratio = val / max_val
            pct_int = int(round(ratio * 100))

            _draw_glass_card(
                canvas,
                (cx + 18, cy + 18, cx + 68, cy + 46),
                radius=8,
                fill_rgba=(accent[0], accent[1], accent[2], 245),
                border_rgba=(tip[0], tip[1], tip[2], 200),
            )
            draw.text((cx + 43, cy + 32), f"#{rank}", fill=(10, 14, 24), font=font_podium_rank, anchor="mm")

            pill_lbl = "LEADER" if is_crown else f"{pct_int}% OF #1"
            pill_w = int(draw.textlength(pill_lbl, font=font_podium_pct)) + 20
            _draw_glass_card(
                canvas,
                (cx + cw - 18 - pill_w, cy + 20, cx + cw - 18, cy + 44),
                radius=12,
                fill_rgba=(12, 18, 32, 195),
                border_rgba=(accent[0], accent[1], accent[2], 105),
            )
            draw.text((cx + cw - 18 - pill_w // 2, cy + 32), pill_lbl, fill=tip, font=font_podium_pct, anchor="mm")

            # Circular portrait with metallic halo ring
            av_cy = cy + (104 if is_crown else 96)
            _paste_circular_with_ring(canvas, podium_avatars[item_idx], cx + cw // 2, av_cy, accent, ring_w=3 if is_crown else 2)

            # Name + inline flag
            font_p_name = get_font(FONT_BOLD, 25 if is_crown else 21)
            font_p_val = get_font(FONT_DISPLAY, 33 if is_crown else 27)
            font_p_sub = get_font(FONT_MEDIUM, 14)

            cc = art.get("country_code")
            has_flag = show_flags and bool(cc) and cc != "XX"
            flag_w, flag_h = (28, 20) if is_crown else (24, 18)
            flag_gap = 9 if has_flag else 0
            max_nw = cw - 40 - (flag_w + flag_gap if has_flag else 0)
            name_txt = _truncate_text(draw, art["artist_name"], font_p_name, max_nw)
            name_w = int(draw.textlength(name_txt, font=font_p_name))
            tot_nw = name_w + flag_gap + (flag_w if has_flag else 0)
            nx = cx + (cw - tot_nw) // 2
            ny = cy + (206 if is_crown else 186)
            draw.text((nx, ny), name_txt, fill=(248, 250, 252), font=font_p_name, anchor="lm")
            if has_flag:
                fimg = get_flag_rgba(cc, flag_w, flag_h)
                canvas.alpha_composite(fimg, dest=(nx + name_w + flag_gap, ny - flag_h // 2))

            # Hero metric + secondary summary
            hrs = art["hours_listened"]
            mins = art["minutes_listened"]
            primary_txt = f"{hrs:.1f} hrs" if is_min else f"{art['play_count']:,} listens"
            secondary_txt = f"{mins:,.0f} mins  •  {art['play_count']:,} listens" if is_min else f"{hrs:.1f} hrs ({mins:,.0f} mins)"
            draw.text((cx + cw // 2, cy + (256 if is_crown else 234)), primary_txt, fill=tip, font=font_p_val, anchor="mm")
            draw.text((cx + cw // 2, cy + (290 if is_crown else 268)), secondary_txt, fill=(148, 163, 184), font=font_p_sub, anchor="mm")

            # Sleek metallic proportional bar
            _draw_row_gradient_bar(canvas, cx + 26, cy + ch - 28, cw - 52, 10, ratio, accent_rgb=accent, tip_rgb=tip)

    # Ranked Visual Cards (#4+) — 2-column magazine layout (column-major) when > 10 rest items
    list_y = podium_y + podium_area_h + podium_gap
    if rest_items:
        col_gap = 20
        col_w = (inner_w - col_gap) // 2 if two_col else inner_w
        left_count = (len(rest_items) + 1) // 2 if two_col else len(rest_items)

        for idx, art in enumerate(rest_items):
            col_idx = (0 if idx < left_count else 1) if two_col else 0
            row_idx = (idx if idx < left_count else idx - left_count) if two_col else idx
            rx = padding + col_idx * (col_w + col_gap)
            ry = list_y + row_idx * (row_h + row_gap)
            rank = art["rank"]
            is_top10 = rank <= 10

            _draw_glass_card(
                canvas,
                (rx, ry, rx + col_w, ry + row_h),
                radius=12,
                fill_rgba=(18, 26, 45, 225) if is_top10 else (14, 21, 36, 205),
                border_rgba=(56, 189, 248, 70) if is_top10 else (51, 65, 85, 90),
            )

            # Rank Pill
            _draw_glass_card(
                canvas,
                (rx + 12, ry + 19, rx + 58, ry + 55),
                radius=8,
                fill_rgba=(29, 78, 216, 130) if is_top10 else (30, 41, 59, 210),
                border_rgba=(56, 189, 248, 110) if is_top10 else (71, 85, 105, 85),
            )
            draw.text((rx + 35, ry + 37), f"#{rank}", fill=(224, 242, 254) if is_top10 else (203, 213, 225), font=font_rank, anchor="mm")

            # Circular Avatar
            av = row_avatars[idx]
            canvas.alpha_composite(av, dest=(rx + 68, ry + 13))

            # Text + Proportional Bar right of avatar
            cx_start = rx + 128
            cx_end = rx + col_w - 16
            top_y = ry + 26

            hrs = art["hours_listened"]
            mins = art["minutes_listened"]
            primary_txt = f"{mins:,.0f}m ({hrs:.1f}h)" if is_min else f"{art['play_count']:,} plays"
            secondary_txt = f"• {art['play_count']:,}p" if is_min else f"• {mins:,.0f}m"
            sec_w = int(draw.textlength(secondary_txt, font=font_sub_row))
            prim_w = int(draw.textlength(primary_txt, font=font_val))

            draw.text((cx_end, top_y), secondary_txt, fill=(148, 163, 184), font=font_sub_row, anchor="rm")
            draw.text((cx_end - sec_w - 8, top_y), primary_txt, fill=(125, 211, 252), font=font_val, anchor="rm")

            # Artist name + inline flag
            cc = art.get("country_code")
            has_flag = show_flags and bool(cc) and cc != "XX"
            flag_w, flag_h = 22, 16
            flag_gap = 8 if has_flag else 0
            stat_block_w = prim_w + sec_w + 22
            max_nw = (cx_end - stat_block_w) - cx_start - (flag_w + flag_gap if has_flag else 0)
            name_txt = _truncate_text(draw, art["artist_name"], font_name, max_nw)
            draw.text((cx_start, top_y), name_txt, fill=(248, 250, 252), font=font_name, anchor="lm")
            if has_flag:
                fimg = get_flag_rgba(cc, flag_w, flag_h)
                nw = int(draw.textlength(name_txt, font=font_name))
                canvas.alpha_composite(fimg, dest=(cx_start + nw + flag_gap, top_y - flag_h // 2))

            # Proportional bar on lower half + % label
            val = art["minutes_listened"] if is_min else art["play_count"]
            ratio = val / max_val
            pct_str = f"{max(1, int(round(ratio * 100)))}%"
            pct_w = 38
            bar_w = (cx_end - cx_start) - pct_w - 8
            _draw_row_gradient_bar(
                canvas,
                cx_start,
                ry + 49,
                bar_w,
                8,
                ratio,
                accent_rgb=(59, 130, 246) if is_top10 else (37, 99, 235),
                tip_rgb=(56, 189, 248) if is_top10 else (34, 211, 238),
            )
            draw.text((cx_end, ry + 53), pct_str, fill=(148, 163, 184), font=font_pct, anchor="rm")

        # Balance bottom-right odd slot in 2-column mode with a crisp collection summary card
        if two_col and (len(rest_items) % 2 == 1):
            sx = padding + (col_w + col_gap)
            sy = list_y + (left_count - 1) * (row_h + row_gap)
            _draw_glass_card(
                canvas,
                (sx, sy, sx + col_w, sy + row_h),
                radius=12,
                fill_rgba=(15, 23, 42, 195),
                border_rgba=(56, 189, 248, 65),
            )
            sum_lbl = f"TOP {len(artists)} SUMMARY"
            sum_vals = (
                f"{total_hrs_shown:,.1f} hrs  •  {total_plays_shown:,} listens  •  {unique_cc} countries"
                if unique_cc > 0
                else f"{total_hrs_shown:,.1f} hrs  •  {total_plays_shown:,} listens"
            )
            draw.text((sx + 20, sy + row_h // 2), sum_lbl, fill=(56, 189, 248), font=font_podium_pct, anchor="lm")
            draw.text((sx + col_w - 20, sy + row_h // 2), sum_vals, fill=(203, 213, 225), font=font_sub_row, anchor="rm")

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
    show_flags: bool = False,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    """Render editorial Wrapped Top Songs poster with elevated #1 Podium and 2-col ranked cards."""
    tracks = get_top_tracks(
        limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not tracks:
        return None

    is_min = metric == "minutes"
    max_val = max((t["minutes_listened"] if is_min else t["play_count"]) for t in tracks) or 1.0

    canvas_w = 1600
    padding = 44
    inner_w = canvas_w - padding * 2
    header_total_h = padding + 122

    podium_items = tracks[: min(3, len(tracks))]
    rest_items = tracks[len(podium_items) :]

    def _load_raw_cov(t, sz):
        return load_album_image(
            {
                "cover_local_path": t.get("album_cover_local_path"),
                "release_name": t.get("release_name"),
                "artist_name": t.get("artist_name"),
                "rank": t["rank"],
            },
            sz,
        )

    def _load_pod_cov(t):
        sz = 140 if t["rank"] == 1 and len(podium_items) == 3 else 114
        return _load_raw_cov(t, sz)

    with ThreadPoolExecutor(max_workers=8) as ex:
        raw_podium = list(ex.map(_load_pod_cov, podium_items))
        row_covs = list(ex.map(lambda t: _round_image(_load_raw_cov(t, 52), radius=9), rest_items))

    podium_covs = [_round_image(im, radius=16 if podium_items[i]["rank"] == 1 and len(podium_items) == 3 else 13) for i, im in enumerate(raw_podium)]
    glow_palette = [
        _extract_vibrant_color(im, fallback)
        for im, fallback in zip(raw_podium, [(139, 92, 246), (56, 189, 248), (245, 158, 11)])
    ]

    podium_area_h = 390 if podium_items else 0
    podium_gap = 28 if rest_items else 0
    two_col = len(rest_items) > 10
    row_h = 82
    row_gap = 10

    if rest_items:
        if two_col:
            left_count = (len(rest_items) + 1) // 2
            list_h = left_count * row_h + max(0, left_count - 1) * row_gap
        else:
            list_h = len(rest_items) * row_h + max(0, len(rest_items) - 1) * row_gap
    else:
        list_h = 0

    canvas_h = header_total_h + podium_area_h + podium_gap + list_h + padding
    canvas = _build_ambient_poster_canvas(canvas_w, canvas_h, glow_palette)
    draw = ImageDraw.Draw(canvas)

    metric_label = "Listen Time" if is_min else "No. of Listens"
    time_label = _format_timeframe_label(timeframe, start_ts, end_ts)
    total_mins_shown = sum(t["minutes_listened"] for t in tracks)
    total_plays_shown = sum(t["play_count"] for t in tracks)
    meta_pill = (
        f"{total_mins_shown / 60.0:,.1f} hrs  •  {total_plays_shown:,} plays"
        if is_min
        else f"{total_plays_shown:,} listens  •  {total_mins_shown / 60.0:,.1f} hrs"
    )
    podium_y = _draw_poster_header(
        canvas,
        draw,
        padding=padding,
        canvas_w=canvas_w,
        title=f"TOP {len(tracks)} SONGS",
        subtitle=f"Ranked by {metric_label}  •  Timeframe: {time_label}",
        accent_rgb=(139, 92, 246),
        meta_pill=meta_pill,
    )

    font_podium_rank = get_font(FONT_MONO, 14)
    font_podium_pct = get_font(FONT_MONO, 12)
    font_rank = get_font(FONT_MONO, 15)
    font_song = get_font(FONT_BOLD, 18)
    font_artist = get_font(FONT_MEDIUM, 14)
    font_val = get_font(FONT_MONO, 16)
    font_sub_row = get_font(FONT_MONO, 12)
    font_pct = get_font(FONT_MONO, 12)

    # Architectural Podium (#2 Left, #1 Center Elevated, #3 Right)
    if podium_items:
        card_gap = 22
        if len(podium_items) == 3:
            layout_specs = [
                (1, padding, 458, podium_y + 24, 366, 114, 13),
                (0, padding + 458 + card_gap, 552, podium_y, 390, 140, 16),
                (2, padding + 458 + card_gap + 552 + card_gap, 458, podium_y + 24, 366, 114, 13),
            ]
        else:
            cw = (inner_w - card_gap * (len(podium_items) - 1)) // len(podium_items)
            layout_specs = [
                (i, padding + i * (cw + card_gap), cw, podium_y, 374, 128, 15)
                for i in range(len(podium_items))
            ]

        for item_idx, cx, cw, cy, ch, cov_sz, cov_rad in layout_specs:
            t = podium_items[item_idx]
            rank = t["rank"]
            is_crown = rank == 1
            accent, tip, card_bg = PODIUM_STYLES.get(rank, ((139, 92, 246), (192, 132, 252), (17, 24, 39)))

            _draw_glass_card(
                canvas,
                (cx, cy, cx + cw, cy + ch),
                radius=18,
                fill_rgba=(card_bg[0], card_bg[1], card_bg[2], 235),
                border_rgba=(accent[0], accent[1], accent[2], 145 if is_crown else 95),
                top_accent_rgb=tip,
            )
            backdrop = _make_blurred_card_backdrop(raw_podium[item_idx], cw - 2, ch - 2, radius=17, tint_rgb=accent)
            canvas.alpha_composite(backdrop, dest=(cx + 1, cy + 1))

            val = t["minutes_listened"] if is_min else t["play_count"]
            ratio = val / max_val
            pct_int = int(round(ratio * 100))

            _draw_glass_card(
                canvas,
                (cx + 18, cy + 18, cx + 68, cy + 46),
                radius=8,
                fill_rgba=(accent[0], accent[1], accent[2], 245),
                border_rgba=(tip[0], tip[1], tip[2], 200),
            )
            draw.text((cx + 43, cy + 32), f"#{rank}", fill=(10, 14, 24), font=font_podium_rank, anchor="mm")

            pill_lbl = "TOP TRACK" if is_crown else f"{pct_int}% OF #1"
            pill_w = int(draw.textlength(pill_lbl, font=font_podium_pct)) + 20
            _draw_glass_card(
                canvas,
                (cx + cw - 18 - pill_w, cy + 20, cx + cw - 18, cy + 44),
                radius=12,
                fill_rgba=(12, 18, 32, 195),
                border_rgba=(accent[0], accent[1], accent[2], 105),
            )
            draw.text((cx + cw - 18 - pill_w // 2, cy + 32), pill_lbl, fill=tip, font=font_podium_pct, anchor="mm")

            cov_x = cx + cw // 2 - cov_sz // 2
            cov_y = cy + (28 if is_crown else 26)
            _paste_cover_with_shadow(canvas, podium_covs[item_idx], cov_x, cov_y, radius=cov_rad, border_rgb=accent)

            font_p_song = get_font(FONT_BOLD, 24 if is_crown else 20)
            font_p_art = get_font(FONT_MEDIUM, 15)
            font_p_alb = get_font(FONT_REGULAR, 13)
            font_p_val = get_font(FONT_DISPLAY, 31 if is_crown else 26)
            font_p_sub = get_font(FONT_MONO, 13)

            title_y = cov_y + cov_sz + 24
            song_txt = _truncate_text(draw, t["track_name"], font_p_song, cw - 36)
            draw.text((cx + cw // 2, title_y), song_txt, fill=(248, 250, 252), font=font_p_song, anchor="mm")

            cc = t.get("country_code")
            has_flag = show_flags and bool(cc) and cc != "XX"
            flag_w, flag_h = 20, 15
            flag_gap = 7 if has_flag else 0
            art_txt = _truncate_text(draw, t["artist_name"], font_p_art, cw - 44 - (flag_w + flag_gap if has_flag else 0))
            art_w = int(draw.textlength(art_txt, font=font_p_art))
            tot_aw = art_w + flag_gap + (flag_w if has_flag else 0)
            ax = cx + (cw - tot_aw) // 2
            ay = title_y + 26
            draw.text((ax, ay), art_txt, fill=(203, 213, 225), font=font_p_art, anchor="lm")
            if has_flag:
                fimg = get_flag_rgba(cc, flag_w, flag_h)
                canvas.alpha_composite(fimg, dest=(ax + art_w + flag_gap, ay - flag_h // 2))

            rel_name = (t.get("release_name") or "").strip()
            if rel_name:
                alb_txt = _truncate_text(draw, rel_name, font_p_alb, cw - 44)
                draw.text((cx + cw // 2, ay + 20), alb_txt, fill=(148, 163, 184), font=font_p_alb, anchor="mm")

            dur = t.get("duration_formatted") or "3:30"
            primary_txt = f"{t['minutes_listened']:,.0f} mins" if is_min else f"{t['play_count']:,} listens"
            secondary_txt = f"{dur} × {t['play_count']} listens"
            draw.text((cx + cw // 2, cy + ch - 78), primary_txt, fill=tip, font=font_p_val, anchor="mm")
            draw.text((cx + cw // 2, cy + ch - 46), secondary_txt, fill=(148, 163, 184), font=font_p_sub, anchor="mm")

            _draw_row_gradient_bar(canvas, cx + 26, cy + ch - 26, cw - 52, 10, ratio, accent_rgb=accent, tip_rgb=tip)

    # Ranked 2-Column Editorial Song Cards (#4+)
    list_y = podium_y + podium_area_h + podium_gap
    if rest_items:
        col_gap = 20
        col_w = (inner_w - col_gap) // 2 if two_col else inner_w
        left_count = (len(rest_items) + 1) // 2 if two_col else len(rest_items)

        for idx, t in enumerate(rest_items):
            col_idx = (0 if idx < left_count else 1) if two_col else 0
            row_idx = (idx if idx < left_count else idx - left_count) if two_col else idx
            rx = padding + col_idx * (col_w + col_gap)
            ry = list_y + row_idx * (row_h + row_gap)
            rank = t["rank"]
            is_top10 = rank <= 10

            _draw_glass_card(
                canvas,
                (rx, ry, rx + col_w, ry + row_h),
                radius=12,
                fill_rgba=(18, 25, 45, 225) if is_top10 else (14, 21, 36, 205),
                border_rgba=(139, 92, 246, 75) if is_top10 else (51, 65, 85, 90),
            )

            _draw_glass_card(
                canvas,
                (rx + 12, ry + 24, rx + 58, ry + 58),
                radius=8,
                fill_rgba=(99, 102, 241, 130) if is_top10 else (30, 41, 59, 210),
                border_rgba=(167, 139, 250, 115) if is_top10 else (71, 85, 105, 85),
            )
            draw.text((rx + 35, ry + 41), f"#{rank}", fill=(237, 233, 254) if is_top10 else (203, 213, 225), font=font_rank, anchor="mm")

            canvas.alpha_composite(row_covs[idx], dest=(rx + 68, ry + 15))

            cx_start = rx + 132
            cx_end = rx + col_w - 16
            top_y = ry + 22

            dur = t.get("duration_formatted") or "3:30"
            primary_txt = f"{t['minutes_listened']:,.0f}m" if is_min else f"{t['play_count']} plays"
            secondary_txt = f"{dur} × {t['play_count']}p" if is_min else f"{t['minutes_listened']:,.0f}m ({dur})"
            sec_w = int(draw.textlength(secondary_txt, font=font_sub_row))
            prim_w = int(draw.textlength(primary_txt, font=font_val))

            draw.text((cx_end, top_y), secondary_txt, fill=(148, 163, 184), font=font_sub_row, anchor="rm")
            draw.text((cx_end - sec_w - 8, top_y), primary_txt, fill=(196, 181, 253), font=font_val, anchor="rm")

            max_song_w = (cx_end - prim_w - sec_w - 22) - cx_start
            song_txt = _truncate_text(draw, t["track_name"], font_song, max_song_w)
            draw.text((cx_start, top_y), song_txt, fill=(248, 250, 252), font=font_song, anchor="lm")

            # Artist + flag + album on middle line
            mid_y = ry + 45
            cc = t.get("country_code")
            has_flag = show_flags and bool(cc) and cc != "XX"
            flag_w, flag_h = 18, 13
            max_meta_w = cx_end - cx_start
            art_txt = _truncate_text(draw, t["artist_name"], font_artist, int(max_meta_w * 0.52))
            draw.text((cx_start, mid_y), art_txt, fill=(203, 213, 225), font=font_artist, anchor="lm")
            cur_x = cx_start + int(draw.textlength(art_txt, font=font_artist))
            if has_flag:
                fimg = get_flag_rgba(cc, flag_w, flag_h)
                cur_x += 7
                canvas.alpha_composite(fimg, dest=(cur_x, mid_y - flag_h // 2))
                cur_x += flag_w
            rem_w = cx_end - cur_x
            if rem_w > 34 and (t.get("release_name") or "").strip():
                rel_txt = _truncate_text(draw, f"  •  {t['release_name']}", font_artist, rem_w)
                draw.text((cur_x, mid_y), rel_txt, fill=(148, 163, 184), font=font_artist, anchor="lm")

            # Bottom sleek gradient bar + %
            val = t["minutes_listened"] if is_min else t["play_count"]
            ratio = val / max_val
            pct_str = f"{max(1, int(round(ratio * 100)))}%"
            pct_w = 38
            bar_w = (cx_end - cx_start) - pct_w - 8
            _draw_row_gradient_bar(
                canvas,
                cx_start,
                ry + 62,
                bar_w,
                7,
                ratio,
                accent_rgb=(124, 58, 237) if is_top10 else (99, 102, 241),
                tip_rgb=(56, 189, 248) if is_top10 else (96, 165, 250),
            )
            draw.text((cx_end, ry + 65), pct_str, fill=(148, 163, 184), font=font_pct, anchor="rm")

        if two_col and (len(rest_items) % 2 == 1):
            sx = padding + (col_w + col_gap)
            sy = list_y + (left_count - 1) * (row_h + row_gap)
            _draw_glass_card(
                canvas,
                (sx, sy, sx + col_w, sy + row_h),
                radius=12,
                fill_rgba=(15, 23, 42, 195),
                border_rgba=(139, 92, 246, 70),
            )
            sum_lbl = f"TOP {len(tracks)} SUMMARY"
            sum_vals = f"{total_mins_shown:,.0f} mins ({total_mins_shown / 60.0:.1f}h)  •  {total_plays_shown:,} listens"
            draw.text((sx + 20, sy + row_h // 2), sum_lbl, fill=(167, 139, 250), font=font_podium_pct, anchor="lm")
            draw.text((sx + col_w - 20, sy + row_h // 2), sum_vals, fill=(203, 213, 225), font=font_sub_row, anchor="rm")

    if formats is not None:
        return save_canvas_formats(canvas, output_path, formats, quality=92)
    save_canvas_image(canvas, output_path, quality=92)
    return output_path


def _format_timeframe_label(
    timeframe: Optional[str], start_ts: Optional[int], end_ts: Optional[int]
) -> str:
    if start_ts and end_ts:
        d1 = datetime.fromtimestamp(start_ts).strftime("%d %b %Y")
        d2 = datetime.fromtimestamp(end_ts).strftime("%d %b %Y")
        return f"{d1} – {d2}"
    return timeframe.title() if timeframe and timeframe != "all" else "All Time"


def _render_svg_to_rgba(svg_str: str, width: int, height: int) -> Optional[Image.Image]:
    if pymupdf is None:
        return None
    doc = pymupdf.open(stream=svg_str.encode("utf-8"), filetype="svg")
    try:
        page = doc[0]
        rect = page.rect
        sx = width / max(rect.width, 1.0)
        sy = height / max(rect.height, 1.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(sx, sy), alpha=True)
        img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        if img.size != (width, height):
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        return img
    finally:
        doc.close()


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    s = hex_color.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _load_world_geo() -> Dict[str, Any]:
    main_path = os.path.join(STATIC_DIR, "world_countries.json")
    extra_path = os.path.join(STATIC_DIR, "countries_svg.json")
    if not os.path.isfile(main_path):
        return {}
    with open(main_path, "r", encoding="utf-8") as fp:
        main_geo = json.load(fp)
    if "CN-TW" in main_geo and "TW" not in main_geo:
        main_geo["TW"] = main_geo.pop("CN-TW")
    if os.path.isfile(extra_path):
        with open(extra_path, "r", encoding="utf-8") as fp:
            extra_geo = json.load(fp)
        for code, entry in extra_geo.items():
            if code not in main_geo or code in ("FR", "NO", "XK"):
                main_geo[code] = entry
    return main_geo


def _get_map_brackets(countries: List[Dict[str, Any]], metric: str, rank_by: str) -> List[Dict[str, Any]]:
    if rank_by == "artists":
        return [
            {"min": 50, "label": "50+ artists", "color": "#f59e0b"},
            {"min": 20, "label": "20 – 49", "color": "#ec4899"},
            {"min": 10, "label": "10 – 19", "color": "#a855f7"},
            {"min": 5, "label": "5 – 9", "color": "#3b82f6"},
            {"min": 2, "label": "2 – 4", "color": "#06b6d4"},
            {"min": 1, "label": "1 artist", "color": "#10b981"},
        ]
    vals = [c["minutes_listened"] if metric == "minutes" else c["play_count"] for c in countries]
    max_val = max(vals, default=1) or 1
    if metric == "plays":
        if max_val < 500:
            return [
                {"min": math.ceil(max_val * 0.55), "label": f"{math.ceil(max_val * 0.55)}+ listens", "color": "#f59e0b"},
                {"min": math.ceil(max_val * 0.25), "label": f"{math.ceil(max_val * 0.25)}+", "color": "#ec4899"},
                {"min": math.ceil(max_val * 0.10), "label": f"{math.ceil(max_val * 0.10)}+", "color": "#a855f7"},
                {"min": 10, "label": "10+", "color": "#3b82f6"},
                {"min": 3, "label": "3 – 9", "color": "#06b6d4"},
                {"min": 1, "label": "1 – 2", "color": "#0f766e"},
            ]
        return [
            {"min": 1500, "label": "1,500+ listens", "color": "#f59e0b"},
            {"min": 500, "label": "500 – 1,499", "color": "#ec4899"},
            {"min": 150, "label": "150 – 499", "color": "#a855f7"},
            {"min": 50, "label": "50 – 149", "color": "#3b82f6"},
            {"min": 15, "label": "15 – 49", "color": "#06b6d4"},
            {"min": 1, "label": "1 – 14 listens", "color": "#0f766e"},
        ]
    return [
        {"min": 5000, "label": "5,000+ mins (83h+)", "color": "#f59e0b"},
        {"min": 1500, "label": "1,500 – 5,000m", "color": "#ec4899"},
        {"min": 500, "label": "500 – 1,500m", "color": "#a855f7"},
        {"min": 150, "label": "150 – 500m", "color": "#3b82f6"},
        {"min": 30, "label": "30 – 150m", "color": "#06b6d4"},
        {"min": 1, "label": "1 – 30m", "color": "#0f766e"},
    ]


def _choropleth_fill(val: float, brackets: List[Dict[str, Any]]) -> Tuple[str, float]:
    if not val or val <= 0:
        return "#1e293b", 0.55
    for b in brackets:
        if val >= b["min"]:
            return b["color"], 0.92
    return "#0f766e", 0.85


PIE_COLORS_HEX = [
    "#3b82f6", "#f59e0b", "#10b981", "#ec4899", "#06b6d4",
    "#a855f7", "#f43f5e", "#84cc16", "#fb923c", "#6366f1",
    "#14b8a6", "#eab308", "#e879f9", "#38bdf8", "#f97316",
]


def _era_color_hex(year: int) -> str:
    if year < 1970:
        return "#f59e0b"
    if year < 1980:
        return "#ec4899"
    if year < 1990:
        return "#a855f7"
    if year < 2000:
        return "#3b82f6"
    if year < 2010:
        return "#06b6d4"
    if year < 2020:
        return "#10b981"
    return "#6366f1"


def _paste_rotated_text(
    canvas: Image.Image,
    text: str,
    font,
    fill: Tuple[int, int, int],
    anchor_x: int,
    anchor_y: int,
    angle: float = 90.0,
    center_y: bool = False,
) -> None:
    if not text:
        return
    tmp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tmp)
    bbox = tdraw.textbbox((0, 0), text, font=font)
    tw = max(1, bbox[2] - bbox[0] + 6)
    th = max(1, bbox[3] - bbox[1] + 6)
    sprite = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(sprite).text((3 - bbox[0], 3 - bbox[1]), text, fill=fill + (255,), font=font)
    rot = sprite.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    px = anchor_x - rot.width // 2
    py = (anchor_y - rot.height // 2) if center_y else (anchor_y - rot.height)
    canvas.paste(rot, (px, py), rot)


def generate_world_map_image(
    metric: str = "minutes",
    rank_by: str = "metric",
    top_x: int = 5,
    show_pie: bool = False,
    show_flags: bool = False,
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    output_path: str = OUTPUT_MAP_WEBP,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    """Render World Map choropleth, bracket legend, Top X Countries table, and optional Donut Pie."""
    countries = get_country_stats(
        metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not countries:
        return None

    geo = _load_world_geo()
    is_min = metric == "minutes"
    brackets = _get_map_brackets(countries, metric=metric, rank_by=rank_by)
    country_map = {c["country_code"]: c for c in countries}

    canvas_w = 1600
    padding = 36
    inner_w = canvas_w - padding * 2
    header_h = 122

    map_card_h = 796
    map_w = inner_w - 28
    map_h = map_w // 2

    actual_top_x = len(countries) if top_x >= 999 else min(max(1, top_x), len(countries))
    table_rows = countries[:actual_top_x]

    # Build Pie data if enabled
    is_artist_pie = rank_by == "artists"
    pie_segments: List[Dict[str, Any]] = []
    pie_total = 1.0
    if show_pie:
        pie_count = min(12, len(countries)) if top_x >= 999 else actual_top_x
        top_slice = countries[:pie_count]
        rest_slice = countries[pie_count:]
        pie_total = sum(
            (c["artist_count"] if is_artist_pie else (c["minutes_listened"] if is_min else c["play_count"]))
            for c in countries
        ) or 1.0
        for idx, c in enumerate(top_slice):
            val = c["artist_count"] if is_artist_pie else (c["minutes_listened"] if is_min else c["play_count"])
            pie_segments.append({
                "label": c["country_name"],
                "code": c["country_code"],
                "val": val,
                "pct": (val / pie_total) * 100.0,
                "color": PIE_COLORS_HEX[idx % len(PIE_COLORS_HEX)],
            })
        rest_val = sum(
            (c["artist_count"] if is_artist_pie else (c["minutes_listened"] if is_min else c["play_count"]))
            for c in rest_slice
        )
        if rest_val > 0:
            pie_segments.append({
                "label": f"Other ({len(rest_slice)} countries)",
                "code": "XX",
                "val": rest_val,
                "pct": (rest_val / pie_total) * 100.0,
                "color": "#475569",
            })

    row_h = 52
    table_header_h = 92
    table_card_h = table_header_h + len(table_rows) * row_h + 18
    pie_card_h = (320 + len(pie_segments) * 34 + 24) if show_pie else 0
    insights_h = max(table_card_h, pie_card_h)

    canvas_h = padding + header_h + map_card_h + 24 + insights_h + padding
    canvas = _build_ambient_poster_canvas(canvas_w, canvas_h, [(56, 189, 248), (59, 130, 246), (139, 92, 246)])
    draw = ImageDraw.Draw(canvas)

    font_h3 = get_font(FONT_BOLD, 20)
    font_th = get_font(FONT_BOLD, 12)
    font_cell = get_font(FONT_MEDIUM, 15)
    font_cell_bold = get_font(FONT_BOLD, 15)
    font_mono = get_font(FONT_MONO, 14)
    font_small = get_font(FONT_REGULAR, 13)
    font_legend = get_font(FONT_MONO, 12)

    metric_label = "Listen Time" if is_min else "No. of Listens"
    rank_label = "Artist Count" if rank_by == "artists" else metric_label
    time_label = _format_timeframe_label(timeframe, start_ts, end_ts)
    map_card_y = _draw_poster_header(
        canvas,
        draw,
        padding=padding,
        canvas_w=canvas_w,
        title="WORLD MAP OF LISTENING ORIGINS",
        subtitle=f"Colored by {rank_label}  •  Ranked by {metric_label}  •  Timeframe: {time_label}",
        accent_rgb=(56, 189, 248),
        meta_pill=f"{len(countries)} Countries",
    )
    draw.rounded_rectangle(
        [(padding, map_card_y), (padding + inner_w, map_card_y + map_card_h)],
        radius=16,
        fill=(7, 11, 20),
        outline=(51, 65, 85),
        width=1,
    )

    if geo:
        svg_parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 500" width="1000" height="500">',
            '<rect width="1000" height="500" fill="#070b14" rx="10"/>',
            '<path d="M 0 125 L 1000 125 M 0 250 L 1000 250 M 0 375 L 1000 375" stroke="#131c2e" stroke-width="1"/>',
            '<path d="M 250 0 L 250 500 M 500 0 L 500 500 M 750 0 L 750 500" stroke="#131c2e" stroke-width="1"/>',
        ]
        for code, entry in geo.items():
            cdata = country_map.get(code)
            val = (
                (cdata["artist_count"] if rank_by == "artists" else (cdata["minutes_listened"] if is_min else cdata["play_count"]))
                if cdata else 0
            )
            fill_hex, op = _choropleth_fill(val, brackets)
            d_path = xml_escape(str(entry.get("path", "")))
            svg_parts.append(
                f'<path d="{d_path}" fill="{fill_hex}" fill-opacity="{op}" stroke="#293548" stroke-width="0.5"/>'
            )
        svg_parts.append("</svg>")
        map_img = _render_svg_to_rgba("".join(svg_parts), map_w, map_h)
        if map_img is not None:
            canvas.paste(map_img, (padding + 14, map_card_y + 14), map_img)

    # Legend overlay card inside bottom-left of Map Card
    leg_items = list(reversed(brackets)) + [{"label": "No listens", "color": "#1e293b"}]
    leg_w = 216
    leg_h = 18 + len(leg_items) * 22
    leg_x = padding + 28
    leg_y = map_card_y + map_card_h - leg_h - 20
    draw.rounded_rectangle(
        [(leg_x, leg_y), (leg_x + leg_w, leg_y + leg_h)],
        radius=10,
        fill=(15, 23, 42),
        outline=(51, 65, 85),
        width=1,
    )
    for idx, item in enumerate(leg_items):
        iy = leg_y + 12 + idx * 22
        draw.rounded_rectangle(
            [(leg_x + 12, iy + 2), (leg_x + 28, iy + 13)],
            radius=2,
            fill=_hex_to_rgb(item["color"]),
        )
        draw.text((leg_x + 38, iy + 7), item["label"], fill=(203, 213, 225), font=font_legend, anchor="lm")

    # Insights grid (Table + optional Pie)
    grid_y = map_card_y + map_card_h + 24
    table_w = 960 if show_pie else inner_w
    draw.rounded_rectangle(
        [(padding, grid_y), (padding + table_w, grid_y + table_card_h)],
        radius=16,
        fill=(19, 28, 46),
        outline=(42, 55, 82),
        width=1,
    )
    table_title = f"All Countries ({len(countries)})" if top_x >= 999 else f"Top {actual_top_x} Countries"
    draw.text((padding + 22, grid_y + 22), table_title, fill=(248, 250, 252), font=font_h3)
    draw.rounded_rectangle([(padding + table_w - 134, grid_y + 18), (padding + table_w - 20, grid_y + 44)], radius=6, fill=(29, 78, 216))
    draw.text((padding + table_w - 77, grid_y + 31), metric_label, fill=(255, 255, 255), font=font_small, anchor="mm")

    # Table column positions
    col_rank_x = padding + 22
    col_country_x = padding + 62
    col_time_x = padding + (408 if show_pie else 570)
    col_plays_x = padding + (492 if show_pie else 715)
    col_art_x = padding + (562 if show_pie else 835)
    col_share_x = padding + (706 if show_pie else 1070)
    col_lead_x = padding + (730 if show_pie else 1105)

    th_y = grid_y + 68
    draw.line([(padding + 18, th_y + 14), (padding + table_w - 18, th_y + 14)], fill=(42, 55, 82), width=1)
    draw.text((col_rank_x, th_y), "#", fill=(148, 163, 184), font=font_th, anchor="lm")
    draw.text((col_country_x, th_y), "COUNTRY", fill=(148, 163, 184), font=font_th, anchor="lm")
    draw.text((col_time_x, th_y), "LISTEN TIME", fill=(148, 163, 184), font=font_th, anchor="rm")
    draw.text((col_plays_x, th_y), "LISTENS", fill=(148, 163, 184), font=font_th, anchor="rm")
    draw.text((col_art_x, th_y), "ARTISTS", fill=(148, 163, 184), font=font_th, anchor="rm")
    draw.text((col_share_x, th_y), "SHARE", fill=(148, 163, 184), font=font_th, anchor="rm")
    draw.text((col_lead_x, th_y), "LEADING ARTIST", fill=(148, 163, 184), font=font_th, anchor="lm")

    for idx, c in enumerate(table_rows):
        ry = grid_y + table_header_h + idx * row_h
        if idx % 2 == 0:
            draw.rounded_rectangle([(padding + 14, ry + 2), (padding + table_w - 14, ry + row_h - 4)], radius=8, fill=(15, 23, 42))
        cy = ry + row_h // 2
        draw.text((col_rank_x, cy), f"#{c['rank']}", fill=(203, 213, 225), font=font_mono, anchor="lm")

        cx = col_country_x
        cc = c.get("country_code")
        if show_flags and cc and cc != "XX":
            fimg = get_flag_rgba(cc, 24, 18)
            canvas.paste(fimg, (cx, cy - 9), fimg)
            cx += 32
        cname = _truncate_text(draw, c["country_name"], font_cell_bold, (col_time_x - 110) - cx)
        draw.text((cx, cy), cname, fill=(248, 250, 252), font=font_cell_bold, anchor="lm")

        time_txt = f"{c['minutes_listened']:,.0f}m ({c['hours_listened']:.1f}h)"
        draw.text((col_time_x, cy), time_txt, fill=(125, 211, 252), font=font_mono, anchor="rm")
        draw.text((col_plays_x, cy), f"{c['play_count']:,}", fill=(203, 213, 225), font=font_mono, anchor="rm")
        draw.text((col_art_x, cy), f"{c['artist_count']:,}", fill=(203, 213, 225), font=font_mono, anchor="rm")

        share_color = _hex_to_rgb(PIE_COLORS_HEX[idx % len(PIE_COLORS_HEX)])
        bar_w = 50 if show_pie else 90
        bar_x = col_share_x - bar_w
        draw.text((bar_x - 8, cy), f"{c['share_pct']}%", fill=(248, 250, 252), font=font_mono, anchor="rm")
        draw.rounded_rectangle([(bar_x, cy - 4), (bar_x + bar_w, cy + 4)], radius=4, fill=(30, 41, 59))
        fill_px = max(4, int(bar_w * min(100.0, c["share_pct"]) / 100.0)) if c["share_pct"] > 0 else 0
        if fill_px > 0:
            draw.rounded_rectangle([(bar_x, cy - 4), (bar_x + fill_px, cy + 4)], radius=4, fill=share_color)

        lead_name = (c.get("top_artists") or [{}])[0].get("artist_name", "—")
        lead_txt = _truncate_text(draw, lead_name, font_cell, (padding + table_w - 20) - col_lead_x)
        draw.text((col_lead_x, cy), lead_txt, fill=(203, 213, 225), font=font_cell, anchor="lm")

    # Optional Country Donut Pie Card
    if show_pie:
        pie_x = padding + table_w + 24
        pie_w = inner_w - table_w - 24
        draw.rounded_rectangle(
            [(pie_x, grid_y), (pie_x + pie_w, grid_y + pie_card_h)],
            radius=16,
            fill=(19, 28, 46),
            outline=(42, 55, 82),
            width=1,
        )
        draw.text((pie_x + 22, grid_y + 22), "Country Share Breakdown", fill=(248, 250, 252), font=font_h3)

        cx_svg, cy_svg, r_outer, r_inner = 120, 120, 104, 56
        ang = -math.pi / 2
        arc_paths = []
        for seg in pie_segments:
            frac = seg["val"] / pie_total
            sweep = frac * math.pi * 2
            end_ang = ang + sweep
            large = 1 if sweep > math.pi else 0
            if frac >= 0.999:
                arc_paths.append(
                    f'<circle cx="{cx_svg}" cy="{cy_svg}" r="{r_outer}" fill="{seg["color"]}"/>'
                    f'<circle cx="{cx_svg}" cy="{cy_svg}" r="{r_inner}" fill="#131c2e"/>'
                )
            else:
                x1, y1 = cx_svg + r_outer * math.cos(ang), cy_svg + r_outer * math.sin(ang)
                x2, y2 = cx_svg + r_outer * math.cos(end_ang), cy_svg + r_outer * math.sin(end_ang)
                x3, y3 = cx_svg + r_inner * math.cos(end_ang), cy_svg + r_inner * math.sin(end_ang)
                x4, y4 = cx_svg + r_inner * math.cos(ang), cy_svg + r_inner * math.sin(ang)
                d = (
                    f"M {x1:.2f} {y1:.2f} A {r_outer} {r_outer} 0 {large} 1 {x2:.2f} {y2:.2f} "
                    f"L {x3:.2f} {y3:.2f} A {r_inner} {r_inner} 0 {large} 0 {x4:.2f} {y4:.2f} Z"
                )
                arc_paths.append(f'<path d="{d}" fill="{seg["color"]}" stroke="#090d16" stroke-width="1.5"/>')
            ang = end_ang

        pie_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" width="240" height="240">'
            + "".join(arc_paths)
            + "</svg>"
        )
        pie_img = _render_svg_to_rgba(pie_svg, 240, 240)
        pie_cx = pie_x + pie_w // 2
        pie_cy = grid_y + 185
        if pie_img is not None:
            canvas.paste(pie_img, (pie_cx - 120, pie_cy - 120), pie_img)
        if is_artist_pie:
            center_txt = f"{int(pie_total):,}"
            center_sub = "artists"
        elif is_min:
            center_txt = f"{round(pie_total / 60):,}h"
            center_sub = "attributed"
        else:
            center_txt = f"{int(pie_total):,}"
            center_sub = "listens"
        draw.text((pie_cx, pie_cy - 8), center_txt, fill=(248, 250, 252), font=font_h3, anchor="mm")
        draw.text((pie_cx, pie_cy + 14), center_sub, fill=(148, 163, 184), font=font_small, anchor="mm")

        leg_start_y = grid_y + 318
        unit_suffix = "a" if is_artist_pie else ("m" if is_min else "p")
        for idx, seg in enumerate(pie_segments):
            ly = leg_start_y + idx * 34
            draw.rounded_rectangle([(pie_x + 20, ly), (pie_x + pie_w - 20, ly + 28)], radius=6, fill=(15, 23, 42))
            draw.rounded_rectangle([(pie_x + 30, ly + 9), (pie_x + 40, ly + 19)], radius=3, fill=_hex_to_rgb(seg["color"]))
            lx = pie_x + 48
            if show_flags and seg["code"] != "XX":
                fimg = get_flag_rgba(seg["code"], 18, 13)
                canvas.paste(fimg, (lx, ly + 7), fimg)
                lx += 24
            val_str = f"{seg['pct']:.1f}% ({seg['val']:,.0f}{unit_suffix})"
            vw = int(draw.textlength(val_str, font=font_legend))
            lbl_txt = _truncate_text(draw, seg["label"], font_small, (pie_x + pie_w - 38 - vw) - lx)
            draw.text((lx, ly + 14), lbl_txt, fill=(226, 232, 240), font=font_small, anchor="lm")
            draw.text((pie_x + pie_w - 30, ly + 14), val_str, fill=(148, 163, 184), font=font_legend, anchor="rm")

    if formats is not None:
        return save_canvas_formats(canvas, output_path, formats, quality=92)
    save_canvas_image(canvas, output_path, quality=92)
    return output_path


def generate_release_years_image(
    metric: str = "minutes",
    mode: str = "active",
    timeframe: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    output_path: str = OUTPUT_YEARS_WEBP,
    formats: Optional[Sequence[str]] = None,
    db_path: str = DB_PATH,
):
    """Render unbinned individual Release Years distribution poster with KPIs and top-year highlights."""
    payload = get_release_years_stats(
        metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    timeline = payload.get("years") or []
    summary = payload.get("summary") or {}
    is_min = metric == "minutes"
    active_years = [y for y in timeline if (y["minutes_listened"] if is_min else y["play_count"]) > 0]
    if not active_years:
        return None

    display_years = active_years if mode == "active" else timeline
    top_years = sorted(
        active_years,
        key=lambda y: (y["minutes_listened"] if is_min else y["play_count"], y["year"]),
        reverse=True,
    )[:8]

    canvas_w = 1600
    padding = 36
    inner_w = canvas_w - padding * 2
    header_h = 122
    kpi_h = 92
    chart_card_h = 490
    top_rows = (len(top_years) + 1) // 2
    highlights_h = 68 + top_rows * 88 + 14

    canvas_h = padding + header_h + kpi_h + 20 + chart_card_h + 22 + highlights_h + padding
    canvas = _build_ambient_poster_canvas(canvas_w, canvas_h, [(6, 182, 212), (99, 102, 241), (245, 158, 11)])
    draw = ImageDraw.Draw(canvas)

    font_kpi_lbl = get_font(FONT_BOLD, 11)
    font_kpi_val = get_font(FONT_BOLD, 21)
    font_h3 = get_font(FONT_BOLD, 20)
    font_legend = get_font(FONT_MEDIUM, 13)
    font_bar_val = get_font(FONT_MONO, 10)
    font_bar_yr = get_font(FONT_MONO, 11)
    font_card_title = get_font(FONT_BOLD, 16)
    font_card_sub = get_font(FONT_REGULAR, 13)
    font_mono = get_font(FONT_MONO, 14)

    metric_label = "Listen Time" if is_min else "No. of Listens"
    mode_label = "Active Years" if mode == "active" else "Full Continuous Timeline"
    time_label = _format_timeframe_label(timeframe, start_ts, end_ts)
    kpi_y = _draw_poster_header(
        canvas,
        draw,
        padding=padding,
        canvas_w=canvas_w,
        title="RELEASE YEARS DISTRIBUTION (UNBINNED)",
        subtitle=f"Metric: {metric_label}  •  View: {mode_label}  •  Timeframe: {time_label}",
        accent_rgb=(6, 182, 212),
    )

    # 6-card KPI Strip (including Listening Age)
    kpi_gap = 12
    kpi_w = (inner_w - kpi_gap * 5) // 6
    peak_val_str = f"{summary['peak_minutes']:,.0f}m" if is_min else f"{summary['peak_plays']:,}p"
    kpis = [
        ("PEAK YEAR", f"{summary.get('peak_year')} ({peak_val_str})" if summary.get("peak_year") else "--", False),
        ("WEIGHTED AVG YEAR", f"{summary['weighted_avg_year']}" if summary.get("weighted_avg_year") else "--", False),
        ("LISTENING AGE", f"{summary['listening_age']} yrs" if summary.get("listening_age") else "--", True),
        ("RELEASE SPAN", f"{summary['earliest_year']} – {summary['latest_year']}" if summary.get("earliest_year") else "--", False),
        ("ACTIVE YEARS", f"{summary.get('active_years_count', 0)} years", False),
        ("METADATA COVERAGE", f"{summary.get('coverage_pct', 0)}%", False),
    ]
    for idx, (lbl, val_txt, is_accent) in enumerate(kpis):
        kx = padding + idx * (kpi_w + kpi_gap)
        _draw_glass_card(
            canvas,
            (kx, kpi_y, kx + kpi_w, kpi_y + kpi_h),
            radius=12,
            fill_rgba=(22, 34, 58, 230) if is_accent else (19, 28, 46, 215),
            border_rgba=(56, 189, 248, 130) if is_accent else (42, 55, 82, 190),
            top_accent_rgb=(56, 189, 248) if is_accent else None,
        )
        draw.text((kx + 16, kpi_y + 24), lbl, fill=(125, 211, 252) if is_accent else (148, 163, 184), font=font_kpi_lbl, anchor="lm")
        draw.text((kx + 16, kpi_y + 58), val_txt, fill=(248, 250, 252), font=font_kpi_val, anchor="lm")

    # Chart Card
    chart_y = kpi_y + kpi_h + 20
    draw.rounded_rectangle(
        [(padding, chart_y), (padding + inner_w, chart_y + chart_card_h)],
        radius=16,
        fill=(19, 28, 46),
        outline=(42, 55, 82),
        width=1,
    )

    eras = [
        ("1960s & earlier", "#f59e0b"),
        ("1970s", "#ec4899"),
        ("1980s", "#a855f7"),
        ("1990s", "#3b82f6"),
        ("2000s", "#06b6d4"),
        ("2010s", "#10b981"),
        ("2020s", "#6366f1"),
    ]
    lx = padding + 24
    ly = chart_y + 28
    for era_lbl, era_hex in eras:
        draw.ellipse([(lx, ly - 5), (lx + 10, ly + 5)], fill=_hex_to_rgb(era_hex))
        lx += 16
        draw.text((lx, ly), era_lbl, fill=(203, 213, 225), font=font_legend, anchor="lm")
        lx += int(draw.textlength(era_lbl, font=font_legend)) + 22

    # Unbinned bars area
    plot_x = padding + 24
    plot_w = inner_w - 48
    bar_top = chart_y + 104
    bar_bottom = chart_y + chart_card_h - 62
    bar_area_h = bar_bottom - bar_top
    n_bars = len(display_years)
    col_step = plot_w / float(max(1, n_bars))
    bar_w = max(4, min(26, int(col_step * 0.72)))
    max_val = max((y["minutes_listened"] if is_min else y["play_count"]) for y in display_years) or 1.0
    dense_labels = n_bars > 76

    for idx, yr in enumerate(display_years):
        val = yr["minutes_listened"] if is_min else yr["play_count"]
        cx = int(plot_x + (idx + 0.5) * col_step)
        bx0 = cx - bar_w // 2
        bx1 = bx0 + bar_w
        era_rgb = _hex_to_rgb(_era_color_hex(yr["year"]))

        # Subtle background bar track
        draw.rounded_rectangle([(bx0, bar_top), (bx1, bar_bottom)], radius=min(3, bar_w // 2), fill=(25, 36, 58))
        if val > 0:
            ratio = val / max_val
            fill_h = max(6, int(bar_area_h * ratio))
            by0 = bar_bottom - fill_h
            draw.rounded_rectangle([(bx0, by0), (bx1, bar_bottom)], radius=min(3, bar_w // 2), fill=era_rgb)
            if not dense_labels or val >= max_val * 0.12 or yr["year"] == summary.get("peak_year"):
                v_txt = f"{yr['minutes_listened']:,.0f}m" if is_min else f"{yr['play_count']}"
                _paste_rotated_text(canvas, v_txt, font_bar_val, (203, 213, 225), cx, by0 - 4, angle=90.0)

        show_yr_lbl = (
            (not dense_labels)
            or (yr["year"] % 5 == 0)
            or (idx == 0)
            or (idx == n_bars - 1)
        )
        if show_yr_lbl:
            if mode == "active" and not dense_labels:
                _paste_rotated_text(canvas, str(yr["year"]), font_bar_yr, (148, 163, 184), cx, bar_bottom + 42, angle=90.0)
            else:
                draw.text((cx, bar_bottom + 14), str(yr["year"]), fill=(148, 163, 184), font=font_bar_yr, anchor="mm")

    # Top Release Years Highlights Card
    hi_y = chart_y + chart_card_h + 22
    draw.rounded_rectangle(
        [(padding, hi_y), (padding + inner_w, hi_y + highlights_h)],
        radius=16,
        fill=(19, 28, 46),
        outline=(42, 55, 82),
        width=1,
    )
    draw.text((padding + 24, hi_y + 22), "Top Release Years & Signature Albums", fill=(248, 250, 252), font=font_h3)

    with ThreadPoolExecutor(max_workers=8) as ex:
        def _load_yr_cov(yr_entry):
            top_albs = yr_entry.get("top_albums") or []
            if not top_albs:
                return _round_image(get_placeholder_cover(58, str(yr_entry["year"]), "Release Year", yr_entry["year"]), radius=8)
            alb = top_albs[0]
            return _round_image(
                load_album_image(
                    {
                        "cover_local_path": alb.get("cover_local_path"),
                        "release_name": alb.get("release_name", ""),
                        "artist_name": alb.get("artist_name", ""),
                        "rank": yr_entry["year"],
                    },
                    58,
                ),
                radius=8,
            )

        yr_covers = list(ex.map(_load_yr_cov, top_years))

    card_gap = 16
    card_w = (inner_w - 48 - card_gap) // 2
    card_h = 76
    for idx, yr in enumerate(top_years):
        col = idx % 2
        row = idx // 2
        cx = padding + 24 + col * (card_w + card_gap)
        cy = hi_y + 62 + row * 88
        draw.rounded_rectangle([(cx, cy), (cx + card_w, cy + card_h)], radius=10, fill=(15, 23, 42))

        era_rgb = _hex_to_rgb(_era_color_hex(yr["year"]))
        draw.rounded_rectangle([(cx + 12, cy + 16), (cx + 76, cy + 60)], radius=8, fill=era_rgb)
        draw.text((cx + 44, cy + 38), str(yr["year"]), fill=(10, 14, 24), font=font_card_title, anchor="mm")

        canvas.paste(yr_covers[idx], (cx + 88, cy + 9), yr_covers[idx])

        top_alb = (yr.get("top_albums") or [{}])[0]
        alb_line = (
            f"{top_alb.get('release_name', 'Various')} — {top_alb.get('artist_name', '')}"
            if top_alb else f"{yr['album_count']} albums"
        )
        stat_line = (
            f"{yr['minutes_listened']:,.0f}m ({yr['hours_listened']:.1f}h) • {yr['play_count']} plays • {yr['share_pct']}% share"
        )
        tx = cx + 160
        max_tw = (cx + card_w - 16) - tx
        draw.text((tx, cy + 25), _truncate_text(draw, alb_line, font_card_title, max_tw), fill=(248, 250, 252), font=font_card_title, anchor="lm")
        draw.text((tx, cy + 51), _truncate_text(draw, stat_line, font_card_sub, max_tw), fill=(148, 163, 184), font=font_card_sub, anchor="lm")

    if formats is not None:
        return save_canvas_formats(canvas, output_path, formats, quality=92)
    save_canvas_image(canvas, output_path, quality=92)
    return output_path


def export_all_visuals(
    timeframe: Optional[str] = None,
    metric: str = "minutes",
    formats: Optional[Sequence[str]] = None,
    show_flags: bool = False,
    show_pie: bool = False,
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
    m_out = generate_world_map_image(
        metric=metric,
        timeframe=timeframe,
        output_path=os.path.join(STATIC_DIR, "world_map"),
        show_pie=show_pie,
        show_flags=show_flags,
        formats=fmt_list,
        db_path=db_path,
    )
    y_out = generate_release_years_image(
        metric=metric,
        timeframe=timeframe,
        output_path=os.path.join(STATIC_DIR, "release_years"),
        formats=fmt_list,
        db_path=db_path,
    )
    return {
        "collage": c_out or [],
        "artists": a_out or [],
        "songs": s_out or [],
        "map": m_out or [],
        "years": y_out or [],
    }


export_all_webp_visuals = export_all_visuals

if __name__ == "__main__":
    print(export_all_visuals(formats=["webp"]))
