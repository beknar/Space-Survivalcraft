"""Performance integration tests — inventory overlays.

Frame-time / FPS coverage for the inventory rendering systems:

  * Ship cargo inventory (5x5) and station inventory (10x10) both
    open with all cells filled — the worst-case 125-cell badge
    + count-text overlay.

Run with:  ``pytest "unit tests/integration/test_performance_inventory.py" -v``
"""
from __future__ import annotations

import time

import arcade
import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BUILDING_TYPES, MODULE_SLOT_COUNT,
)
from zones import ZoneID

# ── Configuration ──────────────────────────────────────────────────────────

MIN_FPS = 40

# Use shared measure_fps from conftest
from integration.conftest import measure_fps as _measure_fps


# ═══════════════════════════════════════════════════════════════════════════
#  Both inventories open (the 40 FPS drop the user reported)
# ═══════════════════════════════════════════════════════════════════════════

class TestInventoriesOpen:
    def test_both_inventories_open_above_threshold(self, real_game_view):
        """Ship cargo (5x5) and station inventory (10x10) both open with
        items in most slots. This stresses the per-frame inventory
        rendering which previously caused sub-40 FPS drops."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Fill ship inventory (25 cells)
        gv.inventory._items.clear()
        for r in range(5):
            for c in range(5):
                gv.inventory._items[(r, c)] = ("iron", 10 + r * 5 + c)
        gv.inventory._mark_dirty()
        gv.inventory.open = True

        # Fill station inventory (100 cells — worst case)
        gv._station_inv._items.clear()
        for r in range(10):
            for c in range(10):
                gv._station_inv._items[(r, c)] = ("iron", r * 10 + c + 1)
        gv._station_inv._mark_dirty()
        gv._station_inv.open = True

        fps = _measure_fps(gv)

        # Close to avoid polluting later tests
        gv.inventory.open = False
        gv._station_inv.open = False

        assert fps >= MIN_FPS, (
            f"Both inventories open (125 cells): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
