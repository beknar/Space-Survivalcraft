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

import json
import math
import os
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


# ── Telemetry ────────────────────────────────────────────────────────────
#
# JSONL stream of FSM transitions, deposit POST attempts, and periodic
# snapshots — written to bot_io/autopilot_telemetry.jsonl so a post-
# session analysis can reconstruct exactly why the bot did what it did.
# Enabled by default; the writer is best-effort and never raises into
# the main loop (a failed write just prints a warning).
#
# Volume: ~50-150 lines per minute under normal play (one per state
# transition + one snapshot every 5 s).  Safe to leave on.

_TELEMETRY_PATH = os.path.join("bot_io", "autopilot_telemetry.jsonl")
_telemetry_lock = threading.Lock()
_telemetry_started = False
_telemetry_last_snapshot_at: float = 0.0
TELEMETRY_SNAPSHOT_INTERVAL_S: float = 5.0


def _telemetry_init() -> None:
    """Create bot_io/ + write a session_start marker exactly once
    per autopilot process.  Safe to call repeatedly."""
    global _telemetry_started
    if _telemetry_started:
        return
    _telemetry_started = True
    try:
        os.makedirs("bot_io", exist_ok=True)
        with _telemetry_lock, open(_TELEMETRY_PATH, "a",
                                    encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "monotonic": _get_now() if "_get_now" in globals() else 0.0,
                "event": "session_start",
                "pid": os.getpid(),
            }) + "\n")
    except Exception as e:
        print(f"[autopilot] telemetry init error: {e}")


