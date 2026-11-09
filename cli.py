#!/usr/bin/env python3
"""CLI entry point for ODB++ component image generator."""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Tuple, Dict, List

from PIL import Image, ImageOps

from odb_image_generator.models import Board, Config, Placement, ViewSpec
from odb_image_generator.parsing import OdbArchive
from odb_image_generator.rendering import (
    RenderContext,
    Compositor,
    BoardLayer,
    CutoutLayer,
    CopperLayer,
    DrillLayer,
    SoldermaskLayer,
    SilkscreenLayer,
)
from odb_image_generator.export import (
    Cropper,
    draw_cross_center,
    draw_side_banner,
    generate_404_image,
    ImageWriter,
)
from odb_image_generator.parallel import (
    parallel_map,
    get_optimal_workers,
    batch_items,
    safe_tqdm,
    safe_tqdm_write,
)


# ---------------------------------------------------------------------------
# Helpers for --list, --all-components, --all-pins
# ---------------------------------------------------------------------------

def _natural_sort_key(text: str) -> list:
    """Sort key for natural ordering (R1, R2, R10 instead of R1, R10, R2).

    Splits *text* into alternating non-digit / digit groups so that
    numeric sub-strings are compared by value rather than lexicographically.
    """
    parts: list = []
    for match in re.finditer(r"(\d+)|(\D+)", text):
        if match.group(1):
            parts.append(("", int(match.group(1))))
        else:
            parts.append((match.group(2), 0))
    return parts


def _build_property_fields(board: Board) -> list:
    """Return the sorted union of every component property field NAME on the board.

    This is the *schema* an LLM discovers before deciding which columns to
    pull. Field names are board/EDA/PLM-specific (e.g. ``Manufacturer_Reference``,
    ``Type``, ``Package``, ``_cmp_attrs`` on one board; arbitrary on the next) —
    so we report exactly the keys present, never a hardcoded list.
    """
    keys: set = set()
    for placement in board.placements:
        keys.update(placement.properties.keys())
    return sorted(keys)


def _project_properties(
    props: dict,
    fields: list | None,
) -> dict:
    """Return *props* narrowed to *fields* (in the requested order).

    ``fields=None`` -> return *props* unchanged (full default, backward-compat).
    A requested field missing on a given component is simply omitted (no null
    padding) so the projection stays faithful to what the board actually carries.
    """
    if fields is None:
        return props
    return {k: props[k] for k in fields if k in props}


def _component_matches_filter(
    props: dict,
    filter_kv: Tuple[str, str] | None,
) -> bool:
    """True when *props* satisfies *filter_kv* ``(KEY, VALUE)``.

    ``filter_kv=None`` -> always True (no filter). The value comparison is
    case-insensitive (e.g. ``Type=Pad`` matches ``Pad``/``pad``/``PAD``); the
    KEY must be present and its value equal to VALUE ignoring case.
    """
    if filter_kv is None:
        return True
    key, value = filter_kv
    if key not in props:
        return False
    return str(props[key]).strip().lower() == value.strip().lower()


def _refdes_matches_prefix(
    refdes: str,
    prefixes: Tuple[str, ...] | None,
) -> bool:
    """True when *refdes* is one of *prefixes* immediately followed by a digit.

    ``prefixes=None`` -> always True (no prefix filter). The prefix must be
    followed by a DIGIT (e.g. ``U`` matches ``U1``/``U11.2`` but NOT ``UART_DE``)
    so a refdes FAMILY (``U,IC`` = ICs) is selected, not every refdes that merely
    starts with the letter. This mirrors the PUSH path's ``^(?:U|IC)\\d`` IC
    pre-filter (the near-universal IPC convention), but with caller-supplied
    prefixes. The refdes is lowercased for the comparison, so *prefixes* must
    already be lowercase (``_parse_refdes_prefix_spec`` guarantees this).
    """
    if not prefixes:
        return True
    low = (refdes or "").lower()
    for p in prefixes:
        if low.startswith(p) and len(low) > len(p) and low[len(p)].isdigit():
            return True
    return False


