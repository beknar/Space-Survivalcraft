"""Star Maze — post-Nebula-boss zone filled with dungeon-wall rooms.

Layout: ``STAR_MAZE_WIDTH × STAR_MAZE_HEIGHT`` field with 81 rooms on
a 9×9 grid (~31 % coverage, equally spaced per spec).  Each room has
two door openings and hides a ``MazeSpawner`` at its centre; the
spawner drips ``MazeAlien``s out through the doors on a 30 s cadence
while firing a 30-damage laser at the player.

The Star Maze inherits "all the other properties of the Nebula zone"
outside the maze rooms — asteroids, gas, null fields, wanderers,
slipspaces.  That open-world population is layered in on top of the
maze skeleton via the Zone 2 helpers, with a position filter that
rejects any candidate spawn sitting inside a room AABB.

This file owns the skeleton + per-frame loop; full Zone 2-style
population lands in a follow-up commit so the core maze mechanic is
in gameplay first.
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
    COPPER_ASTEROID_PNG, COPPER_PICKUP_PNG, Z2_ALIEN_SHIP_PNG,
    GAS_AREA_DAMAGE, GAS_AREA_SLOW,
    WANDERING_DAMAGE, WANDERING_RADIUS,
    ASTEROID_RADIUS, ALIEN_BOUNCE,
    RESPAWN_INTERVAL,
)
from zones import ZoneID, ZoneState
from zones.maze_geometry import (
    Rect, room_rects, all_wall_rects,
    circle_hits_any_wall, segment_hits_any_wall,
    point_inside_any_room_interior,
)
from sprites.wormhole import Wormhole
from sprites.maze_alien import MazeAlien
from sprites.maze_spawner import MazeSpawner

if TYPE_CHECKING:
    from game_view import GameView


# ── Module-level texture caches ─────────────────────────────────────
#
# Generated once per process.  The dungeon sheet is 336 × 184 px of
# 16 × 16 tiles; we pick a single "wall" tile at column 1, row 0 as
# the repeating texture for every wall segment.  If the user later
# wants per-edge-type tiles (corners, doorways, etc.) this is where
# to plug that in.
_WALL_TILE_TEX: arcade.Texture | None = None


def _load_wall_tile() -> arcade.Texture:
    global _WALL_TILE_TEX
    if _WALL_TILE_TEX is None:
        from PIL import Image as _PILImage
        sheet = _PILImage.open(DUNGEON_WALL_SHEET_PNG).convert("RGBA")
        tile = sheet.crop((
            STAR_MAZE_WALL_TILE * 1,
            0,
            STAR_MAZE_WALL_TILE * 2,
            STAR_MAZE_WALL_TILE,
        ))
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
    """The Star Maze."""
    zone_id = ZoneID.STAR_MAZE
    world_width = STAR_MAZE_WIDTH
    world_height = STAR_MAZE_HEIGHT

    def __init__(self) -> None:
        self._world_seed: int = random.randint(0, 2**31 - 1)
        self._populated: bool = False
        # Maze geometry.
        self._rooms: list[Rect] = []
        self._walls: list[Rect] = []
        # Draw lists.
        self._wall_sprite_list: arcade.SpriteList | None = None
        # Maze-specific entities.  ``_spawners`` is a SpriteList so
        # draw_world() can render all 25 in one GL call.  Killed
        # spawners stay in the list (their husk sprite makes a nice
        # "this room is clear" cue); their ``killed`` flag gates
        # production + projectile fire.
        self._spawners: arcade.SpriteList = arcade.SpriteList()
        self._maze_aliens: arcade.SpriteList = arcade.SpriteList()
        self._maze_projectiles: arcade.SpriteList = arcade.SpriteList()
        # Nebula-style population — identical counts + types to Zone 2,
        # but all placed with a maze-room reject filter so nothing
        # spawns inside a maze AABB.  Attribute names match Zone 2 so
        # the shared ``zone2_world`` helpers (populate_*, handle_
        # projectile_hits, try_respawn) can be reused.
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
        # Spawner child bookkeeping — map alien instance -> parent uid
        # so when an alien dies we can decrement the spawner's count.
        self._alien_parent: dict[MazeAlien, int] = {}

    # ── Setup / teardown ────────────────────────────────────────────

    def setup(self, gv: GameView) -> None:
        self._load_textures(gv)
        if not self._populated:
            self._generate(gv)
            self._populated = True
        self._wall_sprite_list = _build_wall_sprites(self._walls)
        self._rebuild_shielded_list()

        # Central wormhole back to Zone 2 as the safety exit.
        cx, cy = self._find_open_point(
            self.world_width / 2, self.world_height / 2)
        wh = Wormhole(cx, cy)
        wh.zone_target = ZoneID.ZONE2
        gv._wormholes = [wh]
        gv._wormhole_list.clear()
        gv._wormhole_list.append(wh)
        # Four corner wormholes chaining to the Star-Maze-launched
        # 2x-danger warp variants.  Exits from those variants loop
        # back to the Star Maze (see WarpZoneBase routing).
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

        # Share fog grid with GameView for the minimap.
        gv._fog_grid = self._fog_grid
        gv._fog_revealed = self._fog_revealed

    def _load_textures(self, gv: GameView) -> None:
        """Load the same texture set Zone 2 uses so the shared
        population + handler helpers work unmodified."""
        from PIL import Image as _PILImage
        self._iron_tex = gv._asteroid_tex
        if self._copper_tex is None:
            self._copper_tex = arcade.load_texture(COPPER_ASTEROID_PNG)
        if self._copper_pickup_tex is None:
            self._copper_pickup_tex = arcade.load_texture(COPPER_PICKUP_PNG)
        self._alien_laser_tex = gv._alien_laser_tex
        if not self._alien_textures:
            from sprites.zone2_aliens import ALIEN_CROPS
            pil = _PILImage.open(Z2_ALIEN_SHIP_PNG).convert("RGBA")
            for name, crop in ALIEN_CROPS.items():
                self._alien_textures[name] = arcade.Texture(pil.crop(crop))
            pil.close()
        self._wanderer_tex = self._iron_tex

    def _rebuild_shielded_list(self) -> None:
        from sprites.zone2_aliens import ShieldedAlien
        self._shielded_aliens = [
            a for a in self._aliens if isinstance(a, ShieldedAlien)]

    def _maze_reject_fn(self):
        """Factory for the Nebula-population reject filter: reject any
        candidate position inside a maze-room AABB plus a 40 px margin
        so hazards don't spawn flush against a wall from outside."""
        rooms = self._rooms
        def _reject(x: float, y: float) -> bool:
            return point_inside_any_room_interior(x, y, rooms, margin=40)
        return _reject

    def _generate(self, gv: GameView) -> None:
        self._rooms = room_rects()
        self._walls = all_wall_rects(self._rooms, zone_seed=self._world_seed)
        # One spawner per room.
        self._spawners = arcade.SpriteList()
        for i, room in enumerate(self._rooms):
            sp = MazeSpawner(
                room.x + room.w / 2,
                room.y + room.h / 2,
            )
            sp.uid = i + 1   # uid 0 reserved for "unlinked"
            self._spawners.append(sp)
        # Nebula-style population — same counts as Zone 2, reject
        # filter keeps everything out of maze rooms.
        from zones.zone2_world import (
            populate_iron_asteroids, populate_double_iron,
            populate_copper_asteroids, populate_gas_areas,
            populate_wanderers, populate_aliens,
        )
        from world_setup import populate_null_fields, populate_slipspaces
        reject = self._maze_reject_fn()
        random.seed(self._world_seed)
        populate_iron_asteroids(self, reject_fn=reject)
        populate_double_iron(self, reject_fn=reject)
        populate_copper_asteroids(self, reject_fn=reject)
        populate_gas_areas(self, reject_fn=reject)
        self._gas_pos_cache = [(g.center_x, g.center_y, g.radius)
                               for g in self._gas_areas]
        populate_wanderers(self, reject_fn=reject)
        populate_aliens(self, reject_fn=reject)
        self._null_fields = populate_null_fields(
            self.world_width, self.world_height,
            reject_fn=reject)
        ss_rng = random.Random(self._world_seed + 197)
        self._slipspaces = populate_slipspaces(
            self.world_width, self.world_height,
            gv._slipspace_tex, rng=ss_rng, reject_fn=reject)
        random.seed()

    def teardown(self, gv: GameView) -> None:
        # Save fog state back from GameView.
        self._fog_grid = gv._fog_grid
        self._fog_revealed = gv._fog_revealed
        self._alien_projectiles.clear()
        self._maze_projectiles.clear()
        gv._wormholes.clear()
        gv._wormhole_list.clear()

    def _update_gas_damage(self, gv: GameView, dt: float) -> None:
        self._gas_damage_cd = max(0.0, self._gas_damage_cd - dt)
        px, py = gv.player.center_x, gv.player.center_y
        in_gas = False
        for g in self._gas_areas:
            if g.contains_point(px, py):
                in_gas = True
                if self._gas_damage_cd <= 0.0:
                    gv._apply_damage_to_player(int(GAS_AREA_DAMAGE))
                    gv._trigger_shake()
                    gv._flash_game_msg("Toxic gas!", 0.5)
                    self._gas_damage_cd = 1.0
                break
        if in_gas:
            gv.player.vel_x *= GAS_AREA_SLOW ** (dt * 60)
            gv.player.vel_y *= GAS_AREA_SLOW ** (dt * 60)

    def _update_wanderer_collision(self, gv: GameView, dt: float) -> None:
        from collisions import resolve_overlap, reflect_velocity
        if gv.player._collision_cd > 0.0:
            return
        for w in arcade.check_for_collision_with_list(
                gv.player, self._wanderers):
            contact = resolve_overlap(
                gv.player, w, SHIP_RADIUS, WANDERING_RADIUS,
                push_a=0.6, push_b=0.4)
            if contact is None:
                continue
            nx, ny = contact
            reflect_velocity(gv.player, nx, ny, SHIP_BOUNCE)
            w._wander_angle = math.atan2(-ny, -nx)
            w._wander_timer = 1.5
            w._repel_timer = 2.0
            gv._apply_damage_to_player(WANDERING_DAMAGE)
            gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.4)
            break

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        # Default entry from a corner wormhole — drop the player at
        # the centre of the zone where the return wormhole lives.
        return self._find_open_point(
            self.world_width / 2, self.world_height / 2)

    def _find_open_point(self, cx: float, cy: float,
                         radius: float = 80.0) -> tuple[float, float]:
        """Return a point near ``(cx, cy)`` that isn't inside a maze
        room or a wall.  Falls back to the input if no clear spot is
        found after 120 attempts."""
        for _ in range(120):
            if (not point_inside_any_room_interior(cx, cy, self._rooms)
                    and not circle_hits_any_wall(cx, cy, radius, self._walls)):
                return cx, cy
            cx = self.world_width / 2 + random.uniform(-800, 800)
            cy = self.world_height / 2 + random.uniform(-800, 800)
        return self.world_width / 2, self.world_height / 2

    # ── Update ──────────────────────────────────────────────────────

    def update(self, gv: GameView, dt: float) -> None:
        from zones.zone2_world import handle_projectile_hits, try_respawn
        from collisions import resolve_overlap, reflect_velocity
        from constants import (
            ALIEN_ASTEROID_DAMAGE, ALIEN_COL_COOLDOWN,
        )
        from sprites.zone2_aliens import ShieldedAlien

        px = gv.player.center_x
        py = gv.player.center_y
        self._update_fog(gv)

        # Wormhole return — covers both the central and the four
        # corner wormholes installed in setup().
        for wh in gv._wormholes:
            wh.update_wormhole(dt)
            if math.hypot(px - wh.center_x, py - wh.center_y) < 100:
                gv._use_glow = (100, 180, 255, 200)
                gv._use_glow_timer = 0.5
                arcade.play_sound(gv._victory_snd, volume=0.6)
                gv._flash_game_msg("Returning through wormhole...", 1.5)
                target = (wh.zone_target if wh.zone_target is not None
                          else ZoneID.ZONE2)
                gv._transition_zone(target, entry_side="wormhole_return")
                return

        # Route the shared GameView alien + alien-projectile lists at
        # the Nebula-style population so reused helpers (handle_
        # projectile_hits, turret targeting, collision handlers) work
        # the same way as in Zone 2.
        gv.alien_list = self._aliens
        gv.alien_projectile_list = self._alien_projectiles

        # Asteroid tick (rotation).
        for a in self._iron_asteroids:
            a.update_asteroid(dt)
        for a in self._double_iron:
            a.update_asteroid(dt)
        for a in self._copper_asteroids:
            a.update_asteroid(dt)

        # Gas damage to the player.
        self._update_gas_damage(gv, dt)

        # Zone 2 aliens AI + projectile fire.
        for alien in list(self._aliens):
            fired = alien.update_alien(
                dt, px, py, self._iron_asteroids, self._aliens,
                force_walls=gv._force_walls)
            for proj in fired:
                self._alien_projectiles.append(proj)

        # Wanderer drift + player collision.
        for w in self._wanderers:
            w.update_wandering(dt, px, py)
        self._update_wanderer_collision(gv, dt)

        # Null fields — update tick for flash / disable timers.
        for nf in self._null_fields:
            nf.update_null_field(dt)

        # Slipspace rotation + teleport collision.
        from update_logic import update_slipspaces
        update_slipspaces(gv, dt)

        # Player projectile hits on Nebula asteroids / aliens.
        handle_projectile_hits(self, gv)

        # Alien-vs-player collisions (same helper Zone 2 uses inline).
        from constants import SHIP_RADIUS, SHIP_COLLISION_COOLDOWN
        for alien in arcade.check_for_collision_with_list(
                gv.player, self._aliens):
            contact = resolve_overlap(
                alien, gv.player, 20.0, SHIP_RADIUS,
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

        # Alien-vs-asteroid collisions.
        for alien in list(self._aliens):
            for alist in (self._iron_asteroids, self._double_iron,
                          self._copper_asteroids):
                for a in arcade.check_for_collision_with_list(alien, alist):
                    a_radius = max(ASTEROID_RADIUS, a.width / 2 * 0.8)
                    contact = resolve_overlap(
                        alien, a, 20.0, a_radius,
                        push_a=1.0, push_b=0.0)
                    if contact is None:
                        continue
                    nx, ny = contact
                    reflect_velocity(alien, nx, ny, ALIEN_BOUNCE)
                    if alien._col_cd <= 0.0:
                        alien._col_cd = ALIEN_COL_COOLDOWN
                        alien.collision_bump()
                        alien.take_damage(ALIEN_ASTEROID_DAMAGE)
                        if alien.hp <= 0:
                            from collisions import _apply_kill_rewards
                            from constants import (
                                ALIEN_IRON_DROP, BLUEPRINT_DROP_CHANCE_ALIEN,
                            )
                            from character_data import bonus_iron_enemy
                            _apply_kill_rewards(
                                gv, alien.center_x, alien.center_y,
                                ALIEN_IRON_DROP, bonus_iron_enemy,
                                BLUEPRINT_DROP_CHANCE_ALIEN)
                            alien.remove_from_sprite_lists()
                    break
                if not alien.sprite_lists:
                    break

        # Maze-specific entities.
        self._update_spawners(gv, dt, px, py)
        self._update_maze_aliens(gv, dt, px, py)
        self._update_maze_projectiles(gv, dt)
        self._handle_player_projectile_hits(gv)
        self._update_player_wall_collision(gv)
        self._reconcile_dead_aliens()

        # Respawn Nebula content (not maze spawners — those stay dead).
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
        """Create one MazeAlien near the spawner's room centre."""
        room = self._room_for_spawner(sp)
        if room is not None:
            ax, ay = self._find_room_interior_point(room, sp)
            home_xy = (room.x + room.w / 2, room.y + room.h / 2)
            patrol_r = min(180.0, (room.w - 120.0) / 2)
        else:
            ax = sp.center_x
            ay = sp.center_y + MAZE_ALIEN_RADIUS * 2 + 4
            home_xy = (sp.center_x, sp.center_y)
            patrol_r = 180.0
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

    def _room_for_spawner(self, sp: MazeSpawner) -> Rect | None:
        for room in self._rooms:
            if (room.x <= sp.center_x <= room.x + room.w
                    and room.y <= sp.center_y <= room.y + room.h):
                return room
        return None

    def _find_room_interior_point(
        self, room: Rect, sp: MazeSpawner,
    ) -> tuple[float, float]:
        """Pick a point near the spawner that isn't inside a wall."""
        for _ in range(40):
            ax = sp.center_x + random.uniform(-120.0, 120.0)
            ay = sp.center_y + random.uniform(-120.0, 120.0)
            if (not circle_hits_any_wall(
                    ax, ay, MAZE_ALIEN_RADIUS + 4, self._walls)
                    and room.x <= ax <= room.x + room.w
                    and room.y <= ay <= room.y + room.h):
                return ax, ay
        return sp.center_x, sp.center_y

    def _update_maze_aliens(self, gv: GameView, dt: float,
                            px: float, py: float) -> None:
        """Tick every MazeAlien — same avoidance inputs as Zone 2
        aliens but with the Star Maze's shared asteroid list."""
        for alien in list(self._maze_aliens):
            fired = alien.update_alien(
                dt, px, py, self._iron_asteroids, self._maze_aliens,
                force_walls=gv._force_walls,
                maze_walls=self._walls,
            )
            for proj in fired:
                self._maze_projectiles.append(proj)

    def _update_maze_projectiles(self, gv: GameView, dt: float) -> None:
        """Advance maze-alien / maze-spawner projectiles, removing any
        that cross a maze wall this tick.  ``Projectile.update_
        projectile`` auto-removes when the weapon's range is exhausted
        so we only need the wall-block check."""
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
        """Block the player from entering walls.  Revert position and
        clamp velocity along the axis of overlap so the ship slides
        along the wall instead of stopping dead."""
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
            # Push the ship out along the contact normal.
            nx = dx / dist if dist > 0.001 else 1.0
            ny = dy / dist if dist > 0.001 else 0.0
            pen = r - dist
            player.center_x += nx * pen
            player.center_y += ny * pen
            # Reflect velocity along the normal, with dampening.
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
        """Walk player projectiles against every maze alien + every
        live spawner, apply damage, remove projectiles on hit, and
        award kill rewards when HP drops to zero."""
        from collisions import _apply_kill_rewards
        from character_data import bonus_iron_enemy
        from constants import BLUEPRINT_DROP_CHANCE_ALIEN
        from sprites.explosion import HitSpark

        for proj in list(gv.projectile_list):
            if getattr(proj, "mines_rock", False):
                continue
            # Spawners first — they're the high-value target and sit
            # at room centres, so iterating them first keeps the hit
            # search short once most rooms are cleared.
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
            # Maze aliens.
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
        """Catch aliens that died through some other path (asteroid
        collision, future AOE, etc.) and decrement the spawner count."""
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
        # Gas first so asteroids draw on top (consistent with Zone 2).
        self._gas_areas.draw()
        self._iron_asteroids.draw()
        self._double_iron.draw()
        self._copper_asteroids.draw()
        self._wanderers.draw()
        # Slipspaces — rotation already advanced by update_slipspaces.
        self._slipspaces.draw()
        # Null fields.
        for nf in self._null_fields:
            nf.draw()
        # Maze walls on top of terrain so they clearly occlude things.
        if self._wall_sprite_list is not None:
            self._wall_sprite_list.draw()
        # All spawners drawn via SpriteList — killed ones stay visible
        # as damaged husks so the player can see at a glance which
        # rooms are clear; the minimap shows them in grey.
        self._spawners.draw()
        # Zone 2 aliens + their projectiles.
        self._aliens.draw()
        # Shielded-alien shield overlays (cull to visible rect).
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
            # Aliens aren't persisted — they're considered in-flight
            # and respawn naturally when the player re-enters (spawner
            # timers resume from save state).
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

    # ── Geometry accessors (used by tests + minimap) ────────────────

    @property
    def rooms(self) -> list[Rect]:
        return self._rooms

    @property
    def walls(self) -> list[Rect]:
        return self._walls

    @property
    def spawners(self) -> list[MazeSpawner]:
        return self._spawners
