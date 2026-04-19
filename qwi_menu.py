"""Quantum Wave Integrator click-menu overlay.

Opens when the player clicks a QWI building within station-info
range.  Shows a single button: "SUMMON NEBULA BOSS — 100 iron".
Clicking the button consumes 100 iron from the player's inventory
and spawns the Nebula boss via ``combat_helpers.spawn_nebula_boss``.
"""
from __future__ import annotations

from typing import Optional

import arcade

from menu_overlay import MenuOverlay
from constants import QWI_SPAWN_NEBULA_BOSS_IRON_COST


_PANEL_W = 320
_PANEL_H = 180


class QWIMenu(MenuOverlay):
    """Non-pausing overlay shown when a Quantum Wave Integrator is
    clicked.  Single-action menu — the button spawns the Nebula boss
    for 100 iron (or shows a flash if the player can't afford it)."""

    _title_text = "QUANTUM WAVE INTEGRATOR"
    _close_text = "ESC / click outside to close"

    def __init__(self) -> None:
        super().__init__()
        self._btn_hover: bool = False
        self._status_text: str = ""
        self._t_btn.text = f"SUMMON NEBULA BOSS  —  {QWI_SPAWN_NEBULA_BOSS_IRON_COST} iron"
        self._t_btn.font_size = 11
        self._t_status = arcade.Text(
            "", 0, 0, arcade.color.LIGHT_GRAY, 10,
            anchor_x="center", anchor_y="center",
        )

    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else 1280
        sh = self._window.height if self._window else 720
        return (sw - _PANEL_W) // 2, (sh - _PANEL_H) // 2

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self._status_text = ""

    def _btn_rect(self) -> tuple[int, int, int, int]:
        px, py = self._panel_origin()
        bw, bh = 240, 40
        bx = px + (_PANEL_W - bw) // 2
        by = py + (_PANEL_H - bh) // 2 - 10
        return bx, by, bw, bh

    def on_mouse_motion(self, x: float, y: float) -> None:
        bx, by, bw, bh = self._btn_rect()
        self._btn_hover = (bx <= x <= bx + bw and by <= y <= by + bh)

    def on_mouse_press(self, x: float, y: float) -> Optional[str]:
        """Return 'spawn_nebula_boss' when the button is clicked, or
        None if the click missed.  Clicks outside the panel close the
        overlay (handled by the caller)."""
        if not self.open:
            return None
        px, py = self._panel_origin()
        # Click outside panel closes.
        if not (px <= x <= px + _PANEL_W and py <= y <= py + _PANEL_H):
            self.open = False
            return None
        bx, by, bw, bh = self._btn_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            return "spawn_nebula_boss"
        return None

    def on_key_press(self, key: int) -> None:
        if key == arcade.key.ESCAPE:
            self.open = False

    def set_status(self, msg: str) -> None:
        """Flash a one-liner below the button (used for 'Not enough
        iron' or 'Nebula boss spawned!')."""
        self._status_text = msg

    def draw(self) -> None:
        if not self.open:
            return
        px, py = self._panel_origin()

        arcade.draw_rect_filled(
            arcade.LBWH(px, py, _PANEL_W, _PANEL_H), (15, 20, 45, 240))
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, _PANEL_W, _PANEL_H),
            arcade.color.STEEL_BLUE, border_width=2)

        self._t_title.x = px + _PANEL_W // 2
        self._t_title.y = py + _PANEL_H - 22
        self._t_title.draw()

        bx, by, bw, bh = self._btn_rect()
        btn_fill = ((60, 30, 100, 230) if self._btn_hover
                    else (40, 20, 80, 220))
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), btn_fill)
        arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh),
                                 arcade.color.STEEL_BLUE, border_width=1)
        self._t_btn.x = bx + bw // 2
        self._t_btn.y = by + bh // 2
        self._t_btn.draw()

        if self._status_text:
            self._t_status.text = self._status_text
            self._t_status.x = px + _PANEL_W // 2
            self._t_status.y = by - 16
            self._t_status.draw()

        self._t_close.x = px + _PANEL_W // 2
        self._t_close.y = py + 12
        self._t_close.draw()
