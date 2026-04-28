"""Performance integration tests — real music video + cleanup churn.

Frame-time / FPS coverage for the production music-video pipeline:

  * Real ./yvideos/*.mp4 music video + char video + Zone 1.
  * Real music video + char video + Zone 2 (Nebula) full population.
  * Real music video + char video + both inventories open.
  * VideoPlayer cleanup-queue churn — 30 pending cleanups should not
    degrade the per-frame queue drain.

These tests skip if ./yvideos has no .mp4 files (gitignored asset
directory) or if FFmpeg cannot decode them.

Run with:  ``pytest "unit tests/integration/test_performance_video_music.py" -v``
"""
from __future__ import annotations

import time

import arcade
import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BUILDING_TYPES, MODULE_SLOT_COUNT,
)
from zones import ZoneID

# ── Configuration ──────────────────────────────────────────────────────────

MIN_FPS = 40

# Use shared measure_fps from conftest
from integration.conftest import measure_fps as _measure_fps


# ═══════════════════════════════════════════════════════════════════════════
#  Video helpers — start/stop char + music videos
# ═══════════════════════════════════════════════════════════════════════════

def _stop_both_videos(gv):
    """Stop both video players and clean up."""
    gv._char_video_player.stop()
    gv._video_player.stop()


# ═══════════════════════════════════════════════════════════════════════════
#  Real music video helper — uses ./yvideos/*.mp4 relative to the project
# ═══════════════════════════════════════════════════════════════════════════

import os as _os_mv

_PROJECT_ROOT_MV = _os_mv.path.abspath(
    _os_mv.path.join(_os_mv.path.dirname(__file__), "..", ".."))
_MUSIC_VIDEO_DIR = _os_mv.path.join(_PROJECT_ROOT_MV, "yvideos")


def _start_real_music_and_char_or_skip(gv):
    """Start a real music video from ./yvideos AND the character video.
    Skips if the directory doesn't exist, has no .mp4 files, or FFmpeg
    can't decode them."""
    import os
    from video_player import scan_characters_dir, character_video_path

    # Music video
    if not os.path.isdir(_MUSIC_VIDEO_DIR):
        pytest.skip(f"Music video directory not found: {_MUSIC_VIDEO_DIR}")
    mp4s = sorted(f for f in os.listdir(_MUSIC_VIDEO_DIR)
                  if f.lower().endswith(".mp4"))
    if not mp4s:
        pytest.skip(f"No .mp4 files in {_MUSIC_VIDEO_DIR}")
    music_path = _os_mv.path.join(_MUSIC_VIDEO_DIR, mp4s[0])

    # Character video
    chars = scan_characters_dir()
    if not chars:
        pytest.skip("No character video files found in characters/")
    char_path = character_video_path(chars[0])
    if char_path is None:
        pytest.skip("Character video path not resolved")

    # Start both
    gv._char_video_player.play_segments(char_path, volume=0.0)
    ok = gv._video_player.play(music_path, volume=0.0)
    if not ok:
        gv._char_video_player.stop()
        pytest.skip(f"Music video failed to start: {gv._video_player.error}")

    # Warmup — let both decoders produce their first frames
    dt = 1 / 60
    for _ in range(15):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._video_player.active:
        gv._char_video_player.stop()
        pytest.skip("Music video player not active after warmup")


# ═══════════════════════════════════════════════════════════════════════════
#  Real music video + char video + Zone 1
# ═══════════════════════════════════════════════════════════════════════════

class TestRealMusicVideoZone1:
    def test_real_music_char_video_zone1_above_threshold(self, real_game_view):
        """Zone 1 gameplay with a REAL music video from ./yvideos AND
        the character portrait video. Real music videos are typically
        720p–1080p, much heavier than the 1440×1440 character portraits
        — a harder GPU blit test."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_real_music_and_char_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 1 + real music video + char video: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Real music video + char video + Zone 2 full population
# ═══════════════════════════════════════════════════════════════════════════

class TestRealMusicVideoZone2:
    def test_real_music_char_video_zone2_above_threshold(self, real_game_view):
        """Zone 2 (Nebula) full population with a real music video and
        the character video. Absolute worst case: heaviest zone + two
        FFmpeg decodes + 200+ minimap dots + fog overlay."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _start_real_music_and_char_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 2 + real music video + char video: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Real music video + char video + both inventories
# ═══════════════════════════════════════════════════════════════════════════

class TestRealMusicVideoInventories:
    def test_real_music_char_video_inventories_above_threshold(
        self, real_game_view
    ):
        """Both inventories open (125 filled cells) with a real music
        video and the character video. Stacks every expensive rendering
        system: inventory badges + two video decodes + GPU blits."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_real_music_and_char_or_skip(gv)

        for r in range(5):
            for c in range(5):
                gv.inventory._items[(r, c)] = ("iron", 10 + r * 5 + c)
        gv.inventory._mark_dirty()
        gv.inventory.open = True

        for r in range(10):
            for c in range(10):
                gv._station_inv._items[(r, c)] = ("iron", r * 10 + c + 1)
        gv._station_inv._mark_dirty()
        gv._station_inv.open = True

        fps = _measure_fps(gv)

        gv.inventory.open = False
        gv._station_inv.open = False
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Inventories + real music video + char video: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  VideoPlayer cleanup-queue churn — stop/start cycles must not spike
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoPlayerStopChurnFps:
    """When a video loops or swaps, the old player is paused and
    pushed onto ``_pending_cleanup`` with a 2 s deadline.  If many
    cycles fire close together, the queue grows and the per-frame
    drain has to walk every entry.  This test simulates 30 stop
    cycles (with fake players, no real FFmpeg) and asserts the FPS
    measurement loop stays above ``MIN_FPS``."""

    def test_many_pending_cleanups_do_not_degrade_fps(
            self, real_game_view):
        from video_player import VideoPlayer
        import time as _time

        # Fake players that record nothing — purpose is to exercise
        # the queue-drain logic, not the underlying FFmpeg.  Deadlines
        # are 60 s in the future so nothing actually .delete()s during
        # the measurement window.
        class _FakePlayer:
            def __init__(self):
                self.deleted = False
            def delete(self):
                self.deleted = True

        prior = VideoPlayer._pending_cleanup
        VideoPlayer._pending_cleanup = [
            (_time.monotonic() + 60.0, _FakePlayer()) for _ in range(30)
        ]
        try:
            gv = real_game_view
            gv._transition_zone(ZoneID.ZONE2)
            fps = _measure_fps(gv)
            print(f"  [perf] zone2 + 30 pending video cleanups: "
                  f"{fps:.1f} FPS")
            assert fps >= MIN_FPS, (
                f"VideoPlayer cleanup queue churn: {fps:.1f} FPS < {MIN_FPS}")
        finally:
            VideoPlayer._pending_cleanup = prior
