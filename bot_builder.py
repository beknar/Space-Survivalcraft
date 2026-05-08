"""In-process starter-base builder for the bot.

When called via ``build_starter_base(gv)``, runs three phases in
one call:

  Phase 1 -- starter base.  Seven buildings around the player:
             Home Station + Service / Power / Solar Array column +
             Repair Module on the east + 2× Turret 2 on the NE
             and SW corners at the max-distance free-place radius
             (300 px from the Home Station, split evenly across
             X and Y so each axis offset is R/√2 ≈ 212 px).

  Phase 2 -- deposit.  Move all ship iron + copper into the home
             station's inventory (player would normally do this
             manually after building the base; the bot does it
             unprompted so future builds are paid out of station
             stock).

  Phase 3 -- west extension + crafter.  Service Module on the
             west side of the home station, then Power Receiver
             attached to that, then Solar Array 2 attached to
             that, then Basic Crafter east of the Repair Module.

Designed to be triggered via ``POST /build_starter_base`` on the
bot HTTP API (the autopilot fires this once it has accumulated
enough iron and is in a clear area).

Each placement step goes through the standard
``building_manager.enter_placement_mode`` +
``building_manager.place_building`` chain, so resource deduction,
snap-port alignment, and connectivity all apply exactly as they
would if the player drove the build menu.  Max-count is enforced
locally (defensive — ``place_building`` itself bypasses the UI's
max gate, which would otherwise let re-triggers create
duplicates).

Threading: the entire function runs on the main thread, dispatched
through ``bot_api.pump_main_thread_queue`` from
``GameView.on_update``.  Sprite + texture creation requires the
GL-context-owning thread, so calling building_manager.place_building
from the HTTP handler thread (where the API endpoint lives) hits
``GL_INVALID_OPERATION (0x1282)``.
"""
from __future__ import annotations

import math

from typing import Any

from constants import TURRET_FREE_PLACE_RADIUS as _TURRET_R


# ── Build sequences ──────────────────────────────────────────────────────

# (building_type, dx_from_player, dy_from_player).  The dy values
# are forward of the ship (the player is anchored at world origin
# for the calc), and the snap logic in ``place_building`` will pull
# each module onto the appropriate port even if our coordinate is a
# few pixels off-grid.
# The whole sequence is shifted 200 px north of the player so the
# Home Station lands clear of the ship — the player ship has
# SHIP_RADIUS = 28 + buildings have BUILDING_RADIUS = 30, so
# placing the Home Station on the player's position trapped the
# ship inside the structure with no way to thrust out.
_STARTER_BASE_OFFSET_Y: float = 200.0
# Per-axis offset for a turret placed diagonally at the maximum
# free-place radius from the Home Station.  Using R/√2 keeps the
# total euclidean distance equal to TURRET_FREE_PLACE_RADIUS while
# splitting evenly across the X and Y axes — the turret lands on
# the NE / SW corner of an imagined square around the station.
_TURRET_DIAG_OFFSET: float = _TURRET_R / math.sqrt(2.0)
STARTER_BASE_SEQUENCE: list[tuple[str, float, float]] = [
    ("Home Station",     0.0, _STARTER_BASE_OFFSET_Y +    0.0),
    ("Service Module",   0.0, _STARTER_BASE_OFFSET_Y +   60.0),
    ("Power Receiver",   0.0, _STARTER_BASE_OFFSET_Y +  120.0),
    ("Solar Array 2",    0.0, _STARTER_BASE_OFFSET_Y +  200.0),
    ("Repair Module",   60.0, _STARTER_BASE_OFFSET_Y +   60.0),
    # NE corner turret (max free-place radius, 45° off the +X axis).
    ("Turret 2",  _TURRET_DIAG_OFFSET,
                 _STARTER_BASE_OFFSET_Y + _TURRET_DIAG_OFFSET),
    # SW corner turret (max free-place radius, 225° off the +X axis).
    ("Turret 2", -_TURRET_DIAG_OFFSET,
                 _STARTER_BASE_OFFSET_Y - _TURRET_DIAG_OFFSET),
]

