"""Movement primitives split from ``bot_autopilot``.

All ``_do_*`` helpers and ``execute_intent`` live here.  Each one
references constants and tunables on the ``bot_autopilot``
module via ``_ap`` so the autopilot keeps owning configuration.
"""
from __future__ import annotations

import math
import time

import bot_autopilot as _ap
import bot_autopilot_navigation as _nav

try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore


# Module-level state for ``_ensure_weapon`` — kept here because the
# rate-limiter only matters for this module.
_last_cycle_t: float = 0.0


def _do_idle() -> None:
    _ap.KeyState.release_all()


def _do_goto(state: dict, p: dict, tx: float, ty: float,
             stop_radius: float = 80.0,
             brake_on_arrival: bool = True) -> None:
    """Rotate toward (tx, ty) and thrust until within ``stop_radius``.

    The heading is blended through ``_steered_heading`` so the
    boundary potential field deflects the bot away from world
    edges before it pins itself — see the BOUNDARY_REPULSION_*
    constants for tuning.  Without this the bot would chase
    edge-adjacent targets right into the wall and rely on the
    reactive stuck-detect watchdog to pull it out.

    ``brake_on_arrival`` (default True) engages the ``s`` reverse-
    thrust key the moment the bot enters the stop radius, so chase
    targets stop cleanly.  Spiral search passes False so the bot
    coasts through consecutive close-spaced targets instead of
    braking-then-recovering for each one (the brake-coast pattern
    matched the stuck-detect criteria and triggered ~30 false-fire
    escape bursts per session).

    Routing layers (applied in order before the heading + thrust
    decision):

    * **A* path** — when the straight-line bot→target segment
      crosses building cluster blocked cells, ``_astar_next_waypoint``
      returns the next intermediate waypoint and the goto target is
      redirected to it.  This gives the bot proper free-space
      navigation around obstacles instead of relying on the
      reactive cluster_detour + stuck-detect machinery alone.
      Cached on ``_state.path_*`` so a stable target reuses the
      plan across ticks.

    * **Cluster detour** — legacy tangent-based detour around a
      cluster centroid.  Still used when A* is bypassed (open
      line-of-sight to target) but the goto path nicks the cluster
      from one side; the tangent waypoint pulls the bot wide.
      Suppressed when the destination IS inside the cluster
      (deposit / craft / install) so docking actions complete.
    """
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    final_target = (tx, ty)  # remember for repulsion suppression

    # A* routing first — when the straight line is blocked, follow
    # the planned waypoint chain instead of fighting the building-
    # repulsion field.
    astar_wp = _ap._astar_next_waypoint(state, px, py, tx, ty)
    if astar_wp == "unreachable":
        # Goal cell is blocked or unreachable — caller's stuck-
        # detect / blacklist machinery will handle abandoning the
        # target.  Fall through to the existing direct-goto so the
        # bot at least faces the right direction while the
        # higher-level FSM re-evaluates.
        pass
    elif astar_wp is not None:
        tx, ty = astar_wp

    # Fall back to the legacy tangent-based cluster detour for the
    # direct-line-of-sight case.  No-op if A* already routed.
    if astar_wp is None:
        waypoint = _nav.cluster_detour_waypoint(state, px, py, tx, ty)
        if waypoint is not None:
            tx, ty = waypoint
    dx = tx - px
    dy = ty - py
    dist = math.hypot(dx, dy)
    if dist < stop_radius:
        # Arrived — release thrust + rotation.  Engage brake only
        # if the caller asked for it; spiral search wants the bot
        # to coast, not brake.
        _ap.KeyState.hold("w", False)
        _ap.KeyState.hold("a", False)
        _ap.KeyState.hold("d", False)
        _ap.KeyState.hold("s", brake_on_arrival)
        return
    _ap.KeyState.hold("s", False)
    target = _nav.steered_heading(state, p, dx, dy, dist,
                                  target=final_target)
    delta = _ap.heading_delta(p.get("heading", 0.0), target)
    if delta < -5.0:
        _ap.KeyState.hold("a", True);  _ap.KeyState.hold("d", False)
    elif delta > 5.0:
        _ap.KeyState.hold("a", False); _ap.KeyState.hold("d", True)
    else:
        _ap.KeyState.hold("a", False); _ap.KeyState.hold("d", False)
    # Only thrust forward when roughly aligned (within 45° of target).
    _ap.KeyState.hold("w", abs(delta) < 45.0)


