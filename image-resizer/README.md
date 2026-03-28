# RS Gauges - PrintPDF

Embeds an gauge image (PNG/JPG) into a PDF at an exact physical size so it prints true-to-scale. Supports Letter and A4 paper, configurable margins, and an optional calibration overlay to verify your printer isn't scaling the output.

## Requirements

Python 3 and two packages:

```bash
pip install reportlab pillow
```

## Usage

```bash
python embedder.py <image> <output.pdf> [options]
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--paper` | `letter` | Paper size: `letter` or `a4` |
| `--width-mm` | — | Target image width in millimeters (preserves aspect ratio) |
| `--height-mm` | — | Target image height in millimeters (preserves aspect ratio) |
| `--margin-mm` | `12` | Page margin on all sides in mm |
| `--calibrate` | off | Add a 40 mm calibration square and a 2-inch ruler to the page |

You must provide exactly one of `--width-mm` or `--height-mm`. If the requested size would overflow the printable area (page minus margins), the image is scaled down to fit — it is never scaled up.

## Sample Usage

Generate a Letter PDF with the gauge at 152.4 mm wide (6 inches) and 12 mm margins:

```bash
python embedder.py Gauge6x1.png Ruinstars_Gauge_Letter.pdf --paper letter --width-mm 152.4 --margin-mm 12
```

Generate the same gauge on A4:

```bash
python embedder.py Gauge6x1.png Ruinstars_Gauge_A4.pdf --paper a4 --width-mm 152.4 --margin-mm 12
```

Generate with a calibration overlay to verify print scaling:

```bash
python embedder.py Gauge6x1.png Ruinstars_Gauge_Letter_cal.pdf --paper letter --width-mm 152.4 --margin-mm 12 --calibrate
```

## Printing

Open the output PDF and print at **100% / Actual Size**. Disable any "Fit to Page", "Shrink to Printable Area", or scaling options in your print dialog. The PDF footer includes a reminder of this. Use the calibration square and ruler (with `--calibrate`) to confirm your printer is not rescaling the output before committing to a full print run.
