"""Boss alien ship — end-game encounter with phased AI."""
from __future__ import annotations

import math

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BOSS_HP, BOSS_SHIELDS, BOSS_SHIELD_REGEN, BOSS_SHIELD_REGEN_P2,
    BOSS_SPEED, BOSS_SPEED_P2, BOSS_ROT_SPEED, BOSS_SCALE, BOSS_RADIUS,
    BOSS_CANNON_DAMAGE, BOSS_CANNON_COOLDOWN, BOSS_CANNON_SPEED,
    BOSS_CANNON_RANGE,
    BOSS_SPREAD_DAMAGE, BOSS_SPREAD_COOLDOWN, BOSS_SPREAD_SPEED,
    BOSS_SPREAD_RANGE, BOSS_SPREAD_COUNT, BOSS_SPREAD_ARC,
    BOSS_CHARGE_SPEED, BOSS_CHARGE_WINDUP,
    BOSS_CHARGE_DURATION, BOSS_CHARGE_COOLDOWN,
    BOSS_PHASE2_HP, BOSS_PHASE3_HP,
    BOSS_DETECT_RANGE,
    ALIEN_AVOIDANCE_RADIUS, ALIEN_AVOIDANCE_FORCE,
    ASTEROID_RADIUS,
)
from sprites.projectile import Projectile


# AI phases
_PHASE1 = 1  # 100%-50% HP: main cannon + spread
_PHASE2 = 2  # 50%-25% HP: adds charge attack, faster, shield regen x2
_PHASE3 = 3  # <25% HP: enraged — cooldowns halved, no shield regen