def _do_hold_distance(state: dict, p: dict, tx: float, ty: float,
                      hold_radius: float,
                      dead_band: float = None  # type: ignore[assignment]
                      ) -> None:
    """Maintain ``hold_radius`` distance from (tx, ty) while always
    facing it.  Used for melee mining with the energy pickaxe — the
    bot needs to keep the asteroid in the swing arc without ramming
    it.  Thrust forward when too far, reverse when too close, coast
    inside the dead-band to avoid jitter.

    Heading is steered through the boundary repulsion field, so an
    asteroid sitting near the edge gets engaged from a position
    that doesn't pin the ship against the wall during the swing
    cycle.
    """
    if dead_band is None:
        dead_band = _ap.PICKAXE_HOLD_DEAD_BAND_PX
    dx = tx - p.get("x", 0)
    dy = ty - p.get("y", 0)
    dist = math.hypot(dx, dy)
    # Always rotate to face the target so the swing arc covers it.
    target = _nav.steered_heading(state, p, dx, dy, dist, target=(tx, ty))
    delta = _ap.heading_delta(p.get("heading", 0.0), target)
    if delta < -5.0:
        _ap.KeyState.hold("a", True);  _ap.KeyState.hold("d", False)
    elif delta > 5.0:
        _ap.KeyState.hold("a", False); _ap.KeyState.hold("d", True)
    else:
        _ap.KeyState.hold("a", False); _ap.KeyState.hold("d", False)
    # Distance control with hysteresis around hold_radius.
    if dist > hold_radius + dead_band:
        # Too far — thrust forward (only when roughly aligned).
        _ap.KeyState.hold("w", abs(delta) < 45.0)
        _ap.KeyState.hold("s", False)
    elif dist < hold_radius - dead_band:
        # Too close — reverse-thrust to back off.  ``s`` is
        # ``thrust_bwd`` in the player controls (not just brake),
        # so this actively pushes the ship away.
        _ap.KeyState.hold("w", False)
        _ap.KeyState.hold("s", True)
    else:
        # In the dead-band — coast in place.
        _ap.KeyState.hold("w", False)
        _ap.KeyState.hold("s", False)


def _do_spiral_search(state: dict, p: dict) -> None:
    """Drive the ship in an outward spiral around the position
    where the spiral started, sweeping the field for any asteroid
    that became reachable.  Re-anchors if the spiral has run for
    too long without finding anything."""
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    if _ap._spiral_state["anchor"] is None:
        _ap._spiral_state["anchor"] = (px, py)
        _ap._spiral_state["angle"] = 0.0
        _ap._spiral_state["radius"] = 100.0
    ax, ay = _ap._spiral_state["anchor"]
    r = _ap._spiral_state["radius"]
    a = _ap._spiral_state["angle"]
    tx = ax + math.cos(a) * r
    ty = ay + math.sin(a) * r
    # Clamp the spiral target to the world rect (with a margin) so
    # the bot doesn't keep aiming at a point off the map and ram
    # the boundary.  Without this clamp, the spiral was the most
    # common cause of edge-stuck cases reported in play-testing.
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 0) or 0)
    world_h = float(zone.get("world_h", 0) or 0)
    if world_w > 0:
        tx = max(_ap.STUCK_WORLD_MARGIN_PX,
                 min(world_w - _ap.STUCK_WORLD_MARGIN_PX, tx))
    if world_h > 0:
        ty = max(_ap.STUCK_WORLD_MARGIN_PX,
                 min(world_h - _ap.STUCK_WORLD_MARGIN_PX, ty))
    # Same sticky weapon as the active mining session — search
    # phase is just positioning, but staying on the picked weapon
    # avoids a Tab the moment we find a target.
    _ap._ensure_weapon(state, _ap._state.mining_weapon_pick)
    # stop_radius=40 px (down from 120) so consecutive spiral
    # targets — which can be only ~7 px apart in tangent at small
    # radii — aren't already "arrived" the moment the spiral
    # advances; brake_on_arrival=False so the bot coasts through
    # nearby targets instead of braking-then-recovering.  Together
    # these two changes eliminate the brake-coast pattern that
    # was triggering ~30 false-fire stuck-detect events per session.
    _ap._do_goto(state, p, tx, ty, stop_radius=40.0,
             brake_on_arrival=False)
    # Only fire when an asteroid is actually in mining range.
    # Used to fire continuously as a "drift past extraction lag"
    # safety net, but that ended up making the bot mine empty
    # space at the centre of the world after a stuck-escape with
    # no real targets nearby.  Blacklist-aware so we don't burn
    # the laser on an asteroid we just gave up on.
    nearest_ast, nd = _ap._nearest_asteroid(state, px, py)
    if _ap._state.mining_weapon_pick == "Energy Pickaxe":
        in_range = (
            nearest_ast is not None and nd < _ap.PICKAXE_MINING_RANGE_PX)
    else:
        in_range = (
            nearest_ast is not None and nd < _ap.MINING_RANGE_PX)
    _ap.KeyState.hold("space", in_range)
    # Advance the spiral incrementally each tick.  Angle advance
    # rate is tuned (SPIRAL_ANGLE_ADVANCE_RAD) so the tangential
    # target speed at typical orbit radii stays under what the
    # ship can actually rotate to follow — otherwise the bot
    # perpetually re-orients without thrusting and looks like
    # it's "rotating endlessly" in place.
    _ap._spiral_state["angle"] = (a + _ap.SPIRAL_ANGLE_ADVANCE_RAD) % (2 * math.pi)
    _ap._spiral_state["radius"] = min(r + 1.5, 3000.0)
    if _ap._spiral_state["radius"] >= 3000.0:
        _ap._spiral_reset()