def _telemetry_log(event: str, **fields: Any) -> None:
    """Append one JSONL line to the telemetry stream.  Never raises
    into the caller — a failed write prints a warning and moves on."""
    try:
        line = json.dumps({
            "ts": time.time(),
            "monotonic": _get_now(),
            "event": event,
            **fields,
        })
        with _telemetry_lock, open(_TELEMETRY_PATH, "a",
                                    encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[autopilot] telemetry write error: {e}")


def _telemetry_snapshot_fields(state: dict, p: dict) -> dict:
    """Compact dump of the conditions that drive the FSM.  Used by
    state_transition + periodic snapshot events so each line is
    self-contained for offline analysis."""
    items = (state.get("inventory") or {}).get("items") or {}
    sitems = (state.get("station_inventory") or {}).get("items") or {}
    hs = _find_home_station(state) if "_find_home_station" in globals() else None
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hs_dist = None
    if hs is not None:
        hs_dist = math.hypot(
            float(hs.get("x", 0.0)) - px,
            float(hs.get("y", 0.0)) - py)
    now = _get_now()
    deposit_cooldown_remaining = max(
        0.0, DEPOSIT_COOLDOWN_S - (now - _state.last_deposit_at))
    return {
        "px": round(px, 1),
        "py": round(py, 1),
        "ship_iron": int(items.get("iron", 0)),
        "ship_blueprints": sum(
            v for k, v in items.items() if k.startswith("bp_")),
        "ship_modules": sum(
            v for k, v in items.items() if k.startswith("mod_")),
        "station_iron": int(sitems.get("iron", 0)),
        "buildings_count": len(state.get("buildings") or []),
        "has_home_station": hs is not None,
        "hs_dist": None if hs_dist is None else round(hs_dist, 1),
        "asteroids_count": len(state.get("asteroids") or []),
        "aliens_count": len(state.get("aliens") or []),
        "iron_pickups_count": len(state.get("iron_pickups") or []),
        "blueprint_pickups_count": len(state.get("blueprint_pickups") or []),
        "shields": int(p.get("shields", 0)),
        "max_shields": int(p.get("max_shields", 1)),
        "build_done": _state.build_done,
        "last_deposit_at": _state.last_deposit_at,
        "deposit_cooldown_remaining_s": round(deposit_cooldown_remaining, 2),
        "modules_to_craft_left": len(_state.queue.modules_to_craft),
        "modules_to_install_left": len(_state.queue.modules_to_install),
        "module_phase_started": _state.queue.module_phase_started,
        "consumable_phase_started": _state.queue.consumable_phase_started,
    }


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
S_DEPOSIT    = "deposit"
S_CRAFT      = "craft"
S_INSTALL    = "install"

ALL_STATES = (
    S_ENGAGE, S_GATHER, S_REGEN, S_MINE, S_SEARCH,
    S_BUILD, S_BUILD_SEEK, S_DEPOSIT, S_CRAFT, S_INSTALL,
)

# Starter-base build gate.  When the bot has accumulated this much
# iron AND there are no asteroids / aliens within the clear-area
# radius, it transitions into S_BUILD once and POSTs the build
# trigger.  ``_state.build_done`` flips True after the first
# attempt so the bot doesn't keep re-rolling the build
# (intentionally simple one-shot — a destroyed station won't
# auto-rebuild).
#
# 1000 iron covers all three build phases:
#   Phase 1 starter base  500 iron (HS 100 + SM 25 + PR 50 +
#                                   SA2 100 + RM 75 + 2× T2 150)
#   Phase 3 extension     325 iron (SM 25 + PR 50 + SA2 100 +
#                                   Basic Crafter 150)
#   Total                 825 iron — leaves ~175 iron of headroom
BUILD_IRON_THRESHOLD = 1000
# Ongoing-deposit gate.  Once a Home Station exists, the bot
# periodically returns to it to dump everything in the ship
# inventory (iron, copper, blueprints, anything).  Triggers on
# either threshold being met:
#   * ship iron ≥ DEPOSIT_IRON_THRESHOLD, OR
#   * ship has any blueprint pickup
# DEPOSIT_RANGE_PX is how close the bot must be to the home
# station before the deposit fires.  DEPOSIT_COOLDOWN_S avoids
# re-triggering the moment the bot starts a new mining run.
DEPOSIT_IRON_THRESHOLD = 200
DEPOSIT_RANGE_PX       = 200.0
DEPOSIT_COOLDOWN_S     = 30.0
# Single radius for "clear and quiet" — no asteroids, aliens,
# pickups, or buildings within this distance of the player.
# Approximately matches the visible game screen so the player's
# inability to see threats from off-screen doesn't trigger the
# build prematurely.
BUILD_CLEAR_RADIUS_PX = 800.0
# Distance the bot walks per tick when seeking a clear spot.
BUILD_SEEK_TARGET_DIST_PX = 1000.0
# Pickup blacklist — when stuck-detect fires while the bot is in
# S_GATHER, the pickup it was chasing gets added to a temporary
# blacklist so subsequent GATHER passes skip it.  Without this the
# bot oscillates indefinitely on a pickup sitting inside a
# station-building's repulsion zone (the field pushes back, the
# GATHER goto pulls forward; no progress, escape burst fires,
# bot returns, repeat).  The 23-event-in-155s gather-stuck loop
# documented in bot_io/autopilot_telemetry.jsonl on 2026-05-02
# was the motivating case.
PICKUP_BLACKLIST_TTL_S: float = 300.0   # entries expire after 5 minutes
PICKUP_BLACKLIST_RADIUS_PX: float = 60.0  # skip any pickup within this distance of a blacklisted point
# Asteroid blacklist — same mechanic as the pickup blacklist but
# for asteroids targeted while in S_MINE.  Diagnosed via the
# bot_io/autopilot_telemetry.jsonl session that showed 5
# consecutive stuck-detect events within 12 s at the same world
# position (3630, 1212), all in S_MINE — the bot was pressing
# against an asteroid (asteroids aren't in the building/boundary
# repulsion field, so the field can't deflect around them).
# Shorter TTL than the pickup blacklist because asteroids may be
# reachable from a different approach angle once the bot drifts
# elsewhere, and 60 s lets the bot retry from a clean state.
ASTEROID_BLACKLIST_TTL_S: float = 60.0
ASTEROID_BLACKLIST_RADIUS_PX: float = 40.0

# ── Craft phase tuning ──────────────────────────────────────────────────
# Iron threshold (in station inventory) the bot must accumulate
# before entering the module-craft phase.  Modules cost a total of
# 700 iron (50+75+100+125+150+200) — the 2000 cushion gives the bot
# headroom for any extra building work and for the consumable phase
# that follows.  Mirrored as the gate for the consumable phase too.
CRAFT_PHASE_IRON_THRESHOLD: int = 2000
# Distance below which the bot is "at" the Basic Crafter and can
# fire the /craft API call.  Wider than the player click range
# (300 px) so the bot doesn't have to inch the last few pixels.
CRAFT_INTERACT_RANGE_PX: float = 200.0
# Same idea for installing a module — the install flow operates on
# the station inventory + ship slots, no positional gate strictly
# required, but we still close to the Home Station so the action
# reads as deliberate (and so the bot is in safe territory when
# installing).
INSTALL_INTERACT_RANGE_PX: float = 250.0
# Sequence of modules the bot crafts after the starter base + all
# blueprints have been deposited.  In the user's wording the fifth
# entry was "damage enhancer" — the in-game module key for that is
# ``damage_absorber`` (effect: shield damage reduction), so the
# crafting cycle uses that key.  Order matches the user's spec.
MODULE_CRAFT_QUEUE: tuple[str, ...] = (
    "armor_plate",
    "engine_booster",
    "shield_booster",
    "shield_enhancer",
    "damage_absorber",
    "broadside",
)
# After all six modules are crafted, install just these four (in
# this order) into the ship.  Engine Booster and Damage Absorber
# stay in the station inventory.
MODULE_INSTALL_QUEUE: tuple[str, ...] = (
    "broadside",
    "shield_booster",
    "shield_enhancer",
    "armor_plate",
)
# Number of repair-pack and shield-recharge crafts to run after the
# install phase.  Each craft yields 5 of the consumable, so 5 craft
# cycles produces 25 repair packs and 25 shield recharges.
REPAIR_PACK_CRAFT_BATCHES: int = 5
SHIELD_RECHARGE_CRAFT_BATCHES: int = 5


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
# Throttle the "STUCK at edge" log so a long escape doesn't spam.
STUCK_LOG_THROTTLE_S     = 30.0
# ── Boundary potential field (preventive — the watchdog above is
# the reactive backstop) ───────────────────────────────────────────
# Within this distance of any world edge, a repulsion vector
# pointing away from that edge is blended into the goto heading.
# Tuned to start nudging well before the bot is at risk of pinning
# (~one screen height of warning) so the deflection is gradual,
# not a last-second swerve.
BOUNDARY_REPULSION_RANGE_PX: float = 400.0
# Strength of the repulsion vs the (unit-normalized) goto vector.
# Gain 1.0 means: at the edge itself (distance 0), repulsion has
# magnitude 1.0 along that axis, which equals the goto's
# magnitude — so a chase target directly through the edge ends up
# deflected ~45° along the wall instead of pinning.  Corners stack
# both axes so they push diagonally without extra logic.
BOUNDARY_REPULSION_GAIN: float = 1.0
# Per-building repulsion — same potential-field idea but the
# obstacles are the player's own structures instead of the world
# walls.  The corner of the player-built station was the one
# remaining edge-pin pattern after the world-boundary field
# landed (two perpendicular building edges create a corner trap
# the same way a world corner does).
#
# Range is intentionally small (well past the building's collision
# radius of ~30 px but still inside the deposit / install / craft
# stop radii of 200-250 px) so navigation TO a building still
# completes — the bot stops at the action range before the
# repulsion zone of the destination building closes the door.
BUILDING_REPULSION_RANGE_PX: float = 80.0
# Slightly softer than world-edge repulsion: a single building's
# push shouldn't fully overwhelm a chase vector when there's only
# 50 px of clearance to spare.  Two adjacent buildings (a corner)
# stack and recover the strong-deflect behaviour automatically.
BUILDING_REPULSION_GAIN: float = 0.7


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
class CraftQueue:
    """Sequential post-build workflow.

    The bot drives this queue in three phases after the starter
    base + extension are up:

      Phase 1 — craft each module key in ``modules_to_craft`` (head
                first), one per S_CRAFT visit; the FSM gathers
                between visits while the crafter ticks down its 60 s
                timer.

      Phase 2 — install each module key in ``modules_to_install``
                via S_INSTALL.  Each visit pulls one ``mod_<key>``
                out of station inventory and into the next free
                ship slot.

      Phase 3 — craft ``repair_packs_remaining`` batches of repair
                packs, then ``shield_recharges_remaining`` batches
                of shield recharges (5 of the consumable per
                batch).  Same S_CRAFT mechanism — only the queue
                contents differ.

    Heads are popped on confirmed completion, not on dispatch — a
    failed POST/start (insufficient iron, blueprint missing, no
    idle crafter) leaves the queue intact so the next FSM tick
    retries naturally.
    """
    modules_to_craft: list[str] = field(
        default_factory=lambda: list(MODULE_CRAFT_QUEUE))
    modules_to_install: list[str] = field(
        default_factory=lambda: list(MODULE_INSTALL_QUEUE))
    repair_packs_remaining: int = REPAIR_PACK_CRAFT_BATCHES
    shield_recharges_remaining: int = SHIELD_RECHARGE_CRAFT_BATCHES
    # Sticky flag: once the module-craft phase has STARTED (the
    # first craft fired), we don't re-gate on the 2000-iron
    # threshold for subsequent module crafts — only per-module
    # cost matters from that point on.  Keeps the bot from
    # stalling mid-queue if iron drops below 2000 between crafts.
    module_phase_started: bool = False
    # Same idea for the consumable phase.
    consumable_phase_started: bool = False


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
    })
    mining_weapon_pick: str = "Mining Beam"
    build_done: bool = False
    # Monotonic timestamp of the last successful POST /deposit_to_station.
    # Used as a cooldown so the bot doesn't re-trigger S_DEPOSIT
    # the moment it returns from a mining run.
    last_deposit_at: float = 0.0
    # Post-build craft + install queue.  See CraftQueue docstring.
    queue: CraftQueue = field(default_factory=CraftQueue)
    # Pickup blacklist: maps (rounded_x, rounded_y) -> expiry
    # monotonic timestamp.  Pickups within
    # PICKUP_BLACKLIST_RADIUS_PX of any live entry are skipped by
    # _nearest_pickup, so the bot stops oscillating on
    # unreachable pickups (typically those sitting inside a
    # station-building's repulsion zone).
    pickup_blacklist: dict = field(default_factory=dict)
    # Asteroid blacklist: same shape as pickup_blacklist but
    # populated when stuck-detect fires while the FSM is in
    # S_MINE.  _nearest_asteroid filters out hits within
    # ASTEROID_BLACKLIST_RADIUS_PX of any live entry.
    asteroid_blacklist: dict = field(default_factory=dict)

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
        self.last_deposit_at = fresh.last_deposit_at
        # Replace the queue object so the install/craft lists reset
        # to their full default contents on each FSM reset.
        self.queue = CraftQueue()
        self.pickup_blacklist.clear()
        self.asteroid_blacklist.clear()


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


