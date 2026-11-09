#!/usr/bin/env python3
"""
Layer order requested:
  1) Board (background)
  2) Copper (full copper of the same face)
  3) Solder mask (board-wide green layer with openings cut out)
  4) Silk (overlay)
  5) Cross + TOP/BOTTOM banner
Bottom crops are mirrored AFTER crop (to look like holding the board).

Inputs expected (present in CE_FLAME-DETECTOR.tgz):
  odb/steps/pcb/profile
  odb/steps/pcb/layers/comp_+_top/components
  odb/steps/pcb/layers/comp_+_bot/components
  odb/steps/pcb/layers/top/features
  odb/steps/pcb/layers/bottom_layer/features
  odb/steps/pcb/layers/top_solder/features
  odb/steps/pcb/layers/bottom_solder/features
  odb/steps/pcb/layers/top_overlay/features
  odb/steps/pcb/layers/bottom_overlay/features
"""

import argparse
import json
import math
import re
import tarfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps


# -------------------------
# Data structures
# -------------------------

@dataclass
class Placement:
    refdes: str
    x_mm: float
    y_mm: float
    rot_deg: float
    side: str  # "TOP" or "BOTTOM"


# -------------------------
# Tar helpers
# -------------------------

def read_text_from_tar(tar: tarfile.TarFile, member_name: str) -> str:
    m = tar.getmember(member_name)
    f = tar.extractfile(m)
    if f is None:
        raise FileNotFoundError(member_name)
    return f.read().decode("utf-8", errors="replace")


# -------------------------
# Parsing: profile outline
# -------------------------

def parse_profile_outline(profile_txt: str) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    for line in profile_txt.splitlines():
        line = line.strip()
        if line.startswith("OS "):
            _, xs, ys = line.split()
            pts.append((float(xs), float(ys)))
    return pts


