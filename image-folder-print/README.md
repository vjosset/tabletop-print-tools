# image-folder-print

Takes all images in a folder, resizes each to a specified physical size, and packs them into a print-ready PDF. Images small enough to share a page are arranged in rows automatically; images too large for that get their own page.

---

## Requirements

```bash
pip install pillow reportlab
```

---

## Usage

```bash
python main.py [folder] --width-mm <mm> --height-mm <mm> [options]
```

`folder` defaults to `images/` in the current directory if not provided.

### Options

| Flag | Default | Description |
|---|---|---|
| `folder` | `images/` | Folder containing images to pack |
| `--width-mm` | *(required)* | Target image width in mm |
| `--height-mm` | *(required)* | Target image height in mm |
| `--paper` | `letter` | Paper size: `letter` or `a4` |
| `--margin-mm` | `12` | Page margin on all sides in mm |
| `--gap-mm` | `3` | Gap between images in mm |
| `--output` | `<folder>_<paper>.pdf` | Output PDF path |

Aspect ratio is always preserved. If an image's aspect ratio doesn't match the target box, it is fitted within it (never cropped or stretched). If the target size would exceed the printable area, the image is scaled down to fit and a warning is printed.

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

Custom output path:

```bash
python main.py ./cards --width-mm 63.5 --height-mm 88.9 --output print_sheet.pdf
```

---

## Printing

Open the output PDF and print at **100% / Actual Size**. Disable any "Fit to Page", "Shrink to Printable Area", or scaling options in your print dialog. The PDF footer on each page includes a reminder of this.
