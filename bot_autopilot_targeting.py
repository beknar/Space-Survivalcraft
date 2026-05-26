"""Selectors, blacklist wrappers, stuck/escape wrappers, station-info
helpers split from ``bot_autopilot``.

Every helper here is functionally pure or reads/writes through the
``_ap._state`` global; constants and the ``_get_now`` clock live on
the ``bot_autopilot`` module and are referenced via ``_ap.X``.
"""
from __future__ import annotations

import math
import random

import bot_autopilot as _ap
import bot_autopilot_blacklist as _bl
import bot_autopilot_navigation as _nav


def _return_wormhole_positions(state: dict) -> list[tuple[float, float]]:
    """Return the (x, y) positions of every wormhole whose
    ``zone_target`` routes back to MAIN, ONLY when the bot is
    currently in a non-MAIN zone.  Empty list otherwise.

    Used by ``_nearest_pickup`` / ``_nearest_asteroid`` to skip
    targets sitting inside a return wormhole's collision +
    repulsion danger zone -- the existing wormhole_repulsion field
    isn't always strong enough to deflect a target-driven path,
    so filtering at selection time is the durable fix.

    The MAIN-zone short-circuit mirrors ``wormhole_repulsion``:
    in MAIN every wormhole is OUTBOUND (target=WARP_*) and the
    bot is allowed (and expected) to route to one for the post-
    boss warp.  Only the Nebula central wormhole and any future
    "back to MAIN" wormhole gets filtered.
    """
    zone_id = str((state.get("zone") or {}).get("id", ""))
    in_main_zone = ("MAIN" in zone_id) and ("WARP" not in zone_id)
    if in_main_zone:
        return []
    out: list[tuple[float, float]] = []
    for wh in (state.get("wormholes") or []):
        zt = str(wh.get("zone_target", ""))
        if "MAIN" in zt:
            out.append((float(wh.get("x", 0.0)),
                        float(wh.get("y", 0.0))))
    return out


def _target_near_return_wormhole(state: dict, x: float, y: float,
                                 radius_px: float | None = None
                                 ) -> bool:
    """Test whether (x, y) sits inside any return wormhole's danger
    zone (collision radius + repulsion range).  Caller decides what
    "near" means via ``radius_px``; default is the sum used by the
    ``wormhole_repulsion`` field.
    """
    if radius_px is None:
        radius_px = (_nav.WORMHOLE_REPULSION_RADIUS_PX
                     + _nav.WORMHOLE_REPULSION_RANGE_PX)
    r2 = radius_px * radius_px
    for (wx, wy) in _return_wormhole_positions(state):
        dx = wx - x
        dy = wy - y
        if dx * dx + dy * dy <= r2:
            return True
    return False


# Margin past the gas cloud's visible radius for the target filter
# (2026-05-17): a pickup spawning right at the cloud's edge would
# pass a strict "inside" test but reaching it still drags the bot
# through the damage zone on approach.  50 px buffer accounts for
# the approach trajectory.
PICKUP_GAS_AVOID_MARGIN_PX: float = 50.0


def _target_in_gas_cloud(state: dict, x: float, y: float,
                         margin_px: float | None = None) -> bool:
    """Test whether (x, y) sits inside any gas cloud's damage zone
    (visible radius + ``margin_px`` safety buffer).  Used by the
    pickup / asteroid selectors to skip targets that would lure
    the bot into a gas cloud where damage compounds faster than
    heal-shield can recover.

    Captured 2026-05-17 bot_io: bot dropped to shields=1 while
    blacklisting three pickups in succession at the NE edge of a
    gas cloud cluster.  The reactive blacklist works but each
    "lesson" cost the bot ~40 shield + several heal-shield uses.
    Pre-filtering at selection eliminates the lesson entirely.
    """
    if margin_px is None:
        margin_px = PICKUP_GAS_AVOID_MARGIN_PX
    for c in (state.get("gas_areas") or []):
        cx = float(c.get("x", 0.0))
        cy = float(c.get("y", 0.0))
        radius = float(c.get("radius", 80.0)) + margin_px
        dx = cx - x
        dy = cy - y
        if dx * dx + dy * dy <= radius * radius:
            return True
    return False


def _pickup_is_blacklisted(pu: dict) -> bool:
    return _bl.pickup_is_blacklisted(
        pu, _ap._state.pickup_blacklist, _ap._get_now)


def _blacklist_pickup(pu: dict) -> None:
    _bl.blacklist_pickup(pu, _ap._state.pickup_blacklist, _ap._get_now)


