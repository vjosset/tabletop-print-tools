# image-folder-print

Takes all images in a folder, sizes each one physically, and packs them into a print-ready PDF. Images small enough to share a page are arranged in rows automatically; images too large for that get their own page.

There are two sizing modes:

- **Box mode** (`--width-mm` + `--height-mm`): every image is fitted inside the same box. Good for cards and tokens.
- **Scale mode** (`--scale`): every image is printed at a fixed scale, such as `1920px/127mm`, so each keeps its own size. An image too big for the printable area is split evenly into the fewest pieces that fit, for example a 2×2-tile room becomes two 1×2 halves.

---

## Requirements

```bash
pip install pillow reportlab
```

---

## Usage

```bash
python main.py [folder] --width-mm <mm> --height-mm <mm> [options]
python main.py [folder] --scale <px>px/<mm>mm [options]
```

`folder` defaults to `images/` in the current directory if not provided.

### Options

| Flag | Default | Description |
|---|---|---|
| `folder` | `images/` | Folder containing images to pack |
| `--width-mm` | — | Box mode: target image width in mm |
| `--height-mm` | — | Box mode: target image height in mm |
| `--scale` | — | Scale mode: pixels per millimetres, e.g. `1920px/127mm` (`127mm/1920px` also works) |
| `--legend` | off | Add a first page with printing instructions, a 100 mm ruler to check the print scale, and thumbnails of each split image showing its numbered pieces and the pages they're on |
| `--paper` | `letter` | Paper size: `letter` or `a4` |
| `--margin-mm` | `12` | Page margin on all sides in mm |
| `--gap-mm` | `3` | Gap between images in mm |
| `--output` | `<folder>_<paper>.pdf` | Output PDF path |

Give either `--scale` or both `--width-mm` and `--height-mm`.

Aspect ratio is always preserved. In box mode, if an image's aspect ratio doesn't match the target box, it is fitted within it (never cropped or stretched). If the target size would exceed the printable area, the image is scaled down to fit and a warning is printed.

In scale mode, images are never scaled down. An image wider or taller than the printable area is cut into equal strips along that axis (or a grid, if it overflows both ways). Its pieces follow each other in the PDF. Each piece is the image's size divided evenly, so for rooms built from whole tiles, the cuts fall on tile edges when the piece count divides the tile count.

Supported formats: JPG, JPEG, PNG, BMP, TIFF, WEBP.

---

## Sample Usage

Pack a folder of poker-size cards (63.5 × 88.9 mm) onto Letter pages:

```bash
python main.py ./cards --width-mm 63.5 --height-mm 88.9
```

Pack 25 mm tokens with a tighter gap on A4:

```bash
python main.py ./tokens --width-mm 25 --height-mm 25 --paper a4 --gap-mm 2
```

Print dungeon rooms for 5" (127 mm) tiles, where one tile is 1920 px. Small (1×1) and medium (1×2) rooms fit as-is; large (2×2) rooms are split into two 1×2 halves:

```bash
python main.py ./city --scale 1920px/127mm --margin-mm 6 --gap-mm 2 --legend --output CityPrint.pdf
```

Custom output path:

```bash
python main.py ./cards --width-mm 63.5 --height-mm 88.9 --output print_sheet.pdf
```

---

## Printing

While it runs, the script prints each image as it's added (`[3/25] page 4/22: LG_L_02.png (piece 1/2)`). Large images take a few seconds each.

Open the output PDF and print at **100% / Actual Size**. Disable any "Fit to Page", "Shrink to Printable Area", or scaling options in your print dialog.
