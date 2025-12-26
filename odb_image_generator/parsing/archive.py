"""ODB++ archive handling."""

import tarfile
from pathlib import Path
from typing import Optional

from ..models import Board, FaceLayers, Placement
from .profile import parse_profile_outline, compute_bbox_from_pts
from .components import parse_components_file
from .features import parse_layer_data


class OdbArchive:
    """Context manager for reading ODB++ .tgz archives."""

    # Standard ODB++ paths
    PROFILE_PATH = "odb/steps/pcb/profile"
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
