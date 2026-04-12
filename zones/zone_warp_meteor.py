"""Meteor warp zone — fast meteors raining from the top."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from zones import ZoneID
from zones.zone_warp_base import WarpZoneBase, WARP_ZONE_WIDTH, WARP_ZONE_HEIGHT

if TYPE_CHECKING:
    from game_view import GameView

_METEOR_SPEED = 350.0      # px/s
_METEOR_HP = 200           # 2x iron asteroid HP
_METEOR_DAMAGE = 25        # collision damage to player
_METEOR_SPAWN_RATE = 0.15  # seconds between spawns (rapid)
_METEOR_RADIUS = 30.0
_NEAR_MISS_DIST = 100.0    # screen shake on close pass


class Meteor(arcade.Sprite):
    def __init__(self, texture: arcade.Texture, x: float, y: float,
                 vx: float = 0.0, vy: float = -_METEOR_SPEED) -> None:
        super().__init__(path_or_texture=texture, scale=0.8)
        self.center_x = x
        self.center_y = y
        self.hp: int = _METEOR_HP
        self.angle = random.uniform(0, 360)
        self._spin: float = random.uniform(-60, 60)
        self._vx: float = vx
        self._vy: float = vy

    def update_meteor(self, dt: float) -> None:
        self.center_x += self._vx * dt
        self.center_y += self._vy * dt
        self.angle = (self.angle + self._spin * dt) % 360

    def take_damage(self, amount: int) -> None:
        self.hp -= amount


class MeteorWarpZone(WarpZoneBase):
    zone_id = ZoneID.WARP_METEOR

    def __init__(self) -> None:
        super().__init__()
        self._meteors: arcade.SpriteList = arcade.SpriteList()
        self._meteor_tex: arcade.Texture | None = None
        self._spawn_timer: float = 0.0

    def setup(self, gv: GameView) -> None:
        super().setup(gv)
        import os
        _HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(
            _HERE, "assets", "kenney space combat assets",
            "Space Shooter Redux", "PNG", "Meteors", "meteorBrown_big4.png")
        self._meteor_tex = arcade.load_texture(path)
        self._meteors = arcade.SpriteList()
        self._spawn_timer = 0.0

    def teardown(self, gv: GameView) -> None:
        super().teardown(gv)
        self._meteors.clear()

    def _update_hazards(self, gv: GameView, dt: float) -> None:
        from sprites.explosion import HitSpark
        from constants import SHIP_RADIUS, SHIP_COLLISION_COOLDOWN

        # Spawn meteors from multiple directions
        self._spawn_timer += dt
        if self._spawn_timer >= _METEOR_SPAWN_RATE:
            self._spawn_timer -= _METEOR_SPAWN_RATE
            edge = random.choices(["top", "left", "right", "bottom"],
                                  weights=[60, 15, 15, 10])[0]
            if edge == "top":
                x = random.uniform(100, WARP_ZONE_WIDTH - 100)
                y = WARP_ZONE_HEIGHT + 40
                vx = random.uniform(-40, 40)
                vy = -_METEOR_SPEED
            elif edge == "left":
                x = -40
                y = random.uniform(100, WARP_ZONE_HEIGHT - 100)
                vx = _METEOR_SPEED
                vy = random.uniform(-60, 60)
            elif edge == "right":
                x = WARP_ZONE_WIDTH + 40
                y = random.uniform(100, WARP_ZONE_HEIGHT - 100)
                vx = -_METEOR_SPEED
                vy = random.uniform(-60, 60)
            else:  # bottom
                x = random.uniform(100, WARP_ZONE_WIDTH - 100)
                y = -40
                vx = random.uniform(-40, 40)
                vy = _METEOR_SPEED
            self._meteors.append(Meteor(self._meteor_tex, x, y, vx, vy))

        # Update meteors
        for m in list(self._meteors):
            m.update_meteor(dt)
            if (m.center_y < -80 or m.center_y > WARP_ZONE_HEIGHT + 80 or
                    m.center_x < -80 or m.center_x > WARP_ZONE_WIDTH + 80):
                m.remove_from_sprite_lists()
                continue
            # Player collision
            dist = math.hypot(m.center_x - gv.player.center_x,
                              m.center_y - gv.player.center_y)
            if dist < _METEOR_RADIUS + SHIP_RADIUS:
                if gv.player._collision_cd <= 0.0:
                    gv._apply_damage_to_player(_METEOR_DAMAGE)
                    gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                    gv._trigger_shake()
            # Near-miss shake (close pass without hit)
            elif dist < _NEAR_MISS_DIST and gv.player._collision_cd <= 0.0:
                gv._shake_amp = 3.0
                gv._shake_timer = 0.1

        # Player projectile hits (mining beam only)
        for proj in list(gv.projectile_list):
            if not proj.mines_rock:
                continue
            for m in list(self._meteors):
                dist = math.hypot(proj.center_x - m.center_x,
                                  proj.center_y - m.center_y)
                if dist < _METEOR_RADIUS + 10:
                    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    m.take_damage(int(proj.damage))
                    if m.hp <= 0:
                        gv._spawn_explosion(m.center_x, m.center_y)
                        m.remove_from_sprite_lists()
                    break

    def get_minimap_objects(self):
        return self._meteors, arcade.SpriteList()

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        self._meteors.draw()
