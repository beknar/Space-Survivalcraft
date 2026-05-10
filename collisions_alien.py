"""Alien ship + alien-projectile collision handlers.

Extracted from ``collisions`` in the 2026-05-10 split.  Covers
every interaction where an alien is the moving body or the laser
source: alien-vs-player, alien-vs-asteroid, alien-vs-alien,
alien-vs-building, plus alien laser hits on the player and on
station buildings.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import (
    SHIP_RADIUS, ASTEROID_RADIUS, ALIEN_RADIUS,
    SHIP_COLLISION_DAMAGE,
    ALIEN_BOUNCE, ALIEN_SPEED, ALIEN_COL_COOLDOWN, ALIEN_ASTEROID_DAMAGE,
    BUILDING_RADIUS, ALIEN_IRON_DROP,
    BUILDING_TYPES,
    BLUEPRINT_DROP_CHANCE_ALIEN,
)
from character_data import bonus_iron_enemy
from sprites.explosion import HitSpark

from collisions_common import (
    resolve_overlap, reflect_velocity,
    _apply_kill_rewards, _hit_player_on_cooldown,
    _station_shield_absorbs, apply_enemy_projectile_hit,
)

if TYPE_CHECKING:
    from game_view import GameView


def handle_alien_player_collision(gv: GameView) -> None:
    """Alien ship vs player: push-apart, bounce, damage."""
    for alien in list(gv.alien_list):
        contact = resolve_overlap(
            alien, gv.player, ALIEN_RADIUS, SHIP_RADIUS,
            push_a=0.5, push_b=0.5)
        if contact is None:
            continue
        nx, ny = contact
        rel_vx = alien.vel_x - gv.player.vel_x
        rel_vy = alien.vel_y - gv.player.vel_y
        dot = rel_vx * nx + rel_vy * ny
        if dot < 0.0:
            j = (1.0 + ALIEN_BOUNCE) * dot
            alien.vel_x -= j * nx
            alien.vel_y -= j * ny
            gv.player.vel_x += j * nx * 0.4
            gv.player.vel_y += j * ny * 0.4
        if alien._col_cd <= 0.0:
            alien._col_cd = ALIEN_COL_COOLDOWN
            alien.collision_bump()
        _hit_player_on_cooldown(gv, SHIP_COLLISION_DAMAGE, volume=0.4)


def handle_alien_asteroid_collision(gv: GameView) -> None:
    """Alien ship vs asteroid: push-out, bounce, and damage. Uses the
    asteroid's base (un-shaken) position for stable collision physics."""
    for alien in list(gv.alien_list):
        for asteroid in arcade.check_for_collision_with_list(
            alien, gv.asteroid_list
        ):
            saved_cx, saved_cy = asteroid.center_x, asteroid.center_y
            asteroid.center_x, asteroid.center_y = asteroid._base_x, asteroid._base_y
            contact = resolve_overlap(
                alien, asteroid, ALIEN_RADIUS, ASTEROID_RADIUS,
                push_a=1.0, push_b=0.0)
            asteroid.center_x, asteroid.center_y = saved_cx, saved_cy
            if contact is None:
                continue
            nx, ny = contact
            dot = reflect_velocity(alien, nx, ny, ALIEN_BOUNCE)
            if dot >= 0.0:
                alien.vel_x += nx * ALIEN_SPEED * 0.4
                alien.vel_y += ny * ALIEN_SPEED * 0.4
            if alien._col_cd <= 0.0:
                alien._col_cd = ALIEN_COL_COOLDOWN
                alien.collision_bump()
                alien.take_damage(ALIEN_ASTEROID_DAMAGE)
                if alien.hp <= 0:
                    _apply_kill_rewards(
                        gv, alien.center_x, alien.center_y,
                        ALIEN_IRON_DROP, bonus_iron_enemy,
                        BLUEPRINT_DROP_CHANCE_ALIEN)
                    alien.remove_from_sprite_lists()
                    break  # alien dead, skip remaining asteroids


