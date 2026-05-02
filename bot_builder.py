"""In-process starter-base builder for the bot.

When called via ``build_starter_base(gv)``, runs three phases in
one call:

  Phase 1 -- starter base.  Seven buildings around the player:
             Home Station + Service / Power / Solar Array column +
             Repair Module on the east + 2× Turret 2 at the
             max-distance free-place radius.

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

from typing import Any


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
STARTER_BASE_SEQUENCE: list[tuple[str, float, float]] = [
    ("Home Station",     0.0, _STARTER_BASE_OFFSET_Y +    0.0),
    ("Service Module",   0.0, _STARTER_BASE_OFFSET_Y +   60.0),
    ("Power Receiver",   0.0, _STARTER_BASE_OFFSET_Y +  120.0),
    ("Solar Array 2",    0.0, _STARTER_BASE_OFFSET_Y +  200.0),
    ("Repair Module",   60.0, _STARTER_BASE_OFFSET_Y +   60.0),
    ("Turret 2",       300.0, _STARTER_BASE_OFFSET_Y +    0.0),
    ("Turret 2",      -300.0, _STARTER_BASE_OFFSET_Y +    0.0),
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


def deposit_ship_resources_to_station(gv: Any) -> dict:
    """Move all ship iron + copper into the Home Station inventory.
    No-op (with a reason) when no Home Station exists.  Bot calls
    this between Phase 1 and Phase 3 so the extension build is
    paid out of station stock — matching how a player would
    behave after putting up their first base."""
    if not _has_home_station(gv):
        return {"deposited": {}, "skipped": "no home station"}
    deposited: dict = {}
    try:
        iron_amt = int(getattr(gv.inventory, "total_iron", 0))
        if iron_amt > 0:
            gv.inventory.remove_item("iron", iron_amt)
            gv._station_inv.add_item("iron", iron_amt)
            deposited["iron"] = iron_amt
    except Exception as e:
        deposited["iron_error"] = str(e)
    try:
        copper_amt = int(gv.inventory.count_item("copper"))
        if copper_amt > 0:
            gv.inventory.remove_item("copper", copper_amt)
            gv._station_inv.add_item("copper", copper_amt)
            deposited["copper"] = copper_amt
    except Exception as e:
        deposited["copper_error"] = str(e)
    return {"deposited": deposited}


# ── Public entry point ──────────────────────────────────────────────────


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
