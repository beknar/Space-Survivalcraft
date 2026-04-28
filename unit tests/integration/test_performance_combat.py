"""Performance integration tests — heavy combat and escape menu.

Frame-time / FPS coverage for chaotic-battle and overlay scenarios:

  * Heavy combat: player broadside + 2 turrets firing + 20 alien
    projectiles + 10 explosions + 30 hit sparks + 10 fire sparks.
  * Escape menu open: world still rendered underneath the overlay,
    with the first-open gc.collect() stall absorbed.

Run with:  ``pytest "unit tests/integration/test_performance_combat.py" -v``
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
#  Heavy combat — projectiles + explosions + sparks everywhere
# ═══════════════════════════════════════════════════════════════════════════

class TestHeavyCombat:
    def test_heavy_combat_above_threshold(self, real_game_view):
        """Simulate a chaotic battle: player broadside active, 2 turrets
        firing, 20 alien projectiles in flight, 10 explosions playing,
        and 30 hit sparks active simultaneously. This is the peak
        per-frame entity count during intense Zone 1 combat."""
        from sprites.building import create_building
        from sprites.explosion import Explosion, HitSpark, FireSpark
        from sprites.projectile import Projectile

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Place 2 turrets
        gv.building_list.clear()
        tex_home = gv._building_textures["Home Station"]
        home = create_building("Home Station", tex_home,
                               WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                               scale=0.5)
        gv.building_list.append(home)
        for i, bt in enumerate(("Turret 1", "Turret 2")):
            tex = gv._building_textures[bt]
            b = create_building(bt, tex,
                                WORLD_WIDTH / 2 + 80 * (i + 1),
                                WORLD_HEIGHT / 2,
                                laser_tex=gv._turret_laser_tex, scale=0.5)
            gv.building_list.append(b)

        # Spawn 20 alien projectiles near the player
        for i in range(20):
            p = Projectile(
                gv._alien_laser_tex,
                gv.player.center_x + i * 30,
                gv.player.center_y + 100,
                heading=180.0, speed=300.0, max_dist=800.0,
                scale=0.5, damage=10,
            )
            gv.alien_projectile_list.append(p)

        # Spawn 10 explosions
        for i in range(10):
            exp = Explosion(
                gv._explosion_frames,
                gv.player.center_x + i * 50 - 250,
                gv.player.center_y + 150,
            )
            gv.explosion_list.append(exp)

        # Spawn 30 hit sparks + 10 fire sparks
        gv.hit_sparks = [
            HitSpark(gv.player.center_x + i * 20, gv.player.center_y + 80)
            for i in range(30)
        ]
        gv.fire_sparks = [
            FireSpark(gv.player.center_x + i * 30, gv.player.center_y - 50)
            for i in range(10)
        ]

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Heavy combat: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Escape menu open — GC stall + double-layer rendering
# ═══════════════════════════════════════════════════════════════════════════

class TestEscapeMenuOpen:
    def test_escape_menu_open_above_threshold(self, real_game_view):
        """Escape menu open: the game world is still rendered underneath
        the menu overlay. On first open, gc.collect() runs (potentially
        a stall). Subsequent frames must stay above 40 FPS."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Open the escape menu (this triggers gc.collect on first update)
        gv._escape_menu.open = True
        gv._gc_ran = False

        # First update absorbs the GC stall
        gv.on_update(1 / 60)
        gv.on_draw()

        # Now measure steady-state with menu open
        fps = _measure_fps(gv)

        gv._escape_menu.open = False

        assert fps >= MIN_FPS, (
            f"Escape menu open: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
