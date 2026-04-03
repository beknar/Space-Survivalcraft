"""Force wall module — shimmering wall of force behind the ship."""
from __future__ import annotations

import math

import arcade

from constants import FORCE_WALL_LENGTH, FORCE_WALL_DURATION


class ForceWall:
    """A temporary wall of force that blocks enemy movement."""

    def __init__(self, x: float, y: float, heading: float) -> None:
        self.x = x
        self.y = y
        self.heading = heading
        self._lifetime: float = FORCE_WALL_DURATION
        self.dead: bool = False
        # Endpoints perpendicular to heading
        rad = math.radians(heading)
        perp_x = math.cos(rad)
        perp_y = -math.sin(rad)
        half = FORCE_WALL_LENGTH / 2
        self.x1 = x + perp_x * half
        self.y1 = y + perp_y * half
        self.x2 = x - perp_x * half
        self.y2 = y - perp_y * half
        self._shimmer: float = 0.0

    def update(self, dt: float) -> None:
        self._lifetime -= dt
        self._shimmer += dt * 6.0
        if self._lifetime <= 0:
            self.dead = True

    def draw(self) -> None:
        if self.dead:
            return
        # Shimmer alpha based on time
        base_alpha = int(180 * (self._lifetime / FORCE_WALL_DURATION))
        pulse = int(40 * abs(math.sin(self._shimmer)))
        alpha = min(255, base_alpha + pulse)
        # Draw thick shimmering line
        arcade.draw_line(self.x1, self.y1, self.x2, self.y2,
                         (100, 200, 255, alpha), 6)
        arcade.draw_line(self.x1, self.y1, self.x2, self.y2,
                         (200, 240, 255, alpha // 2), 2)

    def blocks_point(self, px: float, py: float, radius: float = 20.0) -> bool:
        """Check if a point is blocked by this wall (within radius)."""
        # Distance from point to line segment
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.hypot(px - self.x1, py - self.y1) < radius
        t = max(0, min(1, ((px - self.x1) * dx + (py - self.y1) * dy) / length_sq))
        closest_x = self.x1 + t * dx
        closest_y = self.y1 + t * dy
        return math.hypot(px - closest_x, py - closest_y) < radius
