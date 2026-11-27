#!/usr/bin/env python3
"""
Pack images from a folder into a print-ready PDF at a physical size.
Multiple images are placed per page when they fit; larger images get their own page.

Two sizing modes (pick one):
  --width-mm / --height-mm  fit every image inside the same box
  --scale                   fixed scale, e.g. 1920px/127mm; each image keeps its own
                            size, and images too big for the page are split evenly

--legend adds a first page with printing instructions, a 100 mm check ruler, and
thumbnails of every split image showing how its pieces join and which pages they are on.

Usage:
    python main.py [folder] --width-mm 63.5 --height-mm 88.9
    python main.py ./tokens --width-mm 40 --height-mm 40 --paper a4 --gap-mm 2
    python main.py ./city --scale 1920px/127mm --margin-mm 6 --gap-mm 2 --legend

Requires: pillow reportlab
    pip install pillow reportlab
"""
import argparse
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
from utils import mm_to_pt, get_page_size, compute_fit, IMAGE_EXTS

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


@dataclass
class Piece:
    """One image (or one part of a split image) to place on a page."""
    path: Path
    w_pt: float
    h_pt: float
    crop: tuple[int, int, int, int] | None = None  # (left, top, right, bottom) in px
    part: int = 1     # 1-based number of this piece within its image
    parts: int = 1    # number of pieces the image was split into
    page: int = 0     # 1-based page number in the final PDF, set during layout
    x: float = 0.0    # bottom-left corner on the page, set during layout
    y: float = 0.0


@dataclass
class SplitImage:
    """An image that was split, for the legend."""
    path: Path
    w_px: int
    h_px: int
    col_edges: list[int]   # cut positions in px, including 0 and w_px
    row_edges: list[int]   # cut positions in px, including 0 and h_px
    pieces: list[Piece] = field(default_factory=list)


def parse_scale(text: str) -> tuple[float, float]:
    """Parse '1920px/127mm' (or '127mm/1920px') and return (pixels, millimetres)."""
    m = re.fullmatch(r"\s*([\d.]+)\s*(px|mm)\s*/\s*([\d.]+)\s*(px|mm)\s*", text, re.I)
    if not m or m.group(2).lower() == m.group(4).lower():
        raise argparse.ArgumentTypeError(
            f"Invalid scale {text!r}. Use e.g. 1920px/127mm (pixels per millimetres)."
        )
    a, a_unit, b = float(m.group(1)), m.group(2).lower(), float(m.group(3))
    if a <= 0 or b <= 0:
        raise argparse.ArgumentTypeError("Scale values must be positive.")
    return (a, b) if a_unit == "px" else (b, a)


def split_edges(total_px: int, size_pt: float, area_pt: float) -> list[int]:
    """Cut positions splitting [0, total_px) into the fewest equal spans that fit area_pt."""
    n = max(1, math.ceil(size_pt / area_pt - 1e-9))
    return [round(i * total_px / n) for i in range(n + 1)]


def pieces_at_scale(path: Path, w_px: int, h_px: int, pt_per_px: float,
                    area_w: float, area_h: float) -> tuple[list[Piece], SplitImage | None]:
    """Return the image as one piece, or as an even grid of pieces if it overflows the page."""
    w_pt, h_pt = w_px * pt_per_px, h_px * pt_per_px
    if w_pt <= area_w and h_pt <= area_h:
        return [Piece(path, w_pt, h_pt)], None

    cols = split_edges(w_px, w_pt, area_w)
    rows = split_edges(h_px, h_pt, area_h)
    split = SplitImage(path, w_px, h_px, cols, rows)
    parts = (len(cols) - 1) * (len(rows) - 1)
    for top, bottom in zip(rows[:-1], rows[1:]):
        for left, right in zip(cols[:-1], cols[1:]):
            split.pieces.append(Piece(
                path,
                (right - left) * pt_per_px,
                (bottom - top) * pt_per_px,
                crop=(left, top, right, bottom),
                part=len(split.pieces) + 1,
                parts=parts,
            ))
    first = split.pieces[0]
    print(f"  ✂️  {path.name}: split into {len(cols) - 1} x {len(rows) - 1} piece(s) "
          f"of {first.w_pt / 72 * 25.4:.1f} x {first.h_pt / 72 * 25.4:.1f} mm")
    return split.pieces, split


