"""Soak test for the ``next_source`` heap-corruption regression.

The original crash was a Windows fatal 0xc0000374 inside
``ffmpeg_read`` on the pyglet media worker thread.  Trigger:
``_stop_player`` called ``next_source()`` on the main thread while
the worker was mid-read.

A real soak repeatedly invokes ``play -> stop`` cycles on a
``VideoPlayer`` for 5 minutes.  If the regression returns, this
catches it.  If no test video file is available the test is skipped
without failing — the unit-level grep guard still locks the
regression on every CI run.

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run explicitly with:
    pytest "unit tests/integration/test_soak_video_player.py" -v -s
"""
from __future__ import annotations

import os

import pytest

from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _find_test_video() -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    for d in ("yvideos", "characters"):
        full = os.path.join(here, d)
        if not os.path.isdir(full):
            continue
        for f in sorted(os.listdir(full)):
            if f.lower().endswith((".mp4", ".mkv", ".mov", ".webm")):
                return os.path.join(full, f)
    return None


def _make_video_churn(gv, video_path: str):
    """Toggle the HUD video player every ~3 seconds.  Each toggle
    exercises the play/stop teardown path that used to crash."""
    from video_player import VideoPlayer

    state = {"playing": False, "n": 0}
    vp = gv._video_player

    def tick(dt: float) -> None:
        # Every 180 frames (~3 s at 60 FPS) toggle play/stop.
        if state["n"] % 180 == 0:
            try:
                if state["playing"]:
                    vp.stop()
                    state["playing"] = False
                else:
                    if vp.play(video_path, volume=0.0):
                        state["playing"] = True
            except Exception:
                # Swallow so the soak loop keeps making progress.
                # The OS-level crash is what we're guarding against;
                # Python exceptions here would point at unrelated
                # video stack issues.
                pass
        gv.on_update(dt)
        gv.on_draw()
        state["n"] += 1

    return tick


class TestSoakVideoPlayerPlayStopCycle:
    def test_play_stop_cycles_5min_soak(self, real_game_view):
        path = _find_test_video()
        if path is None:
            pytest.skip("no test video available under yvideos/ or characters/")

        gv = real_game_view
        make_invulnerable(gv)
        gv._transition_zone(ZoneID.ZONE2)
        run_soak(gv, "VideoPlayer play/stop churn",
                 _make_video_churn(gv, path))
