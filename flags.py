"""Crisp vector (SVG) and raster (Pillow RGBA) country flag generator.

Provides self-contained, dependency-free SVG flags for web rendering and
PyMuPDF-rasterized RGBA flag icons for collage/table image generation so
country flags render reliably across Linux, macOS, Windows, and mobile
without relying on system emoji fonts.
"""

from __future__ import annotations

import functools
import math
import os
from typing import Dict, Optional

from PIL import Image, ImageDraw

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover - optional fallback
    pymupdf = None  # type: ignore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FLAGS_DIR = os.path.join(BASE_DIR, "static", "flags")


def _svg_wrap(inner: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 18" '
        'width="24" height="18" shape-rendering="geometricPrecision">'
        f"{inner}"
        '<rect x="0.25" y="0.25" width="23.5" height="17.5" fill="none" '
        'stroke="rgba(255,255,255,0.22)" stroke-width="0.5"/>'
        "</svg>"
    )


def _h_tricolor(c1: str, c2: str, c3: str) -> str:
    return (
        f'<rect width="24" height="6" y="0" fill="{c1}"/>'
        f'<rect width="24" height="6" y="6" fill="{c2}"/>'
        f'<rect width="24" height="6" y="12" fill="{c3}"/>'
    )


def _v_tricolor(c1: str, c2: str, c3: str) -> str:
    return (
        f'<rect width="8" height="18" x="0" fill="{c1}"/>'
        f'<rect width="8" height="18" x="8" fill="{c2}"/>'
        f'<rect width="8" height="18" x="16" fill="{c3}"/>'
    )


def _bicolor_h(c1: str, c2: str) -> str:
    return (
        f'<rect width="24" height="9" y="0" fill="{c1}"/>'
        f'<rect width="24" height="9" y="9" fill="{c2}"/>'
    )


def _nordic_cross(bg: str, cross: str, inner_cross: Optional[str] = None) -> str:
    parts = [
        f'<rect width="24" height="18" fill="{bg}"/>',
        f'<rect x="6.5" y="0" width="4" height="18" fill="{cross}"/>',
        f'<rect x="0" y="7" width="24" height="4" fill="{cross}"/>',
    ]
    if inner_cross:
        parts.extend([
            f'<rect x="7.5" y="0" width="2" height="18" fill="{inner_cross}"/>',
            f'<rect x="0" y="8" width="24" height="2" fill="{inner_cross}"/>',
        ])
    return "".join(parts)


def _star_points(cx: float, cy: float, r_outer: float, r_inner: float, n: int = 5) -> str:
    pts = []
    for i in range(n * 2):
        ang = -math.pi / 2 + i * math.pi / n
        r = r_outer if i % 2 == 0 else r_inner
        pts.append(f"{cx + r * math.cos(ang):.2f},{cy + r * math.sin(ang):.2f}")
    return " ".join(pts)


def _us_flag() -> str:
    stripes = []
    h = 18.0 / 13.0
    for i in range(13):
        col = "#B22234" if i % 2 == 0 else "#FFFFFF"
        stripes.append(f'<rect x="0" y="{i*h:.3f}" width="24" height="{h+0.05:.3f}" fill="{col}"/>')
    canton = '<rect x="0" y="0" width="10.2" height="9.7" fill="#3C3B6E"/>'
    stars = []
    for r in range(5):
        for c in range(6):
            if r % 2 == 1 and c == 5:
                continue
            sx = 0.95 + c * 1.65 + (0.82 if r % 2 == 1 else 0)
            sy = 1.05 + r * 1.85
            stars.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.48" fill="#FFFFFF"/>')
    return "".join(stripes) + canton + "".join(stars)


def _gb_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#012169"/>'
        '<path d="M0,0 L24,18 M24,0 L0,18" stroke="#FFFFFF" stroke-width="3.6"/>'
        '<path d="M0,0 L24,18 M24,0 L0,18" stroke="#C8102E" stroke-width="1.8"/>'
        '<path d="M12,0 V18 M0,9 H24" stroke="#FFFFFF" stroke-width="5.2"/>'
        '<path d="M12,0 V18 M0,9 H24" stroke="#C8102E" stroke-width="3.0"/>'
    )


