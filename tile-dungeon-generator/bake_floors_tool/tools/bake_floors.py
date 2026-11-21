"""
Bake ambientCG material zips into flat-lit, rotation-safe square floor images.

Usage:
    python bake_floors.py INCOMING_DIR OUT_DIR [--config materials.toml] [--size 640] [--grid 0]

INCOMING_DIR  folder of ambientCG zips (e.g. Asphalt019_2K-JPG.zip). Zips are
              read directly; nothing is extracted to disk.
OUT_DIR       where floor_<material>.png files and contact_sheet.png go.
--size        output square size in pixels (default 640).
--grid        grid square size in pixels; a dark groove is drawn along every
              grid line, image edges included. 0 (default) = no grooves.
              Must divide --size: e.g. --size 1920 --grid 640 = 3x3 squares.

Per material (all direction-neutral, so squares can be rotated freely):
  Color                     base image
  AmbientOcclusion          multiplied in; if missing, derived from Displacement
  Normal (GL or DX)         lit from directly overhead: flat = bright, slopes darker
  Displacement              cavity: local lows darker, local highs lighter
  Roughness / Metalness     ignored (only matter under moving light)
Then: value/contrast remap to the theme's mid-tone, warm palette tint,
optional grid grooves. All filtering wraps around the texture edges, so outputs stay seamless.

Settings live in a TOML file: a [default] table plus optional per-material
tables named after the material (e.g. [Asphalt019]) that override it.
"""
import argparse
import io
import re
import tomllib
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

DEFAULT_SIZE = 640

DEFAULTS = {
    "repeats": 1,            # texture repeats across the output image (1 = whole texture)
    "target_value": 118,     # mean brightness 0-255 (theme mid-tone)
    "target_contrast": 16,   # brightness spread (std dev); lower = calmer floor
    "tint": [122, 113, 98],  # palette colour to pull towards
    "tint_amount": 0.55,     # 0 = keep texture colour, 1 = fully palette-coloured
    "normal_strength": 2.0,  # overhead-light shading from the normal map
    "cavity_strength": 1.0,  # grime in lows / wear on highs from displacement
    "ao_strength": 0.6,      # AO map, or AO derived from displacement
    # For textures with a built-in pattern (paving stones, floor tiles), cut
    # along the pattern instead of stretching the whole texture:
    "cells": 0,              # pattern cells (e.g. stones) across the source texture
    "cells_per_square": 0,   # cells per grid square (per image without --grid); 0 = off
    "cell_offset": 0.0,      # where cell boundaries sit, as a fraction of a cell (0-1)
}

GROOVE_PER_640 = 3   # groove width in px for a 640px grid square, scaled with --grid
GROOVE_SHADE = 0.62  # brightness multiplier inside the groove

MAP_PATTERNS = {
    "color": r"_Color\.(jpg|png)$",
    "ao": r"_AmbientOcclusion\.(jpg|png)$",
    "normal": r"_NormalGL\.(jpg|png)$",
    "normal_dx": r"_NormalDX\.(jpg|png)$",
    "disp": r"_Displacement\.(jpg|png)$",
}


# --- helpers -------------------------------------------------------------------
def gauss_wrap(a, sigma):
    """Gaussian blur with wrap-around edges (via FFT), for 2D float arrays."""
    if sigma <= 0:
        return a
    h, w = a.shape
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]
    k = np.exp(-2 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * k))


