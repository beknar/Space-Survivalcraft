"""Performance integration tests — character portrait video.

Frame-time / FPS coverage for the character video player (160×160
portrait, GPU blit downscale + frame readback every ~3 frames):

  * Char video + Zone 1 normal gameplay.
  * Char video + Zone 2 (Nebula) full population.
  * Char video + both inventories open (125 filled cells).

Run with:  ``pytest "unit tests/integration/test_performance_video_char.py" -v``
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
#  Video helper — start character video if a .mp4 file is available
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


def _start_char_video_or_skip(gv):
    """Start the character video player. Skips if no files or no FFmpeg."""
    paths = _get_video_paths()
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    dt = 1 / 60
    for _ in range(10):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._char_video_player.active:
        pytest.skip("Character video player failed to start (no FFmpeg?)")


# ═══════════════════════════════════════════════════════════════════════════
#  Character video + Zone 1 gameplay
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoZone1:
    def test_char_video_with_zone1_above_threshold(self, real_game_view):
        """Zone 1 normal gameplay with the character video portrait
        rendering in the HUD. The video player runs GPU blit downscale +
        frame readback every ~3 frames."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_char_video_or_skip(gv)

        fps = _measure_fps(gv)

        gv._char_video_player.stop()

        assert fps >= MIN_FPS, (
            f"Zone 1 + char video: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Character video + Zone 2 full population
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoZone2:
    def test_char_video_with_zone2_above_threshold(self, real_game_view):
        """Zone 2 (Nebula) full population — the heaviest zone — with the
        character video portrait running. This is the most demanding
        realistic gameplay scenario."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _start_char_video_or_skip(gv)

        fps = _measure_fps(gv)

        gv._char_video_player.stop()

        assert fps >= MIN_FPS, (
            f"Zone 2 + char video: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Character video + both inventories open
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoInventories:
    def test_char_video_with_inventories_above_threshold(self, real_game_view):
        """Both inventories open (125 filled cells) with the character
        video portrait rendering. Stacks the two most expensive UI
        systems together."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_char_video_or_skip(gv)

        # Fill both inventories
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
        gv._char_video_player.stop()

        assert fps >= MIN_FPS, (
            f"Inventories + char video: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
