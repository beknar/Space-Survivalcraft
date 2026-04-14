"""Tests for inventory.py — grid math, item management, drag-and-drop."""
from __future__ import annotations

import pytest

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    INV_COLS, INV_ROWS, INV_CELL, INV_PAD, INV_HEADER, INV_FOOTER, INV_W, INV_H,
)
from inventory import Inventory


@pytest.fixture
def inv():
    # Force fallback to default SCREEN_WIDTH/SCREEN_HEIGHT geometry so the
    # grid-math assertions below hold regardless of whether an earlier
    # integration test left an arcade.Window (of a different size) open.
    iv = Inventory(iron_icon=None)
    iv._window = None
    return iv


class TestInventoryToggle:
    def test_starts_closed(self, inv):
        assert inv.open is False

    def test_toggle_opens(self, inv):
        inv.toggle()
        assert inv.open is True

    def test_toggle_closes(self, inv):
        inv.toggle()
        inv.toggle()
        assert inv.open is False


class TestIronManagement:
    def test_initial_iron_zero(self, inv):
        assert inv.iron == 0
        assert inv.total_iron == 0

    def test_add_iron(self, inv):
        inv.add_iron(10)
        assert inv.iron == 10
        assert inv.total_iron == 10

    def test_add_iron_accumulates(self, inv):
        inv.add_iron(10)
        inv.add_iron(5)
        assert inv.iron == 15

    def test_add_iron_stored_as_item(self, inv):
        inv.add_item("iron", 20)
        assert inv.total_iron == 20
        assert inv.count_item("iron") == 20

    def test_remove_iron(self, inv):
        inv.add_item("iron", 50)
        removed = inv.remove_item("iron", 20)
        assert removed == 20
        assert inv.total_iron == 30

    def test_remove_iron_partial(self, inv):
        inv.add_item("iron", 10)
        removed = inv.remove_item("iron", 20)
        assert removed == 10
        assert inv.total_iron == 0


class TestItemStacking:
    def test_items_stack_on_same_type(self, inv):
        inv.add_item("repair_pack", 3)
        inv.add_item("repair_pack", 2)
        assert inv.count_item("repair_pack") == 5
        # Should be in one cell
        cells_with_pack = [c for c, (t, n) in inv._items.items() if t == "repair_pack"]
        assert len(cells_with_pack) == 1

    def test_different_types_separate_cells(self, inv):
        inv.add_item("iron", 10)
        inv.add_item("repair_pack", 3)
        assert inv.count_item("iron") == 10
        assert inv.count_item("repair_pack") == 3
        assert len(inv._items) == 2


def _inv_window_dims(inv):
    """Use the inventory's own window (matches what _cell_at sees).

    Tests used to hardcode SCREEN_WIDTH/SCREEN_HEIGHT, but Inventory reads
    from `arcade.get_window()` when available. If an earlier integration
    test created a real Window with different dimensions, the test-side
    grid math drifts from the production-side grid math.
    """
    sw = inv._window.width if inv._window else SCREEN_WIDTH
    sh = inv._window.height if inv._window else SCREEN_HEIGHT
    return sw, sh


class TestCellAt:
    """Test the _cell_at method for mapping screen coords to grid cells."""

    def _grid_origin(self, inv):
        sw, sh = _inv_window_dims(inv)
        ox = (sw - INV_W) // 2
        oy = (sh - INV_H) // 2
        return ox + INV_PAD, oy + INV_PAD + INV_FOOTER

    def test_valid_cell_top_left(self, inv):
        gx, gy = self._grid_origin(inv)
        # Bottom-left of grid is row=INV_ROWS-1, col=0 in screen space
        cell = inv._cell_at(gx + 1, gy + 1)
        assert cell is not None
        row, col = cell
        assert col == 0
        assert row == INV_ROWS - 1  # bottom of screen = last row

    def test_valid_cell_centre(self, inv):
        gx, gy = self._grid_origin(inv)
        cx = gx + INV_CELL * 2 + INV_CELL // 2
        cy = gy + INV_CELL * 2 + INV_CELL // 2
        cell = inv._cell_at(cx, cy)
        assert cell is not None
        row, col = cell
        assert col == 2
        assert row == 2

    def test_out_of_bounds_left(self, inv):
        gx, gy = self._grid_origin(inv)
        assert inv._cell_at(gx - 10, gy + 10) is None

    def test_out_of_bounds_below(self, inv):
        gx, gy = self._grid_origin(inv)
        assert inv._cell_at(gx + 10, gy - 10) is None

    def test_out_of_bounds_right(self, inv):
        gx, gy = self._grid_origin(inv)
        assert inv._cell_at(gx + INV_COLS * INV_CELL + 10, gy + 10) is None

    def test_out_of_bounds_above(self, inv):
        gx, gy = self._grid_origin(inv)
        assert inv._cell_at(gx + 10, gy + INV_ROWS * INV_CELL + 10) is None


class TestPanelContains:
    def test_inside_panel(self, inv):
        sw, sh = _inv_window_dims(inv)
        cx = sw // 2
        cy = sh // 2
        assert inv._panel_contains(cx, cy) is True

    def test_outside_panel(self, inv):
        assert inv._panel_contains(0, 0) is False


