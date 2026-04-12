"""Main zone (Double Star) — wraps the existing 6400x6400 gameplay."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    RESPAWN_INTERVAL, ALIEN_DETECT_DIST,
    ALIEN_VEL_DAMPING,
)
from zones import ZoneID, ZoneState

if TYPE_CHECKING:
    from game_view import GameView


# Attributes on GameView that are zone-1-specific and must be stashed
# when the player leaves for a warp zone.
_ZONE1_LISTS = [
    "asteroid_list", "alien_list", "building_list",
    "alien_projectile_list", "turret_projectile_list",
    "iron_pickup_list", "blueprint_pickup_list",
    "explosion_list",
]
_ZONE1_SCALARS = [
    "_fog_grid", "_fog_revealed",
    "_asteroid_respawn_timer", "_alien_respawn_timer",
    "_repair_acc", "_building_repair_acc",
    "_boss", "_boss_spawned", "_boss_defeated",
    "_trade_station",
    "_hover_building",
]
_ZONE1_BOSS_LISTS = ["_boss_list", "_boss_projectile_list"]
_ZONE1_WORMHOLE = ["_wormholes", "_wormhole_list"]


class MainZone(ZoneState):
    zone_id = ZoneID.MAIN
    world_width = WORLD_WIDTH
    world_height = WORLD_HEIGHT

    def __init__(self) -> None:
        self._stash: dict = {}

    def setup(self, gv: GameView) -> None:
        """Restore stashed zone 1 state (or no-op on first entry)."""
        if self._stash:
            for attr in (_ZONE1_LISTS + _ZONE1_BOSS_LISTS + _ZONE1_WORMHOLE):
                setattr(gv, attr, self._stash[attr])
            for attr in _ZONE1_SCALARS:
                setattr(gv, attr, self._stash[attr])
            # Restore hit/fire sparks
            gv.hit_sparks = self._stash.get("hit_sparks", [])
            gv.fire_sparks = self._stash.get("fire_sparks", [])
            self._stash.clear()

    def teardown(self, gv: GameView) -> None:
        """Stash all zone-1-specific state before leaving."""
        for attr in (_ZONE1_LISTS + _ZONE1_BOSS_LISTS + _ZONE1_WORMHOLE):
            self._stash[attr] = getattr(gv, attr)
        for attr in _ZONE1_SCALARS:
            self._stash[attr] = getattr(gv, attr)
        self._stash["hit_sparks"] = gv.hit_sparks
        self._stash["fire_sparks"] = gv.fire_sparks
        # Clear GameView references (warp zone will set its own)
        for attr in _ZONE1_LISTS:
            setattr(gv, attr, arcade.SpriteList())
        for attr in _ZONE1_BOSS_LISTS:
            setattr(gv, attr, arcade.SpriteList())
        for attr in _ZONE1_WORMHOLE:
            if attr == "_wormholes":
                setattr(gv, attr, [])
            else:
                setattr(gv, attr, arcade.SpriteList())
        gv._boss = None
        gv._trade_station = None
        gv._hover_building = None
        gv.hit_sparks = []
        gv.fire_sparks = []

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        if entry_side == "wormhole_return" and self._stash:
            # Return to where the player was when they left
            return self._stash.get("_player_pos", (WORLD_WIDTH / 2, WORLD_HEIGHT / 2))
        return WORLD_WIDTH / 2, WORLD_HEIGHT / 2

    def background_update(self, gv: GameView, dt: float) -> None:
        """Tick Zone 1 while the player is elsewhere — respawns + alien patrol."""
        if not self._stash:
            return

        asteroid_list = self._stash.get("asteroid_list")
        alien_list = self._stash.get("alien_list")
        building_list = self._stash.get("building_list")

        # Advance respawn timers
        ast_timer = self._stash.get("_asteroid_respawn_timer", 0.0) + dt
        ali_timer = self._stash.get("_alien_respawn_timer", 0.0) + dt

        if ast_timer >= RESPAWN_INTERVAL:
            ast_timer = 0.0
            self._bg_respawn_asteroid(gv, asteroid_list, building_list)
        if ali_timer >= RESPAWN_INTERVAL:
            ali_timer = 0.0
            self._bg_respawn_alien(gv, alien_list, building_list)

        self._stash["_asteroid_respawn_timer"] = ast_timer
        self._stash["_alien_respawn_timer"] = ali_timer

        # Tick alien patrol AI (no player target — patrol only)
        damp = ALIEN_VEL_DAMPING ** (dt * 60.0)
        for alien in alien_list:
            alien.vel_x *= damp
            alien.vel_y *= damp
            alien.center_x += alien.vel_x * dt
            alien.center_y += alien.vel_y * dt
            # Keep aliens patrolling within bounds
            if alien._state == alien._STATE_PURSUE:
                alien._state = alien._STATE_PATROL
                alien._pick_patrol_target()
            alien._update_movement(dt, -9999, -9999, asteroid_list, alien_list)

        # Tick asteroids (rotation only)
        for asteroid in asteroid_list:
            asteroid.update_asteroid(dt)

    def _bg_respawn_asteroid(self, gv, asteroid_list, building_list):
        """Respawn one asteroid into the stashed list (no sound/sparks)."""
        import math
        from constants import ASTEROID_COUNT, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS
        if len(asteroid_list) >= ASTEROID_COUNT:
            return
        from sprites.asteroid import IronAsteroid
        margin = 100
        for _ in range(200):
            ax = random.uniform(margin, WORLD_WIDTH - margin)
            ay = random.uniform(margin, WORLD_HEIGHT - margin)
            if math.hypot(ax - WORLD_WIDTH / 2, ay - WORLD_HEIGHT / 2) < ASTEROID_MIN_DIST:
                continue
            if building_list and any(
                math.hypot(ax - b.center_x, ay - b.center_y) < RESPAWN_EXCLUSION_RADIUS
                for b in building_list
            ):
                continue
            asteroid_list.append(IronAsteroid(gv._asteroid_tex, ax, ay))
            return

    def _bg_respawn_alien(self, gv, alien_list, building_list):
        """Respawn one alien into the stashed list (no sound/sparks)."""
        import math
        from constants import ALIEN_COUNT, ALIEN_MIN_DIST, RESPAWN_EXCLUSION_RADIUS
        if len(alien_list) >= ALIEN_COUNT:
            return
        from sprites.alien import SmallAlienShip
        margin = 100
        for _ in range(200):
            ax = random.uniform(margin, WORLD_WIDTH - margin)
            ay = random.uniform(margin, WORLD_HEIGHT - margin)
            if math.hypot(ax - WORLD_WIDTH / 2, ay - WORLD_HEIGHT / 2) < ALIEN_MIN_DIST:
                continue
            if building_list and any(
                math.hypot(ax - b.center_x, ay - b.center_y) < RESPAWN_EXCLUSION_RADIUS
                for b in building_list
            ):
                continue
            alien_list.append(
                SmallAlienShip(gv._alien_ship_tex, gv._alien_laser_tex, ax, ay))
            return

    def to_save_data(self) -> dict:
        return {}  # Zone 1 state is saved by game_save.py's existing logic

    def from_save_data(self, data: dict, gv: GameView) -> None:
        pass  # Restored by game_save.py's existing logic
