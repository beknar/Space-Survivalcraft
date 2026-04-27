"""Telemetry recorder for the "drone won't return" diagnostic.

Verifies the recorder lifecycle, the JSONL row schema, and the
wire-up through ``apply_fleet_order`` (RETURN starts a session, the
other three orders / recall stop it).
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    """Redirect telemetry output to a temp file so tests don't pile
    up junk in the repo root."""
    import drone_telemetry as tel
    monkeypatch.setattr(tel, "_path", lambda: str(tmp_path / "tel.log"))
    # Ensure no leftover state from a prior test.
    tel._state["active"] = False
    return tmp_path / "tel.log"


# ── Recorder lifecycle ────────────────────────────────────────────────────

class TestTelemetryLifecycle:
    def test_inactive_by_default(self, telemetry_log):
        import drone_telemetry as tel
        assert tel.is_recording() is False

    def test_start_writes_header_and_activates(self, telemetry_log):
        import drone_telemetry as tel
        tel.start(reason="test")
        assert tel.is_recording() is True
        assert telemetry_log.exists()
        lines = telemetry_log.read_text().strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row.get("header") is True
        assert row.get("reason") == "test"
        tel.stop()

    def test_stop_writes_footer_and_deactivates(self, telemetry_log):
        import drone_telemetry as tel
        tel.start(reason="test")
        tel.stop(reason="bye")
        assert tel.is_recording() is False
        last = telemetry_log.read_text().strip().splitlines()[-1]
        row = json.loads(last)
        assert row.get("footer") is True
        assert row.get("reason") == "bye"

    def test_record_frame_skipped_when_inactive(self, telemetry_log):
        """No-op + no file write when no session is active."""
        import drone_telemetry as tel
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=100.0, center_y=0.0)
        tel.record_frame(d, player, waypoint=None, nudge_fired=False)
        assert not telemetry_log.exists()


# ── Row schema ────────────────────────────────────────────────────────────

class TestTelemetryRow:
    def test_record_frame_writes_expected_fields(self, telemetry_log):
        import drone_telemetry as tel
        from sprites.drone import CombatDrone
        tel.start(reason="schema test")
        d = CombatDrone(50.0, 50.0)
        player = SimpleNamespace(center_x=200.0, center_y=50.0)
        tel.record_frame(d, player, waypoint=(120.0, 50.0),
                         nudge_fired=True)
        tel.stop()
        rows = [json.loads(line)
                for line in telemetry_log.read_text().splitlines()]
        # Header, snapshot, footer.
        assert len(rows) == 3
        snap = rows[1]
        # Pin every field name we depend on for downstream analysis.
        for k in ("frame", "t", "mode", "dir", "rxn", "pos", "ply",
                  "dist", "moved", "wp", "cd", "stuck", "path",
                  "nudge"):
            assert k in snap
        assert snap["pos"] == [50.0, 50.0]
        assert snap["ply"] == [200.0, 50.0]
        assert snap["dist"] == 150.0
        assert snap["wp"] == [120.0, 50.0]
        assert snap["nudge"] is True


# ── Fleet-order wire-up ──────────────────────────────────────────────────

class TestApplyFleetOrderTelemetry:
    def test_return_starts_recording(self, telemetry_log):
        from combat_helpers import apply_fleet_order
        from sprites.drone import CombatDrone
        import drone_telemetry as tel
        d = CombatDrone(0.0, 0.0)
        gv = SimpleNamespace(
            _active_drone=d,
            player=SimpleNamespace(center_x=0.0, center_y=0.0))
        apply_fleet_order(gv, "return")
        assert tel.is_recording() is True
        # Header in the log mentions RETURN.
        first = telemetry_log.read_text().splitlines()[0]
        assert "RETURN" in first
        tel.stop()

    def test_attack_order_stops_recording(self, telemetry_log):
        from combat_helpers import apply_fleet_order
        from sprites.drone import CombatDrone
        import drone_telemetry as tel
        d = CombatDrone(0.0, 0.0)
        gv = SimpleNamespace(
            _active_drone=d,
            player=SimpleNamespace(center_x=0.0, center_y=0.0))
        apply_fleet_order(gv, "return")
        assert tel.is_recording() is True
        apply_fleet_order(gv, "attack")
        assert tel.is_recording() is False

    def test_follow_only_stops_recording(self, telemetry_log):
        from combat_helpers import apply_fleet_order
        from sprites.drone import CombatDrone
        import drone_telemetry as tel
        d = CombatDrone(0.0, 0.0)
        gv = SimpleNamespace(
            _active_drone=d,
            player=SimpleNamespace(center_x=0.0, center_y=0.0))
        apply_fleet_order(gv, "return")
        apply_fleet_order(gv, "follow_only")
        assert tel.is_recording() is False


# ── Save/load round-trips reaction + direct order ────────────────────────

class TestDroneFleetStateInSave:
    def test_serialize_includes_reaction_and_direct_order(self):
        from game_save import _serialize_active_drone
        from sprites.drone import CombatDrone
        d = CombatDrone(10.0, 20.0)
        d._reaction = "follow"
        d._direct_order = "return"
        gv = SimpleNamespace(_active_drone=d)
        blob = _serialize_active_drone(gv)
        assert blob["reaction"] == "follow"
        assert blob["direct_order"] == "return"

    def test_round_trip_restores_orders(self):
        from game_save import (_serialize_active_drone,
                                _restore_active_drone)
        from sprites.drone import CombatDrone
        d = CombatDrone(100.0, 200.0)
        d._reaction = "follow"
        d._direct_order = "attack"
        blob = _serialize_active_drone(SimpleNamespace(_active_drone=d))
        gv2 = SimpleNamespace(
            _active_drone=None,
            _drone_list=arcade.SpriteList())
        _restore_active_drone(gv2, blob)
        assert gv2._active_drone._reaction == "follow"
        assert gv2._active_drone._direct_order == "attack"
