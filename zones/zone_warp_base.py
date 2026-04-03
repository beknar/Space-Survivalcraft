"""Base class for all warp zones — shared wall, exit, fog, and drawing logic."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from constants import FOG_CELL_SIZE, FOG_REVEAL_RADIUS
from zones import ZoneID, ZoneState

if TYPE_CHECKING:
    from game_view import GameView

WARP_ZONE_WIDTH = 3200
WARP_ZONE_HEIGHT = 6400
WALL_ZONE = 60           # px thickness of red wall regions
EXIT_THRESHOLD = 50       # px from edge to trigger exit

# Fog grid for warp zones (same cell size as zone 1)
_FOG_W = WARP_ZONE_WIDTH // FOG_CELL_SIZE    # 64
_FOG_H = WARP_ZONE_HEIGHT // FOG_CELL_SIZE   # 128


class WarpZoneBase(ZoneState):
    """Shared behaviour for all 4 warp zones."""
    world_width = WARP_ZONE_WIDTH
    world_height = WARP_ZONE_HEIGHT

    def __init__(self) -> None:
        self._return_pos: tuple[float, float] = (3200, 3200)
        self._wall_pulse: float = 0.0
        self._time_in_zone: float = 0.0
        # Walls close in by 10px every 30 seconds
        self._wall_close_rate: float = 10.0 / 30.0  # px per second
        self._wall_extra: float = 0.0  # extra wall thickness from closing
        # Fog of war for this warp zone
        self._fog_grid: list[list[bool]] = [
            [False] * _FOG_W for _ in range(_FOG_H)
        ]
        self._fog_revealed: int = 0

    def setup(self, gv: GameView) -> None:
        """Store return position, set fog grid on GameView."""
        self._return_pos = (gv.player.center_x, gv.player.center_y)
        # Apply our fog grid to GameView for minimap rendering
        gv._fog_grid = self._fog_grid
        gv._fog_revealed = self._fog_revealed

    def teardown(self, gv: GameView) -> None:
        # Save fog state back from GameView
        self._fog_grid = gv._fog_grid
        self._fog_revealed = gv._fog_revealed

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        return self.world_width / 2, 200.0  # spawn near bottom

    def update(self, gv: GameView, dt: float) -> None:
        """Check walls and exits, update fog, then delegate to subclass hazards."""
        self._wall_pulse = (self._wall_pulse + dt * 2.0) % (math.pi * 2)
        self._time_in_zone += dt
        # Walls close in over time (max 400px extra = ~2 min to get very tight)
        self._wall_extra = min(400.0, self._time_in_zone * self._wall_close_rate)
        self._update_fog(gv)
        self._check_walls(gv)
        self._check_exits(gv)
        self._update_hazards(gv, dt)

    def _update_fog(self, gv: GameView) -> None:
        """Reveal fog cells around the player."""
        px, py = gv.player.center_x, gv.player.center_y
        cx = int(px / FOG_CELL_SIZE)
        cy = int(py / FOG_CELL_SIZE)
        r = int(FOG_REVEAL_RADIUS / FOG_CELL_SIZE) + 1
        for gy in range(max(0, cy - r), min(_FOG_H, cy + r + 1)):
            for gx in range(max(0, cx - r), min(_FOG_W, cx + r + 1)):
                if not self._fog_grid[gy][gx]:
                    cell_cx = (gx + 0.5) * FOG_CELL_SIZE
                    cell_cy = (gy + 0.5) * FOG_CELL_SIZE
                    if math.hypot(px - cell_cx, py - cell_cy) <= FOG_REVEAL_RADIUS:
                        self._fog_grid[gy][gx] = True
                        self._fog_revealed += 1
                        gv._fog_revealed = self._fog_revealed

    @property
    def _effective_wall(self) -> float:
        """Current wall thickness including closing."""
        return WALL_ZONE + self._wall_extra

    def _check_walls(self, gv: GameView) -> None:
        """Red energy walls on left and right — drain shields and return."""
        px = gv.player.center_x
        wall = self._effective_wall
        if px < wall or px > self.world_width - wall:
            gv.player.shields = 0
            gv._flash_game_msg("Energy wall! Shields drained!", 2.0)
            self._return_to_main(gv)

    def _check_exits(self, gv: GameView) -> None:
        """Bottom = safe return to zone 1. Top = zone 2."""
        if gv.player.center_y < EXIT_THRESHOLD:
            self._return_to_main(gv)
        elif gv.player.center_y > self.world_height - EXIT_THRESHOLD:
            gv._transition_zone(ZoneID.ZONE2, entry_side="bottom")

    def _return_to_main(self, gv: GameView) -> None:
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

    def _update_hazards(self, gv: GameView, dt: float) -> None:
        """Override in subclasses for zone-specific hazard logic."""

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        """Draw red wall glow (grows over time) + delegate to subclass."""
        alpha = int(120 + 60 * abs(math.sin(self._wall_pulse)))
        wall = self._effective_wall
        # Left wall glow
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, wall, self.world_height),
            (255, 30, 30, alpha))
        # Right wall glow
        arcade.draw_rect_filled(
            arcade.LBWH(self.world_width - wall, 0,
                        wall, self.world_height),
            (255, 30, 30, alpha))
        self._draw_hazards(gv, cx, cy, hw, hh)

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        """Override in subclasses for zone-specific hazard drawing."""

    def get_minimap_objects(self) -> tuple[arcade.SpriteList, arcade.SpriteList]:
        """Return (obstacle_list, enemy_list) for minimap display. Override in subclasses."""
        return arcade.SpriteList(), arcade.SpriteList()

    def to_save_data(self) -> dict:
        return {"return_pos": list(self._return_pos)}

    def from_save_data(self, data: dict, gv: GameView) -> None:
        rp = data.get("return_pos", [3200, 3200])
        self._return_pos = (rp[0], rp[1])
