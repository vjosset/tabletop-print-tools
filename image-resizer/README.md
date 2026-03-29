# image-resizer

Embeds an image into a PDF at an exact physical size so it prints true-to-scale. Supports Letter and A4 paper, configurable margins, and an optional calibration overlay to verify your printer isn't scaling the output.

---

## Requirements

```bash
pip install pillow reportlab
```

---

## Usage

```bash
python embedder.py <image> <output.pdf> [options]
```

### Options

| Flag | Default | Description |
|---|---|---|
| `image` | *(required)* | Input image file (PNG or JPG) |
| `output` | *(required)* | Output PDF path |
| `--paper` | `letter` | Paper size: `letter` or `a4` |
| `--width-mm` | — | Target image width in mm (preserves aspect ratio) |
| `--height-mm` | — | Target image height in mm (preserves aspect ratio) |
| `--margin-mm` | `12` | Page margin on all sides in mm |
| `--calibrate` | off | Add a 40 mm calibration square and a 2-inch ruler to the page |

Specify exactly one of `--width-mm` or `--height-mm`; the other dimension is derived from the image's aspect ratio. If the requested size would overflow the printable area (page minus margins), the image is scaled down to fit — it is never scaled up.

---

## Sample Usage

Print a gauge image at exactly 152.4 mm wide on Letter paper:

```bash
python embedder.py Gauge6x1.png output.pdf --paper letter --width-mm 152.4
```

Same image on A4:

```bash
python embedder.py Gauge6x1.png output_a4.pdf --paper a4 --width-mm 152.4
```

With calibration marks to verify printer accuracy:

```bash
python embedder.py gauge.png output_cal.pdf --paper letter --width-mm 40 --calibrate
```

---

## Printing

Open the output PDF and print at **100% / Actual Size**. Disable any "Fit to Page", "Shrink to Printable Area", or scaling options in your print dialog. The PDF footer includes a reminder of this. Use the calibration square and ruler (with `--calibrate`) to confirm your printer is not rescaling the output before committing to a full print run.