# Phase-3 west extension + Basic Crafter.  All offsets are measured
# from the same player anchor as Phase 1 (NOT from the Home Station)
# so a single (px, py) reference covers both phases.
EXTENSION_SEQUENCE: list[tuple[str, float, float]] = [
    # West chain — each module snaps to the W port of the previous.
    ("Service Module",  -60.0, _STARTER_BASE_OFFSET_Y +    0.0),
    ("Power Receiver", -120.0, _STARTER_BASE_OFFSET_Y +    0.0),
    ("Solar Array 2",  -200.0, _STARTER_BASE_OFFSET_Y +    0.0),
    # Basic Crafter — east of the Phase-1 Repair Module so it
    # snaps to the RM's E port without crowding the player or
    # the west chain.
    ("Basic Crafter",   120.0, _STARTER_BASE_OFFSET_Y +   60.0),
]


# ── Helpers ──────────────────────────────────────────────────────────────


def _existing_count(gv: Any, building_type: str) -> int:
    """Count existing buildings of ``building_type`` in
    ``gv.building_list``.  Used to skip placement of types that
    have already hit their max (``place_building`` itself doesn't
    enforce max-count — that lives in the build-menu UI)."""
    n = 0
    for b in gv.building_list:
        if getattr(b, "building_type", None) == building_type:
            n += 1
    return n


def _has_home_station(gv: Any) -> bool:
    return _existing_count(gv, "Home Station") >= 1


def _place_sequence(
        gv: Any,
        sequence: list[tuple[str, float, float]],
        ) -> tuple[list[dict], list[dict]]:
    """Walk ``sequence`` and call building_manager for each entry.
    Returns ``(placed, failed)`` lists.  Used by both Phase 1
    (starter base) and Phase 3 (extension)."""
    from constants import BUILDING_TYPES
    import building_manager as bm

    px = gv.player.center_x
    py = gv.player.center_y
    placed: list[dict] = []
    failed: list[dict] = []

    for bt, dx, dy in sequence:
        wx = px + dx
        wy = py + dy
        # Defensive max-count check.
        max_count = BUILDING_TYPES.get(bt, {}).get("max")
        if max_count is not None and _existing_count(gv, bt) >= max_count:
            failed.append(
                {"type": bt,
                 "reason": f"max-count {max_count} already placed",
                 "at": [wx, wy]})
            continue
        before = len(gv.building_list)
        try:
            bm.enter_placement_mode(gv, bt)
            bm.place_building(gv, wx, wy)
        except Exception as e:
            try:
                bm.cancel_placement(gv)
            except Exception:
                pass
            failed.append(
                {"type": bt, "error": str(e), "at": [wx, wy]})
            continue
        after = len(gv.building_list)
        if after > before:
            placed.append({"type": bt, "at": [wx, wy]})
        else:
            failed.append(
                {"type": bt, "reason": "placement rejected",
                 "at": [wx, wy]})

    return placed, failed


# Item types that are deliberately kept in the ship inventory and
# never deposited back to the station.  Repair packs and shield
# recharges are bound to quick-use slots after
# ``/equip_consumables``; depositing them would empty the slots
# and force a re-equip round trip every time the bot returns to
# base.  Crafted output still lands in the station first (the
# Basic Crafter's output target), so this exclusion only governs
# the ship→station direction.
SHIP_ONLY_ITEM_TYPES: frozenset[str] = frozenset({
    "repair_pack", "shield_recharge",
})


def deposit_ship_resources_to_station(gv: Any) -> dict:
    """Move EVERY item out of the ship inventory into the Home
    Station inventory — iron, copper, blueprints, crafted items,
    whatever the player has picked up.  No-op (with a reason)
    when no Home Station exists.

    Item types in ``SHIP_ONLY_ITEM_TYPES`` (repair packs, shield
    recharges) are skipped so they remain bound to ship quick-use
    slots between deposit cycles.

    Implementation walks ``gv.inventory._items`` to discover every
    distinct item_type in the ship, then transfers each one
    individually.  Reads station-side count before + after the
    add to detect partial transfers (e.g. station inventory full),
    and only removes from the ship the amount that was actually
    accepted — so we never lose items if the destination rejects.
    """
    if not _has_home_station(gv):
        return {"deposited": {}, "skipped": "no home station"}

    # Discover every distinct item_type in the ship inventory and
    # its total count (an item_type may live in multiple cells).
    items = getattr(gv.inventory, "_items", {}) or {}
    totals: dict[str, int] = {}
    try:
        for (_cell, (item_type, count)) in items.items():
            if item_type in SHIP_ONLY_ITEM_TYPES:
                continue
            totals[item_type] = totals.get(item_type, 0) + int(count)
    except Exception as e:
        return {"deposited": {}, "error": f"failed to scan ship inv: {e}"}

    deposited: dict = {}
    for item_type, ship_count in totals.items():
        if ship_count <= 0:
            continue
        try:
            before = int(gv._station_inv.count_item(item_type))
            gv._station_inv.add_item(item_type, ship_count)
            after = int(gv._station_inv.count_item(item_type))
            actually_added = max(0, after - before)
            if actually_added > 0:
                gv.inventory.remove_item(item_type, actually_added)
                deposited[item_type] = (
                    deposited.get(item_type, 0) + actually_added)
        except Exception as e:
            # Don't break the loop on a single item_type — keep
            # going so later items still get deposited.
            deposited[f"{item_type}_error"] = str(e)
    return {"deposited": deposited}


