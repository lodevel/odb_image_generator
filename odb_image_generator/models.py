"""Data models for ODB++ image generator."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple


@dataclass
class Symbol:
    """Aperture/symbol definition from ODB++ features file."""
    kind: str  # "circle", "rect", "oval", "unknown"
    params: Tuple[float, ...]  # Dimensions in mm

    @property
    def is_valid(self) -> bool:
        return self.kind != "unknown"


@dataclass
class Pin:
    """Component pin/pad from ODB++ components file."""
    name: str           # Pin name (e.g., "1", "2", "A1")
    x_mm: float         # Absolute X position on board (not relative to component)
    y_mm: float         # Absolute Y position on board (not relative to component)
    rot_deg: float = 0.0  # Pin rotation
    net_num: int = -1   # index into Board.net_names (-1 = unknown / no EDA data)


@dataclass
class Placement:
    """Component placement from ODB++ components file."""
    refdes: str
    x_mm: float
    y_mm: float
    rot_deg: float
    side: Literal["TOP", "BOTTOM"]
    pins: List[Pin] = field(default_factory=list)
    # Raw, uninterpreted component properties (name -> value) parsed from CMP
    # trailing attrs ("_cmp_attrs") and PRP records. The LLM decides which
    # field is a plausible part number; we never heuristically guess the MPN.
    properties: Dict[str, str] = field(default_factory=dict)

    def get_pad_position(self, pad_name: str) -> Optional[Tuple[float, float]]:
        """Get absolute position of a pad by name.
        
        ODB++ stores pin coordinates as absolute board positions.
        Returns None if pad not found.
        """
        for pin in self.pins:
            if pin.name == pad_name:
                # Pin coordinates are already absolute in ODB++
                return (pin.x_mm, pin.y_mm)
        return None


@dataclass
class Board:
    """Parsed board data from ODB++ archive."""
    outline_pts: List[Tuple[float, float]]
    bbox_mm: Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
    placements: List[Placement] = field(default_factory=list)
    net_names: List[str] = field(default_factory=list)  # net_num -> net name (EDA)
    # Holes through the board inside the outline (profile H contours + closed
    # rout-layer chains), each a closed polygon in mm.
    cutouts: List[List[Tuple[float, float]]] = field(default_factory=list)

    @property
    def width_mm(self) -> float:
        return self.bbox_mm[2] - self.bbox_mm[0]

    @property
    def height_mm(self) -> float:
        return self.bbox_mm[3] - self.bbox_mm[1]


@dataclass
class LayerData:
    """Parsed layer data (symbols + features) for rendering."""
    symbols: Dict[int, Symbol] = field(default_factory=dict)
    features: List[Tuple[str, Any]] = field(default_factory=list)

    def get_symbol(self, sym_id: int) -> Symbol:
        return self.symbols.get(sym_id, Symbol("unknown", ()))


@dataclass
class FaceLayers:
    """All layer data for one side of the board (TOP or BOTTOM)."""
    copper: LayerData
    soldermask: LayerData
    silkscreen: LayerData


@dataclass
class ViewSpec:
    """One output view: where to write and how to crop/annotate.

    A single CLI run can emit several views (e.g. zoomed + wide) from the same
    rendered board faces — the face render does not depend on these values.
    """
    out_dir: str
    window_mm: float
    cross_arm_mm: float
    cross_thickness_px: int


@dataclass
class Config:
    """Configuration for image generation."""
    odb_path: str
    out_dir: Optional[str] = None
    img_size: int = 1024
    render_size: int = 4096
    window_mm: float = 40.0
    limit: int = 0  # 0 = no limit
    component: Optional[str] = None  # Filter to single component refdes
    pad: Optional[str] = None  # Center on specific pad name
    targets: List[str] = field(default_factory=list)  # --target entries: REFDES or REFDES:PAD
    all_components: bool = False  # Render every component at its center
    all_pins: bool = False        # Render every pin of every component
    list_components: bool = False  # List components/pins as JSON (no rendering)
    list_file: Optional[str] = None  # Write component list JSON to file
    list_nets: bool = False  # List netlist (nets -> pins) + per-pin nets as JSON
    list_property_fields: bool = False  # List property-field schema (sorted JSON array)
    # --list projection / filter (None = full default; backward-compatible)
    fields: Optional[List[str]] = None  # project 'properties' to these field names
    filter_kv: Optional[Tuple[str, str]] = None  # (KEY, VALUE) row filter, case-insens value
    refdes_prefixes: Optional[Tuple[str, ...]] = None  # keep only these refdes prefixes (e.g. U,IC)
    cross_arm_mm: float = 1.5
    cross_thickness_px: int = 3

    # Multi-view emission (--view): when non-empty, supersedes the single
    # out_dir/window_mm/cross_* trio; each view crops from the same face render.
    views: List[ViewSpec] = field(default_factory=list)
    # Directory for cached full-board face renders (--render-cache). None = off.
    render_cache: Optional[str] = None
    # zlib level for output PNGs. 1 = fast (~2% larger files, identical pixels).
    png_compress_level: int = 1

    # Parallel processing
    parallel_render: bool = False  # Render TOP/BOTTOM faces sequentially (parallel doubles peak memory)
    parallel_export: bool = True   # Export components in parallel batches
    max_workers: int = 0           # 0 = auto-detect based on CPU count
    batch_size: int = 50           # Components per batch (memory management)
    quiet: bool = False            # Suppress progress output

    # Colors (RGBA)
    background_color: Tuple[int, int, int, int] = (0, 0, 0, 255)
    outline_color: Tuple[int, int, int, int] = (70, 70, 70, 255)
    copper_color: Tuple[int, int, int, int] = (220, 170, 40, 255)
    soldermask_color: Tuple[int, int, int, int] = (20, 60, 30, 255)
    soldermask_alpha: int = 220
    silkscreen_color: Tuple[int, int, int, int] = (245, 245, 245, 220)
    top_marker_color: Tuple[int, int, int, int] = (255, 0, 0, 255)
    bottom_marker_color: Tuple[int, int, int, int] = (0, 140, 255, 255)
