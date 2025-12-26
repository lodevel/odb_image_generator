"""Annotation overlays for component images."""

from typing import Tuple

from PIL import Image, ImageDraw, ImageFont


def draw_cross_center(
    img: Image.Image,
    side: str,
    window_mm: float,
    top_color: Tuple[int, int, int, int] = (255, 0, 0, 255),
    bottom_color: Tuple[int, int, int, int] = (0, 140, 255, 255),
    arm_mm: float = 1.5,
    thickness_px: int = 3,
) -> None:
    """Draw a cross marker at the center of the image.
    
    Args:
        img: Image to draw on (modified in place)
        side: "TOP" or "BOTTOM"
        window_mm: Crop window size in mm (for scale calculation)
        top_color: Cross color for TOP side
        bottom_color: Cross color for BOTTOM side
        arm_mm: Cross arm length in mm (half of total)
        thickness_px: Line thickness in pixels
    """
    px_per_mm = img.width / window_mm
    arm_px = int(round(arm_mm * px_per_mm))

    cx = img.width // 2
    cy = img.height // 2

    color = top_color if side == "TOP" else bottom_color

    draw = ImageDraw.Draw(img, "RGBA")
    draw.line([(cx - arm_px, cy), (cx + arm_px, cy)], fill=color, width=thickness_px)
    draw.line([(cx, cy - arm_px), (cx, cy + arm_px)], fill=color, width=thickness_px)

    # Center dot
    r = 3
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)


def draw_side_banner(
    img: Image.Image,
    side: str,
    top_color: Tuple[int, int, int, int] = (220, 0, 0, 220),
    bottom_color: Tuple[int, int, int, int] = (0, 100, 220, 220),
    banner_height: int = 32,
) -> None:
    """Draw a TOP/BOTTOM banner at the top of the image.
    
    Args:
        img: Image to draw on (modified in place)
        side: "TOP" or "BOTTOM"
        top_color: Banner color for TOP side
        bottom_color: Banner color for BOTTOM side
        banner_height: Banner height in pixels
    """
    color = top_color if side == "TOP" else bottom_color
    label = side

    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, img.width, banner_height], fill=color)

    # Load font
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    # Get text size
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except Exception:
        text_w, text_h = 50, 16  # Fallback

    x = (img.width - text_w) // 2
    y = (banner_height - text_h) // 2

    draw.text((x, y), label, fill=(255, 255, 255, 255), font=font)


def generate_404_image(
    size: int,
    reason: str,
    bg_color: Tuple[int, int, int, int] = (40, 40, 40, 255),
    text_color: Tuple[int, int, int, int] = (200, 60, 60, 255),
) -> Image.Image:
    """Generate a '404 Not Found' style error image.
    
    Args:
        size: Image size in pixels (square)
        reason: Error message to display (e.g., "Component C99 not found")
        bg_color: Background color (RGBA)
        text_color: Text color (RGBA)
    
    Returns:
        PIL Image with 404 message
    """
    img = Image.new("RGBA", (size, size), bg_color)
    draw = ImageDraw.Draw(img, "RGBA")

    # Load fonts
    try:
        font_large = ImageFont.truetype("DejaVuSans-Bold.ttf", size // 6)
        font_small = ImageFont.truetype("DejaVuSans.ttf", size // 24)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = font_large

    # Draw "404" centered
    text_404 = "404"
    try:
        bbox = draw.textbbox((0, 0), text_404, font=font_large)
        w404 = bbox[2] - bbox[0]
        h404 = bbox[3] - bbox[1]
    except Exception:
        w404, h404 = size // 3, size // 8

    x404 = (size - w404) // 2
    y404 = size // 3 - h404 // 2
    draw.text((x404, y404), text_404, fill=text_color, font=font_large)

    # Draw reason text below
    try:
        bbox = draw.textbbox((0, 0), reason, font=font_small)
        w_reason = bbox[2] - bbox[0]
        h_reason = bbox[3] - bbox[1]
    except Exception:
        w_reason, h_reason = size // 2, size // 16

    x_reason = (size - w_reason) // 2
    y_reason = size // 2 + size // 8
    draw.text((x_reason, y_reason), reason, fill=(180, 180, 180, 255), font=font_small)

    # Draw decorative X marks in corners
    corner_margin = size // 10
    cross_size = size // 20
    corner_color = (100, 40, 40, 255)
    
    for cx, cy in [
        (corner_margin, corner_margin),
        (size - corner_margin, corner_margin),
        (corner_margin, size - corner_margin),
        (size - corner_margin, size - corner_margin),
    ]:
        draw.line(
            [(cx - cross_size, cy - cross_size), (cx + cross_size, cy + cross_size)],
            fill=corner_color,
            width=3,
        )
        draw.line(
            [(cx - cross_size, cy + cross_size), (cx + cross_size, cy - cross_size)],
            fill=corner_color,
            width=3,
        )

    return img
