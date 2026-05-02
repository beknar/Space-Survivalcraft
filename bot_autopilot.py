"""Local autopilot — translates high-level intents into keys.

Runs as its own process alongside the game.  Polls
``http://127.0.0.1:8765/state`` at ~10 Hz (cheap JSON, ~1 ms),
reads the current ``intent`` from the same response, and
dispatches keyboard commands to the game window via pyautogui.

Architecture:

    Claude (5-10 s cadence)  --POST /intent--> bot_api.py
                                                   |
    bot_autopilot.py (10 Hz) <-- GET /state-------'
                  |
                  +-- pyautogui keyDown/keyUp --> game window

The autopilot owns:
  * Reflex behaviours (brake on low shields, dodge on incoming
    projectile -- not yet implemented; placeholder hooks).
  * Mechanical execution of intents (rotate to heading, thrust
    while in range, fire weapon).
  * Weapon cycling so the right weapon is selected for the
    current intent (mining beam for mining, basic laser for
    aliens, energy blade if very close).

Claude / strategist owns:
  * What intent to set (mine vs fight vs build vs flee).
  * When to escalate (boss fight, retreat, station rebuild).

Hotkeys (pynput, global):
    Ctrl+Shift+P  pause / resume
    Ctrl+Shift+Q  stop the autopilot

Run:
    python bot_autopilot.py

The game must be running with ``COO_BOT_API=1`` set so the
state endpoint is reachable.
"""
from __future__ import annotations

import math
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen, Request

# UTF-8 stdout for unicode arrows / em-dashes in log messages.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import pyautogui
    from pynput import keyboard
except ImportError as e:
    print(f"ERROR: missing dependency: {e.name}.  Install with:")
    print("    pip install pyautogui pynput")
    sys.exit(1)

try:
    import pygetwindow as gw
except ImportError:
    gw = None


API_BASE = "http://127.0.0.1:8765"
POLL_HZ = 10.0
FIRE_RANGE_PX = 600.0             # within this -> hold fire
MINING_RANGE_PX = 400.0           # within this -> mining beam
# Energy Pickaxe is melee — its hit zone is centred on the head
# (~80 px from the handle pivot, with a hit radius of 80 px), so
# the bot must close to ~80 px from the asteroid to actually
# damage it.  Distinct stop / fire radii so the pickaxe path
# doesn't inherit the mining beam's 400 px stand-off.
PICKAXE_MINING_RANGE_PX  = 120.0  # within this -> press fire
# Hold the asteroid at this distance from the ship CENTER while
# pickaxe-mining.  Pivot is 80 px ahead of the ship and the head
# arcs at radius 80 around the pivot, so an asteroid centred 100
# px from the ship sits in the swing zone for nearly the entire
# 150° sweep without colliding (collision threshold is
# SHIP_RADIUS + ASTEROID_RADIUS ≈ 54 px).
PICKAXE_HOLD_DISTANCE_PX = 100.0
# Dead-band around the hold distance: the bot only thrusts forward
# when farther than HOLD + HALF_BAND, only reverses when closer
# than HOLD - HALF_BAND.  Prevents forward/back jitter at the
# boundary.
PICKAXE_HOLD_DEAD_BAND_PX = 20.0
# Per-MINE-entry chance the bot picks the Energy Pickaxe over the
# Mining Beam.  The choice is sticky for the entire mining session
# so the bot doesn't tab-flap mid-asteroid.
MINING_PICKAXE_CHANCE = 0.5
MELEE_RANGE_PX = 100.0            # within this -> energy blade


# ── Hotkeys ───────────────────────────────────────────────────────────────

class State:
    paused: bool = False
    stop: bool = False


def _hotkeys():
    def _toggle_pause():
        State.paused = not State.paused
        print(f"[autopilot] {'PAUSED' if State.paused else 'RESUMED'}")
    def _stop():
        State.stop = True
        print("[autopilot] STOP")
    with keyboard.GlobalHotKeys({
        "<ctrl>+<shift>+p": _toggle_pause,
        "<ctrl>+<shift>+q": _stop,
    }) as h:
        h.join()


# ── HTTP client ───────────────────────────────────────────────────────────

def fetch_state(timeout_s: float = 0.5) -> dict | None:
    try:
        with urlopen(f"{API_BASE}/state", timeout=timeout_s) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError):
        return None
    except Exception as e:
        print(f"[autopilot] fetch_state error: {e}")
        return None


# ── Key dispatch ──────────────────────────────────────────────────────────

class KeyState:
    """Track which keys are currently held down so toggling them
    is idempotent + we don't accidentally stack keyDowns."""
    held: set[str] = set()

    @classmethod
    def hold(cls, key: str, down: bool) -> None:
        if down and key not in cls.held:
            pyautogui.keyDown(key)
            cls.held.add(key)
        elif not down and key in cls.held:
            pyautogui.keyUp(key)
            cls.held.discard(key)

    @classmethod
    def release_all(cls) -> None:
        for key in list(cls.held):
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass
        cls.held.clear()


# ── Geometry ──────────────────────────────────────────────────────────────

def angle_to(dx: float, dy: float) -> float:
    """Heading (degrees, 0=N, CW positive) from origin to (dx, dy).
    Matches arcade's player.heading convention used by the game."""
    return math.degrees(math.atan2(dx, dy))


def heading_delta(current: float, target: float) -> float:
    """Shortest signed angle (current -> target) in [-180, 180]."""
    d = (target - current + 540.0) % 360.0 - 180.0
    return d


