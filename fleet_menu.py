"""Fleet Control click-menu overlay (hotkey ``Y``).

Issues orders to the player's currently-deployed drone.  Two
direct-action buttons execute one-shot orders and two reaction
buttons toggle the drone's persistent default behaviour:

  * **RETURN** — direct.  Drone breaks off whatever it's doing and
    A*-paths back to the player.  Auto-clears once the drone is
    close again.
  * **ATTACK** — direct.  Drone stops following and engages every
    detected enemy until manually cleared (or the player issues
    RETURN).  A*-paths to chase enemies through maze walls.
  * **FOLLOW ONLY** — reaction.  Drone passively follows the
    player; never enters ATTACK mode even when targets are in
    range.
  * **ATTACK ONLY** — reaction (default).  Drone engages enemies
    (combat) or asteroids (mining) when in detect range; otherwise
    follows.  Restores the original autonomous behaviour.

Has no effect when no drone is deployed.
"""
from __future__ import annotations

from typing import Optional

import arcade

from menu_overlay import MenuOverlay


_PANEL_W = 360
_PANEL_H = 280
_BTN_W = 280
_BTN_H = 40
_BTN_GAP = 12


class FleetMenu(MenuOverlay):
    """Modal overlay listing four drone-command buttons."""

    _title_text = "FLEET CONTROL"
    _close_text = "Y / ESC to close"

    # Button identifiers returned by ``on_mouse_press``.  Caller maps
    # these to ``combat_helpers.apply_fleet_order``.
    BTN_RETURN = "return"
    BTN_ATTACK = "attack"
    BTN_FOLLOW_ONLY = "follow_only"
    BTN_ATTACK_ONLY = "attack_only"

    def __init__(self) -> None:
        super().__init__()
        self._hover: str | None = None
        self._status_text: str = ""
        self._t_status = arcade.Text(
            "", 0, 0, arcade.color.LIGHT_GRAY, 10,
            anchor_x="center", anchor_y="center",
        )
        # Pre-built per-button labels so we don't rebuild pyglet
        # Text objects every frame the menu is open.
        self._btn_labels = {
            self.BTN_RETURN:
                ("RETURN  —  break off, fly back to ship", (40, 80, 130)),
            self.BTN_ATTACK:
                ("ATTACK  —  engage all nearby enemies", (130, 40, 40)),
            self.BTN_FOLLOW_ONLY:
                ("FOLLOW ONLY  —  passive escort", (40, 70, 50)),
            self.BTN_ATTACK_ONLY:
                ("ATTACK ONLY  —  default reaction", (90, 70, 30)),
        }
        self._t_btn_per: dict[str, arcade.Text] = {
            k: arcade.Text(v[0], 0, 0, arcade.color.WHITE, 11,
                           bold=True, anchor_x="center",
                           anchor_y="center")
            for k, v in self._btn_labels.items()
        }

    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else 1280
        sh = self._window.height if self._window else 720
        return (sw - _PANEL_W) // 2, (sh - _PANEL_H) // 2

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self._status_text = ""
            self._hover = None

    def _btn_order(self) -> list[str]:
        return [
            self.BTN_RETURN, self.BTN_ATTACK,
            self.BTN_FOLLOW_ONLY, self.BTN_ATTACK_ONLY,
        ]

    def _btn_rect(self, button_id: str) -> tuple[int, int, int, int]:
        """Layout: 4 stacked buttons, top-down."""
        px, py = self._panel_origin()
        # Top button sits below the title (~38 px from panel top);
        # each subsequent button steps down by BTN_H + GAP.
        idx = self._btn_order().index(button_id)
        bx = px + (_PANEL_W - _BTN_W) // 2
        top_by = py + _PANEL_H - 38 - _BTN_H
        by = top_by - idx * (_BTN_H + _BTN_GAP)
        return bx, by, _BTN_W, _BTN_H

    def on_mouse_motion(self, x: float, y: float) -> None:
        self._hover = None
        for k in self._btn_order():
            bx, by, bw, bh = self._btn_rect(k)
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self._hover = k
                return

    def on_mouse_press(self, x: float, y: float) -> Optional[str]:
        if not self.open:
            return None
        px, py = self._panel_origin()
        if not (px <= x <= px + _PANEL_W and py <= y <= py + _PANEL_H):
            self.open = False
            return None
        for k in self._btn_order():
            bx, by, bw, bh = self._btn_rect(k)
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return k
        return None

    def on_key_press(self, key: int) -> None:
        if key in (arcade.key.ESCAPE, arcade.key.Y):
            self.open = False

    def set_status(self, msg: str) -> None:
        """Flash a one-liner below the button column (e.g. "No drone
        deployed", "Order: RETURN")."""
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
        self._t_title.y = py + _PANEL_H - 18
        self._t_title.draw()

        for k in self._btn_order():
            bx, by, bw, bh = self._btn_rect(k)
            base = self._btn_labels[k][1]
            if self._hover == k:
                fill = (
                    min(255, base[0] + 30),
                    min(255, base[1] + 30),
                    min(255, base[2] + 30),
                    240,
                )
            else:
                fill = (base[0], base[1], base[2], 220)
            arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), fill)
            arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh),
                                     arcade.color.STEEL_BLUE,
                                     border_width=1)
            t = self._t_btn_per[k]
            t.x = bx + bw // 2
            t.y = by + bh // 2
            t.draw()

        if self._status_text:
            self._t_status.text = self._status_text
            self._t_status.x = px + _PANEL_W // 2
            self._t_status.y = py + 26
            self._t_status.draw()

        self._t_close.x = px + _PANEL_W // 2
        self._t_close.y = py + 10
        self._t_close.draw()
