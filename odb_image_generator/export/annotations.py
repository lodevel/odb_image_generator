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
