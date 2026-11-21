"""
Gap-free dungeon generator for Gears of War board game tiles.

Fills a W x H grid (in small-tile units, default 5x4) with tile sides from
tiles.json so that there is no empty space, every opening meets an opening on
the neighbouring tile, and exactly two openings face the map border: the
dungeon's entrance and exit. Every tile side has exactly two openings, so each
dungeon is a single winding path from entrance to exit.

Rules:
  - Either side of a tile may be used, never both sides of the same tile.
  - Any rotation is allowed; openings only need to be on the matching edge.

Output per dungeon:
  gow_dungeon_{SEED}.png  rendered layout (tile scans, or a schematic if the
                          scans aren't available)
  gow_dungeon_{SEED}.txt  build list: path order, position, rotation, spawns,
                          loot and room rewards
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(HERE, "tiles.json")
DEFAULT_TILES_DIR = os.path.join(HERE, "tiles")
DEFAULT_OUT_DIR = os.path.join(HERE, "output")

DIRS: Dict[str, Tuple[int, int]] = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
ROT_CW = {"N": "E", "E": "S", "S": "W", "W": "N"}
EDGE_NAMES = {"N": "north", "E": "east", "S": "south", "W": "west"}

Opening = Tuple[int, int, str]  # (cell_x, cell_y, edge) relative to the piece's top-left


# ─────────────────────────────────────────────
# Tile data
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class Variant:
    """One tile side in one rotation."""
    side_id: str                  # e.g. "7A"
    tile_id: str                  # physical tile, e.g. "7"
    rotation: int                 # quarter turns clockwise from the printed orientation
    w: int
    h: int
    openings: FrozenSet[Opening]


@dataclass
class SideInfo:
    side_id: str
    tile_id: str
    size: Tuple[int, int]
    shape: str
    openings: List[Opening]
    spawns: int
    loot: int
    room_name: str
    room_reward: str


def load_sides(path: str) -> Dict[str, SideInfo]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    sides: Dict[str, SideInfo] = {}
    for sid, s in data["sides"].items():
        room = s.get("room") or {}
        sides[sid] = SideInfo(
            side_id=sid,
            tile_id=sid[:-1],
            size=(int(s["size"][0]), int(s["size"][1])),
            shape=s.get("shape", "?"),
            openings=[(int(o[0]), int(o[1]), str(o[2])) for o in s["openings"]],
            spawns=int(s.get("spawns", 0)),
            loot=int(s.get("loot", 0)),
            room_name=room.get("name", "") or "",
            room_reward=room.get("reward", "") or "",
        )
    return sides


def rotate_cw(w: int, h: int, openings: List[Opening]) -> Tuple[int, int, List[Opening]]:
    """Rotate a piece 90 degrees clockwise: cell (x, y) -> (h - 1 - y, x)."""
    return h, w, [(h - 1 - y, x, ROT_CW[e]) for x, y, e in openings]


def build_variants(side: SideInfo) -> List[Variant]:
    """All distinct rotations of a tile side."""
    w, h = side.size
    ops = list(side.openings)
    seen = set()
    out: List[Variant] = []
    for rot in range(4):
        key = (w, h, frozenset(ops))
        if key not in seen:
            seen.add(key)
            out.append(Variant(side.side_id, side.tile_id, rot, w, h, frozenset(ops)))
        w, h, ops = rotate_cw(w, h, ops)
    return out


def tile_class(side: SideInfo) -> str:
    w, h = side.size
    return {1: "small", 2: "medium", 4: "large"}.get(w * h, "other")


# ─────────────────────────────────────────────
# Layout search
# ─────────────────────────────────────────────

@dataclass
class Placement:
    variant: Variant
    x: int
    y: int


@dataclass
class Layout:
    width: int
    height: int
    placements: List[Placement]
    cells: List[List[int]]                                   # cell -> index into placements
    path: List[int] = field(default_factory=list)            # placement indexes, entrance -> exit
    entrance: Optional[Tuple[int, int, str]] = None          # absolute (x, y, edge) on the border
    exit: Optional[Tuple[int, int, str]] = None


class Solver:
    """Randomised backtracking: always fill the first empty cell (row-major)."""

    def __init__(self, width: int, height: int, pool: Dict[str, List[Variant]],
                 rng: random.Random, step_budget: int = 20000):
        self.W, self.H = width, height
        self.pool = pool                     # physical tile id -> variants (both sides, all rotations)
        self.rng = rng
        self.step_budget = step_budget

    def solve(self, attempts: int = 60) -> Optional[Layout]:
        for _ in range(attempts):
            self.steps = 0
            self.cells: List[List[int]] = [[-1] * self.W for _ in range(self.H)]
            self.open_at: List[List[FrozenSet[str]]] = [[frozenset()] * self.W for _ in range(self.H)]
            self.placements: List[Placement] = []
            self.used: set = set()
            self.border = 0
            try:
                if self._rec():
                    return self._finish()
            except _OutOfBudget:
                continue
        return None

    def _first_empty(self) -> Optional[Tuple[int, int]]:
        for y in range(self.H):
            row = self.cells[y]
            for x in range(self.W):
                if row[x] < 0:
                    return x, y
        return None

    def _fits(self, v: Variant, x0: int, y0: int) -> Optional[int]:
        """Return the number of border openings this piece adds, or None if it can't go here."""
        if x0 + v.w > self.W or y0 + v.h > self.H:
            return None
        for j in range(v.h):
            for i in range(v.w):
                if self.cells[y0 + j][x0 + i] >= 0:
                    return None
        border = 0
        for j in range(v.h):
            for i in range(v.w):
                cell_open = {e for (ox, oy, e) in v.openings if ox == i and oy == j}
                for e, (dx, dy) in DIRS.items():
                    nx, ny = x0 + i + dx, y0 + j + dy
                    inside_piece = 0 <= nx - x0 < v.w and 0 <= ny - y0 < v.h
                    if inside_piece:
                        continue
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

    def _rec(self) -> bool:
        self.steps += 1
        if self.steps > self.step_budget:
            raise _OutOfBudget()
        fe = self._first_empty()
        if fe is None:
            return self.border == 2 and self._connected()
        x0, y0 = fe
        cands = [v for tid, vs in self.pool.items() if tid not in self.used for v in vs]
        self.rng.shuffle(cands)
        for v in cands:
            if v.tile_id in self.used:
                continue
            added = self._fits(v, x0, y0)
            if added is None or self.border + added > 2:
                continue
            idx = len(self.placements)
            self.placements.append(Placement(v, x0, y0))
            self.used.add(v.tile_id)
            self.border += added
            for j in range(v.h):
                for i in range(v.w):
                    self.cells[y0 + j][x0 + i] = idx
                    self.open_at[y0 + j][x0 + i] = frozenset(
                        e for (ox, oy, e) in v.openings if ox == i and oy == j)
            if self._rec():
                return True
            for j in range(v.h):
                for i in range(v.w):
                    self.cells[y0 + j][x0 + i] = -1
                    self.open_at[y0 + j][x0 + i] = frozenset()
            self.border -= added
            self.used.discard(v.tile_id)
            self.placements.pop()
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

    def _connected(self) -> bool:
        links = self._links()
        seen = {0}
        stack = [0]
        while stack:
            for n in links[stack.pop()]:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        return len(seen) == len(self.placements)

    def _finish(self) -> Layout:
        # Border openings: the two loose ends of the path.
        ends: List[Tuple[int, Tuple[int, int, str]]] = []
        for y in range(self.H):
            for x in range(self.W):
                for e in self.open_at[y][x]:
                    dx, dy = DIRS[e]
                    if not (0 <= x + dx < self.W and 0 <= y + dy < self.H):
                        ends.append((self.cells[y][x], (x, y, e)))
        self.rng.shuffle(ends)
        (start, entrance), (_, exit_) = ends[0], ends[1]
        links = self._links()
        path, prev, cur = [start], -1, start
        while True:
            nxt = [n for n in links[cur] if n != prev]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            path.append(cur)
        return Layout(self.W, self.H, list(self.placements),
                      [row[:] for row in self.cells], path, entrance, exit_)


