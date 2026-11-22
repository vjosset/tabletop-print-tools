"""
Gap-free dungeon generator for any tile set described in a JSON file.

A tile set lists the available tiles: their size in grid squares, which edges
of which squares are open, their image(s), how many copies exist and optional
tags. The generator fills a W x H grid with those tiles so that:

  - there is no empty space,
  - every opening meets an opening on the neighbouring tile (and walls meet walls),
  - the number of openings facing the map edge is within the allowed range,
  - every tile is reachable from every other tile,
  - copy counts and per-tag min/max limits are respected.

Tiles may be any rectangular size (1x1, 2x1, 2x2...) and are rotated freely.

A tile with several images is one shape to the solver; once the layout is
solved, its images are spread evenly over the copies placed.

Game markers (start, console, spawns, loot...) are placed by a rules file in
rules/. This script only interprets the rules; it defines none of its own.

Output: one {tileset}_dungeon_{SEED}.png per dungeon, drawn from the tile
images (or a schematic for tiles whose image is missing).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TILESETS_DIR = os.path.join(HERE, "tilesets")
RULES_DIR = os.path.join(HERE, "rules")
DEFAULT_OUT_DIR = os.path.join(HERE, "output")

DIRS: Dict[str, Tuple[int, int]] = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
ROT_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}

Opening = Tuple[int, int, str]  # (cell_x, cell_y, edge) relative to the tile's top-left


# ─────────────────────────────────────────────
# Tile set
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class Art:
    """One image of a tile. A tile's images share its shape; only the artwork differs."""
    name: str                     # badge and caption label
    path: str                     # absolute path
    copies: Optional[int]         # None = unlimited


@dataclass
class TileDef:
    tile_id: str
    piece: str                    # physical piece; tiles sharing a piece are its faces
    copies: Optional[int]         # None = unlimited
    size: Tuple[int, int]
    openings: List[Opening]
    images: List[Art]             # empty = drawn as a schematic
    weight: float
    tags: FrozenSet[str]          # includes the tile's own id

    @property
    def area(self) -> int:
        return self.size[0] * self.size[1]


@dataclass
class Limit:
    min: int = 0
    max: Optional[int] = None


@dataclass
class TileSet:
    name: str
    path: str
    tiles: Dict[str, TileDef]
    piece_copies: Dict[str, Optional[int]]
    width: int
    height: int
    border: Tuple[int, int]       # allowed number of openings facing the map edge
    limits: Dict[str, Limit]
    number_rooms: bool = False    # badge each tile with its order from the entrance (only meaningful for single-path sets)
    rules: str = "default"        # rules file (name in rules/ or path) used when --rules isn't given


def parse_border(value) -> Tuple[int, int]:
    """2 -> (2, 2); "0-2" -> (0, 2); [0, 2] -> (0, 2)."""
    if isinstance(value, int):
        return value, value
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    s = str(value).strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return int(a), int(b)
    return int(s), int(s)


def _parse_openings(tid: str, raw, w: int, h: int) -> List[Opening]:
    if isinstance(raw, str):
        if (w, h) != (1, 1):
            raise SystemExit(f"Tile {tid}: the \"NESW\" shorthand only works for 1x1 tiles; "
                             f"use [x, y, edge] entries for a {w}x{h} tile.")
        raw = [[0, 0, e] for e in raw.upper()]
    out: List[Opening] = []
    for o in raw:
        x, y, e = int(o[0]), int(o[1]), str(o[2]).upper()
        if e not in DIRS:
            raise SystemExit(f"Tile {tid}: edge {e!r} must be one of N, E, S, W.")
        if not (0 <= x < w and 0 <= y < h):
            raise SystemExit(f"Tile {tid}: opening square ({x}, {y}) is outside its {w}x{h} size.")
        dx, dy = DIRS[e]
        if 0 <= x + dx < w and 0 <= y + dy < h:
            raise SystemExit(f"Tile {tid}: opening ({x}, {y}, {e}) is on an inside edge of the tile, "
                             f"not on its outline.")
        out.append((x, y, e))
    return out


def _parse_images(tid: str, t: dict, image_dir: str) -> List[Art]:
    """`image` (one file) or `images` (a list of files or {"file", "copies"} entries).

    With one image the label is the tile's ID; with several it's each file's name
    without its extension, so the map shows which physical tile to put down.
    """
    if "image" in t and "images" in t:
        raise SystemExit(f"Tile {tid}: use either \"image\" or \"images\", not both.")
    raw = t.get("images", [t["image"]] if t.get("image") else [])
    entries = []
    for r in raw:
        if isinstance(r, str):
            entries.append((r, None))
        elif isinstance(r, dict) and "file" in r:
            entries.append((str(r["file"]), None if r.get("copies") is None else int(r["copies"])))
        else:
            raise SystemExit(f"Tile {tid}: each image must be a file name or {{\"file\": ..., \"copies\": N}}.")
    return [Art(name=tid if len(entries) == 1 else os.path.splitext(os.path.basename(f))[0],
                path=os.path.join(image_dir, f), copies=c)
            for f, c in entries]


def _resolve_json(arg: str, folder: str, what: str, relative_to: Optional[str] = None) -> str:
    """Accept a file path (relative to the working directory, or to `relative_to`),
    or a bare name of a file in `folder` (with or without .json)."""
    candidates = [arg, arg + ".json"]
    if relative_to:
        candidates += [os.path.join(relative_to, arg), os.path.join(relative_to, arg + ".json")]
    candidates += [os.path.join(folder, arg), os.path.join(folder, arg + ".json")]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    available = sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json")) \
        if os.path.isdir(folder) else []
    raise SystemExit(f"{what} {arg!r} not found. "
                     f"Available in {os.path.basename(folder)}/: {', '.join(available) or 'none'}.")


def resolve_tileset_path(arg: str) -> str:
    return _resolve_json(arg, TILESETS_DIR, "Tile set")


