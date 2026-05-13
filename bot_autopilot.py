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

# When this file is launched directly (``python bot_autopilot.py``)
# the module loads as ``__main__``.  The helper modules below
# (``bot_autopilot_http``, ``_targeting``, ``_movement``, ``_actions_*``)
# all do ``import bot_autopilot as _ap`` at top level, which would
# trigger a *second* execution of this file under the canonical
# name and recurse back into the same import block — raising a
# circular-import error.  Registering ``__main__`` under the
# canonical name first makes the helper imports resolve to this
# in-progress module, breaking the cycle.
if __name__ == "__main__":
    sys.modules.setdefault("bot_autopilot", sys.modules["__main__"])

# ── Refactored helper modules (re-exported below) ──────────────────────
import bot_autopilot_telemetry as _tlm
import bot_autopilot_navigation as _nav
import bot_autopilot_blacklist as _bl
import bot_autopilot_astar as _astar

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

# Boss-orbit kite (2026-05-12, ninth telemetry pass).  Instead of a
# STATIC kite point on the boss->bot ray, the kite target leads the
# bot by ``BOSS_ORBIT_LEAD_RAD`` radians along the orbit circle.
# Two reasons:
#   1. Continuous tangential motion -- the bot stops looking
#      "stuck on the boss" (ninth-pass log: 17 s of fight 1 at
#      hs_dist ~415 with zero damage dealt).
#   2. Heading lines up tangent to the boss, so the broadside
#      module's perpendicular shots HIT the boss (90 deg offset
#      from heading = directly at the boss when orbiting).  Basic
#      laser still tracks via the combat-assist aim override.
# The lead is the angular offset of the "carrot" target ahead of
# the bot's current angle around the boss.  At 0.30 rad (~17 deg)
# and kite radius 750 px the lead arc is ~225 px -- always reachable
# in one tick at the bot's top speed but far enough to keep the
# bot chasing a moving target indefinitely.
BOSS_ORBIT_LEAD_RAD:          float = 0.30

# Boss LURE mode (2026-05-11, revised after second telemetry pass):
# The bot now PRE-EMPTIVELY activates lure whenever a boss is alive
# and a Home Station exists -- the previous shields-only trigger let
# the bot chase the boss into the world corner (hs_dist=3000+) and
# die before the threshold ever fired.  Once active, the lure stays
# latched until the boss dies; the prior shield-recovery exit caused
# yo-yo behavior (kite into cannon range -> lose shields -> lure
# back -> shields recover -> kite back into range).  Holds the bot
# at BOSS_LURE_TURRET_RADIUS_PX from the station (inside TURRET_RANGE
# = 400 + a small margin) so turrets land every shot but the bot
# isn't sitting on top of the HS where the boss's charge dash could
# one-shot the station.  The shields constant is retained for
# telemetry hysteresis (boss_lure_enter logs the entry shields) but
# no longer gates lure activation.
BOSS_LURE_SHIELDS_PCT:        float = 0.50
BOSS_LURE_TURRET_RADIUS_PX:   float = 350.0
BOSS_LURE_EXIT_SHIELDS_PCT:   float = 1.00    # only exit at full shields (kept for compat)

# Boss TURRET-ASSIST mode (2026-05-12, eighth telemetry pass):
# Replaces the "kite at 750 px from the boss" default with an
# "orbit the station's far perimeter and let turrets work" default
# whenever the boss is within ``BOSS_TURRET_ASSIST_ENTER_PX`` of
# the Home Station.  Sets:
#
#   * Eighth-pass telemetry: bot died 7 times in two engage_boss
#     sessions, doing 0 damage to the boss in fight 1 and only
#     respawn-cycling near the station in fight 2.  Final boss
#     death came from turrets while the bot kept respawning.
#     The bot's contribution was effectively zero -- its repeated
#     deaths cost it permanent modules (lost on first death,
#     never recovered before the boss died).
#   * The turret + missile umbrella around the Home Station soloes
#     bosses on station-approach attacks; the bot's value is
#     long-range basic-laser support that doesn't risk dying.
#
# Hysteresis: enter at ENTER_PX, exit at EXIT_PX (> ENTER_PX) so a
# boss hovering at the threshold doesn't flap the bot between
# orbit and kite.  When neither condition is met (boss far AND no
# active orbit latch), the legacy kite behavior runs so a boss
# that spawned far from the station gets drawn in.
BOSS_TURRET_ASSIST_ENTER_PX:  float = 1500.0
BOSS_TURRET_ASSIST_EXIT_PX:   float = 1800.0
# Radius from the home station the bot orbits at while turret-
# assisting.  Uses the existing lure radius so the bot sits inside
# both the laser turret range (500) and the missile array radius.
BOSS_TURRET_ASSIST_ORBIT_PX:  float = BOSS_LURE_TURRET_RADIUS_PX

