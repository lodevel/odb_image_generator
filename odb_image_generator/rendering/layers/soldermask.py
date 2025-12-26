"""Soldermask layer rendering with alpha cutouts."""

import math
from typing import List, Tuple

from PIL import Image, ImageDraw

from ...models import Board, LayerData
from ..context import RenderContext
from .base import Layer


class SoldermaskLayer(Layer):
    """Renders soldermask with openings cut out via alpha channel."""

    def __init__(
        self,
        mask_color: Tuple[int, int, int, int] = (20, 60, 30, 255),
        mask_alpha: int = 220,
    ):
        self.mask_color = mask_color
        self.mask_alpha = mask_alpha

    def render(
        self,
        ctx: RenderContext,
        data: LayerData,
        outline_pts: List[Tuple[float, float]] = None,
    ) -> Image.Image:
        """Render soldermask layer with openings.
        
        Args:
            ctx: Render context
            data: Soldermask layer data (features define openings)
            outline_pts: Board outline for mask boundary
        """
        # Create alpha channel (L mode)
        alpha = Image.new("L", (ctx.render_size, ctx.render_size), 0)
        da = ImageDraw.Draw(alpha)

        # Draw board area with mask alpha
        if outline_pts and len(outline_pts) >= 3:
            board_poly = [ctx.mm_to_px(x, y) for x, y in outline_pts]
            da.polygon(board_poly, fill=self.mask_alpha)

        # Cut out openings by drawing alpha=0
        for kind, feature_data in data.features:
            if kind == "P":
                x, y, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                cx, cy = ctx.mm_to_px(x, y)
                self._cut_symbol(da, ctx, cx, cy, symbol)

            elif kind == "L":
                x1, y1, x2, y2, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                self._cut_line(da, ctx, x1, y1, x2, y2, symbol)

            elif kind == "A":
                x1, y1, x2, y2, xc, yc, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                self._cut_arc(da, ctx, x1, y1, x2, y2, xc, yc, symbol)

            elif kind == "POLY":
                poly_kind, pts = feature_data
                if poly_kind == "I":  # Island
                    pts_px = [ctx.mm_to_px(x, y) for x, y in pts]
                    if len(pts_px) >= 3:
                        da.polygon(pts_px, fill=0)

        # Create final mask image
        mask_img = Image.new("RGBA", (ctx.render_size, ctx.render_size), self.mask_color)
        mask_img.putalpha(alpha)
        return mask_img

    def _cut_symbol(self, da: ImageDraw.ImageDraw, ctx: RenderContext, cx: int, cy: int, symbol) -> None:
        """Cut out a symbol shape from the mask."""
        if symbol.kind == "circle" and symbol.params:
            r_px = ctx.symbol_radius_px(symbol.params[0])
            da.ellipse((cx - r_px, cy - r_px, cx + r_px, cy + r_px), fill=0)

        elif symbol.kind == "rect" and len(symbol.params) == 2:
            hw, hh = ctx.symbol_half_size_px(symbol.params[0], symbol.params[1])
            da.rectangle((cx - hw, cy - hh, cx + hw, cy + hh), fill=0)

        elif symbol.kind == "oval" and len(symbol.params) == 2:
            hw, hh = ctx.symbol_half_size_px(symbol.params[0], symbol.params[1])
            da.ellipse((cx - hw, cy - hh, cx + hw, cy + hh), fill=0)

        else:
            da.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=0)

    def _cut_line(self, da: ImageDraw.ImageDraw, ctx: RenderContext,
                  x1: float, y1: float, x2: float, y2: float, symbol) -> None:
        """Cut out a line from the mask."""
        p1 = ctx.mm_to_px(x1, y1)
        p2 = ctx.mm_to_px(x2, y2)

        thickness = 1
        if symbol.kind == "circle" and symbol.params:
            thickness = ctx.mm_to_px_length_x(symbol.params[0])

        da.line([p1, p2], fill=0, width=thickness)

    def _cut_arc(self, da: ImageDraw.ImageDraw, ctx: RenderContext,
                 x1: float, y1: float, x2: float, y2: float,
                 xc: float, yc: float, symbol) -> None:
        """Cut out an arc from the mask."""
        r = math.hypot(x1 - xc, y1 - yc)
        if r < 1e-9:
            return

        a1 = math.atan2(y1 - yc, x1 - xc)
        a2 = math.atan2(y2 - yc, x2 - xc)

        da_angle = a2 - a1
        while da_angle <= -math.pi:
            da_angle += 2 * math.pi
        while da_angle > math.pi:
            da_angle -= 2 * math.pi

        steps = max(12, int(abs(da_angle) / (math.pi / 24)))
        pts = []
        for i in range(steps + 1):
            t = i / steps
            a = a1 + da_angle * t
            x = xc + r * math.cos(a)
            y = yc + r * math.sin(a)
            pts.append(ctx.mm_to_px(x, y))

        thickness = 1
        if symbol.kind == "circle" and symbol.params:
            thickness = ctx.mm_to_px_length_x(symbol.params[0])

        if len(pts) >= 2:
            da.line(pts, fill=0, width=thickness)
