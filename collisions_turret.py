"""Station-turret + AI-pilot projectile collision handling.

Extracted from ``collisions`` in the 2026-05-10 split.  Holds the
single per-frame loop that walks ``gv.turret_projectile_list``
against ``gv.alien_list`` plus any zone-specific extra hostile
SpriteLists exposed via ``gv._zone._turret_extra_target_lists``
(Star Maze: stalkers + Z2-style aliens).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import ALIEN_IRON_DROP, BLUEPRINT_DROP_CHANCE_ALIEN
from character_data import bonus_iron_enemy
from sprites.explosion import HitSpark

from collisions_common import _apply_kill_rewards

if TYPE_CHECKING:
    from game_view import GameView


def handle_turret_projectile_hits(gv: GameView) -> None:
    """Turret laser projectiles hitting aliens -- spawn HitSpark on impact.

    Scans ``gv.alien_list`` plus any zone-specific extra hostile
    SpriteLists exposed via ``gv._zone._turret_extra_target_lists``
    (Star Maze: stalkers + Z2-style aliens).  Each list is queried
    independently against the existing
    ``arcade.check_for_collision_with_list`` contract -- building a
    combined SpriteList per frame leaks ~15 KB per call (arcade
    SpriteList ``clear()+append()`` quirk), which collapsed soak
    runs to 500+ MB growth in 5 min.
    """
    extra_lists = getattr(
        getattr(gv, "_zone", None),
        "_turret_extra_target_lists", None) or ()
    target_lists = (gv.alien_list, *extra_lists)
    for proj in list(gv.turret_projectile_list):
        hit_alien = None
        for tlist in target_lists:
            hits = arcade.check_for_collision_with_list(proj, tlist)
            if hits:
                hit_alien = hits[0]
                break
        if hit_alien is None:
            continue
        gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
        proj.remove_from_sprite_lists()
        hit_alien.take_damage(int(proj.damage))
        if hit_alien.hp <= 0:
            _apply_kill_rewards(gv, hit_alien.center_x, hit_alien.center_y,
                                ALIEN_IRON_DROP, bonus_iron_enemy,
                                BLUEPRINT_DROP_CHANCE_ALIEN)
            hit_alien.remove_from_sprite_lists()
