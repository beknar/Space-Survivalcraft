"""``CombatDrone`` — companion drone that engages aliens / bosses / spawners.

Extracted from ``sprites.drone`` in the 2026-05-07 refactor; the
shared base class lives in ``sprites.drone_base``.
``sprites.drone`` is now a re-export shim so existing
``from sprites.drone import CombatDrone`` imports keep working.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from constants import (
    COMBAT_DRONE_SHIELD,
    COMBAT_DRONE_LASER_DAMAGE,
    COMBAT_DRONE_PNG,
    DRONE_DETECT_RANGE,
    DRONE_RADIUS,
    SFX_COMBAT_DRONE_LASER,
)
from sprites.projectile import Projectile
from sprites.drone_base import _BaseDrone, _load, _load_snd, _walls_from_zone, _iter_asteroids

if TYPE_CHECKING:
    from game_view import GameView


class CombatDrone(_BaseDrone):
    """Attacks nearby aliens + boss."""

    _LABEL = "Combat Drone"

    def __init__(self, x: float, y: float) -> None:
        from constants import COMBAT_DRONE_LASER_PNG
        super().__init__(
            COMBAT_DRONE_PNG,
            _load(COMBAT_DRONE_LASER_PNG),
            x, y,
            shield=COMBAT_DRONE_SHIELD,
            laser_damage=COMBAT_DRONE_LASER_DAMAGE,
            mines_rock=False,
            fire_snd=_load_snd(SFX_COMBAT_DRONE_LASER),
        )

    def update_drone(
        self, dt: float, gv: "GameView",
    ) -> Projectile | None:
        self.update_visuals(dt)
        self.regen_shields(dt, gv.player)
        walls = _walls_from_zone(gv)
        asteroids = _iter_asteroids(gv)
        target = (self._nearest_enemy(gv) if self.has_target_lock()
                  else None)
        self._update_mode(gv.player, target, walls)
        if self._mode == self._MODE_RETURN_HOME:
            self._run_return_home(
                dt, gv.player.center_x, gv.player.center_y,
                gv.player, walls, asteroids)
            return None
        elif self._mode == self._MODE_FOLLOW:
            self.follow(dt, gv.player.center_x, gv.player.center_y,
                        player=gv.player, walls=walls,
                        asteroids=asteroids)
        else:
            # ATTACK — hold station; clear any leftover overlap.
            self._apply_asteroid_pushout(asteroids)
        # Combat drones also vacuum any iron / blueprint pickup
        # they fly past — no reason to leave loot on the ground
        # just because the drone happens to be the combat variant
        # rather than the mining one.
        self._vacuum_pickups(gv)
        if self._mode != self._MODE_ATTACK or target is None:
            return None
        # Stuck check: same target with no HP drop for 5 s → bail.
        if self._track_stuck_progress(dt, target):
            return None
        return self._aim_and_fire(target.center_x, target.center_y)

    def _nearest_enemy(self, gv: "GameView"):
        """Pick the nearest live hostile within ``DRONE_DETECT_RANGE``.

        Maze spawners are **priority targets** — if any spawner sits
        in range, the closest one is returned ahead of every other
        enemy class.  Killing a spawner stops its alien drip + ends
        its laser fire, so prioritising them is much more impactful
        than picking off the next maze alien.

        Otherwise walks every enemy sprite list the active zone
        exposes — ``gv.alien_list`` alone isn't enough because the
        Star Maze swaps that reference between ``self._aliens`` (Z2
        aliens outside the maze) and ``self._maze_aliens`` (inside)
        during update, leaving whichever was last assigned visible.
        By scanning the zone's underlying lists directly the drone
        engages every faction (maze aliens, Z2 aliens, stalkers,
        plus both bosses) regardless of which list happens to be on
        ``gv.alien_list`` when this method runs.
        """
        zone = getattr(gv, "_zone", None)
        # Priority pass: maze spawners.  Star Maze stores them on
        # ``zone._spawners`` (an arcade SpriteList).  Each spawner
        # exposes ``hp`` like every other damageable thing; we filter
        # dead ones (hp <= 0) the same way as the alien pass below.
        spawners = getattr(zone, "_spawners", None)
        if spawners:
            best_sp = None
            best_sp_d2 = DRONE_DETECT_RANGE * DRONE_DETECT_RANGE
            for sp in spawners:
                # ``killed`` is the source of truth (spawner respawns
                # after a window — hp can read >0 even while it's
                # still in the dead phase); skip those husks.
                if getattr(sp, "killed", False):
                    continue
                if getattr(sp, "hp", 0) <= 0:
                    continue
                d2 = ((sp.center_x - self.center_x) ** 2
                      + (sp.center_y - self.center_y) ** 2)
                if d2 < best_sp_d2:
                    best_sp_d2 = d2
                    best_sp = sp
            if best_sp is not None:
                return best_sp

        best = None
        best_d2 = DRONE_DETECT_RANGE * DRONE_DETECT_RANGE
        seen: set[int] = set()

        def _candidates():
            # gv.alien_list often aliases one of the zone lists (Zone 2
            # default) or holds a separate stash — yield it before the
            # zone walk so dedupe-by-id catches the overlap.
            for e in (getattr(gv, "alien_list", []) or []):
                yield e
            if zone is not None and hasattr(zone, "iter_enemies"):
                yield from zone.iter_enemies()
            for boss_attr in ("_boss", "_nebula_boss"):
                b = getattr(gv, boss_attr, None)
                if b is not None:
                    yield b

        for e in _candidates():
            eid = id(e)
            if eid in seen:
                continue
            seen.add(eid)
            if getattr(e, "hp", 0) <= 0:
                continue
            d2 = ((e.center_x - self.center_x) ** 2
                  + (e.center_y - self.center_y) ** 2)
            if d2 < best_d2:
                best_d2 = d2
                best = e
        return best

    def draw_shield(self) -> None:
        """Same dashed-blue arc as ShieldedAlien / shielded MazeAlien."""
        if self.shields <= 0:
            return
        cx, cy = self.center_x, self.center_y
        r = DRONE_RADIUS + 12.0
        segments = 8
        arc = 360 / segments * 0.65
        for i in range(segments):
            start = self._shield_angle + i * (360 / segments)
            a1 = math.radians(start)
            a2 = math.radians(start + arc)
            x1 = cx + math.cos(a1) * r
            y1 = cy + math.sin(a1) * r
            x2 = cx + math.cos(a2) * r
            y2 = cy + math.sin(a2) * r
            arcade.draw_line(x1, y1, x2, y2, (80, 160, 255, 180), 2)
