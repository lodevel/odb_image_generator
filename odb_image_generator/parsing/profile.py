"""Board profile parsing."""

from typing import List, Tuple


def parse_profile_outline(profile_txt: str) -> List[Tuple[float, float]]:
    """Parse board outline from ODB++ profile file.
    
    The profile contains OS (outline segment) lines with x, y coordinates.
    """
    pts: List[Tuple[float, float]] = []
    for line in profile_txt.splitlines():
        line = line.strip()
        if line.startswith("OS "):
            parts = line.split()
            if len(parts) >= 3:
                pts.append((float(parts[1]), float(parts[2])))
    return pts


def compute_bbox_from_pts(pts: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Compute bounding box from list of points.
    
    Returns (xmin, ymin, xmax, ymax) in mm.
    """
    if not pts:
        raise ValueError("Cannot compute bbox from empty point list")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))
