"""Craft menu overlay for the Basic Crafter module."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    CRAFT_TIME, CRAFT_IRON_COST, CRAFT_RESULT_COUNT,
)

_PANEL_W = 280
_PANEL_H = 200


class CraftMenu:
    """Overlay for the Basic Crafter — shows Repair Pack recipe and craft button."""

    def __init__(self) -> None:
        self.open: bool = False
        self._crafting: bool = False
        self._progress: float = 0.0  # 0.0–1.0

        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None

        self._t_title = arcade.Text(
            "BASIC CRAFTER", 0, 0,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_recipe = arcade.Text("", 0, 0, arcade.color.WHITE, 10)
        self._t_cost = arcade.Text("", 0, 0, arcade.color.ORANGE, 10)
        self._t_result = arcade.Text("", 0, 0, arcade.color.LIME_GREEN, 10)
        self._t_status = arcade.Text("", 0, 0, arcade.color.YELLOW, 10, bold=True,
                                     anchor_x="center")
        self._t_btn = arcade.Text(
            "CRAFT", 0, 0, arcade.color.WHITE, 12, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_close = arcade.Text(
            "ESC / click outside to close", 0, 0,
            (120, 120, 120), 8, anchor_x="center",
        )

    def toggle(self) -> None:
        self.open = not self.open

    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        return (sw - _PANEL_W) // 2, (sh - _PANEL_H) // 2

    def _craft_btn_rect(self) -> tuple[int, int, int, int]:
        px, py = self._panel_origin()
        bw, bh = 120, 32
        bx = px + (_PANEL_W - bw) // 2
        by = py + 40
        return bx, by, bw, bh

    def on_mouse_press(self, x: float, y: float, station_iron: int) -> Optional[str]:
        """Returns 'craft' if craft button clicked and affordable, None otherwise."""
        if not self.open:
            return None
        px, py = self._panel_origin()
        # Outside panel → close
        if not (px <= x <= px + _PANEL_W and py <= y <= py + _PANEL_H):
            self.open = False
            return None
        # Craft button
        bx, by, bw, bh = self._craft_btn_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            if not self._crafting and station_iron >= CRAFT_IRON_COST:
                return "craft"
        return None

    def update(self, progress: float, crafting: bool) -> None:
        """Update progress bar state from the BasicCrafter module."""
        self._progress = progress
        self._crafting = crafting

    def draw(self, station_iron: int) -> None:
        if not self.open:
            return
        px, py = self._panel_origin()

        # Panel bg
        arcade.draw_rect_filled(
            arcade.LBWH(px, py, _PANEL_W, _PANEL_H), (15, 20, 45, 240),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, _PANEL_W, _PANEL_H),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        # Title
        self._t_title.x = px + _PANEL_W // 2
        self._t_title.y = py + _PANEL_H - 20
        self._t_title.draw()

        # Recipe info
        self._t_recipe.text = "Recipe: Repair Pack"
        self._t_recipe.x = px + 16
        self._t_recipe.y = py + _PANEL_H - 50
        self._t_recipe.draw()

        cost_colour = arcade.color.ORANGE if station_iron >= CRAFT_IRON_COST else (200, 60, 60)
        self._t_cost.text = f"Cost: {CRAFT_IRON_COST} iron (station has {station_iron})"
        self._t_cost.x = px + 16
        self._t_cost.y = py + _PANEL_H - 70
        self._t_cost.color = cost_colour
        self._t_cost.draw()

        self._t_result.text = f"Produces: {CRAFT_RESULT_COUNT}× Repair Pack ({int(CRAFT_TIME)}s)"
        self._t_result.x = px + 16
        self._t_result.y = py + _PANEL_H - 90
        self._t_result.draw()

        # Craft button
        bx, by, bw, bh = self._craft_btn_rect()
        if self._crafting:
            fill = (40, 40, 60, 220)
        elif station_iron >= CRAFT_IRON_COST:
            fill = (30, 80, 30, 220)
        else:
            fill = (60, 30, 30, 220)
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), fill)
        arcade.draw_rect_outline(
            arcade.LBWH(bx, by, bw, bh), arcade.color.STEEL_BLUE, border_width=1,
        )
        label = "CRAFTING..." if self._crafting else "CRAFT"
        self._t_btn.text = label
        self._t_btn.x = bx + bw // 2
        self._t_btn.y = by + bh // 2
        self._t_btn.draw()

        # Progress bar
        if self._crafting:
            bar_w = _PANEL_W - 32
            bar_x = px + 16
            bar_y = py + 84
            arcade.draw_rect_filled(
                arcade.LBWH(bar_x, bar_y, bar_w, 12), (30, 30, 50),
            )
            arcade.draw_rect_filled(
                arcade.LBWH(bar_x, bar_y, int(bar_w * self._progress), 12),
                (50, 180, 50),
            )
            arcade.draw_rect_outline(
                arcade.LBWH(bar_x, bar_y, bar_w, 12),
                arcade.color.STEEL_BLUE, border_width=1,
            )
            self._t_status.text = f"{int(self._progress * 100)}%"
            self._t_status.x = px + _PANEL_W // 2
            self._t_status.y = bar_y + 6
            self._t_status.draw()

        # Close hint
        self._t_close.x = px + _PANEL_W // 2
        self._t_close.y = py + 10
        self._t_close.draw()
