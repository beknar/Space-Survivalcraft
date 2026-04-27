"""Help/controls sub-mode for the escape menu."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit

_HELP_LINES = [
    ("L/R  or  A/D", "Rotate"),
    ("Up   or  W", "Thrust"),
    ("Down or  S", "Brake"),
    ("Q", "Sideslip left"),
    ("E", "Sideslip right"),
    ("Space", "Fire weapon"),
    ("Tab", "Cycle weapon"),
    ("I", "Inventory"),
    ("B", "Build menu"),
    ("T", "Station info"),
    ("C", "Ship stats"),
    ("M", "Toggle full-screen map"),
    ("F", "Toggle FPS"),
    ("G", "Force Wall (ability)"),
    ("X", "Death Blossom (ability)"),
    ("WASD x2", "Misty Step (ability)"),
    ("R", "Deploy / swap drone"),
    ("Shift+R", "Recall drone (refund)"),
    ("Y", "Fleet Control (drone orders)"),
    ("ESC", "Menu"),
]
_GAMEPAD_LINES = [
    ("Left stick", "Move / Rotate"),
    ("A button", "Fire"),
    ("RB", "Cycle weapon"),
    ("Y button", "Inventory"),
]
# Multi-line how-to for the drone deploy/recall flow.  Plain text
# (no key/action split) so each line can carry a bit more context
# than a single keybind row would fit.
_DRONE_LINES = [
    "Mining beam active + R: deploy MINING drone",
    "Basic laser active + R: deploy COMBAT drone",
    "Same drone already out: R is a no-op",
    "Other drone already out: R swaps",
    "  (refunds 1 of old, consumes 1 of new)",
    "Shift+R: recall drone (refunds 1 charge)",
    "Y: open Fleet Control menu",
    "  RETURN  — A* back to ship, ignore enemies",
    "  ATTACK  — engage every detected enemy",
    "  FOLLOW ONLY  — passive escort (no fire)",
    "  ATTACK ONLY — default; engage in detect range",
    "Craft both at Adv. Crafter: 200 iron + 100 copper / 5",
    "Hover the drone for HP / shield readout",
]


class HelpMode(MenuMode):

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        # Pre-build all text objects once to avoid .bold/.text churn per frame
        self._t_kb_hdr = arcade.Text("KEYBOARD", 0, 0, arcade.color.LIGHT_BLUE, 10,
                                     bold=True, anchor_x="center")
        self._t_gp_hdr = arcade.Text("GAMEPAD", 0, 0, arcade.color.LIGHT_GREEN, 10,
                                     bold=True, anchor_x="center")
        self._t_drone_hdr = arcade.Text(
            "DRONES", 0, 0, arcade.color.YELLOW_ORANGE, 10,
            bold=True, anchor_x="center")
        self._t_keys: list[arcade.Text] = []
        self._t_actions: list[arcade.Text] = []
        for lines in (_HELP_LINES, _GAMEPAD_LINES):
            for key_text, action in lines:
                self._t_keys.append(arcade.Text(key_text, 0, 0, (180, 180, 180), 10))
                self._t_actions.append(arcade.Text(action, 0, 0, arcade.color.WHITE, 9,
                                                   anchor_x="right"))
        # Drone how-to is rendered as plain left-aligned lines
        # (no key/action split) so each step can carry a bit more
        # context than a single keybind row would.
        self._t_drone_lines: list[arcade.Text] = [
            arcade.Text(line, 0, 0, arcade.color.WHITE, 9)
            for line in _DRONE_LINES
        ]

    def draw(self) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
        draw_panel(px, py)

        self.ctx.t_title.text = "CONTROLS"
        self.ctx.t_title.x = cx
        self.ctx.t_title.y = py + MENU_H - 30
        self.ctx.t_title.draw()

        line_y = py + MENU_H - 60
        item_idx = 0
        for hdr, lines in [
            (self._t_kb_hdr, _HELP_LINES),
            (self._t_gp_hdr, _GAMEPAD_LINES),
        ]:
            hdr.x = cx; hdr.y = line_y; hdr.draw()
            line_y -= 20
            for _ in lines:
                tk = self._t_keys[item_idx]
                ta = self._t_actions[item_idx]
                tk.x = px + 16; tk.y = line_y; tk.draw()
                ta.x = px + MENU_W - 16; ta.y = line_y; ta.draw()
                line_y -= 18
                item_idx += 1
            line_y -= 10

        # Drones — multi-line procedural how-to (full-width plain
        # text instead of key/action pairs).
        self._t_drone_hdr.x = cx
        self._t_drone_hdr.y = line_y
        self._t_drone_hdr.draw()
        line_y -= 18
        for tline in self._t_drone_lines:
            tline.x = px + 16
            tline.y = line_y
            tline.draw()
            line_y -= 14

        draw_back_button(px, py, self.ctx.t_back)

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        if back_button_hit(x, y, px, py):
            self.ctx.play_click()
            self.ctx.set_mode("main")

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("main")
