"""Zone 2 alien types — shielded, fast, gunner, rammer."""
from __future__ import annotations

import math
import random

import arcade

from constants import (
    ALIEN_HP, ALIEN_SCALE, ALIEN_SPEED, ALIEN_RADIUS,
    ALIEN_DETECT_DIST, ALIEN_LASER_DAMAGE, ALIEN_LASER_RANGE,
    ALIEN_LASER_SPEED, ALIEN_FIRE_COOLDOWN, ALIEN_STANDOFF_DIST,
    ALIEN_VEL_DAMPING, ALIEN_BUMP_FLASH,
    ALIEN_STUCK_TIME, ALIEN_STUCK_DIST,
    Z2_SHIELDED_SHIELD, Z2_FAST_SPEED, Z2_RAMMER_HP, Z2_RAMMER_SHIELD,
    WORLD_WIDTH, WORLD_HEIGHT,
)
from sprites.projectile import Projectile

# Crop regions for each alien type from Ship.png (top row)
ALIEN_CROPS = {
    "shielded": (883, 356, 1460, 815),   # col 2
    "fast":     (1498, 306, 1883, 793),   # col 3
    "gunner":   (1911, 336, 2427, 900),   # col 4
    "rammer":   (2463, 332, 2838, 900),   # col 5
}


