# gow-dungeon-generator

Generates random, gap-free dungeons from the tiles of the *Gears of War* board game (2011). It fills a grid with tile sides so that there's no empty space and every opening leads into the next room. It renders the layout from your own tile scans and writes a build list you can lay out at the table.

---

## Requirements

```bash
pip install pillow
```

You also need scans of the tiles. They aren't included, since they're published game art: keep them local and never commit them. By default the script reads them from `tiles/` in this folder, named `Tile1A.png` … `Tile17B.png` (scanned upright, 495 px per small tile). Without the scans it still works, drawing schematic tiles instead.

---

## Usage

```bash
python main.py [options]
```

| Argument | Default | Description |
|---|---|---|
| `--width` | `5` | Dungeon width in small-tile units |
| `--height` | `4` | Dungeon height in small-tile units |
| `--mediums` | `2` | Number of medium tiles to use |
| `--no-boss` | off | Leave out the large tile (boss room) |
| `--n` | `3` | Number of dungeons to generate |
| `--seed` | random | Generate one specific dungeon (use the same other options as the original run) |
| `--cell-px` | `300` | Pixels per small tile in the PNG |
| `--tiles-dir` | `tiles/` | Folder with the tile scans |
| `--data` | `tiles.json` | Tile data file |
| `--out-dir` | `output/` | Where to write the outputs (created if missing) |

### Tile mixes

There's no empty space, so the tiles used must exactly cover the grid: `smalls + 2 × mediums + 4 × large = width × height`. There are 12 small tiles, 4 mediums and 1 large. For the default 5×4 (20 spaces) that leaves two options, and both use every small tile:

```bash
# 12 smalls + 2 mediums + the large tile as a boss room (default)
python main.py

# 12 smalls + all 4 mediums, no boss room
python main.py --mediums 4 --no-boss
```

If a combination can't fill the grid, the script says why. Smaller grids use a random subset of the small tiles, e.g. `--width 5 --height 3 --mediums 2 --no-boss` uses 11 of them.

### Output

For each dungeon, written to `output/` in this folder:

- **`gow_dungeon_{SEED}.png`**: the layout drawn from your scans. Each tile has a badge showing its place along the path and its ID (e.g. `6 · 17B`). The entrance and exit are marked **IN** and **OUT** outside the map edge. The caption gives the seed, room count, spawn total and loot total.
- **`gow_dungeon_{SEED}.txt`**: the build list. For each room, in path order: tile ID, shape, position, size, rotation, spawn and loot counts, and the room's name and reward if you've filled them in.

Positions are spreadsheet style: columns `A`… from left to right, rows `1`… from top to bottom, given for each tile's top-left square. Rotation is in quarter turns clockwise from the printed orientation (tile ID text upright).

Both outputs are git-ignored.

---

## How it works

Every tile side has exactly two openings, so a dungeon where every opening leads somewhere is a **single winding path**. Its two loose ends face the map edge and become the entrance and exit.

The generator:

1. Picks the physical tiles for this dungeon (see *Tile mixes*).
2. Fills the grid square by square, top-left first. At each empty square it tries the unused tiles, either side, in every rotation, in random order. A placement is allowed only if openings meet openings and walls meet walls on every neighbouring tile, and no more than two openings face the map edge.
3. Backtracks when stuck, and restarts with a new random order if a search takes too long.
4. Checks that the finished map is one connected path, then numbers the rooms from entrance to exit.

Rules:

- Either side of a tile may be used, but never both sides of the same tile in one dungeon.
- Openings only need to be on the matching edge. Exact alignment along the edge doesn't matter.

Each seed always produces the same dungeon for the same options.

---

## Tile data (`tiles.json`)

There's one line per tile side, keyed by the ID printed on the tile:

```json
"7A": {"size": [1, 1], "shape": "S-L", "openings": [[0, 0, "N"], [0, 0, "E"]], "spawns": 1, "loot": 1, "room": {"name": "", "reward": ""}}
```

| Field | Meaning |
|---|---|
| `size` | `[width, height]` in small-tile units, as scanned: small `[1,1]`, medium `[2,1]`, large `[2,2]` |
| `openings` | `[x, y, edge]`: the square within the tile (from its top-left) and which edge (`N`/`E`/`S`/`W`) is open |
| `shape` | Shape code (below) |
| `spawns` | Printed emergence holes (enemy spawn points) |
| `loot` | Printed `?` tokens (loot markers) |
| `room` | Your own room name and reward. Shown in the build list when filled in. |

### Shape codes

| Code | Shape | Sides |
|---|---|---|
| `S-I` | Small, straight through | 1B 2A 3A 4A 5A 5B 6B 7B 8B 10A 11A 12A |
| `S-L` | Small, corner | 1A 2B 3B 4B 6A 7A 8A 9A 9B 10B 11B 12B |
| `M-I` | Medium, end to end | 14A 16B |
| `M-L` | Medium, end plus the side of the same square | 13A 14B |
| `M-J` | Medium, end plus the side of the far square | 15A 15B 16A |
| `M-Z` | Medium, opposite long sides, offset | 13B |
| `X-I` | Large, straight through | 17B |
| `X-Z` | Large, opposite sides, offset | 17A |

### Room rewards

Like the Location cards in the original game, each room can give the players something when they clear it. Fill in `room.name` and `room.reward` for any side, and they'll appear in the build list. Write your own rewards rather than copying the original card text, since this repo is public.
