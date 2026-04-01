"""Render context for coordinate transformations.

Uses a **uniform** scale (pixels-per-mm identical in X and Y) so that
circles render as circles regardless of board aspect ratio.  The board
is centred within the square render canvas; any extra space is padding.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class RenderContext:
    """Shared rendering state for coordinate transformations.

    Encapsulates board bounding box and render size to provide
    consistent mm-to-pixel conversions across all rendering operations.
    A single uniform scale is used for both axes so that geometry is
    never distorted.
    """
    board_bbox_mm: Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
    render_size: int

    # ── raw board extents ──

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

    # ── uniform scale helpers ──

    @property
    def span_mm(self) -> float:
        """The larger of width / height (uniform scale reference)."""
        return max(self.width_mm, self.height_mm) or 1.0

    @property
    def _virt_xmin(self) -> float:
        """Virtual X origin — centres the board horizontally in the canvas."""
        return self.xmin - (self.span_mm - self.width_mm) / 2.0

    @property
    def _virt_ymax(self) -> float:
        """Virtual Y origin (top) — centres the board vertically in the canvas."""
        return self.ymax + (self.span_mm - self.height_mm) / 2.0

    # ── coordinate conversions (uniform scale) ──

    def mm_to_px_x(self, x_mm: float) -> int:
        """Convert X coordinate from mm to pixels."""
        return int(round((x_mm - self._virt_xmin) / self.span_mm * (self.render_size - 1)))

    def mm_to_px_y(self, y_mm: float) -> int:
        """Convert Y coordinate from mm to pixels (Y-axis flipped)."""
        return int(round((self._virt_ymax - y_mm) / self.span_mm * (self.render_size - 1)))

    def mm_to_px(self, x_mm: float, y_mm: float) -> Tuple[int, int]:
        """Convert (x, y) from mm to pixels."""
        return (self.mm_to_px_x(x_mm), self.mm_to_px_y(y_mm))

    # ── length conversions (uniform scale) ──

    def mm_to_px_length(self, length_mm: float) -> int:
        """Convert a length from mm to pixels."""
        return max(1, int(round(length_mm / self.span_mm * self.render_size)))

    def mm_to_px_length_x(self, length_mm: float) -> int:
        """Convert a horizontal length from mm to pixels."""
        return self.mm_to_px_length(length_mm)

    def mm_to_px_length_y(self, length_mm: float) -> int:
        """Convert a vertical length from mm to pixels."""
        return self.mm_to_px_length(length_mm)

    def symbol_radius_px(self, diameter_mm: float) -> int:
        """Convert symbol diameter to pixel radius."""
        return max(1, int(round((diameter_mm / 2.0) / self.span_mm * self.render_size)))

    def symbol_half_size_px(self, w_mm: float, h_mm: float) -> Tuple[float, float]:
        """Convert symbol dimensions to pixel half-width and half-height."""
        scale = self.render_size / self.span_mm
        hw = (w_mm / 2.0) * scale
        hh = (h_mm / 2.0) * scale
        return (hw, hh)
