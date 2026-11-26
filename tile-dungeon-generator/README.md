# tile-dungeon-generator

Generates random, gap-free dungeons from any tile set described in a JSON file. It fills a grid with rooms so there's no empty space, every opening leads into the next room, and every room can be reached. Rooms can be any rectangular size (1×1, 1×2, 2×2… tiles) and are rotated freely. It renders the layout from your room images, with markers for the goal, the player start and things to discover.

A **tile set** (`tilesets/`) only describes the physical rooms you own: their shapes, images and how many copies you have. How maps are built and where markers go is decided by the script, the same way for every tile set.

It replaces [gow-dungeon-generator](../gow-dungeon-generator/). The Gears of War tiles are now one tile set, `gow`.

### Terms

| Term | Meaning |
|---|---|
| **Room** | One image: a physical piece you put on the table. Small rooms cover 1 tile, medium 2 (1×2), large 4 (2×2). |
| **Tile** | One unit of the map grid, the size of a small room. A 5×4 map is 20 tiles. |
| **Square** | One of the 3×3 subdivisions of a tile. A marker sits on one square. |

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
| `--tileset` | (required) | A tile set in `tilesets/` by name (`city`, `gow`), or a path to any tile-set JSON file |
| `--linear` | off | Make a single path from IN to OUT instead of a branching map (see [Kinds of map](#kinds-of-map)) |
| `--width` | `5` | Dungeon width in tiles |
| `--height` | `4` | Dungeon height in tiles |
| `--number-rooms` | off | Prefix each room's badge with its order from the entrance (see Output) |
| `--no-markers` | off | Leave out the goal and `?` markers |
| `--n` | `3` | Number of dungeons to generate |
| `--seed` | random | Generate one specific dungeon (use the same tile set, size and `--linear` as the original run) |
| `--tile-px` | `300` | Pixels per tile in the PNG |
| `--out-dir` | `output/<tileset>/` | Where to write the PNGs (created if missing) |

### Examples

```bash
# A branching City map
python main.py --tileset city

# A single-path Temple map on 6×4
python main.py --tileset temple --linear --width 6

# Gears of War (single path only), with rooms numbered along the path
python main.py --tileset gow --linear --number-rooms
```

### Output

One **`<tileset>_<branching|linear>_dungeon_{SEED}.png`** per dungeon, written to `output/<tileset>/` in this folder. Each room has a badge with its room ID (e.g. `17B`), or, for a room with several images, the name of the image used (e.g. `SM_I_02`), so you know which physical room to put down. With `--number-rooms`, the badge also shows the room's order from the entrance (e.g. `6 · 17B`). Rooms are numbered breadth-first from the entrance, so the numbers are only a route on a linear map. The openings on the map edge are marked **IN** and **OUT** outside the map. The caption gives the tile set, kind of map, seed, room count and how many of each room the map uses.

Rooms whose image is missing are drawn as a schematic: a dark box with its openings and ID.

---

## Kinds of map

Every map has exactly **one large room** (2×2) and **one or two medium rooms** (1×2). Rooms with a single opening (dead ends) are never used. Every map has exactly two openings on the map edge: **IN**, where the players enter, and **OUT**, the exit. IN is never in the large room; OUT may be.

- **Branching** (default): any room with two or more openings. IN is at a random spot on the map edge, and OUT at the spot mirrored through the map's centre (IN on the east edge, top row → OUT on the west edge, bottom row), so they're as far apart as they can be. Two straight rooms (`I` shapes) never join end to end, so there are no long corridors. A tile set needs rooms with three or more openings to branch; `gow` has none, so it only makes linear maps.
- **Linear** (`--linear`): only rooms with exactly two openings. Every room then has one way in and one way out, so the map is a single path through every room, and its two ends are IN and OUT. Where they sit doesn't matter: the route is always the whole map.

Rooms are tried in a random order weighted by shape, like `dungeon-generator`: four openings 4, three openings 5, a straight 2, any other two-opening room 1. Weights only set the order rooms are tried in, so the actual counts don't follow them closely.

---

## Markers

Each tile is 3×3 squares, all floor. Each marker sits on a tile's centre square.

Markers go on **slots**: every other tile, in a checkerboard pattern. So no two markers are on tiles that share an edge, a medium room always has one slot and the large room two.

The players start at **IN**. The tile they enter has no marker, and the pattern runs from there, so the tiles after it are slots.

- **Goal** (green **G**): on one of the large room's two slots, picked at random.
- **?** (orange): every other slot, discovered during play.

Markers have their own random stream, so a seed gives the same layout with or without `--no-markers`.

---

## Tile sets

A tile set is a JSON file. Put it in `tilesets/` to use it by name, with its images in a folder next to it.

```json
{
  "name": "Test01",
  "image_dir": "test01",
  "rooms": {
    "L":    {"openings": "NE", "images": ["L_01.png", "L_02.png"]},
    "T":    {"openings": "NES", "image": "T_01.png"},
    "HALL": {"size": [1, 2], "openings": [[0, 0, "N"], [0, 1, "S"]], "image": "hall.png", "copies": 2},
    "ROOM": {"size": [2, 2], "openings": [[0, 0, "N"], [1, 1, "E"]], "image": "room.png", "copies": 1}
  }
}
```

| Field | Meaning |
|---|---|
| `name` | Shown in the caption. Defaults to the file name. |
| `image_dir` | Folder with the room images, relative to the JSON file. Defaults to the JSON file's own folder. |
| `rooms` | One entry per room, keyed by its ID |

Keys starting with `_` (like `_about`) are ignored, so you can use them for notes. So is any field the script doesn't know.

### Room fields

| Field | Default | Meaning |
|---|---|---|
| `size` | `[1, 1]` | `[width, height]` in tiles, as the image is drawn. 1×1 is small, 1×2 or 2×1 medium, 2×2 large. |
| `openings` | none | Which edges are open. For a 1×1 room, a string such as `"NES"`. For any size, a list of `[x, y, edge]`: the tile within the room (from its top-left) and which of its edges (`N`/`E`/`S`/`W`) is open. |
| `image` | none | Image file name, inside `image_dir` |
| `images` | none | Instead of `image`: several images of the same room, such as art variations. Each entry is a file name or `{"file": "SM_I_01.png", "copies": 2}`. The room is still one shape when the layout is built, so adding images doesn't change which layouts come out. Once the layout is done, the images are spread evenly over the rooms of that shape: their counts differ by at most one, and touching rooms get different images where possible. When every image has `copies`, the room can't be used more often than their total. |
| `copies` | unlimited | How many of this room you own |
| `piece` | the room's ID | Rooms with the same `piece` are the faces of one physical piece and share its copies. For a double-sided piece, give both sides the same `piece` and `copies: 1`, so only one side can be used. |

### How openings work

The grid is made of tiles, each the size of your smallest room. Two rooms connect when one has an opening on an edge and its neighbour has an opening on the facing edge of the touching tile. Where neither has an opening, it's a wall. An opening facing a wall isn't allowed.

Each opening belongs to one tile of a room. For a room bigger than 1×1, each connector should be centred on one tile's edge, not on the middle of the whole room. A 6×6 room made of four 3×3 tiles has its north connectors at the middle of the left half and/or the middle of the right half. A connector at the exact middle of its 6" side would sit on the seam between two tiles and wouldn't line up with a small room's connector.

Openings only need to be on the matching edge. The script doesn't check where along the edge they sit.

---

## How it works

1. The large room and a medium room are placed first, at a random position and rotation.
2. The rest of the grid is filled tile by tile, top-left first. At each empty tile the script tries the usable rooms in random, weighted order, in every rotation. A room is allowed only if openings meet openings and walls meet walls on every placed neighbour, two straights don't join (branching maps), and the number of openings facing the map edge stays within the limit.
3. It backtracks when stuck. It also backtracks early when the remaining rooms can no longer cover the empty tiles. If a search takes too long, it starts again in a new random order.
4. It checks that every room can be reached and that the room counts are met, then orders the rooms outwards from the entrance (used for room numbering).
5. Going outwards from the entrance, it gives each room with several images the one used least so far, preferring one that no touching room shows.
6. It places the markers.

Each seed always produces the same dungeon for the same tile set, size and kind of map.

---

## Included tile sets

### `gow`: Gears of War board game (2011)

The scans aren't included, since they're published game art. Keep them in `tilesets/gow/`, named `Tile1A.png` … `Tile17B.png` (scanned upright). The folder is git-ignored: never commit them.

Each physical piece has two sides (A and B), each a room, and only one side is used per dungeon. Every side has exactly two openings, so `gow` only makes linear maps (`--linear`), and `--number-rooms` makes the numbers follow the path. Rooms 1–12 are small, 13–16 medium (2×1) and 17 large (2×2). There's no empty space, so the rooms must exactly cover the grid: on the default 5×4 grid (20 tiles), that's 12 smalls, 2 mediums and room 17.

### `test01`: first test rooms

Rooms with centred connectors: 1×1 rooms in the same five shapes as `dungeon-generator` (`X` cross, `T`, `L`, `I` and `O` open room), plus `Medium_I`, a 1×2 straight corridor, and `Large_X`, a 2×2 room with two openings on different tiles.

### `city`, `temple`

Rooms with centred connectors, from ambientCG textures. Both sets have the same shapes and differ only in art: smalls `D` (dead end, never used), `I`, `L`, `T` and `X`; mediums (1×2) `I`, `L`, `J`, `S` and `Z`; larges (2×2) `L`, `S` and `Z`. Each room can be used any number of times. They make both kinds of map: branching by default, and with `--linear` they use only the two-opening rooms.
