"""Craft menu overlay for the Basic Crafter module."""
from __future__ import annotations

from typing import Optional

import arcade

from menu_overlay import MenuOverlay
from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    CRAFT_TIME, CRAFT_IRON_COST, CRAFT_RESULT_COUNT,
    MODULE_TYPES,
)

_PANEL_W = 300
_PANEL_H_MIN = 280
# Cap so the Advanced Crafter doesn't overflow the screen once many
# blueprints are unlocked.  The recipe list scrolls when total height
# exceeds this minus chrome (header + detail + button area).
_PANEL_H_MAX = 560
_RECIPE_H = 28     # single-line recipe row height
_RECIPE_H2 = 42    # two-line recipe row height
_ICON_AREA = 28    # icon column width
_SCROLL_W = 10     # scrollbar track width
_SCROLL_THUMB_MIN_H = 22
_TEXT_W = _PANEL_W - 20 - _ICON_AREA  # available text width (panel - padding - icon)
_HEADER = 55   # title area
_DETAIL = 40   # detail text + padding
_BTN_AREA = 80 # craft button + progress bar + close text



class CraftMenu(MenuOverlay):
    """Overlay for the Basic Crafter — shows Repair Pack recipe + unlocked module recipes."""

    _title_text = "BASIC CRAFTER"
    _close_text = "ESC / click outside to close"

    def __init__(self) -> None:
        super().__init__()
        self._crafting: bool = False
        self._progress: float = 0.0
        self._craft_target: str = ""  # "" = repair pack, "shield_recharge", or module key
        self._is_advanced: bool = False

        # Available module recipes
        self._recipes: list[dict] = []
        self._unlocked: set[str] = set()  # permanently unlocked module keys
        self._scroll_px: float = 0.0     # pixel offset into the recipe list
        self._dragging_scrollbar: bool = False
        self._drag_anchor_y: float = 0.0
        self._drag_anchor_scroll: float = 0.0
        self._selected: int = 0  # 0 = repair pack, 1+ = module recipes

        # Pre-built recipe text objects (avoid .text churn per frame)
        self._t_recipes: list[arcade.Text] = []
        self._t_detail = arcade.Text("", 0, 0, arcade.color.LIME_GREEN, 9)
        self._last_pct: int = -1  # cached progress percentage
        self._t_btn.text = "CRAFT"
        self._t_btn.font_size = 12
        self._t_status = arcade.Text("", 0, 0, arcade.color.YELLOW, 10,
                                     bold=True, anchor_x="center")
        # Item icons (set by game_view)
        self.item_icons: dict[str, arcade.Texture] = {}
        self.repair_pack_icon: Optional[arcade.Texture] = None
        self.shield_recharge_icon: Optional[arcade.Texture] = None

    def refresh_recipes(self, station_inv, is_advanced: bool = False) -> None:
        """Scan station inventory for blueprints and build recipe list.

        Once a blueprint is deposited, the recipe is permanently unlocked.
        ``is_advanced`` gates recipes flagged ``"advanced": True``.
        """
        self._is_advanced = is_advanced
        title = "ADVANCED CRAFTER" if is_advanced else "BASIC CRAFTER"
        if self._t_title.text != title:
            self._t_title.text = title
        # Unlock any new blueprints found in station inv
        for key in MODULE_TYPES:
            if station_inv.count_item(f"bp_{key}") > 0:
                self._unlocked.add(key)
        # Build recipe list from all unlocked modules
        self._recipes = []
        for key in MODULE_TYPES:
            if key in self._unlocked:
                info = MODULE_TYPES[key]
                if info.get("advanced") and not is_advanced:
                    continue
                self._recipes.append({
                    "key": key,
                    "label": info["label"],
                    "cost": info["craft_cost"],
                    "cost_copper": info.get("craft_cost_copper", 0),
                })
        self._selected = 0
        self._scroll_px = 0.0
        self._dragging_scrollbar = False
        # Pre-build recipe text objects (index 0 = repair pack, 1 = shield recharge, then modules)
        self._t_recipes = []
        self._recipe_heights: list[int] = []  # per-row pixel height

        def _add_recipe_text(text: str) -> None:
            t = arcade.Text(text, 0, 0, arcade.color.WHITE, 9,
                            width=_TEXT_W, multiline=True)
            self._t_recipes.append(t)
            # Estimate lines: if content_width > available width, 2 lines
            h = _RECIPE_H2 if len(text) * 5.4 > _TEXT_W else _RECIPE_H
            self._recipe_heights.append(h)

        _add_recipe_text(f"Repair Pack x{CRAFT_RESULT_COUNT}  —  {CRAFT_IRON_COST} iron")
        _add_recipe_text(f"Shield Recharge x{CRAFT_RESULT_COUNT}  —  {CRAFT_IRON_COST} iron")

        for recipe in self._recipes:
            info = MODULE_TYPES[recipe["key"]]
            if info.get("blueprint_only"):
                from constants import BUILDING_TYPES
                bld = BUILDING_TYPES.get("Advanced Crafter", {})
                b_iron = bld.get("cost", 0)
                b_copper = bld.get("cost_copper", 0)
                cost_text = f"Unlocks building\n({b_iron} iron + {b_copper} copper)"
            else:
                cost_text = f"{recipe['cost']} iron"
                if recipe.get("cost_copper", 0) > 0:
                    cost_text += f" + {recipe['cost_copper']} copper"
            _add_recipe_text(f"{recipe['label']}  —  {cost_text}")
        # Pre-build detail text
        self._t_detail.text = f"Produces {CRAFT_RESULT_COUNT}x Repair Pack ({int(CRAFT_TIME)}s)"

    def toggle(self) -> None:
        self.open = not self.open

    def _panel_height(self) -> int:
        list_h = sum(self._recipe_heights) if self._recipe_heights else 2 * _RECIPE_H
        wanted = _HEADER + list_h + _DETAIL + _BTN_AREA
        return max(_PANEL_H_MIN, min(_PANEL_H_MAX, wanted))

    # ── Scroll geometry ───────────────────────────────────────────────────────

    def _list_viewport_h(self) -> int:
        """Height of the recipe-list viewport (between header and detail)."""
        ph = self._panel_height()
        return max(_RECIPE_H, ph - _HEADER - _DETAIL - _BTN_AREA)

    def _content_h(self) -> int:
        return sum(self._recipe_heights) if self._recipe_heights else 0

    def _max_scroll(self) -> float:
        return max(0.0, self._content_h() - self._list_viewport_h())

    def _needs_scrollbar(self) -> bool:
        return self._content_h() > self._list_viewport_h()

    def _clamp_scroll(self) -> None:
        self._scroll_px = max(0.0, min(self._max_scroll(), self._scroll_px))

    def _scrollbar_rect(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) for the scrollbar TRACK."""
        px, py = self._panel_origin()
        ph = self._panel_height()
        track_h = self._list_viewport_h()
        track_y = py + ph - _HEADER - track_h
        track_x = px + _PANEL_W - 10 - _SCROLL_W
        return track_x, track_y, _SCROLL_W, track_h

    def _scrollbar_thumb_rect(self) -> tuple[int, int, int, int]:
        tx, ty, tw, th = self._scrollbar_rect()
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return tx, ty, tw, th
        ratio = th / (th + max_scroll)
        thumb_h = max(_SCROLL_THUMB_MIN_H, int(th * ratio))
        thumb_y = ty + th - thumb_h - int(
            (th - thumb_h) * (self._scroll_px / max_scroll))
        return tx, thumb_y, tw, thumb_h

    def on_mouse_scroll(self, scroll_y: float) -> None:
        """Mouse-wheel scrolls the recipe list one row per click.
        No-op if the list fits in the panel."""
        if not self.open or not self._needs_scrollbar():
            return
        self._scroll_px -= scroll_y * _RECIPE_H
        self._clamp_scroll()

    def on_mouse_release(self, x: float, y: float) -> None:
        """Drop scrollbar drag on mouse-up."""
        self._dragging_scrollbar = False

    def _set_scroll_from_drag(self, mouse_y: float) -> None:
        tx, ty, tw, th = self._scrollbar_rect()
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return
        delta = self._drag_anchor_y - mouse_y
        ratio = th / (th + max_scroll)
        thumb_h = max(_SCROLL_THUMB_MIN_H, int(th * ratio))
        movable = max(1, th - thumb_h)
        self._scroll_px = (self._drag_anchor_scroll
                           + (delta / movable) * max_scroll)
        self._clamp_scroll()

    def on_mouse_motion(self, x: float, y: float) -> None:
        """Drag-scroll while the scrollbar thumb is held."""
        if self._dragging_scrollbar:
            self._set_scroll_from_drag(y)

    def _handle_scrollbar_press(self, x: float, y: float) -> bool:
        if not self._needs_scrollbar():
            return False
        tx, ty, tw, th = self._scrollbar_rect()
        if not (tx <= x <= tx + tw and ty <= y <= ty + th):
            return False
        thx, thy, thw, thh = self._scrollbar_thumb_rect()
        if thy <= y <= thy + thh:
            self._dragging_scrollbar = True
            self._drag_anchor_y = y
            self._drag_anchor_scroll = self._scroll_px
            return True
        # Click above thumb → page up; below → page down.
        page = max(_RECIPE_H, self._list_viewport_h() - _RECIPE_H)
        if y > thy + thh:
            self._scroll_px -= page
        else:
            self._scroll_px += page
        self._clamp_scroll()
        return True

    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        ph = self._panel_height()
        return (sw - _PANEL_W) // 2, (sh - ph) // 2

    def _craft_btn_rect(self) -> tuple[int, int, int, int]:
        px, py = self._panel_origin()
        bw, bh = 140, 32
        bx = px + (_PANEL_W - bw) // 2
        by = py + 40
        return bx, by, bw, bh

    def on_mouse_press(self, x: float, y: float, station_iron: int) -> Optional[str]:
        """Returns 'craft' or 'craft_module:key' if craft button clicked, None otherwise."""
        if not self.open:
            return None
        px, py = self._panel_origin()
        ph = self._panel_height()
        if not (px <= x <= px + _PANEL_W and py <= y <= py + ph):
            self.open = False
            return None

        # Scrollbar takes priority — never falls through to a row.
        if self._handle_scrollbar_press(x, y):
            return None

        # Recipe list clicks (0=repair pack, 1=shield recharge, 2+=modules)
        # Coordinates honour the scroll offset so clicks on visible rows
        # map to the right recipe even when the list is scrolled down.
        top_y = py + ph - _HEADER + int(self._scroll_px)
        view_top = py + ph - _HEADER
        view_bottom = view_top - self._list_viewport_h()
        # Reserve scrollbar gutter from the row hitbox when present.
        right = px + _PANEL_W - 10
        if self._needs_scrollbar():
            right -= (_SCROLL_W + 4)
        cum_y = 0
        for i in range(len(self._t_recipes)):
            rh = self._recipe_heights[i] if i < len(self._recipe_heights) else _RECIPE_H
            ry = top_y - cum_y - rh
            cum_y += rh
            # Skip rows scrolled out of view.
            if ry + rh < view_bottom or ry > view_top:
                continue
            if px + 10 <= x <= right and ry <= y <= ry + rh:
                self._selected = i
                return None

        # Craft button
        bx, by, bw, bh = self._craft_btn_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            if self._crafting:
                return "cancel_craft"
            if self._selected == 0:
                # Repair pack
                if station_iron >= CRAFT_IRON_COST:
                    self._craft_target = ""
                    return "craft"
            elif self._selected == 1:
                # Shield Recharge
                if station_iron >= CRAFT_IRON_COST:
                    self._craft_target = "shield_recharge"
                    return "craft"
            else:
                # Module recipe
                idx = self._selected - 2
                if idx < len(self._recipes):
                    recipe = self._recipes[idx]
                    if station_iron >= recipe["cost"]:
                        self._craft_target = recipe["key"]
                        return f"craft_module:{recipe['key']}"
        return None

    def update(self, progress: float, crafting: bool) -> None:
        self._progress = progress
        self._crafting = crafting

    def draw(self, station_iron: int) -> None:
        if not self.open:
            return
        px, py = self._panel_origin()
        ph = self._panel_height()

        arcade.draw_rect_filled(
            arcade.LBWH(px, py, _PANEL_W, ph), (15, 20, 45, 240))
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, _PANEL_W, ph),
            arcade.color.STEEL_BLUE, border_width=2)

        self._t_title.x = px + _PANEL_W // 2
        self._t_title.y = py + ph - 20
        self._t_title.draw()

        self._draw_recipe_list(px, py, ph, station_iron)
        self._draw_craft_button(px, py, station_iron)

        self._t_close.x = px + _PANEL_W // 2; self._t_close.y = py + 10
        self._t_close.draw()

    def _draw_recipe_list(self, px: int, py: int, ph: int, station_iron: int) -> None:
        """Draw the scrollable recipe list and selected recipe detail."""
        view_top = py + ph - _HEADER
        view_bottom = view_top - self._list_viewport_h()
        top_y = view_top + int(self._scroll_px)
        # Adjust panel-internal width when scrollbar reserves a gutter.
        right_inset = (_SCROLL_W + 4) if self._needs_scrollbar() else 0

        # Draw recipe list using pre-built text objects
        costs = [CRAFT_IRON_COST, CRAFT_IRON_COST] + [r["cost"] for r in self._recipes]
        cum_y = 0
        for i, tr in enumerate(self._t_recipes):
            rh = self._recipe_heights[i] if i < len(self._recipe_heights) else _RECIPE_H
            ry = top_y - cum_y - rh
            cum_y += rh
            # Skip rows entirely outside the viewport.
            if ry + rh < view_bottom or ry > view_top:
                continue
            sel = (self._selected == i)
            fill = (50, 70, 100, 220) if sel else (25, 30, 50, 180)
            arcade.draw_rect_filled(
                arcade.LBWH(px + 10, ry, _PANEL_W - 20 - right_inset, rh - 2),
                fill)
            affordable = station_iron >= costs[i] if i < len(costs) else False
            tr.color = arcade.color.CYAN if sel else (arcade.color.WHITE if affordable else (150, 80, 80))
            # Draw recipe icon
            icon_w = 0
            icon_size = min(rh - 6, _RECIPE_H - 6)
            if i == 0 and self.repair_pack_icon:
                arcade.draw_texture_rect(self.repair_pack_icon,
                    arcade.LBWH(px + 14, ry + (rh - icon_size) // 2, icon_size, icon_size))
                icon_w = _ICON_AREA
            elif i == 1 and self.shield_recharge_icon:
                arcade.draw_texture_rect(self.shield_recharge_icon,
                    arcade.LBWH(px + 14, ry + (rh - icon_size) // 2, icon_size, icon_size))
                icon_w = _ICON_AREA
            elif i >= 2 and i - 2 < len(self._recipes):
                ricon = self.item_icons.get(self._recipes[i - 2]["key"])
                if ricon:
                    arcade.draw_texture_rect(ricon,
                        arcade.LBWH(px + 14, ry + (rh - icon_size) // 2, icon_size, icon_size))
                    icon_w = _ICON_AREA
            tr.x = px + 16 + icon_w; tr.y = ry + rh // 2
            tr.draw()

        if self._needs_scrollbar():
            self._draw_scrollbar()

        # Selected recipe detail with icon — anchored to the panel,
        # not the scrolled list, so it stays visible regardless of
        # current scroll position.
        detail_y = view_bottom - 10
        icon = None
        if self._selected == 0:
            _dt = f"Produces {CRAFT_RESULT_COUNT}x Repair Pack ({int(CRAFT_TIME)}s)"
            icon = self.repair_pack_icon
        elif self._selected == 1:
            _dt = f"Produces {CRAFT_RESULT_COUNT}x Shield Recharge ({int(CRAFT_TIME)}s)"
            icon = self.shield_recharge_icon
        elif self._selected - 2 < len(self._recipes):
            recipe = self._recipes[self._selected - 2]
            info = MODULE_TYPES[recipe["key"]]
            craft_time = int(info.get("craft_time", CRAFT_TIME))
            _dt = f"{info['label']}: {_effect_desc(info)} ({craft_time}s)"
            icon = self.item_icons.get(recipe["key"])
        else:
            _dt = ""
        if self._t_detail.text != _dt:
            self._t_detail.text = _dt
        icon_w = 0
        if icon:
            icon_w = 22
            arcade.draw_texture_rect(icon,
                arcade.LBWH(px + 14, detail_y - 4, 20, 20))
        self._t_detail.x = px + 16 + icon_w; self._t_detail.y = detail_y
        self._t_detail.draw()

    def _draw_craft_button(self, px: int, py: int, station_iron: int) -> None:
        """Draw the craft/cancel button and progress bar."""
        bx, by, bw, bh = self._craft_btn_rect()
        if self._crafting:
            btn_fill = (40, 40, 60, 220)
        elif self._selected <= 1 and station_iron >= CRAFT_IRON_COST:
            btn_fill = (30, 80, 30, 220)
        elif self._selected >= 2 and self._selected - 2 < len(self._recipes):
            cost = self._recipes[self._selected - 2]["cost"]
            btn_fill = (30, 80, 30, 220) if station_iron >= cost else (60, 30, 30, 220)
        else:
            btn_fill = (60, 30, 30, 220)
        arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), btn_fill)
        arcade.draw_rect_outline(arcade.LBWH(bx, by, bw, bh),
                                 arcade.color.STEEL_BLUE, border_width=1)
        _btn_label = "CANCEL" if self._crafting else "CRAFT"
        if self._t_btn.text != _btn_label:
            self._t_btn.text = _btn_label
        self._t_btn.x = bx + bw // 2; self._t_btn.y = by + bh // 2
        self._t_btn.draw()

        # Progress bar + crafting label (below craft button)
        if self._crafting:
            if self._craft_target and self._craft_target in MODULE_TYPES:
                crafting_name = MODULE_TYPES[self._craft_target]["label"]
            elif self._craft_target == "shield_recharge":
                crafting_name = "Shield Recharge"
            else:
                crafting_name = "Repair Pack"
            bar_w = _PANEL_W - 32; bar_x = px + 16; bar_y = by - 22
            arcade.draw_rect_filled(arcade.LBWH(bar_x, bar_y, bar_w, 12), (30, 30, 50))
            arcade.draw_rect_filled(
                arcade.LBWH(bar_x, bar_y, int(bar_w * self._progress), 12), (50, 180, 50))
            arcade.draw_rect_outline(
                arcade.LBWH(bar_x, bar_y, bar_w, 12), arcade.color.STEEL_BLUE, border_width=1)
            pct = int(self._progress * 100)
            if pct != self._last_pct:
                self._last_pct = pct
                self._t_status.text = f"{pct}%"
            self._t_status.x = px + _PANEL_W // 2; self._t_status.y = bar_y + 6
            self._t_status.draw()
            self._t_detail.text = f"Crafting: {crafting_name}"
            self._t_detail.color = arcade.color.YELLOW
            self._t_detail.x = px + 16; self._t_detail.y = bar_y - 14
            self._t_detail.draw()


    def _draw_scrollbar(self) -> None:
        tx, ty, tw, th = self._scrollbar_rect()
        arcade.draw_rect_filled(
            arcade.LBWH(tx, ty, tw, th), (20, 30, 50, 220))
        thx, thy, thw, thh = self._scrollbar_thumb_rect()
        thumb_color = ((180, 220, 255, 240) if self._dragging_scrollbar
                       else (120, 160, 220, 240))
        arcade.draw_rect_filled(
            arcade.LBWH(thx, thy, thw, thh), thumb_color)


def _effect_desc(info: dict) -> str:
    """Short description of a module's effect."""
    eff = info["effect"]
    val = info["value"]
    if info.get("consumable"):
        count = info.get("craft_count", 1)
        return f"produces {count}x per craft"
    descs = {
        "max_hp": f"+{val} HP",
        "max_speed": f"+{val} speed",
        "max_shields": f"+{val} shields",
        "shield_regen": f"+{val} shield regen",
        "shield_absorb": f"-{val} shield damage",
        "broadside": "side-firing lasers",
    }
    return descs.get(eff, str(val))
