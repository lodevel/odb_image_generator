"""Render context for coordinate transformations."""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class RenderContext:
    """Shared rendering state for coordinate transformations.
    
    Encapsulates board bounding box and render size to provide
    consistent mm-to-pixel conversions across all rendering operations.
    """
    board_bbox_mm: Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
    render_size: int

    @property
    def xmin(self) -> float:
        return self.board_bbox_mm[0]

    @property
    def ymin(self) -> float:
        return self.board_bbox_mm[1]

    @property
    def xmax(self) -> float:
        return self.board_bbox_mm[2]

    @property
    def ymax(self) -> float:
        return self.board_bbox_mm[3]

    @property
    def width_mm(self) -> float:
        return self.xmax - self.xmin

    @property
    def height_mm(self) -> float:
        return self.ymax - self.ymin

    def mm_to_px_x(self, x_mm: float) -> int:
        """Convert X coordinate from mm to pixels."""
        return int(round((x_mm - self.xmin) / self.width_mm * (self.render_size - 1)))

    def mm_to_px_y(self, y_mm: float) -> int:
        """Convert Y coordinate from mm to pixels (Y-axis flipped)."""
        return int(round((self.ymax - y_mm) / self.height_mm * (self.render_size - 1)))

    def mm_to_px(self, x_mm: float, y_mm: float) -> Tuple[int, int]:
        """Convert (x, y) from mm to pixels."""
        return (self.mm_to_px_x(x_mm), self.mm_to_px_y(y_mm))

    def mm_to_px_length_x(self, length_mm: float) -> int:
        """Convert a horizontal length from mm to pixels."""
        return max(1, int(round(length_mm / self.width_mm * self.render_size)))

    def mm_to_px_length_y(self, length_mm: float) -> int:
        """Convert a vertical length from mm to pixels."""
        return max(1, int(round(length_mm / self.height_mm * self.render_size)))

    def symbol_radius_px(self, diameter_mm: float) -> int:
        """Convert symbol diameter to pixel radius."""
        return max(1, int(round((diameter_mm / 2.0) / self.width_mm * self.render_size)))

    def symbol_half_size_px(self, w_mm: float, h_mm: float) -> Tuple[float, float]:
        """Convert symbol dimensions to pixel half-width and half-height."""
        hw = (w_mm / 2.0) / self.width_mm * self.render_size
        hh = (h_mm / 2.0) / self.height_mm * self.render_size
        return (hw, hh)
