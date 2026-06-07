"""Tuning constants for ``bot_autopilot``.

Extracted from ``bot_autopilot.py`` in the 2026-05-24 PR 6 refactor.
This module holds the 1000+ lines of FSM hysteresis bands, boss-
fight tuning, state constants, craft-phase thresholds, stuck/
potential-field tuning, etc.  ``bot_autopilot.py`` does
``from bot_autopilot_tuning import *`` so every constant remains
accessible as ``bot_autopilot.CONSTANT_NAME`` (and through the
``_ap.CONSTANT_NAME`` qualified-attribute pattern used by the
helper modules).

Pulled out because the constants block had grown to ~40 % of
``bot_autopilot.py`` and was the single biggest barrier to
navigating the orchestrator -- every fix that touched a tuning
value scrolled past hundreds of unrelated definitions to find
the right place.  No behavioural change; this is a pure
relocation.
"""
from __future__ import annotations

import math

import bot_autopilot_blacklist as _bl
import bot_autopilot_navigation as _nav


# ── Hysteresis thresholds ─────────────────────────────────────────────────

ENGAGE_ENTER_PX: float = 800.0
ENGAGE_EXIT_PX:  float = 1000.0
# Warp-zone swarm gate (2026-05-19).  When the bot is in a warp
# zone (e.g. WARP_ENEMY with its 4 spawners) and the alien count
# exceeds this threshold, suppress ENGAGE preemption so the
# cascade falls through to a movement-capable state (WARP_TRAVERSE
# / BUILD_NEBULA / MINE / GATHER) instead of kiting one alien
# while ~20 others swarm.  Combat assist (the in-process auto-aim
# + fire hook) keeps firing at the closest threat each frame, so
# the bot still defends itself -- only the FSM-level "stop and
# fight" diversion is suppressed.  Captured 2026-05-19 telemetry:
# 4 ENGAGE deaths in WARP_ENEMY in one session, shields 120 -> 0
# in 5-7 s each, aliens_count 20-22 in every case.
#
# Broadened 2026-05-23 v3 from warp-only to all non-MAIN zones.
# Captured pathology: bot warped post-boss to ZONE2 (Nebula)
# with 48 aliens, no Nebula HS yet, pinned in a 870x800 px kite
# box for 500+ s, burned 23 repair packs to stay alive at ~35 HP.
# MAIN is the only zone where ENGAGE's diversion is safe (HS
# umbrella + station shield + fortify turrets layer on top of
# the bot's kite).  Outside MAIN, falling through to a productive
# state (MINE / BUILD_NEBULA / etc.) is strictly safer.  Name
# kept as ``WARP_SWARM_ENGAGE_SUPPRESS_ALIENS`` for backward-
# compat with existing tests; gate is now "outside-base"
# semantically.
WARP_SWARM_ENGAGE_SUPPRESS_ALIENS: int = 8
# Outside-base swarm REGEN suppression (2026-05-23, broadened
# 2026-05-23 v2).  Same intent as the ENGAGE suppression above
# (PR #155), applied to REGEN.  REGEN's action is _do_idle (no
# thrust) -- safe and recovery-positive while sitting under the
# home-station umbrella where shields regen faster than incoming
# damage.  But in a WARP_ENEMY / ZONE2 / STAR_MAZE swarm with
# no HS umbrella, idling is a death sentence.
#
# Originally gated on ``"WARP" in zone_id`` (PR #162).  The
# 2026-05-23 v2 cycle captured 29 REGEN deaths in a row at
# ~(3975, 4250) -- some in WARP_ENEMY but at least some in
# ZONE2 / Nebula or STAR_MAZE where MazeSpawner / Nebula
# spawners produce comparable swarm density.  Broadened to fire
# in any zone except MAIN: MAIN is the only zone with the HS
# umbrella + station shield-regen that makes REGEN's idle
# recovery actually work.
#
# Name kept as ``WARP_SWARM_REGEN_SUPPRESS_ALIENS`` to preserve
# backward-compat with existing test references; the actual gate
# is "not MAIN" now (see ``bot_autopilot_choose.py``).
WARP_SWARM_REGEN_SUPPRESS_ALIENS: int = 8
GATHER_ENTER_PX: float = 1500.0
GATHER_EXIT_PX:  float = 1700.0
# Tighter GATHER-preempts-MINE threshold (2026-05-30).  GATHER sits
# above MINE in the cascade, so any pickup within GATHER_ENTER_PX
# (1500) yanks the bot off an asteroid it is actively mining.  The
# 2026-05-30 telemetry logged 254 mine<->gather flips (105 under
# 3 s) -- mine an asteroid, it drops iron, divert to gather, the
# next chunk drops, flip back.  When already mining, require the
# pickup to be genuinely close before abandoning the asteroid; the
# loot stays on the field and gets gathered once the asteroid is
# spent.  Open-state (non-MINE) entry still uses the wide 1500 px
# gate so the bot doesn't ignore reachable loot while idle.
GATHER_ENTER_WHILE_MINING_PX: float = 600.0
# Symmetric MINE-preempts-GATHER threshold (2026-06-02).  The mirror of
# GATHER_ENTER_WHILE_MINING_PX: while the bot is actively GATHERing,
# only an asteroid within this radius preempts to MINE, instead of the
# full MAX_ASTEROID_CHASE_PX (2000) cap.  The 2026-06-02 telemetry
# logged 287 dwell-suppressed gather->mine transitions -- finishing a
# gather darted the bot to a mid-range asteroid, which then dropped iron
# and pulled it back.  Other states keep the full chase cap so an idle
# bot still commits to a reachable asteroid.
MINE_ENTER_WHILE_GATHERING_PX: float = 600.0
REGEN_ENTER_PCT: float = 0.40
REGEN_EXIT_PCT:  float = 0.60
# Boss-alive REGEN thresholds (2026-05-13 fourteenth telemetry pass).
# When a boss is alive, regen further before re-engaging so the bot
# doesn't repeat the death-loop captured in the log: post-recovery
# install → engage_boss fired at shields=54/120 (45 %), one lure
# trigger later (35 %), then died.  At 70 % enter / 85 % exit the
# bot pauses longer when boss is out of immediate threat range.
# The existing REGEN escape valve (exit when threat < ENGAGE_ENTER_PX)
# still applies, so boss-in-laser-range still gets engaged.
REGEN_ENTER_PCT_BOSS_ALIVE: float = 0.70
REGEN_EXIT_PCT_BOSS_ALIVE:  float = 0.85
# Nebula REGEN thresholds (2026-05-24, post-PR #184 telemetry).
# Captured: second death of the post-merge session was in
# fsm=regen at (5407, 4511) in ZONE2 -- the bot tried to recover
# under fire in the Nebula and lost the damage-vs-regen trade.
# Mirrors the boss-alive pattern: when outside the MAIN-zone HS
# umbrella, regen further before re-engaging so a brief damage
# spike doesn't kick the bot back out at 60 % shields with the
# swarm still pressing.  The existing REGEN escape valve (exit
# when threat < ENGAGE_ENTER_PX after the no-progress timer
# fires) still applies, so a close threat still gets engaged.
REGEN_ENTER_PCT_NEBULA: float = 0.55
REGEN_EXIT_PCT_NEBULA:  float = 0.85
# S_RETREAT thresholds (2026-05-30).  The defensive flee fires in a
# non-MAIN zone when shields fall to RETREAT_ENTER_SHIELD_PCT of max
# AND at least RETREAT_SWARM_ALIEN_COUNT aliens sit within
# RETREAT_SWARM_RANGE_PX AND the bot has no shield_recharge in its
# quick-use slots (so the armed heal latch can't actually fire).
# Hysteresis: once retreating, hold until shields climb back above
# RETREAT_EXIT_SHIELD_PCT so a brief regen tick under fire doesn't
# kick the bot straight back into the swarm.  The enter threshold is
# higher than the Nebula REGEN enter (0.55) on purpose -- when the
# bot is defenceless (no consumables) it should peel off earlier,
# before the swarm grinds it into the fatal sub-20 % band the
# telemetry captured.  Range matches the consumable swarm radius so
# the two density gates agree on what "surrounded" means.
RETREAT_ENTER_SHIELD_PCT: float = 0.60
RETREAT_EXIT_SHIELD_PCT:  float = 0.85
RETREAT_SWARM_ALIEN_COUNT: int   = 6
RETREAT_SWARM_RANGE_PX:    float = 1200.0
# How far past the bot (along the swarm-centroid -> bot ray) the
# no-HS retreat target sits.  Large enough to clear the swarm's
# engage band in one goto; clamped to the world rect by the handler.
RETREAT_FLEE_TARGET_PX:    float = 1400.0
# Max home-station distance at which RETREAT marches to the HS umbrella
# instead of fleeing the swarm centroid (2026-06-01).  Captured: the
# bot in ZONE2 retreating toward an HS 4200 px away across a 46-alien
# swarm -- it never reached the umbrella and thrashed engage<->retreat
# at 0-5/120 shields until it died.  Beyond this distance the umbrella
# is unreachable through the swarm, so breaking contact (centroid flee)
# is the only survivable move; within it the umbrella's shield + HP
# regen + turret ring is worth the drive.
RETREAT_HS_MAX_DIST_PX:    float = 2200.0
# Critical-shield floor (2026-06-01).  Normally a ready shield_recharge
# consumable suppresses RETREAT (the bot can fight + heal instead of
# fleeing).  But the 2026-06-01 telemetry showed a flickering consumable
# releasing RETREAT into a fatal re-engage at near-zero shields under a
# 46-alien swarm.  Below this floor RETREAT fires regardless of
# consumable: a single heal can't outpace swarm DPS at ~0 shields, so
# breaking contact wins.  Well under RETREAT_ENTER_SHIELD_PCT (0.60) so
# a properly-kitted bot still fights + heals in the normal band.
RETREAT_CRITICAL_SHIELD_PCT: float = 0.25
# Widened swarm-detect radius for RETREAT (2026-06-02).  The base
# RETREAT_SWARM_RANGE_PX (1200) gate released RETREAT the moment the
# bot drifted just past the swarm -- captured an engage<->regen thrash
# at 0/120 shields with the swarm strung out at ~1300-1800 px (so <6
# within 1200) that ended in death.  Use this wider radius when ALREADY
# retreating (hysteresis -- stay committed until genuinely clear) OR
# when shields are critical (commit to the flee even if the swarm has
# drifted out, because at near-zero shields it WILL re-converge).
RETREAT_SWARM_RANGE_EXIT_PX: float = 1800.0
# ZONE2 swarm tether (2026-06-02).  When the bot is in ZONE2 farther
# than this from its Home Station AND a dense swarm is adjacent, stop
# seeking resources / aliens deeper and head home instead.  Captured: 20
# edge-stucks while ENGAGE + 2 deaths fighting 55-60 aliens 2500-4600 px
# from the HS -- the bot roamed deep into a persistent swarm chasing
# loot/asteroids/aliens with no win condition.  Set beyond
# RETREAT_HS_MAX_DIST_PX (2200) so the bot still operates in a generous
# radius around base; the tether only fires far out AND under a swarm.
ZONE2_TETHER_DIST_PX:       float = 2800.0
# Tighter tether when the bot has NO shield_recharge equipped (2026-06-06
# evening).  Captured: the bot ran out of shield heals, then died in a
# 4-death spiral far from base (hs_dist 2200-6182) with no way to
# recover -- without a heal it can't survive the ZONE2 swarm out in the
# open.  When unhealed, tether much closer to the HS umbrella (turrets +
# station shield do the surviving) instead of the generous 2800 px
# operating radius.  Still only fires under a dense swarm.
ZONE2_TETHER_UNHEALED_DIST_PX: float = 1500.0
# Tighter tether while the bot is REBUILDING its loadout after a death
# (2026-06-06 evening).  Captured in the same 4-death spiral: each death
# dropped the Nebula modules (misty_step / force_wall / death_blossom)
# AND the broadside, leaving them queued in ``queue.modules_to_install``;
# the bot then re-engaged the swarm half-equipped -- no modules, often no
# heal -- and died again before it ever got back to the crafter to
# re-install.  While modules are pending, keep the bot close to the HS
# umbrella so it actually completes the re-install instead of roaming off
# under-gunned.  Independent of the heal check above -- the bot can be
# topped up on heals yet still be missing every combat module.
ZONE2_TETHER_RECOVERING_DIST_PX: float = 1500.0
# Nebula AI Pilot ship cost gate (2026-05-24).  Mirrors the
# ``BUILDING_TYPES["Basic Ship"]`` cost (500 iron + 250 copper at
# default character rates) plus a small headroom so the placement
# POST doesn't drop the station below operating reserves.  The
# bot waits at the station mining + crafting until both buffers
# are met before triggering ``S_PLACE_AI_PILOT_NEBULA``.
AI_PILOT_SHIP_IRON_COST:   int = 600
AI_PILOT_SHIP_COPPER_COST: int = 300
# Advanced Crafter cost gate (2026-05-25).  Mirrors
# ``BUILDING_TYPES["Advanced Crafter"]`` (1000 iron + 500 copper at
# default character rates).  The trigger waits until the station
# can cover this AND the ``advanced_crafter`` blueprint has been
# deposited.  Without the blueprint the building menu rejects the
# placement, so the choose-cascade short-circuits early to keep
# the bot from looping S_BUILD_ADV_CRAFTER -> idle.
ADVANCED_CRAFTER_IRON_COST:   int = 1000
ADVANCED_CRAFTER_COPPER_COST: int = 500
# Advanced (Nebula-tier) modules the bot installs on the player
# ship when they appear in ZONE2 station inventory.  Order is
# rough installation priority: misty_step first (gas escape is
# the highest-impact buff), then force_wall (defensive), then
# death_blossom (offensive utility).  ai_pilot is omitted on
# purpose -- it belongs on a parked ship via the Nebula AI Pilot
# pipeline (see ``place_ai_pilot_ship_at_home``), not the player's
# loadout.
NEBULA_ADVANCED_MODULES: tuple[str, ...] = (
    "misty_step", "force_wall", "death_blossom")
