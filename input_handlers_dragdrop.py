"""Mouse drag / release / building-move / inventory-eject handlers.

Extracted from ``input_handlers`` in the 2026-05-10 split.  Holds
the long-press building-move state machine, the drag-then-release
flow that swaps modules and quick-use slots, and the four small
``_eject_to_*`` routines that route an ejected ship-inventory item
to the right destination based on what's under the cursor.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    SHIP_RADIUS, EJECT_DIST, WORLD_ITEM_LIFETIME,
    STATION_INFO_RANGE, TURRET_FREE_PLACE_RADIUS,
    QUICK_USE_SLOTS,
)
from sprites.building import HomeStation, Turret, MissileArray

from input_handlers_mouse import _screen_to_world

if TYPE_CHECKING:
    from game_view import GameView


def _try_start_building_move(gv: GameView, x: int, y: int) -> bool:
    """If the click is over a movable building (Turret or MissileArray)
    close to the player, arm the long-press timer and consume the click.

    Release before the threshold cancels; holding past it enters move mode.
    """
    import time as _time
    wx, wy = _screen_to_world(gv, x, y)
    px, py = gv.player.center_x, gv.player.center_y
    best = None
    best_dist = 40.0
    for b in gv.building_list:
        if not isinstance(b, (Turret, MissileArray)):
            continue
        d = math.hypot(wx - b.center_x, wy - b.center_y)
        if d < best_dist:
            best_dist = d
            best = b
    if best is None:
        return False
    if math.hypot(px - best.center_x, py - best.center_y) >= STATION_INFO_RANGE:
        return False
    gv._move_candidate = best
    gv._move_press_time = _time.monotonic()
    gv._move_origin_x = best.center_x
    gv._move_origin_y = best.center_y
    return True


def _update_pending_building_move(gv: GameView, x: int, y: int) -> None:
    """Promote a held LMB into active move mode once the threshold elapses,
    and keep the moving building's position synced with the cursor."""
    import time as _time
    from constants import MOVE_LONG_PRESS_TIME
    if gv._move_candidate is not None and gv._moving_building is None:
        if (_time.monotonic() - gv._move_press_time) >= MOVE_LONG_PRESS_TIME:
            gv._moving_building = gv._move_candidate
            gv._move_candidate = None
    if gv._moving_building is not None:
        wx, wy = _screen_to_world(gv, x, y)
        gv._moving_building.center_x, gv._moving_building.center_y = (
            _clamp_turret_position(gv, wx, wy))


def _clamp_turret_position(gv, wx: float, wy: float) -> tuple[float, float]:
    """Clamp world coords to within TURRET_FREE_PLACE_RADIUS of the
    active Home Station so the turret can never be dragged outside the
    allowed zone. Falls back to (wx, wy) if no Home Station is present."""
    home = next((b for b in gv.building_list if isinstance(b, HomeStation)), None)
    if home is None:
        return wx, wy
    dx = wx - home.center_x
    dy = wy - home.center_y
    d = math.hypot(dx, dy)
    if d <= TURRET_FREE_PLACE_RADIUS or d <= 0.0:
        return wx, wy
    scale = TURRET_FREE_PLACE_RADIUS / d
    return home.center_x + dx * scale, home.center_y + dy * scale


def _finish_building_move(gv: GameView, x: int, y: int) -> bool:
    """LMB release while a move is pending or active. Returns True if the
    release was consumed (i.e. the caller should skip other release logic)."""
    if gv._moving_building is not None:
        building = gv._moving_building
        gv._moving_building = None
        wx, wy = _screen_to_world(gv, x, y)
        if _is_valid_move_target(gv, building, wx, wy):
            building.center_x = wx
            building.center_y = wy
        else:
            building.center_x = gv._move_origin_x
            building.center_y = gv._move_origin_y
        return True
    if gv._move_candidate is not None:
        gv._move_candidate = None
        return True
    return False


def _is_valid_move_target(gv, building, wx: float, wy: float) -> bool:
    """Turret/MissileArray must stay within TURRET_FREE_PLACE_RADIUS of an
    active Home Station and clear of other buildings."""
    from constants import BUILDING_RADIUS
    home = next((b for b in gv.building_list if isinstance(b, HomeStation)), None)
    if home is None or home.disabled:
        return False
    if math.hypot(wx - home.center_x, wy - home.center_y) > TURRET_FREE_PLACE_RADIUS:
        return False
    for other in gv.building_list:
        if other is building:
            continue
        if math.hypot(wx - other.center_x,
                      wy - other.center_y) < BUILDING_RADIUS * 2:
            return False
    return True


def handle_mouse_drag(
    gv: GameView, x: int, y: int, dx: int, dy: int, buttons: int, modifiers: int
) -> None:
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_motion(x, y)
        return
    if gv._hud._qu_drag_src is not None:
        gv._hud._qu_drag_x = x
        gv._hud._qu_drag_y = y
    if gv._hud._mod_drag_src is not None:
        gv._hud._mod_drag_x = x
        gv._hud._mod_drag_y = y
    if gv._move_candidate is not None or gv._moving_building is not None:
        _update_pending_building_move(gv, x, y)
    gv._station_inv.on_mouse_drag(x, y)
    gv.inventory.on_mouse_drag(x, y)


