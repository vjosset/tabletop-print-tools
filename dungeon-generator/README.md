# dungeon-generator

Generates randomized dungeon layouts from modular 3×3 tiles, outputting PNG images.

---

## Requirements

```bash
pip install pillow
```

---

## Usage

```bash
python main.py [options]
```

### Options

| Argument | Default | Description |
|---|---|---|
| `--width` | `5` | Dungeon width in tiles |
| `--height` | `4` | Dungeon height in tiles |
| `--n` | `3` | Number of dungeons to generate |
| `--placement` | `standard` | Marker placement strategy: `standard`, `discovery`, or `none` |
| `--theme` | `scan` | Render theme: `scan` (green CRT look) or `clean` (dark minimal) |
| `--cell-px` | `128` | Cell size in pixels; controls output resolution |
| `--tile-images` | off | Use tile artwork from the `tiles/` folder instead of drawn geometry |
| `--tiles-dir` | `tiles` | Directory containing tile image variants |
| `--overlay-shapes` | off | Overlay drawn geometry at 50% opacity on top of tile images |

### Placement strategies

- **standard**: Places a player start (blue), console/objective (green), 3 enemy spawns (red), and 3 loot locations (orange) using spread logic.
- **discovery**: Places a player start and question-mark markers in a checkerboard pattern across reachable cells.
- **none**: Generates the map only, no markers.

### Output

One `dungeon_{SEED}.png` per map, written to the current directory. The seed is embedded in the filename for reproduction (see below).

Below the map, each PNG has a caption listing how many of each tile type that map uses, e.g. `+:2 I:4 L:4 O:8 T:2`. Use it to pull the right physical tiles before laying out the map. The caption is about 30% of a cell tall, so it scales with `--cell-px`, and it shrinks to fit when the map is too narrow to hold it.

---

## Sample Usage

```bash
# Default: 3 dungeons at 5×4 tile grid, standard placement, scan theme
python main.py

# Wider dungeon
python main.py --width 7 --height 4 --n 15

# Discovery placement, clean theme
python main.py --placement discovery --theme clean

# Use tile artwork with geometry overlay for alignment check
python main.py --tile-images --overlay-shapes
```

---

## How it works

The dungeon is a grid of tiles (default 5×4), each tile being 3×3 cells. Each tile is chosen randomly by type, randomly rotated, and placed. Edge and corner tiles are constrained so corridors don't exit the map boundary.

### Tile types

| Symbol | Shape | Connections |
|---|---|---|
| `+` | Cross | N, E, S, W |
| `T` | T-junction | 3 directions |
| `L` | Corner | 2 adjacent |
| `I` | Straight | 2 opposite |
| `O` | Open room | All sides |

### Placement rules

- `+` and `T` tiles are never placed on edge or corner positions.
- `I` tiles are allowed on edges but not corners.
- `L` and `O` tiles can go anywhere.
- Two `O` tiles may never be orthogonally adjacent (prevents large featureless open areas).
- Two `I` tiles may never sit end to end on the same axis (prevents long 1-wide corridors).
- Any tile that produces an all-wall 3×3 block is rejected and the map is rerolled.
- Disconnected tiles are rerolled; any floor still unreachable after that is walled off.

---

## Reproducing a dungeon

Each PNG is named after its RNG seed (e.g. `dungeon_1436804428.png`). To regenerate that exact dungeon, including its markers:

```python
from main import DungeonConfig, build_floor_grid, render_png, PLACEMENT_STRATEGIES

cfg = DungeonConfig(seed=1436804428, enforce_connected=True, big_room_count=0,
                    tile_grid_w=5, tile_grid_h=4)   # match the --width/--height used
floor, tile_types, tile_rots, big_room_origin, counts, rng = build_floor_grid(cfg)
spawns, player, console, markers = PLACEMENT_STRATEGIES["standard"](  # match --placement
    floor, tile_types, big_room_origin, cfg, rng)
render_png(floor, spawns=spawns, player=player, console=console, markers=markers,
           tile_counts=counts, theme="scan", tile_types=tile_types, tile_rots=tile_rots,
           rng=rng, out_path="replay.png")
```

The seed fixes the layout and markers; the width, height and placement strategy must match the original run. With `--tile-images`, also pass `use_tile_images=True` (and `tiles_dir`) to pick the same image variants.

---

## Tile count statistics

To find out how many physical tiles a player needs to cover most generated dungeons:

```bash
python -c "from main import collect_stats; collect_stats(12000, big_room_every=0)"
```

This runs the generator 12,000 times on the default 5×4 grid and prints a table of min/avg/p90/p95/max counts per tile type. The p95 column is the recommended ownership count: owning that many of a tile type covers it in about 95% of maps.

`big_room_every=0` matches what `main.py` generates, since the command line never adds big rooms. Leave it out (default `3`) to add a 2×2 big room of `O` tiles to every third map.

### 5×4 dungeon, no big rooms (matches `main.py`)

| Tile | min | avg | p90 | p95 | max |
|:---:|:---:|:---:|:---:|:---:|:---:|
| `+` | 0 | 2.0 | 3 | 4 | 6 |
| `I` | 0 | 4.1 | 6 | 6 | 8 |
| `L` | 2 | 5.0 | 7 | 7 | 11 |
| `O` | 3 | 6.8 | 8 | 8 | 10 |
| `T` | 0 | 2.2 | 4 | 4 | 6 |
| **Sum of p95** | | | | **29** | |

Every 5×4 map uses exactly 20 tiles; the sum of p95 is how many physical tiles to own so each type individually is covered about 95% of the time.
