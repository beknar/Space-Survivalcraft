"""Video file picker sub-mode for the escape menu."""
from __future__ import annotations

import os

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H
from settings import audio
from video_player import scan_video_dir, _HAS_FFMPEG
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit


class VideoMode(MenuMode):

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._files: list[str] = []
        self._scroll: int = 0
        self._editing_dir: bool = False
        self._dir_text: str = audio.video_dir

    def on_enter(self) -> None:
        self._dir_text = audio.video_dir
        self._files = scan_video_dir(audio.video_dir)
        self._scroll = 0

    def draw(self) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
        draw_panel(px, py)

        self.ctx.t_title.text = "VIDEO"
        self.ctx.t_title.x = cx
        self.ctx.t_title.y = py + MENU_H - 30
        self.ctx.t_title.draw()

        t = self.ctx.t_text
        ti = self.ctx.t_info

        # Directory bar
        dir_y = py + MENU_H - 70
        dir_x, dir_w = px + 10, MENU_W - 20
        bg = (40, 40, 60, 220) if self._editing_dir else (30, 30, 50, 200)
        arcade.draw_rect_filled(arcade.LBWH(dir_x, dir_y, dir_w, 30), bg)
        outline = arcade.color.CYAN if self._editing_dir else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(arcade.LBWH(dir_x, dir_y, dir_w, 30), outline, border_width=1)
        dd = self._dir_text or "(click to set video folder)"
        if len(dd) > 30: dd = "..." + dd[-27:]
        t.text = dd; t.x = dir_x + 4; t.y = dir_y + 15
        t.color = arcade.color.WHITE if self._dir_text else (120, 120, 120)
        t.bold = False; t.draw()

        if not _HAS_FFMPEG:
            ti.text = "No video decoder available"; ti.x = cx; ti.y = py + MENU_H // 2
            ti.color = (200, 80, 80); ti.draw()
        else:
            list_y = dir_y - 40; item_h = 28; max_vis = 8
            if not self._files:
                ti.text = "No video files found"; ti.x = cx; ti.y = list_y
                ti.color = (160, 160, 160); ti.draw()
            else:
                for i in range(min(max_vis, len(self._files) - self._scroll)):
                    idx = self._scroll + i
                    fname = self._files[idx]; iy = list_y - i * item_h
                    sel = (fname == audio.video_file)
                    fill = (50, 70, 100, 220) if sel else (30, 30, 50, 180)
                    arcade.draw_rect_filled(arcade.LBWH(px + 10, iy, MENU_W - 20, item_h - 2), fill)
                    dn = fname if len(fname) <= 28 else fname[:25] + "..."
                    t.text = dn; t.x = px + 16; t.y = iy + item_h // 2
                    t.color = arcade.color.CYAN if sel else arcade.color.WHITE
                    t.bold = sel; t.draw()

        # Stop Video button
        stop_y = py + 50; abx = px + (MENU_W - MENU_BTN_W) // 2
        arcade.draw_rect_filled(arcade.LBWH(abx, stop_y, MENU_BTN_W, MENU_BTN_H), (60, 30, 30, 220))
        arcade.draw_rect_outline(arcade.LBWH(abx, stop_y, MENU_BTN_W, MENU_BTN_H), (180, 60, 60), border_width=1)
        self.ctx.t_back.text = "Stop Video"
        self.ctx.t_back.x = abx + MENU_BTN_W // 2; self.ctx.t_back.y = stop_y + MENU_BTN_H // 2
        self.ctx.t_back.draw()

        draw_back_button(px, py, self.ctx.t_back)

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        self.ctx.play_click()
        if back_button_hit(x, y, px, py):
            self._editing_dir = False; self.ctx.set_mode("songs"); return
        # Directory bar
        dir_y = py + MENU_H - 70
        if px + 10 <= x <= px + MENU_W - 10 and dir_y <= y <= dir_y + 30:
            self._editing_dir = True; self._dir_text = audio.video_dir; return
        # Stop Video
        stop_y = py + 50; abx = px + (MENU_W - MENU_BTN_W) // 2
        if abx <= x <= abx + MENU_BTN_W and stop_y <= y <= stop_y + MENU_BTN_H:
            if self.ctx.video_stop_fn and audio.video_file:
                self.ctx.video_stop_fn(); audio.video_file = ""
            return
        # File list
        list_y = dir_y - 40; item_h = 28; max_vis = 8
        for i in range(min(max_vis, len(self._files) - self._scroll)):
            idx = self._scroll + i; iy = list_y - i * item_h
            if px + 10 <= x <= px + MENU_W - 10 and iy <= y <= iy + item_h:
                fname = self._files[idx]; audio.video_file = fname
                if self.ctx.video_play_fn:
                    self.ctx.video_play_fn(os.path.join(audio.video_dir, fname))
                return

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self._editing_dir = False; self.ctx.set_mode("songs")
        elif self._editing_dir:
            if key == arcade.key.BACKSPACE:
                self._dir_text = self._dir_text[:-1]
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                audio.video_dir = self._dir_text
                self._editing_dir = False
                self._files = scan_video_dir(audio.video_dir)

    def on_text(self, text: str) -> None:
        if self._editing_dir:
            for ch in text:
                if ch.isprintable() and len(self._dir_text) < 200:
                    self._dir_text += ch

    def on_mouse_scroll(self, scroll_y: float) -> None:
        if self._files:
            mx = max(0, len(self._files) - 8)
            self._scroll = int(max(0, min(mx, self._scroll - scroll_y)))
