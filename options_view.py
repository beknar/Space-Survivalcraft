"""Options screen with audio volume sliders."""
from __future__ import annotations

import os

import arcade

import constants
from constants import SCREEN_WIDTH, SCREEN_HEIGHT, SFX_INTERFACE_DIR, RESOLUTION_PRESETS
from settings import audio, apply_resolution


# ── Slider layout constants ───────────────────────────────────────────────
_SLIDER_W = 300
_SLIDER_H = 8
_KNOB_R = 12

_BTN_W = 240
_BTN_H = 45


class OptionsView(arcade.View):
    """Settings screen with Music/SFX volume sliders and resolution selector."""

    def __init__(self) -> None:
        super().__init__()

        # Use actual window dimensions (correct in fullscreen)
        sw = arcade.get_window().width
        sh = arcade.get_window().height
        self._slider_x = (sw - _SLIDER_W) // 2
        self._music_y = sh // 2 + 120
        self._sfx_y = sh // 2 + 40

        self._dragging: str = ""  # "music", "sfx", or ""
        self._hover_back: bool = False
        self._hover_help: bool = False
        self._hover_exit: bool = False
        self._show_help: bool = False
        self._hover_res_left: bool = False
        self._hover_res_right: bool = False
        self._hover_fs: bool = False

        # Resolution preset index
        current_res = (audio.screen_width, audio.screen_height)
        self._res_idx = 0
        for i, preset in enumerate(RESOLUTION_PRESETS):
            if preset == current_res:
                self._res_idx = i
                break

        # ── Resolution selector rects ────────────────────────────────
        res_y = sh // 2 - 40
        self._res_left_rect = (sw // 2 - 150, res_y - 18, 36, 36)
        self._res_right_rect = (sw // 2 + 114, res_y - 18, 36, 36)
        self._res_y = res_y
        # Fullscreen toggle button
        fs_y = sh // 2 - 100
        self._fs_rect = (
            (sw - _BTN_W) // 2, fs_y - _BTN_H // 2,
            _BTN_W, _BTN_H,
        )

        # ── Main buttons ──────────────────────────────────────────────
        self._back_rect = (
            (sw - _BTN_W) // 2,
            sh // 2 - 180,
            _BTN_W,
            _BTN_H,
        )
        self._help_rect = (
            (sw - _BTN_W) // 2,
            sh // 2 - 180 - _BTN_H - 16,
            _BTN_W,
            _BTN_H,
        )
        self._config_rect = (
            (sw - _BTN_W) // 2,
            sh // 2 - 180 - (_BTN_H + 16) * 2,
            _BTN_W,
            _BTN_H,
        )
        self._exit_rect = (
            (sw - _BTN_W) // 2,
            sh // 2 - 180 - (_BTN_H + 16) * 3,
            _BTN_W,
            _BTN_H,
        )
        self._hover_config: bool = False
        self._config_flash: float = 0.0

        # ── UI sound ───────────────────────────────────────────────────
        self._click_snd = arcade.load_sound(
            os.path.join(SFX_INTERFACE_DIR,
                         "Sci-Fi Interface Simple Notification 2.wav")
        )

        # ── Pre-built text objects ─────────────────────────────────────
        self._t_title = arcade.Text(
            "OPTIONS",
            sw // 2, sh - 120,
            arcade.color.LIGHT_BLUE, 36, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_music_label = arcade.Text(
            "Music Volume", sw // 2, self._music_y + 30,
            arcade.color.WHITE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_music_val = arcade.Text(
            "", sw // 2, self._music_y - 22,
            (180, 180, 180), 11,
            anchor_x="center", anchor_y="center",
        )
        self._t_sfx_label = arcade.Text(
            "Sound Effects Volume", sw // 2, self._sfx_y + 30,
            arcade.color.WHITE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_sfx_val = arcade.Text(
            "", sw // 2, self._sfx_y - 22,
            (180, 180, 180), 11,
            anchor_x="center", anchor_y="center",
        )
        self._t_res_label = arcade.Text(
            "Resolution", sw // 2, self._res_y + 30,
            arcade.color.WHITE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_res_val = arcade.Text(
            "", sw // 2, self._res_y,
            arcade.color.YELLOW, 13, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_fs = arcade.Text(
            "", 0, 0,
            arcade.color.WHITE, 13, bold=True,
            anchor_x="center", anchor_y="center",
        )
        bx, by, bw, bh = self._back_rect
        self._t_back = arcade.Text(
            "Main Menu",
            bx + bw // 2, by + bh // 2,
            arcade.color.WHITE, 15, bold=True,
            anchor_x="center", anchor_y="center",
        )
        hx, hy, hw, hh = self._help_rect
        self._t_help = arcade.Text(
            "Help",
            hx + hw // 2, hy + hh // 2,
            arcade.color.WHITE, 15, bold=True,
            anchor_x="center", anchor_y="center",
        )
        cx2, cy2, cw2, ch2 = self._config_rect
        self._t_config = arcade.Text(
            "Config",
            cx2 + cw2 // 2, cy2 + ch2 // 2,
            arcade.color.WHITE, 15, bold=True,
            anchor_x="center", anchor_y="center",
        )
        ex, ey, ew, eh = self._exit_rect
        self._t_exit = arcade.Text(
            "Exit Game",
            ex + ew // 2, ey + eh // 2,
            arcade.color.WHITE, 15, bold=True,
            anchor_x="center", anchor_y="center",
        )
        # Help overlay text object (reusable)
        self._t_help_line = arcade.Text("", 0, 0, arcade.color.WHITE, 11)
        # Resolution arrow text objects
        lx, ly, lw, lh = self._res_left_rect
        self._t_arrow_left = arcade.Text(
            "<", lx + lw // 2, ly + lh // 2,
            (160, 160, 160), 20, bold=True,
            anchor_x="center", anchor_y="center",
        )
        rx, ry, rw, rh = self._res_right_rect
        self._t_arrow_right = arcade.Text(
            ">", rx + rw // 2, ry + rh // 2,
            (160, 160, 160), 20, bold=True,
            anchor_x="center", anchor_y="center",
        )

    # ── Drawing ────────────────────────────────────────────────────────

    def on_update(self, delta_time: float) -> None:
        if self._config_flash > 0:
            self._config_flash -= delta_time
            if self._config_flash <= 0:
                self._t_config.text = "Config"

    def on_draw(self) -> None:
        self.clear()

        # Dark background
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, self.window.width, self.window.height),
            (8, 8, 24),
        )

        self._t_title.draw()

        # Music slider
        self._t_music_label.draw()
        self._draw_slider(self._music_y, audio.music_volume)
        self._t_music_val.text = f"{int(audio.music_volume * 100)}%"
        self._t_music_val.draw()

        # SFX slider
        self._t_sfx_label.draw()
        self._draw_slider(self._sfx_y, audio.sfx_volume)
        self._t_sfx_val.text = f"{int(audio.sfx_volume * 100)}%"
        self._t_sfx_val.draw()

        # Resolution selector
        self._t_res_label.draw()
        w, h = RESOLUTION_PRESETS[self._res_idx]
        self._t_res_val.text = f"{w} x {h}"
        self._t_res_val.draw()
        # Left/right arrows
        self._t_arrow_left.color = arcade.color.CYAN if self._hover_res_left else (160, 160, 160)
        self._t_arrow_left.draw()
        self._t_arrow_right.color = arcade.color.CYAN if self._hover_res_right else (160, 160, 160)
        self._t_arrow_right.draw()

        # Fullscreen toggle
        fx, fy, fw, fh = self._fs_rect
        fs_bg = (50, 80, 140, 255) if self._hover_fs else (25, 35, 70, 230)
        arcade.draw_rect_filled(arcade.LBWH(fx, fy, fw, fh), fs_bg)
        fs_outline = arcade.color.CYAN if self._hover_fs else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(arcade.LBWH(fx, fy, fw, fh), fs_outline, border_width=2)
        fs_label = "Fullscreen: ON" if audio.fullscreen else "Fullscreen: OFF"
        self._t_fs.text = fs_label
        self._t_fs.x = fx + fw // 2
        self._t_fs.y = fy + fh // 2
        self._t_fs.color = arcade.color.CYAN if audio.fullscreen else arcade.color.WHITE
        self._t_fs.draw()

        # Main Menu button
        bx, by, bw, bh = self._back_rect
        bg = (50, 80, 140, 255) if self._hover_back else (25, 35, 70, 230)
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), bg)
        outline = arcade.color.CYAN if self._hover_back else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(
            arcade.LBWH(bx, by, bw, bh), outline, border_width=2,
        )
        self._t_back.color = (
            arcade.color.CYAN if self._hover_back else arcade.color.WHITE
        )
        self._t_back.draw()

        # Help button
        hx, hy, hw, hh = self._help_rect
        bg_h = (50, 80, 140, 255) if self._hover_help else (25, 35, 70, 230)
        arcade.draw_rect_filled(arcade.LBWH(hx, hy, hw, hh), bg_h)
        outline_h = arcade.color.CYAN if self._hover_help else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(
            arcade.LBWH(hx, hy, hw, hh), outline_h, border_width=2,
        )
        self._t_help.color = (
            arcade.color.CYAN if self._hover_help else arcade.color.WHITE
        )
        self._t_help.draw()

        # Config button
        cx2, cy2, cw2, ch2 = self._config_rect
        bg_c = (50, 80, 140, 255) if self._hover_config else (25, 35, 70, 230)
        arcade.draw_rect_filled(arcade.LBWH(cx2, cy2, cw2, ch2), bg_c)
        outline_c = arcade.color.CYAN if self._hover_config else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(
            arcade.LBWH(cx2, cy2, cw2, ch2), outline_c, border_width=2,
        )
        self._t_config.color = (
            arcade.color.CYAN if self._hover_config else arcade.color.WHITE
        )
        self._t_config.draw()

        # Exit Game button
        ex, ey, ew, eh = self._exit_rect
        bg_e = (50, 80, 140, 255) if self._hover_exit else (25, 35, 70, 230)
        arcade.draw_rect_filled(arcade.LBWH(ex, ey, ew, eh), bg_e)
        outline_e = arcade.color.CYAN if self._hover_exit else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(
            arcade.LBWH(ex, ey, ew, eh), outline_e, border_width=2,
        )
        self._t_exit.color = (
            arcade.color.CYAN if self._hover_exit else arcade.color.WHITE
        )
        self._t_exit.draw()

        # Help overlay
        if self._show_help:
            sw, sh = self.window.width, self.window.height
            panel_w, panel_h = 340, 380
            px = (sw - panel_w) // 2
            py = (sh - panel_h) // 2
            arcade.draw_rect_filled(
                arcade.LBWH(px, py, panel_w, panel_h), (15, 15, 40, 240),
            )
            arcade.draw_rect_outline(
                arcade.LBWH(px, py, panel_w, panel_h),
                arcade.color.STEEL_BLUE, border_width=2,
            )
            cx = px + panel_w // 2
            self._t_help_line.text = "CONTROLS"
            self._t_help_line.x = cx
            self._t_help_line.y = py + panel_h - 24
            self._t_help_line.color = arcade.color.LIGHT_BLUE
            self._t_help_line.bold = True
            self._t_help_line.font_size = 14
            self._t_help_line.anchor_x = "center"
            self._t_help_line.draw()
            self._t_help_line.font_size = 11
            self._t_help_line.anchor_x = "left"

            _HELP = [
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
                ("", ""),
                ("GAMEPAD", ""),
                ("Left stick", "Move / Rotate"),
                ("A button", "Fire"),
                ("RB", "Cycle weapon"),
                ("Y button", "Inventory"),
            ]
            line_y = py + panel_h - 52
            for key_text, action in _HELP:
                if key_text == "GAMEPAD":
                    self._t_help_line.text = "GAMEPAD"
                    self._t_help_line.x = cx
                    self._t_help_line.color = arcade.color.LIGHT_GREEN
                    self._t_help_line.bold = True
                    self._t_help_line.anchor_x = "center"
                    self._t_help_line.y = line_y
                    self._t_help_line.draw()
                    self._t_help_line.anchor_x = "left"
                    line_y -= 18
                    continue
                if not key_text:
                    line_y -= 8
                    continue
                self._t_help_line.text = key_text
                self._t_help_line.x = px + 20
                self._t_help_line.y = line_y
                self._t_help_line.color = (180, 180, 180)
                self._t_help_line.bold = False
                self._t_help_line.draw()
                self._t_help_line.text = action
                self._t_help_line.x = px + panel_w - 20
                self._t_help_line.anchor_x = "right"
                self._t_help_line.color = arcade.color.WHITE
                self._t_help_line.draw()
                self._t_help_line.anchor_x = "left"
                line_y -= 18

            # Close hint
            self._t_help_line.text = "Click anywhere to close"
            self._t_help_line.x = cx
            self._t_help_line.y = py + 12
            self._t_help_line.color = (120, 120, 120)
            self._t_help_line.anchor_x = "center"
            self._t_help_line.draw()
            self._t_help_line.anchor_x = "left"

    def _draw_slider(self, y: int, value: float) -> None:
        """Draw a horizontal slider track + knob at the given y position."""
        sx = self._slider_x
        # Track background
        arcade.draw_rect_filled(
            arcade.LBWH(sx, y - _SLIDER_H // 2, _SLIDER_W, _SLIDER_H),
            (50, 50, 70),
        )
        # Filled portion
        fill_w = int(_SLIDER_W * value)
        if fill_w > 0:
            arcade.draw_rect_filled(
                arcade.LBWH(sx, y - _SLIDER_H // 2, fill_w, _SLIDER_H),
                (60, 140, 220),
            )
        # Knob
        knob_x = sx + fill_w
        arcade.draw_circle_filled(knob_x, y, _KNOB_R, arcade.color.CYAN)
        arcade.draw_circle_outline(knob_x, y, _KNOB_R, arcade.color.WHITE, 2)

    # ── Input ──────────────────────────────────────────────────────────

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        if self._dragging:
            self._apply_drag(x)
            return
        bx, by, bw, bh = self._back_rect
        self._hover_back = (bx <= x <= bx + bw and by <= y <= by + bh)
        hx, hy, hw, hh = self._help_rect
        self._hover_help = (hx <= x <= hx + hw and hy <= y <= hy + hh)
        cx2, cy2, cw2, ch2 = self._config_rect
        self._hover_config = (cx2 <= x <= cx2 + cw2 and cy2 <= y <= cy2 + ch2)
        ex, ey, ew, eh = self._exit_rect
        self._hover_exit = (ex <= x <= ex + ew and ey <= y <= ey + eh)
        lx, ly, lw, lh = self._res_left_rect
        self._hover_res_left = (lx <= x <= lx + lw and ly <= y <= ly + lh)
        rx, ry, rw, rh = self._res_right_rect
        self._hover_res_right = (rx <= x <= rx + rw and ry <= y <= ry + rh)
        fx, fy, fw, fh = self._fs_rect
        self._hover_fs = (fx <= x <= fx + fw and fy <= y <= fy + fh)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        # Check if clicking on a slider knob or track
        if self._hit_slider(x, y, self._music_y):
            self._dragging = "music"
            self._apply_drag(x)
            return
        if self._hit_slider(x, y, self._sfx_y):
            self._dragging = "sfx"
            self._apply_drag(x)
            return

        # Resolution left/right arrows
        lx, ly, lw, lh = self._res_left_rect
        if lx <= x <= lx + lw and ly <= y <= ly + lh:
            self._res_idx = (self._res_idx - 1) % len(RESOLUTION_PRESETS)
            self._apply_resolution_change()
            return
        rx, ry, rw, rh = self._res_right_rect
        if rx <= x <= rx + rw and ry <= y <= ry + rh:
            self._res_idx = (self._res_idx + 1) % len(RESOLUTION_PRESETS)
            self._apply_resolution_change()
            return

        # Fullscreen toggle
        fx, fy, fw, fh = self._fs_rect
        if fx <= x <= fx + fw and fy <= y <= fy + fh:
            from settings import DISPLAY_WINDOWED, DISPLAY_FULLSCREEN
            if audio.display_mode == DISPLAY_WINDOWED:
                audio.display_mode = DISPLAY_FULLSCREEN
            else:
                audio.display_mode = DISPLAY_WINDOWED
            audio.fullscreen = audio.display_mode != DISPLAY_WINDOWED
            w, h = RESOLUTION_PRESETS[self._res_idx]
            apply_resolution(self.window, w, h, display_mode=audio.display_mode)
            self.window.show_view(OptionsView())
            return

        # Help button / close help overlay
        if self._show_help:
            self._show_help = False
            return
        hx, hy, hw, hh = self._help_rect
        if hx <= x <= hx + hw and hy <= y <= hy + hh:
            self._show_help = True
            return

        # Back button
        bx, by, bw, bh = self._back_rect
        if bx <= x <= bx + bw and by <= y <= by + bh:
            arcade.play_sound(self._click_snd, volume=audio.sfx_volume)
            from splash_view import SplashView
            self.window.show_view(SplashView())
            return

        # Config button — save current audio/video settings to config.json
        cx2, cy2, cw2, ch2 = self._config_rect
        if cx2 <= x <= cx2 + cw2 and cy2 <= y <= cy2 + ch2:
            from settings import save_config
            save_config()
            arcade.play_sound(self._click_snd, volume=audio.sfx_volume)
            self._t_config.text = "Saved!"
            self._config_flash = 1.5  # seconds to show confirmation
            return

        # Exit Game button
        ex, ey, ew, eh = self._exit_rect
        if ex <= x <= ex + ew and ey <= y <= ey + eh:
            arcade.exit()

    def _apply_resolution_change(self) -> None:
        """Apply the currently selected resolution preset and rebuild view."""
        w, h = RESOLUTION_PRESETS[self._res_idx]
        apply_resolution(self.window, w, h, display_mode=audio.display_mode)
        self.window.show_view(OptionsView())

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
        self._dragging = ""

    def on_key_press(self, key: int, modifiers: int) -> None:
        if key == arcade.key.ESCAPE:
            from splash_view import SplashView
            self.window.show_view(SplashView())

    def _hit_slider(self, x: int, y: int, slider_y: int) -> bool:
        """Check if (x, y) is within the interactive area of a slider."""
        sx = self._slider_x
        return (sx - _KNOB_R <= x <= sx + _SLIDER_W + _KNOB_R
                and slider_y - _KNOB_R - 4 <= y <= slider_y + _KNOB_R + 4)

    def _apply_drag(self, x: int) -> None:
        """Map cursor x position to a 0.0–1.0 volume value."""
        value = max(0.0, min(1.0, (x - self._slider_x) / _SLIDER_W))
        if self._dragging == "music":
            audio.music_volume = value
        elif self._dragging == "sfx":
            audio.sfx_volume = value
