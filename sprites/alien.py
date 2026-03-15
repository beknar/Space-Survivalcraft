"""Small alien ship AI and sprite."""
from __future__ import annotations

import math
import random
from typing import Optional

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    ALIEN_HP, ALIEN_SCALE, ALIEN_RADIUS, ALIEN_SPEED,
    ALIEN_PATROL_RADIUS_MIN, ALIEN_PATROL_RADIUS_MAX,
    ALIEN_DETECT_DIST, ALIEN_LASER_DAMAGE, ALIEN_LASER_RANGE,
    ALIEN_LASER_SPEED, ALIEN_FIRE_COOLDOWN,
    ALIEN_BOUNCE, ALIEN_VEL_DAMPING, ALIEN_COL_COOLDOWN,
    ALIEN_AVOIDANCE_RADIUS, ALIEN_AVOIDANCE_FORCE, ALIEN_BUMP_FLASH,
    ASTEROID_RADIUS,
)
from sprites.projectile import Projectile


class SmallAlienShip(arcade.Sprite):
    """Scout-class enemy.

    Behaviour
    ---------
    PATROL : circles a randomised point within ALIEN_PATROL_RADIUS of its spawn.
    PURSUE : when the player comes within ALIEN_DETECT_DIST px, locks on and
             chases the player, firing ALIEN_LASER_RANGE-px laser bolts.
    Returns to patrol when the player moves more than 3x ALIEN_DETECT_DIST away.
    """

    _STATE_PATROL = 0
    _STATE_PURSUE = 1

    def __init__(
        self,
        texture: arcade.Texture,
        laser_tex: arcade.Texture,
        x: float,
        y: float,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=ALIEN_SCALE)
        self.center_x = x
        self.center_y = y
        self.hp: int = ALIEN_HP

        self._state: int = self._STATE_PATROL
        self._home_x: float = x
        self._home_y: float = y
        self._patrol_r: float = random.uniform(
            ALIEN_PATROL_RADIUS_MIN, ALIEN_PATROL_RADIUS_MAX
        )
        self._tgt_x: float = x
        self._tgt_y: float = y
        self._pick_patrol_target()

        self._heading: float = random.uniform(0.0, 360.0)
        self.angle = self._heading
        # Stagger fire timers so ships don't all shoot simultaneously
        self._fire_cd: float = random.uniform(0.0, ALIEN_FIRE_COOLDOWN)
        self._laser_tex: arcade.Texture = laser_tex
        # Weapon hit-flash (red)
        self._hit_timer: float = 0.0
        # Physics velocity -- set by collision bounces, decays over time
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        # Collision cooldown -- prevents re-triggering bounce every frame
        self._col_cd: float = 0.0
        # Collision bump-flash (orange)
        self._bump_timer: float = 0.0

    def _pick_patrol_target(self) -> None:
        """Choose a fresh random point within the patrol radius."""
        angle = random.uniform(0.0, math.tau)
        r = random.uniform(0.0, self._patrol_r)
        self._tgt_x = max(50.0, min(WORLD_WIDTH - 50.0,
                                     self._home_x + math.cos(angle) * r))
        self._tgt_y = max(50.0, min(WORLD_HEIGHT - 50.0,
                                     self._home_y + math.sin(angle) * r))

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        self._hit_timer = 0.15   # flash red for 0.15 s

    def collision_bump(self) -> None:
        """Trigger an orange bump-flash when a physics collision is resolved."""
        self._bump_timer = ALIEN_BUMP_FLASH

    def update_alien(
        self,
        dt: float,
        player_x: float,
        player_y: float,
        asteroid_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
    ) -> Optional[Projectile]:
        """Advance AI + movement.  Returns a fired Projectile, or None."""

        # ── Physics velocity (bounce impulses from collisions) ──────────────
        damp = ALIEN_VEL_DAMPING ** (dt * 60.0)   # frame-rate independent
        self.vel_x *= damp
        self.vel_y *= damp
        if math.hypot(self.vel_x, self.vel_y) < 0.5:
            self.vel_x = self.vel_y = 0.0
        self.center_x += self.vel_x * dt
        self.center_y += self.vel_y * dt

        # ── Collision cooldown ──────────────────────────────────────────────
        if self._col_cd > 0.0:
            self._col_cd = max(0.0, self._col_cd - dt)

        dx = player_x - self.center_x
        dy = player_y - self.center_y
        dist = math.hypot(dx, dy)

        # ── State transitions ──────────────────────────────────────────────
        if self._state == self._STATE_PATROL:
            if dist <= ALIEN_DETECT_DIST:
                self._state = self._STATE_PURSUE
                self._fire_cd = 0.0   # fire immediately on first detection
        else:
            if dist > ALIEN_DETECT_DIST * 3.0:
                self._state = self._STATE_PATROL
                self._pick_patrol_target()

        # ── Movement ────────────────────────────────────────────────────────
        if self._state == self._STATE_PATROL:
            tdx = self._tgt_x - self.center_x
            tdy = self._tgt_y - self.center_y
            tdist = math.hypot(tdx, tdy)
            if tdist < 8.0:
                self._pick_patrol_target()
            else:
                step = min(ALIEN_SPEED * dt, tdist)
                self.center_x += tdx / tdist * step
                self.center_y += tdy / tdist * step
                self._heading = math.degrees(math.atan2(tdx, tdy)) % 360.0
                self.angle = self._heading

        else:  # PURSUE -- steer toward player with obstacle avoidance
            if dist > 1.0:
                # Base direction: straight toward player
                steer_x = dx / dist
                steer_y = dy / dist

                # Avoidance: push steering away from nearby asteroids
                for asteroid in asteroid_list:
                    adx = self.center_x - asteroid.center_x
                    ady = self.center_y - asteroid.center_y
                    adist = math.hypot(adx, ady)
                    thresh = ALIEN_RADIUS + ASTEROID_RADIUS + ALIEN_AVOIDANCE_RADIUS
                    if 0.0 < adist < thresh:
                        w = ALIEN_AVOIDANCE_FORCE * (1.0 - adist / thresh)
                        steer_x += adx / adist * w
                        steer_y += ady / adist * w

                # Avoidance: push steering away from other alien ships
                for other in alien_list:
                    if other is self:
                        continue
                    odx = self.center_x - other.center_x
                    ody = self.center_y - other.center_y
                    odist = math.hypot(odx, ody)
                    thresh = ALIEN_RADIUS * 2.0 + ALIEN_AVOIDANCE_RADIUS
                    if 0.0 < odist < thresh:
                        w = ALIEN_AVOIDANCE_FORCE * (1.0 - odist / thresh)
                        steer_x += odx / odist * w
                        steer_y += ody / odist * w

                # Normalise steering vector and advance
                smag = math.hypot(steer_x, steer_y)
                if smag > 0.001:
                    steer_x /= smag
                    steer_y /= smag
                    step = ALIEN_SPEED * dt
                    self.center_x += steer_x * step
                    self.center_y += steer_y * step
                    self._heading = math.degrees(
                        math.atan2(steer_x, steer_y)
                    ) % 360.0
                    self.angle = self._heading

        # ── Colour tint (weapon hit = red, collision bump = orange) ─────────
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = (
                (255, 80, 80, 255) if self._hit_timer > 0.0
                else ((255, 160, 50, 255) if self._bump_timer > 0.0
                      else (255, 255, 255, 255))
            )
        elif self._bump_timer > 0.0:
            self._bump_timer = max(0.0, self._bump_timer - dt)
            self.color = (
                (255, 160, 50, 255) if self._bump_timer > 0.0
                else (255, 255, 255, 255)
            )

        # ── Fire ────────────────────────────────────────────────────────────
        self._fire_cd = max(0.0, self._fire_cd - dt)
        if (
            self._state == self._STATE_PURSUE
            and dist <= ALIEN_LASER_RANGE
            and self._fire_cd <= 0.0
        ):
            self._fire_cd = ALIEN_FIRE_COOLDOWN
            return Projectile(
                self._laser_tex,
                self.center_x, self.center_y,
                self._heading,
                ALIEN_LASER_SPEED, ALIEN_LASER_RANGE,
                scale=0.5,
                damage=ALIEN_LASER_DAMAGE,
            )
        return None