def compute_bbox_from_pts(pts: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


# -------------------------
# Parsing: components placements
# -------------------------

def parse_components_file(components_txt: str, side: str) -> List[Placement]:
    out: List[Placement] = []
    for raw in components_txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("UNITS=") or line.startswith("@"):
            continue
        if line.startswith("CMP "):
            core = line.split(";", 1)[0]
            parts = core.split()
            if len(parts) < 7:
                continue
            out.append(
                Placement(
                    refdes=parts[6],
                    x_mm=float(parts[2]),
                    y_mm=float(parts[3]),
                    rot_deg=float(parts[4]),
                    side=side,
                )
            )
    return out


# -------------------------
# Parsing: symbol defs ($)
# -------------------------

def parse_symbol_defs(feature_txt: str) -> Dict[int, Tuple[str, Tuple[float, ...]]]:
    """
    $id rectW x H or rD. Values are microns => /1000 => mm.
    Also handles oval symbols.
    """
    sym: Dict[int, Tuple[str, Tuple[float, ...]]] = {}
    for line in feature_txt.splitlines():
        line = line.strip()
        if not line.startswith("$"):
            continue
        m = re.match(r"^\$(\d+)\s+(\S+)$", line)
        if not m:
            continue
        sid = int(m.group(1))
        sdef = m.group(2)

        # IMPORTANT: Check more specific patterns FIRST (rect/oval before r)
        if sdef.startswith("rect") and "x" in sdef:
            # Rectangle: rect<width>x<height> e.g., rect1050x1000
            dims = sdef[4:].split("x")
            try:
                w_mm = float(dims[0]) / 1000.0
                h_mm = float(dims[1]) / 1000.0
                sym[sid] = ("rect", (w_mm, h_mm))
            except ValueError:
                sym[sid] = ("unknown", ())
        elif sdef.startswith("oval") and "x" in sdef:
            # Oval: oval<width>x<height>
            dims = sdef[4:].split("x")
            try:
                w_mm = float(dims[0]) / 1000.0
                h_mm = float(dims[1]) / 1000.0
                sym[sid] = ("oval", (w_mm, h_mm))
            except ValueError:
                sym[sid] = ("unknown", ())
        elif sdef.startswith("s") and sdef[1:].replace(".", "").isdigit():
            # Square: s<size> e.g., s600 (600µm square) - treat as rect with equal sides
            try:
                size_mm = float(sdef[1:]) / 1000.0
                sym[sid] = ("rect", (size_mm, size_mm))
            except ValueError:
                sym[sid] = ("unknown", ())
        elif sdef.startswith("r"):
            # Round/Circle: r<diameter> e.g., r400 (must come AFTER rect check)
            try:
                d_mm = float(sdef[1:]) / 1000.0
                sym[sid] = ("circle", (d_mm,))
            except ValueError:
                sym[sid] = ("unknown", ())
        else:
            sym[sid] = ("unknown", ())
    return sym


# -------------------------
# Parsing: features primitives (P/L/A + polygons OB/OS/OE)
# -------------------------

def iter_features(feature_txt: str):
    in_poly = False
    poly_pts: List[Tuple[float, float]] = []
    poly_kind: Optional[str] = None

    for raw in feature_txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("UNITS=") or line.startswith("$") or line.startswith("@") or line.startswith("&"):
            continue

        core = line.split(";", 1)[0].strip()
        if not core:
            continue
        parts = core.split()
        t = parts[0]

        if t == "OB" and len(parts) >= 4:
            in_poly = True
            poly_pts = [(float(parts[1]), float(parts[2]))]
            poly_kind = parts[3]
            continue

        if t == "OS" and in_poly and len(parts) >= 3:
            poly_pts.append((float(parts[1]), float(parts[2])))
            continue

        if t == "OE" and in_poly:
            yield ("POLY", (poly_kind, poly_pts))
            in_poly = False
            poly_pts = []
            poly_kind = None
            continue

        if t == "P" and len(parts) >= 4:
            yield ("P", (float(parts[1]), float(parts[2]), int(parts[3])))
        elif t == "L" and len(parts) >= 6:
            yield ("L", (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), int(parts[5])))
        elif t == "A" and len(parts) >= 8:
            yield ("A", (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]),
                         float(parts[5]), float(parts[6]), int(parts[7])))
        elif t == "T" and len(parts) >= 4:
            # TEXT: T x y font_id mirror_flag orient_deg text_string...
            # Format can vary; typically: T x y font text or T x y font mirror orient xsize ysize wfactor text
            # We'll extract x, y and the text content (last part or after known fields)
            try:
                x = float(parts[1])
                y = float(parts[2])
                # Text content is usually in the original line after the coordinates, in quotes or at end
                # Try to extract text from the raw line
                text_match = re.search(r"'([^']*)'|\"([^\"]*)\"", raw)
                if text_match:
                    text_str = text_match.group(1) or text_match.group(2)
                else:
                    # Fallback: take last part if no quotes
                    text_str = parts[-1] if len(parts) > 4 else ""
                if text_str:
                    yield ("TEXT", (x, y, text_str))
            except (ValueError, IndexError):
                pass


# -------------------------
# Rendering helpers
# -------------------------

def mm_to_px_x(x_mm: float, bbox_mm: Tuple[float, float, float, float], img_size: int) -> int:
    xmin, ymin, xmax, ymax = bbox_mm
    return int(round((x_mm - xmin) / (xmax - xmin) * (img_size - 1)))

def mm_to_px_y(y_mm: float, bbox_mm: Tuple[float, float, float, float], img_size: int) -> int:
    xmin, ymin, xmax, ymax = bbox_mm
    return int(round((ymax - y_mm) / (ymax - ymin) * (img_size - 1)))

def clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v

def draw_board_mask(img: Image.Image, outline_pts: List[Tuple[float, float]], board_bbox_mm, fill_rgba):
    draw = ImageDraw.Draw(img, "RGBA")
    poly = [(mm_to_px_x(x, board_bbox_mm, img.width), mm_to_px_y(y, board_bbox_mm, img.height)) for x, y in outline_pts]
    if len(poly) >= 3:
        draw.polygon(poly, fill=fill_rgba)

def draw_outline(img: Image.Image, outline_pts: List[Tuple[float, float]], board_bbox_mm, rgba=(70, 70, 70, 255), width=2):
    draw = ImageDraw.Draw(img, "RGBA")
    pts = [(mm_to_px_x(x, board_bbox_mm, img.width), mm_to_px_y(y, board_bbox_mm, img.height)) for x, y in outline_pts]
    if len(pts) >= 2:
        draw.line(pts + [pts[0]], fill=rgba, width=width)