def _do_mine_nearest(state: dict, p: dict) -> None:
    import bot_autopilot_astar as _astar
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    target, dist = _ap._nearest_asteroid(state, px, py)
    if target is None:
        _ap._do_idle()
        return
    # Reachability check (2026-05-07 follow-up): asteroid wedged
    # behind the cluster, on the far side of a wall, etc., gets
    # blacklisted up front so the bot doesn't pin against the
    # repulsion field for tens of seconds.  Capped at one
    # re-attempt so a degenerate "all asteroids unreachable"
    # frame can't loop more than twice.
    for _attempt in range(2):
        if _astar.target_reachable(
                state, px, py, float(target["x"]), float(target["y"])):
            break
        _ap._blacklist_asteroid(target)
        print(f"[autopilot] ASTEROID-BLACKLIST (unreachable): "
              f"({target['x']:.0f}, {target['y']:.0f})")
        _ap._astar_invalidate_path()
        target, dist = _ap._nearest_asteroid(state, px, py)
        if target is None:
            _ap._do_idle()
            return
    else:
        _ap._do_idle()
        return
    _ap._ensure_weapon(state, _ap._state.mining_weapon_pick)
    # Clamp the chase target to inside the world rect so an
    # edge-adjacent asteroid doesn't pull the bot into the
    # boundary repulsion local minimum.  Mining Beam range is
    # 400 px vs the 200 px world margin — plenty of reach to
    # mine from inside the safety zone.  ``dist`` (used for the
    # fire gate) is NOT clamped — that's still the real distance
    # to the asteroid so the fire trigger respects the actual
    # weapon range.
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _nav.clamp_to_world(
        target["x"], target["y"], zone)
    if _ap._state.mining_weapon_pick == "Energy Pickaxe":
        # Pickaxe is melee — hold optimal swing distance instead
        # of closing all the way and ramming the asteroid.  After
        # the asteroid is destroyed the FSM transitions to GATHER,
        # which uses _do_goto to close on the iron pickup.
        _ap._do_hold_distance(state, p, chase_x, chase_y,
                          hold_radius=_ap.PICKAXE_HOLD_DISTANCE_PX)
        _ap.KeyState.hold("space", dist < _ap.PICKAXE_MINING_RANGE_PX)
    else:
        # Mining Beam — ranged, stand off and fire from afar.
        _ap._do_goto(state, p, chase_x, chase_y, stop_radius=200.0)
        _ap.KeyState.hold("space", dist < _ap.MINING_RANGE_PX)


