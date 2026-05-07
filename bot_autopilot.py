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

# ── Refactored helper modules (re-exported below) ──────────────────────
import bot_autopilot_telemetry as _tlm
import bot_autopilot_navigation as _nav
import bot_autopilot_blacklist as _bl

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


# ── Telemetry (implementation in bot_autopilot_telemetry.py) ─────────────
#
# JSONL stream of FSM transitions, deposit POST attempts, and periodic
# snapshots — written to bot_io/autopilot_telemetry.jsonl so a post-
# session analysis can reconstruct exactly why the bot did what it did.
# This module owns the FSM-side bindings; the writer + snapshot dict
# live in ``bot_autopilot_telemetry``.

_TELEMETRY_PATH = _tlm._TELEMETRY_PATH
TELEMETRY_SNAPSHOT_INTERVAL_S = _tlm.TELEMETRY_SNAPSHOT_INTERVAL_S
# Last monotonic at which _do_auto wrote a periodic "snapshot" event.
# Lives here (not in the telemetry module) because the cadence is an
# autopilot-loop concern; the telemetry module is just the writer.
_telemetry_last_snapshot_at: float = 0.0


def _telemetry_init() -> None:
    """Re-export of ``bot_autopilot_telemetry.telemetry_init`` —
    bound through this name for backward-compat with tests that
    monkey-patch ``bot_autopilot._telemetry_init``."""
    _tlm.telemetry_init()


def _telemetry_log(event: str, **fields: Any) -> None:
    """Re-export of ``bot_autopilot_telemetry.telemetry_log``."""
    _tlm.telemetry_log(event, **fields)


def _telemetry_snapshot_fields(state: dict, p: dict) -> dict:
    """Bind the autopilot's ``_state`` / ``_get_now`` /
    ``_find_home_station`` into the telemetry snapshot helper."""
    return _tlm.make_snapshot_fields(
        state=state,
        p=p,
        bot_state=_state,
        deposit_cooldown_s=DEPOSIT_COOLDOWN_S,
        find_home_station=_find_home_station,
        get_now=_get_now,
    )


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


# ── Geometry (re-exported from bot_autopilot_navigation) ─────────────────

angle_to = _nav.angle_to
heading_delta = _nav.heading_delta
nearest = _bl.nearest


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
# Bumped 0.6 -> 1.0 after 2026-05-06 telemetry: 25-min session logged
# 182 mine<->gather toggles, 116 of them reversing within 5 s and 43
# gather dwells under 1 s.  Symptom of pickups being collected fast
# enough that GATHER exits in ~1.2 s median, then MINE re-enters,
# and each MINE entry re-rolls the Mining Beam vs Energy Pickaxe
# dice + drives a Tab keystroke through KeyState.  At 1.0 s the
# floor still allows fast reaction to legitimate priority changes
# but suppresses the sub-second flicker.  ENGAGE / REGEN bypass
# this floor (defensive interrupts) so combat responsiveness is
# unchanged.
MIN_DWELL_S:     float = 1.0      # how long a non-ENGAGE state must hold

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
# S_HUNT: when no asteroid is visible, extend engagement range to
# HUNT_RANGE_PX so the bot pursues aliens for resources instead of
# circling in empty space.  Lower priority than ENGAGE (which still
# fires on close threats regardless of asteroid availability) and
# higher priority than SEARCH.  Action handler reuses _act_engage
# since the close-and-fight behaviour is identical — only the
# dispatch logic differs (HUNT triggers proactively, ENGAGE
# defensively).
S_HUNT       = "hunt"
# S_IDLE_AT_BASE: when no asteroid is visible (or all are blacklisted)
# AND no alien is within HUNT_RANGE_PX AND a Home Station exists,
# the bot navigates to the station and idles there waiting for
# respawns.  Replaces the old SEARCH fallback in this case —
# spiralling in empty space wastes time + thrust.  Once a target
# appears, normal FSM priority resumes (asteroid -> MINE; alien ->
# HUNT or ENGAGE).  Falls back to SEARCH when no Home Station
# exists yet (early-game: still need to spiral to find resources
# for the starter base).
S_IDLE_AT_BASE = "idle_at_base"

ALL_STATES = (
    S_ENGAGE, S_GATHER, S_REGEN, S_MINE, S_SEARCH,
    S_BUILD, S_BUILD_SEEK, S_DEPOSIT, S_CRAFT, S_INSTALL,
    S_HUNT, S_IDLE_AT_BASE,
)

# Maximum range at which the bot will commit to chasing an alien
# in S_HUNT.  Mirrors MAX_ASTEROID_CHASE_PX (2000 px) but slightly
# higher because aliens are mobile — they may close on the bot
# during the chase, and a longer leash means fewer SEARCH/HUNT
# transitions if the alien drifts to the edge of view.
HUNT_RANGE_PX: float = 3000.0
# Hunt range while parked at base (S_IDLE_AT_BASE).  Wider than the
# normal 3000 px so the bot proactively sorties from base when an
# alien spawns anywhere on the typical 6400×6400 zone — sitting at
# full HP/shields adjacent to the crafter, there's no downside to a
# longer leash.  2026-05-04 telemetry: the bot sat parked for 95 s
# while aliens roamed at >3000 px because the standard HUNT gate
# never fired.
IDLE_HUNT_RANGE_PX: float = 9000.0
# IDLE_AT_BASE: distance from the Home Station inside which the bot
# stops navigating + just idles.  Set wide (600 px) so the bot
# parks OUTSIDE the typical station-building cluster (HS + 10
# placed buildings spread 300-500 px around the centre) rather
# than trying to penetrate it.  Diagnosed via 2026-05-03
# telemetry: at the original 300 px radius the bot oscillated
# between hs_dist=60 and hs_dist=330 inside the cluster, fired
# stuck-detect 12 times in 5 minutes as the aggregated building
# potential field shoved it around.  At 600 px the bot stops
# (stop_radius = 480) well outside any building's 80 px
# repulsion range, the field reads zero, and the bot drifts
# cleanly.
IDLE_AT_BASE_RADIUS_PX: float = 600.0

