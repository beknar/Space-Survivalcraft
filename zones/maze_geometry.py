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
    # World-space midpoint of the carved-out doorway between two
    # connected rooms.  Keyed by ``frozenset({a, b})`` so callers
    # don't have to know the order.  Used by ``WaypointPlanner`` to
    # aim at the gap in the wall before aiming at the next room's
    # centre — without this the drone steers a straight line
    # between two room centres that may clip a wall corner and
    # wedge the drone forever.
    doorways: dict[frozenset[int], tuple[float, float]] = {}
    # Maze entrance — the single outer-wall cell that's carved out
    # so the player can fly in.  ``entrance_room`` is the room
    # adjacent to that gap, ``entrance_xy`` is the world-space
    # midpoint of the gap itself.  Used by ``WaypointPlanner`` to
    # route a body trying to reach a target outside the maze: the
    # ONLY way out is through the entrance, so when the target
    # sits outside any room the planner heads for the entrance
    # room first (instead of the geographically nearest room,
    # which would dump the drone into a sealed dead end).
    entrance_room: int = 0
    entrance_xy: tuple[float, float] = (0.0, 0.0)


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
    # World-space midpoint of each carved doorway, indexed by the
    # unordered pair of room indices it connects.  Used by the
    # WaypointPlanner to aim at the gap before aiming at the next
    # room's centre.
    doorways: dict[frozenset[int], tuple[float, float]] = {}

    def _idx(c: int, r: int) -> int:
        return c * rows + r
    half_wall = wall_thick * 0.5
    half_room = room_size * 0.5
    for (c, r) in carved_h_edges:           # connects (c, r) ↔ (c, r+1)
        a, b = _idx(c, r), _idx(c, r + 1)
        room_graph[a].append(b)
        room_graph[b].append(a)
        # Carved horizontal wall sat at y = origin_y + wall_thick +
        # r*step + room_size; its midpoint along x is the room centre.
        dx = origin_x + wall_thick + c * step + half_room
        dy = origin_y + wall_thick + r * step + room_size + half_wall
        doorways[frozenset((a, b))] = (dx, dy)
    for (c, r) in carved_v_edges:           # connects (c, r) ↔ (c+1, r)
        a, b = _idx(c, r), _idx(c + 1, r)
        room_graph[a].append(b)
        room_graph[b].append(a)
        dx = origin_x + wall_thick + c * step + room_size + half_wall
        dy = origin_y + wall_thick + r * step + half_room
        doorways[frozenset((a, b))] = (dx, dy)

    # Resolve the entrance room + world-space gap midpoint from the
    # randomly-chosen ``entrance_side`` / ``entrance_cell``.  Same
    # geometry the outer-wall builder used to carve the gap.
    if entrance_side == "N":
        entrance_room = _idx(entrance_cell, rows - 1)
        entrance_xy = (
            origin_x + wall_thick + entrance_cell * step + half_room,
            origin_y + total_h - half_wall,
        )
    elif entrance_side == "S":
        entrance_room = _idx(entrance_cell, 0)
        entrance_xy = (
            origin_x + wall_thick + entrance_cell * step + half_room,
            origin_y + half_wall,
        )
    elif entrance_side == "E":
        entrance_room = _idx(cols - 1, entrance_cell)
        entrance_xy = (
            origin_x + total_w - half_wall,
            origin_y + wall_thick + entrance_cell * step + half_room,
        )
    else:  # "W"
        entrance_room = _idx(0, entrance_cell)
        entrance_xy = (
            origin_x + half_wall,
            origin_y + wall_thick + entrance_cell * step + half_room,
        )

    return MazeLayout(
        rooms=rooms, walls=walls,
        spawner=spawner_xy, bounds=bounds,
        room_graph=room_graph, rows=rows, cols=cols,
        doorways=doorways,
        entrance_room=entrance_room,
        entrance_xy=entrance_xy,
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


class WaypointPlanner:
    """Stateful, per-body pathfinder over the room graph.

    Replaces the inlined A* + waypoint logic that used to live on each
    enemy / drone class.  A single shared implementation means both
    MazeAlien (chasing the player) and the player's combat / mining
    drones (chasing the player or a target across walls) get identical
    "find the next room to steer toward, and give up if it isn't
    working" behaviour.

    Usage per frame::

        wp = planner.plan(dt, body.center_x, body.center_y, tx, ty)
        if planner.gave_up():
            # Pathfinding failed for 5 s with no progress — caller
            # should drop pursuit and patrol / hold for ``COOLDOWN``
            # seconds before trying again.
            body.enter_patrol()
        elif wp is not None:
            wx, wy = wp                # steer toward this point
        else:
            ...                        # same room as target → chase
                                       # directly, no path needed

    Progress is measured by **physical movement** of the body: every
    ``FAIL_TIMEOUT`` seconds we expect the body to have travelled at
    least ``STUCK_DIST`` from its last anchor.  If it didn't, the
    planner declares failure — that catches the "grinding against a
    wall" case (waypoint produced but body can't reach it).  After
    failure the planner refuses to plan for ``COOLDOWN`` seconds so
    the body's patrol behaviour can shake it loose.

    Pure stateful object — no zone / GameView coupling.  ``rooms`` /
    ``room_graph`` may both be ``None`` (caller is outside a maze) in
    which case the planner is a no-op and never gives up.
    """

    FAIL_TIMEOUT: float = 5.0       # seconds w/o progress → give up
    COOLDOWN: float = 5.0           # seconds of no-planning after giving up
    STUCK_DIST: float = 30.0        # px the body must move within FAIL_TIMEOUT
    REPLAN_INTERVAL: float = 0.5    # A* recompute cadence

    # Slack used when the body's centre is outside every room AABB
    # but inside the wall-thickness band of one — wall_thick is 32 in
    # the live mazes, plus a few px so a drone partially clipping the
    # wall still gets matched to the room.
    _WALL_BAND_SLACK: float = 50.0

    def __init__(
        self,
        rooms: list[Rect] | None,
        room_graph: dict[int, list[int]] | None,
        doorways: dict[frozenset[int], tuple[float, float]] | None = None,
        room_to_exit_room: dict[int, int] | None = None,
        exit_xy_by_room: dict[int, tuple[float, float]] | None = None,
    ) -> None:
        self._rooms = rooms
        self._room_graph = room_graph
        # Optional: per-edge doorway midpoints.  When present, the
        # planner aims at the gap-in-the-wall first, then the next
        # room's centre — straight-line steering between two room
        # centres can clip a wall corner and wedge the body forever.
        # ``None`` keeps the legacy room-centre behaviour for
        # callers that haven't passed it yet.
        self._doorways = doorways or {}
        # Optional: maze-exit routing.  Given a room index, what's
        # the entrance room of that room's maze?  And what's the
        # world-space midpoint of the entrance gap?  Used when the
        # target is outside every room — the body must first reach
        # the entrance to get out, the geographically-nearest room
        # might be sealed off from the target's side.
        self._room_to_exit_room = room_to_exit_room or {}
        self._exit_xy_by_room = exit_xy_by_room or {}
        self._path: list[int] = []
        self._path_target_room: int | None = None
        self._replan_t: float = 0.0
        # Progress anchor — set on entering a planning state, reset
        # whenever the body has moved STUCK_DIST from it.
        self._anchor_x: float | None = None
        self._anchor_y: float | None = None
        self._stuck_t: float = 0.0
        # Cooldown ticking down after a give-up event.
        self._cooldown_t: float = 0.0
        # Latch consumed once by ``gave_up()``.
        self._just_gave_up: bool = False

    def gave_up(self) -> bool:
        """Return True exactly once per failure event.  Caller should
        switch behaviour (drop target, patrol, etc.) on True."""
        if self._just_gave_up:
            self._just_gave_up = False
            return True
        return False

    def cooling_down(self) -> bool:
        return self._cooldown_t > 0.0

    def reset(self) -> None:
        """Clear all planner state — used on target change so a new
        target gets a fresh stuck timer."""
        self._path = []
        self._path_target_room = None
        self._anchor_x = None
        self._anchor_y = None
        self._stuck_t = 0.0
        self._just_gave_up = False
        # Note: cooldown_t is intentionally NOT reset — a body that
        # just gave up shouldn't be able to instantly re-plan by
        # picking a new target.

    def plan(
        self, dt: float,
        sx: float, sy: float,
        tx: float, ty: float,
    ) -> tuple[float, float] | None:
        """Return the next waypoint to steer toward, or ``None`` if
        the body should chase the target directly (same room) or
        fall back to its idle behaviour (cooling down / unsupported).

        Always tick the cooldown timer regardless of success."""
        if self._cooldown_t > 0.0:
            self._cooldown_t = max(0.0, self._cooldown_t - dt)
            return None
        if self._rooms is None or self._room_graph is None:
            return None
        sroom = find_room_index(sx, sy, self._rooms)
        troom = find_room_index(tx, ty, self._rooms)
        # Body-side fallback: when the body is inside the wall-
        # thickness band of a room (push-out hasn't shoved it
        # interior-side yet) ``find_room_index`` returns None even
        # though the body is geometrically inside the maze.  Snap
        # to the nearest room IF the body is within
        # ``_WALL_BAND_SLACK`` of one — otherwise we'd route a
        # body sitting in open space into the maze for no reason.
        # Captured by telemetry 2026-04-26 20:03: drone wedged at
        # x=2185 inside maze 1's west outer wall (spans 2154→2186),
        # `path: []` every frame.
        if sroom is None and self._rooms:
            best, best_d2 = self._nearest_room_to_point(sx, sy)
            if best is not None and best_d2 <= (
                    self._WALL_BAND_SLACK * self._WALL_BAND_SLACK):
                sroom = best
        # Target-side fallback: target sits outside every room
        # (e.g. player is in open space outside the maze while the
        # drone is inside).
        #
        #   * If we know the exit room for the body's maze → route
        #     there.  The geographically-nearest room is often a
        #     sealed dead-end; only the entrance room actually
        #     connects to the outside.  Once the drone reaches the
        #     entrance room, ``sroom == troom`` and the next branch
        #     hands back the entrance gap midpoint as the waypoint.
        #
        #   * Otherwise (no exit table provided — legacy callers)
        #     fall back to the geographically-nearest room so the
        #     planner still produces SOME waypoint.
        if (sroom is not None and troom is None
                and self._room_graph is not None):
            exit_room = self._room_to_exit_room.get(sroom)
            if exit_room is not None:
                troom = exit_room
            else:
                best = None
                best_d2 = float("inf")
                for i, r in enumerate(self._rooms):
                    cx = r.x + r.w * 0.5
                    cy = r.y + r.h * 0.5
                    d2 = (cx - tx) ** 2 + (cy - ty) ** 2
                    if d2 < best_d2:
                        best_d2 = d2
                        best = i
                troom = best
        # Body is in the entrance room and target sits outside the
        # maze — direct waypoint to the entrance gap so the drone
        # actually crosses the outer wall instead of bouncing on it.
        if (sroom is not None
                and find_room_index(tx, ty, self._rooms) is None
                and self._room_to_exit_room.get(sroom) == sroom):
            self._anchor_x = None
            self._anchor_y = None
            self._stuck_t = 0.0
            return self._exit_xy_by_room.get(
                sroom, (tx, ty))
        if sroom is None or troom is None or sroom == troom:
            # Body is also outside any room (or already shares the
            # target's room) — caller should chase directly.  Clear
            # stuck tracker so the next inter-room plan starts with
            # a fresh budget.
            self._anchor_x = None
            self._anchor_y = None
            self._stuck_t = 0.0
            return None

        # Re-plan the room sequence on cadence, on target change, or
        # if our current path no longer starts in our room.
        self._replan_t -= dt
        if (self._path_target_room != troom
                or not self._path
                or self._replan_t <= 0.0
                or sroom not in self._path):
            self._path = astar_room_path(
                sroom, troom, self._room_graph, self._rooms)
            self._path_target_room = troom
            self._replan_t = self.REPLAN_INTERVAL

        if not self._path:
            # Disconnected components — body and target live in
            # rooms that aren't reachable through the carved doorways
            # (e.g. the player is in a different maze entirely).  The
            # caller should chase directly through whatever open
            # space lies between them; only the explicit no-progress
            # timer counts as "give up", so a quick no-path frame
            # doesn't strand the body in cooldown.
            self._anchor_x = None
            self._stuck_t = 0.0
            return None

        # Drop already-passed entries up to current room.
        while self._path and self._path[0] != sroom:
            self._path.pop(0)
        if len(self._path) < 2:
            self._anchor_x = None
            self._stuck_t = 0.0
            return None

        # Stuck detection — anchor on first plan call after a reset,
        # then measure displacement.  ``STUCK_DIST`` worth of motion
        # within FAIL_TIMEOUT counts as progress.
        if self._anchor_x is None:
            self._anchor_x = sx
            self._anchor_y = sy
            self._stuck_t = 0.0
        else:
            moved_sq = ((sx - self._anchor_x) ** 2
                        + (sy - self._anchor_y) ** 2)
            if moved_sq >= self.STUCK_DIST * self.STUCK_DIST:
                self._anchor_x = sx
                self._anchor_y = sy
                self._stuck_t = 0.0
            else:
                self._stuck_t += dt
                if self._stuck_t >= self.FAIL_TIMEOUT:
                    self._fail()
                    return None

        # Doorway-aware steering: when we know the gap location
        # between the current room and the next, aim there first so
        # we cleanly cross the wall instead of clipping a corner.
        # Falls back to the next room's centre when no doorway entry
        # exists (caller didn't pass the doorways table or the maze
        # is laid out without carved gaps for some reason).
        edge_key = frozenset((sroom, self._path[1]))
        door = self._doorways.get(edge_key)
        if door is not None:
            return door
        nxt = self._rooms[self._path[1]]
        return (nxt.x + nxt.w * 0.5, nxt.y + nxt.h * 0.5)

    def _nearest_room_to_point(
        self, x: float, y: float,
    ) -> tuple[int | None, float]:
        """Return ``(room_index, squared_distance)`` for the room whose
        AABB sits closest to (x, y).  Distance is point-to-AABB
        (zero when the point is inside the AABB).  Used by the
        wall-band substitution to recover a sensible source room
        when the body's centre falls inside a wall thickness gap."""
        if not self._rooms:
            return (None, float("inf"))
        best = None
        best_d2 = float("inf")
        for i, r in enumerate(self._rooms):
            qx = max(r.x, min(x, r.x + r.w))
            qy = max(r.y, min(y, r.y + r.h))
            d2 = (x - qx) ** 2 + (y - qy) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best = i
        return (best, best_d2)

    def _fail(self) -> None:
        """Trigger a give-up event — used by both the unreachable-
        target path and the no-progress timeout."""
        self._just_gave_up = True
        self._cooldown_t = self.COOLDOWN
        self._path = []
        self._anchor_x = None
        self._stuck_t = 0.0


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