def _nearest_pickup(state: dict, px: float, py: float
                    ) -> tuple[dict | None, float]:
    """Return (nearest_pickup, distance) skipping blacklisted pickups
    AND those sitting within ``PICKUP_EDGE_SKIP_PX`` of a world
    boundary AND those sitting inside a return wormhole's danger
    zone (when the bot is in a non-MAIN zone).

    Edge filter rationale: pickups spawn wherever an alien dies —
    sometimes right against the world wall.  GATHER chasing one
    pins the bot against the boundary the same way edge-adjacent
    asteroids do.  Mirrors the fix added for ``_nearest_asteroid``
    in PR #25.

    Return-wormhole filter rationale (2026-05-17 bot_io capture):
    in Nebula, the central return wormhole at the zone centre
    teleports the bot back to MAIN on contact.  ``wormhole_repulsion``
    deflects a target-driven path but isn't always strong enough
    to overcome a 2000-px attraction vector aimed past it.  Filtering
    at selection time guarantees the bot never picks a target that
    would route it through the danger zone.  Falls back to the
    unfiltered candidate when every pickup is filtered (rare).
    """
    candidate, d = _bl.nearest_pickup(
        state, px, py, _ap._state.pickup_blacklist, _ap._get_now)
    if candidate is None:
        return (None, d)
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    cx = float(candidate.get("x", 0.0))
    cy = float(candidate.get("y", 0.0))
    margin = _ap.PICKUP_EDGE_SKIP_PX
    edge_ok = (cx >= margin and cx <= world_w - margin
               and cy >= margin and cy <= world_h - margin)
    wh_safe = not _target_near_return_wormhole(state, cx, cy)
    pin_safe = not _ap._target_in_pin_zone(cx, cy)
    gas_safe = not _target_in_gas_cloud(state, cx, cy)
    if edge_ok and wh_safe and pin_safe and gas_safe:
        return (candidate, d)
    # Filter-fail: scan for an alternative pickup that clears the
    # edge AND wormhole-proximity AND pin-zone AND gas-cloud tests.
    # If every pickup fails, the fallback semantics differ by
    # filter: edge / wormhole / pin all fall back to the original
    # candidate (defensive), but gas-cloud filter returns ``None``
    # per user spec ("give up and leave the gas cloud" rather than
    # try to reach a pickup inside it).
    iron = state.get("iron_pickups", []) or []
    bps = state.get("blueprint_pickups", []) or []
    best = None
    best_d = float("inf")
    for pu in (list(bps) + list(iron)):  # blueprints sort first like _bl
        bx = float(pu.get("x", 0.0))
        by = float(pu.get("y", 0.0))
        if (bx < margin or bx > world_w - margin
                or by < margin or by > world_h - margin):
            continue
        if _target_near_return_wormhole(state, bx, by):
            continue
        if _ap._target_in_pin_zone(bx, by):
            continue
        if _target_in_gas_cloud(state, bx, by):
            continue
        if _bl.pickup_is_blacklisted(
                pu, _ap._state.pickup_blacklist, _ap._get_now):
            continue
        d2 = math.hypot(bx - px, by - py)
        if d2 < best_d:
            best, best_d = pu, d2
    if best is None:
        # User spec: if the original candidate is in a gas cloud
        # and no safe alternative exists, GIVE UP -- don't fall
        # back to the in-cloud target.  The bot's _act_gather
        # will see no target and the cascade will route to other
        # behaviors (MINE / SEARCH / IDLE).  If REGEN later
        # detects the bot inside a cloud, its gas-escape branch
        # drives the bot out.
        if not gas_safe:
            return (None, float("inf"))
        return (candidate, d)
    return (best, best_d)


def _asteroid_is_blacklisted(ast: dict) -> bool:
    return _bl.asteroid_is_blacklisted(
        ast, _ap._state.asteroid_blacklist, _ap._get_now)


def _blacklist_asteroid(ast: dict) -> None:
    _bl.blacklist_asteroid(
        ast, _ap._state.asteroid_blacklist, _ap._get_now)


