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


# ── Cost-weighted A* (2026-05-12) ───────────────────────────────────────
#
# Replaces the binary blocked/free grid with a per-cell traversal cost.
# Solves a class of bugs where the previous binary grid reported the
# target ``unreachable`` from a blocked start cell whose neighbors
# were also all blocked (the gap between station body and turret
# ring, telemetered repeatedly in 2026-05-12 logs).  Under cost
# weighting the planner ALWAYS finds a path; it just prefers wide
# corridors and falls back to tight gaps with high cost.
#
# Layering:
#
#  * ``ASTAR_HARD_BLOCK_RADIUS_PX`` (55 px = 30 building + 25 ship
#    physical clearance): cells with a building centre within this
#    distance are HARD-blocked.  The ship physically cannot occupy
#    them.  Line-of-sight smoothing still uses this set.
#  * ``ASTAR_SOFT_COST_RADIUS_PX`` (150 px = building-repulsion
#    range): cells in the soft annulus get graduated extra cost.
#    Quadratic falloff from ``ASTAR_SOFT_COST_MAX`` at the hard
#    radius down to 0 at the soft radius.  Multiple buildings in
#    range stack additively (a cell wedged between two turrets is
#    twice as costly as next to one).
#  * Cells outside the soft radius have 0 extra cost; A* runs as
#    normal there.
#
# The flag ``ASTAR_USE_COST_WEIGHTED`` defaults to True.  Setting it
# False reverts to the legacy binary grid for A/B comparison; existing
# unit tests run under both modes by parametrizing the flag.
ASTAR_USE_COST_WEIGHTED: bool = True
ASTAR_HARD_BLOCK_RADIUS_PX: float = 55.0
ASTAR_SOFT_COST_RADIUS_PX: float = 150.0
ASTAR_SOFT_COST_MAX: float = 8.0


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


def _build_cost_grid(state: dict, cell_px: int = ASTAR_CELL_PX,
                     hard_radius_px: float = ASTAR_HARD_BLOCK_RADIUS_PX,
                     soft_radius_px: float = ASTAR_SOFT_COST_RADIUS_PX,
                     soft_cost_max: float = ASTAR_SOFT_COST_MAX,
                     include_boundary: bool = False,
                     boundary_margin_px: float = ASTAR_BOUNDARY_MARGIN_PX
                     ) -> tuple[set[tuple[int, int]],
                                dict[tuple[int, int], float],
                                int, int]:
    """Build the cost-weighted grid.

    Returns ``(blocked, costs, grid_w, grid_h)``:

    * ``blocked``: HARD-blocked cells where a building centre is
      within ``hard_radius_px`` of the cell centre.  These are
      physically impassable and used both by A* and the line-of-
      sight check.
    * ``costs``: ``dict[(cx, cy), float]`` mapping cells in the
      soft annulus (``hard_radius_px < d <= soft_radius_px``) to
      an extra traversal cost.  Cost falls off quadratically from
      ``soft_cost_max`` at the inner edge to 0 at the outer edge.
      Multiple buildings stack additively.
    * ``grid_w, grid_h``: cell grid dimensions.

    The hard radius is calibrated to the ship's physical collision
    (``BUILDING_RADIUS_PX`` + ~25 px ship hitbox), not the legacy
    binary block's 100 px (which conflated "ship can't fit" with
    "the repulsion field is strong here").  Paths through tight
    gaps are now findable; the field's continued role is to keep
    the bot from clipping during high-speed transit.
    """
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400.0) or 6400.0)
    world_h = float(zone.get("world_h", 6400.0) or 6400.0)
    grid_w = int(math.ceil(world_w / cell_px))
    grid_h = int(math.ceil(world_h / cell_px))
    blocked: set[tuple[int, int]] = set()
    costs: dict[tuple[int, int], float] = {}

    if include_boundary:
        margin_cells = int(math.ceil(boundary_margin_px / cell_px))
        if margin_cells > 0:
            for cx in range(grid_w):
                for cy in range(grid_h):
                    if (cx < margin_cells or cx >= grid_w - margin_cells
                            or cy < margin_cells
                            or cy >= grid_h - margin_cells):
                        blocked.add((cx, cy))

    hard_sq = hard_radius_px * hard_radius_px
    soft_sq = soft_radius_px * soft_radius_px
    soft_span = soft_radius_px - hard_radius_px
    for b in (state.get("buildings") or []):
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        radius_cells = int(math.ceil(soft_radius_px / cell_px)) + 1
        cx0, cy0 = _cell_of(bx, by, cell_px)
        # Always hard-block the cell containing the building's
        # centre, even if its centre happens to sit > hard_radius
        # from the building (a building at a cell corner can be
        # 56.6 px from the cell centre with a 55 px hard radius;
        # without this explicit step the building's own cell would
        # be "traversable" and ``target_reachable`` would falsely
        # report an inside-building target as reachable).
        if 0 <= cx0 < grid_w and 0 <= cy0 < grid_h:
            blocked.add((cx0, cy0))
            costs.pop((cx0, cy0), None)
        for cx in range(cx0 - radius_cells, cx0 + radius_cells + 1):
            if not (0 <= cx < grid_w):
                continue
            for cy in range(cy0 - radius_cells, cy0 + radius_cells + 1):
                if not (0 <= cy < grid_h):
                    continue
                wx, wy = _world_of(cx, cy, cell_px)
                d_sq = (wx - bx) ** 2 + (wy - by) ** 2
                if d_sq <= hard_sq:
                    blocked.add((cx, cy))
                    # Drop any soft cost already recorded — hard
                    # block subsumes it.
                    costs.pop((cx, cy), None)
                elif d_sq <= soft_sq:
                    if (cx, cy) in blocked:
                        continue
                    d = math.sqrt(d_sq)
                    t = (d - hard_radius_px) / soft_span
                    # Quadratic falloff: max cost at the hard edge,
                    # 0 at the soft edge.  Stacks additively across
                    # overlapping buildings.
                    extra = soft_cost_max * (1.0 - t) * (1.0 - t)
                    costs[(cx, cy)] = costs.get((cx, cy), 0.0) + extra
    return blocked, costs, grid_w, grid_h


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


