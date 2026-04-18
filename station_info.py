"""Station info overlay for Space Survivalcraft — shows building HP and module stats."""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

import arcade as _arcade_mod

if TYPE_CHECKING:
    pass

# Panel dimensions.
# _PANEL_H was bumped from 490 -> 580 on 2026-04-18 because the
# world-stats list grew to 7 rows in Zone 2 once NULL FIELDS was
# added, pushing the bottom row off the panel.  580 fits 14 building
# lines + footer + 8 stat lines comfortably.  See _STAT_BASELINE
# below for the stats anchor.
_PANEL_W = 280
_PANEL_H = 580
_PANEL_PAD = 12
_LINE_H = 22
_MAX_LINES = 14  # max building lines in pool
_MAX_STAT_LINES = 8  # max world-stat lines in pool
# Stats are drawn ABOVE the footer.  Top of the stat region is at
# py + _STAT_BASELINE; row i lives at py + _STAT_BASELINE - i*18.
# With baseline=200 and 8 rows, the bottom row is at py + 74 (well
# above the panel floor at py).
_STAT_BASELINE = 200
_FOOTER_Y = 24             # was 100 — moved to the panel floor

# Inactive zones panel (drawn to the left of the main panel)
_IZ_PANEL_W = 240
_IZ_PANEL_H = 320
_IZ_MAX_ZONES = 2
_IZ_MAX_LINES_PER_ZONE = 8


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

        # Footer: modules used / capacity (sits at the very bottom of
        # the panel so the stat region above can grow without clipping).
        self._t_footer = arcade.Text(
            "",
            self._px + _PANEL_W // 2,
            self._py + _FOOTER_Y,
            arcade.color.LIGHT_GRAY, 11, bold=True,
            anchor_x="center", anchor_y="center",
        )

        # World stats — pool of generic stat lines (label + count).
        # Anchored above the footer so 8 rows always fit inside the
        # panel; row i is at py + _STAT_BASELINE - i*18.
        self._t_stats: list[arcade.Text] = []
        for i in range(_MAX_STAT_LINES):
            y = self._py + _STAT_BASELINE - i * 18
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

        # Inactive zones panel — pre-built text pool
        self._iz_title = arcade.Text(
            "OTHER ZONES", 0, 0,
            (180, 140, 220), 13, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._iz_zone_titles: list[arcade.Text] = []
        self._iz_lines: list[list[arcade.Text]] = []
        for _ in range(_IZ_MAX_ZONES):
            self._iz_zone_titles.append(arcade.Text(
                "", 0, 0, arcade.color.LIGHT_BLUE, 11, bold=True,
            ))
            zone_lines = []
            for _ in range(_IZ_MAX_LINES_PER_ZONE):
                zone_lines.append(arcade.Text(
                    "", 0, 0, (200, 200, 200), 10,
                ))
            self._iz_lines.append(zone_lines)
        # Data: list of (zone_name, [(label, count, color), ...])
        self._iz_data: list[tuple[str, list[tuple[str, int, tuple]]]] = []

    def toggle(
        self,
        building_list: arcade.SpriteList,
        modules_used: int,
        module_capacity: int,
        stat_lines: list[tuple[str, int, tuple]] | None = None,
        inactive_zone_stats: list[tuple[str, list[tuple[str, int, tuple]]]] | None = None,
    ) -> None:
        """Toggle overlay, refreshing building data when opening."""
        self.open = not self.open
        if self.open:
            self._refresh(building_list, modules_used, module_capacity,
                          stat_lines)
            self._iz_data = inactive_zone_stats or []

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

    def update_stats(
        self,
        stat_lines: list[tuple[str, int, tuple]],
        inactive_zone_stats: list[tuple[str, list[tuple[str, int, tuple]]]] | None = None,
    ) -> None:
        """Update world stats while panel is open (called every frame)."""
        self._stat_lines = stat_lines
        if inactive_zone_stats is not None:
            self._iz_data = inactive_zone_stats

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
                    new_text = f"{btype}  —  DISABLED"
                    new_color = (128, 128, 128, 255)
                else:
                    hp_frac = hp / max_hp if max_hp > 0 else 0.0
                    if hp_frac > 0.5:
                        new_color = (0, 200, 0, 255)
                    elif hp_frac > 0.25:
                        new_color = (220, 160, 0, 255)
                    else:
                        new_color = (220, 50, 50, 255)
                    new_text = f"{btype}  —  HP {hp}/{max_hp}"
                if t.text != new_text:
                    t.text = new_text
                if t.color != new_color:
                    t.color = new_color
                t.draw()

        # Footer (panel floor)
        self._t_footer.x = self._px + _PANEL_W // 2
        self._t_footer.y = self._py + _FOOTER_Y
        new_footer = f"Modules: {self._modules_used} / {self._module_capacity} used"
        if self._t_footer.text != new_footer:
            self._t_footer.text = new_footer
        self._t_footer.draw()

        # World stats — render up to _MAX_STAT_LINES rows above footer
        for i, t in enumerate(self._t_stats):
            if i < len(self._stat_lines):
                label, count, color = self._stat_lines[i]
                t.x = self._px + _PANEL_PAD
                t.y = self._py + _STAT_BASELINE - i * 18
                new_text = f"{label:<11} {count:>5}"
                if t.text != new_text:
                    t.text = new_text
                if t.color != color:
                    t.color = color
                t.draw()

        # ── Inactive zones panel (left of main panel) ──────────────────
        if self._iz_data:
            self._draw_inactive_zones()

    def _draw_inactive_zones(self) -> None:
        """Draw a panel showing stats from zones the player is not in."""
        # Compute needed height
        total_lines = 0
        for _, lines in self._iz_data:
            total_lines += 1 + len(lines)  # zone title + stat lines
        iz_h = max(140, 50 + total_lines * 20 + 10)
        iz_x = self._px - _IZ_PANEL_W - 10
        iz_y = self._py + _PANEL_H - iz_h

        arcade.draw_rect_filled(
            arcade.LBWH(iz_x, iz_y, _IZ_PANEL_W, iz_h),
            (15, 15, 40, 230),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(iz_x, iz_y, _IZ_PANEL_W, iz_h),
            (120, 90, 180), border_width=2,
        )

        self._iz_title.x = iz_x + _IZ_PANEL_W // 2
        self._iz_title.y = iz_y + iz_h - 20
        self._iz_title.draw()

        cur_y = iz_y + iz_h - 48
        for zi, (zone_name, zone_lines) in enumerate(self._iz_data):
            if zi >= _IZ_MAX_ZONES:
                break
            # Zone name header
            zt = self._iz_zone_titles[zi]
            if zt.text != zone_name:
                zt.text = zone_name
            zt.x = iz_x + _PANEL_PAD
            zt.y = cur_y
            zt.draw()
            cur_y -= 20

            # Stat lines
            for li, (label, count, color) in enumerate(zone_lines):
                if li >= _IZ_MAX_LINES_PER_ZONE:
                    break
                lt = self._iz_lines[zi][li]
                new_text = f"  {label:<11} {count:>5}"
                if lt.text != new_text:
                    lt.text = new_text
                if lt.color != color:
                    lt.color = color
                lt.x = iz_x + _PANEL_PAD
                lt.y = cur_y
                lt.draw()
                cur_y -= 20
            cur_y -= 6  # gap between zones
