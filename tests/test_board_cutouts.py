"""Board cutouts: profile hole contours and rout-layer cutouts are parsed and
punched through every rendered layer. All data is synthetic."""

import io
import os
import sys
import tarfile

# Make the package importable when run directly or via pytest (no conftest here).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import cli  # noqa: E402
from odb_image_generator.models import Config, FaceLayers, LayerData, Symbol  # noqa: E402
from odb_image_generator.parsing import OdbArchive  # noqa: E402
from odb_image_generator.parsing.profile import (  # noqa: E402
    parse_profile_holes,
    parse_profile_outline,
)
from odb_image_generator.parsing.rout import parse_rout_chains, rout_cutouts  # noqa: E402
from odb_image_generator.rendering import RenderContext  # noqa: E402

# A 100 x 60 mm board with a 20 x 10 mm hole contour and a round hole (one
# full-circle arc, the way ODB++ writes a circle).
PROFILE_WITH_HOLES = """UNITS=MM
#
S P 0
OB 0 0 I
OS 0 60
OS 100 60
OS 100 0
OS 0 0
OE
OB 10 10 H
OS 30 10
OS 30 20
OS 10 20
OS 10 10
OE
OB 75 30 H
OC 75 30 70 30 Y
OE
SE
"""

PROFILE_OUTLINE_ONLY = """UNITS=MM
S P 0
OB 0 0 I
OS 0 60
OS 100 60
OS 100 0
OS 0 0
OE
SE
"""

# Rout layer: the board edge, one closed cutout at (40..60, 30..50) with an
# arc corner, and an open path (a slot that does not close).
ROUT_FEATURES = """UNITS=MM
$0 r254
@0 .rout_chain
L 0 0 0 60 0 P 0 ;0=1
L 0 60 100 60 0 P 0 ;0=1
L 100 60 100 0 0 P 0 ;0=1
L 100 0 0 0 0 P 0 ;0=1
#
L 40 30 58 30 0 P 0 ;0=2
A 58 30 60 32 58 32 0 P 0 N ;0=2
L 60 32 60 50 0 P 0 ;0=2
L 60 50 40 50 0 P 0 ;0=2
L 40 50 40 30 0 P 0 ;0=2
#
L 80 5 90 5 0 P 0 ;0=3
"""

MATRIX = """STEP {
   COL=1
   NAME=PCB
}
LAYER {
   ROW=1
   CONTEXT=BOARD
   TYPE=SIGNAL
   NAME=TOP
   POLARITY=POSITIVE
}
LAYER {
   ROW=2
   CONTEXT=BOARD
   TYPE=ROUT
   NAME=rout
   POLARITY=POSITIVE
}
"""


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def test_profile_outline_excludes_hole_contours():
    outline = parse_profile_outline(PROFILE_WITH_HOLES)
    assert _bbox(outline) == (0, 0, 100, 60)
    assert (10, 10) not in outline and (30, 20) not in outline


def test_profile_hole_contours_are_cutouts():
    holes = parse_profile_holes(PROFILE_WITH_HOLES)
    assert len(holes) == 2
    assert _bbox(holes[0]) == (10, 10, 30, 20)
    # The full-circle arc becomes a closed polygon of radius 5 around (70, 30).
    xmin, ymin, xmax, ymax = _bbox(holes[1])
    assert abs(xmin - 65) < 1e-6 and abs(xmax - 75) < 1e-6
    assert abs(ymin - 25) < 0.1 and abs(ymax - 35) < 0.1
    assert len(holes[1]) > 8


def test_rout_keeps_only_closed_chains_inside_the_outline():
    outline = parse_profile_outline(PROFILE_OUTLINE_ONLY)
    chains = parse_rout_chains(ROUT_FEATURES)
    assert len(chains) == 3                     # edge, cutout, open slot
    cutouts = rout_cutouts(chains, outline)
    assert len(cutouts) == 1
    xmin, ymin, xmax, ymax = _bbox(cutouts[0])
    assert (xmin, ymin, ymax) == (40, 30, 50)
    assert abs(xmax - 60) < 1e-6


def _write_archive(path, files):
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_rout_cutout_is_punched_through_every_layer(tmp_path):
    archive = tmp_path / "board.tgz"
    _write_archive(archive, {
        "odb/matrix/matrix": MATRIX,
        "odb/steps/pcb/profile": PROFILE_OUTLINE_ONLY,
        "odb/steps/pcb/layers/rout/features": ROUT_FEATURES,
    })
    with OdbArchive(archive) as odb:
        board = odb.parse_board()
    assert len(board.cutouts) == 1

    # Copper pad and a silkscreen stroke right over the cutout centre (50, 40).
    pen = {0: Symbol("circle", (4.0,))}
    layers = FaceLayers(
        copper=LayerData(symbols=pen, features=[("P", (50.0, 40.0, 0))]),
        soldermask=LayerData(),
        silkscreen=LayerData(symbols=pen, features=[("L", (35.0, 40.0, 65.0, 40.0, 0))]),
    )
    config = Config(odb_path=str(archive))
    ctx = RenderContext(board.bbox_mm, 512)
    img = cli.render_board_face(config, ctx, board, layers, None)

    hole = img.getpixel(ctx.mm_to_px(50, 40))
    assert hole == config.background_color
    board_px = img.getpixel(ctx.mm_to_px(20, 40))
    assert board_px != config.background_color  # board material outside the cutout
    # The silkscreen stroke still shows where it leaves the cutout.
    assert img.getpixel(ctx.mm_to_px(37, 40)) != config.background_color


def test_board_without_cutouts_has_none(tmp_path):
    archive = tmp_path / "board.tgz"
    _write_archive(archive, {
        "odb/matrix/matrix": MATRIX,
        "odb/steps/pcb/profile": PROFILE_OUTLINE_ONLY,
    })
    with OdbArchive(archive) as odb:
        assert odb.parse_board().cutouts == []