def resize_wrap(arr, size):
    """Resize a seamless texture to size x size, keeping it seamless."""
    h, w = arr.shape[:2]
    p = max(8, h // 32)
    padded = np.pad(arr, ((p, p), (p, p)) + ((0, 0),) * (arr.ndim - 2), mode="wrap")
    scale = size / w
    big = (int(round(padded.shape[1] * scale)), int(round(padded.shape[0] * scale)))
    if arr.ndim == 2:
        im = Image.fromarray(padded.astype(np.float32), "F").resize(big, Image.Resampling.LANCZOS)
        out = np.asarray(im)
    else:
        chans = [np.asarray(Image.fromarray(padded[..., c].astype(np.float32), "F")
                            .resize(big, Image.Resampling.LANCZOS)) for c in range(arr.shape[2])]
        out = np.stack(chans, -1)
    q = int(round(p * scale))
    return out[q:q + size, q:q + size]


def make_square(im):
    """Make a seamless texture square without breaking seamlessness.

    Whole-number aspect ratios (e.g. 2048x1024) are tiled along the short side;
    anything else is stretched (still seamless, but slightly distorted).
    """
    w, h = im.size
    if w == h:
        return im
    long_, short = max(w, h), min(w, h)
    if long_ % short == 0:
        sq = Image.new(im.mode, (long_, long_))
        for k in range(long_ // short):
            sq.paste(im, (0, k * h) if w > h else (k * w, 0))
        return sq
    print(f"  warning: {w}x{h} is not a whole-number ratio; stretching to square")
    return im.resize((long_, long_), Image.Resampling.LANCZOS)


def load_maps(zpath):
    maps = {}
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            for key, pat in MAP_PATTERNS.items():
                if re.search(pat, name, re.I) and key not in maps:
                    with z.open(name) as f:
                        maps[key] = make_square(Image.open(io.BytesIO(f.read())).copy())
    if "normal" not in maps and "normal_dx" in maps:
        maps["normal"] = maps["normal_dx"]  # only the up (blue) channel is used
    return maps


def luminance(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114])


# --- bake ------------------------------------------------------------------------
def draw_grid(rgb, grid):
    """Darken a groove along every grid line, inside each square's own edges.

    Each square gets the same band on its four edges that a single
    grid-sized bake would, so where two squares meet the groove is
    2x the band, exactly as when two separate squares sit side by side.
    """
    size = rgb.shape[0]
    band = max(1, round(grid * GROOVE_PER_640 / 640))
    mask = np.zeros(size, bool)
    for start in range(0, size, grid):
        mask[start:start + band] = True
        mask[start + grid - band:start + grid] = True
    rgb[mask, :] *= GROOVE_SHADE
    rgb[:, mask] *= GROOVE_SHADE
    rgb[np.ix_(mask, mask)] /= GROOVE_SHADE  # crossings: darken once, not twice


def take_cells(rgb, cfg, size, grid):
    """Cut a whole number of pattern cells out of a patterned texture.

    The output holds cells_per_square cells per grid square (or per image
    without a grid). The source is first scaled so one cell is the right size,
    shifted so a cell boundary sits on the edge, then repeated if more cells
    are needed than it has and cropped to exactly that many cells. Cuts fall on
    cell boundaries (mid-grout), so where squares meet the join looks like
    ordinary grout.
    """
    cells = cfg["cells"]
    need = cfg["cells_per_square"] * (size // grid if grid else 1)
    full = max(1, round(cells * size / need))  # source size at the output's cell scale
    rgb = resize_wrap(rgb, full)               # scale first, so repeating stays small
    shift = round(cfg["cell_offset"] * full / cells)
    rgb = np.roll(rgb, (-shift, -shift), axis=(0, 1))  # wraps, so nothing is lost
    reps = -(-need // cells)
    rgb = np.tile(rgb, (reps, reps, 1))
    crop = round(need * full / cells)
    return rgb[:crop, :crop]


def bake(maps, cfg, size, grid):
    color = np.asarray(maps["color"].convert("RGB"), float)
    n = color.shape[0]
    shade = np.ones((n, n))

    if "normal" in maps:
        nrm = np.asarray(maps["normal"].convert("RGB").resize((n, n)), float) / 127.5 - 1
        nz = np.clip(nrm[..., 2] / (np.linalg.norm(nrm, axis=-1) + 1e-6), 0, 1)
        shade *= nz ** cfg["normal_strength"]

    disp = None
    if "disp" in maps:
        disp = np.asarray(maps["disp"].convert("L").resize((n, n)), float) / 255
        cav = disp - gauss_wrap(disp, n / 256)
        shade *= np.clip(1 + 3 * cfg["cavity_strength"] * cav, 0.5, 1.3)

    if "ao" in maps:
        ao = np.asarray(maps["ao"].convert("L").resize((n, n)), float) / 255
        shade *= 1 - cfg["ao_strength"] * (1 - ao)
    elif disp is not None:
        occl = np.clip(gauss_wrap(disp, n / 50) - disp, 0, 1) * 3
        shade *= 1 - cfg["ao_strength"] * np.clip(occl, 0, 0.8)

    rgb = color * shade[..., None]

    if cfg["cells_per_square"]:
        rgb = take_cells(rgb, cfg, size, grid)
    else:
        # size to one square (with repeats), keeping it seamless
        # (tile at a slightly larger size, then resize the result to exactly
        #  `size`, so repeats that don't divide it still give a full square)
        reps = max(1, int(cfg["repeats"]))
        tile = resize_wrap(rgb, -(-size // reps))
        rgb = np.tile(tile, (reps, reps, 1))
    if rgb.shape[0] != size:
        rgb = resize_wrap(rgb, size)

    # value / contrast remap to the theme, preserving hue
    L = luminance(rgb)
    newL = cfg["target_value"] + (L - L.mean()) / (L.std() + 1e-6) * cfg["target_contrast"]
    rgb = rgb * (newL / np.maximum(L, 1))[..., None]
    tint = np.array(cfg["tint"], float)
    tint_rgb = newL[..., None] * tint / luminance(tint)
    rgb = rgb * (1 - cfg["tint_amount"]) + tint_rgb * cfg["tint_amount"]

    if grid:
        draw_grid(rgb, grid)

    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def contact_sheet(results, path):
    cell = 320
    sheet = Image.new("RGB", (cell * 3 + 40, (cell + 40) * len(results) + 20), (40, 38, 34))
    d = ImageDraw.Draw(sheet)
    for i, (name, img, maps) in enumerate(results):
        y = 20 + i * (cell + 40)
        sheet.paste(img.resize((cell, cell)), (20, y))
        sq = img.size[0]
        rep = Image.new("RGB", (sq * 2, sq * 2))
        for k, (ox, oy) in enumerate([(0, 0), (sq, 0), (0, sq), (sq, sq)]):
            rep.paste(img.rotate(90 * k), (ox, oy))  # mixed rotations, as in play
        sheet.paste(rep.resize((cell, cell)), (cell + 30, y))
        d.text((2 * cell + 50, y + 10), name, fill=(240, 230, 210))
        d.text((2 * cell + 50, y + 30), "maps: " + ", ".join(sorted(maps)), fill=(180, 170, 150))
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("incoming")
    ap.add_argument("out")
    ap.add_argument("--config")
    ap.add_argument("--size", type=int, default=DEFAULT_SIZE,
                    help=f"output square size in pixels (default {DEFAULT_SIZE})")
    ap.add_argument("--grid", type=int, default=0,
                    help="grid square size in pixels for grooves; must divide --size (default 0 = none)")
    args = ap.parse_args()
    if args.size < 16:
        ap.error("--size must be at least 16")
    if args.grid < 0 or (args.grid and args.size % args.grid):
        ap.error(f"--grid must be 0 or divide --size ({args.size}) exactly")
    conf = {}
    if args.config:
        # explicit UTF-8 (not the Windows codepage); -sig also accepts a BOM, which
        # some Windows editors add and tomllib otherwise rejects
        conf = tomllib.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        for table, settings in conf.items():
            if not isinstance(settings, dict):
                print(f"warning: {table} is outside any [table]; ignored")
                continue
            for key in sorted(settings.keys() - DEFAULTS.keys()):
                print(f"warning: [{table}] {key} is not a known setting; ignored")
    base = {**DEFAULTS, **conf.get("default", {})}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for zp in sorted(Path(args.incoming).glob("*.zip")):
        material = zp.stem.split("_")[0]
        maps = load_maps(zp)
        if "color" not in maps:
            print(f"skip {zp.name}: no Color map")
            continue
        cfg = {**base, **conf.get(material, {})}
        if cfg["cells_per_square"]:
            if not (isinstance(cfg["cells"], int) and cfg["cells"] > 0
                    and isinstance(cfg["cells_per_square"], int) and cfg["cells_per_square"] > 0):
                ap.error(f"[{material}] cells and cells_per_square must be whole numbers above 0")
            if not 0 <= cfg["cell_offset"] < 1:
                ap.error(f"[{material}] cell_offset must be from 0 up to (not including) 1")
            if cfg["repeats"] != 1:
                print(f"  warning: [{material}] repeats is ignored when cells_per_square is set")
        img = bake(maps, cfg, args.size, args.grid)
        dest = out / f"floor_{material.lower()}.png"
        img.save(dest)
        used = {k for k in maps if k != "normal_dx" or "normal" not in maps}
        results.append((material, img, used))
        print(f"{zp.name} -> {dest.name}  (maps: {', '.join(sorted(used))})")
    if results:
        contact_sheet(results, out / "contact_sheet.png")


if __name__ == "__main__":
    main()
