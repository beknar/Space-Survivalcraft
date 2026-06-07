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


class TestBoundaryRepulsionTargetSuppression:
    """Per-axis target-aware suppression — when the goto target is
    within ``BOUNDARY_REPULSION_RANGE_PX`` of a given wall, that
    wall's contribution to the repulsion vector is dropped so the
    bot can intentionally chase an edge-adjacent resource without
    the field fighting the goto.  Caught from 2026-05-09 user
    report: "the bot struggles to reach a resource when the
    resource is close to the edge of the play field."  Mirrors
    the existing per-building target-aware suppression in
    ``building_repulsion``."""

    ZONE = {"world_w": 6400.0, "world_h": 6400.0}

    def test_target_near_west_wall_suppresses_west_axis(self):
        """Target 200 px from west wall: bot at the same x in the
        repulsion zone gets ZERO west-axis push (so the goto
        unobstructed) while other walls still contribute normally."""
        rng = nav.BOUNDARY_REPULSION_RANGE_PX
        # Bot at (300, 3200) — 300 px from west wall, deep in field.
        # Target at (200, 3200) — 200 px from west wall, in field.
        rx, ry = nav.boundary_repulsion(
            {"x": 300.0, "y": 3200.0}, self.ZONE,
            target=(200.0, 3200.0))
        # West axis: suppressed → no eastward push.
        assert rx == pytest.approx(0.0), (
            "Target within west-wall range must suppress west-axis "
            f"repulsion at the bot, got rx={rx}")
        # North/south walls far from target → no contribution at this
        # bot y (3200 is comfortably interior).
        assert ry == pytest.approx(0.0)

    def test_target_far_from_walls_keeps_full_repulsion(self):
        """Target in the world interior (no wall within range) →
        bot gets the same repulsion as if no target was passed."""
        rng = nav.BOUNDARY_REPULSION_RANGE_PX
        # Bot in west-wall field, target in centre.
        rx_no_target, _ = nav.boundary_repulsion(
            {"x": 100.0, "y": 3200.0}, self.ZONE)
        rx_with_target, _ = nav.boundary_repulsion(
            {"x": 100.0, "y": 3200.0}, self.ZONE,
            target=(3200.0, 3200.0))
        assert rx_no_target == pytest.approx(rx_with_target)
        assert rx_with_target > 0.0  # west-wall push still active

    def test_target_near_one_wall_keeps_other_walls_active(self):
        """Bot in a corner.  Target near WEST wall but far from
        SOUTH wall.  West axis is suppressed; south axis keeps its
        full corner-push so the bot doesn't end up sitting in the
        SW corner with no south-edge safety."""
        # Bot at (50, 50) — deep in SW corner.
        # Target at (100, 3200) — near west wall, far from south wall.
        rx, ry = nav.boundary_repulsion(
            {"x": 50.0, "y": 50.0}, self.ZONE,
            target=(100.0, 3200.0))
        # West axis suppressed → no east push.
        assert rx == pytest.approx(0.0)
        # South-wall push still active → strong northward push.
        rng = nav.BOUNDARY_REPULSION_RANGE_PX
        assert ry == pytest.approx(1.0 - 50.0 / rng, abs=0.01)

    def test_default_target_none_preserves_legacy_behaviour(self):
        """Calling without ``target`` (or with ``target=None``)
        keeps the original behaviour — pin the backward compat
        contract for any caller that doesn't yet plumb the kwarg."""
        bot = {"x": 100.0, "y": 100.0}
        a = nav.boundary_repulsion(bot, self.ZONE)
        b = nav.boundary_repulsion(bot, self.ZONE, target=None)
        assert a == b
        # And the value isn't trivial — the SW corner pushes diagonally.
        assert a[0] > 0 and a[1] > 0

    def test_target_at_east_wall_suppresses_east_axis(self):
        """Symmetric pin: east-wall target suppresses east axis."""
        # Bot at (6300, 3200) — 100 px from east wall, in field.
        # Target at (6200, 3200) — 200 px from east wall, in field.
        rx, ry = nav.boundary_repulsion(
            {"x": 6300.0, "y": 3200.0}, self.ZONE,
            target=(6200.0, 3200.0))
        assert rx == pytest.approx(0.0), (
            "Target near east wall must suppress east-axis "
            "repulsion at the bot.")
        assert ry == pytest.approx(0.0)

    def test_steered_heading_passes_target_to_boundary(self):
        """End-to-end: ``steered_heading`` must forward its
        ``target`` kwarg to ``boundary_repulsion``.  Without this
        the user-visible bug (bot can't reach edge-adjacent
        resources) would persist even though the function-level
        suppression works.

        Uses a diagonal goto (both dx and dy non-zero) so the
        axis-aligned angle-flattening doesn't hide the deflection
        — when one axis is suppressed and the other isn't, the
        steered heading rotates along the unsuppressed axis."""
        s = {"zone": self.ZONE, "buildings": []}
        bot = {"x": 300.0, "y": 3000.0}
        # Diagonal goto: heading southwest toward (200, 2900).
        dx, dy = -100.0, -100.0
        dist = 141.42
        # WITHOUT target — the boundary field's east-push deflects
        # the western goto component, bending the heading more
        # southerly (more negative dx contribution → angle skews
        # away from -135° toward -180°).
        h_no_target = nav.steered_heading(s, bot, dx, dy, dist)
        # WITH target near west wall — boundary suppression kicks
        # in on the west axis, so the heading is closer to the
        # untouched diagonal (-135°).
        h_with_target = nav.steered_heading(s, bot, dx, dy, dist,
                                             target=(200.0, 2900.0))
        # The two headings must differ — that's the proof the
        # target kwarg actually flows through.
        assert abs(h_with_target - h_no_target) > 5.0, (
            f"Boundary suppression must change the steered heading "
            f"when the target is edge-adjacent; got "
            f"no_target={h_no_target}, with_target={h_with_target}")
        # The with-target heading should be CLOSER to -135° (the
        # raw goto direction) since the field doesn't fight it.
        assert abs(h_with_target - (-135.0)) < abs(h_no_target - (-135.0))


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

    def test_oscillation_in_50px_box_is_stuck(self):
        """Wall-pin oscillation: bot bouncing between two positions
        ~50 px apart for the full 5 s window has high max-dist but
        zero centroid shift — must be flagged as stuck.  Caught from
        2026-05-09 telemetry: bot wedged in S_MINE for 130 s at the
        left wall, oscillating in a 24×49 px box with rotation
        active (which would have defeated the rotation gate)."""
        # Bot oscillates 75↔105 in x, 4140↔4200 in y for the first
        # 3 s, then settles into a tighter cluster for the last
        # 1.5 s (so the short-window spread gate still classifies
        # the bot as a stuck candidate).  Long-window max-dist
        # exceeds LONG_PROGRESS_PX (oscillation amplitude); centroid
        # of first / second half stays near (90, 4170) → < 15 px
        # shift → oscillation override fires.  Heading rotates fast
        # enough that the rotation gate would normally exempt.
        samples = [
            (0.0, 105.0, 4200.0,   0.0),  # corner A
            (0.5,  75.0, 4140.0,  30.0),  # corner B
            (1.0, 105.0, 4200.0,  60.0),  # A
            (1.5,  75.0, 4140.0,  90.0),  # B
            (2.0, 105.0, 4200.0, 120.0),  # A
            (2.5,  75.0, 4140.0, 150.0),  # B
            (3.0, 105.0, 4200.0, 180.0),  # A — last big swing
            (3.5,  82.0, 4146.0, 210.0),  # tight cluster start
            (4.0,  85.0, 4150.0, 240.0),
            (4.5,  88.0, 4155.0, 270.0),
            (4.8,  90.0, 4158.0, 290.0),
            (5.0,  91.0, 4160.0, 300.0),  # current
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is True, (
            "Wall-pin oscillation must fire stuck even when max-dist "
            "exceeds LONG_PROGRESS_PX — the centroid override "
            "catches oscillation that the original gate missed.")

    def test_genuine_chase_not_stuck_centroid_shift(self):
        """A real chase advances the centroid: first-half samples
        cluster around the start, second-half samples cluster around
        the new position.  Centroid displacement >> threshold so the
        bot is correctly marked not-stuck.  Pins that the new
        oscillation override doesn't false-fire on legitimate chases
        that happen to also have small individual short-window
        spread (e.g. early acceleration ramps)."""
        # Bot creeps from ~(0, 0) to ~(120, 0) over 5 s.  Each
        # sample inches forward; centroid of first half ~ (15, 0),
        # second half ~ (90, 0); centroid shift ~75 px.
        samples = [
            (0.0,   0.0, 0.0, 0.0),
            (0.5,  10.0, 0.0, 0.0),
            (1.0,  20.0, 0.0, 0.0),
            (1.5,  30.0, 0.0, 0.0),
            (2.0,  40.0, 0.0, 0.0),
            (2.5,  60.0, 0.0, 0.0),
            (3.0,  80.0, 0.0, 0.0),
            (3.5,  95.0, 0.0, 0.0),
            (4.0, 105.0, 0.0, 0.0),
            (4.5, 115.0, 0.0, 0.0),
            (4.8, 118.0, 0.0, 0.0),
            (5.0, 120.0, 0.0, 0.0),
        ]
        s = self._stuck_with_history(samples)
        assert nav.detect_stuck(s) is False, (
            "Forward progress with large centroid shift must remain "
            "non-stuck — the oscillation override is gated by the "
            "centroid-shift check.")

    def test_oscillation_partial_history_not_stuck(self):
        """Oscillation override requires the FULL long-history span
        before firing — a fresh post-transition history with only
        2-3 s of samples might naturally show oscillation patterns
        during the velocity ramp.  Pins that the oscillation
        override respects the same span guard the hard-pin override
        uses."""
        # 5 samples spanning only 2 s.  Position bounces ±25 px;
        # max-dist ~50 px > LONG_PROGRESS_PX, but history span is
        # under LONG_HISTORY_S so the override must abstain.
        samples = [
            (0.0,  80.0, 4144.0,   0.0),
            (0.5, 105.0, 4193.0,  20.0),
            (1.0,  82.0, 4148.0,  40.0),
            (1.5, 100.0, 4185.0,  60.0),
            (2.0,  90.0, 4170.0,  90.0),
        ]
        s = self._stuck_with_history(samples)
        # Short-window spread is high (50 px > 25), so the spread
        # gate exits first with "not stuck".  The override never
        # gets a chance to fire — correct behaviour, pinned by this
        # test as an explicit non-fire on partial-history input.
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


# ── Slipspace repulsion (2026-06-06) ──────────────────────────────────


class TestSlipspaceRepulsion:
    """Slipspaces teleport the ship to another slipspace in the same
    zone on collision (radius ~60 px) -- captured flinging the bot
    ~4810 px into the swarm.  The repulsion peels the bot off well
    before the trigger, in EVERY zone (no MAIN short-circuit)."""

    def _state(self, slips):
        return {"zone": {"world_w": 6400.0, "world_h": 6400.0},
                "slipspaces": list(slips)}

    def test_no_slipspaces_returns_zero(self):
        rx, ry = nav.slipspace_repulsion(
            {"x": 3200.0, "y": 3200.0}, self._state([]))
        assert (rx, ry) == (0.0, 0.0)

    def test_pushes_directly_away(self):
        s = self._state([{"x": 3200.0, "y": 3200.0, "radius": 60.0}])
        # Bot west of the slipspace -> pushed further west (-x).
        rx, ry = nav.slipspace_repulsion({"x": 3100.0, "y": 3200.0}, s)
        assert rx < 0.0
        assert ry == pytest.approx(0.0)

    def test_full_strength_at_collision_radius(self):
        s = self._state([{"x": 3200.0, "y": 3200.0, "radius": 60.0}])
        # 60 px east of centre == exactly the radius -> strength 1.0.
        rx, _ry = nav.slipspace_repulsion({"x": 3260.0, "y": 3200.0}, s)
        assert rx == pytest.approx(1.0)

    def test_zero_beyond_outer_range(self):
        s = self._state([{"x": 3200.0, "y": 3200.0, "radius": 60.0}])
        far = 60.0 + nav.SLIPSPACE_REPULSION_RANGE_PX + 50.0
        rx, ry = nav.slipspace_repulsion(
            {"x": 3200.0 + far, "y": 3200.0}, s)
        assert (rx, ry) == (0.0, 0.0)

    def test_fires_in_main_zone_too(self):
        # Unlike return wormholes, slipspaces repulse even in MAIN.
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0,
                      "id": "ZoneID.MAIN"},
             "slipspaces": [{"x": 3200.0, "y": 3200.0, "radius": 60.0}]}
        rx, _ry = nav.slipspace_repulsion({"x": 3100.0, "y": 3200.0}, s)
        assert rx < 0.0

    def test_steered_heading_deflects_around_slipspace(self):
        # Bot driving east; a slipspace just off the path ahead must
        # bend the steered heading away from the pure-east goal.
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0},
             "slipspaces": [{"x": 3280.0, "y": 3230.0, "radius": 60.0}]}
        p = {"x": 3200.0, "y": 3200.0, "heading": 90.0}
        plain = nav.angle_to(100.0, 0.0)
        steered = nav.steered_heading(s, p, 100.0, 0.0, 100.0)
        assert abs(steered - plain) > 1.0
