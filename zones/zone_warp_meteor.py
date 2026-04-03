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

_METEOR_SPEED = 240.0      # px/s downward
_METEOR_HP = 200           # 2x iron asteroid HP
_METEOR_DAMAGE = 15        # collision damage to player
_METEOR_SPAWN_RATE = 0.4   # seconds between spawns
_METEOR_RADIUS = 30.0


class Meteor(arcade.Sprite):
    def __init__(self, texture: arcade.Texture, x: float, y: float) -> None:
        super().__init__(path_or_texture=texture, scale=0.8)
        self.center_x = x
        self.center_y = y
        self.hp: int = _METEOR_HP
        self.angle = random.uniform(0, 360)
        self._spin: float = random.uniform(-60, 60)

    def update_meteor(self, dt: float) -> None:
        self.center_y -= _METEOR_SPEED * dt
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
        from constants import BOSS_MONSTER_PNG  # just need os
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

        # Spawn new meteors from the top
        self._spawn_timer += dt
        if self._spawn_timer >= _METEOR_SPAWN_RATE:
            self._spawn_timer -= _METEOR_SPAWN_RATE
            x = random.uniform(100, WARP_ZONE_WIDTH - 100)
            m = Meteor(self._meteor_tex, x, WARP_ZONE_HEIGHT + 40)
            self._meteors.append(m)

        # Update meteors
        for m in list(self._meteors):
            m.update_meteor(dt)
            if m.center_y < -60:
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

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        self._meteors.draw()
