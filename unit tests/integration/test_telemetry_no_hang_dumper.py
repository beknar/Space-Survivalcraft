"""Integration test for the telemetry hang-dumper regression.

Two real crashes (FFmpeg heap corruption + OpenGL VAO access
violation) both fired during ``faulthandler.dump_traceback_later``'s
periodic stack-dump tick.  The dumper races pyglet/FFmpeg/audio C
extensions on Windows and produces access violations of its own.

This test runs a real GameView for enough simulated frames to span
the old 30-second tick window, with telemetry initialised exactly
the way ``main.py`` would do it.  It must complete cleanly — both
no Python exceptions AND no scheduled hang-dumper firing.
"""
from __future__ import annotations

import faulthandler
import os

import pytest

from telemetry import init_crash_telemetry, record_frame


class TestTelemetryDoesNotScheduleHangDumper:
    def test_init_crash_telemetry_leaves_no_dump_timer(
            self, monkeypatch, tmp_path):
        """End-to-end through ``init_crash_telemetry`` — even with the
        full faulthandler / excepthook / flight-recorder pipeline
        wired up, no ``dump_traceback_later`` timer must be active
        after initialisation."""
        # Re-init from scratch so this test isn't affected by any
        # prior init_crash_telemetry call in the session.
        import telemetry as _tel
        monkeypatch.setattr(_tel, "_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(_tel, "_recorder", None)
        monkeypatch.setattr(_tel, "_faulthandler_file", None)
        monkeypatch.setattr(_tel, "_exception_log_path", None)

        # Spy on dump_traceback_later so we can assert it wasn't called.
        scheduled = {"n": 0}
        real = faulthandler.dump_traceback_later

        def spy(*a, **kw):
            scheduled["n"] += 1
            return real(*a, **kw)

        monkeypatch.setattr(faulthandler, "dump_traceback_later", spy)

        init_crash_telemetry()

        # If the hang dumper had been re-added, this counter would be
        # >= 1.  Belt-and-braces: also call cancel just in case some
        # OTHER code in the import chain scheduled one.
        try:
            faulthandler.cancel_dump_traceback_later()
        except Exception:
            pass
        assert scheduled["n"] == 0, (
            "init_crash_telemetry scheduled a hang-dumper timer — "
            "that was removed because it caused crashes inside "
            "OpenGL / FFmpeg threads on Windows")


class TestRealGameViewSurvivesTelemetryFrames:
    """The actual scenario the dumper crashed: a real GameView ticking
    for >30 seconds of simulated frames with telemetry on.  We don't
    sit through 30 wall-clock seconds — we just exercise the same
    code path (record_frame on every tick) for enough iterations that
    any GC/atlas/texture issue would have time to surface."""

    def test_long_run_with_telemetry_does_not_crash(
            self, real_game_view, monkeypatch, tmp_path):
        import telemetry as _tel
        monkeypatch.setattr(_tel, "_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(_tel, "_recorder", None)
        monkeypatch.setattr(_tel, "_faulthandler_file", None)
        init_crash_telemetry()

        gv = real_game_view
        dt = 1 / 60
        # 60 * 60 = 3600 frames ≈ 1 minute simulated, plenty to cover
        # what would have been two hang-dumper ticks.
        for _ in range(3600):
            record_frame(gv)
            gv.on_update(dt)
            gv.on_draw()
        # Reaching here without an OS-level crash IS the assertion.
        # Sanity check that the flight recorder logged something.
        from telemetry import _recorder
        assert _recorder is not None
