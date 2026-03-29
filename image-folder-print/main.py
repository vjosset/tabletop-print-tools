#!/usr/bin/env python3
"""
Pack images from a folder into a print-ready PDF, resized to target physical dimensions.
Multiple images are placed per page when they fit; larger images get their own page.

Usage:
    python main.py [folder] --width-mm 63.5 --height-mm 88.9
    python main.py ./tokens --width-mm 40 --paper a4 --gap-mm 2

Requires: pillow reportlab
    pip install pillow reportlab
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
from utils import mm_to_pt, get_page_size, compute_fit, IMAGE_EXTS

from PIL import Image
from reportlab.pdfgen import canvas


def main():
    ap = argparse.ArgumentParser(
        description="Pack folder images into a print-ready PDF at exact physical dimensions."
    )
    ap.add_argument("folder", nargs="?", default="images",
                    help="Folder containing images (default: images/)")
    ap.add_argument("--width-mm", type=float, required=True,
                    help="Target image width in mm.")
    ap.add_argument("--height-mm", type=float, required=True,
                    help="Target image height in mm.")
    ap.add_argument("--paper", choices=["letter", "a4"], default="letter",
                    help="Paper size (default: letter).")
    ap.add_argument("--margin-mm", type=float, default=12.0,
                    help="Page margin on all sides in mm (default: 12).")
    ap.add_argument("--gap-mm", type=float, default=3.0,
                    help="Gap between images in mm (default: 3).")
    ap.add_argument("--output", default=None,
                    help="Output PDF path (default: <folder>_<paper>.pdf).")
    args = ap.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        raise SystemExit(f"❌ Folder not found: {folder}")

    image_paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not image_paths:
        raise SystemExit(f"❌ No images found in {folder}")

    print(f"Found {len(image_paths)} image(s) in {folder.name}/")

    page_w, page_h = get_page_size(args.paper)
    margin_pt = mm_to_pt(args.margin_mm)
    gap_pt    = mm_to_pt(args.gap_mm)
    target_w_pt = mm_to_pt(args.width_mm)
    target_h_pt = mm_to_pt(args.height_mm)
    area_w = page_w - 2 * margin_pt
    area_h = page_h - 2 * margin_pt

    paper_label = "Letter" if args.paper == "letter" else "A4"
    out_path = Path(args.output) if args.output else Path(f"{folder.name}_{paper_label}.pdf")

    c = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))
    c.setTitle(folder.name)

    # Packing state: cursor_y is the TOP of the current row
    # (ReportLab's origin is bottom-left, so images are drawn from cursor_y - h_pt)
    cursor_x      = margin_pt
    cursor_y      = page_h - margin_pt
    row_h         = 0.0
    page_has_content = False
    pages_used    = 0

    def finish_page():
        nonlocal page_has_content, pages_used
        c.setFont("Helvetica", 7)
        c.drawRightString(
            page_w - margin_pt, margin_pt / 2,
            "Print at 100% (Actual size). Disable 'Fit to page' or scaling in your print dialog.",
        )
        c.showPage()
        page_has_content = False
        pages_used += 1

    def start_new_page():
        nonlocal cursor_x, cursor_y, row_h
        if page_has_content:
            finish_page()
        cursor_x = margin_pt
        cursor_y = page_h - margin_pt
        row_h    = 0.0

    def start_new_row():
        nonlocal cursor_x, cursor_y, row_h
        cursor_y -= row_h + gap_pt
        cursor_x  = margin_pt
        row_h     = 0.0

    for img_path in image_paths:
        with Image.open(img_path) as im:
            w_px, h_px = im.size

        w_pt, h_pt = compute_fit(w_px, h_px, target_w_pt, target_h_pt)

        # If the image still exceeds the printable area, scale it down to fit
        if w_pt > area_w or h_pt > area_h:
            scale = min(area_w / w_pt, area_h / h_pt)
            w_pt *= scale
            h_pt *= scale
            print(f"  ⚠️  {img_path.name}: scaled down to fit page "
                  f"({w_pt / 72 * 25.4:.1f} x {h_pt / 72 * 25.4:.1f} mm)")

        # Image doesn't fit horizontally in the current row: advance to the next row
        if cursor_x + w_pt > page_w - margin_pt:
            start_new_row()
            if cursor_y - h_pt < margin_pt:
                start_new_page()
        # Image fits horizontally but not vertically on this page
        elif cursor_y - h_pt < margin_pt:
            start_new_page()

        c.drawImage(str(img_path), cursor_x, cursor_y - h_pt,
                    width=w_pt, height=h_pt, mask="auto")
        page_has_content = True

        row_h     = max(row_h, h_pt)
        cursor_x += w_pt + gap_pt

    if page_has_content:
        finish_page()

    c.save()
    print(f"✅ PDF saved to: {out_path}  ({len(image_paths)} images across {pages_used} page(s))")


if __name__ == "__main__":
    main()
