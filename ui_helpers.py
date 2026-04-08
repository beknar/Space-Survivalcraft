"""Shared UI drawing helpers used by splash, options, and death screen views."""
from __future__ import annotations

import arcade


# ── Standard button colours ─────────────────────────────────────────────────
BTN_BG_NORMAL = (25, 35, 70, 230)
BTN_BG_HOVER = (50, 80, 140, 255)
BTN_BG_BACK_NORMAL = (30, 40, 80, 255)
BTN_OUTLINE_NORMAL = arcade.color.STEEL_BLUE
BTN_OUTLINE_HOVER = arcade.color.CYAN
BTN_TEXT_NORMAL = arcade.color.WHITE
BTN_TEXT_HOVER = arcade.color.CYAN

# ── Load-slot 3-state colours ──────────────────────────────────────────────
SLOT_BG_EMPTY = (20, 20, 40, 255)
SLOT_OUTLINE_EMPTY = (60, 60, 80)
SLOT_TEXT_EMPTY = (80, 80, 100)
SLOT_BG_NORMAL = (30, 40, 80, 255)
SLOT_DETAIL_NORMAL = (120, 150, 180)
SLOT_DETAIL_HOVER = (140, 200, 240)


def draw_button(
    rect: tuple[int, int, int, int],
    hovered: bool,
    text_obj: arcade.Text,
    *,
    bg_normal: tuple = BTN_BG_NORMAL,
) -> None:
    """Draw a styled button rectangle with hover highlight and centred label."""
    bx, by, bw, bh = rect
    bg = BTN_BG_HOVER if hovered else bg_normal
    arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), bg)
    outline = BTN_OUTLINE_HOVER if hovered else BTN_OUTLINE_NORMAL
    arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh), outline, border_width=2)
    text_obj.color = BTN_TEXT_HOVER if hovered else BTN_TEXT_NORMAL
    text_obj.draw()


def draw_load_slot(
    i: int,
    slot_rects: list[tuple[int, int, int, int]],
    load_slots: list[dict],
    load_hover: int,
    t_labels: list[arcade.Text],
    t_details: list[arcade.Text],
) -> None:
    """Draw a single save-slot row with 3-state colouring (empty/normal/hover)."""
    sx, sy, sw, sh = slot_rects[i]
    info = load_slots[i] if i < len(load_slots) else {"name": "", "exists": False}
    hovered = (i == load_hover)

    if not info["exists"]:
        bg, outline_c, text_c = SLOT_BG_EMPTY, SLOT_OUTLINE_EMPTY, SLOT_TEXT_EMPTY
    elif hovered:
        bg, outline_c, text_c = BTN_BG_HOVER, BTN_OUTLINE_HOVER, BTN_TEXT_HOVER
    else:
        bg, outline_c, text_c = SLOT_BG_NORMAL, BTN_OUTLINE_NORMAL, BTN_TEXT_NORMAL

    arcade.draw_rect_filled(arcade.LBWH(sx, sy, sw, sh), bg)
    arcade.draw_rect_outline(arcade.LBWH(sx, sy, sw, sh), outline_c, border_width=1)

    label = f"Slot {i + 1}: {info['name']}" if info["exists"] else f"Slot {i + 1}: \u2014 Empty \u2014"
    t_labels[i].text = label
    t_labels[i].x = sx + 10
    t_labels[i].y = sy + sh - 10
    t_labels[i].color = text_c
    t_labels[i].draw()

    if info["exists"]:
        zone_label = info.get("zone", "")
        zone_part = f"  \u00b7 {zone_label}" if zone_label else ""
        char_label = info.get("character", "")
        char_part = f"  \u00b7 {char_label}" if char_label else ""
        detail = (f"{info.get('faction', '?')} \u00b7 {info.get('ship_type', '?')}"
                  f"{char_part}{zone_part}"
                  f"  |  HP {info.get('hp', 0)}  Shields {info.get('shields', 0)}")
        det_c = SLOT_DETAIL_HOVER if hovered else SLOT_DETAIL_NORMAL
        t_details[i].text = detail
        t_details[i].x = sx + 10
        t_details[i].y = sy + 10
        t_details[i].color = det_c
        t_details[i].draw()
