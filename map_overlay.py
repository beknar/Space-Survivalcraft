"""Full-screen map overlay toggled by the 'M' key.

Covers ~80% of the window with a large zone map.  Re-uses the
existing ``hud_minimap.draw_minimap`` renderer (fog + asteroid +
alien + building + trade + boss + gas + wormhole + slipspace +
null-field + parked-ship markers) at a much bigger size so the
player can actually plan routes across the 9600 × 9600 Nebula.

While the map is open, ``draw_logic.draw_ui`` treats it as a
modal overlay so the character and music videos aren't rendered
behind it (saves the decode + blit + readback cost and avoids
distracting the player).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import STATUS_WIDTH

if TYPE_CHECKING:
    from game_view import GameView


# Fraction of the non-HUD window area the map covers.  0.92 leaves a
# thin gutter on each edge so the surrounding darkness still reads as
# "overlay" not "new screen".
_MAP_FRACTION: float = 0.92


class MapOverlay:
    """Non-pausing full-screen map toggled by 'M'."""

    def __init__(self) -> None:
        self.open: bool = False
        # Title + hint text pre-built so we don't rebuild pyglet labels
        # every frame the map is open.
        self._t_title = arcade.Text(
            "MAP", 0, 0, arcade.color.LIGHT_GRAY, 18, bold=True,
            anchor_x="center",
        )
        self._t_hint = arcade.Text(
            "Press M to close", 0, 0, (160, 160, 160), 11,
            anchor_x="center",
        )

    def toggle(self) -> None:
        self.open = not self.open

    def _rect(self, window_w: int, window_h: int) -> tuple[int, int, int, int]:
        """Return the (x, y, w, h) for the map canvas.

        Spans the non-HUD play area (right of ``STATUS_WIDTH``) with
        a small inset so the panel border shows.
        """
        play_x = STATUS_WIDTH
        play_w = window_w - STATUS_WIDTH
        mw = int(play_w * _MAP_FRACTION)
        mh = int(window_h * _MAP_FRACTION)
        mx = play_x + (play_w - mw) // 2
        my = (window_h - mh) // 2
        return mx, my, mw, mh

    def draw(self, gv: GameView) -> None:
        if not self.open:
            return
        from draw_logic import (
            _gas_positions, _gas_always_visible,
            _null_field_positions, _slipspace_positions,
            _minimap_obstacles, _minimap_enemies,
        )
        from hud_minimap import draw_minimap

        win = arcade.get_window()
        mx, my, mw, mh = self._rect(win.width, win.height)

        # Position the title + hint at the top and bottom of the
        # canvas respectively — draw_minimap only draws its own frame
        # and the passed-in Text at whatever position it's been set to.
        self._t_title.x = mx + mw // 2
        self._t_title.y = my + mh + 8

        draw_minimap(
            self._t_title,
            asteroid_list=_minimap_obstacles(gv),
            iron_pickup_list=gv.iron_pickup_list,
            alien_list=_minimap_enemies(gv),
            player_x=gv.player.center_x,
            player_y=gv.player.center_y,
            player_heading=gv.player.heading,
            building_list=gv.building_list,
            fog_grid=gv._fog_grid,
            fog_revealed=gv._fog_revealed,
            trade_station_pos=(
                (gv._trade_station.center_x, gv._trade_station.center_y)
                if gv._trade_station is not None else None),
            boss_pos=(
                (gv._boss.center_x, gv._boss.center_y)
                if gv._boss is not None and gv._boss.hp > 0 else None),
            extra_boss_positions=(
                [(gv._nebula_boss.center_x, gv._nebula_boss.center_y)]
                if getattr(gv, "_nebula_boss", None) is not None
                   and gv._nebula_boss.hp > 0 else None),
            wormhole_positions=[
                (wh.center_x, wh.center_y) for wh in gv._wormholes],
            zone_width=gv._zone.world_width,
            zone_height=gv._zone.world_height,
            gas_positions=_gas_positions(gv),
            gas_always_visible=_gas_always_visible(gv),
            parked_ship_positions=[
                (ps.center_x, ps.center_y) for ps in gv._parked_ships],
            null_field_positions=_null_field_positions(gv),
            slipspace_positions=_slipspace_positions(gv),
            rect=(mx, my, mw, mh),
        )

        self._t_hint.x = mx + mw // 2
        self._t_hint.y = my - 18
        self._t_hint.draw()
