#!/usr/bin/env python3
"""CLI entry point for ODB++ component image generator."""

from __future__ import annotations

import argparse
import gc
import json
import re
import sys
from dataclasses import replace
from typing import Tuple, Dict, List

from PIL import Image, ImageOps

from odb_image_generator.models import Board, Config, Placement
from odb_image_generator.parsing import OdbArchive
from odb_image_generator.rendering import (
    RenderContext,
    Compositor,
    BoardLayer,
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


def _build_component_list(board: Board) -> list:
    """Return a sorted list of ``{refdes, side, pins}`` dicts for the board."""
    components = []
    for placement in board.placements:
        pin_names = sorted(
            (pin.name for pin in placement.pins),
            key=_natural_sort_key,
        )
        components.append({
            "refdes": placement.refdes,
            "side": placement.side,
            "pins": pin_names,
        })
    components.sort(key=lambda c: _natural_sort_key(c["refdes"]))
    return components


def _output_component_list(board: Board, list_file: str | None) -> None:
    """Print component/pin listing as JSON to stdout.

    Always writes machine-readable JSON to stdout.  When *list_file* is
    given the same JSON is also written to that path (status printed to
    stderr so it doesn't pollute the JSON stream).
    """
    components = _build_component_list(board)
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


# ---------------------------------------------------------------------------
# Argument parsing & validation
# ---------------------------------------------------------------------------

def _validate_args(ap: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate parsed CLI arguments, calling ``ap.error()`` on failure."""
    # --list-file implies --list
    if args.list_file:
        args.list_components = True

    # --list doesn't require --out-dir; everything else does
    if not args.list_components and not args.out_dir:
        ap.error("--out-dir is required (unless using --list)")

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
        cross_arm_mm=args.cross_arm_mm,
        cross_thickness_px=args.cross_thickness_px,
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


def main() -> None:
    """Main entry point."""
    config = parse_args()

    # 1. Parse ODB++ archive
    with OdbArchive(config.odb_path) as odb:
        board = odb.parse_board()

        # --list: output component listing and exit (no rendering)
        if config.list_components:
            _output_component_list(board, config.list_file)
            return

        top_layers = odb.parse_layers("TOP")
        bot_layers = odb.parse_layers("BOTTOM")
        drill_data = odb.parse_drill()

    # 2. Create render context
    ctx = RenderContext(board.bbox_mm, config.render_size)

    # 3. Render full board faces
    def render_face(side: str) -> Image.Image:
        """Render one board face with all layers."""
        layers = top_layers if side == "TOP" else bot_layers
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
        return comp.render()

    if not config.quiet:
        safe_tqdm_write("Rendering board faces...")

    if config.parallel_render:
        rendered = parallel_map(render_face, ["TOP", "BOTTOM"], max_workers=2)
        top_img, bot_img = rendered[0], rendered[1]
    else:
        top_img = render_face("TOP")
        bot_img = render_face("BOTTOM")

    # 4. Export per-component images
    cropper = Cropper(ctx, config.window_mm, config.img_size)
    writer = ImageWriter(config.out_dir)
    face_imgs = {"TOP": top_img, "BOTTOM": bot_img}

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

    # Build lookup for resolving --target refdes strings
    placements_by_refdes: dict[str, list] = {}
    for p in board.placements:
        placements_by_refdes.setdefault(p.refdes, []).append(p)

    # ---- Build export task list: (placement, pad, strict_pad) ----
    # Two paths converge here:
    #   1. Explicit targets (--target, --all-components, --all-pins)
    #   2. Legacy mode (--component / --pad, or bare invocation)
    export_tasks: List[Tuple[Placement, str | None, bool]] = []

    if config.targets:
        for refdes, pad in (
            pair
            for raw in config.targets
            for pair in _parse_target_spec(raw)
        ):
            if config.limit and len(export_tasks) >= config.limit:
                break

            placement_list = placements_by_refdes.get(refdes)
            if not placement_list:
                img_404 = generate_404_image(
                    config.img_size,
                    f"Component {refdes} not found",
                )
                metadata = {"error": "component_not_found", "requested": refdes, "requested_pad": pad}
                out_name = f"{refdes}_pad{pad}_404" if pad else f"{refdes}_404"
                writer.save_image(img_404, out_name, metadata)
                continue

            # If multiple placements share a refdes, export the first one
            export_tasks.append((placement_list[0], pad, bool(pad)))

    else:
        # Legacy behavior: --component filters, and --pad applies globally
        placements = board.placements
        if config.component:
            placements = [p for p in placements if p.refdes == config.component]
            if not placements:
                img_404 = generate_404_image(
                    config.img_size,
                    f"Component {config.component} not found",
                )
                metadata = {"error": "component_not_found", "requested": config.component}
                writer.save_image(img_404, f"{config.component}_404", metadata)
                writer.write_index()
                safe_tqdm_write(f"Component '{config.component}' not found. Generated 404 image.")
                return

        strict_pad = bool(config.component and config.pad)
        for placement in placements:
            if config.limit and len(export_tasks) >= config.limit:
                break
            export_tasks.append((placement, config.pad, strict_pad))

    # Warn if batch size exceeds task count
    if config.batch_size > len(export_tasks) and len(export_tasks) > 0 and not config.quiet:
        safe_tqdm_write(f"Note: batch size ({config.batch_size}) exceeds component count ({len(export_tasks)})")

    # Process components in batches with parallel workers
    max_workers = config.max_workers if config.max_workers > 0 else get_optimal_workers()

    def process_task(task: Tuple[Placement, str | None, bool]) -> Tuple[Image.Image | None, str | None, dict | None]:
        placement, pad, strict = task
        return _process_component_export(placement, pad, strict, config, face_imgs, cropper)

    # Use single progress bar tracking overall completion
    with safe_tqdm(total=len(export_tasks), desc="Exporting components", disable=config.quiet) as pbar:
        for batch in batch_items(export_tasks, config.batch_size):
            if config.parallel_export and len(batch) > 1:
                results = parallel_map(process_task, batch, max_workers=max_workers)
            else:
                results = [process_task(task) for task in batch]

            # Save results from batch
            for img, filename, metadata in results:
                if img is not None and filename is not None:
                    writer.save_image(img, filename, metadata)
                if img is not None:
                    img.close()
            del results
            gc.collect()

            pbar.update(len(batch))

    # Free face images
    top_img.close()
    bot_img.close()
    del face_imgs, top_img, bot_img
    gc.collect()

    # Write index
    index_path = writer.write_index()

    safe_tqdm_write(f"Done. Wrote {writer.count} images to: {writer.img_dir}")
    safe_tqdm_write(f"Index: {index_path}")


if __name__ == "__main__":
    main()
