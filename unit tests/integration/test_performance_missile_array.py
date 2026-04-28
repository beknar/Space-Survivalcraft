"""Performance integration tests — Missile Array buildings.

Frame-time / FPS coverage for the Missile Array building (8 arrays
periodically firing at 30 aliens):

  * 8 Missile Arrays + 30 aliens, no videos.
  * Same scenario with both video decoders running (catches per-frame
    interaction between array scanning and the GPU-blit pipeline).

Run with:  ``pytest "unit tests/integration/test_performance_missile_array.py" -v``
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
#  Missile Array perf: 8 arrays + 30 aliens
# ═══════════════════════════════════════════════════════════════════════════

class TestMissileArrayPerf:
    def test_missile_arrays_above_threshold(self, real_game_view):
        """8 Missile Arrays periodically firing at 30 aliens should sustain
        at least the standard FPS threshold."""
        from sprites.building import create_building
        from sprites.alien import SmallAlienShip

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        tex = gv._building_textures["Missile Array"]
        for i in range(8):
            ma = create_building("Missile Array", tex,
                                 WORLD_WIDTH / 2 + (i - 4) * 80,
                                 WORLD_HEIGHT / 2 + 200,
                                 scale=0.5)
            gv.building_list.append(ma)

        for i in range(30):
            a = SmallAlienShip(
                gv._alien_ship_tex, gv._alien_laser_tex,
                WORLD_WIDTH / 2 + (i - 15) * 60,
                WORLD_HEIGHT / 2,
            )
            gv.alien_list.append(a)

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Missile Arrays + 30 aliens: {fps:.1f} FPS < {MIN_FPS}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Missile Array perf with both videos running
# ═══════════════════════════════════════════════════════════════════════════

class TestMissileArrayPerfWithVideos:
    def test_missile_arrays_above_threshold_with_videos(self, real_game_view):
        """Same scenario as TestMissileArrayPerf but with both video
        decoders running. Catches any per-frame interaction between
        MissileArray scanning + the GPU-blit video pipeline."""
        from sprites.building import create_building
        from sprites.alien import SmallAlienShip

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_both_videos_or_skip(gv)
        try:
            tex = gv._building_textures["Missile Array"]
            for i in range(8):
                ma = create_building("Missile Array", tex,
                                     WORLD_WIDTH / 2 + (i - 4) * 80,
                                     WORLD_HEIGHT / 2 + 200, scale=0.5)
                gv.building_list.append(ma)

            for i in range(30):
                a = SmallAlienShip(
                    gv._alien_ship_tex, gv._alien_laser_tex,
                    WORLD_WIDTH / 2 + (i - 15) * 60,
                    WORLD_HEIGHT / 2,
                )
                gv.alien_list.append(a)

            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Missile Arrays + 30 aliens + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
