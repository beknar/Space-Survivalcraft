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

# ── Tuning constants -- now in bot_autopilot_tuning.py ──────────────────
# The 1000+ lines of FSM hysteresis bands, boss-fight tuning, state
# constants, craft-phase thresholds, etc. were extracted in the
# 2026-05-24 PR 6 refactor.  ``from ... import *`` keeps every
# constant accessible as ``bot_autopilot.CONSTANT_NAME`` so the
# helper modules' ``_ap.CONSTANT_NAME`` pattern keeps working.
from bot_autopilot_tuning import *  # noqa: F401,F403

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
class WarpState:
    """Post-boss warp + traverse latches.

    Holds the multi-tick state for the boss-killed -> warp_to_wormhole
    -> warp_traverse -> warp_back_to_main arc.  Originally 13 flat
    fields on ``BotState`` (``warp_after_boss_done`` etc.); grouped
    here in the 2026-05-24 PR 5 refactor.  Property aliases on
    ``BotState`` preserve the legacy flat names so external code
    (``_state.warp_after_boss_done``) keeps working unchanged.
    """
    after_boss_done: bool = False
    relatched_pending: bool = False
    traverse_done: bool = False
    wormhole_arrived_at: float = 0.0
    wormhole_best_d: float = 0.0
    wormhole_progress_at: float = 0.0
    traverse_max_y: float = 0.0
    traverse_progress_at: float = 0.0
    traverse_detour_count: int = 0
    traverse_detour_side: int = 0
    traverse_detour_commit_y: float = 0.0
    traverse_progress_committed_y: float = 0.0
    traverse_arc_started_at: float = 0.0
    # Nebula-death recovery latch (2026-05-24).  Latches True at
    # the alive->dead edge when the bot dies in ZONE2 (Nebula).
    # Forces the warp-to-wormhole gate into strict mode: no
    # best-effort path, consumables required in slots, and shields
    # + HP required at the configured recovery percentages (default
    # 100 %) before the next warp can fire.  Combined with the
    # recraft top-up in ``_observe_warp_back_to_main`` this keeps
    # the bot at the home-station umbrella rebuilding consumables
    # + healing until it's actually ready to survive another arc.
    # Cleared once the warp-out transition lands (handled by the
    # existing ``warp_after_boss_complete`` gate in choose).
    nebula_recovery_pending: bool = False
    # Nebula fortify latch (2026-05-24): one-shot per session that
    # latches True once the Nebula HS has its turret + missile ring
    # in place, so the FSM doesn't re-fire S_FORTIFY_NEBULA every
    # tick.  Mirrors the MAIN-zone ``BotState.fortify_done`` field,
    # but separate so the two rings track independently (the bot
    # builds MAIN's ring during boss prep and the Nebula ring after
    # arriving in ZONE2 with an HS).  Cleared by ``BotState.reset``.
    nebula_fortify_done: bool = False
    # Nebula AI Pilot ship latch (2026-05-24): True once a parked
    # ship with the ai_pilot module is sitting near the Nebula HS,
    # providing cover fire while the bot fights.  One-shot per
    # session.  Cleared by ``BotState.reset``.
    nebula_ai_pilot_placed: bool = False
    # Nebula Advanced Crafter latch (2026-05-25): True once an
    # Advanced Crafter sits next to the Nebula HS.  Gates the
    # advanced-module craft queue (misty_step / force_wall /
    # death_blossom).  One-shot per session.  Cleared by
    # ``BotState.reset``.
    nebula_advanced_crafter_done: bool = False


@dataclass
class GasLingerState:
    """gas_lingering observer state (PR #152).

    Tracks the tick the bot first entered the current gas cloud
    plus the shields/hp at that moment so
    ``_observe_gas_lingering`` can emit a single ``gas_lingering``
    event per linger episode.  ``entered_at == 0.0`` means "not
    currently inside any cloud".
    """
    entered_at: float = 0.0
    entry_shields: int = 0
    entry_hp: int = 0
    event_fired: bool = False