def _au_or_nz(is_nz: bool) -> str:
    canton = (
        '<g transform="scale(0.5)">'
        + _gb_flag()
        + "</g>"
    )
    stars = [
        '<rect width="24" height="18" fill="#00008B"/>',
        canton,
    ]
    star_color = "#CC142B" if is_nz else "#FFFFFF"
    stroke_attr = ' stroke="#FFFFFF" stroke-width="0.45"' if is_nz else ""
    coords = [(18.0, 4.0, 1.3), (15.0, 8.2, 1.1), (20.8, 7.6, 1.1), (18.0, 14.0, 1.4)]
    if not is_nz:
        coords.append((6.0, 13.5, 1.9))
    for x, y, r in coords:
        stars.append(f'<polygon points="{_star_points(x, y, r, r*0.42)}" fill="{star_color}"{stroke_attr}/>')
    return "".join(stars)


def _ca_flag() -> str:
    leaf = (
        '<path d="M12,3.4 L12.8,5.8 L14.7,5.2 L14.0,7.5 L16.2,7.1 L15.4,8.6 '
        'L16.6,9.5 L14.2,10.9 L14.5,12.1 L12.5,11.7 L12.5,14.6 L11.5,14.6 '
        'L11.5,11.7 L9.5,12.1 L9.8,10.9 L7.4,9.5 L8.6,8.6 L7.8,7.1 L10.0,7.5 '
        'L9.3,5.2 L11.2,5.8 Z" fill="#D80621"/>'
    )
    return (
        '<rect width="24" height="18" fill="#FFFFFF"/>'
        '<rect x="0" y="0" width="6" height="18" fill="#D80621"/>'
        '<rect x="18" y="0" width="6" height="18" fill="#D80621"/>'
        + leaf
    )


def _br_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#009C3B"/>'
        '<polygon points="12,2.2 21.6,9 12,15.8 2.4,9" fill="#FFDF00"/>'
        '<circle cx="12" cy="9" r="3.9" fill="#002776"/>'
        '<path d="M8.3,8.2 Q12,6.8 15.7,9.5" fill="none" stroke="#FFFFFF" stroke-width="0.85"/>'
    )


def _za_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#002395"/>'
        '<rect width="24" height="9" fill="#DE3831"/>'
        '<polygon points="0,0 10.5,7 24,7 24,11 10.5,11 0,18" fill="#FFFFFF"/>'
        '<polygon points="0,1.2 9.8,7.6 24,7.6 24,10.4 9.8,10.4 0,16.8" fill="#007A4D"/>'
        '<polygon points="0,2.8 7.5,9 0,15.2" fill="#FFB612"/>'
        '<polygon points="0,4.2 5.8,9 0,13.8" fill="#000000"/>'
    )


def _il_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#FFFFFF"/>'
        '<rect y="2" width="24" height="2.6" fill="#0038B8"/>'
        '<rect y="13.4" width="24" height="2.6" fill="#0038B8"/>'
        '<polygon points="12,5.3 15.2,10.9 8.8,10.9" fill="none" stroke="#0038B8" stroke-width="0.95"/>'
        '<polygon points="12,12.7 15.2,7.1 8.8,7.1" fill="none" stroke="#0038B8" stroke-width="0.95"/>'
    )


def _in_flag() -> str:
    return (
        _h_tricolor("#FF9933", "#FFFFFF", "#138808")
        + '<circle cx="12" cy="9" r="2.2" fill="none" stroke="#000080" stroke-width="0.7"/>'
        + '<circle cx="12" cy="9" r="0.45" fill="#000080"/>'
    )


