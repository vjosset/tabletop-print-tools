"""
Random dungeon from modular 3x3 tiles (default: 5x4 tile grid → 15x12 cells).

Tiles:
- +: cross (4 ports)
- T: 3 ports
- L: 2 ports (corner)
- I: 2 ports (straight)
- O: open (all floors)

Each tile is chosen randomly, rotated randomly, and placed.

Pipeline:
  1. build_floor_grid()  — generate map (tile selection + placement)
  2. _validate_and_fix() — island repair + quality checks; retry on failure
  3. place_items_*()     — item placement strategy
  4. render_png()        — render to PNG

Output: PNG images.
"""

from __future__ import annotations
import argparse
import os
import random
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, Set
from PIL import Image, ImageDraw, ImageOps


@dataclass
class Marker:
    x: int
    y: int
    color: Tuple[int, int, int]
    style: str = "dot"  # "dot" | "question"


# ─────────────────────────────────────────────
# Tile definitions (3x3)
# ─────────────────────────────────────────────
# Coordinate system: (x, y) with x,y in 0..2 inside each tile.
# Floor cells are True; walls are False.

def empty_3x3(fill: bool = False) -> List[List[bool]]:
    return [[fill for _ in range(3)] for _ in range(3)]

def rotate_3x3_cw(tile: List[List[bool]]) -> List[List[bool]]:
    return [[tile[2 - x][y] for x in range(3)] for y in range(3)]

def rotate_n(tile: List[List[bool]], n: int) -> List[List[bool]]:
    out = tile
    for _ in range(n % 4):
        out = rotate_3x3_cw(out)
    return out

def has_edge_floors(
    tile: List[List[bool]],
    on_left: bool, on_right: bool, on_top: bool, on_bottom: bool,
) -> bool:
    if on_left   and any(tile[y][0] for y in range(3)): return True
    if on_right  and any(tile[y][2] for y in range(3)): return True
    if on_top    and any(tile[0][x] for x in range(3)): return True
    if on_bottom and any(tile[2][x] for x in range(3)): return True
    return False

def make_plus() -> List[List[bool]]:
    t = empty_3x3(False)
    for x, y in [(1, 1), (1, 0), (2, 1), (1, 2), (0, 1)]:
        t[y][x] = True
    return t

def make_t(missing_dir: str) -> List[List[bool]]:
    """Start from + and remove one port. missing_dir in {"N","E","S","W"}"""
    t = make_plus()
    x, y = {"N": (1, 0), "E": (2, 1), "S": (1, 2), "W": (0, 1)}[missing_dir]
    t[y][x] = False
    return t

def make_l(corner: str) -> List[List[bool]]:
    """Center + two adjacent ports. corner: "NE","ES","SW","WN" """
    t = empty_3x3(False)
    t[1][1] = True
    for x, y in {"NE": [(1,0),(2,1)], "ES": [(2,1),(1,2)], "SW": [(1,2),(0,1)], "WN": [(0,1),(1,0)]}[corner]:
        t[y][x] = True
    return t

def make_i(axis: str) -> List[List[bool]]:
    """Center + two opposite ports. axis: "NS" or "EW" """
    t = empty_3x3(False)
    t[1][1] = True
    if axis == "NS":   t[0][1] = t[2][1] = True
    elif axis == "EW": t[1][0] = t[1][2] = True
    else: raise ValueError("axis must be 'NS' or 'EW'")
    return t

def make_o() -> List[List[bool]]:
    return empty_3x3(True)


# Canonical (unrotated) tile variants — rotated randomly at placement time.
BASE_TILES: Dict[str, List[List[bool]]] = {
    "+": make_plus(),
    "T": make_t("W"),    # missing W (N/E/S open), then rotate
    "L": make_l("NE"),   # NE corner, then rotate
    "I": make_i("NS"),   # NS axis, then rotate
    "O": make_o(),
}

TILE_RULES: Dict[str, Dict[str, bool]] = {
    "+": {"allow_edge": False, "allow_corner": False},
    "T": {"allow_edge": False, "allow_corner": False},
    "L": {"allow_edge": True,  "allow_corner": True},
    "I": {"allow_edge": True,  "allow_corner": False},
    "O": {"allow_edge": True,  "allow_corner": True},
}


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

@dataclass
class DungeonConfig:
    tile_grid_w: int = 5
    tile_grid_h: int = 4
    tile_size: int = 3            # each tile is 3x3 cells
    weights: Dict[str, int] = None
    seed: Optional[int] = None
    enforce_connected: bool = False   # wall-off unreachable floors
    big_room_count: int = 1           # 0 or 1 big rooms
    big_room_tiles: int = 2           # size in tiles (2 → 6x6 cells)
    min_floor: int = 0                # minimum total floor cells required
    max_rerolls: int = 50             # max whole-map regeneration attempts
    island_rerolls: int = 3           # max passes to reroll disconnected tiles

    def __post_init__(self):
        if self.weights is None:
            self.weights = {"+": 4, "I": 2, "L": 1, "O": 4, "T": 5}


# ─────────────────────────────────────────────
# Generation helpers
# ─────────────────────────────────────────────

def neighbors4(x: int, y: int, W: int, H: int):
    if x > 0:     yield (x - 1, y)
    if x < W - 1: yield (x + 1, y)
    if y > 0:     yield (x, y - 1)
    if y < H - 1: yield (x, y + 1)

def pick_tile_type(rng: random.Random, weights: Dict[str, int]) -> str:
    items = list(weights.items())
    return rng.choices([k for k, _ in items], weights=[v for _, v in items], k=1)[0]

