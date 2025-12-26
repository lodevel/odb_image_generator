"""Image cropping utilities with padding support."""

from typing import Tuple

from PIL import Image

from ..rendering.context import RenderContext


class Cropper:
    """Handles cropping component images with proper centering."""

    def __init__(self, ctx: RenderContext, window_mm: float, output_size: int):
        self.ctx = ctx
        self.window_mm = window_mm
        self.output_size = output_size

    def crop_centered(
        self,
        face_img: Image.Image,
        x_mm: float,
        y_mm: float,
    ) -> Image.Image:
        """Crop a region centered on (x_mm, y_mm) with black padding if needed.
        
        Args:
            face_img: Full board face image
            x_mm: Component center X in mm
            y_mm: Component center Y in mm
            
        Returns:
            Cropped and resized image at output_size × output_size
        """
        # Calculate crop box in mm
        half = self.window_mm / 2.0
        box_mm = (x_mm - half, y_mm - half, x_mm + half, y_mm + half)

        # Convert to pixels (unclamped)
        crop_px = self._mm_box_to_px(box_mm, face_img)

        # Extract with padding
        cropped = self._extract_with_padding(face_img, crop_px)

        # Resize to output size
        return cropped.resize(
            (self.output_size, self.output_size),
            resample=Image.Resampling.LANCZOS
        )

    def _mm_box_to_px(
        self,
        box_mm: Tuple[float, float, float, float],
        img: Image.Image,
    ) -> Tuple[int, int, int, int]:
        """Convert mm box to pixel coordinates without clamping."""
        xmin, ymin, xmax, ymax = box_mm

        x1 = int(round((xmin - self.ctx.xmin) / self.ctx.width_mm * (img.width - 1)))
        x2 = int(round((xmax - self.ctx.xmin) / self.ctx.width_mm * (img.width - 1)))
        y1 = int(round((self.ctx.ymax - ymax) / self.ctx.height_mm * (img.height - 1)))
        y2 = int(round((self.ctx.ymax - ymin) / self.ctx.height_mm * (img.height - 1)))

        x1, x2 = sorted([x1, x2])
        y1, y2 = sorted([y1, y2])

        return (x1, y1, x2, y2)

    def _extract_with_padding(
        self,
        face_img: Image.Image,
        crop_px: Tuple[int, int, int, int],
    ) -> Image.Image:
        """Extract crop with black padding for out-of-bounds areas.
        
        This ensures the component stays centered even when near board edges.
        """
        x1, y1, x2, y2 = crop_px
        crop_w = x2 - x1
        crop_h = y2 - y1

        # Create black canvas
        result = Image.new("RGBA", (crop_w, crop_h), (0, 0, 0, 255))

        # Calculate valid region within source image
        src_x1 = max(0, x1)
        src_y1 = max(0, y1)
        src_x2 = min(face_img.width, x2)
        src_y2 = min(face_img.height, y2)

        # Calculate paste position in result
        dst_x1 = src_x1 - x1
        dst_y1 = src_y1 - y1

        # Paste valid region
        if src_x2 > src_x1 and src_y2 > src_y1:
            region = face_img.crop((src_x1, src_y1, src_x2, src_y2))
            result.paste(region, (dst_x1, dst_y1))

        return result
