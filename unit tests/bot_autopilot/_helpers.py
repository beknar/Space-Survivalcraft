"""Plain-function helpers for the split bot-autopilot FSM tests.

State / boss / building factories used across the topical test
files.  Lifted from ``test_bot_autopilot_fsm.py`` in the 2026-05-24
PR 4 refactor.  ``conftest.py`` in this directory prepends the
directory to ``sys.path`` so ``from _helpers import ...`` works.
"""
from __future__ import annotations

import bot_autopilot as ap


def _state(player=None, aliens=(), asteroids=(),
           iron_pickups=(), blueprint_pickups=(),
           weapon_name="Basic Laser", melee_engaged=False,
           iron=0, world_w=6400, world_h=6400,
           buildings=(), inventory_items=None,
           station_inventory_items=None, module_slots=None):
    inv = {"iron": int(iron)} if inventory_items is None else dict(inventory_items)
    sinv = (dict(station_inventory_items)
            if station_inventory_items is not None else {})
    slots = list(module_slots) if module_slots is not None else []
    return {
        "player": player or {
            "x": 0.0, "y": 0.0, "heading": 0.0,
            "shields": 150, "max_shields": 150,
        },
        "weapon": {"name": weapon_name, "idx": 0},
        "aliens": list(aliens),
        "asteroids": list(asteroids),
        "iron_pickups": list(iron_pickups),
        "blueprint_pickups": list(blueprint_pickups),
        "buildings": list(buildings),
        "menu": {},
        "assist": {"melee_engaged": melee_engaged},
        "inventory": {"items": inv},
        "station_inventory": {"items": sinv},
        "module_slots": slots,
        "zone": {"world_w": world_w, "world_h": world_h,
                 "zone_id": "ZoneID.MAIN"},
    }


def _hs_building(x=3200.0, y=3200.0):
    """Build a Home Station entry for /state.buildings."""
    return {"x": x, "y": y, "hp": 100, "type": "StationModule",
            "building_type": "Home Station"}


def _crafter_building(x=3260.0, y=3260.0, *,
                      crafting=False, craft_target=""):
    """Build a Basic Crafter entry for /state.buildings."""
    return {"x": x, "y": y, "hp": 75, "type": "BasicCrafter",
            "building_type": "Basic Crafter",
            "crafting": crafting, "craft_target": craft_target,
            "disabled": False}


def _all_blueprints_in_station(extra=None):
    """Station-inventory dict pre-populated with one of every
    module blueprint the bot waits on before crafting."""
    items = {f"bp_{k}": 1 for k in ap.MODULE_CRAFT_QUEUE}
    if extra:
        items.update(extra)
    return items


def _boss(x=5800.0, y=5800.0, hp=2000, max_hp=2000, phase=1,
          charging=False, windup=0.0):
    """Build a /state ``boss`` dict for the FSM tests."""
    return {
        "x": x, "y": y, "hp": hp, "max_hp": max_hp, "phase": phase,
        "charging": charging, "charge_windup": windup,
        "charge_timer": 0.0,
    }


def _drained_consumable_queue():
    """Reset the bot's craft queue to mimic 25 + 25 batches done."""
    q = ap._state.queue
    q.modules_to_craft.clear()
    q.modules_to_install.clear()
    q.repair_packs_remaining = 0
    q.shield_recharges_remaining = 0
    q.module_phase_started = True
    q.consumable_phase_started = True
