"""Enemy spawner warp zone — 4 spawners producing alien ships."""
from __future__ import annotations

import math
import os
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    ALIEN_HP, ALIEN_SCALE, ALIEN_SPEED,
    ALIEN_LASER_DAMAGE, ALIEN_LASER_RANGE, ALIEN_LASER_SPEED,
    ALIEN_FIRE_COOLDOWN, SHIP_RADIUS, SHIP_COLLISION_COOLDOWN,
)
from zones import ZoneID
from zones.zone_warp_base import WarpZoneBase, WARP_ZONE_WIDTH, WARP_ZONE_HEIGHT
from sprites.projectile import Projectile

if TYPE_CHECKING:
    from game_view import GameView

_SPAWNER_HP = ALIEN_HP * 2          # 100 HP
_SPAWNER_RADIUS = 30.0
_SPAWN_INTERVAL = 15.0              # seconds between waves (was 30)
_SHIPS_PER_WAVE = 6                 # ships per spawner per wave (was 4)
_MINI_ALIEN_HP = ALIEN_HP // 2      # 25 HP
_MINI_FIRE_CD = 0.8                 # aggressive fire cooldown (was 1.5)


class EnemySpawnerWarpZone(WarpZoneBase):
    zone_id = ZoneID.WARP_ENEMY

    def __init__(self) -> None:
        super().__init__()
        self._spawners: arcade.SpriteList = arcade.SpriteList()
        self._spawner_hps: list[int] = []
        self._aliens: arcade.SpriteList = arcade.SpriteList()
        self._alien_projectiles: arcade.SpriteList = arcade.SpriteList()
        self._spawner_tex: arcade.Texture | None = None
        self._alien_tex: arcade.Texture | None = None
        self._alien_laser_tex: arcade.Texture | None = None
        self._spawn_timer: float = 2.0  # first wave after 2s (immediate pressure)
        self._spawner_fire_cd: list[float] = [0.0, 0.0, 0.0, 0.0]

    def setup(self, gv: GameView) -> None:
        super().setup(gv)
        _HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._spawner_tex = arcade.load_texture(os.path.join(
            _HERE, "assets", "kenney space combat assets",
            "Simple Space", "PNG", "Retina", "station_A.png"))
        self._alien_tex = arcade.load_texture(os.path.join(
            _HERE, "assets", "kenney space combat assets",
            "Simple Space", "PNG", "Retina", "enemy_A.png"))
        # Reuse alien laser texture from GameView
        self._alien_laser_tex = gv._alien_laser_tex

        self._spawners = arcade.SpriteList()
        self._spawner_hps = []
        self._aliens = arcade.SpriteList(use_spatial_hash=True)
        self._alien_projectiles = arcade.SpriteList()
        self._spawn_timer = 5.0

        # Place 4 spawners at equidistant points
        positions = [
            (WARP_ZONE_WIDTH * 0.25, WARP_ZONE_HEIGHT * 0.75),
            (WARP_ZONE_WIDTH * 0.75, WARP_ZONE_HEIGHT * 0.75),
            (WARP_ZONE_WIDTH * 0.25, WARP_ZONE_HEIGHT * 0.5),
            (WARP_ZONE_WIDTH * 0.75, WARP_ZONE_HEIGHT * 0.5),
        ]
        for sx, sy in positions:
            spawner = arcade.Sprite(path_or_texture=self._spawner_tex, scale=0.5)
            spawner.center_x = sx
            spawner.center_y = sy
            self._spawners.append(spawner)
            self._spawner_hps.append(_SPAWNER_HP)

    def teardown(self, gv: GameView) -> None:
        super().teardown(gv)
        self._spawners.clear()
        self._aliens.clear()
        self._alien_projectiles.clear()

    def _update_hazards(self, gv: GameView, dt: float) -> None:
        from sprites.explosion import HitSpark
        from sprites.projectile import Projectile

        # Spawn waves from alive spawners
        self._spawn_timer -= dt
        if self._spawn_timer <= 0:
            self._spawn_timer = _SPAWN_INTERVAL
            for i, spawner in enumerate(self._spawners):
                if self._spawner_hps[i] <= 0:
                    continue
                for _ in range(_SHIPS_PER_WAVE):
                    ax = spawner.center_x + random.uniform(-40, 40)
                    ay = spawner.center_y + random.uniform(-40, 40)
                    alien = _MiniAlien(self._alien_tex, self._alien_laser_tex, ax, ay)
                    self._aliens.append(alien)

        # Spawner turret fire (each spawner shoots at the player)
        px, py = gv.player.center_x, gv.player.center_y
        for i, spawner in enumerate(self._spawners):
            if self._spawner_hps[i] <= 0:
                continue
            self._spawner_fire_cd[i] = max(0.0, self._spawner_fire_cd[i] - dt)
            dist = math.hypot(px - spawner.center_x, py - spawner.center_y)
            if dist < 600 and self._spawner_fire_cd[i] <= 0.0:
                self._spawner_fire_cd[i] = 2.0
                dx = px - spawner.center_x
                dy = py - spawner.center_y
                if dist > 0:
                    heading = math.degrees(math.atan2(dx / dist, dy / dist)) % 360
                    self._alien_projectiles.append(Projectile(
                        self._alien_laser_tex,
                        spawner.center_x, spawner.center_y,
                        heading, ALIEN_LASER_SPEED, ALIEN_LASER_RANGE,
                        scale=0.6, damage=ALIEN_LASER_DAMAGE,
                    ))

        # Update mini aliens (aggressive pursue AI)
        for alien in list(self._aliens):
            proj = alien.update_mini(dt, px, py)
            if proj is not None:
                self._alien_projectiles.append(proj)

        # Alien projectile movement
        for proj in list(self._alien_projectiles):
            proj.update_projectile(dt)
            # Hit player
            dist = math.hypot(proj.center_x - px, proj.center_y - py)
            if dist < SHIP_RADIUS + 8:
                proj.remove_from_sprite_lists()
                gv._apply_damage_to_player(int(proj.damage))
                gv._trigger_shake()

        # Player projectiles vs aliens
        for proj in list(gv.projectile_list):
            if proj.mines_rock:
                continue
            for alien in list(self._aliens):
                dist = math.hypot(proj.center_x - alien.center_x,
                                  proj.center_y - alien.center_y)
                if dist < 20:
                    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    alien.hp -= int(proj.damage)
                    if alien.hp <= 0:
                        gv._spawn_explosion(alien.center_x, alien.center_y)
                        alien.remove_from_sprite_lists()
                    break

        # Player projectiles vs spawners
        for proj in list(gv.projectile_list):
            if proj.mines_rock:
                continue
            for i, spawner in enumerate(self._spawners):
                if self._spawner_hps[i] <= 0:
                    continue
                dist = math.hypot(proj.center_x - spawner.center_x,
                                  proj.center_y - spawner.center_y)
                if dist < _SPAWNER_RADIUS + 10:
                    gv.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    self._spawner_hps[i] -= int(proj.damage)
                    if self._spawner_hps[i] <= 0:
                        gv._spawn_explosion(spawner.center_x, spawner.center_y)
                        spawner.alpha = 80
                    break

        # Alien-player collision
        for alien in list(self._aliens):
            dist = math.hypot(alien.center_x - px, alien.center_y - py)
            if dist < 20 + SHIP_RADIUS and gv.player._collision_cd <= 0.0:
                gv._apply_damage_to_player(5)
                gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                gv._trigger_shake()

    def get_minimap_objects(self):
        return self._spawners, self._aliens

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        self._spawners.draw()
        self._aliens.draw()
        self._alien_projectiles.draw()


