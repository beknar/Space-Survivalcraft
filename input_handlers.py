"""Input event handlers extracted from GameView."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    SHIP_RADIUS, EJECT_DIST, WORLD_ITEM_LIFETIME,
    BUILDING_TYPES, STATION_INFO_RANGE, TURRET_FREE_PLACE_RADIUS,
    CRAFT_TIME, CRAFT_IRON_COST,
    MODULE_TYPES, QUICK_USE_SLOTS,
    SHIP_MAX_LEVEL,
)
from settings import audio
from sprites.building import (
    HomeStation, BasicCrafter, DockingPort,
    compute_modules_used, compute_module_capacity,
)

if TYPE_CHECKING:
    from game_view import GameView


def handle_key_press(gv: GameView, key: int, modifiers: int) -> None:
    if gv._death_screen.active:
        gv._death_screen.on_key_press(key)
        return
    if key == arcade.key.ESCAPE:
        if gv._trade_menu.open:
            gv._trade_menu.on_key_press(key)
            return
        if gv._craft_menu.open:
            gv._craft_menu.open = False
            gv._active_crafter = None
            return
        if gv._station_inv.open:
            gv._station_inv.open = False
            return
        if gv._station_info.open:
            gv._station_info.open = False
            return
        if gv._ship_stats.open:
            gv._ship_stats.open = False
            return
        if gv._destroy_mode:
            gv._exit_destroy_mode()
        elif gv._placing_building is not None:
            gv._cancel_placement()
        elif gv._build_menu.open:
            gv._build_menu.toggle()
        elif gv._escape_menu.open:
            gv._escape_menu.on_key_press(key, modifiers)
        elif gv.inventory.open:
            gv.inventory.toggle()
        else:
            gv._escape_menu.toggle()
        return
    if gv._escape_menu.open:
        gv._escape_menu.on_key_press(key, modifiers)
        return
    gv._keys.add(key)
    if key == arcade.key.TAB:
        gv._cycle_weapon()
    elif key == arcade.key.I:
        gv.inventory.toggle()
    elif key == arcade.key.F:
        gv._hud.toggle_fps()
        audio.show_fps = gv._hud.show_fps
    elif key == arcade.key.B:
        if not gv._escape_menu.open and not gv._player_dead:
            if gv._destroy_mode:
                gv._exit_destroy_mode()
                return
            if gv._placing_building is not None:
                gv._cancel_placement()
            gv._build_menu.toggle()
    elif key == arcade.key.T:
        if not gv._escape_menu.open and not gv._player_dead:
            near = any(
                math.hypot(gv.player.center_x - b.center_x,
                           gv.player.center_y - b.center_y) < STATION_INFO_RANGE
                for b in gv.building_list
            )
            if near or gv._station_info.open:
                from draw_logic import compute_world_stats, compute_inactive_zone_stats
                gv._station_info.toggle(
                    gv.building_list,
                    compute_modules_used(gv.building_list),
                    compute_module_capacity(gv.building_list),
                    stat_lines=compute_world_stats(gv),
                    inactive_zone_stats=compute_inactive_zone_stats(gv),
                )
    elif key == arcade.key.C:
        if not gv._escape_menu.open and not gv._player_dead:
            gv._ship_stats.refresh(
                gv.player, gv._faction, gv._ship_type,
                gv._module_slots,
                char_name=audio.character_name,
                char_xp=gv._char_xp,
                char_level=gv._char_level)
            gv._ship_stats.toggle()
    elif key in (arcade.key.KEY_1, arcade.key.KEY_2, arcade.key.KEY_3,
                 arcade.key.KEY_4, arcade.key.KEY_5, arcade.key.KEY_6,
                 arcade.key.KEY_7, arcade.key.KEY_8, arcade.key.KEY_9,
                 arcade.key.KEY_0):
        if not gv._escape_menu.open and not gv._player_dead:
            slot = (key - arcade.key.KEY_1) if key != arcade.key.KEY_0 else 9
            item = gv._hud.get_quick_use(slot)
            if item == "repair_pack":
                gv._use_repair_pack(slot)
            elif item == "shield_recharge":
                gv._use_shield_recharge(slot)
            elif item == "missile":
                gv._fire_missile(slot)
    # Force wall (G key)
    elif key == arcade.key.G:
        if (not gv._escape_menu.open and not gv._player_dead
                and "force_wall" in gv._module_slots):
            from constants import FORCE_WALL_COST
            from sprites.force_wall import ForceWall
            if gv._ability_meter >= FORCE_WALL_COST:
                gv._ability_meter -= FORCE_WALL_COST
                # Spawn wall behind the ship
                rad = math.radians(gv.player.heading)
                behind_x = gv.player.center_x - math.sin(rad) * 60
                behind_y = gv.player.center_y - math.cos(rad) * 60
                gv._force_walls.append(ForceWall(behind_x, behind_y, gv.player.heading))
                arcade.play_sound(gv._force_wall_snd, volume=0.5)
    # Death blossom (X key)
    elif key == arcade.key.X:
        if (not gv._escape_menu.open and not gv._player_dead
                and "death_blossom" in gv._module_slots
                and not gv._death_blossom_active):
            missile_count = gv.inventory.count_item("missile")
            if missile_count > 0:
                gv._death_blossom_active = True
                gv._death_blossom_timer = 0.0
                gv._death_blossom_missiles_left = missile_count
                gv.inventory.remove_item("missile", missile_count)
    # Misty step (double-tap WASD)
    elif key in (arcade.key.W, arcade.key.A, arcade.key.S, arcade.key.D):
        if (not gv._escape_menu.open and not gv._player_dead
                and "misty_step" in gv._module_slots):
            import time
            from constants import MISTY_STEP_DISTANCE, MISTY_STEP_COST, MISTY_STEP_COOLDOWN
            now = time.monotonic()
            last = getattr(gv, '_misty_last_tap', {}).get(key, 0)
            if not hasattr(gv, '_misty_last_tap'):
                gv._misty_last_tap = {}
            if now - last < 0.3 and gv._misty_step_cd <= 0 and gv._ability_meter >= MISTY_STEP_COST:
                # Double tap detected — teleport
                gv._ability_meter -= MISTY_STEP_COST
                gv._misty_step_cd = MISTY_STEP_COOLDOWN
                rad = math.radians(gv.player.heading)
                if key == arcade.key.W:
                    dx, dy = math.sin(rad), math.cos(rad)
                elif key == arcade.key.S:
                    dx, dy = -math.sin(rad), -math.cos(rad)
                elif key == arcade.key.A:
                    dx, dy = -math.cos(rad), math.sin(rad)
                else:  # D
                    dx, dy = math.cos(rad), -math.sin(rad)
                gv.player.center_x += dx * MISTY_STEP_DISTANCE
                gv.player.center_y += dy * MISTY_STEP_DISTANCE
                gv._use_glow = (160, 80, 255, 160)
                gv._use_glow_timer = 0.3
                arcade.play_sound(gv._misty_step_snd, volume=0.4)
                gv._misty_last_tap[key] = 0
            else:
                gv._misty_last_tap[key] = now


def handle_mouse_press(gv: GameView, x: int, y: int, button: int, modifiers: int) -> None:
    if button != arcade.MOUSE_BUTTON_LEFT:
        return
    if gv._death_screen.active:
        action = gv._death_screen.on_mouse_press(x, y)
        if action:
            _handle_death_action(gv, action)
        return
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_press(x, y)
        return
    # Destroy mode
    if gv._destroy_mode:
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        gv._destroy_building_at(wx, wy)
        return
    # Placement mode
    if gv._placing_building is not None:
        if gv._ghost_sprite is not None:
            gv._place_building(
                gv._ghost_sprite.center_x,
                gv._ghost_sprite.center_y,
            )
        return
    # Module slot click
    mod_click = gv._hud.module_slot_at(x, y)
    if mod_click is not None and not gv._player_dead:
        mod = gv._hud.get_module_slot(mod_click)
        if mod is not None:
            gv._hud._mod_drag_src = mod_click
            gv._hud._mod_drag_type = mod
            gv._hud._mod_drag_x = x
            gv._hud._mod_drag_y = y
            return
    # Quick-use slot click
    qu_slot = gv._hud.slot_at(x, y)
    if qu_slot is not None and not gv._player_dead:
        item = gv._hud.get_quick_use(qu_slot)
        if item is not None:
            gv._hud._qu_drag_src = qu_slot
            gv._hud._qu_drag_type = item
            gv._hud._qu_drag_count = gv._hud._qu_counts[qu_slot]
            gv._hud._qu_drag_x = x
            gv._hud._qu_drag_y = y
        return
    # Build menu click
    if gv._build_menu.open:
        selected = gv._build_menu.on_mouse_press(
            x, y,
            iron=gv.inventory.total_iron + gv._station_inv.total_iron,
            building_counts=gv._building_counts(),
            modules_used=compute_modules_used(gv.building_list),
            module_capacity=compute_module_capacity(gv.building_list),
            has_home=gv._has_home_station(),
            copper=gv.inventory.count_item("copper") + gv._station_inv.count_item("copper"),
            unlocked_blueprints=gv._craft_menu._unlocked,
            ship_level=gv._ship_level,
            max_ship_exists=any(
                p.ship_level >= SHIP_MAX_LEVEL for p in gv._parked_ships
            ) or gv._ship_level >= SHIP_MAX_LEVEL,
        )
        if selected is not None:
            if selected == "__destroy__":
                gv._enter_destroy_mode()
            else:
                gv._enter_placement_mode(selected)
        return
    # Station inventory click
    if gv._station_inv.open:
        if gv._station_inv.on_mouse_press(x, y):
            return
    # Craft menu click
    if gv._craft_menu.open:
        action = gv._craft_menu.on_mouse_press(
            x, y, gv._station_inv.total_iron
        )
        if action is not None and gv._active_crafter is not None:
            if action == "cancel_craft":
                from character_data import craft_cost_multiplier
                target = gv._craft_menu._craft_target
                _ccm = craft_cost_multiplier(audio.character_name, gv._char_level)
                if target and target in MODULE_TYPES:
                    refund = int(MODULE_TYPES[target]["craft_cost"] * _ccm)
                else:
                    refund = int(CRAFT_IRON_COST * _ccm)
                gv._station_inv.add_item("iron", refund)
                gv._active_crafter.crafting = False
                gv._active_crafter.craft_timer = 0.0
                gv._craft_menu._craft_target = ""
            elif action == "craft":
                from character_data import craft_cost_multiplier
                _craft_cost = int(CRAFT_IRON_COST * craft_cost_multiplier(
                    audio.character_name, gv._char_level))
                gv._station_inv.remove_item("iron", _craft_cost)
                gv._active_crafter.crafting = True
                gv._active_crafter.craft_timer = 0.0
                gv._active_crafter.craft_total = CRAFT_TIME
                # _craft_target already set by craft_menu.on_mouse_press
            elif action.startswith("craft_module:"):
                from character_data import craft_cost_multiplier
                mod_key = action.split(":", 1)[1]
                info = MODULE_TYPES[mod_key]
                _craft_cost = int(info["craft_cost"] * craft_cost_multiplier(
                    audio.character_name, gv._char_level))
                gv._station_inv.remove_item("iron", _craft_cost)
                gv._active_crafter.crafting = True
                gv._active_crafter.craft_timer = 0.0
                gv._active_crafter.craft_total = CRAFT_TIME
                gv._craft_menu._craft_target = mod_key
        if not gv._craft_menu.open:
            gv._active_crafter = None
        return
    # Trade menu click
    if gv._trade_menu.open:
        action = gv._trade_menu.on_mouse_press(
            x, y, inventory=gv.inventory, station_inv=gv._station_inv)
        if action is not None:
            if action.startswith("sell:"):
                _, item_type, amt_str = action.split(":")
                amt = int(amt_str)
                ship_has = gv.inventory.count_item(item_type)
                if ship_has >= amt:
                    gv.inventory.remove_item(item_type, amt)
                else:
                    if ship_has > 0:
                        gv.inventory.remove_item(item_type, ship_has)
                    gv._station_inv.remove_item(item_type, amt - ship_has)
                gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
            elif action.startswith("buy:"):
                _, item_type, qty_str = action.split(":")
                gv.inventory.add_item(item_type, int(qty_str))
        return
    # Click on parked ships (switch control)
    if not gv._build_menu.open and not gv._player_dead:
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        for ps in gv._parked_ships:
            if math.hypot(wx - ps.center_x, wy - ps.center_y) < 40:
                dist = math.hypot(gv.player.center_x - ps.center_x,
                                  gv.player.center_y - ps.center_y)
                if dist < STATION_INFO_RANGE:
                    from building_manager import switch_to_ship
                    switch_to_ship(gv, ps)
                    return
    # Click on world buildings
    if not gv._build_menu.open and not gv._player_dead:
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        if gv._trade_station is not None:
            ts = gv._trade_station
            if math.hypot(wx - ts.center_x, wy - ts.center_y) < 80:
                dist = math.hypot(gv.player.center_x - ts.center_x,
                                  gv.player.center_y - ts.center_y)
                if dist < STATION_INFO_RANGE:
                    gv._trade_menu.toggle(
                        inventory=gv.inventory,
                        station_inv=gv._station_inv)
                    return
        for b in gv.building_list:
            if math.hypot(wx - b.center_x, wy - b.center_y) < 40:
                dist_to_player = math.hypot(
                    gv.player.center_x - b.center_x,
                    gv.player.center_y - b.center_y,
                )
                if dist_to_player < STATION_INFO_RANGE:
                    if isinstance(b, HomeStation) and not b.disabled:
                        gv._station_inv.toggle()
                        return
                    if isinstance(b, BasicCrafter) and not b.disabled:
                        gv._active_crafter = b
                        gv._craft_menu.refresh_recipes(
                            gv._station_inv,
                            is_advanced=(b.building_type == "Advanced Crafter"),
                        )
                        gv._craft_menu.toggle()
                        gv._craft_menu.update(
                            b.craft_progress, b.crafting,
                        )
                        return
    gv.inventory.on_mouse_press(x, y)


def _handle_death_action(gv: GameView, action: str) -> None:
    """Process an action string from the death screen."""
    if action == "main_menu":
        gv._return_to_menu()
    elif action == "exit":
        arcade.exit()
    elif action.startswith("load:"):
        slot = int(action.split(":")[1])
        gv._load_game(slot)


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
    gv._station_inv.on_mouse_drag(x, y)
    gv.inventory.on_mouse_drag(x, y)


def handle_mouse_release(gv: GameView, x: int, y: int, button: int, modifiers: int) -> None:
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_release(x, y)
        return
    if button != arcade.MOUSE_BUTTON_LEFT:
        return
    # Module drag release
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
    # Quick-use drag release
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
    # Station inventory drop
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
    mod_slot = gv._hud.module_slot_at(x, y)
    is_module = item_type.startswith("mod_") or item_type.startswith("bp_")
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
    # Items other than iron can't become world pickups yet — silently drop.


def handle_mouse_scroll(
    gv: GameView, x: int, y: int, scroll_x: int, scroll_y: int
) -> None:
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_scroll(scroll_y)
        return
    if gv._ghost_sprite is not None and gv._placing_building is not None:
        gv._ghost_rotation = (gv._ghost_rotation + scroll_y * 15.0) % 360.0
        gv._ghost_sprite.angle = gv._ghost_rotation


def handle_mouse_motion(gv: GameView, x: int, y: int, dx: int, dy: int) -> None:
    if gv._death_screen.active:
        gv._death_screen.on_mouse_motion(x, y)
        return
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_motion(x, y)
        return
    if gv._destroy_mode:
        gv._destroy_cursor_x = gv.world_cam.position[0] - gv.window.width / 2 + x
        gv._destroy_cursor_y = gv.world_cam.position[1] - gv.window.height / 2 + y
        return
    if gv._build_menu.open:
        gv._build_menu.on_mouse_motion(x, y)
    # Ghost sprite follows cursor
    if gv._ghost_sprite is not None and gv._placing_building is not None:
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        bt = gv._placing_building
        stats = BUILDING_TYPES[bt]
        if stats["connectable"]:
            snap = gv._find_nearest_snap_port(wx, wy)
            if snap is not None:
                snap_parent_ghost, port, sx, sy = snap
                # Compute physical direction of the snap port
                _DIR_ORDER = ["N", "E", "S", "W"]
                p_steps = round(snap_parent_ghost.angle / 90.0) % 4
                p_label_idx = _DIR_ORDER.index(port.direction)
                phys_dir = _DIR_ORDER[(p_label_idx - p_steps) % 4]
                phys_opp = DockingPort.opposite(phys_dir)

                # Determine ghost rotation (mirror placement auto-rotate)
                tex = gv._building_textures[bt]
                tw = tex.width * 0.5
                th = tex.height * 0.5
                is_wide = tw > th and abs(tw - th) > 4.0
                is_tall = th > tw and abs(tw - th) > 4.0
                ghost_angle = gv._ghost_rotation
                centre_snap = False
                if is_wide and phys_dir in ("N", "S"):
                    centre_snap = True
                elif is_wide and phys_dir in ("E", "W"):
                    ghost_angle = 90.0
                elif is_tall and phys_dir in ("E", "W"):
                    ghost_angle = 90.0
                gv._ghost_sprite.angle = ghost_angle

                if centre_snap:
                    wx, wy = sx, sy
                else:
                    # Find the connecting port on the ghost building
                    bld_steps = round(ghost_angle / 90.0) % 4
                    opp_idx = _DIR_ORDER.index(phys_opp)
                    needed_label = _DIR_ORDER[(opp_idx + bld_steps) % 4]
                    # Use actual port offsets from a fresh building
                    ghw = tw / 2
                    ghh = th / 2
                    _ghost_ports = {"N": (0, ghh), "S": (0, -ghh),
                                    "E": (ghw, 0), "W": (-ghw, 0)}
                    opp_off = _ghost_ports.get(needed_label, (0, 0))
                    rad = math.radians(ghost_angle)
                    cos_a = math.cos(rad)
                    sin_a = math.sin(rad)
                    ox_rot = opp_off[0] * cos_a - opp_off[1] * sin_a
                    oy_rot = opp_off[0] * sin_a + opp_off[1] * cos_a
                    wx = sx - ox_rot
                    wy = sy - oy_rot
        if stats["free_place"]:
            home = None
            for b in gv.building_list:
                if isinstance(b, HomeStation):
                    home = b
                    break
            if home is not None:
                d = math.hypot(wx - home.center_x, wy - home.center_y)
                if d > TURRET_FREE_PLACE_RADIUS:
                    angle = math.atan2(wy - home.center_y, wx - home.center_x)
                    wx = home.center_x + math.cos(angle) * TURRET_FREE_PLACE_RADIUS
                    wy = home.center_y + math.sin(angle) * TURRET_FREE_PLACE_RADIUS
        gv._ghost_sprite.center_x = wx
        gv._ghost_sprite.center_y = wy
    else:
        gv.inventory.on_mouse_move(x, y)
        gv._station_inv.on_mouse_motion(x, y)
        mod_slot = gv._hud.module_slot_at(x, y)
        gv._hud._mod_hover = mod_slot if mod_slot is not None else -1
        qu_hover = gv._hud.slot_at(x, y)
        gv._hud._qu_hover = qu_hover if qu_hover is not None else -1
        if gv._hud._mod_drag_src is not None:
            gv._hud._mod_drag_x = x
            gv._hud._mod_drag_y = y
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        best = None
        best_dist = 40.0
        for b in gv.building_list:
            d = math.hypot(wx - b.center_x, wy - b.center_y)
            if d < best_dist:
                best_dist = d
                best = b
        gv._hover_building = best
        gv._hover_screen_x = x
        gv._hover_screen_y = y
