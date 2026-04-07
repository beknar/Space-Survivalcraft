"""Shared inventory data logic for both ship and station inventories."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import MAX_STACK, MAX_STACK_DEFAULT, SCREEN_WIDTH, SCREEN_HEIGHT


class BaseInventoryData:
    """Mixin providing shared item storage, counting, drag state, and drawing helpers.

    Subclasses must set:
        _items: dict[tuple[int, int], tuple[str, int]]
        _rows: int
        _cols: int
    """

    _items: dict[tuple[int, int], tuple[str, int]]
    _rows: int
    _cols: int

    def _init_drag_state(self) -> None:
        """Initialize drag-and-drop state. Call from subclass __init__."""
        self._drag_type: Optional[str] = None
        self._drag_amount: int = 0
        self._drag_src: Optional[tuple[int, int]] = None
        self._drag_x: float = 0.0
        self._drag_y: float = 0.0
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0

    def _init_icons(
        self,
        iron_icon: Optional[arcade.Texture],
        repair_pack_icon: Optional[arcade.Texture],
        shield_recharge_icon: Optional[arcade.Texture],
    ) -> None:
        """Initialize item icon references. Call from subclass __init__."""
        self._iron_icon = iron_icon
        self._repair_pack_icon = repair_pack_icon
        self._shield_recharge_icon = shield_recharge_icon
        self.item_icons: dict[str, arcade.Texture] = {}
        self._count_cache: dict[str, arcade.Text] = {}

    def _init_window(self) -> None:
        """Initialize window reference. Call from subclass __init__."""
        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None

    @property
    def total_iron(self) -> int:
        return self.count_item("iron")

    @property
    def iron(self) -> int:
        return self.total_iron

    def count_item(self, item_type: str) -> int:
        total = 0
        for (it, ct) in self._items.values():
            if it == item_type:
                total += ct
        return total

    def add_item(self, item_type: str, count: int = 1) -> None:
        for cell, (it, ct) in list(self._items.items()):
            if it == item_type:
                self._items[cell] = (it, ct + count)
                return
        for r in range(self._rows):
            for c in range(self._cols):
                if (r, c) not in self._items:
                    self._items[(r, c)] = (item_type, count)
                    return

    def remove_item(self, item_type: str, count: int = 1) -> int:
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

    def consolidate(self) -> None:
        totals: dict[str, int] = {}
        for (it, ct) in self._items.values():
            totals[it] = totals.get(it, 0) + ct
        self._items.clear()
        cell = 0
        for it, total in totals.items():
            max_s = MAX_STACK.get(it, MAX_STACK_DEFAULT)
            while total > 0 and cell < self._rows * self._cols:
                amt = min(total, max_s)
                r, c = divmod(cell, self._cols)
                self._items[(r, c)] = (it, amt)
                total -= amt
                cell += 1

    def toggle(self) -> None:
        self.open = not self.open

    # ── Shared grid helpers ────────────────────────────────────────────────

    def _resolve_icon(self, item_type: str) -> Optional[arcade.Texture]:
        """Look up the icon texture for an item type."""
        if item_type == "iron" and self._iron_icon is not None:
            return self._iron_icon
        if item_type == "repair_pack" and self._repair_pack_icon is not None:
            return self._repair_pack_icon
        if item_type == "shield_recharge" and self._shield_recharge_icon is not None:
            return self._shield_recharge_icon
        return self.item_icons.get(item_type)

    def _draw_count_badge(self, count: int, x: float, y: float, cell_size: int) -> None:
        """Draw count badge at bottom-right of cell."""
        ct_str = str(count)
        ct_text = self._count_cache.get(ct_str)
        if ct_text is None:
            ct_text = arcade.Text(ct_str, 0, 0, arcade.color.ORANGE, 8,
                                  bold=True, anchor_x="right")
            self._count_cache[ct_str] = ct_text
        ct_text.x = x + cell_size - 4
        ct_text.y = y + 3
        ct_text.draw()

    def _start_drag(self, cell: tuple[int, int], x: float, y: float) -> bool:
        """Start dragging item from cell. Returns True if drag started."""
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

    def _finish_drag(self, target: Optional[tuple[int, int]]) -> None:
        """Drop dragged item onto target cell (handles stacking/swapping)."""
        if target is None:
            if self._drag_src is not None:
                self._items[self._drag_src] = (self._drag_type, self._drag_amount)
        else:
            existing = self._items.get(target)
            if existing is not None:
                if existing[0] == self._drag_type:
                    self._items[target] = (self._drag_type, existing[1] + self._drag_amount)
                else:
                    if self._drag_src is not None:
                        self._items[self._drag_src] = existing
                    self._items[target] = (self._drag_type, self._drag_amount)
            else:
                self._items[target] = (self._drag_type, self._drag_amount)
        self._drag_type = None
        self._drag_amount = 0
        self._drag_src = None

    def _clear_drag(self) -> tuple[str, int]:
        """Clear drag state, returning (type, amount) of what was being dragged."""
        dt, da = self._drag_type, self._drag_amount
        self._drag_type = None
        self._drag_amount = 0
        self._drag_src = None
        return dt, da

    def _screen_size(self) -> tuple[int, int]:
        """Return current screen dimensions."""
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        return sw, sh
