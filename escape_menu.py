"""Escape menu overlay for Space Survivalcraft."""
from __future__ import annotations

import json
import os
from typing import Callable, Optional

import arcade

import constants
from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    MENU_W, MENU_H, MENU_BTN_W, MENU_BTN_H, MENU_BTN_GAP,
    SAVE_MENU_W, SAVE_MENU_H, SAVE_SLOT_W, SAVE_SLOT_H, SAVE_SLOT_GAP,
    SAVE_SLOT_COUNT,
    SFX_VEHICLES_DIR,
    RESOLUTION_PRESETS,
)
from settings import audio


class EscapeMenu:
    """Modal overlay with Resume / Save / Load / Main Menu / Exit buttons
    and a 10-slot save/load sub-menu with named saves."""

    MODE_MAIN = 0
    MODE_SAVE = 1
    MODE_LOAD = 2
    MODE_NAMING = 3
    MODE_RESOLUTION = 4

    MAX_NAME_LEN = 24

    _MAIN_BUTTONS: list[tuple[str, str]] = [
        ("resume",     "Resume"),
        ("save",       "Save Game"),
        ("load",       "Load Game"),
        ("resolution", "Resolution"),
        ("main_menu",  "Main Menu"),
        ("exit",       "Exit Game"),
    ]

    def __init__(
        self,
        save_fn: Callable[[int, str], None],
        load_fn: Callable[[int], None],
        main_menu_fn: Callable[[], None],
        save_dir: str,
        resolution_fn: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self.open: bool = False
        self._save_fn = save_fn
        self._load_fn = load_fn
        self._main_menu_fn = main_menu_fn
        self._save_dir = save_dir
        self._resolution_fn = resolution_fn

        # Resolution selector state
        current_res = (audio.screen_width, audio.screen_height)
        self._res_idx = 0
        for i, preset in enumerate(RESOLUTION_PRESETS):
            if preset == current_res:
                self._res_idx = i
                break

        self._mode: int = self.MODE_MAIN
        self._hover_idx: int = -1
        self._status_msg: str = ""
        self._status_timer: float = 0.0

        # Save slot metadata
        self._slots: list[dict] = []
        self._refresh_slots()

        # Naming state
        self._naming_slot: int = -1
        self._naming_text: str = ""
        self._cursor_visible: bool = True
        self._cursor_timer: float = 0.0

        # ── Audio slider state ──────────────────────────────────────────
        self._slider_dragging: str = ""   # "", "music", or "sfx"

        # ── Main mode geometry (centred on screen) ────────────────────
        # Use actual window dimensions (correct in fullscreen)
        self._window = arcade.get_window()
        sw = self._window.width
        sh = self._window.height
        self._main_px = (sw - MENU_W) // 2
        self._main_py = (sh - MENU_H) // 2

        # Slider geometry (placed below title, above buttons)
        _slider_w = 220
        _slider_x = self._main_px + (MENU_W - _slider_w) // 2
        _music_y = self._main_py + MENU_H - 80
        _sfx_y = _music_y - 50
        self._slider_music_rect = (_slider_x, _music_y, _slider_w, 8)
        self._slider_sfx_rect = (_slider_x, _sfx_y, _slider_w, 8)

        # Buttons shifted down to accommodate sliders (~140px from old position)
        self._main_btn_rects: list[tuple[int, int, int, int]] = []
        bx = self._main_px + (MENU_W - MENU_BTN_W) // 2
        first_by = self._main_py + MENU_H - 200 - MENU_BTN_H
        for i in range(len(self._MAIN_BUTTONS)):
            by = first_by - i * (MENU_BTN_H + MENU_BTN_GAP)
            self._main_btn_rects.append((bx, by, MENU_BTN_W, MENU_BTN_H))

        # ── Save/Load mode geometry ───────────────────────────────────
        self._sl_px = (sw - SAVE_MENU_W) // 2
        self._sl_py = (sh - SAVE_MENU_H) // 2

        self._slot_rects: list[tuple[int, int, int, int]] = []
        slot_bx = self._sl_px + (SAVE_MENU_W - SAVE_SLOT_W) // 2
        first_slot_by = self._sl_py + SAVE_MENU_H - 60 - SAVE_SLOT_H
        for i in range(SAVE_SLOT_COUNT):
            slot_by = first_slot_by - i * (SAVE_SLOT_H + SAVE_SLOT_GAP)
            self._slot_rects.append((slot_bx, slot_by, SAVE_SLOT_W, SAVE_SLOT_H))

        # Back button in save/load mode
        back_bx = self._sl_px + (SAVE_MENU_W - MENU_BTN_W) // 2
        back_by = self._sl_py + 16
        self._back_rect = (back_bx, back_by, MENU_BTN_W, 35)

        # ── Sound ────────────────────────────────────────────────────
        self._click_snd = arcade.load_sound(
            os.path.join(SFX_VEHICLES_DIR,
                         "Sci-Fi Spaceship Interface Mechanical Switch 1.wav")
        )

        # ── Pre-built text objects: main mode ─────────────────────────
        self._t_title = arcade.Text(
            "MENU",
            sw // 2, self._main_py + MENU_H - 30,
            arcade.color.LIGHT_BLUE, 22, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_main_labels: list[arcade.Text] = []
        for i, (_key, label) in enumerate(self._MAIN_BUTTONS):
            bx, by, bw, bh = self._main_btn_rects[i]
            self._t_main_labels.append(arcade.Text(
                label,
                bx + bw // 2, by + bh // 2,
                arcade.color.WHITE, 13, bold=True,
                anchor_x="center", anchor_y="center",
            ))

        # ── Pre-built text objects: audio sliders ──────────────────────
        sx, sy, sw, _sh = self._slider_music_rect
        self._t_music_label = arcade.Text(
            "Music", sx, sy + 16,
            arcade.color.WHITE, 10, bold=True,
        )
        self._t_music_pct = arcade.Text(
            "", sx + sw, sy + 16,
            arcade.color.CYAN, 10,
            anchor_x="right",
        )
        sx2, sy2, sw2, _sh2 = self._slider_sfx_rect
        self._t_sfx_label = arcade.Text(
            "SFX", sx2, sy2 + 16,
            arcade.color.WHITE, 10, bold=True,
        )
        self._t_sfx_pct = arcade.Text(
            "", sx2 + sw2, sy2 + 16,
            arcade.color.CYAN, 10,
            anchor_x="right",
        )

        # ── Pre-built text objects: resolution sub-mode ─────────────────
        mid_y = self._main_py + MENU_H // 2
        self._t_res_title = arcade.Text(
            "RESOLUTION",
            sw // 2, self._main_py + MENU_H - 30,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_res_value = arcade.Text(
            "", sw // 2, mid_y,
            arcade.color.YELLOW, 16, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_res_left = arcade.Text(
            "<", self._main_px + 48, mid_y,
            (180, 180, 180), 22, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_res_right = arcade.Text(
            ">", self._main_px + MENU_W - 48, mid_y,
            (180, 180, 180), 22, bold=True,
            anchor_x="center", anchor_y="center",
        )
        apply_y = mid_y - 50
        abx = self._main_px + (MENU_W - MENU_BTN_W) // 2
        self._t_apply_windowed = arcade.Text(
            "Apply Windowed",
            abx + MENU_BTN_W // 2, apply_y + MENU_BTN_H // 2,
            arcade.color.WHITE, 12, bold=True,
            anchor_x="center", anchor_y="center",
        )
        fs_y = apply_y - MENU_BTN_H - 12
        self._t_apply_fullscreen = arcade.Text(
            "Apply Fullscreen",
            abx + MENU_BTN_W // 2, fs_y + MENU_BTN_H // 2,
            arcade.color.WHITE, 12, bold=True,
            anchor_x="center", anchor_y="center",
        )
        bl_y = fs_y - MENU_BTN_H - 12
        self._t_apply_borderless = arcade.Text(
            "Borderless Windowed",
            abx + MENU_BTN_W // 2, bl_y + MENU_BTN_H // 2,
            arcade.color.WHITE, 12, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_res_back = arcade.Text(
            "Back", 0, 0,
            arcade.color.WHITE, 12, bold=True,
            anchor_x="center", anchor_y="center",
        )

        # ── Pre-built text objects: save/load mode ────────────────────
        self._t_sl_title = arcade.Text(
            "SAVE GAME",
            sw // 2, self._sl_py + SAVE_MENU_H - 30,
            arcade.color.LIGHT_BLUE, 20, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_slot_labels: list[arcade.Text] = []
        self._t_slot_details: list[arcade.Text] = []
        for i in range(SAVE_SLOT_COUNT):
            sx, sy, sw, sh = self._slot_rects[i]
            self._t_slot_labels.append(arcade.Text(
                "",
                sx + 10, sy + sh - 10,
                arcade.color.WHITE, 11,
                anchor_x="left", anchor_y="center",
            ))
            self._t_slot_details.append(arcade.Text(
                "",
                sx + 10, sy + 10,
                (160, 180, 200), 9,
                anchor_x="left", anchor_y="center",
            ))
        bbx, bby, bbw, bbh = self._back_rect
        self._t_back = arcade.Text(
            "Back",
            bbx + bbw // 2, bby + bbh // 2,
            arcade.color.WHITE, 13, bold=True,
            anchor_x="center", anchor_y="center",
        )

        # ── Pre-built text objects: naming overlay ────────────────────
        self._t_naming_prompt = arcade.Text(
            "Enter save name:",
            sw // 2, 0,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_naming_input = arcade.Text(
            "",
            sw // 2, 0,
            arcade.color.WHITE, 14,
            anchor_x="center", anchor_y="center",
        )
        self._t_naming_hint = arcade.Text(
            "ENTER to save  \u00b7  ESC to cancel",
            sw // 2, 0,
            (120, 120, 120), 10,
            anchor_x="center", anchor_y="center",
        )

        # ── Status message ────────────────────────────────────────────
        self._t_status = arcade.Text(
            "",
            sw // 2, 0,
            arcade.color.YELLOW_GREEN, 11, bold=True,
            anchor_x="center", anchor_y="center",
        )

    # ── Slot metadata ─────────────────────────────────────────────────

    def _refresh_slots(self) -> None:
        """Read save directory to populate slot metadata."""
        self._slots = []
        os.makedirs(self._save_dir, exist_ok=True)
        for i in range(SAVE_SLOT_COUNT):
            path = os.path.join(self._save_dir, f"save_slot_{i + 1:02d}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    name = data.get("save_name", f"Save {i + 1}")
                    player = data.get("player", {})
                    self._slots.append({
                        "name": name,
                        "exists": True,
                        "faction": data.get("faction", "?"),
                        "ship_type": data.get("ship_type", "?"),
                        "hp": player.get("hp", 0),
                        "shields": player.get("shields", 0),
                        "modules": len(data.get("buildings", [])),
                    })
                except (json.JSONDecodeError, OSError):
                    self._slots.append({"name": "", "exists": False})
            else:
                self._slots.append({"name": "", "exists": False})

    def _slot_label(self, i: int) -> str:
        """Build the display label for slot i."""
        info = self._slots[i]
        if info["exists"]:
            return f"Slot {i + 1}: {info['name']}"
        return f"Slot {i + 1}: \u2014 Empty \u2014"

    def _slot_detail(self, i: int) -> str:
        """Build a detail line (faction / ship / HP / shields) for slot i."""
        info = self._slots[i]
        if not info.get("exists"):
            return ""
        detail = (f"{info.get('faction', '?')} \u00b7 {info.get('ship_type', '?')}"
                  f"  |  HP {info.get('hp', 0)}  Shields {info.get('shields', 0)}")
        modules = info.get("modules", 0)
        if modules > 0:
            detail += f"  |  Modules {modules}"
        return detail

    # ── Public API ────────────────────────────────────────────────────

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self._mode = self.MODE_MAIN
            self._hover_idx = -1

    def update(self, dt: float) -> None:
        """Tick status message timer and cursor blink."""
        if self._status_timer > 0.0:
            self._status_timer = max(0.0, self._status_timer - dt)
            if self._status_timer <= 0.0:
                self._status_msg = ""
        if self._mode == self.MODE_NAMING:
            self._cursor_timer += dt
            if self._cursor_timer >= 0.5:
                self._cursor_timer -= 0.5
                self._cursor_visible = not self._cursor_visible

    def on_mouse_motion(self, x: int, y: int) -> None:
        if not self.open:
            return
        # Slider drag
        if self._slider_dragging:
            self._apply_slider_drag(x)
            return
        if self._mode == self.MODE_MAIN:
            self._hover_idx = self._btn_at(x, y, self._main_btn_rects)
        elif self._mode in (self.MODE_SAVE, self.MODE_LOAD):
            slot_idx = self._btn_at(x, y, self._slot_rects)
            if slot_idx >= 0:
                self._hover_idx = slot_idx
            elif self._point_in_rect(x, y, self._back_rect):
                self._hover_idx = 100  # sentinel for back button
            else:
                self._hover_idx = -1

    def on_mouse_press(self, x: int, y: int) -> None:
        if not self.open:
            return

        if self._mode == self.MODE_NAMING:
            return  # ignore clicks during naming

        # Check slider hit before button hit
        if self._mode == self.MODE_MAIN:
            slider = self._slider_hit(x, y)
            if slider:
                self._slider_dragging = slider
                self._apply_slider_drag(x)
                return

        arcade.play_sound(self._click_snd, volume=audio.sfx_volume)

        if self._mode == self.MODE_MAIN:
            idx = self._btn_at(x, y, self._main_btn_rects)
            if idx < 0:
                return
            key = self._MAIN_BUTTONS[idx][0]
            if key == "resume":
                self.open = False
            elif key == "save":
                self._refresh_slots()
                self._mode = self.MODE_SAVE
                self._hover_idx = -1
            elif key == "load":
                self._refresh_slots()
                self._mode = self.MODE_LOAD
                self._hover_idx = -1
            elif key == "resolution":
                self._mode = self.MODE_RESOLUTION
                self._hover_idx = -1
            elif key == "main_menu":
                self.open = False
                self._main_menu_fn()
            elif key == "exit":
                arcade.exit()

        elif self._mode == self.MODE_RESOLUTION:
            # Resolution sub-mode click handling
            if self._point_in_rect(x, y, self._back_rect):
                self._mode = self.MODE_MAIN
                self._hover_idx = -1
                return
            # Left arrow
            lx = self._main_px + 30
            ly = self._main_py + MENU_H // 2
            if lx <= x <= lx + 36 and ly - 18 <= y <= ly + 18:
                self._res_idx = (self._res_idx - 1) % len(RESOLUTION_PRESETS)
                return
            # Right arrow
            rx = self._main_px + MENU_W - 66
            if rx <= x <= rx + 36 and ly - 18 <= y <= ly + 18:
                self._res_idx = (self._res_idx + 1) % len(RESOLUTION_PRESETS)
                return
            # Apply Windowed button
            apply_y = ly - 50
            abx = self._main_px + (MENU_W - MENU_BTN_W) // 2
            if abx <= x <= abx + MENU_BTN_W and apply_y <= y <= apply_y + MENU_BTN_H:
                w, h = RESOLUTION_PRESETS[self._res_idx]
                if self._resolution_fn is not None:
                    self._resolution_fn(w, h, "windowed")
                return
            # Fullscreen button
            fs_y = apply_y - MENU_BTN_H - 12
            if abx <= x <= abx + MENU_BTN_W and fs_y <= y <= fs_y + MENU_BTN_H:
                w, h = RESOLUTION_PRESETS[self._res_idx]
                if self._resolution_fn is not None:
                    self._resolution_fn(w, h, "fullscreen")
                return
            # Borderless Windowed button
            bl_y = fs_y - MENU_BTN_H - 12
            if abx <= x <= abx + MENU_BTN_W and bl_y <= y <= bl_y + MENU_BTN_H:
                w, h = RESOLUTION_PRESETS[self._res_idx]
                if self._resolution_fn is not None:
                    self._resolution_fn(w, h, "borderless")
                return

        elif self._mode == self.MODE_SAVE:
            if self._point_in_rect(x, y, self._back_rect):
                self._mode = self.MODE_MAIN
                self._hover_idx = -1
                return
            slot_idx = self._btn_at(x, y, self._slot_rects)
            if slot_idx >= 0:
                self._naming_slot = slot_idx
                # Pre-fill with existing name or empty
                if self._slots[slot_idx]["exists"]:
                    self._naming_text = self._slots[slot_idx]["name"]
                else:
                    self._naming_text = ""
                self._mode = self.MODE_NAMING
                self._cursor_visible = True
                self._cursor_timer = 0.0

        elif self._mode == self.MODE_LOAD:
            if self._point_in_rect(x, y, self._back_rect):
                self._mode = self.MODE_MAIN
                self._hover_idx = -1
                return
            slot_idx = self._btn_at(x, y, self._slot_rects)
            if slot_idx >= 0 and self._slots[slot_idx]["exists"]:
                self._load_fn(slot_idx)
                self._flash_status(f"Loaded: {self._slots[slot_idx]['name']}")
                self._mode = self.MODE_MAIN

    def on_key_press(self, key: int, modifiers: int = 0) -> None:
        """Handle key events when menu is open."""
        if self._mode == self.MODE_NAMING:
            if key == arcade.key.ESCAPE:
                self._mode = self.MODE_SAVE
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                name = self._naming_text.strip() or f"Save {self._naming_slot + 1}"
                self._save_fn(self._naming_slot, name)
                self._refresh_slots()
                self._flash_status(f"Saved: {name}")
                self._mode = self.MODE_MAIN
            elif key == arcade.key.BACKSPACE:
                self._naming_text = self._naming_text[:-1]
        elif self._mode == self.MODE_RESOLUTION:
            if key == arcade.key.ESCAPE:
                self._mode = self.MODE_MAIN
        elif self._mode in (self.MODE_SAVE, self.MODE_LOAD):
            if key == arcade.key.ESCAPE:
                self._mode = self.MODE_MAIN
                self._hover_idx = -1
        elif self._mode == self.MODE_MAIN:
            if key == arcade.key.ESCAPE:
                self.open = False

    def on_text(self, text: str) -> None:
        """Handle text input during naming mode."""
        if self._mode != self.MODE_NAMING:
            return
        for ch in text:
            if len(self._naming_text) < self.MAX_NAME_LEN and ch.isprintable():
                self._naming_text += ch

    # ── Drawing ───────────────────────────────────────────────────────

    def draw(self) -> None:
        if not self.open:
            return

        # Semi-transparent dark overlay
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, self._window.width, self._window.height),
            (0, 0, 0, 160),
        )

        if self._mode == self.MODE_MAIN:
            self._draw_main()
        elif self._mode == self.MODE_RESOLUTION:
            self._draw_resolution()
        elif self._mode in (self.MODE_SAVE, self.MODE_LOAD, self.MODE_NAMING):
            self._draw_save_load()
            if self._mode == self.MODE_NAMING:
                self._draw_naming_overlay()

    def _draw_main(self) -> None:
        px, py = self._main_px, self._main_py

        # Panel
        arcade.draw_rect_filled(
            arcade.LBWH(px, py, MENU_W, MENU_H),
            (20, 20, 50, 240),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, MENU_W, MENU_H),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        self._t_title.draw()

        # ── Audio sliders ───────────────────────────────────────────
        self._draw_slider(self._slider_music_rect, audio.music_volume,
                          self._t_music_label, self._t_music_pct)
        self._draw_slider(self._slider_sfx_rect, audio.sfx_volume,
                          self._t_sfx_label, self._t_sfx_pct)

        for i, (_key, _label) in enumerate(self._MAIN_BUTTONS):
            bx, by, bw, bh = self._main_btn_rects[i]
            hovered = (i == self._hover_idx)

            bg = (50, 80, 140, 255) if hovered else (30, 40, 80, 255)
            arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), bg)
            outline = arcade.color.CYAN if hovered else arcade.color.STEEL_BLUE
            arcade.draw_rect_outline(
                arcade.LBWH(bx, by, bw, bh), outline, border_width=2,
            )

            self._t_main_labels[i].color = (
                arcade.color.CYAN if hovered else arcade.color.WHITE
            )
            self._t_main_labels[i].draw()

        if self._status_msg:
            self._t_status.x = self._window.width // 2
            self._t_status.y = py + 14
            self._t_status.text = self._status_msg
            self._t_status.draw()

    def _draw_resolution(self) -> None:
        """Draw the resolution selector sub-mode."""
        px, py = self._main_px, self._main_py

        arcade.draw_rect_filled(
            arcade.LBWH(px, py, MENU_W, MENU_H),
            (20, 20, 50, 240),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, MENU_W, MENU_H),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        self._t_res_title.draw()

        # Current resolution value
        w, h = RESOLUTION_PRESETS[self._res_idx]
        self._t_res_value.text = f"{w} x {h}"
        self._t_res_value.draw()

        # Left/right arrows
        self._t_res_left.draw()
        self._t_res_right.draw()

        # Apply Windowed button
        mid_y = py + MENU_H // 2
        apply_y = mid_y - 50
        abx = px + (MENU_W - MENU_BTN_W) // 2
        arcade.draw_rect_filled(
            arcade.LBWH(abx, apply_y, MENU_BTN_W, MENU_BTN_H),
            (30, 60, 30, 220),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(abx, apply_y, MENU_BTN_W, MENU_BTN_H),
            arcade.color.LIME_GREEN, border_width=1,
        )
        self._t_apply_windowed.draw()

        # Apply Fullscreen button
        fs_y = apply_y - MENU_BTN_H - 12
        arcade.draw_rect_filled(
            arcade.LBWH(abx, fs_y, MENU_BTN_W, MENU_BTN_H),
            (30, 30, 60, 220),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(abx, fs_y, MENU_BTN_W, MENU_BTN_H),
            arcade.color.CYAN, border_width=1,
        )
        self._t_apply_fullscreen.draw()

        # Borderless Windowed button
        bl_y = fs_y - MENU_BTN_H - 12
        arcade.draw_rect_filled(
            arcade.LBWH(abx, bl_y, MENU_BTN_W, MENU_BTN_H),
            (40, 30, 60, 220),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(abx, bl_y, MENU_BTN_W, MENU_BTN_H),
            (120, 100, 200), border_width=1,
        )
        self._t_apply_borderless.draw()

        # Back button
        bx, by, bw, bh = self._back_rect
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), (40, 40, 70, 220))
        arcade.draw_rect_outline(
            arcade.LBWH(bx, by, bw, bh), arcade.color.STEEL_BLUE, border_width=1,
        )
        self._t_res_back.x = bx + bw // 2
        self._t_res_back.y = by + bh // 2
        self._t_res_back.draw()

    def _draw_save_load(self) -> None:
        px, py = self._sl_px, self._sl_py

        # Panel
        arcade.draw_rect_filled(
            arcade.LBWH(px, py, SAVE_MENU_W, SAVE_MENU_H),
            (20, 20, 50, 240),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, SAVE_MENU_W, SAVE_MENU_H),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        # Title
        is_save = self._mode in (self.MODE_SAVE, self.MODE_NAMING)
        self._t_sl_title.text = "SAVE GAME" if is_save else "LOAD GAME"
        self._t_sl_title.draw()

        # Slots
        for i in range(SAVE_SLOT_COUNT):
            sx, sy, sw, sh = self._slot_rects[i]
            hovered = (i == self._hover_idx)
            info = self._slots[i]

            if self._mode == self.MODE_LOAD and not info["exists"]:
                bg = (20, 20, 40, 255)
                outline_c = (60, 60, 80)
                text_c = (80, 80, 100)
            elif hovered:
                bg = (50, 80, 140, 255)
                outline_c = arcade.color.CYAN
                text_c = arcade.color.CYAN
            else:
                bg = (30, 40, 80, 255)
                outline_c = arcade.color.STEEL_BLUE
                text_c = (
                    arcade.color.WHITE if info["exists"]
                    else (140, 140, 160)
                )

            arcade.draw_rect_filled(arcade.LBWH(sx, sy, sw, sh), bg)
            arcade.draw_rect_outline(
                arcade.LBWH(sx, sy, sw, sh), outline_c, border_width=1,
            )

            self._t_slot_labels[i].text = self._slot_label(i)
            self._t_slot_labels[i].color = text_c
            self._t_slot_labels[i].draw()

            detail = self._slot_detail(i)
            if detail:
                det_c = (120, 150, 180) if not (hovered and info["exists"]) else (140, 200, 240)
                if self._mode == self.MODE_LOAD and not info["exists"]:
                    det_c = (60, 60, 80)
                self._t_slot_details[i].text = detail
                self._t_slot_details[i].color = det_c
                self._t_slot_details[i].draw()

        # Back button
        bbx, bby, bbw, bbh = self._back_rect
        back_hovered = (self._hover_idx == 100)
        bg = (50, 80, 140, 255) if back_hovered else (30, 40, 80, 255)
        arcade.draw_rect_filled(arcade.LBWH(bbx, bby, bbw, bbh), bg)
        outline = arcade.color.CYAN if back_hovered else arcade.color.STEEL_BLUE
        arcade.draw_rect_outline(
            arcade.LBWH(bbx, bby, bbw, bbh), outline, border_width=2,
        )
        self._t_back.color = (
            arcade.color.CYAN if back_hovered else arcade.color.WHITE
        )
        self._t_back.draw()

        # Status
        if self._status_msg:
            self._t_status.x = self._window.width // 2
            self._t_status.y = py + 55
            self._t_status.text = self._status_msg
            self._t_status.draw()

    def _draw_naming_overlay(self) -> None:
        """Draw text input overlay for save naming."""
        # Darken the slots
        arcade.draw_rect_filled(
            arcade.LBWH(self._sl_px, self._sl_py, SAVE_MENU_W, SAVE_MENU_H),
            (0, 0, 0, 120),
        )

        # Input box
        bw, bh = 300, 100
        bx = (self._window.width - bw) // 2
        by = (self._window.height - bh) // 2

        arcade.draw_rect_filled(
            arcade.LBWH(bx, by, bw, bh), (20, 20, 60, 250),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(bx, by, bw, bh), arcade.color.CYAN, border_width=2,
        )

        # Prompt
        self._t_naming_prompt.y = by + bh - 22
        self._t_naming_prompt.draw()

        # Input text with cursor
        display = self._naming_text
        if self._cursor_visible:
            display += "|"
        self._t_naming_input.text = display
        self._t_naming_input.y = by + bh // 2
        self._t_naming_input.draw()

        # Hint
        self._t_naming_hint.y = by + 18
        self._t_naming_hint.draw()

    # ── Audio slider drawing / interaction ─────────────────────────────

    def _draw_slider(
        self,
        rect: tuple[int, int, int, int],
        value: float,
        label_text: arcade.Text,
        pct_text: arcade.Text,
    ) -> None:
        """Draw a horizontal volume slider track + knob + labels."""
        sx, sy, sw, sh = rect
        # Track background
        arcade.draw_rect_filled(arcade.LBWH(sx, sy, sw, sh), (40, 40, 60, 255))
        # Filled portion
        fill_w = int(sw * value)
        if fill_w > 0:
            arcade.draw_rect_filled(arcade.LBWH(sx, sy, fill_w, sh), (0, 160, 220, 255))
        # Knob
        knob_x = sx + fill_w
        knob_y = sy + sh // 2
        arcade.draw_circle_filled(knob_x, knob_y, 7, arcade.color.CYAN)
        # Labels
        label_text.draw()
        pct_text.text = f"{int(value * 100)}%"
        pct_text.draw()

    def _slider_hit(self, x: int, y: int) -> str:
        """Return 'music', 'sfx', or '' depending on which slider was hit."""
        for name, rect in [("music", self._slider_music_rect),
                           ("sfx", self._slider_sfx_rect)]:
            sx, sy, sw, sh = rect
            if sx - 10 <= x <= sx + sw + 10 and sy - 10 <= y <= sy + sh + 18:
                return name
        return ""

    def _apply_slider_drag(self, x: int) -> None:
        """Update the volume for the slider currently being dragged."""
        if not self._slider_dragging:
            return
        rect = (self._slider_music_rect if self._slider_dragging == "music"
                else self._slider_sfx_rect)
        sx, _sy, sw, _sh = rect
        frac = max(0.0, min(1.0, (x - sx) / sw))
        if self._slider_dragging == "music":
            audio.music_volume = frac
        else:
            audio.sfx_volume = frac

    def on_mouse_release(self, x: int, y: int) -> None:
        """Release slider drag state."""
        self._slider_dragging = ""

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _btn_at(
        x: int, y: int, rects: list[tuple[int, int, int, int]]
    ) -> int:
        """Return button index at screen coords, or -1."""
        for i, (rx, ry, rw, rh) in enumerate(rects):
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return i
        return -1

    @staticmethod
    def _point_in_rect(
        x: int, y: int, rect: tuple[int, int, int, int]
    ) -> bool:
        rx, ry, rw, rh = rect
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    def _flash_status(self, msg: str) -> None:
        self._status_msg = msg
        self._status_timer = 2.0