# Target ship loadout once an Advanced Crafter exists (2026-06-02).  The
# ship has only MODULE_SLOT_COUNT (4) slots and the MAIN loadout
# (MODULE_INSTALL_QUEUE) fills all four, so the three Nebula modules
# could never be installed -- a crafting dead-end (no uninstall path).
# This is the preferred 4-slot set in the Nebula: the three advanced
# modules plus ``broadside`` for kill throughput against the swarm.  The
# swap planner (``_module_swap_plan``) uninstalls any installed module
# NOT in this set to make room for a queued advanced module, and never
# uninstalls a module that IS in this set.  Retune freely -- e.g. swap
# ``broadside`` for ``shield_booster`` / ``armor_plate`` to favour
# survivability over offense.
NEBULA_TARGET_LOADOUT: tuple[str, ...] = (
    "death_blossom", "force_wall", "misty_step", "broadside")
# Advanced (Nebula-tier) consumable craft targets.  Each entry
# maps the MODULE_TYPES craft key (what gets queued in
# ``modules_to_craft``) to a (item_key, target_stockpile) tuple,
# where ``item_key`` is the produced item that lands in station
# inventory and ``target_stockpile`` is how many of that item the
# bot tries to keep on hand.  When station-inv count of item_key
# meets the target, the queue head pops (so a single craft cycle
# doesn't spin forever on a consumable that doesn't produce
# ``mod_<key>``).  Used by the housekeeping auto-queue observer
# and by ``_next_craft_target``'s auto-pop guard.
NEBULA_ADV_CONSUMABLE_TARGETS: dict[str, tuple[str, int]] = {
    "homing_missile": ("missile", 20),
    "mining_drone":   ("mining_drone", 5),
    "combat_drone":   ("combat_drone", 5),
}
# REGEN escape-valve hysteresis (2026-05-13 fifteenth telemetry pass).
# The previous escape-valve fired on a SINGLE tick where shields
# didn't gain (``sh > last_regen_shields`` was False).  Captured in
# the log: bot at station regenerating, shields 50 → 68 over 12 s
# (net +18, clearly recovering), but a brief damage spike on one
# tick made shields_recovering=False and the valve fired -- bot
# exited REGEN into recover_loot mid-attack and died 3 more times.
# Require N seconds of sustained no-progress before the valve fires.
REGEN_NO_PROGRESS_TIMEOUT_S: float = 1.5
# REGEN escape-valve fast-drop shortcut (2026-05-14 eighteenth pass).
# The 1.5 s hysteresis above prevents single-tick flicker, but it
# leaves a window where the bot dies if the boss grinds shields
# faster than the regen rate.  Captured pathology: bot recovered
# 53 → 60 shields, then boss did 59 points of damage in 5 s while
# the 1.5 s no-progress timer kept rolling forward (each tiny gain
# tick reset it).  Bot reached 1 shield before exiting REGEN, died
# in recover_loot 300 ms later.  Fix: if shields have dropped by
# more than ``REGEN_FAST_DROP_PX`` from the high water mark while
# threatened, fire the escape valve immediately (bypass the
# 1.5 s timer).  A 20-point drop within the 1.5 s window means
# damage rate exceeds regen rate by ~13 pts/s — REGEN is losing.
REGEN_FAST_DROP_PX: float = 20.0
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