# ── Public entry point ──────────────────────────────────────────────────


def _craft_cost_multiplier(gv: Any) -> float:
    """Mirror of ``input_handlers._apply_craft_action`` cost math —
    bots pay the same per-character craft discount the player gets."""
    try:
        from character_data import craft_cost_multiplier
        import audio
        return craft_cost_multiplier(audio.character_name, gv._char_level)
    except Exception:
        return 1.0


def _find_idle_basic_crafter(gv: Any):
    """Return the first non-disabled, non-busy ``BasicCrafter`` in
    the building list, or ``None`` if every crafter is unavailable.
    Used by ``start_craft`` so the bot doesn't queue a second craft
    on a crafter that's already mid-cycle."""
    from sprites.building import BasicCrafter
    for b in gv.building_list:
        if (isinstance(b, BasicCrafter)
                and not b.disabled
                and not b.crafting):
            return b
    return None


def start_craft(gv: Any, target: str) -> dict:
    """Start a craft on the first idle ``BasicCrafter``.

    ``target`` is one of:
      * ``"repair_pack"``     → craft 5× Repair Pack (CRAFT_IRON_COST)
      * ``"shield_recharge"`` → craft 5× Shield Recharge (CRAFT_IRON_COST)
      * any key in ``MODULE_TYPES`` → craft that module (cost from
        ``MODULE_TYPES[key]["craft_cost"]``).  Requires the matching
        ``bp_<key>`` blueprint in station inventory.

    Returns ``{"ok": True, ...}`` on success, ``{"ok": False,
    "reason": ...}`` on validation failure (no crafter idle,
    insufficient iron, blueprint missing, unknown target).  All
    state mutation happens on the main thread (this function is
    invoked through ``submit_to_main_thread``).
    """
    from constants import MODULE_TYPES, CRAFT_TIME, CRAFT_IRON_COST

    crafter = _find_idle_basic_crafter(gv)
    if crafter is None:
        return {"ok": False, "reason": "no idle basic crafter"}

    ccm = _craft_cost_multiplier(gv)
    is_module = target in MODULE_TYPES
    if is_module:
        cost = int(MODULE_TYPES[target]["craft_cost"] * ccm)
    elif target in ("repair_pack", "shield_recharge", ""):
        cost = int(CRAFT_IRON_COST * ccm)
    else:
        return {"ok": False, "reason": f"unknown craft target {target!r}"}

    iron_have = int(gv._station_inv.count_item("iron"))
    if iron_have < cost:
        return {
            "ok": False,
            "reason": f"insufficient iron: have {iron_have}, need {cost}",
        }

    if is_module and gv._station_inv.count_item(f"bp_{target}") < 1:
        return {
            "ok": False,
            "reason": f"blueprint bp_{target} not in station inventory",
        }

    gv._station_inv.remove_item("iron", cost)
    crafter.crafting = True
    crafter.craft_timer = 0.0
    crafter.craft_total = CRAFT_TIME
    # ``craft_target`` is the same field ``_apply_craft_action`` sets:
    # module key for module crafts, ``"shield_recharge"`` for the
    # shield recipe, ``""`` for repair pack.  ``update_crafting``
    # reads this when the timer elapses to decide what to add to the
    # station inventory.
    if is_module:
        crafter.craft_target = target
    elif target == "shield_recharge":
        crafter.craft_target = "shield_recharge"
    else:
        crafter.craft_target = ""
    # Mirror onto the menu's shared field too — kept for backward
    # compatibility with ``update_crafting``'s legacy fallback path
    # for old saves whose crafters didn't carry per-instance targets.
    try:
        gv._craft_menu._craft_target = crafter.craft_target
    except Exception:
        pass

    return {
        "ok": True,
        "target": target,
        "cost": cost,
        "iron_remaining": int(gv._station_inv.count_item("iron")),
        "craft_time_s": float(CRAFT_TIME),
    }


