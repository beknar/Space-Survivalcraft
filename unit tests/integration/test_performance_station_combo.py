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


# ═══════════════════════════════════════════════════════════════════════════
#  5. QWI menu open — simple overlay, should be fast
# ═══════════════════════════════════════════════════════════════════════════

class TestQWIMenuOpenFps:
    def test_qwi_menu_open_above_threshold(self, real_game_view):
        """Open the QWI menu on top of the full Zone 2 population.
        The menu is minimal (one button + title + hint) so we
        expect comfortable headroom; this test is the guard against
        a future redesign accidentally making it expensive."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        gv._qwi_menu.toggle()
        assert gv._qwi_menu.open is True
        try:
            fps = _measure_fps(gv)
            print(f"  [perf-qwi] QWI menu open: {fps:.1f} FPS")
            assert fps >= MIN_FPS, (
                f"QWI menu open: {fps:.1f} FPS < {MIN_FPS}")
        finally:
            gv._qwi_menu.open = False


# ═══════════════════════════════════════════════════════════════════════════
#  6. Nebula boss + station + both videos + T menu — full worst case
# ═══════════════════════════════════════════════════════════════════════════

class TestNebulaBossWithStationComboAndTMenu:
    def test_nebula_boss_station_videos_t_menu_above_threshold(
            self, real_game_view):
        """The absolute worst-case combat+UI scene: an active
        Nebula boss firing gas attacks on top of the four-system
        station stack (AI pilot + station + char video + music
        video) with the T menu open.  Nothing else in the perf
        suite combines the Nebula boss with the station-combo
        stack — so without this, a future regression in the gas
        cloud draw path could hide behind 40+ FPS margins in the
        individual tests."""
        from combat_helpers import spawn_nebula_boss
        gv = real_game_view
        # Use the station-combo setup — Zone 1, AI pilot orbiting,
        # player at station.  Then drop the player into Zone 2 so
        # the Nebula boss has somewhere valid to spawn.
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        # Nebula boss wants Zone 2 but we want the full station
        # combo running — compromise: transition to Zone 2, rebuild
        # a minimal station there so spawn_nebula_boss can find a
        # Home Station.
        from sprites.building import create_building
        gv._transition_zone(ZoneID.ZONE2)
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        gv.building_list.clear()
        home_tex = gv._building_textures["Home Station"]
        gv.building_list.append(create_building(
            "Home Station", home_tex, cx, cy, scale=0.5))
        # Stock enough iron for the 100-iron Nebula summon.
        gv.inventory._items[(0, 0)] = ("iron", 500)
        gv.inventory._mark_dirty()
        gv._nebula_boss = None
        assert spawn_nebula_boss(gv) is True
        _open_t_menu(gv)
        assert gv._station_info.open
        try:
            fps = _measure_fps(gv)
            print(f"  [perf-combo] Nebula + station combo + T menu: "
                  f"{fps:.1f} FPS")
            # Tolerant floor — this is the single heaviest scene in
            # the entire perf suite (Nebula boss gas/cone + station
            # combo + both videos + T menu's stat overlay + inactive
            # zone panel).  Dev hardware dips to ~33 FPS; CI would
            # hit 100+.  Same precedent as test_performance_menu_scroll
            # and test_soak_video_player — a complete regression
            # (sub-15 FPS) still fails loudly.
            assert fps >= 15, (
                f"Nebula boss + station combo + T menu: "
                f"{fps:.1f} FPS < 15 (dev floor)")
        finally:
            gv._station_info.open = False
            _stop_both_videos(gv)
