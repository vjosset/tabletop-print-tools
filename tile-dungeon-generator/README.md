# tile-dungeon-generator

Generates random, gap-free dungeons from any tile set described in a JSON file. It fills a grid with tiles so there's no empty space, every opening leads into the next tile, and every tile can be reached. Tiles can be any rectangular size (3×3, 6×3, 6×6…) and are rotated freely. It renders the layout from your tile images.

It replaces [gow-dungeon-generator](../gow-dungeon-generator/). The Gears of War tiles are now one tile set, `gow`.

---

## Requirements

```bash
pip install pillow
```

---

## Usage

```bash
python main.py --tileset <name or path> [options]
```

| Argument | Default | Description |
|---|---|---|
| `--tileset` | (required) | A tile set in `tilesets/` by name (`gow`, `test01`), or a path to any tile-set JSON file |
| `--width` | tile set's, else `5` | Dungeon width in grid squares |
| `--height` | tile set's, else `4` | Dungeon height in grid squares |
| `--border-openings` | tile set's, else `0` | How many openings may face the map edge: `N`, or `MIN-MAX` such as `0-2` |
| `--min TAG=N` | tile set's | Use at least N tiles with this tag or tile ID. Repeatable. |
| `--max TAG=N` | tile set's | Use at most N tiles with this tag or tile ID. Repeatable. |
| `--number-rooms` / `--no-number-rooms` | tile set's, else off | Prefix each tile's badge with its order from the entrance (see Output) |
| `--placement` | `standard` | Item markers: `standard`, `discovery` or `none` (see Item markers) |
| `--n` | `3` | Number of dungeons to generate |
| `--seed` | random | Generate one specific dungeon (use the same tile set and options as the original run) |
| `--cell-px` | `300` | Pixels per grid square in the PNG |
| `--out-dir` | `output/<tileset>/` | Where to write the PNGs (created if missing) |

### Examples

```bash
# Gears of War: 12 smalls + 2 mediums + the boss room
python main.py --tileset gow

# Gears of War: all 4 mediums, no boss room
python main.py --tileset gow --max medium=4 --max boss=0

# Test tiles on a bigger map, with an entrance and an exit, and at most 3 open rooms
python main.py --tileset test01 --width 6 --height 5 --border-openings 2 --max O=3
```

### Output

One **`<tileset>_dungeon_{SEED}.png`** per dungeon, written to `output/<tileset>/` in this folder. Each tile has a badge with its tile ID (e.g. `17B`), or, for a tile with several images, the name of the image used (e.g. `SM_I_02`), so you know which physical tile to put down. With room numbering on, the badge also shows the room's order from the entrance (e.g. `6 · 17B`). Rooms are numbered breadth-first from the entrance, so the numbers are only a route when the map is a single path; in a branching map, consecutive numbers can sit on different branches. That's why numbering is off unless the tile set or `--number-rooms` turns it on. Openings on the map edge are marked **IN** (the first) and **OUT** outside the map. The caption gives the tile set, seed, room count and how many of each tile the map uses.

Tiles whose image is missing are drawn as a schematic: a dark box with its openings and ID.

### Item markers

Each grid square is 3×3 spaces, all floor. Markers sit on a single space. Walls are the tile edges, and a connector is the middle space of a grid square's edge. Distances are walking distances through connectors, so markers spread along the route, not just across the map.

The player starts at the **IN** marker. If the dungeon has no entrance (`border_openings` of `0`), a blue marker shows the start instead.

- **`standard`** (default): a green console on the grid square farthest from the start, 3 red spawns spread as far apart as possible, then 3 orange loot markers in the least covered areas, preferring dead-end tiles. Each grid square holds at most one of these, and loot never covers a tile's badge.
- **`discovery`**: an orange **?** on every other grid square, in a checkerboard pattern that skips the start square.
- **`none`**: no markers.

Markers have their own random stream, so a seed gives the same layout with any `--placement`.

---

## Tile sets

A tile set is a JSON file. Put it in `tilesets/` to use it by name, with its images in a folder next to it.

```json
{
  "name": "Test01",
  "image_dir": "test01",
  "grid": {"width": 5, "height": 4},
  "border_openings": 0,
  "limits": {"big": {"min": 1, "max": 1}},
  "tiles": {
    "L":    {"openings": "NE", "images": ["L_01.png", "L_02.png"], "weight": 1},
    "HALL": {"size": [2, 1], "openings": [[0, 0, "W"], [1, 0, "E"]], "image": "hall.png", "copies": 2},
    "ROOM": {"size": [2, 2], "openings": [[0, 0, "N"], [1, 0, "E"], [1, 1, "S"], [0, 1, "W"]],
             "image": "room.png", "copies": 1, "tags": ["big"]}
  }
}
```

### Tile set fields