def handle_mouse_release(gv: GameView, x: int, y: int, button: int, modifiers: int) -> None:
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_release(x, y)
        return
    if button != arcade.MOUSE_BUTTON_LEFT:
        return
    if gv._trade_menu.open:
        gv._trade_menu.on_mouse_release(x, y)
    if gv._build_menu.open:
        gv._build_menu.on_mouse_release(x, y)
    if gv._craft_menu.open:
        gv._craft_menu.on_mouse_release(x, y)
    if _finish_building_move(gv, x, y):
        return
    if gv._hud._mod_drag_src is not None:
        src = gv._hud._mod_drag_src
        mod_type = gv._hud._mod_drag_type
        gv._hud._mod_drag_src = None
        gv._hud._mod_drag_type = None
        target = gv._hud.module_slot_at(x, y)
        if target is not None and target != src:
            other = gv._module_slots[target]
            gv._module_slots[target] = mod_type
            gv._module_slots[src] = other
        elif target == src:
            pass
        else:
            gv._module_slots[src] = None
            gv.inventory.add_item(f"mod_{mod_type}", 1)
        gv.player.apply_modules(gv._module_slots)
        gv._hud._mod_slots = list(gv._module_slots)
        return
    if gv._hud._qu_drag_src is not None:
        src = gv._hud._qu_drag_src
        dt = gv._hud._qu_drag_type
        dc = gv._hud._qu_drag_count
        gv._hud._qu_drag_src = None
        gv._hud._qu_drag_type = None
        gv._hud._qu_drag_count = 0
        target = gv._hud.slot_at(x, y)
        if target is not None and target != src:
            dst_type = gv._hud.get_quick_use(target)
            dst_count = gv._hud._qu_counts[target]
            gv._hud.set_quick_use(target, dt, dc)
            gv._hud.set_quick_use(src, dst_type, dst_count)
        elif target == src:
            if dt == "repair_pack":
                gv._use_repair_pack(src)
            elif dt == "shield_recharge":
                gv._use_shield_recharge(src)
            elif dt == "missile":
                gv._fire_missile(src)
        else:
            gv._hud.set_quick_use(src, None, 0)
        return
    station_drop = gv._station_inv.on_mouse_release(x, y)
    if station_drop is not None:
        _handle_station_drop(gv, x, y, station_drop)
    ejected = gv.inventory.on_mouse_release(x, y)
    if ejected is not None:
        _handle_inventory_eject(gv, x, y, ejected)


