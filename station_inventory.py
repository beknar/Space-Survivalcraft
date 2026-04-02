"""Station inventory — 10×10 grid overlay for the Home Station."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    STATION_INV_COLS, STATION_INV_ROWS, STATION_INV_CELL, STATION_INV_PAD,
    MAX_STACK, MAX_STACK_DEFAULT,
)
from base_inventory import BaseInventoryData

_INV_HEADER = 32
_INV_FOOTER = 20
_INV_W = STATION_INV_COLS * STATION_INV_CELL + STATION_INV_PAD * 2
_INV_H = STATION_INV_ROWS * STATION_INV_CELL + STATION_INV_PAD * 2 + _INV_HEADER + _INV_FOOTER


class StationInventory(BaseInventoryData):
    """10×10 grid for the Home Station, storing named items as (type, count) tuples."""

    # Display names for special item types
    _ITEM_NAMES: dict[str, str] = {}

    def __init__(
        self,
        iron_icon: Optional[arcade.Texture] = None,
        repair_pack_icon: Optional[arcade.Texture] = None,
        shield_recharge_icon: Optional[arcade.Texture] = None,
    ) -> None:
        self._items: dict[tuple[int, int], tuple[str, int]] = {}
        self._rows = STATION_INV_ROWS
        self._cols = STATION_INV_COLS
        self.open: bool = False
        self._iron_icon = iron_icon
        self._repair_pack_icon = repair_pack_icon
        self._shield_recharge_icon = shield_recharge_icon
        # Extra icons for blueprints, modules, etc. (set by game_view)
        self.item_icons: dict[str, arcade.Texture] = {}
        # Mouse tracking for tooltip
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        self._tip_cell: Optional[tuple[int, int]] = None  # cached hover cell

        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None

        # Drag state
        self._drag_type: Optional[str] = None
        self._drag_amount: int = 0
        self._drag_src: Optional[tuple[int, int]] = None
        self._drag_x: float = 0.0
        self._drag_y: float = 0.0

        # Pre-built text
        self._t_title = arcade.Text(
            "STATION INVENTORY  (10 × 10)", 0, 0,
            arcade.color.LIGHT_BLUE, 12, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_hint = arcade.Text(
            "click to close   drag items to ship inventory", 0, 0,
            (160, 160, 160), 8, anchor_x="center", anchor_y="center",
        )
        self._t_consolidate = arcade.Text(
            "Consolidate", 0, 0, arcade.color.WHITE, 8, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_label = arcade.Text("", 0, 0, arcade.color.WHITE, 7)
        self._t_count = arcade.Text("", 0, 0, arcade.color.ORANGE, 8, bold=True)
        # Pre-built count labels to avoid .text churn (0-999)
        self._count_cache: dict[str, arcade.Text] = {}
        self._t_tooltip = arcade.Text("", 0, 0, arcade.color.WHITE, 8, bold=True,
                                      anchor_x="center", anchor_y="center")

        # Build display names from MODULE_TYPES
        from constants import MODULE_TYPES
        for key, info in MODULE_TYPES.items():
            self._ITEM_NAMES[f"bp_{key}"] = f"BP {info['label']}"
            self._ITEM_NAMES[f"mod_{key}"] = info["label"]
        self._ITEM_NAMES["iron"] = "Iron"
        self._ITEM_NAMES["repair_pack"] = "Repair Pack"
        self._ITEM_NAMES["shield_recharge"] = "Shield Recharge"

    # ── Geometry ─────────────────────────────────────────────────────────
    def _panel_origin(self) -> tuple[int, int]:
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        from constants import INV_W
        # Place station inv to the left of the ship inv (which is centred)
        ship_inv_left = (sw - INV_W) // 2
        ox = max(4, ship_inv_left - _INV_W - 10)
        oy = (sh - _INV_H) // 2
        return ox, oy

    def _grid_origin(self) -> tuple[int, int]:
        ox, oy = self._panel_origin()
        return ox + STATION_INV_PAD, oy + STATION_INV_PAD + _INV_FOOTER

    def _nearest_empty_cell(self, x: float, y: float) -> Optional[tuple[int, int]]:
        """Return the closest empty cell to screen coords (x, y)."""
        import math as _math
        gx, gy = self._grid_origin()
        best = None
        best_dist = float('inf')
        for r in range(STATION_INV_ROWS):
            for c in range(STATION_INV_COLS):
                cell = (r, c)
                if cell in self._items:
                    continue
                row_from_bottom = STATION_INV_ROWS - 1 - r
                cx = gx + c * STATION_INV_CELL + STATION_INV_CELL / 2
                cy = gy + row_from_bottom * STATION_INV_CELL + STATION_INV_CELL / 2
                d = _math.hypot(x - cx, y - cy)
                if d < best_dist:
                    best_dist = d
                    best = cell
        return best

    def _cell_at(self, x: float, y: float) -> Optional[tuple[int, int]]:
        gx, gy = self._grid_origin()
        grid_w = STATION_INV_COLS * STATION_INV_CELL
        grid_h = STATION_INV_ROWS * STATION_INV_CELL
        if x < gx or x >= gx + grid_w or y < gy or y >= gy + grid_h:
            return None
        col = int((x - gx) / STATION_INV_CELL)
        row_from_bottom = int((y - gy) / STATION_INV_CELL)
        row = STATION_INV_ROWS - 1 - row_from_bottom
        if 0 <= row < STATION_INV_ROWS and 0 <= col < STATION_INV_COLS:
            return (row, col)
        return None

    def _panel_contains(self, x: float, y: float) -> bool:
        ox, oy = self._panel_origin()
        return ox <= x <= ox + _INV_W and oy <= y <= oy + _INV_H

    def on_mouse_motion(self, x: float, y: float) -> None:
        self._mouse_x = x
        self._mouse_y = y

    # ── Input ────────────────────────────────────────────────────────────
    def on_mouse_press(self, x: float, y: float) -> bool:
        if not self.open:
            return False
        if not self._panel_contains(x, y):
            return False  # click outside — don't close, let caller handle
        # Consolidate button
        ox, oy = self._panel_origin()
        cbx = ox + _INV_W - 70
        cby = oy + _INV_H - _INV_HEADER + 4
        if cbx <= x <= cbx + 60 and cby <= y <= cby + 18:
            self.consolidate()
            return True
        cell = self._cell_at(x, y)
        if cell is None:
            return False
        item = self._items.get(cell)
        if item is not None:
            self._drag_type = item[0]
            self._drag_amount = item[1]
            self._drag_src = cell
            del self._items[cell]
            self._drag_x = x
            self._drag_y = y
            return True
        return False

    def on_mouse_drag(self, x: float, y: float) -> None:
        if self._drag_type is not None:
            self._drag_x = x
            self._drag_y = y

    def on_mouse_release(self, x: float, y: float) -> Optional[tuple[str, int]]:
        """Returns (item_type, amount) if item was dropped outside panel (for transfer)."""
        if self._drag_type is None:
            return None
        dt = self._drag_type
        da = self._drag_amount
        src = self._drag_src
        self._drag_type = None
        self._drag_amount = 0
        self._drag_src = None

        # Check if dropped on the ship inventory panel — treat as external transfer
        from constants import INV_W, INV_H
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        ship_ox = (sw - INV_W) // 2
        ship_oy = (sh - INV_H) // 2
        if ship_ox <= x <= ship_ox + INV_W and ship_oy <= y <= ship_oy + INV_H:
            return (dt, da)

        cell = self._cell_at(x, y)
        if cell is not None:
            # Dropped back into station grid — handle swap/stack
            existing = self._items.get(cell)
            if existing is not None:
                if existing[0] == dt:
                    # Stack onto same type
                    self._items[cell] = (dt, existing[1] + da)
                else:
                    # Swap
                    if src is not None:
                        self._items[src] = existing
                    self._items[cell] = (dt, da)
            else:
                self._items[cell] = (dt, da)
            return None

        if not self._panel_contains(x, y):
            # Dropped outside panel — return for transfer to ship
            return (dt, da)

        # Dropped on panel border — return to source
        if src is not None:
            self._items[src] = (dt, da)
        return None

    # ── Drawing ──────────────────────────────────────────────────────────
    def draw(self) -> None:
        if not self.open:
            return
        ox, oy = self._panel_origin()
        gx, gy = self._grid_origin()

        # Panel bg
        arcade.draw_rect_filled(
            arcade.LBWH(ox, oy, _INV_W, _INV_H), (15, 15, 40, 235),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(ox, oy, _INV_W, _INV_H),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        # Title
        self._t_title.x = ox + _INV_W // 2
        self._t_title.y = oy + _INV_H - _INV_HEADER // 2 - 2
        self._t_title.draw()
        self._t_hint.x = ox + _INV_W // 2
        self._t_hint.y = oy + _INV_FOOTER // 2
        self._t_hint.draw()
        # Consolidate button (top-right corner)
        cbx = ox + _INV_W - 70
        cby = oy + _INV_H - _INV_HEADER + 4
        arcade.draw_rect_filled(arcade.LBWH(cbx, cby, 60, 18), (40, 60, 40, 220))
        arcade.draw_rect_outline(arcade.LBWH(cbx, cby, 60, 18),
                                 arcade.color.LIME_GREEN, border_width=1)
        self._t_consolidate.x = cbx + 30; self._t_consolidate.y = cby + 9
        self._t_consolidate.draw()

        cs = STATION_INV_CELL
        grid_w = STATION_INV_COLS * cs
        grid_h = STATION_INV_ROWS * cs
        # Draw grid background in one call (empty cell colour)
        arcade.draw_rect_filled(arcade.LBWH(gx, gy, grid_w, grid_h), (30, 30, 60, 200))
        # Grid lines (horizontal + vertical)
        for i in range(STATION_INV_COLS + 1):
            lx = gx + i * cs
            arcade.draw_line(lx, gy, lx, gy + grid_h, (60, 80, 120), 1)
        for i in range(STATION_INV_ROWS + 1):
            ly = gy + i * cs
            arcade.draw_line(gx, ly, gx + grid_w, ly, (60, 80, 120), 1)

        # Only draw cells that have items (skip empty cells entirely)
        for cell, (it, ct) in self._items.items():
            r, c = cell
            row_from_bottom = STATION_INV_ROWS - 1 - r
            cx = gx + c * cs
            cy = gy + row_from_bottom * cs
            is_src = (cell == self._drag_src)

            if is_src:
                fill = (70, 90, 40, 200)
            else:
                fill = (50, 80, 50, 200)
            arcade.draw_rect_filled(arcade.LBWH(cx + 1, cy + 1, cs - 2, cs - 2), fill)

            if not is_src:
                    it, ct = self._items[cell]
                    icon = None
                    if it == "iron" and self._iron_icon:
                        icon = self._iron_icon
                    elif it == "repair_pack" and self._repair_pack_icon:
                        icon = self._repair_pack_icon
                    elif it == "shield_recharge" and self._shield_recharge_icon:
                        icon = self._shield_recharge_icon
                    elif it in self.item_icons:
                        icon = self.item_icons[it]

                    if icon:
                        arcade.draw_texture_rect(
                            icon,
                            arcade.LBWH(cx + 4, cy + 8, cs - 8, cs - 12),
                        )
                    else:
                        self._t_label.text = it[:6]
                        self._t_label.x = cx + 3
                        self._t_label.y = cy + cs // 2
                        self._t_label.draw()
                    ct_str = str(ct)
                    ct_text = self._count_cache.get(ct_str)
                    if ct_text is None:
                        ct_text = arcade.Text(ct_str, 0, 0, arcade.color.ORANGE, 8,
                                              bold=True, anchor_x="right")
                        self._count_cache[ct_str] = ct_text
                    ct_text.x = cx + cs - 6
                    ct_text.y = cy + 4
                    ct_text.draw()

        # ── Hover tooltip ──────────────────────────────────────────────
        if self._drag_type is None:
            tip_cell = self._cell_at(self._mouse_x, self._mouse_y)
            if tip_cell is not None:
                item = self._items.get(tip_cell)
                if item is not None:
                    it, ct = item
                    # Only rebuild tooltip text when cell changes
                    if tip_cell != self._tip_cell:
                        self._tip_cell = tip_cell
                        name = self._ITEM_NAMES.get(it, it)
                        self._t_tooltip.text = f"{name}  \u00d7{ct}"
                    row, col = tip_cell
                    row_from_bottom = STATION_INV_ROWS - 1 - row
                    tip_cx = gx + col * cs + cs // 2
                    tip_ty = gy + row_from_bottom * cs + cs + 2
                    tw = len(self._t_tooltip.text) * 6 + 12
                    tx0 = max(2, min(self._window.width - tw - 2, tip_cx - tw // 2))
                    arcade.draw_rect_filled(
                        arcade.LBWH(tx0, tip_ty, tw, 15), (20, 20, 50, 230))
                    arcade.draw_rect_outline(
                        arcade.LBWH(tx0, tip_ty, tw, 15),
                        arcade.color.LIGHT_GRAY, border_width=1)
                    self._t_tooltip.x = tx0 + tw // 2
                    self._t_tooltip.y = tip_ty + 7
                    self._t_tooltip.draw()
                else:
                    self._tip_cell = None
            else:
                self._tip_cell = None

    def draw_drag_preview(self) -> None:
        """Draw the drag preview separately (call after ship inv to be on top)."""
        if not self.open or self._drag_type is None:
            return
        cs = STATION_INV_CELL
        dx, dy = self._drag_x, self._drag_y
        arcade.draw_rect_filled(
            arcade.LBWH(dx - cs // 2, dy - cs // 2, cs, cs),
            (80, 80, 40, 180),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(dx - cs // 2, dy - cs // 2, cs, cs),
            arcade.color.YELLOW, border_width=2,
        )
        self._t_label.text = self._drag_type[:8]
        self._t_label.x = dx - cs // 2 + 3
        self._t_label.y = dy
        self._t_label.draw()
        self._t_count.text = str(self._drag_amount)
        self._t_count.x = dx + cs // 2 - 4
        self._t_count.y = dy - cs // 2 + 4
        self._t_count.anchor_x = "right"
        self._t_count.draw()
        self._t_count.anchor_x = "left"

    def to_save_data(self) -> dict:
        """Serialize station inventory for save game."""
        items = []
        for (r, c), (it, ct) in self._items.items():
            items.append({"r": r, "c": c, "type": it, "count": ct})
        return {"items": items}

    def from_save_data(self, data: dict) -> None:
        """Restore station inventory from save data."""
        self._items.clear()
        # Migrate old saves that stored iron as a separate pool
        old_iron = data.get("iron", 0)
        if old_iron > 0:
            self.add_item("iron", old_iron)
        for entry in data.get("items", []):
            r, c = entry["r"], entry["c"]
            self._items[(r, c)] = (entry["type"], entry["count"])