def nearest(lst: list[dict], px: float, py: float,
            max_dist: float = 1e9) -> tuple[dict | None, float]:
    """Return (entry, distance) of the nearest sprite in the list."""
    best: tuple[dict | None, float] = (None, max_dist)
    for sp in lst:
        dx = sp["x"] - px
        dy = sp["y"] - py
        d = math.hypot(dx, dy)
        if d < best[1]:
            best = (sp, d)
    return best


# ── Intent execution ──────────────────────────────────────────────────────

def execute_intent(state: dict) -> None:
    """One tick of action.  Reads intent from state and dispatches
    keys.  Idempotent — leaves keys held only as long as the
    intent says they should be."""
    p = state.get("player", {})
    intent = state.get("intent", {"type": "idle"})
    menu = state.get("menu", {})

    # Don't fight a player who's in a menu.
    if any(menu.values()):
        KeyState.release_all()
        return

    itype = intent.get("type", "idle")
    if itype == "idle":
        _do_idle()
    elif itype == "auto":
        _do_auto(state, p)
    elif itype == "goto":
        _do_goto(state, p, intent.get("x", p.get("x", 0)),
                 intent.get("y", p.get("y", 0)),
                 stop_radius=intent.get("radius", 80.0))
    elif itype == "mine_nearest":
        _do_mine_nearest(state, p)
    elif itype == "attack_nearest":
        _do_attack_nearest(state, p)
    elif itype == "engage_boss":
        _do_engage_boss(state, p)
    elif itype == "retreat_to_station":
        _do_retreat(state, p)
    elif itype == "cycle_weapon":
        _do_cycle_weapon(state, intent.get("to"))
    else:
        # Unknown intent — log + idle until something we know arrives.
        print(f"[autopilot] unknown intent: {itype!r}")
        _do_idle()


def _do_idle() -> None:
    KeyState.release_all()


# ── Auto-mode finite state machine ────────────────────────────────────────
#
#  Five states with asymmetric enter/exit thresholds.  REGEN and
#  ENGAGE are defensive interrupts -- they bypass MIN_DWELL_S and
#  preempt other states immediately.  REGEN sits at the top so the
#  bot pauses to recover shields rather than chasing a fight at low
#  health; ENGAGE preempts everything else.  The other three states
#  respect MIN_DWELL_S to prevent boundary thrash.
#
#       ┌─────────┐  shields < 40 %             ┌────────┐
#       │  REGEN  │ <─────────────────────────── │ ANY *  │
#       │  idle   │ ───────────────────────────> │        │
#       └─────────┘  shields >= 60 %             └────────┘
#                                                    │
#       ┌─────────┐  alien<800 (any non-REGEN)       │
#       │ ENGAGE  │ <────────────────────────────────┤
#       │ aim+fire│ ────────────────────────────>    │
#       └─────────┘  no alien<1000                   │
#                                                    │
#       ┌─────────┐  pickup<1500 + safe              │
#       │ GATHER  │ <────────────────────────────────┤
#       │  fly to │ ────────────────────────────>    │
#       │  pickup │  pickup>1700 / consumed          │
#       └─────────┘                                  │
#                                                    │
#       ┌─────────┐  asteroids known                 │
#       │  MINE   │ <────────────────────────────────┤
#       │ nearest │ ────────────────────────────>    │
#       │ rock    │  no asteroids visible            │
#       └─────────┘                                  │
#                                                    │
#       ┌─────────┐  no asteroids known              │
#       │ SEARCH  │ <────────────────────────────────┘
#       │ spiral  │
#       └─────────┘
#
#  The hysteresis bands replace three previous sources of flicker:
#    * mine ↔ engage at the 800 px ring
#    * idle ↔ mine at the 50 % shield threshold
#    * spiral state torn down + re-anchored every time a non-spiral
#      state briefly stole a tick
#
#  Combat assist (bot_combat_assist.py) still owns aim + fire while
#  in ENGAGE.  This module owns thrust + weapon selection.

# ── Hysteresis thresholds ─────────────────────────────────────────────────

ENGAGE_ENTER_PX: float = 800.0
ENGAGE_EXIT_PX:  float = 1000.0
GATHER_ENTER_PX: float = 1500.0
GATHER_EXIT_PX:  float = 1700.0
REGEN_ENTER_PCT: float = 0.40
REGEN_EXIT_PCT:  float = 0.60
MELEE_ENTER_PX:  float = 100.0
MELEE_EXIT_PX:   float = 130.0
PICKUP_STOP_RADIUS: float = 60.0
MIN_DWELL_S:     float = 0.6      # how long a non-ENGAGE state must hold

# Stop radius when the in-game combat assist has committed to a
# melee engagement (via its 50 % per-engagement dice roll).  The
# autopilot reads ``state.assist.melee_engaged`` and closes to
# this radius so the swing arc actually reaches the target.
MELEE_STOP_RADIUS_PX: float = 50.0


# ── State constants ───────────────────────────────────────────────────────

S_ENGAGE     = "engage"
S_GATHER     = "gather"
S_REGEN      = "regen"
S_MINE       = "mine"
S_SEARCH     = "search"
S_BUILD      = "build"
S_BUILD_SEEK = "build_seek"

ALL_STATES = (
    S_ENGAGE, S_GATHER, S_REGEN, S_MINE, S_SEARCH, S_BUILD, S_BUILD_SEEK,
)

# Starter-base build gate.  When the bot has accumulated this much
# iron AND there are no asteroids / aliens within the clear-area
# radius, it transitions into S_BUILD once and POSTs the build
# trigger.  ``_state.build_done`` flips True after the first
# attempt so the bot doesn't keep re-rolling the build
# (intentionally simple one-shot — a destroyed station won't
# auto-rebuild).
BUILD_IRON_THRESHOLD = 1000
# Single radius for "clear and quiet" — no asteroids, aliens,
# pickups, or buildings within this distance of the player.
# Approximately matches the visible game screen so the player's
# inability to see threats from off-screen doesn't trigger the
# build prematurely.
BUILD_CLEAR_RADIUS_PX = 800.0
# Distance the bot walks per tick when seeking a clear spot.
BUILD_SEEK_TARGET_DIST_PX = 1000.0


