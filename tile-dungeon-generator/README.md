# tile-dungeon-generator

Generates random, gap-free dungeons from any tile set described in a JSON file. It fills a grid with tiles so there's no empty space, every opening leads into the next tile, and every tile can be reached. Tiles can be any rectangular size (3×3, 6×3, 6×6…) and are rotated freely. It renders the layout from your tile images, with game markers placed by a rules file.

Two kinds of JSON file drive it, and the script holds no game data of its own:

- a **tile set** (`tilesets/`) describes the physical tiles you own;
- a **rules file** (`rules/`) describes the game: which markers exist and where they go.

Any tile set works with any rules file, so a new game mode or theme is a new rules file.

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
| `--rules` | tile set's, else `default` | A rules file in `rules/` by name (`default`, `linear`), or a path to any rules JSON file |
| `--placement` | rules file's | Item markers: `standard`, `discovery` or `none` (see Item markers) |
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

# City tiles on 4×4, with the linear rules swapped for the default ones
python main.py --tileset city-linear --width 4 --height 4 --rules default
```

### Output

One **`<tileset>_dungeon_{SEED}.png`** per dungeon, written to `output/<tileset>/` in this folder. Each tile has a badge with its tile ID (e.g. `17B`), or, for a tile with several images, the name of the image used (e.g. `SM_I_02`), so you know which physical tile to put down. With room numbering on, the badge also shows the room's order from the entrance (e.g. `6 · 17B`). Rooms are numbered breadth-first from the entrance, so the numbers are only a route when the map is a single path; in a branching map, consecutive numbers can sit on different branches. That's why numbering is off unless the tile set or `--number-rooms` turns it on. Openings on the map edge are marked **IN** (the first) and **OUT** outside the map. The caption gives the tile set, rules file, seed, room count and how many of each tile the map uses.

Tiles whose image is missing are drawn as a schematic: a dark box with its openings and ID.

### Item markers

Each grid square is 3×3 spaces, all floor. Each marker sits on one space. Walls are the tile edges, and a connector is the middle space of a grid square's edge.

The player starts at the **IN** marker. If the dungeon has no entrance (`border_openings` of `0`), a blue marker shows the start instead. No other marker goes on the start tile.

- **`standard`**: markers are placed by the rules file's rules (see [Rules files](#rules-files)). `rules/default.json` places:
  - a green **console** 3 or more tiles from the start, picked at random;
  - a red **spawn** 2–4 tiles from the start, then 2 more spawns at least 2 tiles away, spread as far apart as possible;
  - 3 orange **loot** markers spread out, preferring tiles off the main route (the shortest route from the start to the console and the exits), then dead ends. A linear dungeon has no such tiles, so there loot just spreads out.
- **`discovery`**: an orange **?** on every other grid square, in a checkerboard pattern, skipping the start tile.
- **`none`**: no markers.

Distances count tiles walked through, so a 2×2 room counts as one. A tile holds at most one marker of each type. Markers stay off connectors and tile badges. Markers have their own random stream, so a seed gives the same layout with any placement.

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
| `rules` | The rules file to use when `--rules` isn't given: a name in `rules/`, or a path (relative to the tile set). Defaults to `default`. |
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

## Rules files

A rules file is a JSON file describing the game: its marker types and where they go. Put it in `rules/` to use it by name. A tile set names its usual rules with `"rules"`, and `--rules` overrides that. Changing a game mode or a theme (a heist with `vault` and `guard` instead of `console` and `spawn`) is just a new rules file.

| Included | For |
|---|---|
| `default` | Any dungeon: console, spawns and loot, with loot kept off the main route |
| `linear` | Single-path dungeons (`city-linear`, `temple-linear`): spawns spread along the path |

```json
{
  "strategy": "standard",
  "marker_types": {
    "start":   {"color": "#2850dc"},
    "console": {"color": "#28b450", "objective": true},
    "guard":   {"color": "#dc2828"},
    "loot":    {"color": "#dc8c28", "size": "small"}
  },
  "markers": [
    {"type": "console", "distance": [3, null]},
    {"type": "guard",   "distance": [0, 1], "from": "console"},
    {"type": "loot",    "count": 3, "pick": "spread", "prefer": ["off_route", "dead_end"],
     "spread_from": ["start", "guard", "loot"]}
  ]
}
```

`strategy` is the default for `--placement`. `marker_types` lists every marker type the rules use. Two names have a special role:

- `start` (required): the player start, drawn when the dungeon has no IN marker;
- `discovery` (required by the `discovery` strategy): the marker it puts on every other grid square.

| Marker type field | Default | Meaning |
|---|---|---|
| `color` | (required) | `"#rrggbb"` or `[r, g, b]` |
| `size` | `"large"` | How big the dot is drawn: `"large"` or `"small"` (not related to tile size) |
| `label` | none | Text drawn on the marker, such as `"?"` |
| `objective` | `false` | The main route runs from the start to markers of this type (and to the exits) |
| Any rule field | | `distance`, `prefer`, `pick`… set on a type are defaults for that type's rules. A rule's own value wins. |

`markers` is an ordered list of rules. Each rule places `count` markers, one at a time:

| Rule field | Default | Meaning |
|---|---|---|
| `type` | (required) | A marker type |
| `count` | `1` | How many to place |
| `distance` | `[1, null]` | `[min, max]` tiles from `from`. `null` means no maximum. When no tile is in range, the closest one is used. |
| `from` | `"start"` | `"start"`, or a type placed by an earlier rule (distance to the nearest one) |
| `pick` | `"random"` | `"random"` picks any tile that qualifies. `"spread"` picks the one farthest from the `spread_from` markers. |
| `spread_from` | `["start", <type>]` | What `"spread"` keeps away from |
| `prefer` | none | Preferences tried in order, each applied only if some tile still meets it: `"off_route"` (not on the main route), `"dead_end"` (a tile with one way in or out), or a tile tag such as `"large"`. For a tag, tagged tiles with no marker yet come first. So `["large", "medium"]` means an empty large tile, else a large tile, else a medium one, else anywhere. |

Rules never fail: when a requirement can't be met (a tiny map, more markers than tiles), it relaxes.

Keys starting with `_` (like `_about`) are ignored here too.

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
