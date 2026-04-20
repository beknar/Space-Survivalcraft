"""Iron asteroid sprite."""
from __future__ import annotations

import random

import arcade

from constants import ASTEROID_HP


class IronAsteroid(arcade.Sprite):
    """A minable asteroid containing iron ore.

    - 100 HP; only the Mining Beam deals damage.
    - Yields 10 iron when destroyed.
    - Spins slowly at a randomised rate.
    """

    # Hit-shake constants
    _SHAKE_DURATION: float = 0.20   # seconds the asteroid shakes after a hit
    _SHAKE_AMP: float = 4.0         # max pixel offset during shake

    def __init__(self, texture: arcade.Texture, x: float, y: float) -> None:
        super().__init__(path_or_texture=texture, scale=1.0)
        self.center_x = x
        self.center_y = y
        self._base_x: float = x     # home position; shake offsets from here
        self._base_y: float = y
        self.hp: int = ASTEROID_HP
        # Each asteroid spins at a unique rate for visual variety
        self._rot_speed: float = random.uniform(8.0, 30.0) * random.choice((-1, 1))
        # Hit-shake state
        self._hit_timer: float = 0.0

    def update_asteroid(self, dt: float) -> None:
        self.angle = (self.angle + self._rot_speed * dt) % 360
        # Shake: while hit timer is active, jitter position around base.
        # For the far more common idle case we skip the ``center_x = …``
        # self-assignment — writing ``center_x`` on an arcade.Sprite
        # triggers spatial-hash bucket rebuilds every frame (profile
        # showed 13500 spatial_hash.add calls / 180 frames = 75/frame,
        # one per stationary iron asteroid).
        if self._hit_timer > 0.0:
            prev = self._hit_timer
            self._hit_timer = max(0.0, self._hit_timer - dt)
            t = self._hit_timer / self._SHAKE_DURATION   # 1->0
            amp = self._SHAKE_AMP * t
            self.center_x = self._base_x + random.uniform(-amp, amp)
            self.center_y = self._base_y + random.uniform(-amp, amp)
            if self._hit_timer == 0.0 and prev > 0.0:
                # Snap back to base exactly once so the spatial hash
                # lands at the canonical position.
                self.center_x = self._base_x
                self.center_y = self._base_y
                self.color = (255, 255, 255, 255)   # restore normal tint

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        self._hit_timer = self._SHAKE_DURATION   # start shake
        # Flash orange-red on hit
        self.color = (255, 140, 60, 255)