# ── Edge-collision (stuck) detection — tuning constants ──────────────────
# When the ship is held against a world edge by goto/spiral targeting an
# off-map point, the bot would keep thrusting "w" without moving.  We
# sample position over a short rolling window; if displacement is tiny
# despite the action loop firing, we declare "stuck" and override
# movement with a heading toward the world centre for a short escape
# burst, then let the FSM resume.
STUCK_DETECT_WINDOW_S    = 1.5    # window over which displacement is measured
STUCK_DETECT_DIST_PX     = 25.0   # < this much movement in window -> stuck
STUCK_ESCAPE_MIN_DURATION_S = 1.5 # minimum time the escape override lasts
# Escape stays active until the ship is at least this far from any
# world edge — keeps the override running through long rotations
# (e.g. 180° turn from the top edge to face south) so the override
# doesn't expire mid-rotation and immediately re-trigger.
STUCK_ESCAPE_CLEAR_MARGIN_PX = 500.0
STUCK_WORLD_MARGIN_PX    = 200.0  # spiral / escape targets stay this far in
# Throttle the "STUCK at edge" log — bumped to 30 s to match the
# centre-lockout window so a single cycle's worth of messages
# doesn't fire more than once.
STUCK_LOG_THROTTLE_S     = 30.0
# After a stuck-escape, the FSM is locked into SEARCH (around the
# world centre) for this long so MINE / GATHER / BUILD_SEEK can't
# immediately re-target the same edge-adjacent object that pulled
# the bot into the wall in the first place.  ENGAGE + REGEN still
# preempt as defensive interrupts.  Without this lockout the bot
# would cycle between the edge and STUCK_ESCAPE_CLEAR_MARGIN_PX
# from it indefinitely (observed on 2026-05-01 with a top-edge
# alien / asteroid that kept attracting the FSM).
STUCK_CENTRE_LOCKOUT_S   = 30.0


# ── BotState — all persistent runtime state in one place ─────────────────
#
# Bundles the FSM dict, spiral search state, edge-stuck watchdog state,
# the sticky mining-weapon pick, and the one-shot starter-base flag.
# Replaces five separate module-level globals — adding a new piece of
# bot state now means adding a field here and including it in
# ``reset()``, no scattered ``global`` declarations.  The reset()
# method clears+repopulates the dict fields IN PLACE so module-level
# aliases (``_fsm``, ``_spiral_state``, ``_stuck_state``) stay valid
# across resets — preserves backward-compat with the ~70 test
# references that read those dicts directly.

@dataclass
class BotState:
    fsm: dict = field(default_factory=lambda: {
        "state": S_MINE,
        "entered_at": None,
    })
    spiral: dict = field(default_factory=lambda: {
        "anchor": None,
        "angle": 0.0,
        "radius": 100.0,
    })
    stuck: dict = field(default_factory=lambda: {
        "history": [],
        "escape_until": 0.0,
        "last_log": 0.0,
        # Monotonic timestamp until which target-chasing FSM
        # branches (MINE / GATHER / BUILD_SEEK) are suppressed in
        # favour of a centred SEARCH spiral.  Set on stuck-trigger
        # to break the "edge → escape → re-target same edge object
        # → stuck again" cycle.  ENGAGE + REGEN still preempt.
        "centre_lockout_until": 0.0,
    })
    mining_weapon_pick: str = "Mining Beam"
    build_done: bool = False

    def reset(self) -> None:
        """Restore every field to its default.  Mutates dict fields
        in place so external aliases stay live."""
        fresh = BotState()
        for d, src in (
            (self.fsm, fresh.fsm),
            (self.spiral, fresh.spiral),
            (self.stuck, fresh.stuck),
        ):
            d.clear()
            d.update(src)
        self.mining_weapon_pick = fresh.mining_weapon_pick
        self.build_done = fresh.build_done


_state = BotState()

# Backwards-compat module-level aliases.  These point at the SAME
# dict objects as ``_state.fsm`` / ``_state.spiral`` / ``_state.stuck``,
# so writes through either name are visible to both.  Many tests +
# call sites read ``_fsm["state"]`` etc; this keeps them working
# without churn while new code can use ``_state`` directly.
_fsm = _state.fsm
_spiral_state = _state.spiral
_stuck_state = _state.stuck

# Indirection so tests can monkey-patch a fake clock.
_get_now = time.monotonic


def _spiral_reset() -> None:
    s = _state.spiral
    s["anchor"] = None
    s["angle"] = 0.0
    s["radius"] = 100.0


def _stuck_reset() -> None:
    s = _state.stuck
    s["history"] = []
    s["escape_until"] = 0.0
    s["last_log"] = 0.0
    s["centre_lockout_until"] = 0.0


def _fsm_reset(initial: str = S_MINE) -> None:
    """Reset every piece of bot runtime state to its default.
    Tests must call this in their setup/fixture so cross-test
    state doesn't leak.  The dict aliases (_fsm / _spiral_state /
    _stuck_state) stay valid because BotState.reset() mutates in
    place."""
    _state.reset()
    _state.fsm["state"] = initial


def _nearest_pickup(state: dict, px: float, py: float
                    ) -> tuple[dict | None, float]:
    """Return the nearest iron + blueprint pickup combined.
    Blueprints are slightly preferred (worth more than 10 iron)
    so they get pulled in first when a tie."""
    iron = state.get("iron_pickups", []) or []
    bps = state.get("blueprint_pickups", []) or []
    candidates = list(bps) + list(iron)   # blueprints first
    return nearest(candidates, px, py)


