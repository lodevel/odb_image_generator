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

            # Capture any trailing CMP tokens after the refdes (before the ';')
            # verbatim — these can carry part-number / value attributes. Stored
            # raw; the LLM decides which token is meaningful.
            cmp_attrs = parts[7:]
            if cmp_attrs:
                current_placement.properties["_cmp_attrs"] = " ".join(cmp_attrs)

        elif line.startswith("PRP ") and current_placement is not None:
            # ODB++ property record: PRP <name> '<value>' (value single-quoted,
            # may contain spaces). Dump name->value raw; never interpret the
            # value or guess whether it is an MPN. Tolerate malformed lines.
            try:
                rest = line[len("PRP "):].lstrip()
                name, _, after = rest.partition(" ")
                name = name.strip()
                q1 = after.find("'")
                q2 = after.rfind("'")
                if name and q1 != -1 and q2 > q1:
                    value = after[q1 + 1:q2]
                    current_placement.properties[name] = value
            except (ValueError, IndexError):
                # Skip malformed property lines, never raise.
                pass

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
                    net_num = int(parts[6])
                    pin_name = parts[8]
                    current_placement.pins.append(Pin(
                        name=pin_name,
                        x_mm=x_mm,
                        y_mm=y_mm,
                        rot_deg=rot_deg,
                        net_num=net_num,
                    ))
            except (ValueError, IndexError):
                # Skip malformed pin lines
                pass

    # Don't forget the last placement
    if current_placement is not None:
        placements.append(current_placement)

    return placements