# Boss CHARGE panic-escape (2026-05-13 thirteenth telemetry pass).
# When the bot is dangerously close to the boss AND a charge is
# winding up, the standard ``BOSS_DODGE_PERP_PX`` perpendicular
# displacement is dominated by the kite/lure target vector
# (which can be 2700 px away when lure-mode is active).  Net
# result: the bot drifts ALONGSIDE the boss instead of escaping
# perpendicular to its dash line -- thirteenth-pass log captured
# 28 dodge events all at ``boss_dist=143 px`` over 1.9 s of a
# Phase 2 charge windup, the bot stuck inside collision range.
#
# Fix: when boss_dist < ``BOSS_CHARGE_PANIC_DIST_PX`` and the
# boss is charging (windup > 0 OR currently dashing), OVERRIDE
# the kite target with a point ``BOSS_CHARGE_PANIC_ESCAPE_PX``
# from the boss along the boss->bot ray.  Bot heads directly
# away from boss -- doesn't matter what the long-range kite
# target was, the short-range escape vector dominates while
# the panic condition holds.  Releases when boss_dist >=
# BOSS_CHARGE_PANIC_DIST_PX so the bot re-engages the standard
# kite + perpendicular dodge once it has breathing room.
BOSS_CHARGE_PANIC_DIST_PX:    float = 300.0
BOSS_CHARGE_PANIC_ESCAPE_PX:  float = 600.0

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