# Hunt-stuck giveup: if S_HUNT logs HUNT_STUCK_THRESHOLD or more
# stuck-detect events inside HUNT_STUCK_WINDOW_S seconds, suppress
# further HUNT transitions for HUNT_GIVEUP_S seconds.  Triggered by
# the 2026-05-04 telemetry where the bot fired stuck_detected 14
# times in 85 s while the FSM kept re-routing it from inside the
# station building cluster toward an alien on the far side.  The
# giveup gives the bot a chance to fall through to IDLE_AT_BASE,
# regroup at the outer ring, and try the chase from clear space.
#
# Window widened from 10 s to 30 s after 2026-05-05 telemetry: a
# 5-stuck cluster spread over 22 s never tripped the original
# 10 s acute window — every 3-event slice spanned 10.8-11.0 s,
# just barely over the threshold.  30 s catches realistic clusters
# without false-positives during normal hunts (a clean kill chain
# does not produce 3 stucks in any 30 s window).
HUNT_STUCK_WINDOW_S:   float = 30.0
HUNT_STUCK_THRESHOLD:  int   = 3
HUNT_GIVEUP_S:         float = 30.0

# Building-cluster pin escape: the FSM-level guard added in PR #37
# refuses to re-fire HUNT when the bot is inside the building
# repulsion field.  Without a delay it fires on the first re-eval
# tick (dwell ~= MIN_DWELL_S = 1 s) — at that point the bot has
# barely moved.  IDLE_AT_BASE often parks the bot inside the
# cluster perimeter (the 600 px outer ring crosses the 11-building
# spread that extends well past the 150 px repulsion range from
# the HS centroid), so each fresh HUNT entry from a parked
# position immediately bounced back to IDLE — 39 fast IDLE↔HUNT
# pairs in the 2026-05-06 follow-up #3 telemetry.
#
# The delay gives an initial HUNT entry HUNT_CLUSTER_PIN_DELAY_S
# seconds to thread its way out of the perimeter before the guard
# activates.  Sustained pins (the 55 s case from PR #37) still
# trip the guard cleanly at t+3 s instead of t+1 s.
HUNT_CLUSTER_PIN_DELAY_S: float = 3.0

# Pin-escape lockout: when EITHER the wall-pin escape (helper
# returns None on currently_hunting=True with bot+aliens edge-
# adjacent) OR the cluster-pin guard fires, also push out
# ``_state.hunt_giveup_until`` so the FSM can't re-enter HUNT for
# this many seconds.  Without this, the suppression only stops
# the CURRENT HUNT — the very next tick from IDLE_AT_BASE has
# ``currently_hunting=False``, takes the helper's unfiltered
# fallback path, sees the same edge alien, and re-fires HUNT.
# 2026-05-06 follow-up #4 telemetry caught the result: 107
# IDLE↔HUNT toggles in 3 minutes (54 + 53), median dwell 1.01 s
# in both states (right at MIN_DWELL_S floor), bot wall-pinned
# at px=48 for 146 s straight while visibly oscillating to the
# user.  10 s converts a 1-per-second thrash into 1-per-10-seconds
# probing — the same pin still trips the same lockout, but the
# user-visible oscillation drops by 90 %.
HUNT_PIN_GIVEUP_S: float = 10.0

# Long-term per-anchor hunt-stuck tracking: catches the SLOW
# repeated-pin pattern that the acute window above misses.  When a
# stuck event fires in S_HUNT, the anchor (rounded to a 200 px grid)
# is recorded with a 5-min TTL.  Once an anchor accumulates
# HUNT_ANCHOR_MAX_HITS hits, the giveup latch fires for the
# extended HUNT_LONG_GIVEUP_S window.  Caught from 2026-05-04
# telemetry: same (3101, 3816) cluster anchor produced 3 stuck
# events spread over 250 s — never tripped the acute 10 s window
# but burned ~5 % of the session in repeat pins.
#
# Grid widened from 100 px to 200 px after 2026-05-05 telemetry: a
# tight wall-pin cluster around (2600-2700, 4700-4800) generated 8
# stucks but the 100 px grid split them across 3 cells (2+3+3 hits)
# so no single bucket reached the 3-hit threshold.  At 200 px the
# whole cluster collapses into one anchor and trips on the third hit.
HUNT_ANCHOR_TTL_S:      float = 300.0
HUNT_ANCHOR_GRID_PX:    float = 200.0
HUNT_ANCHOR_MAX_HITS:   int   = 3
HUNT_LONG_GIVEUP_S:     float = 120.0

# ``_nearest_asteroid`` skips asteroids within this distance of any
# world boundary at selection time.  Wider than STUCK_WORLD_MARGIN_PX
# (200) so the bot has room to circle the asteroid + brake before
# the boundary repulsion field engages.  The reactive 60 s asteroid
# blacklist is the fallback for the (rare) case where every
# remaining asteroid is edge-adjacent.
ASTEROID_EDGE_SKIP_PX:  float = 250.0
# ``_nearest_pickup`` skips pickups within this distance of any
# world boundary.  Pickups spawn wherever an alien dies — including
# right against the wall.  Slightly tighter than the asteroid
# margin because pickups have a despawn timer (the bot can wait for
# the next one) and a stationary pickup is easier to circle than
# an asteroid that the bot has to physically push.
PICKUP_EDGE_SKIP_PX:    float = 200.0
# ``_nearest_huntable_alien`` skips aliens within this distance of
# any world boundary when picking a HUNT target (the proactive
# "no asteroid in range, chase an alien for iron drops" branch).
# Caught from 2026-05-06 telemetry: bot was wall-pinned at px=48
# for 190+ s chasing aliens whose AI parked them right against the
# left edge — the existing position-based stuck detector never
# fired because the bot kept rotating to face the target (defeating
# the rotation gate) and oscillated 40 px along the wall (defeating
# the displacement gate).  Pre-filtering huntable aliens at the
# selection layer mirrors the asteroid + pickup edge skips and
# avoids committing to a chase that ends in a wall-pin.
#
# ENGAGE (the defensive band) deliberately does NOT use this
# filter — if an alien is shooting us from the wall we still need
# to fight back.  Only HUNT (proactive resource-driven chase) is
# free to be choosy.
ALIEN_EDGE_SKIP_PX:     float = 250.0

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
# Lowered from 200 → 100 on 2026-05-03: telemetry showed the bot
# capping out at 195 ship iron between station visits and never
# reaching the old 200 threshold — only ONE deposit fired in a
# 10-minute session.  At 100, deposits run more often, station
# iron grows steadily, and the post-install consumable phase
# stops stalling.
DEPOSIT_IRON_THRESHOLD = 100
DEPOSIT_RANGE_PX       = 200.0
DEPOSIT_COOLDOWN_S     = 30.0
# Single radius for "clear and quiet" — no asteroids, aliens,
# pickups, or buildings within this distance of the player.
# Approximately matches the visible game screen so the player's
# inability to see threats from off-screen doesn't trigger the
# build prematurely.
BUILD_CLEAR_RADIUS_PX = 800.0
# Distance the bot walks per tick when seeking a clear spot.
BUILD_SEEK_TARGET_DIST_PX = _nav.BUILD_SEEK_TARGET_DIST_PX
# Blacklist tuning lives in bot_autopilot_blacklist; re-exported
# here so existing tests / call sites read them off this module.
PICKUP_BLACKLIST_TTL_S = _bl.PICKUP_BLACKLIST_TTL_S
PICKUP_BLACKLIST_RADIUS_PX = _bl.PICKUP_BLACKLIST_RADIUS_PX
# Maximum chase distance for an asteroid target.  Asteroids
# farther than this are treated as out-of-reach so MINE falls
# through to SEARCH (spiral around the bot's current position).
MAX_ASTEROID_CHASE_PX: float = 2000.0
# Escape hatch for the cap: after the FSM has been continuously
# in S_SEARCH for this long, drop the chase cap and pursue the
# nearest visible asteroid regardless of distance.
SEARCH_GIVEUP_S: float = 60.0
# Spiral angular advance per tick (radians) — 4° / 0.07 rad gives
# tangential target speeds the ship can actually rotate to follow
# at typical search-spiral radii.
SPIRAL_ANGLE_ADVANCE_RAD: float = math.radians(4.0)
ASTEROID_BLACKLIST_TTL_S = _bl.ASTEROID_BLACKLIST_TTL_S
ASTEROID_BLACKLIST_RADIUS_PX = _bl.ASTEROID_BLACKLIST_RADIUS_PX

