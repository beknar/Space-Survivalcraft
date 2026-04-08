"""Zone 2 (The Nebula) — second biome with new resources, hazards, and enemies."""
from __future__ import annotations

import math
import os
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
        self._aliens: arcade.SpriteList = arcade.SpriteList(use_spatial_hash=True)
        self._shielded_aliens: list = []
        self._alien_projectiles: arcade.SpriteList = arcade.SpriteList()
        self._gas_areas: arcade.SpriteList = arcade.SpriteList()
        self._wanderers: arcade.SpriteList = arcade.SpriteList()
        # Visible-set SpriteLists for viewport-culled drawing
        self._vis_draw: arcade.SpriteList = arcade.SpriteList()
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

        if gv._trade_station is None:
            gv._spawn_trade_station()

        gv._fog_grid = self._fog_grid
        gv._fog_revealed = self._fog_revealed

    def teardown(self, gv: GameView) -> None:
        self._fog_grid = gv._fog_grid
        self._fog_revealed = gv._fog_revealed
        self._alien_projectiles.clear()
        gv._wormholes.clear()
        gv._wormhole_list.clear()

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

        # Aliens — always update AI (they need to track player from afar)
        _alien_pre_count = len(self._aliens)
        for alien in self._aliens:
            projs = alien.update_alien(dt, px, py, self._iron_asteroids, self._aliens)
            if projs:
                for p in projs:
                    self._alien_projectiles.append(p)

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
                for a in arcade.check_for_collision_with_list(gv.player, alist):
                    ddx = gv.player.center_x - a.center_x
                    ddy = gv.player.center_y - a.center_y
                    ddist = math.hypot(ddx, ddy)
                    if ddist > 0:
                        a_radius = max(ASTEROID_RADIUS, a.width / 2 * 0.8)
                        combined = a_radius + SHIP_RADIUS
                        nx, ny = ddx / ddist, ddy / ddist
                        overlap = combined - ddist
                        if overlap > 0:
                            gv.player.center_x += nx * overlap
                            gv.player.center_y += ny * overlap
                        dot = gv.player.vel_x * nx + gv.player.vel_y * ny
                        if dot < 0:
                            gv.player.vel_x -= (1 + SHIP_BOUNCE) * dot * nx
                            gv.player.vel_y -= (1 + SHIP_BOUNCE) * dot * ny
                        gv._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                        gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
                        gv._trigger_shake()
                        arcade.play_sound(gv._bump_snd, volume=0.4)
                        break
                else:
                    continue
                break

        # Alien-player collision
        for alien in arcade.check_for_collision_with_list(gv.player, self._aliens):
            ddx = alien.center_x - gv.player.center_x
            ddy = alien.center_y - gv.player.center_y
            ddist = math.hypot(ddx, ddy)
            combined = 20 + SHIP_RADIUS
            if ddist > 0:
                nx, ny = ddx / ddist, ddy / ddist
                overlap = combined - ddist
                if overlap > 0:
                    alien.center_x += nx * overlap * 0.5
                    alien.center_y += ny * overlap * 0.5
                    gv.player.center_x -= nx * overlap * 0.5
                    gv.player.center_y -= ny * overlap * 0.5
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
            # Direction from wanderer to player
            ddx = gv.player.center_x - w.center_x
            ddy = gv.player.center_y - w.center_y
            ddist = math.hypot(ddx, ddy)
            if ddist > 0:
                nx, ny = ddx / ddist, ddy / ddist
                combined = WANDERING_RADIUS + SHIP_RADIUS
                overlap = combined - ddist
                # Push player and wanderer apart
                if overlap > 0:
                    gv.player.center_x += nx * overlap * 0.6
                    gv.player.center_y += ny * overlap * 0.6
                    w.center_x -= nx * overlap * 0.4
                    w.center_y -= ny * overlap * 0.4
                # Bounce player velocity away
                dot = gv.player.vel_x * nx + gv.player.vel_y * ny
                if dot < 0:
                    gv.player.vel_x -= (1 + SHIP_BOUNCE) * dot * nx
                    gv.player.vel_y -= (1 + SHIP_BOUNCE) * dot * ny
                # Kick wanderer away from player
                w._wander_angle = math.atan2(-ny, -nx)
                w._wander_timer = 1.5
            gv._apply_damage_to_player(WANDERING_DAMAGE)
            gv.player._collision_cd = SHIP_COLLISION_COOLDOWN
            gv._trigger_shake()
            arcade.play_sound(gv._bump_snd, volume=0.4)
            break

    # ── Drawing (viewport-culled) ──────────────────────────────────────────

    def _draw_visible(self, source: arcade.SpriteList,
                      vx0: float, vx1: float, vy0: float, vy1: float) -> None:
        """Draw only sprites from source that are within the visible rect."""
        vis = self._vis_draw
        vis.clear()
        for s in source:
            sx = s.center_x
            if vx0 < sx < vx1:
                sy = s.center_y
                if vy0 < sy < vy1:
                    vis.append(s)
        if len(vis) > 0:
            vis.draw()

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        # Compute visible rect with margin
        m = _CULL_MARGIN
        vx0 = cx - hw - m
        vx1 = cx + hw + m
        vy0 = cy - hh - m
        vy1 = cy + hh + m

        # Gas areas need wider margin (they can be large)
        gm = m + 200
        gvx0 = cx - hw - gm
        gvx1 = cx + hw + gm
        gvy0 = cy - hh - gm
        gvy1 = cy + hh + gm
        self._draw_visible(self._gas_areas, gvx0, gvx1, gvy0, gvy1)

        # Asteroids, wanderers
        self._draw_visible(self._iron_asteroids, vx0, vx1, vy0, vy1)
        self._draw_visible(self._double_iron, vx0, vx1, vy0, vy1)
        self._draw_visible(self._copper_asteroids, vx0, vx1, vy0, vy1)
        self._draw_visible(self._wanderers, vx0, vx1, vy0, vy1)

        # Wormholes (few, always draw)
        if gv._wormholes:
            gv._wormhole_list.draw()

        # Aliens (cull)
        self._draw_visible(self._aliens, vx0, vx1, vy0, vy1)
        # Shield overlays (pre-filtered list, cull)
        for alien in self._shielded_aliens:
            ax = alien.center_x
            if vx0 < ax < vx1:
                ay = alien.center_y
                if vy0 < ay < vy1:
                    alien.draw_shield()

        # Projectiles (typically few, near player — always draw)
        self._alien_projectiles.draw()
        gv.iron_pickup_list.draw()
        gv.blueprint_pickup_list.draw()

    def to_save_data(self) -> dict:
        return {}

    def from_save_data(self, data: dict, gv: GameView) -> None:
        pass