def _fsm_reset(initial: str = S_MINE) -> None:
    """Reset every piece of bot runtime state to its default.
    Tests must call this in their setup/fixture so cross-test
    state doesn't leak.  The dict aliases (_fsm / _spiral_state /
    _stuck_state) stay valid because BotState.reset() mutates in
    place."""
    _state.reset()
    _state.fsm["state"] = initial


def _pickup_is_blacklisted(pu: dict) -> bool:
    """True if ``pu`` falls within ``PICKUP_BLACKLIST_RADIUS_PX``
    of any live (non-expired) blacklist entry."""
    bl = _state.pickup_blacklist
    if not bl:
        return False
    pux = float(pu.get("x", 0.0))
    puy = float(pu.get("y", 0.0))
    r_sq = PICKUP_BLACKLIST_RADIUS_PX * PICKUP_BLACKLIST_RADIUS_PX
    now = _get_now()
    for (bx, by), expiry in list(bl.items()):
        if now >= expiry:
            # Lazily evict expired entries during the scan.
            del bl[(bx, by)]
            continue
        dx = bx - pux
        dy = by - puy
        if dx * dx + dy * dy < r_sq:
            return True
    return False


def _blacklist_pickup(pu: dict) -> None:
    """Add ``pu`` to the pickup blacklist with a TTL of
    ``PICKUP_BLACKLIST_TTL_S``.  Position is rounded to the
    nearest 10 px so floating-point variation between ticks
    can't slip past the lookup."""
    pux = float(pu.get("x", 0.0))
    puy = float(pu.get("y", 0.0))
    key = (round(pux / 10.0) * 10.0, round(puy / 10.0) * 10.0)
    _state.pickup_blacklist[key] = _get_now() + PICKUP_BLACKLIST_TTL_S


def _nearest_pickup(state: dict, px: float, py: float
                    ) -> tuple[dict | None, float]:
    """Return the nearest iron + blueprint pickup combined,
    skipping any pickup that's been blacklisted (typically by
    a stuck-detect event in S_GATHER).  Blueprints are slightly
    preferred (worth more than 10 iron) so they get pulled in
    first when a tie."""
    iron = state.get("iron_pickups", []) or []
    bps = state.get("blueprint_pickups", []) or []
    candidates = [c for c in (list(bps) + list(iron))
                  if not _pickup_is_blacklisted(c)]
    return nearest(candidates, px, py)


