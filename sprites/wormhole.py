"""Wormhole sprite — blue gaseous cloud with rotating red spirals."""
from __future__ import annotations

import math
import random

import arcade
from PIL import Image as PILImage, ImageDraw, ImageFilter


_WORMHOLE_SIZE = 128  # texture size in pixels
_WORMHOLE_SCALE = 1.0
_SPIRAL_ARMS = 5
_SPIRAL_SPEED = 40.0  # degrees per second


def _generate_wormhole_texture() -> arcade.Texture:
    """Procedurally generate a blue gaseous cloud texture using PIL."""
    size = _WORMHOLE_SIZE
    img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    # Layer multiple translucent circles to create a gaseous cloud effect
    for _ in range(60):
        r = random.gauss(size * 0.2, size * 0.12)
        r = max(4, min(size * 0.4, r))
        ox = random.gauss(0, size * 0.12)
        oy = random.gauss(0, size * 0.12)
        # Blue-cyan palette with some purple variation
        blue = random.randint(140, 255)
        green = random.randint(60, 180)
        red = random.randint(20, 80)
        alpha = random.randint(15, 45)
        x0 = int(cx + ox - r)
        y0 = int(cy + oy - r)
        x1 = int(cx + ox + r)
        y1 = int(cy + oy + r)
        draw.ellipse([x0, y0, x1, y1], fill=(red, green, blue, alpha))

    # Bright core
    for _ in range(15):
        r = random.gauss(size * 0.06, size * 0.03)
        r = max(2, min(size * 0.15, r))
        ox = random.gauss(0, size * 0.04)
        oy = random.gauss(0, size * 0.04)
        draw.ellipse(
            [int(cx + ox - r), int(cy + oy - r),
             int(cx + ox + r), int(cy + oy + r)],
            fill=(180, 220, 255, random.randint(40, 80)))

    # Soft blur for gas effect
    img = img.filter(ImageFilter.GaussianBlur(radius=3))

    tex = arcade.Texture(img)
    return tex


class Wormhole(arcade.Sprite):
    """A wormhole rendered as a blue gaseous cloud with red rotating spirals."""

    # Shared texture across all instances
    _shared_tex: arcade.Texture | None = None

    def __init__(self, x: float, y: float) -> None:
        if Wormhole._shared_tex is None:
            Wormhole._shared_tex = _generate_wormhole_texture()
        super().__init__(path_or_texture=Wormhole._shared_tex,
                         scale=_WORMHOLE_SCALE)
        self.center_x = x
        self.center_y = y
        self._spiral_angle: float = random.uniform(0, 360)

    def update_wormhole(self, dt: float) -> None:
        """Advance the spiral rotation."""
        self._spiral_angle = (self._spiral_angle + _SPIRAL_SPEED * dt) % 360.0

    def draw_spirals(self) -> None:
        """Draw red spiral arms on top of the sprite texture."""
        cx, cy = self.center_x, self.center_y
        max_r = _WORMHOLE_SIZE * _WORMHOLE_SCALE * 0.45

        for arm in range(_SPIRAL_ARMS):
            base_angle = self._spiral_angle + arm * (360.0 / _SPIRAL_ARMS)
            # Draw spiral as a series of connected line segments
            prev_x, prev_y = cx, cy
            segments = 20
            for s in range(1, segments + 1):
                frac = s / segments
                r = max_r * frac
                # Spiral: angle increases with radius
                angle = math.radians(base_angle + frac * 180.0)
                px = cx + math.cos(angle) * r
                py = cy + math.sin(angle) * r
                # Fade alpha with distance from center
                alpha = int(200 * (1.0 - frac * 0.7))
                width = max(1.0, 2.5 * (1.0 - frac))
                arcade.draw_line(prev_x, prev_y, px, py,
                                 (255, 60, 60, alpha), width)
                prev_x, prev_y = px, py
