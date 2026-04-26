"""Collision handling routines for Space Survivalcraft."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    SHIP_RADIUS, ASTEROID_RADIUS, ALIEN_RADIUS,
    SHIP_COLLISION_DAMAGE, SHIP_COLLISION_COOLDOWN, SHIP_BOUNCE,
    ALIEN_BOUNCE, ALIEN_SPEED, ALIEN_COL_COOLDOWN, ALIEN_ASTEROID_DAMAGE,
    BUILDING_RADIUS, ALIEN_IRON_DROP, ASTEROID_IRON_YIELD,
    BUILDING_TYPES, ALIEN_AGGRO_RANGE,
    BLUEPRINT_DROP_CHANCE_ALIEN, BLUEPRINT_DROP_CHANCE_ASTEROID,
    BOSS_RADIUS, BOSS_COLLISION_DAMAGE, BOSS_COLLISION_COOLDOWN,
    BOSS_BOUNCE, BOSS_CHARGE_DAMAGE, BOSS_XP_REWARD, BOSS_IRON_DROP,
)
from character_data import (
    bonus_iron_asteroid, bonus_iron_enemy, blueprint_drop_bonus,
)
from sprites.explosion import HitSpark

from settings import audio as _audio

if TYPE_CHECKING:
    from game_view import GameView


def _drop_scatter(cx: float, cy: float, n: int,
                  base_radius: float = 24.0) -> list[tuple[float, float]]:
    """Return ``n`` (x, y) positions evenly spaced on a circle around
    ``(cx, cy)`` so multi-item kill drops don't pile on top of each
    other.  ``n`` ≤ 1 returns the centre itself so single-item drops
    are unaffected.  The radius grows with ``n`` so five-to-ten-item
    cargo dumps spread wide enough that the pickup sprites don't
    fully overlap; a small random rotation prevents every death at
    the same spot from producing the identical ring layout.
    """
    if n <= 1:
        return [(cx, cy)]
    # Fan out further the more items there are, but cap so the ring
    # stays visually local to the death point.
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


def handle_alien_player_collision(gv: GameView) -> None:
    """Alien ship vs player: push-apart, bounce, damage."""
    for alien in list(gv.alien_list):
        contact = resolve_overlap(
            alien, gv.player, ALIEN_RADIUS, SHIP_RADIUS,
            push_a=0.5, push_b=0.5)
        if contact is None:
            continue
        nx, ny = contact
        # Asymmetric impulse: alien gets full bounce, player only 0.4x
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
            # Temporarily snap asteroid to base position so resolve_overlap
            # uses a stable centre (asteroid won't be moved — push_b=0).
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
    """Alien ship vs alien ship: O(n²) pair check, push-apart, bounce."""
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
            # Symmetric equal-and-opposite impulse using relative velocity
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
            # Alien lasers bypass the invincibility cooldown (they fire
            # rapidly and the design is that each bolt hurts).
            gv._apply_damage_to_player(int(proj.damage))
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.3)


def _hit_player_on_cooldown(
    gv: GameView, damage: int, volume: float = 0.4,
    cooldown: float | None = None, shake: bool = True,
) -> bool:
    """Apply ``damage`` to the player on the shared invincibility
    cooldown pattern. Returns True when the hit landed (False when
    the player is still on cooldown from a previous collision).

    Six collision handlers used to repeat the same four-line block —
    check cooldown → apply damage → reset cooldown → play bump sound +
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
                # Drop iron equal to build cost
                cost = BUILDING_TYPES[building.building_type]["cost"]
                gv._spawn_iron_pickup(
                    building.center_x, building.center_y, amount=cost,
                )
                # Home Station destroyed — disable every module
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
    # Pre-compute building cluster AABB to skip distant aliens cheaply
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
        # Zero velocity component toward the building (no bounce, no damage)
        reflect_velocity(gv.player, nx, ny, 0.0)


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
                _apply_kill_rewards(gv, alien.center_x, alien.center_y,
                                    ALIEN_IRON_DROP, bonus_iron_enemy,
                                    BLUEPRINT_DROP_CHANCE_ALIEN)
                alien.remove_from_sprite_lists()


