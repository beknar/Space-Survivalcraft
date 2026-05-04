"""Unit tests pinning the ``bot_autopilot_navigation`` module API.

Companion to ``test_bot_autopilot_fsm.py`` which exercises the same
functions via the ``ap._boundary_repulsion`` re-export shims.  These
tests target the module directly so the seam stays stable: any
future refactor that moves the implementation again must keep the
``boundary_repulsion`` / ``building_repulsion`` / ``steered_heading``
public names + signatures intact.
"""
from __future__ import annotations

import math

import pytest

import bot_autopilot_navigation as nav


# ── Geometry ───────────────────────────────────────────────────────────

class TestAngleTo:
    def test_north(self):
        assert nav.angle_to(0.0, 100.0) == pytest.approx(0.0)

    def test_east(self):
        assert nav.angle_to(100.0, 0.0) == pytest.approx(90.0)

    def test_south(self):
        # math.atan2(0, -1) == pi == 180°
        assert abs(nav.angle_to(0.0, -100.0)) == pytest.approx(180.0)

    def test_west(self):
        assert nav.angle_to(-100.0, 0.0) == pytest.approx(-90.0)


class TestHeadingDelta:
    def test_no_change(self):
        assert nav.heading_delta(45.0, 45.0) == pytest.approx(0.0)

    def test_small_clockwise(self):
        assert nav.heading_delta(45.0, 90.0) == pytest.approx(45.0)

    def test_wrap_around_north(self):
        # 350° -> 10° via north — shortest path is +20°.
        assert nav.heading_delta(350.0, 10.0) == pytest.approx(20.0)

    def test_wrap_around_south(self):
        # 10° -> 350° via north — shortest path is -20°.
        assert nav.heading_delta(10.0, 350.0) == pytest.approx(-20.0)


# ── Boundary repulsion ────────────────────────────────────────────────

class TestBoundaryRepulsion:
    ZONE = {"world_w": 6400.0, "world_h": 6400.0}

    def test_centre_returns_zero(self):
        rx, ry = nav.boundary_repulsion(
            {"x": 3200.0, "y": 3200.0}, self.ZONE)
        assert (rx, ry) == (0.0, 0.0)

    def test_west_edge_pushes_east(self):
        rx, ry = nav.boundary_repulsion(
            {"x": 0.0, "y": 3200.0}, self.ZONE)
        assert rx == pytest.approx(1.0)
        assert ry == pytest.approx(0.0)

    def test_east_edge_pushes_west(self):
        rx, ry = nav.boundary_repulsion(
            {"x": 6400.0, "y": 3200.0}, self.ZONE)
        assert rx == pytest.approx(-1.0)
        assert ry == pytest.approx(0.0)

    def test_corner_pushes_diagonal(self):
        # NW corner — push southeast (+x, -y).
        rx, ry = nav.boundary_repulsion(
            {"x": 0.0, "y": 6400.0}, self.ZONE)
        assert rx == pytest.approx(1.0)
        assert ry == pytest.approx(-1.0)

    def test_half_range_half_strength(self):
        half = nav.BOUNDARY_REPULSION_RANGE_PX * 0.5
        rx, _ry = nav.boundary_repulsion(
            {"x": half, "y": 3200.0}, self.ZONE)
        assert rx == pytest.approx(0.5, abs=0.01)

    def test_no_zone_returns_zero(self):
        assert nav.boundary_repulsion({"x": 0.0, "y": 0.0}, {}) == (0.0, 0.0)

    def test_zero_world_dims_returns_zero(self):
        assert nav.boundary_repulsion(
            {"x": 0.0, "y": 0.0},
            {"world_w": 0, "world_h": 0}) == (0.0, 0.0)


# ── Building repulsion ────────────────────────────────────────────────

class TestBuildingRepulsion:
    def test_no_buildings_returns_zero(self):
        assert nav.building_repulsion(
            {"x": 100.0, "y": 100.0}, {"buildings": []}) == (0.0, 0.0)

    def test_far_building_returns_zero(self):
        # Building 1000 px away — well outside the 80 px range.
        rx, ry = nav.building_repulsion(
            {"x": 1000.0, "y": 0.0},
            {"buildings": [{"x": 0.0, "y": 0.0}]})
        assert (rx, ry) == (0.0, 0.0)

    def test_adjacent_building_pushes_away(self):
        # Ship at (40, 0), building at (0, 0) — push east.
        rx, ry = nav.building_repulsion(
            {"x": 40.0, "y": 0.0},
            {"buildings": [{"x": 0.0, "y": 0.0}]})
        assert rx > 0
        assert ry == pytest.approx(0.0)

    def test_corner_stack(self):
        # Two perpendicular buildings — one west, one south of
        # the ship — should produce a NE push.
        rx, ry = nav.building_repulsion(
            {"x": 50.0, "y": 50.0},
            {"buildings": [
                {"x": 0.0, "y": 50.0},   # west
                {"x": 50.0, "y": 0.0},   # south
            ]})
        assert rx > 0
        assert ry > 0

    def test_centred_on_building_pushes_north_arbitrarily(self):
        rx, ry = nav.building_repulsion(
            {"x": 100.0, "y": 100.0},
            {"buildings": [{"x": 100.0, "y": 100.0}]})
        assert ry > 0


# ── Steered heading ──────────────────────────────────────────────────

class TestSteeredHeading:
    def test_safe_zone_returns_raw_angle(self):
        # Far from edges + no buildings — should return raw angle_to(dx, dy).
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0},
             "buildings": []}
        p = {"x": 3200.0, "y": 3200.0}
        h = nav.steered_heading(s, p, 1000.0, 0.0, 1000.0)
        assert h == pytest.approx(90.0)

    def test_pure_repulsion_fallback_on_cancellation(self):
        # Goto pointing west into the west wall — cancels exactly,
        # so the function falls back to pure repulsion (east).
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0},
             "buildings": []}
        p = {"x": 0.0, "y": 3200.0}
        h = nav.steered_heading(s, p, -100.0, 0.0, 100.0)
        # Pure east repulsion -> heading 90°.
        assert h == pytest.approx(90.0)


