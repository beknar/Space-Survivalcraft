"""Star Maze — post-Nebula-boss zone built around two dungeon mazes.

Layout: a ``STAR_MAZE_WIDTH × STAR_MAZE_HEIGHT`` field with **two**
proper mazes carved via recursive backtracking (see ``maze_geometry.
generate_maze``).  Each maze is a 5×5 grid of 300 × 300 rooms bound
by 32 px dungeon walls, with a single ``MazeSpawner`` anchored at
the centre room.  The spawner fires a 30-damage laser and drips
``MazeAlien``s on a 30 s cadence.

Everything outside the two maze footprints is currently open space
— Nebula-style population was removed per the user's "remove the
nebula zone objects" instruction.  The Nebula population hooks
(``reject_fn`` on ``zone2_world.populate_*`` and ``world_setup.
populate_null_fields`` / ``populate_slipspaces``) stay in place so
Zone 2 content can be layered back on top of the maze footprints
later with a single call.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    STAR_MAZE_WIDTH, STAR_MAZE_HEIGHT,
    STAR_MAZE_WALL_TILE, STAR_MAZE_WALL_SCALE,
    DUNGEON_WALL_SHEET_PNG,
    MAZE_ALIEN_RADIUS, MAZE_SPAWNER_RADIUS,
    MAZE_SPAWNER_IRON_DROP, MAZE_SPAWNER_XP,
    MAZE_ALIEN_IRON_DROP, MAZE_ALIEN_XP,
    SHIP_RADIUS, SHIP_COLLISION_COOLDOWN, SHIP_COLLISION_DAMAGE,
    SHIP_BOUNCE,
    FOG_CELL_SIZE, FOG_REVEAL_RADIUS,
    STAR_MAZE_CENTERS,
    WANDERING_RADIUS,
    ASTEROID_RADIUS, ALIEN_BOUNCE,
    RESPAWN_INTERVAL,
)
from zones import ZoneID, ZoneState
from zones.maze_geometry import (
    Rect, MazeLayout, generate_all_mazes,
    circle_hits_any_wall, segment_hits_any_wall,
    point_inside_any_room_interior,
)
from sprites.wormhole import Wormhole
from sprites.maze_alien import MazeAlien
from sprites.maze_spawner import MazeSpawner

if TYPE_CHECKING:
    from game_view import GameView


# ── Wall tile cache ─────────────────────────────────────────────────
#
# The 336 × 184 dungeon sheet has many 16×16 tiles.  Most of the top
# row is fully transparent (verified); tile (col 7, row 1) is
# 256/256 opaque, which is what we repeat over every wall rect.  If
# you want per-edge-type tiles later (corners, doorways, etc.) this
# is where to plug them in.

_WALL_TILE_TEX: arcade.Texture | None = None


def _load_wall_tile() -> arcade.Texture:
    global _WALL_TILE_TEX
    if _WALL_TILE_TEX is None:
        from PIL import Image as _PILImage
        sheet = _PILImage.open(DUNGEON_WALL_SHEET_PNG).convert("RGBA")
        tile_col = 7
        tile_row = 1
        left = tile_col * STAR_MAZE_WALL_TILE
        top = tile_row * STAR_MAZE_WALL_TILE
        tile = sheet.crop(
            (left, top, left + STAR_MAZE_WALL_TILE,
             top + STAR_MAZE_WALL_TILE))
        _WALL_TILE_TEX = arcade.Texture(tile)
    return _WALL_TILE_TEX


def _build_wall_sprites(walls: list[Rect]) -> arcade.SpriteList:
    """Tile each wall rect with 32 × 32 instances of the dungeon wall
    tile.  Returned SpriteList draws in one GL call per frame."""
    tex = _load_wall_tile()
    tile_px = int(STAR_MAZE_WALL_TILE * STAR_MAZE_WALL_SCALE)  # 32
    lst = arcade.SpriteList()
    for r in walls:
        cols = max(1, int(math.ceil(r.w / tile_px)))
        rows = max(1, int(math.ceil(r.h / tile_px)))
        for row in range(rows):
            for col in range(cols):
                sx = r.x + col * tile_px + tile_px / 2
                sy = r.y + row * tile_px + tile_px / 2
                s = arcade.Sprite(
                    path_or_texture=tex,
                    scale=STAR_MAZE_WALL_SCALE,
                    center_x=sx,
                    center_y=sy,
                )
                lst.append(s)
    return lst


class StarMazeZone(ZoneState):
    """The Star Maze — two mazes in a 12 000 × 12 000 field."""
    zone_id = ZoneID.STAR_MAZE
    world_width = STAR_MAZE_WIDTH
    world_height = STAR_MAZE_HEIGHT

    def __init__(self) -> None:
        self._world_seed: int = random.randint(0, 2**31 - 1)
        self._populated: bool = False
        # Per-maze artefacts — parallel lists indexed by maze id.
        self._mazes: list[MazeLayout] = []
        # Flattened room + wall lists covering both mazes (used by
        # collision + population-exclusion helpers).
        self._rooms: list[Rect] = []
        self._walls: list[Rect] = []
        self._wall_sprite_list: arcade.SpriteList | None = None
        # Spawners + aliens.  One spawner per maze, so ``_spawners``
        # has len == STAR_MAZE_COUNT.
        self._spawners: arcade.SpriteList = arcade.SpriteList()
        self._maze_aliens: arcade.SpriteList = arcade.SpriteList()
        self._maze_projectiles: arcade.SpriteList = arcade.SpriteList()
        # Placeholder list handed to MazeAlien.update_alien as the
        # "asteroid avoidance" input.  Allocating this as a fresh
        # SpriteList on every tick leaked ~2 MB / frame of GL-buffer
        # handles (pos/size/colour/tex/index) — see
        # TEST_RESULTS_2026-04-23 soak findings.  Create it once and
        # reuse it.
        self._empty_asteroid_list: arcade.SpriteList = arcade.SpriteList()
        # Nebula-style population — same counts + types as Zone 2,
        # spawned outside every maze AABB via the reject_fn filter.
        # Attribute names match Zone 2 exactly so the shared
        # ``zone2_world`` helpers (populate_*, handle_projectile_hits,
        # try_respawn) can be reused unchanged.
        self._iron_asteroids: arcade.SpriteList = arcade.SpriteList(
            use_spatial_hash=True)
        self._double_iron: arcade.SpriteList = arcade.SpriteList(
            use_spatial_hash=True)
        self._copper_asteroids: arcade.SpriteList = arcade.SpriteList(
            use_spatial_hash=True)
        self._aliens: arcade.SpriteList = arcade.SpriteList()
        self._shielded_aliens: list = []
        self._alien_projectiles: arcade.SpriteList = arcade.SpriteList()
        self._gas_areas: arcade.SpriteList = arcade.SpriteList()
        self._wanderers: arcade.SpriteList = arcade.SpriteList()
        self._null_fields: list = []
        self._slipspaces: arcade.SpriteList = arcade.SpriteList()
        self._iron_tex: arcade.Texture | None = None
        self._copper_tex: arcade.Texture | None = None
        self._copper_pickup_tex: arcade.Texture | None = None
        self._alien_textures: dict[str, arcade.Texture] = {}
        self._alien_laser_tex: arcade.Texture | None = None
        self._wanderer_tex: arcade.Texture | None = None
        self._gas_damage_cd: float = 0.0
        self._respawn_timer: float = 0.0
        self._alien_counts: dict[str, int] = {}
        self._gas_pos_cache: list[tuple[float, float, float]] | None = None
        self._minimap_cache = None
        # Fog of war.
        self._fog_cell = FOG_CELL_SIZE
        self._fog_reveal_r = FOG_REVEAL_RADIUS
        self._fog_w = STAR_MAZE_WIDTH // FOG_CELL_SIZE
        self._fog_h = STAR_MAZE_HEIGHT // FOG_CELL_SIZE
        self._fog_grid: list[list[bool]] = [
            [False] * self._fog_w for _ in range(self._fog_h)]
        self._fog_revealed: int = 0
        # alien -> parent spawner uid.
        self._alien_parent: dict[MazeAlien, int] = {}
        # Spatial hash of wall rects: grid[gx, gy] -> list of wall
        # AABBs that overlap that cell.  Built in _generate and
        # consulted by every per-frame wall query so we don't walk
        # the full ~150-wall list on every circle/segment check.
        # Cell size is 1.5x the wall thickness so even a moving ship
        # only ever straddles 2-3 cells at a time.
        self._wall_grid: dict[tuple[int, int], list[Rect]] = {}
        self._wall_grid_cell: int = 48

    # ── Setup / teardown ────────────────────────────────────────────

    def setup(self, gv: GameView) -> None:
        self._load_textures(gv)
        if not self._populated:
            self._generate(gv)
            self._populated = True
        self._wall_sprite_list = _build_wall_sprites(self._walls)
        self._rebuild_shielded_list()

        # Central wormhole back to Zone 2 (safety exit).
        cx, cy = self._find_open_point(*self._central_wormhole_pos())
        wh = Wormhole(cx, cy)
        wh.zone_target = ZoneID.ZONE2
        gv._wormholes = [wh]
        gv._wormhole_list.clear()
        gv._wormhole_list.append(wh)
        # Four corner wormholes chaining to the MAZE_WARP_* variants.
        margin = 220
        ww = self.world_width
        whh = self.world_height
        corners = [
            (margin, margin, ZoneID.MAZE_WARP_METEOR),
            (ww - margin, margin, ZoneID.MAZE_WARP_LIGHTNING),
            (margin, whh - margin, ZoneID.MAZE_WARP_GAS),
            (ww - margin, whh - margin, ZoneID.MAZE_WARP_ENEMY),
        ]
        for (wx, wy, target) in corners:
            cwh = Wormhole(wx, wy)
            cwh.zone_target = target
            gv._wormholes.append(cwh)
            gv._wormhole_list.append(cwh)

        # Fog grid hand-off.
        gv._fog_grid = self._fog_grid
        gv._fog_revealed = self._fog_revealed

        # Welcome flash on arrival.
        from zones import welcome_message_for
        msg = welcome_message_for(self.zone_id)
        if msg is not None:
            gv._flash_game_msg(msg, 1.8)

    def _load_textures(self, gv: GameView) -> None:
        from zones.nebula_shared import load_nebula_textures
        load_nebula_textures(self, gv)

    def _rebuild_shielded_list(self) -> None:
        from zones.nebula_shared import rebuild_shielded_list
        rebuild_shielded_list(self)

    def _maze_reject_fn(self, radius: float = 0.0, margin: float = 40.0):
        """Factory for the population reject filter.

        Rejects any candidate whose disk ``(x, y, radius + margin)``
        intersects the outer AABB of any maze structure — that keeps
        asteroid + gas bodies (not just centres) out of the maze, so
        their edges don't clip through walls and they don't spawn
        inside a wall rect.  The room-interior check is a strict
        subset of the maze-bounds check, so moving to bounds still
        satisfies the "never spawn in a room" contract.
        """
        bounds = [(m.bounds.x, m.bounds.y, m.bounds.w, m.bounds.h)
                  for m in self._mazes]
        pad = radius + margin

        def _reject(x: float, y: float) -> bool:
            for (bx, by, bw, bh) in bounds:
                if (bx - pad <= x <= bx + bw + pad
                        and by - pad <= y <= by + bh + pad):
                    return True
            return False
        return _reject

    def _respawn_reject(self, x: float, y: float, radius: float) -> bool:
        """Hook for ``zone2_world.try_respawn`` / ``_find_respawn_pos``.
        Returns True for any candidate whose disk ``(x, y, radius)``
        would land inside a maze AABB (plus 40 px margin).  Without
        this, every minute one Z2 alien of each type was spawning
        anywhere on the map — including inside a maze.
        """
        pad = radius + 40.0
        for m in self._mazes:
            b = m.bounds
            if (b.x - pad <= x <= b.x + b.w + pad
                    and b.y - pad <= y <= b.y + b.h + pad):
                return True
        return False

    def _build_wall_grid(self) -> None:
        """Build the spatial-hash index over ``self._walls``.  Every
        wall rect is bucketed into every grid cell it overlaps, so
        a point or circle query only has to look at a handful of
        nearby cells.  Called once per ``_generate``."""
        grid: dict[tuple[int, int], list[Rect]] = {}
        cell = self._wall_grid_cell
        for w in self._walls:
            gx0 = int(w.x // cell)
            gy0 = int(w.y // cell)
            gx1 = int((w.x + w.w) // cell)
            gy1 = int((w.y + w.h) // cell)
            for gy in range(gy0, gy1 + 1):
                for gx in range(gx0, gx1 + 1):
                    grid.setdefault((gx, gy), []).append(w)
        self._wall_grid = grid

    def _walls_near(
        self, cx: float, cy: float, radius: float,
    ) -> list[Rect]:
        """Return the wall rects whose grid cells overlap the disk at
        ``(cx, cy, radius)``.  Walls may appear multiple times if
        they span more than one cell — callers that care about
        uniqueness should dedupe, but the tight inner loops here are
        already O(1) per check so it's fine."""
        if not self._wall_grid:
            return self._walls
        cell = self._wall_grid_cell
        gx0 = int((cx - radius) // cell)
        gy0 = int((cy - radius) // cell)
        gx1 = int((cx + radius) // cell)
        gy1 = int((cy + radius) // cell)
        out: list[Rect] = []
        seen: set[int] = set()
        for gy in range(gy0, gy1 + 1):
            for gx in range(gx0, gx1 + 1):
                bucket = self._wall_grid.get((gx, gy))
                if not bucket:
                    continue
                for w in bucket:
                    wid = id(w)
                    if wid not in seen:
                        seen.add(wid)
                        out.append(w)
        return out

    def _segment_hits_wall_fast(
        self, ax: float, ay: float, bx: float, by: float,
    ) -> bool:
        """Grid-accelerated version of
        ``segment_hits_any_wall`` — samples 4 points along the
        segment and only checks walls whose cell the sample sits
        in."""
        for t in (0.0, 0.33, 0.66, 1.0):
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            for w in self._walls_near(x, y, 2.0):
                if (w.x <= x <= w.x + w.w
                        and w.y <= y <= w.y + w.h):
                    return True
        return False

    def _point_in_any_wall_fast(
        self, x: float, y: float,
    ) -> bool:
        for w in self._walls_near(x, y, 2.0):
            if (w.x <= x <= w.x + w.w
                    and w.y <= y <= w.y + w.h):
                return True
        return False

    def _push_out_of_maze_bounds(
        self, entities, radius: float,
    ) -> None:
        """Eject any entity whose centre has drifted inside a maze's
        outer AABB.  Push it out along the shortest of the four edge
        distances and reflect velocity (if any).  Called every frame
        so non-maze aliens / wanderers can never linger inside the
        maze even if they slip through the entrance gap."""
        for e in entities:
            cx, cy = e.center_x, e.center_y
            for m in self._mazes:
                b = m.bounds
                if not (b.x < cx < b.x + b.w
                        and b.y < cy < b.y + b.h):
                    continue
                d_left = cx - b.x
                d_right = b.x + b.w - cx
                d_bot = cy - b.y
                d_top = b.y + b.h - cy
                dmin = min(d_left, d_right, d_bot, d_top)
                if dmin == d_left:
                    e.center_x = b.x - radius - 1.0
                    nx, ny = -1.0, 0.0
                elif dmin == d_right:
                    e.center_x = b.x + b.w + radius + 1.0
                    nx, ny = 1.0, 0.0
                elif dmin == d_bot:
                    e.center_y = b.y - radius - 1.0
                    nx, ny = 0.0, -1.0
                else:
                    e.center_y = b.y + b.h + radius + 1.0
                    nx, ny = 0.0, 1.0
                vx = getattr(e, "vel_x", None)
                vy = getattr(e, "vel_y", None)
                if vx is not None and vy is not None:
                    v_dot_n = vx * nx + vy * ny
                    if v_dot_n < 0.0:
                        e.vel_x = vx - 2.0 * v_dot_n * nx
                        e.vel_y = vy - 2.0 * v_dot_n * ny
                break

    def _push_out_of_walls(
        self, entities, radius: float,
    ) -> None:
        """Push every entity in ``entities`` (SpriteList-like) out of
        any maze wall it overlaps.  Handles two cases:

          * Circle-vs-AABB overlap where the centre is outside the
            rect — clamp to the nearest point on the rect and push
            out along that normal (standard circle-vs-rect resolve).
          * Centre is INSIDE the rect (can happen when a wanderer
            drifts deep into a wall between ticks) — find the
            nearest edge and teleport the entity to just outside it,
            so "push-out" doesn't collapse to the ambiguous
            dist == 0 case.

        Iterates up to 5 times per entity so corner cases where
        pushing out of one wall lands the entity inside a
        neighbouring wall (T-intersections) eventually resolve.
        """
        for e in entities:
            for _iter in range(5):
                moved = self._resolve_one_wall_collision(e, radius)
                if not moved:
                    break

    def _resolve_one_wall_collision(
        self, e, radius: float,
    ) -> bool:
        """Push ``e`` out of the first overlapping wall and return
        True if it moved.  Separated so ``_push_out_of_walls`` can
        iterate until the entity clears every neighbouring wall."""
        cx, cy = e.center_x, e.center_y
        for w in self._walls_near(cx, cy, radius):
                inside_x = w.x < cx < w.x + w.w
                inside_y = w.y < cy < w.y + w.h
                if inside_x and inside_y:
                    # Teleport out the nearest edge.
                    d_left = cx - w.x
                    d_right = w.x + w.w - cx
                    d_bot = cy - w.y
                    d_top = w.y + w.h - cy
                    dmin = min(d_left, d_right, d_bot, d_top)
                    if dmin == d_left:
                        e.center_x = w.x - radius - 0.5
                        nx, ny = -1.0, 0.0
                    elif dmin == d_right:
                        e.center_x = w.x + w.w + radius + 0.5
                        nx, ny = 1.0, 0.0
                    elif dmin == d_bot:
                        e.center_y = w.y - radius - 0.5
                        nx, ny = 0.0, -1.0
                    else:
                        e.center_y = w.y + w.h + radius + 0.5
                        nx, ny = 0.0, 1.0
                else:
                    qx = max(w.x, min(cx, w.x + w.w))
                    qy = max(w.y, min(cy, w.y + w.h))
                    dx = cx - qx
                    dy = cy - qy
                    dist2 = dx * dx + dy * dy
                    if dist2 >= radius * radius:
                        continue
                    dist = math.sqrt(dist2) if dist2 > 0 else 0.001
                    nx = dx / dist if dist > 0.001 else 1.0
                    ny = dy / dist if dist > 0.001 else 0.0
                    pen = radius - dist + 0.5
                    e.center_x += nx * pen
                    e.center_y += ny * pen
                # Bounce velocity if the entity has one.
                vx = getattr(e, "vel_x", None)
                vy = getattr(e, "vel_y", None)
                if vx is not None and vy is not None:
                    v_dot_n = vx * nx + vy * ny
                    if v_dot_n < 0.0:
                        e.vel_x = vx - 2.0 * v_dot_n * nx
                        e.vel_y = vy - 2.0 * v_dot_n * ny
                return True
        return False

    def _generate(self, gv: GameView) -> None:
        self._mazes = generate_all_mazes(zone_seed=self._world_seed)
        self._rooms = []
        self._walls = []
        for m in self._mazes:
            self._rooms.extend(m.rooms)
            self._walls.extend(m.walls)
        self._build_wall_grid()
        # One spawner per maze, anchored at the maze centre.
        self._spawners = arcade.SpriteList()
        for i, m in enumerate(self._mazes):
            sp = MazeSpawner(m.spawner[0], m.spawner[1])
            sp.uid = i + 1   # uid 0 reserved for "unlinked"
            self._spawners.append(sp)

        # Pre-populate each spawner's maze with MAZE_SPAWNER_MAX_ALIVE
        # (20) aliens spread across the maze's rooms — one alien per
        # randomly-chosen room, with no repetition so the 20 aliens
        # spread evenly across the 25 rooms of the maze.  Uses a
        # dedicated RNG derived from the world seed so save/load is
        # deterministic.
        from constants import MAZE_SPAWNER_MAX_ALIVE
        prep_rng = random.Random(self._world_seed + 977)
        for sp, maze in zip(self._spawners, self._mazes):
            bounds = (maze.bounds.x, maze.bounds.y,
                      maze.bounds.w, maze.bounds.h)
            # Pick 20 distinct rooms; if we somehow have fewer than
            # 20 rooms, repeat rooms to reach the count.
            room_sample = list(maze.rooms)
            prep_rng.shuffle(room_sample)
            rooms_pick = room_sample[:MAZE_SPAWNER_MAX_ALIVE]
            while len(rooms_pick) < MAZE_SPAWNER_MAX_ALIVE:
                rooms_pick.append(prep_rng.choice(maze.rooms))
            for room in rooms_pick:
                ax = room.x + room.w / 2 + prep_rng.uniform(
                    -room.w / 4, room.w / 4)
                ay = room.y + room.h / 2 + prep_rng.uniform(
                    -room.h / 4, room.h / 4)
                alien = MazeAlien(
                    gv._alien_laser_tex, ax, ay,
                    world_w=self.world_width,
                    world_h=self.world_height,
                    patrol_home=(ax, ay),
                    patrol_radius=max(
                        80.0, room.w / 2.0 - 40.0),
                    maze_bounds=bounds,
                    rooms=maze.rooms,
                    room_graph=maze.room_graph,
                )
                self._maze_aliens.append(alien)
                self._alien_parent[alien] = sp.uid
                sp.alive_children += 1

        # Nebula-style population (asteroids, gas, wanderers, null
        # fields, slipspaces, four Z2 alien types) — same counts as
        # Zone 2, reject_fn keeps every candidate out of the four
        # maze AABBs (plus 40 px margin).
        from zones.nebula_shared import populate_nebula_content
        from constants import ASTEROID_RADIUS
        # Radii picked to keep each entity's full body outside the
        # maze AABB.  Gas sizes top out at 384 px (radius 192).
        populate_nebula_content(
            self, gv,
            reject_iron=self._maze_reject_fn(radius=ASTEROID_RADIUS),
            reject_big_iron=self._maze_reject_fn(
                radius=ASTEROID_RADIUS * 2.0),
            reject_copper=self._maze_reject_fn(radius=ASTEROID_RADIUS),
            reject_gas=self._maze_reject_fn(radius=192.0),
            reject_wanderers=self._maze_reject_fn(radius=30.0),
            reject_aliens=self._maze_reject_fn(radius=24.0),
            reject_null=self._maze_reject_fn(radius=100.0),
            reject_slip=self._maze_reject_fn(radius=60.0),
        )

    def teardown(self, gv: GameView) -> None:
        self._fog_grid = gv._fog_grid
        self._fog_revealed = gv._fog_revealed
        self._maze_projectiles.clear()
        self._alien_projectiles.clear()
        gv._wormholes.clear()
        gv._wormhole_list.clear()

    def _update_gas_damage(self, gv: GameView, dt: float) -> None:
        from zones.nebula_shared import update_gas_damage
        update_gas_damage(self, gv, dt)

    def _update_player_asteroid_collision(self, gv: GameView) -> None:
        from zones.nebula_shared import update_player_asteroid_collision
        update_player_asteroid_collision(self, gv)

    def _update_wanderer_collision(self, gv: GameView, dt: float) -> None:
        from zones.nebula_shared import update_wanderer_collision
        update_wanderer_collision(self, gv)

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        """Spawn the player OFFSET from the central wormhole so the
        very next update tick doesn't immediately transition them
        back to Zone 2.  Wormhole touch radius is 100 px; a 400 px
        offset keeps a safe margin even if the player was moving when
        they entered the zone."""
        cwx, cwy = self._central_wormhole_pos()
        # Offset south of the wormhole.  Ship spawn heading is up, so
        # the player faces the wormhole and can freely choose to
        # approach it or fly off to explore.
        return self._find_open_point(cwx, cwy - 400.0)

    def _central_wormhole_pos(self) -> tuple[float, float]:
        """World-space position of the central return wormhole.  Kept
        as a method so ``setup`` + ``get_player_spawn`` stay in sync."""
        return (self.world_width / 2, self.world_height / 2)

    def _find_open_point(self, cx: float, cy: float,
                         radius: float = 80.0) -> tuple[float, float]:
        for _ in range(120):
            if (not point_inside_any_room_interior(cx, cy, self._rooms)
                    and not circle_hits_any_wall(
                        cx, cy, radius, self._walls)):
                return cx, cy
            cx = self.world_width / 2 + random.uniform(-800, 800)
            cy = self.world_height / 2 + random.uniform(-800, 800)
        return self.world_width / 2, self.world_height / 2

    # ── Per-frame update ────────────────────────────────────────────

    def update(self, gv: GameView, dt: float) -> None:
        from zones.zone2_world import handle_projectile_hits, try_respawn
        from collisions import resolve_overlap, reflect_velocity
        from constants import (
            ALIEN_ASTEROID_DAMAGE, ALIEN_COL_COOLDOWN,
        )

        px = gv.player.center_x
        py = gv.player.center_y
        self._update_fog(gv)

        # Wormhole collision.
        for wh in gv._wormholes:
            wh.update_wormhole(dt)
            if math.hypot(px - wh.center_x, py - wh.center_y) < 100:
                gv._use_glow = (100, 180, 255, 200)
                gv._use_glow_timer = 0.5
                arcade.play_sound(gv._victory_snd, volume=0.6)
                target = (wh.zone_target if wh.zone_target is not None
                          else ZoneID.ZONE2)
                from zones import welcome_message_for
                msg = welcome_message_for(target)
                if msg is None:
                    msg = "Returning through wormhole..."
                gv._flash_game_msg(msg, 1.5)
                gv._transition_zone(target, entry_side="wormhole_return")
                return

        # Route shared GameView alien + alien-projectile lists at the
        # Nebula-style population so the reused helpers operate on
        # the right entities.  Maze aliens use their own lists.
        gv.alien_list = self._aliens
        gv.alien_projectile_list = self._alien_projectiles

        # Asteroid rotation tick — cull to a box around the player
        # so 165 asteroids at a 12000x12000 zone don't all rotate
        # every frame when the player's looking at one corner.
        # Matches Zone 2's _CULL_MARGIN pattern.
        try:
            _win = arcade.get_window()
            _hw = _win.width / 2
            _hh = _win.height / 2
        except Exception:
            _hw, _hh = 640.0, 400.0
        _margin = 350.0
        _vx0 = px - _hw - _margin
        _vx1 = px + _hw + _margin
        _vy0 = py - _hh - _margin
        _vy1 = py + _hh + _margin
        for a in self._iron_asteroids:
            if _vx0 < a.center_x < _vx1 and _vy0 < a.center_y < _vy1:
                a.update_asteroid(dt)
        for a in self._double_iron:
            if _vx0 < a.center_x < _vx1 and _vy0 < a.center_y < _vy1:
                a.update_asteroid(dt)
        for a in self._copper_asteroids:
            if _vx0 < a.center_x < _vx1 and _vy0 < a.center_y < _vy1:
                a.update_asteroid(dt)

        # Gas damage + wanderer collision.
        self._update_gas_damage(gv, dt)
        for w in self._wanderers:
            w.update_wandering(dt, px, py)
        self._update_wanderer_collision(gv, dt)
        self._update_player_asteroid_collision(gv)

        # Null field timers + slipspace rotation are advanced globally
        # in game_view.on_update via _ul.update_null_fields /
        # update_slipspaces (which already walk the active zone's
        # _null_fields / _slipspaces lists).  Don't double-tick here.

        # Z2 alien AI + projectile fire.
        for alien in list(self._aliens):
            fired = alien.update_alien(
                dt, px, py, self._iron_asteroids, self._aliens,
                force_walls=gv._force_walls)
            for proj in fired:
                self._alien_projectiles.append(proj)

        # Advance Nebula-alien projectiles, block them at maze
        # walls, and damage the player on contact.  Without the
        # advance call these projectiles stayed on screen forever
        # (no range-exhaust check ever ran).
        self._advance_alien_projectiles(gv, dt)

        # Player-projectile-vs-Nebula-entity collisions.
        handle_projectile_hits(self, gv)

        # Z2 alien ↔ player + alien ↔ asteroid collisions (shared).
        from zones.nebula_shared import (
            update_player_z2_alien_collision,
            update_alien_asteroid_collisions,
        )
        update_player_z2_alien_collision(self, gv)
        update_alien_asteroid_collisions(self, gv)

        # Nebula population containment — push any wanderer or Z2
        # alien that drifted into a maze wall back out along the
        # contact normal.  Runs every frame since wanderers are the
        # worst offender (they move randomly).
        self._push_out_of_walls(self._wanderers, WANDERING_RADIUS)
        self._push_out_of_walls(self._aliens, 20.0)
        # Maze-AABB containment for Z2 aliens + wanderers — wall
        # push-out alone lets a determined alien slip through the
        # entrance gap (which is room-width wide).  Push them back
        # out toward the nearest maze edge along the shortest axis.
        self._push_out_of_maze_bounds(self._aliens, 20.0)
        self._push_out_of_maze_bounds(self._wanderers, WANDERING_RADIUS)

        # Maze-specific entities.
        self._update_spawners(gv, dt, px, py)
        self._update_maze_aliens(gv, dt, px, py)
        self._update_player_maze_alien_collision(gv)
        self._update_maze_projectiles(gv, dt)
        self._handle_maze_projectiles_vs_player(gv)
        self._block_player_projectiles_at_walls(gv)
        self._block_missiles_at_walls(gv)
        self._handle_player_projectile_hits(gv)
        self._update_spawner_physical_collision(gv)
        self._update_player_wall_collision(gv)
        self._reconcile_dead_aliens()

        # Respawn Nebula content on the Zone 2 cadence.  Maze
        # spawners stay dead or self-respawn on their own timer.
        self._respawn_timer += dt
        if self._respawn_timer >= RESPAWN_INTERVAL:
            self._respawn_timer = 0.0
            try_respawn(self, gv)
            self._rebuild_shielded_list()

    def _update_fog(self, gv: GameView) -> None:
        px, py = gv.player.center_x, gv.player.center_y
        cx = int(px / self._fog_cell)
        cy = int(py / self._fog_cell)
        r = int(self._fog_reveal_r / self._fog_cell) + 1
        for gy in range(max(0, cy - r), min(self._fog_h, cy + r + 1)):
            for gx in range(max(0, cx - r), min(self._fog_w, cx + r + 1)):
                if not self._fog_grid[gy][gx]:
                    cell_cx = (gx + 0.5) * self._fog_cell
                    cell_cy = (gy + 0.5) * self._fog_cell
                    if math.hypot(px - cell_cx,
                                  py - cell_cy) <= self._fog_reveal_r:
                        self._fog_grid[gy][gx] = True
                        self._fog_revealed += 1
                        gv._fog_revealed = self._fog_revealed

    # ── Spawner / maze-alien loop ───────────────────────────────────

    def _update_spawners(self, gv: GameView, dt: float,
                         px: float, py: float) -> None:
        # Note: update_spawner still needs to run on killed spawners
        # so its respawn cooldown ticks down — the spawner
        # self-resurrects inside update_spawner when the timer hits
        # zero.  When the player is cloaked by a null field, pass the
        # synthetic far-away position so spawners stop detecting +
        # firing; their spawn cadence still ticks so the maze stays
        # populated when the player uncloaks.
        from update_logic import player_is_cloaked
        if player_is_cloaked(gv):
            ai_px, ai_py = px + 1e9, py + 1e9
        else:
            ai_px, ai_py = px, py
        for sp in self._spawners:
            fired, should_spawn = sp.update_spawner(
                dt, ai_px, ai_py, gv._alien_laser_tex)
            for proj in fired:
                self._maze_projectiles.append(proj)
            if should_spawn:
                self._spawn_child(sp, gv._alien_laser_tex)

    def _spawn_child(self, sp: MazeSpawner,
                     laser_tex: arcade.Texture) -> None:
        """Emit one MazeAlien near the spawner's centre room.  Patrol
        radius is scoped to one room (not the whole maze) so
        waypoints stay reachable without walking through walls.
        The maze AABB is passed through so the alien is hard-bounded
        from leaving its home maze."""
        from constants import STAR_MAZE_ROOM_SIZE
        maze = self._maze_for_spawner(sp)
        if maze is not None:
            ax, ay = self._find_maze_interior_point(sp)
            home_xy = (ax, ay)
            bounds = (maze.bounds.x, maze.bounds.y,
                      maze.bounds.w, maze.bounds.h)
        else:
            home_xy = (sp.center_x, sp.center_y)
            ax = sp.center_x
            ay = sp.center_y + MAZE_ALIEN_RADIUS * 2 + 4
            bounds = None
        patrol_r = max(80.0, STAR_MAZE_ROOM_SIZE / 2.0 - 40.0)
        alien = MazeAlien(
            laser_tex, ax, ay,
            world_w=self.world_width,
            world_h=self.world_height,
            patrol_home=home_xy,
            patrol_radius=patrol_r,
            maze_bounds=bounds,
            rooms=maze.rooms if maze is not None else None,
            room_graph=maze.room_graph if maze is not None else None,
        )
        self._maze_aliens.append(alien)
        self._alien_parent[alien] = sp.uid
        sp.alive_children += 1

    def _maze_for_spawner(self, sp: MazeSpawner) -> MazeLayout | None:
        """Return the MazeLayout whose centre matches ``sp``'s
        position.  Uses the spawner's uid (1-indexed) to index into
        ``self._mazes`` — O(1) instead of a position search."""
        idx = sp.uid - 1
        if 0 <= idx < len(self._mazes):
            return self._mazes[idx]
        return None

    def _find_maze_interior_point(
        self, sp: MazeSpawner,
    ) -> tuple[float, float]:
        """Pick a free point within a short radius of the spawner."""
        for _ in range(40):
            ax = sp.center_x + random.uniform(-120.0, 120.0)
            ay = sp.center_y + random.uniform(-120.0, 120.0)
            if not circle_hits_any_wall(
                    ax, ay, MAZE_ALIEN_RADIUS + 4, self._walls):
                return ax, ay
        return sp.center_x, sp.center_y

    def _update_maze_aliens(self, gv: GameView, dt: float,
                            px: float, py: float) -> None:
        """Tick every MazeAlien.  Culls AI work for aliens far from
        the player — they don't fire, avoid, or reroute while
        offscreen, which saves ~80 maze-wall AABB checks per frame
        in the typical far-corner case."""
        empty_asteroids = self._empty_asteroid_list
        try:
            _win = arcade.get_window()
            _hw = _win.width / 2
            _hh = _win.height / 2
        except Exception:
            _hw, _hh = 640.0, 400.0
        _margin = 400.0
        _vx0 = px - _hw - _margin
        _vx1 = px + _hw + _margin
        _vy0 = py - _hh - _margin
        _vy1 = py + _hh + _margin
        # Spatial-hash the maze walls to the alien's neighbourhood.
        # Full-list scan was 20 aliens × 120 walls × 5 iters = 12k
        # AABB tests per frame and was the biggest near-maze hit.
        from constants import MAZE_ALIEN_RADIUS as _MAR
        from update_logic import player_is_cloaked
        query_r = _MAR + 40.0
        # Null-field cloak — when the player is inside an active null
        # field, feed the maze aliens a synthetic player position far
        # outside detect range so they stay in PATROL and stop firing.
        # Same pattern Zone 2 uses for its Nebula aliens.
        if player_is_cloaked(gv):
            ai_px, ai_py = px + 1e9, py + 1e9
        else:
            ai_px, ai_py = px, py
        for alien in list(self._maze_aliens):
            if not (_vx0 < alien.center_x < _vx1
                    and _vy0 < alien.center_y < _vy1):
                continue
            near_walls = self._walls_near(
                alien.center_x, alien.center_y, query_r)
            fired = alien.update_alien(
                dt, ai_px, ai_py, empty_asteroids, self._maze_aliens,
                force_walls=gv._force_walls,
                maze_walls=near_walls,
            )
            for proj in fired:
                self._maze_projectiles.append(proj)
        # Expose maze aliens + their projectiles on the shared lists
        # so the existing player-hit pipelines process them uniformly.
        gv.alien_list = self._maze_aliens
        gv.alien_projectile_list = self._maze_projectiles

    def _update_maze_projectiles(self, gv: GameView, dt: float) -> None:
        prevs: list[tuple] = []
        for proj in list(self._maze_projectiles):
            prevs.append((proj, proj.center_x, proj.center_y))
        for proj in list(self._maze_projectiles):
            proj.update_projectile(dt)
        for (proj, pprev_x, pprev_y) in prevs:
            if not proj.sprite_lists:
                continue   # already auto-removed by range cap
            if self._segment_hits_wall_fast(
                    pprev_x, pprev_y, proj.center_x, proj.center_y):
                proj.remove_from_sprite_lists()

    def _handle_maze_projectiles_vs_player(self, gv: GameView) -> None:
        """Apply damage when a maze alien / spawner projectile hits
        the player.  Zone 2 handles this inline in its update loop;
        the Star Maze mirrors that pattern so the generic
        ``handle_alien_laser_hits`` isn't needed."""
        for proj in arcade.check_for_collision_with_list(
                gv.player, self._maze_projectiles):
            gv._apply_damage_to_player(int(proj.damage))
            gv._trigger_shake()
            proj.remove_from_sprite_lists()

    def _block_player_projectiles_at_walls(self, gv: GameView) -> None:
        """Remove any player projectile (laser / mining beam / boss
        cannon echo) that has crossed a maze wall this tick.  Uses
        the segment-vs-AABB helper like the maze-projectile check so
        fast projectiles don't tunnel."""
        for proj in list(gv.projectile_list):
            # The projectile's current position — ``update_projectile``
            # has already advanced it this frame.  We approximate the
            # pre-advance position with one tick's worth of velocity.
            dt_back = 1.0 / 60.0
            prev_x = proj.center_x - getattr(proj, "_vx", 0.0) * dt_back
            prev_y = proj.center_y - getattr(proj, "_vy", 0.0) * dt_back
            if self._segment_hits_wall_fast(
                    prev_x, prev_y, proj.center_x, proj.center_y):
                proj.remove_from_sprite_lists()

    def _advance_alien_projectiles(self, gv: GameView, dt: float) -> None:
        """Advance Nebula-alien laser shots, apply damage to the
        player on contact, and remove any that crossed a maze wall.
        Zone 2's update handles this inline; the Star Maze has to
        mirror it because the generic handle_alien_laser_hits isn't
        invoked in non-MAIN zones.
        """
        # Snapshot pre-advance positions for segment-vs-wall check.
        prevs: list[tuple] = []
        for proj in list(self._alien_projectiles):
            prevs.append((proj, proj.center_x, proj.center_y))
        for proj in list(self._alien_projectiles):
            proj.update_projectile(dt)
        # Wall block + player hit.
        for (proj, pprev_x, pprev_y) in prevs:
            if not proj.sprite_lists:
                continue   # already auto-removed by range cap
            if self._segment_hits_wall_fast(
                    pprev_x, pprev_y, proj.center_x, proj.center_y):
                proj.remove_from_sprite_lists()
        # Player collision — same inline pattern Zone 2 uses.
        for proj in arcade.check_for_collision_with_list(
                gv.player, self._alien_projectiles):
            gv._apply_damage_to_player(int(proj.damage))
            gv._trigger_shake()
            proj.remove_from_sprite_lists()

    def _block_missiles_at_walls(self, gv: GameView) -> None:
        """Remove any homing missile that's currently inside a maze
        wall.  Missiles move ~7 px/frame at 60 fps vs a 32 px thick
        wall, so a point-in-AABB check catches them reliably without
        the segment approximation used for lasers."""
        missiles = getattr(gv, "_missile_list", None)
        if not missiles:
            return
        for m in list(missiles):
            if self._point_in_any_wall_fast(m.center_x, m.center_y):
                m.remove_from_sprite_lists()

    def _update_player_maze_alien_collision(self, gv: GameView) -> None:
        """Bounce + damage the player on contact with maze aliens.
        Mirrors the Z2 alien-vs-player block already in update() so
        maze aliens don't phase through the ship."""
        from collisions import resolve_overlap
        for alien in arcade.check_for_collision_with_list(
                gv.player, self._maze_aliens):
            contact = resolve_overlap(
                alien, gv.player, MAZE_ALIEN_RADIUS, SHIP_RADIUS,
                push_a=0.5, push_b=0.5)
            if contact is None:
                continue
            nx, ny = contact
            alien.vel_x += nx * 150
            alien.vel_y += ny * 150
            dot = gv.player.vel_x * (-nx) + gv.player.vel_y * (-ny)
            if dot < 0:
                gv.player.vel_x -= (1 + ALIEN_BOUNCE) * dot * (-nx) * 0.4
                gv.player.vel_y -= (1 + ALIEN_BOUNCE) * dot * (-ny) * 0.4
            if gv.player._collision_cd <= 0.0:
                gv._apply_damage_to_player(5)
                gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                gv._trigger_shake()
                arcade.play_sound(gv._bump_snd, volume=0.3)

    def _update_spawner_physical_collision(self, gv: GameView) -> None:
        """Physically block the player ship from passing through a
        live spawner (its own collision layer — alien collision
        pipelines don't touch spawners).  Killed spawners are
        phase-through so the player can pick their way past husks."""
        player = gv.player
        r_ship = SHIP_RADIUS
        for sp in self._spawners:
            if sp.killed:
                continue
            r_total = r_ship + sp.radius
            dx = player.center_x - sp.center_x
            dy = player.center_y - sp.center_y
            dist2 = dx * dx + dy * dy
            if dist2 >= r_total * r_total:
                continue
            dist = math.sqrt(dist2) if dist2 > 0 else 0.001
            nx = dx / dist if dist > 0.001 else 1.0
            ny = dy / dist if dist > 0.001 else 0.0
            pen = r_total - dist
            player.center_x += nx * pen
            player.center_y += ny * pen
            v_dot_n = player.vel_x * nx + player.vel_y * ny
            if v_dot_n < 0.0:
                player.vel_x -= (1.0 + SHIP_BOUNCE) * v_dot_n * nx * 0.5
                player.vel_y -= (1.0 + SHIP_BOUNCE) * v_dot_n * ny * 0.5
            if player._collision_cd <= 0.0:
                player._collision_cd = SHIP_COLLISION_COOLDOWN
                gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                gv._trigger_shake()
                arcade.play_sound(gv._bump_snd, volume=0.3)

    def _update_player_wall_collision(self, gv: GameView) -> None:
        """Push the player back out along the contact normal and
        reflect velocity with dampening whenever they overlap a wall."""
        player = gv.player
        r = SHIP_RADIUS
        for w in self._walls_near(player.center_x, player.center_y, r):
            qx = max(w.x, min(player.center_x, w.x + w.w))
            qy = max(w.y, min(player.center_y, w.y + w.h))
            dx = player.center_x - qx
            dy = player.center_y - qy
            dist2 = dx * dx + dy * dy
            if dist2 >= r * r:
                continue
            dist = math.sqrt(dist2) if dist2 > 0 else 0.001
            nx = dx / dist if dist > 0.001 else 1.0
            ny = dy / dist if dist > 0.001 else 0.0
            pen = r - dist
            player.center_x += nx * pen
            player.center_y += ny * pen
            v_dot_n = player.vel_x * nx + player.vel_y * ny
            if v_dot_n < 0.0:
                player.vel_x -= (1.0 + SHIP_BOUNCE) * v_dot_n * nx * 0.5
                player.vel_y -= (1.0 + SHIP_BOUNCE) * v_dot_n * ny * 0.5
            if player._collision_cd <= 0.0:
                player._collision_cd = SHIP_COLLISION_COOLDOWN
                gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                gv._trigger_shake()
                arcade.play_sound(gv._bump_snd, volume=0.3)

    # ── Combat: player projectiles vs maze entities ─────────────────

    def _handle_player_projectile_hits(self, gv: GameView) -> None:
        from collisions import _apply_kill_rewards
        from character_data import bonus_iron_enemy
        from constants import BLUEPRINT_DROP_CHANCE_ALIEN
        from sprites.explosion import HitSpark

        for proj in list(gv.projectile_list):
            if getattr(proj, "mines_rock", False):
                continue
            hit_something = False
            for sp in self._spawners:
                if sp.killed:
                    continue
                if math.hypot(sp.center_x - proj.center_x,
                              sp.center_y - proj.center_y) <= sp.radius + 4:
                    sp.take_damage(int(proj.damage))
                    gv.hit_sparks.append(HitSpark(
                        proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    if sp.killed:
                        _apply_kill_rewards(
                            gv, sp.center_x, sp.center_y,
                            MAZE_SPAWNER_IRON_DROP, bonus_iron_enemy,
                            0.0, xp=MAZE_SPAWNER_XP)
                    hit_something = True
                    break
            if hit_something:
                continue
            for alien in list(self._maze_aliens):
                if math.hypot(alien.center_x - proj.center_x,
                              alien.center_y - proj.center_y) <= (
                        MAZE_ALIEN_RADIUS + 4):
                    alien.take_damage(int(proj.damage))
                    gv.hit_sparks.append(HitSpark(
                        proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    if alien.hp <= 0:
                        _apply_kill_rewards(
                            gv, alien.center_x, alien.center_y,
                            MAZE_ALIEN_IRON_DROP, bonus_iron_enemy,
                            BLUEPRINT_DROP_CHANCE_ALIEN,
                            xp=MAZE_ALIEN_XP)
                        self._on_maze_alien_killed(alien)
                        alien.remove_from_sprite_lists()
                    break

    def _reconcile_dead_aliens(self) -> None:
        live = set(self._maze_aliens)
        stale = [a for a in self._alien_parent if a not in live]
        for a in stale:
            self._on_maze_alien_killed(a)

    def _on_maze_alien_killed(self, alien: MazeAlien) -> None:
        parent_uid = self._alien_parent.pop(alien, 0)
        if parent_uid:
            for sp in self._spawners:
                if sp.uid == parent_uid:
                    sp.alive_children = max(0, sp.alive_children - 1)
                    break

    # ── Drawing ─────────────────────────────────────────────────────

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        # Gas first so asteroids draw on top (matches Zone 2 order).
        self._gas_areas.draw()
        self._iron_asteroids.draw()
        self._double_iron.draw()
        self._copper_asteroids.draw()
        self._wanderers.draw()
        self._slipspaces.draw()
        # Null fields are drawn globally via draw_logic._draw_null_fields
        # (batched into 2 draw_points calls).  We do NOT redraw them
        # here — the per-field nf.draw() path issued 28 immediate-mode
        # circles per visible field, which spiked frames hard whenever
        # the player parked inside one.
        # Maze walls on top of the terrain so they clearly occlude.
        if self._wall_sprite_list is not None:
            self._wall_sprite_list.draw()
        self._spawners.draw()
        # Zone 2 aliens + their shield overlays (cull to view rect).
        self._aliens.draw()
        m = 250.0
        vx0 = cx - hw - m
        vx1 = cx + hw + m
        vy0 = cy - hh - m
        vy1 = cy + hh + m
        for alien in self._shielded_aliens:
            if vx0 < alien.center_x < vx1 and vy0 < alien.center_y < vy1:
                alien.draw_shield()
        self._alien_projectiles.draw()
        # Maze aliens + maze projectiles.
        self._maze_aliens.draw()
        self._maze_projectiles.draw()
        if gv._wormholes:
            gv._wormhole_list.draw()
        if len(gv.building_list) > 0:
            gv.building_list.draw()
        gv.turret_projectile_list.draw()
        gv.iron_pickup_list.draw()
        gv.blueprint_pickup_list.draw()

    # ── Save/load ───────────────────────────────────────────────────

    def to_save_data(self) -> dict:
        return {
            "seed": self._world_seed,
            "populated": self._populated,
            "spawners": [sp.to_save_data() for sp in self._spawners],
        }

    def from_save_data(self, data: dict, gv: GameView) -> None:
        seed = data.get("seed")
        if seed is not None:
            self._world_seed = int(seed)
        self._populated = bool(data.get("populated", False))
        if self._populated:
            self._generate(gv)
            spawner_data = data.get("spawners", [])
            for sp, sd in zip(self._spawners, spawner_data):
                sp.from_save_data(sd)

    # ── Geometry accessors (tests + minimap) ────────────────────────

    @property
    def rooms(self) -> list[Rect]:
        return self._rooms

    @property
    def walls(self) -> list[Rect]:
        return self._walls

    @property
    def spawners(self) -> arcade.SpriteList:
        return self._spawners

    @property
    def mazes(self) -> list[MazeLayout]:
        return self._mazes
