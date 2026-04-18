"""Tests for crash telemetry — flight recorder + hooks.

Full ``init_crash_telemetry`` isn't exercised here because it installs
process-wide faulthandler + excepthooks that would leak across tests.
We test the pieces in isolation:

- FlightRecorder: record / rotate / note / close
- Swallows broken ``gv`` without raising
- _log_exception writes a traceback line
"""
from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

import pytest

from telemetry import FlightRecorder, _log_exception


class _StubPlayer:
    center_x = 100.0
    center_y = 200.0
    hp = 75
    shields = 50


def _stub_gv():
    return SimpleNamespace(
        _zone=SimpleNamespace(zone_id=SimpleNamespace(name="MAIN")),
        player=_StubPlayer(),
        projectile_list=[1, 2, 3],
        alien_list=[1, 2],
        alien_projectile_list=[],
        explosion_list=[1],
        building_list=[1, 2, 3, 4],
    )


class TestFlightRecorderBasic:
    def test_record_writes_one_entry_per_flush(self, tmp_path):
        path = tmp_path / "flight.jsonl"
        r = FlightRecorder(str(path), flush_every_s=0.0)
        r.record(_stub_gv())
        r.close(clean=True)

        lines = path.read_text(encoding="utf-8").splitlines()
        # Expect at least the recorded entry + the SHUTDOWN note.
        assert len(lines) >= 2
        first = json.loads(lines[0])
        assert first["f"] == 1
        assert first["z"] == "MAIN"
        assert first["px"] == 100.0
        assert first["py"] == 200.0
        assert first["proj"] == 3
        assert first["alien"] == 2
        assert first["bld"] == 4

    def test_record_buffers_between_flushes(self, tmp_path):
        path = tmp_path / "flight.jsonl"
        r = FlightRecorder(str(path), flush_every_s=60.0)
        for _ in range(10):
            r.record(_stub_gv())
        # Nothing flushed yet.
        assert path.stat().st_size == 0
        r.close(clean=True)
        # Close flushes.
        lines = path.read_text(encoding="utf-8").splitlines()
        # 10 records + 1 SHUTDOWN note.
        assert len(lines) == 11


class TestFlightRecorderRobust:
    def test_record_swallows_broken_gv(self, tmp_path):
        """A gv missing every attribute must not raise — telemetry can
        never take the game down."""
        path = tmp_path / "flight.jsonl"
        r = FlightRecorder(str(path), flush_every_s=0.0)
        r.record(SimpleNamespace())        # missing everything
        r.record(None)                      # even None must be safe
        r.close(clean=False)

    def test_note_records_tag(self, tmp_path):
        path = tmp_path / "flight.jsonl"
        r = FlightRecorder(str(path), flush_every_s=0.0)
        r.note("ZONE_TRANSITION", src="MAIN", dst="ZONE2")
        r.close(clean=True)
        lines = path.read_text(encoding="utf-8").splitlines()
        decoded = [json.loads(ln) for ln in lines]
        tags = [e.get("tag") for e in decoded]
        assert "ZONE_TRANSITION" in tags
        transition = next(e for e in decoded if e.get("tag") == "ZONE_TRANSITION")
        assert transition["src"] == "MAIN"
        assert transition["dst"] == "ZONE2"

    def test_close_marks_shutdown_state(self, tmp_path):
        path = tmp_path / "flight.jsonl"
        r = FlightRecorder(str(path), flush_every_s=0.0)
        r.record(_stub_gv())
        r.close(clean=True)
        lines = path.read_text(encoding="utf-8").splitlines()
        shutdowns = [json.loads(ln) for ln in lines
                     if "SHUTDOWN" in ln]
        assert len(shutdowns) == 1
        assert shutdowns[0]["clean"] is True


class TestFlightRecorderRotation:
    def test_rotates_at_max_bytes(self, tmp_path):
        path = tmp_path / "flight.jsonl"
        r = FlightRecorder(str(path), flush_every_s=0.0, max_bytes=500)
        for _ in range(100):
            r.record(_stub_gv())
        r.close(clean=False)
        # Rotation must have produced <path>.1
        assert (tmp_path / "flight.jsonl.1").exists()


class TestExceptionLogger:
    def test_log_exception_writes_traceback(self, tmp_path, monkeypatch):
        log_path = tmp_path / "exceptions.log"
        monkeypatch.setattr("telemetry._exception_log_path", str(log_path))
        try:
            raise ValueError("boom")
        except ValueError as e:
            _log_exception("test", type(e), e, e.__traceback__)
        text = log_path.read_text(encoding="utf-8")
        assert "ValueError: boom" in text
        assert "[test]" in text

    def test_log_exception_noop_without_path(self, monkeypatch):
        """If init_crash_telemetry failed, _exception_log_path is None
        and _log_exception must quietly do nothing."""
        monkeypatch.setattr("telemetry._exception_log_path", None)
        _log_exception("x", ValueError, ValueError("y"), None)  # no raise