def _asteroid_is_blacklisted(ast: dict) -> bool:
    """True if ``ast`` falls within
    ``ASTEROID_BLACKLIST_RADIUS_PX`` of any live (non-expired)
    asteroid blacklist entry."""
    bl = _state.asteroid_blacklist
    if not bl:
        return False
    ax = float(ast.get("x", 0.0))
    ay = float(ast.get("y", 0.0))
    r_sq = ASTEROID_BLACKLIST_RADIUS_PX * ASTEROID_BLACKLIST_RADIUS_PX
    now = _get_now()
    for (bx, by), expiry in list(bl.items()):
        if now >= expiry:
            del bl[(bx, by)]
            continue
        dx = bx - ax
        dy = by - ay
        if dx * dx + dy * dy < r_sq:
            return True
    return False


def _blacklist_asteroid(ast: dict) -> None:
    """Add ``ast`` to the asteroid blacklist with a TTL of
    ``ASTEROID_BLACKLIST_TTL_S``.  Position is rounded to a 10 px
    grid (same as the pickup blacklist) to absorb floating-point
    variation between ticks."""
    ax = float(ast.get("x", 0.0))
    ay = float(ast.get("y", 0.0))
    key = (round(ax / 10.0) * 10.0, round(ay / 10.0) * 10.0)
    _state.asteroid_blacklist[key] = _get_now() + ASTEROID_BLACKLIST_TTL_S


def _nearest_asteroid(state: dict, px: float, py: float
                      ) -> tuple[dict | None, float]:
    """Return the nearest non-blacklisted asteroid.  Used by
    S_MINE so a single unreachable asteroid doesn't lock the
    bot in an infinite stuck → escape → re-target loop — the
    same failure mode the pickup blacklist solved for S_GATHER.
    """
    asteroids = state.get("asteroids", []) or []
    candidates = [a for a in asteroids
                  if not _asteroid_is_blacklisted(a)]
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
    """Override movement: head AWAY from whatever is pinning the
    ship — boundary edge, station building, or both.

    The escape direction is the combined repulsion vector
    (boundary + building); by definition it points away from the
    obstacle the ship is pressed against.  Picking the world
    centre as a fixed escape target (the prior behaviour) was
    unsafe: a station built near the world centre put the cluster
    BETWEEN the bot and the escape goal, so the override drove
    the bot straight back into the buildings that pinned it,
    triggering a re-detect cycle.  Falls back to world centre
    only when neither field is active (i.e. the watchdog fired
    for a non-edge / non-building reason like a collision-induced
    velocity stall).
    """
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)

    rx, ry = _boundary_repulsion(p, zone)
    bx, by = _building_repulsion(p, state)
    rx += bx * BUILDING_REPULSION_GAIN
    ry += by * BUILDING_REPULSION_GAIN

    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    if abs(rx) > 0.05 or abs(ry) > 0.05:
        norm = math.hypot(rx, ry)
        ux = rx / norm
        uy = ry / norm
        # Travel a substantial distance along the repulsion
        # direction so the ship clears the field before the escape
        # exit-condition re-evaluates.
        tx = px + ux * BUILD_SEEK_TARGET_DIST_PX
        ty = py + uy * BUILD_SEEK_TARGET_DIST_PX
    else:
        tx = world_w * 0.5
        ty = world_h * 0.5
    # Clamp the escape target inside the world rect so it doesn't
    # itself sit at an edge.
    tx = max(STUCK_WORLD_MARGIN_PX,
             min(world_w - STUCK_WORLD_MARGIN_PX, tx))
    ty = max(STUCK_WORLD_MARGIN_PX,
             min(world_h - STUCK_WORLD_MARGIN_PX, ty))
    # stop_radius is generous so the escape ends as soon as we're
    # clearly off the obstacle, not when we reach the exact target.
    _do_goto(state, p, tx, ty, stop_radius=300.0)


def _ship_clear_of_edges(p: dict, zone: dict) -> bool:
    """True when the ship is at least
    STUCK_ESCAPE_CLEAR_MARGIN_PX from every world edge.  Used as
    one half of the exit condition for the escape override so the
    bot doesn't drop back into the FSM while still pinned at a
    boundary."""
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