def symbol_thickness_px(sym_id: int, sym_defs, board_bbox_mm, img_size: int) -> int:
    kind, params = sym_defs.get(sym_id, ("unknown", ()))
    if kind == "circle" and params:
        d_mm = params[0]
        px = int(round(d_mm / (board_bbox_mm[2] - board_bbox_mm[0]) * img_size))
        return max(1, px)
    return 1

def draw_flash(draw: ImageDraw.ImageDraw, x_mm, y_mm, sym_id, sym_defs, board_bbox_mm, img_size, fill_rgba, outline=False, outline_width=2):
    kind, params = sym_defs.get(sym_id, ("unknown", ()))
    cx = mm_to_px_x(x_mm, board_bbox_mm, img_size)
    cy = mm_to_px_y(y_mm, board_bbox_mm, img_size)

    if kind == "circle" and params:
        d_mm = params[0]
        r_px = max(1, int(round((d_mm / 2.0) / (board_bbox_mm[2] - board_bbox_mm[0]) * img_size)))
        box = (cx - r_px, cy - r_px, cx + r_px, cy + r_px)
        if outline:
            draw.ellipse(box, outline=fill_rgba, width=outline_width)
        else:
            draw.ellipse(box, fill=fill_rgba, outline=fill_rgba)
    elif kind == "rect" and len(params) == 2:
        w_mm, h_mm = params
        hw = (w_mm / 2.0) / (board_bbox_mm[2] - board_bbox_mm[0]) * img_size
        hh = (h_mm / 2.0) / (board_bbox_mm[3] - board_bbox_mm[1]) * img_size
        box = (cx - hw, cy - hh, cx + hw, cy + hh)
        if outline:
            draw.rectangle(box, outline=fill_rgba, width=outline_width)
        else:
            draw.rectangle(box, fill=fill_rgba, outline=fill_rgba)
    elif kind == "oval" and len(params) == 2:
        w_mm, h_mm = params
        hw = (w_mm / 2.0) / (board_bbox_mm[2] - board_bbox_mm[0]) * img_size
        hh = (h_mm / 2.0) / (board_bbox_mm[3] - board_bbox_mm[1]) * img_size
        box = (cx - hw, cy - hh, cx + hw, cy + hh)
        if outline:
            draw.ellipse(box, outline=fill_rgba, width=outline_width)
        else:
            draw.ellipse(box, fill=fill_rgba, outline=fill_rgba)
    else:
        draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=fill_rgba, outline=fill_rgba)

def draw_polygon(draw: ImageDraw.ImageDraw, pts_mm: List[Tuple[float,float]], board_bbox_mm, img_size: int, fill_rgba=None, outline_rgba=None, width=2):
    pts_px = [(mm_to_px_x(x, board_bbox_mm, img_size), mm_to_px_y(y, board_bbox_mm, img_size)) for x, y in pts_mm]
    if len(pts_px) < 3:
        return
    if fill_rgba is not None:
        draw.polygon(pts_px, fill=fill_rgba)
    if outline_rgba is not None:
        draw.line(pts_px + [pts_px[0]], fill=outline_rgba, width=width)

def draw_line(draw: ImageDraw.ImageDraw, x1,y1,x2,y2, sym_id, sym_defs, board_bbox_mm, img_size, fill_rgba):
    p1 = (mm_to_px_x(x1, board_bbox_mm, img_size), mm_to_px_y(y1, board_bbox_mm, img_size))
    p2 = (mm_to_px_x(x2, board_bbox_mm, img_size), mm_to_px_y(y2, board_bbox_mm, img_size))
    thick = symbol_thickness_px(sym_id, sym_defs, board_bbox_mm, img_size)
    draw.line([p1, p2], fill=fill_rgba, width=thick)

def draw_arc(draw: ImageDraw.ImageDraw, x1,y1,x2,y2, xc,yc, sym_id, sym_defs, board_bbox_mm, img_size, fill_rgba):
    r = math.hypot(x1 - xc, y1 - yc)
    if r < 1e-9:
        return
    a1 = math.atan2(y1 - yc, x1 - xc)
    a2 = math.atan2(y2 - yc, x2 - xc)
    da = a2 - a1
    while da <= -math.pi:
        da += 2 * math.pi
    while da > math.pi:
        da -= 2 * math.pi
    steps = max(12, int(abs(da) / (math.pi / 24)))
    pts = []
    for i in range(steps + 1):
        t = i / steps
        a = a1 + da * t
        x = xc + r * math.cos(a)
        y = yc + r * math.sin(a)
        pts.append((mm_to_px_x(x, board_bbox_mm, img_size), mm_to_px_y(y, board_bbox_mm, img_size)))
    thick = symbol_thickness_px(sym_id, sym_defs, board_bbox_mm, img_size)
    draw.line(pts, fill=fill_rgba, width=thick)


