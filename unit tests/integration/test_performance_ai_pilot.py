"""Performance integration tests — AI Pilot fleets.

Frame-time / FPS coverage for AI-piloted parked ships (orbit Home
Station, scan aliens, fire 0.5 s lasers):

  * 4 AI ships in Zone 1 / Zone 2.
  * 4 AI ships + both videos in Zone 1 / Zone 2.

Run with:  ``pytest "unit tests/integration/test_performance_ai_pilot.py" -v``
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
#  Helpers: spawn home station + AI parked ships
# ═══════════════════════════════════════════════════════════════════════════

def _spawn_home_station(gv):
    """Place a Home Station at the world centre for AI pilot tests."""
    from sprites.building import create_building
    from constants import WORLD_WIDTH, WORLD_HEIGHT
    gv.building_list.clear()
    tex = gv._building_textures["Home Station"]
    home = create_building("Home Station", tex,
                           WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5)
    gv.building_list.append(home)
    return home


def _spawn_ai_parked_ships(gv, home, count: int = 4):
    """Spawn ``count`` AI-piloted parked ships orbiting the Home Station."""
    from sprites.parked_ship import ParkedShip
    import math
    gv._parked_ships.clear()
    for i in range(count):
        angle = 2 * math.pi * i / count
        ps = ParkedShip(
            gv._faction, gv._ship_type, 1,
            home.center_x + math.cos(angle) * 200,
            home.center_y + math.sin(angle) * 200,
        )
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.append(ps)


# ═══════════════════════════════════════════════════════════════════════════
#  AI Pilot fleets — Zone 1 / Zone 2, with and without videos
# ═══════════════════════════════════════════════════════════════════════════

class TestAIPilotZone1:
    def test_ai_pilot_zone1_above_threshold(self, real_game_view):
        """4 AI-piloted parked ships orbiting the Home Station with
        Zone 1's normal population. Each ship scans aliens every frame
        and may emit a laser every 0.5 s."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        home = _spawn_home_station(gv)
        _spawn_ai_parked_ships(gv, home, count=4)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 1 + 4 AI parked ships: {fps:.1f} FPS < {MIN_FPS}"
        )


class TestAIPilotZone2:
    def test_ai_pilot_zone2_above_threshold(self, real_game_view):
        """Same scenario in the Nebula — the zone's heavier baseline."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        home = _spawn_home_station(gv)
        _spawn_ai_parked_ships(gv, home, count=4)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 + 4 AI parked ships: {fps:.1f} FPS < {MIN_FPS}"
        )


class TestAIPilotZone1WithVideos:
    def test_ai_pilot_zone1_with_videos_above_threshold(self, real_game_view):
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        home = _spawn_home_station(gv)
        _spawn_ai_parked_ships(gv, home, count=4)
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 1 + 4 AI ships + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)


class TestAIPilotZone2WithVideos:
    def test_ai_pilot_zone2_with_videos_above_threshold(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        home = _spawn_home_station(gv)
        _spawn_ai_parked_ships(gv, home, count=4)
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 2 + 4 AI ships + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
