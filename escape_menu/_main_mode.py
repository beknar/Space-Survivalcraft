"""Main menu mode for the escape menu."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H, MENU_BTN_GAP
from settings import audio
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import draw_panel, draw_slider, btn_at

_BUTTONS: list[tuple[str, str]] = [
    ("resume",       "Resume"),
    ("save",         "Save Game"),
    ("load",         "Load Game"),
    ("video_props",  "Video Properties"),
    ("help",         "Help"),
    ("songs",        "Songs"),
    ("main_menu",    "Main Menu"),
]


class MainMode(MenuMode):

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._btn_rects: list[tuple[int, int, int, int]] = [(0, 0, 0, 0)] * len(_BUTTONS)
        self._t_title = arcade.Text("MENU", 0, 0, arcade.color.LIGHT_BLUE, 22,
                                    bold=True, anchor_x="center", anchor_y="center")
        self._t_labels = [arcade.Text(label, 0, 0, arcade.color.WHITE, 13,
                                      bold=True, anchor_x="center", anchor_y="center")
                          for _, label in _BUTTONS]
        self._t_music_label = arcade.Text("Music", 0, 0, arcade.color.WHITE, 10, bold=True)
        self._t_music_pct = arcade.Text("", 0, 0, arcade.color.CYAN, 10, anchor_x="right")
        self._t_sfx_label = arcade.Text("SFX", 0, 0, arcade.color.WHITE, 10, bold=True)
        self._t_sfx_pct = arcade.Text("", 0, 0, arcade.color.CYAN, 10, anchor_x="right")
        self._slider_music: tuple = (0, 0, 0, 0)
        self._slider_sfx: tuple = (0, 0, 0, 0)
        self._dragging: str = ""

    def _recalc(self) -> tuple[int, int]:
        px, py = self.ctx.recalc()
        bx = px + (MENU_W - MENU_BTN_W) // 2
        first_by = py + MENU_H - 200 - MENU_BTN_H
        for i in range(len(_BUTTONS)):
            by = first_by - i * (MENU_BTN_H + MENU_BTN_GAP)
            self._btn_rects[i] = (bx, by, MENU_BTN_W, MENU_BTN_H)
            self._t_labels[i].x = bx + MENU_BTN_W // 2
            self._t_labels[i].y = by + MENU_BTN_H // 2
        sw = 220
        sx = px + (MENU_W - sw) // 2
        my = py + MENU_H - 80; sy = my - 50
        self._slider_music = (sx, my, sw, 8)
        self._slider_sfx = (sx, sy, sw, 8)
        self._t_music_label.x = sx; self._t_music_label.y = my + 16
        self._t_music_pct.x = sx + sw; self._t_music_pct.y = my + 16
        self._t_sfx_label.x = sx; self._t_sfx_label.y = sy + 16
        self._t_sfx_pct.x = sx + sw; self._t_sfx_pct.y = sy + 16
        return px, py

    def draw(self) -> None:
        px, py = self._recalc()
        draw_panel(px, py)
        self._t_title.x = px + MENU_W // 2; self._t_title.y = py + MENU_H - 30
        self._t_title.draw()
        draw_slider(self._slider_music, audio.music_volume, self._t_music_label, self._t_music_pct)
        draw_slider(self._slider_sfx, audio.sfx_volume, self._t_sfx_label, self._t_sfx_pct)
        for i in range(len(_BUTTONS)):
            bx, by, bw, bh = self._btn_rects[i]
            hovered = (i == self.ctx.hover_idx)
            bg = (50, 80, 140, 255) if hovered else (30, 40, 80, 255)
            arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), bg)
            arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh),
                                     arcade.color.CYAN if hovered else arcade.color.STEEL_BLUE, border_width=2)
            self._t_labels[i].color = arcade.color.CYAN if hovered else arcade.color.WHITE
            self._t_labels[i].draw()
        if self.ctx.status_msg:
            self.ctx.t_status.x = self.ctx.window.width // 2
            self.ctx.t_status.y = py + 14
            self.ctx.t_status.text = self.ctx.status_msg
            self.ctx.t_status.draw()

    def on_mouse_motion(self, x: int, y: int) -> None:
        if self._dragging:
            self._apply_drag(x); return
        self.ctx.hover_idx = btn_at(x, y, self._btn_rects)

    def on_mouse_press(self, x: int, y: int) -> None:
        # Slider hit
        slider = self._slider_hit(x, y)
        if slider:
            self._dragging = slider; self._apply_drag(x); return
        self.ctx.play_click()
        idx = btn_at(x, y, self._btn_rects)
        if idx < 0: return
        self._activate(idx)

    def _activate(self, idx: int) -> None:
        """Run the action bound to button ``idx``.  Shared between
        on_mouse_press and on_key_press so keyboard activation
        (Enter / Space) and mouse click reach the same code path."""
        if idx < 0 or idx >= len(_BUTTONS):
            return
        key = _BUTTONS[idx][0]
        actions = {
            "resume": lambda: self.ctx.close_menu(),
            "save": lambda: self.ctx.set_mode("save"),
            "load": lambda: self.ctx.set_mode("load"),
            "video_props": lambda: self.ctx.set_mode("video_props"),
            "help": lambda: self.ctx.set_mode("help"),
            "songs": lambda: self.ctx.set_mode("songs"),
            "main_menu": lambda: (self.ctx.close_menu(), self.ctx.main_menu_fn()),
        }
        if key in actions:
            actions[key]()

    def on_mouse_release(self, x: int, y: int) -> None:
        self._dragging = ""

    def _slider_hit(self, x: int, y: int) -> str:
        for name, rect in [("music", self._slider_music), ("sfx", self._slider_sfx)]:
            sx, sy, sw, sh = rect
            if sx - 10 <= x <= sx + sw + 10 and sy - 10 <= y <= sy + sh + 18:
                return name
        return ""

    def _apply_drag(self, x: int) -> None:
        rect = self._slider_music if self._dragging == "music" else self._slider_sfx
        sx, _, sw, _ = rect
        frac = max(0.0, min(1.0, (x - sx) / sw))
        if self._dragging == "music": audio.music_volume = frac
        else: audio.sfx_volume = frac

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        # ESC: close the menu (preserved).
        if key == arcade.key.ESCAPE:
            self.ctx.close_menu()
            return
        # Tab / Down / S: focus next button (wraps).
        # Shift+Tab / Up / W: focus previous (wraps).
        n = len(_BUTTONS)
        if n == 0:
            return
        cur = self.ctx.hover_idx
        if key in (arcade.key.TAB, arcade.key.DOWN, arcade.key.S):
            shift = bool(modifiers & arcade.key.MOD_SHIFT)
            step = -1 if (key == arcade.key.TAB and shift) else 1
            self.ctx.hover_idx = (
                (cur + step) % n if cur >= 0
                else (0 if step > 0 else n - 1)
            )
            self.ctx.play_click()
            return
        if key in (arcade.key.UP, arcade.key.W):
            self.ctx.hover_idx = (
                (cur - 1) % n if cur >= 0 else n - 1
            )
            self.ctx.play_click()
            return
        # Enter / Space / NUMPAD_ENTER: activate the focused button.
        if key in (arcade.key.RETURN, arcade.key.ENTER,
                   arcade.key.NUM_ENTER, arcade.key.SPACE):
            if cur < 0:
                # Nothing focused yet — adopt the first button so a
                # blind Enter still does something predictable
                # (Resume is index 0).
                self.ctx.hover_idx = 0
                cur = 0
            self.ctx.play_click()
            self._activate(cur)
            return
