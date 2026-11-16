"""High-resolution, mobile-readable collage & Wrapped leaderboard graphic generator.

Supports parallel tile composition, cached typography/masks, inline vector-rasterized
country flags next to artist names, gapless tiered/uniform grid presets, Top-3 podium +
proportional bar chart posters, and single-render multi-format export (WebP, AVIF, JPG, JXL).
"""

from __future__ import annotations

import functools
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple

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

# Gapless Tiered Bento counts:
# 3 (1x3 hero), 7 (3 + 1x4 med), 11 (3 + 2x4 med), then +5 compact per row:
# 16, 21, 26, 31, 36, 41, 46, 51, 56, 61, 66, 71, 76, 81, 86, 91, 96, 101
GAPLESS_TIERED_COUNTS = (3, 7, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56, 61, 66, 71, 76, 81, 86, 91, 96, 101)


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
    show_flags: bool = True,
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
    1: ((245, 158, 11), (251, 191, 36), (17, 24, 39)),   # Gold
    2: ((148, 163, 184), (226, 232, 240), (15, 23, 42)), # Silver
    3: ((217, 119, 6), (251, 146, 60), (15, 23, 42)),    # Bronze
}


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
    """Render Wrapped Top Artists poster with Top-3 Podium cards and proportional metric bars."""
    artists = get_top_artists(
        limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not artists:
        return None

    is_min = metric == "minutes"
    max_val = max((a["minutes_listened"] if is_min else a["play_count"]) for a in artists) or 1.0

    canvas_w = 1200
    padding = 30
    header_h = 104
    podium_items = artists[: min(3, len(artists))]
    rest_items = artists[len(podium_items) :]
    podium_h = 252 if podium_items else 0
    podium_gap = 20 if rest_items else 0
    row_h = 62
    canvas_h = header_h + padding + podium_h + podium_gap + len(rest_items) * row_h + padding

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(9, 13, 22))
    draw = ImageDraw.Draw(canvas)

    font_tag = get_font(FONT_BOLD, 13)
    font_title = get_font(FONT_BOLD, 34)
    font_sub = get_font(FONT_REGULAR, 16)
    font_podium_rank = get_font(FONT_BOLD, 15)
    font_podium_name = get_font(FONT_BOLD, 20)
    font_podium_val = get_font(FONT_BOLD, 24)
    font_podium_sub = get_font(FONT_MEDIUM, 14)
    font_rank = get_font(FONT_BOLD, 16)
    font_name = get_font(FONT_BOLD, 19)
    font_val = get_font(FONT_BOLD, 18)
    font_sub_row = get_font(FONT_MEDIUM, 14)

    # Header
    draw.rounded_rectangle([(padding, padding), (padding + 188, padding + 24)], radius=4, fill=(29, 78, 216))
    draw.text((padding + 94, padding + 12), "MUSICBRAINZ WRAPPED", fill=(255, 255, 255), font=font_tag, anchor="mm")
    draw.text((padding, padding + 32), f"TOP {len(artists)} ARTISTS", fill=(248, 250, 252), font=font_title)
    metric_label = "Listen Time" if is_min else "No. of Listens"
    time_label = f"Timeframe: {timeframe.title() if timeframe else 'All Time'}"
    draw.text(
        (padding, padding + 74),
        f"Ranked by {metric_label}  •  {time_label}  •  Unofficial",
        fill=(148, 163, 184),
        font=font_sub,
    )

    with ThreadPoolExecutor(max_workers=8) as ex:
        podium_avatars = list(ex.map(lambda a: _round_image(load_artist_image(a, 86)), podium_items))
        row_avatars = list(ex.map(lambda a: _round_image(load_artist_image(a, 42)), rest_items))

    # Top 3 Podium Cards
    inner_w = canvas_w - padding * 2
    card_gap = 16
    card_w = (inner_w - card_gap * (len(podium_items) - 1)) // max(1, len(podium_items))
    podium_y = header_h + padding

    for idx, art in enumerate(podium_items):
        cx = padding + idx * (card_w + card_gap)
        rank = art["rank"]
        accent, tip, card_bg = PODIUM_STYLES.get(rank, ((59, 130, 246), (56, 189, 248), (17, 24, 39)))

        draw.rounded_rectangle(
            [(cx, podium_y), (cx + card_w, podium_y + podium_h)],
            radius=14,
            fill=card_bg,
            outline=(148, 163, 184, 55),
            width=1,
        )
        # Top accent highlight bar
        draw.rounded_rectangle([(cx + 18, podium_y + 1), (cx + card_w - 18, podium_y + 5)], radius=2, fill=accent)

        # Rank pill
        draw.rounded_rectangle([(cx + 16, podium_y + 18), (cx + 62, podium_y + 44)], radius=6, fill=accent)
        draw.text((cx + 39, podium_y + 31), f"#{rank}", fill=(10, 14, 24), font=font_podium_rank, anchor="mm")

        # Avatar
        av = podium_avatars[idx]
        canvas.paste(av, (cx + card_w // 2 - 43, podium_y + 20), av)

        # Artist name + inline flag centered
        cc = art.get("country_code")
        has_flag = show_flags and bool(cc) and cc != "XX"
        flag_w, flag_h = 26, 19
        flag_gap = 8 if has_flag else 0
        max_nw = card_w - 36 - flag_w - flag_gap
        name_txt = _truncate_text(draw, art["artist_name"], font_podium_name, max_nw)
        name_w = int(draw.textlength(name_txt, font=font_podium_name))
        total_nw = name_w + flag_gap + (flag_w if has_flag else 0)
        nx = cx + (card_w - total_nw) // 2
        ny = podium_y + 128
        draw.text((nx, ny), name_txt, fill=(248, 250, 252), font=font_podium_name, anchor="lm")
        if has_flag:
            fimg = get_flag_rgba(cc, flag_w, flag_h)
            canvas.paste(fimg, (nx + name_w + flag_gap, ny - flag_h // 2), fimg)

        # Primary + secondary stats
        val = art["minutes_listened"] if is_min else art["play_count"]
        ratio = val / max_val
        hrs = art["hours_listened"]
        mins = art["minutes_listened"]
        primary_txt = f"{hrs:.1f} hrs ({mins:,.0f}m)" if is_min else f"{art['play_count']:,} listens"
        secondary_txt = f"{art['play_count']:,} listens  •  {int(round(ratio * 100))}% of #1" if is_min else f"{hrs:.1f} hrs ({mins:,.0f}m)  •  {int(round(ratio * 100))}% of #1"

        draw.text((cx + card_w // 2, podium_y + 168), primary_txt, fill=tip, font=font_podium_val, anchor="mm")
        draw.text((cx + card_w // 2, podium_y + 196), secondary_txt, fill=(148, 163, 184), font=font_podium_sub, anchor="mm")

        # Visual proportional metric bar inside podium card
        _draw_metric_bar(canvas, draw, cx + 22, podium_y + 218, card_w - 44, 14, ratio, accent_rgb=accent, tip_rgb=tip)

    # Ranked Visual Bar Chart Rows (#4+)
    list_y = podium_y + podium_h + podium_gap
    for idx, art in enumerate(rest_items):
        ry = list_y + idx * row_h
        if idx % 2 == 0:
            draw.rounded_rectangle([(padding, ry + 2), (padding + inner_w, ry + row_h - 2)], radius=8, fill=(16, 23, 39))

        rank = art["rank"]
        draw.rounded_rectangle([(padding + 12, ry + 15), (padding + 56, ry + 47)], radius=6, fill=(30, 41, 59))
        draw.text((padding + 34, ry + 31), f"#{rank}", fill=(203, 213, 225), font=font_rank, anchor="mm")

        canvas.paste(row_avatars[idx], (padding + 68, ry + 10), row_avatars[idx])

        # Visual metric bar on right
        bar_x = padding + 590
        bar_w = 320
        val = art["minutes_listened"] if is_min else art["play_count"]
        ratio = val / max_val
        _draw_metric_bar(canvas, draw, bar_x, ry + 23, bar_w, 16, ratio)

        # Metric text right of bar
        hrs = art["hours_listened"]
        mins = art["minutes_listened"]
        primary_txt = f"{mins:,.0f}m ({hrs:.1f}h)" if is_min else f"{art['play_count']:,} plays"
        secondary_txt = f"{art['play_count']:,}p" if is_min else f"{mins:,.0f}m"
        draw.text((padding + inner_w - 86, ry + 31), primary_txt, fill=(125, 211, 252), font=font_val, anchor="rm")
        draw.text((padding + inner_w - 16, ry + 31), secondary_txt, fill=(148, 163, 184), font=font_sub_row, anchor="rm")

        # Artist name + inline country flag
        name_x = padding + 124
        cc = art.get("country_code")
        has_flag = show_flags and bool(cc) and cc != "XX"
        flag_w, flag_h = 24, 18
        flag_gap = 9 if has_flag else 0
        max_nw = (bar_x - 20) - name_x - (flag_w + flag_gap if has_flag else 0)
        name_txt = _truncate_text(draw, art["artist_name"], font_name, max_nw)
        draw.text((name_x, ry + 31), name_txt, fill=(248, 250, 252), font=font_name, anchor="lm")
        if has_flag:
            fimg = get_flag_rgba(cc, flag_w, flag_h)
            nw = int(draw.textlength(name_txt, font=font_name))
            canvas.paste(fimg, (name_x + nw + flag_gap, ry + 31 - flag_h // 2), fimg)

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
    """Render Wrapped Top Songs poster with Top-3 Podium cards and proportional metric bars."""
    tracks = get_top_tracks(
        limit=limit, metric=metric, timeframe=timeframe, start_ts=start_ts, end_ts=end_ts, db_path=db_path
    )
    if not tracks:
        return None

    is_min = metric == "minutes"
    max_val = max((t["minutes_listened"] if is_min else t["play_count"]) for t in tracks) or 1.0

    canvas_w = 1200
    padding = 30
    header_h = 104
    podium_items = tracks[: min(3, len(tracks))]
    rest_items = tracks[len(podium_items) :]
    podium_h = 264 if podium_items else 0
    podium_gap = 20 if rest_items else 0
    row_h = 66
    canvas_h = header_h + padding + podium_h + podium_gap + len(rest_items) * row_h + padding

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(9, 13, 22))
    draw = ImageDraw.Draw(canvas)

    font_tag = get_font(FONT_BOLD, 13)
    font_title = get_font(FONT_BOLD, 34)
    font_sub = get_font(FONT_REGULAR, 16)
    font_podium_rank = get_font(FONT_BOLD, 15)
    font_podium_song = get_font(FONT_BOLD, 19)
    font_podium_art = get_font(FONT_MEDIUM, 14)
    font_podium_val = get_font(FONT_BOLD, 23)
    font_podium_sub = get_font(FONT_MEDIUM, 13)
    font_rank = get_font(FONT_BOLD, 16)
    font_song = get_font(FONT_BOLD, 18)
    font_artist = get_font(FONT_MEDIUM, 14)
    font_val = get_font(FONT_BOLD, 18)
    font_sub_row = get_font(FONT_MEDIUM, 13)

    draw.rounded_rectangle([(padding, padding), (padding + 188, padding + 24)], radius=4, fill=(29, 78, 216))
    draw.text((padding + 94, padding + 12), "MUSICBRAINZ WRAPPED", fill=(255, 255, 255), font=font_tag, anchor="mm")
    draw.text((padding, padding + 32), f"TOP {len(tracks)} SONGS", fill=(248, 250, 252), font=font_title)
    metric_label = "Listen Time" if is_min else "No. of Listens"
    time_label = f"Timeframe: {timeframe.title() if timeframe else 'All Time'}"
    draw.text(
        (padding, padding + 74),
        f"Ranked by {metric_label}  •  {time_label}  •  Unofficial",
        fill=(148, 163, 184),
        font=font_sub,
    )

    def _load_cov(t, sz):
        return _round_image(
            load_album_image(
                {
                    "cover_local_path": t.get("album_cover_local_path"),
                    "release_name": t.get("release_name"),
                    "artist_name": t.get("artist_name"),
                    "rank": t["rank"],
                },
                sz,
            ),
            radius=8,
        )

    with ThreadPoolExecutor(max_workers=8) as ex:
        podium_covs = list(ex.map(lambda t: _load_cov(t, 84), podium_items))
        row_covs = list(ex.map(lambda t: _load_cov(t, 44), rest_items))

    # Top 3 Podium Cards
    inner_w = canvas_w - padding * 2
    card_gap = 16
    card_w = (inner_w - card_gap * (len(podium_items) - 1)) // max(1, len(podium_items))
    podium_y = header_h + padding

    for idx, t in enumerate(podium_items):
        cx = padding + idx * (card_w + card_gap)
        rank = t["rank"]
        accent, tip, card_bg = PODIUM_STYLES.get(rank, ((59, 130, 246), (56, 189, 248), (17, 24, 39)))

        draw.rounded_rectangle(
            [(cx, podium_y), (cx + card_w, podium_y + podium_h)],
            radius=14,
            fill=card_bg,
            outline=(148, 163, 184, 55),
            width=1,
        )
        draw.rounded_rectangle([(cx + 18, podium_y + 1), (cx + card_w - 18, podium_y + 5)], radius=2, fill=accent)
        draw.rounded_rectangle([(cx + 16, podium_y + 18), (cx + 62, podium_y + 44)], radius=6, fill=accent)
        draw.text((cx + 39, podium_y + 31), f"#{rank}", fill=(10, 14, 24), font=font_podium_rank, anchor="mm")

        canvas.paste(podium_covs[idx], (cx + card_w // 2 - 42, podium_y + 18), podium_covs[idx])

        song_txt = _truncate_text(draw, t["track_name"], font_podium_song, card_w - 32)
        draw.text((cx + card_w // 2, podium_y + 122), song_txt, fill=(248, 250, 252), font=font_podium_song, anchor="mm")

        cc = t.get("country_code")
        has_flag = show_flags and bool(cc) and cc != "XX"
        flag_w, flag_h = 20, 15
        flag_gap = 7 if has_flag else 0
        art_txt = _truncate_text(draw, t["artist_name"], font_podium_art, card_w - 40 - flag_w - flag_gap)
        art_w = int(draw.textlength(art_txt, font=font_podium_art))
        tot_aw = art_w + flag_gap + (flag_w if has_flag else 0)
        ax = cx + (card_w - tot_aw) // 2
        ay = podium_y + 146
        draw.text((ax, ay), art_txt, fill=(203, 213, 225), font=font_podium_art, anchor="lm")
        if has_flag:
            fimg = get_flag_rgba(cc, flag_w, flag_h)
            canvas.paste(fimg, (ax + art_w + flag_gap, ay - flag_h // 2), fimg)

        val = t["minutes_listened"] if is_min else t["play_count"]
        ratio = val / max_val
        dur = t.get("duration_formatted") or "3:30"
        primary_txt = f"{t['minutes_listened']:,.0f} mins" if is_min else f"{t['play_count']:,} listens"
        secondary_txt = f"{dur} × {t['play_count']} listens  •  {int(round(ratio * 100))}% of #1"

        draw.text((cx + card_w // 2, podium_y + 182), primary_txt, fill=tip, font=font_podium_val, anchor="mm")
        draw.text((cx + card_w // 2, podium_y + 208), secondary_txt, fill=(148, 163, 184), font=font_podium_sub, anchor="mm")
        _draw_metric_bar(canvas, draw, cx + 22, podium_y + 230, card_w - 44, 14, ratio, accent_rgb=accent, tip_rgb=tip)

    # Ranked Visual Bar Chart Rows (#4+)
    list_y = podium_y + podium_h + podium_gap
    for idx, t in enumerate(rest_items):
        ry = list_y + idx * row_h
        if idx % 2 == 0:
            draw.rounded_rectangle([(padding, ry + 2), (padding + inner_w, ry + row_h - 2)], radius=8, fill=(16, 23, 39))

        rank = t["rank"]
        draw.rounded_rectangle([(padding + 12, ry + 17), (padding + 56, ry + 49)], radius=6, fill=(30, 41, 59))
        draw.text((padding + 34, ry + 33), f"#{rank}", fill=(203, 213, 225), font=font_rank, anchor="mm")
        canvas.paste(row_covs[idx], (padding + 68, ry + 11), row_covs[idx])

        bar_x = padding + 590
        bar_w = 320
        val = t["minutes_listened"] if is_min else t["play_count"]
        ratio = val / max_val
        _draw_metric_bar(canvas, draw, bar_x, ry + 25, bar_w, 16, ratio, accent_rgb=(99, 102, 241), tip_rgb=(56, 189, 248))

        dur = t.get("duration_formatted") or "3:30"
        primary_txt = f"{t['minutes_listened']:,.0f}m" if is_min else f"{t['play_count']} plays"
        secondary_txt = f"{dur} × {t['play_count']}p" if is_min else f"{t['minutes_listened']:,.0f}m ({dur})"
        draw.text((padding + inner_w - 110, ry + 33), primary_txt, fill=(125, 211, 252), font=font_val, anchor="rm")
        draw.text((padding + inner_w - 16, ry + 33), secondary_txt, fill=(148, 163, 184), font=font_sub_row, anchor="rm")

        text_x = padding + 124
        max_w = (bar_x - 20) - text_x
        song_txt = _truncate_text(draw, t["track_name"], font_song, max_w)
        draw.text((text_x, ry + 21), song_txt, fill=(248, 250, 252), font=font_song, anchor="lm")

        cc = t.get("country_code")
        has_flag = show_flags and bool(cc) and cc != "XX"
        flag_w, flag_h = 20, 15
        art_txt = _truncate_text(draw, t["artist_name"], font_artist, int(max_w * 0.56))
        draw.text((text_x, ry + 45), art_txt, fill=(203, 213, 225), font=font_artist, anchor="lm")
        cur_x = text_x + int(draw.textlength(art_txt, font=font_artist))
        if has_flag:
            fimg = get_flag_rgba(cc, flag_w, flag_h)
            cur_x += 7
            canvas.paste(fimg, (cur_x, ry + 45 - flag_h // 2), fimg)
            cur_x += flag_w
        rem_w = (bar_x - 20) - cur_x
        if rem_w > 30:
            rel_txt = _truncate_text(draw, f"  •  {t['release_name']}", font_artist, rem_w)
            draw.text((cur_x, ry + 45), rel_txt, fill=(148, 163, 184), font=font_artist, anchor="lm")

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