def _build_component_list(
    board: Board,
    fields: list | None = None,
    filter_kv: Tuple[str, str] | None = None,
    refdes_prefixes: Tuple[str, ...] | None = None,
) -> list:
    """Return a sorted list of ``{refdes, side, pins, properties}`` dicts.

    - *fields* (``None`` = all): project ``properties`` to ONLY these field
      names, preserving the requested order. Backward-compatible: when ``None``
      the full raw ``properties`` dict is emitted exactly as before.
    - *filter_kv* (``None`` = no filter): keep only components whose property
      ``KEY`` equals ``VALUE`` (case-insensitive value match).
    - *refdes_prefixes* (``None`` = no filter): keep only components whose refdes
      starts with one of these (case-insensitive) prefixes, e.g. ``("u","ic")``
      to get just the ICs. Composes with *fields* / *filter_kv*.
    """
    components = []
    for placement in board.placements:
        if not _component_matches_filter(placement.properties, filter_kv):
            continue
        if not _refdes_matches_prefix(placement.refdes, refdes_prefixes):
            continue
        pin_names = sorted(
            (pin.name for pin in placement.pins),
            key=_natural_sort_key,
        )
        components.append({
            "refdes": placement.refdes,
            "side": placement.side,
            "pins": pin_names,
            "properties": _project_properties(placement.properties, fields),
        })
    components.sort(key=lambda c: _natural_sort_key(c["refdes"]))
    return components


def _output_property_fields(board: Board) -> None:
    """Print the sorted property-field schema as a JSON list to stdout."""
    print(json.dumps(_build_property_fields(board), indent=2))


def _output_component_list(
    board: Board,
    list_file: str | None,
    fields: list | None = None,
    filter_kv: Tuple[str, str] | None = None,
    refdes_prefixes: Tuple[str, ...] | None = None,
) -> None:
    """Print component/pin listing as JSON to stdout.

    Always writes machine-readable JSON to stdout.  When *list_file* is
    given the same JSON is also written to that path (status printed to
    stderr so it doesn't pollute the JSON stream). *fields* / *filter_kv* /
    *refdes_prefixes* narrow the property columns / rows / refdes families
    (see :func:`_build_component_list`).
    """
    components = _build_component_list(
        board, fields=fields, filter_kv=filter_kv,
        refdes_prefixes=refdes_prefixes)
    json_str = json.dumps(components, indent=2)

    if list_file:
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                f.write(json_str)
            print(f"Component list written to: {list_file}", file=sys.stderr)
        except OSError as exc:
            print(f"ERROR: Failed to write {list_file}: {exc}", file=sys.stderr)
            sys.exit(1)

    print(json_str)


def _build_net_list(board: Board) -> dict:
    """Return ``{components, nets}`` with net names resolved from the EDA netlist.

    - ``components``: ``[{refdes, side, pins:[{name, net}]}]`` — ``net`` is the
      resolved name or ``null`` when unknown / no EDA data.
    - ``nets``: ``[{net, nodes:[{refdes, pin}]}]`` — the unconnected pseudo-net
      (``$NONE$``) and unknown nets are omitted here (pins still carry them).

    Graceful with no EDA data: ``board.net_names`` is empty, every ``net`` is
    ``null`` and ``nets`` is ``[]`` — no error.
    """
    names = board.net_names

    def net_of(pin) -> str | None:
        i = getattr(pin, "net_num", -1)
        return names[i] if 0 <= i < len(names) else None

    components: list = []
    net_map: dict = {}
    for pl in board.placements:
        pin_entries = []
        for pin in pl.pins:
            net = net_of(pin)
            pin_entries.append({"name": pin.name, "net": net})
            if net and net != "$NONE$":
                net_map.setdefault(net, []).append(
                    {"refdes": pl.refdes, "pin": pin.name})
        pin_entries.sort(key=lambda p: _natural_sort_key(p["name"]))
        components.append(
            {"refdes": pl.refdes, "side": pl.side, "pins": pin_entries,
             "properties": pl.properties})
    components.sort(key=lambda c: _natural_sort_key(c["refdes"]))

    nets = [
        {"net": n,
         "nodes": sorted(nodes, key=lambda x: (_natural_sort_key(x["refdes"]),
                                               _natural_sort_key(x["pin"])))}
        for n, nodes in net_map.items()
    ]
    nets.sort(key=lambda e: _natural_sort_key(e["net"]))
    return {"components": components, "nets": nets}


def _output_net_list(board: Board) -> None:
    """Print the netlist (nets + per-pin nets) as JSON to stdout."""
    print(json.dumps(_build_net_list(board), indent=2))


def _generate_all_targets(
    placements: List[Placement],
    all_pins: bool,
    limit: int = 0,
) -> List[str]:
    """Build target specs for ``--all-components`` or ``--all-pins``.

    Expands bulk selection flags into the explicit ``REFDES`` /
    ``REFDES:PAD`` strings consumed by the ``--target`` pipeline.

    When *limit* is non-zero and *all_pins* is ``False`` the list is
    truncated to the first *limit* components.
    """
    targets: List[str] = []
    for placement in placements:
        if not all_pins and limit and len(targets) >= limit:
            break
        if all_pins:
            # Components with no pins are silently skipped
            for pin in sorted(placement.pins, key=lambda p: _natural_sort_key(p.name)):
                targets.append(f"{placement.refdes}:{pin.name}")
        else:
            targets.append(placement.refdes)
    return targets