def _record_position(p: dict) -> None:
    """Append the player's current position to the rolling stuck-
    detect history and evict samples older than the detect window."""
    now = _get_now()
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    h = _stuck_state["history"]
    h.append((now, px, py))
    cutoff = now - STUCK_DETECT_WINDOW_S
    # Drop stale samples (cheap — list is at most ~15 entries at 10 Hz).
    while h and h[0][0] < cutoff:
        h.pop(0)


def _detect_stuck() -> bool:
    """True when the ship has barely moved over the last
    STUCK_DETECT_WINDOW_S.  Conservative: requires the history to
    have spanned at least 80% of the window so we don't false-fire
    in the first second after process start."""
    h = _stuck_state["history"]
    if len(h) < 5:
        return False
    span = h[-1][0] - h[0][0]
    if span < STUCK_DETECT_WINDOW_S * 0.8:
        return False
    moved = math.hypot(h[-1][1] - h[0][1], h[-1][2] - h[0][2])
    return moved < STUCK_DETECT_DIST_PX


def _do_escape_edge(state: dict, p: dict) -> None:
    """Override movement: rotate toward the world centre and thrust
    forward to break out of an edge collision.  Used when
    ``_detect_stuck`` flags the ship as pinned at a map edge."""
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    cx = world_w * 0.5
    cy = world_h * 0.5
    # stop_radius is generous so the escape ends as soon as we're
    # clearly off the edge, not when we reach the exact centre.
    _do_goto(state, p, cx, cy, stop_radius=300.0)


def _ship_clear_of_edges(p: dict, zone: dict) -> bool:
    """True when the ship is at least
    STUCK_ESCAPE_CLEAR_MARGIN_PX from every world edge.  Used as
    the exit condition for the escape override so the bot doesn't
    drop back into the FSM while still pinned."""
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    world_w = float(zone.get("world_w", 0) or 0)
    world_h = float(zone.get("world_h", 0) or 0)
    if world_w <= 0 or world_h <= 0:
        # Don't gate on bounds we don't have — fall back to time only.
        return True
    return (
        px > STUCK_ESCAPE_CLEAR_MARGIN_PX
        and py > STUCK_ESCAPE_CLEAR_MARGIN_PX
        and px < world_w - STUCK_ESCAPE_CLEAR_MARGIN_PX
        and py < world_h - STUCK_ESCAPE_CLEAR_MARGIN_PX
    )


def _iron_total(state: dict) -> int:
    """Iron count from the player inventory snapshot in /state.
    The state.inventory.items dict is keyed by item name."""
    items = (state.get("inventory") or {}).get("items") or {}
    return int(items.get("iron", 0))


def _build_area_clear(state: dict, px: float, py: float) -> bool:
    """True when nothing detectable is within
    ``BUILD_CLEAR_RADIUS_PX`` of the player — checked across
    asteroids, aliens, pickups, and existing buildings.  Used as
    the pre-condition for entering S_BUILD."""
    r_sq = BUILD_CLEAR_RADIUS_PX * BUILD_CLEAR_RADIUS_PX
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
    scan_r_sq = (BUILD_CLEAR_RADIUS_PX * 2.0) ** 2
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


def _act_build_seek(state: dict, p: dict) -> None:
    """BUILD_SEEK: walk in the direction of least detectable
    density, looking for a clear pocket to build the starter
    base.  Heads BUILD_SEEK_TARGET_DIST_PX in the away-from-
    centroid direction (clamped to the world), then the FSM
    re-evaluates each tick and either flips to S_BUILD when the
    area becomes clear or keeps seeking."""
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    ux, uy = _build_seek_direction(state, px, py)
    tx = px + ux * BUILD_SEEK_TARGET_DIST_PX
    ty = py + uy * BUILD_SEEK_TARGET_DIST_PX
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    tx = max(STUCK_WORLD_MARGIN_PX,
             min(world_w - STUCK_WORLD_MARGIN_PX, tx))
    ty = max(STUCK_WORLD_MARGIN_PX,
             min(world_h - STUCK_WORLD_MARGIN_PX, ty))
    # Don't fire any weapon while seeking — the goal is to find
    # an empty pocket, not to mine on the way.
    KeyState.hold("space", False)
    _do_goto(state, p, tx, ty, stop_radius=200.0)