def resolve_rules_path(arg: str, tileset_path: Optional[str] = None) -> str:
    """A rules file named on the command line or in a tile set (paths in a tile set
    may be relative to it)."""
    return _resolve_json(arg, RULES_DIR, "Rules file",
                         os.path.dirname(tileset_path) if tileset_path else None)


def load_tileset(path: str) -> TileSet:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    base = os.path.dirname(path)
    image_dir = os.path.join(base, data.get("image_dir", "."))
    grid = data.get("grid", {})

    tiles: Dict[str, TileDef] = {}
    piece_copies: Dict[str, Optional[int]] = {}
    for tid, t in data["tiles"].items():
        if tid.startswith("_"):
            continue
        w, h = (int(t["size"][0]), int(t["size"][1])) if "size" in t else (1, 1)
        copies = t.get("copies")
        copies = None if copies is None else int(copies)
        piece = str(t.get("piece", tid))
        images = _parse_images(tid, t, image_dir)
        # When every image has a copy count, the tile can't be used more often than their total.
        if images and all(a.copies is not None for a in images):
            total = sum(a.copies for a in images)
            copies = total if copies is None else min(copies, total)
        tiles[tid] = TileDef(
            tile_id=tid,
            piece=piece,
            copies=copies,
            size=(w, h),
            openings=_parse_openings(tid, t.get("openings", []), w, h),
            images=images,
            weight=float(t.get("weight", 1)),
            tags=frozenset([tid, *t.get("tags", [])]),
        )
        # Faces of one piece share its copies; unlimited wins if any face says so.
        if piece in piece_copies and (piece_copies[piece] is None or copies is None):
            piece_copies[piece] = None
        else:
            piece_copies[piece] = copies if piece not in piece_copies else max(piece_copies[piece], copies)

    limits = {tag: Limit(int(v.get("min", 0)), None if v.get("max") is None else int(v["max"]))
              for tag, v in data.get("limits", {}).items() if not tag.startswith("_")}
    if "placement" in data:
        raise SystemExit(f"{os.path.basename(path)}: the \"placement\" section now lives in its own file in "
                         f"rules/. Move it there and point to it with \"rules\": \"<name>\".")
    return TileSet(
        name=data.get("name") or os.path.splitext(os.path.basename(path))[0],
        path=path,
        tiles=tiles,
        piece_copies=piece_copies,
        width=int(grid.get("width", 5)),
        height=int(grid.get("height", 4)),
        border=parse_border(data.get("border_openings", 0)),
        limits=limits,
        number_rooms=bool(data.get("number_rooms", False)),
        rules=str(data.get("rules", "default")),
    )


# ─────────────────────────────────────────────
# Rotations
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class Variant:
    """One tile in one rotation."""
    tile_id: str
    rotation: int                 # quarter turns clockwise from the tile's image orientation
    w: int
    h: int
    cell_open: Tuple[Tuple[FrozenSet[str], ...], ...]   # [y][x] -> open edges of that square


def rotate_cw(w: int, h: int, openings: List[Opening]) -> Tuple[int, int, List[Opening]]:
    """Rotate a tile 90 degrees clockwise: square (x, y) -> (h - 1 - y, x)."""
    return h, w, [(h - 1 - y, x, ROT_CW[e]) for x, y, e in openings]


def build_variants(tile: TileDef) -> List[Variant]:
    """All distinct rotations of a tile."""
    w, h = tile.size
    ops = list(tile.openings)
    seen = set()
    out: List[Variant] = []
    for rot in range(4):
        key = (w, h, frozenset(ops))
        if key not in seen:
            seen.add(key)
            grid = tuple(tuple(frozenset(e for (ox, oy, e) in ops if ox == x and oy == y)
                               for x in range(w)) for y in range(h))
            out.append(Variant(tile.tile_id, rot, w, h, grid))
        w, h, ops = rotate_cw(w, h, ops)
    return out


# ─────────────────────────────────────────────
# Layout search
# ─────────────────────────────────────────────

@dataclass
class Placement:
    variant: Variant
    x: int
    y: int
    art: Optional[Art] = None     # chosen after the layout is solved

    @property
    def label(self) -> str:
        return self.art.name if self.art else self.variant.tile_id


@dataclass
class Layout:
    width: int
    height: int
    placements: List[Placement]
    cells: List[List[int]]                                    # square -> index into placements
    order: List[int] = field(default_factory=list)            # placement indexes, from the entrance outwards
    border_openings: List[Tuple[int, int, str]] = field(default_factory=list)  # absolute (x, y, edge)


class _OutOfBudget(Exception):
    pass


