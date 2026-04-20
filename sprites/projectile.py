"""Projectile and Weapon classes."""
from __future__ import annotations

import math
from typing import Optional

import arcade


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
        self._speed: float = math.hypot(self._vx, self._vy)  # precomputed

    def update_projectile(self, dt: float) -> None:
        self.center_x += self._vx * dt
        self.center_y += self._vy * dt
        self._dist_travelled += self._speed * dt
        # Despawn when range exhausted.  Previously also checked the
        # projectile had left the WORLD_WIDTH × WORLD_HEIGHT box, but
        # those are Zone 1 dimensions (6400) — Zone 2 is 9600 × 9600,
        # so shots fired from x > 6400 were killed on the first tick,
        # which is why the basic laser + mining beam looked like they
        # couldn't fire beyond the shield once the player crossed
        # into the expanded Nebula area.  The range check below
        # already caps every projectile (max 1200 px for basic
        # laser) so the world-bounds gate was only a defensive
        # backstop and is safe to drop.
        if self._dist_travelled >= self._max_dist:
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
        # Sound throttle: cap sound creation rate to reduce media-player stutter
        self._snd_min_interval: float = max(0.15, cooldown)
        self._snd_cd: float = 0.0

    def update(self, dt: float) -> None:
        self._timer = max(0.0, self._timer - dt)
        self._snd_cd = max(0.0, self._snd_cd - dt)

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
        if self._snd_cd <= 0.0:
            arcade.play_sound(self._sound, volume=0.45)
            self._snd_cd = self._snd_min_interval
        return Projectile(
            self._texture, spawn_x, spawn_y, heading,
            self._proj_speed, self._max_range, self._proj_scale,
            mines_rock=self.mines_rock,
            damage=self.damage,
        )