def _choose_next_state(state: dict, p: dict, cur: str) -> str:
    """Pure function: given the world snapshot and the current FSM
    state, return what state the bot *wants* to be in this tick.

    Hysteresis is encoded by branching on ``cur``: the enter
    threshold and exit threshold differ, so a value drifting around
    the boundary doesn't oscillate.

    REGEN is the **top priority** -- when shields drop below 40 %
    the bot disengages, sits still, and waits for shields to climb
    back to 60 % before doing anything else.  Combat assist still
    aims + fires automatically every frame, so the bot isn't
    defenseless while regenerating; it just doesn't burn thrust
    chasing targets while the shield bar is low.
    """
    px, py = p.get("x", 0.0), p.get("y", 0.0)

    # 1. REGEN — shields hurt; sit still and recover.  Preempts
    #    ENGAGE/GATHER/MINE so the bot actually idles instead of
    #    burning thrust while shields are low.
    sh = int(p.get("shields", 0))
    sh_max = max(1, int(p.get("max_shields", 1)))
    pct = sh / sh_max
    if cur == S_REGEN:
        if pct < REGEN_EXIT_PCT:
            return S_REGEN
    else:
        if pct < REGEN_ENTER_PCT:
            return S_REGEN

    # 2. ENGAGE — alien within band.  Preempts the rest.
    aliens = state.get("aliens") or []
    threat, td = nearest(aliens, px, py)
    if cur == S_ENGAGE:
        if threat is not None and td < ENGAGE_EXIT_PX:
            return S_ENGAGE
    else:
        if threat is not None and td < ENGAGE_ENTER_PX:
            return S_ENGAGE

    # 2.5  Centre-lockout.  After a stuck-escape, the spiral has
    #      been re-anchored to the world centre and the FSM is
    #      forced into SEARCH for STUCK_CENTRE_LOCKOUT_S so
    #      MINE / GATHER / BUILD / BUILD_SEEK can't immediately
    #      pull the bot back to whatever edge-adjacent target
    #      caused the stuck cycle in the first place.  ENGAGE
    #      already returned above; REGEN already returned earlier.
    now = _get_now()
    if now < _state.stuck.get("centre_lockout_until", 0.0):
        return S_SEARCH

    # 3. GATHER — loot pickup within reach.
    pickup, pd = _nearest_pickup(state, px, py)
    if cur == S_GATHER:
        if pickup is not None and pd < GATHER_EXIT_PX:
            return S_GATHER
    else:
        if pickup is not None and pd < GATHER_ENTER_PX:
            return S_GATHER

    # 4. BUILD — one-shot starter base when iron + clear area
    #    conditions are met.  Falls below ENGAGE / REGEN so the
    #    bot doesn't try to build during combat or while shields
    #    are low.  Falls above MINE / SEARCH so the bot stops
    #    accumulating iron the moment it has enough and a clear
    #    spot.  ``_state.build_done`` flips True after the first attempt.
    #    BUILD_SEEK actively walks toward less-cluttered space when
    #    iron is met but the area isn't clear.
    if (not _state.build_done
            and _iron_total(state) >= BUILD_IRON_THRESHOLD):
        if _build_area_clear(state, px, py):
            return S_BUILD
        return S_BUILD_SEEK

    # 5. MINE vs SEARCH — discrete event, no hysteresis needed.
    asteroids = state.get("asteroids") or []
    if asteroids:
        return S_MINE
    return S_SEARCH


def _on_enter(new_state: str) -> None:
    """Per-state entry hook.  Currently only SEARCH cares -- its
    spiral anchor must be cleared so each fresh search starts
    from the bot's current position, not a stale prior anchor.

    The melee-commit dice roll on ENGAGE entry happens in the
    in-process combat assist (see ``bot_combat_assist.tick``),
    not here, because combat assist is the authoritative owner
    of weapon selection -- the autopilot's 10 Hz tick + 0.25 s
    Tab rate-limit can't beat the per-frame ranged-vs-melee
    auto-switch unless the assist itself stays out of its way.
    The autopilot reads the result via ``state.assist.melee_engaged``
    in ``_act_engage`` to choose the right movement stop radius.
    """
    if new_state == S_SEARCH:
        _spiral_reset()
    elif new_state == S_MINE:
        # 50/50 dice roll: Mining Beam vs Energy Pickaxe.  Sticky
        # for the entire mining session so the bot doesn't tab-flap
        # mid-asteroid.  Re-rolled on each fresh entry into MINE.
        if random.random() < MINING_PICKAXE_CHANCE:
            _state.mining_weapon_pick = "Energy Pickaxe"
        else:
            _state.mining_weapon_pick = "Mining Beam"


