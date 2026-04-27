"""Energy-blade melee weapon — persistent sprite + swing animation.

The blade is **visible the whole time** the player has the melee
weapon active (cycled in via Tab).  It rests in front of the
ship at ``offset`` px ahead of the nose, pointing forward; when
the player presses fire and the cooldown is ready, the blade
runs a swing animation that rotates ``MELEE_SWING_ARC`` degrees
over ``MELEE_SWING_LIFETIME`` seconds and deals one-hit-per-enemy
AOE damage to anything inside ``hit_radius``.

The set ``_enemies_hit`` keys off ``id(enemy)`` so a single
swing damages each enemy at most once even if the swing's hit
disk overlaps the enemy across multiple animation frames.
"""
from __future__ import annotations

import math

import arcade

from constants import (
    MELEE_SCALE, MELEE_SWING_ARC, MELEE_SWING_LIFETIME,
    MELEE_TEX_ANGLE_OFFSET,
)


class MeleeBlade(arcade.Sprite):
    """Persistent energy-blade visual + AOE-damage carrier."""

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
        # Swing animation timer.  ``> 0`` while animating;
        # ``0`` (or below) → idle, blade points forward.
        self._swing_timer: float = 0.0
        # IDs of enemies already damaged by the CURRENT swing.
        # Cleared at the start of every new swing.
        self._enemies_hit: set[int] = set()
        self._update_pose()

    # ── Pose ────────────────────────────────────────────────────────

    def _update_pose(self) -> None:
        """Anchor to the ship's nose at ``self._offset`` ahead.
        Rotation: idle → points forward (matches ship heading);
        swinging → rotates from ``-arc/2`` to ``+arc/2`` over the
        swing's lifetime."""
        rad = math.radians(self._ship.heading)
        nx = math.sin(rad)
        ny = math.cos(rad)
        self.center_x = self._ship.center_x + nx * self._offset
        self.center_y = self._ship.center_y + ny * self._offset
        # ``MELEE_TEX_ANGLE_OFFSET`` compensates for the sword
        # PNG's diagonal art so the blade tip lines up with the
        # ship's heading direction in both idle and swinging
        # poses.
        if self._swing_timer > 0.0:
            progress = 1.0 - (self._swing_timer / MELEE_SWING_LIFETIME)
            progress = max(0.0, min(1.0, progress))
            self.angle = (self._ship.heading
                          - MELEE_SWING_ARC * 0.5
                          + MELEE_SWING_ARC * progress
                          + MELEE_TEX_ANGLE_OFFSET)
        else:
            # Idle — blade points straight ahead.
            self.angle = self._ship.heading + MELEE_TEX_ANGLE_OFFSET

    def update_blade(self, dt: float) -> None:
        """Advance the swing animation (if any) and re-anchor."""
        if self._swing_timer > 0.0:
            self._swing_timer = max(0.0, self._swing_timer - dt)
            if self._swing_timer == 0.0:
                # Animation ended — clear the hit set so the next
                # swing can damage the same enemies again.
                self._enemies_hit.clear()
        self._update_pose()

    # ── Swing trigger / AOE state ──────────────────────────────────

    def start_swing(self) -> None:
        """Begin a fresh swing animation.  Caller is responsible
        for the cooldown gate (``Weapon.fire`` semantics)."""
        self._swing_timer = MELEE_SWING_LIFETIME
        self._enemies_hit.clear()

    @property
    def is_swinging(self) -> bool:
        return self._swing_timer > 0.0

    def already_hit(self, enemy) -> bool:
        return id(enemy) in self._enemies_hit

    def mark_hit(self, enemy) -> None:
        self._enemies_hit.add(id(enemy))


# Backwards-compat alias kept for older imports.  The persistent-
# blade design subsumes the previous per-swing sprite; ``MeleeSwing``
# remains exposed so any external import doesn't break.
MeleeSwing = MeleeBlade
