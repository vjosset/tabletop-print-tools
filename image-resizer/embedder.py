#!/usr/bin/env python3
# embed_gauge_pdf.py
#
# Usage examples:
#   python embed_gauge_pdf.py gauge.png out.pdf --paper letter --width-mm 40 --margin-mm 12 --calibrate
#   python embed_gauge_pdf.py gauge.png out_a4.pdf --paper a4 --height-mm 80
#
# Requires: reportlab, pillow
#   pip install reportlab pillow

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
from utils import mm_to_pt, get_page_size

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

def draw_calibration(canvas_obj, x, y):
    """
    Draw a 40mm x 40mm calibration square and a 2-inch ruler line with inch ticks.
    Places them near (x, y).
    """
    # 40 mm calibration square
    side_pt = mm_to_pt(40)
    canvas_obj.setLineWidth(1)
    canvas_obj.rect(x, y, side_pt, side_pt)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.drawString(x, y - 10, "40 mm calibration square")

    # 2-inch line with ticks
    start_x = x
    start_y = y + side_pt + 20
    two_in_pt = 2 * inch
    canvas_obj.line(start_x, start_y, start_x + two_in_pt, start_y)

    # Ticks every 0.25"
    for i in range(9):  # 0 to 2" in 0.25" steps
        tx = start_x + i * (0.25 * inch)
        tick_len = 8 if i % 4 == 0 else (5 if i % 2 == 0 else 3)  # 1" major, 0.5" mid, 0.25" minor
        canvas_obj.line(tx, start_y, tx, start_y + tick_len)
        if i % 4 == 0:
            canvas_obj.drawString(tx - 5, start_y + 12, f"{i//4}\"")
    canvas_obj.drawString(start_x, start_y + 22, "2-inch calibration line")

def main():
    ap = argparse.ArgumentParser(description="Embed an image into a PDF at exact physical size.")
    ap.add_argument("image", help="Input image file (PNG/JPG/SVG->rasterized beforehand).")
    ap.add_argument("output", help="Output PDF path.")
    ap.add_argument("--paper", choices=["letter","a4"], default="letter", help="Paper size.")
    ap.add_argument("--width-mm", type=float, help="Target image width in millimeters.")
    ap.add_argument("--height-mm", type=float, help="Target image height in millimeters.")
    ap.add_argument("--margin-mm", type=float, default=12.0, help="Page margin on all sides in mm.")
    ap.add_argument("--calibrate", action="store_true", help="Draw a 40mm square and a 2-inch ruler near the image.")
    args = ap.parse_args()

    if not args.width_mm and not args.height_mm:
        ap.error("You must specify --width-mm or --height-mm (one is enough).")
    if args.width_mm and args.height_mm:
        ap.error("Specify only one of --width-mm or --height-mm (aspect ratio is preserved).")

    page_w, page_h = get_page_size(args.paper)
    margin_pt = mm_to_pt(args.margin_mm)

    # Load image to get aspect ratio
    with Image.open(args.image) as im:
        w_px, h_px = im.size
    aspect = w_px / h_px

    if args.width_mm:
        img_w_pt = mm_to_pt(args.width_mm)
        img_h_pt = img_w_pt / aspect
    else:
        img_h_pt = mm_to_pt(args.height_mm)
        img_w_pt = img_h_pt * aspect

    # Ensure it fits within margins; if not, scale down proportionally (never up-scale here)
    max_w_pt = page_w - 2 * margin_pt
    max_h_pt = page_h - 2 * margin_pt
    scale = min(1.0, max_w_pt / img_w_pt, max_h_pt / img_h_pt)
    img_w_pt *= scale
    img_h_pt *= scale

    # Center within margins
    x = (page_w - img_w_pt) / 2
    y = (page_h - img_h_pt) / 2

    c = canvas.Canvas(args.output, pagesize=(page_w, page_h))

    # Place the image at the exact physical size
    # Note: ReportLab sizes in points (exact), so printer scaling must be "Actual size".
    c.drawImage(args.image, x, y, width=img_w_pt, height=img_h_pt, preserveAspectRatio=False, mask='auto')

    # Optional calibration artifacts
    if args.calibrate:
        # Put calibration near bottom-left margin area
        cal_x = margin_pt
        cal_y = margin_pt
        draw_calibration(c, cal_x, cal_y)

    # Small footer note
    c.setFont("Helvetica", 7)
    c.drawRightString(page_w - margin_pt, margin_pt / 2,
                      "Print at 100% (Actual size). Disable 'Fit to page' or scaling in your print dialog.")

    c.showPage()
    c.save()

if __name__ == "__main__":
    main()
