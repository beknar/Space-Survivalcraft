"""Pure-function geometry + generator for the Star Maze.

Each maze is a ``STAR_MAZE_ROOM_COLS × STAR_MAZE_ROOM_ROWS`` grid of
rooms carved by a deterministic recursive backtracker (DFS).  The
result is a proper maze: some cells read as corridors (two opposite
openings), some as junctions (3-4 openings), some as dead ends (one
opening).  Rooms are ``STAR_MAZE_ROOM_SIZE`` on a side and doorways
between connected rooms span the full room width so the ship (56 px
diameter) can U-turn inside any room or through any doorway.

The generator is seeded so save/load round-trips produce identical
layouts, and the collision helpers stay pure so they're trivially
testable.
"""
from __future__ import annotations

import random
from typing import NamedTuple

from constants import (
    STAR_MAZE_ROOM_COLS, STAR_MAZE_ROOM_ROWS, STAR_MAZE_ROOM_SIZE,
    STAR_MAZE_WALL_THICK, STAR_MAZE_SPAN,
    STAR_MAZE_CENTERS,
)


# ``Rect`` is intentionally (x, y, w, h) with lower-left-origin coords
# so it composes directly with ``arcade.LBWH``.
class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float


class MazeLayout(NamedTuple):
    """One generated maze's artefacts.

    ``rooms`` — AABBs of every room interior (``cols × rows`` of them).
    ``walls`` — AABBs of every wall segment.
    ``spawner`` — world-space ``(x, y)`` of the centre room's centre,
    where the MazeSpawner sits.
    ``bounds`` — outer AABB of the whole maze (rooms + walls).
    """
    rooms: list[Rect]
    walls: list[Rect]
    spawner: tuple[float, float]
    bounds: Rect


def generate_maze(
    center_x: float, center_y: float,
    *,
    cols: int = STAR_MAZE_ROOM_COLS,
    rows: int = STAR_MAZE_ROOM_ROWS,
    room_size: int = STAR_MAZE_ROOM_SIZE,
    wall_thick: int = STAR_MAZE_WALL_THICK,
    seed: int = 0,
) -> MazeLayout:
    """Carve one maze centred on ``(center_x, center_y)``.

    Uses recursive backtracking — pick a random unvisited neighbour
    of the current cell, knock down the wall between them, recurse.
    When the current cell has no unvisited neighbours, backtrack.
    """
    rng = random.Random(seed)

    # ── DFS ─────────────────────────────────────────────────────────
    # carved_h_edges[(c, r)]: horizontal edge between cell (c, r)
    # below and (c, r+1) above is open.
    # carved_v_edges[(c, r)]: vertical edge between cell (c, r) left
    # and (c+1, r) right is open.
    carved_h_edges: set[tuple[int, int]] = set()
    carved_v_edges: set[tuple[int, int]] = set()
    visited: set[tuple[int, int]] = {(0, 0)}
    stack: list[tuple[int, int]] = [(0, 0)]
    while stack:
        c, r = stack[-1]
        options: list[tuple[tuple[int, int], tuple[str, int, int]]] = []
        if r + 1 < rows and (c, r + 1) not in visited:
            options.append(((c, r + 1), ("h", c, r)))
        if c + 1 < cols and (c + 1, r) not in visited:
            options.append(((c + 1, r), ("v", c, r)))
        if r > 0 and (c, r - 1) not in visited:
            options.append(((c, r - 1), ("h", c, r - 1)))
        if c > 0 and (c - 1, r) not in visited:
            options.append(((c - 1, r), ("v", c - 1, r)))
        if options:
            nxt, edge = rng.choice(options)
            if edge[0] == "h":
                carved_h_edges.add((edge[1], edge[2]))
            else:
                carved_v_edges.add((edge[1], edge[2]))
            visited.add(nxt)
            stack.append(nxt)
        else:
            stack.pop()

    # ── Build rects ────────────────────────────────────────────────
    step = room_size + wall_thick
    total_w = cols * step + wall_thick
    total_h = rows * step + wall_thick
    origin_x = center_x - total_w / 2
    origin_y = center_y - total_h / 2

    rooms: list[Rect] = []
    for c in range(cols):
        for r in range(rows):
            rx = origin_x + wall_thick + c * step
            ry = origin_y + wall_thick + r * step
            rooms.append(Rect(rx, ry, room_size, room_size))

    walls: list[Rect] = []
    # Outer boundary — 4 rectangles.
    walls.append(Rect(origin_x, origin_y, total_w, wall_thick))            # bot
    walls.append(Rect(origin_x, origin_y + total_h - wall_thick,
                      total_w, wall_thick))                                 # top
    walls.append(Rect(origin_x, origin_y, wall_thick, total_h))            # left
    walls.append(Rect(origin_x + total_w - wall_thick, origin_y,
                      wall_thick, total_h))                                 # right

    # Internal horizontal walls — between row r and row r+1, spanning
    # the room width.  Only placed where the edge wasn't carved.
    for c in range(cols):
        for r in range(rows - 1):
            if (c, r) in carved_h_edges:
                continue
            wx = origin_x + wall_thick + c * step
            wy = origin_y + wall_thick + r * step + room_size
            walls.append(Rect(wx, wy, room_size, wall_thick))

    # Internal vertical walls.
    for c in range(cols - 1):
        for r in range(rows):
            if (c, r) in carved_v_edges:
                continue
            wx = origin_x + wall_thick + c * step + room_size
            wy = origin_y + wall_thick + r * step
            walls.append(Rect(wx, wy, wall_thick, room_size))

    # Internal corner fillers — the wall-thickness×wall-thickness
    # squares where four cells meet.  Always solid so the maze has a
    # clean grid aesthetic regardless of which edges got carved.
    for c in range(cols - 1):
        for r in range(rows - 1):
            wx = origin_x + wall_thick + c * step + room_size
            wy = origin_y + wall_thick + r * step + room_size
            walls.append(Rect(wx, wy, wall_thick, wall_thick))

    spawner_xy = (center_x, center_y)
    bounds = Rect(origin_x, origin_y, total_w, total_h)
    return MazeLayout(
        rooms=rooms, walls=walls,
        spawner=spawner_xy, bounds=bounds,
    )


