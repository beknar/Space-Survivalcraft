"""Performance integration tests — parked ships (multi-ship rendering).

Frame-time / FPS coverage for the multi-ship system: parked ship
rendering + collision checks against every projectile type while
turrets fire.

  * Zone 2 with 3 parked ships (each with cargo + modules) + turrets
    firing + full alien population.

Run with:  ``pytest "unit tests/integration/test_performance_parked_ships.py" -v``
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
#  Zone 2 with parked ships (multi-ship collision + rendering)
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipsZone2:
    def test_parked_ships_zone2_above_threshold(self, real_game_view):
        """Zone 2 with 3 parked ships (each with cargo and modules), full
        alien population, and turrets firing. Tests rendering overhead of
        parked ships + collision checks against all projectile types."""
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip

        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        # Place 3 parked ships with cargo and modules
        cx, cy = gv.player.center_x, gv.player.center_y
        for i in range(3):
            ps = ParkedShip(
                gv._faction, gv._ship_type, i + 1,
                cx + 200 + i * 100, cy + 100)
            ps.cargo_items[(0, 0)] = ("iron", 50)
            ps.module_slots = ["armor_plate", "engine_booster"]
            gv._parked_ships.append(ps)

        # Also build turrets so projectile lists are active
        _open_station_info_turrets(gv)
        gv._station_info.open = False

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 + 3 parked ships: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