# HS-loss flee target (2026-05-14 eighteenth-pass).  When the home
# station is destroyed mid-fight (boss took it out) AND a boss is
# still alive, REGEN's default ``_do_idle`` parks the bot in
# the boss's aggro range -- in the captured log the bot took 12
# deaths in 60 s after HS destruction.  When no HS exists, the
# REGEN action handler instead drives the bot ``BOSS_FLEE_TARGET_PX``
# away from the boss (clamped to the world).  Shields recover en
# route to the edge instead of standing still inside the kill zone.
BOSS_FLEE_TARGET_PX:          float = 2000.0
# Gas-cloud escape margin in REGEN (2026-05-15).  When ``_act_regen``
# detects that the bot is sitting inside a gas cloud, it drives
# along the cloud-centre -> bot ray to a point this far past the
# cloud edge so the bot ends up clear of the damage field, not
# hugging it.  Captured pathology: bot parked at (2986, 5750) in
# the Nebula for 30+ s with shields stuck at 1-2/120; gas damage
# matched the regen rate, so passive recovery never completed.
REGEN_GAS_ESCAPE_MARGIN_PX:   float = 200.0
# Home-station drive radius for REGEN (2026-05-23).  When REGEN
# fires and an HS exists in the current zone, drive the bot to
# within the game-side healing umbrella (``REPAIR_RANGE = 300 px``
# from constants.py) so shield regen gets the
# ``REPAIR_SHIELD_BOOST`` bonus AND HP regen activates -- both
# only happen inside the umbrella.  Captured pathology: bot sat
# in REGEN for 120 s wherever shields dropped (typically 1000+
# px from HS), passively regenerating at the slow base rate
# while the umbrella was a quick drive away.
#
# Trigger radius (250) is slightly INSIDE the umbrella radius
# (300) so the bot drives to a comfortable interior point and
# can't be bumped out of the umbrella by a single tick of
# repulsion.  The exit hysteresis (when to start driving again
# after exiting REGEN) is handled by the regen exit threshold
# itself -- once shields recover, FSM leaves REGEN and the
# drive logic doesn't reapply.
REGEN_HS_DRIVE_RADIUS_PX:     float = 250.0
REGEN_HS_DRIVE_STOP_PX:       float = 100.0
# FLEE_GAS exit hysteresis (2026-05-18 follow-up to S_FLEE_GAS).
# Once the bot enters S_FLEE_GAS we need the choose function to
# hold the state until the bot is CLEARLY past the cloud edge --
# not just one pixel past the boundary.  Without this, the bot
# exits the boundary on one tick, WARP_TRAVERSE / ENGAGE / etc
# resumes its goal-directed drive, and the bot re-enters the same
# or an adjacent cloud on the next tick.  Telemetry captured 17
# FLEE_GAS <-> WARP_TRAVERSE flips in one session, one with 93 ms
# dwell, costing 52 shields per ~2 s thrash cycle.  Chosen smaller
# than ``REGEN_GAS_ESCAPE_MARGIN_PX`` (200) so the action
# handler's ``_do_goto`` target sits a clear buffer past the
# hysteresis exit -- the bot commits to fully crossing the
# boundary before the state releases.
FLEE_GAS_EXIT_MARGIN_PX:      float = 100.0
# FLEE_GAS cluster-escape distance (2026-05-19 follow-up).  The
# action handler drives this far along the net gas-repulsion vector
# (summed across every cloud within ``GAS_REPULSION_RANGE_PX``) so
# a single goto clears the whole local cluster instead of just
# hugging one cloud's edge.  Captured pathology: in WARP_GAS the
# bot ping-ponged FLEE_GAS / REGEN / FLEE_GAS at (2250-2370,
# 4180-4250) for 16 s while shields drained ~100 px -- escaping
# cloud A only dropped the bot inside adjacent cloud B.  Chosen
# larger than the typical cloud diameter so the escape ray
# crosses any adjacent cluster on the way out.
FLEE_GAS_CLUSTER_ESCAPE_PX:   float = 600.0
# Gas-lingering telemetry thresholds (2026-05-19).  Fire a
# ``gas_lingering`` event when the bot has been continuously inside
# a gas cloud for ``GAS_LINGER_DETECT_S`` seconds AND has lost
# at least ``GAS_LINGER_DAMAGE_PX`` of shields + hp combined since
# the entry edge.  Pure observability -- doesn't drive any behaviour.
# Makes the "stuck in a cloud bleeding out" pathology visible
# directly instead of forcing the operator to cross-reference
# state_transition timestamps and shield deltas by hand (which is
# how we caught the FLEE_GAS thrash in PR #148 and the
# consumable over-firing in PR #151).
#
# 3.0 s is comfortably longer than the bot SHOULD need to drive
# out of any cloud (cloud_radius is typically a few hundred px,
# bot speed is several hundred px/s).  20 px loss covers about
# 4 ticks of gas damage; anything below that is plausibly a
# transit through a small cloud.  One event per linger episode
# (throttled by the ``gas_linger_event_fired`` latch, reset on
# exit).
GAS_LINGER_DETECT_S:          float = 3.0
GAS_LINGER_DAMAGE_PX:         int   = 20
# Boss-camping-death-pos danger radius for recover_loot suppression.
# If the boss is within this distance of ``death_recovery_pos``,
# entering S_RECOVER_LOOT walks the bot into the boss's range and
# kills the respawn before any loot can vacuum.  Captured pathology:
# 7 deaths in 17 s at (3170-3225, 3180-3210) -- the bot kept routing
# back into the same death pile while the boss hovered there.
RECOVER_LOOT_BOSS_DANGER_PX:  float = 1000.0

