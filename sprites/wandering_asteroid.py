"""Wandering magnetic asteroid for Zone 2."""
from __future__ import annotations
import math
import random
import arcade
from constants import (
    WANDERING_HP, WANDERING_SPEED, WANDERING_MAGNET_DIST,
    WANDERING_MAGNET_SPEED,
)


class WanderingAsteroid(arcade.Sprite):
    _SHAKE_DURATION: float = 0.20
    _SHAKE_AMP: float = 4.0

    def __init__(self, texture: arcade.Texture, x: float, y: float,
                 world_w: float = 6400, world_h: float = 6400) -> None:
        super().__init__(path_or_texture=texture, scale=1.0)
        self.center_x = x
        self.center_y = y
        self.hp: int = WANDERING_HP
        self._rot_speed: float = random.uniform(15.0, 45.0) * random.choice((-1, 1))
        self._hit_timer: float = 0.0
        self._world_w = world_w
        self._world_h = world_h
        # Wander direction
        self._wander_angle: float = random.uniform(0, math.tau)
        self._wander_timer: float = random.uniform(1.0, 3.0)
        self._attracted: bool = False
        self._repel_timer: float = 0.0  # post-collision magnet suppression

    def update_wandering(self, dt: float, player_x: float, player_y: float) -> None:
        self.angle = (self.angle + self._rot_speed * dt) % 360

        dx = player_x - self.center_x
        dy = player_y - self.center_y
        dist = math.hypot(dx, dy)

        if self._repel_timer > 0.0:
            self._repel_timer = max(0.0, self._repel_timer - dt)

        if dist < WANDERING_MAGNET_DIST and dist > 0 and self._repel_timer <= 0.0:
            # Magnetic attraction toward player
            nx, ny = dx / dist, dy / dist
            self.center_x += nx * WANDERING_MAGNET_SPEED * dt
            self.center_y += ny * WANDERING_MAGNET_SPEED * dt
            self._attracted = True
        else:
            self._attracted = False
            # Random wander
            self._wander_timer -= dt
            if self._wander_timer <= 0:
                self._wander_angle = random.uniform(0, math.tau)
                self._wander_timer = random.uniform(1.0, 3.0)
            self.center_x += math.cos(self._wander_angle) * WANDERING_SPEED * dt
            self.center_y += math.sin(self._wander_angle) * WANDERING_SPEED * dt

        # Clamp to world and bounce off edges
        margin = 50.0
        if self.center_x < margin:
            self.center_x = margin
            self._wander_angle = random.uniform(-math.pi/2, math.pi/2)
        elif self.center_x > self._world_w - margin:
            self.center_x = self._world_w - margin
            self._wander_angle = random.uniform(math.pi/2, 3*math.pi/2)
        if self.center_y < margin:
            self.center_y = margin
            self._wander_angle = random.uniform(0, math.pi)
        elif self.center_y > self._world_h - margin:
            self.center_y = self._world_h - margin
            self._wander_angle = random.uniform(math.pi, math.tau)

        # Hit shake
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            if self._hit_timer == 0.0:
                self.color = (255, 255, 255, 255)

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        self._hit_timer = self._SHAKE_DURATION
        self.color = (255, 140, 60, 255)
