"""Base class for all warp zones — shared wall, exit, and drawing logic."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from zones import ZoneID, ZoneState

if TYPE_CHECKING:
    from game_view import GameView

WARP_ZONE_WIDTH = 3200
WARP_ZONE_HEIGHT = 6400
WALL_ZONE = 60           # px thickness of red wall regions
EXIT_THRESHOLD = 50       # px from edge to trigger exit


class WarpZoneBase(ZoneState):
    """Shared behaviour for all 4 warp zones."""
    world_width = WARP_ZONE_WIDTH
    world_height = WARP_ZONE_HEIGHT

    def __init__(self) -> None:
        self._return_pos: tuple[float, float] = (3200, 3200)
        self._wall_pulse: float = 0.0

    def setup(self, gv: GameView) -> None:
        """Store return position and set player world bounds."""
        self._return_pos = (gv.player.center_x, gv.player.center_y)

    def teardown(self, gv: GameView) -> None:
        pass

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        return self.world_width / 2, 200.0  # spawn near bottom

    def update(self, gv: GameView, dt: float) -> None:
        """Check walls and exits, then delegate to subclass hazards."""
        self._wall_pulse = (self._wall_pulse + dt * 2.0) % (math.pi * 2)
        self._check_walls(gv)
        self._check_exits(gv)
        self._update_hazards(gv, dt)

    def _check_walls(self, gv: GameView) -> None:
        """Red energy walls on left and right — drain shields and return."""
        px = gv.player.center_x
        if px < WALL_ZONE or px > self.world_width - WALL_ZONE:
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
        """Draw red wall glow + delegate to subclass."""
        alpha = int(120 + 60 * abs(math.sin(self._wall_pulse)))
        # Left wall glow
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, WALL_ZONE, self.world_height),
            (255, 30, 30, alpha))
        # Right wall glow
        arcade.draw_rect_filled(
            arcade.LBWH(self.world_width - WALL_ZONE, 0,
                        WALL_ZONE, self.world_height),
            (255, 30, 30, alpha))
        self._draw_hazards(gv, cx, cy, hw, hh)

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        """Override in subclasses for zone-specific hazard drawing."""

    def to_save_data(self) -> dict:
        return {"return_pos": list(self._return_pos)}

    def from_save_data(self, data: dict, gv: GameView) -> None:
        rp = data.get("return_pos", [3200, 3200])
        self._return_pos = (rp[0], rp[1])
