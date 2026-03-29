# Tabletop Print Tools

A collection of Python utilities for generating and preparing print-ready assets for tabletop games.

---

## Tools

| Tool | Description |
|---|---|
| [battlefield-splitter/](battlefield-splitter/) | Split a large map image into tiled pages and export as a multi-page PDF; or combine tile images into a single grid image |
| [dungeon-generator/](dungeon-generator/) | Procedurally generate randomized dungeon maps as PNG images |
| [image-resizer/](image-resizer/) | Embed an image into a PDF at an exact physical size |
| [image-folder-print/](image-folder-print/) | Pack a folder of images into a single print-ready PDF at target physical dimensions |

All tools require **Python 3.8+** and use only open-source libraries (`pillow`, `reportlab`).

Shared utility functions (unit conversion, page size lookup, aspect-ratio fitting) live in [shared/utils.py](shared/utils.py).

---

## battlefield-splitter

Two scripts for map tile workflows.

**Install:**
```bash
pip install pillow reportlab
```

**BattlefieldPDFGen.py** — split a high-resolution image into square tiles, overlay alignment crosshairs, and compile into a multi-page PDF. Each tile prints at exactly **20×20 cm** on Letter or A4 paper.

```bash
python BattlefieldPDFGen.py <input_image> --tiles 3x2 [--paper letter|a4] [--instructions]
```

**CombineTiles.py** — assemble a folder of tile images into a single grid image.

```bash
python CombineTiles.py <input_folder> --tiles 3x3 [--output sheet.png]
```

---

## dungeon-generator

Generates randomized, tile-based dungeon layouts as PNG images. Tiles are placed on a configurable grid using rules that prevent disconnected areas, dead exits, and overly long corridors.

**Install:**
```bash
pip install pillow
```

```bash
python main.py [--width W] [--height H] [--n N] [--placement standard|discovery|none] [--theme scan|clean]
```

Output: `dungeon_{SEED}.png` per generated map. The seed can be used to reproduce any dungeon exactly.

---

## image-resizer

Embeds an image into a PDF at a precise physical size. Useful for printing game components (gauges, tokens, rulers) that must match real-world dimensions.

**Install:**
```bash
pip install pillow reportlab
```

```bash
python embedder.py <image> <output.pdf> --paper letter --width-mm 152.4
```

Specify exactly one of `--width-mm` or `--height-mm`; the other is derived from the aspect ratio. Optional `--calibrate` flag adds a 40 mm square and 2-inch ruler for print verification.

---

## image-folder-print

Packs all images in a folder into a single print-ready PDF at a specified physical size. Images are arranged in rows per page; oversized images get their own page.

**Install:**
```bash
pip install pillow reportlab
```

```bash
python main.py [folder] --width-mm 63.5 --height-mm 88.9 [--paper letter|a4]
```

---

## Printing

All PDF-generating tools produce files intended to be printed at **100% / Actual Size**. Disable "Fit to Page" or any scaling in your print dialog. Each tool's PDF footer includes a reminder of this.
