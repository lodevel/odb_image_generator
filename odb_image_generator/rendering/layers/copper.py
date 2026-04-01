"""Copper layer rendering."""

from typing import Tuple

from PIL import Image, ImageDraw

from ...models import LayerData
from ..context import RenderContext
from ..primitives import draw_flash, draw_line, draw_arc, draw_polygon
from .base import Layer


class CopperLayer(Layer):
    """Renders copper features (pads, traces, pours)."""

    def __init__(self, color: Tuple[int, int, int, int] = (220, 170, 40, 255)):
        self.color = color

    def render(self, ctx: RenderContext, data: LayerData) -> Image.Image:
        """Render all copper features."""
        img = Image.new("RGBA", (ctx.render_size, ctx.render_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img, "RGBA")

        for kind, feature_data in data.features:
            if kind == "P":
                x, y, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                draw_flash(draw, ctx, x, y, symbol, self.color, outline=False)

            elif kind == "L":
                x1, y1, x2, y2, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                draw_line(draw, ctx, x1, y1, x2, y2, symbol, self.color)

            elif kind == "A":
                x1, y1, x2, y2, xc, yc, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                draw_arc(draw, ctx, x1, y1, x2, y2, xc, yc, symbol, self.color)

            elif kind == "POLY":
                poly_kind, pts = feature_data
                if poly_kind == "I":  # Island (filled)
                    draw_polygon(draw, ctx, pts, fill_rgba=self.color)

        return img
