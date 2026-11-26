"""
Gap-free dungeon generator for any tile set described in a JSON file.

Terms: a room is one tile image (one physical piece); a tile is one unit of the
map grid (a small room covers 1 tile, a 2x2 room 4); a square is one of the
SUB x SUB subdivisions of a tile, where a marker sits.

A tile set only lists the available rooms: their size in tiles, which edges of
which tiles are open, their image(s) and how many copies exist. Everything else
is decided here. The generator fills a W x H grid of tiles with those rooms so that:

  - there is no empty space,
  - every opening meets an opening on the neighbouring room (and walls meet walls),
  - every room is reachable from every other room,
  - there is exactly one large room (2x2) and one or two medium rooms (1x2),
  - copy counts are respected.

Two kinds of map:

  - branching (default): rooms with two or more openings; two straights never join
    end to end. IN is at a random spot on the map edge and OUT at the spot mirrored
    through the map's centre, as far apart as they can be.
  - linear (--linear): only rooms with exactly two openings, so the map is a single
    path from IN to OUT, through every room.

Both have exactly two openings facing the map edge, IN and OUT, and IN is never in
the large room.

Rooms with one opening (dead ends) are never used. Rooms are rotated freely and
picked with fixed weights by shape (see shape_weight).

A room with several images is one shape to the solver; once the layout is
solved, its images are spread evenly over the copies placed.

Markers go on a checkerboard of tiles, starting from the tile after IN: one in the
large room is the goal and the rest are "?" found in play.

Output: one {tileset}_dungeon_{SEED}.png per dungeon, drawn from the room
images (or a schematic for rooms whose image is missing).
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
DEFAULT_OUT_DIR = os.path.join(HERE, "output")

DIRS: Dict[str, Tuple[int, int]] = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
ROT_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}

Opening = Tuple[int, int, str]  # (tile_x, tile_y, edge) relative to the room's top-left


# ─────────────────────────────────────────────
# Tile set
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class Art:
    """One image of a room. A room's images share its shape; only the artwork differs."""
    name: str                     # badge and caption label
    path: str                     # absolute path
    copies: Optional[int]         # None = unlimited


@dataclass
class RoomDef:
    room_id: str
    piece: str                    # physical piece; rooms sharing a piece are its faces
    copies: Optional[int]         # None = unlimited
    size: Tuple[int, int]
    openings: List[Opening]
    images: List[Art]             # empty = drawn as a schematic

    @property
    def area(self) -> int:
        return self.size[0] * self.size[1]

    @property
    def size_class(self) -> str:
        return {(1, 1): "small", (1, 2): "medium", (2, 2): "large"}.get(tuple(sorted(self.size)), "other")

    @property
    def straight(self) -> bool:
        """Two openings facing each other across the room, in line (I shapes)."""
        if len(self.openings) != 2:
            return False
        (x1, y1, e1), (x2, y2, e2) = self.openings
        return ({e1, e2} == {"N", "S"} and x1 == x2) or ({e1, e2} == {"E", "W"} and y1 == y2)

    @property
    def tags(self) -> FrozenSet[str]:
        """What the solver's limits and no-connect rule look at."""
        return frozenset([self.size_class] + (["straight"] if self.straight else []))

    @property
    def weight(self) -> float:
        return shape_weight(self)


def shape_weight(room: RoomDef) -> float:
    """How often the solver tries a room, by its shape (dungeon-generator's weights:
    X 4, T 5, I 2, L 1). Rooms with one opening are never used."""
    n = len(room.openings)
    if n >= 4:
        return 4
    if n == 3:
        return 5
    if n == 2:
        return 2 if room.straight else 1
    return 0


# Every map has exactly one large room and one or two medium rooms: size class -> (min, max).
LIMITS: Dict[str, Tuple[int, int]] = {"large": (1, 1), "medium": (1, 2)}


