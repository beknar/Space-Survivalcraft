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
    HomeStation, BasicCrafter, DockingPort, Turret, MissileArray,
    compute_modules_used, compute_module_capacity,
)

if TYPE_CHECKING:
    from game_view import GameView


def handle_key_press(gv: GameView, key: int, modifiers: int) -> None:
    if gv._death_screen.active:
        gv._death_screen.on_key_press(key)
        return
    if gv._dialogue.open:
        gv._dialogue.on_key_press(key)
        return
    if key == arcade.key.ESCAPE:
        if gv._trade_menu.open:
            gv._trade_menu.on_key_press(key)
            return
        if gv._craft_menu.open:
            gv._craft_menu.open = False
            gv._active_crafter = None
            return
        if gv._qwi_menu.open:
            gv._qwi_menu.open = False
            gv._active_qwi = None
            return
        if gv._fleet_menu.open:
            gv._fleet_menu.open = False
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
        if gv._map_overlay.open:
            gv._map_overlay.open = False
            return
        if gv._moving_building is not None:
            gv._moving_building.center_x = gv._move_origin_x
            gv._moving_building.center_y = gv._move_origin_y
            gv._moving_building = None
            gv._move_candidate = None
        elif gv._destroy_mode:
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
    elif key == arcade.key.M:
        # Full-screen map — toggle on/off.  draw_logic.draw_ui treats
        # it as a modal overlay so the character + music videos stop
        # decoding behind it.
        if not gv._escape_menu.open and not gv._player_dead:
            gv._map_overlay.toggle()
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
    elif key == arcade.key.G:
        _try_force_wall(gv)
    elif key == arcade.key.X:
        _try_death_blossom(gv)
    elif key == arcade.key.R:
        from combat_helpers import deploy_drone, recall_drone
        # Shift+R: dedicated "put away" — stash the active drone back
        # into the inventory without deploying anything new.
        if modifiers & arcade.key.MOD_SHIFT:
            recall_drone(gv)
        else:
            deploy_drone(gv)
    elif key == arcade.key.Y:
        # Fleet Control overlay — toggle on/off.  Suppressed while
        # other modals are open so it doesn't stack on top of (or
        # under) them in unintended ways.
        if (not gv._escape_menu.open
                and not gv._player_dead
                and not gv._build_menu.open
                and not gv._station_inv.open
                and not gv._craft_menu.open
                and not gv._trade_menu.open
                and not gv._qwi_menu.open
                and not gv._dialogue.open
                and not gv._map_overlay.open):
            gv._fleet_menu.toggle()
    elif key in (arcade.key.W, arcade.key.A, arcade.key.S, arcade.key.D):
        _try_misty_step(gv, key)


