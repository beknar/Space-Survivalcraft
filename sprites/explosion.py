"""Explosion animation and HitSpark visual effect."""
from __future__ import annotations

import arcade

from constants import EXPLOSION_FPS


class Explosion(arcade.Sprite):
    """One-shot explosion animation spawned when an asteroid is destroyed."""

    def __init__(
        self,
        frames: list[arcade.Texture],
        x: float,
        y: float,
        scale: float = 1.0,
    ) -> None:
        super().__init__(path_or_texture=frames[0], scale=scale)
        self.center_x = x
        self.center_y = y
        self._frames = frames
        self._frame_idx: int = 0
        self._timer: float = 0.0
        self._interval: float = 1.0 / EXPLOSION_FPS

    def update_explosion(self, dt: float) -> None:
        self._timer += dt
        if self._timer >= self._interval:
            self._timer -= self._interval
            self._frame_idx += 1
            if self._frame_idx >= len(self._frames):
                self.remove_from_sprite_lists()
                return
            self.texture = self._frames[self._frame_idx]


class HitSpark:
    """A brief expanding-ring flash drawn at an impact point.

    No texture required -- drawn with arcade primitives.
    Lasts DURATION seconds; ring expands from 0 to MAX_RADIUS and fades out.
    """

    DURATION: float = 0.18
    MAX_RADIUS: float = 28.0

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self._age: float = 0.0
        self.dead: bool = False

    def update(self, dt: float) -> None:
        self._age += dt
        if self._age >= self.DURATION:
            self.dead = True

    def draw(self) -> None:
        if self.dead:
            return
        t = self._age / self.DURATION          # 0 -> 1
        radius = self.MAX_RADIUS * t
        alpha = int(255 * (1.0 - t))           # fades out
        # Outer ring
        arcade.draw_circle_outline(
            self.x, self.y, radius,
            (255, 200, 80, alpha), border_width=3,
        )
        # Inner bright core (small filled circle, shrinks as t grows)
        core_r = self.MAX_RADIUS * 0.4 * (1.0 - t)
        if core_r > 1.0:
            arcade.draw_circle_filled(
                self.x, self.y, core_r,
                (255, 255, 180, alpha),
            )
