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

# ── Boss fight tuning (Choices 2–4) ───────────────────────────────────────
#
# Constants for the station-anchor kite used by ``_act_engage_boss``.
# Reference: BOSS_CANNON_RANGE = 700, BOSS_SPREAD_RANGE = 600,
# BOSS_CHARGE_WINDUP = 2.0 s, BOSS_CHARGE_DURATION = 0.8 s,
# BOSS_CHARGE_SPEED = 600 px/s.  TURRET_RANGE = 400, TURRET_LASER_RANGE = 500.
#
# The bot holds at BOSS_KITE_RANGE_PX from the boss (just outside
# the cannon's max range) and inside BOSS_KITE_STATION_TETHER_PX of
# the Home Station, so friendly Defense Turrets + Missile Array can
# share DPS.  When the boss telegraphs a charge (Phase 2+), the bot
# strafes BOSS_DODGE_PERP_PX perpendicular to the boss-to-bot vector
# for one tick — the dash only travels 480 px in 0.8 s, so a small
# perpendicular offset clears it.
BOSS_KITE_RANGE_PX:           float = 750.0    # >= BOSS_CANNON_RANGE (700) + buffer
BOSS_KITE_OUTER_PX:           float = 900.0    # max kite distance — keep firing line
BOSS_FIRE_RANGE_PX:           float = 800.0    # max range to hold-fire Basic Laser
BOSS_KITE_STATION_TETHER_PX:  float = 600.0    # max distance from station while kiting
BOSS_DODGE_PERP_PX:           float = 250.0    # perpendicular strafe during charge windup
BOSS_PHASE3_PRESS_RANGE_PX:   float = 600.0    # Phase 3 (no shield regen): close in for DPS

# QWI (Quantum Wave Integrator) staging gate (Choice 1):
# the autopilot refuses to push the boss-trigger build until the
# station has at least this many friendly turrets/defenses and the
# ship has been upgraded to level 2.  The boss spawn is irreversible
# — no point pulling the trigger before the station can absorb the
# 30 s approach window.
QWI_STAGE_MIN_TURRETS:        int   = 2
QWI_STAGE_MIN_SHIP_LEVEL:     int   = 2

# Post-consumable boss-prep pipeline:
# After the 25 + 25 consumable craft batches finish, the bot
# (1) equips them into the ship's quick-use slots, (2) mines
# until station iron hits QWI_BUILD_IRON_TARGET so the QWI build
# (1000 iron + 2000 copper) is paid for, then (3) builds the
# QWI, which spawns the boss.  The HP / shield use thresholds
# below also drive an opportunistic consumable-use tick that
# runs every FSM update independent of the active state.
EQUIP_QUICK_USE_REPAIR_SLOT:  int   = 0      # quick-use slot for repair packs
EQUIP_QUICK_USE_SHIELD_SLOT:  int   = 1      # quick-use slot for shield recharges
QWI_BUILD_IRON_TARGET:        int   = 2000   # station-iron buffer before placing QWI
CONSUMABLE_USE_HP_PCT:        float = 0.50   # use repair pack at <= 50 % HP
CONSUMABLE_USE_SHIELD_PCT:    float = 0.50   # use shield recharge at <= 50 % shields
# Cooldown between auto-use POSTs so the bot doesn't spam the
# endpoint when a tick hits the threshold.  REPAIR_PACK_HEAL +
# SHIELD_RECHARGE_HEAL are 0.5 each so one use brings 50 % to
# 100 %; this floor just prevents back-to-back posts in the
# 100 ms gap before the heal lands.
CONSUMABLE_USE_COOLDOWN_S:    float = 1.0


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
# S_ENGAGE_BOSS: dedicated handler for the Double Star (and Nebula)
# boss fight.  Phase-aware kite anchored on the Home Station rather
# than chasing the boss to point-blank — see _act_engage_boss.  Top
# priority above S_ENGAGE so the boss takes precedence even when
# small aliens are in the engage band, and above MIN_DWELL_S for
# the same reason ENGAGE/REGEN are: a boss-charge windup needs an
# immediate strafe response, not a 1 s cooldown.
S_ENGAGE_BOSS = "engage_boss"
# Post-consumable boss-prep pipeline:
#   * S_EQUIP_CONSUMABLES — once the consumable craft phase has
#     finished its 25 + 25 batches, navigate to the Home Station
#     and POST /equip_consumables to withdraw them from station
#     inventory into the ship's quick-use slots.  One-shot.
#   * S_PRE_BOSS_MINE     — after consumables are equipped but
#     station iron is below QWI_BUILD_IRON_TARGET (2000 default),
#     mine until the iron buffer is staged.  Same action handler
#     as S_MINE; the FSM-level distinction tracks completion.
#   * S_BUILD_QWI         — station iron staged, QWI not yet
#     placed: navigate to the Home Station and POST /place_qwi,
#     which auto-spawns the Double Star boss.
# After the QWI is placed, the boss spawns and the existing
# S_ENGAGE_BOSS state takes over the fight automatically.
S_EQUIP_CONSUMABLES = "equip_consumables"
S_PRE_BOSS_MINE     = "pre_boss_mine"
S_BUILD_QWI         = "build_qwi"