class Zone2Alien(arcade.Sprite):
    """Base class for Zone 2 alien variants.

    Shares the core PATROL/PURSUE AI from SmallAlienShip but supports
    variant-specific overrides for shields, speed, guns, and behaviour.
    """

    _STATE_PATROL = 0
    _STATE_PURSUE = 1

    def __init__(
        self,
        texture: arcade.Texture,
        laser_tex: arcade.Texture,
        x: float, y: float,
        *,
        hp: int = ALIEN_HP,
        shields: int = 0,
        speed: float = ALIEN_SPEED,
        guns: int = 1,
        has_guns: bool = True,
        world_w: float = WORLD_WIDTH,
        world_h: float = WORLD_HEIGHT,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=ALIEN_SCALE)
        self.center_x = x
        self.center_y = y
        self.hp: int = hp
        self.max_hp: int = hp
        self.shields: int = shields
        self.max_shields: int = shields
        self._speed: float = speed
        self._guns: int = guns
        self._has_guns: bool = has_guns
        self._world_w = world_w
        self._world_h = world_h

        self._state: int = self._STATE_PATROL
        self._home_x: float = x
        self._home_y: float = y
        self._patrol_r: float = random.uniform(100.0, 150.0)
        self._tgt_x: float = x
        self._tgt_y: float = y
        self._pick_patrol_target()

        self._heading: float = random.uniform(0.0, 360.0)
        self.angle = self._heading
        self._fire_cd: float = random.uniform(0.0, ALIEN_FIRE_COOLDOWN)
        self._laser_tex: arcade.Texture = laser_tex

        self._hit_timer: float = 0.0
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        self._col_cd: float = 0.0
        self._bump_timer: float = 0.0
        self._stuck_check_x: float = x
        self._stuck_check_y: float = y
        self._stuck_timer: float = 0.0
        self._orbit_dir: int = random.choice((-1, 1))

    def _pick_patrol_target(self) -> None:
        angle = random.uniform(0.0, math.tau)
        r = random.uniform(0.0, self._patrol_r)
        self._tgt_x = max(50.0, min(self._world_w - 50.0,
                                     self._home_x + math.cos(angle) * r))
        self._tgt_y = max(50.0, min(self._world_h - 50.0,
                                     self._home_y + math.sin(angle) * r))

    def alert(self) -> None:
        if self._state == self._STATE_PATROL:
            self._state = self._STATE_PURSUE
            self._fire_cd = 0.0

    def take_damage(self, amount: int) -> None:
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp -= amount
        self._hit_timer = 0.15

    def collision_bump(self) -> None:
        self._bump_timer = ALIEN_BUMP_FLASH

    def update_alien(
        self,
        dt: float,
        player_x: float,
        player_y: float,
        asteroid_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
    ) -> list[Projectile]:
        """Advance AI. Returns list of fired projectiles."""
        fired: list[Projectile] = []

        # Physics velocity
        damp = ALIEN_VEL_DAMPING ** (dt * 60.0)
        self.vel_x *= damp
        self.vel_y *= damp
        if math.hypot(self.vel_x, self.vel_y) < 0.5:
            self.vel_x = self.vel_y = 0.0
        self.center_x += self.vel_x * dt
        self.center_y += self.vel_y * dt

        if self._col_cd > 0.0:
            self._col_cd = max(0.0, self._col_cd - dt)

        dx = player_x - self.center_x
        dy = player_y - self.center_y
        dist = math.hypot(dx, dy)

        # State transitions
        if self._state == self._STATE_PATROL:
            if dist <= ALIEN_DETECT_DIST:
                self._state = self._STATE_PURSUE
                self._fire_cd = 0.0
        else:
            if dist > ALIEN_DETECT_DIST * 3.0:
                self._state = self._STATE_PATROL
                self._pick_patrol_target()

        # Movement
        self._move(dt, player_x, player_y, dist, dx, dy, asteroid_list, alien_list)

        # Stuck detection
        self._stuck_timer += dt
        if self._stuck_timer >= ALIEN_STUCK_TIME:
            moved = math.hypot(self.center_x - self._stuck_check_x,
                               self.center_y - self._stuck_check_y)
            if moved < ALIEN_STUCK_DIST:
                self._pick_patrol_target()
            self._stuck_check_x = self.center_x
            self._stuck_check_y = self.center_y
            self._stuck_timer = 0.0

        # Color tint
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = (255, 80, 80, 255) if self._hit_timer > 0.0 else (255, 255, 255, 255)
        elif self._bump_timer > 0.0:
            self._bump_timer = max(0.0, self._bump_timer - dt)
            self.color = (255, 160, 50, 255) if self._bump_timer > 0.0 else (255, 255, 255, 255)

        # Fire
        if self._has_guns:
            self._fire_cd = max(0.0, self._fire_cd - dt)
            if (self._state == self._STATE_PURSUE
                    and dist <= ALIEN_LASER_RANGE
                    and self._fire_cd <= 0.0):
                self._fire_cd = ALIEN_FIRE_COOLDOWN
                for g in range(self._guns):
                    fired.append(Projectile(
                        self._laser_tex,
                        self.center_x, self.center_y,
                        self._heading,
                        ALIEN_LASER_SPEED, ALIEN_LASER_RANGE,
                        scale=0.5,
                        damage=ALIEN_LASER_DAMAGE,
                    ))

        return fired

    def _move(self, dt, player_x, player_y, dist, dx, dy,
              asteroid_list, alien_list) -> None:
        """Movement — patrol wanders; pursue orbits at standoff range."""
        if self._state == self._STATE_PATROL:
            tdx = self._tgt_x - self.center_x
            tdy = self._tgt_y - self.center_y
            tdist = math.hypot(tdx, tdy)
            if tdist < 8.0:
                self._pick_patrol_target()
            elif tdist > 0.001:
                step = min(self._speed * dt, tdist)
                self.center_x += tdx / tdist * step
                self.center_y += tdy / tdist * step
                self._heading = math.degrees(math.atan2(tdx / tdist, tdy / tdist)) % 360
                self.angle = self._heading
        else:
            if dist > 1.0:
                nx, ny = dx / dist, dy / dist
                # Ranged aliens orbit at standoff distance; face the player
                if self._has_guns:
                    perp_x = -ny * self._orbit_dir
                    perp_y = nx * self._orbit_dir
                    if dist > ALIEN_STANDOFF_DIST * 1.2:
                        radial = 1.0      # close in
                    elif dist < ALIEN_STANDOFF_DIST * 0.7:
                        radial = -0.6     # back off
                    else:
                        radial = 0.0      # hold distance
                    mx = nx * radial + perp_x * 0.9
                    my = ny * radial + perp_y * 0.9
                    mag = math.hypot(mx, my)
                    if mag > 0.001:
                        step = self._speed * dt
                        self.center_x += mx / mag * step
                        self.center_y += my / mag * step
                    # Always face the player
                    self._heading = math.degrees(math.atan2(nx, ny)) % 360
                    self.angle = self._heading
                else:
                    # Non-ranged aliens charge directly
                    step = self._speed * dt
                    self.center_x += nx * step
                    self.center_y += ny * step
                    self._heading = math.degrees(math.atan2(nx, ny)) % 360
                    self.angle = self._heading


