"""Performance integration tests — null field draw + cloak path.

Frame-time / FPS coverage for the 30 null fields in each main zone
(dot-cluster draw + active-fields lookup) and the player-cloak code
path:

  * Zone 1 with all 30 null fields drawing every frame.
  * Zone 2 (full Nebula) with 30 null fields animating.
  * Zone 2 + 30 null fields + both videos.
  * Player parked inside a null field in Zone 2 — exercises the
    synthetic far-away alien-target position.

Run with:  ``pytest "unit tests/integration/test_performance_null_field.py" -v``
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
    """Start BOTH the character video and the music video player."""
    paths = _get_video_paths()
    gv._char_video_player.play_segments(paths[0], volume=0.0)
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
#  Null field draw + cloak check perf — 30 fields every frame
# ═══════════════════════════════════════════════════════════════════════════

class TestNullFieldDrawZone1:
    def test_null_field_zone1_above_threshold(self, real_game_view):
        """Zone 1 with its 30 null fields drawing every frame + the
        cloak check running each alien tick. Catches any regression
        in the dot-cluster draw or the active-fields lookup."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 1 null fields: {fps:.1f} FPS < {MIN_FPS}")


class TestNullFieldDrawZone2:
    def test_null_field_zone2_above_threshold(self, real_game_view):
        """Zone 2 (fully populated nebula) with 30 null fields
        animating alongside every other entity list."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 null fields: {fps:.1f} FPS < {MIN_FPS}")


class TestNullFieldDrawZone2WithVideos:
    def test_null_field_zone2_with_videos_above_threshold(
            self, real_game_view):
        """Worst case: Zone 2 + both videos + all 30 null fields."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 2 null fields + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}")
        finally:
            _stop_both_videos(gv)


class TestNullFieldClookOverhead:
    def test_cloaked_zone2_above_threshold(self, real_game_view):
        """Player parked inside a null field in Zone 2 — the alien AI
        now runs with the synthetic far-away player position, which
        still has to loop over every entity. Ensure the cloak path
        doesn't drop below threshold."""
        from sprites.null_field import NullField
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        # Guarantee cloak by parking the player dead-centre of a big
        # field on top of where the population put the others.
        gv._zone._null_fields.append(
            NullField(gv.player.center_x, gv.player.center_y, size=256))
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 cloaked-player path: {fps:.1f} FPS < {MIN_FPS}")
