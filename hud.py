"""HUD status panel and mini-map drawing for Space Survivalcraft.

Performance pattern (shared with ``craft_menu`` / ``build_menu`` /
``trade_menu``): the quick-use bar and module slots fill their cell
backgrounds through a pooled ``arcade.SpriteList`` (``_rect_add`` /
``_rect_flush``) so one ``SpriteList.draw()`` replaces ~14 immediate-
mode ``draw_rect_filled`` calls per frame.  Per-slot ``arcade.Text``
pools (``_t_qu_slot_num`` / ``_t_qu_slot_count`` / ``_t_qu_slot_abbrev``
and ``_t_mod_text``) are pre-built in ``__init__``; the draw path
only repositions them and sets text/color when the underlying state
actually changes, which keeps pyglet from rebuilding each label
layout every frame.
"""
from __future__ import annotations


import arcade

from constants import (
    STATUS_WIDTH,
    MINIMAP_H, MINIMAP_Y,
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
        self._t_ability = arcade.Text("ABILITY", 10, hp_y - 88,
                                      (220, 200, 50), 10, bold=True)
        self._t_ability_val = arcade.Text("", 10, hp_y - 116,
                                          arcade.color.WHITE, 9)
        self._t_wpn_name = arcade.Text("WEAPON:", cx, hp_y - 140,
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
            10, hp_y - 170,
            arcade.color.LIGHT_BLUE, 9, bold=True,
        )
        self._t_ship_type = arcade.Text(
            f"{ship_label}",
            STATUS_WIDTH - 10, hp_y - 170,
            arcade.color.LIGHT_GREEN, 9, bold=True,
            anchor_x="right",
        )
        # Position NOW PLAYING + track title immediately above the music
        # video (which draws at MINIMAP_Y + MINIMAP_H + 6 with a 16:9 aspect)
        # so the label stays with the video at any window resolution rather
        # than floating by `hp_y` from the screen top.
        _vid_w = STATUS_WIDTH - 20
        _vid_h = int(_vid_w * 9 / 16)
        _vid_top = MINIMAP_Y + MINIMAP_H + 6 + _vid_h
        self._t_track_name = arcade.Text(
            "", STATUS_WIDTH // 2, _vid_top + 4,
            arcade.color.KHAKI, 9, bold=True, anchor_x="center",
        )
        self._t_music_hdr = arcade.Text(
            "NOW PLAYING", STATUS_WIDTH // 2, _vid_top + 18,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
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
        self._missile_icon: arcade.Texture | None = None  # set by game_view
        self._t_qu_label = arcade.Text("QUICK USE", 0, 0,
                                       arcade.color.LIGHT_GRAY, 8,
                                       anchor_x="center")
        self._t_qu_num = arcade.Text("", 0, 0, arcade.color.WHITE, 8, bold=True,
                                     anchor_x="center", anchor_y="center")
        # Per-slot text pools — pre-built so the draw path doesn't
        # rebuild pyglet labels every frame (each ``.text`` assignment
        # re-runs label layout, which was 30%+ of frame time in a
        # full Zone 2 before this optimization).  Position updates
        # stay cheap because only (x, y) change between frames.
        #   * _t_qu_slot_num[i]   — the "1".."9","0" slot index label
        #   * _t_qu_slot_count[i] — the orange quantity badge
        #   * _t_qu_slot_abbrev[i] — 3-letter fallback when an item
        #     type has no icon (rare but cheap to pre-build)
        self._t_qu_slot_num: list[arcade.Text] = [
            arcade.Text(str((i + 1) % 10), 0, 0, (160, 160, 160), 8,
                        bold=True, anchor_x="center", anchor_y="center")
            for i in range(QUICK_USE_SLOTS)
        ]
        self._t_qu_slot_count: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.ORANGE, 8, bold=True,
                        anchor_x="center", anchor_y="center")
            for _ in range(QUICK_USE_SLOTS)
        ]
        self._t_qu_slot_abbrev: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.YELLOW, 8, bold=True,
                        anchor_x="center", anchor_y="center")
            for _ in range(QUICK_USE_SLOTS)
        ]
        # Quick-use drag state (for moving items between slots)
        self._qu_drag_src: int | None = None
        self._qu_drag_type: str | None = None
        self._qu_drag_count: int = 0
        self._qu_drag_x: float = 0.0
        self._qu_drag_y: float = 0.0

        # Module slot state (slots above quick-use bar — count grows with ship level)
        from constants import MODULE_SLOT_COUNT, MODULE_SLOT_CELL, MODULE_TYPES
        self._mod_base_count = MODULE_SLOT_COUNT
        self._mod_count = MODULE_SLOT_COUNT
        self._mod_cell = MODULE_SLOT_CELL
        self._mod_slots: list[str | None] = [None] * MODULE_SLOT_COUNT
        self._mod_types = MODULE_TYPES
        self._mod_cooldowns: set[str] = set()
        self._mod_flash_t: float = 0.0
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
        self._QU_NAMES: dict[str, str] = {"repair_pack": "Repair Pack", "shield_recharge": "Shield Recharge", "missile": "Homing Missile"}

        # Pooled fill rects for HUD overlays (quick-use bar, module
        # slots).  Mirrors trade_menu's pattern — one SpriteList.draw
        # replaces every per-cell draw_rect_filled.  ~14 GL ops/frame
        # → 1, measured as the hottest overhead on the HUD path.
        self._rect_sprites: arcade.SpriteList = arcade.SpriteList()
        self._rect_slot: int = 0

    def _rect_reset(self) -> None:
        self._rect_slot = 0

    def _rect_add(self, x: float, y: float, w: float, h: float,
                  color: tuple[int, int, int, int]) -> None:
        if self._rect_slot >= len(self._rect_sprites):
            self._rect_sprites.append(arcade.SpriteSolidColor(
                int(w), int(h), 0, 0, color))
        s = self._rect_sprites[self._rect_slot]
        s.width = w
        s.height = h
        s.center_x = x + w / 2
        s.center_y = y + h / 2
        s.color = color
        s.visible = True
        self._rect_slot += 1

    def _rect_flush(self) -> None:
        for i in range(self._rect_slot, len(self._rect_sprites)):
            self._rect_sprites[i].visible = False
        self._rect_sprites.draw()

    @property
    def char_video_rect(self) -> tuple[float, float, float]:
        """Return (x, y, max_w) for drawing the character video in the HUD."""
        return (10, self._char_vid_y - self._char_vid_h, STATUS_WIDTH - 20)

    def set_module_count(self, count: int) -> None:
        """Resize module slot list (e.g. after ship upgrade)."""
        old = self._mod_slots
        self._mod_count = count
        self._mod_slots = [None] * count
        for i in range(min(len(old), count)):
            self._mod_slots[i] = old[i]

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
        """Set a quick-use slot (0-indexed).

        Also refreshes the per-slot count badge + fallback-abbrev
        text objects once here rather than mutating them every frame
        in ``_draw_quick_use_bar``.  Each ``.text`` assignment on a
        pyglet-backed ``arcade.Text`` re-runs label layout — was
        ~30% of a full Zone 2 frame before this pool was added.
        """
        if 0 <= slot < self._qu_count:
            self._qu_slots[slot] = item_type
            self._qu_counts[slot] = count
            # Refresh the per-slot text objects now, not per-frame.
            count_str = str(count) if count > 0 else ""
            if self._t_qu_slot_count[slot].text != count_str:
                self._t_qu_slot_count[slot].text = count_str
            abbrev = (item_type[:3].upper() if item_type else "")
            if self._t_qu_slot_abbrev[slot].text != abbrev:
                self._t_qu_slot_abbrev[slot].text = abbrev

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

    def _draw_stat_bar(
        self, y: int, current: int, maximum: int,
        color: tuple, value_text: arcade.Text,
        x: int = 10, width: int = 190, height: int = 10,
    ) -> None:
        """Draw a single stat bar (HP/shield/ability) at ``y`` with a numerical
        ``current / maximum`` label using the cached ``value_text`` object.
        Caches the formatted string to avoid arcade.Text texture rebuilds."""
        frac = max(0.0, current / maximum) if maximum > 0 else 0.0
        arcade.draw_rect_filled(
            arcade.LBWH(x, y, int(width * frac), height), color)
        label = f"{current} / {maximum}"
        if value_text.text != label:
            value_text.text = label
        value_text.draw()

    def _draw_module_slots(self, play_cx: int, qu_y: int) -> None:
        """Draw the 4 module-equipment slots above the quick-use bar."""
        mod_total_w = self._mod_count * self._mod_cell + (self._mod_count - 1) * 4
        mod_x = play_cx - mod_total_w // 2
        mod_y = qu_y + self._qu_cell + 26
        self._t_mod_label.x = play_cx
        self._t_mod_label.y = mod_y + self._mod_cell + 6
        self._t_mod_label.draw()
        # Flash phase advances each frame; 0.0..1.0 sawtooth at ~3 Hz
        import math as _math
        flash_on = _math.sin(self._mod_flash_t * 6.28 * 3.0) > 0.0
        # Resolve per-slot (fill, outline) once; pool fills into a
        # single SpriteList.draw, then outlines go in a second pass
        # after (outlines stay immediate-mode — one GL op each, ≤4).
        slot_colors: list[tuple[tuple[int, int, int, int],
                                tuple[int, int, int]]] = []
        for i in range(self._mod_count):
            mod = self._mod_slots[i]
            is_drag = (i == self._mod_drag_src)
            cooling = (mod is not None and mod in self._mod_cooldowns)
            if is_drag:
                slot_colors.append(((60, 60, 20, 200), (200, 180, 80)))
            elif cooling and flash_on:
                slot_colors.append(((120, 25, 25, 230), (255, 60, 60)))
            elif mod is not None:
                slot_colors.append(((40, 60, 80, 230), (200, 180, 80)))
            else:
                slot_colors.append(((20, 20, 40, 200), (80, 80, 120)))
        self._rect_reset()
        for i in range(self._mod_count):
            sx = mod_x + i * (self._mod_cell + 4)
            self._rect_add(sx, mod_y, self._mod_cell, self._mod_cell,
                           slot_colors[i][0])
        self._rect_flush()
        for i in range(self._mod_count):
            sx = mod_x + i * (self._mod_cell + 4)
            mod = self._mod_slots[i]
            is_drag = (i == self._mod_drag_src)
            arcade.draw_rect_outline(
                arcade.LBWH(sx, mod_y, self._mod_cell, self._mod_cell),
                slot_colors[i][1], border_width=1)
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
        # Hover tooltip
        if self._mod_hover >= 0 and self._mod_hover < self._mod_count:
            mod = self._mod_slots[self._mod_hover]
            if mod is not None and self._mod_drag_src is None:
                info = self._mod_types.get(mod)
                if info:
                    from ui_helpers import draw_tooltip
                    tip_sx = mod_x + self._mod_hover * (self._mod_cell + 4)
                    draw_tooltip(self._t_mod_tip, info["label"],
                                 tip_sx + self._mod_cell // 2,
                                 mod_y + self._mod_cell + 4,
                                 outline_color=(200, 180, 80))
        # Drag preview
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

    def _resolve_qu_icon(self, item_type: str):
        """Return the quick-use icon texture for an item type, or None."""
        if item_type == "repair_pack" and self._repair_pack_icon is not None:
            return self._repair_pack_icon
        if item_type == "shield_recharge" and self._shield_recharge_icon is not None:
            return self._shield_recharge_icon
        if item_type == "missile" and self._missile_icon is not None:
            return self._missile_icon
        return None

    def _draw_quick_use_bar(self, play_cx: int, qu_y: int) -> None:
        """Draw the 10-slot quick-use consumable bar at the bottom."""
        qu_total_w = self._qu_count * self._qu_cell + (self._qu_count - 1) * 2
        qu_x = play_cx - qu_total_w // 2
        cs = self._qu_cell
        self._t_qu_label.x = play_cx
        self._t_qu_label.y = qu_y + cs + 8
        self._t_qu_label.draw()
        # Use the pre-built per-slot text pools instead of mutating a
        # single shared ``arcade.Text`` N times per frame (each
        # ``.text`` mutation runs pyglet label layout — major hotspot
        # in Zone 2 profiling).
        # Phase 1 — batch every slot's fill through the rect pool so
        # the 10 per-frame draw_rect_filled calls collapse into a
        # single SpriteList.draw().
        self._rect_reset()
        for i in range(self._qu_count):
            sx = qu_x + i * (cs + 2)
            is_drag_src = (i == self._qu_drag_src)
            filled = self._qu_slots[i] is not None and not is_drag_src
            if is_drag_src:
                fill = (60, 60, 20, 200)
            elif filled:
                fill = (50, 70, 50, 220)
            else:
                fill = (25, 25, 50, 200)
            self._rect_add(sx, qu_y, cs, cs, fill)
        self._rect_flush()
        # Phase 2 — outlines + per-slot text + icons.  Outlines stay
        # in immediate mode (one GL op each, 10/frame) since hollow
        # rects aren't sprite-batchable without building 4 edge
        # sprites per cell.
        for i in range(self._qu_count):
            sx = qu_x + i * (cs + 2)
            is_drag_src = (i == self._qu_drag_src)
            arcade.draw_rect_outline(arcade.LBWH(sx, qu_y, cs, cs),
                                     (80, 100, 140), border_width=1)
            # Slot number (never changes text) — just reposition.
            t_num = self._t_qu_slot_num[i]
            t_num.x = sx + cs // 2
            t_num.y = qu_y + cs - 6
            t_num.draw()
            if self._qu_slots[i] is not None and not is_drag_src:
                icon = self._resolve_qu_icon(self._qu_slots[i])
                if icon is not None:
                    icon_pad = 4
                    arcade.draw_texture_rect(
                        icon,
                        arcade.LBWH(sx + icon_pad, qu_y + icon_pad + 2,
                                    cs - icon_pad * 2, cs - icon_pad * 2 - 4))
                else:
                    # Fallback 3-letter abbrev — text pre-set in
                    # ``set_quick_use``; only (x, y) change per frame.
                    t_abbrev = self._t_qu_slot_abbrev[i]
                    t_abbrev.x = sx + cs // 2
                    t_abbrev.y = qu_y + cs // 2 - 2
                    t_abbrev.draw()
                if self._qu_counts[i] > 0:
                    # Count badge — pre-built, only reposition.
                    t_count = self._t_qu_slot_count[i]
                    t_count.x = sx + cs // 2
                    t_count.y = qu_y + 4
                    t_count.draw()
        # Hover tooltip
        if (self._qu_hover >= 0 and self._qu_hover < self._qu_count
                and self._qu_drag_src is None):
            item = self._qu_slots[self._qu_hover]
            if item is not None:
                from ui_helpers import draw_tooltip
                name = self._QU_NAMES.get(item, item)
                tip_sx = qu_x + self._qu_hover * (cs + 2)
                draw_tooltip(self._t_qu_tip, name,
                             tip_sx + cs // 2, qu_y + cs + 4,
                             outline_color=arcade.color.LIGHT_GRAY)
        # Drag preview
        if self._qu_drag_src is not None and self._qu_drag_type is not None:
            fx = self._qu_drag_x - cs // 2
            fy = self._qu_drag_y - cs // 2
            arcade.draw_rect_filled(arcade.LBWH(fx, fy, cs, cs), (70, 90, 40, 180))
            arcade.draw_rect_outline(arcade.LBWH(fx, fy, cs, cs),
                                     arcade.color.YELLOW, border_width=2)
            icon = self._resolve_qu_icon(self._qu_drag_type)
            if icon is not None:
                icon_pad = 4
                arcade.draw_texture_rect(
                    icon,
                    arcade.LBWH(fx + icon_pad, fy + icon_pad + 2,
                                cs - icon_pad * 2, cs - icon_pad * 2 - 4),
                    alpha=200)
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
        extra_boss_positions: list[tuple[float, float]] | None = None,
        wormhole_positions: list[tuple[float, float]] | None = None,
        zone_width: float = 6400,
        zone_height: float = 6400,
        ability_meter: float = 0.0,
        ability_meter_max: float = 100.0,
        gas_positions: list[tuple[float, float, float]] | None = None,
        gas_always_visible: bool = False,
        parked_ship_positions: list[tuple[float, float]] | None = None,
        null_field_positions: list[tuple[float, float, float, bool]] | None = None,
        slipspace_positions: list[tuple[float, float]] | None = None,
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
            if self._t_char_name.text != character_name:
                self._t_char_name.text = character_name
            self._t_char_name.draw()

        hp_y = self._hp_y_offset
        self._t_hp.draw()
        self._t_shield.draw()
        if self._show_fps:
            self._t_fps.text = f"FPS  {self._fps:>6.1f}"
            self._t_fps.draw()

        wpn_label = f"WEAPON: {weapon_name}"
        if self._t_wpn_name.text != wpn_label:
            self._t_wpn_name.text = wpn_label
        self._t_wpn_name.draw()

        # HP bar (colour shifts red as HP drops)
        hp_color = (
            (0, 180, 0) if (max_hp > 0 and hp / max_hp > 0.5)
            else (220, 140, 0) if (max_hp > 0 and hp / max_hp > 0.25)
            else (200, 30, 30)
        )
        self._draw_stat_bar(hp_y - 16, hp, max_hp, hp_color, self._t_hp_val)

        # Shield bar
        self._draw_stat_bar(hp_y - 60, shields, max_shields,
                            (0, 140, 210), self._t_shield_val)

        # Ability meter bar (yellow)
        if ability_meter_max > 0:
            self._t_ability.draw()
            self._draw_stat_bar(hp_y - 104, int(ability_meter),
                                int(ability_meter_max),
                                (220, 200, 50), self._t_ability_val)

        self._t_faction.draw()
        self._t_ship_type.draw()

        # Now-playing track name
        if track_name:
            self._t_music_hdr.draw()
            if self._t_track_name.text != track_name:
                self._t_track_name.text = track_name
            self._t_track_name.draw()

        # Equalizer visualizer (only when music is playing, not video)
        if track_name and not video_active:
            eq_y = self._hp_y_offset - 218 - EQ_MAX_H
            self._eq.draw(eq_y)

        # Bottom-centre UI bars
        win = arcade.get_window()
        play_cx = STATUS_WIDTH + (win.width - STATUS_WIDTH) // 2
        qu_y = 10
        self._draw_module_slots(play_cx, qu_y)
        self._draw_quick_use_bar(play_cx, qu_y)

        draw_minimap(
            self._t_minimap,
            asteroid_list, iron_pickup_list, alien_list,
            player_x, player_y, player_heading,
            building_list=building_list,
            fog_grid=fog_grid,
            fog_revealed=fog_revealed,
            trade_station_pos=trade_station_pos,
            boss_pos=boss_pos,
            extra_boss_positions=extra_boss_positions,
            wormhole_positions=wormhole_positions,
            zone_width=zone_width,
            zone_height=zone_height,
            gas_positions=gas_positions,
            gas_always_visible=gas_always_visible,
            parked_ship_positions=parked_ship_positions,
            null_field_positions=null_field_positions,
            slipspace_positions=slipspace_positions,
        )
