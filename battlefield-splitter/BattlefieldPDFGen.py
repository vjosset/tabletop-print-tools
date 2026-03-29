#!/usr/bin/env python3
"""
Split a high-resolution image into square tiles and export as a multi-page PDF.
Each tile is printed on its own page at exactly 20×20 cm.

Usage:
    python BattlefieldPDFGen.py input.jpg --tiles 3x2
    python BattlefieldPDFGen.py map.png --tiles 3x3 --paper a4 --instructions

Requires: pillow reportlab
    pip install pillow reportlab
"""
import io
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
from utils import mm_to_pt, get_page_size

from PIL import Image, ImageDraw, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader

# --- Constants ---
JPEG_QUALITY = 100
MIN_TILE_SIZE = 1024


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
        description="Split an image into tiles and export as a multi-page PDF (20×20 cm per tile)."
    )
    ap.add_argument("input_image", help="Path to the input image (JPG or PNG).")
    ap.add_argument(
        "--tiles", default="1x1",
        help="Tile grid layout in COLSxROWS format, e.g. 3x2 (default: 1x1)."
    )
    ap.add_argument(
        "--paper", choices=["letter", "a4"], default="letter",
        help="Paper size (default: letter)."
    )
    ap.add_argument(
        "--grid-color", default="#c54c21",
        help="Hex color for the alignment crosshair marks (default: #c54c21)."
    )
    ap.add_argument(
        "--grid-width-mm", type=int, default=1,
        help="Width of crosshair lines in millimeters (default: 1)."
    )
    ap.add_argument(
        "--upscale", action="store_true",
        help="Upscale the image to meet minimum tile resolution before processing."
    )
    ap.add_argument(
        "--instructions", action="store_true",
        help="Append an instructions page with a layout preview to the PDF."
    )
    args = ap.parse_args()

    input_path = Path(args.input_image).resolve()
    if not input_path.is_file():
        ap.error(f"Input image not found: {input_path}")

    cols, rows = parse_tiles(args.tiles, ap)

    page_size = get_page_size(args.paper)
    paper_label = "A4" if args.paper == "a4" else "Letter"

    # --- Load Image ---
    image = Image.open(input_path).convert("RGB")
    width, height = image.size

    # Upscale to MIN_TILE_SIZE * cols x MIN_TILE_SIZE * rows before any other manipulation
    if args.upscale:
        target_w = MIN_TILE_SIZE * cols
        target_h = MIN_TILE_SIZE * rows
        if target_w > width or target_h > height:
            scale = max(target_w / width, target_h / height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            print(f"⚠️  Upscaling image from {width}x{height} to {new_width}x{new_height}")
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            width, height = image.size

    # --- Center-crop to exact tile grid ---
    img_w, img_h = image.size
    tile_size = int(min(img_w / cols, img_h / rows))
    crop_w = tile_size * cols
    crop_h = tile_size * rows
    left   = (img_w - crop_w) // 2
    top    = (img_h - crop_h) // 2
    image  = image.crop((left, top, left + crop_w, top + crop_h))

    # --- PDF Layout ---
    img_size  = 20 * cm
    page_w, page_h = page_size
    x_offset  = (page_w - img_size) / 2
    y_offset  = (page_h - img_size) / 2

    output_pdf = input_path.with_name(f"{input_path.stem}_{paper_label}.pdf")
    c = canvas.Canvas(str(output_pdf), pagesize=page_size)
    c.setTitle(input_path.stem)

    # --- Process Each Tile ---
    for row in range(rows):
        for col in range(cols):
            tile = image.crop((
                col * tile_size,
                row * tile_size,
                (col + 1) * tile_size,
                (row + 1) * tile_size,
            ))

            # Draw 5×5 crosshair grid
            draw = ImageDraw.Draw(tile)
            PIXELS_PER_MM = tile.width / 200.0  # 200 mm target print width
            line_width_px = int(round(args.grid_width_mm * PIXELS_PER_MM))
            cross_len = line_width_px * 3
            intersections = 5

            for i in range(intersections):
                for j in range(intersections):
                    x = i * tile_size // (intersections - 1)
                    y = j * tile_size // (intersections - 1)
                    # Black shadow stroke
                    draw.line([(x - cross_len - line_width_px, y), (x + cross_len + line_width_px, y)],
                              fill="#000000", width=line_width_px * 3)
                    draw.line([(x, y - cross_len - line_width_px), (x, y + cross_len + line_width_px)],
                              fill="#000000", width=line_width_px * 3)
                    # Colored foreground stroke
                    draw.line([(x - cross_len, y), (x + cross_len, y)],
                              fill=args.grid_color, width=line_width_px)
                    draw.line([(x, y - cross_len), (x, y + cross_len)],
                              fill=args.grid_color, width=line_width_px)

            # Embed tile in PDF via in-memory JPEG buffer
            buffer = io.BytesIO()
            tile.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            buffer.seek(0)
            c.drawImage(ImageReader(buffer), x_offset, y_offset, width=img_size, height=img_size)
            c.showPage()

    # --- Optional instructions page ---
    if args.instructions:
        c.setFont("Helvetica-Bold", 16)
        c.drawString(2 * cm, page_h - 2 * cm, "How to Print and Use")

        c.setFont("Helvetica", 11)
        instructions = [
            "• Print this PDF at 100% scale (do NOT use 'Fit to page').",
            "• Each tile prints at 20×20 cm and forms a grid of 4×4 squares, each 50 mm / 2\" to a side.",
            f"• This layout preview shows how to arrange the {cols}×{rows} tiles.",
            "• Cut and align the tiles according to the grid.",
            "• Mount to foam board, wood, or card for maximum durability.",
        ]
        y = page_h - 3.2 * cm
        for line in instructions:
            c.drawString(2 * cm, y, line)
            y -= 0.6 * cm

        # Thumbnail preview
        DPI_PREVIEW = 118
        max_px_w = int(10 * DPI_PREVIEW)
        max_px_h = int(10 * DPI_PREVIEW)
        img_w, img_h = image.size
        aspect = img_w / img_h
        if (max_px_w / max_px_h) > aspect:
            prev_h = max_px_h
            prev_w = int(prev_h * aspect)
        else:
            prev_w = max_px_w
            prev_h = int(prev_w / aspect)

        preview = image.resize((prev_w, prev_h), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(preview)
        for i in range(1, cols):
            x = int(i * prev_w / cols)
            draw.line([(x, 0), (x, prev_h)], fill="white", width=2)
        for j in range(1, rows):
            yy = int(j * prev_h / rows)
            draw.line([(0, yy), (prev_w, yy)], fill="white", width=2)

        preview_buf = io.BytesIO()
        preview.save(preview_buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        preview_buf.seek(0)

        prev_aspect = prev_w / prev_h
        max_cm = 10
        if prev_aspect >= 1:
            prev_w_pt = max_cm * cm
            prev_h_pt = prev_w_pt / prev_aspect
        else:
            prev_h_pt = max_cm * cm
            prev_w_pt = prev_h_pt * prev_aspect

        c.drawImage(
            ImageReader(preview_buf),
            (page_w - prev_w_pt) / 2,
            (page_h - prev_h_pt) / 2,
            width=prev_w_pt,
            height=prev_h_pt,
        )
        c.showPage()

    c.save()
    print(f"✅ PDF saved to: {output_pdf}")


if __name__ == "__main__":
    main()
