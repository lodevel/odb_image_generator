"""ODB++ archive handling.

Layer names are discovered dynamically from the ODB++ matrix file so
the code works with any naming convention used by the PCB tool that
exported the archive.
"""

import re
import tarfile
from pathlib import Path
from typing import Dict, List, Optional

from ..models import Board, FaceLayers, LayerData, Placement
from .profile import parse_profile_outline, compute_bbox_from_pts
from .components import parse_components_file
from .features import parse_layer_data

# ---------------------------------------------------------------------------
# Matrix parsing helpers
# ---------------------------------------------------------------------------

_MATRIX_LAYER_RE = re.compile(r"LAYER\s*\{([^}]+)\}", re.DOTALL)


def _parse_matrix_layers(matrix_txt: str) -> List[Dict[str, str]]:
    """Parse every LAYER block from the matrix file into a list of dicts."""
    layers: List[Dict[str, str]] = []
    for m in _MATRIX_LAYER_RE.finditer(matrix_txt):
        block = m.group(1)
        entry: Dict[str, str] = {}
        for line in block.splitlines():
            line = line.strip()
            if "=" in line:
                key, _, val = line.partition("=")
                entry[key.strip()] = val.strip()
        if "NAME" in entry:
            layers.append(entry)
    return layers


def _layers_by_type(
    matrix_layers: List[Dict[str, str]], layer_type: str
) -> List[Dict[str, str]]:
    """Filter matrix layers by TYPE, sorted by ROW ascending."""
    filtered = [
        l for l in matrix_layers
        if l.get("TYPE", "").upper() == layer_type.upper()
    ]
    filtered.sort(key=lambda l: int(l.get("ROW", "0")))
    return filtered


def _discover_face_layers(
    matrix_txt: str,
) -> Dict[str, Dict[str, Optional[str]]]:
    """Discover copper/soldermask/silkscreen layer names per side.

    Strategy:
    * **SIGNAL** layers sorted by ROW — first = top copper, last = bottom.
    * **SOLDER_MASK** and **SILK_SCREEN** are assigned to the side whose
      copper ROW is closest.
    """
    all_layers = _parse_matrix_layers(matrix_txt)

    signals = _layers_by_type(all_layers, "SIGNAL")

    result: Dict[str, Dict[str, Optional[str]]] = {
        "TOP": {"copper": None, "soldermask": None, "silkscreen": None},
        "BOTTOM": {"copper": None, "soldermask": None, "silkscreen": None},
    }

    if signals:
        result["TOP"]["copper"] = signals[0]["NAME"].lower()
        result["BOTTOM"]["copper"] = signals[-1]["NAME"].lower()

    top_row = int(signals[0]["ROW"]) if signals else 0
    bot_row = int(signals[-1]["ROW"]) if signals else 9999

    for layer_type, key in [
        ("SOLDER_MASK", "soldermask"),
        ("SILK_SCREEN", "silkscreen"),
    ]:
        candidates = _layers_by_type(all_layers, layer_type)
        for c in candidates:
            row = int(c.get("ROW", "0"))
            if abs(row - top_row) <= abs(row - bot_row):
                if result["TOP"][key] is None:
                    result["TOP"][key] = c["NAME"].lower()
            else:
                if result["BOTTOM"][key] is None:
                    result["BOTTOM"][key] = c["NAME"].lower()

    return result


# ---------------------------------------------------------------------------
# Archive class
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

_INCH_TO_MM = 25.4


def _detect_units(text: str) -> float:
    """Return the scale factor to convert coordinates in *text* to mm.

    Looks for a ``UNITS=INCH`` or ``UNITS=MM`` line near the top of the file.
    Returns 25.4 for inches, 1.0 for mm (the default).
    """
    for line in text.splitlines()[:30]:
        stripped = line.strip().upper()
        if stripped.startswith("UNITS"):
            if "INCH" in stripped:
                return _INCH_TO_MM
            return 1.0
    return 1.0


