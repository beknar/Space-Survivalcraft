"""Unit tests for ``bot_autopilot_astar`` — grid-based A* pathfinder
used by the bot to route around the station cluster and to detect
unreachable targets up front (before the bot pins against the
building-repulsion field).

The module is pure (no game-state side effects, no Arcade
dependency) so tests can pass synthetic ``state`` dicts directly.
"""
from __future__ import annotations

import math

import pytest

import bot_autopilot_astar as astar


# ── Fixtures ──────────────────────────────────────────────────────────

def _state(zone_w: float = 6400.0, zone_h: float = 6400.0,
           buildings: list | None = None) -> dict:
    """Minimal ``/state``-shaped dict for the planner."""
    return {
        "zone": {"world_w": zone_w, "world_h": zone_h},
        "buildings": list(buildings or []),
    }


def _hs(x: float, y: float) -> dict:
    return {"x": x, "y": y, "building_type": "Home Station"}


# ── Building radius matches constants ────────────────────────────────

class TestBuildingRadiusMatchesConstants:
    """The astar module duplicates ``BUILDING_RADIUS`` rather than
    importing it from ``constants`` so it stays Arcade-free.  Pin
    that the duplicate is in sync with the canonical value."""

    def test_radius_matches_canonical(self):
        from constants import BUILDING_RADIUS
        assert astar.BUILDING_RADIUS_PX == BUILDING_RADIUS


# ── Grid construction ────────────────────────────────────────────────

