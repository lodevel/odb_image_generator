"""Board cutout layer: holes through the whole board inside its outline."""

from typing import Tuple

from PIL import Image, ImageDraw

from ...models import Board
from ..context import RenderContext
from .base import Layer


class CutoutLayer(Layer):
    """Punches the board's cutouts through every layer below it.

    Composite it last: there is no board material in a cutout, so neither
    copper, mask nor silkscreen shows there. A cutout looks like the space
    around the board (background colour, outlined like the board edge)."""

    def __init__(
        self,
        background_color: Tuple[int, int, int, int] = (0, 0, 0, 255),
        outline_color: Tuple[int, int, int, int] = (70, 70, 70, 255),
        outline_width: int = 2,
    ):
        self.background_color = background_color
        self.outline_color = outline_color
        self.outline_width = outline_width

    def render(self, ctx: RenderContext, data: Board) -> Image.Image:
        img = Image.new("RGBA", (ctx.render_size, ctx.render_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img, "RGBA")
        for pts in data.cutouts:
            if len(pts) < 3:
                continue
            poly = [ctx.mm_to_px(x, y) for x, y in pts]
            draw.polygon(poly, fill=self.background_color)
            draw.line(poly + [poly[0]], fill=self.outline_color,
                      width=self.outline_width)
        return img