class OdbArchive:
    """Context manager for reading ODB++ .tgz archives."""

    PROFILE_PATH = "odb/steps/pcb/profile"
    MATRIX_PATH = "odb/matrix/matrix"
    COMP_TOP_PATH = "odb/steps/pcb/layers/comp_+_top/components"
    COMP_BOT_PATH = "odb/steps/pcb/layers/comp_+_bot/components"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._tar: Optional[tarfile.TarFile] = None
        self._matrix_txt: Optional[str] = None

    def __enter__(self) -> "OdbArchive":
        self._tar = tarfile.open(self.path, "r:gz")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._tar:
            self._tar.close()
            self._tar = None

    def _read_text(self, member_name: str) -> str:
        """Read a text file from the archive."""
        if not self._tar:
            raise RuntimeError(
                "Archive not open. Use 'with OdbArchive(...) as odb:'"
            )
        try:
            member = self._tar.getmember(member_name)
            f = self._tar.extractfile(member)
            if f is None:
                raise FileNotFoundError(member_name)
            return f.read().decode("utf-8", errors="replace")
        except KeyError:
            raise FileNotFoundError(
                f"Member not found in archive: {member_name}"
            )

    def _matrix(self) -> str:
        """Return (cached) matrix text."""
        if self._matrix_txt is None:
            self._matrix_txt = self._read_text(self.MATRIX_PATH)
        return self._matrix_txt

    # ── board ──────────────────────────────────────────────────────────

    def parse_board(self) -> Board:
        """Parse board outline and component placements."""
        profile_txt = self._read_text(self.PROFILE_PATH)
        scale = _detect_units(profile_txt)
        outline_pts = parse_profile_outline(profile_txt, scale)
        if len(outline_pts) < 3:
            raise ValueError(
                "Profile outline polygon not found (need >= 3 points)"
            )
        bbox_mm = compute_bbox_from_pts(outline_pts)

        placements: list[Placement] = []
        try:
            top_txt = self._read_text(self.COMP_TOP_PATH)
            placements.extend(parse_components_file(top_txt, "TOP"))
        except FileNotFoundError:
            pass
        try:
            bot_txt = self._read_text(self.COMP_BOT_PATH)
            placements.extend(parse_components_file(bot_txt, "BOTTOM"))
        except FileNotFoundError:
            pass

        return Board(
            outline_pts=outline_pts,
            bbox_mm=bbox_mm,
            placements=placements,
        )

    # ── layers (dynamic from matrix) ──────────────────────────────────

    def parse_layers(self, side: str) -> FaceLayers:
        """Parse copper, soldermask, and silkscreen for *side*.

        Layer names are discovered from the ODB++ matrix file so the code
        works regardless of the naming convention used by the exporting tool.
        """
        if side not in ("TOP", "BOTTOM"):
            raise ValueError(
                f"Invalid side: {side}. Must be 'TOP' or 'BOTTOM'"
            )

        face_map = _discover_face_layers(self._matrix())
        names = face_map[side]

        def _read_layer(key: str) -> LayerData:
            name = names.get(key)
            if name is None:
                return LayerData()
            path = f"odb/steps/pcb/layers/{name}/features"
            try:
                txt = self._read_text(path)
                return parse_layer_data(txt, _detect_units(txt))
            except FileNotFoundError:
                return LayerData()

        return FaceLayers(
            copper=_read_layer("copper"),
            soldermask=_read_layer("soldermask"),
            silkscreen=_read_layer("silkscreen"),
        )

    # ── drill (merged from all TYPE=DRILL) ────────────────────────────

    def parse_drill(self) -> LayerData | None:
        """Parse all drill layers and merge into a single LayerData.

        Drill layer names are discovered from the matrix (``TYPE=DRILL``).
        Returns ``None`` if no drill layers exist.
        """
        try:
            matrix_txt = self._matrix()
        except FileNotFoundError:
            return None

        all_layers = _parse_matrix_layers(matrix_txt)
        drill_names = [
            l["NAME"].lower() for l in _layers_by_type(all_layers, "DRILL")
        ]
        if not drill_names:
            return None

        merged: LayerData | None = None
        for name in drill_names:
            feature_path = f"odb/steps/pcb/layers/{name}/features"
            try:
                txt = self._read_text(feature_path)
            except FileNotFoundError:
                continue
            layer = parse_layer_data(txt, _detect_units(txt))
            if merged is None:
                merged = layer
            else:
                offset = max(merged.symbols.keys(), default=-1) + 1
                for sid, sym in layer.symbols.items():
                    merged.symbols[sid + offset] = sym
                for kind, fdata in layer.features:
                    if kind == "P":
                        x, y, sid = fdata
                        merged.features.append(
                            (kind, (x, y, sid + offset))
                        )
                    elif kind == "L":
                        x1, y1, x2, y2, sid = fdata
                        merged.features.append(
                            (kind, (x1, y1, x2, y2, sid + offset))
                        )
                    else:
                        merged.features.append((kind, fdata))
        return merged