# ── Boss encounter collision handlers ──────────────────────────────────────


def _boss_death(gv: GameView) -> None:
    """Handle boss death: explosion, loot, wormholes, victory message."""
    boss = gv._boss
    gv._spawn_explosion(boss.center_x, boss.center_y)
    from update_logic import play_sfx_at
    play_sfx_at(gv, gv._explosion_snd, boss.center_x, boss.center_y,
                base_volume=1.0)
    play_sfx_at(gv, gv._victory_snd, boss.center_x, boss.center_y,
                base_volume=0.8)
    gv._spawn_iron_pickup(boss.center_x, boss.center_y, amount=BOSS_IRON_DROP)
    gv._add_xp(BOSS_XP_REWARD)
    gv._boss = None
    gv._boss_defeated = True
    gv._boss_list.clear()
    gv._boss_projectile_list.clear()
    # Spawn 4 wormholes in the corners
    gv._spawn_wormholes()
    # Large victory announcement
    gv._boss_announce_timer = 5.0
    gv._t_boss_announce.text = "Double Star Boss KILLED"
    gv._t_boss_subtitle.text = "Wormholes have appeared at the edges of the sector!"


def _projectiles_vs_boss(gv: GameView, boss, on_death) -> None:
    """Shared helper: player + turret projectiles damage ``boss``.

    Used for both the Double Star and the Nebula boss — the same
    player laser or station-turret shot should hurt whichever boss
    is alive.  ``on_death(gv)`` runs exactly once when HP hits 0.
    """
    if boss is None or boss.hp <= 0:
        return
    # Collision radius follows the rendered sprite size — see
    # ``BossAlienShip.radius`` — so if ``BOSS_SCALE`` ever changes
    # again the hitbox scales with it automatically.
    hit_r = boss.radius + 10.0
    for proj in list(gv.projectile_list):
        if proj.mines_rock:
            continue  # mining beam doesn't hurt bosses
        dx = proj.center_x - boss.center_x
        dy = proj.center_y - boss.center_y
        if math.hypot(dx, dy) <= hit_r:
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            gv._trigger_shake()
            proj.remove_from_sprite_lists()
            boss.take_damage(int(proj.damage))
            if boss.hp <= 0:
                on_death(gv)
                return
    # Also check turret projectiles (station turrets + AI-pilot ships
    # both push shots into ``gv.turret_projectile_list``).
    for proj in list(gv.turret_projectile_list):
        if boss.hp <= 0:
            return
        dx = proj.center_x - boss.center_x
        dy = proj.center_y - boss.center_y
        if math.hypot(dx, dy) <= hit_r:
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            boss.take_damage(int(proj.damage))
            if boss.hp <= 0:
                on_death(gv)
                return


def handle_boss_projectile_hits(gv: GameView) -> None:
    """Player + turret projectiles hitting the Double Star boss."""
    _projectiles_vs_boss(gv, gv._boss, _boss_death)


_NEBULA_BOSS_IRON_DROP: int = 3000
_NEBULA_BOSS_COPPER_DROP: int = 1000