# ── Craft phase tuning ──────────────────────────────────────────────────
# Iron threshold (in station inventory) the bot must accumulate
# before entering the module-craft phase.  Modules cost a total of
# 700 iron (50+75+100+125+150+200) — the 2000 cushion gives the bot
# headroom for any extra building work and for the consumable phase
# that follows.
CRAFT_PHASE_IRON_THRESHOLD: int = 2000
# Lower threshold for the consumable phase.  The original 2000 gate
# was the same for both phases, but by the time module crafting
# completes (consuming 700 iron) the buffer has dropped below 2000 —
# and deposits between modules don't always recover it.  The bot
# then sat in a Mine→Search→Mine loop forever, waiting for the
# station iron to climb back to 2000 before consumables could start.
# 500 iron is plenty: 5 repair-pack batches cost 500 total
# (100/each), 5 shield-recharge batches cost 1000, and incremental
# mining covers the rest while the crafter ticks.  Diagnosed via
# 2026-05-03 telemetry (10-minute session, post-install station
# iron stalled at 1335 with cp=False).
CONSUMABLE_PHASE_IRON_THRESHOLD: int = 500
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


# ── Stuck + potential-field tuning (re-exported from bot_autopilot_navigation) ──
STUCK_DETECT_WINDOW_S = _nav.STUCK_DETECT_WINDOW_S
STUCK_DETECT_DIST_PX = _nav.STUCK_DETECT_DIST_PX
STUCK_DETECT_ROTATION_DEG = _nav.STUCK_DETECT_ROTATION_DEG
STUCK_ESCAPE_MIN_DURATION_S = _nav.STUCK_ESCAPE_MIN_DURATION_S
STUCK_ESCAPE_CLEAR_MARGIN_PX = _nav.STUCK_ESCAPE_CLEAR_MARGIN_PX
STUCK_WORLD_MARGIN_PX = _nav.STUCK_WORLD_MARGIN_PX
STUCK_LOG_THROTTLE_S = _nav.STUCK_LOG_THROTTLE_S
BOUNDARY_REPULSION_RANGE_PX = _nav.BOUNDARY_REPULSION_RANGE_PX
BOUNDARY_REPULSION_GAIN = _nav.BOUNDARY_REPULSION_GAIN
BUILDING_REPULSION_RANGE_PX = _nav.BUILDING_REPULSION_RANGE_PX
BUILDING_REPULSION_GAIN = _nav.BUILDING_REPULSION_GAIN
BUILDING_REPULSION_TYPE_MULTIPLIER = _nav.BUILDING_REPULSION_TYPE_MULTIPLIER
REPULSION_TARGET_SUPPRESS_PX = _nav.REPULSION_TARGET_SUPPRESS_PX
CLUSTER_DETOUR_MARGIN_PX = _nav.CLUSTER_DETOUR_MARGIN_PX
CLUSTER_DETOUR_TARGET_INSIDE_PX = _nav.CLUSTER_DETOUR_TARGET_INSIDE_PX
CLUSTER_MIN_BUILDINGS = _nav.CLUSTER_MIN_BUILDINGS


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
    # Sticky commitment flag — once SEARCH_GIVEUP_S elapses and
    # MINE fires for a far asteroid, the chase cap stays dropped
    # until the bot actually reaches a chase-range asteroid (or
    # all visible asteroids are exhausted).  Without this the
    # FSM bounces SEARCH ↔ MINE every MIN_DWELL_S because the
    # giveup condition only holds while ``cur == S_SEARCH``.
    chase_committed: bool = False
    # Rolling timestamps of recent S_HUNT stuck_detected events
    # (capped at HUNT_STUCK_THRESHOLD entries).  When the list
    # fills inside HUNT_STUCK_WINDOW_S, ``hunt_giveup_until``
    # latches the FSM out of HUNT for HUNT_GIVEUP_S seconds.
    hunt_stuck_times: list = field(default_factory=list)
    hunt_giveup_until: float = 0.0
    # Per-anchor hit counts for the long-term hunt-stuck tracker.
    # Maps (rounded_x, rounded_y) -> [hit_count, expiry_ts].
    # Catches the slow repeated-pin pattern (stuck events spread
    # over minutes at the same cluster anchor) that the acute
    # 10 s window above won't see.
    hunt_anchor_hits: dict = field(default_factory=dict)
    # Last shields value seen during S_REGEN — the escape valve
    # in _choose_next_state compares the current value against this
    # to detect "shields not recovering" (i.e., still being shot)
    # and lets ENGAGE preempt REGEN to break the deadlock.  Reset
    # to 0 on REGEN exit so the trend check restarts cleanly on
    # next entry.
    last_regen_shields: int = 0

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
        self.chase_committed = False
        self.hunt_stuck_times.clear()
        self.hunt_giveup_until = 0.0
        self.hunt_anchor_hits.clear()
        self.last_regen_shields = 0


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


# ── Blacklist wrappers (implementation in bot_autopilot_blacklist) ──────
#
# Bind the autopilot's per-process ``_state`` blacklist dicts +
# ``_get_now`` clock so call sites + tests can keep using the
# ``_pickup_is_blacklisted(pu)`` / ``_blacklist_pickup(pu)`` shape.

