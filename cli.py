#!/usr/bin/env python3
"""CLI entry point for ODB++ component image generator."""

import argparse

from PIL import ImageOps

from odb_image_generator.models import Config
from odb_image_generator.parsing import OdbArchive
from odb_image_generator.rendering import (
    RenderContext,
    Compositor,
    BoardLayer,
    CopperLayer,
    SoldermaskLayer,
    SilkscreenLayer,
)
from odb_image_generator.export import (
    Cropper,
    draw_cross_center,
    draw_side_banner,
    ImageWriter,
)


def parse_args() -> Config:
    """Parse command line arguments and return Config."""
    ap = argparse.ArgumentParser(
        description="Generate per-component images from ODB++ archives",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--odb-tgz", required=True, help="Path to ODB++ .tgz archive")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--img-size", type=int, default=1024, help="Output image size (px)")
    ap.add_argument("--render-size", type=int, default=8192, help="Internal render size (px)")
    ap.add_argument("--window-mm", type=float, default=40.0, help="Crop window size (mm)")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of components (0=all)")

    args = ap.parse_args()

    return Config(
        odb_path=args.odb_tgz,
        out_dir=args.out_dir,
        img_size=args.img_size,
        render_size=args.render_size,
        window_mm=args.window_mm,
        limit=args.limit,
    )


def main() -> None:
    """Main entry point."""
    config = parse_args()

    # 1. Parse ODB++ archive
    with OdbArchive(config.odb_path) as odb:
        board = odb.parse_board()
        top_layers = odb.parse_layers("TOP")
        bot_layers = odb.parse_layers("BOTTOM")

    # 2. Create render context
    ctx = RenderContext(board.bbox_mm, config.render_size)

    # 3. Render full board faces
    top_img = (
        Compositor(ctx)
        .add(BoardLayer(config.background_color, config.outline_color), board)
        .add(CopperLayer(config.copper_color), top_layers.copper)
        .add(
            SoldermaskLayer(config.soldermask_color, config.soldermask_alpha),
            top_layers.soldermask,
            outline_pts=board.outline_pts,
        )
        .add(SilkscreenLayer(config.silkscreen_color), top_layers.silkscreen)
        .render()
    )

    bot_img = (
        Compositor(ctx)
        .add(BoardLayer(config.background_color, config.outline_color), board)
        .add(CopperLayer(config.copper_color), bot_layers.copper)
        .add(
            SoldermaskLayer(config.soldermask_color, config.soldermask_alpha),
            bot_layers.soldermask,
            outline_pts=board.outline_pts,
        )
        .add(SilkscreenLayer(config.silkscreen_color), bot_layers.silkscreen)
        .render()
    )

    # 4. Export per-component images
    cropper = Cropper(ctx, config.window_mm, config.img_size)
    writer = ImageWriter(config.out_dir)

    count = 0
    for placement in board.placements:
        if config.limit and count >= config.limit:
            break

        # Select face
        face_img = top_img if placement.side == "TOP" else bot_img

        # Crop centered on component
        crop = cropper.crop_centered(face_img, placement.x_mm, placement.y_mm)

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
        )
        draw_side_banner(crop, placement.side)

        # Save
        metadata = {
            "x_mm": placement.x_mm,
            "y_mm": placement.y_mm,
            "rotation_deg": placement.rot_deg,
            "side": placement.side,
            "crop_window_mm": config.window_mm,
            "crop_box_mm": {
                "xmin": placement.x_mm - config.window_mm / 2,
                "ymin": placement.y_mm - config.window_mm / 2,
                "xmax": placement.x_mm + config.window_mm / 2,
                "ymax": placement.y_mm + config.window_mm / 2,
            },
        }
        writer.save_image(crop, placement.refdes, metadata)
        count += 1

    # Write index
    index_path = writer.write_index()

    print(f"Done. Wrote {writer.count} images to: {writer.img_dir}")
    print(f"Index: {index_path}")


if __name__ == "__main__":
    main()
