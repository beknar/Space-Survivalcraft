"""Gaseous hazard area for Zone 2."""
from __future__ import annotations
import math
import random
import arcade
from PIL import Image as PILImage, ImageDraw, ImageFilter
from constants import GAS_AREA_DAMAGE, GAS_AREA_SLOW


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
        alpha = random.randint(15, 40)
        draw.ellipse(
            [int(cx + ox - r), int(cy + oy - r),
             int(cx + ox + r), int(cy + oy + r)],
            fill=(red, green, blue, alpha))
    # Bright toxic core
    for _ in range(blob_count // 4):
        r = random.gauss(size * 0.05, size * 0.03)
        r = max(2, min(size * 0.1, r))
        ox = random.gauss(0, size * 0.08)
        oy = random.gauss(0, size * 0.08)
        draw.ellipse(
            [int(cx + ox - r), int(cy + oy - r),
             int(cx + ox + r), int(cy + oy + r)],
            fill=(180, 255, 80, random.randint(20, 50)))
    img = img.filter(ImageFilter.GaussianBlur(radius=max(2, size // 40)))
    return arcade.Texture(img)


class GasArea(arcade.Sprite):
    """A toxic gaseous cloud that damages and slows the player."""

    def __init__(self, texture: arcade.Texture, x: float, y: float,
                 size: int = 256) -> None:
        scale = size / texture.width if texture.width > 0 else 1.0
        super().__init__(path_or_texture=texture, scale=scale)
        self.center_x = x
        self.center_y = y
        self.radius: float = size / 2.0
        self._rot_speed: float = random.uniform(-5.0, 5.0)

    def update_gas(self, dt: float) -> None:
        self.angle = (self.angle + self._rot_speed * dt) % 360

    def contains_point(self, px: float, py: float) -> bool:
        return math.hypot(px - self.center_x, py - self.center_y) < self.radius
