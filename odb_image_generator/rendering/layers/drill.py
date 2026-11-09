"""Drill/hole layer rendering.

Draws drill holes as dark circles that punch through copper and soldermask,
representing plated-through-holes and vias.
"""

from typing import Tuple

from PIL import Image, ImageDraw

from ...models import LayerData
from ..context import RenderContext
from ..primitives import draw_flash
from .base import Layer


class DrillLayer(Layer):
    """Renders drill holes as opaque circles (subtractive)."""

    def __init__(self, color: Tuple[int, int, int, int] = (15, 15, 15, 255)):
        self.color = color

    def render(self, ctx: RenderContext, data: LayerData) -> Image.Image:
        """Render all drill features as filled circles."""
        img = Image.new("RGBA", (ctx.render_size, ctx.render_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img, "RGBA")

        for kind, feature_data in data.features:
            if kind == "P":
                x, y, sym_id = feature_data
                symbol = data.get_symbol(sym_id)
                draw_flash(draw, ctx, x, y, symbol, self.color, outline=False)

        return img
