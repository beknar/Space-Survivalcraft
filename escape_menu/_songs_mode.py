"""Songs sub-mode for the escape menu."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_back_button, back_button_hit, point_in_rect


class SongsMode(MenuMode):

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._stop_rect: tuple = (0, 0, 0, 0)
        self._other_rect: tuple = (0, 0, 0, 0)
        self._video_rect: tuple = (0, 0, 0, 0)
        # Keyboard focus into the button list: 0=Stop, 1=Other,
        # 2=Music Videos, 3=Back.  -1 = nothing focused (mouse mode).
        self._focus_idx: int = -1
        # Pre-built section headers (avoids .bold toggle on shared text)
        self._t_ost = arcade.Text("OST Songs", 0, 0, arcade.color.LIGHT_BLUE, 10,
                                  bold=True, anchor_x="center")
        self._t_mv = arcade.Text("Music Videos", 0, 0, arcade.color.LIGHT_GREEN, 10,
                                 bold=True, anchor_x="center")

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
        tb = self.ctx.t_back

        # OST Songs section
        self._t_ost.x = cx; self._t_ost.y = cur_y; self._t_ost.draw()
        cur_y -= 40

        for i, (label, rect_attr, bg) in enumerate([
            ("Stop Song", "_stop_rect", (50, 40, 40, 220)),
            ("Other Song", "_other_rect", (30, 50, 40, 220)),
        ]):
            setattr(self, rect_attr, (abx, cur_y, MENU_BTN_W, MENU_BTN_H))
            focused = (self._focus_idx == i)
            arcade.draw_rect_filled(arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H), bg)
            arcade.draw_rect_outline(
                arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H),
                arcade.color.CYAN if focused else arcade.color.STEEL_BLUE,
                border_width=2 if focused else 1)
            tb.text = label; tb.x = abx + MENU_BTN_W // 2; tb.y = cur_y + MENU_BTN_H // 2
            tb.draw()
            cur_y -= MENU_BTN_H + 10

        cur_y -= 15
        # Music Videos section
        self._t_mv.x = cx; self._t_mv.y = cur_y; self._t_mv.draw()
        cur_y -= 40

        self._video_rect = (abx, cur_y, MENU_BTN_W, MENU_BTN_H)
        focused = (self._focus_idx == 2)
        arcade.draw_rect_filled(arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H),
                                (30, 40, 60, 220))
        arcade.draw_rect_outline(arcade.LBWH(abx, cur_y, MENU_BTN_W, MENU_BTN_H),
                                 arcade.color.CYAN,
                                 border_width=3 if focused else 1)
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
            self.ctx.set_mode("video")

    def _activate_focus(self) -> None:
        if self._focus_idx == 0 and self.ctx.stop_song_fn:
            self.ctx.stop_song_fn()
        elif self._focus_idx == 1 and self.ctx.other_song_fn:
            self.ctx.other_song_fn()
        elif self._focus_idx == 2:
            self.ctx.set_mode("video")
        elif self._focus_idx == 3:
            self.ctx.set_mode("main")

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("main")
            return
        n = 4   # stop / other / video / back
        cur = self._focus_idx
        if key in (arcade.key.TAB, arcade.key.DOWN, arcade.key.S):
            shift = bool(modifiers & arcade.key.MOD_SHIFT)
            step = -1 if (key == arcade.key.TAB and shift) else 1
            self._focus_idx = (
                (cur + step) % n if cur >= 0
                else (0 if step > 0 else n - 1))
            self.ctx.play_click()
            return
        if key in (arcade.key.UP, arcade.key.W):
            self._focus_idx = (cur - 1) % n if cur >= 0 else n - 1
            self.ctx.play_click()
            return
        if key in (arcade.key.RETURN, arcade.key.ENTER,
                   arcade.key.NUM_ENTER, arcade.key.SPACE):
            if cur < 0:
                self._focus_idx = 0; cur = 0
            self.ctx.play_click()
            self._activate_focus()
            return
