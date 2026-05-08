"""Grid-based A* pathfinding for the bot autopilot.

Operates on the live ``/state`` snapshot — buildings as circular
obstacles, world rectangle as bounds.  Designed to plan a path
around the station cluster (or any other building cluster) when the
straight-line route from the bot to its current goto target would
cross blocked space, AND to detect targets that are unreachable
(e.g. a pickup that drifted inside the cluster) so the FSM can
blacklist them immediately instead of letting the bot pin against
the cluster's repulsion field for tens of seconds.

Grid representation:

* Cell size ``ASTAR_CELL_PX`` (default 80 px).  6400×6400 world →
  80×80 cell grid (6400 cells), small enough that an A* call costs
  well under a millisecond on the typical station layout.
* Each cell is BLOCKED iff any building's centre is within
  ``BUILDING_RADIUS_PX + ASTAR_SAFETY_MARGIN_PX`` of the cell
  centre.  The safety margin keeps planned waypoints clear of the
  same building-repulsion field that ``steered_heading`` uses, so
  the bot doesn't fight the field as it follows the path.
* Cells within ``ASTAR_BOUNDARY_MARGIN_PX`` of any world edge are
  also BLOCKED so paths stay inside the playable area (matching
  the boundary-repulsion field's reach).

Public API:

* ``plan_path(state, sx, sy, gx, gy)`` — returns a list of
  ``(x, y)`` waypoints in world coordinates (excluding the start,
  including the goal), or ``[]`` if no path exists.  Path is
  post-processed via line-of-sight smoothing to drop intermediate
  waypoints whose direct connection is unobstructed.
* ``target_reachable(state, sx, sy, gx, gy)`` — convenience
  predicate.  ``True`` iff ``plan_path`` returns a non-empty list.

Both functions tolerate the bot's start cell being marked blocked
(it can drift into the safety margin).  Only the goal cell's
blocked status is decisive — an unreachable goal returns ``[]``.
"""
from __future__ import annotations

import heapq
import math


# ── Tuning ──────────────────────────────────────────────────────────────

# Grid cell size.  Smaller cells = finer paths but slower planning;
# 80 px matches the building-repulsion field's typical scale (range
# 150 px = ~2 cells of clearance) so paths thread between buildings
# without skirting the field's edge.
ASTAR_CELL_PX: int = 80

# Buffer around buildings beyond their physical radius.  Tuned
# slightly tighter than ``BUILDING_REPULSION_RANGE_PX`` (150) so
# A* paths stay outside the strong repulsion zone but don't detour
# unnecessarily wide.
ASTAR_SAFETY_MARGIN_PX: float = 70.0

# Boundary cells within this distance of any world edge are blocked
# only when ``include_boundary=True`` is passed to ``_build_grid``.
# Default-off because edge-adjacent pickups / asteroids would
# otherwise be flagged unreachable when they're physically fine to
# navigate to — boundary handling is already done by
# ``steered_heading`` blending the boundary-repulsion field into
# every heading.  The constant is kept for callers that want
# strict-interior planning (e.g. waypoint chains for transit
# routes), but the default path flow uses the building-only grid.
ASTAR_BOUNDARY_MARGIN_PX: float = 200.0

# Safety cap on A* exploration so a degenerate request (e.g.
# unreachable goal in an open world) can't run away.  Search visits
# at most this many cells before giving up; 6400-cell grid = plenty
# of headroom even for whole-world traversals.
ASTAR_MAX_VISITED: int = 5000

# Building physical radius — duplicated from ``constants.BUILDING_RADIUS``
# so this module has no Arcade / game-state dependency and can be
# unit-tested in isolation.  Verified against ``constants.py`` in
# ``test_bot_autopilot_astar.py``.
BUILDING_RADIUS_PX: float = 30.0


# ── Grid construction ──────────────────────────────────────────────────