class TestBuildGrid:
    def test_empty_buildings_yields_no_blocked(self):
        s = _state(buildings=[])
        blocked, gw, gh = astar._build_grid(s)
        assert len(blocked) == 0
        assert gw == 80  # 6400 / 80
        assert gh == 80

    def test_building_blocks_surrounding_cells(self):
        # Single building at world centre.  Block radius =
        # BUILDING_RADIUS (30) + safety (70) = 100.  At cell_px=80,
        # that covers ~2 cells in each direction from the centre.
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        blocked, _, _ = astar._build_grid(s)
        assert len(blocked) > 0
        # Cell containing the building centre must be blocked.
        cx, cy = astar._cell_of(3200.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (cx, cy) in blocked
        # A cell 200 px away is well beyond the 100 px block radius.
        far_cx, far_cy = astar._cell_of(3400.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (far_cx, far_cy) not in blocked

    def test_boundary_opt_in(self):
        """``include_boundary=True`` blocks edge cells; the default
        omits them so ``target_reachable`` doesn't false-flag
        legitimate edge-adjacent pickups."""
        s = _state(buildings=[])
        # Default: no boundary blocking.
        default_blocked, _, _ = astar._build_grid(s)
        assert (0, 40) not in default_blocked
        # Opt-in: boundary cells blocked.
        boundary_blocked, _, _ = astar._build_grid(
            s, include_boundary=True)
        assert (0, 40) in boundary_blocked


# ── A* search ────────────────────────────────────────────────────────

class TestAstar:
    def test_open_world_returns_direct_path(self):
        """No buildings, no walls, no obstacles — A* should just
        connect the two cells along an octile-optimal path."""
        path = astar._astar(
            (10, 10), (20, 20), set(), 80, 80)
        assert len(path) > 0
        assert path[0] == (10, 10)
        assert path[-1] == (20, 20)

    def test_goal_in_blocked_returns_empty(self):
        blocked = {(20, 20)}
        path = astar._astar((10, 10), (20, 20), blocked, 80, 80)
        assert path == []

    def test_walled_world_routes_around(self):
        """A wall of blocked cells separates start from goal — A*
        should find the way around."""
        # Vertical wall at cx=15 from cy=0 to cy=39, with a gap at
        # cy=40 onward.  Start is west, goal is east.
        blocked = {(15, cy) for cy in range(0, 40)}
        path = astar._astar((5, 20), (25, 20), blocked, 80, 80)
        assert path[0] == (5, 20)
        assert path[-1] == (25, 20)
        # Path must go around (no cell in the wall).
        for cell in path:
            assert cell not in blocked

    def test_completely_walled_returns_empty(self):
        """Goal is fully surrounded by blocked cells — no path."""
        # 3×3 box of blocked cells around the goal at (20, 20).
        blocked = set()
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if (dx, dy) == (0, 0):
                    continue
                blocked.add((20 + dx, 20 + dy))
        # Goal cell is open but enclosed.  Diagonals can squeeze
        # through if not blocked, so block them too:
        blocked.add((19, 19))
        blocked.add((19, 21))
        blocked.add((21, 19))
        blocked.add((21, 21))
        path = astar._astar((5, 5), (20, 20), blocked, 80, 80)
        assert path == []


# ── Line-of-sight smoothing ───────────────────────────────────────────

class TestLineOfSight:
    def test_clear_segment_returns_true(self):
        assert astar._line_of_sight(
            (100.0, 100.0), (500.0, 100.0), set()) is True

    def test_blocked_cell_in_segment_returns_false(self):
        # Segment from (100, 100) to (500, 100) passes through cell
        # (3, 1) at cell_px=80 (cell centre 280, 120 — close to the
        # x ≈ 300 part of the line).
        cx, cy = astar._cell_of(300.0, 100.0, astar.ASTAR_CELL_PX)
        blocked = {(cx, cy)}
        assert astar._line_of_sight(
            (100.0, 100.0), (500.0, 100.0), blocked) is False


class TestSmooth:
    def test_two_waypoints_unchanged(self):
        chain = [(0.0, 0.0), (100.0, 0.0)]
        out = astar._smooth(chain, set())
        assert out == chain

    def test_collinear_chain_collapses_to_endpoints(self):
        chain = [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0),
                 (150.0, 0.0), (200.0, 0.0)]
        out = astar._smooth(chain, set())
        assert out[0] == (0.0, 0.0)
        assert out[-1] == (200.0, 0.0)
        # Should drop the colinear intermediates.
        assert len(out) <= 2


# ── plan_path public API ─────────────────────────────────────────────

class TestPlanPath:
    def test_open_world_returns_direct_goal(self):
        s = _state(buildings=[])
        wp = astar.plan_path(s, 1000.0, 1000.0, 2000.0, 2000.0)
        assert len(wp) >= 1
        # Smoothing should collapse to a single waypoint at the goal.
        assert wp[-1] == pytest.approx((2000.0, 2000.0))

    def test_path_routes_around_cluster(self):
        """A cluster of buildings between bot and target — A* must
        route around it and the goal must be the final waypoint."""
        # 3-building cluster at world centre.
        cluster = [
            _hs(3200.0, 3200.0),
            _hs(3260.0, 3200.0),
            _hs(3140.0, 3200.0),
        ]
        s = _state(buildings=cluster)
        wp = astar.plan_path(s, 2000.0, 3200.0, 4400.0, 3200.0)
        assert len(wp) > 0
        # Final waypoint is the precise goal (replaced from cell-
        # centre).
        assert wp[-1] == pytest.approx((4400.0, 3200.0))
        # No intermediate waypoint sits inside a blocked cell —
        # they should route around the cluster.
        blocked, _, _ = astar._build_grid(s)
        for x, y in wp:
            cell = astar._cell_of(x, y, astar.ASTAR_CELL_PX)
            assert cell not in blocked

    def test_unreachable_goal_returns_empty(self):
        """Target wedged inside a building — no path."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        # Goal AT the building centre.
        wp = astar.plan_path(s, 1000.0, 1000.0, 3200.0, 3200.0)
        assert wp == []

    def test_start_in_blocked_zone_still_plans(self):
        """Bot drifted into the safety margin — the planner must
        still produce a path so the bot can navigate OUT."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        # Start cell would normally be blocked because we sit in
        # the building's safety margin.  ``plan_path`` discards
        # the start's blocked status before running A*.
        start_x, start_y = 3260.0, 3200.0  # ~60 px from building
        wp = astar.plan_path(s, start_x, start_y, 5000.0, 3200.0)
        assert len(wp) > 0
        assert wp[-1] == pytest.approx((5000.0, 3200.0))


# ── target_reachable predicate ───────────────────────────────────────

class TestTargetReachable:
    def test_open_world_reachable(self):
        s = _state()
        assert astar.target_reachable(
            s, 1000.0, 1000.0, 5000.0, 5000.0) is True

    def test_target_inside_building_unreachable(self):
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        assert astar.target_reachable(
            s, 1000.0, 1000.0, 3200.0, 3200.0) is False

    def test_pr60_telemetry_scenario_unreachable_pickup(self):
        """Pins the L649 scenario from the 2026-05-07 telemetry:
        bot at (191, 4100) with the station cluster around (390,
        4030) and a pickup wedged inside the cluster.  The
        reachability predicate must return False so the FSM can
        blacklist the pickup immediately rather than pinning the
        bot for 100+ s."""
        cluster = [
            _hs(390.0, 4030.0),
            _hs(390.0, 4090.0),
            _hs(390.0, 4150.0),
            _hs(330.0, 4030.0),
            _hs(450.0, 4030.0),
        ]
        s = _state(buildings=cluster)
        # Pickup wedged at the centre of the cluster (390, 4090).
        # Bot at (191, 4100) — outside the cluster.
        assert astar.target_reachable(
            s, 191.0, 4100.0, 390.0, 4090.0) is False

    def test_edge_adjacent_target_still_reachable(self):
        """Default grid omits boundary blocking — pickups that drift
        near the wall must NOT be flagged unreachable, otherwise
        many legitimate edge-resource scenarios would deadlock."""
        s = _state()
        # Target at (50, 50) is well inside the boundary margin
        # (200 px) but should still be reachable via the open world.
        assert astar.target_reachable(
            s, 3200.0, 3200.0, 50.0, 50.0) is True


# ── goal_radius_px relaxation (docking actions) ──────────────────────

class TestGoalRadiusRelaxation:
    """Pins the dock-radius relaxation: when ``goal_radius_px > 0``
    and the literal goal cell is blocked, ``plan_path`` finds the
    closest free cell within the radius and plans to it.  Caught
    from 2026-05-08 telemetry: bot pinned at (468, 4304) hs_dist=
    318 in both ``deposit`` and ``craft`` states because A* reported
    the HS center cell as unreachable (it IS a building cell) and
    ``_do_goto`` fell through to direct goto, which deadlocked
    against the new fortify-N turret's repulsion field."""

    def test_strict_default_returns_empty_for_blocked_goal(self):
        """Without ``goal_radius_px`` the strict semantics still
        apply — a target wedged in a building is unreachable."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        wp = astar.plan_path(s, 1000.0, 3200.0, 3200.0, 3200.0)
        assert wp == []

    def test_dock_radius_relaxation_finds_nearby_path(self):
        """With ``goal_radius_px=200``, a goal in a building cell
        gets relaxed to a nearby free cell — the bot can plan a
        path that ends within stop-radius of the building."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        wp = astar.plan_path(s, 1000.0, 3200.0, 3200.0, 3200.0,
                             goal_radius_px=200.0)
        assert len(wp) > 0
        # Final waypoint preserves the literal goal (so the bot's
        # stop-radius arrival logic engages naturally).
        assert wp[-1] == pytest.approx((3200.0, 3200.0))

    def test_radius_too_small_still_returns_empty(self):
        """If every cell within ``goal_radius_px`` of the goal is
        also blocked (e.g. a tight cluster surrounding the goal),
        the relaxation can't find a free cell — returns []."""
        # Build a 3×3 cluster around (3200, 3200) so every
        # radius-1 ring cell sits within block radius of some
        # building.  The ring spans cell offsets ±1, i.e. world
        # coords (3120-3280, 3120-3280) — packing 9 buildings
        # ~60 px apart blankets that area.
        cluster = []
        for dx in (-60, 0, 60):
            for dy in (-60, 0, 60):
                cluster.append(_hs(3200.0 + dx, 3200.0 + dy))
        s = _state(buildings=cluster)
        # Even with 80 px (one ring cell) of radius the relaxation
        # finds no free cell — every neighbour is blocked.
        wp = astar.plan_path(s, 1000.0, 3200.0, 3200.0, 3200.0,
                             goal_radius_px=80.0)
        assert wp == []

    def test_telemetry_dock_scenario_resolves(self):
        """2026-05-08 telemetry replay: bot at (468, 4304)
        targeting HS at (389, 3990) with full station cluster +
        fortify ring.  Without dock-radius relaxation the planner
        returns [] (HS center is in a building cell) and the bot
        deadlocks at the fortify-N repulsion field.  With the 200
        px relaxation (matching ``INSTALL_INTERACT_RANGE_PX * 0.8``)
        the planner must return a non-empty path so the bot can
        approach from a clear direction."""
        # Reproduce the cluster: HS + extension chain + 6 turrets.
        cluster = [
            _hs(389.0, 3990.0),                              # Home Station
            {"x": 389.0, "y": 4050.0, "building_type": "Service Module"},
            {"x": 389.0, "y": 4110.0, "building_type": "Power Receiver"},
            {"x": 389.0, "y": 4190.0, "building_type": "Solar Array 2"},
            {"x": 449.0, "y": 4050.0, "building_type": "Repair Module"},
            {"x": 509.0, "y": 4050.0, "building_type": "Basic Crafter"},
            {"x": 329.0, "y": 3990.0, "building_type": "Service Module"},
            {"x": 269.0, "y": 3990.0, "building_type": "Power Receiver"},
            {"x": 189.0, "y": 3990.0, "building_type": "Solar Array 2"},
            {"x": 601.0, "y": 4202.0, "building_type": "Turret 2"},  # Starter NE
            {"x": 177.0, "y": 3778.0, "building_type": "Turret 2"},  # Starter SW
            {"x": 389.0, "y": 4280.0, "building_type": "Turret 2"},  # Fortify N
            {"x": 389.0, "y": 3700.0, "building_type": "Turret 2"},  # Fortify S
            {"x": 177.0, "y": 4202.0, "building_type": "Turret 2"},  # Fortify NW
            {"x": 601.0, "y": 3778.0, "building_type": "Turret 2"},  # Fortify SE
        ]
        s = _state(buildings=cluster)
        # Strict mode: returns [] (HS center is blocked).
        strict = astar.plan_path(s, 468.0, 4304.0, 389.0, 3990.0)
        assert strict == [], (
            "Strict A* must report HS center unreachable so "
            "the test scenario actually exercises the relaxation.")
        # Dock mode: finds a free cell within 200 px and plans to it.
        relaxed = astar.plan_path(
            s, 468.0, 4304.0, 389.0, 3990.0, goal_radius_px=200.0)
        assert len(relaxed) > 0, (
            "Dock-radius relaxation must find a path so the bot "
            "can approach HS from a clear direction.")
        assert relaxed[-1] == pytest.approx((389.0, 3990.0))

    def test_target_reachable_passes_goal_radius_through(self):
        """``target_reachable`` forwards ``goal_radius_px`` so the
        same semantics apply at the FSM level."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        # Strict: HS center unreachable.
        assert astar.target_reachable(
            s, 1000.0, 3200.0, 3200.0, 3200.0) is False
        # Relaxed: reachable within 200 px.
        assert astar.target_reachable(
            s, 1000.0, 3200.0, 3200.0, 3200.0,
            goal_radius_px=200.0) is True


# ── Nearest-free-cell helper ─────────────────────────────────────────

class TestNearestFreeCell:
    def test_returns_none_when_no_radius(self):
        assert astar._nearest_free_cell(
            (10, 10), set(), 80, 80, 0) is None

    def test_finds_immediately_adjacent_when_goal_blocked(self):
        # All 8 neighbours of (10, 10) are free; goal itself blocked.
        blocked = {(10, 10)}
        free = astar._nearest_free_cell(
            (10, 10), blocked, 80, 80, max_radius_cells=2)
        assert free is not None
        # Picked from the radius=1 ring.
        assert max(abs(free[0] - 10), abs(free[1] - 10)) == 1

    def test_returns_none_when_all_blocked(self):
        # Block goal and every cell within radius 2.
        blocked = set()
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                blocked.add((10 + dx, 10 + dy))
        free = astar._nearest_free_cell(
            (10, 10), blocked, 80, 80, max_radius_cells=2)
        assert free is None

    def test_picks_smallest_distance_in_outer_ring(self):
        # Block the entire radius=1 ring; force the helper out to
        # radius=2.  Among the radius=2 ring, the cardinal cells
        # (dx² + dy² = 4) are closer than the corners (8), so the
        # helper must pick a cardinal.
        blocked = {(10, 10)}
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                blocked.add((10 + dx, 10 + dy))
        free = astar._nearest_free_cell(
            (10, 10), blocked, 80, 80, max_radius_cells=2)
        assert free is not None
        dx = free[0] - 10
        dy = free[1] - 10
        # Picks a cardinal-direction radius-2 cell (one axis is 0).
        assert dx == 0 or dy == 0
        assert abs(dx) + abs(dy) == 2