def install_module(gv: Any, mod_key: str) -> dict:
    """Install one ``mod_<mod_key>`` from station inventory into the
    next free slot of the player ship.  Mirrors the player flow in
    ``input_handlers._handle_station_inventory_drop`` for the
    drop-onto-HUD-module-slot path.

    Returns ``{"ok": True, "slot": i, "installed": mod_key}`` on
    success, ``{"ok": False, "reason": ...}`` otherwise.
    """
    if gv._station_inv.count_item(f"mod_{mod_key}") < 1:
        return {
            "ok": False,
            "reason": f"mod_{mod_key} not in station inventory",
        }
    if mod_key in gv._module_slots:
        return {
            "ok": False,
            "reason": f"{mod_key} already installed in a ship slot",
        }
    free_slot = None
    for i, slot in enumerate(gv._module_slots):
        if slot is None:
            free_slot = i
            break
    if free_slot is None:
        return {"ok": False, "reason": "no free module slot on ship"}

    gv._station_inv.remove_item(f"mod_{mod_key}", 1)
    gv._module_slots[free_slot] = mod_key
    gv.player.apply_modules(gv._module_slots)
    try:
        gv._hud._mod_slots = list(gv._module_slots)
    except Exception:
        pass
    return {"ok": True, "installed": mod_key, "slot": free_slot}


def equip_consumables_to_quick_use(
        gv: Any,
        repair_slot: int = 0,
        shield_slot: int = 1,
        max_each: int = 25) -> dict:
    """Withdraw repair packs + shield recharges from station inventory
    into ship inventory, then bind them to ship quick-use slots.

    Mirrors the player flow: drag repair_pack out of the station
    inventory grid into the ship inventory grid, then drag onto a
    quick-use slot.  Bot does it in one main-thread call.

    Args:
      repair_slot: quick-use slot index (0-9) for repair packs.
      shield_slot: quick-use slot index (0-9) for shield recharges.
      max_each: cap on the number of each consumable to withdraw.
                Defaults to 25 (the post-craft batch total).

    Returns ``{"ok": True, "repair_pack": N, "shield_recharge": M,
    "repair_slot": i, "shield_slot": j}``.  If neither item is in
    station inventory, ``ok`` is False with reason.
    """
    rp_avail = int(gv._station_inv.count_item("repair_pack"))
    sr_avail = int(gv._station_inv.count_item("shield_recharge"))
    if rp_avail <= 0 and sr_avail <= 0:
        return {
            "ok": False,
            "reason": "no consumables in station inventory",
        }

    rp_take = min(rp_avail, int(max_each))
    sr_take = min(sr_avail, int(max_each))

    if rp_take > 0:
        gv._station_inv.remove_item("repair_pack", rp_take)
        gv.inventory.add_item("repair_pack", rp_take)
    if sr_take > 0:
        gv._station_inv.remove_item("shield_recharge", sr_take)
        gv.inventory.add_item("shield_recharge", sr_take)

    # Bind to quick-use slots — uses the running total in the ship
    # inventory (any prior leftover counts get included).
    rp_total = int(gv.inventory.count_item("repair_pack"))
    sr_total = int(gv.inventory.count_item("shield_recharge"))
    try:
        if rp_total > 0:
            gv._hud.set_quick_use(int(repair_slot),
                                  "repair_pack", rp_total)
        if sr_total > 0:
            gv._hud.set_quick_use(int(shield_slot),
                                  "shield_recharge", sr_total)
    except Exception as e:
        return {"ok": False, "reason": f"hud bind failed: {e}"}

    return {
        "ok": True,
        "repair_pack": rp_take,
        "shield_recharge": sr_take,
        "repair_slot": int(repair_slot),
        "shield_slot": int(shield_slot),
        "ship_repair_total": rp_total,
        "ship_shield_total": sr_total,
    }