def _ship_clear_of_buildings(p: dict, state: dict) -> bool:
    """True when the ship is outside ``BUILDING_REPULSION_RANGE_PX``
    of every building.  Used alongside ``_ship_clear_of_edges`` as
    the second half of the escape exit condition: without it, an
    escape from a station-corner pin would expire while the ship
    is still inside the building's repulsion zone, the bot would
    stall against the next-corner repulsion vector, and stuck
    detection would re-fire on the same building cluster."""
    buildings = state.get("buildings") or []
    if not buildings:
        return True
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    margin_sq = (
        BUILDING_REPULSION_RANGE_PX * BUILDING_REPULSION_RANGE_PX)
    for b in buildings:
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        dx = bx - px
        dy = by - py
        if dx * dx + dy * dy < margin_sq:
            return False
    return True


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
    for key in MODULE_CRAFT_QUEUE:
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

    # 0. Unconditional housekeeping — runs every tick, before any
    #    early-return branch.  If the bot just connected to a
    #    world that already has a Home Station (loaded save,
    #    prior session, manual placement), permanently mark
    #    build_done so the BUILD/BUILD_SEEK branch never fires.
    #    Has to live up here, NOT inside the BUILD branch below,
    #    because GATHER/ENGAGE/REGEN early-return long before the
    #    BUILD branch is reached — so if the bot enters GATHER
    #    on its very first tick (likely when a pickup is
    #    visible), build_done would stay False forever and the
    #    BUILD branch would fire as soon as GATHER cleared.
    if (not _state.build_done
            and _find_home_station(state) is not None):
        _state.build_done = True
        _telemetry_log("build_done_short_circuit",
                       reason="home_station_already_exists",
                       **_telemetry_snapshot_fields(state, p))

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

    now = _get_now()

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
    #
    #    The has-Home-Station short-circuit (see section 0
    #    above) flips ``build_done`` True the moment the bot
    #    sees an existing HS, so this branch only fires for a
    #    bot starting in a station-less world.
    if (not _state.build_done
            and _iron_total(state) >= BUILD_IRON_THRESHOLD):
        if _build_area_clear(state, px, py):
            return S_BUILD
        return S_BUILD_SEEK

    # 5. DEPOSIT — once a Home Station exists, the bot periodically
    #    returns to dump everything in the ship inventory (iron,
    #    blueprints, etc.) into the station's bigger inventory.
    #    Triggers when ship iron ≥ DEPOSIT_IRON_THRESHOLD.  The
    #    iron gate is required (no blueprint shortcut) so the bot
    #    doesn't make wasteful return trips with a single
    #    blueprint and 5 iron — blueprints accumulate alongside
    #    iron until the threshold is met, then everything ships
    #    in one round trip.  Cooldown prevents the bot from
    #    re-triggering immediately after a deposit run.
    hs = _find_home_station(state)
    if hs is not None:
        cooldown_ok = (
            now - _state.last_deposit_at) >= DEPOSIT_COOLDOWN_S
        if cooldown_ok and _iron_total(state) >= DEPOSIT_IRON_THRESHOLD:
            return S_DEPOSIT

    # 5.5  CRAFT / INSTALL — sequential post-build workflow.  Only
    #      reachable after a Home Station + Basic Crafter exist.
    #      Install takes priority over a fresh craft (we want
    #      crafted modules onto the ship before queuing more).
    #      Both gates require the FSM to NOT already have a
    #      crafter mid-cycle — the queue is intentionally serial,
    #      so the bot returns to MINE / GATHER / SEARCH while a
    #      craft ticks down its 60 s timer.
    if hs is not None and _find_basic_crafter(state, idle_only=False) is not None:
        if _next_install_target(state) is not None:
            return S_INSTALL
        if not _any_crafter_busy(state) and _next_craft_target(state) is not None:
            return S_CRAFT

    # 6. MINE vs SEARCH — discrete event, no hysteresis needed.
    #    Filter out blacklisted asteroids so a single unreachable
    #    one doesn't force MINE to fire on a target the bot
    #    can't actually reach.
    nearest_ast, _ = _nearest_asteroid(state, px, py)
    if nearest_ast is not None:
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
    _telemetry_init()
    now = _get_now()
    # Periodic snapshot so the JSONL stream still has context
    # during long stable stretches (no transitions = no other
    # events).  Cheap: ~1 line per 5 s.
    global _telemetry_last_snapshot_at
    if now - _telemetry_last_snapshot_at >= TELEMETRY_SNAPSHOT_INTERVAL_S:
        _telemetry_last_snapshot_at = now
        _telemetry_log("snapshot",
                       fsm_state=_fsm["state"],
                       **_telemetry_snapshot_fields(state, p))

    # Stuck watchdog: if the ship has been pinned against either
    # the world boundary OR a station building cluster, override
    # the FSM and head along the local repulsion vector toward
    # open space.  Has to run BEFORE the FSM dispatch so it
    # preempts whatever was driving the ship into the obstacle.
    _record_position(p)
    zone = state.get("zone") or {}
    if _stuck_state["escape_until"] > 0.0:
        # Escape is active.  Stay in escape until ALL of:
        #  * the minimum duration has elapsed, AND
        #  * the ship is clear of all world edges by the safety
        #    margin, AND
        #  * the ship is clear of all buildings by the building-
        #    repulsion range (so an escape from a station-corner
        #    pin doesn't expire while still inside the field that
        #    will pin us again).
        # Continuously clear position history while in escape so
        # the next detect cycle starts fresh after we exit.
        _stuck_state["history"] = []
        if (now < _stuck_state["escape_until"]
                or not _ship_clear_of_edges(p, zone)
                or not _ship_clear_of_buildings(p, state)):
            _do_escape_edge(state, p)
            return
        # Exit condition met — clear the override and fall through.
        _stuck_state["escape_until"] = 0.0
    if _detect_stuck():
        _stuck_state["escape_until"] = now + STUCK_ESCAPE_MIN_DURATION_S
        # Blacklist whichever target the bot was trying to reach —
        # if we got stuck WHILE in S_GATHER, the pickup is
        # unreachable (typically inside a station-building's
        # repulsion zone); if we got stuck WHILE in S_MINE, the
        # asteroid is unreachable (asteroids aren't in the field,
        # so the bot rams them).  Without these blacklists, the
        # FSM re-targets the same object on the next tick and the
        # stuck → escape → re-target loop runs forever.
        blacklisted_pu = None
        blacklisted_ast = None
        sx = float(p.get("x", 0.0))
        sy = float(p.get("y", 0.0))
        if _fsm["state"] == S_GATHER:
            stuck_pu, _ = _nearest_pickup(state, sx, sy)
            if stuck_pu is not None:
                _blacklist_pickup(stuck_pu)
                blacklisted_pu = {
                    "x": round(float(stuck_pu.get("x", 0.0)), 1),
                    "y": round(float(stuck_pu.get("y", 0.0)), 1),
                    "item_type": stuck_pu.get("item_type", ""),
                }
                print(f"[autopilot] PICKUP-BLACKLIST: {blacklisted_pu} "
                      f"(stuck while gathering, ttl "
                      f"{int(PICKUP_BLACKLIST_TTL_S)}s)")
        elif _fsm["state"] == S_MINE:
            stuck_ast, _ = _nearest_asteroid(state, sx, sy)
            if stuck_ast is not None:
                _blacklist_asteroid(stuck_ast)
                blacklisted_ast = {
                    "x": round(float(stuck_ast.get("x", 0.0)), 1),
                    "y": round(float(stuck_ast.get("y", 0.0)), 1),
                    "hp": stuck_ast.get("hp", 0),
                }
                print(f"[autopilot] ASTEROID-BLACKLIST: {blacklisted_ast} "
                      f"(stuck while mining, ttl "
                      f"{int(ASTEROID_BLACKLIST_TTL_S)}s)")
        _telemetry_log("stuck_detected",
                       cause=("building"
                              if not _ship_clear_of_buildings(p, state)
                              else "edge"),
                       fsm_state=_fsm["state"],
                       blacklisted_pickup=blacklisted_pu,
                       blacklisted_asteroid=blacklisted_ast,
                       **_telemetry_snapshot_fields(state, p))
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
        # Throttle the log so a long escape burst doesn't spam.
        if (now - _stuck_state["last_log"]) >= STUCK_LOG_THROTTLE_S:
            # Distinguish edge vs building stucks in the log so
            # repeated firings are easier to diagnose.
            cause = ("building" if not _ship_clear_of_buildings(p, state)
                     else "edge")
            print(f"[autopilot] STUCK at {cause} — escape burst along "
                  "repulsion vector + re-anchoring spiral")
            _stuck_state["last_log"] = now
        _do_escape_edge(state, p)
        return

    cur = _fsm["state"]
    prev = cur
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
        _telemetry_log("state_transition", reason="first_tick",
                       from_state=prev, to_state=cur, desired=desired,
                       **_telemetry_snapshot_fields(state, p))
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
            _telemetry_log("state_transition", reason="dwell_or_preempt",
                           from_state=prev, to_state=cur, desired=desired,
                           dwell_s=round(dwell, 3),
                           **_telemetry_snapshot_fields(state, p))
        else:
            # Desired state changed but MIN_DWELL gating held the
            # current one — log the suppressed transition so we
            # can see when the FSM "wants" to change but can't.
            _telemetry_log("transition_suppressed_by_dwell",
                           from_state=cur, desired=desired,
                           dwell_s=round(dwell, 3),
                           min_dwell_s=MIN_DWELL_S,
                           **_telemetry_snapshot_fields(state, p))

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
    elif cur == S_DEPOSIT:
        _act_deposit(state, p)
    elif cur == S_CRAFT:
        _act_craft(state, p)
    elif cur == S_INSTALL:
        _act_install(state, p)
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