def piece_fitted_to_box(path: Path, w_px: int, h_px: int, target_w_pt: float,
                        target_h_pt: float, area_w: float, area_h: float) -> Piece:
    """Box mode: fit the image within the target box, then shrink it to the page if needed."""
    w_pt, h_pt = compute_fit(w_px, h_px, target_w_pt, target_h_pt)
    if w_pt > area_w or h_pt > area_h:
        scale = min(area_w / w_pt, area_h / h_pt)
        w_pt *= scale
        h_pt *= scale
        print(f"  ⚠️  {path.name}: scaled down to fit page "
              f"({w_pt / 72 * 25.4:.1f} x {h_pt / 72 * 25.4:.1f} mm)")
    return Piece(path, w_pt, h_pt)


def layout_pieces(pieces: list[Piece], page_w: float, page_h: float,
                  margin_pt: float, gap_pt: float, first_page: int) -> int:
    """Pack pieces into rows and pages, setting each piece's page, x and y.

    Returns the number of pages used.
    """
    page = first_page
    cursor_x = margin_pt
    cursor_y = page_h - margin_pt   # TOP of the current row (ReportLab's origin is bottom-left)
    row_h = 0.0
    page_has_content = False

    for piece in pieces:
        w_pt, h_pt = piece.w_pt, piece.h_pt
        new_page = False

        # Piece doesn't fit horizontally in the current row: advance to the next row
        if cursor_x + w_pt > page_w - margin_pt:
            cursor_y -= row_h + gap_pt
            cursor_x = margin_pt
            row_h = 0.0
            new_page = cursor_y - h_pt < margin_pt
        # Piece fits horizontally but not vertically on this page
        elif cursor_y - h_pt < margin_pt:
            new_page = True

        if new_page and page_has_content:
            page += 1
            cursor_x = margin_pt
            cursor_y = page_h - margin_pt
            row_h = 0.0

        piece.page, piece.x, piece.y = page, cursor_x, cursor_y - h_pt
        page_has_content = True
        row_h = max(row_h, h_pt)
        cursor_x += w_pt + gap_pt

    return page - first_page + 1 if pieces else 0


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------

LEGEND_THUMB_PT = mm_to_pt(45)     # max thumbnail size
LEGEND_CAPTION_PT = 24             # room for two caption lines under a thumbnail
LEGEND_GAP_PT = mm_to_pt(8)


def legend_header_lines(scale: tuple[float, float] | None, has_splits: bool) -> list[str]:
    lines = [
        "1. Print at 100% / Actual size. Turn off \"Fit to page\", \"Shrink to printable area\" "
        "and any other scaling.",
        "2. Check the printout: the bar below should measure exactly 100 mm.",
    ]
    if scale is not None:
        px, mm = scale
        lines.append(f"3. Scale: {px:g} px = {mm:g} mm.")
    if has_splits:
        lines.append(f"{len(lines) + 1}. Images too large for one page were split into numbered "
                     "pieces, printed on consecutive pages.")
        lines.append("    Join the pieces as shown below.")
    return lines


