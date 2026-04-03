"""Iron ore pickup sprite."""
from __future__ import annotations

import math
from typing import Optional

import arcade

from constants import (
    ASTEROID_IRON_YIELD, IRON_PICKUP_DIST, IRON_FLY_SPEED,
    BLUEPRINT_SPIN_SPEED,
)


class IronPickup(arcade.Sprite):
    """Iron ore icon dropped at the site of a destroyed asteroid.

    - Idles at drop position until the ship comes within IRON_PICKUP_DIST px.
    - Then flies toward the ship at IRON_FLY_SPEED px/s.
    - Returns True from update_pickup() when it reaches the ship (collected).
    """

    def __init__(
        self,
        texture: arcade.Texture,
        x: float,
        y: float,
        amount: int = ASTEROID_IRON_YIELD,
        lifetime: Optional[float] = None,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=0.5)
        self.center_x = x
        self.center_y = y
        self.amount: int = amount           # units this pickup is worth
        self.item_type: str = "iron"        # item type (overridden for copper etc.)
        self._lifetime: Optional[float] = lifetime  # None = never expires
        self._age: float = 0.0
        self._flying: bool = False

    def update_pickup(
        self, dt: float, ship_x: float, ship_y: float, ship_radius: float = 0.0
    ) -> bool:
        """Advance state. Returns True on collection (caller reads .amount then removes).

        ship_radius: approximate radius of the ship sprite in px.  The pickup
        trigger fires when the *edge* of the ship (not its centre) comes within
        IRON_PICKUP_DIST px of the token.
        """
        # Age the token; despawn silently when lifetime expires
        if self._lifetime is not None:
            self._age += dt
            if self._age >= self._lifetime:
                self.remove_from_sprite_lists()
                return False

        dx = ship_x - self.center_x
        dy = ship_y - self.center_y
        dist = math.hypot(dx, dy)
        # Edge distance = centre-to-centre minus the ship's radius
        edge_dist = max(0.0, dist - ship_radius)

        if not self._flying and edge_dist <= IRON_PICKUP_DIST:
            self._flying = True

        if self._flying:
            if dist < 6.0:
                self.remove_from_sprite_lists()
                return True
            step = IRON_FLY_SPEED * dt
            ratio = min(1.0, step / dist)
            self.center_x += dx * ratio
            self.center_y += dy * ratio

        return False


class BlueprintPickup(IronPickup):
    """Spinning blueprint pickup dropped by destroyed aliens/asteroids.

    Inherits fly-to-ship behavior from IronPickup.  Adds a spinning
    animation and stores the module type for inventory integration.
    """

    def __init__(
        self,
        texture: arcade.Texture,
        x: float,
        y: float,
        module_type: str,
        lifetime: Optional[float] = None,
    ) -> None:
        super().__init__(texture, x, y, amount=1, lifetime=lifetime)
        self.module_type: str = module_type
        self.item_type: str = f"bp_{module_type}"
        self.scale = 0.4

    def update_pickup(
        self, dt: float, ship_x: float, ship_y: float, ship_radius: float = 0.0
    ) -> bool:
        self.angle = (self.angle + BLUEPRINT_SPIN_SPEED * dt) % 360
        return super().update_pickup(dt, ship_x, ship_y, ship_radius)
