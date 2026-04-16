"""Soak test for the station shield + shielded AI fleet.

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run explicitly with:
    pytest "unit tests/integration/test_soak_station_shield.py" -v -s

Builds a Home Station + Shield Generator in the Nebula, spawns four
AI-piloted parked ships, and alternates between (a) pelting the
station shield with alien fire so the absorb path is hot and (b)
letting it sit dormant so the draw + idle tick is exercised.
"""
from __future__ import annotations

import math

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _setup_shielded_zone2(gv):
    """Zone 2 + Home Station + Shield Generator + 4 AI-piloted ships."""
    from sprites.building import create_building
    from sprites.parked_ship import ParkedShip

    make_invulnerable(gv)
    if gv._zone.zone_id != ZoneID.ZONE2:
        gv._transition_zone(ZoneID.ZONE2)

    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    hs_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", hs_tex, cx, cy, scale=0.5))
    sg_tex = gv._building_textures["Shield Generator"]
    gv.building_list.append(create_building(
        "Shield Generator", sg_tex, cx + 90, cy, scale=0.5))
    gv._station_shield_hp = 0
    gv._station_shield_sprite = None

    gv._parked_ships.clear()
    for i in range(4):
        ang = 2 * math.pi * i / 4
        ps = ParkedShip(
            gv._faction, gv._ship_type, 1,
            cx + math.cos(ang) * 260,
            cy + math.sin(ang) * 260,
        )
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.append(ps)

    gv.player.center_x = cx + 4000
    gv.player.center_y = cy + 4000
    return cx, cy


def _make_shield_churn(gv, cx, cy):
    from sprites.projectile import Projectile
    from constants import ALIEN_LASER_SPEED, ALIEN_LASER_RANGE
    step = {"n": 0}

    def tick(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.player.shields = gv.player.max_shields
        if step["n"] % 60 == 0:
            gv._station_shield_hp = max(gv._station_shield_hp, 80)
            proj = Projectile(
                gv._alien_laser_tex, cx + 500.0, cy, 270,
                ALIEN_LASER_SPEED, ALIEN_LASER_RANGE, damage=10)
            gv.alien_projectile_list.append(proj)
        gv.on_update(dt)
        gv.on_draw()
        step["n"] += 1

    return tick


class TestSoakStationShield:
    def test_station_shield_and_shielded_fleet_5min_soak(
            self, real_game_view):
        """5-minute soak: station shield cycling absorb/idle + shielded
        AI fleet patrolling + Zone 2 gameplay ticking."""
        gv = real_game_view
        cx, cy = _setup_shielded_zone2(gv)
        run_soak(gv, "Station shield + AI fleet",
                 _make_shield_churn(gv, cx, cy))
