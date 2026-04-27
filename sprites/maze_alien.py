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
    MAZE_ALIEN_HP_MIN, MAZE_ALIEN_HP_MAX,
    MAZE_ALIEN_LASER_DAMAGE_MIN, MAZE_ALIEN_LASER_DAMAGE_MAX,
    MAZE_ALIEN_SHIELD_CHANCE, MAZE_ALIEN_SHIELD,
    MAZE_ALIEN_SPEED, MAZE_ALIEN_RADIUS,
    MAZE_ALIEN_DETECT_DIST,
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


from sprites.alien_ai import PatrolPursueMixin


class MazeAlien(PatrolPursueMixin, arcade.Sprite):
    """Maze alien — stats per design spec.

    Deliberately lighter than ``Zone2Alien``: no shield, single gun,
    no dodging, single-frame patrol-orbit-pursue AI, maze-wall aware.
    Projectiles are routed through ``gv.alien_projectile_list`` by the
    zone so the existing player-hit pipeline applies.
    """

    # _STATE_PATROL / _STATE_PURSUE provided by PatrolPursueMixin.

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
        rooms: list | None = None,
        room_graph: dict | None = None,
        doorways: dict | None = None,
    ) -> None:
        frames = _load_frames()
        tex = random.choice(frames)
        super().__init__(path_or_texture=tex, scale=_DRAW_SCALE)
        self.center_x = x
        self.center_y = y
        # HP and laser damage are randomised per spawn from the
        # spec ranges so individual maze aliens vary in toughness +
        # bite.  35 % of spawns also get a 50-point shield rendered
        # exactly like the Zone 2 ShieldedAlien (dashed-blue rotating
        # arc).  Shielded aliens are added to ``zones.star_maze.
        # _shielded_maze_aliens`` by the zone's spawn loop so the
        # draw pass can find them in O(N) without walking every
        # alien each frame.
        self.hp: int = random.randint(MAZE_ALIEN_HP_MIN, MAZE_ALIEN_HP_MAX)
        self.max_hp: int = self.hp
        if random.random() < MAZE_ALIEN_SHIELD_CHANCE:
            self.shields: int = MAZE_ALIEN_SHIELD
            self.max_shields: int = MAZE_ALIEN_SHIELD
        else:
            self.shields: int = 0
            self.max_shields: int = 0
        self._laser_damage: float = random.uniform(
            MAZE_ALIEN_LASER_DAMAGE_MIN, MAZE_ALIEN_LASER_DAMAGE_MAX)
        self._shield_angle: float = 0.0
        self._speed: float = MAZE_ALIEN_SPEED
        self._world_w = world_w
        self._world_h = world_h
        # Maze containment AABB — any move that would take the alien
        # outside this rect is reverted.  None means "unbounded"
        # (used by tests that exercise the alien without a maze).
        self._maze_bounds: tuple[float, float, float, float] | None = (
            maze_bounds)

        # PatrolPursueMixin requires home + patrol radius + world
        # bounds + fire cooldown set before _init_patrol_state.
        hx, hy = patrol_home if patrol_home is not None else (x, y)
        self._home_x: float = hx
        self._home_y: float = hy
        self._patrol_r: float = patrol_radius
        self._tgt_x: float = x
        self._tgt_y: float = y
        self._fire_cd: float = 0.0
        self._init_patrol_state()

        self._heading: float = random.uniform(0.0, 360.0)
        self.angle = self._heading
        self._fire_cd = random.uniform(0.0, MAZE_ALIEN_FIRE_CD)
        self._laser_tex: arcade.Texture = laser_tex

        self._hit_timer: float = 0.0
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        self._bump_timer: float = 0.0
        self._stuck_check_x: float = x
        self._stuck_check_y: float = y
        self._stuck_timer: float = 0.0
        self._orbit_dir: int = random.choice((-1, 1))

        # Pathfinding — when both ``rooms`` and ``room_graph`` are
        # supplied, the alien plans a sequence of room indices toward
        # the player via ``WaypointPlanner`` and steers waypoint-to-
        # waypoint instead of straight at the player (which would
        # grind on walls between rooms).  When the planner reports
        # ``gave_up()`` (5 s of no progress, e.g. wedged on a corner),
        # the alien drops pursuit and reverts to PATROL for
        # ``_pathfind_cooldown`` seconds — the planner stays in its
        # own internal cooldown for the same window so it won't
        # re-engage immediately even if the patrol target wanders
        # back into pursue range.
        self._rooms: list | None = rooms
        self._room_graph: dict | None = room_graph
        from zones.maze_geometry import WaypointPlanner
        self._planner = WaypointPlanner(rooms, room_graph, doorways)
        self._pathfind_cooldown: float = 0.0

    # ── AI helpers ───────────────────────────────────────────────────
    # _pick_patrol_target() and alert() come from PatrolPursueMixin.

    def _next_waypoint(
        self, dt: float, player_x: float, player_y: float,
    ) -> tuple[float, float] | None:
        """Return the world position the alien should steer toward
        right now via :class:`WaypointPlanner`.  Returns ``None`` when
        the alien is already in the player's room, when no path
        exists, or when the planner is cooling down — in which case
        the caller should fall back to direct chase / patrol.
        Side effect: if the planner gave up this frame, demote to
        PATROL state and start the patrol-only cooldown so the alien
        doesn't immediately re-pursue and re-grind on the same wall.
        """
        wp = self._planner.plan(
            dt, self.center_x, self.center_y, player_x, player_y)
        if self._planner.gave_up():
            # Planner declared the path unreachable / no-progress.
            # Drop pursuit, scatter out via patrol, and don't try
            # pathfinding again until the cooldown elapses.
            self._state = self._STATE_PATROL
            self._pick_patrol_target()
            self._pathfind_cooldown = self._planner.COOLDOWN
            return None
        return wp

    # alert() inherited from PatrolPursueMixin.

    def take_damage(self, amount: int) -> None:
        # Shields absorb first (matches ShieldedAlien / player damage
        # routing); overflow falls through to HP.
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp -= amount
        self._hit_timer = 0.15

    def draw_shield(self) -> None:
        """Draw the dashed-blue rotating arc visual ShieldedAlien uses.
        Called from ``zones.star_maze.draw_world`` for any maze alien
        whose ``shields > 0``.  Rendering is skipped when the shield
        has already been depleted to zero so we don't pay the eight
        line draws per frame on stripped aliens."""
        if self.shields <= 0:
            return
        cx, cy = self.center_x, self.center_y
        r = MAZE_ALIEN_RADIUS + 15
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

        # Shield ring rotation — kept ticking even when no shields
        # remain so a partial-depletion scenario doesn't visibly
        # pause and resume.
        self._shield_angle = (self._shield_angle + 90.0 * dt) % 360

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

        # Patrol/pursue transition (3× hysteresis matches Z2 aliens).
        # While the pathfind cooldown is active the alien is forced to
        # stay in PATROL — it just got "stuck" trying to chase the
        # player and needs a window to scatter out before trying
        # again.  Same window the WaypointPlanner uses internally to
        # refuse re-planning.
        if self._pathfind_cooldown > 0.0:
            self._pathfind_cooldown = max(
                0.0, self._pathfind_cooldown - dt)
            if self._state == self._STATE_PURSUE:
                self._state = self._STATE_PATROL
                self._pick_patrol_target()
        else:
            self._advance_patrol_state(dist, MAZE_ALIEN_DETECT_DIST)

        # When pursuing through walls, recompute the room-graph path
        # to the player and steer toward the next waypoint instead of
        # the player directly.  Replaces (dx, dy) and ``dist`` so the
        # existing pursue math chases the doorway rather than the
        # player's actual position.
        if (self._state == self._STATE_PURSUE
                and self._rooms is not None
                and self._room_graph is not None):
            wp = self._next_waypoint(dt, player_x, player_y)
            if wp is not None:
                wx, wy = wp
                dx = wx - self.center_x
                dy = wy - self.center_y
                dist = math.hypot(dx, dy)

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
                damage=self._laser_damage,
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

        # Maze-wall block (static AABBs) — circle-vs-AABB push-out.
        # Iterate up to 5 times so T-intersections + corners resolve
        # (the first push-out may land us inside a neighbour wall).
        if maze_walls:
            picked_new_target = False
            for _ in range(5):
                moved = False
                r = MAZE_ALIEN_RADIUS
                for (wx, wy, ww, wh) in maze_walls:
                    qx = max(wx, min(self.center_x, wx + ww))
                    qy = max(wy, min(self.center_y, wy + wh))
                    ddx = self.center_x - qx
                    ddy = self.center_y - qy
                    dist2 = ddx * ddx + ddy * ddy
                    if dist2 >= r * r:
                        continue
                    inside_x = wx < self.center_x < wx + ww
                    inside_y = wy < self.center_y < wy + wh
                    if inside_x and inside_y:
                        d_left = self.center_x - wx
                        d_right = wx + ww - self.center_x
                        d_bot = self.center_y - wy
                        d_top = wy + wh - self.center_y
                        dmin = min(d_left, d_right, d_bot, d_top)
                        if dmin == d_left:
                            self.center_x = wx - r - 0.5
                        elif dmin == d_right:
                            self.center_x = wx + ww + r + 0.5
                        elif dmin == d_bot:
                            self.center_y = wy - r - 0.5
                        else:
                            self.center_y = wy + wh + r + 0.5
                    else:
                        dist = math.sqrt(dist2) if dist2 > 0 else 0.001
                        nx = ddx / dist if dist > 0.001 else 1.0
                        ny = ddy / dist if dist > 0.001 else 0.0
                        pen = r - dist + 0.5
                        self.center_x += nx * pen
                        self.center_y += ny * pen
                    moved = True
                    if not picked_new_target:
                        self._pick_patrol_target()
                        picked_new_target = True
                    break
                if not moved:
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