# Warp-zone traversal targets (2026-05-15).  After the post-boss
# warp, drive the bot to the top of the warp zone so the game's
# edge-collision auto-transition fires.  The exit is triggered
# when ``player.center_y > world_height - EXIT_THRESHOLD`` where
# ``EXIT_THRESHOLD = 50`` (zones/zone_warp_base.py).  The target
# sits 10 px from the top edge so ``_do_goto`` keeps driving the
# bot north all the way into the exit band; the arrival latch
# fires once the bot is INSIDE that band (within EXIT_THRESHOLD
# of the top edge) so the bot doesn't latch done before crossing
# the zone-transition line.
#
# 2026-05-15 follow-up: the original constants (margin=250,
# arrival=150) latched warp_traverse_done at y >= 6000 in a
# 6400-tall warp zone -- 350 px short of the actual exit at
# y > 6350.  Bot then spiralled in SEARCH near the top without
# crossing the trigger.  Companion fix in navigation.py disables
# the north-edge boundary repulsion in warp zones so the bot
# can actually reach the top edge.
WARP_TRAVERSE_MARGIN_PX:      float = 10.0
WARP_TRAVERSE_ARRIVAL_PX:     float = 50.0
# Wormhole-arrival pin timeout (2026-05-23).  When the bot has been
# within ``WARP_TO_WORMHOLE_STOP_RADIUS_PX`` of its target wormhole
# for this many seconds without the game's auto-warp collision (100
# px) firing, the action handler latches ``warp_after_boss_done``
# and releases so the FSM cascade picks something else.  Captured
# pathology: 19 stuck_detected events over 63 s at exactly
# (3310, 4167); bot reached the wormhole goto target, ``_do_goto``
# released all keys, but the game-side warp didn't fire.  Without
# this timeout the bot pings stuck-detect every ~3 s but the
# escape bursts get undone by the next ``_act_warp_to_wormhole``
# call re-asserting the stop.  5 s is comfortable headroom for any
# legitimate first-frame race between bot arrival + game-side
# collision-check tick.
WARP_TO_WORMHOLE_STOP_RADIUS_PX: float = 50.0
WARP_TO_WORMHOLE_PIN_TIMEOUT_S: float = 5.0
# No-progress backstop (2026-05-23 follow-up to PR #163).  When the
# bot has been in WARP_TO_WORMHOLE for this many seconds without
# meaningfully decreasing its nearest-wormhole distance, abandon
# the attempt -- same latch as the arrival pin-timeout, second
# activation path.  Catches the en-route stuck case PR #163 misses:
# bot can't reach the wormhole because of boundary repulsion /
# building geometry / etc., so ``nearest_d`` never drops below
# ``WARP_TO_WORMHOLE_STOP_RADIUS_PX`` and the arrival timer never
# arms.  Captured 2026-05-23 pathology: 7 stuck_detected events
# at (582, 1347), 18 s duration, hs_dist=4220 (near west world
# edge) -- bot was orbiting at the boundary repulsion radius
# never reaching the wormhole.  15 s is long enough that
# legitimate long-haul transits (with steered_heading bending
# around buildings) get to complete; 50 px is the minimum
# decrease that counts as "actual progress" (filters out
# sub-cell wobble from boundary repulsion oscillation).
WARP_TO_WORMHOLE_NO_PROGRESS_TIMEOUT_S: float = 15.0
WARP_TO_WORMHOLE_PROGRESS_THRESHOLD_PX: float = 50.0
# Lateral-detour timeout (2026-05-17): when ``_act_warp_traverse``
# fails to advance the bot's max y over the current arc for this
# many seconds, the action switches target_x from the world centre
# to alternating wall margins so the bot routes around the
# obstructing gas cloud / asteroid cluster blocking the centre
# column.  Captured pathology: bot oscillated traverse → regen →
# traverse → regen for 590 s in WARP_GAS, never advancing past
# y=2670 because a gas cloud sat dead-centre on the path and
# gas_repulsion alone wasn't strong enough to deflect the
# attraction vector aimed at the top edge.  25 s timeout gives
# normal arcs (typically 20-25 s end-to-end) headroom to finish
# without firing the detour.
WARP_TRAVERSE_DETOUR_TIMEOUT_S: float = 25.0
# Detour expiry threshold (2026-05-17 follow-up to PR #133): once
# the bot's max y advances this many pixels past the y at which the
# detour was committed, the obstacle is considered bypassed and the
# detour side resets to 0 (target back to centre).  500 px is wider
# than typical gas-cloud diameter (~80-200 px) so we exit the
# detour cleanly past the obstacle, not while still hugging it.
WARP_TRAVERSE_DETOUR_CLEAR_PX:  float = 500.0
# Meaningful-progress threshold (2026-05-17 follow-up to PRs #133
# + #134): a max_y advance must exceed this many pixels past the
# last "committed" y before the no-progress timer resets.  Without
# this gate, a bot inching forward 3-50 px each traverse cycle (the
# captured WARP_GAS pathology) keeps deferring the detour timer
# forever.  200 px is half the 500-px DETOUR_CLEAR_PX so a single
# meaningful advance contributes to both the detour timer and the
# clear-check without one starving the other.
WARP_TRAVERSE_MEANINGFUL_PROGRESS_PX: float = 200.0
# Outcome threshold for the FSM-exit observer (2026-05-17): when
# the bot's max_y reaches this many pixels (~85% of typical
# 6400-px warp-zone height) the arc is reported as ``crossed``;
# otherwise ``interrupted`` (the FSM was preempted by ENGAGE,
# REGEN, death, etc. before reaching the top edge).
WARP_TRAVERSE_CROSSED_MAX_Y_PX: float = 5440.0

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
# Shield-heal arm threshold.  Bumped 0.20 -> 0.35 after the
# 2026-05-30 telemetry: three Nebula deaths where the shield heal
# armed at <= 20 % (sh=18/12 of 120) but the bot died within ~1 s --
# at the ~37 sh/s drain a 50/60-alien swarm inflicts, 20 % is only
# ~0.65 s of buffer, too little for the 1 s autopilot tick + 100 ms
# heal-land latency to matter.  35 % gives ~1.9 s of headroom.
CONSUMABLE_USE_SHIELD_PCT:    float = 0.35   # use shield recharge at <= 35 % shields
# Swarm-elevated shield-heal arm threshold (2026-05-30).  When the
# bot is surrounded (>= CONSUMABLE_SWARM_ALIEN_COUNT aliens within
# CONSUMABLE_SWARM_RANGE_PX) the incoming DPS is high enough that
# even 35 % drains before the heal lands, so arm the latch earlier.
# Still below the 0.70 disarm band so a single charge from this
# threshold lands in a safe state without a double-spend.
CONSUMABLE_USE_SHIELD_SWARM_PCT: float = 0.55
CONSUMABLE_SWARM_ALIEN_COUNT:    int   = 6
CONSUMABLE_SWARM_RANGE_PX:       float = 1200.0
# Disarm thresholds (2026-05-19): one consumable lifts the bar by
# 50 % of max, so a single use from the 20-30 % arm threshold lands
# at 70-80 % -- already a safe band.  Pre-fix the latches disarmed
# only at 100 %, which made the auto-use loop fire a second (and
# sometimes third) consumable during the next 1 s cooldown window
# to "top off" the bar to full.  Captured 2026-05-18 telemetry:
# 32 heal_shield_fire events but only 16 heal_shield_arm events
# (and 44 / 22 for HP) -- the bot was burning 2x consumables per
# drop event.  Disarming at ~70 % preserves the original "fire
# again under sustained damage" behaviour (damage below the arm
# threshold re-arms naturally) while capping the single-event
# spend at one charge.
CONSUMABLE_DISARM_HP_PCT:     float = 0.70   # release HP latch at >= 70 % HP
CONSUMABLE_DISARM_SHIELD_PCT: float = 0.70   # release shield latch at >= 70 % shields
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
# S_WARP_TO_WORMHOLE (2026-05-15): after the bot kills the
# main-zone boss AND completes recovery + module installs +
# consumable equipping, route to the nearest wormhole and warp
# into one of the four warp zones.  Per spec, the bot doesn't
# pre-pick a destination -- whichever wormhole is closest wins.
# The gas warp zone gets gas-area repulsion in the navigation
# layer so the bot can avoid the toxic clouds once it lands.
S_WARP_TO_WORMHOLE  = "warp_to_wormhole"
# S_WARP_TRAVERSE (2026-05-15): once the bot has warped into a
# warp zone, drive to the far side of the map (entry_side is
# "bottom" so the goal is the top y edge).  Gas / building /
# boundary repulsion in steered_heading deflects around obstacles
# on the way.  Defensive states (REGEN, ENGAGE on close threats)
# still preempt -- this is a high-level navigation goal, not a
# bulldozer.  Latches ``warp_traverse_done`` when the bot reaches
# the far-side margin so the FSM falls through to the regular
# cascade afterward.
S_WARP_TRAVERSE     = "warp_traverse"
# S_BUILD_NEBULA (2026-05-23): mirror of S_BUILD for ZONE2 / Nebula.
# Buildings are zone-scoped (each zone stashes its own
# ``building_list``), so the ``Home Station`` max=1 cap is per-zone
# -- the bot can legitimately have a MAIN HS + a Nebula HS without
# conflicting.  Reuses the existing ``/build_starter_base`` endpoint
# (which places at the player's current position) so the Nebula
# base lands wherever the bot is when this state fires.  Gated by
# its own ``nebula_build_done`` latch independently of the MAIN
# ``build_done`` latch.  Falls below MAIN's S_BUILD in the priority
# cascade -- if the bot is somehow in ZONE2 without a MAIN base
# yet, build MAIN first.
S_BUILD_NEBULA      = "build_nebula"
# S_FORTIFY_NEBULA (2026-05-24): mirror of S_FORTIFY for the Nebula
# HS.  Fires once the bot has built the Nebula starter base AND
# station inventory has enough iron to cover FORTIFY_IRON_COST.
# Re-uses ``bot_builder.fortify_base_defenses`` (which anchors on
# the first Home Station in the current zone's ``building_list``,
# so calling it while the bot is in ZONE2 fortifies the Nebula HS).
# Latches into ``BotState.nebula_fortify_done`` on success.
S_FORTIFY_NEBULA    = "fortify_nebula"
# S_PLACE_AI_PILOT_NEBULA (2026-05-24): place a Basic Ship with the
# AI Pilot module installed next to the Nebula HS, so the bot has
# a friendly-fire-immune second DPS source while it fights the
# swarm.  Same anchor pattern as S_FORTIFY_NEBULA -- fires once
# the Nebula fortify ring is up + station inventory has the
# ai_pilot module + iron / copper budget.  Latches into
# ``BotState.nebula_ai_pilot_placed`` on success.
S_PLACE_AI_PILOT_NEBULA = "place_ai_pilot_nebula"
# S_BUILD_ADV_CRAFTER (2026-05-25): place an Advanced Crafter near
# the Nebula HS so the bot can craft Nebula-tier modules
# (misty_step / force_wall / death_blossom) locally instead of
# warping back to MAIN for every craft.  Latches into
# ``BotState.nebula_advanced_crafter_done`` on success.  Fires
# after the Nebula fortify ring + AI pilot ship are in place,
# gated on the ``advanced_crafter`` blueprint sitting in station
# inventory + 1000 iron / 500 copper budget.
S_BUILD_ADV_CRAFTER = "build_adv_crafter"
# S_FLEE_GAS (2026-05-18): bot is inside a damaging gas cloud --
# drive out before doing anything else.  Captured pathology: bot
# in S_ENGAGE at (3823, 3089) in WARP_GAS, shields drained 18 -> 0
# over 3 s of stuck_detected events while fighting an alien inside
# the same cloud.  Pre-fix the only gas-escape lived inside
# ``_act_regen``, so any non-REGEN state happily idled in the
# damage field.  S_FLEE_GAS preempts every productive state
# (ENGAGE, MINE, GATHER, HUNT, ENGAGE_BOSS, WARP_TRAVERSE, ...)
# but defers to S_REGEN, which already has its own gas-escape
# branch and is the more urgent shield-collapse signal.
S_FLEE_GAS          = "flee_gas"
# S_RETREAT (2026-05-30): defensive flee for the under-equipped
# Nebula swarm.  Captured pathology: three ZONE2 deaths in the first
# 1457 s of the 2026-05-30 session, each in fsm=regen or engage while
# 50-60 aliens drained shields from full to zero in ~10 s.  The root
# cause was a death spiral -- death drops the heal consumables, the
# consumable craft phase resets, and the bot re-engages the swarm
# with no shield_recharge in its quick-use slots, so the armed heal
# latch never fires.  S_RETREAT fires only in that exact situation
# (in ZONE2 + low shields + dense nearby swarm + no ready shield
# consumable) and drives the bot to the in-zone Home Station umbrella
# (or away from the swarm centroid if none exists) instead of sitting
# in REGEN taking fire.  It outranks REGEN / ENGAGE so the bot
# disengages rather than trading blows it cannot win; once a shield
# consumable is available again the gate releases and normal REGEN /
# ENGAGE resume.  Warp zones are excluded -- S_WARP_TRAVERSE already
# keeps the bot moving toward the exit there.
S_RETREAT           = "retreat"