class _OutOfBudget(Exception):
    pass


def choose_pool(sides: Dict[str, SideInfo], width: int, height: int,
                mediums: int, boss: bool, rng: random.Random) -> Dict[str, List[Variant]]:
    """Pick which physical tiles go into this dungeon so their area fills the grid exactly."""
    by_class: Dict[str, List[str]] = {"small": [], "medium": [], "large": []}
    for s in sides.values():
        cls = tile_class(s)
        if cls in by_class and s.tile_id not in by_class[cls]:
            by_class[cls].append(s.tile_id)

    n_large = 1 if boss else 0
    n_small = width * height - 2 * mediums - 4 * n_large
    problems = []
    if mediums > len(by_class["medium"]):
        problems.append(f"only {len(by_class['medium'])} medium tiles exist")
    if boss and not by_class["large"]:
        problems.append("no large tile exists")
    if not 0 <= n_small <= len(by_class["small"]):
        problems.append(f"that leaves {n_small} small-tile spaces, but there are "
                        f"{len(by_class['small'])} small tiles")
    if problems:
        raise SystemExit(
            f"Can't fill {width}x{height} with {mediums} medium(s)"
            f"{' + the large tile' if boss else ''}: {'; '.join(problems)}.\n"
            f"Area check: smalls + 2 x mediums + 4 x large must equal {width * height}.")

    chosen = (rng.sample(by_class["small"], n_small)
              + rng.sample(by_class["medium"], mediums)
              + by_class["large"][:n_large])
    pool: Dict[str, List[Variant]] = {}
    for tid in chosen:
        pool[tid] = [v for s in sides.values() if s.tile_id == tid for v in build_variants(s)]
    return pool


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


