"""Shared Nebula-style zone behaviour.

Both :class:`zones.zone2.Zone2` and :class:`zones.star_maze.StarMazeZone`
host the same "Nebula" content — iron / double-iron / copper asteroids,
gas clouds, wanderers, Z2 aliens + their projectiles, null fields,
slipspaces, and a shared fog-of-war grid — and run the same collision,
update, and population routines against that content.  Before this
module existed, the update / collision blocks were literal copy-paste
between the two files; Star Maze's copy drifted away from Zone 2's
every time Zone 2 got a fix (player-vs-asteroid collision, player-vs-
Z2-alien bounce, shielded-list rebuild, …), which was the source of
several recent bugs.

Every function here takes a ``z`` argument — any object exposing the
attribute contract documented below — and mutates it in place.  The
callers remain the zone classes; this module is structural, not a
subclass.

**Required ``z`` attributes:**

* ``world_width``, ``world_height`` (float)
* ``_iron_asteroids``, ``_double_iron``, ``_copper_asteroids``
  (``arcade.SpriteList``)
* ``_wanderers``, ``_gas_areas``, ``_aliens``, ``_alien_projectiles``
  (``arcade.SpriteList``)
* ``_shielded_aliens`` (``list``)
* ``_null_fields`` (``list``), ``_slipspaces`` (``arcade.SpriteList``)
* ``_iron_tex``, ``_copper_tex``, ``_copper_pickup_tex``,
  ``_alien_laser_tex``, ``_wanderer_tex`` (``arcade.Texture``)
* ``_alien_textures`` (``dict[str, arcade.Texture]``)
* ``_gas_damage_cd``, ``_respawn_timer`` (``float``)
* ``_gas_pos_cache`` (``list | None``), ``_alien_counts`` (``dict``)
* ``_fog_cell``, ``_fog_reveal_r``, ``_fog_w``, ``_fog_h`` (``int``)
* ``_fog_grid`` (``list[list[bool]]``), ``_fog_revealed`` (``int``)
* ``_world_seed`` (``int``)
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Callable

import arcade

from collisions import resolve_overlap, reflect_velocity
from constants import (
    SHIP_RADIUS, SHIP_COLLISION_COOLDOWN, SHIP_COLLISION_DAMAGE,
    SHIP_BOUNCE, ALIEN_BOUNCE,
    ASTEROID_RADIUS, ALIEN_ASTEROID_DAMAGE, ALIEN_COL_COOLDOWN,
    GAS_AREA_DAMAGE, GAS_AREA_SLOW,
    WANDERING_RADIUS, WANDERING_DAMAGE,
    COPPER_ASTEROID_PNG, COPPER_PICKUP_PNG, Z2_ALIEN_SHIP_PNG,
)

if TYPE_CHECKING:
    from game_view import GameView


# ── Shielded-list bookkeeping ─────────────────────────────────────────────

def rebuild_shielded_list(z) -> None:
    """Repopulate ``z._shielded_aliens`` from ``z._aliens``.  Called
    after any alien kill or respawn so shield overlays don't point at
    removed sprites."""
    from sprites.zone2_aliens import ShieldedAlien
    z._shielded_aliens = [
        a for a in z._aliens if isinstance(a, ShieldedAlien)]


# ── Texture loading ──────────────────────────────────────────────────────

def load_nebula_textures(z, gv: "GameView") -> None:
    """Populate the five Nebula textures on ``z`` if not already set.

    ``_iron_tex`` / ``_wanderer_tex`` come from the GameView (Zone 1
    shares the same asteroid PNG so the GPU atlas re-uses the handle).
    ``_copper_tex`` / ``_copper_pickup_tex`` / ``_alien_textures`` load
    once and are cached on the zone — each caller is responsible for
    its own module-level caches if it wants cross-zone sharing.
    """
    from PIL import Image as _PILImage
    z._iron_tex = gv._asteroid_tex
    if getattr(z, "_copper_tex", None) is None:
        z._copper_tex = arcade.load_texture(COPPER_ASTEROID_PNG)
    if getattr(z, "_copper_pickup_tex", None) is None:
        z._copper_pickup_tex = arcade.load_texture(COPPER_PICKUP_PNG)
    z._alien_laser_tex = gv._alien_laser_tex
    if not getattr(z, "_alien_textures", None):
        from sprites.zone2_aliens import ALIEN_CROPS
        pil = _PILImage.open(Z2_ALIEN_SHIP_PNG).convert("RGBA")
        z._alien_textures = {
            name: arcade.Texture(pil.crop(crop))
            for name, crop in ALIEN_CROPS.items()
        }
        pil.close()
    z._wanderer_tex = z._iron_tex


# ── Population ───────────────────────────────────────────────────────────

def populate_nebula_content(
    z, gv: "GameView", *,
    reject_iron: Callable[[float, float], bool] | None = None,
    reject_big_iron: Callable[[float, float], bool] | None = None,
    reject_copper: Callable[[float, float], bool] | None = None,
    reject_gas: Callable[[float, float], bool] | None = None,
    reject_wanderers: Callable[[float, float], bool] | None = None,
    reject_aliens: Callable[[float, float], bool] | None = None,
    reject_null: Callable[[float, float], bool] | None = None,
    reject_slip: Callable[[float, float], bool] | None = None,
) -> None:
    """Run the full populate pipeline on ``z``.

    Every reject filter defaults to ``None``; Zone 2 passes all-None
    (free placement anywhere), Star Maze passes radius-aware factories
    that keep each entity's body outside the maze AABBs.  Seeds from
    ``z._world_seed`` so layouts are save/load deterministic.
    """
    from zones.zone2_world import (
        populate_iron_asteroids, populate_double_iron,
        populate_copper_asteroids, populate_gas_areas,
        populate_wanderers, populate_aliens,
    )
    from world_setup import populate_null_fields, populate_slipspaces

    random.seed(z._world_seed)
    populate_iron_asteroids(z, reject_fn=reject_iron)
    populate_double_iron(z, reject_fn=reject_big_iron)
    populate_copper_asteroids(z, reject_fn=reject_copper)
    populate_gas_areas(z, reject_fn=reject_gas)
    z._gas_pos_cache = [(g.center_x, g.center_y, g.radius)
                        for g in z._gas_areas]
    populate_wanderers(z, reject_fn=reject_wanderers)
    populate_aliens(z, reject_fn=reject_aliens)
    z._null_fields = populate_null_fields(
        z.world_width, z.world_height, reject_fn=reject_null)
    ss_rng = random.Random(z._world_seed + 197)
    z._slipspaces = populate_slipspaces(
        z.world_width, z.world_height,
        gv._slipspace_tex, rng=ss_rng, reject_fn=reject_slip)
    random.seed()


# ── Fog of war ───────────────────────────────────────────────────────────

def update_fog(z, gv: "GameView") -> None:
    """Reveal fog cells within ``z._fog_reveal_r`` of the player.
    Mirrors the fog block in both zones — the math is identical so
    keeping two copies was just a drift surface."""
    px, py = gv.player.center_x, gv.player.center_y
    cx = int(px / z._fog_cell)
    cy = int(py / z._fog_cell)
    r = int(z._fog_reveal_r / z._fog_cell) + 1
    for gy in range(max(0, cy - r), min(z._fog_h, cy + r + 1)):
        for gx in range(max(0, cx - r), min(z._fog_w, cx + r + 1)):
            if not z._fog_grid[gy][gx]:
                cell_cx = (gx + 0.5) * z._fog_cell
                cell_cy = (gy + 0.5) * z._fog_cell
                if math.hypot(px - cell_cx,
                              py - cell_cy) <= z._fog_reveal_r:
                    z._fog_grid[gy][gx] = True
                    z._fog_revealed += 1
                    gv._fog_revealed = z._fog_revealed


# ── Gas damage ───────────────────────────────────────────────────────────

def update_gas_damage(z, gv: "GameView", dt: float) -> None:
    """Tick the gas damage cooldown, apply damage if the player is
    inside any gas area, and drag the player's velocity while inside."""
    z._gas_damage_cd = max(0.0, z._gas_damage_cd - dt)
    px, py = gv.player.center_x, gv.player.center_y
    in_gas = False
    for g in z._gas_areas:
        if g.contains_point(px, py):
            in_gas = True
            if z._gas_damage_cd <= 0.0:
                gv._apply_damage_to_player(int(GAS_AREA_DAMAGE))
                gv._trigger_shake()
                gv._flash_game_msg("Toxic gas!", 0.5)
                z._gas_damage_cd = 1.0
            break
    if in_gas:
        gv.player.vel_x *= GAS_AREA_SLOW ** (dt * 60)
        gv.player.vel_y *= GAS_AREA_SLOW ** (dt * 60)