def _try_force_wall(gv: GameView) -> None:
    """Deploy a force wall behind the ship if G is pressed and available."""
    if gv._escape_menu.open or gv._player_dead:
        return
    if "force_wall" not in gv._module_slots:
        return
    from constants import FORCE_WALL_COST, FORCE_WALL_COOLDOWN
    from sprites.force_wall import ForceWall
    if gv._ability_meter < FORCE_WALL_COST or gv._force_wall_cd > 0.0:
        return
    gv._ability_meter -= FORCE_WALL_COST
    gv._force_wall_cd = FORCE_WALL_COOLDOWN
    rad = math.radians(gv.player.heading)
    behind_x = gv.player.center_x - math.sin(rad) * 60
    behind_y = gv.player.center_y - math.cos(rad) * 60
    gv._force_walls.append(ForceWall(behind_x, behind_y, gv.player.heading))
    arcade.play_sound(gv._force_wall_snd, volume=0.5)
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def _try_death_blossom(gv: GameView) -> None:
    """Activate Death Blossom if X is pressed and missiles are available."""
    if gv._escape_menu.open or gv._player_dead:
        return
    if "death_blossom" not in gv._module_slots or gv._death_blossom_active:
        return
    missile_count = gv.inventory.count_item("missile")
    if missile_count <= 0:
        return
    gv._death_blossom_active = True
    gv._death_blossom_timer = 0.0
    gv._death_blossom_missiles_left = missile_count
    gv.inventory.remove_item("missile", missile_count)
    for s in range(QUICK_USE_SLOTS):
        if gv._hud.get_quick_use(s) == "missile":
            gv._hud.set_quick_use(s, None, 0)
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def _try_misty_step(gv: GameView, key: int) -> None:
    """Handle WASD key-press — double-tap within 0.3s triggers teleport."""
    if gv._escape_menu.open or gv._player_dead:
        return
    if "misty_step" not in gv._module_slots:
        return
    import time
    from constants import MISTY_STEP_DISTANCE, MISTY_STEP_COST, MISTY_STEP_COOLDOWN
    if not hasattr(gv, '_misty_last_tap'):
        gv._misty_last_tap = {}
    now = time.monotonic()
    last = gv._misty_last_tap.get(key, 0)
    if (now - last < 0.3 and gv._misty_step_cd <= 0
            and gv._ability_meter >= MISTY_STEP_COST):
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
        # Check the null field at the PRE-teleport position — teleporting
        # out of a null field counts as "using an ability from inside".
        from update_logic import disable_null_field_around_player
        disable_null_field_around_player(gv)
        start_x = gv.player.center_x
        start_y = gv.player.center_y
        target_x = start_x + dx * MISTY_STEP_DISTANCE
        target_y = start_y + dy * MISTY_STEP_DISTANCE
        # Star Maze: refuse to teleport if the target lands inside a
        # maze structure OR if the line from the current position to
        # the target crosses any wall.  The segment check has to be
        # densely sampled — a 4-point sample (the helper default)
        # would skip a 32-px wall on a long jump.  Walk the segment
        # in 16-px steps and reject if any sample lands in a wall.
        rooms = getattr(gv._zone, "rooms", None)
        walls = getattr(gv._zone, "walls", None)
        from zones.maze_geometry import (
            point_inside_any_room_interior as _in_room,
            circle_hits_any_wall as _hits_wall,
            point_in_rect,
        )
        from constants import SHIP_RADIUS

        def _segment_crosses_wall() -> bool:
            if not walls:
                return False
            seg_len = math.hypot(target_x - start_x, target_y - start_y)
            n = max(2, int(seg_len / 16.0) + 1)
            for i in range(n + 1):
                t = i / n
                sx = start_x + (target_x - start_x) * t
                sy = start_y + (target_y - start_y) * t
                for w in walls:
                    if point_in_rect(sx, sy, w):
                        return True
            return False

        if ((rooms and _in_room(target_x, target_y, rooms))
                or (walls
                    and _hits_wall(target_x, target_y,
                                   SHIP_RADIUS, walls))
                or _segment_crosses_wall()):
            gv._ability_meter += MISTY_STEP_COST
            gv._misty_step_cd = 0.0
            gv._flash_game_msg("Blocked by maze wall!", 0.8)
            gv._misty_last_tap[key] = 0
            return
        gv.player.center_x = target_x
        gv.player.center_y = target_y
        gv._use_glow = (160, 80, 255, 160)
        gv._use_glow_timer = 0.3
        _player = arcade.play_sound(gv._misty_step_snd, volume=0.4)
        # Cap the misty-step sfx at 5 s — the source clip is longer
        # and the extended tail was bleeding into the next ability.
        if _player is not None:
            import pyglet
            pyglet.clock.schedule_once(
                lambda _dt, p=_player: (
                    p.pause() if hasattr(p, "pause") else None),
                5.0)
        gv._misty_last_tap[key] = 0
    else:
        gv._misty_last_tap[key] = now


def handle_mouse_press(gv: GameView, x: int, y: int, button: int, modifiers: int) -> None:
    # Right-click routes ONLY to the two inventory panels so stacks can
    # be split; all other overlays + world clicks stay left-click only.
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
            _apply_craft_action(gv, action)
        if not gv._craft_menu.open:
            gv._active_crafter = None
        return
    # Trade menu click
    if gv._trade_menu.open:
        action = gv._trade_menu.on_mouse_press(
            x, y, inventory=gv.inventory, station_inv=gv._station_inv)
        if action is not None:
            apply_trade_action(gv, action)
        return
    # Fleet menu click — apply the selected drone order.
    if gv._fleet_menu.open:
        action = gv._fleet_menu.on_mouse_press(x, y)
        if action is not None:
            from combat_helpers import apply_fleet_order
            gv._fleet_menu.set_status(apply_fleet_order(gv, action))
        return
    # QWI menu click — the "SUMMON NEBULA BOSS" button.
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
    # Inventory has visual priority over the world — when its
    # panel is open and the click lands inside the panel rect, the
    # inventory absorbs the click before any world-click dispatch
    # so a station building (crafter / trade station / Home
    # Station) sitting under the cursor in world space doesn't
    # also fire.  Cell clicks become drag/split via
    # ``inventory.on_mouse_press``; non-cell clicks inside the
    # panel (border / consolidate-button / drag-cancel zone) are
    # still considered "consumed" so the world doesn't see them.
    if (gv.inventory.open
            and gv.inventory._panel_contains(x, y)):
        gv.inventory.on_mouse_press(x, y, button=button)
        return
    # World clicks (parked ships, trade station, buildings)
    if not gv._build_menu.open and not gv._player_dead:
        if _try_start_building_move(gv, x, y):
            return
        if _handle_world_click(gv, x, y):
            return
    gv.inventory.on_mouse_press(x, y)


