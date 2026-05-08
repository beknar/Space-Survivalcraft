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