def place_quantum_wave_integrator(gv: Any) -> dict:
    """Place a Quantum Wave Integrator near the Home Station.

    The QWI must be within 300 px of an active Home Station; placing
    it auto-spawns the Double Star boss at the world corner furthest
    from the station (``combat_helpers.spawn_boss``).

    Picks a placement spot 200 px south of the Home Station —
    free-place radius is 300 px, so 200 px south is comfortably
    inside.  Falls back to other compass points if south is blocked.
    Returns ``{"ok": True, "placed_at": [x, y]}`` on success,
    ``{"ok": False, "reason": ...}`` otherwise.
    """
    from constants import BUILDING_TYPES
    import building_manager as bm

    if BUILDING_TYPES.get("Quantum Wave Integrator") is None:
        return {"ok": False, "reason": "QWI not in BUILDING_TYPES"}
    if _existing_count(gv, "Quantum Wave Integrator") >= 1:
        return {"ok": False, "reason": "QWI already placed"}

    # Find the active Home Station.
    home = None
    for b in gv.building_list:
        if getattr(b, "building_type", None) == "Home Station" \
                and not getattr(b, "disabled", False):
            home = b
            break
    if home is None:
        return {"ok": False, "reason": "no active home station"}

    hx = float(home.center_x)
    hy = float(home.center_y)

    # Try compass offsets in order: S, N, E, W.  200 px sits inside
    # the 300 px free-place radius and clear of the typical
    # north-extension chain (HS at +0, SM at +60, PR at +120, SA2 at
    # +200) — south is open by default.
    candidates = [
        (hx + 0.0,   hy - 200.0),
        (hx + 0.0,   hy + 280.0),
        (hx + 280.0, hy + 0.0),
        (hx - 280.0, hy + 0.0),
    ]
    last_reason = "all candidates rejected"
    for wx, wy in candidates:
        before = len(gv.building_list)
        try:
            bm.enter_placement_mode(gv, "Quantum Wave Integrator")
            bm.place_building(gv, wx, wy)
        except Exception as e:
            try:
                bm.cancel_placement(gv)
            except Exception:
                pass
            last_reason = f"placement raised: {e}"
            continue
        if len(gv.building_list) > before:
            return {
                "ok": True,
                "placed_at": [wx, wy],
                "boss_spawned": bool(getattr(gv, "_boss_spawned", False)),
            }
    return {"ok": False, "reason": last_reason}


def use_quick_use_slot(gv: Any, slot: int) -> dict:
    """Trigger the consumable in quick-use slot ``slot`` (0-9).

    Looks up the slot's item type and calls the matching ``gv._use_*``
    method.  Used by the autopilot to fire consumables based on
    HP / shield thresholds (it can't press number keys directly
    without driving the keyboard handler).
    """
    item = None
    try:
        item = gv._hud.get_quick_use(int(slot))
    except Exception as e:
        return {"ok": False, "reason": f"slot read failed: {e}"}
    if item is None:
        return {"ok": False, "reason": f"slot {slot} empty"}
    try:
        if item == "repair_pack":
            gv._use_repair_pack(int(slot))
        elif item == "shield_recharge":
            gv._use_shield_recharge(int(slot))
        elif item == "missile":
            gv._fire_missile(int(slot))
        else:
            return {"ok": False, "reason": f"unknown item {item!r}"}
    except Exception as e:
        return {"ok": False, "reason": f"use raised: {e}"}
    return {"ok": True, "used": item, "slot": int(slot)}


def build_starter_base(gv: Any) -> dict:
    """Three-phase build: starter base → deposit → west extension.
    See module docstring for the layout of each sequence.

    Returns a JSON-serialisable dict combining the placed/failed
    lists from both build phases plus the deposit result.
    """
    initial_count = len(gv.building_list)

    # Phase 1 — starter base.
    p1_placed, p1_failed = _place_sequence(gv, STARTER_BASE_SEQUENCE)

    # Phase 2 — deposit ship iron + copper to the new home station.
    deposit_result = deposit_ship_resources_to_station(gv)

    # Phase 3 — west extension + Basic Crafter (paid from station
    # inventory now that the deposit has landed).
    p3_placed, p3_failed = _place_sequence(gv, EXTENSION_SEQUENCE)

    return {
        "placed": p1_placed + p3_placed,
        "failed": p1_failed + p3_failed,
        "deposit": deposit_result,
        "buildings_added": len(gv.building_list) - initial_count,
        "total_buildings_now": len(gv.building_list),
    }