def _do_auto(state: dict, p: dict) -> None:
    """Step the FSM one tick, then dispatch the action for the
    current state.  ENGAGE preempts dwell; everything else waits
    out ``MIN_DWELL_S`` before transitioning.

    The first tick after ``_fsm_reset()`` (entered_at sentinel
    None) always stamps the timer and is allowed to transition
    freely -- otherwise a fresh process couldn't react to its
    initial observation."""
    now = _get_now()

    # Edge-collision watchdog: if the ship has been pinned against
    # the world boundary by goto/spiral targeting an off-map point,
    # override the FSM and head toward the world centre.  Has to
    # run BEFORE the FSM dispatch so it preempts whatever was
    # driving the ship into the edge.
    _record_position(p)
    zone = state.get("zone") or {}
    if _stuck_state["escape_until"] > 0.0:
        # Escape is active.  Stay in escape until BOTH:
        #  * the minimum duration has elapsed, AND
        #  * the ship is clear of all world edges by the safety
        #    margin (so a long 180° rotation doesn't drop us out
        #    of escape mid-pivot, immediately re-pinning).
        # Continuously clear position history while in escape so
        # the next detect cycle starts fresh after we exit.
        _stuck_state["history"] = []
        if (now < _stuck_state["escape_until"]
                or not _ship_clear_of_edges(p, zone)):
            _do_escape_edge(state, p)
            return
        # Exit condition met — clear the override and fall through.
        _stuck_state["escape_until"] = 0.0
    if _detect_stuck():
        _stuck_state["escape_until"] = now + STUCK_ESCAPE_MIN_DURATION_S
        # Re-anchor the spiral to the WORLD CENTRE (not just reset
        # to None which would re-anchor at the current edge
        # position).  When the FSM eventually re-enters SEARCH
        # post-escape, the spiral will expand from the centre
        # rather than from the edge — no more immediate re-pin.
        world_w = float(zone.get("world_w", 6400) or 6400)
        world_h = float(zone.get("world_h", 6400) or 6400)
        _spiral_state["anchor"] = (world_w * 0.5, world_h * 0.5)
        _spiral_state["angle"] = 0.0
        _spiral_state["radius"] = 100.0
        _stuck_state["history"] = []
        # Centre-lockout: suppress MINE / GATHER / BUILD branches
        # for the next STUCK_CENTRE_LOCKOUT_S so the FSM can't
        # immediately retarget the same edge object.  ENGAGE +
        # REGEN still preempt for safety.
        _stuck_state["centre_lockout_until"] = (
            now + STUCK_CENTRE_LOCKOUT_S)
        # Throttle the log so a long lockout doesn't spam.
        if (now - _stuck_state["last_log"]) >= STUCK_LOG_THROTTLE_S:
            print("[autopilot] STUCK at edge — escape burst toward "
                  "world centre + re-anchoring spiral + "
                  f"{int(STUCK_CENTRE_LOCKOUT_S)}s centre lockout")
            _stuck_state["last_log"] = now
        _do_escape_edge(state, p)
        return

    cur = _fsm["state"]
    desired = _choose_next_state(state, p, cur)

    if _fsm["entered_at"] is None:
        # First tick: stamp the timer, allow immediate transition.
        # Always fire the entry hook so initial-state side effects
        # (spiral reset for SEARCH, mining-weapon dice for MINE)
        # run even when the desired state matches the seeded
        # default — otherwise a fresh process that begins in MINE
        # would never roll the per-session dice.
        _fsm["entered_at"] = now
        if desired != cur:
            _fsm["state"] = desired
            cur = desired
        _on_enter(cur)
    elif desired != cur:
        dwell = now - _fsm["entered_at"]
        # ENGAGE and REGEN are defensive interrupts -- they bypass
        # MIN_DWELL so the bot reacts to a sudden threat or a sudden
        # shield collapse without waiting for the dwell timer.
        if desired in (S_ENGAGE, S_REGEN) or dwell >= MIN_DWELL_S:
            _fsm["state"] = desired
            _fsm["entered_at"] = now
            cur = desired
            _on_enter(cur)

    if cur == S_ENGAGE:
        _act_engage(state, p)
    elif cur == S_GATHER:
        _act_gather(state, p)
    elif cur == S_REGEN:
        _do_idle()
    elif cur == S_MINE:
        _do_mine_nearest(state, p)
    elif cur == S_BUILD:
        _act_build(state, p)
    elif cur == S_BUILD_SEEK:
        _act_build_seek(state, p)
    else:  # S_SEARCH
        _do_spiral_search(state, p)


def _post_build_starter_base(timeout_s: float = 5.0) -> dict | None:
    """POST /build_starter_base on the in-game HTTP API.  Returns
    the parsed JSON response, or ``None`` on transport failure.
    The endpoint is synchronous — the entire build sequence runs
    in the HTTP-handler thread before the response is sent."""
    try:
        req = Request(
            f"{API_BASE}/build_starter_base",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] build POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] build POST unexpected error: {e}")
        return None


def _act_build(state: dict, p: dict) -> None:
    """BUILD: fire the one-shot starter-base trigger and flip
    ``_state.build_done`` so the FSM falls through to MINE /
    SEARCH on subsequent ticks.  Releases all movement keys for
    the duration of the call so the ship coasts in place while
    the seven buildings are placed in-process.

    Guarded by an early ``build_done`` check: while the FSM is
    holding S_BUILD through MIN_DWELL_S, the dispatch can call
    this multiple times — but only the FIRST call should actually
    POST the build.  Without the guard, a 0.6 s dwell at 10 Hz
    plus the synchronous HTTP POST round-trip produced 6 build
    attempts in one play-test, each one re-spending iron on
    duplicate buildings."""
    if _state.build_done:
        # Already POSTed once this session.  Coast until the FSM
        # transitions out of S_BUILD on the next tick.
        _do_idle()
        return
    KeyState.release_all()
    _do_idle()
    print("[autopilot] BUILD: requesting starter base "
          f"(iron={_iron_total(state)})")
    # Mark done BEFORE the POST so a re-entry mid-POST (if it
    # ever happens) early-returns above.  The HTTP request is
    # synchronous so we'll typically only re-enter post-completion.
    _state.build_done = True
    result = _post_build_starter_base()
    if result is None:
        print("[autopilot] BUILD: POST failed; flagging done so the "
              "FSM resumes normal flow")
        return
    placed = result.get("placed", [])
    failed = result.get("failed", [])
    print(f"[autopilot] BUILD: placed {len(placed)} "
          f"({[p['type'] for p in placed]})  "
          f"failed {len(failed)}")
    if failed:
        for f in failed:
            print(f"  - {f}")


def _act_engage(state: dict, p: dict) -> None:
    """ENGAGE: close on the nearest threat + hold fire.  Combat
    assist (bot_combat_assist.py) owns aim + fire override; this
    function chooses movement stop radius based on whether the
    assist has committed to a melee rush.

    The assist exposes ``state.assist.melee_engaged`` -- True when
    its per-engagement 50 % dice roll landed on melee.  In that
    case the autopilot drives forward to ``MELEE_STOP_RADIUS_PX``
    so the swing arc reaches the target and lets the assist's
    weapon lock keep the lightsabre selected.  Otherwise it
    stands off at ~380 px and uses the laser/melee sub-band
    hysteresis here.
    """
    aliens = state.get("aliens") or []
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    threat, td = nearest(aliens, px, py)
    if threat is None:
        # FSM said engage but the alien vanished mid-tick.  Bail
        # to a safe no-op; next tick will re-route us out.
        KeyState.hold("space", False)
        return

    melee_committed = bool(
        (state.get("assist") or {}).get("melee_engaged", False))
    if melee_committed:
        # Committed melee rush: drive in to swing range.  Don't
        # call _ensure_weapon -- the in-process combat assist has
        # locked the Energy Blade and would just fight us at
        # 60 FPS vs our 10 Hz Tab presses.
        _do_goto(state, p, threat["x"], threat["y"],
                 stop_radius=MELEE_STOP_RADIUS_PX)
        KeyState.hold("space", True)
        return

    # Ranged engagement (default): laser/melee sub-band hysteresis.
    cur_weapon = state.get("weapon", {}).get("name", "Basic Laser")
    if cur_weapon == "Melee":
        # In Melee already: only swap back to Laser once we're past
        # the exit band (130 px).
        if td > MELEE_EXIT_PX:
            _ensure_weapon(state, "Basic Laser")
    else:
        # In a ranged weapon: only swap to Melee once we're firmly
        # inside the enter band (100 px).
        if td < MELEE_ENTER_PX:
            _ensure_weapon(state, "Melee")
        else:
            _ensure_weapon(state, "Basic Laser")
    _do_goto(state, p, threat["x"], threat["y"], stop_radius=380.0)
    KeyState.hold("space", td < FIRE_RANGE_PX)