| Field | Meaning |
|---|---|
| `name` | Shown in the caption. Defaults to the file name. |
| `image_dir` | Folder with the tile images, relative to the JSON file. Defaults to the JSON file's own folder. |
| `grid` | Default `width` and `height` in grid squares |
| `border_openings` | How many openings may face the map edge: a number, `"MIN-MAX"`, or `[min, max]`. `0` means a closed dungeon. |
| `number_rooms` | `true` to number the rooms on the map (default `false`). Use it only for tile sets whose dungeons are a single path. |
| `limits` | Per tag or tile ID: `min` and/or `max` number of tiles to use |
| `tiles` | One entry per tile, keyed by its ID |

Keys starting with `_` (like `_about`) are ignored, so you can use them for notes. So is any field the script doesn't know.

### Tile fields

| Field | Default | Meaning |
|---|---|---|
| `size` | `[1, 1]` | `[width, height]` in grid squares, as the image is drawn |
| `openings` | none | Which edges are open. For a 1×1 tile, a string such as `"NES"`. For any size, a list of `[x, y, edge]`: the square within the tile (from its top-left) and which of its edges (`N`/`E`/`S`/`W`) is open. |
| `image` | none | Image file name, inside `image_dir` |
| `images` | none | Instead of `image`: several images of the same tile, such as art variations. Each entry is a file name or `{"file": "SM_I_01.png", "copies": 2}`. The tile is still one shape when the layout is built, so adding images doesn't change which layouts come out. Once the layout is done, the images are spread evenly over the tiles of that shape: their counts differ by at most one, and touching tiles get different images where possible. When every image has `copies`, the tile can't be used more often than their total. |
| `copies` | unlimited | How many of this tile you own |
| `piece` | the tile's ID | Tiles with the same `piece` are the faces of one physical tile and share its copies. For a double-sided tile, give both sides the same `piece` and `copies: 1`, so only one side can be used. |
| `tags` | none | Labels used by `limits`, `--min` and `--max` (e.g. `"medium"`, `"boss"`). Every tile also counts as tagged with its own ID. |
| `weight` | `1` | How often the tile is tried relative to others. `0` leaves it out. |

### How openings work

The grid is made of squares the size of your smallest tile. Two tiles connect when one has an opening on an edge and its neighbour has an opening on the facing edge of the touching square. Where neither has an opening, it's a wall. An opening facing a wall isn't allowed.

Each opening belongs to one square of a tile. For a tile bigger than 1×1, each connector should be centred on one square's edge, not on the middle of the whole tile. A 6×6 room made of four 3×3 squares has its north connectors at the middle of the left half and/or the middle of the right half. A connector at the exact middle of its 6" side would sit on the seam between two squares and wouldn't line up with a 3×3 tile's connector.

Openings only need to be on the matching edge. The script doesn't check where along the edge they sit.

---

## How it works

1. Tiles needed by a `min` limit (e.g. the boss room) are placed first, at a random position and rotation.
2. The rest of the grid is filled square by square, top-left first. At each empty square the script tries the available tiles in random, weighted order, in every rotation. A tile is allowed only if openings meet openings and walls meet walls on every placed neighbour, and the number of openings facing the map edge stays within the limit.
3. It backtracks when stuck. It also backtracks early when the remaining tiles can no longer cover the empty squares. If a search takes too long, it starts again in a new random order.
4. It checks that every tile can be reached, then orders the rooms outwards from the entrance (used for room numbering, when it's on).
5. Going outwards from the entrance, it gives each tile with several images the one used least so far, preferring one that no touching tile shows.

Each seed always produces the same dungeon for the same tile set and options.

---

## Included tile sets

### `gow`: Gears of War board game (2011)

The scans aren't included, since they're published game art. Keep them in `tilesets/gow/`, named `Tile1A.png` … `Tile17B.png` (scanned upright). The folder is git-ignored: never commit them.

Each physical tile has two sides (A and B), and only one side is used per dungeon. Every side has exactly two openings, so each dungeon is a single winding path. That's why the tile set sets `border_openings` to `2` (an entrance and an exit), and why it turns on `number_rooms`: the numbers follow the path.

| Tag | Tiles | Default limit |
|---|---|---|
| `small` | 1–12 (1×1) | |
| `medium` | 13–16 (2×1) | at most 2 |
| `large`, `boss` | 17 (2×2) | exactly 1 |

There's no empty space, so the tiles must exactly cover the grid. For the default 5×4 grid (20 squares), that's either 12 smalls + 2 mediums + the boss room (the default) or 12 smalls + 4 mediums (`--max medium=4 --max boss=0`).

### `test01`: first test tiles

Tiles with centred connectors: 1×1 squares in the same five shapes as `dungeon-generator` (`X` cross, `T`, `L`, `I` and `O` open room), plus `Medium_I`, a 1×2 straight corridor, and `Large_X`, a 2×2 room with one opening on each side (each on a different square, like a pinwheel). Each can be used any number of times, except `Large_X`, which is limited to one per dungeon. The squares' weights match `dungeon-generator`'s defaults, and `Medium_I` has the same weight as `I`. The dungeon is closed (no openings on the map edge) unless you pass `--border-openings`.