@dataclass
class BossCombatState:
    """Per-fight boss-combat tracking.

    Captures the state of the ship + boss at S_ENGAGE_BOSS entry
    (so the matching ``boss_engage_end`` event can log dwell +
    HP/shield deltas + outcome), plus the LURE / TURRET-ASSIST
    latches that gate which kite mode the bot uses, plus the
    sticky ``was_killed`` latch that arms post-boss warp logic.
    """
    engage_started_at: float = 0.0
    engage_start_hp: int = 0
    engage_start_shields: int = 0
    engage_start_boss_hp: int = 0
    lure_active: bool = False
    turret_assist_active: bool = False
    was_killed: bool = False


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
    # Nebula (ZONE2) starter-base latch (2026-05-23).  Separate from
    # ``build_done`` so the bot can build one base in MAIN AND one
    # in Nebula.  Latches True on the first attempt OR the first
    # time the bot sees a Home Station in ZONE2's building_list
    # (loaded save / manual placement).  Buildings are zone-scoped
    # via the ZoneState stash mechanism, so the BUILDING_TYPES
    # max=1 cap on Home Station applies per-zone, not save-wide.
    nebula_build_done: bool = False
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
    # Active pin-zone anchors recorded from stuck_detected events
    # across ALL fsm states (not just HUNT).  Each entry is
    # ``(cx, cy, expiry_ts)`` -- the targeting helpers filter
    # pickups / asteroids / huntable aliens within
    # PIN_ZONE_RADIUS_PX of any non-expired anchor so the bot
    # can't be pulled back into a known stuck location while
    # the TTL is active.  Captured 2026-05-17 bot_io: 8 stuck
    # events in 130 s at (8592, 1453) in Nebula -- bot frozen
    # for 30+ s with shields=0, burned 28 repair packs.  Specific
    # blacklisted pickups / asteroids weren't enough since the
    # surrounding 54 aliens kept spawning new pickups in the
    # same area.  See PIN_ZONE_* constants for the tuning.
    pin_zones: list = field(default_factory=list)
    # Last shields value seen during S_REGEN — the escape valve
    # in _choose_next_state compares the current value against this
    # to detect "shields not recovering" (i.e., still being shot)
    # and lets ENGAGE preempt REGEN to break the deadlock.  Reset
    # to 0 on REGEN exit so the trend check restarts cleanly on
    # next entry.
    last_regen_shields: int = 0
    # Timestamp of the most recent tick where shields gained ground
    # during REGEN.  Used by the escape valve's hysteresis: the
    # valve only fires when no progress has been seen for
    # REGEN_NO_PROGRESS_TIMEOUT_S consecutive seconds.  Without
    # this, a single tick of damage during recovery flips
    # ``shields_recovering`` to False and kicks the bot out --
    # 2026-05-13 fifteenth telemetry pass captured the symptom:
    # shields 50 → 68 over 12 s (recovering), then escape valve
    # fired on a damage spike, bot exited REGEN → recover_loot,
    # died 3 more times near station.
    last_regen_progress_at: float = 0.0
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
    # Gas-lingering telemetry state (PR #152).  Grouped into
    # ``GasLingerState`` in PR 5; legacy flat names
    # (``gas_linger_entered_at`` etc.) are preserved via property
    # aliases below.
    gas_linger: GasLingerState = field(default_factory=GasLingerState)
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
    # Zone the death happened in (2026-05-28).  Captured at the
    # alive -> dead edge so the recovery flow can detect a
    # cross-zone case: if the bot respawns in MAIN but its loot
    # is in Nebula coordinates, the recorded position is
    # unreachable from MAIN.  ``_maybe_clear_death_recovery``
    # short-circuits the latch + the 60 s window when the bot's
    # current zone differs from the death zone.  Empty string =
    # uncaptured (legacy save / first session before this PR).
    death_recovery_zone: str = ""
    # Boss combat tracking (engage start metrics + LURE / TURRET-
    # ASSIST latches + boss-killed sticky).  Grouped into
    # ``BossCombatState`` in PR 5; legacy flat names
    # (``boss_engage_started_at``, ``boss_lure_active``,
    # ``boss_turret_assist_active``, ``boss_was_killed`` etc.) are
    # preserved via property aliases below.
    boss_combat: BossCombatState = field(default_factory=BossCombatState)
    # Post-boss warp + traverse latches.  Grouped into ``WarpState``
    # in PR 5; legacy flat names (``warp_after_boss_done``,
    # ``warp_relatched_pending``, ``warp_traverse_done``,
    # ``warp_wormhole_*``, ``warp_traverse_*``) are preserved via
    # property aliases below.
    warp: WarpState = field(default_factory=WarpState)
    # Install-blocked telemetry throttle (2026-06-07).  A 34-min
    # session deadlocked in S_INSTALL (190 stuck_detected, queue head
    # never advancing) and the snapshot couldn't show WHY -- whether
    # the module item was missing from station inventory, a slot was
    # full, or the install POST was rejected.  ``_act_install`` emits a
    # throttled ``install_blocked`` event keyed off this timestamp.
    install_blocked_last_log_at: float = 0.0
    # Install-progress watchdog (2026-06-07).  Tracks the queue head the
    # bot is currently trying (and failing) to install while docked, and
    # how long it's been stalled, so ``_act_install`` can re-queue or
    # abandon a head that can't advance instead of deadlocking S_INSTALL
    # forever.  ``install_recraft_attempts`` caps the re-craft retries
    # per module key.
    install_stall_head: str = ""
    install_stall_since: float = 0.0
    install_recraft_attempts: dict = field(default_factory=dict)

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
        self.nebula_build_done = fresh.nebula_build_done
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
        self.pin_zones.clear()
        self.last_regen_shields = 0
        self.last_regen_progress_at = 0.0
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
        # Sub-state objects -- replace the whole object rather than
        # poke each field, so adding a new field to one of these
        # dataclasses doesn't silently leak prior-run state through
        # reset().
        self.gas_linger = GasLingerState()
        self.death_recovery_pending = False
        self.death_recovery_pos = (0.0, 0.0)
        self.death_recovery_modules = []
        self.death_recovery_consumables = []
        self.death_recovery_started_at = 0.0
        self.death_recovery_zone = ""
        self.boss_combat = BossCombatState()
        self.warp = WarpState()
        self.install_blocked_last_log_at = 0.0
        self.install_stall_head = ""
        self.install_stall_since = 0.0
        self.install_recraft_attempts = {}