def _kr_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#FFFFFF"/>'
        '<circle cx="12" cy="9" r="3.8" fill="#CD2E3A"/>'
        '<path d="M8.2,9 A3.8,3.8 0 0,0 15.8,9 A1.9,1.9 0 0,0 12,9 A1.9,1.9 0 0,1 8.2,9 Z" fill="#0047A0"/>'
        '<g stroke="#000000" stroke-width="0.95">'
        '<line x1="4.4" y1="5.0" x2="6.6" y2="2.8"/><line x1="5.3" y1="5.9" x2="7.5" y2="3.7"/>'
        '<line x1="17.4" y1="2.8" x2="19.6" y2="5.0"/><line x1="16.5" y1="3.7" x2="18.7" y2="5.9"/>'
        '<line x1="4.4" y1="13.0" x2="6.6" y2="15.2"/><line x1="5.3" y1="12.1" x2="7.5" y2="14.3"/>'
        '<line x1="17.4" y1="15.2" x2="19.6" y2="13.0"/><line x1="16.5" y1="14.3" x2="18.7" y2="12.1"/>'
        "</g>"
    )


def _gr_flag() -> str:
    stripes = []
    for i in range(9):
        col = "#0D5EAF" if i % 2 == 0 else "#FFFFFF"
        stripes.append(f'<rect x="0" y="{i*2}" width="24" height="2" fill="{col}"/>')
    canton = (
        '<rect x="0" y="0" width="10" height="10" fill="#0D5EAF"/>'
        '<rect x="4" y="0" width="2" height="10" fill="#FFFFFF"/>'
        '<rect x="0" y="4" width="10" height="2" fill="#FFFFFF"/>'
    )
    return "".join(stripes) + canton


def _ch_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#D52B1E"/>'
        '<rect x="10.2" y="3.5" width="3.6" height="11" fill="#FFFFFF"/>'
        '<rect x="6.5" y="7.2" width="11" height="3.6" fill="#FFFFFF"/>'
    )


def _es_flag() -> str:
    return (
        '<rect width="24" height="4.5" y="0" fill="#AA151B"/>'
        '<rect width="24" height="9" y="4.5" fill="#F1BF00"/>'
        '<rect width="24" height="4.5" y="13.5" fill="#AA151B"/>'
        '<rect x="5.5" y="6.6" width="2.8" height="4.2" rx="0.8" fill="#AA151B" stroke="#855800" stroke-width="0.4"/>'
    )


def _pt_flag() -> str:
    return (
        '<rect width="9.5" height="18" x="0" fill="#006600"/>'
        '<rect width="14.5" height="18" x="9.5" fill="#FF0000"/>'
        '<circle cx="9.5" cy="9" r="3.1" fill="#FFCC00" stroke="#996600" stroke-width="0.4"/>'
        '<rect x="8.2" y="7.4" width="2.6" height="3.2" rx="0.7" fill="#FFFFFF" stroke="#B00000" stroke-width="0.5"/>'
    )


def _jm_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#009B3A"/>'
        '<polygon points="0,0 10.5,9 0,18" fill="#000000"/>'
        '<polygon points="24,0 13.5,9 24,18" fill="#000000"/>'
        '<path d="M0,0 L24,18 M24,0 L0,18" stroke="#FED100" stroke-width="2.4"/>'
    )


def _cu_flag() -> str:
    stripes = []
    h = 18.0 / 5.0
    for i in range(5):
        col = "#002A8F" if i % 2 == 0 else "#FFFFFF"
        stripes.append(f'<rect x="0" y="{i*h:.2f}" width="24" height="{h+0.05:.2f}" fill="{col}"/>')
    tri = '<polygon points="0,0 11.5,9 0,18" fill="#CF142B"/>'
    star = f'<polygon points="{_star_points(4.2, 9.0, 2.2, 0.9)}" fill="#FFFFFF"/>'
    return "".join(stripes) + tri + star


def _cl_flag() -> str:
    return (
        '<rect width="24" height="9" y="0" fill="#FFFFFF"/>'
        '<rect width="24" height="9" y="9" fill="#D52B1E"/>'
        '<rect width="9" height="9" x="0" y="0" fill="#0039A6"/>'
        f'<polygon points="{_star_points(4.5, 4.5, 2.3, 0.9)}" fill="#FFFFFF"/>'
    )


def _cz_flag() -> str:
    return (
        '<rect width="24" height="9" y="0" fill="#FFFFFF"/>'
        '<rect width="24" height="9" y="9" fill="#D7141A"/>'
        '<polygon points="0,0 11.5,9 0,18" fill="#11457E"/>'
    )


