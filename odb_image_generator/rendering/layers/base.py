"""Abstract base class for renderable layers."""

from abc import ABC, abstractmethod
from typing import Any

from PIL import Image

from ..context import RenderContext


class Layer(ABC):
    """Abstract base class for PCB layers.
    
    Each layer knows how to render itself to an RGBA image.
    """

    @abstractmethod
    def render(self, ctx: RenderContext, data: Any) -> Image.Image:
        """Render this layer to an RGBA image.
        
        Args:
            ctx: Render context with coordinate transformations
            data: Layer-specific data (LayerData, Board, etc.)
            
        Returns:
            RGBA PIL Image with this layer's content
        """
        pass
