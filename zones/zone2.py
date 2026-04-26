"""Zone 2 (The Nebula) — second biome with new resources, hazards, and enemies."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    ZONE2_WIDTH, ZONE2_HEIGHT,
    RESPAWN_INTERVAL,
)
from zones import ZoneID, ZoneState
from sprites.wormhole import Wormhole

if TYPE_CHECKING:
    from game_view import GameView

# Module-level caches (persist across zone entries, generated once)
_gas_texture_cache: dict[int, arcade.Texture] = {}
_alien_texture_cache: dict[str, arcade.Texture] | None = None
_copper_tex_cache: arcade.Texture | None = None

# Margin around the camera rect for culling (px)
_CULL_MARGIN = 250.0


class Zone2(ZoneState):
    """The Nebula — second biome with copper, gas clouds, new aliens."""
    zone_id = ZoneID.ZONE2
    world_width = ZONE2_WIDTH
    world_height = ZONE2_HEIGHT

    def __init__(self) -> None:
        from constants import FOG_CELL_SIZE, FOG_REVEAL_RADIUS
        self._fog_cell = FOG_CELL_SIZE
        self._fog_reveal_r = FOG_REVEAL_RADIUS
        _fog_w = ZONE2_WIDTH // FOG_CELL_SIZE
        _fog_h = ZONE2_HEIGHT // FOG_CELL_SIZE
        self._fog_grid: list[list[bool]] = [[False] * _fog_w for _ in range(_fog_h)]
        self._fog_revealed: int = 0
        self._fog_w = _fog_w
        self._fog_h = _fog_h
        self._minimap_cache: arcade.SpriteList | None = None
        self._gas_pos_cache: list[tuple[float, float, float]] | None = None
        self._world_seed: int = random.randint(0, 2**31)
        self._populated: bool = False
        # Sprite lists
        self._iron_asteroids: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        self._double_iron: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        self._copper_asteroids: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        # Aliens move every frame — spatial hash would be rebuilt each tick
        self._aliens: arcade.SpriteList = arcade.SpriteList()
        self._shielded_aliens: list = []
        self._alien_projectiles: arcade.SpriteList = arcade.SpriteList()
        self._gas_areas: arcade.SpriteList = arcade.SpriteList()
        self._wanderers: arcade.SpriteList = arcade.SpriteList()
        # Null fields — stealth patches. Populated once; updated every
        # frame in ``update`` so the disabled-timer flash animates.
        self._null_fields: list = []
        # Slipspaces — teleporters. SpriteList so collision helpers work.
        self._slipspaces: arcade.SpriteList = arcade.SpriteList()
        # Textures (loaded on setup)
        self._iron_tex: arcade.Texture | None = None
        self._copper_tex: arcade.Texture | None = None
        self._copper_pickup_tex: arcade.Texture | None = None
        self._alien_textures: dict[str, arcade.Texture] = {}
        self._alien_laser_tex: arcade.Texture | None = None
        self._wanderer_tex: arcade.Texture | None = None
        # State
        self._gas_damage_cd: float = 0.0
        self._respawn_timer: float = 0.0
        self._alien_counts: dict[str, int] = {}
        # Building stash — Zone 2 has its own buildings separate from Zone 1
        self._building_stash: dict | None = None
        # Post-Nebula-boss progression: once the Nebula boss is
        # defeated, four corner wormholes appear in this zone that
        # route to the NEBULA_WARP_* variants, which in turn deposit
        # the player in the Star Maze.  The central Zone-2 wormhole
        # (to ZoneID.MAIN) keeps working alongside them per spec.
        self._nebula_boss_defeated: bool = False

    def _rebuild_shielded_list(self) -> None:
        from zones.nebula_shared import rebuild_shielded_list
        rebuild_shielded_list(self)

    # ── Post-Nebula-boss wormholes ──────────────────────────────────

    def _build_corner_wormholes(self) -> list[Wormhole]:
        """Return four corner ``Wormhole`` instances tagged with the
        NEBULA_WARP_* zone ids.  Corner-to-type mapping mirrors Zone
        1's pattern so the visual cue is consistent across biomes.
        """
        margin = 220
        ww = self.world_width
        wh = self.world_height
        corners = [
            (margin, margin, ZoneID.NEBULA_WARP_METEOR),      # bottom-left
            (ww - margin, margin, ZoneID.NEBULA_WARP_LIGHTNING),   # bottom-right
            (margin, wh - margin, ZoneID.NEBULA_WARP_GAS),         # top-left
            (ww - margin, wh - margin, ZoneID.NEBULA_WARP_ENEMY),  # top-right
        ]
        out: list[Wormhole] = []
        for x, y, target in corners:
            w = Wormhole(x, y)
            w.zone_target = target
            out.append(w)
        return out

    def mark_nebula_boss_defeated(self, gv: GameView) -> None:
        """Called from the collision layer when the Nebula boss dies.
        Flips the persistence flag and adds the four corner wormholes
        to the live wormhole lists so the player can enter them
        without having to leave and re-enter the zone."""
        if self._nebula_boss_defeated:
            return
        self._nebula_boss_defeated = True
        for cwh in self._build_corner_wormholes():
            gv._wormholes.append(cwh)
            gv._wormhole_list.append(cwh)

    def setup(self, gv: GameView) -> None:
        from zones.nebula_shared import (
            load_nebula_textures, populate_nebula_content,
        )
        load_nebula_textures(self, gv)
        if not self._populated:
            populate_nebula_content(self, gv)
            self._populated = True

        self._rebuild_shielded_list()

        whx, why = self._find_clear_position(
            self.world_width / 2, self.world_height / 2, 120)
        wh = Wormhole(whx, why)
        wh.zone_target = ZoneID.MAIN
        gv._wormholes = [wh]
        gv._wormhole_list.clear()
        gv._wormhole_list.append(wh)
        # Post-Nebula-boss: four corner wormholes to the 2x-danger
        # warp zones that route the player to the Star Maze.  Coexist
        # with the central wormhole back to Zone 1.
        if self._nebula_boss_defeated:
            for cwh in self._build_corner_wormholes():
                gv._wormholes.append(cwh)
                gv._wormhole_list.append(cwh)

        gv._fog_grid = self._fog_grid
        gv._fog_revealed = self._fog_revealed

        # Restore Zone 2 buildings (stashed when the player left)
        if self._building_stash is not None:
            gv.building_list = self._building_stash["building_list"]
            gv.turret_projectile_list = self._building_stash["turret_projectile_list"]
            gv._trade_station = self._building_stash["_trade_station"]
            gv._parked_ships = self._building_stash.get(
                "_parked_ships", arcade.SpriteList())
            gv._hover_building = None
            self._building_stash = None
        # First visit or no trade station yet
        if gv._trade_station is None:
            gv._spawn_trade_station()
        else:
            self._validate_trade_station(gv)

    def teardown(self, gv: GameView) -> None:
        self._fog_grid = gv._fog_grid
        self._fog_revealed = gv._fog_revealed
        self._alien_projectiles.clear()
        gv._wormholes.clear()
        gv._wormhole_list.clear()

        # Stash Zone 2 buildings so MainZone doesn't overwrite them
        self._building_stash = {
            "building_list": gv.building_list,
            "turret_projectile_list": gv.turret_projectile_list,
            "_trade_station": gv._trade_station,
            "_parked_ships": gv._parked_ships,
        }
        # Give GameView empty lists so MainZone.setup doesn't merge them
        gv.building_list = arcade.SpriteList()
        gv._parked_ships = arcade.SpriteList()
        gv.turret_projectile_list = arcade.SpriteList()
        gv._trade_station = None
        gv._hover_building = None

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        return self._find_clear_position(
            self.world_width / 2, self.world_height / 2 - 200, 80)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _find_clear_position(self, cx: float, cy: float,
                              clearance: float = 120) -> tuple[float, float]:
        for _ in range(80):
            ok = True
            for g in self._gas_areas:
                if g.contains_point(cx, cy):
                    ok = False
                    break
            if ok:
                for alist in (self._iron_asteroids, self._double_iron,
                              self._copper_asteroids, self._wanderers):
                    for a in alist:
                        if math.hypot(a.center_x - cx, a.center_y - cy) < clearance:
                            ok = False
                            break
                    if not ok:
                        break
            if ok:
                return cx, cy
            cx = self.world_width / 2 + random.uniform(-500, 500)
            cy = self.world_height / 2 + random.uniform(-500, 500)
        return cx, cy

    def _validate_trade_station(self, gv: GameView) -> None:
        """Relocate the trade station if it overlaps a gas cloud or asteroid."""
        ts = gv._trade_station
        if ts is None:
            return
        tx, ty = ts.center_x, ts.center_y
        blocked = False
        for g in self._gas_areas:
            if math.hypot(g.center_x - tx, g.center_y - ty) < g.radius + 80:
                blocked = True
                break
        if not blocked:
            for alist in (self._iron_asteroids, self._double_iron,
                          self._copper_asteroids, self._wanderers):
                for a in alist:
                    if math.hypot(a.center_x - tx, a.center_y - ty) < 80:
                        blocked = True
                        break
                if blocked:
                    break
        if blocked:
            from building_manager import _trade_pos_clear
            margin = 500
            for _ in range(400):
                nx = random.uniform(margin, self.world_width - margin)
                ny = random.uniform(margin, self.world_height - margin)
                if math.hypot(nx - self.world_width / 2,
                              ny - self.world_height / 2) < 1500:
                    continue
                if _trade_pos_clear(gv, nx, ny, 120.0):
                    ts.center_x = nx
                    ts.center_y = ny
                    return

    # ── Update ─────────────────────────────────────────────────────────────

    def _update_fog(self, gv: GameView) -> None:
        from zones.nebula_shared import update_fog
        update_fog(self, gv)

    def update(self, gv: GameView, dt: float) -> None:
        from zones.zone2_world import handle_projectile_hits, try_respawn

        px, py = gv.player.center_x, gv.player.center_y
        self._update_fog(gv)

        # Wormhole animation + collision
        for wh in gv._wormholes:
            wh.update_wormhole(dt)
            if math.hypot(px - wh.center_x, py - wh.center_y) < 100:
                gv._use_glow = (100, 180, 255, 200)
                gv._use_glow_timer = 0.5
                arcade.play_sound(gv._victory_snd, volume=0.6)
                target = wh.zone_target if wh.zone_target is not None else ZoneID.MAIN
                from zones import welcome_message_for
                msg = welcome_message_for(target)
                if msg is None:
                    msg = "Returning through wormhole..."
                gv._flash_game_msg(msg, 1.5)
                gv._transition_zone(target, entry_side="wormhole_return")
                return

        # Compute visible rect for update culling (wider margin for updates)
        try:
            win = arcade.get_window()
            _hw = win.width / 2
            _hh = win.height / 2
        except Exception:
            _hw, _hh = 640.0, 400.0
        _margin = _CULL_MARGIN + 100  # extra margin so sprites rotate in smoothly
        vx0 = px - _hw - _margin
        vx1 = px + _hw + _margin
        vy0 = py - _hh - _margin
        vy1 = py + _hh + _margin

        # Update asteroids — only update visible ones (rotation is invisible offscreen)
        for a in self._iron_asteroids:
            ax = a.center_x
            if vx0 < ax < vx1:
                ay = a.center_y
                if vy0 < ay < vy1:
                    a.update_asteroid(dt)
        for a in self._double_iron:
            ax = a.center_x
            if vx0 < ax < vx1:
                ay = a.center_y
                if vy0 < ay < vy1:
                    a.update_asteroid(dt)
        for a in self._copper_asteroids:
            ax = a.center_x
            if vx0 < ax < vx1:
                ay = a.center_y
                if vy0 < ay < vy1:
                    a.update_asteroid(dt)

        # Gas areas — only update visible ones
        for g in self._gas_areas:
            gx = g.center_x
            if vx0 - 200 < gx < vx1 + 200:
                gy = g.center_y
                if vy0 - 200 < gy < vy1 + 200:
                    g.update_gas(dt)
        self._update_gas_damage(gv, dt)

        # Wanderers — full wander + magnet AI near viewport, spin-only when far
        for w in self._wanderers:
            wx = w.center_x
            if vx0 < wx < vx1:
                wy = w.center_y
                if vy0 < wy < vy1:
                    w.update_wandering(dt, px, py)
                    continue
            w.angle = (w.angle + w._rot_speed * dt) % 360
        self._update_wanderer_collision(gv, dt)

        # Aliens — full AI for nearby, cheap position-only for distant.
        # Null field cloak: feed the aliens a far-away position so they
        # stay in PATROL.
        from update_logic import player_is_cloaked
        if player_is_cloaked(gv):
            ai_px, ai_py = px + 1e9, py + 1e9
        else:
            ai_px, ai_py = px, py
        _alien_pre_count = len(self._aliens)
        _ai_range_sq = (vx1 - vx0 + 500) ** 2  # viewport width + generous margin
        for alien in self._aliens:
            adx = alien.center_x - px
            ady = alien.center_y - py
            if adx * adx + ady * ady < _ai_range_sq:
                projs = alien.update_alien(
                    dt, ai_px, ai_py, self._iron_asteroids, self._aliens,
                    force_walls=getattr(gv, '_force_walls', None))
                if projs:
                    for p in projs:
                        self._alien_projectiles.append(p)
                    from update_logic import play_alien_laser_sound
                    play_alien_laser_sound(gv)
            else:
                # Minimal update: velocity decay + position drift only
                alien.center_x += alien.vel_x * dt
                alien.center_y += alien.vel_y * dt
                alien.vel_x *= 0.95
                alien.vel_y *= 0.95

        # Alien projectiles + laser hits
        from zones.nebula_shared import (
            update_alien_laser_hits,
            update_player_asteroid_collision,
            update_player_z2_alien_collision,
            update_alien_asteroid_collisions,
        )
        for proj in self._alien_projectiles:
            proj.update_projectile(dt)
        update_alien_laser_hits(self, gv)

        # Player projectile hits (delegated)
        handle_projectile_hits(self, gv)

        # Rebuild shielded list if aliens died
        if len(self._aliens) != _alien_pre_count:
            self._rebuild_shielded_list()

        update_player_asteroid_collision(self, gv)
        update_player_z2_alien_collision(self, gv)
        update_alien_asteroid_collisions(self, gv)

        # Buildings (turrets, repair, collisions)
        if len(gv.building_list) > 0:
            from update_logic import update_buildings
            # Point shared lists at Zone 2 entities for turret/collision logic
            _saved_alien = gv.alien_list
            _saved_aproj = gv.alien_projectile_list
            gv.alien_list = self._aliens
            gv.alien_projectile_list = self._alien_projectiles
            update_buildings(gv, dt)
            gv.alien_list = _saved_alien
            gv.alien_projectile_list = _saved_aproj

        # Parked-ship hit flash + AI pilot (AI-piloted ships patrol and
        # fire into gv.turret_projectile_list, which the turret hit
        # handler already routes to Zone 2 aliens).
        from update_logic import _update_parked_ships
        _saved_alien = gv.alien_list
        gv.alien_list = self._aliens
        _update_parked_ships(gv, dt)
        gv.alien_list = _saved_alien

        # Respawn
        self._respawn_timer += dt
        if self._respawn_timer >= RESPAWN_INTERVAL:
            self._respawn_timer = 0.0
            try_respawn(self, gv)
            self._rebuild_shielded_list()

    def _update_gas_damage(self, gv: GameView, dt: float) -> None:
        from zones.nebula_shared import update_gas_damage
        update_gas_damage(self, gv, dt)

    def _update_wanderer_collision(self, gv: GameView, dt: float) -> None:
        from zones.nebula_shared import update_wanderer_collision
        update_wanderer_collision(self, gv)

    # ── Drawing ────────────────────────────────────────────────────────────

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        # Static sprite lists upload their VBO once and Arcade's renderer
        # handles per-frame draw efficiently — issuing one draw() per list
        # is cheaper than per-frame visibility rebuilds.
        self._gas_areas.draw()
        self._iron_asteroids.draw()
        self._double_iron.draw()
        self._copper_asteroids.draw()
        self._wanderers.draw()

        # Wormholes (few, always draw)
        if gv._wormholes:
            gv._wormhole_list.draw()

        # Aliens move every frame — draw the whole list (also cheap)
        self._aliens.draw()
        # cull bounds for shield overlays only
        m = _CULL_MARGIN
        vx0 = cx - hw - m
        vx1 = cx + hw + m
        vy0 = cy - hh - m
        vy1 = cy + hh + m
        # Shield overlays (pre-filtered list, cull)
        for alien in self._shielded_aliens:
            ax = alien.center_x
            if vx0 < ax < vx1:
                ay = alien.center_y
                if vy0 < ay < vy1:
                    alien.draw_shield()

        # Station buildings (if any built in this zone)
        if len(gv.building_list) > 0:
            gv.building_list.draw()
        gv.turret_projectile_list.draw()

        # Projectiles (typically few, near player — always draw)
        self._alien_projectiles.draw()
        gv.iron_pickup_list.draw()
        gv.blueprint_pickup_list.draw()

    def background_update(self, gv: GameView, dt: float) -> None:
        """Tick Zone 2 while the player is elsewhere — respawns + alien patrol."""
        if not self._populated:
            return

        from zones.zone2_world import try_respawn
        from constants import ALIEN_VEL_DAMPING

        # Respawn timer
        self._respawn_timer += dt
        if self._respawn_timer >= RESPAWN_INTERVAL:
            self._respawn_timer = 0.0
            try_respawn(self, gv)
            self._rebuild_shielded_list()

        # Tick alien patrol AI (no player — patrol only)
        damp = ALIEN_VEL_DAMPING ** (dt * 60.0)
        for alien in self._aliens:
            alien.vel_x *= damp
            alien.vel_y *= damp
            alien.center_x += alien.vel_x * dt
            alien.center_y += alien.vel_y * dt
            if alien._state == alien._STATE_PURSUE:
                alien._state = alien._STATE_PATROL
                alien._pick_patrol_target()
            # Patrol movement toward waypoint
            tdx = alien._tgt_x - alien.center_x
            tdy = alien._tgt_y - alien.center_y
            tdist = math.hypot(tdx, tdy)
            if tdist < 8.0:
                alien._pick_patrol_target()
            elif tdist > 0.001:
                step = min(getattr(alien, '_speed', 80) * dt, tdist)
                alien.center_x += tdx / tdist * step
                alien.center_y += tdy / tdist * step

        # Tick asteroids (rotation)
        for a in self._iron_asteroids:
            a.update_asteroid(dt)
        for a in self._double_iron:
            a.update_asteroid(dt)
        for a in self._copper_asteroids:
            a.update_asteroid(dt)

        # Wanderers drift randomly (no player magnet)
        for w in self._wanderers:
            w.angle = (w.angle + w._rot_speed * dt) % 360

    def to_save_data(self) -> dict:
        return {}

    def from_save_data(self, data: dict, gv: GameView) -> None:
        pass
