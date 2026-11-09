"""The tool and the render daemon share one target resolution and one export loop."""

import os
import sys
from types import SimpleNamespace

# Make the package importable when run directly or via pytest (no conftest here).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

import cli  # noqa: E402
import render_daemon  # noqa: E402
from odb_image_generator.models import Config, Pin, Placement, ViewSpec  # noqa: E402
from odb_image_generator.rendering import RenderContext  # noqa: E402


def _placement(refdes: str, x: float, y: float, side: str = "TOP") -> Placement:
    return Placement(refdes=refdes, x_mm=x, y_mm=y, rot_deg=0.0, side=side,
                     pins=[Pin(name="1", x_mm=x + 1.0, y_mm=y + 1.0)])


def _board(count: int = 6):
    placements = [_placement(f"R{n}", 10.0 + 12 * n, 20.0 + 9 * n) for n in range(1, count + 1)]
    return SimpleNamespace(placements=placements + [_placement("R1", 90.0, 90.0)])   # R1 placed twice


def test_targets_resolve_to_the_first_placement_and_name_what_is_missing():
    by_refdes = cli.placements_by_refdes(_board())

    tasks, missing = cli.resolve_targets(by_refdes, ["R1", "R2:1,ZZ9", "ZZ8:4"])

    assert [(p.refdes, p.x_mm, pad, strict) for p, pad, strict in tasks] == [
        ("R1", 22.0, None, False), ("R2", 34.0, "1", True)]
    assert missing == [("ZZ9", None), ("ZZ8", "4")]


def test_a_limit_caps_the_tasks():
    by_refdes = cli.placements_by_refdes(_board())

    tasks, _ = cli.resolve_targets(by_refdes, ["R1", "R2", "R3"], limit=2)

    assert [p.refdes for p, _, _ in tasks] == ["R1", "R2"]


def _export(folder, **settings) -> dict:
    ctx = RenderContext((0.0, 0.0, 100.0, 100.0), 512)
    face = Image.linear_gradient("L").resize((512, 512)).convert("RGBA")
    config = Config(odb_path="board.tgz", img_size=64, render_size=512, quiet=True, **settings)
    tasks, _ = cli.resolve_targets(cli.placements_by_refdes(_board()),
                                   ["R1", "R2:1", "R3", "R4", "R5", "R6:9"])
    view = ViewSpec(out_dir=str(folder), window_mm=20.0, cross_arm_mm=2.0, cross_thickness_px=2)
    writer = cli.export_view(config, view, ctx, {"TOP": face}, tasks)
    files = {path.name: path.read_bytes() for path in (folder / "images").iterdir()}
    assert writer.count == len(files)
    return files


def test_pictures_are_the_same_one_by_one_or_in_parallel(tmp_path):
    one_by_one = _export(tmp_path / "a", parallel_export=False)
    in_parallel = _export(tmp_path / "b", parallel_export=True, max_workers=4)

    assert sorted(one_by_one) == ["R1.png", "R2_pad1.png", "R3.png", "R4.png", "R5.png",
                                  "R6_pad9_404.png"]
    assert in_parallel == one_by_one


def test_the_daemon_exports_through_the_tools_loop_with_the_requests_settings(monkeypatch):
    service = render_daemon.RenderService()
    state = SimpleNamespace(by_refdes=cli.placements_by_refdes(_board()), ctx=None, faces={})
    monkeypatch.setattr(service, "_ensure_board", lambda odb, size: state)
    monkeypatch.setattr(service, "_ensure_faces", lambda *args: None)
    calls = []

    def export_view(config, view, ctx, faces, tasks):
        calls.append((config, view.out_dir, [p.refdes for p, _, _ in tasks]))
        return SimpleNamespace(count=len(tasks))

    monkeypatch.setattr(cli, "export_view", export_view)
    request = {"odb": "board.tgz", "targets": ["R1", "R2:1", "ZZ9"],
               "views": [{"out_dir": out, "window_mm": 40, "cross_arm_mm": 3, "cross_thickness_px": 6}
                         for out in ("zoomed", "wide")]}

    answer = service.render({**request, "parallel_export": False, "max_workers": 3, "batch_size": 7})

    assert answer == {"written": 4, "missing": ["ZZ9"]}
    assert [(out, names) for _, out, names in calls] == [("zoomed", ["R1", "R2"]), ("wide", ["R1", "R2"])]
    config = calls[0][0]
    assert (config.parallel_export, config.max_workers, config.batch_size) == (False, 3, 7)

    calls.clear()
    service.render(request)                                   # nothing said: the tool's defaults
    config = calls[0][0]
    assert (config.parallel_export, config.max_workers, config.batch_size) == (True, 0, 50)
