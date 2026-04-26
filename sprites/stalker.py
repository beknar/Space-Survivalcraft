"""Stalker — third Star Maze enemy type.

Ranged missile platform: fires the same `HomingMissile` the player
launches (same speed, range, damage, turn rate) at a 1.6 s cadence.
The stalker itself is slower than other aliens (100 px/s) and
prefers to orbit at standoff distance so its missiles have time to
acquire and turn into the player.  Drops 90 iron + 30 XP on kill.

Stalkers live in ``zones.star_maze.StarMazeZone._stalkers``.  Their
fired missiles go to ``gv._alien_missile_list`` (separate from the
player's ``_missile_list``) so the existing missile-vs-alien
collision pipeline doesn't accidentally home them onto their own
faction.  Player-side update / damage handling lives in
``update_logic.update_alien_missiles``.
"""
from __future__ import annotations

import math
import random

import arcade

from constants import (
    STALKER_PNG, STALKER_FRAME_SIZE, STALKER_SHEET_ROW, STALKER_SHEET_COL,
    STALKER_HP, STALKER_SPEED, STALKER_RADIUS,
    STALKER_DETECT_DIST, STALKER_FIRE_COOLDOWN, STALKER_FIRE_RANGE,
    STALKER_STANDOFF_DIST, STALKER_SCALE,
    ALIEN_VEL_DAMPING, ALIEN_BUMP_FLASH,
    STAR_MAZE_WIDTH, STAR_MAZE_HEIGHT,
)
from sprites.missile import HomingMissile


# Cache the cropped frame once across instances so the PIL crop
# only happens on the first stalker spawn.
_FRAME_CACHE: dict[str, arcade.Texture] = {}


def _load_frame(sheet_path: str = STALKER_PNG) -> arcade.Texture:
    cached = _FRAME_CACHE.get(sheet_path)
    if cached is None:
        from PIL import Image as _PILImage
        sheet = _PILImage.open(sheet_path).convert("RGBA")
        fs = STALKER_FRAME_SIZE
        x = STALKER_SHEET_COL * fs
        y = STALKER_SHEET_ROW * fs
        crop = sheet.crop((x, y, x + fs, y + fs))
        cached = arcade.Texture(crop)
        _FRAME_CACHE[sheet_path] = cached
    return cached