def is_big_room_tile(tx: int, ty: int, big_room_origin: Optional[Tuple[int, int, int]]) -> bool:
    if not big_room_origin:
        return False
    bx, by, bs = big_room_origin
    return bx <= tx < bx + bs and by <= ty < by + bs

def can_place_o(
    tx: int, ty: int,
    cfg: DungeonConfig,
    tile_types: List[List[Optional[str]]],
    big_room_origin: Optional[Tuple[int, int, int]],
) -> bool:
    """O tiles may not be adjacent to any other O tile (except within the big room block)."""
    if is_big_room_tile(tx, ty, big_room_origin):
        return True
    for nx, ny in neighbors4(tx, ty, cfg.tile_grid_w, cfg.tile_grid_h):
        if tile_types[ny][nx] == "O":
            return False
    return True

def choose_tile_type_for(
    tx: int, ty: int,
    cfg: DungeonConfig,
    tile_types: List[List[Optional[str]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    rng: random.Random,
) -> str:
    on_left   = tx == 0
    on_right  = tx == cfg.tile_grid_w - 1
    on_top    = ty == 0
    on_bottom = ty == cfg.tile_grid_h - 1
    on_edge   = on_left or on_right or on_top or on_bottom
    on_corner = (on_left or on_right) and (on_top or on_bottom)

    for _ in range(50):
        candidate = pick_tile_type(rng, cfg.weights)
        rules = TILE_RULES.get(candidate, {})
        if on_corner and not rules.get("allow_corner", True): continue
        if on_edge   and not rules.get("allow_edge",   True): continue
        if candidate == "O" and not can_place_o(tx, ty, cfg, tile_types, big_room_origin): continue
        return candidate

    # Fallback: first non-O tile satisfying corner/edge rules.
    for key in cfg.weights:
        if key == "O": continue
        rules = TILE_RULES.get(key, {})
        if on_corner and not rules.get("allow_corner", True): continue
        if on_edge   and not rules.get("allow_edge",   True): continue
        return key

    return "L"  # last resort — always valid anywhere

def place_tile(
    ttype: str, tx: int, ty: int,
    cfg: DungeonConfig,
    floor: List[List[bool]],
    tile_rots: List[List[Optional[int]]],
    rng: random.Random,
) -> None:
    """Rotate ttype and blit it into floor at tile position (tx, ty)."""
    tile = BASE_TILES[ttype]
    rot = rng.randint(0, 3)
    tile_r = rotate_n(tile, rot)

    if ttype != "O":
        on_left   = tx == 0
        on_right  = tx == cfg.tile_grid_w - 1
        on_top    = ty == 0
        on_bottom = ty == cfg.tile_grid_h - 1
        if on_left or on_right or on_top or on_bottom:
            for _ in range(4):
                if not has_edge_floors(tile_r, on_left, on_right, on_top, on_bottom):
                    break
                tile_r = rotate_3x3_cw(tile_r)
                rot += 1

    tile_rots[ty][tx] = rot % 4
    ox, oy = tx * cfg.tile_size, ty * cfg.tile_size
    for y in range(cfg.tile_size):
        for x in range(cfg.tile_size):
            floor[oy + y][ox + x] = tile_r[y][x]


def _generate_attempt(
    cfg: DungeonConfig,
    rng: random.Random,
) -> Tuple[
    List[List[bool]],
    List[List[Optional[str]]],
    List[List[Optional[int]]],
    Optional[Tuple[int, int, int]],
]:
    """One map-generation attempt: pick tile types and blit them into a floor grid.

    Does not validate or apply connectivity rules — that is handled separately.
    Returns (floor, tile_types, tile_rots, big_room_origin).
    """
    W = cfg.tile_grid_w * cfg.tile_size
    H = cfg.tile_grid_h * cfg.tile_size
    floor:      List[List[bool]]         = [[False] * W for _ in range(H)]
    tile_types: List[List[Optional[str]]] = [[None] * cfg.tile_grid_w for _ in range(cfg.tile_grid_h)]
    tile_rots:  List[List[Optional[int]]] = [[None] * cfg.tile_grid_w for _ in range(cfg.tile_grid_h)]

    big_room_origin: Optional[Tuple[int, int, int]] = None
    if cfg.big_room_count > 0:
        room_tiles = max(1, min(cfg.big_room_tiles, cfg.tile_grid_w, cfg.tile_grid_h))
        tx0 = rng.randint(0, cfg.tile_grid_w - room_tiles)
        ty0 = rng.randint(0, cfg.tile_grid_h - room_tiles)
        big_room_origin = (tx0, ty0, room_tiles)
        for ty in range(ty0, ty0 + room_tiles):
            for tx in range(tx0, tx0 + room_tiles):
                tile_types[ty][tx] = "O"

    for ty in range(cfg.tile_grid_h):
        for tx in range(cfg.tile_grid_w):
            if tile_types[ty][tx] is None:
                tile_types[ty][tx] = choose_tile_type_for(tx, ty, cfg, tile_types, big_room_origin, rng)
            place_tile(tile_types[ty][tx], tx, ty, cfg, floor, tile_rots, rng)

    return floor, tile_types, tile_rots, big_room_origin


# ─────────────────────────────────────────────
# Validation and connectivity
# ─────────────────────────────────────────────

def compute_reachable(floor: List[List[bool]]) -> Set[Tuple[int, int]]:
    H = len(floor)
    W = len(floor[0]) if H else 0
    start = next(((x, y) for y in range(H) for x in range(W) if floor[y][x]), None)
    if not start:
        return set()
    reachable: Set[Tuple[int, int]] = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for nx, ny in neighbors4(x, y, W, H):
            if floor[ny][nx] and (nx, ny) not in reachable:
                reachable.add((nx, ny))
                stack.append((nx, ny))
    return reachable

def wall_off_unreachable(floor: List[List[bool]]) -> List[List[bool]]:
    """Keep only the largest connected floor component; wall off everything else."""
    H = len(floor)
    W = len(floor[0]) if H else 0
    visited: Set[Tuple[int, int]] = set()
    largest: Set[Tuple[int, int]] = set()
    for y in range(H):
        for x in range(W):
            if not floor[y][x] or (x, y) in visited:
                continue
            comp: Set[Tuple[int, int]] = set()
            stack = [(x, y)]
            visited.add((x, y))
            comp.add((x, y))
            while stack:
                cx, cy = stack.pop()
                for nx, ny in neighbors4(cx, cy, W, H):
                    if floor[ny][nx] and (nx, ny) not in visited:
                        visited.add((nx, ny))
                        comp.add((nx, ny))
                        stack.append((nx, ny))
            if len(comp) > len(largest):
                largest = comp
    if not largest:
        return floor
    return [[(x, y) in largest for x in range(W)] for y in range(H)]

def count_floor(floor: List[List[bool]]) -> int:
    return sum(v for row in floor for v in row)

def has_blank_tile(floor: List[List[bool]], cfg: DungeonConfig) -> bool:
    """Return True if any tile-aligned 3x3 block is entirely walls."""
    for ty in range(cfg.tile_grid_h):
        for tx in range(cfg.tile_grid_w):
            ox, oy = tx * cfg.tile_size, ty * cfg.tile_size
            if not any(
                floor[oy + dy][ox + dx]
                for dy in range(cfg.tile_size)
                for dx in range(cfg.tile_size)
            ):
                return True
    return False

def _i_tile_axis(floor: List[List[bool]], tx: int, ty: int, tile_size: int) -> str:
    """Return 'EW' or 'NS' for an I-tile based on its floor pattern."""
    ox, oy = tx * tile_size, ty * tile_size
    return "EW" if all(floor[oy + 1][ox + dx] for dx in range(tile_size)) else "NS"

def has_chained_i_tiles(
    floor: List[List[bool]],
    tile_types: List[List[Optional[str]]],
    cfg: DungeonConfig,
) -> bool:
    """Return True if two orthogonally adjacent I-tiles share the same axis.

    Same-axis adjacent I-tiles create a long 1-wide corridor (6 cells).
    Different-axis I-tiles don't even connect, so they're fine.
    """
    for ty in range(cfg.tile_grid_h):
        for tx in range(cfg.tile_grid_w):
            if tile_types[ty][tx] != "I":
                continue
            axis = _i_tile_axis(floor, tx, ty, cfg.tile_size)
            for nx, ny in neighbors4(tx, ty, cfg.tile_grid_w, cfg.tile_grid_h):
                if tile_types[ny][nx] == "I" and _i_tile_axis(floor, nx, ny, cfg.tile_size) == axis:
                    return True
    return False

def tiles_share_connection(
    floor: List[List[bool]],
    tx1: int, ty1: int, tx2: int, ty2: int,
    tile_size: int,
) -> bool:
    """Return True if two orthogonally adjacent tiles share at least one floor crossing."""
    ox1, oy1 = tx1 * tile_size, ty1 * tile_size
    ox2, oy2 = tx2 * tile_size, ty2 * tile_size
    if tx2 == tx1 + 1:
        return any(floor[oy1 + r][ox1 + tile_size - 1] and floor[oy2 + r][ox2] for r in range(tile_size))
    if tx2 == tx1 - 1:
        return any(floor[oy1 + r][ox1] and floor[oy2 + r][ox2 + tile_size - 1] for r in range(tile_size))
    if ty2 == ty1 + 1:
        return any(floor[oy1 + tile_size - 1][ox1 + c] and floor[oy2][ox2 + c] for c in range(tile_size))
    if ty2 == ty1 - 1:
        return any(floor[oy1][ox1 + c] and floor[oy2 + tile_size - 1][ox2 + c] for c in range(tile_size))
    return False


def _repair_islands(
    floor: List[List[bool]],
    tile_types: List[List[Optional[str]]],
    tile_rots: List[List[Optional[int]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    cfg: DungeonConfig,
    rng: random.Random,
) -> None:
    """First-pass fixup: reroll tiles whose floors are unreachable from the main component.

    Runs up to cfg.island_rerolls passes. Mutates floor, tile_types, tile_rots in place.
    After this, wall_off_unreachable is called in _validate_and_fix as a final failsafe.
    """
    for _ in range(max(0, cfg.island_rerolls)):
        reachable = compute_reachable(floor)
        rerolled = False
        for ty in range(cfg.tile_grid_h):
            for tx in range(cfg.tile_grid_w):
                if is_big_room_tile(tx, ty, big_room_origin):
                    continue
                if tile_types[ty][tx] == "O":
                    continue
                ox, oy = tx * cfg.tile_size, ty * cfg.tile_size
                has_floor = any(
                    floor[oy + dy][ox + dx]
                    for dy in range(cfg.tile_size)
                    for dx in range(cfg.tile_size)
                )
                has_reachable = has_floor and any(
                    (ox + dx, oy + dy) in reachable
                    for dy in range(cfg.tile_size)
                    for dx in range(cfg.tile_size)
                    if floor[oy + dy][ox + dx]
                )
                if has_floor and not has_reachable:
                    ttype = choose_tile_type_for(tx, ty, cfg, tile_types, big_room_origin, rng)
                    tile_types[ty][tx] = ttype
                    place_tile(ttype, tx, ty, cfg, floor, tile_rots, rng)
                    rerolled = True
        if not rerolled:
            break


def _validate_and_fix(
    floor: List[List[bool]],
    tile_types: List[List[Optional[str]]],
    tile_rots: List[List[Optional[int]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    cfg: DungeonConfig,
    rng: random.Random,
) -> Tuple[List[List[bool]], bool]:
    """Apply connectivity repair and quality checks to a generated map.

    Step 1 — Island repair: reroll disconnected tiles (best-effort fixup).
    Step 2 — Wall off unreachable floors (failsafe for anything repair missed).
    Step 3 — Quality checks: reject maps that still don't meet the rules.

    Returns (floor, is_valid). floor may be a new object after wall_off_unreachable.
    """
    if cfg.enforce_connected:
        _repair_islands(floor, tile_types, tile_rots, big_room_origin, cfg, rng)
        floor = wall_off_unreachable(floor)

    # Reject maps with no floor cells at all (degenerate output).
    if not any(any(row) for row in floor):
        return floor, False

    # Reject maps below the minimum floor cell count.
    if cfg.min_floor > 0 and count_floor(floor) < cfg.min_floor:
        return floor, False

    # Reject maps where any tile-aligned block is entirely walls.
    # Blank tiles waste grid space and make the map feel sparse.
    if has_blank_tile(floor, cfg):
        return floor, False

    # Reject maps with same-axis adjacent I-tiles (creates overly long corridors).
    if has_chained_i_tiles(floor, tile_types, cfg):
        return floor, False

    return floor, True


# ─────────────────────────────────────────────
# Map generation (public entry point)
# ─────────────────────────────────────────────

def count_tile_types(tile_types: List[List[Optional[str]]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in tile_types:
        for t in row:
            if t is not None:
                counts[t] = counts.get(t, 0) + 1
    return counts

def build_floor_grid(
    cfg: DungeonConfig,
) -> Tuple[
    List[List[bool]],
    List[List[Optional[str]]],
    List[List[Optional[int]]],
    Optional[Tuple[int, int, int]],
    Dict[str, int],
    random.Random,
]:
    """Generate a validated dungeon map, retrying up to cfg.max_rerolls times.

    The rng is returned so downstream placement can continue the same random
    sequence — this lets the seed alone reproduce the full output.
    """
    rng = random.Random(cfg.seed)
    last = None

    for _ in range(max(1, cfg.max_rerolls + 1)):
        floor, tile_types, tile_rots, big_room_origin = _generate_attempt(cfg, rng)
        floor, valid = _validate_and_fix(floor, tile_types, tile_rots, big_room_origin, cfg, rng)
        counts = count_tile_types(tile_types)
        last = (floor, tile_types, tile_rots, big_room_origin, counts)
        if valid:
            break

    return *last, rng


# ─────────────────────────────────────────────
# Placement utilities
# ─────────────────────────────────────────────

def gather_floor_cells(
    floor: List[List[bool]],
    exclude: Set[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    H = len(floor)
    W = len(floor[0]) if H else 0
    return [(x, y) for y in range(H) for x in range(W) if floor[y][x] and (x, y) not in exclude]

def find_leaf_cells(floor: List[List[bool]]) -> List[Tuple[int, int]]:
    """Return all floor cells with exactly one floor neighbour (dead-end corridors)."""
    H = len(floor)
    W = len(floor[0]) if H else 0
    return [
        (x, y)
        for y in range(H) for x in range(W)
        if floor[y][x]
        and sum(1 for nx, ny in neighbors4(x, y, W, H) if floor[ny][nx]) == 1
    ]

def find_leaf_tiles(
    floor: List[List[bool]],
    tile_grid_w: int, tile_grid_h: int, tile_size: int,
) -> Set[Tuple[int, int]]:
    """Return tile coords with exactly one connection to an adjacent tile.

    Catches dead-end rooms (e.g. O tiles with one exit) that have no degree-1
    cells and would be missed by find_leaf_cells alone.
    """
    leaf_tiles: Set[Tuple[int, int]] = set()
    for ty in range(tile_grid_h):
        for tx in range(tile_grid_w):
            ox, oy = tx * tile_size, ty * tile_size
            if not any(floor[oy + dy][ox + dx] for dy in range(tile_size) for dx in range(tile_size)):
                continue
            degree = sum(
                1 for nx, ny in neighbors4(tx, ty, tile_grid_w, tile_grid_h)
                if tiles_share_connection(floor, tx, ty, nx, ny, tile_size)
            )
            if degree == 1:
                leaf_tiles.add((tx, ty))
    return leaf_tiles

def pick_farthest_points(
    rng: random.Random,
    primary: List[Tuple[int, int]],
    fallback: List[Tuple[int, int]],
    count: int,
    seeds: Optional[List[Tuple[int, int]]] = None,
) -> List[Tuple[int, int]]:
    """Pick `count` points spread as far apart as possible from each other and from seeds."""
    candidates = list(primary) or list(fallback)
    anchors: List[Tuple[int, int]] = list(seeds) if seeds else []
    picks: List[Tuple[int, int]] = []

    while candidates and len(picks) < count:
        pick = (
            rng.choice(candidates) if not anchors
            else max(candidates, key=lambda c: min(abs(c[0]-ax) + abs(c[1]-ay) for ax, ay in anchors))
        )
        picks.append(pick)
        anchors.append(pick)
        candidates.remove(pick)

    if len(picks) < count:
        extras = [c for c in fallback if c not in picks]
        while extras and len(picks) < count:
            pick = (
                rng.choice(extras) if not anchors
                else max(extras, key=lambda c: min(abs(c[0]-ax) + abs(c[1]-ay) for ax, ay in anchors))
            )
            picks.append(pick)
            anchors.append(pick)
            extras.remove(pick)

    return picks

def pick_player_tile(
    tile_types: List[List[Optional[str]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    cfg: DungeonConfig,
    rng: random.Random,
    floor: List[List[bool]],
) -> Optional[Tuple[int, int]]:
    candidates = [
        (tx * cfg.tile_size + 1, ty * cfg.tile_size + 1)
        for ty in range(cfg.tile_grid_h)
        for tx in range(cfg.tile_grid_w)
        if tile_types[ty][tx] == "O"
        and not is_big_room_tile(tx, ty, big_room_origin)
        and floor[ty * cfg.tile_size + 1][tx * cfg.tile_size + 1]
    ]
    return rng.choice(candidates) if candidates else None

def pick_console_tile(
    tile_types: List[List[Optional[str]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    cfg: DungeonConfig,
    rng: random.Random,
    floor: List[List[bool]],
    player: Optional[Tuple[int, int]],
) -> Optional[Tuple[int, int]]:
    candidates = [
        (tx * cfg.tile_size + 1, ty * cfg.tile_size + 1)
        for ty in range(cfg.tile_grid_h)
        for tx in range(cfg.tile_grid_w)
        if tile_types[ty][tx] == "O"
        and not is_big_room_tile(tx, ty, big_room_origin)
        and floor[ty * cfg.tile_size + 1][tx * cfg.tile_size + 1]
    ]
    if not candidates:
        return None
    if player is None:
        return rng.choice(candidates)
    px, py = player
    return max(candidates, key=lambda c: (c[0] - px) ** 2 + (c[1] - py) ** 2)

def pick_spawn_tiles(
    tile_types: List[List[Optional[str]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    cfg: DungeonConfig,
    rng: random.Random,
    floor: List[List[bool]],
    count: int,
    exclude: Optional[Set[Tuple[int, int]]] = None,
    seeds: Optional[List[Tuple[int, int]]] = None,
) -> List[Tuple[int, int]]:
    o_candidates: List[Tuple[int, int]] = []
    all_candidates: List[Tuple[int, int]] = []
    for ty in range(cfg.tile_grid_h):
        for tx in range(cfg.tile_grid_w):
            if tile_types[ty][tx] is None:
                continue
            if is_big_room_tile(tx, ty, big_room_origin):
                continue
            cx, cy = tx * cfg.tile_size + 1, ty * cfg.tile_size + 1
            if floor[cy][cx]:
                all_candidates.append((cx, cy))
                if tile_types[ty][tx] == "O":
                    o_candidates.append((cx, cy))

    if exclude:
        o_candidates   = [c for c in o_candidates   if c not in exclude]
        all_candidates = [c for c in all_candidates if c not in exclude]

    if not all_candidates:
        return []

    # Prefer O tiles (open rooms) for spawn locations — better combat spaces.
    # Fall back to any tile center if not enough O tiles are available.
    return pick_farthest_points(rng, o_candidates, all_candidates, count, seeds=seeds)


# ─────────────────────────────────────────────
# Placement strategies
# ─────────────────────────────────────────────

def place_items_standard(
    floor: List[List[bool]],
    tile_types: List[List[Optional[str]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    cfg: DungeonConfig,
    rng: random.Random,
) -> Tuple[List[Tuple[int, int]], Optional[Tuple[int, int]], Optional[Tuple[int, int]], List[Marker]]:
    player  = pick_player_tile(tile_types, big_room_origin, cfg, rng, floor)
    console = pick_console_tile(tile_types, big_room_origin, cfg, rng, floor, player)
    spawns  = pick_spawn_tiles(
        tile_types, big_room_origin, cfg, rng, floor,
        count=3,
        exclude={p for p in (player, console) if p is not None},
        seeds=[player] if player is not None else None,
    )

    def cell_to_tile(cx: int, cy: int) -> Tuple[int, int]:
        return (cx // cfg.tile_size, cy // cfg.tile_size)

    occupied_tiles: Set[Tuple[int, int]] = {
        cell_to_tile(*pt) for pt in [player, console] + spawns if pt is not None
    }

    leaves    = [p for p in find_leaf_cells(floor) if cell_to_tile(*p) not in occupied_tiles]
    all_floor = [p for p in gather_floor_cells(floor, set()) if cell_to_tile(*p) not in occupied_tiles]
    leaf_tile_set = find_leaf_tiles(floor, cfg.tile_grid_w, cfg.tile_grid_h, cfg.tile_size)

    # Pick orange markers one at a time using a three-tier priority:
    #   tier 1 — leaf cells (degree-1 floor cells) on free tiles
    #   tier 2 — any cell on a free leaf tile (dead-end room, any cell)
    #   tier 3 — any free floor cell (last resort)
    # Seeded from player + spawns so markers fill the least-covered areas.
    player_seed = ([player] if player else []) + spawns
    leaf_coords: List[Tuple[int, int]] = []
    for _ in range(3):
        free = lambda p: cell_to_tile(*p) not in occupied_tiles
        tier1 = [p for p in leaves    if free(p)]
        tier2 = [p for p in all_floor if free(p) and cell_to_tile(*p) in leaf_tile_set]
        tier3 = [p for p in all_floor if free(p)]
        if tier1:   primary, fallback = tier1, tier2 if tier2 else tier3
        elif tier2: primary, fallback = tier2, tier3
        else:       primary, fallback = tier3, tier3
        picks = pick_farthest_points(rng, primary, fallback, count=1, seeds=player_seed + leaf_coords)
        if picks:
            pt = picks[0]
            leaf_coords.append(pt)
            occupied_tiles.add(cell_to_tile(*pt))

    markers = [Marker(x, y, (220, 140, 40), "dot") for x, y in leaf_coords]
    return spawns, player, console, markers


def place_items_discovery(
    floor: List[List[bool]],
    tile_types: List[List[Optional[str]]],
    big_room_origin: Optional[Tuple[int, int, int]],
    cfg: DungeonConfig,
    rng: random.Random,
) -> Tuple[List[Tuple[int, int]], Optional[Tuple[int, int]], Optional[Tuple[int, int]], List[Marker]]:
    # Place player on the O tile most connected to its neighbours; break ties randomly.
    bx = by = bs = None
    if big_room_origin:
        bx, by, bs = big_room_origin

    best_cells: List[Tuple[int, int]] = []
    best_degree = -1
    for ty in range(cfg.tile_grid_h):
        for tx in range(cfg.tile_grid_w):
            if tile_types[ty][tx] != "O":
                continue
            if big_room_origin and bx <= tx < bx + bs and by <= ty < by + bs:
                continue
            cx, cy = tx * cfg.tile_size + 1, ty * cfg.tile_size + 1
            if not floor[cy][cx]:
                continue
            degree = sum(
                1 for nx, ny in neighbors4(tx, ty, cfg.tile_grid_w, cfg.tile_grid_h)
                if tiles_share_connection(floor, tx, ty, nx, ny, cfg.tile_size)
            )
            if degree > best_degree:
                best_degree, best_cells = degree, [(cx, cy)]
            elif degree == best_degree:
                best_cells.append((cx, cy))

    player = rng.choice(best_cells) if best_cells else None
    parity = ((player[0] // cfg.tile_size) + (player[1] // cfg.tile_size)) % 2 if player else 0

    H = len(floor)
    W = len(floor[0]) if H else 0
    markers: List[Marker] = []
    for ty in range(cfg.tile_grid_h):
        for tx in range(cfg.tile_grid_w):
            if (tx + ty) % 2 != parity:
                continue
            ox, oy = tx * cfg.tile_size, ty * cfg.tile_size
            cx, cy = ox + 1, oy + 1
            if tile_types[ty][tx] == "O":
                pos = (cx, cy)
            else:
                # Use edge cells that have no floor crossing outside the tile boundary.
                edge = [
                    (ox + dx, oy + dy)
                    for dy in range(cfg.tile_size)
                    for dx in range(cfg.tile_size)
                    if (dx == 0 or dx == cfg.tile_size - 1 or dy == 0 or dy == cfg.tile_size - 1)
                    and floor[oy + dy][ox + dx]
                    and all(
                        not floor[ny][nx]
                        or (ox <= nx < ox + cfg.tile_size and oy <= ny < oy + cfg.tile_size)
                        for nx, ny in neighbors4(ox + dx, oy + dy, W, H)
                    )
                ]
                pos = rng.choice(edge) if edge else (cx, cy)
            if pos != player:
                markers.append(Marker(pos[0], pos[1], (220, 140, 40), "question"))

    return [], player, None, markers


PLACEMENT_STRATEGIES = {
    "standard":  place_items_standard,
    "discovery": place_items_discovery,
    "none":      lambda *_: ([], None, None, []),
}


# ─────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────

def _discover_tile_variants(tiles_dir: str) -> Dict[str, List[str]]:
    """Scan tiles_dir and return a dict of ttype -> sorted list of image file paths.

    Matches files like: O.png, O.jpg, O_01.png, O_alt.jpg (case-insensitive).
    Supports PNG and JPG/JPEG. Returns an empty list for any type with no files found.
    """
    import re
    variants: Dict[str, List[str]] = {t: [] for t in BASE_TILES}
    try:
        entries = os.listdir(tiles_dir)
    except OSError:
        return variants
    pattern = re.compile(r'^(.+?)(_\w+)?\.(png|jpg|jpeg)$', re.IGNORECASE)
    for entry in sorted(entries):
        m = pattern.match(entry)
        if not m:
            continue
        ttype = m.group(1).upper()
        if ttype in variants:
            variants[ttype].append(os.path.join(tiles_dir, entry))
    return variants


def render_png(
    floor: List[List[bool]],
    cell_px: int = 128,
    margin_px: int = 16,
    draw_grid: bool = True,
    spawns: Optional[List[Tuple[int, int]]] = None,
    player: Optional[Tuple[int, int]] = None,
    console: Optional[Tuple[int, int]] = None,
    tile_counts: Optional[Dict[str, int]] = None,
    markers: Optional[List[Marker]] = None,
    out_path: str = "dungeon.png",
    tile_grid_every: int = 3,
    theme: str = "clean",
    use_tile_images: bool = False,
    tiles_dir: str = "tiles",
    tile_types: Optional[List[List[Optional[str]]]] = None,
    tile_rots: Optional[List[List[Optional[int]]]] = None,
    overlay_shapes: bool = False,
    rng: Optional[random.Random] = None,
) -> None:
    H = len(floor)
    W = len(floor[0]) if H else 0
    img_w  = margin_px * 2 + W * cell_px
    text_pad = 18 if tile_counts else 0
    img_h  = margin_px * 2 + H * cell_px + text_pad

    def lerp(a: int, b: int, t: float) -> int:
        return int(a + (b - a) * t)

    # Background
    if theme == "scan":
        bg_top, bg_bottom = (12, 18, 24), (8, 12, 16)
        img = Image.new("RGB", (img_w, img_h), bg_top)
        d = ImageDraw.Draw(img)
        for y in range(img_h):
            t = y / max(1, img_h - 1)
            d.line([0, y, img_w, y], fill=(lerp(bg_top[0], bg_bottom[0], t),
                                           lerp(bg_top[1], bg_bottom[1], t),
                                           lerp(bg_top[2], bg_bottom[2], t)))
    else:
        img = Image.new("RGB", (img_w, img_h), (30, 30, 30))
        d = ImageDraw.Draw(img)

    # Theme colors
    if theme == "scan":
        WALL      = (5, 8, 10)
        FLOOR     = (205, 235, 215)
        GRID      = (35, 80, 45)
        GRID_BOLD = (60, 120, 70)
        GLOW      = (90, 200, 110)
    else:
        WALL      = (0, 0, 0)
        FLOOR     = (245, 245, 245)
        GRID      = (70, 70, 70)
        GRID_BOLD = GRID
        GLOW      = None

    # Draw cells — tile images or solid shapes
    if use_tile_images and tile_types is not None and tile_rots is not None:
        tile_cells = tile_grid_every if tile_grid_every > 0 else 3
        tile_px = tile_cells * cell_px
        _rot_transpose = {
            0: None,
            1: Image.Transpose.ROTATE_270,
            2: Image.Transpose.ROTATE_180,
            3: Image.Transpose.ROTATE_90,
        }
        _rng = rng or random.Random()

        # Discover all variants per tile type (e.g. O.png, O_01.jpg, O_02.jpg).
        variants = _discover_tile_variants(tiles_dir)
        # Per-type shuffled decks: pick without replacement, refill when exhausted.
        decks: Dict[str, List[str]] = {t: [] for t in BASE_TILES}
        img_cache: Dict[str, Image.Image] = {}  # keyed by file path

        for ty in range(len(tile_types)):
            for tx in range(len(tile_types[ty])):
                ttype = tile_types[ty][tx]
                if ttype is None:
                    continue
                type_variants = variants.get(ttype, [])
                if not type_variants:
                    # No image files found for this type — skip.
                    continue
                if not decks[ttype]:
                    deck = list(type_variants)
                    _rng.shuffle(deck)
                    decks[ttype] = deck
                path = decks[ttype].pop()
                if path not in img_cache:
                    img_cache[path] = ImageOps.exif_transpose(
                        Image.open(path)
                    ).convert("RGB")
                scaled = img_cache[path].resize((tile_px, tile_px), Image.LANCZOS)
                rot = (tile_rots[ty][tx] or 0) % 4
                if _rot_transpose[rot] is not None:
                    scaled = scaled.transpose(_rot_transpose[rot])
                img.paste(scaled, (margin_px + tx * tile_px, margin_px + ty * tile_px))

        if overlay_shapes:
            shape_layer = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
            d_s = ImageDraw.Draw(shape_layer)
            for y in range(H):
                for x in range(W):
                    x0, y0 = margin_px + x * cell_px, margin_px + y * cell_px
                    fill = (245, 245, 245, 0) if floor[y][x] else (0, 0, 0, 128)
                    d_s.rectangle([x0, y0, x0 + cell_px, y0 + cell_px], fill=fill)
            img = Image.alpha_composite(img.convert("RGBA"), shape_layer).convert("RGB")
            d = ImageDraw.Draw(img)
    else:
        for y in range(H):
            for x in range(W):
                x0, y0 = margin_px + x * cell_px, margin_px + y * cell_px
                x1, y1 = x0 + cell_px, y0 + cell_px
                d.rectangle([x0, y0, x1, y1], fill=(FLOOR if floor[y][x] else WALL))
                if theme == "scan" and floor[y][x]:
                    d.rectangle([x0 + 1, y0 + 1, x1 - 1, y1 - 1], outline=GLOW)

    # Gridlines
    if draw_grid:
        for x in range(W + 1):
            x0   = margin_px + x * cell_px
            bold = tile_grid_every > 0 and x % tile_grid_every == 0
            d.line([x0, margin_px, x0, margin_px + H * cell_px],
                   fill=GRID_BOLD if bold else GRID, width=2 if bold else 1)
        for y in range(H + 1):
            y0   = margin_px + y * cell_px
            bold = tile_grid_every > 0 and y % tile_grid_every == 0
            d.line([margin_px, y0, margin_px + W * cell_px, y0],
                   fill=GRID_BOLD if bold else GRID, width=2 if bold else 1)
        if theme == "scan" and tile_grid_every > 0:
            for x in range(0, W + 1, tile_grid_every):
                x0 = margin_px + x * cell_px
                d.line([x0, margin_px, x0, margin_px + H * cell_px], fill=GLOW, width=2)
            for y in range(0, H + 1, tile_grid_every):
                y0 = margin_px + y * cell_px
                d.line([margin_px, y0, margin_px + W * cell_px, y0], fill=GLOW, width=2)

    # Markers — player, console, spawns, custom
    r = max(3, cell_px // 3)
    if spawns:
        for x, y in spawns:
            cx, cy = margin_px + x * cell_px + cell_px // 2, margin_px + y * cell_px + cell_px // 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 40, 40))
    if player:
        x, y = player
        cx, cy = margin_px + x * cell_px + cell_px // 2, margin_px + y * cell_px + cell_px // 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(40, 80, 220))
    if console:
        x, y = console
        cx, cy = margin_px + x * cell_px + cell_px // 2, margin_px + y * cell_px + cell_px // 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(40, 180, 80))
    if markers:
        r2 = max(3, cell_px // 4)
        for m in markers:
            cx, cy = margin_px + m.x * cell_px + cell_px // 2, margin_px + m.y * cell_px + cell_px // 2
            d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=m.color)

    if tile_counts:
        label = "  ".join(f"{k}:{tile_counts[k]}" for k in sorted(tile_counts))
        d.text((margin_px, margin_px + H * cell_px + 2), label, fill=(200, 200, 200))

    img.save(out_path)
    print(f"Saved: {out_path}")


# ─────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────

def generate_many(
    n: int = 6,
    out_dir: str = ".",
    enforce_connected: bool = False,
    theme: str = "clean",
    tile_grid_w: int = 5,
    tile_grid_h: int = 4,
    cell_px: int = 128,
    placement: str = "standard",
    use_tile_images: bool = False,
    tiles_dir: str = "tiles",
    overlay_shapes: bool = False,
) -> None:
    place_items = PLACEMENT_STRATEGIES[placement]
    for _ in range(n):
        seed = random.randint(0, 2**32 - 1)
        cfg  = DungeonConfig(
            enforce_connected=enforce_connected,
            big_room_count=0,
            seed=seed,
            tile_grid_w=tile_grid_w,
            tile_grid_h=tile_grid_h,
        )
        floor, tile_types, tile_rots, big_room_origin, counts, rng = build_floor_grid(cfg)
        spawns, player, console, markers = place_items(floor, tile_types, big_room_origin, cfg, rng)
        render_png(
            floor,
            cell_px=cell_px,
            margin_px=16,
            draw_grid=True,
            spawns=spawns,
            player=player,
            console=console,
            tile_counts=counts,
            markers=markers,
            theme=theme,
            out_path=f"{out_dir}/dungeon_{seed}.png",
            use_tile_images=use_tile_images,
            tiles_dir=tiles_dir,
            tile_types=tile_types,
            tile_rots=tile_rots,
            overlay_shapes=overlay_shapes,
            rng=rng,
        )


def collect_stats(n: int = 1000) -> None:
    """Run the generator n times and print tile-count percentile stats."""
    import statistics

    all_counts: Dict[str, List[int]] = {k: [] for k in BASE_TILES}
    for i in range(n):
        cfg = DungeonConfig(
            enforce_connected=True,
            big_room_count=1 if (i + 1) % 3 == 0 else 0,
        )
        _, _, _, _, counts, _ = build_floor_grid(cfg)
        for tile in BASE_TILES:
            all_counts[tile].append(counts.get(tile, 0))

    def pct(data: List[int], p: float) -> int:
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * p / 100)
        return sorted_data[min(idx, len(sorted_data) - 1)]

    print(f"\nTile count stats over {n} dungeons:\n")
    print("| Tile |  min |  avg |  p90 |  p95 |  max |")
    print("|:----:|:----:|:----:|:----:|:----:|:----:|")
    for tile in sorted(BASE_TILES):
        data = all_counts[tile]
        print(
            f"|  `{tile}` | {min(data):>4} | {statistics.mean(data):>4.1f}"
            f" | {pct(data, 90):>4} | {pct(data, 95):>4} | {max(data):>4} |"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dungeon generator")
    parser.add_argument("--width",          type=int, default=5,          help="Dungeon width in tiles (default: 5)")
    parser.add_argument("--height",         type=int, default=4,          help="Dungeon height in tiles (default: 4)")
    parser.add_argument("--placement",      choices=PLACEMENT_STRATEGIES, help="Item placement strategy (default: standard)", default="standard")
    parser.add_argument("--n",              type=int, default=15,         help="Number of dungeons to generate (default: 15)")
    parser.add_argument("--theme",          default="scan",               help="Render theme (default: scan)")
    parser.add_argument("--cell-px",        type=int, default=128,        help="Pixels per cell (controls output resolution, default: 128)")
    parser.add_argument("--tile-images",    action="store_true",          help="Use tile images from the tiles/ folder instead of drawing shapes")
    parser.add_argument("--tiles-dir",      default="tiles",              help="Directory containing tile images (default: tiles)")
    parser.add_argument("--overlay-shapes", action="store_true",          help="Overlay drawn shapes at 50%% opacity on top of tile images (for alignment checking)")
    args = parser.parse_args()

    generate_many(
        n=args.n,
        out_dir=".",
        enforce_connected=True,
        theme=args.theme,
        tile_grid_w=args.width,
        tile_grid_h=args.height,
        cell_px=args.cell_px,
        placement=args.placement,
        use_tile_images=args.tile_images,
        tiles_dir=args.tiles_dir,
        overlay_shapes=args.overlay_shapes,
    )
