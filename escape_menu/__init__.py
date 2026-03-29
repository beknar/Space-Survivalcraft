"""Escape menu package for Space Survivalcraft.

Provides ``EscapeMenu`` — a thin orchestrator that delegates to per-mode
classes for drawing, input, and state management.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

import arcade

from constants import (
    MENU_W, MENU_H,
    SFX_VEHICLES_DIR,
    RESOLUTION_PRESETS,
)
from settings import audio
from escape_menu._context import MenuContext
from escape_menu._main_mode import MainMode
from escape_menu._save_load_mode import SaveLoadMode
from escape_menu._resolution_mode import ResolutionMode
from escape_menu._video_mode import VideoMode
from escape_menu._config_mode import ConfigMode
from escape_menu._help_mode import HelpMode
from escape_menu._songs_mode import SongsMode
from escape_menu._video_props_mode import VideoPropsMode


class EscapeMenu:
    """Modal overlay with sub-modes for save/load, settings, and more."""

    def __init__(
        self,
        save_fn: Callable[[int, str], None],
        load_fn: Callable[[int], None],
        main_menu_fn: Callable[[], None],
        save_dir: str,
        resolution_fn: Callable[[int, int, str], None] | None = None,
        video_play_fn: Callable[[str], None] | None = None,
        video_stop_fn: Callable[[], None] | None = None,
        stop_song_fn: Callable[[], None] | None = None,
        other_song_fn: Callable[[], None] | None = None,
        character_select_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.open: bool = False

        # Build shared context
        window = arcade.get_window()
        ctx = MenuContext(window)
        ctx.click_snd = arcade.load_sound(
            os.path.join(SFX_VEHICLES_DIR,
                         "Sci-Fi Spaceship Interface Mechanical Switch 1.wav"))
        ctx.save_fn = save_fn
        ctx.load_fn = load_fn
        ctx.main_menu_fn = main_menu_fn
        ctx.save_dir = save_dir
        ctx.resolution_fn = resolution_fn
        ctx.video_play_fn = video_play_fn
        ctx.video_stop_fn = video_stop_fn
        ctx.stop_song_fn = stop_song_fn
        ctx.other_song_fn = other_song_fn
        ctx.character_select_fn = character_select_fn
        ctx.set_mode = self._set_mode
        ctx.close_menu = self._close
        # Sync resolution index
        current_res = (audio.screen_width, audio.screen_height)
        for i, preset in enumerate(RESOLUTION_PRESETS):
            if preset == current_res:
                ctx.res_idx = i
                break
        self._ctx = ctx

        # Create mode instances
        self._save_load = SaveLoadMode(ctx)
        self._modes: dict[str, object] = {
            "main": MainMode(ctx),
            "save": self._save_load,
            "load": self._save_load,
            "resolution": ResolutionMode(ctx),
            "video": VideoMode(ctx),
            "config": ConfigMode(ctx),
            "help": HelpMode(ctx),
            "songs": SongsMode(ctx),
            "video_props": VideoPropsMode(ctx),
        }
        self._active_name: str = "main"

    @property
    def _active(self):
        return self._modes[self._active_name]

    def _set_mode(self, name: str) -> None:
        self._ctx.hover_idx = -1
        self._active_name = name
        if name == "save":
            self._save_load.open_save()
        elif name == "load":
            self._save_load.open_load()
        mode = self._modes.get(name)
        if mode and hasattr(mode, 'on_enter'):
            mode.on_enter()

    # Attribute accessed by game_view for video error display
    _last_video_error: str = ""

    def _flash_status(self, msg: str) -> None:
        """Public flash status (used by game_view for load errors)."""
        self._ctx.flash_status(msg)

    def _close(self) -> None:
        self.open = False

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self._set_mode("main")

    def update(self, dt: float) -> None:
        if self._ctx.status_timer > 0.0:
            self._ctx.status_timer = max(0.0, self._ctx.status_timer - dt)
            if self._ctx.status_timer <= 0.0:
                self._ctx.status_msg = ""
        self._active.update(dt)

    def draw(self) -> None:
        if not self.open:
            return
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, self._ctx.window.width, self._ctx.window.height),
            (0, 0, 0, 160),
        )
        self._active.draw()

    def on_mouse_motion(self, x: int, y: int) -> None:
        if self.open:
            self._active.on_mouse_motion(x, y)

    def on_mouse_press(self, x: int, y: int) -> None:
        if self.open:
            self._active.on_mouse_press(x, y)

    def on_mouse_release(self, x: int, y: int) -> None:
        if self.open:
            self._active.on_mouse_release(x, y)

    def on_mouse_scroll(self, scroll_y: float) -> None:
        if self.open:
            self._active.on_mouse_scroll(scroll_y)

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if self.open:
            self._active.on_key_press(key, modifiers)

    def on_text(self, text: str) -> None:
        if self.open:
            self._active.on_text(text)