def _parse_fields_spec(raw: str | None) -> List[str] | None:
    """Parse ``--fields a,b,c`` into a de-duplicated ordered list (or ``None``).

    ``None`` / empty input -> ``None`` (meaning "all properties", the default).
    Whitespace around each name is trimmed; blanks dropped; order preserved.
    """
    if raw is None:
        return None
    fields: List[str] = []
    for name in (part.strip() for part in raw.split(",")):
        if name and name not in fields:
            fields.append(name)
    return fields or None


def _parse_refdes_prefix_spec(raw: str | None) -> Tuple[str, ...] | None:
    """Parse ``--refdes-prefix U,IC`` into a lowercased prefix tuple (or ``None``).

    ``None`` / empty input -> ``None`` (meaning "no prefix filter", the default).
    Each prefix is trimmed and lowercased (the match is case-insensitive); blanks
    dropped; order/dups don't matter for matching. Returns ``None`` when nothing
    usable remains so callers can treat it as "all components".
    """
    if raw is None:
        return None
    prefixes: List[str] = []
    for name in (part.strip().lower() for part in raw.split(",")):
        if name and name not in prefixes:
            prefixes.append(name)
    return tuple(prefixes) or None


def _parse_filter_spec(raw: str | None) -> Tuple[str, str] | None:
    """Parse ``--filter KEY=VALUE`` into ``(KEY, VALUE)`` (or ``None``).

    Splits on the FIRST ``=`` only, so VALUE may itself contain ``=``. KEY is
    trimmed; VALUE keeps any internal characters (trailing/leading space
    stripped at match time). Returns ``None`` when *raw* is ``None``.
    """
    if raw is None:
        return None
    key, sep, value = raw.partition("=")
    if not sep:
        return ("", "")  # signals "malformed" to the validator (no '=')
    return (key.strip(), value)


def _parse_target_spec(raw: str) -> List[Tuple[str, str | None]]:
    """Parse a single ``--target`` value into ``(refdes, pad|None)`` pairs.

    Supports comma-separated lists: ``"C45:1,R1"`` → ``[("C45","1"),("R1",None)]``.
    """
    specs: List[Tuple[str, str | None]] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        refdes, sep, pad = item.partition(":")
        refdes = refdes.strip()
        pad = pad.strip() if sep else ""
        specs.append((refdes, pad if sep else None))
    return specs


def placements_by_refdes(board: Board) -> Dict[str, List[Placement]]:
    """Every placement of the board, under its reference designator."""
    found: Dict[str, List[Placement]] = {}
    for placement in board.placements:
        found.setdefault(placement.refdes, []).append(placement)
    return found


def resolve_targets(
    by_refdes: Dict[str, List[Placement]],
    targets: List[str],
    limit: int = 0,
) -> Tuple[List[Tuple[Placement, str | None, bool]], List[Tuple[str, str | None]]]:
    """The export tasks for ``REFDES`` / ``REFDES:PAD`` targets, and the
    ``(refdes, pad)`` pairs the board does not have.

    When several placements share a refdes the first one is exported.
    *limit* caps the number of tasks (0 = no cap)."""
    tasks: List[Tuple[Placement, str | None, bool]] = []
    missing: List[Tuple[str, str | None]] = []
    for raw in targets:
        for refdes, pad in _parse_target_spec(raw):
            if limit and len(tasks) >= limit:
                return tasks, missing
            placements = by_refdes.get(refdes)
            if placements:
                tasks.append((placements[0], pad, bool(pad)))
            else:
                missing.append((refdes, pad))
    return tasks, missing


# ---------------------------------------------------------------------------
# Argument parsing & validation
# ---------------------------------------------------------------------------

