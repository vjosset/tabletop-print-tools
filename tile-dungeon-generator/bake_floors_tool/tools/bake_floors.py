"""
Bake ambientCG / 3dtextures.me material zips into flat-lit, rotation-safe square floor images.

Usage:
    python bake_floors.py INCOMING_DIR OUT_DIR [--config materials.toml] [--size 640] [--grid 0]

INCOMING_DIR  folder of material zips (ambientCG or 3dtextures.me; any zip name). Zips are
              read directly; nothing is extracted to disk.
OUT_DIR       where floor_<material>.png files and contact_sheet.png go; the
              material name comes from the Color map inside each zip.
--size        output square size in pixels (default 640).
--grid        grid square size in pixels; a dark groove is drawn along every
              grid line, image edges included. 0 (default) = no grooves.
              Must divide --size: e.g. --size 1920 --grid 640 = 3x3 squares.

Per material (all rotation-safe, so squares can be rotated freely):
  Color                     base image: value/contrast remapped to the theme's
                            mid-tone and tinted to the palette
  Normal (GL or DX)         lit by a lamp above the centre of the image
                            (slopes facing the centre lighter, facing away
                            darker), plus edge curvature (ridges lighter, creases
                            darker)
  Displacement              cavity: local lows darker, local highs lighter
  AmbientOcclusion          multiplied in; if missing, derived from Displacement
  Emissive                  lights painted on top, bright and in their own colour
  Opacity                   saved as transparency (RGBA PNG), for overlays
  Roughness / Metalness     ignored (only matter under moving light)
The shading goes on after the colour remap, so relief adds to target_contrast
instead of being squashed by it. Then optional grid grooves. All filtering wraps around the texture edges, so outputs stay seamless.

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
    "relief": 0.75,          # overall strength of all shading (normal, edges, cavity, AO)
    "normal_strength": 2.0,  # lamp shading from the normal map
    "edge_strength": 0.35,   # ridges/edges lighter, creases darker (from the normal map)
    "light_height": 2.0,     # lamp height above the image centre, in image widths;
                             # higher = closer to straight down, subtler
    "falloff": 0.0,          # darkening towards the image edges, as under a real lamp; 0 = none
    "transparent": True,     # use the Opacity map, if any, to save a transparent PNG
    "cavity_strength": 1.0,  # grime in lows / wear on highs from displacement
    "ao_strength": 0.6,      # AO map, or AO derived from displacement
    # For textures with a built-in pattern (paving stones, floor tiles), cut
    # along the pattern instead of stretching the whole texture:
    "cells": 0,              # pattern cells (e.g. stones) across the source texture
    "cells_per_square": 0,   # cells per grid square (per image without --grid); 0 = off
    "cell_offset": 0.0,      # where cell boundaries sit, as a fraction of a cell (0-1)
    # Emissive maps (lights): painted on after the theme remap, so they stay bright
    "emissive_strength": 0.5,  # 0 = off (lights look like the rest of the base colour)
    "glow": 0.5,               # soft halo around lights; 0 = none
}

GLOW_SIGMA = 1 / 128  # halo blur radius, as a fraction of the source texture size
GLOW_GAIN = 3.0       # halo brightness at glow = 1

GROOVE_PER_640 = 3   # groove width in px for a 640px grid square, scaled with --grid
GROOVE_SHADE = 0.62  # brightness multiplier inside the groove

# Map file endings (case-insensitive). ambientCG: _Color, _NormalGL, ...;
# 3dtextures.me uses two styles: _basecolor, _normal, _height,
# _ambientOcclusion (or _ambient_occlusion), and older _COLOR, _NORM, _DISP, _OCC.
MAP_PATTERNS = {
    "color": r"_(Color|BaseColor)\.(jpe?g|png)$",
    "ao": r"_(AmbientOcclusion|Ambient_Occlusion|OCC)\.(jpe?g|png)$",
    "normal": r"_(NormalGL|Normal|NORM)\.(jpe?g|png)$",
    "normal_dx": r"_NormalDX\.(jpe?g|png)$",
    "disp": r"_(Displacement|Height|DISP)\.(jpe?g|png)$",
    "opacity": r"_(Opacity|Alpha)\.(jpe?g|png)$",
}

# Emissive (light) maps. 3dtextures.me: _emissive, or numbered light channels
# as _Emissive_01_Color (light in its colour) + _Emissive_01_Mask (where it is).
# Their _Color ending must not be taken for the base Color map.
EMISSIVE_PATTERN = r"_(Emissive|Emission)[^/]*\.(jpe?g|png)$"

# ambientCG files carry a resolution/format tag (Asphalt019_2K-JPG_Color.jpg)
# that isn't part of the material name.
AMBIENTCG_SUFFIX = r"_\d+K-(JPG|PNG)$"


def material_name(color_file, zpath):
    """Name the material after its Color map, since zip names may be generic.

    Asphalt019_2K-JPG_Color.jpg -> Asphalt019
    Concrete_Tiles_003_basecolor.png -> Concrete_Tiles_003
    Falls back to the zip name if the Color map's name has nothing before
    the map ending.
    """
    stem = re.sub(MAP_PATTERNS["color"], "", Path(color_file).name, flags=re.I)
    stem = re.sub(AMBIENTCG_SUFFIX, "", stem, flags=re.I)
    return stem or re.sub(AMBIENTCG_SUFFIX, "", zpath.stem, flags=re.I)


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


def to_8bit(im):
    """Bring 16-bit and float greyscale maps (modes I;16, I, F) down to 8-bit L.

    Pillow's own convert("L") clips them instead of scaling, which turns a
    16-bit height map solid white.
    """
    if im.mode in ("L", "LA", "RGB", "RGBA", "P", "1", "CMYK"):
        return im.copy()
    a = np.asarray(im, dtype=np.float64)
    if im.mode == "F":
        a = (a - a.min()) / max(a.max() - a.min(), 1e-12)  # float range is arbitrary
    else:
        a = a / 65535.0  # I;16 and 16-bit PNGs opened as I
    return Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8), "L")


def combine_emissive(files):
    """Merge emissive maps into one RGB light map (black = no light).

    Files are grouped per light channel (Emissive_01, Emissive_02, ...). In
    each group the _Color map is used if there is one, since it holds the
    light's colour; a _Mask alone gives white light. Groups are merged by
    taking the brighter value.
    """
    groups = {}
    for name, im in files:
        group = re.sub(r"_(Color|Mask)\.(jpe?g|png)$", "", name, flags=re.I)
        is_color = bool(re.search(r"_Color\.(jpe?g|png)$", name, re.I))
        if group not in groups or is_color:
            groups[group] = im
    out = None
    for im in groups.values():
        a = np.asarray(im.convert("RGB"), np.uint8)
        if out is not None and a.shape != out.shape:
            a = np.asarray(im.convert("RGB").resize(out.shape[1::-1]), np.uint8)
        out = a if out is None else np.maximum(out, a)
    return Image.fromarray(out, "RGB")


def load_maps(zpath):
    """Return (maps, color_file, normal_y).

    maps: the maps found. color_file: the Color map's file name.
    normal_y: the normal map's green-channel convention: "gl" (green = up),
    "dx" (green = down), or None if the file name doesn't say.
    """
    maps, color_file, emissive, normal_file = {}, None, [], None
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if re.search(EMISSIVE_PATTERN, name, re.I):
                with z.open(name) as f:
                    emissive.append((name, make_square(to_8bit(Image.open(io.BytesIO(f.read()))))))
                continue
            for key, pat in MAP_PATTERNS.items():
                if re.search(pat, name, re.I) and key not in maps:
                    with z.open(name) as f:
                        maps[key] = make_square(to_8bit(Image.open(io.BytesIO(f.read()))))
                    if key == "color":
                        color_file = name
                    if key == "normal":
                        normal_file = name
    normal_y = None
    if normal_file and re.search(r"_NormalGL\.", normal_file, re.I):
        normal_y = "gl"
    elif "normal" not in maps and "normal_dx" in maps:
        maps["normal"] = maps["normal_dx"]
        normal_y = "dx"
    if emissive:
        maps["emissive"] = combine_emissive(emissive)
    return maps, color_file, normal_y


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


def ddx(a):
    return (np.roll(a, -1, 1) - np.roll(a, 1, 1)) / 2


def ddy(a):
    return (np.roll(a, -1, 0) - np.roll(a, 1, 0)) / 2


def read_normals(img, n, normal_y, disp):
    """Unit normals in image space (x right, y DOWN, z up), shape (n, n, 3).

    The green channel's direction differs between GL and DX normal maps. If
    the file name didn't say, pick the one whose bumps agree with the height
    map (convex where the height has local highs), else assume GL.
    """
    nrm = np.asarray(img.convert("RGB").resize((n, n)), float) / 127.5 - 1
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-6
    if normal_y is None and disp is not None:
        highs = (disp - gauss_wrap(disp, n / 128)).ravel()
        as_gl = np.corrcoef(curvature(nrm * [1, -1, 1], n).ravel(), highs)[0, 1]
        as_dx = np.corrcoef(curvature(nrm, n).ravel(), highs)[0, 1]
        normal_y = "dx" if as_dx > as_gl else "gl"
    if normal_y != "dx":
        nrm[..., 1] *= -1  # GL green points up the image; flip to y-down
    return nrm


def curvature(nrm, n):
    """Convexity from image-space normals: > 0 on ridges/edges, < 0 in creases.

    Scaled so the strongest 1% of edges sit around +-1.
    """
    c = gauss_wrap(ddx(nrm[..., 0]) + ddy(nrm[..., 1]), n / 1024)
    return c / (np.percentile(np.abs(c), 99) + 1e-6)


def lamp(nrm, size, cfg):
    """Shading from a lamp above the centre of the image.

    The light is symmetric about the image centre, so rotating the image by
    any multiple of 90 degrees leaves its lighting unchanged. It ignores
    --grid: the grid is only gameplay lines drawn on top.
    Returns (relief, flat): relief shading relative to a flat surface, and the
    flat surface's own brightness (for falloff).
    """
    off = size / 2 - (np.arange(size) + 0.5)  # towards the image centre
    lx, ly = np.meshgrid(off, off)            # x across columns, y down rows
    lz = np.full_like(lx, cfg["light_height"] * size)
    L = np.stack([lx, ly, lz], -1)
    L /= np.linalg.norm(L, axis=-1, keepdims=True)
    lit = np.clip((nrm * L).sum(-1), 0, None)
    relief = np.clip(lit / L[..., 2], 0, 1.6) ** cfg["normal_strength"]
    flat = L[..., 2] ** (3 * cfg["falloff"])  # cos^3: angle plus distance
    return relief, flat


def bake(maps, cfg, size, grid, normal_y=None):
    color = np.asarray(maps["color"].convert("RGB"), float)
    n = color.shape[0]

    # Shading that doesn't depend on the light: cavity and AO
    shade = np.ones((n, n))
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

    # Everything rides through the cropping/tiling below as channels of one
    # array: colour 3, shade 1, then optionally normals 3 + curvature 1, and
    # emissive light 3 + its halo 3 (blurred at source scale, so the halo stays
    # in proportion to the texture's features).
    alpha = None
    if "opacity" in maps and cfg["transparent"]:
        alpha = np.asarray(maps["opacity"].convert("L").resize((n, n)), float) / 255
        color = color * alpha[..., None]  # premultiplied, so hidden colour can't bleed into edges
    layers = {"color": color, "shade": shade[..., None]}
    if alpha is not None:
        layers["alpha"] = alpha[..., None]
    if "normal" in maps:
        nrm = read_normals(maps["normal"], n, normal_y, disp)
        layers["normal"] = nrm
        layers["curv"] = curvature(nrm, n)[..., None]
    if "emissive" in maps and cfg["emissive_strength"] > 0:
        em = np.asarray(maps["emissive"].convert("RGB").resize((n, n)), float)
        layers["em"] = em
        layers["halo"] = np.stack([gauss_wrap(em[..., c], n * GLOW_SIGMA) for c in range(3)], -1)
    stack = np.concatenate(list(layers.values()), -1)

    if cfg["cells_per_square"]:
        stack = take_cells(stack, cfg, size, grid)
    else:
        # size to one square (with repeats), keeping it seamless
        # (tile at a slightly larger size, then resize the result to exactly
        #  `size`, so repeats that don't divide it still give a full square)
        reps = max(1, int(cfg["repeats"]))
        tile = resize_wrap(stack, -(-size // reps))
        stack = np.tile(tile, (reps, reps, 1))
    if stack.shape[0] != size:
        stack = resize_wrap(stack, size)
    i = 0
    for k, v in layers.items():
        c = v.shape[-1]
        layers[k] = stack[..., i:i + c]
        i += c
    rgb = layers["color"]
    # statistics come from visible pixels only (all pixels without an Opacity map)
    vis = np.ones(rgb.shape[:2], bool)
    if "alpha" in layers:
        a = np.clip(layers["alpha"][..., 0], 0, 1)
        rgb = rgb / np.maximum(a, 1e-3)[..., None]  # un-premultiply
        vis = a > 0.5
        if not vis.any():
            vis = a > 0

    # value / contrast remap of the colour alone, preserving hue
    L = luminance(rgb)
    Lv = L[vis]
    newL = cfg["target_value"] + (L - Lv.mean()) / (Lv.std() + 1e-6) * cfg["target_contrast"]
    rgb = rgb * (newL / np.maximum(L, 1))[..., None]
    tint = np.array(cfg["tint"], float)
    tint_rgb = newL[..., None] * tint / luminance(tint)
    rgb = rgb * (1 - cfg["tint_amount"]) + tint_rgb * cfg["tint_amount"]

    # shading on top, so relief adds to the colour's contrast rather than
    # being normalised away with it; average brightness stays at target_value
    shade = np.clip(layers["shade"][..., 0], 0.05, None)
    flat = 1.0
    if "normal" in layers:
        nrm = layers["normal"] / (np.linalg.norm(layers["normal"], axis=-1, keepdims=True) + 1e-6)
        relief, flat = lamp(nrm, size, cfg)
        edges = np.clip(1 + cfg["edge_strength"] * layers["curv"][..., 0], 0.5, 1.5)
        shade = shade * relief * edges
    shade = np.clip(shade, 0.02, None) ** cfg["relief"] * flat
    rgb = rgb * (shade / shade[vis].mean())[..., None]

    if "em" in layers:
        # screen blend: brightens towards the light colour, never past white
        light = cfg["emissive_strength"] * (layers["em"] + cfg["glow"] * GLOW_GAIN * layers["halo"])
        light = np.clip(light, 0, 255)
        rgb = 255 - (255 - np.clip(rgb, 0, 255)) * (255 - light) / 255

    if grid:
        draw_grid(rgb, grid)

    rgb = np.clip(rgb, 0, 255)
    if "alpha" in layers:
        a = np.clip(layers["alpha"], 0, 1) * 255
        return Image.fromarray(np.concatenate([rgb, a], -1).astype(np.uint8), "RGBA")
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def on_checker(img, size):
    """Composite an RGBA image over a checkerboard so transparency shows."""
    img = img.resize((size, size))
    if img.mode != "RGBA":
        return img.convert("RGB")
    sq = max(4, size // 20)
    yy, xx = np.mgrid[0:size, 0:size]
    board = np.where(((yy // sq + xx // sq) % 2)[..., None] == 0, 90, 60).repeat(3, -1).astype(np.uint8)
    bg = Image.fromarray(board, "RGB")
    bg.paste(img, (0, 0), img)
    return bg


def contact_sheet(results, path):
    cell = 320
    sheet = Image.new("RGB", (cell * 3 + 40, (cell + 40) * len(results) + 20), (40, 38, 34))
    d = ImageDraw.Draw(sheet)
    for i, (name, img, maps) in enumerate(results):
        y = 20 + i * (cell + 40)
        sheet.paste(on_checker(img, cell), (20, y))
        sq = img.size[0]
        rep = Image.new(img.mode, (sq * 2, sq * 2))
        for k, (ox, oy) in enumerate([(0, 0), (sq, 0), (0, sq), (sq, sq)]):
            rep.paste(img.rotate(90 * k), (ox, oy))  # mixed rotations, as in play
        sheet.paste(on_checker(rep, cell), (cell + 30, y))
        d.text((2 * cell + 50, y + 10), name, fill=(240, 230, 210))
        d.text((2 * cell + 50, y + 30), "maps: " + ", ".join(sorted(maps)), fill=(180, 170, 150))
    sheet.save(path)


def table_key(name):
    """Settings-table lookup key: lower case, with "-", "_" and spaces removed."""
    return re.sub(r"[-_\s]", "", name.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("incoming")
    ap.add_argument("out")
    ap.add_argument("--config",
                    help="settings TOML (default: materials.toml next to this script, if present)")
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
    if not args.config:
        # without this, per-material settings (cells, overrides) silently vanish
        default_config = Path(__file__).with_name("materials.toml")
        if default_config.exists():
            args.config = str(default_config)
    print(f"settings: {args.config or 'built-in defaults (no materials.toml found)'}")
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
    # Material tables match loosely (case, "-", "_" and spaces ignored), since
    # sources spell names inconsistently: Sci-fi_, Sci_fi_, Sci-Fi_ ...
    tables = {}
    for table, settings in conf.items():
        if table == "default" or not isinstance(settings, dict):
            continue
        key = table_key(table)
        if key in tables:
            print(f"warning: [{table}] and [{tables[key][0]}] name the same material; using [{table}]")
        tables[key] = (table, settings)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    seen = {}  # material -> zip it came from
    for zp in sorted(Path(args.incoming).glob("*.zip")):
        maps, color_file, normal_y = load_maps(zp)
        if "color" not in maps:
            print(f"skip {zp.name}: no Color map")
            continue
        material = material_name(color_file, zp)
        if material in seen:
            print(f"skip {zp.name}: {material} already baked from {seen[material]}")
            continue
        seen[material] = zp.name
        cfg = {**base, **tables.get(table_key(material), (None, {}))[1]}
        if cfg["cells_per_square"]:
            if not (isinstance(cfg["cells"], int) and cfg["cells"] > 0
                    and isinstance(cfg["cells_per_square"], int) and cfg["cells_per_square"] > 0):
                ap.error(f"[{material}] cells and cells_per_square must be whole numbers above 0")
            if not 0 <= cfg["cell_offset"] < 1:
                ap.error(f"[{material}] cell_offset must be from 0 up to (not including) 1")
            if cfg["repeats"] != 1:
                print(f"  warning: [{material}] repeats is ignored when cells_per_square is set")
        img = bake(maps, cfg, args.size, args.grid, normal_y)
        dest = out / f"floor_{material.lower()}.png"
        img.save(dest)
        used = {k for k in maps if k != "normal_dx" or "normal" not in maps}
        results.append((material, img, used))
        print(f"{zp.name} -> {dest.name}  (maps: {', '.join(sorted(used))})")
    if results:
        contact_sheet(results, out / "contact_sheet.png")


if __name__ == "__main__":
    main()
