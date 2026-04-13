"""Zone 2 (The Nebula) — second biome with new resources, hazards, and enemies."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade
from PIL import Image as PILImage

from constants import (
    ZONE2_WIDTH, ZONE2_HEIGHT,
    SHIP_RADIUS, SHIP_COLLISION_COOLDOWN,
    ASTEROID_RADIUS, SHIP_COLLISION_DAMAGE, SHIP_BOUNCE,
    ALIEN_BOUNCE,
    GAS_AREA_DAMAGE, GAS_AREA_SLOW,
    WANDERING_DAMAGE, WANDERING_RADIUS,
    COPPER_ASTEROID_PNG, COPPER_PICKUP_PNG,
    Z2_ALIEN_SHIP_PNG,
    RESPAWN_INTERVAL,
)
from zones import ZoneID, ZoneState
from sprites.wormhole import Wormhole
from sprites.zone2_aliens import ShieldedAlien
from collisions import resolve_overlap, reflect_velocity

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

    def _rebuild_shielded_list(self) -> None:
        self._shielded_aliens = [
            a for a in self._aliens if isinstance(a, ShieldedAlien)]

    def setup(self, gv: GameView) -> None:
        global _alien_texture_cache, _copper_tex_cache
        self._iron_tex = gv._asteroid_tex
        if _copper_tex_cache is None:
            _copper_tex_cache = arcade.load_texture(COPPER_ASTEROID_PNG)
        self._copper_tex = _copper_tex_cache
        self._copper_pickup_tex = arcade.load_texture(COPPER_PICKUP_PNG)
        self._alien_laser_tex = gv._alien_laser_tex

        if _alien_texture_cache is None:
            from sprites.zone2_aliens import ALIEN_CROPS
            pil_ship = PILImage.open(Z2_ALIEN_SHIP_PNG).convert("RGBA")
            _alien_texture_cache = {}
            for name, crop in ALIEN_CROPS.items():
                _alien_texture_cache[name] = arcade.Texture(pil_ship.crop(crop))
            pil_ship.close()
        self._alien_textures = _alien_texture_cache
        self._wanderer_tex = self._iron_tex

        if not self._populated:
            from zones.zone2_world import (
                populate_iron_asteroids, populate_double_iron,
                populate_copper_asteroids, populate_gas_areas,
                populate_wanderers, populate_aliens,
            )
            random.seed(self._world_seed)
            populate_iron_asteroids(self)
            populate_double_iron(self)
            populate_copper_asteroids(self)
            populate_gas_areas(self)
            self._gas_pos_cache = [(g.center_x, g.center_y, g.radius)
                                   for g in self._gas_areas]
            populate_wanderers(self)
            populate_aliens(self)
            random.seed()
            self._populated = True

        self._rebuild_shielded_list()

        whx, why = self._find_clear_position(
            self.world_width / 2, self.world_height / 2, 120)
        wh = Wormhole(whx, why)
        wh.zone_target = ZoneID.MAIN
        gv._wormholes = [wh]
        gv._wormhole_list.clear()
        gv._wormhole_list.append(wh)

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
        px, py = gv.player.center_x, gv.player.center_y
        cx = int(px / self._fog_cell)
        cy = int(py / self._fog_cell)
        r = int(self._fog_reveal_r / self._fog_cell) + 1
        for gy in range(max(0, cy - r), min(self._fog_h, cy + r + 1)):
            for gx in range(max(0, cx - r), min(self._fog_w, cx + r + 1)):
                if not self._fog_grid[gy][gx]:
                    cell_cx = (gx + 0.5) * self._fog_cell
                    cell_cy = (gy + 0.5) * self._fog_cell
                    if math.hypot(px - cell_cx, py - cell_cy) <= self._fog_reveal_r:
                        self._fog_grid[gy][gx] = True
                        self._fog_revealed += 1
                        gv._fog_revealed = self._fog_revealed

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
                gv._flash_game_msg("Returning through wormhole...", 1.5)
                target = wh.zone_target if wh.zone_target is not None else ZoneID.MAIN
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

        # Aliens — full AI for nearby, cheap position-only for distant
        _alien_pre_count = len(self._aliens)
        _ai_range_sq = (vx1 - vx0 + 500) ** 2  # viewport width + generous margin
        for alien in self._aliens:
            adx = alien.center_x - px
            ady = alien.center_y - py
            if adx * adx + ady * ady < _ai_range_sq:
                projs = alien.update_alien(dt, px, py, self._iron_asteroids, self._aliens)
                if projs:
                    for p in projs:
                        self._alien_projectiles.append(p)
            else:
                # Minimal update: velocity decay + position drift only
                alien.center_x += alien.vel_x * dt
                alien.center_y += alien.vel_y * dt
                alien.vel_x *= 0.95
                alien.vel_y *= 0.95

        # Alien projectiles
        for proj in self._alien_projectiles:
            proj.update_projectile(dt)
        for proj in arcade.check_for_collision_with_list(
                gv.player, self._alien_projectiles):
            gv._apply_damage_to_player(int(proj.damage))
            gv._trigger_shake()
            proj.remove_from_sprite_lists()

        # Player projectile hits (delegated)
        handle_projectile_hits(self, gv)

        # Rebuild shielded list if aliens died
        if len(self._aliens) != _alien_pre_count:
            self._rebuild_shielded_list()

        # Player-asteroid collision
        if gv.player._collision_cd <= 0.0:
            for alist in (self._iron_asteroids, self._double_iron, self._copper_asteroids):
                hit = False
                for a in arcade.check_for_collision_with_list(gv.player, alist):
                    a_radius = max(ASTEROID_RADIUS, a.width / 2 * 0.8)
                    contact = resolve_overlap(
                        gv.player, a, SHIP_RADIUS, a_radius,
                        push_a=1.0, push_b=0.0)
                    if contact is None:
                        continue
                    nx, ny = contact
                    reflect_velocity(gv.player, nx, ny, SHIP_BOUNCE)
                    gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                    gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                    gv._trigger_shake()
                    arcade.play_sound(gv._bump_snd, volume=0.4)
                    hit = True
                    break
                if hit:
                    break

        # Alien-player collision
        for alien in arcade.check_for_collision_with_list(gv.player, self._aliens):
            contact = resolve_overlap(
                alien, gv.player, 20.0, SHIP_RADIUS,
                push_a=0.5, push_b=0.5)
            if contact is None:
                continue
            nx, ny = contact
            # Push aliens forward away from player and dampen player slightly
            alien.vel_x += nx * 150
            alien.vel_y += ny * 150
            # Player gets a 0.4-weighted bounce against the same normal
            dot = gv.player.vel_x * (-nx) + gv.player.vel_y * (-ny)
            if dot < 0:
                gv.player.vel_x -= (1 + ALIEN_BOUNCE) * dot * (-nx) * 0.4
                gv.player.vel_y -= (1 + ALIEN_BOUNCE) * dot * (-ny) * 0.4
            if gv.player._collision_cd <= 0.0:
                gv._apply_damage_to_player(5)
                gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                gv._trigger_shake()
                arcade.play_sound(gv._bump_snd, volume=0.3)

        # Alien-asteroid collisions (damage + bounce)
        from constants import ALIEN_ASTEROID_DAMAGE, ALIEN_COL_COOLDOWN
        for alien in list(self._aliens):
            for alist in (self._iron_asteroids, self._double_iron,
                          self._copper_asteroids):
                for a in arcade.check_for_collision_with_list(alien, alist):
                    a_radius = max(ASTEROID_RADIUS, a.width / 2 * 0.8)
                    contact = resolve_overlap(
                        alien, a, 20.0, a_radius, push_a=1.0, push_b=0.0)
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
                    break  # one collision per alien per frame
                if not alien.sprite_lists:
                    break  # alien was killed

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

        # Respawn
        self._respawn_timer += dt
        if self._respawn_timer >= RESPAWN_INTERVAL:
            self._respawn_timer = 0.0
            try_respawn(self, gv)
            self._rebuild_shielded_list()

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
        if gv.player._collision_cd > 0.0:
            return
        for w in arcade.check_for_collision_with_list(gv.player, self._wanderers):
            contact = resolve_overlap(
                gv.player, w, SHIP_RADIUS, WANDERING_RADIUS,
                push_a=0.6, push_b=0.4)
            if contact is None:
                continue
            nx, ny = contact
            reflect_velocity(gv.player, nx, ny, SHIP_BOUNCE)
            # Kick wanderer away from player, suppress magnet
            w._wander_angle = math.atan2(-ny, -nx)
            w._wander_timer = 1.5
            w._repel_timer = 2.0
            gv._apply_damage_to_player(WANDERING_DAMAGE)
            gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.4)
            break

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