def draw_text(draw: ImageDraw.ImageDraw, x_mm: float, y_mm: float, text_str: str,
              board_bbox_mm, img_size: int, fill_rgba, font_size_px: int = 12):
    """Draw text at the given position."""
    px = mm_to_px_x(x_mm, board_bbox_mm, img_size)
    py = mm_to_px_y(y_mm, board_bbox_mm, img_size)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size_px)
    except Exception:
        font = ImageFont.load_default()
    draw.text((px, py), text_str, fill=fill_rgba, font=font)


# -------------------------
# Soldermask layer creation (alpha mask with openings cut out)
# -------------------------

def build_soldermask_layer(render_size: int,
                           board_bbox_mm: Tuple[float,float,float,float],
                           outline_pts: List[Tuple[float,float]],
                           openings_features_txt: str,
                           mask_rgba=(20, 60, 30, 255),
                           mask_alpha: int = 220) -> Image.Image:
    """
    Creates an RGBA image:
    - board area alpha = mask_alpha
    - openings drawn with alpha = 0 (cut-out)
    """
    # Alpha mask (L)
    alpha = Image.new("L", (render_size, render_size), 0)
    da = ImageDraw.Draw(alpha)

    # board polygon alpha
    board_poly = [(mm_to_px_x(x, board_bbox_mm, render_size), mm_to_px_y(y, board_bbox_mm, render_size)) for x, y in outline_pts]
    if len(board_poly) >= 3:
        da.polygon(board_poly, fill=mask_alpha)

    sym_defs = parse_symbol_defs(openings_features_txt)

    # cut out openings (paint alpha=0 on those shapes)
    for kind, data in iter_features(openings_features_txt):
        if kind == "P":
            x, y, sid = data
            # draw flash in alpha=0
            kind_s, params = sym_defs.get(sid, ("unknown", ()))
            cx = mm_to_px_x(x, board_bbox_mm, render_size)
            cy = mm_to_px_y(y, board_bbox_mm, render_size)
            if kind_s == "circle" and params:
                d_mm = params[0]
                r_px = max(1, int(round((d_mm / 2.0) / (board_bbox_mm[2] - board_bbox_mm[0]) * render_size)))
                da.ellipse((cx - r_px, cy - r_px, cx + r_px, cy + r_px), fill=0)
            elif kind_s == "rect" and len(params) == 2:
                w_mm, h_mm = params
                hw = (w_mm / 2.0) / (board_bbox_mm[2] - board_bbox_mm[0]) * render_size
                hh = (h_mm / 2.0) / (board_bbox_mm[3] - board_bbox_mm[1]) * render_size
                da.rectangle((cx - hw, cy - hh, cx + hw, cy + hh), fill=0)
            elif kind_s == "oval" and len(params) == 2:
                w_mm, h_mm = params
                hw = (w_mm / 2.0) / (board_bbox_mm[2] - board_bbox_mm[0]) * render_size
                hh = (h_mm / 2.0) / (board_bbox_mm[3] - board_bbox_mm[1]) * render_size
                da.ellipse((cx - hw, cy - hh, cx + hw, cy + hh), fill=0)
            else:
                da.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=0)

        elif kind == "L":
            x1, y1, x2, y2, sid = data
            # Draw line with symbol thickness as stroke, alpha=0 to cut opening
            kind_s, params = sym_defs.get(sid, ("unknown", ()))
            p1 = (mm_to_px_x(x1, board_bbox_mm, render_size), mm_to_px_y(y1, board_bbox_mm, render_size))
            p2 = (mm_to_px_x(x2, board_bbox_mm, render_size), mm_to_px_y(y2, board_bbox_mm, render_size))
            if kind_s == "circle" and params:
                d_mm = params[0]
                thick = max(1, int(round(d_mm / (board_bbox_mm[2] - board_bbox_mm[0]) * render_size)))
            else:
                thick = 1
            da.line([p1, p2], fill=0, width=thick)

        elif kind == "A":
            x1, y1, x2, y2, xc, yc, sid = data
            # Draw arc with symbol thickness as stroke, alpha=0 to cut opening
            kind_s, params = sym_defs.get(sid, ("unknown", ()))
            r = math.hypot(x1 - xc, y1 - yc)
            if r < 1e-9:
                continue
            a1 = math.atan2(y1 - yc, x1 - xc)
            a2 = math.atan2(y2 - yc, x2 - xc)
            da_angle = a2 - a1
            while da_angle <= -math.pi:
                da_angle += 2 * math.pi
            while da_angle > math.pi:
                da_angle -= 2 * math.pi
            steps = max(12, int(abs(da_angle) / (math.pi / 24)))
            pts = []
            for i in range(steps + 1):
                t = i / steps
                a = a1 + da_angle * t
                x = xc + r * math.cos(a)
                y = yc + r * math.sin(a)
                pts.append((mm_to_px_x(x, board_bbox_mm, render_size), mm_to_px_y(y, board_bbox_mm, render_size)))
            if kind_s == "circle" and params:
                d_mm = params[0]
                thick = max(1, int(round(d_mm / (board_bbox_mm[2] - board_bbox_mm[0]) * render_size)))
            else:
                thick = 1
            if len(pts) >= 2:
                da.line(pts, fill=0, width=thick)

        elif kind == "POLY":
            poly_kind, pts_mm = data
            if poly_kind != "I":
                continue
            pts_px = [(mm_to_px_x(x, board_bbox_mm, render_size), mm_to_px_y(y, board_bbox_mm, render_size)) for x, y in pts_mm]
            if len(pts_px) >= 3:
                da.polygon(pts_px, fill=0)

    mask_img = Image.new("RGBA", (render_size, render_size), mask_rgba)
    mask_img.putalpha(alpha)
    return mask_img


