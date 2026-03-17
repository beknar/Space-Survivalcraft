"""Options screen with audio volume sliders."""
from __future__ import annotations

import os

import arcade

from constants import SCREEN_WIDTH, SCREEN_HEIGHT, SFX_INTERFACE_DIR
from settings import audio


# ── Slider layout constants ───────────────────────────────────────────────
_SLIDER_W = 300
_SLIDER_H = 8
_KNOB_R = 12
_SLIDER_X = (SCREEN_WIDTH - _SLIDER_W) // 2
_MUSIC_Y = SCREEN_HEIGHT // 2 + 60
_SFX_Y = SCREEN_HEIGHT // 2 - 20

_BTN_W = 240
_BTN_H = 45


class OptionsView(arcade.View):
    """Settings screen with Music and SFX volume sliders."""

    def __init__(self) -> None:
        super().__init__()

        self._dragging: str = ""  # "music", "sfx", or ""
        self._hover_back: bool = False

        # ── Button rect (Main Menu) ────────────────────────────────────
        self._back_rect = (
            (SCREEN_WIDTH - _BTN_W) // 2,
            SCREEN_HEIGHT // 2 - 140,
            _BTN_W,
            _BTN_H,
        )

        # ── UI sound ───────────────────────────────────────────────────
        self._click_snd = arcade.load_sound(
            os.path.join(SFX_INTERFACE_DIR,
                         "Sci-Fi Interface Simple Notification 2.wav")
        )

        # ── Pre-built text objects ─────────────────────────────────────
        self._t_title = arcade.Text(
            "OPTIONS",
            SCREEN_WIDTH // 2, SCREEN_HEIGHT - 120,
            arcade.color.LIGHT_BLUE, 36, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_music_label = arcade.Text(
            "Music Volume", SCREEN_WIDTH // 2, _MUSIC_Y + 30,
            arcade.color.WHITE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_music_val = arcade.Text(
            "", SCREEN_WIDTH // 2, _MUSIC_Y - 22,
            (180, 180, 180), 11,
            anchor_x="center", anchor_y="center",
        )
        self._t_sfx_label = arcade.Text(
            "Sound Effects Volume", SCREEN_WIDTH // 2, _SFX_Y + 30,
            arcade.color.WHITE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_sfx_val = arcade.Text(
            "", SCREEN_WIDTH // 2, _SFX_Y - 22,
            (180, 180, 180), 11,
            anchor_x="center", anchor_y="center",
        )
        bx, by, bw, bh = self._back_rect
        self._t_back = arcade.Text(
            "Main Menu",
            bx + bw // 2, by + bh // 2,
            arcade.color.WHITE, 15, bold=True,
            anchor_x="center", anchor_y="center",
        )

    # ── Drawing ────────────────────────────────────────────────────────

    def on_draw(self) -> None:
        self.clear()

        # Dark background
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT),
            (8, 8, 24),
        )

        self._t_title.draw()

        # Music slider
        self._t_music_label.draw()
        self._draw_slider(_MUSIC_Y, audio.music_volume)
        self._t_music_val.text = f"{int(audio.music_volume * 100)}%"
        self._t_music_val.draw()

        # SFX slider
        self._t_sfx_label.draw()
        self._draw_slider(_SFX_Y, audio.sfx_volume)
        self._t_sfx_val.text = f"{int(audio.sfx_volume * 100)}%"
        self._t_sfx_val.draw()

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

    def _draw_slider(self, y: int, value: float) -> None:
        """Draw a horizontal slider track + knob at the given y position."""
        # Track background
        arcade.draw_rect_filled(
            arcade.LBWH(_SLIDER_X, y - _SLIDER_H // 2, _SLIDER_W, _SLIDER_H),
            (50, 50, 70),
        )
        # Filled portion
        fill_w = int(_SLIDER_W * value)
        if fill_w > 0:
            arcade.draw_rect_filled(
                arcade.LBWH(_SLIDER_X, y - _SLIDER_H // 2, fill_w, _SLIDER_H),
                (60, 140, 220),
            )
        # Knob
        knob_x = _SLIDER_X + fill_w
        arcade.draw_circle_filled(knob_x, y, _KNOB_R, arcade.color.CYAN)
        arcade.draw_circle_outline(knob_x, y, _KNOB_R, arcade.color.WHITE, 2)

    # ── Input ──────────────────────────────────────────────────────────

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        if self._dragging:
            self._apply_drag(x)
            return
        bx, by, bw, bh = self._back_rect
        self._hover_back = (bx <= x <= bx + bw and by <= y <= by + bh)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        # Check if clicking on a slider knob or track
        if self._hit_slider(x, y, _MUSIC_Y):
            self._dragging = "music"
            self._apply_drag(x)
            return
        if self._hit_slider(x, y, _SFX_Y):
            self._dragging = "sfx"
            self._apply_drag(x)
            return

        # Back button
        bx, by, bw, bh = self._back_rect
        if bx <= x <= bx + bw and by <= y <= by + bh:
            arcade.play_sound(self._click_snd, volume=audio.sfx_volume)
            from splash_view import SplashView
            self.window.show_view(SplashView())

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
        self._dragging = ""

    def on_key_press(self, key: int, modifiers: int) -> None:
        if key == arcade.key.ESCAPE:
            from splash_view import SplashView
            self.window.show_view(SplashView())

    def _hit_slider(self, x: int, y: int, slider_y: int) -> bool:
        """Check if (x, y) is within the interactive area of a slider."""
        return (_SLIDER_X - _KNOB_R <= x <= _SLIDER_X + _SLIDER_W + _KNOB_R
                and slider_y - _KNOB_R - 4 <= y <= slider_y + _KNOB_R + 4)

    def _apply_drag(self, x: int) -> None:
        """Map cursor x position to a 0.0–1.0 volume value."""
        value = max(0.0, min(1.0, (x - _SLIDER_X) / _SLIDER_W))
        if self._dragging == "music":
            audio.music_volume = value
        elif self._dragging == "sfx":
            audio.sfx_volume = value
