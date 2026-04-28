"""Performance integration tests — station shield + AI Pilot shields.

Frame-time / FPS coverage for the station-shield bubble + the
AI-piloted parked-ship yellow shields:

  * Station shield active in Zone 1 with aliens shooting.
  * Station shield active in Zone 2 (Nebula).
  * Station shield active in Zone 2 with both videos running.
  * AI-piloted fleet wearing yellow shield bubbles in the Nebula.

Run with:  ``pytest "unit tests/integration/test_performance_station_shield.py" -v``
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
#  Helpers: spawn AI parked ships (used by shielded fleet test)
# ═══════════════════════════════════════════════════════════════════════════

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
#  Station shield + AI Pilot shields — new combat-path perf coverage
# ═══════════════════════════════════════════════════════════════════════════

def _spawn_station_with_shield_gen(gv):
    """Home Station + Shield Generator — drives station-shield spawn."""
    from sprites.building import create_building
    from constants import WORLD_WIDTH, WORLD_HEIGHT
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    hs_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", hs_tex, cx, cy, scale=0.5))
    sg_tex = gv._building_textures["Shield Generator"]
    gv.building_list.append(create_building(
        "Shield Generator", sg_tex, cx + 80, cy, scale=0.5))
    # Tick once so update_station_shield creates the sprite.
    gv._station_shield_hp = 0
    gv._station_shield_sprite = None
    gv.on_update(1 / 60)
    return gv.building_list[0], (cx, cy)


class TestStationShieldZone1:
    def test_station_shield_active_above_threshold(self, real_game_view):
        """Zone 1 with a Shield Generator + aliens shooting at the
        station. The station shield draw/update + absorb path must
        stay above MIN_FPS."""
        from sprites.alien import SmallAlienShip
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _spawn_station_with_shield_gen(gv)
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        for i in range(15):
            a = SmallAlienShip(
                gv._alien_ship_tex, gv._alien_laser_tex,
                cx + 400 + (i - 7) * 40, cy)
            gv.alien_list.append(a)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 1 station shield combat: {fps:.1f} FPS < {MIN_FPS}")


class TestStationShieldZone2:
    def test_station_shield_zone2_above_threshold(self, real_game_view):
        """Nebula baseline + station shield bubble + full alien pop."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _spawn_station_with_shield_gen(gv)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 station shield: {fps:.1f} FPS < {MIN_FPS}")


class TestStationShieldZone2WithVideos:
    def test_station_shield_zone2_with_videos_above_threshold(
            self, real_game_view):
        """Worst case: Nebula + station shield + both videos running."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _spawn_station_with_shield_gen(gv)
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 2 station shield + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}")
        finally:
            _stop_both_videos(gv)


class TestAIPilotShieldedFleetZone2:
    def test_ai_pilot_fleet_with_yellow_shields_above_threshold(
            self, real_game_view):
        """4 AI-piloted parked ships + each now draws its own yellow
        shield bubble + half-rate regen inside the Nebula."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        home, _ = _spawn_station_with_shield_gen(gv)
        _spawn_ai_parked_ships(gv, home, count=4)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 shielded AI fleet: {fps:.1f} FPS < {MIN_FPS}")
