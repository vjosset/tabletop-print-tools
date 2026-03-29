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
| `--n` | `15` | Number of dungeons to generate |
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

`dungeon_{SEED}.png` written to the current directory. The seed is embedded in the filename for exact reproduction.

---

## Sample Usage

```bash
# Default: 15 dungeons at 5×4 tile grid, standard placement, scan theme
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
- Any tile that produces an all-wall 3×3 block is rejected and the map is rerolled.

---

## Reproducing a dungeon

Each PNG is named after its RNG seed (e.g. `dungeon_1436804428.png`). To regenerate that exact dungeon:

```python
from main import DungeonConfig, build_floor_grid, render_png

cfg = DungeonConfig(seed=1436804428, enforce_connected=True, big_room_count=0)
floor, tile_types, tile_rots, big_room_origin, counts, rng = build_floor_grid(cfg)
render_png(floor, spawns=[], player=None, console=None,
           tile_counts=counts, markers=[], out_path="replay.png")
```

---

## Tile count statistics

To find out how many physical tiles a player needs to cover most generated dungeons:

```bash
python -c "from main import collect_stats; collect_stats(12000)"
```

This runs the generator 12,000 times and prints a table of min/avg/p90/p95/max counts per tile type. The p95 column is the recommended ownership count.

### 5×4 dungeon, big room every 3 maps

| Tile | min | avg | p90 | p95 | max |
|:---:|:---:|:---:|:---:|:---:|:---:|
| `+` | 0 | 1.5 | 3 | 3 | 6 |
| `I` | 0 | 3.2 | 5 | 5 | 8 |
| `L` | 1 | 6.2 | 8 | 9 | 13 |
| `O` | 3 | 7.3 | 9 | 9 | 10 |
| `T` | 0 | 1.8 | 3 | 4 | 6 |
| **Total** | | | | **30** | **43** |
