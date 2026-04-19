"""Shared inventory operations that span ship + station inventories.

Extracted to eliminate the ship-first-then-station deduction pattern
that was duplicated across ``combat_helpers``, ``building_manager``,
and ``ship_manager``.  All three now call ``deduct_resources``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_view import GameView


def deduct_resources(gv: "GameView", iron: int, copper: int = 0) -> None:
    """Deduct ``iron`` and ``copper`` from the player's inventories.

    Pulls from the ship's carry-inventory first, falls back to the
    station inventory for whatever's left.  Silently tolerates
    partial shortages (the caller is expected to have already
    checked totals).  Each resource is handled independently.
    """
    if iron > 0:
        remaining = iron
        ship_iron = min(remaining, gv.inventory.total_iron)
        if ship_iron > 0:
            gv.inventory.remove_item("iron", ship_iron)
            remaining -= ship_iron
        if remaining > 0:
            gv._station_inv.remove_item("iron", remaining)

    if copper > 0:
        remaining_cu = copper
        ship_cu = min(remaining_cu, gv.inventory.count_item("copper"))
        if ship_cu > 0:
            gv.inventory.remove_item("copper", ship_cu)
            remaining_cu -= ship_cu
        if remaining_cu > 0:
            gv._station_inv.remove_item("copper", remaining_cu)
