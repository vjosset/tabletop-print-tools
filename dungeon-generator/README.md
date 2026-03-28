# DungeonGenerator

Generates randomized dungeon layouts from modular 3×3 tiles, outputting PNG images.

## How it works

The dungeon is a grid of tiles (default 5×5 = 25 tiles), each tile being 3×3 cells, producing a 15×15 cell map. Each tile is chosen randomly by type, randomly rotated, and placed. Edge and corner tiles are constrained so corridors don't exit the map boundary.

### Tile types

| Symbol | Name    | Ports         |
|--------|---------|---------------|
| `+`    | Cross   | N, E, S, W    |
| `T`    | T-shape | 3 directions  |
| `L`    | Corner  | 2 adjacent    |
| `I`    | Straight| 2 opposite    |
| `O`    | Open    | All floors    |

### Special features

- **Big room**: Optionally places a 2×2 tile open room somewhere in the map.
- **Connectivity cleanup**: Optionally walls off disconnected floor islands, keeping only the largest connected region.
- **Spawn/player/console placement**: Picks sensible floor cells for game entity placement.
- **Search markers**: Identifies dead-end tiles and picks the most spread-out ones.

## Tile placement rules

Tiles are chosen randomly by weight, then randomly rotated. Additional constraints apply:

- `+` and `T` tiles are never placed on edge or corner positions (they have ports that would exit the map boundary).
- `I` tiles are allowed on edges but not corners.
- `L` and `O` tiles can go anywhere.
- Two `O` tiles may never be orthogonally adjacent (except within a big room). This prevents large featureless open areas.
- Two `I` tiles with the same axis (both NS or both EW) may never be orthogonally adjacent. This prevents 1-cell-wide corridors 6 cells long.
- Any tile that produces an all-wall 3×3 block is rejected and the map is rerolled.

Edge and corner tiles are additionally rotated until no floor cell faces outward (corridors cannot exit the map boundary).

## Marker placement rules

Colored dots are drawn on top of the floor cells. No two markers of any type may share the same 3×3 tile.

| Color  | Meaning | Placement |
|--------|---------|-----------|
| Blue   | Player start | Center cell of a randomly chosen `O` tile (outside the big room) |
| Green  | Console | Center cell of the `O` tile farthest from the player |
| Red    | Enemy spawns (×3) | Tile center cells, spread across the map using farthest-point sampling seeded from the player position |
| Orange | Search markers (×3) | Dead-end locations, picked one at a time using three-tier priority (see below), spread using farthest-point sampling seeded from the player position |

### Orange marker placement priority

Each orange marker is placed on the best available tier, falling back only when the higher tier is exhausted:

1. **Leaf cells** — individual floor cells with exactly one floor neighbour (corridor dead ends)
2. **Leaf tiles** — any free floor cell within a tile that has exactly one connection to the rest of the map in the tile graph (catches dead-end rooms like isolated `O` tiles that contain no degree-1 cells)
3. **Any free floor cell** — last resort fallback

Once a tile receives any marker it is blocked from receiving another.

## Output

PNG images are written to the output directory. Two visual themes are available:

- `clean` — dark background, light floors, subtle grid
- `scan` — dark green CRT/scanline aesthetic

## Reproducing a dungeon

Each generated PNG is named after its RNG seed (e.g. `dungeon_1436804428.png`). To regenerate that exact dungeon, pass the seed to `DungeonConfig`:

```python
from main import DungeonConfig, build_floor_grid, render_png

cfg = DungeonConfig(seed=1436804428, enforce_connected=True, big_room_count=0)
floor, spawns, player, console, counts, leaf_marks = build_floor_grid(cfg)
render_png(floor, spawns=spawns, player=player, console=console,
           tile_counts=counts, leaf_marks=leaf_marks, out_path="replay.png")
```

`big_room_count` is `1` for every third dungeon in a normal batch and `0` otherwise — check which it was by looking at the batch position, or just try both if unsure.

## Configuration

All generation parameters live in `DungeonConfig`:

```python
DungeonConfig(
    tile_grid_w=5,          # tiles wide (default 5)
    tile_grid_h=5,          # tiles tall (default 5)
    tile_size=3,            # cells per tile (always 3)
    weights={...},          # per-type tile weights
    seed=None,              # set for reproducible output
    enforce_connected=True, # wall off disconnected regions
    big_room_count=1,       # 0 or 1 big open rooms
    big_room_tiles=2,       # big room size in tiles (2 → 2×2)
    min_floor=0,            # minimum floor cell count
    max_rerolls=50,         # attempts to satisfy constraints
)
```