def generate_all_mazes(
    centers: tuple[tuple[int, int], ...] = STAR_MAZE_CENTERS,
    *,
    zone_seed: int = 0,
) -> list[MazeLayout]:
    """Generate every maze in the Star Maze zone.

    Each maze gets a distinct seed derived from ``zone_seed`` and its
    index so save/load round-trips reproduce the same two layouts.
    """
    return [
        generate_maze(cx, cy, seed=zone_seed * 131 + i * 17)
        for i, (cx, cy) in enumerate(centers)
    ]


# ── Point/rect tests ────────────────────────────────────────────────

def point_in_rect(x: float, y: float, r: Rect) -> bool:
    return r.x <= x <= r.x + r.w and r.y <= y <= r.y + r.h


def point_in_any(x: float, y: float, rects: list[Rect]) -> bool:
    for r in rects:
        if point_in_rect(x, y, r):
            return True
    return False


def circle_overlaps_rect(
    cx: float, cy: float, radius: float, r: Rect,
) -> bool:
    """Classic circle-vs-AABB overlap: clamp the circle centre to the
    rect and check distance to the clamped point.  Used for the
    player ship + maze-aliens' wall collision."""
    qx = max(r.x, min(cx, r.x + r.w))
    qy = max(r.y, min(cy, r.y + r.h))
    dx = cx - qx
    dy = cy - qy
    return dx * dx + dy * dy <= radius * radius


def circle_hits_any_wall(
    cx: float, cy: float, radius: float, walls: list[Rect],
) -> bool:
    for w in walls:
        if circle_overlaps_rect(cx, cy, radius, w):
            return True
    return False


def segment_hits_any_wall(
    ax: float, ay: float, bx: float, by: float, walls: list[Rect],
) -> bool:
    """Cheap segment-vs-rect test — samples 4 interpolated points and
    checks each with ``point_in_any_rect``.  For projectile vs wall
    where the segment is at most ~10 px per tick, this is plenty.
    """
    for t in (0.0, 0.33, 0.66, 1.0):
        x = ax + (bx - ax) * t
        y = ay + (by - ay) * t
        for w in walls:
            if point_in_rect(x, y, w):
                return True
    return False


def point_inside_any_room_interior(
    x: float, y: float,
    rooms: list[Rect],
    margin: float = 0.0,
) -> bool:
    """Reject predicate for zone-population helpers: returns True if
    ``(x, y)`` falls inside any room rect (plus a margin).  Still
    exported even though the current design has no Nebula content in
    the Star Maze — the hook lets callers filter on maze geometry
    without coupling to StarMazeZone internals.
    """
    for r in rooms:
        if (r.x - margin <= x <= r.x + r.w + margin
                and r.y - margin <= y <= r.y + r.h + margin):
            return True
    return False
