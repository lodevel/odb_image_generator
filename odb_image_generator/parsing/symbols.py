"""Symbol definition parsing."""

import re
from typing import Dict, Tuple

from ..models import Symbol


def parse_symbol_defs(feature_txt: str) -> Dict[int, Symbol]:
    """Parse symbol definitions from ODB++ features file.
    
    Symbol lines: $id symbol_name
    Examples: $1 r400 (circle d=400µm), $2 rect1050x1000 (rectangle)
    
    Values are in microns, converted to mm.
    """
    symbols: Dict[int, Symbol] = {}

    for line in feature_txt.splitlines():
        line = line.strip()
        if not line.startswith("$"):
            continue

        match = re.match(r"^\$(\d+)\s+(\S+)$", line)
        if not match:
            continue

        sym_id = int(match.group(1))
        sym_def = match.group(2)

        symbol = _parse_symbol_def(sym_def)
        symbols[sym_id] = symbol

    return symbols


def _parse_symbol_def(sym_def: str) -> Symbol:
    """Parse a single symbol definition string."""
    
    # IMPORTANT: Check more specific patterns FIRST (rect/oval before r)
    if sym_def.startswith("rect") and "x" in sym_def:
        # Rectangle: rect<width>x<height> e.g., rect1050x1000
        dims = sym_def[4:].split("x")
        try:
            w_mm = float(dims[0]) / 1000.0
            h_mm = float(dims[1]) / 1000.0
            return Symbol("rect", (w_mm, h_mm))
        except (ValueError, IndexError):
            return Symbol("unknown", ())

    elif sym_def.startswith("oval") and "x" in sym_def:
        # Oval: oval<width>x<height>
        dims = sym_def[4:].split("x")
        try:
            w_mm = float(dims[0]) / 1000.0
            h_mm = float(dims[1]) / 1000.0
            return Symbol("oval", (w_mm, h_mm))
        except (ValueError, IndexError):
            return Symbol("unknown", ())

    elif sym_def.startswith("s") and sym_def[1:].replace(".", "").isdigit():
        # Square: s<size> e.g., s600 (600µm square) - treat as rect with equal sides
        try:
            size_mm = float(sym_def[1:]) / 1000.0
            return Symbol("rect", (size_mm, size_mm))
        except ValueError:
            return Symbol("unknown", ())

    elif sym_def.startswith("r"):
        # Round/Circle: r<diameter> e.g., r400 (must come AFTER rect check)
        try:
            d_mm = float(sym_def[1:]) / 1000.0
            return Symbol("circle", (d_mm,))
        except ValueError:
            return Symbol("unknown", ())

    return Symbol("unknown", ())
