"""Station inventory — 10×10 grid overlay for the Home Station."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    STATION_INV_COLS, STATION_INV_ROWS, STATION_INV_CELL, STATION_INV_PAD,
)

_INV_HEADER = 32
_INV_FOOTER = 20
_INV_W = STATION_INV_COLS * STATION_INV_CELL + STATION_INV_PAD * 2
_INV_H = STATION_INV_ROWS * STATION_INV_CELL + STATION_INV_PAD * 2 + _INV_HEADER + _INV_FOOTER


class StationInventory:
    """10×10 grid for the Home Station, storing named items as (type, count) tuples."""

    def __init__(
        self,
        iron_icon: Optional[arcade.Texture] = None,
        repair_pack_icon: Optional[arcade.Texture] = None,
    ) -> None:
        self._items: dict[tuple[int, int], tuple[str, int]] = {}
        self.open: bool = False
        self._iron_icon = iron_icon
        self._repair_pack_icon = repair_pack_icon

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
        self._t_label = arcade.Text("", 0, 0, arcade.color.WHITE, 7)
        self._t_count = arcade.Text("", 0, 0, arcade.color.ORANGE, 8, bold=True)

    def toggle(self) -> None:
        self.open = not self.open

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def total_iron(self) -> int:
        """Total iron across all cells."""
        return self.count_item("iron")

    # Backward-compat alias
    @property
    def iron(self) -> int:
        return self.total_iron

    def add_item(self, item_type: str, count: int = 1) -> None:
        """Add items to the first available cell or stack on existing."""
        # Try to stack on existing cell of same type
        for cell, (it, ct) in list(self._items.items()):
            if it == item_type:
                self._items[cell] = (it, ct + count)
                return
        # Find first empty cell
        for r in range(STATION_INV_ROWS):
            for c in range(STATION_INV_COLS):
                if (r, c) not in self._items:
                    self._items[(r, c)] = (item_type, count)
                    return

    def remove_item(self, item_type: str, count: int = 1) -> int:
        """Remove up to *count* items of the given type. Returns amount removed."""
        removed = 0
        for cell, (it, ct) in list(self._items.items()):
            if it == item_type:
                take = min(ct, count - removed)
                remaining = ct - take
                removed += take
                if remaining <= 0:
                    del self._items[cell]
                else:
                    self._items[cell] = (it, remaining)
                if removed >= count:
                    break
        return removed

    def count_item(self, item_type: str) -> int:
        """Count total items of the given type."""
        total = 0
        for (it, ct) in self._items.values():
            if it == item_type:
                total += ct
        return total

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

    # ── Input ────────────────────────────────────────────────────────────
    def on_mouse_press(self, x: float, y: float) -> bool:
        if not self.open:
            return False
        if not self._panel_contains(x, y):
            return False  # click outside — don't close, let caller handle
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
        if self._drag_type is not None:
            print(f"[STATION_REL] drag_type={self._drag_type} at ({x:.0f},{y:.0f})")
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
        print(f"[STATION_REL] ship_panel=({ship_ox},{ship_oy})-({ship_ox+INV_W},{ship_oy+INV_H}) cursor=({x:.0f},{y:.0f})")
        if ship_ox <= x <= ship_ox + INV_W and ship_oy <= y <= ship_oy + INV_H:
            # Cursor is on ship inventory — return item for cross-transfer
            print(f"[INV] Station→Ship: returning {dt} x{da}")
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

        cs = STATION_INV_CELL
        for r in range(STATION_INV_ROWS):
            for c in range(STATION_INV_COLS):
                row_from_bottom = STATION_INV_ROWS - 1 - r
                cx = gx + c * cs
                cy = gy + row_from_bottom * cs
                cell = (r, c)

                # Cell colour
                is_item = cell in self._items
                is_src = (cell == self._drag_src)
                if is_src:
                    fill = (70, 90, 40, 200)
                elif is_item:
                    fill = (50, 80, 50, 200)
                else:
                    fill = (30, 30, 60, 200)

                arcade.draw_rect_filled(arcade.LBWH(cx, cy, cs - 1, cs - 1), fill)
                arcade.draw_rect_outline(
                    arcade.LBWH(cx, cy, cs - 1, cs - 1),
                    (60, 80, 120), border_width=1,
                )

                # Draw item
                if is_item and not is_src:
                    it, ct = self._items[cell]
                    icon = None
                    if it == "iron" and self._iron_icon:
                        icon = self._iron_icon
                    elif it == "repair_pack" and self._repair_pack_icon:
                        icon = self._repair_pack_icon

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
                    self._t_count.text = str(ct)
                    self._t_count.x = cx + cs - 6
                    self._t_count.y = cy + 4
                    self._t_count.anchor_x = "right"
                    self._t_count.draw()
                    self._t_count.anchor_x = "left"

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
