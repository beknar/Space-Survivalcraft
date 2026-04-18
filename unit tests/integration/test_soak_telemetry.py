"""Soak test for the telemetry hang-dumper regression.

Two crashes both fired during the 30-second
``faulthandler.dump_traceback_later`` tick.  After removing it, a
real GameView running for the full ``SOAK_DURATION_S`` (5 minutes)
must complete without an OS-level access violation.

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run explicitly with:
    pytest "unit tests/integration/test_soak_telemetry.py" -v -s
"""
from __future__ import annotations

from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _make_telemetry_churn(gv):
    """Tick GameView + telemetry every frame for the full duration so
    the same code paths the failed sessions exercised stay hot."""
    from telemetry import record_frame, note

    step = {"n": 0}

    def tick(dt: float) -> None:
        # Full update + draw + per-frame telemetry record.
        record_frame(gv)
        gv.on_update(dt)
        gv.on_draw()
        # Every ~10 s drop a tagged note so flight.jsonl entries
        # interleave with frame snapshots, exercising the note() path
        # too — that path was suspect because it shares the same
        # buffer + flush plumbing.
        if step["n"] % 600 == 0:
            note("SOAK_TICK", n=step["n"])
        step["n"] += 1

    return tick


class TestSoakTelemetryNoCrash:
    def test_zone2_with_telemetry_5min_soak(
            self, real_game_view, monkeypatch, tmp_path):
        import telemetry as _tel
        from telemetry import init_crash_telemetry
        # Redirect telemetry output to a temp dir so the soak doesn't
        # pollute the real crash_logs/ folder, and reset state so we
        # call init from scratch.
        monkeypatch.setattr(_tel, "_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(_tel, "_recorder", None)
        monkeypatch.setattr(_tel, "_faulthandler_file", None)
        init_crash_telemetry()

        gv = real_game_view
        make_invulnerable(gv)
        gv._transition_zone(ZoneID.ZONE2)
        run_soak(gv, "Telemetry + Zone 2", _make_telemetry_churn(gv))


class TestSoakTelemetryZone1NoCrash:
    """Same scenario in MAIN — null fields, slipspaces, asteroids,
    aliens — to surface anything that's specific to Zone 1's draw
    path (different SpriteList lineup, different texture mix)."""

    def test_zone1_with_telemetry_5min_soak(
            self, real_game_view, monkeypatch, tmp_path):
        import telemetry as _tel
        from telemetry import init_crash_telemetry
        monkeypatch.setattr(_tel, "_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(_tel, "_recorder", None)
        monkeypatch.setattr(_tel, "_faulthandler_file", None)
        init_crash_telemetry()

        gv = real_game_view
        make_invulnerable(gv)
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        run_soak(gv, "Telemetry + Zone 1", _make_telemetry_churn(gv))