class _MiniAlien(arcade.Sprite):
    """Small alien with half HP, pursues and fires at player."""

    def __init__(self, texture: arcade.Texture, laser_tex: arcade.Texture,
                 x: float, y: float) -> None:
        super().__init__(path_or_texture=texture, scale=0.4)
        self.center_x = x
        self.center_y = y
        self.hp: int = _MINI_ALIEN_HP
        self._laser_tex = laser_tex
        self._fire_cd: float = random.uniform(0, _MINI_FIRE_CD)
        self._heading: float = random.uniform(0, 360)

    def update_mini(self, dt: float, px: float, py: float):
        """Simple pursue AI — move toward player and fire."""
        from sprites.projectile import Projectile

        dx = px - self.center_x
        dy = py - self.center_y
        dist = math.hypot(dx, dy)

        if dist > 1.0:
            nx, ny = dx / dist, dy / dist
            self.center_x += nx * ALIEN_SPEED * dt
            self.center_y += ny * ALIEN_SPEED * dt
            self._heading = math.degrees(math.atan2(nx, ny)) % 360
            self.angle = self._heading

        self._fire_cd = max(0.0, self._fire_cd - dt)
        if self._fire_cd <= 0.0 and dist <= ALIEN_LASER_RANGE:
            self._fire_cd = _MINI_FIRE_CD
            return Projectile(
                self._laser_tex,
                self.center_x, self.center_y,
                self._heading,
                ALIEN_LASER_SPEED, ALIEN_LASER_RANGE,
                scale=0.5,
                damage=ALIEN_LASER_DAMAGE,
            )
        return None
