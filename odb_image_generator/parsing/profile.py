"""Board profile parsing.

The ODB++ profile is one surface made of contours. Each contour opens with
``OB x y I|H`` (I = island = board material, H = hole = a cutout in it),
continues with ``OS x y`` (straight segment) and ``OC xe ye xc yc Y|N``
(arc, Y = clockwise) records, and closes with ``OE``.
"""

import math
from typing import List, Optional, Tuple

Point = Tuple[float, float]
Contour = Tuple[str, List[Point]]  # ("I" or "H", points in mm)


def arc_points(
    start: Point,
    end: Point,
    center: Point,
    clockwise: bool,
    step_deg: float = 7.5,
) -> List[Point]:
    """Points along an arc from *start* to *end* around *center*, both ends
    included. ``start == end`` is a full circle (the ODB++ way to write one)."""
    r = math.hypot(start[0] - center[0], start[1] - center[1])
    if r < 1e-9:
        return [start, end]
    a1 = math.atan2(start[1] - center[1], start[0] - center[0])
    a2 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = a2 - a1
    if clockwise:
        while sweep >= -1e-12:
            sweep -= 2 * math.pi
    else:
        while sweep <= 1e-12:
            sweep += 2 * math.pi
    steps = max(4, int(math.ceil(abs(math.degrees(sweep)) / step_deg)))
    pts = [
        (center[0] + r * math.cos(a1 + sweep * i / steps),
         center[1] + r * math.sin(a1 + sweep * i / steps))
        for i in range(steps)
    ]
    pts.append(end)
    return pts


def parse_profile_contours(profile_txt: str) -> List[Contour]:
    """Every closed contour of the profile, in file order, as (kind, points)."""
    contours: List[Contour] = []
    pts: Optional[List[Point]] = None
    kind = "I"
    for line in profile_txt.splitlines():
        parts = line.split(";", 1)[0].split()
        if not parts:
            continue
        token = parts[0]
        try:
            if token == "OB" and len(parts) >= 3:
                pts = [(float(parts[1]), float(parts[2]))]
                kind = parts[3].upper() if len(parts) >= 4 else "I"
            elif token == "OS" and pts is not None and len(parts) >= 3:
                pts.append((float(parts[1]), float(parts[2])))
            elif token == "OC" and pts is not None and len(parts) >= 5:
                end = (float(parts[1]), float(parts[2]))
                center = (float(parts[3]), float(parts[4]))
                clockwise = len(parts) < 6 or parts[5].upper() == "Y"
                pts.extend(arc_points(pts[-1], end, center, clockwise)[1:])
            elif token == "OE" and pts is not None:
                if len(pts) >= 3:
                    contours.append((kind, pts))
                pts = None
        except ValueError:
            pts = None  # malformed contour: drop it, keep the rest
    return contours


def polygon_area(pts: List[Point]) -> float:
    """Unsigned area of a polygon (shoelace)."""
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i - 1]
        x2, y2 = pts[i]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def parse_profile_outline(profile_txt: str) -> List[Point]:
    """The board outline: the largest island contour of the profile.

    Hole contours are *not* part of it (see :func:`parse_profile_holes`)."""
    islands = [p for k, p in parse_profile_contours(profile_txt) if k != "H"]
    return max(islands, key=polygon_area) if islands else []


def parse_profile_holes(profile_txt: str) -> List[List[Point]]:
    """Cutouts the profile declares as hole (``H``) contours."""
    return [p for k, p in parse_profile_contours(profile_txt) if k == "H"]


def compute_bbox_from_pts(pts: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Compute bounding box from list of points.

    Returns (xmin, ymin, xmax, ymax) in mm.
    """
    if not pts:
        raise ValueError("Cannot compute bbox from empty point list")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))
