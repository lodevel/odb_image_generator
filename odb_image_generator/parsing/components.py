"""Component placement parsing."""

from typing import List, Literal

from ..models import Placement


def parse_components_file(components_txt: str, side: Literal["TOP", "BOTTOM"]) -> List[Placement]:
    """Parse component placements from ODB++ components file.
    
    CMP line format: CMP pkg_ref x y rot mirror refdes [attributes] ;properties
    """
    placements: List[Placement] = []

    for raw in components_txt.splitlines():
        line = raw.strip()

        # Skip comments and metadata
        if not line or line.startswith("#") or line.startswith("UNITS=") or line.startswith("@"):
            continue

        if line.startswith("CMP "):
            # Strip properties after semicolon
            core = line.split(";", 1)[0]
            parts = core.split()

            # Need at least: CMP pkg_ref x y rot mirror refdes
            if len(parts) < 7:
                continue

            placements.append(
                Placement(
                    refdes=parts[6],
                    x_mm=float(parts[2]),
                    y_mm=float(parts[3]),
                    rot_deg=float(parts[4]),
                    side=side,
                )
            )

    return placements