@dataclass
class TileSet:
    name: str
    path: str
    rooms: Dict[str, RoomDef]
    piece_copies: Dict[str, Optional[int]]

    def usable(self, linear: bool) -> List[RoomDef]:
        """Linear maps use only rooms with exactly two openings; branching maps any with two or more."""
        return [r for r in self.rooms.values()
                if (len(r.openings) == 2 if linear else len(r.openings) >= 2)]


def _parse_openings(rid: str, raw, w: int, h: int) -> List[Opening]:
    if isinstance(raw, str):
        if (w, h) != (1, 1):
            raise SystemExit(f"Room {rid}: the \"NESW\" shorthand only works for 1x1 rooms; "
                             f"use [x, y, edge] entries for a {w}x{h} room.")
        raw = [[0, 0, e] for e in raw.upper()]
    out: List[Opening] = []
    for o in raw:
        x, y, e = int(o[0]), int(o[1]), str(o[2]).upper()
        if e not in DIRS:
            raise SystemExit(f"Room {rid}: edge {e!r} must be one of N, E, S, W.")
        if not (0 <= x < w and 0 <= y < h):
            raise SystemExit(f"Room {rid}: opening tile ({x}, {y}) is outside its {w}x{h} size.")
        dx, dy = DIRS[e]
        if 0 <= x + dx < w and 0 <= y + dy < h:
            raise SystemExit(f"Room {rid}: opening ({x}, {y}, {e}) is on an inside edge of the room, "
                             f"not on its outline.")
        out.append((x, y, e))
    return out


def _parse_images(rid: str, t: dict, image_dir: str) -> List[Art]:
    """`image` (one file) or `images` (a list of files or {"file", "copies"} entries).

    With one image the label is the room's ID; with several it's each file's name
    without its extension, so the map shows which physical room to put down.
    """
    if "image" in t and "images" in t:
        raise SystemExit(f"Room {rid}: use either \"image\" or \"images\", not both.")
    raw = t.get("images", [t["image"]] if t.get("image") else [])
    entries = []
    for r in raw:
        if isinstance(r, str):
            entries.append((r, None))
        elif isinstance(r, dict) and "file" in r:
            entries.append((str(r["file"]), None if r.get("copies") is None else int(r["copies"])))
        else:
            raise SystemExit(f"Room {rid}: each image must be a file name or {{\"file\": ..., \"copies\": N}}.")
    return [Art(name=rid if len(entries) == 1 else os.path.splitext(os.path.basename(f))[0],
                path=os.path.join(image_dir, f), copies=c)
            for f, c in entries]


def resolve_tileset_path(arg: str) -> str:
    """A file path, or the bare name of a file in tilesets/ (with or without .json)."""
    for c in (arg, arg + ".json", os.path.join(TILESETS_DIR, arg), os.path.join(TILESETS_DIR, arg + ".json")):
        if os.path.isfile(c):
            return os.path.abspath(c)
    available = sorted(f[:-5] for f in os.listdir(TILESETS_DIR) if f.endswith(".json"))
    raise SystemExit(f"Tile set {arg!r} not found. Available in tilesets/: {', '.join(available) or 'none'}.")


def load_tileset(path: str) -> TileSet:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    image_dir = os.path.join(os.path.dirname(path), data.get("image_dir", "."))
    rooms: Dict[str, RoomDef] = {}
    piece_copies: Dict[str, Optional[int]] = {}
    for rid, t in data.get("rooms", {}).items():
        if rid.startswith("_"):
            continue
        w, h = (int(t["size"][0]), int(t["size"][1])) if "size" in t else (1, 1)
        copies = t.get("copies")
        copies = None if copies is None else int(copies)
        piece = str(t.get("piece", rid))
        images = _parse_images(rid, t, image_dir)
        # When every image has a copy count, the room can't be used more often than their total.
        if images and all(a.copies is not None for a in images):
            total = sum(a.copies for a in images)
            copies = total if copies is None else min(copies, total)
        rooms[rid] = RoomDef(
            room_id=rid,
            piece=piece,
            copies=copies,
            size=(w, h),
            openings=_parse_openings(rid, t.get("openings", []), w, h),
            images=images,
        )
        # Faces of one piece share its copies; unlimited wins if any face says so.
        if piece in piece_copies and (piece_copies[piece] is None or copies is None):
            piece_copies[piece] = None
        else:
            piece_copies[piece] = copies if piece not in piece_copies else max(piece_copies[piece], copies)

    return TileSet(
        name=data.get("name") or os.path.splitext(os.path.basename(path))[0],
        path=path,
        rooms=rooms,
        piece_copies=piece_copies,
    )