# ── Player ↔ wanderer collisions ─────────────────────────────────────────

def update_wanderer_collision(z, gv: "GameView") -> None:
    """Bounce + damage the player on contact with any wandering
    asteroid.  Short-circuits on the player's collision cooldown."""
    if gv.player._collision_cd > 0.0:
        return
    for w in arcade.check_for_collision_with_list(gv.player, z._wanderers):
        contact = resolve_overlap(
            gv.player, w, SHIP_RADIUS, WANDERING_RADIUS,
            push_a=0.6, push_b=0.4)
        if contact is None:
            continue
        nx, ny = contact
        reflect_velocity(gv.player, nx, ny, SHIP_BOUNCE)
        # Kick wanderer away from player, suppress magnet
        w._wander_angle = math.atan2(-ny, -nx)
        w._wander_timer = 1.5
        w._repel_timer = 2.0
        gv._apply_damage_to_player(WANDERING_DAMAGE)
        gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
        gv._trigger_shake()
        arcade.play_sound(gv._bump_snd, volume=0.4)
        break


# ── Player ↔ static asteroid collisions ──────────────────────────────────

def update_player_asteroid_collision(z, gv: "GameView") -> None:
    """Bounce + damage the player on contact with iron / double-iron /
    copper asteroids.  Only the first collision per frame registers so
    a stack of asteroids doesn't multiply the damage."""
    if gv.player._collision_cd > 0.0:
        return
    for alist in (z._iron_asteroids, z._double_iron, z._copper_asteroids):
        hit = False
        for a in arcade.check_for_collision_with_list(gv.player, alist):
            a_radius = max(ASTEROID_RADIUS, a.width / 2 * 0.8)
            contact = resolve_overlap(
                gv.player, a, SHIP_RADIUS, a_radius,
                push_a=1.0, push_b=0.0)
            if contact is None:
                continue
            nx, ny = contact
            reflect_velocity(gv.player, nx, ny, SHIP_BOUNCE)
            gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
            gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.4)
            hit = True
            break
        if hit:
            break