def _do_attack_nearest(state: dict, p: dict) -> None:
    aliens = state.get("aliens", [])
    target, dist = _ap.nearest(aliens, p.get("x", 0), p.get("y", 0))
    if target is None:
        _ap._do_idle()
        return
    if dist < _ap.MELEE_RANGE_PX:
        _ap._ensure_weapon(state, "Melee")
    else:
        _ap._ensure_weapon(state, "Basic Laser")
    # Clamp chase target to the world rect (mirrors _act_engage and
    # the mine/gather actions) so an edge-adjacent alien doesn't
    # pull the bot into the boundary repulsion oscillation trap.
    # Combat assist's 60 FPS aim still hits through the boundary.
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _nav.clamp_to_world(
        target["x"], target["y"], zone)
    _ap._do_goto(state, p, chase_x, chase_y, stop_radius=300.0)
    _ap.KeyState.hold("space", dist < _ap.FIRE_RANGE_PX)


def _do_engage_boss(state: dict, p: dict) -> None:
    boss = state.get("boss")
    if boss is None:
        _ap._do_attack_nearest(state, p)
        return
    _ap._ensure_weapon(state, "Basic Laser")
    _ap._do_goto(state, p, boss["x"], boss["y"], stop_radius=400.0)
    _ap.KeyState.hold("space", True)


def _do_retreat(state: dict, p: dict) -> None:
    # Find a Home Station building, head toward it.
    buildings = state.get("buildings", [])
    home = None
    for b in buildings:
        if "Station" in (b.get("type") or "") or \
           "Station" in (b.get("name") or ""):
            home = b
            break
    if home is None:
        # No station — head to world centre as fallback.
        zone = state.get("zone", {})
        cx = zone.get("world_w", 6400) / 2
        cy = zone.get("world_h", 6400) / 2
        _ap._do_goto(state, p, cx, cy, stop_radius=200.0)
        return
    _ap._do_goto(state, p, home["x"], home["y"], stop_radius=150.0)
    _ap.KeyState.hold("space", False)


# ── Weapon cycling ────────────────────────────────────────────────────────


def _do_cycle_weapon(state: dict, target_name: str | None) -> None:
    if target_name is None:
        return
    _ap._ensure_weapon(state, target_name)


def _ensure_weapon(state: dict, want: str) -> None:
    """Press Tab as many times as needed to land on ``want``.  Has
    a per-call rate limit so we don't spam Tab faster than the
    game can register weapon cycles."""
    global _last_cycle_t
    cur = state.get("weapon", {}).get("name", "Basic Laser")
    if cur == want:
        return
    if (time.time() - _last_cycle_t) < 0.25:
        return
    try:
        cur_idx = _ap._WEAPON_ORDER.index(cur)
        want_idx = _ap._WEAPON_ORDER.index(want)
    except ValueError:
        return
    n = (want_idx - cur_idx) % len(_ap._WEAPON_ORDER)
    pyautogui.press("tab")
    _last_cycle_t = time.time()


def execute_intent(state: dict) -> None:
    """One tick of action.  Reads intent from state and dispatches
    keys.  Idempotent — leaves keys held only as long as the
    intent says they should be."""
    p = state.get("player", {})
    intent = state.get("intent", {"type": "idle"})
    menu = state.get("menu", {})

    # Don't fight a player who's in a menu.
    if any(menu.values()):
        _ap.KeyState.release_all()
        return

    itype = intent.get("type", "idle")
    if itype == "idle":
        _ap._do_idle()
    elif itype == "auto":
        _ap._do_auto(state, p)
    elif itype == "goto":
        _ap._do_goto(state, p, intent.get("x", p.get("x", 0)),
                 intent.get("y", p.get("y", 0)),
                 stop_radius=intent.get("radius", 80.0))
    elif itype == "mine_nearest":
        _ap._do_mine_nearest(state, p)
    elif itype == "attack_nearest":
        _ap._do_attack_nearest(state, p)
    elif itype == "engage_boss":
        _ap._do_engage_boss(state, p)
    elif itype == "retreat_to_station":
        _ap._do_retreat(state, p)
    elif itype == "cycle_weapon":
        _ap._do_cycle_weapon(state, intent.get("to"))
    else:
        # Unknown intent — log + idle until something we know arrives.
        print(f"[autopilot] unknown intent: {itype!r}")
        _ap._do_idle()
