#!/usr/bin/env python3
"""
Combine images from a folder into a single tiled grid image.

Usage:
    python CombineTiles.py ./tiles --tiles 3x3
    python CombineTiles.py ./tokens --tiles 4x2 --output sheet.png

Requires: pillow
    pip install pillow
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
from utils import IMAGE_EXTS

from PIL import Image


def parse_tiles(value: str, ap: argparse.ArgumentParser) -> tuple[int, int]:
    """Parse a 'COLSxROWS' string and return (cols, rows), or exit on bad input."""
    try:
        cols, rows = map(int, value.lower().split("x"))
        if cols < 1 or rows < 1:
            raise ValueError
    except ValueError:
        ap.error(f"Invalid --tiles value {value!r}. Use format like 3x2 or 1x1.")
    return cols, rows


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Combine images from a folder into a single tiled grid image."
    )
    ap.add_argument("input_folder", help="Path to folder containing input images.")
    ap.add_argument(
        "--tiles", default="3x3",
        help="Grid layout in COLSxROWS format, e.g. 4x2 (default: 3x3)."
    )
    ap.add_argument(
        "--output", default=None,
        help="Output filename (default: tiled.png saved inside the input folder)."
    )
    args = ap.parse_args()

    input_folder = Path(args.input_folder).resolve()
    if not input_folder.is_dir():
        ap.error(f"Folder not found: {input_folder}")

    cols, rows = parse_tiles(args.tiles, ap)

    image_files = sorted(f for f in input_folder.iterdir() if f.suffix.lower() in IMAGE_EXTS)
    needed = cols * rows
    if len(image_files) < needed:
        ap.error(
            f"Not enough images in folder to fill {cols}x{rows} = {needed} tiles "
            f"(found {len(image_files)})."
        )

    images = [Image.open(f).convert("RGB") for f in image_files[:needed]]

    # Resize all images to the size of the first one
    tile_w, tile_h = images[0].size
    images = [img.resize((tile_w, tile_h), Image.Resampling.LANCZOS) for img in images]

    # Composite into a single grid image
    combined = Image.new("RGB", (cols * tile_w, rows * tile_h))
    for idx, img in enumerate(images):
        x = (idx % cols) * tile_w
        y = (idx // cols) * tile_h
        combined.paste(img, (x, y))

    output_path = Path(args.output) if args.output else input_folder / "tiled.png"
    combined.save(output_path)
    print(f"✅ Saved combined image to: {output_path}")


if __name__ == "__main__":
    main()
