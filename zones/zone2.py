"""Zone 2 — second biome (stub with return wormhole to zone 1)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from zones import ZoneID, ZoneState
from sprites.wormhole import Wormhole

if TYPE_CHECKING:
    from game_view import GameView


class Zone2(ZoneState):
    zone_id = ZoneID.ZONE2
    world_width = 6400
    world_height = 6400

    def setup(self, gv: GameView) -> None:
        # Single wormhole at centre leading back to zone 1
        wh = Wormhole(self.world_width / 2, self.world_height / 2)
        wh.zone_target = ZoneID.MAIN
        gv._wormholes = [wh]
        gv._wormhole_list.clear()
        gv._wormhole_list.append(wh)

    def teardown(self, gv: GameView) -> None:
        gv._wormholes.clear()
        gv._wormhole_list.clear()

    def get_player_spawn(self, entry_side: str) -> tuple[float, float]:
        return self.world_width / 2, self.world_height / 2 - 200

    def update(self, gv: GameView, dt: float) -> None:
        import math
        # Update wormhole animation
        for wh in gv._wormholes:
            wh.update_wormhole(dt)
        # Check wormhole collision
        px, py = gv.player.center_x, gv.player.center_y
        for wh in gv._wormholes:
            if math.hypot(px - wh.center_x, py - wh.center_y) < 64:
                if wh.zone_target is not None:
                    gv._transition_zone(wh.zone_target, entry_side="wormhole_return")
                    return

    def draw_world(self, gv: GameView, cx: float, cy: float,
                   hw: float, hh: float) -> None:
        if gv._wormholes:
            gv._wormhole_list.draw()
