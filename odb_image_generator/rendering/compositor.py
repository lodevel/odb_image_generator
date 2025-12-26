"""Layer compositor for combining multiple layers."""

from typing import List, Tuple, Any

from PIL import Image

from .context import RenderContext
from .layers.base import Layer


class Compositor:
    """Composites multiple layers into a single image."""

    def __init__(self, ctx: RenderContext):
        self.ctx = ctx
        self._layers: List[Tuple[Layer, Any, dict]] = []

    def add(self, layer: Layer, data: Any, **kwargs) -> "Compositor":
        """Add a layer to the composition.
        
        Args:
            layer: Layer instance to render
            data: Data to pass to layer.render()
            **kwargs: Additional keyword arguments for layer.render()
            
        Returns:
            self for chaining
        """
        self._layers.append((layer, data, kwargs))
        return self

    def render(self) -> Image.Image:
        """Render all layers and composite them.
        
        Returns:
            Final composited RGBA image
        """
        result = Image.new("RGBA", (self.ctx.render_size, self.ctx.render_size), (0, 0, 0, 255))

        for layer, data, kwargs in self._layers:
            layer_img = layer.render(self.ctx, data, **kwargs)
            result = Image.alpha_composite(result, layer_img)

        return result

    def clear(self) -> None:
        """Clear all layers."""
        self._layers.clear()