def _nearest_asteroid(state: dict, px: float, py: float
                      ) -> tuple[dict | None, float]:
    """Return (nearest_asteroid, distance) skipping blacklisted
    asteroids AND those sitting within ``ASTEROID_EDGE_SKIP_PX`` of
    a world boundary.

    Edge filter rationale: asteroids spawned right against the
    world wall can't be circled (the bot rams the wall when trying
    to position).  The reactive blacklist (60 s TTL) eventually
    catches each one but the user pays one stuck event per
    asteroid; pre-filtering at selection skips them up front.
    Caught from 2026-05-04 telemetry: 10 MINE stucks at edge-
    adjacent asteroids over a 45-min session.
    """
    candidate, d = _bl.nearest_asteroid(
        state, px, py, _ap._state.asteroid_blacklist, _ap._get_now)
    if candidate is None:
        return (None, d)
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    ax = float(candidate.get("x", 0.0))
    ay = float(candidate.get("y", 0.0))
    margin = _ap.ASTEROID_EDGE_SKIP_PX
    edge_ok = (ax >= margin and ax <= world_w - margin
               and ay >= margin and ay <= world_h - margin)
    wh_safe = not _target_near_return_wormhole(state, ax, ay)
    pin_safe = not _ap._target_in_pin_zone(ax, ay)
    gas_safe = not _target_in_gas_cloud(state, ax, ay)
    if edge_ok and wh_safe and pin_safe and gas_safe:
        return (candidate, d)
    # Filter-fail: scan asteroids list for one that clears the
    # edge AND wormhole-proximity AND pin-zone AND gas-cloud tests.
    # See ``_nearest_pickup`` for the filter rationale.
    asteroids = state.get("asteroids", []) or []
    best = None
    best_d = float("inf")
    for ast in asteroids:
        bx = float(ast.get("x", 0.0))
        by = float(ast.get("y", 0.0))
        if (bx < margin or bx > world_w - margin
                or by < margin or by > world_h - margin):
            continue
        if _target_near_return_wormhole(state, bx, by):
            continue
        if _ap._target_in_pin_zone(bx, by):
            continue
        if _target_in_gas_cloud(state, bx, by):
            continue
        if _bl.asteroid_is_blacklisted(
                ast, _ap._state.asteroid_blacklist, _ap._get_now):
            continue
        d2 = math.hypot(bx - px, by - py)
        if d2 < best_d:
            best, best_d = ast, d2
    if best is None:
        # If the original candidate is in a gas cloud and no safe
        # alternative exists, give up entirely (same shape as the
        # pickup selector).  Otherwise fall back to the original
        # candidate -- let the blacklist + stuck-detect cycle
        # handle it as before.
        if not gas_safe:
            return (None, float("inf"))
        return (candidate, d)
    return (best, best_d)


def _nearest_huntable_alien(state: dict, px: float, py: float,
                            *, currently_hunting: bool = False
                            ) -> tuple[dict | None, float]:
    """Return (nearest_alien, distance) for HUNT target selection,
    skipping aliens within ``ALIEN_EDGE_SKIP_PX`` of a world
    boundary.  Falls back to the unfiltered nearest when every
    visible alien is edge-adjacent so HUNT can still trigger when
    that's all that's available — but the symmetric-exit hysteresis
    (cur == S_HUNT) re-checks via this same helper, so a chase that
    drifts onto the edge will drop back to IDLE/MINE on the next
    tick instead of grinding.

    Defensive layers (ENGAGE, REGEN escape valve) deliberately
    keep using the unfiltered ``nearest`` over ``state['aliens']``
    so an attacker pressing us from the wall still triggers a
    response — only the proactive HUNT chase is gated.

    Wall-pin escape: when ``currently_hunting`` is True (the FSM
    is already in S_HUNT) AND the bot is itself inside the same
    edge margin AND every visible alien is edge-adjacent, return
    ``None`` instead of falling back.  This is the wall-pin re-
    commit pattern caught from 2026-05-06 follow-up telemetry: the
    bot pinned at px=48 in S_HUNT for 95 s because combat had
    herded every alien against the wall and the helper kept
    re-selecting them.  No ``stuck_detected`` fired (the 40 px
    py-oscillation + turn-to-face rotation defeated the position-
    history detector) so the giveup latch never armed.  Returning
    ``None`` lets the FSM cascade reach IDLE_AT_BASE / SEARCH
    which navigates AWAY from the wall and breaks the loop.
    Initial HUNT entries (``currently_hunting=False``) still get
    the fallback so a one-shot proactive chase from open space
    isn't suppressed.
    """
    aliens = state.get("aliens") or []
    if not aliens:
        return (None, float("inf"))
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    margin = _ap.ALIEN_EDGE_SKIP_PX
    best = None
    best_d = float("inf")
    for a in aliens:
        ax = float(a.get("x", 0.0))
        ay = float(a.get("y", 0.0))
        if (ax < margin or ax > world_w - margin
                or ay < margin or ay > world_h - margin):
            continue
        d = math.hypot(ax - px, ay - py)
        if d < best_d:
            best, best_d = a, d
    if best is not None:
        return (best, best_d)
    # Every visible alien is edge-adjacent.  Suppress the fallback
    # only when we're already in S_HUNT and the bot is itself
    # inside the edge margin — that's the wall-pin re-commit
    # signature.  Otherwise fall back so initial proactive chases
    # from open space (or from interior positions) still fire.
    if currently_hunting:
        bot_near_edge = (
            px < margin or px > world_w - margin
            or py < margin or py > world_h - margin)
        if bot_near_edge:
            return (None, float("inf"))
    return _ap.nearest(aliens, px, py)