def _nebula_boss_death(gv: GameView) -> None:
    """Handle Nebula boss death: loot, announce, and spawn four corner
    wormholes in Zone 2 that route to the 2x-danger Nebula warp
    zones, which in turn deposit the player in the Star Maze.

    Drops 3000 iron + 1000 copper per user spec (no XP — the Nebula
    boss is a resource-summonable encore boss, not an XP milestone).
    """
    nb = gv._nebula_boss
    if nb is None:
        return
    gv._spawn_explosion(nb.center_x, nb.center_y)
    from update_logic import play_sfx_at
    play_sfx_at(gv, gv._explosion_snd, nb.center_x, nb.center_y,
                base_volume=1.0)
    play_sfx_at(gv, gv._victory_snd, nb.center_x, nb.center_y,
                base_volume=0.8)
    # Scatter the two drops so they're next to each other instead of
    # stacked at the boss centre.
    (ix, iy), (cx, cy) = _drop_scatter(nb.center_x, nb.center_y, 2)
    gv._spawn_iron_pickup(ix, iy, amount=_NEBULA_BOSS_IRON_DROP)
    from sprites.pickup import IronPickup
    copper_tex = getattr(gv, "_copper_tex", None) or gv._iron_tex
    copper_pickup = IronPickup(copper_tex, cx, cy,
                                amount=_NEBULA_BOSS_COPPER_DROP)
    copper_pickup.item_type = "copper"
    gv.iron_pickup_list.append(copper_pickup)
    gv._nebula_boss = None
    if hasattr(gv, "_nebula_boss_list"):
        gv._nebula_boss_list.clear()
    if hasattr(gv, "_nebula_gas_clouds"):
        gv._nebula_gas_clouds.clear()
    # Unlock the four corner wormholes to the Star Maze.  The current
    # zone is Zone 2 (we just killed its boss); defer to it for the
    # actual placement so the Zone 2 state owns the persistence flag.
    from zones.zone2 import Zone2 as _Zone2
    if isinstance(gv._zone, _Zone2):
        gv._zone.mark_nebula_boss_defeated(gv)
    gv._boss_announce_timer = 5.0
    gv._t_boss_announce.text = "Nebula Boss KILLED"
    gv._t_boss_subtitle.text = (
        "Corner wormholes open. The Star Maze awaits.")


def handle_nebula_boss_projectile_hits(gv: GameView) -> None:
    """Player + turret projectiles hitting the Nebula boss."""
    nb = getattr(gv, "_nebula_boss", None)
    _projectiles_vs_boss(gv, nb, _nebula_boss_death)


def handle_boss_laser_hits(gv: GameView) -> None:
    """Boss projectiles hitting the player."""
    for proj in list(gv._boss_projectile_list):
        dx = proj.center_x - gv.player.center_x
        dy = proj.center_y - gv.player.center_y
        if math.hypot(dx, dy) <= SHIP_RADIUS + 8.0:
            proj.remove_from_sprite_lists()
            gv._apply_damage_to_player(int(proj.damage))
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.5)


def handle_boss_player_collision(gv: GameView) -> None:
    """Boss ship vs player: heavy push-apart and damage."""
    boss = gv._boss
    if boss is None or boss.hp <= 0:
        return
    dx = boss.center_x - gv.player.center_x
    dy = boss.center_y - gv.player.center_y
    dist = math.hypot(dx, dy)
    combined_r = boss.radius + SHIP_RADIUS
    if dist >= combined_r or dist <= 0.0:
        return
    nx, ny = dx / dist, dy / dist
    overlap = combined_r - dist
    # Push: boss barely moves, player gets most of the push
    boss.center_x += nx * overlap * 0.2
    boss.center_y += ny * overlap * 0.2
    gv.player.center_x -= nx * overlap * 0.8
    gv.player.center_y -= ny * overlap * 0.8
    # Bounce player away
    dot = gv.player.vel_x * (-nx) + gv.player.vel_y * (-ny)
    if dot < 0.0:
        j = (1.0 + BOSS_BOUNCE) * dot
        gv.player.vel_x -= j * (-nx) * 0.8
        gv.player.vel_y -= j * (-ny) * 0.8
    # Damage
    if boss._col_cd <= 0.0:
        boss._col_cd = BOSS_COLLISION_COOLDOWN
        boss.collision_bump()
    _hit_player_on_cooldown(gv, BOSS_COLLISION_DAMAGE, volume=0.6)


def handle_boss_building_hits(gv: GameView) -> None:
    """Boss projectiles hitting station buildings."""
    from sprites.building import HomeStation
    for proj in list(gv._boss_projectile_list):
        if _station_shield_absorbs(gv, proj):
            continue
        for building in list(gv.building_list):
            dx = proj.center_x - building.center_x
            dy = proj.center_y - building.center_y
            if math.hypot(dx, dy) <= BUILDING_RADIUS + 8.0:
                gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                proj.remove_from_sprite_lists()
                building.take_damage(int(proj.damage))
                if building.hp <= 0:
                    gv._disconnect_ports(building)
                    cost = BUILDING_TYPES[building.building_type]["cost"]
                    gv._spawn_iron_pickup(
                        building.center_x, building.center_y, amount=cost)
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
                break  # projectile consumed


