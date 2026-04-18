"""Integration test for the ``next_source`` heap-corruption regression.

A real ``VideoPlayer`` (with a hidden Arcade window so pyglet can
construct its GL context) must complete a ``play -> stop`` cycle
without ever calling ``next_source()`` on the underlying
``pyglet.media.Player``.  Calling ``next_source()`` while pyglet's
media worker thread is mid-``ffmpeg_read`` produces a Windows fatal
0xc0000374 (heap corruption).  This test wraps the real player and
fails if ``next_source`` is invoked even once.

The video file used here is the smallest mp4 we can find under
``yvideos/`` or ``characters/``.  If neither has a video file the
test is skipped — that's fine because the unit-level grep guard in
``test_video_player.py`` still locks the regression on every CI run.
"""
from __future__ import annotations

import os

import pytest


def _find_test_video() -> str | None:
    """Pick any small video file we can find for the play() call.
    No video → skip; the unit-level guards still fire."""
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


class TestRealVideoPlayerNeverCallsNextSource:
    def test_play_then_stop_does_not_call_next_source(self, real_window):
        from video_player import VideoPlayer

        path = _find_test_video()
        if path is None:
            pytest.skip("no test video available under yvideos/ or characters/")

        vp = VideoPlayer(convert_fps=15.0)
        VideoPlayer._pending_cleanup = []   # clean slate

        if not vp.play(path, volume=0.0):
            pytest.skip(f"VideoPlayer.play returned False for {path}")

        # Wrap the real underlying pyglet Player's next_source so any
        # call from inside _stop_player or stop is recorded.
        called = {"n": 0}
        real_next = vp._player.next_source

        def spy_next():
            called["n"] += 1
            return real_next()

        vp._player.next_source = spy_next

        # Trigger the teardown path that used to crash.
        vp.stop()

        assert called["n"] == 0, (
            f"VideoPlayer teardown called next_source {called['n']} "
            "time(s) — that races the pyglet media worker and produces "
            "0xc0000374 heap corruption inside ffmpeg_read")

        # Drain the pending-cleanup queue so the deferred .delete()
        # actually runs before the next test (otherwise the player
        # leaks until the next update_volume / update tick).
        import time as _time
        for _entry in list(VideoPlayer._pending_cleanup):
            _entry[1].volume = 0.0
        VideoPlayer._pending_cleanup = [
            (0.0, pl) for _, pl in VideoPlayer._pending_cleanup
        ]
        VideoPlayer._drain_pending_cleanup()