class Stalker(arcade.Sprite):
    """Patrol/pursue missile-firing enemy."""

    _STATE_PATROL = 0
    _STATE_PURSUE = 1

    def __init__(
        self,
        missile_tex: arcade.Texture,
        x: float, y: float,
        *,
        world_w: float = STAR_MAZE_WIDTH,
        world_h: float = STAR_MAZE_HEIGHT,
        patrol_radius: float = 200.0,
    ) -> None:
        super().__init__(path_or_texture=_load_frame(),
                         scale=STALKER_SCALE)
        self.center_x = x
        self.center_y = y
        self.hp: int = STALKER_HP
        self.max_hp: int = STALKER_HP
        # Stalkers don't carry shields per spec — keep the field for
        # uniformity with other enemy classes (HUD/collision code can
        # branch on `getattr(e, 'shields', 0)`).
        self.shields: int = 0
        self.max_shields: int = 0
        self.radius: float = STALKER_RADIUS
        self._world_w = world_w
        self._world_h = world_h

        self._state: int = self._STATE_PATROL
        self._home_x: float = x
        self._home_y: float = y
        self._patrol_r: float = patrol_radius
        self._tgt_x: float = x
        self._tgt_y: float = y
        self._pick_patrol_target()

        self._heading: float = random.uniform(0.0, 360.0)
        self.angle = self._heading
        # Stagger first-shot cooldowns so 15 stalkers don't all
        # launch on the same tick when the player wanders into a
        # cluster's detect range.
        self._fire_cd: float = random.uniform(0.0, STALKER_FIRE_COOLDOWN)
        self._missile_tex: arcade.Texture = missile_tex

        self._hit_timer: float = 0.0
        self._bump_timer: float = 0.0
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        # Random orbit direction so a cluster doesn't all swing
        # the same way.
        self._orbit_dir: int = random.choice((-1, 1))

    # ── AI helpers ───────────────────────────────────────────────────

    def _pick_patrol_target(self) -> None:
        from sprites.alien_ai import pick_patrol_target
        self._tgt_x, self._tgt_y = pick_patrol_target(
            self._home_x, self._home_y, self._patrol_r,
            self._world_w, self._world_h)

    def alert(self) -> None:
        if self._state == self._STATE_PATROL:
            self._state = self._STATE_PURSUE
            self._fire_cd = 0.0

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        self._hit_timer = 0.15

    def collision_bump(self) -> None:
        self._bump_timer = ALIEN_BUMP_FLASH

    # ── Per-frame update ─────────────────────────────────────────────

    def update_alien(
        self, dt: float, player_x: float, player_y: float,
        asteroid_list, alien_list, force_walls=None,
    ) -> list[HomingMissile]:
        """Advance AI + return any fired missiles.

        Signature matches Z2Alien.update_alien so the star-maze
        update loop can iterate stalkers + Z2 aliens uniformly.
        """
        fired: list[HomingMissile] = []

        damp = ALIEN_VEL_DAMPING ** (dt * 60.0)
        self.vel_x *= damp
        self.vel_y *= damp
        if math.hypot(self.vel_x, self.vel_y) < 0.5:
            self.vel_x = self.vel_y = 0.0
        self.center_x += self.vel_x * dt
        self.center_y += self.vel_y * dt

        dx = player_x - self.center_x
        dy = player_y - self.center_y
        dist = math.hypot(dx, dy)

        if self._state == self._STATE_PATROL:
            if dist <= STALKER_DETECT_DIST:
                self._state = self._STATE_PURSUE
                self._fire_cd = 0.0
        else:
            if dist > STALKER_DETECT_DIST * 3.0:
                self._state = self._STATE_PATROL
                self._pick_patrol_target()

        self._move(dt, dist, dx, dy)
        self._update_visuals(dt)

        # Fire — gated on state + range + cooldown.
        self._fire_cd = max(0.0, self._fire_cd - dt)
        if (self._state == self._STATE_PURSUE
                and dist <= STALKER_FIRE_RANGE
                and self._fire_cd <= 0.0):
            self._fire_cd = STALKER_FIRE_COOLDOWN
            # Aim heading at the player at launch; the missile's own
            # homing logic takes over after one frame.
            launch_heading = math.degrees(math.atan2(dx, dy)) % 360.0
            fired.append(HomingMissile(
                self._missile_tex,
                self.center_x, self.center_y,
                launch_heading,
            ))

        return fired

    def _move(self, dt: float, dist: float, dx: float, dy: float) -> None:
        """Patrol wanders toward a waypoint; pursue orbits the player
        at STALKER_STANDOFF_DIST so the launched missiles have travel
        room to acquire."""
        if self._state == self._STATE_PATROL:
            tdx = self._tgt_x - self.center_x
            tdy = self._tgt_y - self.center_y
            tdist = math.hypot(tdx, tdy)
            if tdist < 8.0:
                self._pick_patrol_target()
            elif tdist > 0.001:
                step = min(STALKER_SPEED * dt, tdist)
                self.center_x += tdx / tdist * step
                self.center_y += tdy / tdist * step
                self._heading = math.degrees(
                    math.atan2(tdx / tdist, tdy / tdist)) % 360
                self.angle = self._heading
        elif dist > 1.0:
            nx, ny = dx / dist, dy / dist
            perp_x = -ny * self._orbit_dir
            perp_y = nx * self._orbit_dir
            if dist > STALKER_STANDOFF_DIST * 1.2:
                radial = 1.0
            elif dist < STALKER_STANDOFF_DIST * 0.7:
                radial = -0.6
            else:
                radial = 0.0
            mx = nx * radial + perp_x * 0.9
            my = ny * radial + perp_y * 0.9
            mag = math.hypot(mx, my)
            if mag > 0.001:
                step = STALKER_SPEED * dt
                self.center_x += mx / mag * step
                self.center_y += my / mag * step
            self._heading = math.degrees(math.atan2(nx, ny)) % 360
            self.angle = self._heading

    def _update_visuals(self, dt: float) -> None:
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = ((255, 80, 80, 255) if self._hit_timer > 0.0
                          else (255, 255, 255, 255))
        elif self._bump_timer > 0.0:
            self._bump_timer = max(0.0, self._bump_timer - dt)
            self.color = ((255, 160, 50, 255) if self._bump_timer > 0.0
                          else (255, 255, 255, 255))