class TestDragAndDrop:
    def _grid_origin(self, inv):
        sw, sh = _inv_window_dims(inv)
        ox = (sw - INV_W) // 2
        oy = (sh - INV_H) // 2
        return ox + INV_PAD, oy + INV_PAD + INV_FOOTER

    def test_pick_up_iron(self, inv):
        inv.open = True
        inv.add_item("iron", 10)
        # Find which cell iron ended up in
        iron_cell = None
        for cell, (it, ct) in inv._items.items():
            if it == "iron":
                iron_cell = cell
                break
        assert iron_cell is not None
        gx, gy = self._grid_origin(inv)
        row, col = iron_cell
        cx = gx + col * INV_CELL + INV_CELL // 2
        cy = gy + (INV_ROWS - 1 - row) * INV_CELL + INV_CELL // 2
        result = inv.on_mouse_press(cx, cy)
        assert result is True
        assert inv._drag_type == "iron"
        assert inv._drag_amount == 10

    def test_drop_iron_in_new_cell(self, inv):
        inv.open = True
        # Simulate drag in progress (item already removed from _items)
        inv._drag_type = "iron"
        inv._drag_amount = 10
        inv._drag_src = (0, 0)
        gx, gy = self._grid_origin(inv)
        # Drop in cell (0, 1)
        cx = gx + INV_CELL + INV_CELL // 2
        cy = gy + (INV_ROWS - 1) * INV_CELL + INV_CELL // 2
        result = inv.on_mouse_release(cx, cy)
        assert result is None  # no ejection
        assert inv._items[(0, 1)] == ("iron", 10)

    def test_drop_outside_panel_ejects(self, inv):
        inv.open = True
        # Simulate drag in progress (item already removed from _items)
        inv._drag_type = "iron"
        inv._drag_amount = 10
        inv._drag_src = (0, 0)
        # Drop far outside
        result = inv.on_mouse_release(0, 0)
        assert result is not None
        assert result[0] == "iron"
        assert result[1] == 10
        assert inv.total_iron == 0

    def test_drop_on_panel_border_returns_to_source(self, inv):
        inv.open = True
        # Simulate drag in progress (item already removed from _items)
        inv._drag_type = "iron"
        inv._drag_amount = 10
        inv._drag_src = (0, 0)
        # Drop inside panel but outside grid (on header area)
        sw, sh = _inv_window_dims(inv)
        ox = (sw - INV_W) // 2
        oy = (sh - INV_H) // 2
        result = inv.on_mouse_release(ox + INV_W // 2, oy + INV_H - 5)
        assert result is None
        assert inv._items[(0, 0)] == ("iron", 10)

    def test_no_drag_when_closed(self, inv):
        inv.open = False
        inv.add_item("iron", 10)
        sw, sh = _inv_window_dims(inv)
        result = inv.on_mouse_press(sw // 2, sh // 2)
        assert result is False

    def test_stack_on_drop(self, inv):
        """Dropping iron onto an existing iron cell should merge counts."""
        inv.open = True
        inv._items[(0, 0)] = ("iron", 5)
        # Simulate drag in progress from (0,1) — item already removed
        inv._drag_type = "iron"
        inv._drag_amount = 10
        inv._drag_src = (0, 1)
        gx, gy = self._grid_origin(inv)
        cx = gx + INV_CELL // 2
        cy = gy + (INV_ROWS - 1) * INV_CELL + INV_CELL // 2
        result = inv.on_mouse_release(cx, cy)
        assert result is None
        assert inv._items[(0, 0)] == ("iron", 15)


class TestRenderCacheDirtyFlag:
    """The dirty flag controls whether the cached SpriteList renderer rebuilds.

    If a mutator forgets to call _mark_dirty, the inventory will silently
    render stale icons — these tests lock down the contract so it can't
    regress without a test failure.
    """

    def test_starts_dirty(self, inv):
        # Newly constructed inventory has no cache yet → must be dirty
        assert inv._render_dirty is True

    def test_add_item_marks_dirty(self, inv):
        inv._render_dirty = False
        inv.add_item("iron", 5)
        assert inv._render_dirty is True

    def test_add_item_to_existing_stack_marks_dirty(self, inv):
        inv.add_item("iron", 5)
        inv._render_dirty = False
        inv.add_item("iron", 3)  # bumps existing stack
        assert inv._render_dirty is True

    def test_remove_item_marks_dirty(self, inv):
        inv.add_item("iron", 10)
        inv._render_dirty = False
        inv.remove_item("iron", 5)
        assert inv._render_dirty is True

    def test_remove_zero_does_not_mark_dirty(self, inv):
        # Removing a non-existent item shouldn't dirty the cache
        inv._render_dirty = False
        inv.remove_item("missile", 1)  # nothing to remove
        assert inv._render_dirty is False

    def test_consolidate_marks_dirty(self, inv):
        inv.add_item("iron", 5)
        inv.add_item("iron", 3)
        inv._render_dirty = False
        inv.consolidate()
        assert inv._render_dirty is True

    def test_start_drag_marks_dirty(self, inv):
        inv.add_item("iron", 5)
        # add_item will have placed iron at (0, 0)
        inv._render_dirty = False
        inv._start_drag((0, 0), 100.0, 100.0)
        assert inv._render_dirty is True

    def test_finish_drag_marks_dirty(self, inv):
        inv.add_item("iron", 5)
        inv._start_drag((0, 0), 100.0, 100.0)
        inv._render_dirty = False
        inv._finish_drag((0, 1))
        assert inv._render_dirty is True

    def test_clear_drag_marks_dirty(self, inv):
        inv.add_item("iron", 5)
        inv._start_drag((0, 0), 100.0, 100.0)
        inv._render_dirty = False
        inv._clear_drag()
        assert inv._render_dirty is True

    def test_mark_dirty_helper(self, inv):
        inv._render_dirty = False
        inv._mark_dirty()
        assert inv._render_dirty is True

    def test_render_cache_attrs_initialised(self, inv):
        # The cache fields should exist even before the first build
        assert inv._cache_icon_list is None
        assert inv._cache_fill_list is None
        assert inv._cache_badge_list is None
        assert inv._cache_origin == (-1, -1)

