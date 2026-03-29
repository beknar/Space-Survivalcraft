"""Configuration sub-mode for the escape menu."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H
from settings import audio, save_config
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit


class ConfigMode(MenuMode):

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._editing_dir: bool = False
        self._dir_text: str = audio.video_dir
        self._slider_dragging: str = ""

    def draw(self) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
        draw_panel(px, py)

        self.ctx.t_title.text = "CONFIG"
        self.ctx.t_title.x = cx; self.ctx.t_title.y = py + MENU_H - 30
        self.ctx.t_title.draw()

        t = self.ctx.t_text; ti = self.ctx.t_info

        # Video directory
        dir_y = py + MENU_H - 70; dir_x = px + 10; dir_w = MENU_W - 20
        bg = (40, 40, 60, 220) if self._editing_dir else (30, 30, 50, 200)
        arcade.draw_rect_filled(arcade.LBWH(dir_x, dir_y, dir_w, 30), bg)
        outline = arcade.color.CYAN if self._editing_dir else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(arcade.LBWH(dir_x, dir_y, dir_w, 30), outline, border_width=1)
        dd = self._dir_text or "(video folder)"
        if len(dd) > 30: dd = "..." + dd[-27:]
        t.text = dd; t.x = dir_x + 4; t.y = dir_y + 15
        t.color = arcade.color.WHITE if self._dir_text else (120, 120, 120)
        t.bold = False; t.draw()

        # FPS toggle
        fps_y = py + MENU_H - 130; fps_x = px + MENU_W - 60
        t.text = "Show FPS"; t.x = px + 16; t.y = fps_y + 12
        t.color = arcade.color.WHITE; t.bold = True; t.draw()
        on = audio.show_fps
        arcade.draw_rect_filled(arcade.LBWH(fps_x, fps_y, 40, 24),
                                (30, 80, 30, 220) if on else (60, 30, 30, 220))
        ti.text = "ON" if on else "OFF"
        ti.x = fps_x + 20; ti.y = fps_y + 12
        ti.color = arcade.color.LIME_GREEN if on else (200, 60, 60)
        ti.draw()

        # Music slider
        slider_x = px + 60; slider_w = MENU_W - 80
        music_y = py + MENU_H - 180
        t.text = "Music"; t.x = px + 16; t.y = music_y + 12; t.bold = True
        t.color = arcade.color.WHITE; t.draw()
        self._draw_cfg_slider(slider_x, music_y, slider_w, audio.music_volume)

        # SFX slider
        sfx_y = py + MENU_H - 230
        t.text = "SFX"; t.x = px + 16; t.y = sfx_y + 12; t.draw()
        self._draw_cfg_slider(slider_x, sfx_y, slider_w, audio.sfx_volume)

        # Save button
        abx = px + (MENU_W - MENU_BTN_W) // 2; save_y = py + 50
        arcade.draw_rect_filled(arcade.LBWH(abx, save_y, MENU_BTN_W, MENU_BTN_H),
                                (30, 60, 30, 220))
        arcade.draw_rect_outline(arcade.LBWH(abx, save_y, MENU_BTN_W, MENU_BTN_H),
                                 arcade.color.LIME_GREEN, border_width=1)
        self.ctx.t_back.text = "Save Config"
        self.ctx.t_back.x = abx + MENU_BTN_W // 2; self.ctx.t_back.y = save_y + MENU_BTN_H // 2
        self.ctx.t_back.draw()

        draw_back_button(px, py, self.ctx.t_back)

    def _draw_cfg_slider(self, x: int, y: int, w: int, value: float) -> None:
        arcade.draw_rect_filled(arcade.LBWH(x, y, w, 8), (40, 40, 60, 255))
        fw = int(w * value)
        if fw > 0:
            arcade.draw_rect_filled(arcade.LBWH(x, y, fw, 8), (0, 160, 220, 255))
        arcade.draw_circle_filled(x + fw, y + 4, 7, arcade.color.CYAN)

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        self.ctx.play_click()
        if back_button_hit(x, y, px, py):
            self.ctx.set_mode("main"); return
        abx = px + (MENU_W - MENU_BTN_W) // 2
        # Save
        if abx <= x <= abx + MENU_BTN_W and py + 50 <= y <= py + 50 + MENU_BTN_H:
            audio.video_dir = self._dir_text; save_config()
            self.ctx.flash_status("Config saved!"); self.ctx.set_mode("main"); return
        # Dir bar
        dir_y = py + MENU_H - 70
        if px + 10 <= x <= px + MENU_W - 10 and dir_y <= y <= dir_y + 30:
            self._editing_dir = True; return
        # FPS toggle
        fps_y = py + MENU_H - 130; fps_x = px + MENU_W - 60
        if fps_x <= x <= fps_x + 40 and fps_y <= y <= fps_y + 24:
            audio.show_fps = not audio.show_fps; return
        # Sliders
        slider_x = px + 60; slider_w = MENU_W - 80
        for name, sy in [("music", py + MENU_H - 180), ("sfx", py + MENU_H - 230)]:
            if slider_x <= x <= slider_x + slider_w and sy - 10 <= y <= sy + 10:
                self._slider_dragging = name
                frac = max(0.0, min(1.0, (x - slider_x) / slider_w))
                if name == "music": audio.music_volume = frac
                else: audio.sfx_volume = frac
                return

    def on_mouse_motion(self, x: int, y: int) -> None:
        if self._slider_dragging:
            px, py = self.ctx.recalc()
            slider_x = px + 60; slider_w = MENU_W - 80
            frac = max(0.0, min(1.0, (x - slider_x) / slider_w))
            if self._slider_dragging == "music": audio.music_volume = frac
            else: audio.sfx_volume = frac

    def on_mouse_release(self, x: int, y: int) -> None:
        self._slider_dragging = ""

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self._editing_dir = False; self.ctx.set_mode("main")
        elif self._editing_dir:
            if key == arcade.key.BACKSPACE: self._dir_text = self._dir_text[:-1]
            elif key in (arcade.key.RETURN, arcade.key.ENTER): self._editing_dir = False

    def on_text(self, text: str) -> None:
        if self._editing_dir:
            for ch in text:
                if ch.isprintable() and len(self._dir_text) < 200:
                    self._dir_text += ch