## Usage

```bash
pip install Pillow
python main.py [--width W] [--height H] [--placement STRATEGY] [--n N] [--theme THEME]
```

| Argument | Default | Description |
|---|---|---|
| `--width` | `5` | Dungeon width in tiles |
| `--height` | `4` | Dungeon height in tiles |
| `--placement` | `standard` | Item placement strategy: `standard`, `discovery`, or `none` |
| `--n` | `15` | Number of dungeons to generate |
| `--theme` | `scan` | Render theme: `scan` or `clean` |
| `--tile-images` | | Use tile images in the local `tiles` folder instead of drawn geometry |
| `--overlay-shapes` | | When used with `--tile-images`, add a transparent overlay to better mark the tile images for floors vs walls |
| `--cell-px` | `32` | Cell/square size in pixels |

### Sample calls

```bash
# Default: 5×4 dungeon, standard placement, scan theme
python main.py

# Wider dungeon
python main.py --width 7 --height 4 --n 15

# Discovery placement on a 5×4 dungeon
python main.py --n 15 --placement discovery

# Generate 5 dungeons with the clean theme
python main.py --n 5 --theme clean

# Small dungeon with discovery placement
python main.py --width 5 --height 4 --n 10 --placement discovery
```

## Tile count statistics

To find out how many physical tiles a player needs to own to cover most generated dungeons, use `collect_stats()`:

```python
python -c "from main import collect_stats; collect_stats(12000)"
```

This runs the generator the specified number of times (using the default dungeon config for generation) and prints a table of min/average/p90/p95/max counts per tile type. The p95 column is the recommended ownership count: stocking that many of each tile covers 95% of possible dungeons.

12,000 run stats for a 4x4 dungeon with big room every 3 maps:

| Tile |  min |  avg |  p90 |  p95 |  max |
|:----:|:----:|:----:|:----:|:----:|:----:|
|  `+` |    0 |  1.0 |    2 |    2 |    4 |
|  `I` |    0 |  2.5 |    4 |    4 |    6 |
|  `L` |    1 |  5.3 |    7 |    8 |   10 |
|  `O` |    1 |  6.0 |    7 |    8 |    8 |
|  `T` |    0 |  1.2 |    2 |    3 |    4 |
|**Total**|   |      |      |**25**|**32**|

12,000 run stats for a 5x4 dungeon with big room every 3 maps:

| Tile |  min |  avg |  p90 |  p95 |  max |
|:----:|:----:|:----:|:----:|:----:|:----:|
|  `+` |    0 |  1.5 |    3 |    3 |    6 |
|  `I` |    0 |  3.2 |    5 |    5 |    8 |
|  `L` |    1 |  6.2 |    8 |    9 |   13 |
|  `O` |    3 |  7.3 |    9 |    9 |   10 |
|  `T` |    0 |  1.8 |    3 |    4 |    6 |
|**Total**|   |      |      |**30**|**43**|

12,000 run stats for a 5x4 dungeon, no big room:

| Tile |  min |  avg |  p90 |  p95 |  max |
|:----:|:----:|:----:|:----:|:----:|:----:|
|  `+` |    0 |  1.8 |    3 |    4 |    6 |
|  `I` |    0 |  3.9 |    5 |    6 |    8 |
|  `L` |    0 |  4.8 |    7 |    7 |   11 |
|  `O` |    4 |  7.5 |    9 |    9 |   10 |
|  `T` |    0 |  2.0 |    3 |    4 |    6 |
|**Total**|   |      |      |**30**|**41**|

Another run, same criteria:

| Tile |  min |  avg |  p90 |  p95 |  max |
|:----:|:----:|:----:|:----:|:----:|:----:|
|  `+` |    0 |  1.8 |    3 |    4 |    6 |
|  `I` |    0 |  3.9 |    5 |    6 |    8 |
|  `L` |    1 |  4.9 |    7 |    7 |   10 |
|  `O` |    3 |  7.2 |    9 |    9 |   10 |
|  `T` |    0 |  2.1 |    4 |    4 |    6 |
|**Total**|   |      |      |**30**|**40**|