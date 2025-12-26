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


@dataclass
class Placement:
    """Component placement from ODB++ components file."""
    refdes: str
    x_mm: float
    y_mm: float
    rot_deg: float
    side: Literal["TOP", "BOTTOM"]
    pins: List[Pin] = field(default_factory=list)

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
class Config:
    """Configuration for image generation."""
    odb_path: str
    out_dir: str
    img_size: int = 1024
    render_size: int = 8192
    window_mm: float = 40.0
    limit: int = 0  # 0 = no limit
    component: Optional[str] = None  # Filter to single component refdes
    pad: Optional[str] = None  # Center on specific pad name

    # Colors (RGBA)
    background_color: Tuple[int, int, int, int] = (0, 0, 0, 255)
    outline_color: Tuple[int, int, int, int] = (70, 70, 70, 255)
    copper_color: Tuple[int, int, int, int] = (220, 170, 40, 255)
    soldermask_color: Tuple[int, int, int, int] = (20, 60, 30, 255)
    soldermask_alpha: int = 220
    silkscreen_color: Tuple[int, int, int, int] = (245, 245, 245, 220)
    top_marker_color: Tuple[int, int, int, int] = (255, 0, 0, 255)
    bottom_marker_color: Tuple[int, int, int, int] = (0, 140, 255, 255)
