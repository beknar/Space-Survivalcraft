"""Performance integration tests — Station Info panel (T menu).

Frame-time / FPS coverage for the Station Info overlay (current-zone
stats + inactive-zone panel + module-capacity readout):

  * Station Info open in Zone 1 with full population.
  * Station Info open in Zone 2 (Nebula) with full population.
  * Station Info + music + level 2 ship in Zone 1.
  * Station Info + music + level 2 ship in Zone 2.
  * Full scenario: Station Info + 3 turrets actively firing + music
    + L2 ship, in both Zone 1 and Zone 2.
  * Bare-bones T-menu open in Zone 2 (catches accidental per-frame
    Text re-creation during a future StationInfo refactor).

Run with:  ``pytest "unit tests/integration/test_performance_station_info.py" -v``
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
#  Helper: open Station Info with full stats
# ═══════════════════════════════════════════════════════════════════════════

def _open_station_info(gv):
    """Open Station Info panel with full stats and inactive zone data."""
    from sprites.building import create_building, compute_modules_used, compute_module_capacity
    from draw_logic import compute_world_stats, compute_inactive_zone_stats

    # Build a station near the player so the panel can open
    if not any(b.building_type == "Home Station" for b in gv.building_list):
        gv.building_list.clear()
        cx, cy = gv.player.center_x, gv.player.center_y
        for i, bt in enumerate([
            "Home Station", "Service Module", "Service Module",
            "Turret 1", "Repair Module",
        ]):
            tex = gv._building_textures[bt]
            laser = gv._turret_laser_tex if "Turret" in bt else None
            b = create_building(bt, tex, cx + 200 + i * 60, cy,
                                laser_tex=laser, scale=0.5)
            gv.building_list.append(b)

    gv._station_info.toggle(
        gv.building_list,
        compute_modules_used(gv.building_list),
        compute_module_capacity(gv.building_list),
        stat_lines=compute_world_stats(gv),
        inactive_zone_stats=compute_inactive_zone_stats(gv),
    )


class TestStationInfoZone1:
    def test_station_info_zone1_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, station buildings, and
        Station Info panel open showing current zone stats + inactive
        Zone 2 stats. Stresses the Station Info panel rendering and
        live update loop."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Ensure Zone 2 exists so the inactive panel has data
        if gv._zone2 is None:
            gv._transition_zone(ZoneID.ZONE2)
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        _open_station_info(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv)
        gv._station_info.open = False

        assert fps >= MIN_FPS, (
            f"Station Info Zone 1: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Station Info panel open in Zone 2 with full population
# ═══════════════════════════════════════════════════════════════════════════

class TestStationInfoZone2:
    def test_station_info_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        station buildings, and Station Info panel open showing current
        zone stats + inactive Double Star stats. This is the heaviest
        Station Info scenario."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        _open_station_info(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv)
        gv._station_info.open = False

        assert fps >= MIN_FPS, (
            f"Station Info Zone 2: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: start music + set ship level 2
# ═══════════════════════════════════════════════════════════════════════════

def _start_music(gv):
    """Start OST music playback if tracks are available. Returns True if
    music is playing."""
    if gv._music_tracks:
        from settings import audio as _audio
        sound, name = gv._music_tracks[0]
        gv._current_track_name = name
        gv._music_player = arcade.play_sound(sound, volume=_audio.music_volume)
        return gv._music_player is not None
    return False


def _set_ship_level_2(gv):
    """Upgrade the player ship to level 2 by swapping its texture."""
    from sprites.player import PlayerShip
    gv._ship_level = 2
    # Rebuild the player with level 2 texture
    old = gv.player
    new_player = PlayerShip(
        faction=gv._faction, ship_type=gv._ship_type, ship_level=2)
    new_player.center_x = old.center_x
    new_player.center_y = old.center_y
    new_player.vel_x = old.vel_x
    new_player.vel_y = old.vel_y
    new_player.hp = old.hp
    new_player.max_hp = old.max_hp
    new_player.shields = old.shields
    new_player.max_shields = old.max_shields
    gv.player_list.clear()
    gv.player = new_player
    gv.player_list.append(new_player)


def _stop_music(gv):
    """Stop music playback."""
    if gv._music_player is not None:
        try:
            arcade.stop_sound(gv._music_player)
        except Exception:
            pass
        gv._music_player = None


# ═══════════════════════════════════════════════════════════════════════════
#  Station Info + music + level 2 ship in Zone 1
# ═══════════════════════════════════════════════════════════════════════════

class TestStationInfoMusicZone1:
    def test_station_info_music_zone1_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, station buildings, Station
        Info panel open, level 2 ship, and background music playing. This
        combines the Station Info overlay, music decode overhead, and the
        higher-res level 2 ship texture."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Ensure Zone 2 exists for inactive panel
        if gv._zone2 is None:
            gv._transition_zone(ZoneID.ZONE2)
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info(gv)
        assert gv._station_info.open

        # Extra warmup to absorb music player initialization spike
        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        assert fps >= MIN_FPS, (
            f"Station Info + music + L2 ship Zone 1 "
            f"(music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Station Info + music + level 2 ship in Zone 2
# ═══════════════════════════════════════════════════════════════════════════

class TestStationInfoMusicZone2:
    def test_station_info_music_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        station buildings, Station Info panel open, level 2 ship, and
        background music playing. Heaviest combined Station Info scenario."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info(gv)
        assert gv._station_info.open

        # Extra warmup to absorb music player initialization spike
        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        assert fps >= MIN_FPS, (
            f"Station Info + music + L2 ship Zone 2 "
            f"(music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: build a heavy station with multiple turrets firing at aliens
# ═══════════════════════════════════════════════════════════════════════════

def _build_turret_station(gv):
    """Build a 9-module station with 3 turrets near the player, and ensure
    aliens are within turret range so the turrets actively fire."""
    from sprites.building import create_building

    gv.building_list.clear()
    cx, cy = gv.player.center_x, gv.player.center_y
    station_types = [
        "Home Station",
        "Service Module", "Service Module", "Service Module",
        "Turret 1", "Turret 2", "Turret 1",
        "Repair Module",
        "Power Receiver",
    ]
    spacing = 60
    for i, bt in enumerate(station_types):
        tex = gv._building_textures[bt]
        laser = gv._turret_laser_tex if "Turret" in bt else None
        bx = cx + 200 + (i % 3) * spacing
        by = cy + (i // 3) * spacing
        b = create_building(bt, tex, bx, by, laser_tex=laser, scale=0.5)
        gv.building_list.append(b)

    # Move a few aliens within turret range so turrets actively fire
    from constants import TURRET_RANGE
    turret_x = cx + 200
    turret_y = cy
    alien_list = gv.alien_list
    from zones import ZoneID
    if gv._zone.zone_id == ZoneID.ZONE2 and hasattr(gv._zone, '_aliens'):
        alien_list = gv._zone._aliens
    moved = 0
    for alien in alien_list:
        if moved >= 8:
            break
        alien.center_x = turret_x + (moved % 3 - 1) * 100
        alien.center_y = turret_y + (moved // 3) * 100 + 150
        moved += 1


def _open_station_info_turrets(gv):
    """Build turret station and open Station Info panel."""
    from sprites.building import compute_modules_used, compute_module_capacity
    from draw_logic import compute_world_stats, compute_inactive_zone_stats

    _build_turret_station(gv)
    gv._station_info.toggle(
        gv.building_list,
        compute_modules_used(gv.building_list),
        compute_module_capacity(gv.building_list),
        stat_lines=compute_world_stats(gv),
        inactive_zone_stats=compute_inactive_zone_stats(gv),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Full scenario — Station Info + turrets + music + L2 ship, Zone 1
# ═══════════════════════════════════════════════════════════════════════════

class TestFullScenarioZone1:
    def test_full_scenario_zone1_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, 9-module station with 3
        turrets actively firing, Station Info panel open, level 2 ship,
        and background music playing. This is the heaviest realistic
        Zone 1 scenario combining all overlays and combat systems."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        if gv._zone2 is None:
            gv._transition_zone(ZoneID.ZONE2)
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info_turrets(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        assert fps >= MIN_FPS, (
            f"Full scenario Zone 1 (music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Full scenario — Station Info + turrets + music + L2 ship, Zone 2
# ═══════════════════════════════════════════════════════════════════════════

class TestFullScenarioZone2:
    def test_full_scenario_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        9-module station with 3 turrets actively firing, Station Info
        panel open, level 2 ship, and background music playing. Absolute
        heaviest realistic scenario — uses 35 FPS threshold (vs 40 for
        lighter tests) because this combines every expensive system."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info_turrets(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        _FULL_SCENARIO_MIN = 35  # relaxed: absolute worst-case scenario
        assert fps >= _FULL_SCENARIO_MIN, (
            f"Full scenario Zone 2 (music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {_FULL_SCENARIO_MIN} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  T-menu open in the Nebula (catches a Text-recreation regression)
# ═══════════════════════════════════════════════════════════════════════════

class TestStationInfoOpenInZone2Fps:
    """Open the T menu in the Nebula (worst case — 7 stat rows + 16
    buildings + inactive-zone panel) and run the FPS measurement loop.
    Catches the case where a future StationInfo redraw refactor
    accidentally re-creates Text objects every frame."""

    def test_t_menu_open_zone2_above_threshold(self, real_game_view):
        from station_info import StationInfo
        from draw_logic import (
            compute_world_stats, compute_inactive_zone_stats,
        )
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        info = StationInfo()
        info.toggle(
            gv.building_list, 0, 0,
            stat_lines=compute_world_stats(gv),
            inactive_zone_stats=compute_inactive_zone_stats(gv),
        )
        # Replace gv._station_info temporarily so the regular draw
        # path picks it up — but easier to just measure manually.
        import time as _time
        dt = 1 / 60
        for _ in range(10):
            gv.on_update(dt)
            gv.on_draw()
            info.draw()
        n = 60
        t0 = _time.perf_counter()
        for _ in range(n):
            gv.on_update(dt)
            gv.on_draw()
            info.draw()
        elapsed = _time.perf_counter() - t0
        fps = n / elapsed if elapsed > 0 else 999.0
        print(f"  [perf] zone2 + T menu open: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Zone 2 with T menu open: {fps:.1f} FPS < {MIN_FPS}")
