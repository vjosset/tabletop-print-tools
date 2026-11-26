# bake_floors

Turns ambientCG and 3dtextures.me material downloads into square floor images for Ruinstars dungeon sections. They come out evenly lit, seamless and safe to rotate in Tiled. Materials with an Opacity map come out as transparent overlays. The default output is 640 × 640 px, which is one 2" square at 320 DPI. Use `--size` for larger tiles, such as 1920 px for a 6" tile.

Drop the zips in a folder, run one command, and get one floor PNG per material plus a contact sheet to review them all at once.

## Requirements

- Python 3.11 or newer (the script uses `tomllib`, which was added in 3.11)
- `numpy` and `pillow`:

```
pip install numpy pillow
```

## Quick start

1. Download materials from [ambientCG](https://ambientcg.com) or [3dtextures.me](https://3dtextures.me). From ambientCG the 2K JPG version is plenty (e.g. `Asphalt019_2K-JPG.zip`); PNG versions work too. 3dtextures.me zips work as downloaded, even with generic names like `drive-download-….zip`.
2. Put the zips, still zipped, in one folder, e.g. `incoming/`. The zip names don't matter.
3. Run the script from the `tools/` folder:

```
python bake_floors.py incoming art/floor --config materials.toml
```

4. Open `art/floor/contact_sheet.png` to check the results.
5. In Tiled, add the new PNGs to your floor tileset (open the `.tsx`, then **Add Tiles**).

Each zip becomes `floor_<material>.png`, e.g. `floor_asphalt019.png` or `floor_concrete_tiles_003.png`. The output folder is created if needed. Running the command again overwrites earlier outputs, so tweaking settings and re-running is safe.

## Command-line options

```
python bake_floors.py INCOMING_DIR OUT_DIR [--config FILE] [--size PX] [--grid PX]
```

| Option | Default | What it does |
|---|---|---|
| `INCOMING_DIR` | required | Folder of material zips. They're read directly; nothing is extracted to disk. |
| `OUT_DIR` | required | Where the floor PNGs and `contact_sheet.png` go. |
| `--config` | `materials.toml` next to the script | TOML settings file (see [Settings](#settings)). Without `--config`, the script uses the `materials.toml` in its own folder, or the built-in defaults if there is none. It prints which one it used. |
| `--size` | `640` | Width and height of each output image in pixels. At least 16. |
| `--grid` | `0` | Size of one grid square in pixels. A dark groove is drawn along every grid line, the image edges included. `0` means no grooves. It must divide `--size` exactly. |

### Grid grooves

The groove makes each grid square read as a separate floor plate. It also hides the slight texture mismatch where two squares at different rotations meet. Use it when your Tiled project lays out floors one grid square at a time. Leave it off for whole tiles that have printed walls or 3D-printed wall bands around them.

`--grid` sets where the grooves go independently of the image size, so different bakes line up:

| Command | Result |
|---|---|
| `--grid 640` | One 640 px square with a groove around its edges. |
| `--size 1920 --grid 640` | A 3 × 3 block of 640 px squares. It looks exactly like nine separate 640 px squares placed side by side. |
| `--size 1920` | A 1920 px tile with no grooves. |

Each square darkens a band on its own four edges, so where two squares meet, the groove is twice as wide. The band is 3 px for a 640 px grid square and scales with `--grid`.

## What it does with each map

Materials come as several maps. The tool finds each by its file ending, ignoring case, and uses it in a way that looks the same at any 90° rotation, so squares can be rotated freely.

| Map | File endings | What the tool does |
|---|---|---|
| Color | `_Color`, `_basecolor` | The base image. Required: zips without one are skipped. |
| AmbientOcclusion | `_AmbientOcclusion`, `_ambient_occlusion`, `_OCC` | Multiplied in, darkening cracks and recesses evenly. If a pack has none, a soft version is derived from Displacement. |
| Normal | `_NormalGL`, `_NormalDX`, `_normal`, `_NORM` | Lit by a lamp above the centre of the image (see [Lighting](#lighting)), plus edge shading: ridges lighter, creases darker. Any version works; GL is used if both GL and DX are present. When the file name doesn't say GL or DX, the tool works it out from the Displacement map, and assumes GL if there is none. |
| Displacement | `_Displacement`, `_height`, `_DISP` | Grime in local lows, slight wear on local highs. |
| Emissive | `_emissive`, `_Emission`, `_Emissive_01_Color` / `_Emissive_01_Mask` (numbered channels) | Lights. Painted on after steps 2–3 below, so they stay bright and keep their own colour, with a soft halo. A `_Mask` without a matching `_Color` gives white light. See `emissive_strength` and `glow`. |
| Opacity | `_Opacity`, `_Alpha` | Saved as transparency: the output is an RGBA PNG, for overlays such as doors, grates and fences. Brightness and contrast are measured on the visible part only. Set `transparent = false` to ignore it. |
| Roughness, Metalness | any | Ignored. They only matter under angled or moving light. |

Maps can be 8-bit or 16-bit; 16-bit maps (common for height) are scaled down to 8-bit.

Textures that aren't square, such as 2048 × 1024, are first made square. A texture whose sides are a whole-number ratio, like 2:1, is repeated along its short side, so it stays seamless and undistorted. Any other ratio is stretched to a square, and a warning is printed.

After combining the maps, the tool:

1. Resizes the texture to the output size, repeated `repeats` times across it, keeping it seamless. For patterned textures with `cells_per_square` set, it instead cuts out a whole number of stones (see [Patterned textures](#patterned-textures)).
2. Remaps the colour's brightness and contrast to the theme's mid-tone, so every floor sits in the same value range.
3. Pulls the colour toward the theme palette.
4. Applies the shading (lamp, edges, Displacement, AO) on top. This comes after the remap so the relief adds to `target_contrast` instead of being squashed by it. The average brightness stays at `target_value`.
5. Paints on any emissive lights.
6. If `--grid` is set, darkens the grid grooves.

All filtering wraps around the texture edges, so outputs stay seamless.

## Lighting

The normal map is lit by a lamp above the centre of the image. Slopes facing the centre come out lighter and slopes facing away darker, which makes raised panels and bevels stand out. `--grid` doesn't affect the lighting: the grid lines are drawn on top afterwards, as an overlay.

Because the lamp is centred, the lighting is the same after rotating the image by 90°, 180° or 270°, so rotated tiles still match. A lamp off to one side would light a quarter of the rotated tiles from the wrong side, and raised panels would read as dents.

- `light_height` sets how high the lamp is, in image widths, so the lighting looks the same at any `--size`. Lower means stronger, more one-sided shading. Very high (e.g. `50`) is the same as light from straight above. Rough, organic surfaces such as concrete or ground can show a faint circular pattern around the centre when the lamp is low, so keep the default `2.0` for those. Hard-surface panels can take `1.0`–`1.5`.
- `falloff` darkens the edges of the image, as under a real lamp. It's off by default. Around `0.3` gives a soft vignette.
- `relief` scales all the shading together (lamp, edges, Displacement, AO). Lower it if grooves come out too dark.

## Contact sheet

`contact_sheet.png` has one row per material:

- **Left:** the floor image. Transparent areas show as a checkerboard.
- **Middle:** four copies in a 2 × 2 block, each rotated by a different multiple of 90°, as they might be laid out in play. Mismatches at the joins show up here.
- **Right:** the material name and which maps were used.

## Settings

Settings live in `materials.toml`. The `[default]` table applies to every material. A table named after a material overrides just that material.

The material name comes from the Color map inside the zip, not the zip's own name. It's the file name without the map ending and ambientCG's resolution tag: `Asphalt019_2K-JPG_Color.jpg` → `Asphalt019`, `Concrete_Tiles_003_basecolor.png` → `Concrete_Tiles_003`.

Table names don't have to match exactly: case, hyphens, underscores and spaces are ignored. So `[Sci_Fi_Metal_Panel_002]`, `[sci-fi metal panel 002]` and `[Sci_fi_Metal_Panel_002]` all apply to `Sci_fi_Metal_Panel_002`. This helps with 3dtextures.me, which spells `Sci-fi`, `Sci_fi` and `Sci-Fi` differently from pack to pack. The material names printed by each run are the exact ones.

```toml
[default]
target_contrast = 16

[Asphalt019]
target_contrast = 12
repeats = 2
```

| Setting | Default | What it does |
|---|---|---|
| `repeats` | `1` | How many times the texture repeats across the output image. Raise it for coarse textures that look oversized. |
| `target_value` | `118` | Average brightness, 0–255. Keep all floors in a theme close to the same value. |
| `target_contrast` | `16` | Brightness spread of the colour, before shading. Lower for a calmer floor that keeps markers and minis readable. |
| `tint` | `[122, 113, 98]` | Theme palette colour (RGB). |
| `tint_amount` | `0.55` | `0` keeps the texture's own colour, `1` uses the palette colour only. |
| `relief` | `0.75` | Overall strength of all shading: lamp, edges, Displacement and AO. `0` gives the flat colour. |
| `normal_strength` | `2.0` | Strength of the lamp shading from the normal map. `0` turns it off. |
| `edge_strength` | `0.35` | Ridges lighter, creases darker, from the normal map. `0` turns it off. |
| `light_height` | `2.0` | Height of the lamp above the image centre, in image widths. Lower means stronger shading. See [Lighting](#lighting). |
| `falloff` | `0.0` | Darkening towards the image edges. `0` is off. |
| `cavity_strength` | `1.0` | Strength of grime and wear from Displacement. `0` turns it off. |
| `ao_strength` | `0.6` | Strength of ambient occlusion (real or derived). `0` turns it off. |
| `emissive_strength` | `0.5` | Brightness of lights from emissive maps. `0` turns them off, leaving the lights as they look in the Color map. |
| `glow` | `0.5` | Strength of the soft halo around lights. `0` gives crisp lights with no halo. |
| `transparent` | `true` | Use the Opacity map, if there is one, to save a transparent PNG. `false` gives a solid image. |
| `cells` | `0` | For patterned textures: how many cells (stones, tiles) the source texture has across. |
| `cells_per_square` | `0` | For patterned textures: how many cells to put in each grid square, or in the whole image without `--grid`. `0` turns pattern cutting off. Replaces `repeats`. |
| `cell_offset` | `0.0` | For patterned textures: where cell boundaries sit in the source, as a fraction of a cell from its left and top edges (0 up to, not including, 1). |

Unknown settings, including the old `seams` and `painterly`, are ignored with a warning.

`repeats` counts across the whole output image, not per grid square. So the same material baked at `--size 1920` with `repeats = 1` comes out three times coarser on the table than at 640. To keep the same scale at 1920, use three times the `repeats`. Patterned textures with `cells_per_square` don't have this problem.

## Patterned textures

Some textures have a built-in grid, such as paving stones or floor tiles. `Tiles085` is 8 × 8 stones. Stretching it across a 3 × 3 tile puts 2⅔ stones in each grid square, so grid lines cut through stones.

For these, tell the tool how many cells the source has, and how many you want per grid square:

```toml
[Tiles085]
cells = 8
cells_per_square = 2
```

The tool then takes exactly the number of stones the output needs, which is `cells_per_square` × the number of grid squares across:

| Command | Stones across | Taken from the source |
|---|---|---|
| `--grid 640` | 2 | Cropped to the top-left 2 × 2 of its 8 × 8 |
| `--size 1920 --grid 640` | 6 | Cropped to the top-left 6 × 6 |
| `--size 1920 --grid 640` with `cells_per_square = 4` | 12 | Repeated once, then cropped to 12 × 12 |

Stones come out the same size on the table at any `--size`. Without `--grid`, `cells_per_square` is the number of stones across the whole image.

Cuts fall on stone boundaries, which are the middle of a grout line. So where two squares meet, even at different rotations, the join looks like an ordinary grout line. The stones on either side aren't the source's original neighbours, which doesn't show with grout between them. Shading is worked out on the full source before cutting, so it's unaffected.

Things to check:

- **Count the cells along one side of the source's Color map**, not in ambientCG's preview, which may show the texture repeated. For a non-square source, count along the longer side.
- **The grout must sit on the source's edges.** In most ambientCG tile textures it does, split half on each edge. If the crop cuts through stones instead, set `cell_offset` to where the first grout line is, as a fraction of a stone: `0.5` for a line half a stone in from the edge.
- **The crop always starts at the top-left.** Every bake of a material uses the same stones.

## Choosing good materials

- **Prefer even textures with no strong direction:** concrete, tread plate, grating, worn metal. Squares get rotated, so a texture with stripes or bands produces mismatches where squares meet.
- **Avoid damage that runs to the edges.** Potholes or cracks cut by an edge look wrong next to a rotated neighbour. Use decals for distinctive damage so you control where it goes.
- **Avoid single objects as floors.** A manhole cover or a door is one object, not a repeating texture, so its edges won't line up with a neighbour. Packs with an Opacity map (doors, fences, grates) come out transparent: use them as overlays on top of a floor.
- **Check the scale.** A 2" square is roughly 3 m across at 28–32 mm scale. If a texture's features look too large, raise `repeats`.

## Troubleshooting

- **`skip <name>.zip: no Color map`:** the zip has no file ending in `_Color` or `_basecolor` (`.jpg` or `.png`). The tool recognises ambientCG's and 3dtextures.me's file naming; for another source, add its endings to `MAP_PATTERNS` in `bake_floors.py`.
- **`skip <zip>: <material> already baked from <other zip>`:** two zips hold the same material, e.g. the same texture downloaded twice. Only the first one (in name order) is baked; delete the duplicate.
- **`ModuleNotFoundError: No module named 'tomllib'`:** your Python is older than 3.11. Upgrade Python.
- **`--grid must be 0 or divide --size`:** pick a grid that fits the image a whole number of times, e.g. 640 or 960 for `--size 1920`.
- **`warning: ... is not a whole-number ratio; stretching to square`:** the texture's proportions can't be repeated into a square, so it was stretched slightly. Check it on the contact sheet.
- **`warning: [<table>] <key> is not a known setting; ignored`:** remove or fix that line in `materials.toml`.
- **`warning: <key> is outside any [table]; ignored`:** the setting comes before the first table heading. Move it under `[default]` or under a material's table.
- **`[<material>] cells and cells_per_square must be whole numbers above 0`:** `cells_per_square` is set but `cells` is missing, or one of them isn't a positive whole number.
- **`[<material>] cell_offset must be from 0 up to (not including) 1`:** `cell_offset` is a fraction of one cell. Use e.g. `0.5`, not a pixel count.
- **`warning: [<material>] repeats is ignored when cells_per_square is set`:** remove `repeats` from that material's table. The number of stones is set by `cells_per_square`.
- **Grid lines cut through the stones of a tile texture:** set `cells` and `cells_per_square` for it, and `cell_offset` if needed (see [Patterned textures](#patterned-textures)).
- **The floor looks too busy or too dark:** lower `target_contrast`, or adjust `target_value`, in that material's table.
- **Visible mismatches between rotated squares:** the texture has a strong direction or edge-crossing damage. Pick a more even material, use `--grid` to add grooves, or don't rotate that square.

## Licence of the source textures

ambientCG and 3dtextures.me materials are CC0: free to use, change and sell, with no credit required. Check the licence on any other source before using its textures.