# -------------------------
# Face renderer: Board -> Copper -> Mask -> Silk
# -------------------------

def render_face(render_size: int,
                board_bbox_mm: Tuple[float,float,float,float],
                outline_pts: List[Tuple[float,float]],
                copper_features_txt: str,
                openings_features_txt: str,
                silk_features_txt: str) -> Image.Image:
    # 1) Board
    img = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 255))
    draw_board_mask(img, outline_pts, board_bbox_mm, (0, 0, 0, 255))
    draw_outline(img, outline_pts, board_bbox_mm, rgba=(70, 70, 70, 255), width=2)

    copper_syms = parse_symbol_defs(copper_features_txt)
    silk_syms = parse_symbol_defs(silk_features_txt)

    d = ImageDraw.Draw(img, "RGBA")

    # 2) Copper (full)
    copper_rgba = (220, 170, 40, 255)
    for kind, data in iter_features(copper_features_txt):
        if kind == "P":
            x, y, sid = data
            draw_flash(d, x, y, sid, copper_syms, board_bbox_mm, render_size, copper_rgba, outline=False)
        elif kind == "L":
            x1, y1, x2, y2, sid = data
            draw_line(d, x1, y1, x2, y2, sid, copper_syms, board_bbox_mm, render_size, copper_rgba)
        elif kind == "A":
            x1, y1, x2, y2, xc, yc, sid = data
            draw_arc(d, x1, y1, x2, y2, xc, yc, sid, copper_syms, board_bbox_mm, render_size, copper_rgba)
        elif kind == "POLY":
            poly_kind, pts = data
            if poly_kind == "I":
                draw_polygon(d, pts, board_bbox_mm, render_size, fill_rgba=copper_rgba)

    # 3) Solder mask (green layer with openings cut out)
    mask_layer = build_soldermask_layer(render_size, board_bbox_mm, outline_pts, openings_features_txt,
                                        mask_rgba=(20, 60, 30, 255), mask_alpha=220)
    img = Image.alpha_composite(img, mask_layer)
    d = ImageDraw.Draw(img, "RGBA")

    # 4) Silk (white, non-obscuring: L/A filled, P/POLY outlines, TEXT rendered)
    silk_rgba = (245, 245, 245, 220)
    for kind, data in iter_features(silk_features_txt):
        if kind == "L":
            x1, y1, x2, y2, sid = data
            draw_line(d, x1, y1, x2, y2, sid, silk_syms, board_bbox_mm, render_size, silk_rgba)
        elif kind == "A":
            x1, y1, x2, y2, xc, yc, sid = data
            draw_arc(d, x1, y1, x2, y2, xc, yc, sid, silk_syms, board_bbox_mm, render_size, silk_rgba)
        elif kind == "P":
            x, y, sid = data
            draw_flash(d, x, y, sid, silk_syms, board_bbox_mm, render_size, silk_rgba, outline=True, outline_width=2)
        elif kind == "POLY":
            poly_kind, pts = data
            if poly_kind == "I":
                draw_polygon(d, pts, board_bbox_mm, render_size, outline_rgba=silk_rgba, width=2)
        elif kind == "TEXT":
            x, y, text_str = data
            # Calculate font size based on render resolution (approx 0.8mm text height)
            font_size_px = max(8, int(round(0.8 / (board_bbox_mm[2] - board_bbox_mm[0]) * render_size)))
            draw_text(d, x, y, text_str, board_bbox_mm, render_size, silk_rgba, font_size_px)

    return img


