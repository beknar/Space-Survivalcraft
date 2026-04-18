"""Slip space — rotating teleporter scattered across non-warp zones.

A player who collides with one is instantly relocated to a different
slipspace in the same zone, with velocity and heading preserved.

Implemented as an ``arcade.Sprite`` so the texture can rotate via the
standard ``angle`` property and so distance checks work via the same
math the rest of the codebase uses.  Slipspaces don't move (centre
stays fixed) — only the texture rotates.

The slipspace's ``radius`` (used for collision) is intentionally
smaller than the displayed texture so the player has to actually fly
into the swirling visual, not just brush its edge.
"""
from __future__ import annotations

import arcade

from constants import (
    SLIPSPACE_DISPLAY_SIZE, SLIPSPACE_RADIUS, SLIPSPACE_ROT_SPEED,
)


class Slipspace(arcade.Sprite):
    """A single slipspace teleporter.

    ``radius`` is exposed as an attribute so the collision helper can
    do a circular check without having to cross-reference the constant.
    """

    def __init__(self, texture: arcade.Texture, x: float, y: float) -> None:
        # Scale so the texture renders at SLIPSPACE_DISPLAY_SIZE px wide
        # regardless of the underlying PNG dimensions.
        scale = SLIPSPACE_DISPLAY_SIZE / max(texture.width, 1)
        super().__init__(path_or_texture=texture, scale=scale)
        self.center_x = x
        self.center_y = y
        self.radius: float = SLIPSPACE_RADIUS
        self.angle: float = 0.0

    def update_slipspace(self, dt: float) -> None:
        """Advance the rotation by ``SLIPSPACE_ROT_SPEED * dt`` degrees."""
        self.angle = (self.angle + SLIPSPACE_ROT_SPEED * dt) % 360.0

    def contains_point(self, px: float, py: float) -> bool:
        """Circular bounds check — ``radius`` covers the active jump zone."""
        dx = px - self.center_x
        dy = py - self.center_y
        return dx * dx + dy * dy <= self.radius * self.radius