# QWI (Quantum Wave Integrator) staging gate (Choice 1):
# the autopilot refuses to push the boss-trigger build until the
# station has at least this many friendly turrets/defenses and the
# ship has been upgraded to level 2.  The boss spawn is irreversible
# — no point pulling the trigger before the station can absorb the
# 30 s approach window.  The minimum is 6: the 2 starter Turret 2
# entries placed during ``build_starter_base`` (NE / SW corners)
# plus the 4 fortify turrets (N / S cardinals + NW / SE corners)
# placed by the S_FORTIFY phase before BUILD_QWI fires.
QWI_STAGE_MIN_TURRETS:        int   = 6
QWI_STAGE_MIN_SHIP_LEVEL:     int   = 2
# Iron cost of the fortify ring (4× Turret 2 at 75 iron each).
# Fortify won't fire until station inventory has at least this much
# iron staged; the gate keeps the ring affordable without dipping
# below the QWI's 1000-iron cost cushion.
FORTIFY_IRON_COST:            int   = 4 * 75

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
# Consumables are LAST RESORT (user spec 2026-05-11): the bot should
# rely on kite + lure + dodge to manage damage during a boss fight.
# Consumables only fire once those strategies have failed.  Lowered
# from 0.50 / 0.50 so kite and lure get the first try; the bot
# wastes a consumable charge less often on small dips that the
# station-tether kite + shield regen handle on their own.
CONSUMABLE_USE_HP_PCT:        float = 0.30   # use repair pack at <= 30 % HP
CONSUMABLE_USE_SHIELD_PCT:    float = 0.20   # use shield recharge at <= 20 % shields
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
# S_FORTIFY: fires after the consumable phase finishes and before
# the QWI is built.  Navigates to the Home Station and POSTs
# /fortify to drop 4 more Turret 2 entries (N / S cardinals +
# NW / SE corners) — bringing the cluster's defender count from
# the 2 starter turrets up to QWI_STAGE_MIN_TURRETS so the QWI
# build's ``_qwi_ready_to_build`` gate clears.  One-shot; latches
# ``_state.fortify_done`` on success or "ring already complete".
S_FORTIFY           = "fortify"
S_BUILD_QWI         = "build_qwi"
# S_RECOVER_LOOT (PR 2026-05-10): after the bot observes a dead->
# alive transition, navigate back to the recorded death position
# and idle until the dropped pickups (modules + consumables) vacuum
# into the ship via the existing auto-attract loop.  Cleared by the
# action handler once the loot is collected or
# DEATH_RECOVERY_TIMEOUT_S elapses.  Fires AFTER REGEN / ENGAGE /
# ENGAGE_BOSS / GATHER (defensive + opportunistic states take
# priority) but BEFORE the boss-prep pipeline (re-install is
# usually a prerequisite to re-engage).
S_RECOVER_LOOT      = "recover_loot"

