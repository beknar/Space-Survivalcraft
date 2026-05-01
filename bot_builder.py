"""In-process starter-base builder for the bot.

When called via ``build_starter_base(gv)``, places a fixed sequence
of seven buildings around the player's current position.  Designed
to be triggered via ``POST /build_starter_base`` on the bot HTTP
API (the autopilot fires this once it has accumulated enough iron
and is in a clear area).

Sequence (positions are relative to the player at trigger time):

  1. Home Station   at (px,         py)         -- anchor
  2. Service Module at (px,         py + 60)    -- snaps to N port of HS
  3. Power Receiver at (px,         py + 120)   -- snaps to N port of SM
  4. Solar Array 2  at (px,         py + 200)   -- snaps to N port of PR
  5. Repair Module  at (px + 60,    py + 60)    -- snaps to E port of SM
  6. Turret 2       at (px + 300,   py)         -- max-distance free place
  7. Turret 2       at (px - 300,   py)         -- max-distance free place

Each step goes through the standard
``building_manager.enter_placement_mode`` +
``building_manager.place_building`` chain, so resource deduction,
max-count, snap-port, and connectivity checks all apply exactly
as they would if the player drove the build menu.

Threading: this runs in the HTTP-handler thread (same as the
existing ``POST /build`` endpoint), which mutates ``gv``
attributes directly.  arcade SpriteList isn't strictly thread
safe but the operation is short and synchronous, so races with
the game's 60 Hz tick are very unlikely in practice.
"""
from __future__ import annotations

from typing import Any


# ── Build sequence ────────────────────────────────────────────────────────

# (building_type, dx_from_player, dy_from_player).  The dy values
# are forward of the ship (the player is anchored at world origin
# for the calc), and the snap logic in ``place_building`` will pull
# each module onto the appropriate port even if our coordinate is a
# few pixels off-grid.
STARTER_BASE_SEQUENCE: list[tuple[str, float, float]] = [
    ("Home Station",     0.0,    0.0),
    ("Service Module",   0.0,   60.0),
    ("Power Receiver",   0.0,  120.0),
    ("Solar Array 2",    0.0,  200.0),
    ("Repair Module",   60.0,   60.0),
    ("Turret 2",       300.0,    0.0),
    ("Turret 2",      -300.0,    0.0),
]


def build_starter_base(gv: Any) -> dict:
    """Walk the starter-base build sequence in one call.

    Returns a JSON-serialisable dict reporting which buildings were
    placed successfully and which failed (with reasons).  Resource
    cost validation, snap-port alignment, and max-count gates are
    enforced by ``building_manager.place_building`` itself; this
    function just sequences the calls and records the outcome.
    """
    import building_manager as bm

    px = gv.player.center_x
    py = gv.player.center_y
    placed: list[dict] = []
    failed: list[dict] = []
    initial_count = len(gv.building_list)

    for bt, dx, dy in STARTER_BASE_SEQUENCE:
        wx = px + dx
        wy = py + dy
        before = len(gv.building_list)
        try:
            bm.enter_placement_mode(gv, bt)
            bm.place_building(gv, wx, wy)
        except Exception as e:
            # Defensive: if anything in placement raises, cancel
            # the ghost so the menu doesn't get stuck and continue
            # with the next building.
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
            # ``place_building`` silently cancels on failure (cost
            # too high, connectivity rejected, max-count hit).
            failed.append(
                {"type": bt, "reason": "placement rejected",
                 "at": [wx, wy]})

    return {
        "placed": placed,
        "failed": failed,
        "buildings_added": len(gv.building_list) - initial_count,
        "total_buildings_now": len(gv.building_list),
    }