def _handle_station_drop(
    gv: GameView, x: int, y: int, drop: tuple[str, int]
) -> None:
    """Handle an item dropped from station inventory."""
    item_type, amount = drop
    is_module = item_type.startswith("mod_") or item_type.startswith("bp_")
    if is_module and item_type.startswith("mod_"):
        from constants import MODULE_SLOT_COUNT, SHIP_LEVEL_MODULE_BONUS
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        for ps in gv._parked_ships:
            if math.hypot(wx - ps.center_x, wy - ps.center_y) < 40:
                mod_key = item_type[len("mod_"):]
                slot_count = MODULE_SLOT_COUNT + (
                    ps.ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
                while len(ps.module_slots) < slot_count:
                    ps.module_slots.append(None)
                if mod_key in ps.module_slots:
                    gv._station_inv.add_item(item_type, amount)
                    return
                for i, existing in enumerate(ps.module_slots):
                    if existing is None:
                        ps.module_slots[i] = mod_key
                        if amount > 1:
                            gv._station_inv.add_item(item_type, amount - 1)
                        return
                gv._station_inv.add_item(item_type, amount)
                return
    mod_slot = gv._hud.module_slot_at(x, y)
    if mod_slot is not None and is_module:
        prefix = "mod_" if item_type.startswith("mod_") else "bp_"
        mod_key = item_type[len(prefix):]
        if mod_key in gv._module_slots:
            gv._station_inv.add_item(item_type, amount)
        else:
            old = gv._module_slots[mod_slot]
            if old is not None:
                gv._station_inv.add_item(f"mod_{old}", 1)
            gv._module_slots[mod_slot] = mod_key
            if amount > 1:
                gv._station_inv.add_item(item_type, amount - 1)
            gv.player.apply_modules(gv._module_slots)
            gv._hud._mod_slots = list(gv._module_slots)
    elif mod_slot is not None:
        gv._station_inv.add_item(item_type, amount)
    elif (qu_slot := gv._hud.slot_at(x, y)) is not None and item_type in ("repair_pack", "shield_recharge", "missile"):
        gv.inventory.add_item(item_type, amount)
        total = gv.inventory.count_item(item_type)
        for s in range(QUICK_USE_SLOTS):
            if s != qu_slot and gv._hud.get_quick_use(s) == item_type:
                gv._hud.set_quick_use(s, None, 0)
        gv._hud.set_quick_use(qu_slot, item_type, total)
    else:
        target_cell = gv.inventory._cell_at(x, y)
        if (target_cell is not None
                and target_cell not in gv.inventory._items):
            gv.inventory._items[target_cell] = (item_type, amount)
            gv.inventory._mark_dirty()
        else:
            nearest = gv.inventory._nearest_empty_cell(x, y)
            if nearest is not None:
                gv.inventory._items[nearest] = (item_type, amount)
                gv.inventory._mark_dirty()
            else:
                gv.inventory.add_item(item_type, amount)
        if item_type in ("repair_pack", "shield_recharge", "missile"):
            for slot in range(QUICK_USE_SLOTS):
                if gv._hud.get_quick_use(slot) == item_type:
                    gv._hud.set_quick_use(
                        slot, item_type,
                        gv.inventory.count_item(item_type),
                    )


def _eject_to_module_slot(
    gv: GameView, mod_slot: int, item_type: str, amount: int,
) -> None:
    """Try to equip a module/blueprint into a HUD module slot. Falls back to
    returning the item to inventory if the module key is already equipped or
    the item is not a module."""
    is_module = item_type.startswith("mod_") or item_type.startswith("bp_")
    if not is_module:
        gv.inventory.add_item(item_type, amount)
        return
    prefix = "mod_" if item_type.startswith("mod_") else "bp_"
    mod_key = item_type[len(prefix):]
    if mod_key in gv._module_slots:
        gv.inventory.add_item(item_type, amount)
        return
    old = gv._module_slots[mod_slot]
    if old is not None:
        gv.inventory.add_item(f"mod_{old}", 1)
    gv._module_slots[mod_slot] = mod_key
    if amount > 1:
        gv.inventory.add_item(item_type, amount - 1)
    gv.player.apply_modules(gv._module_slots)
    gv._hud._mod_slots = list(gv._module_slots)


def _eject_to_quick_use(
    gv: GameView, qu_slot: int, item_type: str, amount: int,
) -> None:
    """Assign a consumable to a quick-use slot. Returns the item to inventory
    first so the slot count reflects the full stack."""
    gv.inventory.add_item(item_type, amount)
    if item_type not in ("repair_pack", "shield_recharge", "missile"):
        return
    total = gv.inventory.count_item(item_type)
    for s in range(QUICK_USE_SLOTS):
        if s != qu_slot and gv._hud.get_quick_use(s) == item_type:
            gv._hud.set_quick_use(s, None, 0)
    gv._hud.set_quick_use(qu_slot, item_type, total)


def _eject_to_station_inv(
    gv: GameView, x: int, y: int, item_type: str, amount: int,
) -> None:
    """Drop an item into the station inventory at (x, y), preferring the
    cell under the cursor and falling back to the nearest empty one."""
    target_cell = gv._station_inv._cell_at(x, y)
    if target_cell is not None and target_cell not in gv._station_inv._items:
        gv._station_inv._items[target_cell] = (item_type, amount)
        gv._station_inv._mark_dirty()
        return
    nearest = gv._station_inv._nearest_empty_cell(x, y)
    if nearest is not None:
        gv._station_inv._items[nearest] = (item_type, amount)
        gv._station_inv._mark_dirty()
    else:
        gv._station_inv.add_item(item_type, amount)


def _eject_iron_to_world(gv: GameView, amount: int) -> None:
    """Spawn an iron pickup just outside the player ship."""
    eject_angle = random.uniform(0.0, math.tau)
    eject_r = SHIP_RADIUS + EJECT_DIST
    eject_x = max(0.0, min(WORLD_WIDTH,
                  gv.player.center_x + math.cos(eject_angle) * eject_r))
    eject_y = max(0.0, min(WORLD_HEIGHT,
                  gv.player.center_y + math.sin(eject_angle) * eject_r))
    gv._spawn_iron_pickup(
        eject_x, eject_y, amount=amount, lifetime=WORLD_ITEM_LIFETIME,
    )


def _handle_inventory_eject(
    gv: GameView, x: int, y: int, ejected: tuple[str, int]
) -> None:
    """Route an ejected ship-inventory item to the right destination based
    on what's under the cursor: module slot, quick-use slot, station
    inventory, or the world (iron only)."""
    item_type, amount = ejected
    if amount <= 0:
        return

    mod_slot = gv._hud.module_slot_at(x, y)
    if mod_slot is not None:
        _eject_to_module_slot(gv, mod_slot, item_type, amount)
        return

    qu_slot = gv._hud.slot_at(x, y)
    if qu_slot is not None:
        _eject_to_quick_use(gv, qu_slot, item_type, amount)
        return

    if gv._station_inv.open and gv._station_inv._panel_contains(x, y):
        _eject_to_station_inv(gv, x, y, item_type, amount)
        return

    if item_type == "iron":
        _eject_iron_to_world(gv, amount)