ALL_STATES = (
    S_ENGAGE, S_GATHER, S_REGEN, S_MINE, S_SEARCH,
    S_BUILD, S_BUILD_SEEK, S_DEPOSIT, S_CRAFT, S_INSTALL,
    S_HUNT, S_IDLE_AT_BASE, S_ENGAGE_BOSS,
    S_EQUIP_CONSUMABLES, S_PRE_BOSS_MINE, S_FORTIFY, S_BUILD_QWI,
    S_RECOVER_LOOT,
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
#
# Threshold lowered from 3 to 2 after 2026-05-10 telemetry: a 52 s
# HUNT cycle at (4447, 3628) with the bot moving 17 px total over
# 22 s of stuck-detect activity.  Three stuck events fired at
# t+30s / t+39s / t+51s — the acute window held the giveup until
# the third stuck cleared the threshold, even though two stuck
# events already inside the 30 s window are themselves sustained
# evidence of a pin (one-off stucks during a clean kill chain
# don't repeat within 30 s).  With threshold=2 the giveup would
# have fired ~12 s sooner, ending the wasted HUNT at t+40s
# instead of t+52s.
HUNT_STUCK_WINDOW_S:   float = 30.0
HUNT_STUCK_THRESHOLD:  int   = 2
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
# Above this iron level the bot ALWAYS prefers DEPOSIT over MINE,
# regardless of whether asteroids are nearby.  Between
# DEPOSIT_IRON_THRESHOLD and DEPOSIT_IRON_FULL_THRESHOLD the bot
# favours mining a visible asteroid (within MAX_ASTEROID_CHASE_PX)
# over a deposit run, so it doesn't zigzag back to the station
# after every loot drop.  Caught from 2026-05-09 user report:
# "the ship returns to the station after destroying an enemy
# even when there [are] asteroids on the screen."  500 is ~5×
# the deposit threshold — enough headroom for several mining
# cycles, well below any sane ship-cargo cap (5×5 grid × 999
# stack = 24975), and matches the per-trip "this is enough to
# make the round trip worth it" feel.
DEPOSIT_IRON_FULL_THRESHOLD = 500
#
# Widened from 200 to 500 after 2026-05-10 telemetry: a 45-second
# session captured the bot wedged in S_DEPOSIT for 38.7 seconds
# (t+6.7s through t+45.4s) with ship_iron stuck at 110 and hs_dist
# oscillating between 361-393 px.  The bot couldn't close the
# final 161-193 px because the 7 non-suppressed buildings of the
# 11-building cluster (Power Receiver, Solar Array 2, Turret 2
# corners, fortify-ring turrets, Basic Crafter -- everything past
# the 100 px target-suppression gate from PR #83) stacked their
# repulsion fields and pushed the bot to a force-balance
# equilibrium outside the pre-fix 200 px DEPOSIT_RANGE.  Server-
# side ``deposit_ship_resources_to_station`` does NOT enforce a
# distance check (it just dumps inventory at the HS), so a wider
# range is safe -- the only effect is letting the bot fire the
# POST from its actual stop position outside the cluster rather
# than wedging inside the cluster forever.  500 covers the
# observed 393 px wedge with comfortable margin.
DEPOSIT_RANGE_PX       = 500.0
DEPOSIT_COOLDOWN_S     = 30.0
# Distance gate for non-urgent deposit runs.  When ship_iron is
# above DEPOSIT_IRON_THRESHOLD but below DEPOSIT_IRON_FULL_THRESHOLD
# (i.e. cargo isn't critical), suppress S_DEPOSIT if the bot is
# more than this far from the home station — a long round trip is
# very likely to be interrupted by combat (ENGAGE preempt aborts
# the deposit mid-flight, leaving the bot far from home with
# unchanged cargo state).  Caught from 2026-05-09 telemetry: bot
# at hs_dist=6340 px triggered DEPOSIT with iron=320, traveled
# 600 px, hit an alien, aborted; spent the next 2 minutes mining
# its way back instead of one efficient close-range deposit.
# Cargo-full deposits (iron ≥ DEPOSIT_IRON_FULL_THRESHOLD) bypass
# this gate — when cargo is critical, the trip is worth the risk.
# 5000 px chosen as a comfortable upper bound: large enough that
# typical mining runs near the station / mid-world remain
# eligible (HS at (3200,3200), bot anywhere in the same half-world
# is within ~4500 px), tight enough to suppress the worst-case
# corner-of-world commits (the telemetry case fired at 6340 px).
DEPOSIT_HS_MAX_DIST_PX = 5000.0
# Single radius for "clear and quiet" — no asteroids, aliens,
# pickups, or buildings within this distance of the player.
#
# Halved from 800 to 400 after 2026-05-10 telemetry: a 10-minute
# session collected 1045 iron without ever firing S_BUILD.  Once
# the iron gate cleared at t+495 s the bot entered BUILD_SEEK and
# wandered for 104 s without finding a clear spot before getting
# wall-pinned at (3084, 6219) (the south margin, py within 200 px
# of world_h=6400).  At the captured density of 75 asteroids in
# the 6400² world (density 1.83e-6/px²), the probability of any
# random position having an asteroid-free 800-px clear disk is
# exp(-density · π · 800²) ≈ 0.025 -- effectively unreachable.
# Lowering to 400 raises that probability to ~0.4, so the bot can
# find a buildable pocket in seconds instead of minutes-or-never.
# The starter base footprint extends ~300 px from the anchor
# (Solar Array 2 at +200, Turret 2 corners at +212 diagonal), so
# 400 px still keeps placed buildings comfortably clear of nearby
# asteroids on the outside of the ring.
BUILD_CLEAR_RADIUS_PX = 400.0
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
# Equivalent escape hatch for the parked-at-base case.  Tuned much
# tighter than ``SEARCH_GIVEUP_S`` (60 s) because at base the bot
# is genuinely doing nothing — there's no useful spiral search in
# progress, and the user-observable latency between "asteroids
# visible on the 't' menu" and "bot leaves to mine" should feel
# responsive rather than open-ended.  Caught from 2026-05-09 user
# report: "the bot only leaves [base] if it is being attacked or
# when an enemy spawns. it does not leave when there are asteroids
# available to be harvested."  Section 6 still fires MINE
# **immediately** for in-chase-range asteroids; this gate only
# kicks in for far targets that need the cap to be dropped.
IDLE_AT_BASE_GIVEUP_S: float = 10.0
# Stale-blacklist flush gate.  When the bot has been parked in
# S_IDLE_AT_BASE this long AND the world has visible asteroids
# (state.get("asteroids") non-empty) yet ``_nearest_asteroid``
# keeps returning None, every visible asteroid must be inside the
# active asteroid blacklist — almost always from silent
# ``_do_mine_nearest`` "unreachable" blacklisting that accumulates
# faster than the per-entry 60 s TTL evicts.  Wipe the asteroid +
# pickup blacklists so the next FSM tick re-evaluates from a clean
# slate.  Caught from 2026-05-09 telemetry: bot held S_IDLE_AT_BASE
# for 852 s (14 min) with ast=14 / aliens=13 visible, zero
# transitions — confirming the cascade fell through to section 8
# every tick because the targeting helpers all returned None.
IDLE_BLACKLIST_FLUSH_S: float = 60.0
# MINE-without-progress watchdog window.  The bot occasionally
# wedges in S_MINE for many minutes without ship_iron rising —
# every nominal target passes A* reachability and the position-
# history detector (PR #74's centroid override included) doesn't
# fire because the bot IS moving (just not making mining
# progress).  After this many seconds in S_MINE without any
# ship_iron increase, blacklist the current target so the next
# FSM tick selects a different asteroid.  Caught from 2026-05-09
# telemetry: 12-minute S_MINE session, 145/145 snapshots in
# MINE, ship_iron static at 85, asteroid_blacklist empty
# throughout — the bot orbited asteroids in a 185×295 px region
# without ever closing to mining range.
MINE_NO_PROGRESS_S: float = 60.0
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
#
# Widened from 200 to 500 after 2026-05-10 telemetry: 9 stuck_detected
# events in S_CRAFT in a single 39-minute session, all at hs_dist
# 280-470 px (cluster-pin band, same root cause as the DEPOSIT pin
# fixed in PR #86).  The Basic Crafter sits at HS+(120, 60), so the
# bot-to-crafter distance at the wedge is 270-460 px -- past the
# pre-fix 200 px gate, leaving the bot thrashing against building
# repulsion forever.  Server-side ``start_craft`` doesn't enforce a
# distance check (it just routes through the station inventory), so
# widening the client-side gate is safe.  500 covers the observed
# 470 px wedge with comfortable margin against future cluster
# variations.
CRAFT_INTERACT_RANGE_PX: float = 500.0
# Same idea for installing a module — the install flow operates on
# the station inventory + ship slots, no positional gate strictly
# required, but we still close to the Home Station so the action
# reads as deliberate (and so the bot is in safe territory when
# installing).
#
# Widened from 250 to 500 after 2026-05-10 telemetry caught the same
# cluster-pin pattern in CRAFT (see above); INSTALL shares the
# station-cluster geometry and the same target-suppress gaps, so the
# preventive widening keeps the install pipeline from wedging when
# the bot retries after a death.  Server-side ``install_module``
# doesn't enforce a distance check either.
INSTALL_INTERACT_RANGE_PX: float = 500.0
# Death-loot recovery (PR 2026-05-10): how close the bot must get to
# the recorded death position before the dropped iron / module
# pickups vacuum into the ship via the existing auto-attract loop.
# Iron pickups attract within 300 px (see ``IronPickup.update_pickup``),
# so 200 px stop radius keeps the bot inside attract range without
# pinning it on top of any stray asteroid that spawned at the spot.
DEATH_RECOVERY_STOP_RADIUS_PX: float = 200.0
# Hard ceiling on time spent in S_RECOVER_LOOT: if the bot can't
# reach the death site within this window (e.g. it died inside an
# inaccessible alien cluster, or the pickups despawned via
# WORLD_ITEM_LIFETIME), give up and resume normal operation rather
# than locking the FSM forever.  60 s is comfortably longer than
# the bot's longest cross-world traversal (~30 s @ MAX_SPEED).
DEATH_RECOVERY_TIMEOUT_S: float = 60.0
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
    fortify_done: bool = False
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
    # A* path cache.  Set by ``_astar_next_waypoint`` when a chase
    # target requires routing around the building cluster (or any
    # other obstacle).  ``path_target`` is the (gx, gy) we last
    # planned for — when the FSM re-targets this gets invalidated;
    # when the bot reaches a waypoint the head of ``path_waypoints``
    # is popped.  Without caching a fresh A* would run every tick,
    # which is cheap (<1 ms) but unnecessary when the target is
    # stable.
    path_target: tuple = (None, None)
    path_waypoints: list = field(default_factory=list)
    path_planned_at: float = 0.0
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
    # MINE no-progress watchdog (2026-05-09 follow-up).  Captures
    # ship_iron at S_MINE entry and the next deadline at which the
    # action handler must verify that mining is actually producing
    # iron.  If MINE has held for ``MINE_NO_PROGRESS_S`` without a
    # ship_iron increase, the current chase target gets blacklisted
    # so the FSM re-targets next tick — breaks the deadlock pattern
    # where the bot orbits asteroids that are nominally reachable
    # (A* passes) but never closes to mining range, observed as a
    # 12-minute zero-iron-progress S_MINE wedge in the telemetry.
    mine_iron_baseline: int = 0
    mine_progress_check_at: float = 0.0
    # Death detection + loot recovery (PR 2026-05-10).  The bot
    # observes alive->dead transitions via ``player.is_dead`` in the
    # snapshot; when it sees the player just died it records the
    # death position and the loadout that was on the ship the tick
    # BEFORE the death so the recovery action can navigate back and
    # the install / equip pipelines can re-queue what was lost.
    #
    # ``last_alive_*`` refreshed every tick while is_dead=False so
    # the snapshot at the alive->dead boundary captures the last
    # known loadout (death wipes ``module_slots`` + ``quick_use_slots``
    # to empty / None immediately, so we can't read them post-mortem).
    last_alive_pos: tuple = (0.0, 0.0)
    last_alive_modules: list = field(default_factory=list)
    last_alive_consumable_types: list = field(default_factory=list)
    was_dead: bool = False  # alive->dead edge detector
    # ``death_recovery_pending`` flips True on the dead->alive edge
    # when the prior loadout contained anything worth recovering.
    # Cleared by the recovery action once the dropped pickups have
    # been collected (or after RECOVERY_TIMEOUT_S elapses so a bot
    # that can't reach the death site doesn't sit in S_RECOVER_LOOT
    # forever).
    death_recovery_pending: bool = False
    death_recovery_pos: tuple = (0.0, 0.0)
    death_recovery_modules: list = field(default_factory=list)
    death_recovery_consumables: list = field(default_factory=list)
    death_recovery_started_at: float = 0.0
    # Boss combat metrics (PR 2026-05-10): captures the state of the
    # ship + boss at S_ENGAGE_BOSS entry so the matching exit-time
    # ``boss_engage_end`` event can log dwell + HP/shield deltas +
    # outcome (boss_killed / player_died / disengaged).
    boss_engage_started_at: float = 0.0
    boss_engage_start_hp: int = 0
    boss_engage_start_shields: int = 0
    boss_engage_start_boss_hp: int = 0
    # Boss LURE latch (2026-05-11): True while the bot is actively
    # retreating toward the Home Station to drag the boss into the
    # turret + missile-array DPS zone.  Hysteresis is driven by
    # BOSS_LURE_SHIELDS_PCT (enter) / BOSS_LURE_EXIT_SHIELDS_PCT
    # (exit) so the bot doesn't oscillate between kite ring + lure
    # at the threshold boundary.
    boss_lure_active: bool = False
    # Boss TURRET-ASSIST latch (2026-05-12): True while the bot is
    # orbiting the home station instead of kiting the boss directly
    # (the boss is close enough to the station that turrets can
    # solo it).  Set when the boss enters
    # ``BOSS_TURRET_ASSIST_ENTER_PX`` of the station; cleared when
    # it leaves ``BOSS_TURRET_ASSIST_EXIT_PX`` (hysteresis so a
    # boss hovering at the threshold doesn't flap the bot).
    boss_turret_assist_active: bool = False

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
        self.fortify_done = False
        self.qwi_placed = False
        self.last_consumable_use_at = 0.0
        self.wall_pin_anchor = (0.0, 0.0)
        self.wall_pin_anchor_at = 0.0
        self.heal_hp_active = False
        self.heal_shield_active = False
        self.path_target = (None, None)
        self.path_waypoints = []
        self.path_planned_at = 0.0
        self.mine_iron_baseline = 0
        self.mine_progress_check_at = 0.0
        self.last_alive_pos = (0.0, 0.0)
        self.last_alive_modules = []
        self.last_alive_consumable_types = []
        self.was_dead = False
        self.death_recovery_pending = False
        self.death_recovery_pos = (0.0, 0.0)
        self.death_recovery_modules = []
        self.death_recovery_consumables = []
        self.death_recovery_started_at = 0.0
        self.boss_engage_started_at = 0.0
        self.boss_engage_start_hp = 0
        self.boss_engage_start_shields = 0
        self.boss_engage_start_boss_hp = 0
        self.boss_lure_active = False
        self.boss_turret_assist_active = False


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


# ── A* path-cache helpers ───────────────────────────────────────────────
# Wrappers around ``bot_autopilot_astar.plan_path`` that cache the
# result on ``_state.path_*`` so a stable target doesn't trigger a
# fresh A* every tick.  Replan when:
#   * target moves more than ASTAR_REPLAN_TARGET_DRIFT_PX from the
#     last planned (gx, gy);
#   * the cached path is older than ASTAR_REPLAN_TTL_S;
#   * the next-waypoint queue has been emptied (last waypoint
#     reached).
# Cheap (~0.1-1 ms per plan on a typical 6400×6400 / 12-building
# state) so the cache is mostly an FSM-stability concern, not a
# performance one — without caching, every tick's tiny target jitter
# (alien moving, asteroid drifting) would flush the path.

ASTAR_REPLAN_TTL_S:           float = 3.0
ASTAR_REPLAN_TARGET_DRIFT_PX: float = 80.0
# Stop-radius for "reached this waypoint" — popped off the queue
# when the bot is within this distance.  Matches the grid cell
# size so a cell-centre waypoint is considered reached when the
# bot enters that cell.
ASTAR_WAYPOINT_REACHED_PX:    float = 80.0


def _astar_plan_path(state: dict, sx: float, sy: float,
                     gx: float, gy: float,
                     goal_radius_px: float = 0.0) -> list:
    """Thin wrapper around ``_astar.plan_path`` so test harnesses
    can monkey-patch the planner without touching the underlying
    module.  Returns the same list of (x, y) waypoints (or []).

    ``goal_radius_px`` is forwarded so docking actions can plan to
    a nearby free cell when the literal goal cell is a building."""
    return _astar.plan_path(state, sx, sy, gx, gy,
                            goal_radius_px=goal_radius_px)


def _astar_invalidate_path() -> None:
    """Clear the cached A* path.  Called on FSM transitions and
    blacklist events so the next ``_astar_next_waypoint`` plans
    fresh against the new target / world snapshot."""
    _state.path_target = (None, None)
    _state.path_waypoints = []
    _state.path_planned_at = 0.0


def _astar_next_waypoint(state: dict, sx: float, sy: float,
                         gx: float, gy: float,
                         stop_radius_px: float = 0.0):
    """Return the next ``(wx, wy)`` waypoint along an A* path from
    ``(sx, sy)`` to ``(gx, gy)``, OR ``None`` to indicate the
    direct path is fine, OR the sentinel string ``"unreachable"``
    when no path exists.

    ``stop_radius_px`` is the goto's ``stop_radius`` argument: when
    > 0 it relaxes the planner from "reach the literal goal cell"
    to "reach within stop_radius of the goal".  Critical for
    docking actions where the literal goal is a building cell
    (necessarily blocked); without the relaxation A* always
    reports the docking target as unreachable and the bot falls
    back to direct-goto, which deadlocks against building-
    repulsion at the dock-zone perimeter (caught from
    2026-05-08 telemetry: bot pinned at (468, 4304) hs_dist=318
    in both ``deposit`` and ``craft`` states with the new fortify-N
    turret blocking the north-side approach).

    Uses ``_state.path_*`` as a cache so a stable target reuses the
    same plan across ticks.  Replans when the target drifts more
    than ``ASTAR_REPLAN_TARGET_DRIFT_PX`` from the cached target,
    when the path is stale (> ``ASTAR_REPLAN_TTL_S``), or when the
    waypoint queue has been emptied.

    A direct line-of-sight check between the bot and the goal is
    used as the "no plan needed" signal — the planner is bypassed
    when the world snapshot's grid would mark the bot→goal segment
    as fully clear.  This skips the per-tick A* call for the common
    case (no clusters between bot and target).
    """
    # Direct line of sight first — most ticks have no cluster in
    # the way, so this fast path skips the planner entirely.
    # Uses the hard-block set (physical ship clearance) under cost
    # weighting; under the legacy binary mode this is the wider
    # safety-margin set.
    blocked = _astar.los_blocked_set(state)
    if _astar._line_of_sight((sx, sy), (gx, gy), blocked):
        # Direct path is clear; invalidate any stale cached path so
        # the next blocked target plans from scratch.
        if _state.path_waypoints:
            _astar_invalidate_path()
        return None

    now = _get_now()
    cached_tgt = _state.path_target
    drift_sq = ASTAR_REPLAN_TARGET_DRIFT_PX * ASTAR_REPLAN_TARGET_DRIFT_PX
    needs_replan = (
        not _state.path_waypoints
        or cached_tgt[0] is None
        or (gx - cached_tgt[0]) ** 2 + (gy - cached_tgt[1]) ** 2 > drift_sq
        or (now - _state.path_planned_at) > ASTAR_REPLAN_TTL_S
    )
    if needs_replan:
        wp = _astar_plan_path(state, sx, sy, gx, gy,
                              goal_radius_px=stop_radius_px)
        if not wp:
            _astar_invalidate_path()
            return "unreachable"
        _state.path_waypoints = wp
        _state.path_target = (gx, gy)
        _state.path_planned_at = now

    # Pop reached waypoints off the head of the queue.  Iterate
    # because the bot may have skipped past several waypoints in
    # one frame (e.g. high-speed pursuit through a smoothed path).
    reached_sq = (ASTAR_WAYPOINT_REACHED_PX
                  * ASTAR_WAYPOINT_REACHED_PX)
    while _state.path_waypoints:
        wx, wy = _state.path_waypoints[0]
        if (wx - sx) ** 2 + (wy - sy) ** 2 <= reached_sq:
            _state.path_waypoints.pop(0)
        else:
            break
    if not _state.path_waypoints:
        # Reached the end of the cached path — re-evaluate next
        # tick (probably direct-line-of-sight by now).
        _astar_invalidate_path()
        return None
    return _state.path_waypoints[0]


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
    _post_fortify,
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
    _act_at_station, _act_equip_consumables, _act_fortify, _act_build_qwi,
    _act_recover_loot,
)
from bot_autopilot_actions_combat import (
    _act_engage, _act_engage_boss, _maybe_use_consumables,
    _act_gather, _act_idle_at_base,
)