def _validate_args(ap: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate parsed CLI arguments, calling ``ap.error()`` on failure."""
    # --list-file implies --list
    if args.list_file:
        args.list_components = True

    # --filter KEY=VALUE must contain a '=' (KEY may be empty? no — require KEY).
    if args.filter_kv is not None:
        key, _value = _parse_filter_spec(args.filter_kv)
        if not key:
            ap.error(
                f"Invalid --filter {args.filter_kv!r}: expected KEY=VALUE, e.g. "
                "--filter Type=Pad. KEY must be one of the property fields from "
                "--list-property-fields (run that first to see the board's "
                "field names)."
            )

    # The inspection modes (--list / --list-nets / --list-property-fields) emit
    # JSON to stdout and don't render; everything else needs an output
    # destination — either the legacy --out-dir or at least one --view.
    if (not args.list_components and not args.list_nets
            and not args.list_property_fields
            and not args.out_dir and not args.view):
        ap.error("--out-dir or --view is required (unless using --list / "
                 "--list-nets / --list-property-fields)")
    if args.view and args.out_dir:
        ap.error("--view and --out-dir are mutually exclusive (a --view carries "
                 "its own output directory)")
    for raw in args.view or []:
        out_dir, window_mm, arm_mm, thick_px = raw
        try:
            if float(window_mm) <= 0 or float(arm_mm) <= 0 or int(thick_px) <= 0:
                raise ValueError
        except ValueError:
            ap.error(f"Invalid --view numbers: {raw!r} (WINDOW_MM and "
                     f"CROSS_ARM_MM must be > 0 floats, CROSS_THICK_PX a > 0 int)")

    # Mutual exclusion: only one selection mode at a time
    active_modes = [
        name
        for flag, name in [
            (bool(args.target), "--target"),
            (bool(args.component or args.pad), "--component/--pad"),
            (args.all_components, "--all-components"),
            (args.all_pins, "--all-pins"),
        ]
        if flag
    ]
    if len(active_modes) > 1:
        ap.error(f"Cannot combine selection modes: {' and '.join(active_modes)}")

    # --all-pins renders everything; --limit contradicts that
    if args.all_pins and args.limit:
        ap.error("--all-pins cannot be combined with --limit (all means all)")

    if args.cross_arm_mm <= 0:
        ap.error("--cross-arm-mm must be > 0")
    if args.cross_thickness_px <= 0:
        ap.error("--cross-thickness-px must be > 0")
    if args.batch_size < 1:
        ap.error("--batch-size must be >= 1")

    # Validate --target syntax early
    for raw in args.target:
        for refdes, pad in _parse_target_spec(raw):
            if not refdes:
                ap.error(f"Invalid --target entry (empty refdes): '{raw}'")
            if pad is not None and not pad:
                ap.error(f"Invalid --target entry (missing pad after ':'): '{raw}'")


def parse_args() -> Config:
    """Parse command line arguments and return Config."""
    ap = argparse.ArgumentParser(
        description="Generate per-component images from ODB++ archives",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--odb-tgz", required=True, help="Path to ODB++ .tgz archive")
    ap.add_argument("--out-dir", default=None, help="Output directory for images (not required with --list)")
    ap.add_argument("--img-size", type=int, default=1024, help="Output image size (px)")
    ap.add_argument("--render-size", type=int, default=4096, help="Internal render size (px)")
    ap.add_argument("--window-mm", type=float, default=40.0, help="Crop window size (mm)")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of components (0=all)")

    # Legacy selection (keep for backwards compatibility)
    ap.add_argument("--component", type=str, default=None, help="Filter to single component refdes (e.g., C45)")
    ap.add_argument("--pad", type=str, default=None, help="Center crosshair on pad name (e.g., 1)")

    # New selection mode: per-target list, optional per-target pad
    ap.add_argument(
        "--target",
        action="append",
        default=[],
        help="Repeatable target spec: REFDES or REFDES:PAD (e.g., --target C45:1). Commas allowed.",
    )

    # Bulk selection modes
    bulk_group = ap.add_argument_group("bulk selection", "Generate images for all components or all pins")
    bulk_group.add_argument(
        "--all-components",
        action="store_true",
        default=False,
        help="Render every component at its center (one image per refdes)",
    )
    bulk_group.add_argument(
        "--all-pins",
        action="store_true",
        default=False,
        help="Render every pin of every component (one image per pin)",
    )

    # Inspection
    inspect_group = ap.add_argument_group("inspection", "Inspect board data without rendering")
    inspect_group.add_argument(
        "--list",
        dest="list_components",
        action="store_true",
        default=False,
        help="List all components and their pins as JSON to stdout (no rendering)",
    )
    inspect_group.add_argument(
        "--list-file",
        type=str,
        default=None,
        help="Write component list JSON to file (implies --list)",
    )
    inspect_group.add_argument(
        "--list-nets",
        dest="list_nets",
        action="store_true",
        default=False,
        help="List the netlist (nets -> component pins) plus components with "
             "per-pin net names as JSON to stdout (no rendering)",
    )
    inspect_group.add_argument(
        "--list-property-fields",
        dest="list_property_fields",
        action="store_true",
        default=False,
        help="List the SCHEMA: a sorted JSON array of every component property "
             "field name present on the board (no rendering). Use this to "
             "discover columns, then pull them with --list --fields.",
    )
    inspect_group.add_argument(
        "--fields",
        type=str,
        default=None,
        metavar="A,B,C",
        help="With --list: project component 'properties' to ONLY these "
             "comma-separated field names (order preserved). Absent = emit all "
             "properties (default, unchanged). Unknown fields are omitted.",
    )
    inspect_group.add_argument(
        "--filter",
        dest="filter_kv",
        type=str,
        default=None,
        metavar="KEY=VALUE",
        help="With --list: keep only components whose property KEY equals VALUE "
             "(case-insensitive value match, e.g. --filter Type=Pad). KEY must be "
             "a real field from --list-property-fields.",
    )
    inspect_group.add_argument(
        "--refdes-prefix",
        dest="refdes_prefix",
        type=str,
        default=None,
        metavar="U,IC",
        help="With --list: keep only components whose refdes starts with one of "
             "these comma-separated, case-insensitive prefixes (e.g. "
             "--refdes-prefix U,IC to get just the ICs). Composes with --fields "
             "and --filter.",
    )

    # Multi-view + caching (one run can emit several views from one render)
    multi_group = ap.add_argument_group(
        "multi-view / caching",
        "Emit several crop views from a single board render, and cache the "
        "rendered faces on disk so later runs skip parsing + rendering",
    )
    multi_group.add_argument(
        "--view",
        nargs=4,
        action="append",
        metavar=("OUT_DIR", "WINDOW_MM", "CROSS_ARM_MM", "CROSS_THICK_PX"),
        default=None,
        help="Repeatable output view. Mutually exclusive with --out-dir; "
             "--window-mm/--cross-* are ignored when --view is used.",
    )
    multi_group.add_argument(
        "--render-cache",
        type=str,
        default=None,
        help="Directory for cached full-board face renders (keyed by render "
             "size + generator version). The caller owns invalidation: pass a "
             "directory that is wiped when the ODB archive changes.",
    )
    multi_group.add_argument(
        "--png-compress-level",
        type=int,
        default=1,
        choices=range(0, 10),
        help="zlib level for output PNGs (1 = fast, ~2%% larger, identical pixels)",
    )

    # Crosshair sizing
    ap.add_argument("--cross-arm-mm", type=float, default=1.5, help="Crosshair arm half-length (mm)")
    ap.add_argument("--cross-thickness-px", type=int, default=3, help="Crosshair line thickness (px)")

    # Performance options
    perf_group = ap.add_argument_group("performance", "Parallel processing and performance options")
    perf_group.add_argument(
        "--parallel-render",
        action="store_true",
        default=False,
        help="Enable parallel layer rendering (doubles peak memory)",
    )
    perf_group.add_argument(
        "--no-parallel-render",
        dest="parallel_render",
        action="store_false",
        help="Disable parallel layer rendering",
    )
    perf_group.add_argument(
        "--parallel-export",
        action="store_true",
        default=True,
        help="Enable parallel component export (default: enabled)",
    )
    perf_group.add_argument(
        "--no-parallel-export",
        dest="parallel_export",
        action="store_false",
        help="Disable parallel component export",
    )
    perf_group.add_argument(
        "--max-workers",
        type=int,
        default=0,
        help="Max parallel workers (0=auto-detect based on CPU count, 1=disable parallelism)",
    )
    perf_group.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Components per batch for memory management",
    )
    perf_group.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress progress output",
    )

    args = ap.parse_args()
    _validate_args(ap, args)

    return Config(
        odb_path=args.odb_tgz,
        out_dir=args.out_dir,
        img_size=args.img_size,
        render_size=args.render_size,
        window_mm=args.window_mm,
        limit=args.limit,
        component=args.component,
        pad=args.pad,
        targets=args.target,
        all_components=args.all_components,
        all_pins=args.all_pins,
        list_components=args.list_components,
        list_file=args.list_file,
        list_nets=args.list_nets,
        list_property_fields=args.list_property_fields,
        fields=_parse_fields_spec(args.fields),
        filter_kv=_parse_filter_spec(args.filter_kv),
        refdes_prefixes=_parse_refdes_prefix_spec(args.refdes_prefix),
        cross_arm_mm=args.cross_arm_mm,
        cross_thickness_px=args.cross_thickness_px,
        views=[
            ViewSpec(out_dir=v[0], window_mm=float(v[1]),
                     cross_arm_mm=float(v[2]), cross_thickness_px=int(v[3]))
            for v in (args.view or [])
        ],
        render_cache=args.render_cache,
        png_compress_level=args.png_compress_level,
        parallel_render=args.parallel_render,
        parallel_export=args.parallel_export,
        max_workers=args.max_workers,
        batch_size=args.batch_size,
        quiet=args.quiet,
    )


def _process_component_export(
    placement: Placement,
    requested_pad: str | None,
    strict_pad: bool,
    config: Config,
    face_imgs: Dict[str, Image.Image],
    cropper: Cropper,
) -> Tuple[Image.Image | None, str | None, dict | None]:
    """Process a single component export (thread-safe).
    
    Args:
        placement: Component placement data
        requested_pad: Optional pad name to center on
        strict_pad: If True, generate 404 when pad not found
        config: Configuration
        face_imgs: Dict with "TOP" and "BOTTOM" rendered images
        cropper: Cropper instance for extracting component region
        
    Returns:
        Tuple of (image, filename, metadata) or (None, None, None) if error
    """
    try:
        # Determine center point (component center or pad position)
        center_x, center_y = placement.x_mm, placement.y_mm
        pad_found = True

        if requested_pad:
            pad_pos = placement.get_pad_position(requested_pad)
            if pad_pos:
                center_x, center_y = pad_pos
            else:
                pad_found = False
                if strict_pad:
                    img_404 = generate_404_image(
                        config.img_size,
                        f"Pad {requested_pad} not found on {placement.refdes}",
                    )
                    metadata = {
                        "error": "pad_not_found",
                        "component": placement.refdes,
                        "requested_pad": requested_pad,
                    }
                    return (img_404, f"{placement.refdes}_pad{requested_pad}_404", metadata)
                # In non-strict mode, fall back to component center

        # Select face
        face_img = face_imgs[placement.side]

        # Crop centered on component or pad
        crop = cropper.crop_centered(face_img, center_x, center_y)

        # Mirror BOTTOM to look like holding the board
        if placement.side == "BOTTOM":
            crop = ImageOps.mirror(crop)

        # Add annotations
        draw_cross_center(
            crop,
            placement.side,
            config.window_mm,
            config.top_marker_color,
            config.bottom_marker_color,
            arm_mm=config.cross_arm_mm,
            thickness_px=config.cross_thickness_px,
        )
        draw_side_banner(crop, placement.side)

        # Build filename
        if requested_pad and pad_found:
            filename = f"{placement.refdes}_pad{requested_pad}"
        else:
            filename = placement.refdes

        # Build metadata
        metadata = {
            "x_mm": placement.x_mm,
            "y_mm": placement.y_mm,
            "center_x_mm": center_x,
            "center_y_mm": center_y,
            "rotation_deg": placement.rot_deg,
            "side": placement.side,
            "crop_window_mm": config.window_mm,
            "pad": requested_pad if (requested_pad and pad_found) else None,
            "crop_box_mm": {
                "xmin": center_x - config.window_mm / 2,
                "ymin": center_y - config.window_mm / 2,
                "xmax": center_x + config.window_mm / 2,
                "ymax": center_y + config.window_mm / 2,
            },
        }
        return (crop, filename, metadata)

    except Exception as e:
        safe_tqdm_write(f"Error processing {placement.refdes}: {e}")
        return (None, None, None)


# Bump when anything that changes rendered-face pixels changes (layer styling,
# colors, compositing order) — it invalidates cached face renders.
RENDER_STYLE_VERSION = 2


def _face_cache_path(config: Config, side: str) -> Path:
    return Path(config.render_cache) / (
        f"face_{side}_r{config.render_size}_v{RENDER_STYLE_VERSION}.png")


def _odb_stat_token(config: Config) -> str:
    """Identity of the source archive (mtime+size) — the face cache is only
    valid for the archive it was rendered from."""
    st = os.stat(config.odb_path)
    return f"{st.st_mtime_ns}:{st.st_size}"


def _face_cache_valid(config: Config) -> bool:
    """True when the cache dir's ``.odb_stat`` sidecar matches the current
    archive. Self-validating: an ODB swap invalidates the face cache even for
    consumers that never run the GUI's checksum wipe (e.g. the editor)."""
    try:
        sidecar = Path(config.render_cache) / ".odb_stat"
        return sidecar.read_text(encoding="utf-8").strip() == _odb_stat_token(config)
    except OSError:
        return False


def _load_cached_face(config: Config, side: str) -> Image.Image | None:
    """Cached full-board face render, or ``None`` (no cache dir / miss /
    unreadable — a miss just falls back to rendering)."""
    if not config.render_cache:
        return None
    if not _face_cache_valid(config):     # cache from a DIFFERENT archive -> miss
        return None
    path = _face_cache_path(config, side)
    if not path.is_file():
        return None
    try:
        img = Image.open(path)
        img.load()
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        return img
    except Exception:  # noqa: BLE001 — corrupt cache file -> re-render
        return None


def render_board_face(config: Config, ctx, board, layers, drill_data):
    """Render one board face (all layers composited). Shared by the CLI and
    the render daemon so the pixels are identical wherever rendering happens."""
    comp = (
        Compositor(ctx)
        .add(BoardLayer(config.background_color, config.outline_color), board)
        .add(CopperLayer(config.copper_color), layers.copper)
    )
    if drill_data:
        comp.add(DrillLayer(), drill_data)
    comp.add(
        SoldermaskLayer(config.soldermask_color, config.soldermask_alpha),
        layers.soldermask,
        outline_pts=board.outline_pts,
    )
    comp.add(SilkscreenLayer(config.silkscreen_color), layers.silkscreen)
    if board.cutouts:
        comp.add(CutoutLayer(config.background_color, config.outline_color), board)
    return comp.render()


def _save_cached_faces(config: Config, faces: dict) -> None:
    """Best-effort persist of freshly rendered faces (lossless PNG; the PNG
    round-trip is bit-exact for RGBA). Failures are silent — the cache is an
    accelerator, never a correctness dependency."""
    if not config.render_cache:
        return
    try:
        Path(config.render_cache).mkdir(parents=True, exist_ok=True)
        for side, img in faces.items():
            if img is None:           # a failed parallel render — nothing to cache
                continue
            # Atomic write: concurrent CLI runs share this cache; a reader must
            # never observe a half-written face PNG.
            path = _face_cache_path(config, side)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            img.save(tmp, "PNG", compress_level=1)
            os.replace(tmp, path)
        # Stamp the archive identity LAST so a partially written cache from a
        # crashed run can never validate against the new archive.
        sidecar = Path(config.render_cache) / ".odb_stat"
        tmp = sidecar.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(_odb_stat_token(config), encoding="utf-8")
        os.replace(tmp, sidecar)
    except Exception:  # noqa: BLE001 — the cache is best-effort, never fatal
        pass


def export_view(
    config: Config,
    view: ViewSpec,
    ctx: RenderContext,
    face_imgs: Dict[str, Image.Image],
    export_tasks: List[Tuple[Placement, str | None, bool]],
    missing_404: List[Tuple[str, str, dict]] = (),
) -> ImageWriter:
    """Write one view's pictures, cropped from the rendered faces; returns its writer.

    THE export loop: the one-shot tool and the render daemon both call it, so
    ``parallel_export`` / ``max_workers`` / ``batch_size`` mean the same in both.
    *missing_404* = ``(filename, message, metadata)`` placeholders to write."""
    vcfg = replace(
        config,
        out_dir=view.out_dir,
        window_mm=view.window_mm,
        cross_arm_mm=view.cross_arm_mm,
        cross_thickness_px=view.cross_thickness_px,
    )
    cropper = Cropper(ctx, vcfg.window_mm, vcfg.img_size)
    writer = ImageWriter(vcfg.out_dir)
    max_workers = config.max_workers if config.max_workers > 0 else get_optimal_workers()

    for out_name, message, metadata in missing_404:
        img_404 = generate_404_image(vcfg.img_size, message)
        writer.save_image(img_404, out_name, metadata,
                          compress_level=vcfg.png_compress_level)
        img_404.close()

    def process_task(task: Tuple[Placement, str | None, bool]) -> str | None:
        placement, pad, strict = task
        img, filename, metadata = _process_component_export(
            placement, pad, strict, vcfg, face_imgs, cropper)
        if img is not None and filename is not None:
            # PNG encode runs HERE, in the worker — Pillow releases the
            # GIL during encode, so workers scale instead of serializing
            # the encode in the batch loop.
            writer.save_image(img, filename, metadata,
                              compress_level=vcfg.png_compress_level)
        if img is not None:
            img.close()
        return filename

    desc = f"Exporting components ({view.window_mm:g} mm)"
    with safe_tqdm(total=len(export_tasks), desc=desc, disable=config.quiet) as pbar:
        for batch in batch_items(export_tasks, config.batch_size):
            if config.parallel_export and len(batch) > 1:
                parallel_map(process_task, batch, max_workers=max_workers)
            else:
                for task in batch:
                    process_task(task)
            pbar.update(len(batch))
    return writer


def main() -> None:
    """Main entry point."""
    config = parse_args()

    # 1. Parse ODB++ archive. The board (outline + placements) is always
    #    parsed; LAYERS are parsed lazily below — only for faces that the
    #    requested targets sit on AND that aren't served from the render cache.
    with OdbArchive(config.odb_path) as odb:
        board = odb.parse_board()

        # --list-property-fields: output the property-field schema and exit.
        if config.list_property_fields:
            _output_property_fields(board)
            return

        # --list: output component listing and exit (no rendering). --fields /
        # --filter narrow the property columns / rows when supplied.
        if config.list_components:
            _output_component_list(
                board, config.list_file,
                fields=config.fields, filter_kv=config.filter_kv,
                refdes_prefixes=config.refdes_prefixes)
            return

        # --list-nets: output netlist + per-pin nets and exit (no rendering)
        if config.list_nets:
            _output_net_list(board)
            return

        # Output views: explicit --view groups, or the legacy single view.
        views = config.views or [ViewSpec(
            out_dir=config.out_dir,
            window_mm=config.window_mm,
            cross_arm_mm=config.cross_arm_mm,
            cross_thickness_px=config.cross_thickness_px,
        )]

        # Expand --all-components / --all-pins into explicit target list.
        # --limit is applied here for --all-components to avoid generating
        # unused targets; --all-pins disallows --limit (validated earlier).
        if config.all_components or config.all_pins:
            generated = _generate_all_targets(
                board.placements, config.all_pins, limit=config.limit,
            )
            config = replace(config, targets=generated)
            if not config.quiet:
                mode = "all-pins" if config.all_pins else "all-components"
                safe_tqdm_write(f"Generated {len(config.targets)} targets ({mode})")

        # ---- Build export task list BEFORE rendering, so only the faces the
        # targets actually sit on get parsed + rendered (face gating). ----
        export_tasks: List[Tuple[Placement, str | None, bool]] = []
        missing_404: List[Tuple[str, str, dict]] = []   # (filename, message, meta)

        if config.targets:
            export_tasks, missing = resolve_targets(
                placements_by_refdes(board), config.targets, config.limit)
            missing_404 = [(
                f"{refdes}_pad{pad}_404" if pad else f"{refdes}_404",
                f"Component {refdes} not found",
                {"error": "component_not_found", "requested": refdes,
                 "requested_pad": pad},
            ) for refdes, pad in missing]

        else:
            # Legacy behavior: --component filters, and --pad applies globally
            placements = board.placements
            if config.component:
                placements = [p for p in placements if p.refdes == config.component]
                if not placements:
                    missing_404.append((
                        f"{config.component}_404",
                        f"Component {config.component} not found",
                        {"error": "component_not_found",
                         "requested": config.component},
                    ))
                    safe_tqdm_write(
                        f"Component '{config.component}' not found. "
                        f"Generated 404 image.")

            strict_pad = bool(config.component and config.pad)
            for placement in placements:
                if config.limit and len(export_tasks) >= config.limit:
                    break
                export_tasks.append((placement, config.pad, strict_pad))

        # Face gating: the archive declares each placement's side (it comes
        # from comp_+_top/ or comp_+_bot/), so only those faces are needed.
        needed_sides = sorted({p.side for p, _, _ in export_tasks})

        # Render cache: serve cached faces; parse layers only for the misses.
        face_imgs: dict = {}
        to_render: List[str] = []
        for side in needed_sides:
            cached = _load_cached_face(config, side)
            if cached is not None:
                face_imgs[side] = cached
            else:
                to_render.append(side)

        layer_data = {side: odb.parse_layers(side) for side in to_render}
        drill_data = odb.parse_drill() if to_render else None

    # 2. Create render context
    ctx = RenderContext(board.bbox_mm, config.render_size)

    # 3. Render full board faces
    def render_face(side: str) -> Image.Image:
        """Render one board face with all layers."""
        return render_board_face(config, ctx, board, layer_data[side], drill_data)

    if to_render:
        if not config.quiet:
            safe_tqdm_write(f"Rendering board faces: {', '.join(to_render)}...")
        if config.parallel_render and len(to_render) > 1:
            rendered = parallel_map(render_face, to_render, max_workers=2)
            for side, img in zip(to_render, rendered):
                face_imgs[side] = img
        else:
            for side in to_render:
                face_imgs[side] = render_face(side)
        _save_cached_faces(config, {s: face_imgs[s] for s in to_render})

    # 4. Export per-component images — once per view, all cropped from the
    #    same rendered faces (the face render does not depend on the view).
    if config.batch_size > len(export_tasks) and len(export_tasks) > 0 and not config.quiet:
        safe_tqdm_write(f"Note: batch size ({config.batch_size}) exceeds component count ({len(export_tasks)})")

    for view in views:
        writer = export_view(config, view, ctx, face_imgs, export_tasks, missing_404)
        index_path = writer.write_index()
        safe_tqdm_write(f"Done. Wrote {writer.count} images to: {writer.img_dir}")
        safe_tqdm_write(f"Index: {index_path}")

    # Free face images
    for img in face_imgs.values():
        img.close()
    face_imgs.clear()
    gc.collect()


if __name__ == "__main__":
    main()