class BossAlienShip(arcade.Sprite):
    """Boss-class enemy that targets the player's space station."""

    def __init__(
        self,
        texture: arcade.Texture,
        laser_tex: arcade.Texture,
        x: float,
        y: float,
        target_x: float,
        target_y: float,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=BOSS_SCALE)
        self.center_x = x
        self.center_y = y

        self.hp: int = BOSS_HP
        self.max_hp: int = BOSS_HP
        self.shields: float = BOSS_SHIELDS
        self.max_shields: int = BOSS_SHIELDS

        # Target: the Home Station position
        self._target_x: float = target_x
        self._target_y: float = target_y

        self._heading: float = 0.0
        self.angle = 0.0
        self._phase: int = _PHASE1

        # Physics velocity (from collision bounces)
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        self._col_cd: float = 0.0

        # Weapon cooldowns
        self._cannon_cd: float = 1.0  # slight delay before first shot
        self._spread_cd: float = 2.0
        self._charge_cd: float = BOSS_CHARGE_COOLDOWN
        self._laser_tex: arcade.Texture = laser_tex

        # Charge state
        self._charging: bool = False
        self._charge_windup: float = 0.0
        self._charge_timer: float = 0.0
        self._charge_dir_x: float = 0.0
        self._charge_dir_y: float = 0.0

        # Visual feedback
        self._hit_timer: float = 0.0
        self._bump_timer: float = 0.0

    @property
    def phase(self) -> int:
        return self._phase

    @property
    def radius(self) -> float:
        """Collision radius derived from the current sprite size so the
        hitbox always matches what's rendered on screen.  Subclasses
        inherit this automatically.  Prefer this over the legacy
        ``BOSS_RADIUS`` constant at collision call sites — the constant
        remains for spawn-time distance checks and for code that needs
        the "canonical" boss size before any sprite is alive.
        """
        # ``self.width`` is the post-scale display width in world px;
        # half of that is the radius the player sees.
        return float(self.width) * 0.5

    def _update_phase(self) -> None:
        hp_frac = self.hp / self.max_hp
        if hp_frac <= BOSS_PHASE3_HP:
            self._phase = _PHASE3
        elif hp_frac <= BOSS_PHASE2_HP:
            self._phase = _PHASE2
        else:
            self._phase = _PHASE1

    def take_damage(self, amount: int) -> None:
        """Apply damage to shields first, then HP."""
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= int(absorbed)
        if amount > 0:
            self.hp = max(0, self.hp - amount)
        self._hit_timer = 0.15
        self._update_phase()

    def collision_bump(self) -> None:
        self._bump_timer = 0.15

    def _current_speed(self) -> float:
        if self._phase >= _PHASE2:
            return BOSS_SPEED_P2
        return BOSS_SPEED

    def _current_shield_regen(self) -> float:
        if self._phase == _PHASE3:
            return 0.0  # no regen when enraged
        if self._phase == _PHASE2:
            return BOSS_SHIELD_REGEN_P2
        return BOSS_SHIELD_REGEN

    def _cannon_cooldown(self) -> float:
        if self._phase == _PHASE3:
            return BOSS_CANNON_COOLDOWN * 0.5
        return BOSS_CANNON_COOLDOWN

    def _spread_cooldown(self) -> float:
        if self._phase == _PHASE3:
            return BOSS_SPREAD_COOLDOWN * 0.5
        return BOSS_SPREAD_COOLDOWN

    def _compute_avoidance(
        self,
        base_x: float,
        base_y: float,
        asteroid_list: arcade.SpriteList,
    ) -> tuple[float, float]:
        """Steer around asteroids."""
        steer_x, steer_y = base_x, base_y
        for asteroid in asteroid_list:
            adx = self.center_x - asteroid.center_x
            ady = self.center_y - asteroid.center_y
            adist = math.hypot(adx, ady)
            # ``self.radius`` (derived from sprite size) keeps the
            # avoidance buffer proportional to the visible hull.
            thresh = self.radius + ASTEROID_RADIUS + ALIEN_AVOIDANCE_RADIUS
            if 0.0 < adist < thresh:
                w = ALIEN_AVOIDANCE_FORCE * (1.0 - adist / thresh)
                steer_x += adx / adist * w
                steer_y += ady / adist * w
        return steer_x, steer_y

    def _steer_toward(
        self,
        tx: float,
        ty: float,
        dt: float,
        asteroid_list: arcade.SpriteList,
    ) -> None:
        """Move toward a target with obstacle avoidance and rotation speed limit."""
        dx = tx - self.center_x
        dy = ty - self.center_y
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            return

        base_x = dx / dist
        base_y = dy / dist
        steer_x, steer_y = self._compute_avoidance(base_x, base_y, asteroid_list)
        smag = math.hypot(steer_x, steer_y)
        if smag < 0.001:
            return

        steer_x /= smag
        steer_y /= smag

        # Desired heading
        desired = math.degrees(math.atan2(steer_x, steer_y)) % 360.0
        # Rotate toward desired heading at BOSS_ROT_SPEED
        diff = (desired - self._heading + 180.0) % 360.0 - 180.0
        max_rot = BOSS_ROT_SPEED * dt
        if abs(diff) <= max_rot:
            self._heading = desired
        else:
            self._heading = (self._heading + max_rot * (1.0 if diff > 0 else -1.0)) % 360.0
        self.angle = self._heading

        # Move in current heading direction
        rad = math.radians(self._heading)
        move_x = math.sin(rad)
        move_y = math.cos(rad)
        speed = self._current_speed()
        step = speed * dt
        self.center_x += move_x * step
        self.center_y += move_y * step

        # Clamp to world
        self.center_x = max(50.0, min(WORLD_WIDTH - 50.0, self.center_x))
        self.center_y = max(50.0, min(WORLD_HEIGHT - 50.0, self.center_y))

    def update_boss(
        self,
        dt: float,
        player_x: float,
        player_y: float,
        station_x: float,
        station_y: float,
        asteroid_list: arcade.SpriteList,
    ) -> list[Projectile]:
        """Advance boss AI. Returns list of fired projectiles."""
        fired: list[Projectile] = []

        # ── Physics velocity decay ──
        damp = 0.97 ** (dt * 60.0)
        self.vel_x *= damp
        self.vel_y *= damp
        if math.hypot(self.vel_x, self.vel_y) < 0.5:
            self.vel_x = self.vel_y = 0.0
        self.center_x += self.vel_x * dt
        self.center_y += self.vel_y * dt

        # ── Collision cooldown ──
        if self._col_cd > 0.0:
            self._col_cd = max(0.0, self._col_cd - dt)

        # ── Shield regen ──
        regen = self._current_shield_regen()
        if regen > 0.0 and self.shields < self.max_shields:
            self.shields = min(self.max_shields, self.shields + regen * dt)

        # Update target to station position (it might move if rebuilt)
        self._target_x = station_x
        self._target_y = station_y

        # Distance to player and station
        dx_p = player_x - self.center_x
        dy_p = player_y - self.center_y
        dist_player = math.hypot(dx_p, dy_p)

        # ── Charge attack (Phase 2+) ──
        if self._update_charge(dt):
            return fired

        # ── Movement: head toward station, but engage player if close ──
        if dist_player <= BOSS_DETECT_RANGE:
            self._steer_toward(player_x, player_y, dt, asteroid_list)
        else:
            self._steer_toward(self._target_x, self._target_y, dt, asteroid_list)

        # ── Weapon cooldowns ──
        self._cannon_cd = max(0.0, self._cannon_cd - dt)
        self._spread_cd = max(0.0, self._spread_cd - dt)
        self._charge_cd = max(0.0, self._charge_cd - dt)

        # ── Initiate charge attack (Phase 2+, player in range) ──
        if (self._phase >= _PHASE2
                and self._charge_cd <= 0.0
                and dist_player <= BOSS_DETECT_RANGE):
            self._charging = True
            self._charge_windup = BOSS_CHARGE_WINDUP
            self._charge_timer = BOSS_CHARGE_DURATION
            if dist_player > 1.0:
                self._charge_dir_x = dx_p / dist_player
                self._charge_dir_y = dy_p / dist_player
            else:
                rad = math.radians(self._heading)
                self._charge_dir_x = math.sin(rad)
                self._charge_dir_y = math.cos(rad)
            return fired

        # ── Fire weapons ──
        fired.extend(self._try_fire_weapons(dist_player))

        # ── Colour tint ──
        self._update_color_tint(dt)

        return fired

    def _update_charge(self, dt: float) -> bool:
        """Handle charge attack state (windup + dash). Returns True if charging."""
        if not self._charging:
            return False

        if self._charge_windup > 0.0:
            # Windup: boss flashes white, not moving
            self._charge_windup -= dt
            # Visual telegraph: rapid color pulse
            pulse = int(abs(math.sin(self._charge_windup * 8.0)) * 200) + 55
            self.color = (pulse, pulse, 255, 255)
        else:
            # Dashing
            self._charge_timer -= dt
            self.center_x += self._charge_dir_x * BOSS_CHARGE_SPEED * dt
            self.center_y += self._charge_dir_y * BOSS_CHARGE_SPEED * dt
            self.center_x = max(50.0, min(WORLD_WIDTH - 50.0, self.center_x))
            self.center_y = max(50.0, min(WORLD_HEIGHT - 50.0, self.center_y))
            self.color = (255, 100, 100, 255)
            if self._charge_timer <= 0.0:
                self._charging = False
                self._charge_cd = BOSS_CHARGE_COOLDOWN
        return True

    def _try_fire_weapons(
        self, dist_player: float,
    ) -> list[Projectile]:
        """Fire main cannon and spread shot if cooldowns allow. Returns new projectiles."""
        result: list[Projectile] = []

        # ── Fire main cannon ──
        if self._cannon_cd <= 0.0 and dist_player <= BOSS_CANNON_RANGE:
            self._cannon_cd = self._cannon_cooldown()
            result.append(Projectile(
                self._laser_tex,
                self.center_x, self.center_y,
                self._heading,
                BOSS_CANNON_SPEED, BOSS_CANNON_RANGE,
                scale=0.8,
                damage=BOSS_CANNON_DAMAGE,
            ))

        # ── Fire spread shot ──
        if self._spread_cd <= 0.0 and dist_player <= BOSS_SPREAD_RANGE:
            self._spread_cd = self._spread_cooldown()
            half_arc = BOSS_SPREAD_ARC / 2.0
            for i in range(BOSS_SPREAD_COUNT):
                offset = -half_arc + (BOSS_SPREAD_ARC / max(1, BOSS_SPREAD_COUNT - 1)) * i
                result.append(Projectile(
                    self._laser_tex,
                    self.center_x, self.center_y,
                    self._heading + offset,
                    BOSS_SPREAD_SPEED, BOSS_SPREAD_RANGE,
                    scale=0.5,
                    damage=BOSS_SPREAD_DAMAGE,
                ))

        return result

    def _update_color_tint(self, dt: float) -> None:
        """Update hit/bump flashes and phase-based color tinting."""
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = (255, 80, 80, 255) if self._hit_timer > 0.0 else (255, 255, 255, 255)
        elif self._bump_timer > 0.0:
            self._bump_timer = max(0.0, self._bump_timer - dt)
            self.color = (255, 160, 50, 255) if self._bump_timer > 0.0 else (255, 255, 255, 255)
        else:
            # Phase-based tint: Phase 3 = angry red glow
            if self._phase == _PHASE3:
                self.color = (255, 180, 180, 255)
            elif self._phase == _PHASE2:
                self.color = (220, 200, 255, 255)
            else:
                self.color = (255, 255, 255, 255)