def _post_craft(target: str, timeout_s: float = 5.0) -> dict | None:
    """POST /craft to start a Basic Crafter cycle for ``target``
    (a MODULE_TYPES key, ``"repair_pack"``, or ``"shield_recharge"``).
    Returns the parsed response dict (with ``ok`` flag) or ``None``
    on transport failure."""
    try:
        import json
        req = Request(
            f"{API_BASE}/craft",
            data=json.dumps({"target": target}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] craft POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] craft POST unexpected error: {e}")
        return None


def _post_install_module(mod_key: str,
                          timeout_s: float = 5.0) -> dict | None:
    """POST /install_module to install one ``mod_<mod_key>`` from
    station inventory into the next free ship slot.  Returns the
    parsed response dict or ``None`` on transport failure."""
    try:
        import json
        req = Request(
            f"{API_BASE}/install_module",
            data=json.dumps({"mod_key": mod_key}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] install POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] install POST unexpected error: {e}")
        return None


def _post_deposit_to_station(timeout_s: float = 5.0) -> dict | None:
    """POST /deposit_to_station on the in-game HTTP API.  Returns
    the parsed JSON response, or ``None`` on transport failure.
    The endpoint is synchronous — the in-process deposit runs on
    the main thread and returns the moved-items dict."""
    try:
        req = Request(
            f"{API_BASE}/deposit_to_station",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout_s) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[autopilot] deposit POST error: {e}")
        return None
    except Exception as e:
        print(f"[autopilot] deposit POST unexpected error: {e}")
        return None


def _act_deposit(state: dict, p: dict) -> None:
    """DEPOSIT: head to the home station and dump everything in
    the ship inventory into the station's bigger storage.  Once
    within DEPOSIT_RANGE_PX of the Home Station, POSTs the
    deposit and stamps ``last_deposit_at`` so the cooldown kicks
    in.  Otherwise just navigates toward the station — the FSM
    re-evaluates next tick."""
    hs = _find_home_station(state)
    if hs is None:
        # Home Station vanished mid-tick (destroyed?) — fall back
        # to idle so the FSM can re-route on the next tick.
        _do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hx = float(hs.get("x", 0.0))
    hy = float(hs.get("y", 0.0))
    dist = math.hypot(hx - px, hy - py)
    if dist <= DEPOSIT_RANGE_PX:
        # In range — fire the deposit and stamp cooldown.
        result = _post_deposit_to_station()
        _state.last_deposit_at = _get_now()
        deposited = (result or {}).get("deposited", {}) or {}
        _telemetry_log("deposit_post",
                       success=result is not None,
                       in_range_dist=round(dist, 1),
                       deposited=deposited,
                       **_telemetry_snapshot_fields(state, p))
        if result is not None and deposited:
            print("[autopilot] DEPOSIT: "
                  f"{', '.join(f'{k}={v}' for k, v in deposited.items())}")
        return
    # Not yet in range — navigate to the home station, no fire.
    KeyState.hold("space", False)
    _do_goto(state, p, hx, hy, stop_radius=DEPOSIT_RANGE_PX * 0.8)


