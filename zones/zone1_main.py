"""Main zone (Double Star) — wraps the existing 6400x6400 gameplay."""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import WORLD_WIDTH, WORLD_HEIGHT
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

    def to_save_data(self) -> dict:
        return {}  # Zone 1 state is saved by game_save.py's existing logic

    def from_save_data(self, data: dict, gv: GameView) -> None:
        pass  # Restored by game_save.py's existing logic