# ─────────────────────────────────────────────
# Rotations
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class Variant:
    """One room in one rotation."""
    room_id: str
    rotation: int                 # quarter turns clockwise from the room's image orientation
    w: int
    h: int
    tile_open: Tuple[Tuple[FrozenSet[str], ...], ...]   # [y][x] -> open edges of that tile


def rotate_cw(w: int, h: int, openings: List[Opening]) -> Tuple[int, int, List[Opening]]:
    """Rotate a room 90 degrees clockwise: tile (x, y) -> (h - 1 - y, x)."""
    return h, w, [(h - 1 - y, x, ROT_CW[e]) for x, y, e in openings]


def build_variants(room: RoomDef) -> List[Variant]:
    """All distinct rotations of a room."""
    w, h = room.size
    ops = list(room.openings)
    seen = set()
    out: List[Variant] = []
    for rot in range(4):
        key = (w, h, frozenset(ops))
        if key not in seen:
            seen.add(key)
            grid = tuple(tuple(frozenset(e for (ox, oy, e) in ops if ox == x and oy == y)
                               for x in range(w)) for y in range(h))
            out.append(Variant(room.room_id, rot, w, h, grid))
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
        return self.art.name if self.art else self.variant.room_id


@dataclass
class Layout:
    width: int
    height: int
    placements: List[Placement]
    room_at: List[List[int]]                                  # tile -> index into placements
    order: List[int] = field(default_factory=list)            # placement indexes, from the entrance outwards
    border_openings: List[Tuple[int, int, str]] = field(default_factory=list)  # absolute (x, y, edge)


class _OutOfBudget(Exception):
    pass