# ── BotState backward-compat property aliases ─────────────────────────────
#
# The 2026-05-24 PR 5 refactor grouped 24 flat fields into three
# sub-dataclasses (``WarpState``, ``GasLingerState``,
# ``BossCombatState``).  External code still uses the legacy flat
# names (~430 call sites in production + tests).  These property
# descriptors delegate get/set to the sub-objects so the flat
# interface keeps working without churn -- adding a real
# behavioural callsite that wants the sub-object should reach for
# ``_state.warp.after_boss_done`` directly; the flat aliases are
# the compat layer.

def _alias(group: str, attr: str) -> property:
    """Property descriptor that delegates get/set to a sub-state
    attribute on ``BotState``."""
    def _get(self):
        return getattr(getattr(self, group), attr)
    def _set(self, value):
        setattr(getattr(self, group), attr, value)
    return property(_get, _set)


# WarpState aliases.
BotState.warp_after_boss_done = _alias("warp", "after_boss_done")
BotState.warp_relatched_pending = _alias("warp", "relatched_pending")
BotState.warp_traverse_done = _alias("warp", "traverse_done")
BotState.warp_wormhole_arrived_at = _alias("warp", "wormhole_arrived_at")
BotState.warp_wormhole_best_d = _alias("warp", "wormhole_best_d")
BotState.warp_wormhole_progress_at = _alias("warp", "wormhole_progress_at")
BotState.warp_traverse_max_y = _alias("warp", "traverse_max_y")
BotState.warp_traverse_progress_at = _alias("warp", "traverse_progress_at")
BotState.warp_traverse_detour_count = _alias("warp", "traverse_detour_count")
BotState.warp_traverse_detour_side = _alias("warp", "traverse_detour_side")
BotState.warp_traverse_detour_commit_y = _alias(
    "warp", "traverse_detour_commit_y")