# ── Death detection + loot-recovery state machine (PR 2026-05-10) ────────

def _observe_death_edges(state: dict, p: dict, now: float) -> None:
    """Track alive->dead and dead->alive transitions to drive the
    post-death loot-recovery action + boss telemetry.

    While alive:
      * Refresh ``last_alive_pos`` / ``last_alive_modules`` /
        ``last_alive_consumable_types`` every tick so the snapshot
        AT THE MOMENT OF DEATH captures the loadout that's about to
        be dropped (``combat_helpers._drop_player_loadout`` wipes
        the module + quick-use slots immediately).

    On alive -> dead edge:
      * Emit ``player_death`` telemetry with the FSM state, dropped
        loadout size, and -- if the death happened during boss
        combat -- a ``boss_context`` snapshot.

    On dead -> alive edge:
      * If the bot had anything worth recovering (modules OR
        consumables), set ``death_recovery_pending=True`` with the
        death position + lost-module list captured at the alive
        edge so the FSM cascade picks S_RECOVER_LOOT until the
        loot is collected.
      * Refill ``queue.modules_to_install`` with the lost modules
        so the existing install pipeline re-installs them after
        the bot deposits the recovered loot.
      * Reset ``consumables_equipped`` so the existing
        S_EQUIP_CONSUMABLES action re-binds quick-use slots once
        the recovered consumables land in station inventory.
    """
    is_dead_now = bool((state.get("player") or {}).get("is_dead",
                                                       False))
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))

    if not is_dead_now:
        # Snapshot live loadout each tick so the alive->dead edge
        # captures the loadout that's about to drop.
        _state.last_alive_pos = (px, py)
        _state.last_alive_modules = [
            m for m in (state.get("module_slots") or [])
            if m is not None]
        _state.last_alive_consumable_types = [
            s.get("item_type") for s in (state.get("quick_use_slots") or [])
            if s and s.get("item_type")
            and s.get("item_type") != "missile"]
        # dead -> alive edge: finalize recovery setup if there was
        # anything to recover (snapshotted at the alive->dead edge
        # in ``death_recovery_modules`` / ``_consumables``).
        if _state.was_dead:
            _state.was_dead = False
            had_modules = bool(_state.death_recovery_modules)
            had_consumables = bool(_state.death_recovery_consumables)
            if had_modules or had_consumables:
                _state.death_recovery_pending = True
                _state.death_recovery_started_at = now
                # Refill the install queue with what was lost so
                # the existing INSTALL pipeline picks them up after
                # the bot deposits the recovered modules.
                for mod in _state.death_recovery_modules:
                    if mod not in _state.queue.modules_to_install:
                        _state.queue.modules_to_install.append(mod)
                # Reset the consumables latch so the existing
                # EQUIP pipeline re-binds quick-use slots once the
                # recovered consumables reach station inventory.
                if had_consumables:
                    _state.consumables_equipped = False
                _telemetry_log(
                    "death_recovery_armed",
                    death_pos=[round(_state.death_recovery_pos[0], 1),
                               round(_state.death_recovery_pos[1], 1)],
                    lost_modules=list(_state.death_recovery_modules),
                    lost_consumables=list(
                        _state.death_recovery_consumables),
                )
        return

    # is_dead_now == True
    if not _state.was_dead:
        # alive -> dead edge.  Freeze the alive-tick snapshots into
        # the death-recovery fields so the dead->alive edge can read
        # them even after this same tick's wipe of module_slots /
        # quick_use_slots clears the live values.
        _state.was_dead = True
        _state.death_recovery_pos = _state.last_alive_pos
        _state.death_recovery_modules = list(
            _state.last_alive_modules)
        _state.death_recovery_consumables = list(
            _state.last_alive_consumable_types)
        boss = state.get("boss")
        boss_ctx = None
        if boss is not None:
            boss_ctx = {
                "boss_hp": int(boss.get("hp", 0)),
                "boss_max_hp": int(boss.get("max_hp", 0)),
                "boss_phase": int(boss.get("phase", 1)),
            }
        _telemetry_log(
            "player_death",
            fsm_state=_fsm["state"],
            death_pos=[round(_state.death_recovery_pos[0], 1),
                       round(_state.death_recovery_pos[1], 1)],
            lost_modules=list(_state.death_recovery_modules),
            lost_consumables=list(_state.death_recovery_consumables),
            boss_context=boss_ctx,
        )


