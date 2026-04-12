"""Inventory (cargo hold) UI overlay."""
from __future__ import annotations

from typing import Optional

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    INV_COLS, INV_ROWS, INV_CELL, INV_PAD, INV_HEADER, INV_FOOTER, INV_W, INV_H,
)
from base_inventory import BaseInventoryData


class Inventory(BaseInventoryData):
    """5x5 cargo hold grid drawn as a modal overlay.

    All items (iron, repair_pack, etc.) are stored as (type, count) tuples
    in grid cells and support stacking.
    """

    def __init__(
        self,
        iron_icon: Optional[arcade.Texture] = None,
        repair_pack_icon: Optional[arcade.Texture] = None,
        shield_recharge_icon: Optional[arcade.Texture] = None,
    ) -> None:
        self._items: dict[tuple[int, int], tuple[str, int]] = {}
        self._rows = INV_ROWS
        self._cols = INV_COLS
        self.open: bool = False
        self._init_window()
        self._init_icons(iron_icon, repair_pack_icon, shield_recharge_icon)
        self._init_drag_state()
        self._item_names: dict[str, str] = {"iron": "Iron", "copper": "Copper", "repair_pack": "Repair Pack", "shield_recharge": "Shield Recharge", "missile": "Homing Missile"}

        _sw, _sh = self._screen_size()
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
        self._t_consolidate = arcade.Text(
            "Consolidate", 0, 0, arcade.color.WHITE, 8, bold=True,
            anchor_x="center", anchor_y="center",
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

    def add_iron(self, amount: int) -> None:
        """Backward-compat helper — delegates to add_item."""
        self.add_item("iron", amount)

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
        # Consolidate button (above panel)
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        ox = (sw - INV_W) // 2
        oy = (sh - INV_H) // 2
        cbw, cbh = 70, 20
        cbx = ox + (INV_W - cbw) // 2
        cby = oy + INV_H + 4
        if cbx <= x <= cbx + cbw and cby <= y <= cby + cbh:
            self.consolidate()
            return True
        cell = self._cell_at(x, y)
        if cell is None:
            return False
        return self._start_drag(cell, x, y)

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

        # Check if dropped on station inventory panel — treat as cross-transfer
        from station_inventory import _INV_W as _SI_W, _INV_H as _SI_H
        try:
            from constants import INV_W as _ship_w
            sw, sh = self._screen_size()
            ship_left = (sw - _ship_w) // 2
            si_ox = max(4, ship_left - _SI_W - 10)
            si_oy = (sh - _SI_H) // 2
            if si_ox <= x <= si_ox + _SI_W and si_oy <= y <= si_oy + _SI_H:
                return self._clear_drag()
        except ImportError:
            pass

        target = self._cell_at(x, y)

        if target is None and not self._panel_contains(x, y):
            return self._clear_drag()

        if target is None:
            target = self._drag_src

        self._finish_drag(target)
        return None

    # ── Drawing ─────────────────────────────────────────────────────────────
    def _draw_item_in_cell(
        self, item_type: str, count: int, cell_x: float, cell_y: float, alpha: int = 255
    ) -> None:
        """Draw an item icon + count badge in a cell."""
        icon = self._resolve_icon(item_type)
        if icon is not None:
            isz = INV_CELL - 12
            arcade.draw_texture_rect(
                icon,
                arcade.LBWH(cell_x + 6, cell_y + 6, isz, isz),
                alpha=alpha,
            )
        else:
            self._t_item_label.text = item_type[:6]
            self._t_item_label.x = cell_x + 4
            self._t_item_label.y = cell_y + INV_CELL // 2 - 5
            self._t_item_label.draw()

        self._draw_count_badge(count, cell_x, cell_y, INV_CELL)
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
        # Consolidate button (above panel)
        cbw, cbh = 70, 20
        cbx = ox + (INV_W - cbw) // 2
        cby = oy + INV_H + 4
        arcade.draw_rect_filled(arcade.LBWH(cbx, cby, cbw, cbh), (40, 60, 40, 220))
        arcade.draw_rect_outline(arcade.LBWH(cbx, cby, cbw, cbh),
                                 arcade.color.LIME_GREEN, border_width=1)
        self._t_consolidate.x = cbx + cbw // 2; self._t_consolidate.y = cby + cbh // 2
        self._t_consolidate.draw()

        self._t_title.draw()

        # Determine which cell the cursor is hovering over (for highlight)
        hover_cell = self._cell_at(self._drag_x, self._drag_y) if self._drag_type else None

        # Grid: single background + batched grid lines
        grid_w = INV_COLS * INV_CELL
        grid_h = INV_ROWS * INV_CELL
        arcade.draw_rect_filled(
            arcade.LBWH(gx, gy, grid_w, grid_h), (30, 30, 60, 200))
        line_pts: list[tuple[float, float]] = []
        for r in range(INV_ROWS + 1):
            ly = gy + r * INV_CELL
            line_pts.append((gx, ly))
            line_pts.append((gx + grid_w, ly))
        for c in range(INV_COLS + 1):
            lx = gx + c * INV_CELL
            line_pts.append((lx, gy))
            line_pts.append((lx, gy + grid_h))
        arcade.draw_lines(line_pts, (60, 80, 120), 1)

        # Batched cell fills + icons + count badges via cached SpriteLists
        # (rebuilt only on item change). Replaces dozens of GPU calls with 3.
        self._ensure_render_cache(gx, gy, INV_CELL)
        if self._cache_fill_list is not None and len(self._cache_fill_list) > 0:
            self._cache_fill_list.draw()
        if self._cache_icon_list is not None and len(self._cache_icon_list) > 0:
            self._cache_icon_list.draw()
        if self._cache_badge_list is not None and len(self._cache_badge_list) > 0:
            self._cache_badge_list.draw()

        # Drag-source / hover overlays (1–2 cells, cheap per-frame).
        if self._drag_src is not None and self._drag_type is not None:
            row, col = self._drag_src
            cx_ = gx + col * INV_CELL
            cy_ = gy + (INV_ROWS - 1 - row) * INV_CELL
            arcade.draw_rect_filled(
                arcade.LBWH(cx_ + 1, cy_ + 1, INV_CELL - 2, INV_CELL - 2),
                (60, 60, 20, 200))
        if hover_cell is not None and hover_cell not in self._items:
            row, col = hover_cell
            cx_ = gx + col * INV_CELL
            cy_ = gy + (INV_ROWS - 1 - row) * INV_CELL
            arcade.draw_rect_filled(
                arcade.LBWH(cx_ + 1, cy_ + 1, INV_CELL - 2, INV_CELL - 2),
                (50, 70, 100, 220))

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
                name = self._item_names.get(it, it)
                tip_label = f"{name}  \u00d7{ct}"
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
