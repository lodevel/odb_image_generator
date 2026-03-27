"""ODB++ archive handling."""

import re
import tarfile
from pathlib import Path
from typing import List, Optional

from ..models import Board, FaceLayers, LayerData, Placement
from .profile import parse_profile_outline, compute_bbox_from_pts
from .components import parse_components_file
from .features import parse_layer_data

# Regex to extract NAME from a LAYER block in the matrix file
_MATRIX_LAYER_RE = re.compile(
    r"LAYER\s*\{([^}]+)\}", re.DOTALL
)


def _drill_layer_names_from_matrix(matrix_txt: str) -> List[str]:
    """Return lowercase layer names for every LAYER with TYPE=DRILL."""
    names: List[str] = []
    for m in _MATRIX_LAYER_RE.finditer(matrix_txt):
        block = m.group(1)
        if re.search(r"^\s*TYPE\s*=\s*DRILL\s*$", block, re.MULTILINE):
            nm = re.search(r"^\s*NAME\s*=\s*(\S+)", block, re.MULTILINE)
            if nm:
                names.append(nm.group(1).lower())
    return names


class OdbArchive:
    """Context manager for reading ODB++ .tgz archives."""

    # Standard ODB++ paths
    PROFILE_PATH = "odb/steps/pcb/profile"
    MATRIX_PATH = "odb/matrix/matrix"
    COMP_TOP_PATH = "odb/steps/pcb/layers/comp_+_top/components"
    COMP_BOT_PATH = "odb/steps/pcb/layers/comp_+_bot/components"

    # Layer paths by side
    LAYER_PATHS = {
        "TOP": {
            "copper": "odb/steps/pcb/layers/top/features",
            "soldermask": "odb/steps/pcb/layers/top_solder/features",
            "silkscreen": "odb/steps/pcb/layers/top_overlay/features",
        },
        "BOTTOM": {
            "copper": "odb/steps/pcb/layers/bottom_layer/features",
            "soldermask": "odb/steps/pcb/layers/bottom_solder/features",
            "silkscreen": "odb/steps/pcb/layers/bottom_overlay/features",
        },
    }

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._tar: Optional[tarfile.TarFile] = None

    def __enter__(self) -> "OdbArchive":
        self._tar = tarfile.open(self.path, "r:gz")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._tar:
            self._tar.close()
            self._tar = None

    def _read_text(self, member_name: str) -> str:
        """Read text file from archive."""
        if not self._tar:
            raise RuntimeError("Archive not open. Use 'with OdbArchive(...) as odb:'")
        try:
            member = self._tar.getmember(member_name)
            f = self._tar.extractfile(member)
            if f is None:
                raise FileNotFoundError(member_name)
            return f.read().decode("utf-8", errors="replace")
        except KeyError:
            raise FileNotFoundError(f"Member not found in archive: {member_name}")

    def parse_board(self) -> Board:
        """Parse board outline and component placements."""
        # Parse profile
        profile_txt = self._read_text(self.PROFILE_PATH)
        outline_pts = parse_profile_outline(profile_txt)
        if len(outline_pts) < 3:
            raise ValueError("Profile outline polygon not found (need >= 3 points)")
        bbox_mm = compute_bbox_from_pts(outline_pts)

        # Parse placements
        placements: list[Placement] = []
        try:
            top_txt = self._read_text(self.COMP_TOP_PATH)
            placements.extend(parse_components_file(top_txt, "TOP"))
        except FileNotFoundError:
            pass  # No top components

        try:
            bot_txt = self._read_text(self.COMP_BOT_PATH)
            placements.extend(parse_components_file(bot_txt, "BOTTOM"))
        except FileNotFoundError:
            pass  # No bottom components

        return Board(outline_pts=outline_pts, bbox_mm=bbox_mm, placements=placements)

    def parse_layers(self, side: str) -> FaceLayers:
        """Parse all layer data for one side of the board."""
        if side not in self.LAYER_PATHS:
            raise ValueError(f"Invalid side: {side}. Must be 'TOP' or 'BOTTOM'")

        paths = self.LAYER_PATHS[side]

        copper_txt = self._read_text(paths["copper"])
        soldermask_txt = self._read_text(paths["soldermask"])
        silkscreen_txt = self._read_text(paths["silkscreen"])

        return FaceLayers(
            copper=parse_layer_data(copper_txt),
            soldermask=parse_layer_data(soldermask_txt),
            silkscreen=parse_layer_data(silkscreen_txt),
        )

    def parse_drill(self) -> LayerData | None:
        """Parse all drill layers and merge them into a single LayerData.

        Drill layer names are discovered dynamically from the ODB++ matrix
        file (``TYPE=DRILL``).  All matching layers are merged so that both
        plated and non-plated holes appear.

        Returns ``None`` if no drill layers are found.
        """
        # Discover drill layer names from the matrix
        try:
            matrix_txt = self._read_text(self.MATRIX_PATH)
        except FileNotFoundError:
            return None

        drill_names = _drill_layer_names_from_matrix(matrix_txt)
        if not drill_names:
            return None

        merged: LayerData | None = None
        for name in drill_names:
            feature_path = f"odb/steps/pcb/layers/{name}/features"
            try:
                txt = self._read_text(feature_path)
            except FileNotFoundError:
                continue
            layer = parse_layer_data(txt)
            if merged is None:
                merged = layer
            else:
                # Merge symbols (offset IDs to avoid collisions)
                offset = max(merged.symbols.keys(), default=-1) + 1
                for sid, sym in layer.symbols.items():
                    merged.symbols[sid + offset] = sym
                # Re-map feature sym_ids
                for kind, fdata in layer.features:
                    if kind == "P":
                        x, y, sid = fdata
                        merged.features.append((kind, (x, y, sid + offset)))
                    elif kind == "L":
                        x1, y1, x2, y2, sid = fdata
                        merged.features.append((kind, (x1, y1, x2, y2, sid + offset)))
                    else:
                        merged.features.append((kind, fdata))
        return merged
