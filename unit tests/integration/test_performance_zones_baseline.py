"""Performance integration tests — zone baselines.

Frame-time / FPS coverage for the un-modified zone scenarios:

  * Zone 2 (Nebula) full population — the original 30-FPS bug report.
  * Zone 2 + a 9-module station (turrets fire at ~60 aliens).
  * Zone 1 + boss + station (heavy combat baseline).
  * Zone 2 minimap draw under 200+ entities.
  * Zone 2 alien-asteroid collisions + obstacle avoidance.

Run with:  ``pytest "unit tests/integration/test_performance_zones_baseline.py" -v``
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
#  Zone 2 fully populated (the scenario that dropped to 30 FPS)
# ═══════════════════════════════════════════════════════════════════════════

class TestZone2FullPopulation:
    def test_zone2_with_all_entities_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        and fog of war mostly revealed. This matches the user's original
        report of 30 FPS drops in the Nebula zone."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        assert gv._zone.zone_id == ZoneID.ZONE2

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 full population: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Zone 2 with station buildings (turrets targeting 60 aliens)
# ═══════════════════════════════════════════════════════════════════════════

class TestZone2WithStation:
    def test_zone2_with_9_buildings_above_threshold(self, real_game_view):
        """Zone 2 with a 9-module station: Home Station + 4 Service Modules
        + 2 Turrets + Repair Module + Power Receiver. Turrets fire at ~60
        aliens every frame. This is the heaviest realistic scenario."""
        from sprites.building import create_building

        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        gv.building_list.clear()

        # Build a small station near the player
        cx, cy = gv.player.center_x, gv.player.center_y
        station_types = [
            "Home Station",
            "Service Module", "Service Module",
            "Service Module", "Service Module",
            "Turret 1", "Turret 2",
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

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 + 9 buildings: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Zone 1 with full station + boss active
# ═══════════════════════════════════════════════════════════════════════════

class TestZone1WithBoss:
    def test_zone1_boss_fight_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, a boss, and a station.
        The boss fires spread shots and the station has turrets — heavy
        combat scenario."""
        from sprites.building import create_building
        from combat_helpers import spawn_boss

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Place a small station
        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        home = create_building("Home Station", tex,
                               WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                               scale=0.5)
        gv.building_list.append(home)
        for bt in ("Turret 1", "Turret 2"):
            tex = gv._building_textures[bt]
            b = create_building(bt, tex,
                                WORLD_WIDTH / 2 + 80,
                                WORLD_HEIGHT / 2,
                                laser_tex=gv._turret_laser_tex, scale=0.5)
            gv.building_list.append(b)

        # Spawn the boss
        gv._boss = None
        gv._boss_spawned = False
        gv._boss_defeated = False
        gv._boss_list.clear()
        gv._boss_projectile_list.clear()
        spawn_boss(gv, WORLD_WIDTH / 2, WORLD_HEIGHT / 2)

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 1 boss fight: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Zone 2 minimap with 200+ entities (draw-heavy)
# ═══════════════════════════════════════════════════════════════════════════

class TestMinimapHeavyDraw:
    def test_zone2_minimap_rendering_above_threshold(self, real_game_view):
        """Zone 2 minimap must render dots for ~150 asteroids + ~60 aliens
        + gas areas + buildings using batched draw_points. This test
        ensures the minimap batching optimization holds under load."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        # The minimap draws inside on_draw via HUD. Just measure FPS of
        # the full frame loop — the minimap is a significant fraction.
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 minimap heavy: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Zone 2 alien-asteroid collisions + obstacle avoidance
# ═══════════════════════════════════════════════════════════════════════════

class TestAlienAsteroidZone2:
    def test_alien_asteroid_collision_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens colliding with ~150 asteroids (damage +
        bounce + obstacle avoidance). Tests that the new alien-asteroid
        collision handler + avoidance steering don't cause FPS drops."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        # Move some aliens near asteroids to trigger collisions
        zone = gv._zone
        aliens = list(zone._aliens)[:10]
        asteroids = list(zone._iron_asteroids)[:10]
        for alien, ast in zip(aliens, asteroids):
            alien.center_x = ast.center_x + 20
            alien.center_y = ast.center_y

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 alien-asteroid collisions: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
