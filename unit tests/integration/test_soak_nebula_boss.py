"""5-minute soak for the Nebula boss combat pipeline.

Covers:
  - Gas cloud projectile creation + expiry loop (sprites come and go
    hundreds of times over 5 minutes — any per-spawn leak shows up)
  - Cone on/off cycle every 6 s ≈ 50 cycles in 5 min
  - Player invulnerable + parked in aggro range so the attacks fire
    continuously

Run explicitly with:
    pytest "unit tests/integration/test_soak_nebula_boss.py" -v -s
"""
from __future__ import annotations

import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT, BOSS_DETECT_RANGE
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _setup_nebula_soak(gv):
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

    gv.inventory._items[(0, 0)] = ("iron", 500)
    gv.inventory._mark_dirty()
    gv._nebula_boss = None
    assert spawn_nebula_boss(gv) is True

    gv.player.center_x = gv._nebula_boss.center_x + (BOSS_DETECT_RANGE * 0.6)
    gv.player.center_y = gv._nebula_boss.center_y
    make_invulnerable(gv)


def _make_nebula_tick(gv):
    nb_hp_lock = gv._nebula_boss.hp   # pin HP so the boss can't die mid-soak

    def tick(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.player.shields = gv.player.max_shields
        # Keep the boss alive so gas attacks run the full duration.
        if gv._nebula_boss is not None:
            gv._nebula_boss.hp = nb_hp_lock
        gv.on_update(dt)
        gv.on_draw()

    return tick


class TestSoakNebulaBossCombat:
    def test_nebula_boss_5min_soak(self, real_game_view):
        gv = real_game_view
        _setup_nebula_soak(gv)
        run_soak(gv, "Nebula boss combat", _make_nebula_tick(gv))
