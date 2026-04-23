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

    # ── Setup / teardown ────────────────────────────────────────────

    def setup(self, gv: GameView) -> None:
        if not self._populated:
            self._generate(gv)
            self._populated = True
        self._wall_sprite_list = _build_wall_sprites(self._walls)

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

    def _generate(self, gv: GameView) -> None:
        self._mazes = generate_all_mazes(zone_seed=self._world_seed)
        self._rooms = []
        self._walls = []
        for m in self._mazes:
            self._rooms.extend(m.rooms)
            self._walls.extend(m.walls)
        # One spawner per maze, anchored at the maze centre.
        self._spawners = arcade.SpriteList()
        for i, m in enumerate(self._mazes):
            sp = MazeSpawner(m.spawner[0], m.spawner[1])
            sp.uid = i + 1   # uid 0 reserved for "unlinked"
            self._spawners.append(sp)

    def teardown(self, gv: GameView) -> None:
        self._fog_grid = gv._fog_grid
        self._fog_revealed = gv._fog_revealed
        self._maze_projectiles.clear()
        gv._wormholes.clear()
        gv._wormhole_list.clear()

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

        self._update_spawners(gv, dt, px, py)
        self._update_maze_aliens(gv, dt, px, py)
        self._update_maze_projectiles(gv, dt)
        self._handle_player_projectile_hits(gv)
        self._update_player_wall_collision(gv)
        self._reconcile_dead_aliens()

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
        for sp in self._spawners:
            if sp.killed:
                continue
            fired, should_spawn = sp.update_spawner(
                dt, px, py, gv._alien_laser_tex)
            for proj in fired:
                self._maze_projectiles.append(proj)
            if should_spawn:
                self._spawn_child(sp, gv._alien_laser_tex)

    def _spawn_child(self, sp: MazeSpawner,
                     laser_tex: arcade.Texture) -> None:
        """Emit one MazeAlien near the spawner's centre room."""
        maze = self._maze_for_spawner(sp)
        if maze is not None:
            home_xy = maze.spawner
            patrol_r = maze.bounds.w / 2 - 100.0
            ax, ay = self._find_maze_interior_point(sp)
        else:
            home_xy = (sp.center_x, sp.center_y)
            patrol_r = 400.0
            ax = sp.center_x
            ay = sp.center_y + MAZE_ALIEN_RADIUS * 2 + 4
        alien = MazeAlien(
            laser_tex, ax, ay,
            world_w=self.world_width,
            world_h=self.world_height,
            patrol_home=home_xy,
            patrol_radius=patrol_r,
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
        empty_asteroids = arcade.SpriteList()
        for alien in list(self._maze_aliens):
            fired = alien.update_alien(
                dt, px, py, empty_asteroids, self._maze_aliens,
                force_walls=gv._force_walls,
                maze_walls=self._walls,
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
            if segment_hits_any_wall(
                    pprev_x, pprev_y, proj.center_x, proj.center_y,
                    self._walls):
                proj.remove_from_sprite_lists()

    def _update_player_wall_collision(self, gv: GameView) -> None:
        """Push the player back out along the contact normal and
        reflect velocity with dampening whenever they overlap a wall."""
        player = gv.player
        r = SHIP_RADIUS
        for w in self._walls:
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
        if self._wall_sprite_list is not None:
            self._wall_sprite_list.draw()
        self._spawners.draw()
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