class Solver:
    """Randomised backtracking: always fill the first empty tile (row-major)."""

    def __init__(self, ts: TileSet, width: int, height: int, linear: bool,
                 rng: random.Random, step_budget: int = 20000):
        self.ts = ts
        self.W, self.H = width, height
        self.border_min = self.border_max = 2                    # IN and OUT
        self.linear = linear
        self.limits = LIMITS
        self.rng = rng
        self.step_budget = step_budget
        self.rooms = ts.usable(linear)
        self.variants = {t.room_id: build_variants(t) for t in self.rooms}
        # Size classes of each room that have a limit, checked on every step.
        self.max_tags = {t.room_id: [tag for tag in sorted(t.tags) if tag in LIMITS] for t in self.rooms}
        # For each size class with a minimum: the smallest room area in it (for pruning).
        self.min_tag_area = {
            tag: min((t.area for t in self.rooms if tag in t.tags), default=math.inf)
            for tag, (lo, _) in LIMITS.items() if lo > 0}
        # On branching maps, straights never join end to end (no long corridors).
        straights = [] if linear else [t.room_id for t in self.rooms if t.straight]
        self.no_connect = {(a, b) for a in straights for b in straights}

    # ── state ──
    def _reset(self) -> None:
        self.steps = 0
        # Branching maps: IN at a random spot on the edge, OUT mirrored through the centre.
        # Linear maps need no spots: the path visits every room, so its ends are IN and OUT.
        self.spots: Optional[set] = None
        self.in_spot: Optional[Tuple[int, int, str]] = None
        if not self.linear:
            edge = [(x, y, e) for y in range(self.H) for x in range(self.W) for e, (dx, dy) in DIRS.items()
                    if not (0 <= x + dx < self.W and 0 <= y + dy < self.H)]
            x, y, e = self.in_spot = self.rng.choice(edge)
            self.spots = {self.in_spot, (self.W - 1 - x, self.H - 1 - y, OPP[e])}
        self.room_at = [[-1] * self.W for _ in range(self.H)]
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
        """Put the rooms the limits require (the large room...) at random spots before the main fill.

        Filling row by row and only then discovering that a required room (e.g. a
        2x2 boss room) no longer fits wastes most of the search, so they go first.
        """
        for tag, (lo, _) in sorted(self.limits.items()):
            while self.tag_used[tag] < lo:
                spots = [(v, x, y)
                         for t in self.rooms if tag in t.tags and self._available(t)
                         for v in self.variants[t.room_id]
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
    def _available(self, t: RoomDef) -> bool:
        cap = self.ts.piece_copies[t.piece]
        if cap is not None and self.piece_used[t.piece] >= cap:
            return False
        for tag in self.max_tags[t.room_id]:
            if self.tag_used[tag] >= self.limits[tag][1]:
                return False
        return True

    def _capacity(self, avail: List[RoomDef]) -> float:
        """Upper bound on the area the available rooms can still cover."""
        free = 0.0
        best: Dict[str, Tuple[int, Optional[str]]] = {}   # piece -> (largest face area, a capped tag)
        for t in avail:
            area, tag = best.get(t.piece, (0, None))
            mt = self.max_tags[t.room_id]
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
                room = self.limits[tag][1] - self.tag_used[tag]
                capped.setdefault(tag, []).extend([area] * int(min(left, room)))
        for tag, areas in capped.items():
            room = self.limits[tag][1] - self.tag_used[tag]
            free += sum(sorted(areas, reverse=True)[:room])
        return free

    def _min_area_needed(self) -> float:
        need = 0.0
        for tag, area in self.min_tag_area.items():
            missing = self.limits[tag][0] - self.tag_used[tag]
            if missing > 0:
                need = max(need, missing * area)
        return need

    def _first_empty(self) -> Optional[Tuple[int, int]]:
        for y in range(self.H):
            row = self.room_at[y]
            for x in range(self.W):
                if row[x] < 0:
                    return x, y
        return None

    def _fits(self, v: Variant, x0: int, y0: int) -> Optional[int]:
        """Return the number of border openings this room adds, or None if it can't go here."""
        if x0 + v.w > self.W or y0 + v.h > self.H:
            return None
        for j in range(v.h):
            for i in range(v.w):
                if self.room_at[y0 + j][x0 + i] >= 0:
                    return None
        if self.in_spot and self.ts.rooms[v.room_id].size_class == "large" \
                and x0 <= self.in_spot[0] < x0 + v.w and y0 <= self.in_spot[1] < y0 + v.h:
            return None   # IN is never in the large room
        border = 0
        for j in range(v.h):
            for i in range(v.w):
                tile_open = v.tile_open[j][i]
                for e, (dx, dy) in DIRS.items():
                    if 0 <= i + dx < v.w and 0 <= j + dy < v.h:
                        continue  # inside the room
                    nx, ny = x0 + i + dx, y0 + j + dy
                    if not (0 <= nx < self.W and 0 <= ny < self.H):
                        if self.spots is not None and ((x0 + i, y0 + j, e) in self.spots) != (e in tile_open):
                            return None   # open exactly at IN and OUT, walls elsewhere
                        if e in tile_open:
                            border += 1
                        continue
                    if self.room_at[ny][nx] < 0:
                        continue
                    # Openings must meet openings; walls must meet walls.
                    if (e in tile_open) != (OPP[e] in self.open_at[ny][nx]):
                        return None
                    if e in tile_open and self.no_connect:
                        other = self.placements[self.room_at[ny][nx]].variant.room_id
                        if (v.room_id, other) in self.no_connect:
                            return None
        return border

    def _candidates(self, avail: List[RoomDef]) -> List[Variant]:
        """Available rooms in weighted random order, each followed by its rotations in random order."""
        keyed = sorted(avail, key=lambda t: self.rng.random() ** (1.0 / t.weight), reverse=True)
        out: List[Variant] = []
        for t in keyed:
            vs = list(self.variants[t.room_id])
            self.rng.shuffle(vs)
            out.extend(vs)
        return out

    # ── search ──
    def _place(self, v: Variant, x0: int, y0: int, added: int) -> None:
        t = self.ts.rooms[v.room_id]
        idx = len(self.placements)
        self.placements.append(Placement(v, x0, y0))
        self.piece_used[t.piece] += 1
        for tag in t.tags:
            self.tag_used[tag] += 1
        self.border += added
        self.empty -= v.w * v.h
        for j in range(v.h):
            for i in range(v.w):
                self.room_at[y0 + j][x0 + i] = idx
                self.open_at[y0 + j][x0 + i] = v.tile_open[j][i]

    def _unplace(self, v: Variant, x0: int, y0: int, added: int) -> None:
        t = self.ts.rooms[v.room_id]
        for j in range(v.h):
            for i in range(v.w):
                self.room_at[y0 + j][x0 + i] = -1
                self.open_at[y0 + j][x0 + i] = frozenset()
        self.empty += v.w * v.h
        self.border -= added
        for tag in t.tags:
            self.tag_used[tag] -= 1
        self.piece_used[t.piece] -= 1
        self.placements.pop()

    def _limits_met(self) -> bool:
        return all(self.tag_used[tag] >= lo for tag, (lo, _) in self.limits.items())

    def _rec(self) -> bool:
        self.steps += 1
        if self.steps > self.step_budget:
            raise _OutOfBudget()
        fe = self._first_empty()
        if fe is None:
            return (self.border_min <= self.border <= self.border_max
                    and self._limits_met() and self._connected())
        avail = [t for t in self.rooms if self._available(t)]
        if self._capacity(avail) < self.empty or self._min_area_needed() > self.empty:
            return False
        x0, y0 = fe
        for v in self._candidates(avail):
            if not self._available(self.ts.rooms[v.room_id]):
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
                a = self.room_at[y][x]
                for e in ("E", "S"):
                    dx, dy = DIRS[e]
                    nx, ny = x + dx, y + dy
                    if nx < self.W and ny < self.H:
                        b = self.room_at[ny][nx]
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
                        ends.append((self.room_at[y][x], (x, y, e)))
        self.rng.shuffle(ends)
        if self.in_spot:
            ends.sort(key=lambda e: e[1] != self.in_spot)
        else:   # linear: IN is the end outside the large room when there's a choice
            ends.sort(key=lambda e: self.ts.rooms[self.placements[e[0]].variant.room_id].size_class == "large")
        start = ends[0][0] if ends else self.rng.randrange(len(self.placements))
        order = self._bfs(start)
        self._assign_art(order)
        return Layout(self.W, self.H, list(self.placements),
                      [row[:] for row in self.room_at], order, [e for _, e in ends])

    def _assign_art(self, order: List[int]) -> None:
        """Pick each room's image once the layout is solved.

        Images never affect the layout, so this can't fail or force backtracking.
        Going outwards from the entrance, each room gets its least-used image
        (keeping counts within one of each other), preferring one that no touching
        room already shows, then at random. Per-image copies are never exceeded:
        the solver already kept the room within their total.
        """
        touching: Dict[int, set] = {i: set() for i in range(len(self.placements))}
        for y in range(self.H):
            for x in range(self.W):
                a = self.room_at[y][x]
                for nx, ny in ((x + 1, y), (x, y + 1)):
                    if nx < self.W and ny < self.H and self.room_at[ny][nx] != a:
                        b = self.room_at[ny][nx]
                        touching[a].add(b)
                        touching[b].add(a)
        used: Counter = Counter()
        for idx in order:
            p = self.placements[idx]
            arts = self.ts.rooms[p.variant.room_id].images
            if not arts:
                continue
            nearby = {self.placements[n].art for n in touching[idx]}
            free = [a for a in arts if a.copies is None or used[a] < a.copies]
            p.art = min(free, key=lambda a: (used[a], a in nearby, self.rng.random()))
            used[p.art] += 1


# ─────────────────────────────────────────────
# Markers
# ─────────────────────────────────────────────
# Each tile is split into SUB x SUB squares; a marker sits on a tile's centre square.
# Markers go on slots: every other tile, like a checkerboard. So no two markers are on
# tiles that share an edge, a medium room always holds one and the large room two.
# The players start at IN; the tile they enter has no marker and the pattern runs from
# there. One slot in the large room is the goal; every other slot is a "?" found in play.

SUB = 3
Square = Tuple[int, int]          # (x, y) in squares, from the map's top-left
Tile = Tuple[int, int]            # (x, y) in tiles, from the map's top-left


@dataclass(frozen=True)
class MarkerType:
    color: Tuple[int, int, int]
    large: bool                   # drawn bigger than the "?"s
    label: str = ""


MARKER_TYPES: Dict[str, MarkerType] = {
    "goal":  MarkerType((40, 180, 80), True, "G"),
    "?":     MarkerType((220, 140, 40), False, "?"),
}


@dataclass
class Marker:
    tile: Tile
    type: str

    @property
    def square(self) -> Square:
        return self.tile[0] * SUB + SUB // 2, self.tile[1] * SUB + SUB // 2


def place_markers(layout: Layout, ts: TileSet, rng: random.Random) -> List[Marker]:
    room_of = lambda t: layout.room_at[t[1]][t[0]]
    large = next((i for i, p in enumerate(layout.placements)
                  if ts.rooms[p.variant.room_id].size_class == "large"), None)
    x, y, _ = layout.border_openings[0]            # IN: its tile is off, the next ones are slots
    parity = (x + y + 1) % 2
    slots = [(x, y) for y in range(layout.height) for x in range(layout.width) if (x + y) % 2 == parity]

    markers: List[Marker] = []
    goal = [t for t in slots if room_of(t) == large]
    if goal:
        markers.append(Marker(rng.choice(goal), "goal"))
    taken = {m.tile for m in markers}
    markers += [Marker(t, "?") for t in slots if t not in taken]
    return markers


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


def _schematic(room: RoomDef, tile_px: int) -> Image.Image:
    """Stand-in room drawing for when the image isn't available."""
    w, h = room.size
    img = Image.new("RGB", (w * tile_px, h * tile_px), (70, 66, 60))
    d = ImageDraw.Draw(img)
    t = max(4, tile_px // 10)
    d.rectangle([0, 0, img.width - 1, img.height - 1], outline=(25, 25, 25), width=t)
    for x, y, e in room.openings:
        x0, y0 = x * tile_px, y * tile_px
        a, b = int(tile_px * 0.3), int(tile_px * 0.7)
        box = {"N": (x0 + a, y0, x0 + b, y0 + t), "S": (x0 + a, y0 + tile_px - t, x0 + b, y0 + tile_px),
               "W": (x0, y0 + a, x0 + t, y0 + b), "E": (x0 + tile_px - t, y0 + a, x0 + tile_px, y0 + b)}[e]
        d.rectangle(box, fill=(200, 190, 160))
    d.text((img.width // 2, img.height // 2), room.room_id, fill=(230, 230, 230),
           font=_font(max(12, tile_px // 5)), anchor="mm")
    return img


def render_png(layout: Layout, ts: TileSet, out_path: str, tile_px: int, caption: str,
               number_rooms: bool = False, markers: Optional[List[Marker]] = None) -> List[str]:
    """Render the layout. Returns the labels of rooms drawn as schematics (image missing)."""
    margin = max(24, tile_px // 3)
    font_px = max(12, round(tile_px * 0.09))
    font = _font(font_px)
    cap_font = _font(max(12, round(tile_px * 0.1)))
    cap_h = round(cap_font.size * 1.8) if hasattr(cap_font, "size") else 24
    W, H = layout.width * tile_px, layout.height * tile_px
    img = Image.new("RGB", (W + 2 * margin, H + 2 * margin + cap_h), (18, 20, 22))
    d = ImageDraw.Draw(img)

    missing: List[str] = []
    cache: Dict[str, Image.Image] = {}
    for p in layout.placements:
        room = ts.rooms[p.variant.room_id]
        path = p.art.path if p.art else ""
        if path and os.path.exists(path):
            if path not in cache:
                cache[path] = Image.open(path).convert("RGB")
            pic = cache[path]
        else:
            if p.label not in missing:
                missing.append(p.label)
            pic = _schematic(room, tile_px)
        if p.variant.rotation:
            pic = pic.rotate(-90 * p.variant.rotation, expand=True)
        pic = pic.resize((p.variant.w * tile_px, p.variant.h * tile_px), Image.LANCZOS)
        img.paste(pic, (margin + p.x * tile_px, margin + p.y * tile_px))

    # Room outlines, then badges (room ID, optionally prefixed by its order from the entrance).
    order = {idx: n + 1 for n, idx in enumerate(layout.order)}
    for idx, p in enumerate(layout.placements):
        x0, y0 = margin + p.x * tile_px, margin + p.y * tile_px
        x1, y1 = x0 + p.variant.w * tile_px, y0 + p.variant.h * tile_px
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(10, 10, 10), width=max(2, tile_px // 100))
        label = f"{order[idx]} · {p.label}" if number_rooms else p.label
        pad = font_px // 3
        tw = d.textlength(label, font=font)
        bx, by = x0 + pad * 2, y0 + pad * 2
        d.rounded_rectangle([bx, by, bx + tw + 2 * pad, by + font_px + 2 * pad],
                            radius=pad, fill=(15, 15, 15), outline=(230, 200, 90), width=2)
        d.text((bx + pad, by + pad + font_px / 2), label, fill=(240, 240, 240), font=font, anchor="lm")

    # Markers, centred on their square.
    if markers:
        sp = tile_px / SUB

        def dot(s: Square, colour, r: float, text: str = "") -> None:
            cx, cy = margin + (s[0] + 0.5) * sp, margin + (s[1] + 0.5) * sp
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour, outline=(15, 15, 15),
                      width=max(2, tile_px // 100))
            if text:
                d.text((cx, cy), text, fill=(255, 255, 255), font=_font(max(10, round(r * 1.3))), anchor="mm")

        for m in markers:
            mt = MARKER_TYPES[m.type]
            dot(m.square, mt.color, sp / 3 if mt.large else sp / 4, mt.label)

    # Border openings in the margin: the first is the entrance, the rest are exits.
    for n, (x, y, e) in enumerate(layout.border_openings):
        text, colour = ("IN", (60, 170, 80)) if n == 0 else ("OUT", (200, 60, 50))
        cx = margin + x * tile_px + tile_px // 2
        cy = margin + y * tile_px + tile_px // 2
        dx, dy = DIRS[e]
        cx += dx * (tile_px // 2 + margin // 2)
        cy += dy * (tile_px // 2 + margin // 2)
        r = margin // 2 - 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)
        d.text((cx, cy), text, fill=(255, 255, 255), font=_font(max(10, round(r * 0.8))), anchor="mm")

    # Shrink the caption to fit the map's width (long room lists on narrow maps).
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


def room_counts(layout: Layout) -> str:
    counts = Counter(p.label for p in layout.placements)
    return "  ".join(f"{rid} x{counts[rid]}" for rid in sorted(counts, key=_natural))


# ─────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────

def check_rooms(ts: TileSet, width: int, height: int, linear: bool) -> None:
    """Fail early with a clear message when the tile set obviously can't make the map."""
    rooms = ts.usable(linear)
    kind = "linear" if linear else "branching"
    for size, (lo, _) in LIMITS.items():
        if lo and not any(r.size_class == size for r in rooms):
            raise SystemExit(f"{ts.name} has no {size} room usable on a {kind} map "
                             f"({'exactly two' if linear else 'two or more'} openings).")
    if not linear and not any(len(r.openings) >= 3 for r in rooms):
        raise SystemExit(f"{ts.name} has no room with three or more openings, so it can't branch. "
                         f"Use --linear.")
    capacity = 0.0
    for piece, cap in ts.piece_copies.items():
        faces = [t for t in rooms if t.piece == piece]
        if not faces:
            continue
        if cap is None:
            return
        capacity += cap * max(t.area for t in faces)
    if capacity < width * height:
        raise SystemExit(f"Can't fill {width}x{height} ({width * height} tiles): "
                         f"all of {ts.name}'s usable rooms together cover only {int(capacity)}.")


def generate(seed: int, ts: TileSet, width: int, height: int, linear: bool) -> Optional[Layout]:
    """Deterministic for a given seed, tile set, size and kind of map."""
    return Solver(ts, width, height, linear, random.Random(seed)).solve()


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate gap-free dungeons from a tile set described in JSON.")
    ap.add_argument("--tileset",  required=True,
                    help="Tile set: a name from tilesets/ (e.g. city) or a path to a JSON file.")
    ap.add_argument("--linear",   action="store_true",
                    help="A single path from IN to OUT, using only rooms with two openings "
                         "(default: a branching map, with IN and OUT on opposite edges).")
    ap.add_argument("--width",    type=int, default=5, help="Dungeon width in tiles (default: 5).")
    ap.add_argument("--height",   type=int, default=4, help="Dungeon height in tiles (default: 4).")
    ap.add_argument("--number-rooms", action="store_true",
                    help="Prefix each room's badge with its order from the entrance. Only meaningful "
                         "on linear maps.")
    ap.add_argument("--no-markers", action="store_true", help="Leave out the goal and '?' markers.")
    ap.add_argument("--n",        type=int, default=3,    help="Number of dungeons to generate (default: 3).")
    ap.add_argument("--seed",     type=int, default=None, help="Generate one specific dungeon by seed.")
    ap.add_argument("--tile-px", type=int, default=300, help="Pixels per tile in the PNG (default: 300).")
    ap.add_argument("--out-dir",  default=None,
                    help="Where to write the PNGs (default: output/<tileset>/ in this folder).")
    args = ap.parse_args()

    ts = load_tileset(resolve_tileset_path(args.tileset))
    width, height, linear = args.width, args.height, args.linear
    check_rooms(ts, width, height, linear)
    slug = "".join(c if c.isalnum() else "_" for c in os.path.splitext(os.path.basename(ts.path))[0]).lower()
    out_dir = args.out_dir or os.path.join(DEFAULT_OUT_DIR, slug)
    os.makedirs(out_dir, exist_ok=True)
    kind = "linear" if linear else "branching"

    seeds = [args.seed] if args.seed is not None else [random.randint(0, 2**32 - 1) for _ in range(args.n)]
    warned: set = set()
    for seed in seeds:
        layout = generate(seed, ts, width, height, linear)
        if layout is None:
            print(f"Seed {seed}: no layout found, skipping. "
                  f"If this keeps happening, the rooms may not be able to fill {width}x{height}.")
            continue
        caption = (f"{ts.name}  ·  {kind.capitalize()}  ·  Seed {seed}  ·  "
                   f"{len(layout.placements)} rooms  ·  {room_counts(layout)}")
        base = os.path.join(out_dir, f"{slug}_{kind}_dungeon_{seed}")
        # Own random stream, so marker placement never changes the layout for a seed.
        markers = None if args.no_markers else place_markers(layout, ts, random.Random(f"{seed}:items"))
        missing = render_png(layout, ts, base + ".png", args.tile_px, caption, args.number_rooms, markers)
        print(f"Saved: {base}.png")
        new = [m for m in missing if m not in warned]
        if new:
            print(f"Note: no image found for {', '.join(new)}; drew schematic rooms instead.")
            warned.update(new)


if __name__ == "__main__":
    main()