# ── Stuck detect + escape wrappers (impl in bot_autopilot_navigation) ───

def _record_position(p: dict) -> None:
    _nav.record_position(p, _ap._stuck_state, _ap._get_now)


def _detect_stuck() -> bool:
    return _nav.detect_stuck(_ap._stuck_state)


def _wall_pin_trap_active(state: dict, p: dict) -> bool:
    """True when the bot is in the wall+cluster trap geometry: bot
    inside ``STUCK_ESCAPE_CLEAR_MARGIN_PX`` of a world edge AND a
    building cluster's centroid sits between the bot and the world
    interior on the wall-pinned axis.

    Mirrors the gate in ``compute_escape_target``'s wall-tangent
    path (PR #42) so the geometry-aware force-escape and the
    wall-tangent target use the same trap definition.
    """
    buildings = state.get("buildings") or []
    if not buildings:
        return False
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    margin = _ap.STUCK_ESCAPE_CLEAR_MARGIN_PX
    near_west = px < margin
    near_east = px > world_w - margin
    near_south = py < margin
    near_north = py > world_h - margin
    if not (near_west or near_east or near_south or near_north):
        return False
    sx = sum(float(b.get("x", 0.0)) for b in buildings)
    sy = sum(float(b.get("y", 0.0)) for b in buildings)
    n = len(buildings)
    cx = sx / n
    cy = sy / n
    # Require the bot's wall-parallel coordinate to lie within the
    # cluster's perpendicular extent (plus one repulsion-range
    # buffer) before declaring the trap.  Without this gate the
    # detector fires whenever the cluster centroid is on the inland
    # side of the bot, even if the bot is far above/below the
    # cluster — at which point inland motion clears the cluster
    # laterally and forcing escape mode just keeps the bot pinned
    # to the wall.  Mirrors the equivalent gate in
    # ``compute_escape_target`` (PR for the 2026-05-07 telemetry
    # showing the bot oscillating at (370, 4542) with cluster
    # centred at (390, 4030)).
    r = 0.0
    for b in buildings:
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        d = math.hypot(bx - cx, by - cy)
        if d > r:
            r = d
    extent = r + _ap.BUILDING_REPULSION_RANGE_PX
    if near_west or near_east:
        if abs(py - cy) > extent:
            return False
        return (near_west and cx > px) or (near_east and cx < px)
    # near_south or near_north
    if abs(px - cx) > extent:
        return False
    return (near_south and cy > py) or (near_north and cy < py)


def _maybe_force_wall_pin_escape(state: dict, p: dict,
                                 now: float) -> None:
    """Geometry-aware backstop for the position-history stuck
    detector.  When the bot has been in the wall+cluster trap
    geometry for ``WALL_PIN_TRAP_WINDOW_S`` AND has not moved more
    than ``WALL_PIN_TRAP_PROGRESS_PX`` over that window, force-arm
    the escape mechanism so ``compute_escape_target``'s wall-
    tangent path takes over.

    Why this is needed: the navigation-layer ``detect_stuck`` has a
    rotation gate (>30° rotation in the 1.5 s window short-circuits
    the "stuck" classification) that legitimately filters out
    "rotating-to-aim" cases.  But it also misses the wall-pin where
    the bot is rotating to track a wall-glued alien while making
    only ~1 px/s of net translation.  Trap geometry confirms the
    pin without depending on rotation; the existing escape
    machinery handles the rest.
    """
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    if not _wall_pin_trap_active(state, p):
        # Trap conditions not met — reset the anchor so the next
        # entry into the trap restarts the timer cleanly.
        _ap._state.wall_pin_anchor_at = 0.0
        return
    if _ap._stuck_state["escape_until"] > 0.0:
        # Escape already active — the stuck-watchdog block below
        # owns the dispatch + exit conditions.  Reset the anchor
        # so the next cycle (after escape ends) starts fresh.
        _ap._state.wall_pin_anchor_at = 0.0
        return
    if _ap._state.wall_pin_anchor_at == 0.0:
        # First tick in the trap — set the anchor.
        _ap._state.wall_pin_anchor = (px, py)
        _ap._state.wall_pin_anchor_at = now
        return
    # In trap with an anchor.  Check elapsed time + displacement.
    elapsed = now - _ap._state.wall_pin_anchor_at
    if elapsed < _ap.WALL_PIN_TRAP_WINDOW_S:
        return
    ax, ay = _ap._state.wall_pin_anchor
    moved = math.hypot(px - ax, py - ay)
    if moved >= _ap.WALL_PIN_TRAP_PROGRESS_PX:
        # Bot is making net progress — re-anchor and keep watching.
        _ap._state.wall_pin_anchor = (px, py)
        _ap._state.wall_pin_anchor_at = now
        return
    # Trap confirmed: bot has been wall-pinned in cluster-blocking
    # geometry for >= WALL_PIN_TRAP_WINDOW_S with displacement
    # < WALL_PIN_TRAP_PROGRESS_PX.  Force-arm the escape so
    # compute_escape_target's wall-tangent path runs.
    _ap._stuck_state["escape_until"] = now + _ap.STUCK_ESCAPE_MIN_DURATION_S
    _ap._stuck_state["history"] = []
    _ap._state.wall_pin_anchor_at = 0.0  # reset; next trap entry restarts


