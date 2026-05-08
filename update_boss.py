"""Boss / Nebula-boss per-frame update helpers extracted from update_logic.

The Double Star boss (Zone 1 + warp variants) and the Nebula boss
(Zone 2, summoned via QWI) share a common preamble (find Home Station
anchor + cloak-aware player position) and a common projectile flow.
This module owns:

* ``_boss_update_context`` — the shared preamble.
* ``update_boss`` — Double Star boss spawn check + per-frame tick.
* ``update_nebula_boss`` — Nebula boss tick (gas clouds + cone AOE).
* ``_apply_nebula_slow`` — slow-timer setter triggered by gas/cone hits.

Re-exported from update_logic so existing
``from update_logic import update_boss`` / ``update_nebula_boss`` /
``_apply_nebula_slow`` call sites keep working.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from constants import WORLD_WIDTH, WORLD_HEIGHT
from collisions import (
    handle_boss_projectile_hits,
    handle_nebula_boss_projectile_hits,
    handle_boss_player_collision,
    handle_boss_laser_hits,
    handle_boss_building_hits,
    handle_boss_charge_hit,
)

import update_logic as _ul

if TYPE_CHECKING:
    from game_view import GameView


def _boss_update_context(gv: GameView) -> tuple[float, float, float, float]:
    """Return (station_x, station_y, boss_px, boss_py) for the boss
    update path.  Looks up the active Home Station (falls back to
    world centre) and feeds the boss a cloak-aware player position:
    when the player is inside an active null field, we hand the boss
    coordinates a billion pixels away so its AI stays in patrol
    instead of engaging.  Shared by both the Double Star boss and
    the Nebula boss update loops.
    """
    station_x, station_y = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    for b in gv.building_list:
        if isinstance(b, _ul.HomeStation) and not b.disabled:
            station_x, station_y = b.center_x, b.center_y
            break
    if _ul.player_is_cloaked(gv):
        boss_px, boss_py = gv.player.center_x + 1e9, gv.player.center_y + 1e9
    else:
        boss_px, boss_py = gv.player.center_x, gv.player.center_y
    return station_x, station_y, boss_px, boss_py


def update_boss(gv: GameView, dt: float) -> None:
    """Boss spawn check and update."""
    gv._check_boss_spawn()
    if gv._boss is not None and gv._boss.hp > 0:
        station_x, station_y, boss_px, boss_py = _boss_update_context(gv)
        projs = gv._boss.update_boss(
            dt, boss_px, boss_py,
            station_x, station_y,
            gv.asteroid_list,
            force_walls=getattr(gv, "_force_walls", None),
        )
        for p in projs:
            gv._boss_projectile_list.append(p)
        for proj in list(gv._boss_projectile_list):
            proj.update_projectile(dt)
        handle_boss_projectile_hits(gv)
        handle_boss_laser_hits(gv)
        handle_boss_player_collision(gv)
        handle_boss_building_hits(gv)
        if gv._boss is not None and gv._boss._charging and gv._boss._charge_windup <= 0.0:
            handle_boss_charge_hit(gv)


def update_nebula_boss(gv: GameView, dt: float) -> None:
    """Per-frame tick for the Nebula boss (spawned via QWI menu).

    Inherits the parent ``update_boss`` flow for movement + cannon
    fire + phase management, and layers on the gas-cloud projectile
    + cone-AoE attacks.  Gas clouds apply damage + a time-limited
    slow to the player on contact.  The cone applies both while the
    player is inside it."""
    import math as _math
    nb = getattr(gv, "_nebula_boss", None)
    if nb is None or nb.hp <= 0:
        return

    # Shared preamble: home station anchor + cloak-aware player pos.
    station_x, station_y, boss_px, boss_py = _boss_update_context(gv)

    # Run the base BossAlienShip update (movement, cannon + spread,
    # charge dash).  Projectiles go to the standard boss projectile
    # list so existing collision handlers deliver damage.
    asteroid_list = gv.asteroid_list
    zone = getattr(gv, "_zone", None)
    zone_asts = getattr(zone, "_iron_asteroids", None)
    if zone_asts is not None:
        asteroid_list = zone_asts
    projs = nb.update_boss(
        dt, boss_px, boss_py, station_x, station_y, asteroid_list,
        force_walls=getattr(gv, "_force_walls", None))
    # Nebula boss rams through asteroids instead of steering around
    # them — destroy any the boss is currently overlapping and drop
    # normal loot.  Only runs when the boss lives in Zone 2 (the
    # crush helper reads from ``zone._iron_asteroids`` etc.).
    if zone is not None and hasattr(zone, "_iron_asteroids"):
        from zones.zone2_world import nebula_boss_destroy_asteroids
        nebula_boss_destroy_asteroids(zone, gv, nb)
    for p in projs:
        gv._boss_projectile_list.append(p)

    # Nebula-specific tick — returns a GasCloudProjectile when the
    # gas cooldown expires.
    new_gas = nb.tick_nebula(dt, boss_px, boss_py)
    if new_gas is not None:
        gv._nebula_gas_clouds.append(new_gas)

    # Advance gas clouds + test hit on the player.
    px, py = gv.player.center_x, gv.player.center_y
    survivors = []
    for c in gv._nebula_gas_clouds:
        expired = c.update_gas(dt)
        hit = c.contains_point(px, py)
        if hit and not getattr(gv, "_player_dead", False):
            from combat_helpers import apply_damage_to_player
            apply_damage_to_player(gv, int(c.damage))
            _apply_nebula_slow(gv)
            # Cloud dissipates on hit.
            continue
        if not expired:
            survivors.append(c)
    gv._nebula_gas_clouds = survivors

    # Cone tick — damage while player inside; slow + damage ~2 Hz.
    if getattr(nb, "_cone_active", False):
        if nb.cone_contains_point(px, py):
            if not hasattr(gv, "_nebula_cone_tick_cd"):
                gv._nebula_cone_tick_cd = 0.0
            gv._nebula_cone_tick_cd -= dt
            if gv._nebula_cone_tick_cd <= 0.0:
                from constants import NEBULA_BOSS_CONE_DAMAGE
                from combat_helpers import apply_damage_to_player
                apply_damage_to_player(gv, int(NEBULA_BOSS_CONE_DAMAGE))
                _apply_nebula_slow(gv)
                gv._nebula_cone_tick_cd = 0.5

    # Route player + turret projectiles at the Nebula boss.  Station
    # turrets, Missile Arrays (via missile-explosion hits below), and
    # AI-piloted parked ships all push shots into the same two lists
    # ``_projectiles_vs_boss`` walks, so this one call wires every
    # friendly damage source into the Nebula boss's HP pool.
    handle_nebula_boss_projectile_hits(gv)

    # Clear the boss from GameView once HP drops to zero — the
    # projectile handler already runs _nebula_boss_death on the
    # frame that lands the killing shot, but the boss can also die
    # from gas-cloud / cone internals touching its own HP in
    # future changes, so keep this fallback.
    if gv._nebula_boss is not None and gv._nebula_boss.hp <= 0:
        gv._nebula_boss = None
        gv._nebula_boss_list.clear()
        gv._nebula_gas_clouds.clear()


def _apply_nebula_slow(gv) -> None:
    """Mark the player as slowed for ``NEBULA_BOSS_SLOW_DURATION``
    seconds.  Player movement code (update_movement) honors the
    ``_nebula_slow_timer`` by halving effective speed while it's
    positive."""
    from constants import NEBULA_BOSS_SLOW_DURATION
    gv._nebula_slow_timer = max(
        getattr(gv, "_nebula_slow_timer", 0.0),
        NEBULA_BOSS_SLOW_DURATION,
    )
