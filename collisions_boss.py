"""Zone 1 + Nebula boss collision handlers.

Extracted from ``collisions`` in the 2026-05-10 split.  Holds the
two boss-death + loot routines, the shared ``_projectiles_vs_boss``
helper, and the per-frame handlers for boss laser/charge/projectile
hits on the player and station buildings.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from constants import (
    SHIP_RADIUS, BUILDING_RADIUS,
    BOSS_COLLISION_DAMAGE, BOSS_COLLISION_COOLDOWN,
    BOSS_BOUNCE, BOSS_CHARGE_DAMAGE, BOSS_XP_REWARD, BOSS_IRON_DROP,
    BUILDING_TYPES,
)
from sprites.explosion import HitSpark

from collisions_common import (
    _drop_scatter, _hit_player_on_cooldown,
    _station_shield_absorbs, apply_enemy_projectile_hit,
)

if TYPE_CHECKING:
    from game_view import GameView


_NEBULA_BOSS_IRON_DROP: int = 3000
_NEBULA_BOSS_COPPER_DROP: int = 1000


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
    gv._spawn_wormholes()
    gv._boss_announce_timer = 5.0
    gv._t_boss_announce.text = "Double Star Boss KILLED"
    gv._t_boss_subtitle.text = "Wormholes have appeared at the edges of the sector!"


def damage_boss(gv: GameView, boss, amount: int) -> bool:
    """Apply ``amount`` damage to ``boss`` + fire the appropriate
    death helper (``_boss_death`` / ``_nebula_boss_death``) if HP
    reaches 0.  Returns ``True`` if the boss died this call.

    Consolidates the take_damage + post-damage death routing that
    was previously duplicated across three call sites
    (projectiles, missiles, melee).  Caught a real bug:
    ``_update_blade_aoe`` in update_blade.py forgot to call
    ``_boss_death`` after a lethal melee hit, leaving the boss as
    a spriteless ghost still referenced by ``gv._boss`` (twelfth
    telemetry pass, fixed in PR #110).  This helper makes that
    class of bug unreachable -- every player-damage path now
    funnels through one function.

    Caller is responsible for hit detection / VFX / projectile
    cleanup; this function only handles the
    ``take_damage + check hp + dispatch death helper`` triad.
    """
    if boss is None or boss.hp <= 0:
        return False
    boss.take_damage(int(amount))
    if boss.hp > 0:
        return False
    if boss is gv._boss:
        _boss_death(gv)
    elif boss is getattr(gv, "_nebula_boss", None):
        _nebula_boss_death(gv)
    return True


def _projectiles_vs_boss(gv: GameView, boss, _on_death=None) -> None:
    """Shared helper: player + turret projectiles damage ``boss``.

    Used for both the Double Star and the Nebula boss -- the same
    player laser or station-turret shot should hurt whichever boss
    is alive.  Death routing is handled by ``damage_boss`` based
    on whether ``boss`` is ``gv._boss`` or ``gv._nebula_boss``.

    The legacy ``on_death`` parameter is accepted but ignored for
    backwards-compat with any out-of-tree callers; new code should
    just pass ``(gv, boss)``.
    """
    if boss is None or boss.hp <= 0:
        return
    hit_r = boss.radius + 10.0
    for proj in list(gv.projectile_list):
        if proj.mines_rock:
            continue
        dx = proj.center_x - boss.center_x
        dy = proj.center_y - boss.center_y
        if math.hypot(dx, dy) <= hit_r:
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            gv._trigger_shake()
            proj.remove_from_sprite_lists()
            if damage_boss(gv, boss, proj.damage):
                return
    for proj in list(gv.turret_projectile_list):
        if boss.hp <= 0:
            return
        dx = proj.center_x - boss.center_x
        dy = proj.center_y - boss.center_y
        if math.hypot(dx, dy) <= hit_r:
            gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
            proj.remove_from_sprite_lists()
            if damage_boss(gv, boss, proj.damage):
                return


def handle_boss_projectile_hits(gv: GameView) -> None:
    """Player + turret projectiles hitting the Double Star boss."""
    _projectiles_vs_boss(gv, gv._boss)


def _nebula_boss_death(gv: GameView) -> None:
    """Handle Nebula boss death: loot, announce, and spawn four corner
    wormholes in Zone 2 that route to the 2x-danger Nebula warp
    zones, which in turn deposit the player in the Star Maze.

    Drops 3000 iron + 1000 copper per user spec (no XP -- the Nebula
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
    from zones.zone2 import Zone2 as _Zone2
    from zones.star_maze import StarMazeZone as _StarMazeZone
    if isinstance(gv._zone, (_Zone2, _StarMazeZone)):
        gv._zone.mark_nebula_boss_defeated(gv)
    gv._boss_announce_timer = 5.0
    gv._t_boss_announce.text = "Nebula Boss KILLED"
    gv._t_boss_subtitle.text = (
        "Corner wormholes open. The Star Maze awaits.")


def handle_nebula_boss_projectile_hits(gv: GameView) -> None:
    """Player + turret projectiles hitting the Nebula boss."""
    nb = getattr(gv, "_nebula_boss", None)
    _projectiles_vs_boss(gv, nb)


def handle_boss_laser_hits(gv: GameView) -> None:
    """Boss projectiles hitting the player."""
    for proj in list(gv._boss_projectile_list):
        dx = proj.center_x - gv.player.center_x
        dy = proj.center_y - gv.player.center_y
        if math.hypot(dx, dy) <= SHIP_RADIUS + 8.0:
            apply_enemy_projectile_hit(gv, proj, bump_volume=0.5)


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
    boss.center_x += nx * overlap * 0.2
    boss.center_y += ny * overlap * 0.2
    gv.player.center_x -= nx * overlap * 0.8
    gv.player.center_y -= ny * overlap * 0.8
    dot = gv.player.vel_x * (-nx) + gv.player.vel_y * (-ny)
    if dot < 0.0:
        j = (1.0 + BOSS_BOUNCE) * dot
        gv.player.vel_x -= j * (-nx) * 0.8
        gv.player.vel_y -= j * (-ny) * 0.8
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
                break


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
            if dist > 0.0:
                nx, ny = -dx / dist, -dy / dist
                gv.player.vel_x += nx * 400.0
                gv.player.vel_y += ny * 400.0
