"""Performance integration tests — both videos (char + music stand-in).

Frame-time / FPS coverage for running BOTH video players at once
(two FFmpeg decoders + two GPU-blit downscales per frame). Music
video uses a second character .mp4 as a stand-in to exercise the
same pipeline without requiring a real music asset.

  * Both videos + Zone 1.
  * Both videos + Zone 2 (Nebula) full population.
  * Both videos + both inventories open (125 filled cells).

Run with:  ``pytest "unit tests/integration/test_performance_video_dual.py" -v``
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

def _get_video_paths():
    """Return up to 2 character video paths, or skip."""
    from video_player import scan_characters_dir, character_video_path
    chars = scan_characters_dir()
    if not chars:
        pytest.skip("No character video files found in characters/")
    paths = []
    for name in chars:
        p = character_video_path(name)
        if p is not None:
            paths.append(p)
        if len(paths) >= 2:
            break
    if not paths:
        pytest.skip("No character video file paths resolved")
    return paths


def _start_both_videos_or_skip(gv):
    """Start BOTH the character video and the music video player.
    Uses two different character .mp4 files as stand-ins (same FFmpeg
    decode + GPU blit pipeline). Skips if fewer than 2 video files exist
    or FFmpeg is unavailable."""
    paths = _get_video_paths()
    # Character video (small 160×160 portrait)
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    # Music video (larger 16:9 panel) — use a second file if available,
    # otherwise reuse the same file (still exercises both decode pipelines)
    music_path = paths[1] if len(paths) > 1 else paths[0]
    gv._video_player.play(music_path, volume=0.0)
    dt = 1 / 60
    for _ in range(10):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._char_video_player.active and not gv._video_player.active:
        pytest.skip("Neither video player started (no FFmpeg?)")


def _stop_both_videos(gv):
    """Stop both video players and clean up."""
    gv._char_video_player.stop()
    gv._video_player.stop()


# ═══════════════════════════════════════════════════════════════════════════
#  BOTH videos + Zone 1 gameplay
# ═══════════════════════════════════════════════════════════════════════════

class TestDualVideoZone1:
    def test_both_videos_with_zone1_above_threshold(self, real_game_view):
        """Zone 1 gameplay with BOTH the character video portrait AND a
        music video rendering simultaneously. Two independent FFmpeg
        decode pipelines + two GPU blit downscales per frame."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_both_videos_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 1 + both videos: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  BOTH videos + Zone 2 full population
# ═══════════════════════════════════════════════════════════════════════════

class TestDualVideoZone2:
    def test_both_videos_with_zone2_above_threshold(self, real_game_view):
        """Zone 2 (Nebula) full population with both video players active.
        This is the absolute worst-case scenario: ~60 aliens, ~150
        asteroids, gas, wanderers, fog, minimap dots, PLUS two FFmpeg
        decode pipelines and GPU blit downscales."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _start_both_videos_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 2 + both videos: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  BOTH videos + both inventories open
# ═══════════════════════════════════════════════════════════════════════════

class TestDualVideoInventories:
    def test_both_videos_with_inventories_above_threshold(self, real_game_view):
        """Both inventories open (125 filled cells) with both video
        players active. Stacks the three most expensive rendering
        systems: inventory badges + character video + music video."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_both_videos_or_skip(gv)

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
            f"Inventories + both videos: {fps:.1f} FPS "
            f"< {MIN_FPS} FPS threshold"
        )