def handle_alien_alien_collision(gv: GameView) -> None:
    """Alien ship vs alien ship: O(n^2) pair check, push-apart, bounce."""
    aliens = list(gv.alien_list)
    n = len(aliens)
    for i in range(n):
        a1 = aliens[i]
        for j in range(i + 1, n):
            a2 = aliens[j]
            contact = resolve_overlap(
                a1, a2, ALIEN_RADIUS, ALIEN_RADIUS,
                push_a=0.5, push_b=0.5)
            if contact is None:
                continue
            nx, ny = contact
            rel_vx = a1.vel_x - a2.vel_x
            rel_vy = a1.vel_y - a2.vel_y
            dot = rel_vx * nx + rel_vy * ny
            if dot < 0.0:
                j_imp = (1.0 + ALIEN_BOUNCE) * dot
                a1.vel_x -= j_imp * nx
                a1.vel_y -= j_imp * ny
                a2.vel_x += j_imp * nx
                a2.vel_y += j_imp * ny
            if a1._col_cd <= 0.0:
                a1._col_cd = ALIEN_COL_COOLDOWN
                a1.collision_bump()
            if a2._col_cd <= 0.0:
                a2._col_cd = ALIEN_COL_COOLDOWN
                a2.collision_bump()


def handle_alien_laser_hits(gv: GameView) -> None:
    """Alien laser projectiles hitting the player."""
    for proj in list(gv.alien_projectile_list):
        if arcade.check_for_collision(proj, gv.player):
            apply_enemy_projectile_hit(gv, proj, bump_volume=0.3)


def handle_alien_laser_building_hits(gv: GameView) -> None:
    """Alien laser projectiles hitting station buildings."""
    if len(gv.building_list) == 0 or len(gv.alien_projectile_list) == 0:
        return
    from sprites.building import HomeStation

    for proj in list(gv.alien_projectile_list):
        if _station_shield_absorbs(gv, proj):
            continue
        hits = arcade.check_for_collision_with_list(proj, gv.building_list)
        if hits:
            building = hits[0]
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            building.take_damage(int(proj.damage))
            if building.hp <= 0:
                gv._disconnect_ports(building)
                cost = BUILDING_TYPES[building.building_type]["cost"]
                gv._spawn_iron_pickup(
                    building.center_x, building.center_y, amount=cost,
                )
                if isinstance(building, HomeStation):
                    for b in gv.building_list:
                        b.disabled = True
                        b.color = (128, 128, 128, 255)
                gv._spawn_explosion(building.center_x, building.center_y)
                from update_logic import play_sfx_at
                play_sfx_at(gv, gv._explosion_snd,
                            building.center_x, building.center_y,
                            base_volume=0.7)
                building.remove_from_sprite_lists()


def handle_alien_building_collision(gv: GameView) -> None:
    """Alien ship vs station building: push-apart, bounce."""
    if len(gv.building_list) == 0:
        return
    _margin = BUILDING_RADIUS + ALIEN_RADIUS + 20.0
    _bx0 = _by0 = float('inf')
    _bx1 = _by1 = float('-inf')
    for b in gv.building_list:
        bx, by = b.center_x, b.center_y
        if bx < _bx0: _bx0 = bx
        if bx > _bx1: _bx1 = bx
        if by < _by0: _by0 = by
        if by > _by1: _by1 = by
    _bx0 -= _margin; _by0 -= _margin
    _bx1 += _margin; _by1 += _margin

    for alien in gv.alien_list:
        ax, ay = alien.center_x, alien.center_y
        if ax < _bx0 or ax > _bx1 or ay < _by0 or ay > _by1:
            continue
        for building in arcade.check_for_collision_with_list(
            alien, gv.building_list
        ):
            contact = resolve_overlap(
                alien, building, ALIEN_RADIUS, BUILDING_RADIUS,
                push_a=1.0, push_b=0.0)
            if contact is None:
                continue
            nx, ny = contact
            dot = reflect_velocity(alien, nx, ny, ALIEN_BOUNCE)
            if dot >= 0.0:
                alien.vel_x += nx * ALIEN_SPEED * 0.4
                alien.vel_y += ny * ALIEN_SPEED * 0.4
            if alien._col_cd <= 0.0:
                alien._col_cd = ALIEN_COL_COOLDOWN
                alien.collision_bump()
