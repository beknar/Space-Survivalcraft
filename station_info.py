"""Station info overlay for Space Survivalcraft — shows building HP and module stats."""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import SCREEN_WIDTH, SCREEN_HEIGHT

if TYPE_CHECKING:
    pass

# Panel dimensions
_PANEL_W = 280
_PANEL_H = 420
_PANEL_PAD = 12
_LINE_H = 22
_MAX_LINES = 14  # max building lines in pool


class StationInfo:
    """Non-pausing right-side overlay showing station module HP and capacity."""

    def __init__(self) -> None:
        self.open: bool = False

        # Panel position (right side)
        self._px = SCREEN_WIDTH - _PANEL_W - 10
        self._py = (SCREEN_HEIGHT - _PANEL_H) // 2

        # Pre-built text objects
        self._t_title = arcade.Text(
            "STATION INFO",
            self._px + _PANEL_W // 2, self._py + _PANEL_H - 20,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )

        # Pool of building line texts (type + HP)
        self._t_lines: list[arcade.Text] = []
        for i in range(_MAX_LINES):
            y = self._py + _PANEL_H - 50 - i * _LINE_H
            self._t_lines.append(arcade.Text(
                "", self._px + _PANEL_PAD, y,
                arcade.color.WHITE, 10,
            ))

        # Footer: modules used / capacity
        self._t_footer = arcade.Text(
            "",
            self._px + _PANEL_W // 2,
            self._py + 20,
            arcade.color.LIGHT_GRAY, 11, bold=True,
            anchor_x="center", anchor_y="center",
        )

        # Cached data
        self._building_data: list[tuple[str, int, int, bool]] = []
        self._modules_used: int = 0
        self._module_capacity: int = 0

    def toggle(
        self,
        building_list: arcade.SpriteList,
        modules_used: int,
        module_capacity: int,
    ) -> None:
        """Toggle overlay, refreshing building data when opening."""
        self.open = not self.open
        if self.open:
            self._refresh(building_list, modules_used, module_capacity)

    def _refresh(
        self,
        building_list: arcade.SpriteList,
        modules_used: int,
        module_capacity: int,
    ) -> None:
        self._modules_used = modules_used
        self._module_capacity = module_capacity
        self._building_data = []
        for b in building_list:
            self._building_data.append((
                b.building_type,
                b.hp,
                b.max_hp,
                b.disabled,
            ))

    def draw(self) -> None:
        if not self.open:
            return

        # Panel background
        arcade.draw_rect_filled(
            arcade.LBWH(self._px, self._py, _PANEL_W, _PANEL_H),
            (15, 15, 40, 230),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(self._px, self._py, _PANEL_W, _PANEL_H),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        self._t_title.draw()

        # Building lines
        for i, t in enumerate(self._t_lines):
            if i < len(self._building_data):
                btype, hp, max_hp, disabled = self._building_data[i]
                if disabled:
                    t.text = f"{btype}  —  DISABLED"
                    t.color = (128, 128, 128, 255)
                else:
                    hp_frac = hp / max_hp if max_hp > 0 else 0.0
                    if hp_frac > 0.5:
                        color = (0, 200, 0, 255)
                    elif hp_frac > 0.25:
                        color = (220, 160, 0, 255)
                    else:
                        color = (220, 50, 50, 255)
                    t.text = f"{btype}  —  HP {hp}/{max_hp}"
                    t.color = color
                t.draw()

        # Footer
        self._t_footer.text = (
            f"Modules: {self._modules_used} / {self._module_capacity} used"
        )
        self._t_footer.draw()
