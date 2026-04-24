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

    ``rooms`` — AABBs of every room interior (``cols × rows`` of them,
    flattened in column-major order: index = ``c * rows + r``).
    ``walls`` — AABBs of every wall segment.
    ``spawner`` — world-space ``(x, y)`` of the centre room's centre,
    where the MazeSpawner sits.
    ``bounds`` — outer AABB of the whole maze (rooms + walls).
    ``room_graph`` — adjacency map ``room_idx -> list[room_idx]``
    listing every room reachable through a carved doorway.  Used by
    :func:`astar_room_path` so MazeAliens can plan around walls
    instead of grinding on them.
    ``rows``, ``cols`` — grid dimensions (room count along y, x).
    """
    rooms: list[Rect]
    walls: list[Rect]
    spawner: tuple[float, float]
    bounds: Rect
    room_graph: dict[int, list[int]]
    rows: int
    cols: int


def _add_outer_wall_with_gap(
    walls: list[Rect],
    origin_x: float, origin_y: float,
    total_w: int, total_h: int,
    wall_thick: int, room_size: int, step: int,
    side: str, cell: int,
) -> None:
    """Emit the four outer-boundary wall rects for one maze, with the
    wall segment in front of ``(side, cell)`` omitted so the player
    can fly in.  Corner filler tiles on either side of the gap remain
    so the outline stays visually complete.
    """
    # The three full walls — emit all four, then replace the chosen
    # side with two pre/post segments around the entrance gap.
    bot = Rect(origin_x, origin_y, total_w, wall_thick)
    top = Rect(origin_x, origin_y + total_h - wall_thick,
               total_w, wall_thick)
    left = Rect(origin_x, origin_y, wall_thick, total_h)
    right = Rect(origin_x + total_w - wall_thick, origin_y,
                 wall_thick, total_h)

    if side in ("N", "S"):
        # Horizontal wall.  Room at column ``cell`` sits from
        # ``wall_thick + cell*step`` to ``wall_thick + cell*step +
        # room_size`` along x.  Gap aligns to that room width.
        gap_start = origin_x + wall_thick + cell * step
        gap_end = gap_start + room_size
        base = bot if side == "S" else top
        pre_w = gap_start - base.x
        post_x = gap_end
        post_w = (base.x + base.w) - gap_end
        if pre_w > 0:
            walls.append(Rect(base.x, base.y, pre_w, base.h))
        if post_w > 0:
            walls.append(Rect(post_x, base.y, post_w, base.h))
        # The other three sides render normally.
        walls.append(top if side == "S" else bot)
        walls.append(left)
        walls.append(right)
    else:
        # Vertical wall.  Room at row ``cell`` sits from
        # ``wall_thick + cell*step`` to ``wall_thick + cell*step +
        # room_size`` along y.
        gap_start = origin_y + wall_thick + cell * step
        gap_end = gap_start + room_size
        base = left if side == "W" else right
        pre_h = gap_start - base.y
        post_y = gap_end
        post_h = (base.y + base.h) - gap_end
        if pre_h > 0:
            walls.append(Rect(base.x, base.y, base.w, pre_h))
        if post_h > 0:
            walls.append(Rect(base.x, post_y, base.w, post_h))
        walls.append(right if side == "W" else left)
        walls.append(bot)
        walls.append(top)


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
    # Outer boundary with an entrance cut.  One random outer-edge
    # cell is chosen and the wall segment in front of it is omitted
    # so the player can fly in.  Per spec "at least one entrance."
    entrance_side = rng.choice(("N", "S", "E", "W"))
    if entrance_side in ("N", "S"):
        entrance_cell = rng.randint(0, cols - 1)
    else:
        entrance_cell = rng.randint(0, rows - 1)
    _add_outer_wall_with_gap(
        walls, origin_x, origin_y, total_w, total_h,
        wall_thick, room_size, step,
        entrance_side, entrance_cell,
    )

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
    # Build the room adjacency graph from the carved-edge sets.  The
    # rooms list above is laid out as ``rooms[c * rows + r]`` so that
    # index can be derived from a (col, row) pair.
    room_graph: dict[int, list[int]] = {i: [] for i in range(len(rooms))}

    def _idx(c: int, r: int) -> int:
        return c * rows + r
    for (c, r) in carved_h_edges:           # connects (c, r) ↔ (c, r+1)
        a, b = _idx(c, r), _idx(c, r + 1)
        room_graph[a].append(b)
        room_graph[b].append(a)
    for (c, r) in carved_v_edges:           # connects (c, r) ↔ (c+1, r)
        a, b = _idx(c, r), _idx(c + 1, r)
        room_graph[a].append(b)
        room_graph[b].append(a)

    return MazeLayout(
        rooms=rooms, walls=walls,
        spawner=spawner_xy, bounds=bounds,
        room_graph=room_graph, rows=rows, cols=cols,
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


def find_room_index(
    x: float, y: float, rooms: list[Rect],
) -> int | None:
    """Return the index of the room AABB containing ``(x, y)``, or
    ``None`` if the point sits in a wall / outside the maze.  Used by
    MazeAlien path-planning to locate the alien + the player on the
    room graph."""
    for i, r in enumerate(rooms):
        if r.x <= x <= r.x + r.w and r.y <= y <= r.y + r.h:
            return i
    return None


def astar_room_path(
    start: int, goal: int,
    room_graph: dict[int, list[int]],
    rooms: list[Rect],
) -> list[int]:
    """Return the shortest path of room indices from ``start`` to
    ``goal`` (inclusive of both ends), or ``[]`` if no path exists.

    Heuristic is straight-line distance between room centres — admissible
    on a uniform grid, so A* returns the optimal path.  With at most
    25 rooms per maze and ~4 neighbours each, the open set never
    exceeds ~30 entries; a plain ``list`` + linear-scan tie-break is
    cheaper than ``heapq`` for this size.
    """
    if start == goal:
        return [start]
    if start not in room_graph or goal not in room_graph:
        return []

    def _h(i: int) -> float:
        a, b = rooms[i], rooms[goal]
        ax = a.x + a.w * 0.5
        ay = a.y + a.h * 0.5
        bx = b.x + b.w * 0.5
        by = b.y + b.h * 0.5
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    came_from: dict[int, int] = {}
    g_score: dict[int, float] = {start: 0.0}
    open_set: list[int] = [start]
    while open_set:
        # Pick the open-set node with lowest f = g + h.
        best_i = 0
        best_f = g_score[open_set[0]] + _h(open_set[0])
        for k in range(1, len(open_set)):
            f = g_score[open_set[k]] + _h(open_set[k])
            if f < best_f:
                best_f = f
                best_i = k
        current = open_set.pop(best_i)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path
        g_cur = g_score[current]
        for nbr in room_graph[current]:
            tentative = g_cur + 1.0   # uniform edge cost — adjacent rooms
            if tentative < g_score.get(nbr, float("inf")):
                came_from[nbr] = current
                g_score[nbr] = tentative
                if nbr not in open_set:
                    open_set.append(nbr)
    return []


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