class ShieldedAlien(Zone2Alien):
    """Alien with a 50-point shield (dashed blue rotating circle)."""

    def __init__(self, texture, laser_tex, x, y, **kw) -> None:
        super().__init__(texture, laser_tex, x, y,
                         shields=Z2_SHIELDED_SHIELD, **kw)
        self._shield_angle: float = 0.0

    def update_alien(self, dt, player_x, player_y, asteroid_list, alien_list):
        self._shield_angle = (self._shield_angle + 90.0 * dt) % 360
        return super().update_alien(dt, player_x, player_y, asteroid_list, alien_list)

    def draw_shield(self) -> None:
        if self.shields > 0:
            cx, cy = self.center_x, self.center_y
            r = ALIEN_RADIUS * ALIEN_SCALE * 10 + 15
            segments = 8
            arc = 360 / segments * 0.65
            for i in range(segments):
                start = self._shield_angle + i * (360 / segments)
                a1 = math.radians(start)
                a2 = math.radians(start + arc)
                x1 = cx + math.cos(a1) * r
                y1 = cy + math.sin(a1) * r
                x2 = cx + math.cos(a2) * r
                y2 = cy + math.sin(a2) * r
                arcade.draw_line(x1, y1, x2, y2, (80, 160, 255, 180), 2)


class FastAlien(Zone2Alien):
    """Fast alien that can sideslip to dodge player fire."""

    def __init__(self, texture, laser_tex, x, y, **kw) -> None:
        super().__init__(texture, laser_tex, x, y,
                         speed=Z2_FAST_SPEED, **kw)
        self._dodge_cd: float = 0.0

    def _move(self, dt, player_x, player_y, dist, dx, dy,
              asteroid_list, alien_list) -> None:
        super()._move(dt, player_x, player_y, dist, dx, dy,
                      asteroid_list, alien_list)
        # Occasional sudden sideslip dodge while in pursuit
        if self._state == self._STATE_PURSUE:
            self._dodge_cd -= dt
            if self._dodge_cd <= 0:
                self._dodge_cd = random.uniform(0.8, 2.0)
                # Flip orbit direction for unpredictable strafing
                self._orbit_dir *= -1


class GunnerAlien(Zone2Alien):
    """Alien with 2 guns."""

    def __init__(self, texture, laser_tex, x, y, **kw) -> None:
        super().__init__(texture, laser_tex, x, y, guns=2, **kw)


class RammerAlien(Zone2Alien):
    """Heavily shielded alien that rams the player. No guns."""

    def __init__(self, texture, laser_tex, x, y, **kw) -> None:
        super().__init__(texture, laser_tex, x, y,
                         hp=Z2_RAMMER_HP, shields=Z2_RAMMER_SHIELD,
                         has_guns=False, **kw)

    def _move(self, dt, player_x, player_y, dist, dx, dy,
              asteroid_list, alien_list) -> None:
        """Always charge at player when in pursuit."""
        if self._state == self._STATE_PURSUE and dist > 1.0:
            nx, ny = dx / dist, dy / dist
            # Move faster when pursuing (1.5x normal speed)
            step = self._speed * 1.5 * dt
            self.center_x += nx * step
            self.center_y += ny * step
            self._heading = math.degrees(math.atan2(nx, ny)) % 360
            self.angle = self._heading
        else:
            super()._move(dt, player_x, player_y, dist, dx, dy,
                          asteroid_list, alien_list)