# ── Stuck detection ───────────────────────────────────────────────────

class TestRecordPosition:
    def test_appends_quad_with_heading(self):
        clock = [0.0]
        stuck = {"history": [], "escape_until": 0.0, "last_log": 0.0}
        nav.record_position(
            {"x": 100.0, "y": 200.0, "heading": 45.0},
            stuck, lambda: clock[0])
        assert len(stuck["history"]) == 1
        ts, x, y, h = stuck["history"][0]
        assert (x, y, h) == (100.0, 200.0, 45.0)

    def test_evicts_stale_samples(self):
        clock = [0.0]
        stuck = {"history": [], "escape_until": 0.0, "last_log": 0.0}
        # First sample at t=0.
        nav.record_position(
            {"x": 0.0, "y": 0.0, "heading": 0.0},
            stuck, lambda: clock[0])
        # Sample 5 s later — should evict the t=0 sample.
        clock[0] = 5.0
        nav.record_position(
            {"x": 0.0, "y": 0.0, "heading": 0.0},
            stuck, lambda: clock[0])
        assert len(stuck["history"]) == 1
        assert stuck["history"][0][0] == 5.0


class TestDetectStuck:
    def _stuck_with_history(self, samples):
        return {"history": list(samples),
                "escape_until": 0.0, "last_log": 0.0}

    def test_too_few_samples_not_stuck(self):
        s = self._stuck_with_history([(0.0, 0, 0, 0)])
        assert nav.detect_stuck(s) is False

    def test_short_span_not_stuck(self):
        # 5 samples but only spanning 0.5 s — under the 80% gate.
        samples = [(t, 100.0, 100.0, 0.0)
                   for t in (0.0, 0.1, 0.2, 0.3, 0.5)]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is False

    def test_moved_far_not_stuck(self):
        samples = [
            (0.0, 0.0, 0.0, 0.0),
            (0.4, 50.0, 0.0, 0.0),
            (0.8, 100.0, 0.0, 0.0),
            (1.2, 150.0, 0.0, 0.0),
            (1.5, 200.0, 0.0, 0.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is False

    def test_pinned_no_rotation_is_stuck(self):
        samples = [
            (0.0, 100.0, 100.0, 0.0),
            (0.4, 100.0, 100.0, 0.0),
            (0.8, 100.0, 100.0, 0.0),
            (1.2, 100.0, 100.0, 0.0),
            (1.5, 100.0, 100.0, 0.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is True

    def test_rotating_in_place_not_stuck(self):
        # Position is pinned but heading rotates by 90° — actively
        # turning, not stuck.
        samples = [
            (0.0, 100.0, 100.0, 0.0),
            (0.4, 100.0, 100.0, 30.0),
            (0.8, 100.0, 100.0, 60.0),
            (1.2, 100.0, 100.0, 80.0),
            (1.5, 100.0, 100.0, 90.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is False


# ── Ship-clear gates ─────────────────────────────────────────────────

class TestShipClearOfEdges:
    ZONE = {"world_w": 6400.0, "world_h": 6400.0}

    def test_centre_clear(self):
        assert nav.ship_clear_of_edges(
            {"x": 3200.0, "y": 3200.0}, self.ZONE) is True

    def test_at_west_edge_not_clear(self):
        assert nav.ship_clear_of_edges(
            {"x": 100.0, "y": 3200.0}, self.ZONE) is False

    def test_zero_dims_returns_true(self):
        assert nav.ship_clear_of_edges(
            {"x": 0.0, "y": 0.0},
            {"world_w": 0, "world_h": 0}) is True


class TestShipClearOfBuildings:
    def test_no_buildings_clear(self):
        assert nav.ship_clear_of_buildings(
            {"x": 0.0, "y": 0.0}, {"buildings": []}) is True

    def test_adjacent_building_not_clear(self):
        # 50 px from a building — inside the 80 px range.
        assert nav.ship_clear_of_buildings(
            {"x": 50.0, "y": 0.0},
            {"buildings": [{"x": 0.0, "y": 0.0}]}) is False

    def test_far_building_clear(self):
        assert nav.ship_clear_of_buildings(
            {"x": 1000.0, "y": 0.0},
            {"buildings": [{"x": 0.0, "y": 0.0}]}) is True


# ── Escape target ─────────────────────────────────────────────────────

class TestComputeEscapeTarget:
    def test_pinned_west_targets_east(self):
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0},
             "buildings": []}
        p = {"x": 0.0, "y": 3200.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Should head east, away from the west wall.
        assert tx > 100.0
        assert ty == pytest.approx(3200.0)

    def test_no_field_falls_back_to_world_centre(self):
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0},
             "buildings": []}
        # Player at world centre — no field active.
        p = {"x": 3200.0, "y": 3200.0}
        tx, ty = nav.compute_escape_target(s, p)
        assert (tx, ty) == (3200.0, 3200.0)

    def test_target_clamped_inside_world(self):
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0},
             "buildings": []}
        p = {"x": 0.0, "y": 0.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Target stays at least STUCK_WORLD_MARGIN_PX inside.
        assert tx >= nav.STUCK_WORLD_MARGIN_PX
        assert ty >= nav.STUCK_WORLD_MARGIN_PX
        assert tx <= 6400.0 - nav.STUCK_WORLD_MARGIN_PX
        assert ty <= 6400.0 - nav.STUCK_WORLD_MARGIN_PX