# -------------------------
# Overlays: cross + banner
# -------------------------

def draw_cross_center(img: Image.Image, side: str, window_mm: float):
    px_per_mm = img.width / window_mm
    arm_mm = 1.5  # 3mm total
    thickness_px = 3
    arm_px = int(round(arm_mm * px_per_mm))
    cx = img.width // 2
    cy = img.height // 2
    color = (255, 0, 0, 255) if side == "TOP" else (0, 140, 255, 255)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.line([(cx - arm_px, cy), (cx + arm_px, cy)], fill=color, width=thickness_px)
    draw.line([(cx, cy - arm_px), (cx, cy + arm_px)], fill=color, width=thickness_px)
    r = 3
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

def draw_side_banner(img: Image.Image, side: str):
    banner_h = 32
    opacity = 220
    if side == "TOP":
        color = (220, 0, 0, opacity)
        label = "TOP"
    else:
        color = (0, 100, 220, opacity)
        label = "BOTTOM"

    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, img.width, banner_h], fill=color)

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    try:
        text_w, text_h = draw.textsize(label, font=font)
    except Exception:
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    x = (img.width - text_w) // 2
    y = (banner_h - text_h) // 2
    draw.text((x, y), label, fill=(255, 255, 255, 255), font=font)


# -------------------------
# Crop helpers
# -------------------------

def crop_box_mm_centered(x_mm: float, y_mm: float, window_mm: float) -> Tuple[float, float, float, float]:
    half = window_mm / 2.0
    return (x_mm - half, y_mm - half, x_mm + half, y_mm + half)

def crop_mm_to_px_unclamped(box_mm: Tuple[float,float,float,float],
                            board_bbox_mm: Tuple[float,float,float,float],
                            img: Image.Image) -> Tuple[int,int,int,int]:
    """Convert mm crop box to pixel coordinates WITHOUT clamping."""
    xmin, ymin, xmax, ymax = box_mm
    x1 = mm_to_px_x(xmin, board_bbox_mm, img.width)
    x2 = mm_to_px_x(xmax, board_bbox_mm, img.width)
    y1 = mm_to_px_y(ymax, board_bbox_mm, img.height)
    y2 = mm_to_px_y(ymin, board_bbox_mm, img.height)
    x1, x2 = sorted([x1, x2])
    y1, y2 = sorted([y1, y2])
    return (x1, y1, x2, y2)

def extract_crop_with_padding(face_img: Image.Image, crop_px: Tuple[int,int,int,int]) -> Image.Image:
    """
    Extract a crop from the face image, padding with black where the crop
    extends beyond the image bounds. This ensures the component stays centered.
    """
    x1, y1, x2, y2 = crop_px
    crop_w = x2 - x1
    crop_h = y2 - y1
    
    # Create black canvas of the desired crop size
    result = Image.new("RGBA", (crop_w, crop_h), (0, 0, 0, 255))
    
    # Calculate the valid region within the source image
    src_x1 = max(0, x1)
    src_y1 = max(0, y1)
    src_x2 = min(face_img.width, x2)
    src_y2 = min(face_img.height, y2)
    
    # Calculate where to paste in the result image
    dst_x1 = src_x1 - x1
    dst_y1 = src_y1 - y1
    
    # Only paste if there's a valid region
    if src_x2 > src_x1 and src_y2 > src_y1:
        region = face_img.crop((src_x1, src_y1, src_x2, src_y2))
        result.paste(region, (dst_x1, dst_y1))
    
    return result


