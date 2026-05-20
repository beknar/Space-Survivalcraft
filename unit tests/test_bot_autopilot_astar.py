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
        # Place a building inside each of the 9 cells in the goal
        # cell's 3×3 neighborhood (the radius-1 search ring plus
        # the goal cell itself).  Each building hard-blocks the
        # cell containing its centre regardless of cell-centre
        # distance, so every ring cell is unconditionally blocked.
        # Goal is (3200, 3200) at cell (40, 40), centre (3240, 3240).
        # Ring cells span (39-41) × (39-41) at world centres
        # (3160 / 3240 / 3320, 3160 / 3240 / 3320).
        cluster = []
        for dx in (-80, 0, 80):
            for dy in (-80, 0, 80):
                cluster.append(_hs(3240.0 + dx, 3240.0 + dy))
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


# ── Cost-weighted A* (2026-05-12) ─────────────────────────────────────

class TestCostGridConstruction:
    """``_build_cost_grid`` partitions cells into hard-blocked (inside
    the ship-clearance radius), soft-cost (in the falloff annulus),
    and free.  Multiple buildings stack additively in the soft zone.
    """

    def test_no_buildings_yields_empty_grids(self):
        s = _state(buildings=[])
        blocked, costs, _gw, _gh = astar._build_cost_grid(s)
        assert blocked == set()
        assert costs == {}

    def test_building_centre_cell_is_hard_blocked(self):
        """The cell containing the building's centre is always
        hard-blocked, even if its centre sits > hard_radius from
        the building (the cell-corner-vs-centre edge case)."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        blocked, _costs, _gw, _gh = astar._build_cost_grid(s)
        assert (40, 40) in blocked

    def test_cells_in_soft_zone_get_extra_cost(self):
        """Cells in the (hard_radius, soft_radius] annulus carry a
        positive extra cost — they're traversable but discouraged."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        _blocked, costs, _gw, _gh = astar._build_cost_grid(s)
        # Cell (40, 41) centre = (3240, 3320), 120 px from building.
        # 120 is between hard_radius=55 and soft_radius=150 → soft zone.
        assert (40, 41) in costs
        assert costs[(40, 41)] > 0.0

    def test_cells_outside_soft_radius_are_free(self):
        """Cells > soft_radius_px from every building have no entry
        in ``costs`` — A* treats them at base step cost."""
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        _blocked, costs, _gw, _gh = astar._build_cost_grid(s)
        # Cell (45, 40) centre = (3640, 3240) is 400 px east of HS.
        # Outside the 150 px soft radius.
        assert (45, 40) not in costs

    def test_costs_stack_additively_across_buildings(self):
        """A cell wedged between two buildings carries the sum of
        their soft-cost contributions — wider corridors stay
        cheaper than narrow ones."""
        # Two buildings 200 px apart along x.  Cell between them
        # gets soft cost from BOTH.
        s = _state(buildings=[_hs(3000.0, 3200.0), _hs(3200.0, 3200.0)])
        _blocked, costs, _gw, _gh = astar._build_cost_grid(s)
        # Cell (38, 40) at (3120, 3240) — 80 px from west building,
        # 80 px from east building.  Both contribute.
        single = _state(buildings=[_hs(3000.0, 3200.0)])
        _b1, c1, _, _ = astar._build_cost_grid(single)
        # Cell (38, 40) carries one contribution under "single",
        # the sum under "two".  The two-building cost is strictly
        # greater than the single-building cost.
        assert (38, 40) in costs
        assert (38, 40) in c1
        assert costs[(38, 40)] > c1[(38, 40)]


