"""Shared UI drawing helpers for escape menu modes."""
from __future__ import annotations

import arcade

from constants import MENU_W, MENU_H, MENU_BTN_W


def draw_panel(px: int, py: int, w: int = MENU_W, h: int = MENU_H) -> None:
    """Draw the standard blue semi-transparent panel."""
    arcade.draw_rect_filled(arcade.LBWH(px, py, w, h), (20, 20, 50, 240))
    arcade.draw_rect_outline(arcade.LBWH(px, py, w, h),
                             arcade.color.STEEL_BLUE, border_width=2)


def draw_back_button(px: int, py: int, t_back: arcade.Text,
                     menu_w: int = MENU_W) -> None:
    """Draw a standard back button at the bottom of the panel."""
    bx = px + (menu_w - MENU_BTN_W) // 2
    by = py + 12
    bw, bh = MENU_BTN_W, 35
    arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), (40, 40, 70, 220))
    arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh),
                             arcade.color.STEEL_BLUE, border_width=1)
    t_back.text = "Back"
    t_back.x = bx + bw // 2
    t_back.y = by + bh // 2
    t_back.draw()


def back_button_hit(x: int, y: int, px: int, py: int,
                    menu_w: int = MENU_W) -> bool:
    """Return True if (x, y) is inside the standard back button."""
    bx = px + (menu_w - MENU_BTN_W) // 2
    by = py + 12
    return bx <= x <= bx + MENU_BTN_W and by <= y <= by + 35


def draw_slider(rect: tuple, value: float,
                label_text: arcade.Text, pct_text: arcade.Text) -> None:
    """Draw a horizontal volume slider track + knob + labels."""
    sx, sy, sw, sh = rect
    arcade.draw_rect_filled(arcade.LBWH(sx, sy, sw, sh), (40, 40, 60, 255))
    fill_w = int(sw * value)
    if fill_w > 0:
        arcade.draw_rect_filled(arcade.LBWH(sx, sy, fill_w, sh),
                                (0, 160, 220, 255))
    arcade.draw_circle_filled(sx + fill_w, sy + sh // 2, 7, arcade.color.CYAN)
    label_text.draw()
    pct_text.text = f"{int(value * 100)}%"
    pct_text.draw()


def btn_at(x: int, y: int, rects: list[tuple[int, int, int, int]]) -> int:
    """Return button index at screen coords, or -1."""
    for i, (rx, ry, rw, rh) in enumerate(rects):
        if rx <= x <= rx + rw and ry <= y <= ry + rh:
            return i
    return -1


def point_in_rect(x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x <= rx + rw and ry <= y <= ry + rh
