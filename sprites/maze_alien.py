"""Maze alien — spawned inside Star Maze rooms by a ``MazeSpawner``.

Anatomy mirrors ``Zone2Alien`` (patrol/pursue, asteroid + force-wall
avoidance, laser cooldown + heading) but uses its own per-stat
constants instead of the ``ALIEN_*`` set.  Adds static-wall collision
for the dungeon walls carved around every maze room — on any tick
whose move would land the alien inside a wall rect, the position
reverts and a new patrol target is picked so it doesn't grind on the
geometry.
"""
from __future__ import annotations

import math
import random

import arcade

from constants import (
    MAZE_ALIEN_HP, MAZE_ALIEN_SPEED, MAZE_ALIEN_RADIUS,
    MAZE_ALIEN_DETECT_DIST, MAZE_ALIEN_LASER_DAMAGE,
    MAZE_ALIEN_LASER_RANGE, MAZE_ALIEN_LASER_SPEED,
    MAZE_ALIEN_FIRE_CD,
    MAZE_ALIEN_SHEET_PNG, MAZE_ALIEN_SHEET_FRAME_SIZE,
    MAZE_ALIEN_SHEET_ROWS_FROM_BOTTOM, MAZE_ALIEN_SHEET_COLS,
    ALIEN_VEL_DAMPING, ALIEN_STANDOFF_DIST, ALIEN_BUMP_FLASH,
    ALIEN_STUCK_TIME, ALIEN_STUCK_DIST,
    STAR_MAZE_WIDTH, STAR_MAZE_HEIGHT,
)
from sprites.projectile import Projectile


# Cache the eight 128×128 source frames across instances so the PIL
# crop + texture upload only happens once per game run.  Keyed by
# (sheet_path, column_index).
_FRAME_CACHE: dict[tuple[str, int], arcade.Texture] = {}
# Scale applied to the 128 px source frame — the sprite should
# render at roughly MAZE_ALIEN_RADIUS * 2 px diameter.
_DRAW_SCALE: float = (MAZE_ALIEN_RADIUS * 2.0) / MAZE_ALIEN_SHEET_FRAME_SIZE


def _load_frames(sheet_path: str = MAZE_ALIEN_SHEET_PNG
                 ) -> list[arcade.Texture]:
    """Return eight ``arcade.Texture``s — one per column of the third
    row from the bottom of the faction-3 monsters sheet.  Cached across
    callers."""
    frames: list[arcade.Texture] = []
    for col in range(MAZE_ALIEN_SHEET_COLS):
        key = (sheet_path, col)
        cached = _FRAME_CACHE.get(key)
        if cached is None:
            from PIL import Image as _PILImage
            sheet = _PILImage.open(sheet_path).convert("RGBA")
            sheet_w, sheet_h = sheet.size
            fs = MAZE_ALIEN_SHEET_FRAME_SIZE
            rows_from_bottom = MAZE_ALIEN_SHEET_ROWS_FROM_BOTTOM
            # "Third row from the bottom" — PIL origin is top-left, so
            # the actual top of that row sits ``rows_from_bottom`` rows
            # above the sheet bottom.
            y_top = sheet_h - rows_from_bottom * fs
            x_left = col * fs
            crop = sheet.crop((x_left, y_top, x_left + fs, y_top + fs))
            cached = arcade.Texture(crop)
            _FRAME_CACHE[key] = cached
        frames.append(cached)
    return frames


