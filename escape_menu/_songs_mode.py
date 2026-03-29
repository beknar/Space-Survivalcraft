"""Songs sub-mode for the escape menu."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H
from settings import audio
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit, point_in_rect


class SongsMode(MenuMode):

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._stop_rect: tuple = (0, 0, 0, 0)
        self._other_rect: tuple = (0, 0, 0, 0)
        self._video_rect: tuple = (0, 0, 0, 0)

    def draw(self) -> None:
        px, py = self.ctx.recalc()
        cx = px + MENU_W // 2
        draw_panel(px, py)

        self.ctx.t_title.text = "SONGS"
        self.ctx.t_title.x = cx
        self.ctx.t_title.y = py + MENU_H - 30
        self.ctx.t_title.draw()

        abx = px + (MENU_W - MENU_BTN_W) // 2
        cur_y = py + MENU_H - 70
        t = self.ctx.t_text
        tb = self.ctx.t_back

        # OST Songs section
        t.bold = True; t.text = "OST Songs"; t.x = cx; t.y = cur_y
        t.color = arcade.color.LIGHT_BLUE; t.anchor_x = "center"
        t.draw(); t.anchor_x = "left"
        cur_y -= 40

        for label, rect_attr, bg in [
            ("Stop Song", "_stop_rect", (50, 40, 40, 220)),
            ("Other Song", "_other_rect", (30, 50, 40, 220)),
        ]:
            setattr(self, rect_attr, (abx, cur_y, MENU_BTN_W, MENU_BTN_H))
            arcade.draw_rect_filled(arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H), bg)
            arcade.draw_rect_outline(arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H),
                                     arcade.color.STEEL_BLUE, border_width=1)
            tb.text = label; tb.x = abx + MENU_BTN_W // 2; tb.y = cur_y + MENU_BTN_H // 2
            tb.draw()
            cur_y -= MENU_BTN_H + 10

        cur_y -= 15
        # Music Videos section
        t.bold = True; t.text = "Music Videos"; t.x = cx; t.y = cur_y
        t.color = arcade.color.LIGHT_GREEN; t.anchor_x = "center"
        t.draw(); t.anchor_x = "left"
        cur_y -= 40

        self._video_rect = (abx, cur_y, MENU_BTN_W, MENU_BTN_H)
        arcade.draw_rect_filled(arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H),
                                (30, 40, 60, 220))
        arcade.draw_rect_outline(arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H),
                                 arcade.color.CYAN, border_width=1)
        tb.text = "Music Videos"; tb.x = abx + MENU_BTN_W // 2
        tb.y = cur_y + MENU_BTN_H // 2; tb.draw()

        draw_back_button(px, py, self.ctx.t_back)

        if self.ctx.status_msg:
            self.ctx.t_status.x = cx
            self.ctx.t_status.y = py + MENU_H - 12
            self.ctx.t_status.text = self.ctx.status_msg
            self.ctx.t_status.draw()

    def on_mouse_press(self, x: int, y: int) -> None:
        px, py = self.ctx.recalc()
        self.ctx.play_click()
        if back_button_hit(x, y, px, py):
            self.ctx.set_mode("main"); return
        if point_in_rect(x, y, self._stop_rect):
            if self.ctx.stop_song_fn: self.ctx.stop_song_fn(); return
        if point_in_rect(x, y, self._other_rect):
            if self.ctx.other_song_fn: self.ctx.other_song_fn(); return
        if point_in_rect(x, y, self._video_rect):
            if not audio.fullscreen:
                self.ctx.flash_status("Fullscreen required for video"); return
            self.ctx.set_mode("video")

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("main")