def _pickup_is_blacklisted(pu: dict) -> bool:
    return _bl.pickup_is_blacklisted(pu, _state.pickup_blacklist, _get_now)


def _blacklist_pickup(pu: dict) -> None:
    _bl.blacklist_pickup(pu, _state.pickup_blacklist, _get_now)


def _nearest_pickup(state: dict, px: float, py: float
                    ) -> tuple[dict | None, float]:
    """Return (nearest_pickup, distance) skipping blacklisted pickups
    AND those sitting within ``PICKUP_EDGE_SKIP_PX`` of a world
    boundary.

    Edge filter rationale: pickups spawn wherever an alien dies —
    sometimes right against the world wall.  GATHER chasing one
    pins the bot against the boundary the same way edge-adjacent
    asteroids do.  Mirrors the fix added for ``_nearest_asteroid``
    in PR #25.  Pre-filtering at selection skips the stuck event
    entirely; the existing blacklist + 60 s TTL catches any pickup
    we DO try to reach that turns out to be unreachable.
    """
    candidate, d = _bl.nearest_pickup(
        state, px, py, _state.pickup_blacklist, _get_now)
    if candidate is None:
        return (None, d)
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    cx = float(candidate.get("x", 0.0))
    cy = float(candidate.get("y", 0.0))
    margin = PICKUP_EDGE_SKIP_PX
    if (cx >= margin and cx <= world_w - margin
            and cy >= margin and cy <= world_h - margin):
        return (candidate, d)
    # Edge-adjacent.  Inline-filter the pickup lists for an interior
    # alternative; fall back to the edge candidate if every pickup
    # is edge-adjacent (rare — let the blacklist handle it).
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
        if _bl.pickup_is_blacklisted(
                pu, _state.pickup_blacklist, _get_now):
            continue
        d2 = math.hypot(bx - px, by - py)
        if d2 < best_d:
            best, best_d = pu, d2
    if best is None:
        return (candidate, d)
    return (best, best_d)


def _asteroid_is_blacklisted(ast: dict) -> bool:
    return _bl.asteroid_is_blacklisted(
        ast, _state.asteroid_blacklist, _get_now)


def _blacklist_asteroid(ast: dict) -> None:
    _bl.blacklist_asteroid(ast, _state.asteroid_blacklist, _get_now)


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
        state, px, py, _state.asteroid_blacklist, _get_now)
    if candidate is None:
        return (None, d)
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    ax = float(candidate.get("x", 0.0))
    ay = float(candidate.get("y", 0.0))
    margin = ASTEROID_EDGE_SKIP_PX
    if (ax >= margin and ax <= world_w - margin
            and ay >= margin and ay <= world_h - margin):
        return (candidate, d)
    # Edge-adjacent.  Try the next-nearest by temporarily
    # blacklisting (with a short TTL) and re-querying.  Cheaper
    # to inline-filter the asteroids list once.
    asteroids = state.get("asteroids", []) or []
    best = None
    best_d = float("inf")
    for ast in asteroids:
        bx = float(ast.get("x", 0.0))
        by = float(ast.get("y", 0.0))
        if (bx < margin or bx > world_w - margin
                or by < margin or by > world_h - margin):
            continue
        if _bl.asteroid_is_blacklisted(
                ast, _state.asteroid_blacklist, _get_now):
            continue
        d2 = math.hypot(bx - px, by - py)
        if d2 < best_d:
            best, best_d = ast, d2
    if best is None:
        # Fall back to the original (edge-adjacent) candidate.  No
        # interior asteroid is reachable; let the existing
        # blacklist + stuck-detect cycle handle it as before.
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
    margin = ALIEN_EDGE_SKIP_PX
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
    return nearest(aliens, px, py)


# ── Stuck detect + escape wrappers (impl in bot_autopilot_navigation) ───

def _record_position(p: dict) -> None:
    _nav.record_position(p, _stuck_state, _get_now)


