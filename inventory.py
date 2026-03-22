"""Inventory (cargo hold) UI overlay."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    INV_COLS, INV_ROWS, INV_CELL, INV_PAD, INV_HEADER, INV_FOOTER, INV_W, INV_H,
)


class Inventory:
    """5x5 cargo hold grid drawn as a modal overlay.

    All items (iron, repair_pack, etc.) are stored as (type, count) tuples
    in grid cells and support stacking.
    """

    def __init__(
        self,
        iron_icon: Optional[arcade.Texture] = None,
        repair_pack_icon: Optional[arcade.Texture] = None,
    ) -> None:
        # items: dict[(row, col)] -> (item_type, count); absent key = empty slot
        self._items: dict[tuple[int, int], tuple[str, int]] = {}
        self.open: bool = False
        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None  # tests may run without a window

        self._iron_icon: Optional[arcade.Texture] = iron_icon
        self._repair_pack_icon: Optional[arcade.Texture] = repair_pack_icon

        # Drag-and-drop state
        self._drag_type: Optional[str] = None
        self._drag_amount: int = 0
        self._drag_src: Optional[tuple[int, int]] = None
        self._drag_x: float = 0.0
        self._drag_y: float = 0.0

        # Mouse position (for hover tooltip)
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0

        # Pre-built Text labels (avoids per-draw allocations)
        _sw = self._window.width if self._window else SCREEN_WIDTH
        _sh = self._window.height if self._window else SCREEN_HEIGHT
        cx = _sw // 2
        oy = (_sh - INV_H) // 2
        self._t_title = arcade.Text(
            "CARGO HOLD  (5 \u00d7 5)",
            cx,
            oy + INV_H - INV_HEADER // 2 - 2,
            arcade.color.LIGHT_BLUE,
            14,
            bold=True,
            anchor_x="center",
            anchor_y="center",
        )
        self._t_hint = arcade.Text(
            "I \u2014 close   drag to move items",
            cx,
            oy + INV_FOOTER // 2,
            (160, 160, 160),
            9,
            anchor_x="center",
            anchor_y="center",
        )
        # Count label (reused for all item types)
        self._t_count = arcade.Text("", 0, 0, arcade.color.ORANGE, 9, bold=True)
        # Generic item text labels
        self._t_item_label = arcade.Text("", 0, 0, arcade.color.WHITE, 8)
        self._t_drag_label = arcade.Text("", 0, 0, arcade.color.WHITE, 8)
        self._t_tooltip = arcade.Text(
            "", 0, 0, arcade.color.WHITE, 9,
            anchor_x="center", anchor_y="center",
        )

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def total_iron(self) -> int:
        """Total iron across all cells."""
        return self.count_item("iron")

    # Backward-compat alias so existing code using `inventory.iron` keeps working
    # during migration. Reads sum from cells; writes not supported (use add_item).
    @property
    def iron(self) -> int:
        return self.total_iron

    def add_iron(self, amount: int) -> None:
        """Backward-compat helper — delegates to add_item."""
        self.add_item("iron", amount)

    def add_item(self, item_type: str, count: int = 1) -> None:
        """Add items to the first available cell or stack on existing."""
        # Try to stack on existing cell of same type
        for cell, (it, ct) in list(self._items.items()):
            if it == item_type:
                self._items[cell] = (it, ct + count)
                return
        # Find first empty cell
        for r in range(INV_ROWS):
            for c in range(INV_COLS):
                if (r, c) not in self._items:
                    self._items[(r, c)] = (item_type, count)
                    return

    def count_item(self, item_type: str) -> int:
        """Count total items of the given type across all cells."""
        total = 0
        for (it, ct) in self._items.values():
            if it == item_type:
                total += ct
        return total

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

    def toggle(self) -> None:
        self.open = not self.open

    # ── Mouse helpers ───────────────────────────────────────────────────────
    def _grid_origin(self) -> tuple[int, int]:
        """Return (grid_x, grid_y) -- pixel coords of the bottom-left of the grid."""
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        ox = (sw - INV_W) // 2
        oy = (sh - INV_H) // 2
        return ox + INV_PAD, oy + INV_PAD + INV_FOOTER

    def _nearest_empty_cell(self, x: float, y: float) -> Optional[tuple[int, int]]:
        """Return the closest empty cell to screen coords (x, y)."""
        import math as _math
        gx, gy = self._grid_origin()
        best = None
        best_dist = float('inf')
        for r in range(INV_ROWS):
            for c in range(INV_COLS):
                cell = (r, c)
                if cell in self._items:
                    continue
                row_from_bottom = INV_ROWS - 1 - r
                cx = gx + c * INV_CELL + INV_CELL / 2
                cy = gy + row_from_bottom * INV_CELL + INV_CELL / 2
                d = _math.hypot(x - cx, y - cy)
                if d < best_dist:
                    best_dist = d
                    best = cell
        return best

    def _cell_at(self, x: float, y: float) -> Optional[tuple[int, int]]:
        """Return (row, col) for screen-space coords, or None if outside grid."""
        gx, gy = self._grid_origin()
        # Explicit bounds check first
        grid_w = INV_COLS * INV_CELL
        grid_h = INV_ROWS * INV_CELL
        if x < gx or x >= gx + grid_w or y < gy or y >= gy + grid_h:
            return None
        col = int((x - gx) / INV_CELL)
        row_from_bottom = int((y - gy) / INV_CELL)
        row = INV_ROWS - 1 - row_from_bottom
        if 0 <= row < INV_ROWS and 0 <= col < INV_COLS:
            return (row, col)
        return None

    def _panel_contains(self, x: float, y: float) -> bool:
        """Return True if (x, y) lies within the inventory panel rectangle."""
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        ox = (sw - INV_W) // 2
        oy = (sh - INV_H) // 2
        return ox <= x <= ox + INV_W and oy <= y <= oy + INV_H

    def on_mouse_press(self, x: float, y: float) -> bool:
        """Attempt to pick up the item at (x, y).  Returns True if drag started."""
        if not self.open:
            return False
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
        """Update the floating icon position during a drag."""
        if self._drag_type is not None:
            self._drag_x = x
            self._drag_y = y
        self._mouse_x = x
        self._mouse_y = y

    def on_mouse_move(self, x: float, y: float) -> None:
        """Track cursor position for hover tooltip."""
        self._mouse_x = x
        self._mouse_y = y

    def on_mouse_release(
        self, x: float, y: float
    ) -> Optional[tuple[str, int]]:
        """Drop the carried item.

        Returns (item_type, amount) when an item is ejected into the game world
        (dropped outside the inventory panel), or None otherwise.
        """
        if self._drag_type is None:
            return None

        dt = self._drag_type
        da = self._drag_amount

        # Check if dropped on station inventory panel — treat as cross-transfer
        from station_inventory import StationInventory, _INV_W as _SI_W, _INV_H as _SI_H
        try:
            from constants import INV_W as _ship_w
            sw = self._window.width if self._window else SCREEN_WIDTH
            sh = self._window.height if self._window else SCREEN_HEIGHT
            ship_left = (sw - _ship_w) // 2
            si_ox = max(4, ship_left - _SI_W - 10)
            si_oy = (sh - _SI_H) // 2
            if si_ox <= x <= si_ox + _SI_W and si_oy <= y <= si_oy + _SI_H:
                self._drag_type = None
                self._drag_amount = 0
                self._drag_src = None
                return (dt, da)
        except ImportError:
            pass

        target = self._cell_at(x, y)

        if target is None and not self._panel_contains(x, y):
            # ── Ejected outside the inventory panel -> drop into world ─────
            self._drag_type = None
            self._drag_amount = 0
            self._drag_src = None
            return (dt, da)

        if target is None:
            # Dropped on panel header/border -- return to source cell
            target = self._drag_src

        assert target is not None
        existing = self._items.get(target)
        if existing is not None:
            if existing[0] == dt:
                # Stack onto same type
                self._items[target] = (dt, existing[1] + da)
            else:
                # Swap: put existing back in source, place dragged in target
                if self._drag_src is not None:
                    self._items[self._drag_src] = existing
                self._items[target] = (dt, da)
        else:
            self._items[target] = (dt, da)

        self._drag_type = None
        self._drag_amount = 0
        self._drag_src = None
        return None

    # ── Drawing ─────────────────────────────────────────────────────────────
    def _draw_item_in_cell(
        self, item_type: str, count: int, cell_x: float, cell_y: float, alpha: int = 255
    ) -> None:
        """Draw an item icon + count badge in a cell."""
        icon = None
        if item_type == "iron" and self._iron_icon is not None:
            icon = self._iron_icon
        elif item_type == "repair_pack" and self._repair_pack_icon is not None:
            icon = self._repair_pack_icon

        if icon is not None:
            icon_scale = (INV_CELL - 12) / max(icon.width, icon.height)
            arcade.draw_texture_rect(
                icon,
                arcade.LBWH(
                    cell_x + 6, cell_y + 6,
                    icon.width * icon_scale,
                    icon.height * icon_scale,
                ),
                alpha=alpha,
            )
        else:
            self._t_item_label.text = item_type[:6]
            self._t_item_label.x = cell_x + 4
            self._t_item_label.y = cell_y + INV_CELL // 2 - 5
            self._t_item_label.draw()

        self._t_count.text = str(count)
        self._t_count.x = cell_x + INV_CELL - 4
        self._t_count.y = cell_y + 3
        self._t_count.anchor_x = "right"
        self._t_count.draw()
        self._t_count.anchor_x = "left"

    def draw(self) -> None:
        if not self.open:
            return

        ox = (self._window.width - INV_W) // 2
        oy = (self._window.height - INV_H) // 2
        # Update title/hint positions for current window size
        self._t_title.x = self._window.width // 2
        self._t_title.y = oy + INV_H - INV_HEADER // 2 - 2
        self._t_hint.x = self._window.width // 2
        self._t_hint.y = oy + INV_FOOTER // 2
        gx, gy = self._grid_origin()

        # Panel background and border
        arcade.draw_rect_filled(
            arcade.LBWH(ox, oy, INV_W, INV_H), (10, 10, 35, 230)
        )
        arcade.draw_rect_outline(
            arcade.LBWH(ox, oy, INV_W, INV_H),
            arcade.color.STEEL_BLUE,
            border_width=2,
        )

        self._t_title.draw()

        # Determine which cell the cursor is hovering over (for highlight)
        hover_cell = self._cell_at(self._drag_x, self._drag_y) if self._drag_type else None

        # Grid cells
        for row in range(INV_ROWS):
            for col in range(INV_COLS):
                cx_ = gx + col * INV_CELL
                cy_ = gy + (INV_ROWS - 1 - row) * INV_CELL
                cell = (row, col)
                is_src = (cell == self._drag_src and self._drag_type is not None)
                is_hover = (cell == hover_cell)

                item = self._items.get(cell)
                occupied = item is not None

                if is_src:
                    fill = (60, 60, 20, 200)
                elif is_hover:
                    fill = (50, 70, 100, 220)
                elif occupied:
                    fill = (50, 80, 50, 200)
                else:
                    fill = (30, 30, 60, 200)

                arcade.draw_rect_filled(
                    arcade.LBWH(cx_ + 1, cy_ + 1, INV_CELL - 2, INV_CELL - 2),
                    fill,
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx_, cy_, INV_CELL, INV_CELL),
                    (60, 80, 120),
                    border_width=1,
                )

                # Draw item content (skip source cell of drag)
                if not is_src and item is not None:
                    self._draw_item_in_cell(item[0], item[1], cx_, cy_)

        # Hint text (drawn after grid so cells don't occlude it)
        self._t_hint.draw()

        # Floating icon under cursor during drag
        if self._drag_type is not None:
            half = INV_CELL // 2
            fx = self._drag_x - half
            fy = self._drag_y - half
            arcade.draw_rect_filled(
                arcade.LBWH(fx, fy, INV_CELL, INV_CELL),
                (70, 90, 40, 180),
            )
            arcade.draw_rect_outline(
                arcade.LBWH(fx, fy, INV_CELL, INV_CELL),
                arcade.color.YELLOW,
                border_width=1,
            )
            self._draw_item_in_cell(self._drag_type, self._drag_amount, fx, fy, alpha=200)

        # ── Hover tooltip ──────────────────────────────────────────────────
        tip_cell = self._cell_at(self._mouse_x, self._mouse_y)
        if tip_cell is not None and self._drag_type is None:
            item = self._items.get(tip_cell)
            if item is not None:
                it, ct = item
                tip_label = f"{it}  \u00d7{ct}"
            else:
                tip_label = None

            if tip_label:
                row, col = tip_cell
                gx2, gy2 = self._grid_origin()
                cell_cx = gx2 + col * INV_CELL + INV_CELL // 2
                cell_ty = gy2 + (INV_ROWS - 1 - row) * INV_CELL + INV_CELL + 2
                # Keep tooltip inside screen
                if cell_ty + 16 > self._window.height:
                    cell_ty = gy2 + (INV_ROWS - 1 - row) * INV_CELL - 18
                tw = len(tip_label) * 6 + 12
                tx0 = max(2, min(self._window.width - tw - 2, cell_cx - tw // 2))
                arcade.draw_rect_filled(
                    arcade.LBWH(tx0, cell_ty, tw, 15), (20, 20, 50, 230)
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(tx0, cell_ty, tw, 15),
                    arcade.color.LIGHT_GRAY, border_width=1,
                )
                self._t_tooltip.text = tip_label
                self._t_tooltip.x = tx0 + tw // 2
                self._t_tooltip.y = cell_ty + 7
                self._t_tooltip.draw()