def legend_cells_per_page(area_w: float, area_h: float, header_h: float) -> tuple[int, int, int]:
    """Return (columns, rows on the first legend page, rows on later legend pages)."""
    cell_h = LEGEND_THUMB_PT + LEGEND_CAPTION_PT
    cols = max(1, int((area_w + LEGEND_GAP_PT) // (LEGEND_THUMB_PT + LEGEND_GAP_PT)))
    first_rows = max(0, int((area_h - header_h + LEGEND_GAP_PT) // (cell_h + LEGEND_GAP_PT)))
    rows = max(1, int((area_h + LEGEND_GAP_PT) // (cell_h + LEGEND_GAP_PT)))
    return cols, first_rows, rows


def legend_header_height(n_lines: int, has_splits: bool) -> float:
    # title + subtitle + instruction lines + ruler + "Split images" heading
    return 24 + 18 + n_lines * 13 + 40 + (24 if has_splits else 0)


def count_legend_pages(n_splits: int, area_w: float, area_h: float, header_h: float) -> int:
    cols, first_rows, rows = legend_cells_per_page(area_w, area_h, header_h)
    remaining = n_splits - cols * first_rows
    return 1 + max(0, math.ceil(remaining / (cols * rows)))


def draw_ruler(c: canvas.Canvas, x: float, y: float) -> None:
    """Draw a 100 mm ruler with 10 mm ticks; y is the baseline."""
    length = mm_to_pt(100)
    c.setLineWidth(0.8)
    c.line(x, y, x + length, y)
    c.setFont("Helvetica", 6)
    for i in range(11):
        tx = x + mm_to_pt(10 * i)
        c.line(tx, y, tx, y + (8 if i % 5 == 0 else 5))
        if i % 5 == 0:
            c.drawCentredString(tx, y - 8, f"{i * 10}")
    c.drawString(x + length + 6, y - 2, "mm")


def draw_split_thumbnail(c: canvas.Canvas, split: SplitImage, x: float, top: float) -> None:
    """Draw one split image's thumbnail with cut lines, piece numbers and caption."""
    scale = LEGEND_THUMB_PT / max(split.w_px, split.h_px)
    tw, th = split.w_px * scale, split.h_px * scale
    tx, ty = x + (LEGEND_THUMB_PT - tw) / 2, top - th

    with Image.open(split.path) as im:
        im.thumbnail((400, 400))
        thumb = im.copy()
    c.drawImage(ImageReader(thumb), tx, ty, width=tw, height=th, mask="auto")
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    c.rect(tx, ty, tw, th)

    # Cut lines
    c.setStrokeColorRGB(0.9, 0.1, 0.1)
    c.setLineWidth(1.5)
    c.setDash(4, 2)
    for ex in split.col_edges[1:-1]:
        c.line(tx + ex * scale, ty, tx + ex * scale, ty + th)
    for ey in split.row_edges[1:-1]:
        c.line(tx, top - ey * scale, tx + tw, top - ey * scale)
    c.setDash()

    # Piece numbers, centred in each piece
    for piece in split.pieces:
        left, ptop, right, bottom = piece.crop
        cx = tx + (left + right) / 2 * scale
        cy = top - (ptop + bottom) / 2 * scale
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(0, 0, 0)
        c.circle(cx, cy, 7, stroke=1, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(cx, cy - 3, str(piece.part))

    # Caption
    pages = sorted({p.page for p in split.pieces})
    page_text = f"page {pages[0]}" if len(pages) == 1 else f"pages {pages[0]}–{pages[-1]}"
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x, top - LEGEND_THUMB_PT - 10, split.path.stem)
    c.setFont("Helvetica", 7)
    c.drawString(x, top - LEGEND_THUMB_PT - 20, f"{len(split.pieces)} pieces, {page_text}")


def draw_legend(c: canvas.Canvas, title: str, summary: str, lines: list[str],
                splits: list[SplitImage], page_w: float, page_h: float,
                margin_pt: float) -> None:
    area_w = page_w - 2 * margin_pt
    area_h = page_h - 2 * margin_pt
    header_h = legend_header_height(len(lines), bool(splits))
    cols, first_rows, rows = legend_cells_per_page(area_w, area_h, header_h)
    cell_h = LEGEND_THUMB_PT + LEGEND_CAPTION_PT

    y = page_h - margin_pt
    c.setFont("Helvetica-Bold", 18)
    c.drawString(margin_pt, y - 18, title)
    y -= 24
    c.setFont("Helvetica", 9)
    c.drawString(margin_pt, y - 10, summary)
    y -= 18
    c.setFont("Helvetica", 9)
    for line in lines:
        c.drawString(margin_pt, y - 10, line)
        y -= 13
    draw_ruler(c, margin_pt + 4, y - 22)
    y -= 40
    if splits:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin_pt, y - 14, "Split images")
        y -= 24

    rows_left = first_rows
    col = 0
    for split in splits:
        if rows_left == 0:
            c.showPage()
            y = page_h - margin_pt
            rows_left = rows
        print(f"  Legend: {split.path.name}", flush=True)
        draw_split_thumbnail(c, split, margin_pt + col * (LEGEND_THUMB_PT + LEGEND_GAP_PT), y)
        col += 1
        if col == cols:
            col = 0
            rows_left -= 1
            y -= cell_h + LEGEND_GAP_PT
    c.showPage()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Pack folder images into a print-ready PDF at exact physical dimensions."
    )
    ap.add_argument("folder", nargs="?", default="images",
                    help="Folder containing images (default: images/)")
    ap.add_argument("--width-mm", type=float,
                    help="Box mode: target image width in mm (use with --height-mm).")
    ap.add_argument("--height-mm", type=float,
                    help="Box mode: target image height in mm (use with --width-mm).")
    ap.add_argument("--scale", type=parse_scale, metavar="PX/MM",
                    help="Scale mode: pixels per millimetres, e.g. 1920px/127mm. "
                         "Images too big for the page are split evenly into pieces.")
    ap.add_argument("--legend", action="store_true",
                    help="Add a first page with printing instructions, a 100 mm check ruler "
                         "and thumbnails showing how split images join.")
    ap.add_argument("--paper", choices=["letter", "a4"], default="letter",
                    help="Paper size (default: letter).")
    ap.add_argument("--margin-mm", type=float, default=12.0,
                    help="Page margin on all sides in mm (default: 12).")
    ap.add_argument("--gap-mm", type=float, default=3.0,
                    help="Gap between images in mm (default: 3).")
    ap.add_argument("--output", default=None,
                    help="Output PDF path (default: <folder>_<paper>.pdf).")
    args = ap.parse_args()

    box_mode = args.width_mm is not None or args.height_mm is not None
    mm_per_px = args.scale[1] / args.scale[0] if args.scale else None
    if args.scale is not None and box_mode:
        ap.error("--scale cannot be combined with --width-mm / --height-mm.")
    if args.scale is None and (args.width_mm is None or args.height_mm is None):
        ap.error("Give either --scale, or both --width-mm and --height-mm.")

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
    area_w = page_w - 2 * margin_pt
    area_h = page_h - 2 * margin_pt

    # Build the list of pieces to place
    pieces: list[Piece] = []
    splits: list[SplitImage] = []
    for img_path in image_paths:
        with Image.open(img_path) as im:
            w_px, h_px = im.size
        if args.scale is not None:
            new_pieces, split = pieces_at_scale(img_path, w_px, h_px, mm_to_pt(mm_per_px),
                                                area_w, area_h)
            pieces += new_pieces
            if split:
                splits.append(split)
        else:
            pieces.append(piece_fitted_to_box(
                img_path, w_px, h_px, mm_to_pt(args.width_mm), mm_to_pt(args.height_mm),
                area_w, area_h))

    # Work out the legend's length first, so image pages can be numbered after it
    legend_lines = legend_header_lines(args.scale, bool(splits))
    legend_pages = 0
    if args.legend:
        header_h = legend_header_height(len(legend_lines), bool(splits))
        legend_pages = count_legend_pages(len(splits), area_w, area_h, header_h)

    image_pages = layout_pieces(pieces, page_w, page_h, margin_pt, gap_pt,
                                first_page=legend_pages + 1)
    total_pages = legend_pages + image_pages

    paper_label = "Letter" if args.paper == "letter" else "A4"
    out_path = Path(args.output) if args.output else Path(f"{folder.name}_{paper_label}.pdf")

    c = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))
    c.setTitle(folder.name)

    if args.legend:
        print("Drawing legend…", flush=True)
        summary = (f"{len(image_paths)} images, {len(pieces)} pieces, {total_pages} pages "
                   f"({paper_label}, {args.margin_mm:g} mm margins)")
        draw_legend(c, folder.name, summary, legend_lines, splits,
                    page_w, page_h, margin_pt)

    current_page = legend_pages + 1
    for i, piece in enumerate(pieces, 1):
        if piece.page != current_page:
            c.showPage()
            current_page = piece.page

        part_text = f" (piece {piece.part}/{piece.parts})" if piece.parts > 1 else ""
        print(f"  [{i}/{len(pieces)}] page {piece.page}/{total_pages}: "
              f"{piece.path.name}{part_text}", flush=True)

        if piece.crop is None:
            c.drawImage(str(piece.path), piece.x, piece.y,
                        width=piece.w_pt, height=piece.h_pt, mask="auto")
        else:
            with Image.open(piece.path) as im:
                part = im.crop(piece.crop)
                part.load()
            c.drawImage(ImageReader(part), piece.x, piece.y,
                        width=piece.w_pt, height=piece.h_pt, mask="auto")
    if pieces:
        c.showPage()

    print("Writing PDF…", flush=True)
    c.save()
    print(f"✅ PDF saved to: {out_path}  ({len(image_paths)} images, {len(pieces)} piece(s) "
          f"across {total_pages} page(s))")


if __name__ == "__main__":
    main()