def _cell_of(x: float, y: float, cell_px: int) -> tuple[int, int]:
    """Map world coords to grid-cell indices."""
    return (int(x // cell_px), int(y // cell_px))


def _world_of(cx: int, cy: int, cell_px: int) -> tuple[float, float]:
    """Centre of grid cell ``(cx, cy)`` in world coords."""
    return (cx * cell_px + cell_px * 0.5,
            cy * cell_px + cell_px * 0.5)


def _build_grid(state: dict, cell_px: int = ASTAR_CELL_PX,
                safety_margin_px: float = ASTAR_SAFETY_MARGIN_PX,
                include_boundary: bool = False,
                boundary_margin_px: float = ASTAR_BOUNDARY_MARGIN_PX
                ) -> tuple[set[tuple[int, int]], int, int]:
    """Build the BLOCKED-cell set + grid dimensions from ``state``.

    Returns ``(blocked, grid_w, grid_h)``.  ``blocked`` is a set of
    ``(cx, cy)`` tuples; cells not in the set are assumed free.

    Boundary blocking is opt-in (``include_boundary=True``) — the
    default omits edge cells from the blocked set so that
    ``target_reachable`` doesn't false-flag legitimate edge-adjacent
    pickups / asteroids as unreachable.  The bot's existing
    ``steered_heading`` boundary-repulsion blend handles wall
    avoidance smoothly without needing the planner to detour.
    """
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400.0) or 6400.0)
    world_h = float(zone.get("world_h", 6400.0) or 6400.0)
    grid_w = int(math.ceil(world_w / cell_px))
    grid_h = int(math.ceil(world_h / cell_px))
    blocked: set[tuple[int, int]] = set()

    if include_boundary:
        margin_cells = int(math.ceil(boundary_margin_px / cell_px))
        if margin_cells > 0:
            for cx in range(grid_w):
                for cy in range(grid_h):
                    if (cx < margin_cells or cx >= grid_w - margin_cells
                            or cy < margin_cells
                            or cy >= grid_h - margin_cells):
                        blocked.add((cx, cy))

    # Building cells.  For each building, iterate the (cx, cy) bounding
    # box of its blocking radius and mark cells whose CENTRE falls
    # inside the radius.  Centre-based check is conservative — a cell
    # whose corner just barely overlaps the radius isn't blocked,
    # which keeps the safety margin honest (we want clearance from
    # the building's true extent, not the cell's).
    block_radius = BUILDING_RADIUS_PX + safety_margin_px
    block_radius_sq = block_radius * block_radius
    for b in (state.get("buildings") or []):
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        radius_cells = int(math.ceil(block_radius / cell_px)) + 1
        cx0, cy0 = _cell_of(bx, by, cell_px)
        for cx in range(cx0 - radius_cells, cx0 + radius_cells + 1):
            if not (0 <= cx < grid_w):
                continue
            for cy in range(cy0 - radius_cells, cy0 + radius_cells + 1):
                if not (0 <= cy < grid_h):
                    continue
                wx, wy = _world_of(cx, cy, cell_px)
                if (wx - bx) ** 2 + (wy - by) ** 2 <= block_radius_sq:
                    blocked.add((cx, cy))
    return blocked, grid_w, grid_h


# ── A* search ──────────────────────────────────────────────────────────

# 8-neighbour moves with proper Euclidean costs.
_NEIGHBOR_OFFSETS: tuple[tuple[int, int, float], ...] = (
    (-1, -1, math.sqrt(2.0)),
    (-1,  0, 1.0),
    (-1, +1, math.sqrt(2.0)),
    (0,  -1, 1.0),
    (0,  +1, 1.0),
    (+1, -1, math.sqrt(2.0)),
    (+1,  0, 1.0),
    (+1, +1, math.sqrt(2.0)),
)


