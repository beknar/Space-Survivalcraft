"""Collision-handling re-export shim.

The actual collision routines were extracted into per-entity modules
in the 2026-05-10 split.  This module exists as a thin shim so
existing
``from collisions import handle_projectile_hits`` /
``import collisions; collisions._try_melee_deflect`` style imports
keep working.

* ``collisions_common``      -- drop scatter, kill rewards, overlap +
                                reflect helpers, melee deflect, the
                                player-on-cooldown hit helper, station
                                shield absorb check.
* ``collisions_player``      -- player-projectile loop, player-vs-
                                asteroid, player-vs-building.
* ``collisions_alien``       -- alien-vs-everything plus alien laser
                                hits on player and buildings.
* ``collisions_turret``      -- turret + AI-pilot projectile loop.
* ``collisions_boss``        -- Zone 1 + Nebula boss death routines,
                                projectile/laser/charge/building hits.
* ``collisions_parked_ship`` -- parked-ship destruction + per-frame
                                damage from every projectile source.

Tests still ``import collisions`` and ``monkeypatch.setattr(
collisions.random, "random", ...)`` etc -- ``random`` and ``math`` are
re-imported here so attribute access on the shim resolves the same
modules every helper uses internally.
"""
from __future__ import annotations

import math  # re-exported for test patches that touch ``collisions.math``
import random  # re-exported for tests that patch ``collisions.random``

from collisions_common import (
    _drop_scatter,
    _apply_kill_rewards,
    resolve_overlap,
    reflect_velocity,
    _alert_nearby_aliens,
    _try_melee_deflect,
    apply_enemy_projectile_hit,
    _hit_player_on_cooldown,
    _station_shield_absorbs,
)
from collisions_player import (
    handle_projectile_hits,
    handle_ship_asteroid_collision,
    handle_ship_building_collision,
)
from collisions_alien import (
    handle_alien_player_collision,
    handle_alien_asteroid_collision,
    handle_alien_alien_collision,
    handle_alien_laser_hits,
    handle_alien_laser_building_hits,
    handle_alien_building_collision,
)
from collisions_turret import handle_turret_projectile_hits
from collisions_boss import (
    _NEBULA_BOSS_IRON_DROP,
    _NEBULA_BOSS_COPPER_DROP,
    _boss_death,
    _projectiles_vs_boss,
    handle_boss_projectile_hits,
    _nebula_boss_death,
    handle_nebula_boss_projectile_hits,
    handle_boss_laser_hits,
    handle_boss_player_collision,
    handle_boss_building_hits,
    handle_boss_charge_hit,
)
from collisions_parked_ship import (
    _destroy_parked_ship,
    handle_parked_ship_damage,
)

__all__ = [
    # common helpers
    "_drop_scatter", "_apply_kill_rewards",
    "resolve_overlap", "reflect_velocity",
    "_alert_nearby_aliens", "_try_melee_deflect",
    "apply_enemy_projectile_hit",
    "_hit_player_on_cooldown", "_station_shield_absorbs",
    # player
    "handle_projectile_hits", "handle_ship_asteroid_collision",
    "handle_ship_building_collision",
    # alien
    "handle_alien_player_collision", "handle_alien_asteroid_collision",
    "handle_alien_alien_collision", "handle_alien_laser_hits",
    "handle_alien_laser_building_hits", "handle_alien_building_collision",
    # turret
    "handle_turret_projectile_hits",
    # boss
    "_NEBULA_BOSS_IRON_DROP", "_NEBULA_BOSS_COPPER_DROP",
    "_boss_death", "_projectiles_vs_boss",
    "handle_boss_projectile_hits",
    "_nebula_boss_death", "handle_nebula_boss_projectile_hits",
    "handle_boss_laser_hits", "handle_boss_player_collision",
    "handle_boss_building_hits", "handle_boss_charge_hit",
    # parked ship
    "_destroy_parked_ship", "handle_parked_ship_damage",
]
