"""Companion drones — mining + combat variants.

Both drones follow the player at a small rotating offset (orbits when
the player is stationary, trails when the player moves) and fire
projectiles into ``gv.projectile_list`` so the existing player-
projectile collision pipelines deliver damage.

- ``MiningDrone`` (75 HP, 0 shield, no shield render) targets the
  nearest asteroid within ``MINING_DRONE_MINING_RANGE`` and fires
  mining-beam projectiles (``mines_rock=True``, 20 HP per hit).  In
  addition, it vacuums any iron / blueprint pickup within
  ``MINING_DRONE_PICKUP_RADIUS`` by force-flagging them ``_flying``
  so the standard fly-to-player loop carries them home.
- ``CombatDrone`` (75 HP, 25 shield, ShieldedAlien-style arc render
  while shielded) targets the nearest live alien / boss within
  ``DRONE_DETECT_RANGE`` and fires combat-laser projectiles
  (``mines_rock=False``, 35 HP per hit).

Only one drone may be deployed at a time.  ``combat_helpers.deploy_drone``
enforces that contract — pressing R again with the same active weapon
is a no-op (no consumable charged), pressing R after switching weapons
swaps the active drone for the matching type.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    DRONE_HP, MINING_DRONE_SHIELD, COMBAT_DRONE_SHIELD,
    DRONE_MAX_SPEED, DRONE_FOLLOW_DIST, DRONE_ORBIT_SPEED,
    DRONE_FIRE_COOLDOWN, DRONE_DETECT_RANGE,
    DRONE_LASER_RANGE, DRONE_LASER_SPEED,
    MINING_DRONE_LASER_DAMAGE, COMBAT_DRONE_LASER_DAMAGE,
    DRONE_SCALE, DRONE_RADIUS,
    MINING_DRONE_PICKUP_RADIUS, MINING_DRONE_MINING_RANGE,
    MINING_DRONE_PNG, COMBAT_DRONE_PNG,
    SFX_MINING_DRONE_LASER, SFX_COMBAT_DRONE_LASER,
)
from settings import audio
from sprites.projectile import Projectile

if TYPE_CHECKING:
    from game_view import GameView


# Module-level texture cache so each PNG decode happens once per game
# run regardless of how many times the player redeploys a drone.
_TEX_CACHE: dict[str, arcade.Texture] = {}
_SND_CACHE: dict[str, arcade.Sound] = {}


def _load(path: str) -> arcade.Texture:
    tex = _TEX_CACHE.get(path)
    if tex is None:
        tex = arcade.load_texture(path)
        _TEX_CACHE[path] = tex
    return tex


def _load_snd(path: str) -> arcade.Sound:
    snd = _SND_CACHE.get(path)
    if snd is None:
        snd = arcade.load_sound(path)
        _SND_CACHE[path] = snd
    return snd


class _BaseDrone(arcade.Sprite):
    """Common follow / orbit / damage / shield state for both drones."""

    _LABEL: str = "Drone"

    def __init__(
        self,
        sprite_path: str,
        laser_tex: arcade.Texture,
        x: float, y: float,
        *,
        shield: int,
        laser_damage: float,
        mines_rock: bool,
        fire_snd: arcade.Sound | None = None,
    ) -> None:
        super().__init__(path_or_texture=_load(sprite_path),
                         scale=DRONE_SCALE)
        self.center_x = x
        self.center_y = y
        self.hp: int = DRONE_HP
        self.max_hp: int = DRONE_HP
        self.shields: int = shield
        self.max_shields: int = shield
        self.radius: float = DRONE_RADIUS
        # Per-instance offset angle so the drone hangs on a specific
        # quadrant relative to the player; the angle ticks via
        # ``DRONE_ORBIT_SPEED`` so it visibly orbits when the player
        # is stationary.
        self._orbit_angle: float = random.uniform(0.0, 360.0)
        self._fire_cd: float = 0.0
        self._hit_timer: float = 0.0
        self._shield_angle: float = 0.0
        self._laser_tex: arcade.Texture = laser_tex
        self._laser_damage: float = laser_damage
        self._mines_rock: bool = mines_rock
        self._fire_snd: arcade.Sound | None = fire_snd
        # Computed each frame — used by the fire path and the alien
        # AI / collisions to know "which way is forward" for muzzle.
        self._heading: float = 0.0
        self.angle = 0.0

    # ── Damage ───────────────────────────────────────────────────────

    def take_damage(self, amount: int) -> None:
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp -= amount
        self._hit_timer = 0.15

    @property
    def dead(self) -> bool:
        return self.hp <= 0

    # ── Per-frame update ─────────────────────────────────────────────

    def follow(self, dt: float, player_x: float, player_y: float) -> None:
        """Steer toward the rotating offset position around the
        player; projectile-style straight-line motion (no inertia).
        Speed-capped at ``DRONE_MAX_SPEED``."""
        self._orbit_angle = (self._orbit_angle + DRONE_ORBIT_SPEED * dt) % 360.0
        rad = math.radians(self._orbit_angle)
        target_x = player_x + math.cos(rad) * DRONE_FOLLOW_DIST
        target_y = player_y + math.sin(rad) * DRONE_FOLLOW_DIST
        dx = target_x - self.center_x
        dy = target_y - self.center_y
        dist = math.hypot(dx, dy)
        if dist <= 0.001:
            return
        step = min(DRONE_MAX_SPEED * dt, dist)
        nx = dx / dist
        ny = dy / dist
        self.center_x += nx * step
        self.center_y += ny * step
        # Heading uses the same (sin, cos) convention as the player
        # ship so the projectile flies forward on launch.
        self._heading = math.degrees(math.atan2(nx, ny)) % 360.0
        self.angle = self._heading

    def update_visuals(self, dt: float) -> None:
        # Hit-flash tint.
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = ((255, 80, 80, 255) if self._hit_timer > 0.0
                          else (255, 255, 255, 255))
        # Shield-arc rotation (used only by CombatDrone but cheap
        # to advance unconditionally).
        self._shield_angle = (self._shield_angle + 90.0 * dt) % 360.0
        # Cooldown tick.
        self._fire_cd = max(0.0, self._fire_cd - dt)

    # ── Fire ─────────────────────────────────────────────────────────

    def _aim_and_fire(
        self, target_x: float, target_y: float,
    ) -> Projectile | None:
        """Spawn one Projectile aimed at ``(target_x, target_y)`` if
        off cooldown; returns the projectile (or ``None``).  Caller
        appends it to the projectile list."""
        if self._fire_cd > 0.0:
            return None
        dx = target_x - self.center_x
        dy = target_y - self.center_y
        dist = math.hypot(dx, dy)
        if dist > DRONE_LASER_RANGE or dist <= 0.001:
            return None
        heading = math.degrees(math.atan2(dx, dy)) % 360.0
        self._fire_cd = DRONE_FIRE_COOLDOWN
        self._heading = heading
        self.angle = heading
        if self._fire_snd is not None:
            arcade.play_sound(self._fire_snd,
                              volume=audio.sfx_volume * 0.4)
        return Projectile(
            self._laser_tex,
            self.center_x, self.center_y,
            heading,
            DRONE_LASER_SPEED, DRONE_LASER_RANGE,
            scale=0.5,
            mines_rock=self._mines_rock,
            damage=self._laser_damage,
        )


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
        ``gv.projectile_list``."""
        self.follow(dt, gv.player.center_x, gv.player.center_y)
        self.update_visuals(dt)
        # Vacuum any iron / blueprint pickup within reach by flagging
        # it as flying — the standard pickup loop in game_view's
        # on_update already pulls it toward the player and credits
        # the inventory on contact.
        for plist in (gv.iron_pickup_list, gv.blueprint_pickup_list):
            for p in plist:
                if getattr(p, "_flying", True):
                    continue
                if math.hypot(p.center_x - self.center_x,
                              p.center_y - self.center_y
                              ) <= MINING_DRONE_PICKUP_RADIUS:
                    p._flying = True
        # Find the nearest static asteroid in the active zone.
        target = self._nearest_asteroid(gv)
        if target is None:
            return None
        return self._aim_and_fire(target.center_x, target.center_y)

    def _nearest_asteroid(self, gv: "GameView"):
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
        else:
            sources.append(getattr(gv, "asteroid_list", []))
        for a in chain(*sources):
            d2 = ((a.center_x - self.center_x) ** 2
                  + (a.center_y - self.center_y) ** 2)
            if d2 < best_d2:
                best_d2 = d2
                best = a
        return best


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
        self.follow(dt, gv.player.center_x, gv.player.center_y)
        self.update_visuals(dt)
        target = self._nearest_enemy(gv)
        if target is None:
            return None
        return self._aim_and_fire(target.center_x, target.center_y)

    def _nearest_enemy(self, gv: "GameView"):
        """Pick the nearest live hostile within ``DRONE_DETECT_RANGE``.

        Walks every enemy sprite list the active zone exposes —
        ``gv.alien_list`` alone isn't enough because the Star Maze
        swaps that reference between ``self._aliens`` (Z2 aliens
        outside the maze) and ``self._maze_aliens`` (inside) during
        update, leaving whichever was last assigned visible.  By
        scanning the zone's underlying lists directly the drone
        engages every faction (maze aliens, Z2 aliens, stalkers,
        plus both bosses) regardless of which list happens to be on
        ``gv.alien_list`` when this method runs.
        """
        best = None
        best_d2 = DRONE_DETECT_RANGE * DRONE_DETECT_RANGE
        sources: list = [getattr(gv, "alien_list", []) or []]
        zone = getattr(gv, "_zone", None)
        if zone is not None:
            for attr in ("_aliens", "_maze_aliens", "_stalkers"):
                lst = getattr(zone, attr, None)
                if lst is not None:
                    sources.append(lst)
        if getattr(gv, "_boss", None) is not None:
            sources.append([gv._boss])
        if getattr(gv, "_nebula_boss", None) is not None:
            sources.append([gv._nebula_boss])
        seen: set[int] = set()
        for src in sources:
            for e in src:
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
