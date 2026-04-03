"""Homing missile projectile."""
from __future__ import annotations

import math

import arcade

from constants import MISSILE_SPEED, MISSILE_RANGE, MISSILE_TURN_RATE, MISSILE_DAMAGE


class HomingMissile(arcade.Sprite):
    """A missile that homes toward the nearest target."""

    def __init__(
        self,
        texture: arcade.Texture,
        x: float, y: float,
        heading: float,
        scale: float = 0.5,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=scale)
        self.center_x = x
        self.center_y = y
        self._heading: float = heading
        self.angle = heading
        self.damage: float = MISSILE_DAMAGE
        self._dist_travelled: float = 0.0
        self._max_range: float = MISSILE_RANGE

    def update_missile(
        self, dt: float,
        targets: list[tuple[float, float]],
    ) -> None:
        """Advance missile toward nearest target.

        targets: list of (x, y) positions to home toward.
        """
        # Find nearest target
        if targets:
            best_dist = float('inf')
            best_x, best_y = self.center_x, self.center_y
            for tx, ty in targets:
                d = math.hypot(tx - self.center_x, ty - self.center_y)
                if d < best_dist:
                    best_dist = d
                    best_x, best_y = tx, ty

            # Turn toward target
            dx = best_x - self.center_x
            dy = best_y - self.center_y
            desired = math.degrees(math.atan2(dx, dy)) % 360
            diff = (desired - self._heading + 180) % 360 - 180
            max_turn = MISSILE_TURN_RATE * dt
            if abs(diff) <= max_turn:
                self._heading = desired
            else:
                self._heading = (self._heading + max_turn * (1 if diff > 0 else -1)) % 360

        # Move forward
        rad = math.radians(self._heading)
        vx = math.sin(rad) * MISSILE_SPEED
        vy = math.cos(rad) * MISSILE_SPEED
        self.center_x += vx * dt
        self.center_y += vy * dt
        self.angle = self._heading
        self._dist_travelled += MISSILE_SPEED * dt

        # Despawn when range exceeded
        if self._dist_travelled >= self._max_range:
            self.remove_from_sprite_lists()
