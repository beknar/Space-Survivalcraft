"""Explosion animation, HitSpark, and FireSpark visual effects."""
from __future__ import annotations

import math
import random

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


class _FireParticle:
    """A single fire particle that flies outward and fades."""

    __slots__ = ("x", "y", "vx", "vy", "age", "lifetime", "size")

    def __init__(self, x: float, y: float, angle: float, speed: float,
                 lifetime: float, size: float) -> None:
        self.x = x
        self.y = y
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.age: float = 0.0
        self.lifetime = lifetime
        self.size = size


class FireSpark:
    """Spray of fire particles emitted when the player takes damage.

    Creates PARTICLE_COUNT small particles that fly outward from the
    impact point, transitioning from bright yellow to dark red over their
    lifespan.
    """

    PARTICLE_COUNT: int = 12
    DURATION: float = 0.35
    MIN_SPEED: float = 60.0
    MAX_SPEED: float = 180.0
    MIN_SIZE: float = 2.0
    MAX_SIZE: float = 5.0

    def __init__(self, x: float, y: float) -> None:
        self.dead: bool = False
        self._particles: list[_FireParticle] = []
        for _ in range(self.PARTICLE_COUNT):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(self.MIN_SPEED, self.MAX_SPEED)
            lifetime = random.uniform(self.DURATION * 0.5, self.DURATION)
            size = random.uniform(self.MIN_SIZE, self.MAX_SIZE)
            self._particles.append(_FireParticle(x, y, angle, speed, lifetime, size))

    def update(self, dt: float) -> None:
        alive = False
        for p in self._particles:
            p.age += dt
            if p.age < p.lifetime:
                p.x += p.vx * dt
                p.y += p.vy * dt
                alive = True
        if not alive:
            self.dead = True

    def draw(self) -> None:
        for p in self._particles:
            if p.age >= p.lifetime:
                continue
            t = p.age / p.lifetime  # 0→1
            alpha = int(255 * (1.0 - t))
            # Yellow → Orange → Red transition
            r = 255
            g = int(255 * (1.0 - t * 0.85))  # 255→38
            b = int(80 * (1.0 - t))           # 80→0
            size = p.size * (1.0 - t * 0.5)
            arcade.draw_circle_filled(p.x, p.y, size, (r, g, b, alpha))
