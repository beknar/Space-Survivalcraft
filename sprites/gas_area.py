"""Gaseous hazard area for Zone 2."""
from __future__ import annotations
import math
import random
import arcade
from PIL import Image as PILImage, ImageDraw, ImageFilter


def generate_gas_texture(size: int) -> arcade.Texture:
    """Generate a green-yellow toxic gas cloud texture."""
    img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    blob_count = max(20, size // 8)
    for _ in range(blob_count):
        r = random.gauss(size * 0.18, size * 0.1)
        r = max(4, min(size * 0.35, r))
        ox = random.gauss(0, size * 0.15)
        oy = random.gauss(0, size * 0.15)
        green = random.randint(120, 220)
        red = random.randint(80, 160)
        blue = random.randint(20, 80)
        alpha = random.randint(30, 70)
        draw.ellipse(
            [int(cx + ox - r), int(cy + oy - r),
             int(cx + ox + r), int(cy + oy + r)],
            fill=(red, green, blue, alpha))
    # Bright toxic core
    for _ in range(blob_count // 4):
        r = random.gauss(size * 0.08, size * 0.04)
        r = max(3, min(size * 0.15, r))
        ox = random.gauss(0, size * 0.06)
        oy = random.gauss(0, size * 0.06)
        draw.ellipse(
            [int(cx + ox - r), int(cy + oy - r),
             int(cx + ox + r), int(cy + oy + r)],
            fill=(180, 255, 80, random.randint(40, 90)))
    img = img.filter(ImageFilter.GaussianBlur(radius=max(3, size // 30)))
    # Apply circular alpha mask so edges are rounded, not square
    mask = PILImage.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse([0, 0, size - 1, size - 1], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, size // 20)))
    img.putalpha(PILImage.composite(img.getchannel("A"), PILImage.new("L", (size, size), 0), mask))
    return arcade.Texture(img)


class GasArea(arcade.Sprite):
    """A toxic gaseous cloud that damages and slows the player."""

    def __init__(self, texture: arcade.Texture, x: float, y: float,
                 size: int = 256, world_w: float = 6400, world_h: float = 6400,
                 mobile: bool = False) -> None:
        scale = size / texture.width if texture.width > 0 else 1.0
        super().__init__(path_or_texture=texture, scale=scale)
        self.center_x = x
        self.center_y = y
        self.radius: float = size / 2.0
        self._rot_speed: float = random.uniform(-5.0, 5.0)
        self._mobile: bool = mobile
        # Brownian motion: speed = half of small alien (120/2 = 60 px/s)
        self._drift_speed: float = 60.0 if mobile else 0.0
        angle = random.uniform(0, math.tau)
        self._drift_x: float = math.cos(angle) * self._drift_speed
        self._drift_y: float = math.sin(angle) * self._drift_speed
        self._brownian_timer: float = random.uniform(0.3, 1.0)
        self._world_w = world_w
        self._world_h = world_h

    def update_gas(self, dt: float) -> None:
        self.angle = (self.angle + self._rot_speed * dt) % 360
        if not self._mobile:
            return
        # Brownian motion: randomly change direction at intervals
        self._brownian_timer -= dt
        if self._brownian_timer <= 0:
            self._brownian_timer = random.uniform(0.3, 1.0)
            angle = random.uniform(0, math.tau)
            self._drift_x = math.cos(angle) * self._drift_speed
            self._drift_y = math.sin(angle) * self._drift_speed
        self.center_x += self._drift_x * dt
        self.center_y += self._drift_y * dt
        # Bounce off world edges
        margin = self.radius
        if self.center_x < margin:
            self.center_x = margin
            self._drift_x = abs(self._drift_x)
        elif self.center_x > self._world_w - margin:
            self.center_x = self._world_w - margin
            self._drift_x = -abs(self._drift_x)
        if self.center_y < margin:
            self.center_y = margin
            self._drift_y = abs(self._drift_y)
        elif self.center_y > self._world_h - margin:
            self.center_y = self._world_h - margin
            self._drift_y = -abs(self._drift_y)

    def contains_point(self, px: float, py: float) -> bool:
        return math.hypot(px - self.center_x, py - self.center_y) < self.radius