def los_blocked_set(state: dict, cell_px: int = ASTAR_CELL_PX
                    ) -> set[tuple[int, int]]:
    """Return the hard-blocked cell set used by line-of-sight
    smoothing + the bot's per-tick LoS fast-path check.

    Under cost weighting (``ASTAR_USE_COST_WEIGHTED=True``) this is
    the cells inside ``ASTAR_HARD_BLOCK_RADIUS_PX`` of any
    building -- the tight physical-clearance set.  Under the
    legacy binary mode it's the wider ``BUILDING_RADIUS_PX +
    ASTAR_SAFETY_MARGIN_PX`` block set.
    """
    if ASTAR_USE_COST_WEIGHTED:
        blocked, _costs, _gw, _gh = _build_cost_grid(state, cell_px)
        return blocked
    blocked, _gw, _gh = _build_grid(state, cell_px)
    return blocked


def _astar_cost(start: tuple[int, int], goal: tuple[int, int],
                blocked: set[tuple[int, int]],
                costs: dict[tuple[int, int], float],
                grid_w: int, grid_h: int
                ) -> list[tuple[int, int]]:
    """Cost-weighted A* over the cell grid.

    Cells in ``blocked`` are infinite cost (impassable).  Cells in
    ``costs`` contribute ``base_step_cost + costs[cell]`` when
    entered.  Cells not in either dict cost their base step cost
    only.  Returns the cell path (inclusive of start + goal) or
    ``[]`` if no path exists.

    Same start-cell tolerance as the binary variant: a blocked
    start cell is permitted so a bot that drifted inside a
    building's hard radius can plan its way out.  The goal cell's
    blocked status is still decisive.
    """
    if start == goal:
        return [start]
    if goal in blocked:
        return []

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
        for dx, dy, step in _NEIGHBOR_OFFSETS:
            nbr = (current[0] + dx, current[1] + dy)
            if nbr in visited or nbr in blocked:
                continue
            if not (0 <= nbr[0] < grid_w and 0 <= nbr[1] < grid_h):
                continue
            move_cost = step + costs.get(nbr, 0.0)
            tentative = cur_g + move_cost
            if tentative < g_score.get(nbr, float("inf")):
                came_from[nbr] = current
                g_score[nbr] = tentative
                heapq.heappush(
                    open_heap,
                    (tentative + _heuristic(nbr, goal), counter, nbr))
                counter += 1
    return []


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

