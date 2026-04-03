"""Copper asteroid sprite for Zone 2."""
from __future__ import annotations
import random
import arcade
from constants import COPPER_ASTEROID_HP


class CopperAsteroid(arcade.Sprite):
    _SHAKE_DURATION: float = 0.20
    _SHAKE_AMP: float = 4.0

    def __init__(self, texture: arcade.Texture, x: float, y: float) -> None:
        super().__init__(path_or_texture=texture, scale=1.0)
        self.center_x = x
        self.center_y = y
        self._base_x: float = x
        self._base_y: float = y
        self.hp: int = COPPER_ASTEROID_HP
        self._rot_speed: float = random.uniform(8.0, 30.0) * random.choice((-1, 1))
        self._hit_timer: float = 0.0

    def update_asteroid(self, dt: float) -> None:
        self.angle = (self.angle + self._rot_speed * dt) % 360
        if self._hit_timer > 0.0:
            prev = self._hit_timer
            self._hit_timer = max(0.0, self._hit_timer - dt)
            t = self._hit_timer / self._SHAKE_DURATION
            amp = self._SHAKE_AMP * t
            self.center_x = self._base_x + random.uniform(-amp, amp)
            self.center_y = self._base_y + random.uniform(-amp, amp)
            if self._hit_timer == 0.0 and prev > 0.0:
                self.color = (255, 255, 255, 255)
        else:
            self.center_x = self._base_x
            self.center_y = self._base_y

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        self._hit_timer = self._SHAKE_DURATION
        self.color = (255, 140, 60, 255)
