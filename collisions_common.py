"""Shared collision helpers used by every topical collisions_* module.

Extracted from ``collisions`` in the 2026-05-10 split.  Holds the
small primitives — drop scatter, kill rewards, overlap resolution,
velocity reflection, melee deflect, the on-cooldown player hit
helper, and the station-shield absorption check — that the
per-entity handlers (player, alien, boss, turret, parked ship)
all reach for.

``collisions`` re-exports every public + private name from the
topical modules so existing
``from collisions import handle_projectile_hits`` /
``import collisions; collisions._try_melee_deflect`` style imports
keep working.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    SHIP_COLLISION_COOLDOWN,
    ALIEN_AGGRO_RANGE,
    MELEE_DEFLECT_CHANCE,
)
from character_data import blueprint_drop_bonus
from sprites.explosion import HitSpark
from settings import audio as _audio

if TYPE_CHECKING:
    from game_view import GameView


def _drop_scatter(cx: float, cy: float, n: int,
                  base_radius: float = 24.0) -> list[tuple[float, float]]:
    """Return ``n`` (x, y) positions evenly spaced on a circle around
    ``(cx, cy)`` so multi-item kill drops don't pile on top of each
    other.  ``n`` <= 1 returns the centre itself so single-item drops
    are unaffected.  The radius grows with ``n`` so five-to-ten-item
    cargo dumps spread wide enough that the pickup sprites don't
    fully overlap; a small random rotation prevents every death at
    the same spot from producing the identical ring layout.
    """
    if n <= 1:
        return [(cx, cy)]
    radius = min(base_radius + 6.0 * (n - 1), base_radius * 3.0)
    theta0 = random.uniform(0.0, math.tau)
    out: list[tuple[float, float]] = []
    for i in range(n):
        theta = theta0 + (math.tau * i) / n
        out.append((cx + math.cos(theta) * radius,
                    cy + math.sin(theta) * radius))
    return out


def _apply_kill_rewards(
    gv: GameView, x: float, y: float,
    base_iron: int,
    iron_bonus_fn,
    bp_base_chance: float,
    xp: int = 25,
    asteroid: bool = False,
) -> None:
    """Spawn explosion, drop iron (base + character bonus), maybe blueprint, award XP.

    Passing ``asteroid=True`` routes the explosion through the 10-frame
    asteroid-specific sprite so Zone 1 asteroid kills get the new
    cinematic look while alien kills keep the legacy sheet.
    """
    if asteroid:
        gv._spawn_asteroid_explosion(x, y)
    else:
        gv._spawn_explosion(x, y)
    from update_logic import play_sfx_at
    play_sfx_at(gv, gv._explosion_snd, x, y, base_volume=0.7)
    gv._spawn_iron_pickup(x - 20, y, amount=base_iron)
    _cn = _audio.character_name
    _cl = gv._char_level
    _extra = iron_bonus_fn(_cn, _cl)
    if _extra > 0:
        gv._spawn_iron_pickup(x + 20, y, amount=_extra)
    _bp_chance = bp_base_chance + blueprint_drop_bonus(_cn, _cl)
    if random.random() < _bp_chance:
        gv._spawn_blueprint_pickup(x, y + 25)
    gv._add_xp(xp)


def resolve_overlap(
    a, b, ra: float, rb: float,
    push_a: float = 0.5, push_b: float = 0.5,
) -> tuple[float, float] | None:
    """Push two circle bodies apart along the contact normal.

    Returns the contact normal ``(nx, ny)`` pointing FROM ``b`` TO ``a``,
    or ``None`` if the bodies are not in contact. ``push_a`` / ``push_b``
    weight the position correction (use ``1.0 / 0.0`` for static-vs-mover).
    """
    dx = a.center_x - b.center_x
    dy = a.center_y - b.center_y
    dist = math.hypot(dx, dy)
    combined = ra + rb
    if dist >= combined:
        return None
    if dist == 0.0:
        dx, dy, dist = 1.0, 0.0, 1.0
    nx = dx / dist
    ny = dy / dist
    overlap = combined - dist
    if overlap > 0.0:
        a.center_x += nx * overlap * push_a
        a.center_y += ny * overlap * push_a
        if push_b > 0.0:
            b.center_x -= nx * overlap * push_b
            b.center_y -= ny * overlap * push_b
    return nx, ny


def reflect_velocity(obj, nx: float, ny: float, bounce: float) -> float:
    """Reflect a single body's velocity off a contact normal with restitution.

    Returns the closing speed along the normal before reflection (``dot``);
    negative means the body was approaching the surface. No-op when the body
    is already moving away (``dot >= 0``).
    """
    dot = obj.vel_x * nx + obj.vel_y * ny
    if dot < 0.0:
        obj.vel_x -= (1.0 + bounce) * dot * nx
        obj.vel_y -= (1.0 + bounce) * dot * ny
    return dot


def _alert_nearby_aliens(gv: GameView, x: float, y: float) -> None:
    """Alert all aliens within ALIEN_AGGRO_RANGE of (x, y) to pursue the player."""
    for alien in gv.alien_list:
        if math.hypot(alien.center_x - x, alien.center_y - y) <= ALIEN_AGGRO_RANGE:
            alien.alert()


def _try_melee_deflect(gv: GameView, proj) -> bool:
    """Roll the energy-blade deflect dice for a single enemy projectile.

    Returns True if the bolt was deflected -- the caller must skip the
    "damage the player" branch in that case.  A deflected projectile
    has its velocity reversed, its travel distance reset, and is moved
    out of the enemy list and into ``gv.projectile_list`` so it can
    hit aliens on the way back (player projectiles don't damage the
    player, so the deflected bolt is no longer a self-hazard).
    """
    blade = getattr(gv, "_active_blade", None)
    if blade is None or not blade.is_swinging:
        return False
    if random.random() >= MELEE_DEFLECT_CHANCE:
        return False
    proj._vx = -proj._vx
    proj._vy = -proj._vy
    proj.angle = (proj.angle + 180.0) % 360.0
    proj._dist_travelled = 0.0
    proj.remove_from_sprite_lists()
    gv.projectile_list.append(proj)
    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
    arcade.play_sound(gv._bump_snd, volume=0.4)
    return True


def apply_enemy_projectile_hit(
        gv: GameView, proj, *,
        bump_volume: float | None = None) -> None:
    """Standard handler for an enemy projectile that has just
    collided with the player.  Tries a melee deflect first; on
    miss, removes the projectile, applies damage to the player,
    triggers a screen shake, and optionally plays the bump sound
    at the given volume.

    Consolidates the "deflect -> damage -> shake" pattern that was
    duplicated across five call sites (Zone 1 alien lasers, boss
    lasers, nebula_shared alien lasers, Star Maze maze
    projectiles, Star Maze nebula projectiles) -- each site only
    differed in the bump-sound volume.
    """
    if _try_melee_deflect(gv, proj):
        return
    proj.remove_from_sprite_lists()
    gv._apply_damage_to_player(int(proj.damage))
    gv._trigger_shake()
    if bump_volume is not None:
        arcade.play_sound(gv._bump_snd, volume=bump_volume)


def _hit_player_on_cooldown(
    gv: GameView, damage: int, volume: float = 0.4,
    cooldown: float | None = None, shake: bool = True,
) -> bool:
    """Apply ``damage`` to the player on the shared invincibility
    cooldown pattern. Returns True when the hit landed (False when
    the player is still on cooldown from a previous collision).

    Six collision handlers used to repeat the same four-line block --
    check cooldown -> apply damage -> reset cooldown -> play bump sound +
    shake. Centralising it keeps every collision site shorter and
    guarantees identical behaviour (e.g. a future tweak to shake
    duration only has to land here).
    """
    if gv.player._collision_cd > 0.0:
        return False
    gv._apply_damage_to_player(int(damage))
    gv.player._collision_cd = (
        cooldown if cooldown is not None else SHIP_COLLISION_COOLDOWN)
    if volume > 0.0:
        arcade.play_sound(gv._bump_snd, volume=volume)
    if shake:
        gv._trigger_shake()
    return True


def _station_shield_absorbs(gv: GameView, proj) -> bool:
    """Return True when the station shield intercepts this projectile.

    The shield is a flat disk centred on the Home Station with radius
    ``gv._station_shield_radius``. Any enemy projectile that crosses
    into the disk bleeds ``proj.damage`` from the shield pool and is
    removed. When HP reaches zero the shield goes dormant until
    ``update_station_shield`` refills it (currently only via the
    Shield Generator respawn path in save/load; the bubble does not
    auto-regen during a run).
    """
    if getattr(gv, "_station_shield_hp", 0) <= 0:
        return False
    if gv._station_shield_sprite is None:
        return False
    sx = gv._station_shield_sprite.center_x
    sy = gv._station_shield_sprite.center_y
    r = gv._station_shield_radius
    if r <= 0.0:
        return False
    if (proj.center_x - sx) ** 2 + (proj.center_y - sy) ** 2 > r * r:
        return False
    gv._station_shield_hp = max(
        0, gv._station_shield_hp - int(getattr(proj, "damage", 0)))
    gv._station_shield_sprite.hit_flash()
    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
    proj.remove_from_sprite_lists()
    return True