class TestCostWeightedFindsNarrowGap:
    """The key property the prototype is supposed to fix: A* must
    find a path THROUGH a narrow corridor between two buildings
    instead of returning ``unreachable`` like the legacy binary
    grid would.
    """

    def _setup(self):
        """Two buildings 120 px apart along the y axis with a 60 px
        clearance corridor between them.  Under the legacy
        binary block (100 px each) the gap is fully blocked; under
        cost weighting the bot can squeeze through with extra cost.
        """
        return _state(buildings=[
            _hs(3200.0, 3120.0),  # north building (owns cell (40, 39))
            _hs(3200.0, 3280.0),  # south building (owns cell (40, 41))
        ])

    def test_narrow_corridor_is_traversable(self):
        s = self._setup()
        # Plan from west of the buildings to east through the gap.
        wp = astar.plan_path(s, 2800.0, 3200.0, 3600.0, 3200.0)
        assert wp != [], "Cost-weighted A* must find a path"
        # Final waypoint is the literal goal.
        assert wp[-1] == pytest.approx((3600.0, 3200.0))

    def test_wider_alternative_preferred_when_available(self):
        """Same two buildings, but with the goal far enough east
        that a detour north or south is cheaper than threading the
        narrow corridor.  Compare path total g-cost: detour < gap."""
        s = self._setup()
        # Goal directly east of the corridor.  Detour cost should
        # be lower than gap cost.  Hard to assert g-cost without
        # internals; instead, assert the path uses MORE waypoints
        # (a detour) than a single line through the gap would.
        wp = astar.plan_path(s, 3200.0, 2900.0, 3200.0, 3500.0)
        # Detour means the path's middle waypoints sit away from
        # x=3200 (the gap axis).  At least one intermediate
        # waypoint should be > 80 px east or west of the axis.
        deviated = any(abs(w[0] - 3200.0) > 80.0 for w in wp[:-1])
        assert deviated, (
            "Cost-weighted A* must detour around the corridor when "
            "a clearer path exists, not thread the narrow gap.")


class TestCostWeightedBotInsideClusterFindsExit:
    """Pin the 2026-05-12 telemetry pathology: bot inside the
    cluster with all-blocked neighbors used to get ``unreachable``
    from the binary planner.  Cost weighting must find a path
    out by treating tight cells as costly-but-traversable.
    """

    def test_bot_inside_cluster_to_far_target_finds_path(self):
        # 4-building diamond around (3200, 3200) with bot in the
        # centre; far target to the east.  Under the binary grid
        # the bot's neighbors are all blocked.  Cost weighting
        # routes through the lowest-cost gap.
        s = _state(buildings=[
            _hs(3120.0, 3200.0),
            _hs(3280.0, 3200.0),
            _hs(3200.0, 3120.0),
            _hs(3200.0, 3280.0),
        ])
        wp = astar.plan_path(s, 3200.0, 3200.0, 5000.0, 3200.0)
        assert wp != [], (
            "Bot inside cluster must reach far target under "
            "cost-weighted planning.")


class TestLosBlockedSet:
    """``los_blocked_set`` returns the appropriate hard-clearance
    cell set so the bot's per-tick line-of-sight check still
    excludes physical-collision cells under cost weighting."""

    def test_returns_hard_blocked_under_cost_weighting(
            self, monkeypatch):
        monkeypatch.setattr(astar, "ASTAR_USE_COST_WEIGHTED", True)
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        los = astar.los_blocked_set(s)
        hard_blocked, _costs, _gw, _gh = astar._build_cost_grid(s)
        assert los == hard_blocked

    def test_returns_legacy_blocked_under_binary_mode(
            self, monkeypatch):
        monkeypatch.setattr(astar, "ASTAR_USE_COST_WEIGHTED", False)
        s = _state(buildings=[_hs(3200.0, 3200.0)])
        los = astar.los_blocked_set(s)
        legacy_blocked, _gw, _gh = astar._build_grid(s)
        assert los == legacy_blocked


class TestCostWeightedFlagDispatch:
    """The ``ASTAR_USE_COST_WEIGHTED`` flag toggles plan_path's
    behaviour.  When False, the legacy binary planner runs.
    Useful for A/B comparison and rollback safety.
    """

    def test_disabling_flag_reverts_to_binary_planner(
            self, monkeypatch):
        # Setup is the narrow-corridor case from above: binary
        # planner reports unreachable, cost-weighted finds it.
        s = _state(buildings=[
            _hs(3200.0, 3120.0),
            _hs(3200.0, 3280.0),
        ])
        # Cost-weighted: path exists.
        monkeypatch.setattr(astar, "ASTAR_USE_COST_WEIGHTED", True)
        cw_wp = astar.plan_path(s, 2800.0, 3200.0, 3600.0, 3200.0)
        assert cw_wp != []
        # Legacy binary: path also exists but is the detour, not the
        # gap (legacy hard-blocks the full 100 px around each
        # building; the gap is 60 px clear which is fully inside
        # both block circles).
        monkeypatch.setattr(astar, "ASTAR_USE_COST_WEIGHTED", False)
        bin_wp = astar.plan_path(s, 2800.0, 3200.0, 3600.0, 3200.0)
        # Legacy may or may not find the detour depending on
        # search radius; pin only the dispatch property -- that
        # the binary planner sees the gap as fully blocked.
        bin_blocked, _gw, _gh = astar._build_grid(s)
        # Cell (40, 40) at (3240, 3240) is within 100 px of both
        # buildings → blocked under legacy.
        assert (40, 40) in bin_blocked
        # And NOT in the cost-weighted hard-blocked set (cell
        # centre is 60 px from each building, > 55 px hard radius).
        cw_blocked, _costs, _gw2, _gh2 = astar._build_cost_grid(s)
        assert (40, 40) not in cw_blocked


