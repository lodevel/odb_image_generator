"""Board background layer."""

from typing import List, Tuple

from PIL import Image, ImageDraw

from ...models import Board
from ..context import RenderContext
from .base import Layer


class BoardLayer(Layer):
    """Renders board background and outline."""

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
        """Render board background and outline."""
        img = Image.new("RGBA", (ctx.render_size, ctx.render_size), self.background_color)
        draw = ImageDraw.Draw(img, "RGBA")

        # Draw board polygon (filled with background)
        if len(data.outline_pts) >= 3:
            poly = [ctx.mm_to_px(x, y) for x, y in data.outline_pts]
            draw.polygon(poly, fill=self.background_color)

            # Draw outline
            draw.line(poly + [poly[0]], fill=self.outline_color, width=self.outline_width)

        return img
