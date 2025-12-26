"""Component placement parsing."""

from typing import List, Literal

from ..models import Pin, Placement


def parse_components_file(components_txt: str, side: Literal["TOP", "BOTTOM"]) -> List[Placement]:
    """Parse component placements from ODB++ components file.
    
    CMP line format: CMP pkg_ref x y rot mirror refdes [attributes] ;properties
    TOP/BOT line format: TOP index x y rot mirror net_num subnet_num name
    """
    placements: List[Placement] = []
    current_placement: Placement | None = None

    for raw in components_txt.splitlines():
        line = raw.strip()

        # Skip comments and metadata
        if not line or line.startswith("#") or line.startswith("UNITS=") or line.startswith("@"):
            continue

        if line.startswith("CMP "):
            # Save previous placement if exists
            if current_placement is not None:
                placements.append(current_placement)

            # Strip properties after semicolon
            core = line.split(";", 1)[0]
            parts = core.split()

            # Need at least: CMP pkg_ref x y rot mirror refdes
            if len(parts) < 7:
                current_placement = None
                continue

            current_placement = Placement(
                refdes=parts[6],
                x_mm=float(parts[2]),
                y_mm=float(parts[3]),
                rot_deg=float(parts[4]),
                side=side,
                pins=[],
            )

        elif (line.startswith("TOP ") or line.startswith("BOT ")) and current_placement is not None:
            # Parse pin line: TOP index x y rot mirror net_num subnet_num name
            # Format: TOP 0 95.2394209 42.46449724 270 N 118 283 1
            try:
                parts = line.split()
                # Need at least: TOP/BOT index x y rot mirror net subnet name
                if len(parts) >= 9:
                    x_mm = float(parts[2])
                    y_mm = float(parts[3])
                    rot_deg = float(parts[4])
                    pin_name = parts[8]
                    current_placement.pins.append(Pin(
                        name=pin_name,
                        x_mm=x_mm,
                        y_mm=y_mm,
                        rot_deg=rot_deg,
                    ))
            except (ValueError, IndexError):
                # Skip malformed pin lines
                pass

    # Don't forget the last placement
    if current_placement is not None:
        placements.append(current_placement)

    return placements
