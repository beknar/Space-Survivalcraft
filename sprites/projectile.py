"""Projectile and Weapon classes."""
from __future__ import annotations

import math
from typing import Optional

import arcade

from constants import WORLD_WIDTH, WORLD_HEIGHT


class Projectile(arcade.Sprite):
    """A fired weapon projectile that travels in a straight line."""

    def __init__(
        self,
        texture: arcade.Texture,
        x: float,
        y: float,
        heading: float,
        speed: float,
        max_dist: float,
        scale: float = 1.0,
        mines_rock: bool = False,
        damage: float = 0.0,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=scale)
        self.center_x = x
        self.center_y = y
        self.angle = heading       # CW-positive compass heading
        rad = math.radians(heading)
        self._vx: float = math.sin(rad) * speed
        self._vy: float = math.cos(rad) * speed
        self._max_dist: float = max_dist
        self._dist_travelled: float = 0.0
        self.mines_rock: bool = mines_rock   # True for Mining Beam only
        self.damage: float = damage          # HP damage dealt on impact

    def update_projectile(self, dt: float) -> None:
        self.center_x += self._vx * dt
        self.center_y += self._vy * dt
        self._dist_travelled += math.hypot(self._vx, self._vy) * dt
        # Despawn when range exhausted or projectile leaves the world
        if (
            self._dist_travelled >= self._max_dist
            or self.center_x < 0 or self.center_x > WORLD_WIDTH
            or self.center_y < 0 or self.center_y > WORLD_HEIGHT
        ):
            self.remove_from_sprite_lists()


class Weapon:
    """Defines a weapon's stats and manages its fire cooldown."""

    def __init__(
        self,
        name: str,
        texture: arcade.Texture,
        sound: arcade.Sound,
        cooldown: float,
        damage: float,
        projectile_speed: float,
        max_range: float,
        proj_scale: float = 1.0,
        mines_rock: bool = False,
    ) -> None:
        self.name = name
        self._texture = texture
        self._sound = sound
        self.cooldown = cooldown
        self.damage = damage
        self._proj_speed = projectile_speed
        self._max_range = max_range
        self._proj_scale = proj_scale
        self.mines_rock = mines_rock
        self._timer: float = 0.0

    def update(self, dt: float) -> None:
        self._timer = max(0.0, self._timer - dt)

    def fire(
        self,
        spawn_x: float,
        spawn_y: float,
        heading: float,
    ) -> Optional[Projectile]:
        """Attempt to fire; returns a Projectile if off cooldown, else None."""
        if self._timer > 0.0:
            return None
        self._timer = self.cooldown
        arcade.play_sound(self._sound, volume=0.45)
        return Projectile(
            self._texture, spawn_x, spawn_y, heading,
            self._proj_speed, self._max_range, self._proj_scale,
            mines_rock=self.mines_rock,
            damage=self.damage,
        )