class Solver:
    """Randomised backtracking: always fill the first empty square (row-major)."""

    def __init__(self, ts: TileSet, width: int, height: int, border: Tuple[int, int],
                 limits: Dict[str, Limit], rng: random.Random, step_budget: int = 20000):
        self.ts = ts
        self.W, self.H = width, height
        self.border_min, self.border_max = border
        self.limits = limits
        self.rng = rng
        self.step_budget = step_budget
        self.variants = {tid: build_variants(t) for tid, t in ts.tiles.items()}
        self.tiles = [t for t in ts.tiles.values() if t.weight > 0]
        # Tags of each tile that have a max, checked on every step.
        self.max_tags = {t.tile_id: [tag for tag in sorted(t.tags)
                                     if tag in limits and limits[tag].max is not None]
                         for t in self.tiles}
        # For each tag with a minimum: the smallest tile area carrying it (for pruning).
        self.min_tag_area = {
            tag: min((t.area for t in ts.tiles.values() if tag in t.tags), default=math.inf)
            for tag, lim in limits.items() if lim.min > 0}

    # ── state ──
    def _reset(self) -> None:
        self.steps = 0
        self.cells = [[-1] * self.W for _ in range(self.H)]
        self.open_at: List[List[FrozenSet[str]]] = [[frozenset()] * self.W for _ in range(self.H)]
        self.placements: List[Placement] = []
        self.piece_used: Counter = Counter()
        self.tag_used: Counter = Counter()
        self.border = 0
        self.empty = self.W * self.H

    def solve(self, attempts: int = 60) -> Optional[Layout]:
        for _ in range(attempts):
            self._reset()
            if not self._place_required():
                continue
            try:
                if self._rec():
                    return self._finish()
            except _OutOfBudget:
                continue
        return None

    def _place_required(self) -> bool:
        """Put tiles needed by --min / 'min' limits at random spots before the main fill.

        Filling row by row and only then discovering that a required tile (e.g. a
        2x2 boss room) no longer fits wastes most of the search, so they go first.
        """
        for tag, lim in sorted(self.limits.items()):
            while self.tag_used[tag] < lim.min:
                spots = [(v, x, y)
                         for t in self.tiles if tag in t.tags and self._available(t)
                         for v in self.variants[t.tile_id]
                         for y in range(self.H - v.h + 1) for x in range(self.W - v.w + 1)]
                self.rng.shuffle(spots)
                for v, x, y in spots:
                    added = self._fits(v, x, y)
                    if added is not None and self.border + added <= self.border_max:
                        self._place(v, x, y, added)
                        break
                else:
                    return False
        return True

    # ── constraints ──
    def _available(self, t: TileDef) -> bool:
        cap = self.ts.piece_copies[t.piece]
        if cap is not None and self.piece_used[t.piece] >= cap:
            return False
        for tag in self.max_tags[t.tile_id]:
            if self.tag_used[tag] >= self.limits[tag].max:
                return False
        return True

    def _capacity(self, avail: List[TileDef]) -> float:
        """Upper bound on the area the available tiles can still cover."""
        free = 0.0
        best: Dict[str, Tuple[int, Optional[str]]] = {}   # piece -> (largest face area, a capped tag)
        for t in avail:
            area, tag = best.get(t.piece, (0, None))
            mt = self.max_tags[t.tile_id]
            best[t.piece] = (max(area, t.area), tag or (mt[0] if mt else None))
        capped: Dict[str, List[int]] = {}
        for piece, (area, tag) in best.items():
            cap = self.ts.piece_copies[piece]
            left = math.inf if cap is None else cap - self.piece_used[piece]
            if tag is None:
                if left == math.inf:
                    return math.inf
                free += area * left
            else:
                room = self.limits[tag].max - self.tag_used[tag]
                capped.setdefault(tag, []).extend([area] * int(min(left, room)))
        for tag, areas in capped.items():
            room = self.limits[tag].max - self.tag_used[tag]
            free += sum(sorted(areas, reverse=True)[:room])
        return free

    def _min_area_needed(self) -> float:
        need = 0.0
        for tag, area in self.min_tag_area.items():
            missing = self.limits[tag].min - self.tag_used[tag]
            if missing > 0:
                need = max(need, missing * area)
        return need

    def _first_empty(self) -> Optional[Tuple[int, int]]:
        for y in range(self.H):
            row = self.cells[y]
            for x in range(self.W):
                if row[x] < 0:
                    return x, y
        return None

    def _fits(self, v: Variant, x0: int, y0: int) -> Optional[int]:
        """Return the number of border openings this tile adds, or None if it can't go here."""
        if x0 + v.w > self.W or y0 + v.h > self.H:
            return None
        for j in range(v.h):
            for i in range(v.w):
                if self.cells[y0 + j][x0 + i] >= 0:
                    return None
        border = 0
        for j in range(v.h):
            for i in range(v.w):
                cell_open = v.cell_open[j][i]
                for e, (dx, dy) in DIRS.items():
                    if 0 <= i + dx < v.w and 0 <= j + dy < v.h:
                        continue  # inside the tile
                    nx, ny = x0 + i + dx, y0 + j + dy
                    if not (0 <= nx < self.W and 0 <= ny < self.H):
                        if e in cell_open:
                            border += 1
                        continue
                    if self.cells[ny][nx] < 0:
                        continue
                    # Openings must meet openings; walls must meet walls.
                    if (e in cell_open) != (OPP[e] in self.open_at[ny][nx]):
                        return None
        return border

    def _candidates(self, avail: List[TileDef]) -> List[Variant]:
        """Available tiles in weighted random order, each followed by its rotations in random order."""
        keyed = sorted(avail, key=lambda t: self.rng.random() ** (1.0 / t.weight), reverse=True)
        out: List[Variant] = []
        for t in keyed:
            vs = list(self.variants[t.tile_id])
            self.rng.shuffle(vs)
            out.extend(vs)
        return out

    # ── search ──
    def _place(self, v: Variant, x0: int, y0: int, added: int) -> None:
        t = self.ts.tiles[v.tile_id]
        idx = len(self.placements)
        self.placements.append(Placement(v, x0, y0))
        self.piece_used[t.piece] += 1
        for tag in t.tags:
            self.tag_used[tag] += 1
        self.border += added
        self.empty -= v.w * v.h
        for j in range(v.h):
            for i in range(v.w):
                self.cells[y0 + j][x0 + i] = idx
                self.open_at[y0 + j][x0 + i] = v.cell_open[j][i]

    def _unplace(self, v: Variant, x0: int, y0: int, added: int) -> None:
        t = self.ts.tiles[v.tile_id]
        for j in range(v.h):
            for i in range(v.w):
                self.cells[y0 + j][x0 + i] = -1
                self.open_at[y0 + j][x0 + i] = frozenset()
        self.empty += v.w * v.h
        self.border -= added
        for tag in t.tags:
            self.tag_used[tag] -= 1
        self.piece_used[t.piece] -= 1
        self.placements.pop()

    def _limits_met(self) -> bool:
        return all(self.tag_used[tag] >= lim.min for tag, lim in self.limits.items())

    def _rec(self) -> bool:
        self.steps += 1
        if self.steps > self.step_budget:
            raise _OutOfBudget()
        fe = self._first_empty()
        if fe is None:
            return (self.border_min <= self.border <= self.border_max
                    and self._limits_met() and self._connected())
        avail = [t for t in self.tiles if self._available(t)]
        if self._capacity(avail) < self.empty or self._min_area_needed() > self.empty:
            return False
        x0, y0 = fe
        for v in self._candidates(avail):
            if not self._available(self.ts.tiles[v.tile_id]):
                continue
            added = self._fits(v, x0, y0)
            if added is None or self.border + added > self.border_max:
                continue
            self._place(v, x0, y0, added)
            if self._rec():
                return True
            self._unplace(v, x0, y0, added)
        return False

    def _links(self) -> Dict[int, List[int]]:
        links: Dict[int, List[int]] = {i: [] for i in range(len(self.placements))}
        for y in range(self.H):
            for x in range(self.W):
                a = self.cells[y][x]
                for e in ("E", "S"):
                    dx, dy = DIRS[e]
                    nx, ny = x + dx, y + dy
                    if nx < self.W and ny < self.H:
                        b = self.cells[ny][nx]
                        if a != b and e in self.open_at[y][x]:
                            links[a].append(b)
                            links[b].append(a)
        return links

    def _bfs(self, start: int) -> List[int]:
        links = self._links()
        seen, order, queue = {start}, [start], deque([start])
        while queue:
            for n in links[queue.popleft()]:
                if n not in seen:
                    seen.add(n)
                    order.append(n)
                    queue.append(n)
        return order

    def _connected(self) -> bool:
        return len(self._bfs(0)) == len(self.placements)

    def _finish(self) -> Layout:
        ends: List[Tuple[int, Tuple[int, int, str]]] = []
        for y in range(self.H):
            for x in range(self.W):
                for e in sorted(self.open_at[y][x]):
                    dx, dy = DIRS[e]
                    if not (0 <= x + dx < self.W and 0 <= y + dy < self.H):
                        ends.append((self.cells[y][x], (x, y, e)))
        self.rng.shuffle(ends)
        start = ends[0][0] if ends else self.rng.randrange(len(self.placements))
        order = self._bfs(start)
        self._assign_art(order)
        return Layout(self.W, self.H, list(self.placements),
                      [row[:] for row in self.cells], order, [e for _, e in ends])

    def _assign_art(self, order: List[int]) -> None:
        """Pick each tile's image once the layout is solved.

        Images never affect the layout, so this can't fail or force backtracking.
        Going outwards from the entrance, each tile gets its least-used image
        (keeping counts within one of each other), preferring one that no touching
        tile already shows, then at random. Per-image copies are never exceeded:
        the solver already kept the tile within their total.
        """
        touching: Dict[int, set] = {i: set() for i in range(len(self.placements))}
        for y in range(self.H):
            for x in range(self.W):
                a = self.cells[y][x]
                for nx, ny in ((x + 1, y), (x, y + 1)):
                    if nx < self.W and ny < self.H and self.cells[ny][nx] != a:
                        b = self.cells[ny][nx]
                        touching[a].add(b)
                        touching[b].add(a)
        used: Counter = Counter()
        for idx in order:
            p = self.placements[idx]
            arts = self.ts.tiles[p.variant.tile_id].images
            if not arts:
                continue
            nearby = {self.placements[n].art for n in touching[idx]}
            free = [a for a in arts if a.copies is None or used[a] < a.copies]
            p.art = min(free, key=lambda a: (used[a], a in nearby, self.rng.random()))
            used[p.art] += 1


