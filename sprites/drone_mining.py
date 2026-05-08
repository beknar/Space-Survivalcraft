"""``MiningDrone`` — companion drone that mines asteroids and vacuums loot.

Extracted from ``sprites.drone`` in the 2026-05-07 refactor; the
shared base class lives in ``sprites.drone_base``.
``sprites.drone`` is now a re-export shim so existing
``from sprites.drone import MiningDrone`` imports keep working.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from constants import (
    MINING_DRONE_SHIELD,
    MINING_DRONE_LASER_DAMAGE,
    MINING_DRONE_PNG,
    MINING_DRONE_MINING_RANGE,
    SFX_MINING_DRONE_LASER,
)
from sprites.projectile import Projectile
from sprites.drone_base import _BaseDrone, _load, _load_snd, _walls_from_zone, _iter_asteroids

if TYPE_CHECKING:
    from game_view import GameView


class MiningDrone(_BaseDrone):
    """Mines nearby asteroids and vacuums up dropped loot."""

    _LABEL = "Mining Drone"

    def __init__(self, x: float, y: float) -> None:
        from constants import MINING_DRONE_LASER_PNG
        super().__init__(
            MINING_DRONE_PNG,
            _load(MINING_DRONE_LASER_PNG),
            x, y,
            shield=MINING_DRONE_SHIELD,
            laser_damage=MINING_DRONE_LASER_DAMAGE,
            mines_rock=True,
            fire_snd=_load_snd(SFX_MINING_DRONE_LASER),
        )

    def update_drone(
        self, dt: float, gv: "GameView",
    ) -> Projectile | None:
        """Advance follow + fire + pickup-vacuum logic.  Returns a
        Projectile (or ``None``) for the caller to append to
        ``gv.projectile_list``.

        Mode transitions: with an asteroid in mining range, switch to
        ATTACK and mine; otherwise FOLLOW player at one of the three
        side / back slots.  Mining drones break off if the player
        drifts past ``DRONE_BREAK_OFF_DIST`` so the drone doesn't get
        stranded chasing rocks while the player flies away."""
        self.update_visuals(dt)
        self.regen_shields(dt, gv.player)
        walls = _walls_from_zone(gv)
        asteroids = _iter_asteroids(gv)
        # Mode update — target = nearest asteroid.
        target = (self._nearest_asteroid(gv) if self.has_target_lock()
                  else None)
        self._update_mode(gv.player, target, walls)
        if self._mode == self._MODE_RETURN_HOME:
            self._run_return_home(
                dt, gv.player.center_x, gv.player.center_y,
                gv.player, walls, asteroids)
        elif self._mode == self._MODE_FOLLOW:
            self.follow(dt, gv.player.center_x, gv.player.center_y,
                        player=gv.player, walls=walls,
                        asteroids=asteroids)
        else:
            # ATTACK: hold position but still avoid drifting into a
            # rock if push-out from a previous frame left an overlap.
            self._apply_asteroid_pushout(asteroids)
        self._vacuum_pickups(gv)
        if self._mode != self._MODE_ATTACK or target is None:
            return None
        # Stuck check: same target with no HP drop for 5 s → bail.
        if self._track_stuck_progress(dt, target):
            return None
        return self._aim_and_fire(target.center_x, target.center_y)

    def _nearest_asteroid(self, gv: "GameView"):
        """Pick the nearest mineable rock within
        ``MINING_DRONE_MINING_RANGE``.  Now includes wandering
        magnetic asteroids alongside the static iron / double-iron /
        copper lists — wanderers carry the same ``mines_rock``
        damage profile and were previously invisible to the drone
        only because the source list omitted them.
        """
        from itertools import chain
        best = None
        best_d2 = MINING_DRONE_MINING_RANGE * MINING_DRONE_MINING_RANGE
        zone = getattr(gv, "_zone", None)
        # Static asteroid lists for the active zone.
        sources = []
        if hasattr(zone, "_iron_asteroids"):
            sources.append(zone._iron_asteroids)
            sources.append(getattr(zone, "_double_iron", []))
            sources.append(getattr(zone, "_copper_asteroids", []))
            sources.append(getattr(zone, "_wanderers", []))
        else:
            sources.append(getattr(gv, "asteroid_list", []))
        for a in chain(*sources):
            d2 = ((a.center_x - self.center_x) ** 2
                  + (a.center_y - self.center_y) ** 2)
            if d2 < best_d2:
                best_d2 = d2
                best = a
        return best
