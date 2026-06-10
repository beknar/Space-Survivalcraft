"""Landing-scene airborne enemies (docs/planets.md section 5).

Three spec-driven variants — Sky Worm, Cloud Drone, Thunder Worm — all
share one class; behaviour differences come entirely from their
``LandingEnemySpec`` (see specs.py).  Modeled on the Enemy Spawner warp
zone's ``_MiniAlien``: pursue the player, fire when in range.  Two
differences: these carry shields (rolled per-spawn from ``shield_chance``)
and the Thunder Worm fires two projectiles per shot (``spec.shots == 2``).

The owning zone (zones/zone_planetary_landing.py) drives the per-frame
update and owns the projectile + collision handling, mirroring how
``EnemySpawnerWarpZone`` drives ``_MiniAlien``.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from sprites.projectile import Projectile

if TYPE_CHECKING:
    from specs import LandingEnemySpec


class LandingEnemy(arcade.Sprite):
    """One airborne enemy.  Patrols a small home orbit until the player
    enters ``spec.detect`` range, then pursues + fires."""

    def __init__(
        self,
        spec: "LandingEnemySpec",
        body_tex: arcade.Texture,
        laser_tex: arcade.Texture,
        x: float,
        y: float,
        *,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(path_or_texture=body_tex, scale=spec.scale)
        self.center_x = x
        self.center_y = y
        self.spec = spec
        r = rng or random
        self.hp: int = spec.hp
        self.max_hp: int = spec.hp
        # Shield is rolled per spawn: a fraction (shield_chance) of this
        # type spawns with its shield bank, the rest with none.
        self.shields: int = spec.shield if r.random() < spec.shield_chance else 0
        self.max_shields: int = spec.shield
        self._laser_tex = laser_tex
        self._fire_cd: float = r.uniform(0.0, spec.fire_cd)
        self._heading: float = r.uniform(0.0, 360.0)
        self.angle = self._heading

    def take_damage(self, amount: int) -> None:
        """Drain shields first, then HP (mirrors the player/alien rule)."""
        amount = int(amount)
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp -= amount

    def update_enemy(self, dt: float, px: float, py: float) -> list[Projectile]:
        """Advance one frame; return any projectiles fired this tick
        (0, 1, or — for the Thunder Worm — 2)."""
        spec = self.spec
        dx = px - self.center_x
        dy = py - self.center_y
        dist = math.hypot(dx, dy)

        pursuing = dist <= spec.detect
        if pursuing and dist > 1.0:
            nx, ny = dx / dist, dy / dist
            self.center_x += nx * spec.speed * dt
            self.center_y += ny * spec.speed * dt
            self._heading = math.degrees(math.atan2(nx, ny)) % 360
            self.angle = self._heading

        self._fire_cd = max(0.0, self._fire_cd - dt)
        if pursuing and self._fire_cd <= 0.0 and dist <= spec.laser_range:
            self._fire_cd = spec.fire_cd
            return self._fire(dx, dy, dist)
        return []

    def _fire(self, dx: float, dy: float, dist: float) -> list[Projectile]:
        """Emit ``spec.shots`` projectiles aimed at the player.  A
        2-shot burst (Thunder Worm) fans the pair out symmetrically by
        ``LANDING_THUNDER_WORM_DOUBLE_SHOT_SPREAD`` degrees."""
        from constants import LANDING_THUNDER_WORM_DOUBLE_SHOT_SPREAD

        spec = self.spec
        if dist <= 0:
            base = self._heading
        else:
            base = math.degrees(math.atan2(dx / dist, dy / dist)) % 360
        if spec.shots <= 1:
            offsets = [0.0]
        else:
            half = LANDING_THUNDER_WORM_DOUBLE_SHOT_SPREAD / 2.0
            offsets = [-half, half]
        shots: list[Projectile] = []
        for off in offsets:
            shots.append(Projectile(
                self._laser_tex,
                self.center_x, self.center_y,
                (base + off) % 360,
                spec.laser_speed, spec.laser_range,
                scale=0.5, damage=spec.damage,
            ))
        return shots