def _ship_clear_of_edges(p: dict, zone: dict) -> bool:
    return _nav.ship_clear_of_edges(p, zone)


def _ship_clear_of_buildings(p: dict, state: dict) -> bool:
    return _nav.ship_clear_of_buildings(p, state)


def _do_escape_edge(state: dict, p: dict) -> None:
    """Override movement: head AWAY from whatever is pinning the
    ship — boundary edge, station building, or both.  Direction
    comes from ``compute_escape_target``; this wrapper hands off
    to ``_do_goto`` so weapon / thrust state stays consistent
    with the rest of the FSM."""
    tx, ty = _nav.compute_escape_target(state, p)
    # stop_radius is generous so the escape ends as soon as we're
    # clearly off the obstacle, not when we reach the exact target.
    _ap._do_goto(state, p, tx, ty, stop_radius=300.0)


def _iron_total(state: dict) -> int:
    """Iron count from the player inventory snapshot in /state.
    The state.inventory.items dict is keyed by item name."""
    items = (state.get("inventory") or {}).get("items") or {}
    return int(items.get("iron", 0))


def _ship_has_blueprint(state: dict) -> bool:
    """True when the ship inventory contains any blueprint pickup
    (item names starting with ``bp_``).  Used as one of the
    triggers for the S_DEPOSIT state — the user wants blueprints
    in the home station inventory, not the ship's."""
    items = (state.get("inventory") or {}).get("items") or {}
    return any(name.startswith("bp_") for name in items.keys())


def _find_home_station(state: dict) -> dict | None:
    """Locate the Home Station building in the /state snapshot.
    Returns the building dict (with x, y) or None if the bot
    hasn't built one yet.  Matches on the ``building_type``
    field that bot_api stamps onto every building sprite."""
    for b in state.get("buildings") or []:
        if b.get("building_type") == "Home Station":
            return b
    return None


def _find_basic_crafter(state: dict, *, idle_only: bool = True
                        ) -> dict | None:
    """Locate a Basic Crafter building.  When ``idle_only`` is True
    (default) only returns one that's currently not crafting and
    not disabled — what S_CRAFT navigates toward.  When False,
    returns any Basic Crafter (used to test whether the build
    phase has produced one yet)."""
    for b in state.get("buildings") or []:
        if b.get("building_type") != "Basic Crafter":
            continue
        if idle_only and (
                b.get("crafting", False) or b.get("disabled", False)):
            continue
        return b
    return None


def _any_crafter_busy(state: dict) -> bool:
    """True when at least one Basic Crafter is mid-craft.  The bot
    waits on this so it doesn't queue a second craft while a
    pending one is still ticking — the craft queue is intentionally
    serial."""
    for b in state.get("buildings") or []:
        if b.get("building_type") != "Basic Crafter":
            continue
        if b.get("crafting", False):
            return True
    return False


def _station_items(state: dict) -> dict:
    """Station-inventory item-name → count map from /state.  Empty
    dict if the home station hasn't been built (then /state
    returns no station_inventory).  Used by the craft queue to
    gate on iron, blueprints, and crafted-module presence without
    touching gv state."""
    return (state.get("station_inventory") or {}).get("items") or {}


def _station_iron(state: dict) -> int:
    return int(_station_items(state).get("iron", 0))


def _all_blueprints_deposited(state: dict) -> bool:
    """True when every blueprint in MODULE_CRAFT_QUEUE has been
    deposited at the home station (count >= 1).  Pre-condition for
    entering the module-craft phase — the user wants to be sure
    every recipe is unlocked before the queue starts."""
    items = _station_items(state)
    for key in _ap.MODULE_CRAFT_QUEUE:
        if items.get(f"bp_{key}", 0) < 1:
            return False
    return True


