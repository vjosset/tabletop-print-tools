"""
Resize every image in a folder to SIZE x SIZE, in place, for Tiled image-collection tilesets.

- Non-square images are centre-cropped to a square first.
- Filenames and formats are kept, so Tiled references stay valid.
- Originals are copied to <folder>/_originals/ before anything is changed.
- Images smaller than MIN_SOURCE px are listed as print-quality warnings.

Usage:  python normalize_squares.py art/floor [--pixel-art]
        --pixel-art  enlarge with hard pixel edges (nearest neighbour) instead of smoothing
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

SIZE = 640
MIN_SOURCE = 160  # below this, the image is enlarged more than 2x when printed at 2"
EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}


def main():
    folder = Path(sys.argv[1])
    resample_up = Image.Resampling.NEAREST if "--pixel-art" in sys.argv else Image.Resampling.LANCZOS
    backup = folder / "_originals"
    backup.mkdir(exist_ok=True)
    warnings = []

    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in EXTS or not path.is_file():
            continue
        with Image.open(path) as im:
            im.load()
        w, h = im.size
        if (w, h) == (SIZE, SIZE):
            continue
        if not (backup / path.name).exists():
            shutil.copy2(path, backup / path.name)

        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        im = im.crop((left, top, left + side, top + side))
        resample = resample_up if side < SIZE else Image.Resampling.LANCZOS
        im = im.resize((SIZE, SIZE), resample)
        if path.suffix.lower() in {".jpg", ".jpeg"} and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(path)
        note = f"{path.name}: {w}x{h} -> {SIZE}x{SIZE}"
        if w != h:
            note += " (cropped to square)"
        print(note)
        if side < MIN_SOURCE:
            warnings.append(f"{path.name} ({side}px source, enlarged {SIZE / side:.0f}x)")

    if warnings:
        print("\nLow resolution for print, fine for prototyping only:")
        print("\n".join("  " + w for w in warnings))


if __name__ == "__main__":
    main()
