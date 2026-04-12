"""Station info overlay for Space Survivalcraft — shows building HP and module stats."""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

import arcade as _arcade_mod

if TYPE_CHECKING:
    pass

# Panel dimensions
_PANEL_W = 280
_PANEL_H = 490
_PANEL_PAD = 12
_LINE_H = 22
_MAX_LINES = 14  # max building lines in pool
_MAX_STAT_LINES = 8  # max world-stat lines in pool


class StationInfo:
    """Non-pausing right-side overlay showing station module HP and capacity."""

    def __init__(self) -> None:
        self.open: bool = False

        # Panel position (right side)
        self._window = _arcade_mod.get_window()
        self._px = self._window.width - _PANEL_W - 10
        self._py = (self._window.height - _PANEL_H) // 2

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

        # World stats — pool of generic stat lines (label + count)
        self._t_stats: list[arcade.Text] = []
        for i in range(_MAX_STAT_LINES):
            y = self._py + 80 - i * 18
            self._t_stats.append(arcade.Text(
                "", self._px + _PANEL_PAD, y,
                (200, 200, 200), 11,
            ))

        # Cached data
        self._building_data: list[tuple[str, int, int, bool]] = []
        self._modules_used: int = 0
        self._module_capacity: int = 0
        # List of (label, count, color) tuples for world stats
        self._stat_lines: list[tuple[str, int, tuple]] = []

    def toggle(
        self,
        building_list: arcade.SpriteList,
        modules_used: int,
        module_capacity: int,
        stat_lines: list[tuple[str, int, tuple]] | None = None,
    ) -> None:
        """Toggle overlay, refreshing building data when opening."""
        self.open = not self.open
        if self.open:
            self._refresh(building_list, modules_used, module_capacity,
                          stat_lines)

    def _refresh(
        self,
        building_list: arcade.SpriteList,
        modules_used: int,
        module_capacity: int,
        stat_lines: list[tuple[str, int, tuple]] | None = None,
    ) -> None:
        self._modules_used = modules_used
        self._module_capacity = module_capacity
        self._stat_lines = stat_lines or []
        self._building_data = []
        for b in building_list:
            self._building_data.append((
                b.building_type,
                b.hp,
                b.max_hp,
                b.disabled,
            ))

    def update_stats(self, stat_lines: list[tuple[str, int, tuple]]) -> None:
        """Update world stats while panel is open (called every frame)."""
        self._stat_lines = stat_lines

    def draw(self) -> None:
        if not self.open:
            return
        # Update panel position for current window size
        self._px = self._window.width - _PANEL_W - 10
        self._py = (self._window.height - _PANEL_H) // 2
        self._t_title.x = self._px + _PANEL_W // 2
        self._t_title.y = self._py + _PANEL_H - 20

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
        self._t_footer.x = self._px + _PANEL_W // 2
        self._t_footer.y = self._py + 100
        self._t_footer.text = (
            f"Modules: {self._modules_used} / {self._module_capacity} used"
        )
        self._t_footer.draw()

        # World stats — render up to _MAX_STAT_LINES rows
        for i, t in enumerate(self._t_stats):
            if i < len(self._stat_lines):
                label, count, color = self._stat_lines[i]
                t.x = self._px + _PANEL_PAD
                t.y = self._py + 80 - i * 18
                t.text = f"{label:<11} {count:>5}"
                t.color = color
                t.draw()