def _tr_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#E30A17"/>'
        '<circle cx="9.2" cy="9" r="4.1" fill="#FFFFFF"/>'
        '<circle cx="10.4" cy="9" r="3.3" fill="#E30A17"/>'
        f'<polygon points="{_star_points(14.5, 9.0, 2.0, 0.8)}" fill="#FFFFFF"/>'
    )


def _cn_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#DE2910"/>'
        f'<polygon points="{_star_points(4.8, 4.8, 2.2, 0.85)}" fill="#FFDE00"/>'
        f'<polygon points="{_star_points(8.6, 2.4, 0.75, 0.3)}" fill="#FFDE00"/>'
        f'<polygon points="{_star_points(9.8, 4.2, 0.75, 0.3)}" fill="#FFDE00"/>'
        f'<polygon points="{_star_points(9.6, 6.4, 0.75, 0.3)}" fill="#FFDE00"/>'
        f'<polygon points="{_star_points(8.2, 7.8, 0.75, 0.3)}" fill="#FFDE00"/>'
    )


def _tw_flag() -> str:
    return (
        '<rect width="24" height="18" fill="#FE0000"/>'
        '<rect width="12" height="9" fill="#000095"/>'
        '<circle cx="6" cy="4.5" r="2.2" fill="#FFFFFF"/>'
    )


def _globe_svg() -> str:
    return (
        '<rect width="24" height="18" fill="#1E293B"/>'
        '<circle cx="12" cy="9" r="5.6" fill="none" stroke="#60A5FA" stroke-width="1.1"/>'
        '<ellipse cx="12" cy="9" rx="2.7" ry="5.6" fill="none" stroke="#60A5FA" stroke-width="0.9"/>'
        '<line x1="6.4" y1="9" x2="17.6" y2="9" stroke="#60A5FA" stroke-width="0.9"/>'
    )