def _next_craft_target(state: dict) -> str | None:
    """Return the next thing the bot wants to craft, or ``None`` if
    the queue is empty / preconditions aren't met.  Encapsulates
    the three-phase workflow:

      1. Modules from MODULE_CRAFT_QUEUE (gated by 2000 iron on
         entry, then by per-module cost + matching blueprint).
      2. Repair packs (after install queue is drained).
      3. Shield recharges (after repair packs are done).

    The 2000-iron gate sticks once the phase has started — so the
    bot doesn't stall mid-queue if iron drops below 2000 after the
    first craft pays out.
    """
    from constants import MODULE_TYPES, CRAFT_IRON_COST  # local import: kept off the
                                                          # autopilot's hot path; this
                                                          # function only fires when the
                                                          # craft phase is reachable.
    q = _state.queue
    items = _station_items(state)
    iron = int(items.get("iron", 0))

    # ── Module craft phase ────────────────────────────────────────
    if q.modules_to_craft:
        # 2000-iron gate on the FIRST module craft only.
        if not q.module_phase_started and iron < CRAFT_PHASE_IRON_THRESHOLD:
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

    if q.repair_packs_remaining > 0:
        # 2000-iron gate on the FIRST consumable craft only.
        if (not q.consumable_phase_started
                and iron < CRAFT_PHASE_IRON_THRESHOLD):
            return None
        if iron < CRAFT_IRON_COST:
            return None
        return "repair_pack"

    # ── Shield recharge phase ─────────────────────────────────────
    if q.shield_recharges_remaining > 0:
        if (not q.consumable_phase_started
                and iron < CRAFT_PHASE_IRON_THRESHOLD):
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
    q = _state.queue
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


def _act_craft(state: dict, p: dict) -> None:
    """S_CRAFT: navigate to the nearest idle Basic Crafter.  Once
    in range, fire POST /craft for the queue head and pop the
    queue on success.  The FSM transitions back to MINE / GATHER /
    SEARCH on the next tick — the crafter ticks down its 60 s
    timer on its own, and ``_choose_next_state`` won't re-enter
    S_CRAFT until ``_any_crafter_busy`` reports False again."""
    crafter = _find_basic_crafter(state, idle_only=True)
    if crafter is None:
        # No idle crafter visible — happens for one tick right
        # after we just started a craft (state hasn't refreshed
        # yet).  Fall back to safe coast; the FSM re-routes us
        # next tick.
        _do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    cx = float(crafter.get("x", 0.0))
    cy = float(crafter.get("y", 0.0))
    dist = math.hypot(cx - px, cy - py)
    if dist > CRAFT_INTERACT_RANGE_PX:
        # Still travelling — navigate, don't fire.
        KeyState.hold("space", False)
        _do_goto(state, p, cx, cy,
                 stop_radius=CRAFT_INTERACT_RANGE_PX * 0.8)
        return
    # In range.  Compute what to craft, fire the POST, pop on success.
    target = _next_craft_target(state)
    if target is None:
        # Queue head not ready (insufficient iron, blueprint
        # missing, etc.).  Idle one tick; FSM will re-route.
        _do_idle()
        return
    KeyState.release_all()
    print(f"[autopilot] CRAFT: starting {target!r} "
          f"(station_iron={_station_iron(state)})")
    result = _post_craft(target)
    q = _state.queue
    if result is None or not result.get("ok", False):
        reason = (result or {}).get("reason", "transport failure")
        print(f"[autopilot] CRAFT: {target!r} rejected ({reason})")
        return
    # Success — pop the queue head + flip the phase-started latch.
    if target in MODULE_CRAFT_QUEUE and q.modules_to_craft \
            and q.modules_to_craft[0] == target:
        q.modules_to_craft.pop(0)
        q.module_phase_started = True
    elif target == "repair_pack" and q.repair_packs_remaining > 0:
        q.repair_packs_remaining -= 1
        q.consumable_phase_started = True
    elif target == "shield_recharge" and q.shield_recharges_remaining > 0:
        q.shield_recharges_remaining -= 1
        q.consumable_phase_started = True
    print(f"[autopilot] CRAFT: queued {target!r} -- "
          f"modules_left={len(q.modules_to_craft)} "
          f"installs_left={len(q.modules_to_install)} "
          f"rp_left={q.repair_packs_remaining} "
          f"sr_left={q.shield_recharges_remaining}")


def _act_install(state: dict, p: dict) -> None:
    """S_INSTALL: navigate to the Home Station, then fire POST
    /install_module for the head of ``modules_to_install``.  Pops
    the queue on success."""
    hs = _find_home_station(state)
    if hs is None:
        _do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hx = float(hs.get("x", 0.0))
    hy = float(hs.get("y", 0.0))
    dist = math.hypot(hx - px, hy - py)
    if dist > INSTALL_INTERACT_RANGE_PX:
        KeyState.hold("space", False)
        _do_goto(state, p, hx, hy,
                 stop_radius=INSTALL_INTERACT_RANGE_PX * 0.8)
        return
    target = _next_install_target(state)
    if target is None:
        _do_idle()
        return
    KeyState.release_all()
    result = _post_install_module(target)
    q = _state.queue
    if result is None or not result.get("ok", False):
        reason = (result or {}).get("reason", "transport failure")
        print(f"[autopilot] INSTALL: {target!r} rejected ({reason})")
        return
    if q.modules_to_install and q.modules_to_install[0] == target:
        q.modules_to_install.pop(0)
    print(f"[autopilot] INSTALL: {target!r} -> slot "
          f"{result.get('slot')} (installs_left="
          f"{len(q.modules_to_install)})")


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
    # no real targets nearby.  Blacklist-aware so we don't burn
    # the laser on an asteroid we just gave up on.
    nearest_ast, nd = _nearest_asteroid(state, px, py)
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


