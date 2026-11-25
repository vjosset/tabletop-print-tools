# tile-dungeon-generator

Generates random, gap-free dungeons from any tile set described in a JSON file. It fills a grid with rooms so there's no empty space, every opening leads into the next room, and every room can be reached. Rooms can be any rectangular size (1×1, 1×2, 2×2… tiles) and are rotated freely. It renders the layout from your room images, with game markers placed by a rules file.

Two kinds of JSON file drive it, and the script holds no game data of its own:

- a **tile set** (`tilesets/`) describes the physical rooms you own;
- a **rules file** (`rules/`) describes the game: which markers exist and where they go.

Any tile set works with any rules file, so a new game mode or theme is a new rules file.

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
| `--tileset` | (required) | A tile set in `tilesets/` by name (`gow`, `test01`), or a path to any tile-set JSON file |
| `--width` | tile set's, else `5` | Dungeon width in tiles |
| `--height` | tile set's, else `4` | Dungeon height in tiles |
| `--border-openings` | tile set's, else `0` | How many openings may face the map edge: `N`, or `MIN-MAX` such as `0-2` |
| `--min TAG=N` | tile set's | Use at least N rooms with this tag or room ID. Repeatable. |
| `--max TAG=N` | tile set's | Use at most N rooms with this tag or room ID. Repeatable. |
| `--number-rooms` / `--no-number-rooms` | tile set's, else off | Prefix each room's badge with its order from the entrance (see Output) |
| `--rules` | tile set's, else `default` | A rules file in `rules/` by name (`default`, `linear`), or a path to any rules JSON file |
| `--placement` | rules file's | Item markers: `standard` or `none` (see Item markers) |
| `--n` | `3` | Number of dungeons to generate |
| `--seed` | random | Generate one specific dungeon (use the same tile set and options as the original run) |
| `--tile-px` | `300` | Pixels per tile in the PNG (`--cell-px` still works) |
| `--out-dir` | `output/<tileset>/` | Where to write the PNGs (created if missing) |

### Examples

```bash
# Gears of War: 12 smalls + 2 mediums + the boss room
python main.py --tileset gow

# Gears of War: all 4 mediums, no boss room
python main.py --tileset gow --max medium=4 --max large=0

# Test rooms on a bigger map, with an entrance and an exit, and at most 3 open rooms
python main.py --tileset test01 --width 6 --height 5 --border-openings 2 --max O=3

# City rooms on 4×4, with the linear rules swapped for the default ones
python main.py --tileset city-linear --width 4 --height 4 --rules default
```

### Output

One **`<tileset>_dungeon_{SEED}.png`** per dungeon, written to `output/<tileset>/` in this folder. Each room has a badge with its room ID (e.g. `17B`), or, for a room with several images, the name of the image used (e.g. `SM_I_02`), so you know which physical room to put down. With room numbering on, the badge also shows the room's order from the entrance (e.g. `6 · 17B`). Rooms are numbered breadth-first from the entrance, so the numbers are only a route when the map is a single path; in a branching map, consecutive numbers can sit on different branches. That's why numbering is off unless the tile set or `--number-rooms` turns it on. Openings on the map edge are marked **IN** (the first) and **OUT** outside the map. The caption gives the tile set, rules file, seed, room count and how many of each room the map uses.

Rooms whose image is missing are drawn as a schematic: a dark box with its openings and ID.

### Item markers

Each tile is 3×3 squares, all floor. Each marker sits on one square. Walls are the room edges, and a connector is the middle square of a tile's edge.

The player starts at the **IN** marker. If the dungeon has no entrance (`border_openings` of `0`), a blue marker shows the start instead, in a random small room on the checkerboard (see below). No other marker goes in the start room.