def _module_already_installed(state: dict, mod_key: str) -> bool:
    """True when ``mod_key`` is currently in one of the ship's
    installed module slots.  Used by the install queue to skip
    keys that ended up installed via some other path (e.g. the
    user dropped one manually mid-run)."""
    slots = state.get("module_slots") or []
    return mod_key in slots


def _build_area_clear(state: dict, px: float, py: float) -> bool:
    """True when nothing detectable is within
    ``BUILD_CLEAR_RADIUS_PX`` of the player — checked across
    asteroids, aliens, pickups, and existing buildings.  Used as
    the pre-condition for entering S_BUILD."""
    r_sq = _ap.BUILD_CLEAR_RADIUS_PX * _ap.BUILD_CLEAR_RADIUS_PX
    for key in ("asteroids", "aliens",
                "iron_pickups", "blueprint_pickups", "buildings"):
        for o in state.get(key) or []:
            dx = o.get("x", 0.0) - px
            dy = o.get("y", 0.0) - py
            if dx * dx + dy * dy < r_sq:
                return False
    return True


def _build_seek_direction(state: dict, px: float, py: float
                          ) -> tuple[float, float]:
    """Return a unit vector pointing AWAY from the centroid of
    nearby detectables — the direction of least clutter.  Used
    by S_BUILD_SEEK to actively find a clear pocket instead of
    waiting passively for one to appear.

    Considers detectables within twice the build clear radius so
    the bot reacts to clutter just outside its visible screen."""
    scan_r_sq = (_ap.BUILD_CLEAR_RADIUS_PX * 2.0) ** 2
    cx_sum = 0.0
    cy_sum = 0.0
    n = 0
    for key in ("asteroids", "aliens",
                "iron_pickups", "blueprint_pickups", "buildings"):
        for o in state.get(key) or []:
            ox = o.get("x", 0.0)
            oy = o.get("y", 0.0)
            dx = ox - px
            dy = oy - py
            if dx * dx + dy * dy < scan_r_sq:
                cx_sum += ox
                cy_sum += oy
                n += 1
    if n == 0:
        # Already clear — caller shouldn't have entered seek mode.
        # Pick an arbitrary forward direction so we still return
        # something sensible.
        return (0.0, 1.0)
    cx = cx_sum / n
    cy = cy_sum / n
    dx = px - cx
    dy = py - cy
    d = math.hypot(dx, dy)
    if d < 0.1:
        # Centroid coincides with the ship — pick a random heading
        # so we don't sit in place.
        ang = random.random() * 2.0 * math.pi
        return (math.cos(ang), math.sin(ang))
    return (dx / d, dy / d)


def _consumable_phase_finished() -> bool:
    """True iff the bot's consumable craft phase has finished its
    25 + 25 batches.  Reads ``_state.queue`` directly so callers
    don't have to thread the queue through their args."""
    q = _ap._state.queue
    return (q.repair_packs_remaining <= 0
            and q.shield_recharges_remaining <= 0
            and q.consumable_phase_started)


def _consumables_in_station_inv(state: dict) -> bool:
    """True when the station inventory still has at least one
    repair pack OR shield recharge waiting to be withdrawn."""
    items = _station_items(state)
    return (int(items.get("repair_pack", 0)) > 0
            or int(items.get("shield_recharge", 0)) > 0)


def _qwi_already_built(state: dict) -> bool:
    """True when a Quantum Wave Integrator is already in the
    building list (either placed by the bot earlier or — defensively
    — placed manually by the player)."""
    for b in state.get("buildings") or []:
        if b.get("building_type") == "Quantum Wave Integrator":
            return True
    return False


def _advanced_crafter_already_built(state: dict) -> bool:
    """True when an Advanced Crafter is already in the building
    list (placed by the bot earlier, loaded from save, or manually
    placed).  Used to short-circuit the BUILD_ADV_CRAFTER trigger
    without churning the latch each tick the bot sees one."""
    for b in state.get("buildings") or []:
        if b.get("building_type") == "Advanced Crafter":
            return True
    return False