def _act_gather(state: dict, p: dict) -> None:
    """GATHER: head toward the nearest pickup, no fire."""
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    pickup, _pd = _nearest_pickup(state, px, py)
    if pickup is None:
        # Pickup vanished (probably collected); next tick re-routes.
        KeyState.hold("space", False)
        return
    KeyState.hold("space", False)
    _do_goto(state, p, pickup["x"], pickup["y"],
             stop_radius=PICKUP_STOP_RADIUS)


def _do_spiral_search(state: dict, p: dict) -> None:
    """Drive the ship in an outward spiral around the position
    where the spiral started, sweeping the field for any asteroid
    that became reachable.  Re-anchors if the spiral has run for
    too long without finding anything."""
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    if _spiral_state["anchor"] is None:
        _spiral_state["anchor"] = (px, py)
        _spiral_state["angle"] = 0.0
        _spiral_state["radius"] = 100.0
    ax, ay = _spiral_state["anchor"]
    r = _spiral_state["radius"]
    a = _spiral_state["angle"]
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
        tx = max(STUCK_WORLD_MARGIN_PX,
                 min(world_w - STUCK_WORLD_MARGIN_PX, tx))
    if world_h > 0:
        ty = max(STUCK_WORLD_MARGIN_PX,
                 min(world_h - STUCK_WORLD_MARGIN_PX, ty))
    # Same sticky weapon as the active mining session — search
    # phase is just positioning, but staying on the picked weapon
    # avoids a Tab the moment we find a target.
    _ensure_weapon(state, _state.mining_weapon_pick)
    _do_goto(state, p, tx, ty, stop_radius=120.0)
    # Only fire when an asteroid is actually in mining range.
    # Used to fire continuously as a "drift past extraction lag"
    # safety net, but that ended up making the bot mine empty
    # space at the centre of the world after a stuck-escape with
    # no real targets nearby.
    asteroids = state.get("asteroids") or []
    nearest_ast, nd = nearest(asteroids, px, py)
    if _state.mining_weapon_pick == "Energy Pickaxe":
        in_range = (
            nearest_ast is not None and nd < PICKAXE_MINING_RANGE_PX)
    else:
        in_range = (
            nearest_ast is not None and nd < MINING_RANGE_PX)
    KeyState.hold("space", in_range)
    # Advance the spiral incrementally each tick.
    _spiral_state["angle"] = (a + math.radians(8.0)) % (2 * math.pi)
    _spiral_state["radius"] = min(r + 1.5, 3000.0)
    if _spiral_state["radius"] >= 3000.0:
        _spiral_reset()


def _do_goto(state: dict, p: dict, tx: float, ty: float,
             stop_radius: float = 80.0) -> None:
    """Rotate toward (tx, ty) and thrust until within ``stop_radius``."""
    dx = tx - p.get("x", 0)
    dy = ty - p.get("y", 0)
    dist = math.hypot(dx, dy)
    if dist < stop_radius:
        # Arrived — release thrust + rotation, drift in place.
        KeyState.hold("w", False)
        KeyState.hold("a", False)
        KeyState.hold("d", False)
        KeyState.hold("s", True)         # gentle brake
        return
    KeyState.hold("s", False)
    target = angle_to(dx, dy)
    delta = heading_delta(p.get("heading", 0.0), target)
    if delta < -5.0:
        KeyState.hold("a", True);  KeyState.hold("d", False)
    elif delta > 5.0:
        KeyState.hold("a", False); KeyState.hold("d", True)
    else:
        KeyState.hold("a", False); KeyState.hold("d", False)
    # Only thrust forward when roughly aligned (within 45° of target).
    KeyState.hold("w", abs(delta) < 45.0)


def _do_hold_distance(state: dict, p: dict, tx: float, ty: float,
                      hold_radius: float,
                      dead_band: float = PICKAXE_HOLD_DEAD_BAND_PX
                      ) -> None:
    """Maintain ``hold_radius`` distance from (tx, ty) while always
    facing it.  Used for melee mining with the energy pickaxe — the
    bot needs to keep the asteroid in the swing arc without ramming
    it.  Thrust forward when too far, reverse when too close, coast
    inside the dead-band to avoid jitter."""
    dx = tx - p.get("x", 0)
    dy = ty - p.get("y", 0)
    dist = math.hypot(dx, dy)
    # Always rotate to face the target so the swing arc covers it.
    target = angle_to(dx, dy)
    delta = heading_delta(p.get("heading", 0.0), target)
    if delta < -5.0:
        KeyState.hold("a", True);  KeyState.hold("d", False)
    elif delta > 5.0:
        KeyState.hold("a", False); KeyState.hold("d", True)
    else:
        KeyState.hold("a", False); KeyState.hold("d", False)
    # Distance control with hysteresis around hold_radius.
    if dist > hold_radius + dead_band:
        # Too far — thrust forward (only when roughly aligned).
        KeyState.hold("w", abs(delta) < 45.0)
        KeyState.hold("s", False)
    elif dist < hold_radius - dead_band:
        # Too close — reverse-thrust to back off.  ``s`` is
        # ``thrust_bwd`` in the player controls (not just brake),
        # so this actively pushes the ship away.
        KeyState.hold("w", False)
        KeyState.hold("s", True)
    else:
        # In the dead-band — coast in place.
        KeyState.hold("w", False)
        KeyState.hold("s", False)


