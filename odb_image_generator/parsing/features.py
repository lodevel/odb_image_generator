"""Feature primitives parsing."""

import re
from typing import Any, Generator, List, Optional, Tuple

from ..models import LayerData, Symbol
from .symbols import parse_symbol_defs


def parse_layer_data(feature_txt: str) -> LayerData:
    """Parse complete layer data (symbols + features) from features file."""
    symbols = parse_symbol_defs(feature_txt)
    features = list(iter_features(feature_txt))
    
    # Convert symbols dict to use Symbol objects
    symbol_objs = {k: v for k, v in symbols.items()}
    
    return LayerData(symbols=symbol_objs, features=features)


def iter_features(feature_txt: str) -> Generator[Tuple[str, Any], None, None]:
    """Iterate over feature primitives in ODB++ features file.
    
    Yields tuples of (kind, data) where:
    - "P": (x, y, sym_id) - pad/flash
    - "L": (x1, y1, x2, y2, sym_id) - line
    - "A": (x1, y1, x2, y2, xc, yc, sym_id) - arc
    - "POLY": (poly_kind, [(x,y), ...]) - polygon (standalone)
    - "SURFACE": (polarity, contours) - surface feature with contours
      where contours = [(poly_kind, [(x,y), ...]), ...]
    - "TEXT": (x, y, text_str) - text
    """
    in_poly = False
    poly_pts: List[Tuple[float, float]] = []
    poly_kind: Optional[str] = None
    
    # Surface tracking
    in_surface = False
    surface_polarity: Optional[str] = None
    surface_contours: List[Tuple[str, List[Tuple[float, float]]]] = []

    for raw in feature_txt.splitlines():
        line = raw.strip()

        # Skip metadata lines
        if not line or line.startswith("#") or line.startswith("UNITS=") or \
           line.startswith("$") or line.startswith("@") or line.startswith("&"):
            continue

        # Strip properties after semicolon
        core = line.split(";", 1)[0].strip()
        if not core:
            continue

        parts = core.split()
        token = parts[0]

        # Surface start: S P|N dcode (polarity P=positive, N=negative)
        if token == "S" and len(parts) >= 2:
            in_surface = True
            surface_polarity = parts[1]  # P or N
            surface_contours = []
            continue

        # Surface end: SE
        if token == "SE" and in_surface:
            if surface_contours:
                yield ("SURFACE", (surface_polarity, surface_contours))
            in_surface = False
            surface_polarity = None
            surface_contours = []
            continue

        # Polygon start: OB x y kind
        if token == "OB" and len(parts) >= 4:
            in_poly = True
            poly_pts = [(float(parts[1]), float(parts[2]))]
            poly_kind = parts[3]
            continue

        # Polygon segment: OS x y
        if token == "OS" and in_poly and len(parts) >= 3:
            poly_pts.append((float(parts[1]), float(parts[2])))
            continue

        # Polygon end: OE
        if token == "OE" and in_poly:
            if in_surface:
                # Add to current surface
                surface_contours.append((poly_kind, poly_pts))
            else:
                # Standalone polygon
                yield ("POLY", (poly_kind, poly_pts))
            in_poly = False
            poly_pts = []
            poly_kind = None
            continue

        # Pad/flash: P x y sym_id
        if token == "P" and len(parts) >= 4:
            yield ("P", (float(parts[1]), float(parts[2]), int(parts[3])))

        # Line: L x1 y1 x2 y2 sym_id
        elif token == "L" and len(parts) >= 6:
            yield ("L", (float(parts[1]), float(parts[2]), 
                        float(parts[3]), float(parts[4]), int(parts[5])))

        # Arc: A x1 y1 x2 y2 xc yc sym_id
        elif token == "A" and len(parts) >= 8:
            yield ("A", (float(parts[1]), float(parts[2]),
                        float(parts[3]), float(parts[4]),
                        float(parts[5]), float(parts[6]), int(parts[7])))

        # Text: T x y ... 'text'
        elif token == "T" and len(parts) >= 4:
            try:
                x = float(parts[1])
                y = float(parts[2])
                # Extract text from quotes
                text_match = re.search(r"'([^']*)'|\"([^\"]*)\"", raw)
                if text_match:
                    text_str = text_match.group(1) or text_match.group(2)
                else:
                    text_str = parts[-1] if len(parts) > 4 else ""
                if text_str:
                    yield ("TEXT", (x, y, text_str))
            except (ValueError, IndexError):
                pass
