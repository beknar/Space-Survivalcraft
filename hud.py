"""HUD status panel and mini-map drawing for Space Survivalcraft."""
from __future__ import annotations

import math
import random

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT, STATUS_WIDTH,
    WORLD_WIDTH, WORLD_HEIGHT,
    MINIMAP_PAD, MINIMAP_W, MINIMAP_H, MINIMAP_X, MINIMAP_Y,
    FOG_CELL_SIZE, FOG_GRID_W, FOG_GRID_H,
)
from hud_equalizer import EqualizerState, EQ_MAX_H
from hud_minimap import draw_minimap


class HUD:
    """Left-side status panel with stats, weapon display, controls, and mini-map."""

    def __init__(
        self,
        has_gamepad: bool = False,
        faction: str | None = None,
        ship_type: str | None = None,
        repair_pack_icon: arcade.Texture | None = None,
        shield_recharge_icon: arcade.Texture | None = None,
    ) -> None:
        # Store the current screen height so draw() uses the right value
        # (SCREEN_HEIGHT gets updated at runtime by apply_resolution, but
        #  the local import binding would be stale)
        self._sh = arcade.get_window().height
        cx = STATUS_WIDTH // 2
        self._t_title = arcade.Text(
            "STATUS", cx, self._sh - 26,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )

        # Character video area (replaces old IRON/ROIDS/ALIEN stats)
        # Video is drawn externally; we just reserve layout space + name label
        self._char_vid_y = self._sh - 44  # top of video area (close to STATUS title)
        self._char_vid_h = STATUS_WIDTH - 20  # 1:1 square aspect
        self._t_char_name = arcade.Text(
            "", cx, self._char_vid_y - self._char_vid_h - 10,
            arcade.color.KHAKI, 10, bold=True,
            anchor_x="center", anchor_y="top",
        )

        # HP header starts below character video + name
        self._hp_y_offset = self._char_vid_y - self._char_vid_h - 30
        self._t_hp = arcade.Text("HP", 10, self._hp_y_offset,
                                 arcade.color.LIME_GREEN, 10, bold=True)
        hp_y = self._hp_y_offset
        self._t_hp_val = arcade.Text("", 10, hp_y - 28,
                                     arcade.color.WHITE, 9)
        self._t_shield = arcade.Text("SHIELD", 10, hp_y - 44,
                                     arcade.color.CYAN, 10, bold=True)
        self._t_shield_val = arcade.Text("", 10, hp_y - 72,
                                         arcade.color.WHITE, 9)
        self._t_wpn_hdr = arcade.Text("WEAPON", cx, hp_y - 90,
                                      arcade.color.LIGHT_GRAY, 9,
                                      anchor_x="center")
        self._t_wpn_name = arcade.Text("", cx, hp_y - 106,
                                       arcade.color.YELLOW, 10, bold=True,
                                       anchor_x="center")
        self._show_fps: bool = False
        self._fps: float = 60.0
        self._t_fps = arcade.Text("", STATUS_WIDTH - 10, self._sh - 26,
                                  arcade.color.YELLOW, 9, bold=True,
                                  anchor_x="right", anchor_y="center")
        self._t_minimap = arcade.Text(
            "MINI-MAP", STATUS_WIDTH // 2,
            MINIMAP_Y + MINIMAP_H + 3,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
        )

        faction_label = faction if faction else "Legacy"
        ship_label = ship_type if ship_type else "Classic"
        self._t_faction = arcade.Text(
            f"{faction_label}",
            10, hp_y - 126,
            arcade.color.LIGHT_BLUE, 9, bold=True,
        )
        self._t_ship_type = arcade.Text(
            f"{ship_label}",
            STATUS_WIDTH - 10, hp_y - 126,
            arcade.color.LIGHT_GREEN, 9, bold=True,
            anchor_x="right",
        )
        self._t_music_hdr = arcade.Text(
            "NOW PLAYING", STATUS_WIDTH // 2, hp_y - 146,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
        )
        self._t_track_name = arcade.Text(
            "", STATUS_WIDTH // 2, hp_y - 162,
            arcade.color.KHAKI, 9, bold=True, anchor_x="center",
        )

        # Equalizer visualizer state (extracted to hud_equalizer.py)
        self._eq = EqualizerState()

        # Quick-use bar state (5 slots, each holds item_type or None)
        from constants import QUICK_USE_SLOTS, QUICK_USE_CELL
        self._qu_slots: list[str | None] = [None] * QUICK_USE_SLOTS
        self._qu_counts: list[int] = [0] * QUICK_USE_SLOTS
        self._qu_cell = QUICK_USE_CELL
        self._qu_count = QUICK_USE_SLOTS
        self._repair_pack_icon = repair_pack_icon
        self._shield_recharge_icon = shield_recharge_icon
        self._t_qu_label = arcade.Text("QUICK USE", 0, 0,
                                       arcade.color.LIGHT_GRAY, 8,
                                       anchor_x="center")
        self._t_qu_num = arcade.Text("", 0, 0, arcade.color.WHITE, 8, bold=True,
                                     anchor_x="center", anchor_y="center")

        # Quick-use drag state (for moving items between slots)
        self._qu_drag_src: int | None = None
        self._qu_drag_type: str | None = None
        self._qu_drag_count: int = 0
        self._qu_drag_x: float = 0.0
        self._qu_drag_y: float = 0.0

        # Module slot state (4 slots above quick-use bar)
        from constants import MODULE_SLOT_COUNT, MODULE_SLOT_CELL, MODULE_TYPES
        self._mod_count = MODULE_SLOT_COUNT
        self._mod_cell = MODULE_SLOT_CELL
        self._mod_slots: list[str | None] = [None] * MODULE_SLOT_COUNT
        self._mod_types = MODULE_TYPES
        self._t_mod_label = arcade.Text("MODULES", 0, 0,
                                        arcade.color.LIGHT_GRAY, 8,
                                        anchor_x="center")
        self._t_mod_text = arcade.Text("", 0, 0, arcade.color.WHITE, 7,
                                       bold=True,
                                       anchor_x="center", anchor_y="center")
        # Module short labels (3-char abbreviations)
        self._MOD_ABBR = {
            "armor_plate": "ARM",
            "engine_booster": "ENG",
            "shield_booster": "SHD",
            "shield_enhancer": "REG",
            "damage_absorber": "ABS",
            "broadside": "BRD",
        }
        # Module icon textures (set by game_view)
        self._mod_icons: dict[str, arcade.Texture] = {}
        # Module hover tooltip
        self._mod_hover: int = -1
        self._t_mod_tip = arcade.Text("", 0, 0, arcade.color.WHITE, 9, bold=True,
                                      anchor_x="center", anchor_y="center")
        # Module drag state
        self._mod_drag_src: int | None = None
        self._mod_drag_type: str | None = None
        self._mod_drag_x: float = 0.0
        self._mod_drag_y: float = 0.0
        # Quick-use hover tooltip
        self._qu_hover: int = -1
        self._t_qu_tip = arcade.Text("", 0, 0, arcade.color.WHITE, 9, bold=True,
                                     anchor_x="center", anchor_y="center")
        self._QU_NAMES: dict[str, str] = {"repair_pack": "Repair Pack", "shield_recharge": "Shield Recharge"}

    @property
    def char_video_rect(self) -> tuple[float, float, float]:
        """Return (x, y, max_w) for drawing the character video in the HUD."""
        return (10, self._char_vid_y - self._char_vid_h, STATUS_WIDTH - 20)

    def set_module_slot(self, slot: int, mod_type: str | None) -> None:
        if 0 <= slot < self._mod_count:
            self._mod_slots[slot] = mod_type

    def get_module_slot(self, slot: int) -> str | None:
        if 0 <= slot < self._mod_count:
            return self._mod_slots[slot]
        return None

    def module_slot_at(self, x: float, y: float) -> int | None:
        """Return module slot index at screen coords, or None."""
        win = arcade.get_window()
        mod_total_w = self._mod_count * self._mod_cell + (self._mod_count - 1) * 4
        play_cx = STATUS_WIDTH + (win.width - STATUS_WIDTH) // 2
        mod_x = play_cx - mod_total_w // 2
        qu_total_w = self._qu_count * self._qu_cell + (self._qu_count - 1) * 2
        qu_y = 10
        mod_y = qu_y + self._qu_cell + 26
        if y < mod_y or y > mod_y + self._mod_cell:
            return None
        for i in range(self._mod_count):
            sx = mod_x + i * (self._mod_cell + 4)
            if sx <= x <= sx + self._mod_cell:
                return i
        return None

    def set_quick_use(self, slot: int, item_type: str | None, count: int = 0) -> None:
        """Set a quick-use slot (0-indexed)."""
        if 0 <= slot < self._qu_count:
            self._qu_slots[slot] = item_type
            self._qu_counts[slot] = count

    def get_quick_use(self, slot: int) -> str | None:
        """Get the item type in a quick-use slot (0-indexed)."""
        if 0 <= slot < self._qu_count:
            return self._qu_slots[slot]
        return None

    def slot_at(self, x: float, y: float) -> int | None:
        """Return quick-use slot index (0-based) at screen coords, or None."""
        win = arcade.get_window()
        qu_total_w = self._qu_count * self._qu_cell + (self._qu_count - 1) * 2
        play_cx = STATUS_WIDTH + (win.width - STATUS_WIDTH) // 2
        qu_x = play_cx - qu_total_w // 2
        qu_y = 10
        if y < qu_y or y > qu_y + self._qu_cell:
            return None
        for i in range(self._qu_count):
            sx = qu_x + i * (self._qu_cell + 2)
            if sx <= x <= sx + self._qu_cell:
                return i
        return None

    def toggle_fps(self) -> None:
        self._show_fps = not self._show_fps

    @property
    def show_fps(self) -> bool:
        return self._show_fps

    def update_fps(self, delta_time: float) -> None:
        if delta_time > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / delta_time)
        from settings import audio
        self._eq.update(delta_time, audio.music_volume)

    def draw(
        self,
        weapon_name: str,
        hp: int,
        max_hp: int,
        shields: int,
        max_shields: int,
        asteroid_list: arcade.SpriteList,
        iron_pickup_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
        player_x: float,
        player_y: float,
        player_heading: float,
        track_name: str = "",
        building_list: arcade.SpriteList | None = None,
        fog_grid: list[list[bool]] | None = None,
        fog_revealed: int = 0,
        video_active: bool = False,
        character_name: str = "",
        trade_station_pos: tuple[float, float] | None = None,
        boss_pos: tuple[float, float] | None = None,
        wormhole_positions: list[tuple[float, float]] | None = None,
        zone_width: float = 6400,
        zone_height: float = 6400,
    ) -> None:
        """Draw the full HUD status panel."""
        # Panel background
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, STATUS_WIDTH, self._sh),
            (15, 15, 40, 235),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(0, 0, STATUS_WIDTH, self._sh),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        self._t_title.draw()

        # Character name label below video area
        if character_name:
            self._t_char_name.text = character_name
            self._t_char_name.draw()

        hp_y = self._hp_y_offset
        self._t_hp.draw()
        self._t_shield.draw()
        self._t_wpn_hdr.draw()
        if self._show_fps:
            self._t_fps.text = f"FPS  {self._fps:>6.1f}"
            self._t_fps.draw()

        self._t_wpn_name.text = weapon_name
        self._t_wpn_name.draw()

        # HP bar
        hp_frac = max(0.0, hp / max_hp) if max_hp > 0 else 0.0
        hp_color = (
            (0, 180, 0) if hp_frac > 0.5
            else (220, 140, 0) if hp_frac > 0.25
            else (200, 30, 30)
        )
        arcade.draw_rect_filled(
            arcade.LBWH(10, hp_y - 16, int(190 * hp_frac), 10),
            hp_color,
        )
        # HP numerical value
        self._t_hp_val.text = f"{hp} / {max_hp}"
        self._t_hp_val.draw()

        # Shield bar
        shield_frac = max(0.0, shields / max_shields) if max_shields > 0 else 0.0
        arcade.draw_rect_filled(
            arcade.LBWH(10, hp_y - 60, int(190 * shield_frac), 10),
            (0, 140, 210),
        )
        # Shield numerical value
        self._t_shield_val.text = f"{shields} / {max_shields}"
        self._t_shield_val.draw()

        self._t_faction.draw()
        self._t_ship_type.draw()

        # Now-playing track name
        if track_name:
            self._t_music_hdr.draw()
            self._t_track_name.text = track_name
            self._t_track_name.draw()

        # Equalizer visualizer (only when music is playing, not video)
        if track_name and not video_active:
            eq_y = self._hp_y_offset - 174 - EQ_MAX_H
            self._eq.draw(eq_y)

        # Quick-use bar (10 slots labeled 1–9, 0) — bottom-centre of screen
        win = arcade.get_window()
        play_cx = STATUS_WIDTH + (win.width - STATUS_WIDTH) // 2
        qu_total_w = self._qu_count * self._qu_cell + (self._qu_count - 1) * 2
        qu_x = play_cx - qu_total_w // 2
        qu_y = 10

        # Module slots (4 boxes above quick-use bar)
        mod_total_w = self._mod_count * self._mod_cell + (self._mod_count - 1) * 4
        mod_x = play_cx - mod_total_w // 2
        mod_y = qu_y + self._qu_cell + 26
        self._t_mod_label.x = play_cx
        self._t_mod_label.y = mod_y + self._mod_cell + 6
        self._t_mod_label.draw()
        for i in range(self._mod_count):
            sx = mod_x + i * (self._mod_cell + 4)
            mod = self._mod_slots[i]
            is_drag = (i == self._mod_drag_src)
            if is_drag:
                fill = (60, 60, 20, 200)
                outline = (200, 180, 80)
            elif mod is not None:
                fill = (40, 60, 80, 230)
                outline = (200, 180, 80)
            else:
                fill = (20, 20, 40, 200)
                outline = (80, 80, 120)
            arcade.draw_rect_filled(
                arcade.LBWH(sx, mod_y, self._mod_cell, self._mod_cell), fill)
            arcade.draw_rect_outline(
                arcade.LBWH(sx, mod_y, self._mod_cell, self._mod_cell),
                outline, border_width=1)
            if mod is not None and not is_drag:
                icon = self._mod_icons.get(mod)
                if icon:
                    pad = 4
                    arcade.draw_texture_rect(
                        icon,
                        arcade.LBWH(sx + pad, mod_y + pad,
                                    self._mod_cell - pad * 2, self._mod_cell - pad * 2))
                else:
                    abbr = self._MOD_ABBR.get(mod, mod[:3].upper())
                    self._t_mod_text.text = abbr
                    self._t_mod_text.x = sx + self._mod_cell // 2
                    self._t_mod_text.y = mod_y + self._mod_cell // 2
                    self._t_mod_text.color = (200, 180, 80)
                    self._t_mod_text.draw()

        # Module hover tooltip
        if self._mod_hover >= 0 and self._mod_hover < self._mod_count:
            mod = self._mod_slots[self._mod_hover]
            if mod is not None and self._mod_drag_src is None:
                info = self._mod_types.get(mod)
                if info:
                    tip_sx = mod_x + self._mod_hover * (self._mod_cell + 4)
                    tip_cx = tip_sx + self._mod_cell // 2
                    tip_y = mod_y + self._mod_cell + 4
                    self._t_mod_tip.text = info["label"]
                    tw = len(info["label"]) * 7 + 12
                    tx0 = max(2, tip_cx - tw // 2)
                    arcade.draw_rect_filled(arcade.LBWH(tx0, tip_y, tw, 16),
                                            (20, 20, 50, 230))
                    arcade.draw_rect_outline(arcade.LBWH(tx0, tip_y, tw, 16),
                                             (200, 180, 80), border_width=1)
                    self._t_mod_tip.x = tx0 + tw // 2
                    self._t_mod_tip.y = tip_y + 8
                    self._t_mod_tip.draw()

        # Module drag preview
        if self._mod_drag_src is not None and self._mod_drag_type is not None:
            cs = self._mod_cell
            fx = self._mod_drag_x - cs // 2
            fy = self._mod_drag_y - cs // 2
            arcade.draw_rect_filled(arcade.LBWH(fx, fy, cs, cs), (70, 90, 40, 180))
            arcade.draw_rect_outline(arcade.LBWH(fx, fy, cs, cs),
                                     (200, 180, 80), border_width=2)
            icon = self._mod_icons.get(self._mod_drag_type)
            if icon:
                pad = 4
                arcade.draw_texture_rect(icon,
                    arcade.LBWH(fx + pad, fy + pad, cs - pad * 2, cs - pad * 2),
                    alpha=200)

        self._t_qu_label.x = play_cx
        self._t_qu_label.y = qu_y + self._qu_cell + 8
        self._t_qu_label.draw()
        for i in range(self._qu_count):
            sx = qu_x + i * (self._qu_cell + 2)
            is_drag_src = (i == self._qu_drag_src)
            filled = self._qu_slots[i] is not None and not is_drag_src
            if is_drag_src:
                fill = (60, 60, 20, 200)
            elif filled:
                fill = (50, 70, 50, 220)
            else:
                fill = (25, 25, 50, 200)
            arcade.draw_rect_filled(
                arcade.LBWH(sx, qu_y, self._qu_cell, self._qu_cell), fill,
            )
            arcade.draw_rect_outline(
                arcade.LBWH(sx, qu_y, self._qu_cell, self._qu_cell),
                (80, 100, 140), border_width=1,
            )
            # Slot number (1-9, then 0 for slot 10)
            self._t_qu_num.text = str((i + 1) % 10)
            self._t_qu_num.x = sx + self._qu_cell // 2
            self._t_qu_num.y = qu_y + self._qu_cell - 6
            self._t_qu_num.color = (160, 160, 160)
            self._t_qu_num.draw()
            # Item icon/label (skip source slot during drag)
            if self._qu_slots[i] is not None and not is_drag_src:
                icon = None
                if self._qu_slots[i] == "repair_pack" and self._repair_pack_icon is not None:
                    icon = self._repair_pack_icon
                elif self._qu_slots[i] == "shield_recharge" and self._shield_recharge_icon is not None:
                    icon = self._shield_recharge_icon
                if icon is not None:
                    icon_pad = 4
                    icon_size = self._qu_cell - icon_pad * 2
                    arcade.draw_texture_rect(
                        icon,
                        arcade.LBWH(sx + icon_pad, qu_y + icon_pad + 2,
                                    icon_size, icon_size - 4),
                    )
                else:
                    self._t_qu_num.text = self._qu_slots[i][:3].upper()
                    self._t_qu_num.y = qu_y + self._qu_cell // 2 - 2
                    self._t_qu_num.color = arcade.color.YELLOW
                    self._t_qu_num.draw()
                if self._qu_counts[i] > 0:
                    self._t_qu_num.text = str(self._qu_counts[i])
                    self._t_qu_num.x = sx + self._qu_cell // 2
                    self._t_qu_num.y = qu_y + 4
                    self._t_qu_num.color = arcade.color.ORANGE
                    self._t_qu_num.draw()

        # Quick-use hover tooltip
        if (self._qu_hover >= 0 and self._qu_hover < self._qu_count
                and self._qu_drag_src is None):
            item = self._qu_slots[self._qu_hover]
            if item is not None:
                name = self._QU_NAMES.get(item, item)
                tip_sx = qu_x + self._qu_hover * (self._qu_cell + 2)
                tip_cx = tip_sx + self._qu_cell // 2
                tip_y = qu_y + self._qu_cell + 4
                self._t_qu_tip.text = name
                tw = len(name) * 7 + 12
                tx0 = max(2, tip_cx - tw // 2)
                arcade.draw_rect_filled(arcade.LBWH(tx0, tip_y, tw, 16),
                                        (20, 20, 50, 230))
                arcade.draw_rect_outline(arcade.LBWH(tx0, tip_y, tw, 16),
                                         arcade.color.LIGHT_GRAY, border_width=1)
                self._t_qu_tip.x = tx0 + tw // 2
                self._t_qu_tip.y = tip_y + 8
                self._t_qu_tip.draw()

        # Floating drag preview for quick-use
        if self._qu_drag_src is not None and self._qu_drag_type is not None:
            cs = self._qu_cell
            fx = self._qu_drag_x - cs // 2
            fy = self._qu_drag_y - cs // 2
            arcade.draw_rect_filled(
                arcade.LBWH(fx, fy, cs, cs), (70, 90, 40, 180),
            )
            arcade.draw_rect_outline(
                arcade.LBWH(fx, fy, cs, cs),
                arcade.color.YELLOW, border_width=2,
            )
            icon = None
            if self._qu_drag_type == "repair_pack" and self._repair_pack_icon is not None:
                icon = self._repair_pack_icon
            elif self._qu_drag_type == "shield_recharge" and self._shield_recharge_icon is not None:
                icon = self._shield_recharge_icon
            if icon is not None:
                icon_pad = 4
                icon_size = cs - icon_pad * 2
                arcade.draw_texture_rect(
                    icon,
                    arcade.LBWH(fx + icon_pad, fy + icon_pad + 2,
                                icon_size, icon_size - 4),
                    alpha=200,
                )
            else:
                self._t_qu_num.text = self._qu_drag_type[:3].upper()
                self._t_qu_num.x = fx + cs // 2
                self._t_qu_num.y = fy + cs // 2 - 2
                self._t_qu_num.color = arcade.color.YELLOW
                self._t_qu_num.draw()
            if self._qu_drag_count > 0:
                self._t_qu_num.text = str(self._qu_drag_count)
                self._t_qu_num.x = fx + cs // 2
                self._t_qu_num.y = fy + 4
                self._t_qu_num.color = arcade.color.ORANGE
                self._t_qu_num.draw()

        draw_minimap(
            self._t_minimap,
            asteroid_list, iron_pickup_list, alien_list,
            player_x, player_y, player_heading,
            building_list=building_list,
            fog_grid=fog_grid,
            fog_revealed=fog_revealed,
            trade_station_pos=trade_station_pos,
            boss_pos=boss_pos,
            wormhole_positions=wormhole_positions,
            zone_width=zone_width,
            zone_height=zone_height,
        )
