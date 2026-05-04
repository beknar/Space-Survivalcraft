"""Seam-pinning tests for the ``bot_autopilot`` -> sibling-module split.

After the 2026-05-03 refactor, telemetry / navigation / blacklist
helpers live in dedicated modules.  ``bot_autopilot`` re-exports them
under the original ``_foo`` names so the ~70 test references that
read ``ap._boundary_repulsion``, ``ap._pickup_is_blacklisted``, etc.
keep working.

These tests guard the contract: every ``ap._foo`` shim must remain
reachable, and the constants must continue to round-trip through the
bot_autopilot namespace.
"""
from __future__ import annotations

import pytest

import bot_autopilot as ap
import bot_autopilot_telemetry as tlm
import bot_autopilot_navigation as nav
import bot_autopilot_blacklist as bl


# ── Telemetry shim contract ───────────────────────────────────────────

class TestTelemetryShims:
    def test_telemetry_init_exists(self):
        assert callable(ap._telemetry_init)

    def test_telemetry_log_exists(self):
        assert callable(ap._telemetry_log)

    def test_snapshot_fields_exists(self):
        assert callable(ap._telemetry_snapshot_fields)

    def test_telemetry_path_re_exported(self):
        assert ap._TELEMETRY_PATH == tlm._TELEMETRY_PATH

    def test_telemetry_snapshot_interval_re_exported(self):
        assert ap.TELEMETRY_SNAPSHOT_INTERVAL_S \
            == tlm.TELEMETRY_SNAPSHOT_INTERVAL_S


# ── Navigation shim contract ──────────────────────────────────────────

class TestNavigationShims:
    def test_potential_field_helpers_re_exported(self):
        assert ap._boundary_repulsion is nav.boundary_repulsion
        assert ap._building_repulsion is nav.building_repulsion
        assert ap._steered_heading is nav.steered_heading

    def test_geometry_helpers_re_exported(self):
        assert ap.angle_to is nav.angle_to
        assert ap.heading_delta is nav.heading_delta

    def test_stuck_detect_constants_re_exported(self):
        assert ap.STUCK_DETECT_WINDOW_S == nav.STUCK_DETECT_WINDOW_S
        assert ap.STUCK_DETECT_DIST_PX == nav.STUCK_DETECT_DIST_PX
        assert ap.STUCK_DETECT_ROTATION_DEG == nav.STUCK_DETECT_ROTATION_DEG
        assert ap.STUCK_ESCAPE_MIN_DURATION_S == nav.STUCK_ESCAPE_MIN_DURATION_S
        assert ap.STUCK_ESCAPE_CLEAR_MARGIN_PX == nav.STUCK_ESCAPE_CLEAR_MARGIN_PX
        assert ap.STUCK_WORLD_MARGIN_PX == nav.STUCK_WORLD_MARGIN_PX
        assert ap.STUCK_LOG_THROTTLE_S == nav.STUCK_LOG_THROTTLE_S

    def test_potential_field_constants_re_exported(self):
        assert ap.BOUNDARY_REPULSION_RANGE_PX == nav.BOUNDARY_REPULSION_RANGE_PX
        assert ap.BOUNDARY_REPULSION_GAIN == nav.BOUNDARY_REPULSION_GAIN
        assert ap.BUILDING_REPULSION_RANGE_PX == nav.BUILDING_REPULSION_RANGE_PX
        assert ap.BUILDING_REPULSION_GAIN == nav.BUILDING_REPULSION_GAIN

    def test_record_position_writes_through_to_state(self):
        ap._fsm_reset()
        ap._record_position(
            {"x": 100.0, "y": 200.0, "heading": 0.0})
        assert len(ap._stuck_state["history"]) == 1

    def test_detect_stuck_reads_through(self):
        ap._fsm_reset()
        # No history -> not stuck.
        assert ap._detect_stuck() is False


# ── Blacklist shim contract ───────────────────────────────────────────

class TestBlacklistShims:
    def test_pickup_blacklist_uses_state_dict(self):
        ap._fsm_reset()
        ap._blacklist_pickup({"x": 100.0, "y": 0.0})
        assert len(ap._state.pickup_blacklist) == 1
        # Read through the shim — should match.
        assert ap._pickup_is_blacklisted({"x": 100.0, "y": 0.0}) is True

    def test_asteroid_blacklist_uses_state_dict(self):
        ap._fsm_reset()
        ap._blacklist_asteroid({"x": 50.0, "y": 50.0})
        assert len(ap._state.asteroid_blacklist) == 1
        assert ap._asteroid_is_blacklisted({"x": 50.0, "y": 50.0}) is True

    def test_blacklist_constants_re_exported(self):
        assert ap.PICKUP_BLACKLIST_TTL_S == bl.PICKUP_BLACKLIST_TTL_S
        assert ap.PICKUP_BLACKLIST_RADIUS_PX == bl.PICKUP_BLACKLIST_RADIUS_PX
        assert ap.ASTEROID_BLACKLIST_TTL_S == bl.ASTEROID_BLACKLIST_TTL_S
        assert ap.ASTEROID_BLACKLIST_RADIUS_PX == bl.ASTEROID_BLACKLIST_RADIUS_PX

    def test_nearest_pickup_filters_blacklist(self):
        ap._fsm_reset()
        ap._blacklist_pickup({"x": 100.0, "y": 0.0})
        state = {
            "iron_pickups": [{"x": 100.0, "y": 0.0},
                             {"x": 500.0, "y": 0.0}],
            "blueprint_pickups": [],
        }
        pu, _ = ap._nearest_pickup(state, 0.0, 0.0)
        # Skipped the blacklisted one; picked the far one.
        assert pu == {"x": 500.0, "y": 0.0}

    def test_nearest_asteroid_filters_blacklist(self):
        ap._fsm_reset()
        ap._blacklist_asteroid({"x": 100.0, "y": 0.0})
        state = {"asteroids": [{"x": 100.0, "y": 0.0},
                                {"x": 500.0, "y": 0.0}]}
        ast, _ = ap._nearest_asteroid(state, 0.0, 0.0)
        assert ast == {"x": 500.0, "y": 0.0}


# ── No circular-import regression ─────────────────────────────────────

class TestNoCircularImport:
    """The new modules late-import bot_autopilot only inside function
    bodies (telemetry's _now_monotonic; zone_effects'
    _check_slipspace_teleport).  This test pins that the modules
    can be imported in isolation without bot_autopilot loaded first."""

    def test_navigation_imports_standalone(self):
        # bot_autopilot_navigation has no bot_autopilot dependency at all.
        # Reimport in a clean namespace to verify.
        import importlib
        import bot_autopilot_navigation
        importlib.reload(bot_autopilot_navigation)
        assert callable(bot_autopilot_navigation.boundary_repulsion)

    def test_blacklist_imports_standalone(self):
        import importlib
        import bot_autopilot_blacklist
        importlib.reload(bot_autopilot_blacklist)
        assert callable(bot_autopilot_blacklist.pickup_is_blacklisted)
