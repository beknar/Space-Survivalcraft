"""Gas cloud warp zone — maze of damaging gaseous clouds."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade
from PIL import Image as PILImage, ImageDraw, ImageFilter

from zones import ZoneID
from zones.zone_warp_base import WarpZoneBase, WARP_ZONE_WIDTH, WARP_ZONE_HEIGHT

if TYPE_CHECKING:
    from game_view import GameView

_CLOUD_DAMAGE = 30
_CLOUD_COOLDOWN = 1.0      # seconds between damage ticks
_CLOUD_RADIUS = 80.0       # collision radius
_CLOUD_COUNT = 40           # number of clouds in the maze
_CLOUD_SIZE = 160           # texture size


def _generate_cloud_texture() -> arcade.Texture:
    """Procedurally generate a green-purple gas cloud texture."""
    size = _CLOUD_SIZE
    img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    for _ in range(40):
        r = random.gauss(size * 0.2, size * 0.1)
        r = max(4, min(size * 0.35, r))
        ox = random.gauss(0, size * 0.1)
        oy = random.gauss(0, size * 0.1)
        green = random.randint(80, 180)
        red = random.randint(60, 140)
        blue = random.randint(40, 120)
        alpha = random.randint(20, 50)
        draw.ellipse(
            [int(cx + ox - r), int(cy + oy - r),
             int(cx + ox + r), int(cy + oy + r)],
            fill=(red, green, blue, alpha))
    img = img.filter(ImageFilter.GaussianBlur(radius=4))
    return arcade.Texture(img)


class GasCloud(arcade.Sprite):
    def __init__(self, texture: arcade.Texture, x: float, y: float) -> None:
        super().__init__(path_or_texture=texture, scale=1.0)
        self.center_x = x
        self.center_y = y


class GasCloudWarpZone(WarpZoneBase):
    zone_id = ZoneID.WARP_GAS

    def __init__(self) -> None:
        super().__init__()
        self._clouds: arcade.SpriteList = arcade.SpriteList()
        self._cloud_tex: arcade.Texture | None = None
        self._damage_cd: float = 0.0

    def setup(self, gv: GameView) -> None:
        super().setup(gv)
        if self._cloud_tex is None:
            self._cloud_tex = _generate_cloud_texture()
        self._clouds = arcade.SpriteList()
        self._damage_cd = 0.0
        # Generate maze-like cloud layout (grid with gaps)
        margin = 150
        cols = 5
        rows = 12
        spacing_x = (WARP_ZONE_WIDTH - margin * 2) / cols
        spacing_y = (WARP_ZONE_HEIGHT - margin * 2) / rows
        for row in range(rows):
            for col in range(cols):
                # Leave gaps for navigation (skip ~40% of positions)
                if random.random() < 0.4:
                    continue
                x = margin + col * spacing_x + random.uniform(-30, 30)
                y = margin + row * spacing_y + random.uniform(-30, 30)
                x = max(100, min(WARP_ZONE_WIDTH - 100, x))
                y = max(100, min(WARP_ZONE_HEIGHT - 100, y))
                self._clouds.append(GasCloud(self._cloud_tex, x, y))

    def teardown(self, gv: GameView) -> None:
        super().teardown(gv)
        self._clouds.clear()

    def _update_hazards(self, gv: GameView, dt: float) -> None:
        self._damage_cd = max(0.0, self._damage_cd - dt)
        if self._damage_cd > 0.0:
            return
        # Check if player is inside any cloud
        px, py = gv.player.center_x, gv.player.center_y
        for cloud in self._clouds:
            dist = math.hypot(px - cloud.center_x, py - cloud.center_y)
            if dist < _CLOUD_RADIUS:
                gv._apply_damage_to_player(_CLOUD_DAMAGE)
                gv._trigger_shake()
                gv._flash_game_msg("Toxic gas! -30 damage", 1.0)
                self._damage_cd = _CLOUD_COOLDOWN
                break

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        self._clouds.draw()
