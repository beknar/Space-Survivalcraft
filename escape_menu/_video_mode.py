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

    # Visible-list window size, kept here so keyboard scroll
    # logic and the draw loop agree without magic numbers.
    _MAX_VIS: int = 8

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._files: list[str] = []
        self._scroll: int = 0
        self._editing_dir: bool = False
        self._dir_text: str = audio.video_dir
        # Keyboard focus across the file list + Stop + Back.
        # 0..len(files)-1 = a file row; len(files) = Stop Video;
        # len(files)+1 = Back.  -1 = nothing focused (mouse mode).
        self._focus_idx: int = -1
        # Pre-built text objects (avoids per-frame font regen / bold toggling)
        self._t_dir = arcade.Text("", 0, 0, arcade.color.WHITE, 10)
        self._t_items: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.WHITE, 10)
            for _ in range(8)
        ]
        self._t_sel_items: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.CYAN, 10, bold=True)
            for _ in range(8)
        ]

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

        # Directory bar
        dir_y = py + MENU_H - 70
        dir_x, dir_w = px + 10, MENU_W - 20
        bg = (40, 40, 60, 220) if self._editing_dir else (30, 30, 50, 200)
        arcade.draw_rect_filled(arcade.LBWH(dir_x, dir_y, dir_w, 30), bg)
        outline = arcade.color.CYAN if self._editing_dir else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(arcade.LBWH(dir_x, dir_y, dir_w, 30), outline, border_width=1)
        dd = self._dir_text or "(click to set video folder)"
        if len(dd) > 30: dd = "..." + dd[-27:]
        td = self._t_dir
        td.text = dd; td.x = dir_x + 4; td.y = dir_y + 15
        td.color = arcade.color.WHITE if self._dir_text else (120, 120, 120)
        td.draw()

        if not _HAS_FFMPEG:
            ti = self.ctx.t_info
            ti.text = "No video decoder available"; ti.x = cx; ti.y = py + MENU_H // 2
            ti.color = (200, 80, 80); ti.draw()
        else:
            list_y = dir_y - 40; item_h = 28; max_vis = 8
            if not self._files:
                ti = self.ctx.t_info
                ti.text = "No video files found"; ti.x = cx; ti.y = list_y
                ti.color = (160, 160, 160); ti.draw()
            else:
                for i in range(min(max_vis, len(self._files) - self._scroll)):
                    idx = self._scroll + i
                    fname = self._files[idx]; iy = list_y - i * item_h
                    sel = (fname == audio.video_file)
                    focused = (self._focus_idx == idx)
                    fill = (50, 70, 100, 220) if sel else (30, 30, 50, 180)
                    arcade.draw_rect_filled(arcade.LBWH(px + 10, iy, MENU_W - 20, item_h - 2), fill)
                    if focused:
                        arcade.draw_rect_outline(
                            arcade.LBWH(px + 10, iy, MENU_W - 20, item_h - 2),
                            arcade.color.CYAN, border_width=2)
                    dn = fname if len(fname) <= 28 else fname[:25] + "..."
                    item = self._t_sel_items[i] if sel else self._t_items[i]
                    item.text = dn
                    item.x = px + 16; item.y = iy + item_h // 2
                    item.draw()

        # Stop Video button
        stop_y = py + 50; abx = px + (MENU_W - MENU_BTN_W) // 2
        from escape_menu._ui import draw_button
        n_files = len(self._files)
        stop_focused = (self._focus_idx == n_files)
        draw_button((abx, stop_y, MENU_BTN_W, MENU_BTN_H),
                    self.ctx.t_back, label="Stop Video",
                    fill=(60, 30, 30, 220),
                    outline=arcade.color.CYAN if stop_focused else (180, 60, 60))
        draw_back_button(px, py, self.ctx.t_back)
        # Highlight the back button if it's the keyboard focus.
        # Geometry mirrors escape_menu._ui.draw_back_button.
        if self._focus_idx == n_files + 1:
            bx = px + (MENU_W - MENU_BTN_W) // 2
            by = py + 12
            arcade.draw_rect_outline(
                arcade.LBWH(bx, by, MENU_BTN_W, 35),
                arcade.color.CYAN, border_width=2)

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

    def _commit_dir(self) -> None:
        audio.video_dir = self._dir_text.strip()
        self._files = scan_video_dir(audio.video_dir)
        self._scroll = 0

    def _focus_count(self) -> int:
        """Total focusable items: file rows + Stop + Back."""
        return len(self._files) + 2

    def _back_idx(self) -> int:
        return len(self._files) + 1

    def _stop_idx(self) -> int:
        return len(self._files)

    def _ensure_focus_visible(self) -> None:
        """Scroll the file list so the keyboard-focused row is on
        screen.  No-op if focus is on Stop / Back."""
        n = len(self._files)
        if not (0 <= self._focus_idx < n):
            return
        if self._focus_idx < self._scroll:
            self._scroll = self._focus_idx
        elif self._focus_idx >= self._scroll + self._MAX_VIS:
            self._scroll = self._focus_idx - self._MAX_VIS + 1
        # Clamp.
        max_scroll = max(0, n - self._MAX_VIS)
        self._scroll = max(0, min(max_scroll, self._scroll))

    def _activate_focus(self) -> None:
        cur = self._focus_idx
        if cur == self._back_idx():
            self._editing_dir = False
            self.ctx.set_mode("songs")
            return
        if cur == self._stop_idx():
            if self.ctx.video_stop_fn and audio.video_file:
                self.ctx.video_stop_fn()
                audio.video_file = ""
            return
        if 0 <= cur < len(self._files):
            fname = self._files[cur]
            audio.video_file = fname
            if self.ctx.video_play_fn:
                self.ctx.video_play_fn(
                    os.path.join(audio.video_dir, fname))

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        # Editing the directory text field absorbs all printable
        # input; only ESC + RETURN + BACKSPACE escape it.
        if self._editing_dir:
            if key == arcade.key.ESCAPE:
                self._editing_dir = False
                return
            if key == arcade.key.BACKSPACE:
                self._dir_text = self._dir_text[:-1]
                self._commit_dir()
                return
            if key in (arcade.key.RETURN, arcade.key.ENTER,
                       arcade.key.NUM_ENTER):
                self._commit_dir()
                self._editing_dir = False
                return
            return
        # ESC: leave the menu (preserved).
        if key == arcade.key.ESCAPE:
            self.ctx.set_mode("songs")
            return
        n = self._focus_count()
        if n == 0:
            return
        cur = self._focus_idx
        # Tab / Down / S: focus next (wraps).
        if key in (arcade.key.TAB, arcade.key.DOWN, arcade.key.S):
            shift = bool(modifiers & arcade.key.MOD_SHIFT)
            step = -1 if (key == arcade.key.TAB and shift) else 1
            self._focus_idx = (
                (cur + step) % n if cur >= 0
                else (0 if step > 0 else n - 1))
            self._ensure_focus_visible()
            self.ctx.play_click()
            return
        if key in (arcade.key.UP, arcade.key.W):
            self._focus_idx = (cur - 1) % n if cur >= 0 else n - 1
            self._ensure_focus_visible()
            self.ctx.play_click()
            return
        # Enter / Space / Numpad-Enter: activate focused.
        if key in (arcade.key.RETURN, arcade.key.ENTER,
                   arcade.key.NUM_ENTER, arcade.key.SPACE):
            if cur < 0:
                # Bare Enter on first open -> focus first file (or Stop
                # when no files exist) so a "blind tap" still does
                # something predictable.
                self._focus_idx = 0
                self._ensure_focus_visible()
                cur = 0
            self.ctx.play_click()
            self._activate_focus()
            return

    def on_text(self, text: str) -> None:
        if self._editing_dir:
            for ch in text:
                if ch.isprintable() and len(self._dir_text) < 200:
                    self._dir_text += ch
            self._commit_dir()

    def on_mouse_scroll(self, scroll_y: float) -> None:
        if self._files:
            mx = max(0, len(self._files) - 8)
            self._scroll = int(max(0, min(mx, self._scroll - scroll_y)))