def _do_mine_nearest(state: dict, p: dict) -> None:
    asteroids = state.get("asteroids", [])
    target, dist = nearest(asteroids, p.get("x", 0), p.get("y", 0))
    if target is None:
        _do_idle()
        return
    _ensure_weapon(state, _state.mining_weapon_pick)
    if _state.mining_weapon_pick == "Energy Pickaxe":
        # Pickaxe is melee — hold optimal swing distance instead
        # of closing all the way and ramming the asteroid.  After
        # the asteroid is destroyed the FSM transitions to GATHER,
        # which uses _do_goto to close on the iron pickup.
        _do_hold_distance(state, p, target["x"], target["y"],
                          hold_radius=PICKAXE_HOLD_DISTANCE_PX)
        KeyState.hold("space", dist < PICKAXE_MINING_RANGE_PX)
    else:
        # Mining Beam — ranged, stand off and fire from afar.
        _do_goto(state, p, target["x"], target["y"], stop_radius=200.0)
        KeyState.hold("space", dist < MINING_RANGE_PX)


def _do_attack_nearest(state: dict, p: dict) -> None:
    aliens = state.get("aliens", [])
    target, dist = nearest(aliens, p.get("x", 0), p.get("y", 0))
    if target is None:
        _do_idle()
        return
    if dist < MELEE_RANGE_PX:
        _ensure_weapon(state, "Melee")
    else:
        _ensure_weapon(state, "Basic Laser")
    _do_goto(state, p, target["x"], target["y"], stop_radius=300.0)
    KeyState.hold("space", dist < FIRE_RANGE_PX)


def _do_engage_boss(state: dict, p: dict) -> None:
    boss = state.get("boss")
    if boss is None:
        _do_attack_nearest(state, p)
        return
    _ensure_weapon(state, "Basic Laser")
    _do_goto(state, p, boss["x"], boss["y"], stop_radius=400.0)
    KeyState.hold("space", True)


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
        _do_goto(state, p, cx, cy, stop_radius=200.0)
        return
    _do_goto(state, p, home["x"], home["y"], stop_radius=150.0)
    KeyState.hold("space", False)


# ── Weapon cycling ────────────────────────────────────────────────────────

_WEAPON_ORDER = (
    "Basic Laser", "Mining Beam", "Melee", "Energy Pickaxe")
_last_cycle_t: float = 0.0


def _do_cycle_weapon(state: dict, target_name: str | None) -> None:
    if target_name is None:
        return
    _ensure_weapon(state, target_name)


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
        cur_idx = _WEAPON_ORDER.index(cur)
        want_idx = _WEAPON_ORDER.index(want)
    except ValueError:
        return
    n = (want_idx - cur_idx) % len(_WEAPON_ORDER)
    pyautogui.press("tab")
    _last_cycle_t = time.time()


# ── Main loop ─────────────────────────────────────────────────────────────

def _ensure_game_focused() -> None:
    """Activate the game window so pyautogui keystrokes reach
    it.  No-op on non-Windows or if pygetwindow isn't installed.
    Called periodically from main()."""
    if gw is None:
        return
    try:
        for w in gw.getAllWindows():
            if "Call of Orion" in (w.title or ""):
                # Skip if already active to avoid focus thrash.
                try:
                    if hasattr(w, "isActive") and w.isActive:
                        return
                except Exception:
                    pass
                try:
                    w.activate()
                except Exception:
                    pass
                return
    except Exception:
        pass


def main() -> None:
    print("=" * 60)
    print("Call of Orion -- autopilot")
    print(f"API: {API_BASE}/state  |  Poll: {POLL_HZ:.0f} Hz")
    print("Hotkeys: Ctrl+Shift+P pause | Ctrl+Shift+Q quit")
    print("=" * 60)
    threading.Thread(target=_hotkeys, daemon=True).start()
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0
    period = 1.0 / POLL_HZ
    last_warn = 0.0
    last_focus = 0.0
    # Activate the game once at startup so the very first
    # keystroke lands in the game window.
    _ensure_game_focused()
    while not State.stop:
        if State.paused:
            KeyState.release_all()
            time.sleep(0.1)
            continue
        t0 = time.time()
        # Re-activate the game window every ~2 s so keystrokes
        # keep reaching it even if the user clicks elsewhere.
        if t0 - last_focus > 2.0:
            _ensure_game_focused()
            last_focus = t0
        state = fetch_state()
        if state is None:
            if time.time() - last_warn > 5.0:
                print("[autopilot] no /state response -- is the "
                      "game running with COO_BOT_API=1?")
                last_warn = time.time()
            KeyState.release_all()
            time.sleep(1.0)
            continue
        try:
            execute_intent(state)
        except Exception as e:
            print(f"[autopilot] execute_intent error: {e}")
            KeyState.release_all()
        # Sleep the remainder of the frame.
        elapsed = time.time() - t0
        if elapsed < period:
            time.sleep(period - elapsed)
    KeyState.release_all()
    print("[autopilot] done")


if __name__ == "__main__":
    main()
