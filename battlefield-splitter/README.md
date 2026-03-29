# battlefield-splitter

Two scripts for working with tiled battlefield maps:

- **BattlefieldPDFGen.py** — split a large image into square tiles and export as a multi-page PDF (one tile per page, each 20×20 cm).
- **CombineTiles.py** — assemble a folder of tile images into a single tiled grid image.

---

## Requirements

```bash
pip install pillow reportlab
```

*(CombineTiles.py only needs `pillow`.)*

---

## BattlefieldPDFGen.py

### Usage

```bash
python BattlefieldPDFGen.py <input_image> [options]
```

### Options

| Argument | Default | Description |
|---|---|---|
| `input_image` | *(required)* | Path to the input image (JPG or PNG) |
| `--tiles` | `1x1` | Tile grid layout in `COLSxROWS` format, e.g. `3x2` |
| `--paper` | `letter` | Paper size: `letter` or `a4` |
| `--grid-color` | `#c54c21` | Hex color for the alignment crosshair marks |
| `--grid-width-mm` | `1` | Width of crosshair lines in millimeters |
| `--upscale` | off | Upscale the image to meet minimum tile resolution before processing |
| `--instructions` | off | Append an instructions page with a layout preview |

### Output

A PDF named `{image_stem}_{Letter|A4}.pdf` saved alongside the input image. One tile per page, each printed at exactly 20×20 cm. The optional instructions page appears last and includes assembly guidance and a full-layout preview.

### Examples

```bash
# 3-column × 2-row split on Letter paper
python BattlefieldPDFGen.py map.jpg --tiles 3x2

# 3×3 grid on A4 with instruction page
python BattlefieldPDFGen.py TheRuinedCity.png --tiles 3x3 --paper a4 --instructions
```

### Printing

Print at **100% / Actual Size**. Disable "Fit to Page" or any scaling in your print dialog. Each tile will measure exactly 20×20 cm.

---

## CombineTiles.py

### Usage

```bash
python CombineTiles.py <input_folder> [options]
```

### Options

| Argument | Default | Description |
|---|---|---|
| `input_folder` | *(required)* | Folder containing PNG/JPG images |
| `--tiles` | `3x3` | Grid layout in `COLSxROWS` format |
| `--output` | `tiled.png` in the input folder | Output file path |

Images are sorted alphabetically; the first `COLS × ROWS` are used. All images are resized to match the first image's dimensions.

### Examples

```bash
# 3×3 grid saved as tiled.png inside the folder
python CombineTiles.py ./my-tokens --tiles 3x3

# 4×2 grid with a custom output path
python CombineTiles.py ./my-tokens --tiles 4x2 --output sheet.png
```