def _flag_bodies() -> Dict[str, str]:
    return {
        "US": _us_flag(),
        "GB": _gb_flag(),
        "UK": _gb_flag(),
        "CA": _ca_flag(),
        "AU": _au_or_nz(False),
        "NZ": _au_or_nz(True),
        "DE": _h_tricolor("#000000", "#DD0000", "#FFCE00"),
        "AT": _h_tricolor("#ED2939", "#FFFFFF", "#ED2939"),
        "FR": _v_tricolor("#002395", "#FFFFFF", "#ED2939"),
        "IT": _v_tricolor("#009246", "#FFFFFF", "#CE2B37"),
        "IE": _v_tricolor("#169B62", "#FFFFFF", "#FF883E"),
        "BE": _v_tricolor("#000000", "#FAE042", "#ED2939"),
        "RO": _v_tricolor("#002B7F", "#FCD116", "#CE1126"),
        "NG": _v_tricolor("#008751", "#FFFFFF", "#008751"),
        "ML": _v_tricolor("#14B53A", "#FCD116", "#CE1126"),
        "NL": _h_tricolor("#AE1C28", "#FFFFFF", "#21468B"),
        "LU": _h_tricolor("#ED2939", "#FFFFFF", "#00A1DE"),
        "RU": _h_tricolor("#FFFFFF", "#0039A6", "#D52B1E"),
        "HU": _h_tricolor("#CD2A3E", "#FFFFFF", "#436F4D"),
        "BG": _h_tricolor("#FFFFFF", "#00966E", "#D62612"),
        "EE": _h_tricolor("#0072CE", "#000000", "#FFFFFF"),
        "LT": _h_tricolor("#FDB913", "#006A44", "#C1272D"),
        "LV": '<rect width="24" height="18" fill="#9E3039"/><rect y="7" width="24" height="4" fill="#FFFFFF"/>',
        "PL": _bicolor_h("#FFFFFF", "#DC143C"),
        "ID": _bicolor_h("#FF0000", "#FFFFFF"),
        "UA": _bicolor_h("#0057B7", "#FFD700"),
        "SE": _nordic_cross("#006AA7", "#FECC00"),
        "FI": _nordic_cross("#FFFFFF", "#003580"),
        "DK": _nordic_cross("#C60C30", "#FFFFFF"),
        "NO": _nordic_cross("#BA0C2F", "#FFFFFF", "#00205B"),
        "IS": _nordic_cross("#02529C", "#FFFFFF", "#DC1E35"),
        "CH": _ch_flag(),
        "ES": _es_flag(),
        "PT": _pt_flag(),
        "GR": _gr_flag(),
        "BR": _br_flag(),
        "ZA": _za_flag(),
        "JP": '<rect width="24" height="18" fill="#FFFFFF"/><circle cx="12" cy="9" r="4.8" fill="#BC002D"/>',
        "KR": _kr_flag(),
        "IN": _in_flag(),
        "IL": _il_flag(),
        "AR": (
            _h_tricolor("#74ACDF", "#FFFFFF", "#74ACDF")
            + '<circle cx="12" cy="9" r="2.0" fill="#F6B40E"/>'
        ),
        "MX": (
            _v_tricolor("#006847", "#FFFFFF", "#CE1126")
            + '<circle cx="12" cy="9" r="1.7" fill="#8B5A2B"/>'
        ),
        "CO": (
            '<rect width="24" height="9" y="0" fill="#FCD116"/>'
            '<rect width="24" height="4.5" y="9" fill="#003893"/>'
            '<rect width="24" height="4.5" y="13.5" fill="#CE1126"/>'
        ),
        "CL": _cl_flag(),
        "PE": _v_tricolor("#D91023", "#FFFFFF", "#D91023"),
        "CU": _cu_flag(),
        "JM": _jm_flag(),
        "CZ": _cz_flag(),
        "SK": (
            _h_tricolor("#FFFFFF", "#0B4EA2", "#EE1C25")
            + '<rect x="5" y="5.5" width="3.5" height="5" rx="1.2" fill="#EE1C25" stroke="#FFFFFF" stroke-width="0.6"/>'
        ),
        "HR": (
            _h_tricolor("#FF0000", "#FFFFFF", "#171796")
            + '<rect x="10.2" y="6.2" width="3.6" height="4.6" rx="0.8" fill="#FF0000" stroke="#FFFFFF" stroke-width="0.5"/>'
        ),
        "RS": (
            _h_tricolor("#C6363C", "#0C4076", "#FFFFFF")
            + '<rect x="6" y="5.8" width="3.2" height="4.5" rx="0.8" fill="#FFFFFF" stroke="#C6363C" stroke-width="0.5"/>'
        ),
        "SI": (
            _h_tricolor("#FFFFFF", "#003DA5", "#ED1C24")
            + '<rect x="5.2" y="4.8" width="3.0" height="3.6" rx="0.8" fill="#003DA5" stroke="#FFFFFF" stroke-width="0.4"/>'
        ),
        "TR": _tr_flag(),
        "CN": _cn_flag(),
        "TW": _tw_flag(),
        "VN": f'<rect width="24" height="18" fill="#DA251D"/><polygon points="{_star_points(12, 9, 4.3, 1.7)}" fill="#FFFF00"/>',
        "TH": (
            '<rect width="24" height="3" y="0" fill="#A51931"/>'
            '<rect width="24" height="3" y="3" fill="#FFFFFF"/>'
            '<rect width="24" height="6" y="6" fill="#2D2A4A"/>'
            '<rect width="24" height="3" y="12" fill="#FFFFFF"/>'
            '<rect width="24" height="3" y="15" fill="#A51931"/>'
        ),
        "MY": (
            _h_tricolor("#CC0001", "#FFFFFF", "#CC0001")
            + '<rect width="12" height="10" fill="#010066"/>'
            + '<circle cx="5.2" cy="5" r="2.6" fill="#FFCC00"/>'
            + '<circle cx="6.1" cy="5" r="2.1" fill="#010066"/>'
        ),
        "PH": (
            '<rect width="24" height="9" y="0" fill="#0038A8"/>'
            '<rect width="24" height="9" y="9" fill="#CE1126"/>'
            '<polygon points="0,0 10.5,9 0,18" fill="#FFFFFF"/>'
            '<circle cx="3.8" cy="9" r="1.7" fill="#FCD116"/>'
        ),
        "PK": (
            '<rect width="6" height="18" fill="#FFFFFF"/>'
            '<rect x="6" width="18" height="18" fill="#01411C"/>'
            '<circle cx="15.2" cy="9" r="3.8" fill="#FFFFFF"/>'
            '<circle cx="16.4" cy="8.2" r="3.2" fill="#01411C"/>'
        ),
        "EG": (
            _h_tricolor("#CE1126", "#FFFFFF", "#000000")
            + '<circle cx="12" cy="9" r="1.4" fill="#C09300"/>'
        ),
        "MA": '<rect width="24" height="18" fill="#C1272D"/><circle cx="12" cy="9" r="2.8" fill="none" stroke="#006233" stroke-width="0.9"/>',
        "DZ": (
            '<rect width="12" height="18" fill="#006233"/>'
            '<rect x="12" width="12" height="18" fill="#FFFFFF"/>'
            '<circle cx="12.5" cy="9" r="3.5" fill="#D21034"/>'
            '<circle cx="13.6" cy="9" r="2.8" fill="#FFFFFF"/>'
        ),
        "XX": _globe_svg(),
    }


