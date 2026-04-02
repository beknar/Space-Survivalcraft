"""Shared inventory data logic for both ship and station inventories."""
from __future__ import annotations

from typing import Optional

from constants import MAX_STACK, MAX_STACK_DEFAULT


class BaseInventoryData:
    """Mixin providing shared item storage, counting, and stack management.

    Subclasses must set:
        _items: dict[tuple[int, int], tuple[str, int]]
        _rows: int
        _cols: int
    """

    _items: dict[tuple[int, int], tuple[str, int]]
    _rows: int
    _cols: int

    @property
    def total_iron(self) -> int:
        """Total iron across all cells."""
        return self.count_item("iron")

    @property
    def iron(self) -> int:
        return self.total_iron

    def count_item(self, item_type: str) -> int:
        """Count total items of the given type across all cells."""
        total = 0
        for (it, ct) in self._items.values():
            if it == item_type:
                total += ct
        return total

    def add_item(self, item_type: str, count: int = 1) -> None:
        """Add items to the first available cell or stack on existing."""
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

    def consolidate(self) -> None:
        """Merge stacks of the same item type, respecting max stack sizes."""
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
