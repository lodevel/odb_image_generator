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

        Works directly at output_size to avoid creating huge intermediate
        images when the crop window is much larger than the rendered board.

        Args:
            face_img: Full board face image
            x_mm: Component center X in mm
            y_mm: Component center Y in mm

        Returns:
            Cropped and resized image at output_size x output_size
        """
        half = self.window_mm / 2.0
        box_mm = (x_mm - half, y_mm - half, x_mm + half, y_mm + half)

        # Crop box in render pixels (may extend far outside the image)
        xmin, ymin, xmax, ymax = box_mm
        rx1 = self.ctx.mm_to_px_x(xmin)
        rx2 = self.ctx.mm_to_px_x(xmax)
        ry1 = self.ctx.mm_to_px_y(ymax)
        ry2 = self.ctx.mm_to_px_y(ymin)
        rx1, rx2 = sorted([rx1, rx2])
        ry1, ry2 = sorted([ry1, ry2])

        crop_w = rx2 - rx1 or 1
        crop_h = ry2 - ry1 or 1
        out = self.output_size

        # Scale factor from crop-pixel space to output-pixel space
        sx = out / crop_w
        sy = out / crop_h

        # Start with black canvas at output size (always small)
        result = Image.new("RGBA", (out, out), (0, 0, 0, 255))

        # Intersect crop region with the actual source image
        src_x1 = max(0, rx1)
        src_y1 = max(0, ry1)
        src_x2 = min(face_img.width, rx2)
        src_y2 = min(face_img.height, ry2)

        if src_x2 > src_x1 and src_y2 > src_y1:
            region = face_img.crop((src_x1, src_y1, src_x2, src_y2))

            # Where this region lands on the output canvas
            dst_x1 = int(round((src_x1 - rx1) * sx))
            dst_y1 = int(round((src_y1 - ry1) * sy))
            dst_w = int(round((src_x2 - src_x1) * sx)) or 1
            dst_h = int(round((src_y2 - src_y1) * sy)) or 1

            region = region.resize((dst_w, dst_h), resample=Image.Resampling.LANCZOS)
            result.paste(region, (dst_x1, dst_y1))

        return result