FLAG_BODIES = _flag_bodies()


def normalize_country_code(code: Optional[str]) -> str:
    if not code:
        return "XX"
    c = str(code).strip().upper()
    if c == "UK":
        return "GB"
    if c == "CN-TW":
        return "TW"
    if len(c) != 2 or not c.isalpha():
        return "XX"
    return c


def build_flag_svg(code: Optional[str]) -> str:
    c = normalize_country_code(code)
    body = FLAG_BODIES.get(c)
    if body is None:
        # Clean deterministic fallback badge for any ISO code not in FLAG_BODIES
        h = sum(ord(ch) * (i + 17) for i, ch in enumerate(c)) % 360
        body = (
            f'<rect width="24" height="18" fill="hsl({h}, 52%, 34%)"/>'
            f'<text x="12" y="12.5" text-anchor="middle" font-family="sans-serif" '
            f'font-size="9" font-weight="700" fill="#F8FAFC">{c}</text>'
        )
    return _svg_wrap(body)


def ensure_flag_assets(codes: Optional[list[str]] = None) -> int:
    """Write SVG flag files to static/flags/ and return count written."""
    os.makedirs(FLAGS_DIR, exist_ok=True)
    target_codes = set(FLAG_BODIES.keys()) | {"XX"}
    if codes:
        target_codes |= {normalize_country_code(c) for c in codes if c}
    written = 0
    for code in sorted(target_codes):
        out_path = os.path.join(FLAGS_DIR, f"{code.lower()}.svg")
        svg = build_flag_svg(code)
        if not os.path.exists(out_path):
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(svg)
            written += 1
        else:
            # Refresh if content changed
            with open(out_path, "r", encoding="utf-8") as f:
                old = f.read()
            if old != svg:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(svg)
                written += 1
    return written


@functools.lru_cache(maxsize=512)
def get_flag_rgba(code: Optional[str], width: int = 24, height: int = 18) -> Image.Image:
    """Return a crisp RGBA Pillow Image of the country flag at (width, height)."""
    c = normalize_country_code(code)
    svg_str = build_flag_svg(c)

    if pymupdf is not None:
        try:
            doc = pymupdf.open(stream=svg_str.encode("utf-8"), filetype="svg")
            page = doc[0]
            rect = page.rect
            sx = width / max(rect.width, 1.0)
            sy = height / max(rect.height, 1.0)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(sx, sy), alpha=True)
            img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
            if img.size != (width, height):
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            mask = Image.new("L", (width, height), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (width - 1, height - 1)], radius=max(2, width // 10), fill=255)
            out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            out.paste(img, (0, 0), mask)
            return out
        except Exception:
            pass

    # Pure Pillow fallback if PyMuPDF is unavailable
    img = Image.new("RGBA", (width, height), (30, 41, 59, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (width - 1, height - 1)], radius=2, fill=(51, 65, 85, 255), outline=(148, 163, 184, 180))
    draw.text((width // 2, height // 2), c, fill=(248, 250, 252, 255), anchor="mm")
    return img


if __name__ == "__main__":
    count = ensure_flag_assets()
    print(f"Ensured {len(FLAG_BODIES)} built-in flag SVGs in {FLAGS_DIR} ({count} written/updated).")
