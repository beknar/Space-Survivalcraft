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
        # Sample past STUCK_DETECT_LONG_HISTORY_S later — should
        # evict the t=0 sample (eviction tracks the long history
        # window so the long-window net-progress gate can run).
        clock[0] = nav.STUCK_DETECT_LONG_HISTORY_S + 1.0
        nav.record_position(
            {"x": 0.0, "y": 0.0, "heading": 0.0},
            stuck, lambda: clock[0])
        assert len(stuck["history"]) == 1
        assert stuck["history"][0][0] == clock[0]


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

    def test_out_and_back_motion_not_stuck(self):
        """The bot drifts 30 px east during the window then rotates
        and drifts 12 px back, ending only 18 px east of its start
        — a legitimate slow-thrust phase.  Endpoint-to-endpoint
        distance (18) is under the 25 px threshold, but spread
        (max excursion = 30) is above it, so the bot must NOT be
        flagged as stuck.  Caught from 2026-05-07 telemetry: three
        back-to-back stuck_detected events in ~6 s while the bot
        was advancing SE at ~50 px/s — each escape burst interrupted
        the chase and produced the heading oscillation users
        reported."""
        samples = [
            (0.0, 100.0, 100.0, 0.0),
            (0.4, 110.0, 100.0, 0.0),
            (0.8, 130.0, 100.0, 5.0),
            (1.2, 125.0, 100.0, 10.0),
            (1.5, 118.0, 100.0, 12.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is False, (
            "Bot reached 30 px from start mid-window — spread is "
            "30 px > 25 px threshold, so the watchdog must not "
            "false-fire on the 18 px endpoint distance.")

    def test_small_spread_under_threshold_is_stuck(self):
        """Pinned with sub-threshold jitter (positions all within a
        12 px box) AND sub-threshold rotation — this is the genuine
        pin signature the watchdog must still catch.  Spread metric
        must not be so loose it misses a real pin."""
        samples = [
            (0.0, 100.0, 100.0, 0.0),
            (0.4, 102.0, 103.0, 1.0),
            (0.8, 105.0, 100.0, 2.0),
            (1.2, 100.0, 105.0, 1.0),
            (1.5, 103.0, 102.0, 0.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is True

    def test_long_window_progress_overrides_short_spread(self):
        """Even when the last 1.5 s shows tight spread + low
        rotation, a sample > LONG_PROGRESS_PX away in the longer
        history rules the bot 'making progress'.  Caught from
        2026-05-07 telemetry: 4.7 s after ``idle_at_base→hunt`` the
        bot had moved 48 px from the idle anchor (avg 10 px/s) but
        the most recent 1.5 s only showed ~21 px of spread because
        of the velocity ramp-up + station-cluster repulsion cross-
        currents.  Endpoint distance was 48, spread was 21, and the
        watchdog mis-fired three stuck events within 60 s.  The
        long-window gate must filter this case as 'making progress'.
        """
        # 5 s of samples: bot creeps from (317, 3875) at idle anchor
        # to (365, 3861) at the moment of the would-be stuck event.
        # Last 1.5 s: positions tightly clustered around (358-365,
        # 3861-3863) with rotation < 30°.  Long history: spans 48 px
        # of net displacement.
        samples = [
            (0.0, 317.0, 3875.0, 0.0),
            (1.0, 330.0, 3870.0, 5.0),
            (2.0, 345.0, 3866.0, 8.0),
            (3.5, 358.0, 3863.0, 10.0),
            (4.0, 360.0, 3862.0, 11.0),
            (4.4, 362.0, 3861.5, 11.5),
            (4.7, 365.0, 3861.0, 12.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is False, (
            "Bot has moved 50 px from the idle anchor over 4.7 s "
            "— long-window progress gate must override the tight "
            "short-window spread.")

    def test_hard_pin_overrides_rotation_gate(self):
        """Bot pinned at one position for the full 5 s window with
        the heading rotating > 30°/window — the rotation gate would
        normally exempt the bot, but the hard-pin override fires
        because there's zero translation.  Caught from 2026-05-07
        telemetry: bot deadlocked in S_GATHER for 100+ s at exactly
        (160, 4083) while the steered heading fluttered under
        building-repulsion cross-currents."""
        # 5 s of samples all clustered within 4 px of (160, 4083),
        # heading sweeping 0° → 60° (rotation_total > 30°).  Extra
        # samples in the last 1.5 s subset to clear the short-window
        # ``len < 5`` gate.
        samples = [
            (0.0, 160.0, 4083.0, 0.0),
            (1.0, 161.0, 4083.0, 12.0),
            (2.0, 160.0, 4084.0, 24.0),
            (3.0, 162.0, 4082.0, 36.0),
            (3.6, 161.0, 4083.0, 42.0),
            (3.9, 160.0, 4084.0, 46.0),
            (4.2, 162.0, 4082.0, 50.0),
            (4.5, 161.0, 4083.0, 54.0),
            (4.8, 160.0, 4084.0, 57.0),
            (5.0, 160.0, 4083.0, 60.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is True, (
            "Bot pinned within 4 px for the full 5 s window — "
            "rotation gate must NOT exempt a hard pin.")

    def test_partial_history_does_not_trigger_hard_pin(self):
        """Hard-pin requires the FULL long-history window to be
        accumulated.  A bot that just transitioned (history span
        only 1.5 s) and is rotating must still be exempted by the
        rotation gate — otherwise the override would false-fire on
        legitimate post-transition rotations."""
        samples = [
            (0.0, 100.0, 100.0, 0.0),
            (0.4, 100.0, 100.0, 30.0),
            (0.8, 100.0, 100.0, 60.0),
            (1.2, 100.0, 100.0, 80.0),
            (1.5, 100.0, 100.0, 100.0),
        ]
        s = self._stuck_with_history(samples)
        # Span is 1.5 s, well under the 5 s long-history window.
        # Hard-pin must not fire; rotation gate exempts.
        assert nav.detect_stuck(s) is False

    def test_pinned_for_full_long_window_is_stuck(self):
        """The opposite of the above: bot has been pinned in a
        small region for the entire 5 s long-window, so neither
        the short-window spread nor the long-window progress gate
        finds escape — the watchdog must still fire.  Pins the
        long-window gate doesn't accidentally over-suppress real
        pins."""
        samples = [
            (0.0, 100.0, 100.0, 0.0),
            (1.0, 105.0, 102.0, 1.0),
            (2.0, 100.0, 105.0, 2.0),
            (3.0, 103.0, 100.0, 1.0),
            (3.5, 102.0, 102.0, 1.5),
            (3.8, 100.0, 103.0, 2.0),
            (4.2, 105.0, 100.0, 1.0),
            (4.6, 100.0, 105.0, 1.5),
            (5.0, 102.0, 102.0, 0.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is True


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


# ── Wall + cluster trap escape (2026-05-06 follow-up #6) ──────────────

class TestComputeEscapeTargetWallClusterTrap:
    """Pins the wall+cluster trap escape: when the bot is inside
    ``STUCK_ESCAPE_CLEAR_MARGIN_PX`` of a world edge AND the
    building cluster's centroid sits between the bot and the
    world interior on that axis, ``compute_escape_target`` must
    return a target ALONG the wall tangent (away from the cluster
    centroid) instead of the legacy gradient/world-centre target
    which the cluster physically blocks.

    Caught from 2026-05-06 follow-up #6 telemetry: bot frozen at
    exactly (48.0, 3983.8) in S_HUNT for 117+ seconds while
    ``stuck_detected`` fired and escape mode kept computing
    targets the cluster blocked.
    """

    ZONE = {"zone": {"world_w": 6400.0, "world_h": 6400.0}}

    def test_west_wall_cluster_inland_uses_y_tangent(self):
        """Bot at west wall, cluster centroid at higher px (inland).
        Escape must move along ±y, NOT toward the cluster (+x)."""
        s = {**self.ZONE, "buildings": [
            {"x": 290.0, "y": 3984.0, "building_type": "Home Station"},
            {"x": 200.0, "y": 3950.0, "building_type": "Service Module"},
            {"x": 380.0, "y": 4020.0, "building_type": "Service Module"},
        ]}
        p = {"x": 48.0, "y": 3984.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Target stays at the wall x-coordinate (no +x push into cluster).
        assert abs(tx - 48.0) < 1.0, (
            f"Tangent escape must NOT push the bot into the cluster — "
            f"got tx={tx}, expected px={p['x']}.")
        # Target moves significantly in y (along the wall).
        assert abs(ty - p["y"]) > 100.0, (
            f"Tangent escape must produce significant y-displacement — "
            f"got ty={ty}, py={p['y']}.")

    def test_east_wall_cluster_inland_uses_y_tangent(self):
        """Mirror of the west case for the east wall."""
        s = {**self.ZONE, "buildings": [
            {"x": 6110.0, "y": 3984.0, "building_type": "Home Station"},
            {"x": 6200.0, "y": 3950.0, "building_type": "Service Module"},
        ]}
        p = {"x": 6352.0, "y": 3984.0}
        tx, ty = nav.compute_escape_target(s, p)
        assert abs(tx - 6352.0) < 1.0
        assert abs(ty - p["y"]) > 100.0

    def test_south_wall_cluster_inland_uses_x_tangent(self):
        """Bot at south wall (low py), cluster centroid at higher
        py.  Tangent direction is ±x."""
        s = {**self.ZONE, "buildings": [
            {"x": 3200.0, "y": 290.0, "building_type": "Home Station"},
            {"x": 3150.0, "y": 200.0, "building_type": "Service Module"},
        ]}
        p = {"x": 3200.0, "y": 48.0}
        tx, ty = nav.compute_escape_target(s, p)
        assert abs(ty - 48.0) < 1.0
        assert abs(tx - p["x"]) > 100.0

    def test_tangent_direction_picks_away_from_cluster_in_y(self):
        """West-wall scenario with cluster ABOVE the bot's y → bot
        should slide DOWN (-y), not up.  This is the disambiguating
        rule: tangent sign should move the bot AWAY from the
        cluster's y centroid.  Bot is positioned within the
        cluster's lateral extent so the wall-tangent gate fires
        (otherwise the legacy gradient handles it without picking
        a y direction)."""
        s = {**self.ZONE, "buildings": [
            {"x": 290.0, "y": 4500.0, "building_type": "Home Station"},
            {"x": 290.0, "y": 4400.0, "building_type": "Service Module"},
        ]}
        # Bot just below the cluster centroid (cy ≈ 4450, r ≈ 50,
        # extent = r + 150 = 200).  py=4350 is 100 px below cy —
        # still within extent 200, so wall-tangent fires.
        p = {"x": 48.0, "y": 4350.0}
        tx, ty = nav.compute_escape_target(s, p)
        assert ty < p["y"], (
            f"Cluster is north of bot — tangent must go SOUTH; "
            f"got ty={ty}, py={p['y']}.")

    def test_bot_outside_cluster_lat_extent_falls_to_gradient(self):
        """Wall-tangent must NOT fire when the bot is far above /
        below / left / right of the cluster on the wall-parallel
        axis — the cluster doesn't actually block the inland path
        from that y / x.  Caught from 2026-05-07 telemetry: bot
        oscillated at (370, 4542) for 50+ s with the station
        cluster centred near (390, 4030).  cluster_cx>px (≈ 390>370)
        gated wall-tangent on, but py was 500+ px above the cluster,
        so going east at that y had no obstruction — the bot should
        fall through to the legacy gradient (which targets due east
        from there) and exit the wall margin promptly."""
        s = {**self.ZONE, "buildings": [
            {"x": 390.0, "y": 4030.0, "building_type": "Home Station"},
            {"x": 410.0, "y": 4040.0, "building_type": "Service Module"},
            {"x": 370.0, "y": 4020.0, "building_type": "Service Module"},
        ]}
        # Bot 500+ px above the cluster, near west wall.
        p = {"x": 370.0, "y": 4542.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Tangent would have produced (370, py±1000); the gradient
        # produces (px + ~1000, py).  Assert the gradient outcome:
        # significant +x displacement, near-zero y change.
        assert tx > p["x"] + 100.0, (
            f"Cluster does not block inland east at this y — "
            f"gradient must push +x; got tx={tx}, px={p['x']}.")
        assert abs(ty - p["y"]) < 50.0, (
            f"No wall-tangent → escape target's y should match "
            f"the bot's; got ty={ty}, py={p['y']}.")

    def test_no_buildings_falls_back_to_legacy_gradient(self):
        """The wall-tangent path is gated on actual buildings
        existing.  An empty cluster with bot at wall must keep
        the legacy boundary-gradient behaviour (head into the
        world)."""
        s = {**self.ZONE, "buildings": []}
        p = {"x": 0.0, "y": 3200.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Legacy gradient still pushes the bot east.
        assert tx > 100.0, (
            f"Wall-tangent must NOT activate without buildings — "
            f"legacy gradient should still move bot east; got tx={tx}.")

    def test_cluster_outside_inland_keeps_legacy_gradient(self):
        """Bot at west wall, cluster centroid at LOWER px (between
        bot and the wall).  Cluster doesn't block the inland path,
        so legacy gradient (push +x toward interior) applies."""
        s = {**self.ZONE, "buildings": [
            # Cluster sits at the wall itself, not inland.
            {"x": 30.0, "y": 3984.0, "building_type": "Home Station"},
        ]}
        p = {"x": 100.0, "y": 3984.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Cluster cx (30) < px (100) — cluster is NOT inland of bot.
        # Legacy gradient should fire (boundary push +x).
        assert tx > p["x"], (
            f"Cluster behind bot, not inland — tangent must NOT "
            f"override the gradient; got tx={tx}, px={p['x']}.")

    def test_corner_pin_skips_wall_tangent(self):
        """2026-05-06 follow-up #8: when the bot is in TWO wall
        margins (corner pin), the wall-tangent escape must NOT
        fire — its tangent along wall A points perpendicular,
        which is toward wall B at a corner.  Caught from telemetry
        showing the bot wedged in the SE corner for 145+ s while
        the wall-tangent target pointed due south into the south
        wall.

        At a corner, the legacy gradient + world-centre fallback's
        diagonal direction is the only escape that exits both
        walls simultaneously.  This test pins the SE corner case:
        bot at (px=6003, py=480) with cluster at NW — the result
        must NOT be due-south (wall-tangent's pick) but a diagonal
        target (world centre) that pulls the bot NW.
        """
        s = {**self.ZONE, "buildings": [
            {"x": 200.0, "y": 4000.0, "building_type": "Home Station"},
            {"x": 250.0, "y": 3950.0, "building_type": "Service Module"},
        ]}
        # SE corner: px in east margin, py in south margin.
        p = {"x": 6003.0, "y": 480.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Wall-tangent for east wall would have produced (6003, 200)
        # or similar — same px, way south.  The corner-skip must
        # produce a target that's NOT pinned at the wall x AND
        # NOT due south.  World-centre fallback gives (3200, 3200).
        assert tx < p["x"] - 100.0, (
            f"Corner escape must move bot AWAY from east wall; "
            f"got tx={tx}, px={p['x']}.")
        assert ty > p["y"] + 100.0, (
            f"Corner escape must move bot AWAY from south wall; "
            f"got ty={ty}, py={p['y']}.")

    def test_corner_pin_skips_wall_tangent_nw_corner(self):
        """Mirror of the SE corner test for the NW corner."""
        s = {**self.ZONE, "buildings": [
            {"x": 6200.0, "y": 2400.0, "building_type": "Home Station"},
        ]}
        p = {"x": 400.0, "y": 5950.0}
        tx, ty = nav.compute_escape_target(s, p)
        # Diagonal toward interior — both axes move TOWARD centre.
        assert tx > p["x"] + 100.0
        assert ty < p["y"] - 100.0

    def test_single_wall_pin_still_uses_tangent(self):
        """Regression: the corner-skip must NOT disable wall-tangent
        for genuine single-wall pins.  Bot at the west wall but
        well clear of north/south margins keeps the PR #42 tangent
        behaviour."""
        s = {**self.ZONE, "buildings": [
            {"x": 290.0, "y": 3984.0, "building_type": "Home Station"},
        ]}
        # Single wall: only near west, far from north/south.
        p = {"x": 48.0, "y": 3984.0}
        tx, ty = nav.compute_escape_target(s, p)
        # PR #42 wall-tangent: tx stays at the wall, ty moves a lot.
        assert abs(tx - 48.0) < 1.0, (
            "Single-wall pin must still use wall-tangent — "
            "tx should stay at the wall.")
        assert abs(ty - p["y"]) > 100.0


class TestBuildingClusterCentroid:
    """Helper used by the wall+cluster escape path."""

    def test_no_buildings_returns_fallback(self):
        cx, cy = nav._building_cluster_centroid(
            {"buildings": []}, fallback=(123.0, 456.0))
        assert (cx, cy) == (123.0, 456.0)

    def test_single_building_returns_its_position(self):
        cx, cy = nav._building_cluster_centroid(
            {"buildings": [{"x": 200.0, "y": 300.0}]},
            fallback=(0.0, 0.0))
        assert (cx, cy) == (200.0, 300.0)

    def test_multiple_buildings_returns_arithmetic_mean(self):
        cx, cy = nav._building_cluster_centroid(
            {"buildings": [
                {"x": 100.0, "y": 100.0},
                {"x": 200.0, "y": 300.0},
                {"x": 300.0, "y": 200.0},
            ]},
            fallback=(0.0, 0.0))
        assert cx == pytest.approx(200.0)
        assert cy == pytest.approx(200.0)