def _maybe_log_boss_engage_edges(state: dict, p: dict, now: float,
                                 prev: str, cur: str) -> None:
    """Emit ``boss_engage_start`` / ``boss_engage_end`` telemetry on
    the matching FSM transitions so post-hoc log analysis can
    measure how long each boss fight took, HP / shield deltas, and
    the outcome (boss killed / player died / disengaged).

    Pulled out into its own helper so the dispatch-loop call sites
    stay one-line.
    """
    if cur == S_ENGAGE_BOSS and prev != S_ENGAGE_BOSS:
        player = state.get("player") or {}
        boss = state.get("boss") or {}
        _state.boss_engage_started_at = now
        _state.boss_engage_start_hp = int(player.get("hp", 0))
        _state.boss_engage_start_shields = int(player.get("shields", 0))
        _state.boss_engage_start_boss_hp = int(boss.get("hp", 0))
        _telemetry_log(
            "boss_engage_start",
            from_state=prev,
            player_hp=_state.boss_engage_start_hp,
            player_max_hp=int(player.get("max_hp", 0)),
            player_shields_at_start=_state.boss_engage_start_shields,
            boss_hp=_state.boss_engage_start_boss_hp,
            boss_max_hp=int(boss.get("max_hp", 0)),
            boss_phase=int(boss.get("phase", 1)),
            **_telemetry_snapshot_fields(state, p))
    elif prev == S_ENGAGE_BOSS and cur != S_ENGAGE_BOSS:
        player = state.get("player") or {}
        boss = state.get("boss") or {}
        # Outcome inference:
        #   * boss_killed -- ``state.boss`` is now empty / hp <= 0
        #   * player_died -- ``player.is_dead`` flipped True
        #   * disengaged  -- neither; FSM cascade preempted (REGEN /
        #                    something higher priority)
        boss_alive = (state.get("boss") is not None
                      and int(boss.get("hp", 0)) > 0)
        if not boss_alive:
            outcome = "boss_killed"
        elif bool(player.get("is_dead", False)):
            outcome = "player_died"
        else:
            outcome = "disengaged"
        dwell = now - _state.boss_engage_started_at
        _telemetry_log(
            "boss_engage_end",
            to_state=cur,
            outcome=outcome,
            dwell_s=round(dwell, 2),
            player_hp_delta=int(player.get("hp", 0))
                            - _state.boss_engage_start_hp,
            player_shields_delta=int(player.get("shields", 0))
                                 - _state.boss_engage_start_shields,
            boss_hp_delta=int(boss.get("hp", 0))
                          - _state.boss_engage_start_boss_hp,
            **_telemetry_snapshot_fields(state, p))