def _recovery_loadout_ready(state: dict) -> bool:
    """True iff the bot is fit to drive into the non-MAIN
    death-recovery danger zone.  Used by the choose-cascade gate
    at section 1.4 to defer ``S_RECOVER_LOOT`` until the bot has
    healed + re-equipped.

    Requirements (in non-MAIN zones):
      * shields and hp at or above ``RECOVER_LOOT_*_PCT`` of their
        respective max,
      * at least one repair pack AND one shield recharge bound to
        a quick-use slot.

    MAIN-zone recoveries skip the gate entirely -- the HS umbrella
    + turret ring make recovery safe even with a stripped ship.
    """
    zone_id = str((state.get("zone") or {}).get("id", ""))
    # Only gate explicitly-known non-MAIN zones.  Empty / unknown
    # zone_id defaults to "assume MAIN" so test stubs that don't
    # bother setting zone_id retain the pre-2026-05-26 behaviour.
    in_danger_zone = (
        "ZONE2" in zone_id
        or "WARP" in zone_id
        or "STAR_MAZE" in zone_id)
    if not in_danger_zone:
        return True
    player = state.get("player") or {}
    hp = int(player.get("hp", 0))
    hp_max = max(1, int(player.get("max_hp", 1)))
    sh = int(player.get("shields", 0))
    sh_max = max(1, int(player.get("max_shields", 1)))
    if (hp / hp_max) < _ap.RECOVER_LOOT_HP_PCT:
        return False
    if (sh / sh_max) < _ap.RECOVER_LOOT_SHIELDS_PCT:
        return False
    slots = state.get("quick_use_slots") or []
    have_repair = any(
        (s.get("item_type") == "repair_pack"
         and int(s.get("count", 0)) > 0)
        for s in slots)
    have_shield = any(
        (s.get("item_type") == "shield_recharge"
         and int(s.get("count", 0)) > 0)
        for s in slots)
    return have_repair and have_shield


def _qwi_ready_to_build(state: dict) -> tuple[bool, str]:
    """Predicate gate for Choice 1 — pre-trigger boss staging.

    Returns ``(ready, reason)``.  ``ready`` is True only when:

      * a Home Station exists,
      * at least ``QWI_STAGE_MIN_TURRETS`` Defense Turrets / Turret 2
        / Missile Array entries are placed (counts the cluster's
        defensive umbrella, not just one type),
      * the player ship has been upgraded to at least
        ``QWI_STAGE_MIN_SHIP_LEVEL``.

    A future build sequence that wants to auto-place the QWI should
    call this predicate first and skip the placement when it returns
    False — pulling the trigger before the station is ready is
    irreversible (the boss spawn flag is one-shot).
    """
    if _find_home_station(state) is None:
        return False, "no_home_station"
    buildings = state.get("buildings") or []
    defenders = sum(
        1 for b in buildings
        if (b.get("building_type") or "") in (
            "Defense Turret", "Turret 2", "Missile Array")
    )
    if defenders < _ap.QWI_STAGE_MIN_TURRETS:
        return False, f"defenders_{defenders}_lt_{_ap.QWI_STAGE_MIN_TURRETS}"
    p = state.get("player") or {}
    ship_level = int(p.get("ship_level", 1))
    if ship_level < _ap.QWI_STAGE_MIN_SHIP_LEVEL:
        return False, f"ship_level_{ship_level}_lt_{_ap.QWI_STAGE_MIN_SHIP_LEVEL}"
    return True, "ok"


def _find_quick_use_slot(slots: list, item_type: str) -> int | None:
    """First quick-use slot that holds ``item_type`` with count > 0,
    or None if no such slot exists."""
    for i, s in enumerate(slots):
        if s.get("item_type") == item_type \
                and int(s.get("count", 0)) > 0:
            return i
    return None


