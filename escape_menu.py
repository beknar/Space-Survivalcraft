"""Escape menu overlay for Space Survivalcraft."""
from __future__ import annotations

import os
from typing import Callable, Optional

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H, MENU_BTN_GAP,
    SFX_VEHICLES_DIR,
)


class EscapeMenu:
    """Modal overlay with Resume / Save / Load / Main Menu / Exit buttons."""

    _BUTTONS: list[tuple[str, str]] = [
        ("resume",    "Resume"),
        ("save",      "Save Game"),
        ("load",      "Load Game"),
        ("main_menu", "Main Menu"),
        ("exit",      "Exit Game"),
    ]

    def __init__(
        self,
        save_fn: Callable[[], None],
        load_fn: Callable[[], None],
        main_menu_fn: Callable[[], None],
    ) -> None:
        self.open: bool = False
        self._save_fn = save_fn
        self._load_fn = load_fn
        self._main_menu_fn = main_menu_fn

        self._hover_idx: int = -1  # which button is hovered (-1 = none)
        self._status_msg: str = ""  # brief feedback ("Saved!", "Loaded!", etc.)
        self._status_timer: float = 0.0

        # Panel geometry (centred on screen)
        self._px = (SCREEN_WIDTH - MENU_W) // 2
        self._py = (SCREEN_HEIGHT - MENU_H) // 2

        # Pre-compute button rects (bottom-left origin)
        self._btn_rects: list[tuple[int, int, int, int]] = []  # (x, y, w, h)
        bx = self._px + (MENU_W - MENU_BTN_W) // 2
        # First button starts below the title area
        first_by = self._py + MENU_H - 60 - MENU_BTN_H
        for i in range(len(self._BUTTONS)):
            by = first_by - i * (MENU_BTN_H + MENU_BTN_GAP)
            self._btn_rects.append((bx, by, MENU_BTN_W, MENU_BTN_H))

        # Sound
        self._click_snd = arcade.load_sound(
            os.path.join(SFX_VEHICLES_DIR,
                         "Sci-Fi Spaceship Interface Mechanical Switch 1.wav")
        )

        # Pre-built text objects
        self._t_title = arcade.Text(
            "MENU",
            SCREEN_WIDTH // 2, self._py + MENU_H - 30,
            arcade.color.LIGHT_BLUE, 22, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_labels: list[arcade.Text] = []
        for i, (_key, label) in enumerate(self._BUTTONS):
            bx, by, bw, bh = self._btn_rects[i]
            self._t_labels.append(arcade.Text(
                label,
                bx + bw // 2, by + bh // 2,
                arcade.color.WHITE, 13, bold=True,
                anchor_x="center", anchor_y="center",
            ))
        self._t_status = arcade.Text(
            "",
            SCREEN_WIDTH // 2, self._py + 14,
            arcade.color.YELLOW_GREEN, 11, bold=True,
            anchor_x="center", anchor_y="center",
        )

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self._hover_idx = -1

    def update(self, dt: float) -> None:
        """Tick status message timer."""
        if self._status_timer > 0.0:
            self._status_timer = max(0.0, self._status_timer - dt)
            if self._status_timer <= 0.0:
                self._status_msg = ""

    def on_mouse_motion(self, x: int, y: int) -> None:
        if not self.open:
            return
        self._hover_idx = self._button_at(x, y)

    def on_mouse_press(self, x: int, y: int) -> None:
        if not self.open:
            return
        idx = self._button_at(x, y)
        if idx < 0:
            return
        arcade.play_sound(self._click_snd, volume=0.5)
        key = self._BUTTONS[idx][0]
        if key == "resume":
            self.open = False
        elif key == "save":
            self._save_fn()
            self._flash_status("Game saved!")
        elif key == "load":
            self._load_fn()
            self._flash_status("Game loaded!")
        elif key == "main_menu":
            self.open = False
            self._main_menu_fn()
        elif key == "exit":
            arcade.exit()

    def draw(self) -> None:
        if not self.open:
            return

        # Semi-transparent dark overlay
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT),
            (0, 0, 0, 160),
        )

        # Panel background
        arcade.draw_rect_filled(
            arcade.LBWH(self._px, self._py, MENU_W, MENU_H),
            (20, 20, 50, 240),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(self._px, self._py, MENU_W, MENU_H),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        # Title
        self._t_title.draw()

        # Buttons
        for i, (_key, _label) in enumerate(self._BUTTONS):
            bx, by, bw, bh = self._btn_rects[i]
            hovered = (i == self._hover_idx)

            # Button background
            bg = (50, 80, 140, 255) if hovered else (30, 40, 80, 255)
            arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), bg)
            outline = arcade.color.CYAN if hovered else arcade.color.STEEL_BLUE
            arcade.draw_rect_outline(
                arcade.LBWH(bx, by, bw, bh), outline, border_width=2,
            )

            # Label
            self._t_labels[i].color = arcade.color.CYAN if hovered else arcade.color.WHITE
            self._t_labels[i].draw()

        # Status feedback message
        if self._status_msg:
            self._t_status.text = self._status_msg
            self._t_status.draw()

    def _button_at(self, x: int, y: int) -> int:
        """Return button index at screen coords, or -1."""
        for i, (bx, by, bw, bh) in enumerate(self._btn_rects):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return i
        return -1

    def _flash_status(self, msg: str) -> None:
        self._status_msg = msg
        self._status_timer = 2.0
