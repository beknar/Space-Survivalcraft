"""Performance tests for the Nebula boss combat scene.

Covers the new sprite + attack paths:
  - Nebula boss sprite draw alongside station + turrets
  - Zone 2 combat with Nebula boss firing gas clouds + cone
  - Worst case: Nebula boss + many active gas clouds on screen

Run with:
    pytest "unit tests/integration/test_performance_nebula_boss.py" -v -s
"""
from __future__ import annotations

import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID

MIN_FPS = 40

from integration.conftest import measure_fps as _measure_fps


def _setup_nebula_combat(gv):
    """Zone 2 + Home Station + 2 turrets + spawned Nebula boss.
    Player placed within aggro range so the boss fires every tick."""
    from sprites.building import create_building
    from combat_helpers import spawn_nebula_boss

    gv._transition_zone(ZoneID.ZONE2)
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))
    for bt, ox in (("Turret 1", 80), ("Turret 2", -80)):
        t_tex = gv._building_textures[bt]
        gv.building_list.append(create_building(
            bt, t_tex, cx + ox, cy,
            laser_tex=gv._turret_laser_tex, scale=0.5))

    # Stock enough iron to afford the 100-iron spawn.
    gv.inventory._items[(0, 0)] = ("iron", 500)
    gv.inventory._mark_dirty()
    gv._nebula_boss = None
    assert spawn_nebula_boss(gv) is True

    # Park the player within boss aggro range so the gas/cannon
    # attacks fire every cooldown.
    from constants import BOSS_DETECT_RANGE
    gv.player.center_x = gv._nebula_boss.center_x + (BOSS_DETECT_RANGE * 0.6)
    gv.player.center_y = gv._nebula_boss.center_y

    # Invulnerable for the duration of the measurement window.
    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999


class TestNebulaBossCombatFps:
    def test_nebula_boss_combat_above_threshold(self, real_game_view):
        """Baseline: Nebula boss + station + player in aggro range
        in Zone 2."""
        gv = real_game_view
        _setup_nebula_combat(gv)
        fps = _measure_fps(gv)
        print(f"  [perf-nebula-boss] combat: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Nebula boss combat: {fps:.1f} FPS < {MIN_FPS}")


class TestNebulaBossManyGasCloudsFps:
    def test_20_gas_clouds_above_threshold(self, real_game_view):
        """Worst case: 20 gas clouds active simultaneously."""
        from sprites.nebula_boss import GasCloudProjectile
        import random as _r
        gv = real_game_view
        _setup_nebula_combat(gv)
        # Pre-populate a fat gas-cloud list.
        gv._nebula_gas_clouds = []
        for _ in range(20):
            x = gv.player.center_x + _r.uniform(-300, 300)
            y = gv.player.center_y + _r.uniform(-300, 300)
            heading = _r.uniform(0, 360)
            gv._nebula_gas_clouds.append(
                GasCloudProjectile(x, y, heading, damage=15.0))
        fps = _measure_fps(gv)
        print(f"  [perf-nebula-boss] 20 gas clouds: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Nebula boss + 20 gas clouds: {fps:.1f} FPS < {MIN_FPS}")


class TestNebulaBossConeActiveFps:
    def test_cone_active_above_threshold(self, real_game_view):
        """Force the cone attack active and measure — draw path
        adds a filled triangle + per-frame contains_point check."""
        gv = real_game_view
        _setup_nebula_combat(gv)
        nb = gv._nebula_boss
        nb._cone_active = True
        nb._cone_timer = 5.0   # keep active through the full measurement
        nb._cone_dir_x = 1.0
        nb._cone_dir_y = 0.0
        fps = _measure_fps(gv)
        print(f"  [perf-nebula-boss] cone active: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Nebula boss cone: {fps:.1f} FPS < {MIN_FPS}")