def cell_label(x: int, y: int) -> str:
    """Spreadsheet-style position: columns A, B, C... rows 1, 2, 3... from the top-left."""
    return f"{chr(ord('A') + x)}{y + 1}"


def _schematic(side: SideInfo, cell_px: int) -> Image.Image:
    """Stand-in tile drawing for when the scans aren't available."""
    w, h = side.size
    img = Image.new("RGB", (w * cell_px, h * cell_px), (70, 66, 60))
    d = ImageDraw.Draw(img)
    t = max(4, cell_px // 10)
    d.rectangle([0, 0, img.width - 1, img.height - 1], outline=(25, 25, 25), width=t)
    for x, y, e in side.openings:
        x0, y0 = x * cell_px, y * cell_px
        a, b = int(cell_px * 0.3), int(cell_px * 0.7)
        box = {"N": (x0 + a, y0, x0 + b, y0 + t), "S": (x0 + a, y0 + cell_px - t, x0 + b, y0 + cell_px),
               "W": (x0, y0 + a, x0 + t, y0 + b), "E": (x0 + cell_px - t, y0 + a, x0 + cell_px, y0 + b)}[e]
        d.rectangle(box, fill=(200, 190, 160))
    d.text((t + 4, img.height - t - 4), side.side_id, fill=(230, 230, 230),
           font=_font(max(12, cell_px // 6)), anchor="lb")
    return img


def render_png(layout: Layout, sides: Dict[str, SideInfo], out_path: str, cell_px: int,
               tiles_dir: str, image_pattern: str, caption: str) -> bool:
    """Render the layout. Returns True if the tile scans were used."""
    margin = max(24, cell_px // 3)
    font_px = max(12, round(cell_px * 0.09))
    font = _font(font_px)
    cap_font = _font(max(12, round(cell_px * 0.1)))
    cap_h = round(cap_font.size * 1.8) if hasattr(cap_font, "size") else 24
    W, H = layout.width * cell_px, layout.height * cell_px
    img = Image.new("RGB", (W + 2 * margin, H + 2 * margin + cap_h), (18, 20, 22))
    d = ImageDraw.Draw(img)

    used_scans = True
    for p in layout.placements:
        side = sides[p.variant.side_id]
        path = os.path.join(tiles_dir, image_pattern.format(id=side.side_id))
        if os.path.exists(path):
            tile = Image.open(path).convert("RGB")
            if p.variant.rotation:
                tile = tile.rotate(-90 * p.variant.rotation, expand=True)
        else:
            used_scans = False
            tile = _schematic(side, cell_px)
            if p.variant.rotation:
                tile = tile.rotate(-90 * p.variant.rotation, expand=True)
        tile = tile.resize((p.variant.w * cell_px, p.variant.h * cell_px), Image.LANCZOS)
        img.paste(tile, (margin + p.x * cell_px, margin + p.y * cell_px))

    # Tile outlines, then path-order badges.
    order = {idx: n + 1 for n, idx in enumerate(layout.path)}
    for idx, p in enumerate(layout.placements):
        x0, y0 = margin + p.x * cell_px, margin + p.y * cell_px
        x1, y1 = x0 + p.variant.w * cell_px, y0 + p.variant.h * cell_px
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(10, 10, 10), width=max(2, cell_px // 100))
        label = f"{order[idx]} · {p.variant.side_id}"
        pad = font_px // 3
        tw = d.textlength(label, font=font)
        bx, by = x0 + pad * 2, y0 + pad * 2
        d.rounded_rectangle([bx, by, bx + tw + 2 * pad, by + font_px + 2 * pad],
                            radius=pad, fill=(15, 15, 15), outline=(230, 200, 90), width=2)
        d.text((bx + pad, by + pad + font_px / 2), label, fill=(240, 240, 240), font=font, anchor="lm")

    # Entrance / exit markers in the margin.
    for (x, y, e), text, colour in ((layout.entrance, "IN", (60, 170, 80)),
                                    (layout.exit, "OUT", (200, 60, 50))):
        if x is None:
            continue
        cx = margin + x * cell_px + cell_px // 2
        cy = margin + y * cell_px + cell_px // 2
        dx, dy = DIRS[e]
        cx += dx * (cell_px // 2 + margin // 2)
        cy += dy * (cell_px // 2 + margin // 2)
        r = margin // 2 - 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)
        d.text((cx, cy), text, fill=(255, 255, 255), font=_font(max(10, round(r * 0.8))), anchor="mm")

    d.text((margin, margin + H + margin // 2 + cap_h / 2), caption,
           fill=(210, 210, 210), font=cap_font, anchor="lm")
    img.save(out_path)
    return used_scans


def build_list(layout: Layout, sides: Dict[str, SideInfo], seed: int, mediums: int, boss: bool) -> str:
    ent, ext = layout.entrance, layout.exit
    lines = [
        f"GoW dungeon {seed}  ({layout.width}x{layout.height}, {mediums} medium(s)"
        f"{' + boss room' if boss else ''})",
        "",
        "Positions: columns A.. left to right, rows 1.. top to bottom (a tile's position is its top-left square).",
        "Rotation: quarter turns clockwise from the printed orientation (tile ID text upright).",
        "",
        f"Entrance: {EDGE_NAMES[ent[2]]} edge of {cell_label(ent[0], ent[1])}",
        f"Exit:     {EDGE_NAMES[ext[2]]} edge of {cell_label(ext[0], ext[1])}",
        "",
        f"{'#':>2}  {'Tile':<4}  {'Shape':<5}  {'At':<3}  {'Size':<4}  {'Rotate':<6}  {'Spawn':>5}  {'Loot':>4}  Room",
    ]
    spawns = loot = 0
    for n, idx in enumerate(layout.path, 1):
        p = layout.placements[idx]
        s = sides[p.variant.side_id]
        spawns += s.spawns
        loot += s.loot
        room = s.room_name or "-"
        if s.room_reward:
            room += f": {s.room_reward}"
        lines.append(
            f"{n:>2}  {s.side_id:<4}  {s.shape:<5}  {cell_label(p.x, p.y):<3}  "
            f"{p.variant.w}x{p.variant.h:<2}  {str(90 * p.variant.rotation) + '°':<6}  "
            f"{s.spawns:>5}  {s.loot:>4}  {room}")
    lines += ["", f"Totals: {len(layout.path)} rooms, {spawns} spawn points, {loot} loot markers"]
    used = {p.variant.tile_id for p in layout.placements}
    unused = sorted({s.tile_id for s in sides.values()} - used, key=int)
    lines.append(f"Unused tiles: {', '.join(unused) if unused else 'none'}")
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────

def generate(seed: int, sides: Dict[str, SideInfo], width: int, height: int,
             mediums: int, boss: bool) -> Optional[Layout]:
    """Deterministic for a given seed and options."""
    rng = random.Random(seed)
    for _ in range(5):  # a fresh tile selection if a pool proves stubborn
        pool = choose_pool(sides, width, height, mediums, boss, rng)
        layout = Solver(width, height, pool, rng).solve()
        if layout:
            return layout
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate gap-free dungeons from Gears of War board game tiles.")
    ap.add_argument("--width",     type=int, default=5,   help="Dungeon width in small-tile units (default: 5).")
    ap.add_argument("--height",    type=int, default=4,   help="Dungeon height in small-tile units (default: 4).")
    ap.add_argument("--mediums",   type=int, default=2,   help="Number of medium tiles to use (default: 2).")
    ap.add_argument("--no-boss",   action="store_true",   help="Leave out the large tile (boss room).")
    ap.add_argument("--n",         type=int, default=3,   help="Number of dungeons to generate (default: 3).")
    ap.add_argument("--seed",      type=int, default=None, help="Generate one specific dungeon by seed.")
    ap.add_argument("--cell-px",   type=int, default=300, help="Pixels per small tile in the PNG (default: 300).")
    ap.add_argument("--tiles-dir", default=DEFAULT_TILES_DIR, help="Folder with the tile scans (default: tiles/).")
    ap.add_argument("--data",      default=DEFAULT_DATA,  help="Tile data file (default: tiles.json).")
    ap.add_argument("--out-dir",   default=DEFAULT_OUT_DIR, help="Where to write the PNG and build list (default: output/).")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        image_pattern = json.load(f).get("image_pattern", "Tile{id}.png")
    sides = load_sides(args.data)
    boss = not args.no_boss
    os.makedirs(args.out_dir, exist_ok=True)
    seeds = [args.seed] if args.seed is not None else [random.randint(0, 2**32 - 1) for _ in range(args.n)]
    warned = False

    for seed in seeds:
        layout = generate(seed, sides, args.width, args.height, args.mediums, boss)
        if layout is None:
            print(f"Seed {seed}: no layout found, skipping.")
            continue
        spawns = sum(sides[p.variant.side_id].spawns for p in layout.placements)
        loot = sum(sides[p.variant.side_id].loot for p in layout.placements)
        caption = (f"Seed {seed}  ·  {len(layout.placements)} rooms  ·  "
                   f"{spawns} spawns  ·  {loot} loot")
        base = os.path.join(args.out_dir, f"gow_dungeon_{seed}")
        scans = render_png(layout, sides, base + ".png", args.cell_px, args.tiles_dir, image_pattern, caption)
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(build_list(layout, sides, seed, args.mediums, boss))
        print(f"Saved: {base}.png / .txt")
        if not scans and not warned:
            print(f"Note: tile scans not found in {args.tiles_dir}; drew schematic tiles instead.")
            warned = True


if __name__ == "__main__":
    main()
