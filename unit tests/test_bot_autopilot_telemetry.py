"""Unit tests pinning the ``bot_autopilot_telemetry`` module API.

The autouse ``_silence_bot_telemetry`` fixture in ``conftest.py``
monkey-patches ``bot_autopilot._telemetry_init`` and
``bot_autopilot._telemetry_log`` to no-ops so production analysis
files are never polluted by the test suite.  These tests opt OUT
of that fixture (by patching the writer to a list-collector) so
they can verify the module's behaviour without writing to disk.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import bot_autopilot_telemetry as tlm


@pytest.fixture
def collector(monkeypatch):
    """Capture every written JSONL line into a list, no disk I/O."""
    captured: list[str] = []

    def fake_open(path, mode="r", encoding=None):
        class FakeFile:
            def write(self, data: str) -> None:
                captured.append(data)
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
        return FakeFile()

    monkeypatch.setattr(tlm, "open", fake_open, raising=False)
    monkeypatch.setattr(tlm.os, "makedirs", lambda *a, **kw: None)
    tlm.reset_for_test()
    return captured


# ── Constants ──────────────────────────────────────────────────────────

class TestTelemetryConstants:
    def test_path_under_bot_io(self):
        assert tlm._TELEMETRY_PATH.startswith("bot_io")
        assert tlm._TELEMETRY_PATH.endswith(".jsonl")

    def test_snapshot_interval_is_5s(self):
        assert tlm.TELEMETRY_SNAPSHOT_INTERVAL_S == pytest.approx(5.0)


# ── telemetry_init / telemetry_log ─────────────────────────────────────

class TestTelemetryInit:
    def test_init_writes_session_start_once(self, collector):
        tlm.telemetry_init()
        tlm.telemetry_init()  # second call is idempotent
        assert len(collector) == 1
        line = json.loads(collector[0].strip())
        assert line["event"] == "session_start"
        assert line["pid"] == os.getpid()

    def test_init_includes_monotonic(self, collector):
        tlm.telemetry_init()
        line = json.loads(collector[0].strip())
        assert "monotonic" in line


class TestTelemetryLog:
    def test_log_event_with_fields(self, collector, monkeypatch):
        # Skip the init line by stubbing the open call manually.
        monkeypatch.setattr(tlm, "_telemetry_started", True)
        tlm.telemetry_log("custom_event", a=1, b="x")
        assert len(collector) == 1
        line = json.loads(collector[0].strip())
        assert line["event"] == "custom_event"
        assert line["a"] == 1
        assert line["b"] == "x"

    def test_log_swallows_write_errors(self, monkeypatch, capsys):
        """A failed write must NOT crash the autopilot loop."""
        monkeypatch.setattr(tlm, "_telemetry_started", True)
        def bad_open(*a, **kw):
            raise OSError("disk full")
        monkeypatch.setattr(tlm, "open", bad_open, raising=False)
        # Should not raise.
        tlm.telemetry_log("event")
        out = capsys.readouterr().out
        assert "telemetry write error" in out


# ── make_snapshot_fields ───────────────────────────────────────────────

class TestMakeSnapshotFields:
    def _bot_state(self):
        queue = SimpleNamespace(
            modules_to_craft=["a", "b"],
            modules_to_install=["c"],
            module_phase_started=True,
            consumable_phase_started=False,
        )
        return SimpleNamespace(
            queue=queue,
            build_done=True,
            last_deposit_at=10.0,
        )

    def test_basic_fields_round_trip(self):
        state = {
            "inventory": {"items": {"iron": 250, "bp_armor": 1, "mod_x": 1}},
            "station_inventory": {"items": {"iron": 1500}},
            "buildings": [{"x": 0.0, "y": 0.0,
                            "building_type": "Home Station"}],
            "asteroids": [{}, {}],
            "aliens": [],
            "iron_pickups": [{}, {}, {}],
            "blueprint_pickups": [{}],
        }
        p = {"x": 100.0, "y": 200.0, "shields": 50, "max_shields": 100}
        bot = self._bot_state()
        find_hs = lambda s: s["buildings"][0]
        clock = [50.0]
        snap = tlm.make_snapshot_fields(
            state, p, bot,
            deposit_cooldown_s=30.0,
            find_home_station=find_hs,
            get_now=lambda: clock[0],
        )
        assert snap["px"] == 100.0
        assert snap["py"] == 200.0
        assert snap["ship_iron"] == 250
        assert snap["ship_blueprints"] == 1
        assert snap["ship_modules"] == 1
        assert snap["station_iron"] == 1500
        assert snap["asteroids_count"] == 2
        assert snap["aliens_count"] == 0
        assert snap["iron_pickups_count"] == 3
        assert snap["blueprint_pickups_count"] == 1
        assert snap["shields"] == 50
        assert snap["max_shields"] == 100
        assert snap["build_done"] is True
        assert snap["last_deposit_at"] == 10.0
        # 50 - 10 = 40 s elapsed; cooldown 30 s -> remaining 0.
        assert snap["deposit_cooldown_remaining_s"] == 0.0
        assert snap["modules_to_craft_left"] == 2
        assert snap["modules_to_install_left"] == 1
        assert snap["module_phase_started"] is True
        assert snap["consumable_phase_started"] is False
        # HS distance computed.
        assert snap["has_home_station"] is True
        assert snap["hs_dist"] is not None
        # No zone in the state -> empty string (never KeyErrors).
        assert snap["zone_id"] == ""

    def test_zone_id_in_snapshot(self):
        """2026-06-09: every post-hoc analysis had to infer the zone
        from alien-count signatures; the snapshot now carries it."""
        state = {
            "inventory": {"items": {}},
            "station_inventory": {"items": {}},
            "buildings": [],
            "zone": {"id": "ZoneID.ZONE2", "world_w": 6400},
        }
        p = {"x": 0.0, "y": 0.0, "shields": 100, "max_shields": 100}
        snap = tlm.make_snapshot_fields(
            state, p, self._bot_state(),
            deposit_cooldown_s=30.0,
            find_home_station=lambda s: None,
            get_now=lambda: 0.0,
        )
        assert snap["zone_id"] == "ZoneID.ZONE2"

    def test_blacklist_sizes_in_snapshot(self):
        """Snapshot must report current asteroid + pickup blacklist
        sizes so post-hoc analysis can distinguish "world is empty"
        from "all visible targets are blacklisted" (the deadlock
        pattern that wedged the bot in IDLE_AT_BASE for 14 minutes
        in the 2026-05-09 telemetry).  Missing-attr fall back to
        empty-dict / size 0 so test fixtures using SimpleNamespace
        don't have to thread the field."""
        state = {"inventory": {"items": {}},
                 "station_inventory": {"items": {}},
                 "buildings": []}
        p = {"x": 0.0, "y": 0.0}
        # Construct a bot state that exposes both blacklists.
        queue = SimpleNamespace(
            modules_to_craft=[], modules_to_install=[],
            module_phase_started=False,
            consumable_phase_started=False)
        bot = SimpleNamespace(
            queue=queue, build_done=True, last_deposit_at=0.0,
            asteroid_blacklist={(0.0, 0.0): 999.0,
                                (10.0, 10.0): 999.0},
            pickup_blacklist={(20.0, 20.0): 999.0})
        snap = tlm.make_snapshot_fields(
            state, p, bot,
            deposit_cooldown_s=30.0,
            find_home_station=lambda s: None,
            get_now=lambda: 0.0,
        )
        assert snap["asteroid_blacklist_size"] == 2
        assert snap["pickup_blacklist_size"] == 1

    def test_blacklist_sizes_default_to_zero_when_missing(self):
        """Older bot-state fixtures that pre-date the blacklist
        attrs (e.g. SimpleNamespace constructed in unrelated tests)
        must still produce a valid snapshot — the helper falls back
        to ``{}`` via ``getattr`` so downstream JSON serialization
        keeps working."""
        state = {"inventory": {"items": {}},
                 "station_inventory": {"items": {}},
                 "buildings": []}
        p = {"x": 0.0, "y": 0.0}
        queue = SimpleNamespace(
            modules_to_craft=[], modules_to_install=[],
            module_phase_started=False,
            consumable_phase_started=False)
        bot = SimpleNamespace(queue=queue, build_done=True,
                              last_deposit_at=0.0)
        snap = tlm.make_snapshot_fields(
            state, p, bot,
            deposit_cooldown_s=30.0,
            find_home_station=lambda s: None,
            get_now=lambda: 0.0,
        )
        assert snap["asteroid_blacklist_size"] == 0
        assert snap["pickup_blacklist_size"] == 0

    def test_no_home_station_yields_none_distance(self):
        state = {"inventory": {"items": {}},
                 "station_inventory": {}, "buildings": []}
        p = {"x": 0.0, "y": 0.0}
        bot = self._bot_state()
        snap = tlm.make_snapshot_fields(
            state, p, bot,
            deposit_cooldown_s=30.0,
            find_home_station=lambda s: None,
            get_now=lambda: 0.0,
        )
        assert snap["has_home_station"] is False
        assert snap["hs_dist"] is None