# -------------------------
# Main
# -------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--odb-tgz", required=True, help="Path to ODB++ .tgz")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--img-size", type=int, default=1024, help="Output crop size (px)")
    ap.add_argument("--render-size", type=int, default=8192, help="Global render resolution per face (px)")
    ap.add_argument("--window-mm", type=float, default=40.0, help="Crop window size in mm (square)")
    ap.add_argument("--limit", type=int, default=0, help="If >0, only export first N components (debug)")
    args = ap.parse_args()

    import os
    os.makedirs(args.out_dir, exist_ok=True)
    img_dir = os.path.join(args.out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)

    with tarfile.open(args.odb_tgz, "r:gz") as tar:
        outline_pts = parse_profile_outline(read_text_from_tar(tar, "odb/steps/pcb/profile"))
        if len(outline_pts) < 3:
            raise RuntimeError("Profile outline polygon not found (need >=3 OS points).")
        board_bbox_mm = compute_bbox_from_pts(outline_pts)

        top_components = read_text_from_tar(tar, "odb/steps/pcb/layers/comp_+_top/components")
        bot_components = read_text_from_tar(tar, "odb/steps/pcb/layers/comp_+_bot/components")
        placements = parse_components_file(top_components, "TOP") + parse_components_file(bot_components, "BOTTOM")

        # Copper, openings (solder), silk for each side
        top_cu = read_text_from_tar(tar, "odb/steps/pcb/layers/top/features")
        bot_cu = read_text_from_tar(tar, "odb/steps/pcb/layers/bottom_layer/features")

        top_open = read_text_from_tar(tar, "odb/steps/pcb/layers/top_solder/features")
        bot_open = read_text_from_tar(tar, "odb/steps/pcb/layers/bottom_solder/features")

        top_silk = read_text_from_tar(tar, "odb/steps/pcb/layers/top_overlay/features")
        bot_silk = read_text_from_tar(tar, "odb/steps/pcb/layers/bottom_overlay/features")

        # Render global faces once
        top_img = render_face(args.render_size, board_bbox_mm, outline_pts, top_cu, top_open, top_silk)
        bot_img = render_face(args.render_size, board_bbox_mm, outline_pts, bot_cu, bot_open, bot_silk)

        index = []
        count = 0
        for p in placements:
            if args.limit and count >= args.limit:
                break

            face_img = top_img if p.side == "TOP" else bot_img
            box_mm = crop_box_mm_centered(p.x_mm, p.y_mm, args.window_mm)
            crop_px = crop_mm_to_px_unclamped(box_mm, board_bbox_mm, face_img)

            # Extract crop with black padding for out-of-bounds areas (keeps component centered)
            crop = extract_crop_with_padding(face_img, crop_px)
            crop = crop.resize((args.img_size, args.img_size), resample=Image.Resampling.LANCZOS)

            # Mirror BOTTOM after crop to look like holding the board
            if p.side == "BOTTOM":
                crop = ImageOps.mirror(crop)

            # 5) Cross + banner last
            draw_cross_center(crop, p.side, window_mm=args.window_mm)
            draw_side_banner(crop, p.side)

            filename = f"{p.refdes}.png"
            crop.save(os.path.join(img_dir, filename), "PNG")

            index.append({
                "refdes": p.refdes,
                "x_mm": p.x_mm,
                "y_mm": p.y_mm,
                "rotation_deg": p.rot_deg,
                "side": p.side,
                "crop_window_mm": args.window_mm,
                "crop_box_mm": {"xmin": box_mm[0], "ymin": box_mm[1], "xmax": box_mm[2], "ymax": box_mm[3]},
                "image_file": f"images/{filename}",
            })
            count += 1

        with open(os.path.join(args.out_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

    print(f"Done. Wrote {count} images to: {img_dir}")
    print(f"Index: {os.path.join(args.out_dir, 'index.json')}")


if __name__ == "__main__":
    main()
