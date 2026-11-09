#!/usr/bin/env python3
"""Persistent board-image render daemon.

Why: every CLI invocation pays ~1.3 s of process tax (interpreter + PIL
imports, re-parsing the archive, re-decoding the cached face PNGs) before the
~0.4 s of actual crop+encode work. This daemon is spawned once by a GUI/editor
process and stays alive holding the parsed board and the DECODED face images in
RAM, so each subsequent render request costs only the real work.

Protocol: framed NDJSON over stdio (mirrors the equipment-runner daemon).
One JSON object per line in, one per line out:

    {"id": 1, "cmd": "ping"}
    {"id": 2, "cmd": "render", "odb": "<path>.tgz",
     "img_size": 1024, "render_size": 4096, "png_compress_level": 1,
     "render_cache": "<dir>"|null,
     "views": [{"out_dir": "...", "window_mm": 40.0,
                "cross_arm_mm": 3.0, "cross_thickness_px": 6}, ...],
     "targets": ["C1", "P10:3", ...],
     "parallel_export": true, "max_workers": 0, "batch_size": 50}   (optional,
     the tool's own settings and defaults: the export loop is the tool's)
    {"id": 3, "cmd": "shutdown"}

Responses: {"id": N, "ok": true/false, "error": str|null, ...}.
For "render": {"written": <count>, "missing": [refdes...]} — output files land
in the exact same <out_dir>/images/*.png locations the CLI writes, so callers
re-read them from disk exactly as before.

State invalidation: the board+faces cache is keyed by (odb path, mtime_ns,
size, render_size); a changed archive or render size reloads automatically.

Stdout is reserved for protocol frames: the fd is duplicated at startup and
fd 1 is redirected to stderr, so stray prints from library code can never
corrupt a frame (same hardening as the equipment daemon).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli as _cli  # noqa: E402 — the CLI module IS the render library
from odb_image_generator.models import Config, ViewSpec  # noqa: E402
from odb_image_generator.parsing import OdbArchive  # noqa: E402
from odb_image_generator.rendering import RenderContext  # noqa: E402


class _BoardState:
    """Parsed board + decoded faces for one (archive, render_size)."""

    def __init__(self, key):
        self.key = key                  # (odb_path, mtime_ns, size, render_size)
        self.board = None
        self.ctx = None
        self.faces: dict = {}           # side -> PIL.Image (RGBA, decoded)
        self.by_refdes: dict = {}


class RenderService:
    def __init__(self):
        self._state: _BoardState | None = None

    # -- board / face management ------------------------------------------

    @staticmethod
    def _board_key(odb_path: str, render_size: int):
        st = os.stat(odb_path)
        return (os.path.abspath(odb_path), st.st_mtime_ns, st.st_size, render_size)

    def _ensure_board(self, odb_path: str, render_size: int) -> _BoardState:
        key = self._board_key(odb_path, render_size)
        if self._state is not None and self._state.key == key:
            return self._state
        # New archive / changed archive / different render size: rebuild.
        state = _BoardState(key)
        with OdbArchive(odb_path) as odb:
            state.board = odb.parse_board()
        state.ctx = RenderContext(state.board.bbox_mm, render_size)
        state.by_refdes = _cli.placements_by_refdes(state.board)
        self._state = state
        return state

    def _ensure_faces(self, state: _BoardState, config: Config,
                      sides: list) -> None:
        """Faces for *sides* decoded in RAM: from memory, else the disk render
        cache, else parse+render (and persist to the disk cache)."""
        missing = [s for s in sides if s not in state.faces]
        to_render = []
        for side in missing:
            cached = _cli._load_cached_face(config, side)
            if cached is not None:
                state.faces[side] = cached
            else:
                to_render.append(side)
        if not to_render:
            return
        with OdbArchive(config.odb_path) as odb:
            layer_data = {side: odb.parse_layers(side) for side in to_render}
            drill_data = odb.parse_drill()
        for side in to_render:
            state.faces[side] = _cli.render_board_face(
                config, state.ctx, state.board, layer_data[side], drill_data)
        _cli._save_cached_faces(config, {s: state.faces[s] for s in to_render})

    # -- request handling ---------------------------------------------------

    def render(self, req: dict) -> dict:
        odb_path = req["odb"]
        render_size = int(req.get("render_size", 4096))
        views = [ViewSpec(out_dir=v["out_dir"], window_mm=float(v["window_mm"]),
                          cross_arm_mm=float(v["cross_arm_mm"]),
                          cross_thickness_px=int(v["cross_thickness_px"]))
                 for v in req["views"]]
        config = Config(
            odb_path=odb_path,
            img_size=int(req.get("img_size", 1024)),
            render_size=render_size,
            render_cache=req.get("render_cache"),
            png_compress_level=int(req.get("png_compress_level", 1)),
            quiet=True,
            **{name: req[name] for name in ("parallel_export", "max_workers", "batch_size")
               if name in req},
        )

        state = self._ensure_board(odb_path, render_size)

        # Missing refs are reported back instead of written as 404 images
        # (the callers surface 'no image' themselves).
        tasks, missing = _cli.resolve_targets(state.by_refdes, req.get("targets", []))
        self._ensure_faces(state, config,
                           sorted({p.side for p, _, _ in tasks}))

        # No index.json from the daemon: it would grow without bound across
        # requests and no GUI consumer reads it (files are found by name).
        written = sum(
            _cli.export_view(config, view, state.ctx, state.faces, tasks).count
            for view in views)
        return {"written": written, "missing": [refdes for refdes, _ in missing]}


def main() -> None:
    # Reserve stdout for protocol frames; reroute fd 1 to stderr so library
    # prints can't corrupt frames.
    proto_fd = os.dup(1)
    os.dup2(2, 1)
    proto = os.fdopen(proto_fd, "w", buffering=1)

    service = RenderService()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            proto.write(json.dumps(
                {"id": None, "ok": False, "error": "malformed frame"}) + "\n")
            continue
        rid = req.get("id")
        cmd = req.get("cmd")
        try:
            if cmd == "ping":
                resp = {"id": rid, "ok": True, "error": None}
            elif cmd == "shutdown":
                proto.write(json.dumps(
                    {"id": rid, "ok": True, "error": None}) + "\n")
                return
            elif cmd == "render":
                out = service.render(req)
                resp = {"id": rid, "ok": True, "error": None, **out}
            else:
                resp = {"id": rid, "ok": False, "error": f"unknown cmd {cmd!r}"}
        except Exception as exc:  # noqa: BLE001 — daemon must never die on a request
            resp = {"id": rid, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        proto.write(json.dumps(resp) + "\n")


if __name__ == "__main__":
    main()
