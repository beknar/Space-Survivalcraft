"""Energy-blade melee swing — third basic weapon.

The swing is a brief sprite anchored at the player's nose for
``MELEE_SWING_LIFETIME`` seconds; it rotates ``MELEE_SWING_ARC``
degrees over its lifetime to read as a swung blade rather than a
static frame.

Damage is dealt as a one-tick AOE on every enemy within
``hit_radius`` of the swing centre — see
``update_logic.update_melee_swings`` for the per-frame damage
pass.  The set ``_enemies_hit`` keys off ``id(enemy)`` so a
single swing damages each enemy at most once even if the swing
overlaps the enemy across multiple frames.
"""
from __future__ import annotations

import math

import arcade

from constants import (
    MELEE_SCALE, MELEE_SWING_ARC, MELEE_SWING_LIFETIME,
)


class MeleeSwing(arcade.Sprite):
    """Brief sword-swing visual + AOE-damage carrier."""

    def __init__(
        self,
        texture: arcade.Texture,
        ship,
        offset: float,
        damage: int,
        hit_radius: float,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=MELEE_SCALE)
        self._ship = ship
        self._offset: float = offset
        self.damage: int = damage
        self.hit_radius: float = hit_radius
        self._lifetime: float = MELEE_SWING_LIFETIME
        self._age: float = 0.0
        # IDs of enemies already damaged by THIS swing — keeps a
        # single swing from chunking the same target every frame
        # of its lifetime.
        self._enemies_hit: set[int] = set()
        self._anchor_to_ship()

    def _anchor_to_ship(self) -> None:
        """Snap to the ship's nose at ``self._offset`` ahead, with the
        sword visually rotated by a fraction of ``MELEE_SWING_ARC``
        so the player sees a swing across the swing's lifetime."""
        rad = math.radians(self._ship.heading)
        nx = math.sin(rad)
        ny = math.cos(rad)
        self.center_x = self._ship.center_x + nx * self._offset
        self.center_y = self._ship.center_y + ny * self._offset
        # Swing arc — start at -arc/2 from heading, end at +arc/2.
        progress = (self._age / self._lifetime
                    if self._lifetime > 0 else 1.0)
        progress = max(0.0, min(1.0, progress))
        self.angle = (self._ship.heading
                      - MELEE_SWING_ARC * 0.5
                      + MELEE_SWING_ARC * progress)

    def update_swing(self, dt: float) -> None:
        """Tick lifetime + re-anchor to the ship's current pose."""
        self._age += dt
        self._anchor_to_ship()

    @property
    def expired(self) -> bool:
        return self._age >= self._lifetime

    def already_hit(self, enemy) -> bool:
        return id(enemy) in self._enemies_hit

    def mark_hit(self, enemy) -> None:
        self._enemies_hit.add(id(enemy))
