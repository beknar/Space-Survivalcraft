"""Shared context and base class for escape menu sub-modes."""
from __future__ import annotations

from typing import Callable, Optional

import arcade


class MenuContext:
    """Shared state passed to every menu mode."""

    def __init__(self, window: arcade.Window) -> None:
        self.window = window
        self.click_snd: Optional[arcade.Sound] = None
        self.hover_idx: int = -1
        self.status_msg: str = ""
        self.status_timer: float = 0.0

        # Shared reusable text objects (modes reset properties before use)
        self.t_title = arcade.Text("", 0, 0, arcade.color.LIGHT_BLUE, 14,
                                   bold=True, anchor_x="center", anchor_y="center")
        self.t_text = arcade.Text("", 0, 0, arcade.color.WHITE, 10)
        self.t_info = arcade.Text("", 0, 0, (160, 160, 160), 9,
                                  anchor_x="center", anchor_y="center")
        self.t_back = arcade.Text("Back", 0, 0, arcade.color.WHITE, 12,
                                  bold=True, anchor_x="center", anchor_y="center")
        self.t_status = arcade.Text("", 0, 0, arcade.color.YELLOW_GREEN, 11,
                                    bold=True, anchor_x="center", anchor_y="center")

        # Resolution index shared between resolution and video_props modes
        self.res_idx: int = 0

        # Callbacks (set by EscapeMenu orchestrator)
        self.set_mode: Callable[[str], None] = lambda m: None
        self.close_menu: Callable[[], None] = lambda: None
        self.save_fn: Callable[[int, str], None] = lambda i, n: None
        self.load_fn: Callable[[int], None] = lambda i: None
        self.main_menu_fn: Callable[[], None] = lambda: None
        self.resolution_fn: Optional[Callable[[int, int, str], None]] = None
        self.video_play_fn: Optional[Callable[[str], None]] = None
        self.video_stop_fn: Optional[Callable[[], None]] = None
        self.stop_song_fn: Optional[Callable[[], None]] = None
        self.other_song_fn: Optional[Callable[[], None]] = None
        self.character_select_fn: Optional[Callable[[str], None]] = None
        self.save_dir: str = ""

    def recalc(self) -> tuple[int, int]:
        """Recompute main panel position; return (px, py)."""
        from constants import MENU_W, MENU_H
        px = (self.window.width - MENU_W) // 2
        py = (self.window.height - MENU_H) // 2
        return px, py

    def flash_status(self, msg: str) -> None:
        self.status_msg = msg
        self.status_timer = 2.0

    def play_click(self) -> None:
        if self.click_snd:
            from settings import audio
            arcade.play_sound(self.click_snd, volume=audio.sfx_volume)


class MenuMode:
    """Base class for escape menu sub-modes."""

    def __init__(self, ctx: MenuContext) -> None:
        self.ctx = ctx

    def on_enter(self) -> None:
        """Called when this mode becomes active."""

    def update(self, dt: float) -> None:
        """Per-frame update."""

    def draw(self) -> None:
        """Draw the mode's UI."""

    def on_mouse_press(self, x: int, y: int) -> None:
        """Handle mouse click."""

    def on_mouse_motion(self, x: int, y: int) -> None:
        """Handle mouse movement."""

    def on_mouse_release(self, x: int, y: int) -> None:
        """Handle mouse release."""

    def on_mouse_scroll(self, scroll_y: float) -> None:
        """Handle scroll wheel."""

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        """Handle key press."""

    def on_text(self, text: str) -> None:
        """Handle text input."""