class MazeAlien(arcade.Sprite):
    """Maze alien — stats per design spec.

    Deliberately lighter than ``Zone2Alien``: no shield, single gun,
    no dodging, single-frame patrol-orbit-pursue AI, maze-wall aware.
    Projectiles are routed through ``gv.alien_projectile_list`` by the
    zone so the existing player-hit pipeline applies.
    """

    _STATE_PATROL = 0
    _STATE_PURSUE = 1

    def __init__(
        self,
        laser_tex: arcade.Texture,
        x: float, y: float,
        *,
        world_w: float = STAR_MAZE_WIDTH,
        world_h: float = STAR_MAZE_HEIGHT,
        patrol_home: tuple[float, float] | None = None,
        patrol_radius: float = 180.0,
        maze_bounds: tuple[float, float, float, float] | None = None,
    ) -> None:
        frames = _load_frames()
        tex = random.choice(frames)
        super().__init__(path_or_texture=tex, scale=_DRAW_SCALE)
        self.center_x = x
        self.center_y = y
        self.hp: int = MAZE_ALIEN_HP
        self.max_hp: int = MAZE_ALIEN_HP
        self.shields: int = 0
        self.max_shields: int = 0
        self._speed: float = MAZE_ALIEN_SPEED
        self._world_w = world_w
        self._world_h = world_h
        # Maze containment AABB — any move that would take the alien
        # outside this rect is reverted.  None means "unbounded"
        # (used by tests that exercise the alien without a maze).
        self._maze_bounds: tuple[float, float, float, float] | None = (
            maze_bounds)

        self._state: int = self._STATE_PATROL
        hx, hy = patrol_home if patrol_home is not None else (x, y)
        self._home_x: float = hx
        self._home_y: float = hy
        self._patrol_r: float = patrol_radius
        self._tgt_x: float = x
        self._tgt_y: float = y
        self._pick_patrol_target()

        self._heading: float = random.uniform(0.0, 360.0)
        self.angle = self._heading
        self._fire_cd: float = random.uniform(0.0, MAZE_ALIEN_FIRE_CD)
        self._laser_tex: arcade.Texture = laser_tex

        self._hit_timer: float = 0.0
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        self._bump_timer: float = 0.0
        self._stuck_check_x: float = x
        self._stuck_check_y: float = y
        self._stuck_timer: float = 0.0
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
        self,
        dt: float,
        player_x: float,
        player_y: float,
        asteroid_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
        force_walls: list | None = None,
        maze_walls: list | None = None,
    ) -> list[Projectile]:
        """Advance AI + return any fired projectiles.

        ``maze_walls`` is a list of AABB rects ``(x, y, w, h)`` for the
        static dungeon walls.  Any move that would land inside one of
        them is rolled back and a new patrol target is chosen.
        """
        fired: list[Projectile] = []

        # Physics velocity damping (for knockback etc.).
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
            if dist <= MAZE_ALIEN_DETECT_DIST:
                self._state = self._STATE_PURSUE
                self._fire_cd = 0.0
        else:
            # Disengage much further out than the detect range — matches
            # the Zone 2 alien hysteresis.
            if dist > MAZE_ALIEN_DETECT_DIST * 3.0:
                self._state = self._STATE_PATROL
                self._pick_patrol_target()

        self._move(dt, player_x, player_y, dist, dx, dy,
                   asteroid_list, alien_list, force_walls, maze_walls)

        # Stuck detection — if the alien hasn't moved much in
        # ALIEN_STUCK_TIME seconds, pick a new patrol target.  Maze
        # walls are the usual culprit.
        self._stuck_timer += dt
        if self._stuck_timer >= ALIEN_STUCK_TIME:
            moved = math.hypot(self.center_x - self._stuck_check_x,
                               self.center_y - self._stuck_check_y)
            if moved < ALIEN_STUCK_DIST:
                self._pick_patrol_target()
            self._stuck_check_x = self.center_x
            self._stuck_check_y = self.center_y
            self._stuck_timer = 0.0

        # Colour tint — red on damage, orange on collision bump.
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = ((255, 80, 80, 255) if self._hit_timer > 0.0
                          else (255, 255, 255, 255))
        elif self._bump_timer > 0.0:
            self._bump_timer = max(0.0, self._bump_timer - dt)
            self.color = ((255, 160, 50, 255) if self._bump_timer > 0.0
                          else (255, 255, 255, 255))

        # Fire — gated on state + range + cooldown.
        self._fire_cd = max(0.0, self._fire_cd - dt)
        if (self._state == self._STATE_PURSUE
                and dist <= MAZE_ALIEN_LASER_RANGE
                and self._fire_cd <= 0.0):
            self._fire_cd = MAZE_ALIEN_FIRE_CD
            fired.append(Projectile(
                self._laser_tex,
                self.center_x, self.center_y,
                self._heading,
                MAZE_ALIEN_LASER_SPEED, MAZE_ALIEN_LASER_RANGE,
                scale=0.5,
                damage=MAZE_ALIEN_LASER_DAMAGE,
            ))

        return fired

    # ── Movement ─────────────────────────────────────────────────────

    def _move(self, dt, player_x, player_y, dist, dx, dy,
              asteroid_list, alien_list,
              force_walls=None, maze_walls=None) -> None:
        """Patrol wanders toward a waypoint; pursue orbits at standoff.
        In both modes, a move that would intersect a maze-wall AABB
        reverts to the pre-move position (simple blocking, not
        smoothing — complete reprogramming for maze navigation is
        outside the scope of the initial pass)."""
        from sprites.alien_ai import compute_avoidance

        prev_x, prev_y = self.center_x, self.center_y

        if self._state == self._STATE_PATROL:
            tdx = self._tgt_x - self.center_x
            tdy = self._tgt_y - self.center_y
            tdist = math.hypot(tdx, tdy)
            if tdist < 8.0:
                self._pick_patrol_target()
            elif tdist > 0.001:
                base_x = tdx / tdist
                base_y = tdy / tdist
                sx, sy = compute_avoidance(
                    self, base_x, base_y, asteroid_list, (), force_walls)
                smag = math.hypot(sx, sy)
                if smag > 0.001:
                    step = min(self._speed * dt, tdist)
                    self.center_x += sx / smag * step
                    self.center_y += sy / smag * step
                    self._heading = math.degrees(math.atan2(
                        sx / smag, sy / smag)) % 360
                    self.angle = self._heading
        else:
            if dist > 1.0:
                nx, ny = dx / dist, dy / dist
                perp_x = -ny * self._orbit_dir
                perp_y = nx * self._orbit_dir
                if dist > ALIEN_STANDOFF_DIST * 1.2:
                    radial = 1.0
                elif dist < ALIEN_STANDOFF_DIST * 0.7:
                    radial = -0.6
                else:
                    radial = 0.0
                mx = nx * radial + perp_x * 0.9
                my = ny * radial + perp_y * 0.9
                sx, sy = compute_avoidance(
                    self, mx, my, asteroid_list, (), force_walls)
                smag = math.hypot(sx, sy)
                if smag > 0.001:
                    step = self._speed * dt
                    self.center_x += sx / smag * step
                    self.center_y += sy / smag * step
                self._heading = math.degrees(math.atan2(nx, ny)) % 360
                self.angle = self._heading

        # Force-wall block (dynamic).
        if force_walls:
            for wall in force_walls:
                if wall.segment_crosses(prev_x, prev_y,
                                        self.center_x, self.center_y):
                    self.center_x, self.center_y = prev_x, prev_y
                    break

        # Maze-wall block (static AABBs).
        if maze_walls:
            cx, cy = self.center_x, self.center_y
            r = MAZE_ALIEN_RADIUS
            for (wx, wy, ww, wh) in maze_walls:
                if (cx + r > wx and cx - r < wx + ww
                        and cy + r > wy and cy - r < wy + wh):
                    self.center_x, self.center_y = prev_x, prev_y
                    # Rethink the waypoint so we don't keep crashing
                    # into the same tile.
                    self._pick_patrol_target()
                    break

        # Maze-bounds containment — an alien must never leave its
        # home maze's AABB (per spec).  Clamp + revert if the move
        # would have taken them outside.  The existing maze-wall
        # check already blocks most exits, but pursuit of a player
        # who's *just outside* a doorway can still drift out — this
        # is the hard stop.
        if self._maze_bounds is not None:
            bx, by, bw, bh = self._maze_bounds
            r = MAZE_ALIEN_RADIUS
            if (self.center_x - r < bx or self.center_x + r > bx + bw
                    or self.center_y - r < by
                    or self.center_y + r > by + bh):
                self.center_x, self.center_y = prev_x, prev_y
                self._pick_patrol_target()
