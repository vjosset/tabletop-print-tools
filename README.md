# Tabletop Print Tools

A collection of four Python utilities for generating and preparing print-ready assets for tabletop games.

---

## Tools

| Tool | Description |
|------|-------------|
| [battlefield-splitter/](battlefield-splitter/) | Split a large map image into tiled pages and export as a multi-page PDF |
| [dungeon-generator/](dungeon-generator/) | Procedurally generate randomized dungeon maps as PNG images |
| [image-resizer/](image-resizer/) | Embed an image into a PDF at an exact physical size |
| [image-folder-print/](image-folder-print/) | Combine a folder of images into a single tiled grid image |

All tools require **Python 3.7+** and use only standard open-source libraries.

---

## battlefield-splitter

Splits a high-resolution image into evenly-sized tiles, overlays alignment crosshairs on each, and compiles them into a multi-page PDF. Each tile prints at exactly **20×20 cm** on US Letter or A4 paper.

**Install dependencies:**
```bash
pip install Pillow reportlab
```

**Usage:**
```bash
python BattlefieldPDFGen.py <input_image> [options]
```

**Options:**

| Argument | Default | Description |
|----------|---------|-------------|
| `input_image` | *(required)* | Path to input image (JPG or PNG) |
| `--tiles COLSxROWS` | `1x1` | Tile grid layout, e.g. `3x2` for 3 columns and 2 rows |
| `--page_size` | `US Letter` | Paper size: `US Letter` or `A4` |
| `--grid-color` | `#c54c21` | Hex color for the alignment crosshair marks |
| `--grid-width-mm` | `1` | Line width of crosshair marks in millimeters |
| `--upscale` | `1` | Upscale small images to meet minimum tile resolution (1=yes, 0=no) |
| `--instructions` | `0` | Append an assembly instruction page with a layout preview (1=yes, 0=no) |

**Output:** `{image_name}_{page_size}.pdf` — one tile per page, with an optional instruction page at the end.

**Examples:**
```bash
# 3-column × 2-row grid on US Letter
python BattlefieldPDFGen.py map.jpg --tiles 3x2

# 3×3 grid on A4 with instruction page
python BattlefieldPDFGen.py TheRuinedCity.png --tiles 3x3 --instructions 1 --page_size A4
```

**Print instructions:** Open the output PDF and print at **100% / Actual Size** (disable "Fit to Page"). Each tile will measure exactly 20×20 cm.

---

## dungeon-generator

Generates randomized, tile-based dungeon layouts. Tiles are placed on a configurable grid using placement rules that prevent disconnected areas, dead exits, and overly long corridors. Output is a PNG image with optional item/spawn markers.

**Install dependencies:**
```bash
pip install Pillow
```

**Usage:**
```bash
python main.py [options]
```

**Options:**

| Argument | Default | Description |
|----------|---------|-------------|
| `--width` | `5` | Dungeon width in tiles |
| `--height` | `4` | Dungeon height in tiles |
| `--n` | `15` | Number of dungeons to generate |
| `--placement` | `standard` | Marker placement strategy: `standard`, `discovery`, or `none` |
| `--theme` | `scan` | Render theme: `scan` (green CRT look) or `clean` (dark minimal) |
| `--cell-px` | `128` | Cell size in pixels; controls output resolution |
| `--tile-images` | off | Use tile artwork from the `tiles/` folder instead of drawn geometry |
| `--tiles-dir` | `tiles` | Directory containing tile image variants |
| `--overlay-shapes` | off | Overlay drawn geometry at 50% opacity on top of tile images |

**Placement strategies:**

- **standard** — Places a player start (blue), console/objective (green), 3 enemy spawns (red), and 3 loot locations (orange) using spread logic.
- **discovery** — Places a player start and question-mark markers in a checkerboard pattern across reachable cells.
- **none** — Generates the map only, no markers.

**Output:** `dungeon_{SEED}.png` — the seed is embedded in the filename for exact reproduction.

**Examples:**
```bash
# 15 dungeons at default 5×4 size
python main.py

# 7-wide × 4-tall dungeon, 15 maps
python main.py --width 7 --height 4 --n 15

# Discovery placement, clean theme
python main.py --placement discovery --theme clean

# Use tile artwork with geometry overlay for alignment check
python main.py --tile-images --overlay-shapes
```

**Tile types:**

| Symbol | Shape | Connections |
|--------|-------|-------------|
| `+` | Cross | N, E, S, W |
| `T` | T-junction | 3 directions |
| `L` | Corner | 2 adjacent |
| `I` | Straight | 2 opposite |
| `O` | Open room | All sides |

---

## image-resizer

Embeds an image into a PDF at a precise physical size. Useful for printing game components (gauges, tokens, rulers) that must match real-world dimensions. The image is never upscaled beyond the requested size; if it would exceed the printable area, it is scaled down to fit.

**Install dependencies:**
```bash
pip install Pillow reportlab
```

**Usage:**
```bash
python embedder.py <image> <output.pdf> --paper <letter|a4> --width-mm <mm>
```

Specify exactly one of `--width-mm` or `--height-mm`; the other dimension is derived from the image's aspect ratio.

**Options:**

| Argument | Default | Description |
|----------|---------|-------------|
| `image` | *(required)* | Input image (PNG or JPG) |
| `output` | *(required)* | Output PDF path |
| `--paper` | `letter` | Paper size: `letter` or `a4` |
| `--width-mm` | — | Target image width in mm |
| `--height-mm` | — | Target image height in mm |
| `--margin-mm` | `12` | Page margin on all sides in mm |
| `--calibrate` | off | Add a 40 mm calibration square and a 2-inch ruler to verify printer scaling |

**Output:** A single-page PDF with the image centered on the page at the requested physical size, plus a footer reminder to print at 100%.

**Examples:**
```bash
# Print a gauge image at exactly 152.4 mm wide on US Letter
python embedder.py Gauge6x1.png output.pdf --paper letter --width-mm 152.4

# Same image on A4
python embedder.py Gauge6x1.png output_a4.pdf --paper a4 --width-mm 152.4

# With calibration marks to check printer accuracy
python embedder.py gauge.png output_cal.pdf --paper letter --width-mm 40 --calibrate
```

**Print instructions:** Print at **100% / Actual Size**. Use the calibration square (if generated) to confirm no scaling has been applied.

---

## image-folder-print

Combines multiple images from a folder into a single tiled grid image. Useful for producing contact sheets or printing multiple small assets on one page.

**Install dependencies:**
```bash
pip install Pillow
```

**Usage:**
```bash
python CombineTiles.py <input_folder> [--tiles COLSxROWS] [--output filename]
```

**Options:**

| Argument | Default | Description |
|----------|---------|-------------|
| `input_folder` | *(required)* | Folder containing PNG/JPG images |
| `--tiles` | `3x3` | Grid layout in `COLSxROWS` format |
| `--output` | `tiled_output.jpg` | Output filename |

Images are sorted alphabetically and the first `COLS × ROWS` images are used. All images are resized to match the dimensions of the first image. The output is saved as `tiled.png` inside the input folder.

**Example:**
```bash
# Combine up to 9 images into a 3×3 grid
python CombineTiles.py ./my-tokens --tiles 3x3

# 4 columns × 2 rows
python CombineTiles.py ./my-tokens --tiles 4x2
```
