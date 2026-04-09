"""Save/Load/Naming sub-mode for the escape menu."""
from __future__ import annotations

import json
import os

import arcade

from constants import (
    MENU_W, MENU_BTN_W,
    SAVE_MENU_W, SAVE_MENU_H, SAVE_SLOT_W, SAVE_SLOT_H, SAVE_SLOT_GAP,
    SAVE_SLOT_COUNT,
)
from escape_menu._context import MenuContext, MenuMode
from escape_menu._ui import btn_at, point_in_rect

MAX_NAME_LEN = 24


class SaveLoadMode(MenuMode):
    """Handles save, load, and naming as internal sub-states."""

    def __init__(self, ctx: MenuContext) -> None:
        super().__init__(ctx)
        self._sub: str = "save"  # "save", "load", "confirm", "delete_confirm", or "naming"
        self._slots: list[dict] = []
        self._naming_slot: int = -1
        self._naming_text: str = ""
        self._cursor_visible: bool = True
        self._cursor_timer: float = 0.0
        # Pre-built text objects
        self._t_title = arcade.Text("SAVE GAME", 0, 0, arcade.color.LIGHT_BLUE, 20,
                                    bold=True, anchor_x="center", anchor_y="center")
        self._t_slot_labels: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.WHITE, 11, anchor_x="left", anchor_y="center")
            for _ in range(SAVE_SLOT_COUNT)
        ]
        self._t_slot_details: list[arcade.Text] = [
            arcade.Text("", 0, 0, (160, 180, 200), 9, anchor_x="left", anchor_y="center")
            for _ in range(SAVE_SLOT_COUNT)
        ]
        self._t_back = arcade.Text("Back", 0, 0, arcade.color.WHITE, 13,
                                   bold=True, anchor_x="center", anchor_y="center")
        self._t_prompt = arcade.Text("Enter save name:", 0, 0, arcade.color.LIGHT_BLUE,
                                     14, bold=True, anchor_x="center", anchor_y="center")
        self._t_input = arcade.Text("", 0, 0, arcade.color.WHITE, 14,
                                    anchor_x="center", anchor_y="center")
        self._t_hint = arcade.Text("ENTER to save  \u00b7  ESC to cancel", 0, 0,
                                   (120, 120, 120), 10, anchor_x="center", anchor_y="center")
        self._t_confirm = arcade.Text("", 0, 0, arcade.color.YELLOW, 12, bold=True,
                                      anchor_x="center", anchor_y="center")
        self._t_confirm_hint = arcade.Text("ENTER to overwrite  \u00b7  ESC to cancel", 0, 0,
                                           (120, 120, 120), 10,
                                           anchor_x="center", anchor_y="center")
        self._t_delete_hint = arcade.Text("ENTER to delete  \u00b7  ESC to cancel", 0, 0,
                                          (120, 120, 120), 10,
                                          anchor_x="center", anchor_y="center")

    def open_save(self) -> None:
        self._sub = "save"; self._refresh_slots()

    def open_load(self) -> None:
        self._sub = "load"; self._refresh_slots()

    def _refresh_slots(self) -> None:
        self._slots = []
        os.makedirs(self.ctx.save_dir, exist_ok=True)
        for i in range(SAVE_SLOT_COUNT):
            path = os.path.join(self.ctx.save_dir, f"save_slot_{i + 1:02d}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    player = data.get("player", {})
                    zone_names = {"MAIN": "Double Star", "ZONE2": "Nebula",
                                   "WARP_METEOR": "Warp", "WARP_LIGHTNING": "Warp",
                                   "WARP_GAS": "Warp", "WARP_ENEMY": "Warp"}
                    zone_id = data.get("zone_id", "MAIN")
                    self._slots.append({
                        "name": data.get("save_name", f"Save {i + 1}"),
                        "exists": True,
                        "faction": data.get("faction", "?"),
                        "ship_type": data.get("ship_type", "?"),
                        "character": data.get("character_name", ""),
                        "hp": player.get("hp", 0),
                        "shields": player.get("shields", 0),
                        "modules": len(data.get("buildings", [])),
                        "zone": zone_names.get(zone_id, zone_id),
                    })
                except (json.JSONDecodeError, OSError):
                    self._slots.append({"name": "", "exists": False})
            else:
                self._slots.append({"name": "", "exists": False})

    def _layout(self) -> tuple[int, int, list, tuple]:
        w = self.ctx.window
        px = (w.width - SAVE_MENU_W) // 2
        py = (w.height - SAVE_MENU_H) // 2
        slot_bx = px + (SAVE_MENU_W - SAVE_SLOT_W) // 2
        first_by = py + SAVE_MENU_H - 60 - SAVE_SLOT_H
        rects = [(slot_bx, first_by - i * (SAVE_SLOT_H + SAVE_SLOT_GAP),
                  SAVE_SLOT_W, SAVE_SLOT_H) for i in range(SAVE_SLOT_COUNT)]
        back = (px + (SAVE_MENU_W - MENU_BTN_W) // 2, py + 16, MENU_BTN_W, 35)
        return px, py, rects, back

    def update(self, dt: float) -> None:
        if self._sub == "naming":
            self._cursor_timer += dt
            if self._cursor_timer >= 0.5:
                self._cursor_timer -= 0.5
                self._cursor_visible = not self._cursor_visible

    def draw(self) -> None:
        px, py, rects, back = self._layout()
        arcade.draw_rect_filled(arcade.LBWH(px, py, SAVE_MENU_W, SAVE_MENU_H), (20, 20, 50, 240))
        arcade.draw_rect_outline(arcade.LBWH(px, py, SAVE_MENU_W, SAVE_MENU_H),
                                 arcade.color.STEEL_BLUE, border_width=2)

        is_save = self._sub in ("save", "naming", "confirm")
        self._t_title.text = "SAVE GAME" if is_save else "LOAD GAME  (DEL to delete)"
        self._t_title.x = px + SAVE_MENU_W // 2
        self._t_title.y = py + SAVE_MENU_H - 30
        self._t_title.draw()

        from ui_helpers import draw_load_slot, draw_button, BTN_BG_BACK_NORMAL
        is_load = self._sub == "load"
        for i in range(SAVE_SLOT_COUNT):
            draw_load_slot(i, rects, self._slots, self.ctx.hover_idx,
                           self._t_slot_labels, self._t_slot_details,
                           grey_empty=is_load)

        # Back button
        self._t_back.x = back[0] + back[2] // 2
        self._t_back.y = back[1] + back[3] // 2
        draw_button(back, self.ctx.hover_idx == 100, self._t_back,
                    bg_normal=BTN_BG_BACK_NORMAL)

        if self.ctx.status_msg:
            self.ctx.t_status.x = self.ctx.window.width // 2
            self.ctx.t_status.y = py + 55
            self.ctx.t_status.text = self.ctx.status_msg
            self.ctx.t_status.draw()

        if self._sub == "confirm":
            self._draw_confirm(px, py)
        elif self._sub == "delete_confirm":
            self._draw_delete_confirm(px, py)
        elif self._sub == "naming":
            self._draw_naming(px, py)

    def _draw_confirm(self, sl_px: int, sl_py: int) -> None:
        arcade.draw_rect_filled(arcade.LBWH(sl_px, sl_py, SAVE_MENU_W, SAVE_MENU_H), (0, 0, 0, 120))
        bw, bh = 300, 80
        bx = (self.ctx.window.width - bw) // 2
        by = (self.ctx.window.height - bh) // 2
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), (40, 20, 20, 250))
        arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh), (200, 80, 80), border_width=2)
        cx = bx + bw // 2
        slot_name = self._slots[self._naming_slot]["name"] if self._naming_slot >= 0 else "?"
        self._t_confirm.text = f'Overwrite "{slot_name}"?'
        self._t_confirm.x = cx; self._t_confirm.y = by + bh - 25
        self._t_confirm.draw()
        self._t_confirm_hint.x = cx; self._t_confirm_hint.y = by + 18
        self._t_confirm_hint.draw()

    def _draw_delete_confirm(self, sl_px: int, sl_py: int) -> None:
        arcade.draw_rect_filled(arcade.LBWH(sl_px, sl_py, SAVE_MENU_W, SAVE_MENU_H), (0, 0, 0, 120))
        bw, bh = 300, 80
        bx = (self.ctx.window.width - bw) // 2
        by = (self.ctx.window.height - bh) // 2
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), (50, 15, 15, 250))
        arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh), (220, 50, 50), border_width=2)
        cx = bx + bw // 2
        slot_name = self._slots[self._naming_slot]["name"] if self._naming_slot >= 0 else "?"
        self._t_confirm.text = f'Delete "{slot_name}"?'
        self._t_confirm.color = (255, 100, 100)
        self._t_confirm.x = cx; self._t_confirm.y = by + bh - 25
        self._t_confirm.draw()
        self._t_confirm.color = arcade.color.YELLOW
        self._t_delete_hint.x = cx; self._t_delete_hint.y = by + 18
        self._t_delete_hint.draw()

    def _delete_slot(self, slot: int) -> None:
        """Delete a save file and refresh the slot list."""
        path = os.path.join(self.ctx.save_dir, f"save_slot_{slot + 1:02d}.json")
        if os.path.exists(path):
            os.remove(path)
        self._refresh_slots()
        self.ctx.flash_status(f"Slot {slot + 1} deleted")
        self._sub = "load"

    def _draw_naming(self, sl_px: int, sl_py: int) -> None:
        arcade.draw_rect_filled(arcade.LBWH(sl_px, sl_py, SAVE_MENU_W, SAVE_MENU_H), (0, 0, 0, 120))
        bw, bh = 300, 100
        bx = (self.ctx.window.width - bw) // 2
        by = (self.ctx.window.height - bh) // 2
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), (20, 20, 60, 250))
        arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh), arcade.color.CYAN, border_width=2)
        cx = bx + bw // 2
        self._t_prompt.x = cx; self._t_prompt.y = by + bh - 22; self._t_prompt.draw()
        display = self._naming_text + ("|" if self._cursor_visible else "")
        self._t_input.text = display; self._t_input.x = cx; self._t_input.y = by + bh // 2
        self._t_input.draw()
        self._t_hint.x = cx; self._t_hint.y = by + 18; self._t_hint.draw()

    def on_mouse_motion(self, x: int, y: int) -> None:
        _, _, rects, back = self._layout()
        slot = btn_at(x, y, rects)
        if slot >= 0:
            self.ctx.hover_idx = slot
        elif point_in_rect(x, y, back):
            self.ctx.hover_idx = 100
        else:
            self.ctx.hover_idx = -1

    def on_mouse_press(self, x: int, y: int) -> None:
        if self._sub in ("naming", "confirm", "delete_confirm"): return
        _, _, rects, back = self._layout()
        self.ctx.play_click()
        if point_in_rect(x, y, back):
            self.ctx.set_mode("main"); return
        slot = btn_at(x, y, rects)
        if slot < 0: return
        if self._sub == "save":
            self._naming_slot = slot
            if self._slots[slot]["exists"]:
                self._sub = "confirm"
            else:
                self._naming_text = ""
                self._sub = "naming"; self._cursor_visible = True; self._cursor_timer = 0.0
        elif self._sub == "load" and self._slots[slot]["exists"]:
            self.ctx.load_fn(slot)
            self.ctx.flash_status(f"Loaded: {self._slots[slot]['name']}")
            self.ctx.set_mode("main")

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        if self._sub == "delete_confirm":
            if key == arcade.key.ESCAPE:
                self._sub = "load"
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                self._delete_slot(self._naming_slot)
            return
        if self._sub == "confirm":
            if key == arcade.key.ESCAPE:
                self._sub = "save"
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                self._naming_text = self._slots[self._naming_slot]["name"]
                self._sub = "naming"; self._cursor_visible = True; self._cursor_timer = 0.0
            return
        if self._sub == "load":
            if key == arcade.key.DELETE:
                # Delete the currently hovered slot
                idx = self.ctx.hover_idx
                if 0 <= idx < len(self._slots) and self._slots[idx]["exists"]:
                    self._naming_slot = idx
                    self._sub = "delete_confirm"
                return
        if self._sub == "naming":
            if key == arcade.key.ESCAPE:
                self._sub = "save"
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                name = self._naming_text.strip() or f"Save {self._naming_slot + 1}"
                self.ctx.save_fn(self._naming_slot, name)
                self._refresh_slots()
                self.ctx.flash_status(f"Saved: {name}")
                self.ctx.set_mode("main")
            elif key == arcade.key.BACKSPACE:
                self._naming_text = self._naming_text[:-1]
        else:
            if key == arcade.key.ESCAPE:
                self.ctx.set_mode("main")

    def on_text(self, text: str) -> None:
        if self._sub == "naming":
            for ch in text:
                if len(self._naming_text) < MAX_NAME_LEN and ch.isprintable():
                    self._naming_text += ch