BotState.warp_traverse_progress_committed_y = _alias(
    "warp", "traverse_progress_committed_y")
BotState.warp_traverse_arc_started_at = _alias(
    "warp", "traverse_arc_started_at")
BotState.nebula_recovery_pending = _alias(
    "warp", "nebula_recovery_pending")
BotState.nebula_fortify_done = _alias("warp", "nebula_fortify_done")
BotState.nebula_ai_pilot_placed = _alias(
    "warp", "nebula_ai_pilot_placed")
BotState.nebula_advanced_crafter_done = _alias(
    "warp", "nebula_advanced_crafter_done")

# GasLingerState aliases.
BotState.gas_linger_entered_at = _alias("gas_linger", "entered_at")
BotState.gas_linger_entry_shields = _alias("gas_linger", "entry_shields")
BotState.gas_linger_entry_hp = _alias("gas_linger", "entry_hp")
BotState.gas_linger_event_fired = _alias("gas_linger", "event_fired")

# BossCombatState aliases.
BotState.boss_engage_started_at = _alias("boss_combat", "engage_started_at")
BotState.boss_engage_start_hp = _alias("boss_combat", "engage_start_hp")
BotState.boss_engage_start_shields = _alias(
    "boss_combat", "engage_start_shields")
BotState.boss_engage_start_boss_hp = _alias(
    "boss_combat", "engage_start_boss_hp")
BotState.boss_lure_active = _alias("boss_combat", "lure_active")
BotState.boss_turret_assist_active = _alias(
    "boss_combat", "turret_assist_active")
BotState.boss_was_killed = _alias("boss_combat", "was_killed")


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


def _record_pin_zone_anchor(x: float, y: float, now: float) -> None:
    """Add (x, y, now + PIN_ZONE_TTL_S) to ``_state.pin_zones``,
    evicting expired entries first.  Caps the list at
    PIN_ZONE_MAX entries by dropping the oldest-expiring entry so
    a runaway stuck-loop can't grow the list unbounded.

    Called from the stuck-watchdog every time ``stuck_detected``
    fires so the targeting helpers can filter targets within
    PIN_ZONE_RADIUS_PX of any active anchor for the TTL.
    """
    # Evict expired first.
    if _state.pin_zones:
        _state.pin_zones[:] = [z for z in _state.pin_zones
                               if z[2] > now]
    _state.pin_zones.append((float(x), float(y),
                             now + PIN_ZONE_TTL_S))
    # Cap by dropping the soonest-expiring entry (typically the
    # oldest) if the list overflows.  This is a defensive bound;
    # the TTL alone normally keeps the list small.
    if len(_state.pin_zones) > PIN_ZONE_MAX:
        _state.pin_zones.sort(key=lambda z: z[2])
        _state.pin_zones.pop(0)