ALL_STATES = (
    S_ENGAGE, S_GATHER, S_REGEN, S_MINE, S_SEARCH,
    S_BUILD, S_BUILD_SEEK, S_DEPOSIT, S_CRAFT, S_INSTALL,
    S_HUNT, S_IDLE_AT_BASE, S_ENGAGE_BOSS,
    S_EQUIP_CONSUMABLES, S_PRE_BOSS_MINE, S_BUILD_QWI,
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

# Wall+cluster trap detector (2026-05-06 follow-up #7): the
# position-history stuck detector in bot_autopilot_navigation gets
# defeated when the bot rotates to track aliens while wall-pinned
# (rotation gate prevents "stuck" even when net displacement is
# tiny).  This pair of constants drives a geometry-aware backstop:
# when trap conditions hold (bot inside STUCK_ESCAPE_CLEAR_MARGIN_PX
# of an edge AND building cluster centroid is on the inland side)
# AND the bot's position has not changed by WALL_PIN_TRAP_PROGRESS_PX
# over WALL_PIN_TRAP_WINDOW_S, the escape mechanism is force-armed
# so compute_escape_target's wall-tangent path takes over (PR #42).
#
# Caught from 2026-05-06 follow-up #7 telemetry: 65 s session, bot
# locked at px=48 hsd~250 throughout, 2 aliens visible, py
# oscillating 3942-3983 (~40 px range over 30 s = 1.3 px/s, well
# under the 25 px / 1.5 s rotation-gated stuck threshold), zero
# stuck_detected events, zero escape activations.
WALL_PIN_TRAP_WINDOW_S:    float = 5.0
WALL_PIN_TRAP_PROGRESS_PX: float = 50.0

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
    # Boss-prep pipeline flags.  Flip True after the matching
    # one-shot action confirms success (consumables equipped /
    # QWI placed).  Once both are True the FSM trusts that the
    # boss is incoming and falls through to the existing
    # S_ENGAGE_BOSS path.
    consumables_equipped: bool = False
    qwi_placed: bool = False
    # Monotonic timestamp of the last successful POST /use_quick_use
    # so the auto-use tick doesn't spam the endpoint between the
    # POST and the heal landing.
    last_consumable_use_at: float = 0.0
    # Wall+cluster trap detector (PR #44).  The position-history
    # stuck detector in bot_autopilot_navigation is defeated when
    # the bot rotates to track aliens while wall-pinned (rotation
    # gate >30° prevents the "stuck" classification even when net
    # displacement is well under 25 px).  This pair of fields is a
    # geometry-aware backstop: when the bot sits in the wall+cluster
    # trap geometry (wall_pinned + cluster centroid blocking the
    # inland path) AND has not moved more than
    # WALL_PIN_TRAP_PROGRESS_PX over WALL_PIN_TRAP_WINDOW_S, force-
    # arm the existing escape mechanism so compute_escape_target's
    # wall-tangent path (PR #42) takes over.
    wall_pin_anchor: tuple = (0.0, 0.0)
    wall_pin_anchor_at: float = 0.0
    # Heal-active latches (PR #45 follow-up).  Once HP / shields
    # drop past CONSUMABLE_USE_*_PCT, the matching latch arms and
    # stays armed until the bar refills to 100 %.  Without these,
    # one 50 %-heal use leaves the bot at e.g. 80 % HP if HP
    # dropped to 30 % between ticks — above the 50 % re-trigger
    # threshold, so no second use would fire.  The latch makes the
    # auto-use loop keep firing on each cooldown tick until the
    # bar is fully filled, matching the user spec ("use until 100 %").
    heal_hp_active: bool = False
    heal_shield_active: bool = False

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
        self.consumables_equipped = False
        self.qwi_placed = False
        self.last_consumable_use_at = 0.0
        self.wall_pin_anchor = (0.0, 0.0)
        self.wall_pin_anchor_at = 0.0
        self.heal_hp_active = False
        self.heal_shield_active = False


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


# ── Weapon cycling ────────────────────────────────────────────────────────
# ``_WEAPON_ORDER`` lives here because tests + tuning constants on
# this module need to read it; the actual cycle logic
# (``_ensure_weapon`` + ``_last_cycle_t``) lives in
# ``bot_autopilot_movement``.
_WEAPON_ORDER = (
    "Basic Laser", "Mining Beam", "Melee", "Energy Pickaxe")


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


# ── Helper-module re-exports ────────────────────────────────────────────
#
# After the 2026-05-07 split, the action / movement / targeting /
# HTTP helpers live in dedicated sibling modules.  Re-export each
# moved symbol back into ``bot_autopilot``'s namespace so existing
# test imports (``bot_autopilot._post_use_quick_use``,
# ``bot_autopilot._act_engage_boss``, etc.) and runtime monkey-
# patching keep working unchanged.

from bot_autopilot_http import (
    fetch_state,
    _post_build_starter_base,
    _post_craft,
    _post_install_module,
    _post_deposit_to_station,
    _post_use_quick_use,
    _post_equip_consumables,
    _post_place_qwi,
    _ensure_game_focused,
)
from bot_autopilot_targeting import (
    _pickup_is_blacklisted, _blacklist_pickup, _nearest_pickup,
    _asteroid_is_blacklisted, _blacklist_asteroid, _nearest_asteroid,
    _nearest_huntable_alien, _record_position, _detect_stuck,
    _wall_pin_trap_active, _maybe_force_wall_pin_escape,
    _ship_clear_of_edges, _ship_clear_of_buildings, _do_escape_edge,
    _iron_total, _ship_has_blueprint, _find_home_station,
    _find_basic_crafter, _any_crafter_busy, _station_items, _station_iron,
    _all_blueprints_deposited, _module_already_installed,
    _build_area_clear, _build_seek_direction,
    _consumable_phase_finished, _consumables_in_station_inv,
    _qwi_already_built, _qwi_ready_to_build, _find_quick_use_slot,
    _next_craft_target, _next_install_target,
)
from bot_autopilot_movement import (
    _do_idle, _do_goto, _do_hold_distance, _do_spiral_search,
    _do_mine_nearest, _do_attack_nearest, _do_engage_boss, _do_retreat,
    _do_cycle_weapon, _ensure_weapon, execute_intent,
)
from bot_autopilot_actions_station import (
    _act_build_seek, _act_deposit, _act_craft, _act_install, _act_build,
    _act_at_station, _act_equip_consumables, _act_build_qwi,
)
from bot_autopilot_actions_combat import (
    _act_engage, _act_engage_boss, _maybe_use_consumables,
    _act_gather, _act_idle_at_base,
)


# ── FSM core (orchestrator) ──────────────────────────────────────────────


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

    # 1.5  ENGAGE_BOSS — boss alive, station-anchor kite owns the fight.
    #      Above ENGAGE so a roaming small alien at 200 px doesn't
    #      pull the bot off the station perimeter into the boss's
    #      cannon range — boss DPS dwarfs anything a small alien
    #      brings, and combat assist still aims/fires at small
    #      aliens that walk into laser range during the kite.
    boss = state.get("boss")
    if boss is not None:
        return S_ENGAGE_BOSS

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

    # 5.6  Boss-prep pipeline — fires once the consumable craft
    #      queue is fully drained (25 repair packs + 25 shield
    #      recharges produced, all sitting in station inventory).
    #      Three sequential one-shot stages; each flips a sticky
    #      flag on success so the FSM never re-fires it:
    #
    #        a) S_EQUIP_CONSUMABLES — withdraw consumables from
    #           station inventory + bind them to ship quick-use
    #           slots.  Falls through immediately if no consumables
    #           remain in station inventory (already withdrawn).
    #        b) S_PRE_BOSS_MINE     — if station iron is below the
    #           QWI_BUILD_IRON_TARGET buffer (default 2000), keep
    #           mining.  Same action handler as S_MINE, but the
    #           FSM-level distinction tracks the explicit mining
    #           goal so telemetry can see it.
    #        c) S_BUILD_QWI         — iron staged + QWI not yet
    #           placed: navigate to the Home Station and POST
    #           /place_qwi.  The QWI auto-spawns the Double Star
    #           boss; from there S_ENGAGE_BOSS takes over.
    if hs is not None and _consumable_phase_finished():
        if not _state.consumables_equipped \
                and _consumables_in_station_inv(state):
            return S_EQUIP_CONSUMABLES
        if not _state.qwi_placed \
                and not _qwi_already_built(state):
            station_iron = _station_iron(state)
            if station_iron < QWI_BUILD_IRON_TARGET:
                # Still mining toward the iron buffer — fall back
                # to the normal MINE / SEARCH cascade below but
                # tag it as PRE_BOSS_MINE so telemetry knows we're
                # heading toward the QWI build.
                if _nearest_asteroid(state, px, py)[0] is not None:
                    return S_PRE_BOSS_MINE
            else:
                return S_BUILD_QWI

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

    # Auto-use consumables BEFORE the FSM dispatch so a low HP /
    # shield read this tick fires a heal regardless of which state
    # the bot is in (combat / mining / boss fight all benefit).
    # The HP threshold + cooldown live in
    # ``_maybe_use_consumables`` — see its docstring.
    _maybe_use_consumables(state, p)

    # Stuck watchdog: if the ship has been pinned against either
    # the world boundary OR a station building cluster, override
    # the FSM and head along the local repulsion vector toward
    # open space.  Has to run BEFORE the FSM dispatch so it
    # preempts whatever was driving the ship into the obstacle.
    _record_position(p)
    zone = state.get("zone") or {}
    # Wall+cluster trap force-escape (2026-05-06 follow-up #7): the
    # navigation-layer position-history stuck detector misses a
    # very specific failure mode — the bot rotating in place to
    # track an alien while wall-pinned, with cluster-inland
    # geometry.  Rotation defeats the rotation gate and the bot's
    # tiny tracking-jitter movements (~1 px/s in the telemetry)
    # don't cleanly trigger the displacement gate over a 1.5 s
    # window either.  Add a geometry-aware detector that bypasses
    # the rotation gate when trap conditions hold AND the bot's
    # position has barely changed.  Force-arming escape mode lets
    # compute_escape_target's wall-tangent path (PR #42) take over.
    _maybe_force_wall_pin_escape(state, p, now)
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
        if desired in (S_ENGAGE, S_REGEN, S_ENGAGE_BOSS,
                       S_EQUIP_CONSUMABLES, S_BUILD_QWI) or \
                dwell >= MIN_DWELL_S:
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

    if cur == S_ENGAGE_BOSS:
        _act_engage_boss(state, p)
    elif cur == S_ENGAGE:
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
    elif cur == S_EQUIP_CONSUMABLES:
        _act_equip_consumables(state, p)
    elif cur == S_PRE_BOSS_MINE:
        # Same close-and-mine behavior as S_MINE; the FSM-level
        # distinction tracks completion (mining toward the
        # QWI_BUILD_IRON_TARGET buffer instead of indefinitely).
        _do_mine_nearest(state, p)
    elif cur == S_BUILD_QWI:
        _act_build_qwi(state, p)
    else:  # S_SEARCH
        _do_spiral_search(state, p)


# ── Main loop ─────────────────────────────────────────────────────────────


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