def _heuristic(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Octile distance — the exact lower bound on 8-connected grid
    movement cost.  Admissible (never overestimates) so A* returns
    optimal paths."""
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return (max(dx, dy) - min(dx, dy)) + math.sqrt(2.0) * min(dx, dy)


def _astar(start: tuple[int, int], goal: tuple[int, int],
           blocked: set[tuple[int, int]],
           grid_w: int, grid_h: int) -> list[tuple[int, int]]:
    """Standard A* over the cell grid.  Returns the cell path
    (inclusive of start + goal) or ``[]`` if no path exists."""
    if start == goal:
        return [start]
    if goal in blocked:
        # Goal cell itself is blocked — pickup wedged inside a
        # building, asteroid behind the cluster, etc.  Caller can
        # blacklist immediately instead of pinning against the
        # field for tens of seconds.
        return []

    # Priority queue: (f-score, tie-break counter, cell).  The
    # counter avoids comparing tuples when f-scores tie.
    open_heap: list[tuple[float, int, tuple[int, int]]] = []
    counter = 0
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {start: 0.0}

    heapq.heappush(open_heap, (_heuristic(start, goal), counter, start))
    counter += 1
    visited: set[tuple[int, int]] = set()

    while open_heap and len(visited) < ASTAR_MAX_VISITED:
        _f, _, current = heapq.heappop(open_heap)
        if current in visited:
            continue
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path
        visited.add(current)
        cur_g = g_score[current]
        for dx, dy, cost in _NEIGHBOR_OFFSETS:
            nbr = (current[0] + dx, current[1] + dy)
            if nbr in visited or nbr in blocked:
                continue
            if not (0 <= nbr[0] < grid_w and 0 <= nbr[1] < grid_h):
                continue
            tentative = cur_g + cost
            if tentative < g_score.get(nbr, float("inf")):
                came_from[nbr] = current
                g_score[nbr] = tentative
                heapq.heappush(
                    open_heap,
                    (tentative + _heuristic(nbr, goal), counter, nbr))
                counter += 1
    return []


# ── Path smoothing ─────────────────────────────────────────────────────

def _line_of_sight(a: tuple[float, float], b: tuple[float, float],
                   blocked: set[tuple[int, int]],
                   cell_px: int = ASTAR_CELL_PX) -> bool:
    """Sample cells between the two world points; return True iff
    every sampled cell is free.  Used by ``_smooth`` to drop
    intermediate A* waypoints whose direct connection is
    unobstructed.  Sample rate is half a cell so we can't miss a
    blocked cell wedged between samples."""
    ax, ay = a
    bx, by = b
    dist = math.hypot(bx - ax, by - ay)
    if dist <= cell_px * 0.5:
        return _cell_of(ax, ay, cell_px) not in blocked
    steps = max(1, int(math.ceil(dist / (cell_px * 0.5))))
    for i in range(steps + 1):
        t = i / steps
        x = ax + t * (bx - ax)
        y = ay + t * (by - ay)
        if _cell_of(x, y, cell_px) in blocked:
            return False
    return True


def _smooth(waypoints: list[tuple[float, float]],
            blocked: set[tuple[int, int]],
            cell_px: int = ASTAR_CELL_PX
            ) -> list[tuple[float, float]]:
    """Greedy line-of-sight smoothing.  From each waypoint, find the
    farthest later waypoint connectable by a straight line through
    free cells; drop everything in between.  Cuts the typical
    A* stair-step path down to ~2-3 waypoints around a cluster."""
    if len(waypoints) <= 2:
        return list(waypoints)
    smoothed = [waypoints[0]]
    i = 0
    n = len(waypoints)
    while i < n - 1:
        # Farthest j from i that's still line-of-sight reachable.
        j = n - 1
        while j > i + 1:
            if _line_of_sight(waypoints[i], waypoints[j], blocked, cell_px):
                break
            j -= 1
        smoothed.append(waypoints[j])
        i = j
    return smoothed


# ── Public API ─────────────────────────────────────────────────────────

def plan_path(state: dict, sx: float, sy: float, gx: float, gy: float,
              cell_px: int = ASTAR_CELL_PX
              ) -> list[tuple[float, float]]:
    """Plan a path from ``(sx, sy)`` to ``(gx, gy)`` through the
    building-blocked grid built from ``state``.  Returns a list of
    ``(x, y)`` waypoints in world coordinates.

    The list **excludes** the start and **includes** the goal —
    callers walk the list head-first; ``result[0]`` is the immediate
    waypoint to navigate toward, ``result[-1]`` is the final goal.

    Returns ``[]`` if the goal cell is blocked or no path exists.

    Tolerates the bot drifting into the safety margin: the start
    cell's "blocked" status is ignored so a bot that slipped into
    the cluster can still plan its way out.
    """
    blocked, grid_w, grid_h = _build_grid(state, cell_px)
    start = _cell_of(sx, sy, cell_px)
    goal = _cell_of(gx, gy, cell_px)

    # Bot may have drifted into the safety margin; allow planning out
    # by removing only the start cell's block.
    blocked.discard(start)

    if start == goal:
        # Already in the goal cell — the only waypoint is the
        # precise goal point.
        return [(gx, gy)]

    cell_path = _astar(start, goal, blocked, grid_w, grid_h)
    if not cell_path:
        return []

    # Convert cell path to world coords (cell centres) excluding the
    # start cell.  Replace the final cell-centre with the actual goal
    # so the bot heads to the precise target rather than the cell
    # centre (which can be 40+ px off).
    world_wp = [_world_of(c[0], c[1], cell_px) for c in cell_path[1:]]
    if world_wp:
        world_wp[-1] = (gx, gy)

    # Smooth the path using line-of-sight collapse.  Prepend the
    # start so the smoothing chain considers the bot's actual
    # position when deciding which intermediate waypoints to drop.
    chain = [(sx, sy)] + world_wp
    smoothed = _smooth(chain, blocked, cell_px)
    return smoothed[1:]  # drop the start


def target_reachable(state: dict, sx: float, sy: float,
                     gx: float, gy: float,
                     cell_px: int = ASTAR_CELL_PX) -> bool:
    """Convenience predicate.  Returns ``True`` iff
    ``plan_path(state, sx, sy, gx, gy)`` returns a non-empty list.

    Used by action handlers (``_act_gather``, ``_act_mine``) to
    blacklist genuinely unreachable targets BEFORE the bot pins
    against the cluster's repulsion field for tens of seconds.
    """
    return bool(plan_path(state, sx, sy, gx, gy, cell_px))