def _maybe_clear_death_recovery(state: dict, p: dict, now: float) -> None:
    """Clear the recovery pending flag when the loot at the death
    site is no longer there (collected, or despawned via
    WORLD_ITEM_LIFETIME), OR when ``DEATH_RECOVERY_TIMEOUT_S`` has
    elapsed since the recovery was armed.  Called by the FSM
    cascade so the bot doesn't sit in S_RECOVER_LOOT forever.
    """
    if not _state.death_recovery_pending:
        return
    if now - _state.death_recovery_started_at >= DEATH_RECOVERY_TIMEOUT_S:
        _telemetry_log(
            "death_recovery_timeout",
            elapsed_s=round(now - _state.death_recovery_started_at, 1),
            **_telemetry_snapshot_fields(state, p))
        _state.death_recovery_pending = False
        return
    # Check whether any pickup is still within range of the death
    # position.  If none remain (everything collected / despawned),
    # we're done.
    drx, dry = _state.death_recovery_pos
    radius_sq = 600.0 * 600.0   # generous match radius
    for plist_key in ("iron_pickups", "blueprint_pickups"):
        for pu in (state.get(plist_key) or []):
            dx = float(pu.get("x", 0.0)) - drx
            dy = float(pu.get("y", 0.0)) - dry
            if dx * dx + dy * dy <= radius_sq:
                return  # loot still on the floor near the death site
    # No loot remains -- clear the latch and let the FSM fall
    # through to its normal cascade (which will then deposit any
    # recovered items and route through the INSTALL pipeline).
    _telemetry_log(
        "death_recovery_complete",
        elapsed_s=round(now - _state.death_recovery_started_at, 1),
        **_telemetry_snapshot_fields(state, p))
    _state.death_recovery_pending = False