Markers go on **slots**: the centre square of every other tile, in a checkerboard pattern. So no two markers are on tiles that share an edge, every medium room has a slot (a large room has two), and every branch two or more tiles long has at least one. The start follows the same pattern. With an entrance, the entrance tile sets which checkerboard colour is used. Without one, the colour that reaches more dead ends is used, and the start goes on it. A dead end one tile long on the other colour gets no slot.

- **`standard`**: the rules file decides what goes on which slot (see [Rules files](#rules-files)), and its `fill` type goes on every slot left. `rules/default.json` places:
  - a green **console** 3 or more rooms from the start, picked at random;
  - a red **spawn** 2–4 rooms from the start, then 2 more spawns at least 2 rooms away, spread as far apart as possible. Spawns prefer big rooms (medium or large), then junctions, where there's room to fight;
  - 3 orange **loot** markers spread out, preferring rooms off the main route (the shortest route from the start to the console and the exits), then dead ends. A linear dungeon has no such rooms, so there loot just spreads out;
  - a purple **?** event on every slot left (2 or 3 on a 5×4 map), decided at the table.
- **`none`**: no markers.

`--rules discovery` puts an orange **?** on every slot and nothing else.

Distances count rooms walked through, so a 2×2 room counts as one. A room holds at most one marker of each type. Markers have their own random stream, so a seed gives the same layout with any placement.

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
  "rooms": {
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
| `image_dir` | Folder with the room images, relative to the JSON file. Defaults to the JSON file's own folder. |
| `grid` | Default `width` and `height` in tiles |
| `border_openings` | How many openings may face the map edge: a number, `"MIN-MAX"`, or `[min, max]`. `0` means a closed dungeon. |
| `number_rooms` | `true` to number the rooms on the map (default `false`). Use it only for tile sets whose dungeons are a single path. |
| `limits` | Per tag or room ID: `min` and/or `max` number of rooms to use |
| `no_connect` | Pairs of tags or room IDs that may never be joined through an opening, e.g. `[["straight", "straight"]]` so straight corridors never line up into a long one. Rooms that only touch, with a wall between them, are fine. Too strict a list can leave no layout. |
| `rules` | The rules file to use when `--rules` isn't given: a name in `rules/`, or a path (relative to the tile set). Defaults to `default`. |
| `rooms` | One entry per room, keyed by its ID. Older tile sets call it `tiles`, which still works. |

Keys starting with `_` (like `_about`) are ignored, so you can use them for notes. So is any field the script doesn't know.

### Room fields

| Field | Default | Meaning |
|---|---|---|
| `size` | `[1, 1]` | `[width, height]` in tiles, as the image is drawn |
| `openings` | none | Which edges are open. For a 1×1 room, a string such as `"NES"`. For any size, a list of `[x, y, edge]`: the tile within the room (from its top-left) and which of its edges (`N`/`E`/`S`/`W`) is open. |
| `image` | none | Image file name, inside `image_dir` |
| `images` | none | Instead of `image`: several images of the same room, such as art variations. Each entry is a file name or `{"file": "SM_I_01.png", "copies": 2}`. The room is still one shape when the layout is built, so adding images doesn't change which layouts come out. Once the layout is done, the images are spread evenly over the rooms of that shape: their counts differ by at most one, and touching rooms get different images where possible. When every image has `copies`, the room can't be used more often than their total. |
| `copies` | unlimited | How many of this room you own |
| `piece` | the room's ID | Rooms with the same `piece` are the faces of one physical piece and share its copies. For a double-sided piece, give both sides the same `piece` and `copies: 1`, so only one side can be used. |
| `tags` | none | Labels used by `limits`, `--min`, `--max` and the rules' `prefer` (e.g. `"medium"`, `"boss"`). Every room also counts as tagged with its own ID. |
| `weight` | `1` | How often the room is tried relative to others. `0` leaves it out. |

### How openings work

The grid is made of tiles, each the size of your smallest room. Two rooms connect when one has an opening on an edge and its neighbour has an opening on the facing edge of the touching tile. Where neither has an opening, it's a wall. An opening facing a wall isn't allowed.

Each opening belongs to one tile of a room. For a room bigger than 1×1, each connector should be centred on one tile's edge, not on the middle of the whole room. A 6×6 room made of four 3×3 tiles has its north connectors at the middle of the left half and/or the middle of the right half. A connector at the exact middle of its 6" side would sit on the seam between two tiles and wouldn't line up with a small room's connector.

Openings only need to be on the matching edge. The script doesn't check where along the edge they sit.

---

## Rules files

A rules file is a JSON file describing the game: its marker types and where they go. Put it in `rules/` to use it by name. A tile set names its usual rules with `"rules"`, and `--rules` overrides that. Changing a game mode or a theme (a heist with `vault` and `guard` instead of `console` and `spawn`) is just a new rules file.

| Included | For |
|---|---|
| `default` | Any dungeon (`gow`, `city`, `temple`…): console, spawns and loot, with loot kept off the main route, and a `?` event on every other slot |
| `linear` | Single-path dungeons (`city-linear`, `temple-linear`): spawns spread along the path, and a `?` event on every other slot |
| `discovery` | A `?` on every slot, nothing else |

```json
{
  "strategy": "standard",
  "fill": "event",
  "marker_types": {
    "start":   {"color": "#2850dc"},
    "console": {"color": "#28b450", "objective": true},
    "guard":   {"color": "#dc2828"},
    "loot":    {"color": "#dc8c28", "size": "small"},
    "event":   {"color": "#8c50c8", "size": "small", "label": "?"}
  },
  "markers": [
    {"type": "console", "distance": [3, null]},
    {"type": "guard",   "distance": [0, 1], "from": "console"},
    {"type": "loot",    "count": 3, "pick": "spread", "prefer": ["off_route", "dead_end"],
     "spread_from": ["start", "guard", "loot"]}
  ]
}
```

`strategy` is the default for `--placement` (`standard` or `none`). `fill` is the marker type put on every slot the rules leave empty; without it, those slots stay empty. `marker_types` lists every marker type the rules use. `start` is required: it's the player start, drawn when the dungeon has no IN marker.

| Marker type field | Default | Meaning |
|---|---|---|
| `color` | (required) | `"#rrggbb"` or `[r, g, b]` |
| `size` | `"large"` | How big the dot is drawn: `"large"` or `"small"` (not related to room size) |
| `label` | none | Text drawn on the marker, such as `"?"` |
| `objective` | `false` | The main route runs from the start to markers of this type (and to the exits) |
| Any rule field | | `distance`, `prefer`, `pick`… set on a type are defaults for that type's rules. A rule's own value wins. |

`markers` is an ordered list of rules. Each rule places `count` markers, one at a time, each on a free slot. Distances and preferences are about the slot's room:

| Rule field | Default | Meaning |
|---|---|---|
| `type` | (required) | A marker type |
| `count` | `1` | How many to place |
| `distance` | `[1, null]` | `[min, max]` rooms from `from`. `null` means no maximum. When no room is in range, the closest one is used. |
| `from` | `"start"` | `"start"`, or a type placed by an earlier rule (distance to the nearest one) |
| `pick` | `"random"` | `"random"` picks any room that qualifies. `"spread"` picks the one farthest from the `spread_from` markers. |
| `spread_from` | `["start", <type>]` | What `"spread"` keeps away from |
| `prefer` | none | Preferences tried in order, each applied only if some room still meets it: `"off_route"` (not on the main route), `"dead_end"` (a room with one way in or out), `"junction"` (three or more ways in or out), `"big"` (a room covering more than one tile), or a room tag such as `"large"`. The built-in ones work with any tile set; a tag must exist in the tile set. Preferences narrow one after another: `["big", "junction"]` means a big junction, else any big room, else a junction. For a tag, tagged rooms with no marker yet come first. So `["large", "medium"]` means an empty large room, else a large room, else a medium one, else anywhere. |

Rules never fail: when a requirement can't be met, it relaxes. When the slots run out (a tiny map, or more markers than slots), the remaining markers go on the other tiles, then are dropped.

Keys starting with `_` (like `_about`) are ignored here too.

---

## How it works

1. Rooms needed by a `min` limit (e.g. the boss room) are placed first, at a random position and rotation.
2. The rest of the grid is filled tile by tile, top-left first. At each empty tile the script tries the available rooms in random, weighted order, in every rotation. A room is allowed only if openings meet openings and walls meet walls on every placed neighbour, no opening joins a `no_connect` pair, and the number of openings facing the map edge stays within the limit.
3. It backtracks when stuck. It also backtracks early when the remaining rooms can no longer cover the empty tiles. If a search takes too long, it starts again in a new random order.
4. It checks that every room can be reached, then orders the rooms outwards from the entrance (used for room numbering, when it's on).
5. Going outwards from the entrance, it gives each room with several images the one used least so far, preferring one that no touching room shows.

Each seed always produces the same dungeon for the same tile set and options.

---

## Included tile sets

### `gow`: Gears of War board game (2011)

The scans aren't included, since they're published game art. Keep them in `tilesets/gow/`, named `Tile1A.png` … `Tile17B.png` (scanned upright). The folder is git-ignored: never commit them.

Each physical piece has two sides (A and B), each a room, and only one side is used per dungeon. Every side has exactly two openings, so each dungeon is a single winding path. That's why the tile set sets `border_openings` to `2` (an entrance and an exit), and why it turns on `number_rooms`: the numbers follow the path.

| Tag | Rooms | Default limit |
|---|---|---|
| `small` | 1–12 (1×1) | |
| `medium` | 13–16 (2×1) | 1–2 |
| `large`, `boss` | 17 (2×2) | exactly 1 |

There's no empty space, so the rooms must exactly cover the grid. For the default 5×4 grid (20 tiles), that's 12 smalls + 2 mediums + the boss room (the default) or 12 smalls + 4 mediums (`--max medium=4 --max large=0`).

### `test01`: first test rooms

Rooms with centred connectors: 1×1 rooms in the same five shapes as `dungeon-generator` (`X` cross, `T`, `L`, `I` and `O` open room), plus `Medium_I`, a 1×2 straight corridor, and `Large_X`, a 2×2 room with one opening on each side (each on a different tile, like a pinwheel). Each can be used any number of times, except `Large_X`, which is limited to one per dungeon. The 1×1 rooms' weights match `dungeon-generator`'s defaults, and `Medium_I` has the same weight as `I`. The dungeon is closed (no openings on the map edge) unless you pass `--border-openings`.

### `city`, `temple`: branching dungeons

Rooms with centred connectors, from ambientCG textures. Both sets have the same shapes and differ only in art: smalls `D` (dead end, one opening), `I`, `L`, `T` and `X`; mediums (1×2) `I`, `L`, `J`, `S` and `Z`; larges (2×2) `L`, `S` and `Z`. Junctions and dead ends make the map branch, so these sets use the `default` rules (spawns in big rooms and junctions, loot off the main route and in dead ends) and leave room numbering off. Both are closed dungeons (`border_openings` `0`). `city` uses small rooms only; `temple` uses exactly 1 large and 1 medium. Each room can be used any number of times. The single-path versions are `city-linear` and `temple-linear`.

The small rooms' weights match `dungeon-generator`'s (`X` 4, `T` 5, `I` 2, `L` 1), so maps branch more; `MD_I` weighs the same as `I`, and the other rooms 1. `D` is 0.25, which cuts dead ends from about 4 to about 2 per map; fewer dead ends means fewer one-tile spurs that miss a marker slot. Weights only set the order rooms are tried in, so actual counts don't follow them closely. `SM_I` and `MD_I` are tagged `straight`, and `no_connect` keeps two straights from joining end to end.