ALL_STATES = (
    S_ENGAGE, S_GATHER, S_REGEN, S_MINE, S_SEARCH,
    S_BUILD, S_BUILD_SEEK, S_DEPOSIT, S_CRAFT, S_INSTALL,
    S_HUNT, S_IDLE_AT_BASE, S_ENGAGE_BOSS,
    S_EQUIP_CONSUMABLES, S_PRE_BOSS_MINE, S_FORTIFY, S_BUILD_QWI,
    S_RECOVER_LOOT, S_WARP_TO_WORMHOLE, S_WARP_TRAVERSE,
    S_FLEE_GAS, S_BUILD_NEBULA, S_FORTIFY_NEBULA,
    S_PLACE_AI_PILOT_NEBULA, S_BUILD_ADV_CRAFTER, S_RETREAT,
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

# Pin-zone tracking (2026-05-17): when stuck_detected fires the
# bot's current position is added as a pin-zone anchor.  Target
# selectors then filter pickups / asteroids within
# PIN_ZONE_RADIUS_PX of any non-expired anchor for the TTL, so the
# bot can't be pulled back into a known stuck location by new
# targets spawning in the area.  Captured pathology: 8 stuck
# events in 130 s at (8592, 1453) in Nebula, bot frozen for 30+ s
# at shields=0, burned 28 repair packs.  Specific pickup /
# asteroid blacklists weren't enough since the surrounding 54
# aliens kept dropping new pickups in the same cluster.
#
# Threshold rationale:
#   * radius 400 px wider than HUNT_ANCHOR_GRID_PX so the filter
#     blanket-covers the slop in the recorded position
#   * TTL 180 s long enough for the bot to drift to a different
#     region of the zone and find fresh targets there
#   * cap 16 anchors so a degenerate session doesn't grow the
#     list unbounded; oldest expire first
PIN_ZONE_RADIUS_PX:     float = 400.0
PIN_ZONE_TTL_S:         float = 180.0
PIN_ZONE_MAX:           int   = 16

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
# Non-MAIN-zone recovery-loadout gate (2026-05-26).  When the bot
# dies in a Nebula / warp / star-maze zone, ``S_RECOVER_LOOT``
# previously fired immediately on respawn -- the bot then drove
# toward its death pile with cold weapons (per the action handler)
# and an empty loadout, got swarmed before reaching the loot, and
# died again.  The 2026-05-25 20:43 telemetry captured 4 deaths
# in 77 min with one death IN ``fsm=recover_loot``.
#
# Fix: in non-MAIN zones, require the bot to be at the recovery
# percentages AND have consumables in slots before initiating
# the trip.  Falls through to IDLE_AT_BASE / REGEN until the
# loadout is rebuilt.  MAIN is exempt -- the HS umbrella + turret
# ring make recovery there safe even with a stripped ship.
#
# Item lifetime is 600 s (10 min) so the bot has plenty of
# headroom to heal first; the existing ``DEATH_RECOVERY_TIMEOUT_S``
# (60 s) is bumped to 180 s in non-MAIN to give the bot a
# realistic window to heal + travel.
RECOVER_LOOT_HP_PCT:        float = 0.85
RECOVER_LOOT_SHIELDS_PCT:   float = 0.85
DEATH_RECOVERY_TIMEOUT_NEBULA_S: float = 180.0
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
# Re-craft batches added to the consumable queue when the bot
# returns to MAIN with no consumables in station inventory (2026-
# 05-17, follow-up to PR #141).  Smaller than the initial 5
# batches because the bot typically only needs a partial restock
# to survive the next warp arc -- it can come back for more if
# needed.  Each batch yields 5 consumables, so 3 batches = 15
# repair packs / 15 shield recharges.
WARP_RECRAFT_REPAIR_BATCHES: int = 3
WARP_RECRAFT_SHIELD_BATCHES: int = 3
# Depleted-restock floor (2026-06-06).  The warp-back recraft above only
# fires on the warp-edge-into-MAIN; a bot that burns its consumables
# down while operating (no warp edge) never restocks.  Captured
# 2026-06-05: the bot spent ~12 min using ~19 shield heals in ZONE2,
# then fought the final ~13 min with shield supply = 0.  When the total
# shield_recharge OR repair_pack supply (station + ship + quick-use)
# falls to this floor or below AND the craft queue is idle, re-arm the
# WARP_RECRAFT batches so the bot restocks at its next crafter visit.
# Above zero so the bot starts replenishing before it runs fully dry.
CONSUMABLE_RESTOCK_FLOOR: int = 5
# Nebula-death recovery batches (2026-05-24).  When the bot dies in
# ZONE2 (Nebula), latch ``nebula_recovery_pending`` and force a
# fresh craft of repair packs + shield recharges before the next
# warp can fire -- even if the station inventory still has some
# consumables.  Captured pathology: 22 deaths in a 35-minute span,
# 20 of them in Nebula or the warp zones en-route; the bot looped
# warp -> die -> warp without ever rebuilding its consumable
# buffer because the existing recraft trigger only fires when
# station inventory is fully empty.
NEBULA_RECOVERY_REPAIR_BATCHES: int = 5
NEBULA_RECOVERY_SHIELD_BATCHES: int = 5
# Health-bar fullness gate for the post-Nebula-death recovery.
# 1.0 = require the bar at exactly its max before the warp can
# fire.  Combined with the consumables-in-slots gate, this forces
# the bot to idle at the home-station umbrella (where shield +
# HP regen are both active) until it's fully topped up.
NEBULA_RECOVERY_HP_PCT: float = 1.0
NEBULA_RECOVERY_SHIELDS_PCT: float = 1.0


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


