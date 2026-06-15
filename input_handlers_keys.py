"""Keyboard input handler + ability triggers.

Extracted from ``input_handlers`` in the 2026-05-10 split.  Holds
``handle_key_press`` (the modal-aware top-level dispatcher) plus the
three ability triggers it routes to: ``_try_force_wall``,
``_try_death_blossom``, ``_try_misty_step``.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from constants import (
    STATION_INFO_RANGE,
    QUICK_USE_SLOTS,
)
from settings import audio
from sprites.building import (
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
            # On foot: the planetary build menu (zone-owned) instead of the
            # ship build menu.
            if getattr(gv, "_on_foot", False):
                zone = getattr(gv, "_zone", None)
                if zone is not None and hasattr(zone, "toggle_build_menu"):
                    zone.toggle_build_menu(gv)
                return
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
        if modifiers & arcade.key.MOD_SHIFT:
            recall_drone(gv)
        else:
            deploy_drone(gv)
    elif key == arcade.key.Y:
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


def fire_misty_step(gv: GameView, key: int) -> bool:
    """Execute a misty-step teleport in the direction encoded by
    ``key`` (one of ``arcade.key.W/A/S/D``).

    Extracted from ``_try_misty_step`` so external callers (the bot
    combat assist, the bot autopilot, tests) can trigger the
    teleport without going through the double-tap detector.
    Performs all the same gates ``_try_misty_step`` enforces
    (escape menu / player dead / module presence / cooldown /
    ability budget / maze-wall collision) and returns True iff
    the teleport actually happened.
    """
    if gv._escape_menu.open or gv._player_dead:
        return False
    if "misty_step" not in gv._module_slots:
        return False
    from constants import MISTY_STEP_DISTANCE, MISTY_STEP_COST, MISTY_STEP_COOLDOWN
    if gv._misty_step_cd > 0 or gv._ability_meter < MISTY_STEP_COST:
        return False
    rad = math.radians(gv.player.heading)
    if key == arcade.key.W:
        dx, dy = math.sin(rad), math.cos(rad)
    elif key == arcade.key.S:
        dx, dy = -math.sin(rad), -math.cos(rad)
    elif key == arcade.key.A:
        dx, dy = -math.cos(rad), math.sin(rad)
    elif key == arcade.key.D:
        dx, dy = math.cos(rad), -math.sin(rad)
    else:
        return False
    gv._ability_meter -= MISTY_STEP_COST
    gv._misty_step_cd = MISTY_STEP_COOLDOWN
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)
    start_x = gv.player.center_x
    start_y = gv.player.center_y
    target_x = start_x + dx * MISTY_STEP_DISTANCE
    target_y = start_y + dy * MISTY_STEP_DISTANCE
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
        # Refund + flash; teleport did NOT happen.
        gv._ability_meter += MISTY_STEP_COST
        gv._misty_step_cd = 0.0
        gv._flash_game_msg("Blocked by maze wall!", 0.8)
        return False
    gv.player.center_x = target_x
    gv.player.center_y = target_y
    gv._use_glow = (160, 80, 255, 160)
    gv._use_glow_timer = 0.3
    _player = arcade.play_sound(gv._misty_step_snd, volume=0.4)
    if _player is not None:
        import pyglet
        pyglet.clock.schedule_once(
            lambda _dt, p=_player: (
                p.pause() if hasattr(p, "pause") else None),
            5.0)
    return True


def _try_misty_step(gv: GameView, key: int) -> None:
    """Handle WASD key-press -- double-tap within 0.3s triggers teleport."""
    if gv._escape_menu.open or gv._player_dead:
        return
    if "misty_step" not in gv._module_slots:
        return
    import time
    if not hasattr(gv, '_misty_last_tap'):
        gv._misty_last_tap = {}
    now = time.monotonic()
    last = gv._misty_last_tap.get(key, 0)
    if now - last < 0.3:
        # Double-tap detected -- run the teleport.  Reset the
        # tap-timer regardless of whether the teleport actually
        # fired (cooldown / ability budget / wall collision can
        # all veto), since the user clearly meant to trigger it.
        fire_misty_step(gv, key)
        gv._misty_last_tap[key] = 0
    else:
        gv._misty_last_tap[key] = now