def _target_in_pin_zone(x: float, y: float, now: float | None = None
                        ) -> bool:
    """Test whether (x, y) is inside any non-expired pin-zone's
    radius.  Used by the targeting helpers to filter pickups /
    asteroids near recently-stuck positions.
    """
    if not _state.pin_zones:
        return False
    if now is None:
        now = _get_now()
    r2 = PIN_ZONE_RADIUS_PX * PIN_ZONE_RADIUS_PX
    for (cx, cy, exp) in _state.pin_zones:
        if exp <= now:
            continue
        dx = cx - x
        dy = cy - y
        if dx * dx + dy * dy <= r2:
            return True
    return False


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
    _post_uninstall_module,
    _post_deposit_to_station,
    _post_use_quick_use,
    _post_equip_consumables,
    _post_fortify,
    _post_place_qwi,
    _post_place_ai_pilot_ship,
    _post_place_advanced_crafter,
    _ensure_game_focused,
)
from bot_autopilot_targeting import (
    _pickup_is_blacklisted, _blacklist_pickup, _nearest_pickup,
    _asteroid_is_blacklisted, _blacklist_asteroid, _nearest_asteroid,
    _nearest_copper_asteroid, _copper_priority_active,
    _nearest_huntable_alien, _record_position, _detect_stuck,
    _wall_pin_trap_active, _maybe_force_wall_pin_escape,
    _ship_clear_of_edges, _ship_clear_of_buildings, _do_escape_edge,
    _iron_total, _ship_has_blueprint, _find_home_station,
    _find_basic_crafter, _any_crafter_busy, _station_items, _station_iron,
    _all_blueprints_deposited, _module_already_installed,
    _build_area_clear, _build_seek_direction,
    _consumable_phase_finished, _consumables_in_station_inv,
    _qwi_already_built, _advanced_crafter_already_built,
    _recovery_loadout_ready,
    _qwi_ready_to_build, _find_quick_use_slot,
    _next_craft_target, _next_install_target, _module_swap_plan,
)
from bot_autopilot_movement import (
    _do_idle, _do_goto, _do_hold_distance, _do_spiral_search,
    _do_mine_nearest, _do_attack_nearest, _do_engage_boss, _do_retreat,
    _do_cycle_weapon, _ensure_weapon, execute_intent,
)
from bot_autopilot_actions_station import (
    _act_build_seek, _act_deposit, _act_craft, _act_install, _act_build,
    _act_at_station, _act_equip_consumables, _act_fortify, _act_build_qwi,
    _act_recover_loot, _act_build_nebula, _act_fortify_nebula,
    _act_place_ai_pilot_nebula, _act_build_advanced_crafter,
)
from bot_autopilot_actions_combat import (
    _act_engage, _act_engage_boss, _act_regen, _maybe_use_consumables,
    _act_gather, _act_idle_at_base, _act_warp_to_wormhole,
    _act_warp_traverse, _act_flee_gas, _act_retreat, _gas_cloud_at,
)


# ── Death detection + loot-recovery state machine ────────────────────────
# Moved to bot_autopilot_lifecycle.py.  Re-exported below so existing
# ``bot_autopilot._observe_death_edges`` etc. call sites + tests keep
# working unchanged.
from bot_autopilot_lifecycle import (
    _observe_death_edges,
    _maybe_log_boss_engage_edges,
    _maybe_clear_death_recovery,
    _observe_warp_back_to_main,
    _observe_warp_traverse_arc_complete,
    _observe_gas_lingering,
    _observe_consumable_restock,
)


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
    elif new_state == S_WARP_TO_WORMHOLE:
        # Reset wormhole arrival + progress trackers so a fresh
        # WARP_TO_WORMHOLE arc gets clean timing for both the
        # PR #163 arrival pin-timeout and the 2026-05-23 follow-up
        # no-progress backstop.  Without this a stale ``best_d``
        # from a prior arc would make the no-progress timer think
        # the bot started further away than it actually did.
        _state.warp_wormhole_arrived_at = 0.0
        _state.warp_wormhole_best_d = 0.0
        _state.warp_wormhole_progress_at = 0.0
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


def _docked_for_interaction(state: dict, p: dict) -> bool:
    """True when the bot is in a station-dock interaction state
    (DEPOSIT / CRAFT / INSTALL) AND already within interact range of the
    building it's acting on -- i.e. docked and meant to sit still to fire
    its POST.

    Added 2026-06-07.  The stuck-escape burst must NOT fire here: a
    docked bot is intentionally stationary, so the position watchdog
    reads it as stuck and shoves it off the station, which then drives
    back, thrashing.  The captured S_INSTALL deadlock did exactly this --
    190 stuck_detected events at hs_dist 59-611 over 34 min, zero
    progress.  Only the DOCKED phase is skipped; while still travelling
    to the station the burst keeps protecting against real pins (see the
    skip-set notes in ``_run_stuck_escape``).
    """
    st = _fsm["state"]
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    if st in (S_DEPOSIT, S_INSTALL):
        hs = _find_home_station(state)
        if hs is None:
            return False
        d = math.hypot(float(hs.get("x", 0.0)) - px,
                       float(hs.get("y", 0.0)) - py)
        rng = (INSTALL_INTERACT_RANGE_PX if st == S_INSTALL
               else DEPOSIT_RANGE_PX)
        return d <= rng
    if st == S_CRAFT:
        crafter = _find_basic_crafter(state, idle_only=False)
        if crafter is None:
            return False
        d = math.hypot(float(crafter.get("x", 0.0)) - px,
                       float(crafter.get("y", 0.0)) - py)
        return d <= CRAFT_INTERACT_RANGE_PX
    return False