def handle_boss_charge_hit(gv: GameView) -> None:
    """Boss charge attack hitting the player (during dash phase only)."""
    boss = gv._boss
    if boss is None or boss.hp <= 0:
        return
    dx = boss.center_x - gv.player.center_x
    dy = boss.center_y - gv.player.center_y
    dist = math.hypot(dx, dy)
    if dist < boss.radius + SHIP_RADIUS:
        if _hit_player_on_cooldown(gv, int(BOSS_CHARGE_DAMAGE), volume=0.8):
            # Knock player back hard on the charge hit.
            if dist > 0.0:
                nx, ny = -dx / dist, -dy / dist
                gv.player.vel_x += nx * 400.0
                gv.player.vel_y += ny * 400.0


# ── Parked ship collision handlers ────────────────────────────────────────


def _destroy_parked_ship(gv: GameView, ship) -> None:
    """Destroy a parked ship, dropping cargo + modules as pickups.

    Cargo dumps used to spawn every pickup at the exact ship centre,
    which stacked them into a single hard-to-distinguish blob.  Now
    every item is placed on an evenly-spaced ring around the death
    point via ``_drop_scatter`` so the player can tell what dropped
    at a glance and the auto-attraction code picks them up cleanly.
    """
    gv._spawn_explosion(ship.center_x, ship.center_y)
    from update_logic import play_sfx_at
    play_sfx_at(gv, gv._explosion_snd,
                ship.center_x, ship.center_y, base_volume=0.7)
    # Pre-count every pickup this death will produce so we can lay
    # them out on one ring.
    cargo_drops: list[tuple[str, int]] = []
    for (_r, _c), (item_type, count) in ship.cargo_items.items():
        if item_type in ("iron", "copper") and count > 0:
            cargo_drops.append((item_type, count))
    module_drops: list[str] = [m for m in ship.module_slots if m is not None]
    total = len(cargo_drops) + len(module_drops)
    positions = _drop_scatter(ship.center_x, ship.center_y, total)
    pos_i = 0
    for item_type, count in cargo_drops:
        x, y = positions[pos_i]
        pos_i += 1
        # ``_spawn_iron_pickup`` also handles copper — the pickup
        # records its own item_type.  Keep the two branches for
        # clarity in case copper ever needs a dedicated spawner.
        gv._spawn_iron_pickup(x, y, amount=count)
    _bp_icons = getattr(gv, "_blueprint_drop_tex", {}) or {}
    for mod in module_drops:
        x, y = positions[pos_i]
        pos_i += 1
        from sprites.pickup import BlueprintPickup
        tex = _bp_icons.get(mod, gv._blueprint_tex)
        bp = BlueprintPickup(tex, x, y, module_type=mod)
        gv.blueprint_pickup_list.append(bp)
    ship.remove_from_sprite_lists()


def handle_parked_ship_damage(gv: GameView) -> None:
    """All projectiles (alien, player, boss, turret) vs parked ships."""
    if len(gv._parked_ships) == 0:
        return
    # Alien lasers
    for proj in list(gv.alien_projectile_list):
        hits = arcade.check_for_collision_with_list(proj, gv._parked_ships)
        if hits:
            ship = hits[0]
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            ship.take_damage(int(proj.damage))
            if ship.hp <= 0:
                _destroy_parked_ship(gv, ship)
    # Player projectiles (friendly fire)
    for proj in list(gv.projectile_list):
        hits = arcade.check_for_collision_with_list(proj, gv._parked_ships)
        if hits:
            ship = hits[0]
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            ship.take_damage(int(proj.damage))
            if ship.hp <= 0:
                _destroy_parked_ship(gv, ship)
    # Boss projectiles
    if gv._boss is not None:
        for proj in list(gv._boss_projectile_list):
            hits = arcade.check_for_collision_with_list(proj, gv._parked_ships)
            if hits:
                ship = hits[0]
                gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                proj.remove_from_sprite_lists()
                ship.take_damage(int(proj.damage))
                if ship.hp <= 0:
                    _destroy_parked_ship(gv, ship)
