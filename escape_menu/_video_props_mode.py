"""Video Properties sub-mode (resolution + character picker)."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, RESOLUTION_PRESETS
from settings import audio, save_config
from video_player import scan_characters_dir
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit


class VideoPropsMode(MenuMode):

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._characters: list[str] = []
        self._scroll: int = 0

    def on_enter(self) -> None:
        self._characters = scan_characters_dir()
        self._scroll = 0

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

        # Character section
        bl_y = apply_y - 72
        char_y = bl_y - 30
        t.text = "Character"; t.x = cx; t.y = char_y; t.color = arcade.color.WHITE
        t.bold = True; t.anchor_x = "center"; t.draw(); t.anchor_x = "left"

        list_y = char_y - 18; item_h = 30; max_vis = 6
        if not self._characters:
            ti.text = "No characters in characters/"; ti.x = cx; ti.y = list_y - 20
            ti.color = (200, 80, 80); ti.draw()
        else:
            for i in range(min(max_vis, len(self._characters) - self._scroll)):
                idx = self._scroll + i; name = self._characters[idx]
                iy = list_y - i * item_h
                sel = (name == audio.character_name)
                fill = (50, 70, 100, 220) if sel else (30, 30, 50, 180)
                arcade.draw_rect_filled(arcade.LBWH(px + 10, iy, MENU_W - 20, item_h - 2), fill)
                t.text = name; t.x = px + 20; t.y = iy + item_h // 2
                t.color = arcade.color.CYAN if sel else arcade.color.WHITE
                t.bold = sel; t.draw()

        draw_back_button(px, py, self.ctx.t_back)

        if self.ctx.status_msg:
            self.ctx.t_status.x = cx; self.ctx.t_status.y = py + MENU_H + 20
            self.ctx.t_status.text = self.ctx.status_msg; self.ctx.t_status.draw()

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
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
        # Character list
        bl_y = apply_y - 72; list_y = bl_y - 30 - 18; item_h = 30; max_vis = 6
        for i in range(min(max_vis, len(self._characters) - self._scroll)):
            idx = self._scroll + i; iy = list_y - i * item_h
            if px + 10 <= x <= px + MENU_W - 10 and iy <= y <= iy + item_h:
                name = self._characters[idx]; audio.character_name = name; save_config()
                if self.ctx.character_select_fn: self.ctx.character_select_fn(name)
                self.ctx.flash_status(f"Character: {name}"); return

    def on_mouse_scroll(self, scroll_y: float) -> None:
        if self._characters:
            mx = max(0, len(self._characters) - 6)
            self._scroll = int(max(0, min(mx, self._scroll - scroll_y)))

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("main")