def _apply_craft_action(gv: GameView, action: str) -> None:
    """Apply a craft-menu action (``cancel_craft``, ``craft``, or
    ``craft_module:<key>``) to the active crafter."""
    from character_data import craft_cost_multiplier
    crafter = gv._active_crafter
    if action == "cancel_craft":
        # Refund based on the THIS crafter's target — two parallel
        # crafters can hold different recipes, so reading the menu's
        # shared field would refund the wrong amount when the player
        # cancels the second crafter while the first is still going.
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
        # The menu's _craft_target was set to "" for repair pack or
        # "shield_recharge" for the shield recharge recipe.  Carry
        # whichever one is current onto this crafter so two crafters
        # can run different recipes simultaneously.
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
        # Short press — treat as a normal click (no action for turrets
        # today, but keep the hook so future click behaviours work).
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


def _handle_world_click(gv: GameView, x: int, y: int) -> bool:
    """Check world clicks (refugee NPC → dialogue; parked ship → switch;
    trade station → trade menu; building → station inv or craft menu).
    Returns True if consumed."""
    wx, wy = _screen_to_world(gv, x, y)
    px, py = gv.player.center_x, gv.player.center_y

    # Refugee NPC — open dialogue if the player is within interact range.
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

    # Parked ship — click within 40px and player within STATION_INFO_RANGE
    for ps in gv._parked_ships:
        if math.hypot(wx - ps.center_x, wy - ps.center_y) >= 40:
            continue
        if math.hypot(px - ps.center_x, py - ps.center_y) >= STATION_INFO_RANGE:
            continue
        from building_manager import switch_to_ship
        switch_to_ship(gv, ps)
        return True

    # Trade station
    ts = gv._trade_station
    if ts is not None and math.hypot(wx - ts.center_x, wy - ts.center_y) < 80:
        if math.hypot(px - ts.center_x, py - ts.center_y) < STATION_INFO_RANGE:
            gv._trade_menu.toggle(
                inventory=gv.inventory, station_inv=gv._station_inv)
            return True

    # Buildings — Home Station opens station inv, BasicCrafter opens craft menu
    for b in gv.building_list:
        if math.hypot(wx - b.center_x, wy - b.center_y) >= 40:
            continue
        if math.hypot(px - b.center_x, py - b.center_y) >= STATION_INFO_RANGE:
            continue
        if isinstance(b, HomeStation) and not b.disabled:
            # Record this station as the player's most recent visit
            # so the respawn-on-death system knows where to send them.
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
        # Quantum Wave Integrator — open the Nebula-boss spawn menu.
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
    # Clear any hold-to-sell loop in the trade menu.
    if gv._trade_menu.open:
        gv._trade_menu.on_mouse_release(x, y)
    # Drop any in-flight scrollbar drag in the build / craft menus.
    if gv._build_menu.open:
        gv._build_menu.on_mouse_release(x, y)
    if gv._craft_menu.open:
        gv._craft_menu.on_mouse_release(x, y)
    # Finish a long-press building move (if any).
    if _finish_building_move(gv, x, y):
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
    is_module = item_type.startswith("mod_") or item_type.startswith("bp_")
    # Drop onto a parked ship installs one module into that ship's slots
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
                # No empty slot
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
    # Items other than iron can't become world pickups yet — silently drop.


def handle_mouse_scroll(
    gv: GameView, x: int, y: int, scroll_x: int, scroll_y: int
) -> None:
    if gv._escape_menu.open:
        gv._escape_menu.on_mouse_scroll(scroll_y)
        return
    # Build menu and Craft menu are scrollable when their content
    # exceeds the panel height.  Wheel events are consumed by the
    # menu so they don't double-route into placement-mode rotation.
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
        # Parked ship hover — show tooltip when cursor is over a parked ship
        hover_ps = None
        hover_dist = 40.0
        for ps in gv._parked_ships:
            d = math.hypot(wx - ps.center_x, wy - ps.center_y)
            if d < hover_dist:
                hover_dist = d
                hover_ps = ps
        gv._hover_parked_ship = hover_ps
        # Drone hover — show HP / shield tooltip when cursor is over
        # the active companion drone.
        gv._hover_drone = None
        active_drone = getattr(gv, "_active_drone", None)
        if active_drone is not None:
            d = math.hypot(wx - active_drone.center_x,
                           wy - active_drone.center_y)
            if d < 30.0:
                gv._hover_drone = active_drone
        # Refugee NPC hover
        gv._hover_refugee = False
        if gv._refugee_npc is not None:
            if math.hypot(wx - gv._refugee_npc.center_x,
                          wy - gv._refugee_npc.center_y) < 50:
                gv._hover_refugee = True