def _next_craft_target(state: dict) -> str | None:
    """Return the next thing the bot wants to craft, or ``None`` if
    the queue is empty / preconditions aren't met.  Encapsulates
    the three-phase workflow:

      1. Modules from MODULE_CRAFT_QUEUE (gated by
         CRAFT_PHASE_IRON_THRESHOLD = 2000 iron on entry, then by
         per-module cost + matching blueprint).
      2. Repair packs (after install queue is drained, gated by
         CONSUMABLE_PHASE_IRON_THRESHOLD = 500 on entry; the latch
         then auto-flips so a subsequent iron dip can't stall).
      3. Shield recharges (after repair packs are done).

    Each phase's entry gate sticks once the phase has started — so
    the bot doesn't stall mid-queue if iron drops below the entry
    threshold after the first craft pays out.  The consumable
    threshold is much lower than the module threshold because
    consumables are cheap (100 iron each) and incremental mining
    covers them while the crafter ticks down its 60 s timer.
    """
    from constants import MODULE_TYPES, CRAFT_IRON_COST  # local import: kept off the
                                                          # autopilot's hot path; this
                                                          # function only fires when the
                                                          # craft phase is reachable.
    q = _ap._state.queue
    items = _station_items(state)
    iron = int(items.get("iron", 0))

    # ── Module craft phase ────────────────────────────────────────
    # Skip-and-pop heads that are already crafted (sitting in
    # station inventory as ``mod_<key>``) or already installed on
    # the ship.  Catches the session-restart case: a process that
    # connects to an existing world with prior progress has
    # ``CraftQueue`` reset to the full ``MODULE_CRAFT_QUEUE`` even
    # though some modules are already done.  Without this skip the
    # bot would re-craft every module it already had -- user
    # complaint 2026-05-10: "the bot should only build the modules
    # once, and it has built them multiple times".
    #
    # Mirrors the equivalent guard in ``_next_install_target``
    # (which only checks "already installed"); here we also check
    # the station-inv ``mod_<key>`` count so a previously-crafted
    # but not-yet-installed module isn't re-crafted either.
    while q.modules_to_craft:
        head = q.modules_to_craft[0]
        # Advanced consumables (homing_missile / mining_drone /
        # combat_drone) produce ``item_key`` items in station
        # inventory, NOT ``mod_<head>``, so the basic-module guard
        # below would spin forever on them.  Pop the head once
        # station-inv stock of the produced item meets its target.
        adv_target = _ap.NEBULA_ADV_CONSUMABLE_TARGETS.get(head)
        if adv_target is not None:
            item_key, target_count = adv_target
            if items.get(item_key, 0) >= target_count:
                q.modules_to_craft.pop(0)
                continue
            break
        already_in_station = items.get(f"mod_{head}", 0) >= 1
        already_installed = _module_already_installed(state, head)
        if already_in_station or already_installed:
            q.modules_to_craft.pop(0)
            continue
        break

    if q.modules_to_craft:
        # 2000-iron gate on the FIRST module craft only.
        if not q.module_phase_started and iron < _ap.CRAFT_PHASE_IRON_THRESHOLD:
            return None
        # Every blueprint must already be in the station inventory
        # before we start the phase.  Once started, individual
        # blueprint counts are checked per-craft.
        if not q.module_phase_started and not _all_blueprints_deposited(state):
            return None
        head = q.modules_to_craft[0]
        cost = int(MODULE_TYPES.get(head, {}).get("craft_cost", 0))
        if iron < cost:
            return None
        if items.get(f"bp_{head}", 0) < 1:
            return None
        return head

    # ── Repair pack phase ─────────────────────────────────────────
    # Install must be drained before consumables; the gate below
    # already enforces that via the FSM-level ordering, but we
    # double-check here to keep the helper standalone.
    if q.modules_to_install:
        return None

    # Auto-flip the consumable-phase latch the moment the install
    # queue empties IF station iron is past the entry buffer.  This
    # latches the phase started so a later iron dip doesn't re-
    # gate.  Without the auto-flip the bot deadlocked when station
    # iron sat between CRAFT_IRON_COST (100) and
    # CONSUMABLE_PHASE_IRON_THRESHOLD (500): per-craft cost was
    # met but the entry gate held forever.
    if (not q.consumable_phase_started
            and iron >= _ap.CONSUMABLE_PHASE_IRON_THRESHOLD):
        q.consumable_phase_started = True

    if q.repair_packs_remaining > 0:
        # Consumable phase uses CONSUMABLE_PHASE_IRON_THRESHOLD
        # (500) as the entry gate — much lower than the module
        # phase's 2000 because consumables are cheap (100 iron
        # per batch) and incremental mining covers them while
        # the crafter ticks.  Once the phase has started the
        # gate stops applying so a transient iron dip can't
        # stall the queue.
        if (not q.consumable_phase_started
                and iron < _ap.CONSUMABLE_PHASE_IRON_THRESHOLD):
            return None
        if iron < CRAFT_IRON_COST:
            return None
        return "repair_pack"

    # ── Shield recharge phase ─────────────────────────────────────
    if q.shield_recharges_remaining > 0:
        if (not q.consumable_phase_started
                and iron < _ap.CONSUMABLE_PHASE_IRON_THRESHOLD):
            return None
        if iron < CRAFT_IRON_COST:
            return None
        return "shield_recharge"

    return None


def _next_install_target(state: dict) -> str | None:
    """Return the head of the install queue iff its
    ``mod_<key>`` is sitting in station inventory and the key
    isn't already installed on the ship.  Else None.
    """
    q = _ap._state.queue
    if not q.modules_to_install:
        return None
    head = q.modules_to_install[0]
    if _module_already_installed(state, head):
        # Skip ahead — somebody installed it manually.  Pop and
        # let the next tick re-evaluate.
        q.modules_to_install.pop(0)
        return None
    items = _station_items(state)
    if items.get(f"mod_{head}", 0) < 1:
        return None
    return head
