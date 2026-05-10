"""Mouse-press / motion / scroll handlers + the small action helpers
they invoke (craft, trade, world click, death-screen action).

Extracted from ``input_handlers`` in the 2026-05-10 split.  The
drag/release/eject path lives in ``input_handlers_dragdrop``.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from constants import (
    BUILDING_TYPES, STATION_INFO_RANGE, TURRET_FREE_PLACE_RADIUS,
    CRAFT_TIME, CRAFT_IRON_COST,
    MODULE_TYPES,
    SHIP_MAX_LEVEL,
)
from settings import audio
from sprites.building import (
    HomeStation, BasicCrafter, DockingPort,
    compute_modules_used, compute_module_capacity,
)

if TYPE_CHECKING:
    from game_view import GameView


def handle_mouse_press(gv: GameView, x: int, y: int, button: int, modifiers: int) -> None:
    if button == arcade.MOUSE_BUTTON_RIGHT:
        if gv._station_inv.open and gv._station_inv.on_mouse_press(
                x, y, button=button):
            return
        if gv.inventory.open:
            gv.inventory.on_mouse_press(x, y, button=button)
        return
    if button != arcade.MOUSE_BUTTON_LEFT:
        return
    if gv._death_screen.active:
        action = gv._death_screen.on_mouse_press(x, y)
        if action:
            _handle_death_action(gv, action)
        return
    if gv._dialogue.open:
        gv._dialogue.on_mouse_press(x, y)
        return
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_press(x, y)
        return
    if gv._destroy_mode:
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        gv._destroy_building_at(wx, wy)
        return
    if gv._placing_building is not None:
        if gv._ghost_sprite is not None:
            gv._place_building(
                gv._ghost_sprite.center_x,
                gv._ghost_sprite.center_y,
            )
        return
    mod_click = gv._hud.module_slot_at(x, y)
    if mod_click is not None and not gv._player_dead:
        mod = gv._hud.get_module_slot(mod_click)
        if mod is not None:
            gv._hud._mod_drag_src = mod_click
            gv._hud._mod_drag_type = mod
            gv._hud._mod_drag_x = x
            gv._hud._mod_drag_y = y
            return
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
    if gv._build_menu.open:
        from ship_manager import count_l1_ships
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
            l1_ship_exists=count_l1_ships(gv) > 0,
            zone_id=getattr(getattr(gv, "_zone", None), "zone_id", None),
        )
        if selected is not None:
            if selected == "__destroy__":
                gv._enter_destroy_mode()
            else:
                gv._enter_placement_mode(selected)
        return
    if gv._station_inv.open:
        if gv._station_inv.on_mouse_press(x, y):
            return
    if gv._craft_menu.open:
        action = gv._craft_menu.on_mouse_press(
            x, y, gv._station_inv.total_iron
        )
        if action is not None and gv._active_crafter is not None:
            _apply_craft_action(gv, action)
        if not gv._craft_menu.open:
            gv._active_crafter = None
        return
    if gv._trade_menu.open:
        action = gv._trade_menu.on_mouse_press(
            x, y, inventory=gv.inventory, station_inv=gv._station_inv)
        if action is not None:
            apply_trade_action(gv, action)
        return
    if gv._fleet_menu.open:
        action = gv._fleet_menu.on_mouse_press(x, y)
        if action is not None:
            from combat_helpers import apply_fleet_order
            gv._fleet_menu.set_status(apply_fleet_order(gv, action))
        return
    if gv._qwi_menu.open:
        action = gv._qwi_menu.on_mouse_press(x, y)
        if action == "spawn_nebula_boss":
            from combat_helpers import spawn_nebula_boss
            if spawn_nebula_boss(gv):
                gv._qwi_menu.set_status("Nebula boss spawned!")
                gv._qwi_menu.open = False
                gv._active_qwi = None
            else:
                gv._qwi_menu.set_status(
                    "Not enough iron (need 100).")
        return
    if (gv.inventory.open
            and gv.inventory._panel_contains(x, y)):
        gv.inventory.on_mouse_press(x, y, button=button)
        return
    if not gv._build_menu.open and not gv._player_dead:
        # Look up via the ``input_handlers`` shim so test-time
        # ``patch("input_handlers._handle_world_click", ...)`` /
        # ``patch("input_handlers._try_start_building_move", ...)``
        # threads through to the actual call site.  The bot_autopilot
        # split uses the same late-binding pattern for the same
        # reason.
        import input_handlers as _ih
        if _ih._try_start_building_move(gv, x, y):
            return
        if _ih._handle_world_click(gv, x, y):
            return
    gv.inventory.on_mouse_press(x, y)


def _apply_craft_action(gv: GameView, action: str) -> None:
    """Apply a craft-menu action (``cancel_craft``, ``craft``, or
    ``craft_module:<key>``) to the active crafter."""
    from character_data import craft_cost_multiplier
    crafter = gv._active_crafter
    if action == "cancel_craft":
        target = crafter.craft_target
        ccm = craft_cost_multiplier(audio.character_name, gv._char_level)
        if target and target in MODULE_TYPES:
            refund = int(MODULE_TYPES[target]["craft_cost"] * ccm)
        else:
            refund = int(CRAFT_IRON_COST * ccm)
        gv._station_inv.add_item("iron", refund)
        crafter.crafting = False
        crafter.craft_timer = 0.0
        crafter.craft_target = ""
        gv._craft_menu._craft_target = ""
        return
    if action == "craft":
        cost = int(CRAFT_IRON_COST * craft_cost_multiplier(
            audio.character_name, gv._char_level))
        gv._station_inv.remove_item("iron", cost)
        crafter.crafting = True
        crafter.craft_timer = 0.0
        crafter.craft_total = CRAFT_TIME
        crafter.craft_target = gv._craft_menu._craft_target
        return
    if action.startswith("craft_module:"):
        mod_key = action.split(":", 1)[1]
        info = MODULE_TYPES[mod_key]
        cost = int(info["craft_cost"] * craft_cost_multiplier(
            audio.character_name, gv._char_level))
        gv._station_inv.remove_item("iron", cost)
        crafter.crafting = True
        crafter.craft_timer = 0.0
        crafter.craft_total = CRAFT_TIME
        crafter.craft_target = mod_key
        gv._craft_menu._craft_target = mod_key


def _screen_to_world(gv: GameView, x: int, y: int) -> tuple[float, float]:
    wx = gv.world_cam.position[0] - gv.window.width / 2 + x
    wy = gv.world_cam.position[1] - gv.window.height / 2 + y
    return wx, wy


def _handle_world_click(gv: GameView, x: int, y: int) -> bool:
    """Check world clicks (refugee NPC -> dialogue; parked ship -> switch;
    trade station -> trade menu; building -> station inv or craft menu).
    Returns True if consumed."""
    wx, wy = _screen_to_world(gv, x, y)
    px, py = gv.player.center_x, gv.player.center_y

    if gv._refugee_npc is not None:
        from constants import NPC_REFUGEE_INTERACT_DIST
        rx = gv._refugee_npc.center_x
        ry = gv._refugee_npc.center_y
        if (math.hypot(wx - rx, wy - ry) < 50
                and math.hypot(px - rx, py - ry) < NPC_REFUGEE_INTERACT_DIST):
            from dialogue import get_refugee_tree
            tree = get_refugee_tree(audio.character_name or "")
            gv._dialogue.start(tree, aftermath_sink=gv._quest_flags)
            gv._met_refugee = True
            return True

    for ps in gv._parked_ships:
        if math.hypot(wx - ps.center_x, wy - ps.center_y) >= 40:
            continue
        if math.hypot(px - ps.center_x, py - ps.center_y) >= STATION_INFO_RANGE:
            continue
        from building_manager import switch_to_ship
        switch_to_ship(gv, ps)
        return True

    ts = gv._trade_station
    if ts is not None and math.hypot(wx - ts.center_x, wy - ts.center_y) < 80:
        if math.hypot(px - ts.center_x, py - ts.center_y) < STATION_INFO_RANGE:
            gv._trade_menu.toggle(
                inventory=gv.inventory, station_inv=gv._station_inv)
            return True

    for b in gv.building_list:
        if math.hypot(wx - b.center_x, wy - b.center_y) >= 40:
            continue
        if math.hypot(px - b.center_x, py - b.center_y) >= STATION_INFO_RANGE:
            continue
        if isinstance(b, HomeStation) and not b.disabled:
            gv._last_station_pos = (b.center_x, b.center_y)
            gv._last_station_zone = getattr(
                getattr(gv, "_zone", None), "zone_id", None)
            gv._station_inv.toggle()
            return True
        if isinstance(b, BasicCrafter) and not b.disabled:
            gv._active_crafter = b
            gv._craft_menu.refresh_recipes(
                gv._station_inv,
                is_advanced=(b.building_type == "Advanced Crafter"),
                zone_id=getattr(getattr(gv, "_zone", None), "zone_id", None),
            )
            gv._craft_menu.toggle()
            gv._craft_menu.update(b.craft_progress, b.crafting)
            return True
        from sprites.building import QuantumWaveIntegrator
        if isinstance(b, QuantumWaveIntegrator) and not b.disabled:
            gv._active_qwi = b
            gv._qwi_menu.set_status("")
            gv._qwi_menu.toggle()
            return True
    return False


def apply_trade_action(gv: GameView, action: str) -> None:
    """Apply a trade-menu action string (``sell:*:N`` or ``buy:*:N``).

    Shared by mouse-press handling and the hold-to-sell update loop.
    Sell drains the ship inventory first, then the station inventory,
    and refreshes the sell list so empty rows disappear.
    """
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


def _handle_death_action(gv: GameView, action: str) -> None:
    """Process an action string from the death screen."""
    if action == "main_menu":
        gv._return_to_menu()
    elif action == "exit":
        arcade.exit()
    elif action.startswith("load:"):
        slot = int(action.split(":")[1])
        gv._load_game(slot)


def handle_mouse_scroll(
    gv: GameView, x: int, y: int, scroll_x: int, scroll_y: int
) -> None:
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_scroll(scroll_y)
        return
    if gv._build_menu.open:
        gv._build_menu.on_mouse_scroll(
            scroll_y,
            zone_id=getattr(getattr(gv, "_zone", None), "zone_id", None))
        return
    if gv._craft_menu.open:
        gv._craft_menu.on_mouse_scroll(scroll_y)
        return
    if gv._trade_menu.open:
        gv._trade_menu.on_mouse_scroll(scroll_y)
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
        gv._build_menu.on_mouse_motion(
            x, y,
            zone_id=getattr(getattr(gv, "_zone", None), "zone_id", None))
    if gv._craft_menu.open:
        gv._craft_menu.on_mouse_motion(x, y)
    if gv._qwi_menu.open:
        gv._qwi_menu.on_mouse_motion(x, y)
    if gv._fleet_menu.open:
        gv._fleet_menu.on_mouse_motion(x, y)
    if gv._ghost_sprite is not None and gv._placing_building is not None:
        wx = gv.world_cam.position[0] - gv.window.width / 2 + x
        wy = gv.world_cam.position[1] - gv.window.height / 2 + y
        bt = gv._placing_building
        stats = BUILDING_TYPES[bt]
        if stats["connectable"]:
            snap = gv._find_nearest_snap_port(wx, wy)
            if snap is not None:
                snap_parent_ghost, port, sx, sy = snap
                _DIR_ORDER = ["N", "E", "S", "W"]
                p_steps = round(snap_parent_ghost.angle / 90.0) % 4
                p_label_idx = _DIR_ORDER.index(port.direction)
                phys_dir = _DIR_ORDER[(p_label_idx - p_steps) % 4]
                phys_opp = DockingPort.opposite(phys_dir)

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
                    bld_steps = round(ghost_angle / 90.0) % 4
                    opp_idx = _DIR_ORDER.index(phys_opp)
                    needed_label = _DIR_ORDER[(opp_idx + bld_steps) % 4]
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
        hover_ps = None
        hover_dist = 40.0
        for ps in gv._parked_ships:
            d = math.hypot(wx - ps.center_x, wy - ps.center_y)
            if d < hover_dist:
                hover_dist = d
                hover_ps = ps
        gv._hover_parked_ship = hover_ps
        gv._hover_drone = None
        active_drone = getattr(gv, "_active_drone", None)
        if active_drone is not None:
            d = math.hypot(wx - active_drone.center_x,
                           wy - active_drone.center_y)
            if d < 30.0:
                gv._hover_drone = active_drone
        gv._hover_refugee = False
        if gv._refugee_npc is not None:
            if math.hypot(wx - gv._refugee_npc.center_x,
                          wy - gv._refugee_npc.center_y) < 50:
                gv._hover_refugee = True