# ─────────────────────────────────────────────
# Item placement
# ─────────────────────────────────────────────
# Each grid square is split into SUB x SUB spaces, all floor. Walls are the
# tile edges; a connector is the middle space of a grid square's edge.
# Markers are placed by an ordered list of rules from a rules file (rules/*.json).
# Which markers exist and where they go is data; this section is only the engine
# that interprets it. Rules choose a tile; the marker then goes on a free space in it.

SUB = 3
Space = Tuple[int, int]           # (x, y) in spaces, from the map's top-left

PICKS = ("random", "spread")
PREFERENCES = ("off_route", "dead_end")


@dataclass
class MarkerType:
    name: str
    color: Tuple[int, int, int]
    size: str = "large"           # "large" | "small"
    label: str = ""               # text drawn on the marker, e.g. "?"
    objective: bool = False       # the main route runs through markers of this type
    defaults: Dict[str, object] = field(default_factory=dict)   # rule fields its rules inherit


@dataclass
class MarkerRule:
    type: str
    count: int
    distance: Tuple[int, Optional[int]]   # tiles from `source`; None = no maximum
    source: str                           # "start" or a marker type placed by an earlier rule
    pick: str                             # "random" | "spread"
    prefer: List[str]
    spread_from: List[str]


@dataclass
class PlacementRules:
    strategy: str
    types: Dict[str, MarkerType]
    rules: List[MarkerRule]


def _parse_colour(where: str, value) -> Tuple[int, int, int]:
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(int(v) for v in value)
    raise SystemExit(f"{where}: colour must be \"#rrggbb\" or [r, g, b], got {value!r}.")


RULE_FIELDS = ("count", "distance", "from", "pick", "prefer", "spread_from")


# Marker types the engine itself draws, which a rules file must define.
REQUIRED_TYPES = {"start": "the player start, drawn when the dungeon has no IN marker"}
STRATEGY_TYPES = {"discovery": "discovery"}   # strategy -> marker type it places