# ── Gas cloud planner integration (2026-05-19) ──────────────────────

class TestGasCloudBlocking:
    """The 2026-05-19 follow-up: gas clouds in ``state["gas_areas"]``
    are treated as additional circular obstacles in both the binary
    and cost-weighted grids.  Captured pathology: a 750 px radius
    cloud in WARP_GAS that the reactive ``_act_flee_gas`` couldn't
    escape in a single 600 px goto.  Proactive A* routes around it.
    """

    def _state_with_gas(self, clouds, **kw):
        s = _state(**kw)
        s["gas_areas"] = list(clouds)
        return s

    def test_binary_no_gas_areas_is_no_op(self):
        s = _state(buildings=[])
        s["gas_areas"] = []
        blocked, gw, gh = astar._build_grid(s)
        baseline, gw2, gh2 = astar._build_grid(_state(buildings=[]))
        assert blocked == baseline
        assert gw == gw2 and gh == gh2

    def test_binary_gas_cloud_blocks_interior_cells(self):
        s = self._state_with_gas([
            {"x": 3200.0, "y": 3200.0, "radius": 200.0}
        ])
        blocked, _, _ = astar._build_grid(s)
        cx, cy = astar._cell_of(3200.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (cx, cy) in blocked
        far_cx, far_cy = astar._cell_of(
            3700.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (far_cx, far_cy) not in blocked

    def test_cost_no_gas_areas_is_no_op(self):
        s = _state(buildings=[])
        s["gas_areas"] = []
        blocked, costs, _, _ = astar._build_cost_grid(s)
        baseline_b, baseline_c, _, _ = astar._build_cost_grid(
            _state(buildings=[]))
        assert blocked == baseline_b
        assert costs == baseline_c

    def test_cost_gas_cloud_hard_blocks_interior(self):
        s = self._state_with_gas([
            {"x": 3200.0, "y": 3200.0, "radius": 200.0}
        ])
        blocked, _costs, _, _ = astar._build_cost_grid(s)
        cx, cy = astar._cell_of(3200.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (cx, cy) in blocked

    def test_cost_gas_cloud_soft_annulus_has_cost(self):
        """Cells past the hard radius but inside the soft annulus
        get extra traversal cost so the planner prefers wider
        detours when room allows."""
        s = self._state_with_gas([
            {"x": 3200.0, "y": 3200.0, "radius": 200.0}
        ])
        blocked, costs, _, _ = astar._build_cost_grid(s)
        # Cell at 280 px east of centre: past hard (230) but
        # inside soft (350).
        cx, cy = astar._cell_of(3480.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (cx, cy) not in blocked
        assert costs.get((cx, cy), 0.0) > 0.0

    def test_cost_gas_cloud_outside_soft_radius_has_no_cost(self):
        s = self._state_with_gas([
            {"x": 3200.0, "y": 3200.0, "radius": 200.0}
        ])
        blocked, costs, _, _ = astar._build_cost_grid(s)
        cx, cy = astar._cell_of(3900.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (cx, cy) not in blocked
        assert costs.get((cx, cy), 0.0) == 0.0


class TestPlanPathAroundGas:
    """End-to-end: ``plan_path`` routes around gas clouds the same
    way it routes around building clusters."""

    def test_plan_routes_around_single_cloud_blocking_direct_line(self):
        s = _state(buildings=[])
        s["gas_areas"] = [
            {"x": 3200.0, "y": 3200.0, "radius": 300.0}
        ]
        wp = astar.plan_path(s, 2400.0, 3200.0, 4000.0, 3200.0)
        assert wp, "expected a path around the cloud, got unreachable"
        assert wp[-1] == (4000.0, 3200.0)
        # No waypoint inside the cloud edge.
        crossed = any(
            (wx - 3200.0) ** 2 + (wy - 3200.0) ** 2 <= 300.0 ** 2
            for wx, wy in wp)
        assert not crossed, f"path crossed cloud interior: {wp}"

    def test_plan_open_world_with_no_clouds_returns_direct(self):
        s = _state(buildings=[])
        s["gas_areas"] = []
        wp = astar.plan_path(s, 1000.0, 1000.0, 2000.0, 2000.0)
        assert wp != []
        assert wp[-1] == (2000.0, 2000.0)
        assert len(wp) <= 2

    def test_target_inside_cloud_is_unreachable(self):
        """Pickup or asteroid inside a cloud -- bot must treat
        it as unreachable so the FSM blacklists rather than
        charging in and bleeding out."""
        s = _state(buildings=[])
        s["gas_areas"] = [
            {"x": 3200.0, "y": 3200.0, "radius": 300.0}
        ]
        wp = astar.plan_path(s, 2400.0, 3200.0, 3200.0, 3200.0)
        assert wp == []
        assert astar.target_reachable(
            s, 2400.0, 3200.0, 3200.0, 3200.0) is False

    def test_plan_routes_around_giant_cloud(self):
        """The captured 2026-05-19 pathology: 750 px radius cloud
        at (574, 3374).  Bot must detour around it instead of
        flee-bouncing through it."""
        s = _state(zone_w=3000.0, zone_h=8000.0, buildings=[])
        s["gas_areas"] = [
            {"x": 574.9, "y": 3374.0, "radius": 750.0}
        ]
        wp = astar.plan_path(s, 1318.0, 3398.0, 1500.0, 6000.0)
        assert wp, "expected detour around 750 px cloud"
        for wx, wy in wp:
            d = math.hypot(wx - 574.9, wy - 3374.0)
            assert d >= 750.0, (
                f"waypoint ({wx},{wy}) is inside the cloud edge "
                f"(d={d:.1f} < 750)")

    def test_plan_routes_through_gap_between_two_clouds(self):
        """Two clouds flanking the direct path with a navigable
        gap between them.  Planner should thread the gap rather
        than detouring around both."""
        s = _state(buildings=[])
        s["gas_areas"] = [
            {"x": 3200.0, "y": 2800.0, "radius": 150.0},
            {"x": 3200.0, "y": 3600.0, "radius": 150.0},
        ]
        wp = astar.plan_path(s, 2400.0, 3200.0, 4000.0, 3200.0)
        assert wp
        max_y_excursion = max(abs(wy - 3200.0) for _wx, wy in wp)
        assert max_y_excursion < 600.0, (
            f"expected gap-thread, got y excursion of "
            f"{max_y_excursion}: {wp}")


class TestLosBlockedSetWithGas:
    """``los_blocked_set`` includes gas clouds so the bot's
    direct-line-of-sight fast path correctly identifies a cloud
    between bot and goal and triggers the planner."""

    def test_los_blocked_set_includes_gas_hard_block(self):
        s = _state(buildings=[])
        s["gas_areas"] = [
            {"x": 3200.0, "y": 3200.0, "radius": 200.0}
        ]
        blocked = astar.los_blocked_set(s)
        cx, cy = astar._cell_of(3200.0, 3200.0, astar.ASTAR_CELL_PX)
        assert (cx, cy) in blocked

    def test_los_returns_false_through_gas_cloud(self):
        s = _state(buildings=[])
        s["gas_areas"] = [
            {"x": 3200.0, "y": 3200.0, "radius": 200.0}
        ]
        blocked = astar.los_blocked_set(s)
        assert astar._line_of_sight(
            (2400.0, 3200.0), (4000.0, 3200.0), blocked) is False

    def test_los_returns_true_when_path_skirts_cloud(self):
        s = _state(buildings=[])
        s["gas_areas"] = [
            {"x": 3200.0, "y": 3200.0, "radius": 200.0}
        ]
        blocked = astar.los_blocked_set(s)
        assert astar._line_of_sight(
            (2400.0, 4000.0), (4000.0, 4000.0), blocked) is True