# ── Player ↔ Z2 alien collisions ─────────────────────────────────────────

def update_player_z2_alien_collision(z, gv: "GameView") -> None:
    """Shove + damage on contact between the player and Z2 aliens."""
    for alien in arcade.check_for_collision_with_list(gv.player, z._aliens):
        contact = resolve_overlap(
            alien, gv.player, 20.0, SHIP_RADIUS,
            push_a=0.5, push_b=0.5)
        if contact is None:
            continue
        nx, ny = contact
        # Push aliens forward away from player, dampen player slightly.
        alien.vel_x += nx * 150
        alien.vel_y += ny * 150
        dot = gv.player.vel_x * (-nx) + gv.player.vel_y * (-ny)
        if dot < 0:
            gv.player.vel_x -= (1 + ALIEN_BOUNCE) * dot * (-nx) * 0.4
            gv.player.vel_y -= (1 + ALIEN_BOUNCE) * dot * (-ny) * 0.4
        if gv.player._collision_cd <= 0.0:
            gv._apply_damage_to_player(5)
            gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.3)


# ── Z2 alien ↔ asteroid collisions ───────────────────────────────────────

def update_alien_asteroid_collisions(z, gv: "GameView") -> None:
    """Damage + bounce Z2 aliens that collide with static asteroids.
    Drops iron / XP / blueprint on kill via ``_apply_kill_rewards``."""
    from collisions import _apply_kill_rewards
    from constants import ALIEN_IRON_DROP, BLUEPRINT_DROP_CHANCE_ALIEN
    from character_data import bonus_iron_enemy
    for alien in list(z._aliens):
        for alist in (z._iron_asteroids, z._double_iron,
                      z._copper_asteroids):
            for a in arcade.check_for_collision_with_list(alien, alist):
                a_radius = max(ASTEROID_RADIUS, a.width / 2 * 0.8)
                contact = resolve_overlap(
                    alien, a, 20.0, a_radius, push_a=1.0, push_b=0.0)
                if contact is None:
                    continue
                nx, ny = contact
                reflect_velocity(alien, nx, ny, ALIEN_BOUNCE)
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
                break   # one collision per alien per frame
            if not alien.sprite_lists:
                break   # alien was killed


# ── Alien laser vs player ────────────────────────────────────────────────

def update_alien_laser_hits(z, gv: "GameView") -> None:
    """Apply damage + remove any Z2 alien projectile currently
    overlapping the player sprite.  Both zones called the same inline
    loop; now centralised."""
    for proj in arcade.check_for_collision_with_list(
            gv.player, z._alien_projectiles):
        gv._apply_damage_to_player(int(proj.damage))
        gv._trigger_shake()
        proj.remove_from_sprite_lists()
