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

    Tracks stackable resources (iron) separately from slot items.
    Supports mouse drag-and-drop to rearrange items between cells.
    """

    def __init__(self, iron_icon: Optional[arcade.Texture] = None) -> None:
        # items: dict[(row, col)] -> item name string; absent key = empty slot
        self._items: dict[tuple[int, int], str] = {}
        self.open: bool = False
        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None  # tests may run without a window

        # Stackable resource totals
        self.iron: int = 0
        self._iron_icon: Optional[arcade.Texture] = iron_icon
        # Cell that currently displays the iron stack (draggable)
        self._iron_cell: tuple[int, int] = (0, 0)

        # Drag-and-drop state
        self._drag_type: Optional[str] = None        # item name or "iron"
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
        # Iron count label (reused in cell and while dragging)
        self._t_iron = arcade.Text("", 0, 0, arcade.color.ORANGE, 9, bold=True)
        # Generic item text labels
        self._t_item_label = arcade.Text("", 0, 0, arcade.color.WHITE, 8)
        self._t_drag_label = arcade.Text("", 0, 0, arcade.color.WHITE, 8)
        self._t_tooltip = arcade.Text(
            "", 0, 0, arcade.color.WHITE, 9,
            anchor_x="center", anchor_y="center",
        )

    # ── Public API ──────────────────────────────────────────────────────────
    def add_iron(self, amount: int) -> None:
        self.iron += amount

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
        # Iron stack has priority in its display cell
        if self.iron > 0 and cell == self._iron_cell:
            self._drag_type = "iron"
            self._drag_src = cell
            self._drag_x = x
            self._drag_y = y
            return True
        # Named item
        item = self._items.get(cell)
        if item is not None:
            self._drag_type = item
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

        target = self._cell_at(x, y)

        if target is None and not self._panel_contains(x, y):
            # ── Ejected outside the inventory panel -> drop into world ─────
            ejected_type = self._drag_type
            if ejected_type == "iron":
                ejected_amount = self.iron
                self.iron = 0
            else:
                ejected_amount = 1
            self._drag_type = None
            self._drag_src = None
            return (ejected_type, ejected_amount)

        if target is None:
            # Dropped on panel header/border -- return to source cell
            target = self._drag_src

        assert target is not None
        if self._drag_type == "iron":
            existing = self._items.get(target)
            if existing is not None:
                self._items[self._drag_src] = existing
                del self._items[target]
            self._iron_cell = target
        else:
            existing = self._items.get(target)
            if existing is not None:
                self._items[self._drag_src] = existing
            elif self._drag_src in self._items:
                del self._items[self._drag_src]
            self._items[target] = self._drag_type

        self._drag_type = None
        self._drag_src = None
        return None

    # ── Drawing ─────────────────────────────────────────────────────────────
    def _draw_iron_in_cell(
        self, cell_x: float, cell_y: float, alpha: int = 255
    ) -> None:
        """Draw the iron icon + count badge anchored at the bottom-left of a cell."""
        if self._iron_icon is not None:
            icon_scale = (INV_CELL - 12) / max(
                self._iron_icon.width, self._iron_icon.height
            )
            arcade.draw_texture_rect(
                self._iron_icon,
                arcade.LBWH(
                    cell_x + 6, cell_y + 6,
                    self._iron_icon.width * icon_scale,
                    self._iron_icon.height * icon_scale,
                ),
                alpha=alpha,
            )
        self._t_iron.text = str(self.iron)
        self._t_iron.x = cell_x + INV_CELL - 4
        self._t_iron.y = cell_y + 3
        self._t_iron.anchor_x = "right"
        self._t_iron.draw()

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
                has_iron = (self.iron > 0 and cell == self._iron_cell)
                occupied = (item is not None) or has_iron

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
                if not is_src:
                    if has_iron:
                        self._draw_iron_in_cell(cx_, cy_)
                    elif item is not None:
                        self._t_item_label.text = item[:6]
                        self._t_item_label.x = cx_ + 4
                        self._t_item_label.y = cy_ + INV_CELL // 2 - 5
                        self._t_item_label.draw()

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
            if self._drag_type == "iron":
                self._draw_iron_in_cell(fx, fy, alpha=200)
            else:
                self._t_drag_label.text = self._drag_type[:6]
                self._t_drag_label.x = fx + 4
                self._t_drag_label.y = fy + INV_CELL // 2 - 5
                self._t_drag_label.draw()

        # ── Hover tooltip ──────────────────────────────────────────────────
        tip_cell = self._cell_at(self._mouse_x, self._mouse_y)
        if tip_cell is not None and self._drag_type is None:
            row, col = tip_cell
            is_iron = (self.iron > 0 and tip_cell == self._iron_cell)
            item = self._items.get(tip_cell)
            if is_iron:
                tip_label = f"Iron  \u00d7{self.iron}"
            elif item is not None:
                tip_label = item
            else:
                tip_label = None

            if tip_label:
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
