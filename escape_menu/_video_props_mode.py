"""Video Properties sub-mode (resolution settings only)."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, RESOLUTION_PRESETS
from escape_menu._context import MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit


class VideoPropsMode(MenuMode):

    def draw(self) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
        draw_panel(px, py)

        self.ctx.t_title.text = "VIDEO PROPERTIES"
        self.ctx.t_title.x = cx; self.ctx.t_title.y = py + MENU_H - 30
        self.ctx.t_title.draw()

        ti = self.ctx.t_info; t = self.ctx.t_text

        # Resolution section
        res_y = py + MENU_H - 60
        ti.text = "Resolution"; ti.x = cx; ti.y = res_y; ti.color = arcade.color.WHITE; ti.draw()
        val_y = res_y - 30
        w, h = RESOLUTION_PRESETS[self.ctx.res_idx]
        ti.text = f"{w} x {h}"; ti.y = val_y; ti.color = arcade.color.YELLOW; ti.draw()
        # Arrows
        t.bold = True; t.color = (180, 180, 180)
        t.text = "<"; t.x = px + 30; t.y = val_y; t.anchor_x = "center"; t.draw()
        t.text = ">"; t.x = px + MENU_W - 30; t.draw(); t.anchor_x = "left"

        abx = px + (MENU_W - MENU_BTN_W) // 2
        apply_y = val_y - 44
        for label, y_off, bg, outline in [
            ("Apply Windowed", 0, (30, 60, 30, 220), arcade.color.LIME_GREEN),
            ("Apply Fullscreen", -36, (30, 30, 60, 220), arcade.color.CYAN),
            ("Borderless Windowed", -72, (40, 30, 60, 220), (120, 100, 200)),
        ]:
            by = apply_y + y_off
            arcade.draw_rect_filled(arcade.LBWH(abx, by, MENU_BTN_W, 30), bg)
            arcade.draw_rect_outline(arcade.LBWH(abx, by, MENU_BTN_W, 30), outline, border_width=1)
            self.ctx.t_back.text = label
            self.ctx.t_back.x = abx + MENU_BTN_W // 2; self.ctx.t_back.y = by + 15
            self.ctx.t_back.draw()

        draw_back_button(px, py, self.ctx.t_back)

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        self.ctx.play_click()
        if back_button_hit(x, y, px, py):
            self.ctx.set_mode("main"); return
        res_y = py + MENU_H - 60; val_y = res_y - 30
        # Arrows
        if px + 12 <= x <= px + 48 and val_y - 14 <= y <= val_y + 14:
            self.ctx.res_idx = (self.ctx.res_idx - 1) % len(RESOLUTION_PRESETS); return
        if px + MENU_W - 48 <= x <= px + MENU_W - 12 and val_y - 14 <= y <= val_y + 14:
            self.ctx.res_idx = (self.ctx.res_idx + 1) % len(RESOLUTION_PRESETS); return
        # Apply buttons
        abx = px + (MENU_W - MENU_BTN_W) // 2; apply_y = val_y - 44
        for mode, y_off in [("windowed", 0), ("fullscreen", -36), ("borderless", -72)]:
            by = apply_y + y_off
            if abx <= x <= abx + MENU_BTN_W and by <= y <= by + 30:
                w, h = RESOLUTION_PRESETS[self.ctx.res_idx]
                if self.ctx.resolution_fn: self.ctx.resolution_fn(w, h, mode)
                return

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("main")