def _boundary_repulsion(p: dict, zone: dict) -> tuple[float, float]:
    """Potential-field repulsion vector pointing **away from world
    edges**.  Each axis contributes independently and linearly:
    magnitude is 0 at distance ``BOUNDARY_REPULSION_RANGE_PX`` from
    an edge, ramps to 1.0 right at the edge.

    Corners get the sum of both axis components automatically, which
    yields a diagonal push (correct: away from the corner).  Far
    from any edge the result is exactly ``(0.0, 0.0)`` so callers
    pay no cost for the safe case.

    Returns a (dx, dy) vector in world coords; the caller is
    expected to add it to a unit-normalized goto vector to bias
    the heading.
    """
    if not zone:
        return (0.0, 0.0)
    world_w = float(zone.get("world_w", 0) or 0)
    world_h = float(zone.get("world_h", 0) or 0)
    if world_w <= 0 or world_h <= 0:
        return (0.0, 0.0)
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    rng = BOUNDARY_REPULSION_RANGE_PX
    rx = 0.0
    ry = 0.0
    # West edge (x = 0) — push east (+x).
    if px < rng:
        rx += 1.0 - max(0.0, px) / rng
    # East edge — push west (-x).
    east_dist = world_w - px
    if east_dist < rng:
        rx -= 1.0 - max(0.0, east_dist) / rng
    # South edge (y = 0) — push north (+y).
    if py < rng:
        ry += 1.0 - max(0.0, py) / rng
    # North edge — push south (-y).
    north_dist = world_h - py
    if north_dist < rng:
        ry -= 1.0 - max(0.0, north_dist) / rng
    return (rx, ry)


def _building_repulsion(p: dict, state: dict) -> tuple[float, float]:
    """Per-building potential-field repulsion summed across every
    building visible in /state.  Same linear ramp as
    ``_boundary_repulsion`` but the source is the player's own
    structures instead of the world walls.

    Each building within ``BUILDING_REPULSION_RANGE_PX`` of the
    ship contributes a unit-vector pointing from the building
    center to the ship, scaled by ``1 - dist/range``.  Two adjacent
    buildings (a station corner) sum their contributions
    automatically, recovering the strong-deflect behaviour the
    boundary field gets at world corners.

    Returns a (dx, dy) push vector in world coords; the caller
    blends it with the boundary field inside ``_steered_heading``.
    """
    buildings = state.get("buildings") or []
    if not buildings:
        return (0.0, 0.0)
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    rng = BUILDING_REPULSION_RANGE_PX
    rng_sq = rng * rng
    rx = 0.0
    ry = 0.0
    for b in buildings:
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        dx_b = px - bx
        dy_b = py - by
        d_sq = dx_b * dx_b + dy_b * dy_b
        if d_sq >= rng_sq:
            continue
        d = math.sqrt(d_sq)
        if d < 0.5:
            # Centred on a building (shouldn't happen given
            # collision, but be safe) — push north arbitrarily so
            # the field has *some* direction to act on instead of
            # collapsing to zero.
            ry += 1.0
            continue
        strength = 1.0 - d / rng
        rx += (dx_b / d) * strength
        ry += (dy_b / d) * strength
    return (rx, ry)


def _steered_heading(state: dict, p: dict, dx: float, dy: float,
                     dist: float) -> float:
    """Return the heading (degrees) the bot should rotate toward,
    after blending in the boundary + building repulsion fields.
    ``dx, dy`` is the raw goto vector from the ship to the target;
    ``dist`` is its magnitude (caller usually has it already from
    ``math.hypot``).

    When the ship is far from every world edge AND every building
    the function just returns ``angle_to(dx, dy)`` — both fields
    are zero so the blended heading is identical to the
    unmodified one.  Closer to an edge / building the field
    pushes the heading along that wall instead of through it,
    deflecting smoothly so the bot routes around corners rather
    than pinning.
    """
    zone = state.get("zone") or {}
    rx, ry = _boundary_repulsion(p, zone)
    bx, by = _building_repulsion(p, state)
    rx += bx * BUILDING_REPULSION_GAIN
    ry += by * BUILDING_REPULSION_GAIN
    if rx == 0.0 and ry == 0.0:
        return angle_to(dx, dy)
    # Unit-normalize the goto vector so the field's unit-scale
    # repulsion has comparable weight regardless of the goto
    # vector's length.  Avoids a 5000-px goto vector dominating a
    # near-edge repulsion of magnitude ~1.0.
    norm = max(1.0, dist)
    gx = dx / norm
    gy = dy / norm
    sx = gx + rx * BOUNDARY_REPULSION_GAIN
    sy = gy + ry * BOUNDARY_REPULSION_GAIN
    # Degenerate cancellation: a goto pointing straight into a
    # wall opposes the repulsion exactly along one axis, so the
    # sum's magnitude collapses to ~0 and ``angle_to(0, 0)``
    # would return 0° (north) — arbitrary direction unrelated to
    # either the goto or the wall.  Fall back to **pure
    # repulsion** in that case so the bot peels off the wall
    # instead of picking a random heading.
    if abs(sx) < 0.05 and abs(sy) < 0.05:
        return angle_to(rx, ry)
    return angle_to(sx, sy)


def _do_goto(state: dict, p: dict, tx: float, ty: float,
             stop_radius: float = 80.0) -> None:
    """Rotate toward (tx, ty) and thrust until within ``stop_radius``.

    The heading is blended through ``_steered_heading`` so the
    boundary potential field deflects the bot away from world
    edges before it pins itself — see the BOUNDARY_REPULSION_*
    constants for tuning.  Without this the bot would chase
    edge-adjacent targets right into the wall and rely on the
    reactive stuck-detect watchdog to pull it out.
    """
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
    target = _steered_heading(state, p, dx, dy, dist)
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
    inside the dead-band to avoid jitter.

    Heading is steered through the boundary repulsion field, so an
    asteroid sitting near the edge gets engaged from a position
    that doesn't pin the ship against the wall during the swing
    cycle.
    """
    dx = tx - p.get("x", 0)
    dy = ty - p.get("y", 0)
    dist = math.hypot(dx, dy)
    # Always rotate to face the target so the swing arc covers it.
    target = _steered_heading(state, p, dx, dy, dist)
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
    target, dist = _nearest_asteroid(
        state, p.get("x", 0), p.get("y", 0))
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
