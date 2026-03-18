"""Collision handling routines for Space Survivalcraft."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from constants import (
    SHIP_RADIUS, ASTEROID_RADIUS, ALIEN_RADIUS,
    SHIP_COLLISION_DAMAGE, SHIP_COLLISION_COOLDOWN, SHIP_BOUNCE,
    ALIEN_BOUNCE, ALIEN_SPEED, ALIEN_COL_COOLDOWN,
    BUILDING_RADIUS, ALIEN_IRON_DROP,
)
from sprites.explosion import HitSpark

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
                proj.remove_from_sprite_lists()
                consumed = True
                asteroid.take_damage(int(proj.damage))
                if asteroid.hp <= 0:
                    ax, ay = asteroid._base_x, asteroid._base_y
                    gv._spawn_explosion(ax, ay)
                    arcade.play_sound(gv._explosion_snd, volume=0.7)
                    asteroid.remove_from_sprite_lists()
                    gv._spawn_iron_pickup(ax, ay)

        if not consumed and not proj.mines_rock:
            hit_aliens = arcade.check_for_collision_with_list(
                proj, gv.alien_list
            )
            if hit_aliens:
                alien = hit_aliens[0]
                gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                gv._trigger_shake()
                proj.remove_from_sprite_lists()
                alien.take_damage(int(proj.damage))
                if alien.hp <= 0:
                    gv._spawn_explosion(alien.center_x, alien.center_y)
                    arcade.play_sound(gv._explosion_snd, volume=0.7)
                    gv._spawn_iron_pickup(
                        alien.center_x, alien.center_y,
                        amount=ALIEN_IRON_DROP,
                    )
                    alien.remove_from_sprite_lists()


def handle_ship_asteroid_collision(gv: GameView) -> None:
    """Player ship vs asteroid: push-out, bounce, damage."""
    hit_list = arcade.check_for_collision_with_list(
        gv.player, gv.asteroid_list
    )
    for asteroid in hit_list:
        dx = gv.player.center_x - asteroid.center_x
        dy = gv.player.center_y - asteroid.center_y
        dist = math.hypot(dx, dy)
        if dist == 0:
            dx, dy, dist = 0.0, 1.0, 1.0
        nx = dx / dist
        ny = dy / dist
        combined_r = SHIP_RADIUS + ASTEROID_RADIUS
        overlap = combined_r - dist
        if overlap > 0:
            gv.player.center_x += nx * overlap
            gv.player.center_y += ny * overlap

        dot = gv.player.vel_x * nx + gv.player.vel_y * ny
        if dot < 0:
            gv.player.vel_x -= (1 + SHIP_BOUNCE) * dot * nx
            gv.player.vel_y -= (1 + SHIP_BOUNCE) * dot * ny

        if gv.player._collision_cd <= 0.0:
            gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
            gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
            arcade.play_sound(gv._bump_snd, volume=0.5)
            gv._trigger_shake()


def handle_alien_player_collision(gv: GameView) -> None:
    """Alien ship vs player: push-apart, bounce, damage."""
    for alien in list(gv.alien_list):
        ddx = alien.center_x - gv.player.center_x
        ddy = alien.center_y - gv.player.center_y
        ddist = math.hypot(ddx, ddy)
        combined_r = ALIEN_RADIUS + SHIP_RADIUS
        if ddist < combined_r and ddist > 0.0:
            nx, ny = ddx / ddist, ddy / ddist
            overlap = combined_r - ddist
            alien.center_x += nx * overlap * 0.5
            alien.center_y += ny * overlap * 0.5
            gv.player.center_x -= nx * overlap * 0.5
            gv.player.center_y -= ny * overlap * 0.5
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
            if gv.player._collision_cd <= 0.0:
                gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                arcade.play_sound(gv._bump_snd, volume=0.4)
                gv._trigger_shake()


def handle_alien_asteroid_collision(gv: GameView) -> None:
    """Alien ship vs asteroid: push-out, bounce."""
    for alien in list(gv.alien_list):
        for asteroid in arcade.check_for_collision_with_list(
            alien, gv.asteroid_list
        ):
            adx = alien.center_x - asteroid._base_x
            ady = alien.center_y - asteroid._base_y
            adist = math.hypot(adx, ady)
            if adist == 0.0:
                adx, ady, adist = 1.0, 0.0, 1.0
            combined_r = ALIEN_RADIUS + ASTEROID_RADIUS
            nx, ny = adx / adist, ady / adist
            overlap = combined_r - adist
            if overlap > 0.0:
                alien.center_x += nx * overlap
                alien.center_y += ny * overlap
            dot = alien.vel_x * nx + alien.vel_y * ny
            if dot < 0.0:
                alien.vel_x -= (1.0 + ALIEN_BOUNCE) * dot * nx
                alien.vel_y -= (1.0 + ALIEN_BOUNCE) * dot * ny
            else:
                alien.vel_x += nx * ALIEN_SPEED * 0.4
                alien.vel_y += ny * ALIEN_SPEED * 0.4
            if alien._col_cd <= 0.0:
                alien._col_cd = ALIEN_COL_COOLDOWN
                alien.collision_bump()


def handle_alien_alien_collision(gv: GameView) -> None:
    """Alien ship vs alien ship: O(n²) pair check, push-apart, bounce."""
    aliens = list(gv.alien_list)
    for i in range(len(aliens)):
        for j in range(i + 1, len(aliens)):
            a1, a2 = aliens[i], aliens[j]
            ddx = a1.center_x - a2.center_x
            ddy = a1.center_y - a2.center_y
            ddist = math.hypot(ddx, ddy)
            combined_r = ALIEN_RADIUS * 2.0
            if ddist < combined_r and ddist > 0.0:
                nx, ny = ddx / ddist, ddy / ddist
                overlap = combined_r - ddist
                a1.center_x += nx * overlap * 0.5
                a1.center_y += ny * overlap * 0.5
                a2.center_x -= nx * overlap * 0.5
                a2.center_y -= ny * overlap * 0.5
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
            proj.remove_from_sprite_lists()
            gv._apply_damage_to_player(int(proj.damage))
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.3)


def handle_alien_laser_building_hits(gv: GameView) -> None:
    """Alien laser projectiles hitting station buildings."""
    from sprites.building import HomeStation

    for proj in list(gv.alien_projectile_list):
        hits = arcade.check_for_collision_with_list(proj, gv.building_list)
        if hits:
            building = hits[0]
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            building.take_damage(int(proj.damage))
            if building.hp <= 0:
                # Home Station destroyed — disable every module
                if isinstance(building, HomeStation):
                    for b in gv.building_list:
                        b.disabled = True
                        b.color = (128, 128, 128, 255)
                gv._spawn_explosion(building.center_x, building.center_y)
                arcade.play_sound(gv._explosion_snd, volume=0.7)
                building.remove_from_sprite_lists()


def handle_alien_building_collision(gv: GameView) -> None:
    """Alien ship vs station building: push-apart, bounce."""
    for alien in list(gv.alien_list):
        for building in arcade.check_for_collision_with_list(
            alien, gv.building_list
        ):
            adx = alien.center_x - building.center_x
            ady = alien.center_y - building.center_y
            adist = math.hypot(adx, ady)
            if adist == 0.0:
                adx, ady, adist = 1.0, 0.0, 1.0
            combined_r = ALIEN_RADIUS + BUILDING_RADIUS
            nx, ny = adx / adist, ady / adist
            overlap = combined_r - adist
            if overlap > 0.0:
                alien.center_x += nx * overlap
                alien.center_y += ny * overlap
            dot = alien.vel_x * nx + alien.vel_y * ny
            if dot < 0.0:
                alien.vel_x -= (1.0 + ALIEN_BOUNCE) * dot * nx
                alien.vel_y -= (1.0 + ALIEN_BOUNCE) * dot * ny
            else:
                alien.vel_x += nx * ALIEN_SPEED * 0.4
                alien.vel_y += ny * ALIEN_SPEED * 0.4
            if alien._col_cd <= 0.0:
                alien._col_cd = ALIEN_COL_COOLDOWN
                alien.collision_bump()


def handle_ship_building_collision(gv: GameView) -> None:
    """Player ship vs station building: gentle push-out, no damage, no bounce."""
    hit_list = arcade.check_for_collision_with_list(
        gv.player, gv.building_list
    )
    for building in hit_list:
        dx = gv.player.center_x - building.center_x
        dy = gv.player.center_y - building.center_y
        dist = math.hypot(dx, dy)
        if dist == 0:
            dx, dy, dist = 0.0, 1.0, 1.0
        nx = dx / dist
        ny = dy / dist
        combined_r = SHIP_RADIUS + BUILDING_RADIUS
        overlap = combined_r - dist
        if overlap > 0:
            gv.player.center_x += nx * overlap
            gv.player.center_y += ny * overlap

        # Zero velocity component toward the building (no bounce, no damage)
        dot = gv.player.vel_x * nx + gv.player.vel_y * ny
        if dot < 0:
            gv.player.vel_x -= dot * nx
            gv.player.vel_y -= dot * ny


def handle_turret_projectile_hits(gv: GameView) -> None:
    """Turret laser projectiles hitting aliens — spawn HitSpark on impact."""
    for proj in list(gv.turret_projectile_list):
        hits = arcade.check_for_collision_with_list(proj, gv.alien_list)
        if hits:
            alien = hits[0]
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            alien.take_damage(int(proj.damage))
            if alien.hp <= 0:
                gv._spawn_explosion(alien.center_x, alien.center_y)
                arcade.play_sound(gv._explosion_snd, volume=0.7)
                gv._spawn_iron_pickup(
                    alien.center_x, alien.center_y,
                    amount=ALIEN_IRON_DROP,
                )
                alien.remove_from_sprite_lists()