def _run_stuck_escape(state: dict, p: dict, now: float) -> bool:
    """Stuck-watchdog + escape-burst machine, run once per tick before
    the FSM dispatch.  Returns True when an escape burst was dispatched
    this tick and ``_do_auto`` must return immediately; False to fall
    through into normal state selection.

    If the ship has been pinned against either the world boundary OR a
    station building cluster, this overrides the FSM and heads along the
    local repulsion vector toward open space -- it has to run BEFORE the
    FSM dispatch so it preempts whatever was driving the ship into the
    obstacle.  It records the position sample, runs the wall-pin
    force-escape, then:
      * if an escape burst is already active, keeps driving it until the
        ship clears the edges + buildings, then re-anchors the SEARCH
        spiral at the clear-space landing position;
      * otherwise runs the position/rotation stuck detector (with the
        2026-05-30 edge-pin override for the REGEN / IDLE / RETREAT skip
        states) and, on a fresh stuck, arms the burst, blacklists the
        unreachable target, records the pin-zone anchor, and logs.
    """
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
            return True
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
    # Edge-pin override (2026-05-30): the skip set above keeps the
    # escape burst from firing during intentional idle / spiral /
    # regen parking.  But a GENUINE world-edge pin (ship inside the
    # edge margin, not a spiral-coast false positive) while a threat
    # is adjacent is lethal even in those states -- the 2026-05-30
    # telemetry captured two Nebula deaths in fsm=regen wall-pinned
    # near the map edge, shields collapsing while the watchdog stayed
    # silent because REGEN was in the skip set.  Let the escape fire
    # in REGEN / IDLE_AT_BASE / RETREAT when both conditions hold so
    # the bot peels off the wall instead of bleeding out against it.
    # S_SEARCH stays excluded (its small-radius spiral coast routinely
    # trips the position watchdog in open space, edge or not).
    _edge_pinned = not _ship_clear_of_edges(p, zone)
    _stuck_threat, _stuck_threat_d = nearest(
        state.get("aliens") or [],
        float(p.get("x", 0.0)), float(p.get("y", 0.0)))
    _threatened_pin = (_stuck_threat is not None
                       and _stuck_threat_d < ENGAGE_ENTER_PX)
    _escape_skip_states = (S_SEARCH, S_IDLE_AT_BASE, S_REGEN, S_RETREAT)
    # Docked-interaction skip (2026-06-07): a bot within interact range
    # of the station building it's acting on (DEPOSIT / CRAFT / INSTALL)
    # is meant to sit still and POST -- bursting it off-station just
    # thrashes (the S_INSTALL deadlock logged 190 stuck_detected events
    # doing this).  Still protected while travelling to the station.
    _docked_interacting = _docked_for_interaction(state, p)
    _escape_skipped = (_fsm["state"] in _escape_skip_states
                       or _docked_interacting)
    # Edge-pin + threat overrides the soft skip states so a cornered bot
    # still flees -- but NOT the docked skip: the station umbrella /
    # turret ring defends the dock, and peeling off would re-open the
    # thrash and abandon the in-progress interaction.
    if (_escape_skipped and not _docked_interacting
            and _edge_pinned and _threatened_pin
            and _fsm["state"] != S_SEARCH):
        _escape_skipped = False
    if _detect_stuck() and not _escape_skipped:
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
        # Pin-zone anchor (2026-05-17): every stuck event adds the
        # current ship position to the pin-zone list so the target
        # selectors filter pickups / asteroids near it for the TTL.
        # Generalizes the HUNT-anchor pattern above to all FSM
        # states -- the captured log showed 8 stuck events in 130 s
        # at the same Nebula anchor, but only HUNT had per-anchor
        # giveup logic so ENGAGE/MINE/GATHER kept pulling the bot
        # back via newly-spawned targets in the same cluster.
        _record_pin_zone_anchor(sx, sy, now)
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
        return True
    return False


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

    # Gas-lingering detector (2026-05-19).  Pure telemetry --
    # fires a ``gas_lingering`` event when the bot has been
    # stuck in a damaging gas cloud for too long.  See
    # ``_observe_gas_lingering`` for thresholds + rationale.
    _observe_gas_lingering(state, p, now)

    # Re-arm the post-boss warp cascade if the bot is observed back
    # in MAIN after warp_after_boss_done was already True.  Captured
    # 2026-05-16: bot warped to a warp zone, traversed to Nebula,
    # then wandered into Nebula's central return wormhole and ended
    # up back in MAIN with the latch sticky -- no path out.  See
    # ``_observe_warp_back_to_main`` for the full rationale.
    _observe_warp_back_to_main(state, p, now)

    # Re-arm the consumable craft queue when the bot has run its
    # shield/repair stock dry while operating (not just on the warp-back
    # edge), so it restocks at its next crafter visit.  See
    # ``_observe_consumable_restock`` for the captured pathology (2026-
    # 06-05: ~13 min fought with shield supply = 0).
    _observe_consumable_restock(state, p, now)

    # Emit warp_traverse_arc_completed when the FSM exits S_WARP_TRAVERSE
    # without the action-handler arrival-band branch having fired
    # it (game's auto-zone-transition can preempt the action handler).
    # Captured 2026-05-17: bot crossed WARP_GAS to y=6352, FSM
    # transitioned warp_traverse -> search via zone change, no
    # arc_completed event ever fired.  See
    # ``_observe_warp_traverse_arc_complete`` for the rationale.
    _observe_warp_traverse_arc_complete(state, p, now)

    # Stuck watchdog: if the ship has been pinned against either the
    # world boundary OR a station building cluster, override the FSM
    # and head along the local repulsion vector toward open space.
    # Runs (and may dispatch an escape burst) BEFORE the FSM dispatch so
    # it preempts whatever was driving the ship into the obstacle.  Full
    # machine -- active-escape drive, edge-pin override, blacklisting,
    # pin-zone anchoring -- lives in ``_run_stuck_escape``.
    if _run_stuck_escape(state, p, now):
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
                       S_EQUIP_CONSUMABLES, S_FORTIFY, S_FORTIFY_NEBULA,
                       S_PLACE_AI_PILOT_NEBULA, S_BUILD_ADV_CRAFTER,
                       S_BUILD_QWI, S_WARP_TO_WORMHOLE,
                       S_WARP_TRAVERSE, S_FLEE_GAS, S_RETREAT) or \
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
        _act_regen(state, p)
    elif cur == S_MINE:
        _do_mine_nearest(state, p)
    elif cur == S_BUILD:
        _act_build(state, p)
    elif cur == S_BUILD_NEBULA:
        _act_build_nebula(state, p)
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
    elif cur == S_FORTIFY_NEBULA:
        _act_fortify_nebula(state, p)
    elif cur == S_PLACE_AI_PILOT_NEBULA:
        _act_place_ai_pilot_nebula(state, p)
    elif cur == S_BUILD_ADV_CRAFTER:
        _act_build_advanced_crafter(state, p)
    elif cur == S_BUILD_QWI:
        _act_build_qwi(state, p)
    elif cur == S_RECOVER_LOOT:
        _act_recover_loot(state, p)
    elif cur == S_WARP_TO_WORMHOLE:
        _act_warp_to_wormhole(state, p)
    elif cur == S_WARP_TRAVERSE:
        _act_warp_traverse(state, p)
    elif cur == S_FLEE_GAS:
        _act_flee_gas(state, p)
    elif cur == S_RETREAT:
        _act_retreat(state, p)
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