def _detect_stuck() -> bool:
    return _nav.detect_stuck(_stuck_state)


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
    _do_goto(state, p, tx, ty, stop_radius=300.0)


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
    #
    #    REGEN escape valve (added 2026-05-04): the original "always
    #    return REGEN while shields < REGEN_EXIT_PCT" rule deadlocks
    #    when the bot starts already low on shields with nearby
    #    aliens still firing — the bot sits idle, takes damage, can
    #    never reach the exit threshold, and dies.  Telemetry caught
    #    this clearly: 78 s session, 23 stuck_detected events all in
    #    REGEN with shields=0, 0 iron collected.
    #    Fix: if a threat is within ENGAGE_ENTER_PX AND shields are
    #    NOT recovering between ticks, fall through and let ENGAGE
    #    (or other priorities) take over — better to fight back at
    #    low HP than die idling.
    sh = int(p.get("shields", 0))
    sh_max = max(1, int(p.get("max_shields", 1)))
    pct = sh / sh_max
    aliens = state.get("aliens") or []
    threat, td = nearest(aliens, px, py)
    if cur == S_REGEN:
        if pct < REGEN_EXIT_PCT:
            shields_recovering = (sh > _state.last_regen_shields)
            threatened = (threat is not None
                          and td < ENGAGE_ENTER_PX)
            if threatened and not shields_recovering:
                # Escape valve — let priority cascade pick ENGAGE
                # (or whatever fits) instead of sitting in REGEN
                # forever.  Don't update last_regen_shields here so
                # if we re-enter REGEN later the trend check starts
                # fresh.
                pass
            else:
                _state.last_regen_shields = sh
                return S_REGEN
        else:
            # Shields fully recovered — leave REGEN cleanly.
            _state.last_regen_shields = 0
    else:
        if pct < REGEN_ENTER_PCT:
            # Entry-side mirror of the escape valve: don't enter
            # REGEN if a close threat is already engaging us.  The
            # escape valve in the cur==S_REGEN branch above would
            # immediately exit on the very next tick anyway, so
            # entering and exiting in a 0.1 s loop just burns FSM
            # cycles + telemetry without doing useful work.
            #
            # Telemetry from the previous session caught the
            # pathology: 111 REGEN <-> ENGAGE transitions in a
            # single combat encounter, median dwell 0.09 s (one
            # tick — both states bypass MIN_DWELL as defensive
            # interrupts).  Plus 14 stuck_detected misfires in the
            # tiny REGEN visits since REGEN action is _do_idle().
            #
            # Better: stay in ENGAGE for the duration of combat,
            # let combat assist + character bonuses keep firing,
            # transition to REGEN only after disengaging.
            threatened = (threat is not None
                          and td < ENGAGE_ENTER_PX)
            if threatened:
                pass  # stay in current state; ENGAGE/etc preempts
            else:
                # Entering REGEN — initialize the trend baseline.
                _state.last_regen_shields = sh
                return S_REGEN

    # 2. ENGAGE — alien within band.  Preempts the rest.
    # ``threat, td`` already loaded above for the REGEN escape
    # valve so we don't re-walk the alien list here.
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
    #    can't actually reach.  Also cap chase distance: an
    #    asteroid farther than MAX_ASTEROID_CHASE_PX is treated
    #    as out-of-reach so MINE falls through to SEARCH (spiral
    #    around current position) instead of long obstacle-laden
    #    trips across the world.
    #
    #    Escape hatch: if SEARCH has been the active state for
    #    SEARCH_GIVEUP_S, drop the cap and commit to whatever's
    #    nearest.  A long round trip is better than spiralling
    #    indefinitely in a region with no in-range asteroids.
    #    The commitment is STICKY (``_state.chase_committed``):
    #    once we decide to chase a far target, the cap stays
    #    dropped until the bot reaches chase range — otherwise
    #    the FSM bounces SEARCH ↔ MINE every MIN_DWELL_S
    #    because ``long_search`` only holds while ``cur == S_SEARCH``.
    nearest_ast, ast_d = _nearest_asteroid(state, px, py)
    if nearest_ast is not None:
        in_chase_range = ast_d < MAX_ASTEROID_CHASE_PX
        if in_chase_range:
            # Reached (or approached) a chase-range asteroid —
            # clear any prior commitment so future SEARCH
            # episodes get the normal cap-protected behaviour.
            _state.chase_committed = False
            return S_MINE
        # Out of chase range.  Either we're already committed
        # to a far chase, or we've been searching long enough
        # to commit now.
        search_entered = _fsm.get("entered_at")
        long_search = (
            cur == S_SEARCH
            and search_entered is not None
            and (now - search_entered) >= SEARCH_GIVEUP_S
        )
        if _state.chase_committed or long_search:
            _state.chase_committed = True
            return S_MINE
    else:
        # No visible asteroid (everything blacklisted, or none
        # in /state) — clear the commitment so the next time an
        # asteroid appears we start fresh.
        _state.chase_committed = False

    # 7. HUNT — no asteroid available but an alien is in HUNT_RANGE_PX.
    #    The bot needs resources (iron drops on alien kills) and
    #    sitting in SEARCH circling empty space wastes time.
    #    Triggered only when ENGAGE didn't fire (alien out of the
    #    800 px engage band) AND no asteroid is reachable.  Action
    #    handler reuses _act_engage so the close-and-fight behaviour
    #    is identical — only the dispatch differs (HUNT proactively,
    #    ENGAGE defensively).
    #
    #    Use the wider IDLE_HUNT_RANGE_PX gate when CURRENTLY in
    #    either S_IDLE_AT_BASE (bot parked at base, healed, adjacent
    #    to crafter — no reason to be picky) OR S_HUNT (already
    #    committed to a chase — finish it instead of bouncing back
    #    to idle).  The S_HUNT case is the symmetric-exit half of
    #    the hysteresis: without it, an alien sitting between
    #    HUNT_RANGE_PX (3000) and IDLE_HUNT_RANGE_PX (9000) creates
    #    a thrash band where IDLE keeps re-entering HUNT and HUNT
    #    keeps falling out — the 2026-05-04-evening telemetry
    #    captured 52 IDLE↔HUNT bounces in 5.9 minutes (one every
    #    7 s, 22/23 dwells right at the MIN_DWELL_S floor) before
    #    this fix.  Other states (MINE / SEARCH / GATHER) still
    #    use the tight 3000 px gate so they only divert to a chase
    #    when the alien is genuinely close.
    hunt_gate = (IDLE_HUNT_RANGE_PX
                 if cur in (S_IDLE_AT_BASE, S_HUNT)
                 else HUNT_RANGE_PX)
    # Use the edge-filtered selector for HUNT so we don't commit
    # to chasing an alien parked against the world boundary; that
    # was the dominant failure mode in the 2026-05-06 telemetry
    # (190 s wall-pin at px=48 with no stuck_detected firing).
    # ENGAGE / REGEN above keep using the unfiltered ``threat``
    # because defensive responses must react to any attacker
    # regardless of position.
    hunt_target, hunt_td = _nearest_huntable_alien(
        state, px, py, currently_hunting=(cur == S_HUNT))
    # Building-cluster pin escape (2026-05-06 follow-up #2): if we're
    # already in S_HUNT and the bot has wandered INSIDE the home-
    # station building repulsion field, refuse to re-fire HUNT.
    # Symmetric to the wall-pin escape but against buildings instead
    # of world edges: bot drove into the cluster chasing an alien,
    # buildings are blocking forward motion, but the FSM keeps
    # picking HUNT every tick because the alien target is interior
    # (not edge-adjacent) so the wall-pin escape doesn't engage.
    # Telemetry caught a 55 s pin at px≈220, hsd≈230 inside the
    # cluster — the alien was chased through the field, the bot
    # oscillated 10–20 px per 5 s tick, and rotation defeated the
    # position-history stuck detector after the initial hit.
    # Falling through to IDLE_AT_BASE pulls the bot to the 600 px
    # outer ring (clear of all buildings) on the next tick; HUNT can
    # then re-fire from open space and engage cleanly.
    #
    # Delay (2026-05-06 follow-up #3): require HUNT to have been
    # active for >= HUNT_CLUSTER_PIN_DELAY_S before the guard fires.
    # Without this, the guard tripped on the very first re-eval tick
    # (dwell ~ MIN_DWELL_S = 1 s) which broke fresh HUNT entries
    # from cluster-interior idle parking positions: 39 fast IDLE↔HUNT
    # pairs in the follow-up telemetry.  The delay gives the bot
    # 3 s of HUNT travel to thread its way out of the perimeter
    # before the guard activates; the 55 s pin from #37 is still
    # caught well within the original symptom window.
    hunt_entered = _fsm.get("entered_at")
    hunt_time = (now - hunt_entered
                 if cur == S_HUNT and hunt_entered is not None
                 else 0.0)
    # Wall exemption (2026-05-06 follow-up #5): when the bot is
    # inside the world-edge margin, the cluster guard is the WRONG
    # tool — the bot isn't stuck in the cluster centre, it's wall-
    # pinned with the cluster on the inboard side, and the cluster
    # is the *only path* to interior aliens.  Pre-fix telemetry
    # showed the guard firing every 13 s in this scenario (3 s HUNT
    # + 10 s lockout), with the user complaint "bot stays idle even
    # though enemies are present on the minimap; only moves when an
    # asteroid respawns".  Letting HUNT continue here returns the
    # geometry-driven slow-but-steady chase the user expects.
    #
    # PR #36's wall-pin escape still owns the wall+edge-aliens case
    # (it returns None when every alien is edge-adjacent, which
    # arms PR #39's lockout).  The cluster guard now owns only the
    # interior cluster pin it was originally designed for: bot
    # genuinely stuck deep in the station, far from any wall.
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    bot_at_wall = (px < ALIEN_EDGE_SKIP_PX
                   or px > world_w - ALIEN_EDGE_SKIP_PX
                   or py < ALIEN_EDGE_SKIP_PX
                   or py > world_h - ALIEN_EDGE_SKIP_PX)
    if (cur == S_HUNT and hunt_target is not None
            and hunt_time >= HUNT_CLUSTER_PIN_DELAY_S
            and not _ship_clear_of_buildings(p, state)
            and not bot_at_wall):
        hunt_target = None
    # Pin-escape lockout (2026-05-06 follow-up #4): if either pin-
    # escape path zeroed hunt_target while aliens were still visible,
    # block HUNT re-entry from IDLE_AT_BASE for HUNT_PIN_GIVEUP_S so
    # the next tick doesn't immediately re-fire (currently_hunting
    # would be False from IDLE, taking the helper's fallback path).
    # Without this lockout the bot oscillated IDLE↔HUNT 107 times in
    # 3 minutes during a wall-pin (median dwell 1.01 s in both
    # states).  hunt_target is None here only when aliens are
    # visible AND we were in HUNT (no-aliens case has empty list,
    # legitimate alien-out-of-range case has non-None target with
    # hunt_td >= hunt_gate); both gates fail-closed for safety.
    if (cur == S_HUNT and hunt_target is None
            and (state.get("aliens") or [])):
        _state.hunt_giveup_until = max(
            _state.hunt_giveup_until, now + HUNT_PIN_GIVEUP_S)
    if (hunt_target is not None and hunt_td < hunt_gate
            and now >= _state.hunt_giveup_until):
        return S_HUNT

    # 8. IDLE_AT_BASE — nothing actionable is visible.  When a Home
    #    Station exists, head there and wait for respawns rather
    #    than spiralling forever in empty space (observed:
    #    2026-05-03 session, 47 s of SEARCH with 0 aliens visible
    #    + 1 distant blacklisted asteroid, bot oscillated between
    #    two positions).  When no Home Station exists yet
    #    (early-game), fall back to the original SEARCH spiral —
    #    the bot still needs to roam to find resources for the
    #    starter base.
    if hs is not None:
        return S_IDLE_AT_BASE
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
        # Re-anchor the SEARCH spiral at the bot's CURRENT
        # (clear-space) position.  Prior code re-anchored at
        # world centre during the on-stuck handler — but the
        # home station is typically built near world centre, so
        # the next SEARCH cycle would target right back through
        # the building cluster that caused the stuck (observed:
        # 13 consecutive stuck events in 72 s, all in S_SEARCH,
        # all oscillating between two positions 60-130 px from
        # the HS).  Anchoring at the post-escape position means
        # the new spiral starts in clear space.
        _spiral_state["anchor"] = (
            float(p.get("x", 0.0)), float(p.get("y", 0.0)))
        _spiral_state["angle"] = 0.0
        _spiral_state["radius"] = 100.0
    # Skip stuck-detect when in S_SEARCH, S_IDLE_AT_BASE, or S_REGEN.
    #
    # S_SEARCH: the spiral's brake-coast motion at small radii
    # looks indistinguishable from "pinned" to the position +
    # rotation watchdog (consecutive spiral targets at r=100 are
    # only ~7 px apart in tangent — well inside the 25 px detect
    # threshold).
    #
    # S_IDLE_AT_BASE: the bot is intentionally parked + drifting;
    # the watchdog has no useful work to do.  At the original 300 px
    # radius the watchdog fired 12 times in 5 minutes when the bot
    # was inside a tight building cluster.  Even with the radius
    # widened to 600 px, drift / micro-collisions inside the idle
    # zone shouldn't trigger a 1.5 s escape burst — the bot would
    # just navigate back to the same idle target on the next tick.
    #
    # S_REGEN: action is ``_do_idle()`` — bot intentionally parks
    # and waits for shields to recover.  Zero movement is the
    # whole point, so the watchdog fires every cycle.  2026-05-05
    # telemetry caught the pathology cleanly: a single 40 s REGEN
    # run produced 8 stuck_detected events; each escape burst
    # shoved the bot ~700 px (4 successive bursts moved it 2052 px
    # north along x≈3050) before pinning it against an edge for
    # the final 12 s.  Shields still recovered (54 → 88) but the
    # ship ended up far from where REGEN started.
    #
    # GATHER / MINE / DEPOSIT / CRAFT / INSTALL / HUNT still get
    # stuck-detect protection — those states call _do_goto with
    # brake_on_arrival=True against single chase targets, so a
    # real pin cleanly fires the watchdog.
    if (_detect_stuck()
            and _fsm["state"] not in (S_SEARCH, S_IDLE_AT_BASE, S_REGEN)):
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
        elif _fsm["state"] == S_HUNT:
            # Hunt-stuck giveup (acute): track recent stuck events,
            # and if the threshold trips inside the window, latch
            # HUNT off for HUNT_GIVEUP_S so the FSM falls through
            # to IDLE_AT_BASE and re-routes from clear space.
            times = _state.hunt_stuck_times
            cutoff = now - HUNT_STUCK_WINDOW_S
            _state.hunt_stuck_times = [t for t in times if t >= cutoff]
            _state.hunt_stuck_times.append(now)
            if len(_state.hunt_stuck_times) >= HUNT_STUCK_THRESHOLD:
                _state.hunt_giveup_until = now + HUNT_GIVEUP_S
                _state.hunt_stuck_times.clear()
                print(f"[autopilot] HUNT-GIVEUP: "
                      f"{HUNT_STUCK_THRESHOLD} stuck events in "
                      f"{HUNT_STUCK_WINDOW_S:.0f}s — suppressing "
                      f"S_HUNT for {HUNT_GIVEUP_S:.0f}s")
            # Hunt-stuck giveup (long-term per-anchor): catches the
            # slow repeated-pin pattern (3 stucks at the same cluster
            # anchor spread over 250 s — never trips the acute window
            # but burns sessions on repeated pins).  Anchor is
            # rounded to a HUNT_ANCHOR_GRID_PX grid; once it
            # accumulates HUNT_ANCHOR_MAX_HITS within HUNT_ANCHOR_TTL_S
            # the long-giveup latches for HUNT_LONG_GIVEUP_S.
            anchor = (round(sx / HUNT_ANCHOR_GRID_PX) * HUNT_ANCHOR_GRID_PX,
                      round(sy / HUNT_ANCHOR_GRID_PX) * HUNT_ANCHOR_GRID_PX)
            # Evict expired anchors inline so the dict stays bounded.
            expired = [k for k, (_n, exp) in _state.hunt_anchor_hits.items()
                       if now >= exp]
            for k in expired:
                del _state.hunt_anchor_hits[k]
            entry = _state.hunt_anchor_hits.get(anchor)
            if entry is None:
                _state.hunt_anchor_hits[anchor] = [1, now + HUNT_ANCHOR_TTL_S]
            else:
                entry[0] += 1
                entry[1] = now + HUNT_ANCHOR_TTL_S
                if entry[0] >= HUNT_ANCHOR_MAX_HITS:
                    _state.hunt_giveup_until = max(
                        _state.hunt_giveup_until,
                        now + HUNT_LONG_GIVEUP_S)
                    del _state.hunt_anchor_hits[anchor]
                    print(f"[autopilot] HUNT-LONG-GIVEUP: anchor "
                          f"{anchor} hit {HUNT_ANCHOR_MAX_HITS}× — "
                          f"suppressing S_HUNT for "
                          f"{HUNT_LONG_GIVEUP_S:.0f}s")
        _telemetry_log("stuck_detected",
                       cause=("building"
                              if not _ship_clear_of_buildings(p, state)
                              else "edge"),
                       fsm_state=_fsm["state"],
                       blacklisted_pickup=blacklisted_pu,
                       blacklisted_asteroid=blacklisted_ast,
                       **_telemetry_snapshot_fields(state, p))
        # The spiral re-anchor moved to the escape-EXIT branch
        # (above).  Anchoring at world centre on stuck-detect
        # was the source of a regression: the home station is
        # typically built near world centre, so the next SEARCH
        # cycle would target right back through the building
        # cluster.  We now wait until the escape lands the ship
        # in clear space and anchor THERE.
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
            # Clear stale position history so the new state's first
            # tick doesn't inherit the old state's "no progress"
            # signature — see the dwell-or-preempt branch below.
            _stuck_state["history"] = []
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
            # Clear stale position history at every state boundary.
            # Without this, leaving an exempt state (S_SEARCH /
            # S_IDLE_AT_BASE) carries forward a window of near-zero
            # motion samples and stuck-detect false-fires on the
            # very first tick of the new (non-exempt) state.
            # 2026-05-04 telemetry caught this: a 42 s IDLE_AT_BASE
            # park into HUNT logged stuck_detected one tick after
            # the transition with the bot in clear space.
            _stuck_state["history"] = []
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
    elif cur == S_HUNT:
        # Reuses ENGAGE's close-and-fight action; the FSM-level
        # distinction (HUNT vs ENGAGE) only matters for telemetry
        # and dispatch priority.
        _act_engage(state, p)
    elif cur == S_IDLE_AT_BASE:
        _act_idle_at_base(state, p)
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

    # Auto-flip the consumable-phase latch the moment the install
    # queue empties IF station iron is past the entry buffer.  This
    # latches the phase started so a later iron dip doesn't re-
    # gate.  Without the auto-flip the bot deadlocked when station
    # iron sat between CRAFT_IRON_COST (100) and
    # CONSUMABLE_PHASE_IRON_THRESHOLD (500): per-craft cost was
    # met but the entry gate held forever.
    if (not q.consumable_phase_started
            and iron >= CONSUMABLE_PHASE_IRON_THRESHOLD):
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
                and iron < CONSUMABLE_PHASE_IRON_THRESHOLD):
            return None
        if iron < CRAFT_IRON_COST:
            return None
        return "repair_pack"

    # ── Shield recharge phase ─────────────────────────────────────
    if q.shield_recharges_remaining > 0:
        if (not q.consumable_phase_started
                and iron < CONSUMABLE_PHASE_IRON_THRESHOLD):
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

    # Clamp the chase target inside the world rect so a chase
    # toward an alien sitting at / past a world edge doesn't pin
    # the bot against the boundary.  Combat assist (60 FPS aim +
    # fire) still hits the alien through the boundary.  2026-05-04
    # telemetry: 12 HUNT stucks within 200-700 px of the north
    # edge before this clamp.
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _clamp_to_world(
        threat["x"], threat["y"], zone)

    melee_committed = bool(
        (state.get("assist") or {}).get("melee_engaged", False))
    if melee_committed:
        # Committed melee rush: drive in to swing range.  Don't
        # call _ensure_weapon -- the in-process combat assist has
        # locked the Energy Blade and would just fight us at
        # 60 FPS vs our 10 Hz Tab presses.
        _do_goto(state, p, chase_x, chase_y,
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
    _do_goto(state, p, chase_x, chase_y, stop_radius=380.0)
    KeyState.hold("space", td < FIRE_RANGE_PX)


def _act_gather(state: dict, p: dict) -> None:
    """GATHER: head toward the nearest pickup, no fire.

    Chase target is clamped to the world rect via ``_clamp_to_world``
    so a pickup sitting past the safety margin doesn't pull the bot
    into the boundary repulsion field's local-minimum trap (the
    classical edge-resource oscillation: goto pulls toward the wall,
    boundary repulsion pushes back, leftover force is wall-parallel,
    bot drifts along the edge instead of toward the resource).  When
    the pickup is inside the margin the clamp is a no-op.  When it's
    past the margin the bot navigates to the boundary edge — if the
    pickup hasn't drifted into reach, stuck-detect + the pickup
    blacklist let the bot move on to the next pickup instead of
    grinding for tens of seconds.
    """
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    pickup, _pd = _nearest_pickup(state, px, py)
    if pickup is None:
        # Pickup vanished (probably collected); next tick re-routes.
        KeyState.hold("space", False)
        return
    KeyState.hold("space", False)
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _clamp_to_world(
        pickup["x"], pickup["y"], zone)
    _do_goto(state, p, chase_x, chase_y,
             stop_radius=PICKUP_STOP_RADIUS)


def _act_idle_at_base(state: dict, p: dict) -> None:
    """IDLE_AT_BASE: navigate to the *outer ring* of the idle zone
    (one ``IDLE_AT_BASE_RADIUS_PX`` from the Home Station, on the
    line from the player toward the station) and idle there.

    Why the outer ring instead of the station centre: 2026-05-04
    telemetry showed the bot drifting all the way to hs_dist 58 —
    deep inside the 11-building station cluster.  When an alien
    later spawned and HUNT fired, the bot couldn't escape the
    cluster (14 ``stuck_detected`` events, all anchored at the
    same cluster-interior position, zero combat).  Parking at the
    outer ring instead means HUNT can launch from clear space.
    """
    hs = _find_home_station(state)
    if hs is None:
        # Defensive: caller (_choose_next_state) only routes here
        # when an HS exists, but if it disappeared mid-tick fall
        # back to a clean idle so the FSM re-evaluates next tick.
        _do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hx = float(hs.get("x", 0.0))
    hy = float(hs.get("y", 0.0))
    KeyState.hold("space", False)  # never fire while idle
    # Vector from station to player — the outer-ring target is on
    # this ray at distance IDLE_AT_BASE_RADIUS_PX from the station.
    dx = px - hx
    dy = py - hy
    dist = math.hypot(dx, dy)
    if dist <= IDLE_AT_BASE_RADIUS_PX:
        # Already inside the idle zone — release everything and
        # drift.  Stuck-detect is exempt for IDLE_AT_BASE so a
        # nudge from a building's potential field won't trigger
        # an escape burst.
        _do_idle()
        return
    # Outside the idle ring — head to a point on the ring around HS
    # that's INSIDE the world rect.  Preferred direction is the
    # player→HS ray (so the bot parks on the side it's coming from);
    # if that point is past the world boundary (HS near a corner),
    # ``find_clear_ring_point`` sweeps the ring for an interior
    # alternative.  Caught from 2026-05-04 telemetry: HS in the
    # upper-right of the world produced 12 HUNT stucks at y≈5500-6200
    # because the projected outer-ring target sat at y≈6600.
    zone = state.get("zone") or {}
    target_x, target_y = _find_clear_ring_point(
        hx, hy, IDLE_AT_BASE_RADIUS_PX, zone, dx, dy)
    _do_goto(state, p, target_x, target_y, stop_radius=80.0)


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
    # stop_radius=40 px (down from 120) so consecutive spiral
    # targets — which can be only ~7 px apart in tangent at small
    # radii — aren't already "arrived" the moment the spiral
    # advances; brake_on_arrival=False so the bot coasts through
    # nearby targets instead of braking-then-recovering.  Together
    # these two changes eliminate the brake-coast pattern that
    # was triggering ~30 false-fire stuck-detect events per session.
    _do_goto(state, p, tx, ty, stop_radius=40.0,
             brake_on_arrival=False)
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
    # Advance the spiral incrementally each tick.  Angle advance
    # rate is tuned (SPIRAL_ANGLE_ADVANCE_RAD) so the tangential
    # target speed at typical orbit radii stays under what the
    # ship can actually rotate to follow — otherwise the bot
    # perpetually re-orients without thrusting and looks like
    # it's "rotating endlessly" in place.
    _spiral_state["angle"] = (a + SPIRAL_ANGLE_ADVANCE_RAD) % (2 * math.pi)
    _spiral_state["radius"] = min(r + 1.5, 3000.0)
    if _spiral_state["radius"] >= 3000.0:
        _spiral_reset()


# ── Potential field re-exports ──────────────────────────────────────────
# Implementation lives in bot_autopilot_navigation; re-exported here so
# tests and call sites that read ``ap._boundary_repulsion`` etc keep
# working without churn.

_boundary_repulsion = _nav.boundary_repulsion
_building_repulsion = _nav.building_repulsion
_steered_heading = _nav.steered_heading
_cluster_centroid_and_radius = _nav.cluster_centroid_and_radius
_cluster_detour_waypoint = _nav.cluster_detour_waypoint
_clamp_to_world = _nav.clamp_to_world
_find_clear_ring_point = _nav.find_clear_ring_point


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

    Cluster detour: if the straight-line path to (tx, ty) crosses
    the placed-building cluster, the immediate goto target is
    redirected to a tangent waypoint on the cluster boundary.  Once
    the bot reaches the waypoint the next tick re-evaluates and
    typically routes straight to the original target from the new
    (cluster-clear) angle.  Suppressed when the destination IS
    inside the cluster (deposit / craft / install) so docking
    actions complete normally.
    """
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    final_target = (tx, ty)  # remember for repulsion suppression
    waypoint = _cluster_detour_waypoint(state, px, py, tx, ty)
    if waypoint is not None:
        tx, ty = waypoint
    dx = tx - px
    dy = ty - py
    dist = math.hypot(dx, dy)
    if dist < stop_radius:
        # Arrived — release thrust + rotation.  Engage brake only
        # if the caller asked for it; spiral search wants the bot
        # to coast, not brake.
        KeyState.hold("w", False)
        KeyState.hold("a", False)
        KeyState.hold("d", False)
        KeyState.hold("s", brake_on_arrival)
        return
    KeyState.hold("s", False)
    target = _steered_heading(state, p, dx, dy, dist,
                              target=final_target)
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
    target = _steered_heading(state, p, dx, dy, dist, target=(tx, ty))
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
    # Clamp the chase target to inside the world rect so an
    # edge-adjacent asteroid doesn't pull the bot into the
    # boundary repulsion local minimum.  Mining Beam range is
    # 400 px vs the 200 px world margin — plenty of reach to
    # mine from inside the safety zone.  ``dist`` (used for the
    # fire gate) is NOT clamped — that's still the real distance
    # to the asteroid so the fire trigger respects the actual
    # weapon range.
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _clamp_to_world(
        target["x"], target["y"], zone)
    if _state.mining_weapon_pick == "Energy Pickaxe":
        # Pickaxe is melee — hold optimal swing distance instead
        # of closing all the way and ramming the asteroid.  After
        # the asteroid is destroyed the FSM transitions to GATHER,
        # which uses _do_goto to close on the iron pickup.
        _do_hold_distance(state, p, chase_x, chase_y,
                          hold_radius=PICKAXE_HOLD_DISTANCE_PX)
        KeyState.hold("space", dist < PICKAXE_MINING_RANGE_PX)
    else:
        # Mining Beam — ranged, stand off and fire from afar.
        _do_goto(state, p, chase_x, chase_y, stop_radius=200.0)
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
    # Clamp chase target to the world rect (mirrors _act_engage and
    # the mine/gather actions) so an edge-adjacent alien doesn't
    # pull the bot into the boundary repulsion oscillation trap.
    # Combat assist's 60 FPS aim still hits through the boundary.
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _clamp_to_world(
        target["x"], target["y"], zone)
    _do_goto(state, p, chase_x, chase_y, stop_radius=300.0)
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
