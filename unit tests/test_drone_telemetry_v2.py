"""Round-2 drone telemetry recorder tests.

Resurrected for the "drone wanders in the Nebula instead of
following" diagnostic.  Now triggers for the lifetime of any
deployed drone (start on deploy, stop on recall / destruction)
and records every frame from both ``follow()`` and
``_run_return_home``.
"""
from __future__ import annotations

import json
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
    tel._state["active"] = False
    return tmp_path / "tel.log"


# ── Lifecycle ─────────────────────────────────────────────────────────────


class TestRecorderLifecycle:
    def test_start_writes_header_with_reason(self, telemetry_log):
        import drone_telemetry as tel
        tel.start(reason="deploy in nebula")
        assert tel.is_recording() is True
        first = telemetry_log.read_text().splitlines()[0]
        assert json.loads(first)["reason"] == "deploy in nebula"
        tel.stop()

    def test_stop_writes_footer_and_deactivates(self, telemetry_log):
        import drone_telemetry as tel
        tel.start()
        tel.stop(reason="recalled")
        assert tel.is_recording() is False
        last = telemetry_log.read_text().splitlines()[-1]
        assert json.loads(last)["reason"] == "recalled"

    def test_record_frame_no_op_when_inactive(self, telemetry_log):
        """No file write, no exception when no session is active."""
        import drone_telemetry as tel
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        gv = SimpleNamespace(
            player=SimpleNamespace(center_x=10.0, center_y=10.0),
            _zone=SimpleNamespace(zone_id=None, _walls=None))
        tel.record_frame(d, gv)
        assert not telemetry_log.exists()


# ── Snapshot row schema ──────────────────────────────────────────────────


class TestSnapshotRow:
    def test_record_frame_writes_expected_fields(self, telemetry_log):
        import drone_telemetry as tel
        from sprites.drone import CombatDrone, _BaseDrone
        tel.start(reason="schema")
        d = CombatDrone(50.0, 50.0)
        d._mode = _BaseDrone._MODE_FOLLOW
        d._reaction = "follow"
        d._direct_order = None
        d._slot = _BaseDrone._SLOT_LEFT
        d._last_steer_target = (120.0, 50.0)
        gv = SimpleNamespace(
            player=SimpleNamespace(center_x=200.0, center_y=50.0),
            _zone=SimpleNamespace(
                zone_id=SimpleNamespace(name="ZONE2"),
                _walls=None))
        tel.record_frame(d, gv)
        tel.stop()
        rows = [json.loads(line)
                for line in telemetry_log.read_text().splitlines()]
        # Header, snapshot, footer.
        assert len(rows) == 3
        snap = rows[1]
        for k in ("frame", "t", "zone", "mode", "dir", "rxn",
                  "slot", "pos", "ply", "dist", "moved", "wp",
                  "cd", "stuck", "path", "nudge_t", "walls",
                  "ast", "tcd"):
            assert k in snap, f"missing field: {k}"
        assert snap["zone"] == "ZONE2"
        assert snap["mode"] == "FOLLOW"
        assert snap["rxn"] == "follow"
        assert snap["slot"] == "LEFT"
        assert snap["wp"] == [120.0, 50.0]
        assert snap["dist"] == 150.0


# ── deploy_drone starts a recording session ──────────────────────────────


class TestDeployStartsRecording:
    def test_deploy_starts_recording(self, telemetry_log):
        from combat_helpers import deploy_drone
        from game_view import GameView
        import drone_telemetry as tel
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        # Default weapon (idx 0) is the Basic Laser which has
        # ``mines_rock=False`` so deploy_drone picks the combat
        # variant.  Seed one charge.
        gv.inventory.add_item("combat_drone", 1)
        deploy_drone(gv)
        assert tel.is_recording() is True
        # Header should mention the drone label and the zone.
        first = telemetry_log.read_text().splitlines()[0]
        h = json.loads(first)
        assert "Combat Drone deployed" in h["reason"]
        tel.stop()

    def test_recall_stops_recording(self, telemetry_log):
        from combat_helpers import deploy_drone, recall_drone
        from game_view import GameView
        import drone_telemetry as tel
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv.inventory.add_item("combat_drone", 1)
        deploy_drone(gv)
        assert tel.is_recording() is True
        recall_drone(gv)
        assert tel.is_recording() is False
