"""Engine contrail particle effect."""
from __future__ import annotations

import arcade


class ContrailParticle:
    """A single fading, shrinking particle in a ship's engine contrail."""

    def __init__(
        self, x: float, y: float,
        start_colour: tuple[int, int, int],
        end_colour: tuple[int, int, int],
        lifetime: float,
        start_size: float,
        end_size: float,
    ) -> None:
        self.x = x
        self.y = y
        self._start_r, self._start_g, self._start_b = start_colour
        self._end_r, self._end_g, self._end_b = end_colour
        self._lifetime = lifetime
        self._start_size = start_size
        self._end_size = end_size
        self._age: float = 0.0
        self.dead: bool = False

    def update(self, dt: float) -> None:
        self._age += dt
        if self._age >= self._lifetime:
            self.dead = True

    def draw(self) -> None:
        if self.dead:
            return
        t = self._age / self._lifetime  # 0 -> 1
        radius = self._start_size + (self._end_size - self._start_size) * t
        alpha = int(255 * (1.0 - t))
        r = int(self._start_r + (self._end_r - self._start_r) * t)
        g = int(self._start_g + (self._end_g - self._start_g) * t)
        b = int(self._start_b + (self._end_b - self._start_b) * t)
        if radius > 0.5:
            arcade.draw_circle_filled(self.x, self.y, radius, (r, g, b, alpha))
