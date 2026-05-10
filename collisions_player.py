"""Player ship + player-projectile collision handlers.

Extracted from ``collisions`` in the 2026-05-10 split.  Covers the
player's interactions with asteroids and station buildings, plus the
single per-frame loop that walks every player-fired projectile and
deals damage to whatever it hits (asteroid or alien).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import (
    SHIP_RADIUS, ASTEROID_RADIUS,
    SHIP_COLLISION_DAMAGE, SHIP_BOUNCE,
    BUILDING_RADIUS,
    ALIEN_IRON_DROP, ASTEROID_IRON_YIELD,
    BLUEPRINT_DROP_CHANCE_ALIEN, BLUEPRINT_DROP_CHANCE_ASTEROID,
)
from character_data import bonus_iron_asteroid, bonus_iron_enemy
from sprites.explosion import HitSpark

from collisions_common import (
    resolve_overlap, reflect_velocity,
    _alert_nearby_aliens, _apply_kill_rewards, _hit_player_on_cooldown,
)

if TYPE_CHECKING:
    from game_view import GameView


def handle_projectile_hits(gv: GameView) -> None:
    """Single-pass loop: player projectiles vs asteroids and aliens."""
    for proj in list(gv.projectile_list):
        consumed = False

        if proj.mines_rock:
            hit_asteroids = arcade.check_for_collision_with_list(
                proj, gv.asteroid_list
            )
            if hit_asteroids:
                asteroid = hit_asteroids[0]
                gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                _alert_nearby_aliens(gv, proj.center_x, proj.center_y)
                proj.remove_from_sprite_lists()
                consumed = True
                asteroid.take_damage(int(proj.damage))
                if asteroid.hp <= 0:
                    ax, ay = asteroid._base_x, asteroid._base_y
                    asteroid.remove_from_sprite_lists()
                    _apply_kill_rewards(gv, ax, ay, ASTEROID_IRON_YIELD,
                                        bonus_iron_asteroid,
                                        BLUEPRINT_DROP_CHANCE_ASTEROID,
                                        asteroid=True)

        if not consumed and not proj.mines_rock:
            hit_aliens = arcade.check_for_collision_with_list(
                proj, gv.alien_list
            )
            if hit_aliens:
                alien = hit_aliens[0]
                gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                gv._trigger_shake()
                _alert_nearby_aliens(gv, proj.center_x, proj.center_y)
                proj.remove_from_sprite_lists()
                alien.take_damage(int(proj.damage))
                if alien.hp <= 0:
                    _apply_kill_rewards(gv, alien.center_x, alien.center_y,
                                        ALIEN_IRON_DROP, bonus_iron_enemy,
                                        BLUEPRINT_DROP_CHANCE_ALIEN)
                    alien.remove_from_sprite_lists()


def handle_ship_asteroid_collision(gv: GameView) -> None:
    """Player ship vs asteroid: push-out, bounce, damage."""
    hit_list = arcade.check_for_collision_with_list(
        gv.player, gv.asteroid_list
    )
    for asteroid in hit_list:
        contact = resolve_overlap(
            gv.player, asteroid, SHIP_RADIUS, ASTEROID_RADIUS,
            push_a=1.0, push_b=0.0)
        if contact is None:
            continue
        nx, ny = contact
        reflect_velocity(gv.player, nx, ny, SHIP_BOUNCE)
        _hit_player_on_cooldown(gv, SHIP_COLLISION_DAMAGE, volume=0.5)


def handle_ship_building_collision(gv: GameView) -> None:
    """Player ship vs station building: gentle push-out, no damage, no bounce."""
    hit_list = arcade.check_for_collision_with_list(
        gv.player, gv.building_list
    )
    for building in hit_list:
        contact = resolve_overlap(
            gv.player, building, SHIP_RADIUS, BUILDING_RADIUS,
            push_a=1.0, push_b=0.0)
        if contact is None:
            continue
        nx, ny = contact
        reflect_velocity(gv.player, nx, ny, 0.0)
