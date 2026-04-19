"""Combined-stress performance tests at the station with both videos.

Each test stacks the heaviest concurrent rendering and update systems
the game can have running at a station:

  - AI-piloted parked ship orbiting the Home Station (full AI Pilot
    update path: orbit_patrol + shield regen + module update)
  - Player parked AT the station (turret targeting hot, station
    shield update with player in range)
  - Character video playing (160×160 portrait, FFmpeg decode + GPU
    blit downscale)
  - Music video playing (16:9 panel, second FFmpeg decode + blit)

Variants add an extra UI overlay on top:

  - Vanilla (no extra menu) — measures the four-system baseline
  - T menu open — Station Info panel + inactive-zone panel
  - B menu open — Build Menu overlay
  - Video properties menu open — escape menu in ``video_props`` mode

If any of these regress below the FPS floor, the named test points
straight at the offending combination.

Run with:
    pytest "unit tests/integration/test_performance_station_combo.py" -v -s
"""
from __future__ import annotations

import math

import arcade
import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID

MIN_FPS = 40

from integration.conftest import measure_fps as _measure_fps


# ── Shared scene setup ────────────────────────────────────────────────────

def _setup_station_with_ai_pilot(gv):
    """Common scenery: Zone 1, Home Station + 2 turrets at world
    centre, one AI-piloted parked ship orbiting at 250 px, and the
    player sitting just off the station's edge so turret targeting
    + station shield + AI Pilot all run hot."""
    from sprites.building import create_building
    from sprites.parked_ship import ParkedShip

    if gv._zone.zone_id != ZoneID.MAIN:
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2

    gv.building_list.clear()
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))
    for bt, ox in (("Turret 1", 80), ("Turret 2", -80)):
        t_tex = gv._building_textures[bt]
        b = create_building(bt, t_tex, cx + ox, cy,
                            laser_tex=gv._turret_laser_tex, scale=0.5)
        gv.building_list.append(b)

    gv._parked_ships.clear()
    ps = ParkedShip(gv._faction, gv._ship_type, 1,
                    cx + 250, cy)
    ps.module_slots = ["ai_pilot"]
    gv._parked_ships.append(ps)

    # Player parked next to the Home Station (within STATION_INFO_RANGE
    # so T/B menu interactions in real gameplay would be available).
    gv.player.center_x = cx + 60
    gv.player.center_y = cy + 60

    # Make invulnerable so the ~10 s measurement window doesn't end
    # in a death screen and pollute the FPS sample.
    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999


def _start_both_videos(gv) -> bool:
    """Start the character + music videos.  Returns False (so the
    test can pytest.skip) if no video files / no FFmpeg."""
    from video_player import scan_characters_dir, character_video_path
    chars = scan_characters_dir()
    if not chars:
        return False
    paths = []
    for name in chars:
        p = character_video_path(name)
        if p is not None:
            paths.append(p)
        if len(paths) >= 2:
            break
    if not paths:
        return False
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    music_path = paths[1] if len(paths) > 1 else paths[0]
    gv._video_player.play(music_path, volume=0.0)
    dt = 1 / 60
    for _ in range(10):
        gv.on_update(dt)
        gv.on_draw()
    return gv._char_video_player.active or gv._video_player.active


def _stop_both_videos(gv) -> None:
    try:
        gv._char_video_player.stop()
    except Exception:
        pass
    try:
        gv._video_player.stop()
    except Exception:
        pass


def _open_t_menu(gv) -> None:
    """Open the Station Info (T) overlay with live stats."""
    from sprites.building import compute_modules_used, compute_module_capacity
    from draw_logic import compute_world_stats, compute_inactive_zone_stats
    # Make sure the inactive Zone 2 stats panel has data to render.
    if gv._zone2 is None:
        gv._transition_zone(ZoneID.ZONE2)
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
    gv._station_info.toggle(
        gv.building_list,
        compute_modules_used(gv.building_list),
        compute_module_capacity(gv.building_list),
        stat_lines=compute_world_stats(gv),
        inactive_zone_stats=compute_inactive_zone_stats(gv),
    )


def _open_b_menu(gv) -> None:
    """Open the Build Menu overlay."""
    if not gv._build_menu.open:
        gv._build_menu.toggle()


def _open_video_props_menu(gv) -> None:
    """Open the escape menu in its ``video_props`` sub-mode."""
    gv._escape_menu.open = True
    gv._escape_menu._set_mode("video_props")


# ═══════════════════════════════════════════════════════════════════════════
#  1. AI ship circling station + player at station + both videos
# ═══════════════════════════════════════════════════════════════════════════

class TestStationWithAIAndBothVideos:
    def test_ai_pilot_plus_both_videos_at_station_above_threshold(
            self, real_game_view):
        """Baseline of the four-system stack: AI pilot orbit + player
        at station + character video + music video.  Catches any
        regression that emerges only when these systems run together."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        try:
            fps = _measure_fps(gv)
            print(f"  [perf-combo] AI + station + 2 videos: {fps:.1f} FPS")
            assert fps >= MIN_FPS, (
                f"AI + station + both videos: {fps:.1f} FPS < {MIN_FPS}")
        finally:
            _stop_both_videos(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  2. + T menu open
# ═══════════════════════════════════════════════════════════════════════════

class TestStationWithAIBothVideosAndTMenu:
    def test_t_menu_with_combo_above_threshold(self, real_game_view):
        """T menu open on top of the four-system stack.  The Station
        Info overlay rebuilds stat strings every frame; with AI pilot
        + both videos already in flight, this is the worst-case for
        the T-key UI path."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        _open_t_menu(gv)
        assert gv._station_info.open
        try:
            fps = _measure_fps(gv)
            print(f"  [perf-combo] T menu + combo: {fps:.1f} FPS")
            assert fps >= MIN_FPS, (
                f"T menu + AI + station + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}")
        finally:
            gv._station_info.open = False
            _stop_both_videos(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  3. + B menu open
# ═══════════════════════════════════════════════════════════════════════════

class TestStationWithAIBothVideosAndBMenu:
    def test_b_menu_with_combo_above_threshold(self, real_game_view):
        """Build menu open on top of the four-system stack.  First
        perf coverage of the build menu under any load — catches a
        future regression where opening the build overlay tanks FPS."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        _open_b_menu(gv)
        assert gv._build_menu.open
        try:
            fps = _measure_fps(gv)
            print(f"  [perf-combo] B menu + combo: {fps:.1f} FPS")
            assert fps >= MIN_FPS, (
                f"B menu + AI + station + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}")
        finally:
            gv._build_menu.open = False
            _stop_both_videos(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  4. + Video properties menu open
# ═══════════════════════════════════════════════════════════════════════════

class TestStationWithAIBothVideosAndVideoPropsMenu:
    def test_video_props_menu_with_combo_above_threshold(
            self, real_game_view):
        """Escape menu in video_props sub-mode on top of the four-
        system stack.  First perf coverage of the video-properties
        UI — particularly worth measuring because it overlays the
        same surface where the music video is rendering."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        _open_video_props_menu(gv)
        assert gv._escape_menu.open
        try:
            fps = _measure_fps(gv)
            print(f"  [perf-combo] video-props + combo: {fps:.1f} FPS")
            assert fps >= MIN_FPS, (
                f"Video props + AI + station + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}")
        finally:
            gv._escape_menu.open = False
            _stop_both_videos(gv)
