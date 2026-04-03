"""Lightning warp zone — periodic lightning bolts from every direction."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from zones import ZoneID
from zones.zone_warp_base import WarpZoneBase, WARP_ZONE_WIDTH, WARP_ZONE_HEIGHT

if TYPE_CHECKING:
    from game_view import GameView

_BOLT_SPEED = 650.0        # px/s (same as alien laser)
_BOLT_DAMAGE = 20
_BOLT_INTERVAL_MIN = 0.5   # seconds between volleys
_BOLT_INTERVAL_MAX = 2.0
_BOLTS_PER_VOLLEY_MIN = 8
_BOLTS_PER_VOLLEY_MAX = 15
_BOLT_WIDTH = 3.0
_BOLT_LIFETIME = 1.5       # seconds before despawn


class LightningBolt:
    """A fast-moving lightning projectile."""
    def __init__(self, x: float, y: float, dx: float, dy: float) -> None:
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy
        self.age: float = 0.0
        self.dead: bool = False
        self.hit: bool = False
        # Generate jagged path segments for visual
        self.segments: list[tuple[float, float]] = self._gen_segments()

    def _gen_segments(self) -> list[tuple[float, float]]:
        """Generate offset points for jagged lightning appearance."""
        pts = [(0.0, 0.0)]
        length = 80.0
        seg_count = 6
        perp_x = -self.dy
        perp_y = self.dx
        for i in range(1, seg_count + 1):
            frac = i / seg_count
            jitter = random.uniform(-15, 15)
            pts.append((
                self.dx * length * frac + perp_x * jitter,
                self.dy * length * frac + perp_y * jitter,
            ))
        return pts

    def update(self, dt: float) -> None:
        self.x += self.dx * _BOLT_SPEED * dt
        self.y += self.dy * _BOLT_SPEED * dt
        self.age += dt
        if (self.age > _BOLT_LIFETIME or
                self.x < -100 or self.x > WARP_ZONE_WIDTH + 100 or
                self.y < -100 or self.y > WARP_ZONE_HEIGHT + 100):
            self.dead = True

    def draw(self) -> None:
        alpha = max(40, int(255 * (1.0 - self.age / _BOLT_LIFETIME)))
        for i in range(len(self.segments) - 1):
            x1 = self.x + self.segments[i][0]
            y1 = self.y + self.segments[i][1]
            x2 = self.x + self.segments[i + 1][0]
            y2 = self.y + self.segments[i + 1][1]
            arcade.draw_line(x1, y1, x2, y2, (180, 200, 255, alpha), _BOLT_WIDTH)
            # Bright core
            arcade.draw_line(x1, y1, x2, y2, (255, 255, 255, alpha // 2), 1)


class LightningWarpZone(WarpZoneBase):
    zone_id = ZoneID.WARP_LIGHTNING

    def __init__(self) -> None:
        super().__init__()
        self._bolts: list[LightningBolt] = []
        self._volley_timer: float = random.uniform(_BOLT_INTERVAL_MIN, _BOLT_INTERVAL_MAX)
        self._warning_lines: list[tuple[float, float, float, float]] = []
        self._warning_timer: float = 0.0
        self._pending_bolts: list[tuple[float, float, float, float]] = []

    def setup(self, gv: GameView) -> None:
        super().setup(gv)
        self._bolts = []
        self._volley_timer = random.uniform(_BOLT_INTERVAL_MIN, _BOLT_INTERVAL_MAX)

    def teardown(self, gv: GameView) -> None:
        super().teardown(gv)
        self._bolts.clear()

    def _update_hazards(self, gv: GameView, dt: float) -> None:
        from constants import SHIP_RADIUS

        # Warning phase: show faint lines before bolts arrive
        if self._warning_timer > 0:
            self._warning_timer -= dt
            if self._warning_timer <= 0:
                # Warning expired — fire the pending bolts
                for sx, sy, dx, dy in self._pending_bolts:
                    self._bolts.append(LightningBolt(sx, sy, dx, dy))
                self._pending_bolts.clear()
                self._warning_lines.clear()

        # Spawn volleys
        self._volley_timer -= dt
        if self._volley_timer <= 0 and self._warning_timer <= 0:
            self._volley_timer = random.uniform(_BOLT_INTERVAL_MIN, _BOLT_INTERVAL_MAX)
            count = random.randint(_BOLTS_PER_VOLLEY_MIN, _BOLTS_PER_VOLLEY_MAX)
            px, py = gv.player.center_x, gv.player.center_y
            self._pending_bolts.clear()
            self._warning_lines.clear()
            for _ in range(count):
                edge = random.choice(["top", "bottom", "left", "right"])
                if edge == "top":
                    sx = random.uniform(0, WARP_ZONE_WIDTH)
                    sy = WARP_ZONE_HEIGHT + 50
                elif edge == "bottom":
                    sx = random.uniform(0, WARP_ZONE_WIDTH)
                    sy = -50
                elif edge == "left":
                    sx = -50
                    sy = random.uniform(0, WARP_ZONE_HEIGHT)
                else:
                    sx = WARP_ZONE_WIDTH + 50
                    sy = random.uniform(0, WARP_ZONE_HEIGHT)
                dx = px - sx + random.uniform(-200, 200)
                dy = py - sy + random.uniform(-200, 200)
                dist = math.hypot(dx, dy)
                if dist > 0:
                    dx /= dist
                    dy /= dist
                self._pending_bolts.append((sx, sy, dx, dy))
                # Warning line from source toward player
                self._warning_lines.append((sx, sy, sx + dx * 300, sy + dy * 300))
            self._warning_timer = 0.5  # 0.5s warning

        # Update bolts and check player hits
        for bolt in self._bolts:
            bolt.update(dt)
            if not bolt.hit and not bolt.dead:
                dist = math.hypot(bolt.x - gv.player.center_x,
                                  bolt.y - gv.player.center_y)
                if dist < SHIP_RADIUS + 12:
                    bolt.hit = True
                    gv._apply_damage_to_player(_BOLT_DAMAGE)
                    gv._trigger_shake()

        self._bolts = [b for b in self._bolts if not b.dead]

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        # Warning lines (faint pulsing before strike)
        if self._warning_timer > 0:
            pulse = abs(math.sin(self._warning_timer * 12.0))
            alpha = int(60 + 80 * pulse)
            for x1, y1, x2, y2 in self._warning_lines:
                arcade.draw_line(x1, y1, x2, y2, (255, 255, 100, alpha), 2)
        for bolt in self._bolts:
            bolt.draw()