def _nearest_free_cell(goal: tuple[int, int],
                       blocked: set[tuple[int, int]],
                       grid_w: int, grid_h: int,
                       max_radius_cells: int
                       ) -> tuple[int, int] | None:
    """Find the free grid cell closest (by octile distance) to
    ``goal``, scanning outward up to ``max_radius_cells``.  Used
    when the literal goal cell is blocked but the caller's intent
    is to be *near* the goal (docking actions with a stop_radius).

    Returns ``None`` if every cell within the search radius is
    either blocked or out of bounds.
    """
    if max_radius_cells <= 0:
        return None
    # Breadth-first ring expansion: r=1 first, then r=2, ...
    # Within each ring we pick the cell with smallest Euclidean
    # distance to the literal goal so the chosen waypoint is the
    # most natural "approach point".
    for r in range(1, max_radius_cells + 1):
        best = None
        best_dist_sq = float("inf")
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                # Only consider the ring perimeter on this iteration;
                # interior rings were searched in earlier passes.
                if abs(dx) != r and abs(dy) != r:
                    continue
                cx = goal[0] + dx
                cy = goal[1] + dy
                if not (0 <= cx < grid_w and 0 <= cy < grid_h):
                    continue
                if (cx, cy) in blocked:
                    continue
                d_sq = dx * dx + dy * dy
                if d_sq < best_dist_sq:
                    best_dist_sq = d_sq
                    best = (cx, cy)
        if best is not None:
            return best
    return None


def plan_path(state: dict, sx: float, sy: float, gx: float, gy: float,
              cell_px: int = ASTAR_CELL_PX,
              goal_radius_px: float = 0.0
              ) -> list[tuple[float, float]]:
    """Plan a path from ``(sx, sy)`` to ``(gx, gy)`` through the
    building-blocked grid built from ``state``.  Returns a list of
    ``(x, y)`` waypoints in world coordinates.

    The list **excludes** the start and **includes** the goal —
    callers walk the list head-first; ``result[0]`` is the immediate
    waypoint to navigate toward, ``result[-1]`` is the final goal.

    Returns ``[]`` if the goal cell is blocked AND no free cell
    within ``goal_radius_px`` of the goal is reachable, OR if no
    path exists at all.

    ``goal_radius_px > 0`` switches the planner from strict
    cell-exact reachability to *near*-the-goal reachability — when
    the goal cell itself is blocked (e.g. the bot is asked to dock
    with a building, whose centre is necessarily inside a blocked
    cell), the planner finds the nearest free cell within the
    radius and plans a path to that cell instead, with the literal
    goal still appearing as the final waypoint so the bot's stop-
    radius arrival logic engages naturally.  Used by docking
    actions (``_act_at_station``, install/craft/deposit) where the
    intent is "be within stop_radius of the building", not "stand
    on the building".

    Pickup / asteroid reachability checks pass
    ``goal_radius_px = 0`` (the default) and keep the strict
    behaviour: a target wedged inside a building cell is treated
    as unreachable so the FSM can blacklist it.

    Tolerates the bot drifting into the safety margin: the start
    cell's "blocked" status is ignored so a bot that slipped into
    the cluster can still plan its way out.
    """
    if ASTAR_USE_COST_WEIGHTED:
        blocked, costs, grid_w, grid_h = _build_cost_grid(state, cell_px)
    else:
        blocked, grid_w, grid_h = _build_grid(state, cell_px)
        costs = {}
    start = _cell_of(sx, sy, cell_px)
    goal = _cell_of(gx, gy, cell_px)

    # Bot may have drifted into the safety margin; allow planning out
    # by removing only the start cell's block.  (Under cost weighting
    # the hard radius is tighter, but the same tolerance still
    # applies when the bot clips a wall during high-speed transit.)
    blocked.discard(start)

    # Goal-cell-blocked relaxation for docking actions.  The literal
    # goal stays in ``world_wp[-1]`` regardless — only the A* pathing
    # target is shifted to a nearby free cell.
    if goal in blocked:
        if goal_radius_px <= 0.0:
            return []
        radius_cells = int(math.ceil(goal_radius_px / cell_px))
        free = _nearest_free_cell(goal, blocked, grid_w, grid_h,
                                  radius_cells)
        if free is None:
            return []
        goal = free

    if start == goal:
        # Already in the (possibly relaxed) goal cell — the only
        # waypoint is the precise literal goal point.
        return [(gx, gy)]

    if ASTAR_USE_COST_WEIGHTED:
        cell_path = _astar_cost(start, goal, blocked, costs,
                                grid_w, grid_h)
    else:
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
                     cell_px: int = ASTAR_CELL_PX,
                     goal_radius_px: float = 0.0) -> bool:
    """Convenience predicate.  Returns ``True`` iff
    ``plan_path(state, sx, sy, gx, gy, goal_radius_px=...)``
    returns a non-empty list.

    Used by action handlers (``_act_gather``, ``_act_mine``) to
    blacklist genuinely unreachable targets BEFORE the bot pins
    against the cluster's repulsion field for tens of seconds.
    Default ``goal_radius_px=0`` keeps strict cell-exact
    semantics; pass a positive value to relax to "reachable
    within radius" semantics for docking-style intents.
    """
    return bool(plan_path(state, sx, sy, gx, gy,
                          cell_px, goal_radius_px))
