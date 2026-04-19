"""5-minute soak tests for the worst-case station combo scenarios.

Mirrors the four ``test_performance_station_combo.py`` perf tests
under sustained load:

  - AI-piloted parked ship orbiting Home Station
  - Player parked AT the station
  - Character video playing
  - Music video playing

…with the variant menu opened on top: nothing, T menu, B menu, or
video-properties menu.  Catches accumulating leaks (FFmpeg per-load
leak from periodic restart, AI-pilot weapon SFX accumulation, build-
menu render cache growth, etc.) over the full ``SOAK_DURATION_S``
that the FPS-only perf tests miss.

NOTE: video soaks tolerate the documented pyglet ``Player.delete()``
source-leak by raising ``max_memory_growth_mb`` (see
``test_soak_video_player.py`` for the full background).

Run with:
    pytest "unit tests/integration/test_soak_station_combo.py" -v -s
"""
from __future__ import annotations

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


# Tolerant cap — the music video is restarted on loop every ~few minutes
# inside ``run_soak``'s 5-minute window via ``_restart_for_loop``, which
# leaks ~12 MB per pyglet.media.load() call (see test_soak_video_player.py).
# 600 MB is enough headroom for the ~1-2 loop restarts the soak typically
# triggers without masking unrelated leaks.
_VIDEO_SOAK_MEM_CAP_MB = 600

# FPS floor — the first sample includes FFmpeg startup cost and on slower
# dev hardware can dip to ~10-20 FPS.  Steady-state runs much higher.
# Same rationale as test_soak_video_player.py.
_VIDEO_SOAK_MIN_FPS = 8


# ── Shared scene setup ────────────────────────────────────────────────────

def _setup_station_with_ai_pilot(gv):
    """Zone 1 + Home Station (with 2 turrets) at world centre + one
    AI-piloted parked ship orbiting + player parked at the station."""
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

    gv.player.center_x = cx + 60
    gv.player.center_y = cy + 60

    make_invulnerable(gv)


def _start_both_videos(gv) -> bool:
    """Start char + music video players.  Returns False if FFmpeg or
    video files aren't available so the soak can pytest.skip."""
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
    from sprites.building import compute_modules_used, compute_module_capacity
    from draw_logic import compute_world_stats, compute_inactive_zone_stats
    if gv._zone2 is None:
        gv._transition_zone(ZoneID.ZONE2)
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        make_invulnerable(gv)
    gv._station_info.toggle(
        gv.building_list,
        compute_modules_used(gv.building_list),
        compute_module_capacity(gv.building_list),
        stat_lines=compute_world_stats(gv),
        inactive_zone_stats=compute_inactive_zone_stats(gv),
    )


def _open_b_menu(gv) -> None:
    if not gv._build_menu.open:
        gv._build_menu.toggle()


def _open_video_props_menu(gv) -> None:
    gv._escape_menu.open = True
    gv._escape_menu._set_mode("video_props")


def _make_combo_tick(gv):
    """Standard tick for the soak — top up player HP/shields and
    advance one frame.  All overlay and update systems are already
    active before run_soak starts."""
    def tick(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.player.shields = gv.player.max_shields
        gv.on_update(dt)
        gv.on_draw()

    return tick


# ═══════════════════════════════════════════════════════════════════════════
#  1. AI ship circling station + player at station + both videos
# ═══════════════════════════════════════════════════════════════════════════

import pytest


class TestSoakStationWithAIAndBothVideos:
    def test_ai_pilot_plus_both_videos_at_station_5min_soak(
            self, real_game_view):
        """5-minute baseline soak — AI pilot + station + both videos
        without any extra UI overlay.  Catches accumulating leaks
        in the four-system stack itself."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        try:
            run_soak(
                gv, "AI + station + 2 videos",
                _make_combo_tick(gv),
                min_fps=_VIDEO_SOAK_MIN_FPS,
                max_memory_growth_mb=_VIDEO_SOAK_MEM_CAP_MB,
            )
        finally:
            _stop_both_videos(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  2. + T menu open for the full 5 minutes
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakStationWithAIBothVideosAndTMenu:
    def test_t_menu_with_combo_5min_soak(self, real_game_view):
        """Station Info panel held open for 5 minutes on top of AI
        pilot + station + both videos.  Stresses live stat update
        cost + Text reposition + inactive-zone panel rebuilds under
        sustained dual-video load."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        _open_t_menu(gv)
        assert gv._station_info.open
        try:
            run_soak(
                gv, "T menu + AI + station + 2 videos",
                _make_combo_tick(gv),
                min_fps=_VIDEO_SOAK_MIN_FPS,
                max_memory_growth_mb=_VIDEO_SOAK_MEM_CAP_MB,
            )
        finally:
            gv._station_info.open = False
            _stop_both_videos(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  3. + B menu open for the full 5 minutes
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakStationWithAIBothVideosAndBMenu:
    def test_b_menu_with_combo_5min_soak(self, real_game_view):
        """Build menu held open for 5 minutes on top of the combo
        stack.  First soak coverage of the build menu — guards
        against a future regression where the build overlay leaks
        sprite-list state on every redraw."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        _open_b_menu(gv)
        assert gv._build_menu.open
        try:
            run_soak(
                gv, "B menu + AI + station + 2 videos",
                _make_combo_tick(gv),
                min_fps=_VIDEO_SOAK_MIN_FPS,
                max_memory_growth_mb=_VIDEO_SOAK_MEM_CAP_MB,
            )
        finally:
            gv._build_menu.open = False
            _stop_both_videos(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  4. + Video properties menu open for the full 5 minutes
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakStationWithAIBothVideosAndVideoPropsMenu:
    def test_video_props_menu_with_combo_5min_soak(self, real_game_view):
        """Escape menu in video_props mode held open for 5 minutes on
        top of the combo stack.  Particularly worth running because
        the video-properties UI sits over the same surface where the
        music video draws — a regression in the stack would surface
        as either a video glitch or a measurable FPS / memory drift."""
        gv = real_game_view
        _setup_station_with_ai_pilot(gv)
        if not _start_both_videos(gv):
            pytest.skip("video files / FFmpeg not available")
        _open_video_props_menu(gv)
        assert gv._escape_menu.open
        try:
            run_soak(
                gv, "Video-props menu + AI + station + 2 videos",
                _make_combo_tick(gv),
                min_fps=_VIDEO_SOAK_MIN_FPS,
                max_memory_growth_mb=_VIDEO_SOAK_MEM_CAP_MB,
            )
        finally:
            gv._escape_menu.open = False
            _stop_both_videos(gv)
