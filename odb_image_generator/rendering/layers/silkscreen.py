"""Silkscreen layer rendering (outlines only to avoid covering pads)."""

from typing import Tuple

from PIL import Image, ImageDraw

from ...models import LayerData
from ..context import RenderContext
from ..primitives import draw_flash, draw_line, draw_arc, draw_polygon, draw_text
from .base import Layer


class SilkscreenLayer(Layer):
    """Renders silkscreen features as outlines to avoid covering pads."""

    def __init__(self, color: Tuple[int, int, int, int] = (245, 245, 245, 220)):
        self.color = color

    def render(self, ctx: RenderContext, data: LayerData) -> Image.Image:
        """Render silkscreen features (outlines only for P/POLY)."""
        img = Image.new("RGBA", (ctx.render_size, ctx.render_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img, "RGBA")

        for kind, feature_data in data.features:
            if kind == "L":
                x1, y1, x2, y2, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                draw_line(draw, ctx, x1, y1, x2, y2, symbol, self.color)

            elif kind == "A":
                x1, y1, x2, y2, xc, yc, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                draw_arc(draw, ctx, x1, y1, x2, y2, xc, yc, symbol, self.color)

            elif kind == "P":
                # Draw as outline to avoid covering pads
                x, y, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                draw_flash(draw, ctx, x, y, symbol, self.color, outline=True, outline_width=2)

            elif kind == "POLY":
                poly_kind, pts = feature_data
                if poly_kind == "I":
                    # Draw as outline only
                    draw_polygon(draw, ctx, pts, outline_rgba=self.color, width=2)

            elif kind == "TEXT":
                x, y, text_str = feature_data
                font_size = max(8, int(round(0.8 / ctx.width_mm * ctx.render_size)))
                draw_text(draw, ctx, x, y, text_str, self.color, font_size)

        return img
