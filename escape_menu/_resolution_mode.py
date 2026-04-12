"""Resolution selector sub-mode for the escape menu."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H, RESOLUTION_PRESETS
from escape_menu._context import MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit


class ResolutionMode(MenuMode):

    def draw(self) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
        mid_y = py + MENU_H // 2
        draw_panel(px, py)

        self.ctx.t_title.text = "RESOLUTION"
        self.ctx.t_title.x = cx; self.ctx.t_title.y = py + MENU_H - 30
        self.ctx.t_title.draw()

        # Resolution value
        w, h = RESOLUTION_PRESETS[self.ctx.res_idx]
        ti = self.ctx.t_info
        ti.text = f"{w} x {h}"; ti.x = cx; ti.y = mid_y
        ti.color = arcade.color.YELLOW; ti.draw()

        # Arrows
        t = self.ctx.t_text
        t.bold = True; t.color = (180, 180, 180)
        t.text = "<"; t.x = px + 48; t.y = mid_y; t.anchor_x = "center"; t.draw()
        t.text = ">"; t.x = px + MENU_W - 48; t.draw()
        t.anchor_x = "left"

        abx = px + (MENU_W - MENU_BTN_W) // 2
        for i, (label, y_off, bg, outline) in enumerate([
            ("Apply Windowed", -50, (30, 60, 30, 220), arcade.color.LIME_GREEN),
            ("Apply Fullscreen", -50 - MENU_BTN_H - 12, (30, 30, 60, 220), arcade.color.CYAN),
            ("Borderless Windowed", -50 - 2 * (MENU_BTN_H + 12), (40, 30, 60, 220), (120, 100, 200)),
        ]):
            by = mid_y + y_off
            arcade.draw_rect_filled(arcade.LBWH(abx, by, MENU_BTN_W, MENU_BTN_H), bg)
            arcade.draw_rect_outline(arcade.LBWH(abx, by, MENU_BTN_W, MENU_BTN_H), outline, border_width=1)
            self.ctx.t_back.text = label
            self.ctx.t_back.x = abx + MENU_BTN_W // 2; self.ctx.t_back.y = by + MENU_BTN_H // 2
            self.ctx.t_back.draw()

        draw_back_button(px, py, self.ctx.t_back)

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        mid_y = py + MENU_H // 2
        self.ctx.play_click()
        if back_button_hit(x, y, px, py):
            self.ctx.set_mode("main"); return
        # Arrows
        if px + 30 <= x <= px + 66 and mid_y - 18 <= y <= mid_y + 18:
            self.ctx.res_idx = (self.ctx.res_idx - 1) % len(RESOLUTION_PRESETS); return
        if px + MENU_W - 66 <= x <= px + MENU_W - 30 and mid_y - 18 <= y <= mid_y + 18:
            self.ctx.res_idx = (self.ctx.res_idx + 1) % len(RESOLUTION_PRESETS); return
        # Apply buttons
        abx = px + (MENU_W - MENU_BTN_W) // 2
        for mode_name, y_off in [("windowed", -50), ("fullscreen", -50 - MENU_BTN_H - 12),
                                  ("borderless", -50 - 2 * (MENU_BTN_H + 12))]:
            by = mid_y + y_off
            if abx <= x <= abx + MENU_BTN_W and by <= y <= by + MENU_BTN_H:
                w, h = RESOLUTION_PRESETS[self.ctx.res_idx]
                if self.ctx.resolution_fn: self.ctx.resolution_fn(w, h, mode_name)
                return

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("main")
