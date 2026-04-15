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

    def closest_point(self, px: float, py: float) -> tuple[float, float, float]:
        """Return (cx, cy, dist) — the closest point on the wall segment
        to (px, py) and the distance to it."""
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            cx, cy = self.x1, self.y1
        else:
            t = max(0.0, min(1.0,
                             ((px - self.x1) * dx + (py - self.y1) * dy) / length_sq))
            cx = self.x1 + t * dx
            cy = self.y1 + t * dy
        return cx, cy, math.hypot(px - cx, py - cy)

    def blocks_point(self, px: float, py: float, radius: float = 20.0) -> bool:
        """Check if a point is blocked by this wall (within radius)."""
        return self.closest_point(px, py)[2] < radius

    def side_of(self, px: float, py: float) -> float:
        """Signed perpendicular offset from the wall segment. Used to detect
        when a moving body crosses from one side to the other."""
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        return (px - self.x1) * dy - (py - self.y1) * dx

    def segment_crosses(self, ax: float, ay: float,
                        bx: float, by: float) -> bool:
        """True if the segment (a→b) crosses through the wall segment —
        i.e. both endpoints straddle the wall line AND both wall endpoints
        straddle the (a→b) line."""
        s1 = self.side_of(ax, ay)
        s2 = self.side_of(bx, by)
        if s1 == 0.0 or s2 == 0.0 or (s1 > 0) == (s2 > 0):
            return False
        # Now check the other axis.
        mdx = bx - ax
        mdy = by - ay
        s3 = (self.x1 - ax) * mdy - (self.y1 - ay) * mdx
        s4 = (self.x2 - ax) * mdy - (self.y2 - ay) * mdx
        if s3 == 0.0 or s4 == 0.0 or (s3 > 0) == (s4 > 0):
            return False
        return True
