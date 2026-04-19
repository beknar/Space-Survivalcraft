"""Ship upgrade, placement, and switching logic.

Extracted from building_manager.py. building_manager re-exports these
functions for backwards compatibility with existing imports (tests and
game_view delegates).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from constants import BUILDING_TYPES
from settings import audio

if TYPE_CHECKING:
    from game_view import GameView


def _deduct_ship_cost(gv: GameView, cost: int, copper_cost: int) -> None:
    """Deduct iron + copper across ship and station inventories.

    Thin backward-compat shim over ``inventory_ops.deduct_resources``
    — the real logic moved to the shared helper on 2026-04-19
    (three-way duplicate across ship_manager / building_manager /
    combat_helpers).
    """
    from inventory_ops import deduct_resources
    deduct_resources(gv, cost, copper_cost)


def _resize_module_slots(gv: GameView, new_slot_count: int) -> None:
    """Resize gv._module_slots to new_slot_count, preserving existing entries."""
    old_slots = gv._module_slots
    gv._module_slots = [None] * new_slot_count
    for i in range(min(len(old_slots), new_slot_count)):
        gv._module_slots[i] = old_slots[i]
    gv.player.apply_modules(gv._module_slots)
    gv._hud.set_module_count(new_slot_count)
    gv._hud._mod_slots = list(gv._module_slots)


def _upgrade_ship(gv: GameView) -> None:
    """Upgrade the player ship to the next level (legacy in-place upgrade).

    Deducts iron + copper, upgrades the player sprite/stats, expands module
    slots, increases ability meter max, and shows a flash message. All
    existing modules and cargo are preserved.
    """
    from constants import (
        SHIP_MAX_LEVEL, SHIP_LEVEL_MODULE_BONUS, SHIP_LEVEL_ABILITY_BONUS,
        MODULE_SLOT_COUNT,
    )
    from character_data import build_cost_multiplier
    stats = BUILDING_TYPES["Advanced Ship"]
    if gv._ship_level >= SHIP_MAX_LEVEL:
        gv._flash_msg = "Ship already at maximum level!"
        gv._flash_timer = 2.0
        return
    cost_mult = build_cost_multiplier(audio.character_name, gv._char_level)
    cost = int(stats["cost"] * cost_mult)
    copper_cost = int(stats.get("cost_copper", 0) * cost_mult)
    total_iron = gv.inventory.total_iron + gv._station_inv.total_iron
    if total_iron < cost:
        gv._flash_msg = "Not enough iron!"
        gv._flash_timer = 2.0
        return
    if copper_cost > 0:
        total_copper = (gv.inventory.count_item("copper")
                        + gv._station_inv.count_item("copper"))
        if total_copper < copper_cost:
            gv._flash_msg = "Not enough copper!"
            gv._flash_timer = 2.0
            return
    _deduct_ship_cost(gv, cost, copper_cost)
    gv._ship_level += 1
    gv.player.upgrade_ship()
    new_slot_count = MODULE_SLOT_COUNT + (gv._ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
    _resize_module_slots(gv, new_slot_count)
    gv._ability_meter_max += SHIP_LEVEL_ABILITY_BONUS
    gv._ability_meter = gv._ability_meter_max
    gv._flash_msg = f"Ship upgraded to level {gv._ship_level}!"
    gv._flash_timer = 3.0


def _place_new_ship(gv: GameView, wx: float, wy: float) -> None:
    """Place a new level ship at (wx, wy), leaving the old ship parked."""
    from constants import (
        SHIP_LEVEL_MODULE_BONUS, SHIP_LEVEL_ABILITY_BONUS,
        MODULE_SLOT_COUNT,
    )
    from character_data import build_cost_multiplier
    from sprites.parked_ship import ParkedShip

    bt_stats = BUILDING_TYPES["Advanced Ship"]
    cost_mult = build_cost_multiplier(audio.character_name, gv._char_level)
    cost = int(bt_stats["cost"] * cost_mult)
    copper_cost = int(bt_stats.get("cost_copper", 0) * cost_mult)

    _deduct_ship_cost(gv, cost, copper_cost)

    # Park the old (current) ship with empty cargo — player keeps their cargo.
    old_parked = ParkedShip(
        faction=gv._faction,
        ship_type=gv._ship_type,
        ship_level=gv._ship_level,
        x=gv.player.center_x,
        y=gv.player.center_y,
        heading=gv.player.heading,
    )
    old_parked.hp = gv.player.hp
    old_parked.max_hp = gv.player.max_hp
    old_parked.shields = gv.player.shields
    old_parked.max_shields = gv.player.max_shields
    gv._parked_ships.append(old_parked)

    gv._ship_level += 1
    gv.player.upgrade_ship()

    new_slot_count = MODULE_SLOT_COUNT + (gv._ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
    _resize_module_slots(gv, new_slot_count)

    gv._ability_meter_max += SHIP_LEVEL_ABILITY_BONUS
    gv._ability_meter = gv._ability_meter_max

    gv.player.center_x = wx
    gv.player.center_y = wy
    gv.player.vel_x = 0.0
    gv.player.vel_y = 0.0

    gv._flash_msg = f"Ship upgraded to level {gv._ship_level}!"
    gv._flash_timer = 3.0


def count_l1_ships(gv: GameView) -> int:
    """Count how many level-1 ships exist (player + parked).

    Used by the build menu to gate "Basic Ship" so we can't end up
    with two L1 ships at once.  When the player upgrades from L1 to
    L2, the old L1 ship gets parked; if aliens then destroy that
    parked ship, the count drops to zero and "Basic Ship" unlocks
    in the build menu so the player can rebuild their AI scout."""
    n = 0
    if getattr(gv, "_ship_level", 1) == 1 and not getattr(gv, "_player_dead", False):
        n += 1
    parked = getattr(gv, "_parked_ships", None) or []
    for ps in parked:
        if getattr(ps, "ship_level", 1) == 1:
            n += 1
    return n


def _place_basic_ship(gv: GameView, wx: float, wy: float) -> None:
    """Place a fresh level-1 parked ship at (wx, wy).

    Charges the half-cost listed in BUILDING_TYPES["Basic Ship"]
    (500 iron + 250 copper at default character rates).  Unlike
    ``_place_new_ship``, this does NOT touch the player's ship —
    it spawns a brand-new empty L1 parked ship that the player can
    later install modules on (e.g. AI Pilot to make it a scout)."""
    from character_data import build_cost_multiplier
    from sprites.parked_ship import ParkedShip
    from sprites.player import PlayerShip

    bt_stats = BUILDING_TYPES["Basic Ship"]
    cost_mult = build_cost_multiplier(audio.character_name, gv._char_level)
    cost = int(bt_stats["cost"] * cost_mult)
    copper_cost = int(bt_stats.get("cost_copper", 0) * cost_mult)

    _deduct_ship_cost(gv, cost, copper_cost)

    new_ship = ParkedShip(
        faction=gv._faction,
        ship_type=gv._ship_type,
        ship_level=1,
        x=wx,
        y=wy,
        heading=0.0,
    )
    # Fresh ship — full HP and shields, no modules, no cargo.
    gv._parked_ships.append(new_ship)

    gv._flash_msg = "Basic ship built!"
    gv._flash_timer = 3.0


def switch_to_ship(gv: GameView, target) -> None:
    """Swap control from the active PlayerShip to a parked ship."""
    from constants import (
        MODULE_SLOT_COUNT, SHIP_LEVEL_MODULE_BONUS,
        ABILITY_METER_MAX, SHIP_LEVEL_ABILITY_BONUS,
    )
    from sprites.player import PlayerShip
    from sprites.parked_ship import ParkedShip

    old_player = gv.player

    old_parked = ParkedShip(
        faction=gv._faction,
        ship_type=gv._ship_type,
        ship_level=gv._ship_level,
        x=old_player.center_x,
        y=old_player.center_y,
        heading=old_player.heading,
    )
    old_parked.hp = old_player.hp
    old_parked.max_hp = old_player.max_hp
    old_parked.shields = old_player.shields
    old_parked.max_shields = old_player.max_shields
    old_parked.cargo_items = dict(gv.inventory._items)
    old_parked.module_slots = list(gv._module_slots)

    new_player = PlayerShip(
        faction=target.faction,
        ship_type=target.ship_type,
        ship_level=target.ship_level,
    )
    new_player.center_x = target.center_x
    new_player.center_y = target.center_y
    new_player.heading = target.heading
    new_player.angle = target.heading
    new_player.hp = target.hp
    new_player.max_hp = target.max_hp
    new_player.shields = target.shields
    new_player.max_shields = target.max_shields
    new_player.vel_x = 0.0
    new_player.vel_y = 0.0
    new_player.world_width = gv._zone.world_width
    new_player.world_height = gv._zone.world_height

    gv.player_list.clear()
    gv.player = new_player
    gv.player_list.append(new_player)

    gv.inventory._items = dict(target.cargo_items)
    gv.inventory._mark_dirty()

    gv._ship_level = target.ship_level
    slot_count = MODULE_SLOT_COUNT + (target.ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
    gv._module_slots = list(target.module_slots)
    while len(gv._module_slots) < slot_count:
        gv._module_slots.append(None)
    gv._module_slots = gv._module_slots[:slot_count]
    new_player.apply_modules(gv._module_slots)
    gv._hud.set_module_count(slot_count)
    gv._hud._mod_slots = list(gv._module_slots)

    gv._ability_meter_max = ABILITY_METER_MAX + (gv._ship_level - 1) * SHIP_LEVEL_ABILITY_BONUS
    gv._ability_meter = min(gv._ability_meter, gv._ability_meter_max)

    from world_setup import load_weapons
    gv._weapons = load_weapons(new_player.guns)
    gv._weapon_idx = 0

    gv._parked_ships.remove(target)
    gv._parked_ships.append(old_parked)

    gv.shield_sprite.center_x = new_player.center_x
    gv.shield_sprite.center_y = new_player.center_y

    gv._flash_msg = f"Switched to level {gv._ship_level} ship!"
    gv._flash_timer = 2.0
