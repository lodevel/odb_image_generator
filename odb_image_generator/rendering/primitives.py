"""Drawing primitives for ODB++ features."""

import math
from typing import Dict, List, Tuple

from PIL import ImageDraw, ImageFont

from ..models import Symbol
from .context import RenderContext


def draw_flash(
    draw: ImageDraw.ImageDraw,
    ctx: RenderContext,
    x_mm: float,
    y_mm: float,
    symbol: Symbol,
    fill_rgba: Tuple[int, int, int, int],
    outline: bool = False,
    outline_width: int = 2,
) -> None:
    """Draw a pad/flash at the given position using the symbol shape."""
    cx, cy = ctx.mm_to_px(x_mm, y_mm)

    if symbol.kind == "circle" and symbol.params:
        d_mm = symbol.params[0]
        r_px = ctx.symbol_radius_px(d_mm)
        box = (cx - r_px, cy - r_px, cx + r_px, cy + r_px)
        if outline:
            draw.ellipse(box, outline=fill_rgba, width=outline_width)
        else:
            draw.ellipse(box, fill=fill_rgba, outline=fill_rgba)

    elif symbol.kind == "rect" and len(symbol.params) == 2:
        w_mm, h_mm = symbol.params
        hw, hh = ctx.symbol_half_size_px(w_mm, h_mm)
        box = (cx - hw, cy - hh, cx + hw, cy + hh)
        if outline:
            draw.rectangle(box, outline=fill_rgba, width=outline_width)
        else:
            draw.rectangle(box, fill=fill_rgba, outline=fill_rgba)

    elif symbol.kind == "oval" and len(symbol.params) == 2:
        w_mm, h_mm = symbol.params
        hw, hh = ctx.symbol_half_size_px(w_mm, h_mm)
        box = (cx - hw, cy - hh, cx + hw, cy + hh)
        if outline:
            draw.ellipse(box, outline=fill_rgba, width=outline_width)
        else:
            draw.ellipse(box, fill=fill_rgba, outline=fill_rgba)

    else:
        # Unknown symbol: draw tiny dot
        draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=fill_rgba, outline=fill_rgba)


def draw_line(
    draw: ImageDraw.ImageDraw,
    ctx: RenderContext,
    x1: float, y1: float,
    x2: float, y2: float,
    symbol: Symbol,
    fill_rgba: Tuple[int, int, int, int],
) -> None:
    """Draw a line with symbol-defined thickness."""
    p1 = ctx.mm_to_px(x1, y1)
    p2 = ctx.mm_to_px(x2, y2)
    
    thickness = 1
    if symbol.kind == "circle" and symbol.params:
        thickness = ctx.mm_to_px_length_x(symbol.params[0])
    
    draw.line([p1, p2], fill=fill_rgba, width=thickness)


def draw_arc(
    draw: ImageDraw.ImageDraw,
    ctx: RenderContext,
    x1: float, y1: float,
    x2: float, y2: float,
    xc: float, yc: float,
    symbol: Symbol,
    fill_rgba: Tuple[int, int, int, int],
) -> None:
    """Draw an arc as a series of line segments."""
    r = math.hypot(x1 - xc, y1 - yc)
    if r < 1e-9:
        return

    a1 = math.atan2(y1 - yc, x1 - xc)
    a2 = math.atan2(y2 - yc, x2 - xc)

    da = a2 - a1
    while da <= -math.pi:
        da += 2 * math.pi
    while da > math.pi:
        da -= 2 * math.pi

    steps = max(12, int(abs(da) / (math.pi / 24)))
    pts = []
    for i in range(steps + 1):
        t = i / steps
        a = a1 + da * t
        x = xc + r * math.cos(a)
        y = yc + r * math.sin(a)
        pts.append(ctx.mm_to_px(x, y))

    thickness = 1
    if symbol.kind == "circle" and symbol.params:
        thickness = ctx.mm_to_px_length_x(symbol.params[0])

    draw.line(pts, fill=fill_rgba, width=thickness)


def draw_polygon(
    draw: ImageDraw.ImageDraw,
    ctx: RenderContext,
    pts_mm: List[Tuple[float, float]],
    fill_rgba: Tuple[int, int, int, int] = None,
    outline_rgba: Tuple[int, int, int, int] = None,
    width: int = 2,
) -> None:
    """Draw a polygon, optionally filled and/or outlined."""
    pts_px = [ctx.mm_to_px(x, y) for x, y in pts_mm]
    if len(pts_px) < 3:
        return

    if fill_rgba is not None:
        draw.polygon(pts_px, fill=fill_rgba)
    if outline_rgba is not None:
        draw.line(pts_px + [pts_px[0]], fill=outline_rgba, width=width)


def draw_text(
    draw: ImageDraw.ImageDraw,
    ctx: RenderContext,
    x_mm: float,
    y_mm: float,
    text_str: str,
    fill_rgba: Tuple[int, int, int, int],
    font_size_px: int = 12,
) -> None:
    """Draw text at the given position."""
    px, py = ctx.mm_to_px(x_mm, y_mm)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size_px)
    except Exception:
        font = ImageFont.load_default()

    draw.text((px, py), text_str, fill=fill_rgba, font=font)
