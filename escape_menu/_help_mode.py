"""Help/controls sub-mode for the escape menu."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit

_HELP_LINES = [
    ("L/R  or  A/D", "Rotate"),
    ("Up   or  W", "Thrust"),
    ("Down or  S", "Brake"),
    ("Space", "Fire weapon"),
    ("Tab", "Cycle weapon"),
    ("I", "Inventory"),
    ("B", "Build menu"),
    ("T", "Station info"),
    ("F", "Toggle FPS"),
    ("ESC", "Menu"),
]
_GAMEPAD_LINES = [
    ("Left stick", "Move / Rotate"),
    ("A button", "Fire"),
    ("RB", "Cycle weapon"),
    ("Y button", "Inventory"),
]


class HelpMode(MenuMode):

    def draw(self) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
        draw_panel(px, py)

        self.ctx.t_title.text = "CONTROLS"
        self.ctx.t_title.x = cx
        self.ctx.t_title.y = py + MENU_H - 30
        self.ctx.t_title.draw()

        t = self.ctx.t_text
        ti = self.ctx.t_info
        line_y = py + MENU_H - 60

        for section_title, color, lines in [
            ("KEYBOARD", arcade.color.LIGHT_BLUE, _HELP_LINES),
            ("GAMEPAD", arcade.color.LIGHT_GREEN, _GAMEPAD_LINES),
        ]:
            t.bold = True
            t.text = section_title
            t.x = cx
            t.y = line_y
            t.color = color
            t.anchor_x = "center"
            t.draw()
            t.anchor_x = "left"
            line_y -= 20
            for key_text, action in lines:
                t.text = key_text
                t.x = px + 16
                t.y = line_y
                t.color = (180, 180, 180)
                t.bold = False
                t.draw()
                ti.text = action
                ti.x = px + MENU_W - 16
                ti.y = line_y
                ti.color = arcade.color.WHITE
                ti.anchor_x = "right"
                ti.draw()
                ti.anchor_x = "center"
                line_y -= 18
            line_y -= 10

        draw_back_button(px, py, self.ctx.t_back)

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        if back_button_hit(x, y, px, py):
            self.ctx.play_click()
            self.ctx.set_mode("main")

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("main")