def load_rules(path: str, tags: FrozenSet[str] = frozenset()) -> PlacementRules:
    """Read a rules file. `tags` are the tile set's tile tags, which "prefer" may name.

    Rule fields set on a marker type are defaults for that type's rules; a rule's own
    value wins.
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    where = os.path.basename(path)
    types: Dict[str, MarkerType] = {}
    merged = {n: v for n, v in raw.get("marker_types", {}).items() if not n.startswith("_")}
    for n, v in merged.items():
        if "color" not in v:
            raise SystemExit(f"{where}: marker type {n!r} needs a \"color\".")
        size = v.get("size", "large")
        if size not in ("large", "small"):
            raise SystemExit(f"{where}: marker type {n!r} size must be \"large\" or \"small\".")
        types[n] = MarkerType(n, _parse_colour(f"{where}: marker type {n!r}", v["color"]),
                              size, str(v.get("label", "")), bool(v.get("objective", False)),
                              {k: v[k] for k in RULE_FIELDS if k in v})

    for n, why in REQUIRED_TYPES.items():
        if n not in types:
            raise SystemExit(f"{where}: needs a {n!r} marker type ({why}).")

    rules: List[MarkerRule] = []
    placed = {"start"}
    for i, r in enumerate(raw.get("markers", [])):
        here = f"{where}: marker rule {i + 1}"
        t = r.get("type")
        if t not in types:
            raise SystemExit(f"{here}: unknown marker type {t!r}. Known: {', '.join(sorted(types))}.")
        r = {**types[t].defaults, **r}
        lo, hi = r.get("distance", [1, None])
        source = r.get("from", "start")
        if source not in placed:
            raise SystemExit(f"{here}: \"from\" must be \"start\" or a type placed by an earlier rule, got {source!r}.")
        pick = r.get("pick", "random")
        if pick not in PICKS:
            raise SystemExit(f"{here}: \"pick\" must be one of {', '.join(PICKS)}.")
        prefer = list(r.get("prefer", []))
        for p in prefer:
            if p not in PREFERENCES and p not in tags:
                raise SystemExit(f"{here}: unknown preference {p!r}: use {', '.join(PREFERENCES)} "
                                 f"or a tile tag ({', '.join(sorted(tags))}).")
        rules.append(MarkerRule(t, int(r.get("count", 1)), (int(lo), None if hi is None else int(hi)),
                                source, pick, prefer, list(r.get("spread_from", ["start", t]))))
        placed.add(t)

    strategy = raw.get("strategy", "standard")
    check_strategy(PlacementRules(strategy, types, rules), strategy, where)
    return PlacementRules(strategy, types, rules)


def check_strategy(rules: PlacementRules, strategy: str, where: str) -> None:
    if strategy not in PLACEMENT_STRATEGIES:
        raise SystemExit(f"{where}: placement strategy must be one of {', '.join(PLACEMENT_STRATEGIES)}.")
    needed = STRATEGY_TYPES.get(strategy)
    if needed and needed not in rules.types:
        raise SystemExit(f"{where}: the {strategy!r} strategy needs a {needed!r} marker type.")


@dataclass
class Marker:
    x: int
    y: int
    type: str


@dataclass
class Items:
    start: Optional[Space] = None         # player start
    draw_start: bool = False              # False when the IN marker already shows it
    markers: List[Marker] = field(default_factory=list)


class SpaceMap:
    """The layout as spaces, plus the tile graph (which tiles connect through connectors)."""

    def __init__(self, layout: Layout, ts: TileSet):
        self.layout = layout
        self.tags = [ts.tiles[p.variant.tile_id].tags for p in layout.placements]
        self.W, self.H = layout.width * SUB, layout.height * SUB
        self.open = [[frozenset()] * layout.width for _ in range(layout.height)]
        for p in layout.placements:
            for j in range(p.variant.h):
                for i in range(p.variant.w):
                    self.open[p.y + j][p.x + i] = p.variant.cell_open[j][i]
        self.links: Dict[int, set] = {i: set() for i in range(len(layout.placements))}
        for y in range(layout.height):
            for x in range(layout.width):
                a = layout.cells[y][x]
                for e in self.open[y][x]:
                    dx, dy = DIRS[e]
                    if 0 <= x + dx < layout.width and 0 <= y + dy < layout.height:
                        b = layout.cells[y + dy][x + dx]
                        if a != b:
                            self.links[a].add(b)
        # Openings on the map edge count as a way out (so a linear map's exit tile isn't a dead end).
        self.exits = Counter(layout.cells[y][x] for x, y, _ in layout.border_openings)

    def square(self, s: Space) -> Tuple[int, int]:
        return s[0] // SUB, s[1] // SUB

    def tile(self, s: Space) -> int:
        x, y = self.square(s)
        return self.layout.cells[y][x]

    def centre(self, x: int, y: int) -> Space:
        return x * SUB + SUB // 2, y * SUB + SUB // 2

    def entrance(self) -> Optional[Space]:
        """The space just inside the first border opening (the IN marker), if any."""
        if not self.layout.border_openings:
            return None
        x, y, e = self.layout.border_openings[0]
        cx, cy = self.centre(x, y)
        dx, dy = DIRS[e]
        return cx + dx * (SUB // 2), cy + dy * (SUB // 2)

    def degree(self, t: int) -> int:
        return len(self.links[t]) + self.exits[t]

    def tile_dist(self, sources: List[int]) -> Dict[int, int]:
        """Tiles walked through from the nearest source (a 2x2 room counts as one)."""
        dist = {s: 0 for s in sources}
        queue = deque(sources)
        while queue:
            t = queue.popleft()
            for n in self.links[t]:
                if n not in dist:
                    dist[n] = dist[t] + 1
                    queue.append(n)
        return dist

    def route(self, start: int, targets: List[int]) -> set:
        """Tiles on the shortest paths from start to each target."""
        parent = {start: start}
        queue = deque([start])
        while queue:
            t = queue.popleft()
            for n in sorted(self.links[t]):
                if n not in parent:
                    parent[n] = t
                    queue.append(n)
        on = {start}
        for t in targets:
            while t in parent and t not in on:
                on.add(t)
                t = parent[t]
        return on

    def tile_spaces(self, t: int) -> List[Space]:
        p = self.layout.placements[t]
        return [(x, y) for y in range(p.y * SUB, (p.y + p.variant.h) * SUB)
                for x in range(p.x * SUB, (p.x + p.variant.w) * SUB)]

    def blocked(self, t: int) -> set:
        """Spaces of a tile that shouldn't hold a marker: its badge and its connectors."""
        p = self.layout.placements[t]
        out = {(p.x * SUB, p.y * SUB)}
        for j in range(p.variant.h):
            for i in range(p.variant.w):
                cx, cy = self.centre(p.x + i, p.y + j)
                for e in p.variant.cell_open[j][i]:
                    dx, dy = DIRS[e]
                    out.add((cx + dx * (SUB // 2), cy + dy * (SUB // 2)))
        return out


def _place_start(sm: SpaceMap, rng: random.Random, best_connected: bool = False) -> Items:
    """At the IN marker if there is one; else the centre of a 1x1 tile (dungeon-generator
    kept the player out of the big room), optionally the best-connected one."""
    start = sm.entrance()
    if start is not None:
        return Items(start=start)
    tiles = [i for i, p in enumerate(sm.layout.placements) if p.variant.w * p.variant.h == 1] \
        or list(range(len(sm.layout.placements)))
    if best_connected:
        best = max(sm.degree(t) for t in tiles)
        tiles = [t for t in tiles if sm.degree(t) == best]
    p = sm.layout.placements[rng.choice(tiles)]
    return Items(start=sm.centre(p.x, p.y), draw_start=True)


def _pick_tile(sm: SpaceMap, rng: random.Random, rules: PlacementRules, rule: MarkerRule,
               items: Items, start_tile: int) -> Optional[int]:
    """Choose a tile for one marker. Each step narrows the choice but never empties it."""
    tiles_of = lambda kind: [start_tile] if kind == "start" else \
        [sm.tile((m.x, m.y)) for m in items.markers if m.type == kind]

    pool = [t for t in sm.links if t != start_tile]               # never on the start tile
    if not pool:
        return None
    taken = set(tiles_of(rule.type))                              # one marker of each type per tile
    pool = [t for t in pool if t not in taken] or pool

    # Distance from the source, or as close to the range as the map allows.
    dist = sm.tile_dist(tiles_of(rule.source) or [start_tile])
    lo, hi = rule.distance
    gap = lambda t: max(lo - dist.get(t, math.inf), 0, 0 if hi is None else dist.get(t, math.inf) - hi)
    best = min(gap(t) for t in pool)
    pool = [t for t in pool if gap(t) == best]

    for pref in rule.prefer:
        if pref == "off_route":
            targets = [t for kind, mt in rules.types.items() if mt.objective for t in tiles_of(kind)]
            targets += [sm.layout.cells[y][x] for x, y, _ in sm.layout.border_openings[1:]]
            route = sm.route(start_tile, targets)
            narrowed = [t for t in pool if t not in route]
        elif pref == "dead_end":
            narrowed = [t for t in pool if sm.degree(t) == 1]
        else:  # a tile tag; tagged tiles with no marker yet come first, to spread markers over the rooms
            narrowed = [t for t in pool if pref in sm.tags[t]]
            marked = {sm.tile((m.x, m.y)) for m in items.markers}
            narrowed = [t for t in narrowed if t not in marked] or narrowed
        pool = narrowed or pool

    if rule.pick == "spread":
        anchors = [t for kind in rule.spread_from for t in tiles_of(kind)]
        if anchors:
            ad = sm.tile_dist(anchors)
            far = max(ad.get(t, math.inf) for t in pool)
            pool = [t for t in pool if ad.get(t, math.inf) == far]
    return rng.choice(pool)


def _pick_space(sm: SpaceMap, rng: random.Random, t: int, items: Items) -> Space:
    """A free space in tile t: an unused grid square's centre, else one not touching
    another marker, else any free one."""
    used = {(m.x, m.y) for m in items.markers} | {items.start}
    free = [s for s in sm.tile_spaces(t) if s not in used and s not in sm.blocked(t)]
    busy_squares = {sm.square(s) for s in used}
    near = lambda s: any((s[0] + dx, s[1] + dy) in used for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    for tier in ([s for s in free if s == sm.centre(*sm.square(s)) and sm.square(s) not in busy_squares],
                 [s for s in free if not near(s)],
                 free):
        if tier:
            return rng.choice(tier)
    p = sm.layout.placements[t]
    return sm.centre(p.x, p.y)


def place_items_standard(sm: SpaceMap, rng: random.Random, rules: PlacementRules) -> Items:
    """Apply the placement rules in order."""
    items = _place_start(sm, rng)
    start_tile = sm.tile(items.start)
    for rule in rules.rules:
        for _ in range(rule.count):
            t = _pick_tile(sm, rng, rules, rule, items, start_tile)
            if t is None:
                break
            x, y = _pick_space(sm, rng, t, items)
            items.markers.append(Marker(x, y, rule.type))
    return items


def place_items_discovery(sm: SpaceMap, rng: random.Random, rules: PlacementRules) -> Items:
    """Player start, then a '?' marker on every other grid square, like a checkerboard."""
    items = _place_start(sm, rng, best_connected=True)
    start_tile = sm.tile(items.start)
    sx, sy = sm.square(items.start)
    for y in range(sm.layout.height):
        for x in range(sm.layout.width):
            if (x + y) % 2 == (sx + sy) % 2 and sm.layout.cells[y][x] != start_tile:
                items.markers.append(Marker(*sm.centre(x, y), "discovery"))
    return items


PLACEMENT_STRATEGIES = {
    "standard":  place_items_standard,
    "discovery": place_items_discovery,
    "none":      lambda sm, rng, rules: Items(),
}


# ─────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────

def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        for name in ("DejaVuSans.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
        return ImageFont.load_default()


def _schematic(tile: TileDef, cell_px: int) -> Image.Image:
    """Stand-in tile drawing for when the image isn't available."""
    w, h = tile.size
    img = Image.new("RGB", (w * cell_px, h * cell_px), (70, 66, 60))
    d = ImageDraw.Draw(img)
    t = max(4, cell_px // 10)
    d.rectangle([0, 0, img.width - 1, img.height - 1], outline=(25, 25, 25), width=t)
    for x, y, e in tile.openings:
        x0, y0 = x * cell_px, y * cell_px
        a, b = int(cell_px * 0.3), int(cell_px * 0.7)
        box = {"N": (x0 + a, y0, x0 + b, y0 + t), "S": (x0 + a, y0 + cell_px - t, x0 + b, y0 + cell_px),
               "W": (x0, y0 + a, x0 + t, y0 + b), "E": (x0 + cell_px - t, y0 + a, x0 + cell_px, y0 + b)}[e]
        d.rectangle(box, fill=(200, 190, 160))
    d.text((img.width // 2, img.height // 2), tile.tile_id, fill=(230, 230, 230),
           font=_font(max(12, cell_px // 5)), anchor="mm")
    return img


def render_png(layout: Layout, ts: TileSet, out_path: str, cell_px: int, caption: str,
               number_rooms: bool = False, items: Optional[Items] = None,
               marker_types: Optional[Dict[str, MarkerType]] = None) -> List[str]:
    """Render the layout. Returns the labels of tiles drawn as schematics (image missing)."""
    margin = max(24, cell_px // 3)
    font_px = max(12, round(cell_px * 0.09))
    font = _font(font_px)
    cap_font = _font(max(12, round(cell_px * 0.1)))
    cap_h = round(cap_font.size * 1.8) if hasattr(cap_font, "size") else 24
    W, H = layout.width * cell_px, layout.height * cell_px
    img = Image.new("RGB", (W + 2 * margin, H + 2 * margin + cap_h), (18, 20, 22))
    d = ImageDraw.Draw(img)

    missing: List[str] = []
    cache: Dict[str, Image.Image] = {}
    for p in layout.placements:
        tile = ts.tiles[p.variant.tile_id]
        path = p.art.path if p.art else ""
        if path and os.path.exists(path):
            if path not in cache:
                cache[path] = Image.open(path).convert("RGB")
            pic = cache[path]
        else:
            if p.label not in missing:
                missing.append(p.label)
            pic = _schematic(tile, cell_px)
        if p.variant.rotation:
            pic = pic.rotate(-90 * p.variant.rotation, expand=True)
        pic = pic.resize((p.variant.w * cell_px, p.variant.h * cell_px), Image.LANCZOS)
        img.paste(pic, (margin + p.x * cell_px, margin + p.y * cell_px))

    # Tile outlines, then badges (tile ID, optionally prefixed by its order from the entrance).
    order = {idx: n + 1 for n, idx in enumerate(layout.order)}
    for idx, p in enumerate(layout.placements):
        x0, y0 = margin + p.x * cell_px, margin + p.y * cell_px
        x1, y1 = x0 + p.variant.w * cell_px, y0 + p.variant.h * cell_px
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(10, 10, 10), width=max(2, cell_px // 100))
        label = f"{order[idx]} · {p.label}" if number_rooms else p.label
        pad = font_px // 3
        tw = d.textlength(label, font=font)
        bx, by = x0 + pad * 2, y0 + pad * 2
        d.rounded_rectangle([bx, by, bx + tw + 2 * pad, by + font_px + 2 * pad],
                            radius=pad, fill=(15, 15, 15), outline=(230, 200, 90), width=2)
        d.text((bx + pad, by + pad + font_px / 2), label, fill=(240, 240, 240), font=font, anchor="lm")

    # Item markers, centred on their space.
    if items:
        sp = cell_px / SUB

        def dot(s: Space, colour, r: float, text: str = "") -> None:
            cx, cy = margin + (s[0] + 0.5) * sp, margin + (s[1] + 0.5) * sp
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour, outline=(15, 15, 15),
                      width=max(2, cell_px // 100))
            if text:
                d.text((cx, cy), text, fill=(255, 255, 255), font=_font(max(10, round(r * 1.3))), anchor="mm")

        types = marker_types or {}
        drawn = ([Marker(*items.start, "start")] if items.start and items.draw_start else []) + items.markers
        for m in drawn:
            mt = types[m.type]
            dot((m.x, m.y), mt.color, sp / 3 if mt.size == "large" else sp / 4, mt.label)

    # Border openings in the margin: the first is the entrance, the rest are exits.
    for n, (x, y, e) in enumerate(layout.border_openings):
        text, colour = ("IN", (60, 170, 80)) if n == 0 else ("OUT", (200, 60, 50))
        cx = margin + x * cell_px + cell_px // 2
        cy = margin + y * cell_px + cell_px // 2
        dx, dy = DIRS[e]
        cx += dx * (cell_px // 2 + margin // 2)
        cy += dy * (cell_px // 2 + margin // 2)
        r = margin // 2 - 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)
        d.text((cx, cy), text, fill=(255, 255, 255), font=_font(max(10, round(r * 0.8))), anchor="mm")

    # Shrink the caption to fit the map's width (long tile lists on narrow maps).
    size = cap_font.size if hasattr(cap_font, "size") else 12
    while size > 8 and d.textlength(caption, font=cap_font) > W:
        size -= 1
        cap_font = _font(size)
    d.text((margin, margin + H + margin + cap_h / 2), caption,   # below the IN/OUT markers
           fill=(210, 210, 210), font=cap_font, anchor="lm")
    img.save(out_path)
    return missing


def _natural(s: str):
    """Sort key so that 2A comes before 10A."""
    digits = "".join(c for c in s if c.isdigit())
    return (int(digits) if digits else math.inf, s)


def tile_counts(layout: Layout) -> str:
    counts = Counter(p.label for p in layout.placements)
    return "  ".join(f"{tid} x{counts[tid]}" for tid in sorted(counts, key=_natural))


# ─────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────

def _parse_tag_values(items: List[str], flag: str) -> Dict[str, int]:
    out = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"{flag} expects TAG=N, got {item!r}.")
        tag, n = item.split("=", 1)
        out[tag.strip()] = int(n)
    return out


def check_area(ts: TileSet, width: int, height: int) -> None:
    """Fail early with a clear message when the grid obviously can't be filled."""
    capacity = 0.0
    for piece, cap in ts.piece_copies.items():
        faces = [t for t in ts.tiles.values() if t.piece == piece and t.weight > 0]
        if not faces:
            continue
        if cap is None:
            return
        capacity += cap * max(t.area for t in faces)
    if capacity < width * height:
        raise SystemExit(f"Can't fill {width}x{height} ({width * height} squares): "
                         f"all of {ts.name}'s tiles together cover only {int(capacity)}.")


def generate(seed: int, ts: TileSet, width: int, height: int,
             border: Tuple[int, int], limits: Dict[str, Limit]) -> Optional[Layout]:
    """Deterministic for a given seed, tile set and options."""
    rng = random.Random(seed)
    return Solver(ts, width, height, border, limits, rng).solve()


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate gap-free dungeons from a tile set described in JSON.")
    ap.add_argument("--tileset",  required=True,
                    help="Tile set: a name from tilesets/ (e.g. gow) or a path to a JSON file.")
    ap.add_argument("--width",    type=int, default=None, help="Dungeon width in grid squares (default: from the tile set, else 5).")
    ap.add_argument("--height",   type=int, default=None, help="Dungeon height in grid squares (default: from the tile set, else 4).")
    ap.add_argument("--border-openings", default=None,
                    help="Openings allowed to face the map edge: N or MIN-MAX (default: from the tile set, else 0).")
    ap.add_argument("--min",      action="append", default=[], metavar="TAG=N",
                    help="Use at least N tiles with this tag or tile id. Repeatable; overrides the tile set.")
    ap.add_argument("--max",      action="append", default=[], metavar="TAG=N",
                    help="Use at most N tiles with this tag or tile id. Repeatable; overrides the tile set.")
    ap.add_argument("--number-rooms", action=argparse.BooleanOptionalAction, default=None,
                    help="Prefix each tile's badge with its order from the entrance. Only meaningful when "
                         "the dungeon is a single path (default: from the tile set, else off).")
    ap.add_argument("--rules",    default=None,
                    help="Game rules: a name from rules/ (e.g. linear) or a path to a JSON file "
                         "(default: the tile set's \"rules\", else default).")
    ap.add_argument("--placement", choices=PLACEMENT_STRATEGIES, default=None,
                    help="Item placement strategy (default: from the rules file).")
    ap.add_argument("--n",        type=int, default=3,    help="Number of dungeons to generate (default: 3).")
    ap.add_argument("--seed",     type=int, default=None, help="Generate one specific dungeon by seed.")
    ap.add_argument("--cell-px",  type=int, default=300,  help="Pixels per grid square in the PNG (default: 300).")
    ap.add_argument("--out-dir",  default=None,
                    help="Where to write the PNGs (default: output/<tileset>/ in this folder).")
    args = ap.parse_args()

    ts = load_tileset(resolve_tileset_path(args.tileset))
    rules_path = resolve_rules_path(args.rules) if args.rules else resolve_rules_path(ts.rules, ts.path)
    rules = load_rules(rules_path, frozenset().union(*(t.tags for t in ts.tiles.values())))
    strategy = args.placement or rules.strategy
    check_strategy(rules, strategy, os.path.basename(rules_path))
    rules_name = os.path.splitext(os.path.basename(rules_path))[0]
    width = args.width or ts.width
    height = args.height or ts.height
    border = parse_border(args.border_openings) if args.border_openings is not None else ts.border

    limits = {tag: Limit(l.min, l.max) for tag, l in ts.limits.items()}
    for tag, n in _parse_tag_values(args.min, "--min").items():
        limits.setdefault(tag, Limit()).min = n
    for tag, n in _parse_tag_values(args.max, "--max").items():
        lim = limits.setdefault(tag, Limit())
        lim.max = n
        lim.min = min(lim.min, n)
    known_tags = set().union(*(t.tags for t in ts.tiles.values()))
    for tag in limits:
        if tag not in known_tags:
            raise SystemExit(f"No tile in {ts.name} has the tag or id {tag!r}.")

    check_area(ts, width, height)
    slug = "".join(c if c.isalnum() else "_" for c in os.path.splitext(os.path.basename(ts.path))[0]).lower()
    out_dir = args.out_dir or os.path.join(DEFAULT_OUT_DIR, slug)
    os.makedirs(out_dir, exist_ok=True)

    seeds = [args.seed] if args.seed is not None else [random.randint(0, 2**32 - 1) for _ in range(args.n)]
    warned: set = set()
    for seed in seeds:
        layout = generate(seed, ts, width, height, border, limits)
        if layout is None:
            print(f"Seed {seed}: no layout found, skipping. "
                  f"If this keeps happening, the tiles may not be able to fill {width}x{height} with these settings.")
            continue
        caption = (f"{ts.name}  ·  Rules {rules_name}  ·  Seed {seed}  ·  "
                   f"{len(layout.placements)} rooms  ·  {tile_counts(layout)}")
        base = os.path.join(out_dir, f"{slug}_dungeon_{seed}")
        number_rooms = ts.number_rooms if args.number_rooms is None else args.number_rooms
        # Own random stream, so changing item placement never changes the layout for a seed.
        items = PLACEMENT_STRATEGIES[strategy](SpaceMap(layout, ts), random.Random(f"{seed}:items"), rules)
        missing = render_png(layout, ts, base + ".png", args.cell_px, caption, number_rooms, items, rules.types)
        print(f"Saved: {base}.png")
        new = [m for m in missing if m not in warned]
        if new:
            print(f"Note: no image found for {', '.join(new)}; drew schematic tiles instead.")
            warned.update(new)


if __name__ == "__main__":
    main()
