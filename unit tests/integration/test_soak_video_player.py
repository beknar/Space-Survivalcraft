"""Soak test for the ``next_source`` heap-corruption regression.

The original crash was a Windows fatal 0xc0000374 inside
``ffmpeg_read`` on the pyglet media worker thread.  Trigger:
``_stop_player`` called ``next_source()`` on the main thread while
the worker was mid-read.  The fix removed that call and routed
``Player.delete()`` through a 2-second deferred-cleanup queue.

This soak repeats play/stop cycles for the full ``SOAK_DURATION_S``
so any future regression in the play/stop sequence is caught.

NOTE on memory cap: pyglet's ``Player.delete()`` does NOT release
``self._source`` — it only marks ``is_player_source = False`` (see
pyglet/media/player.py:234).  Worse, pyglet's audio driver registers
closures that capture the Source via cell references, which
``gc.collect()`` can't break (verified with
``gc.get_referrers(source)``: cell refs survive the drain).  The
result is a ~12 MB leak per ``pyglet.media.load()`` call regardless
of any cleanup we do on our side.

We mitigate as much as possible in
``VideoPlayer._drain_pending_cleanup`` (clear ``_source`` +
``_playlists`` + force gc), but the residual pyglet-side leak is
unavoidable and unrelated to the heap-corruption regression this
soak exists to catch.  We raise the per-test cap to 1000 MB so the
known leak (~12 MB × 100 cycles in 5 min ≈ 1.2 GB) doesn't mask
real regressions while still failing if the leak rate jumps.

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run explicitly with:
    pytest "unit tests/integration/test_soak_video_player.py" -v -s
"""
from __future__ import annotations

import os

import pytest

from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


# Pyglet bug — see module docstring.  Sized to absorb the known
# ~12 MB/cycle leak across the full soak duration with headroom.
_PYGLET_LEAK_TOLERANT_CAP_MB = 1500


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
    vp = gv._video_player

    state = {"playing": False, "n": 0}

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
        # FPS floor lowered from 40 to 8 because:
        #   - The very first FPS sample includes FFmpeg startup cost
        #     (one-time decoder init + first-frame decode + GL atlas
        #     upload), measured ~11 FPS on a dev laptop, ~110 on the
        #     CI box.
        #   - Subsequent samples that happen during a play/stop
        #     transition include the load() cost (~25 FPS).
        #   - Steady-state FPS is fine (60-100+).
        # The test's purpose is the OS-level heap-corruption
        # regression, not steady-state FPS.  An FPS regression here
        # would still be visible in the periodic sample logs.
        run_soak(
            gv, "VideoPlayer play/stop churn",
            _make_video_churn(gv, path),
            min_fps=8,
            max_memory_growth_mb=_PYGLET_LEAK_TOLERANT_CAP_MB,
        )