# ── FSM core (orchestrator) ──────────────────────────────────────────────


def _choose_next_state(state: dict, p: dict, cur: str) -> str:
    """Pure function: given the world snapshot and the current FSM
    state, return what state the bot *wants* to be in this tick.

    Implementation lives in ``bot_autopilot_choose.choose_next_state``
    -- the 551-line priority cascade was extracted in the 2026-05-10
    refactor.  Test-time monkey-patches on ``bot_autopilot`` symbols
    (``_state``, ``_fsm``, threshold constants, helper functions)
    still thread through because the helper module qualifies every
    cross-reference as ``_ap.<name>`` at call time.
    """
    from bot_autopilot_choose import choose_next_state
    return choose_next_state(state, p, cur)


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
    elif new_state in (S_MINE, S_PRE_BOSS_MINE):
        # 50/50 dice roll: Mining Beam vs Energy Pickaxe.  Sticky
        # for the entire mining session so the bot doesn't tab-flap
        # mid-asteroid.  Re-rolled on each fresh entry into MINE.
        if random.random() < MINING_PICKAXE_CHANCE:
            _state.mining_weapon_pick = "Energy Pickaxe"
        else:
            _state.mining_weapon_pick = "Mining Beam"
        # Reset the MINE-without-progress watchdog so the action
        # handler re-seeds the baseline + deadline on its first
        # tick after this entry.  Avoids carrying stale baselines
        # across MINE→OTHER→MINE cycles.
        #
        # S_PRE_BOSS_MINE shares the same _do_mine_nearest action
        # handler + watchdog as S_MINE, so it also needs the reset.
        # 2026-05-10 telemetry caught 10 false-positive blacklists
        # (one every ~120 s during the boss-prep mining grind), all
        # with iron_now < baseline -- the baseline was set during an
        # earlier MINE/PRE_BOSS_MINE before a deposit dropped
        # ship_iron to 0, then PRE_BOSS_MINE re-entered without the
        # watchdog being reset and the 60-s deadline tripped on the
        # stale baseline.  Adding S_PRE_BOSS_MINE here fixes the
        # cycle (PRE_BOSS_MINE → DEPOSIT → PRE_BOSS_MINE) cleanly.
        _state.mine_progress_check_at = 0.0


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

    # Death edge detection + loadout snapshot (PR 2026-05-10).
    # Tracks the alive->dead transition so the bot can drive a
    # recovery action after respawn that picks up the dropped
    # modules + consumables.  See ``_observe_death_edges`` for the
    # full state machine.
    _observe_death_edges(state, p, now)

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
            _astar_invalidate_path()
        _on_enter(cur)
        _maybe_log_boss_engage_edges(state, p, now, prev, cur)
        _telemetry_log("state_transition", reason="first_tick",
                       from_state=prev, to_state=cur, desired=desired,
                       **_telemetry_snapshot_fields(state, p))
    elif desired != cur:
        dwell = now - _fsm["entered_at"]
        # ENGAGE and REGEN are defensive interrupts -- they bypass
        # MIN_DWELL so the bot reacts to a sudden threat or a sudden
        # shield collapse without waiting for the dwell timer.
        #
        # S_IDLE_AT_BASE is the bot's "doing nothing while parked"
        # state.  Leaving it for ANY productive state should be
        # immediate -- the bot was already idle, there's nothing
        # to preserve.  2026-05-10 telemetry caught 87 suppressed
        # idle_at_base->hunt transitions in a 10-minute session
        # (one per ~10 ticks, each wasting 1 s of reaction time
        # before the eventual hunt fired).  The hunt-stuck giveup
        # mechanisms (HUNT_PIN_GIVEUP_S, HUNT_GIVEUP_S, the
        # hunt_anchor_hits tracker) already prevent thrash on
        # genuine wall pins, so making hunt-from-idle instant is
        # safe.
        idle_react = cur == S_IDLE_AT_BASE
        if desired in (S_ENGAGE, S_REGEN, S_ENGAGE_BOSS,
                       S_EQUIP_CONSUMABLES, S_FORTIFY,
                       S_BUILD_QWI) or \
                idle_react or \
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
            _astar_invalidate_path()
            cur = desired
            _on_enter(cur)
            _maybe_log_boss_engage_edges(state, p, now, prev, cur)
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
    elif cur == S_FORTIFY:
        _act_fortify(state, p)
    elif cur == S_BUILD_QWI:
        _act_build_qwi(state, p)
    elif cur == S_RECOVER_LOOT:
        _act_recover_loot(state, p)
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
