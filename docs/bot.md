# Call of Orion --- Bot stack

The repo ships three flavours of automation tooling for
hands-off play, plus an in-process API + combat-assist layer so
external scripts (or Claude Code) can read live game state and
issue high-level commands.

# Overview

| Bot | Operator | Cadence | Strengths |
|---|---|---|---|
| `bot_play.py` | none (autonomous) | game-loop | Always-on baseline.  Random thrust + fire + occasional build.  Good for soak-testing the game itself. |
| `bot_supervised.py` + screenshots | Claude (manual) | 3-5 s | Snapshot ↔ command-file protocol.  Claude sees pixels.  Slow but no game changes required. |
| `bot_api.py` + `bot_autopilot.py` + Claude | hybrid | 10 Hz local + 5-10 s remote | **Recommended.**  Game broadcasts JSON state, autopilot handles reflex actions, Claude sets high-level intent. |

The recommended stack is the one wired into `bot_kickoff.py`:

```
              Claude (5-10 s, sets intents)
                        |
                  POST /intent
                        v
   +-------------- bot_api.py (in-game HTTP server) -------------+
   |    GET /state -> {player, enemies, asteroids, pickups, ...}  |
   +-------------------------------------------------------------+
                        ^
                  GET /state  (10 Hz)
                        |
              bot_autopilot.py (FSM orchestrator)
                  ├── bot_autopilot_http.py         (fetch_state + _post_*)
                  ├── bot_autopilot_targeting.py    (selectors + blacklists + stuck)
                  ├── bot_autopilot_movement.py     (_do_* + execute_intent)
                  ├── bot_autopilot_actions_station.py (_act_* station handlers)
                  ├── bot_autopilot_actions_combat.py  (_act_engage* + _maybe_use_consumables)
                  ├── bot_autopilot_navigation.py   (potential field + escape)
                  ├── bot_autopilot_blacklist.py    (pickup + asteroid blacklists)
                  └── bot_autopilot_telemetry.py    (JSONL writer + snapshot)
                        |
                pyautogui keyDown/keyUp
                        v
                  Game window
```

## Autopilot module layout

`bot_autopilot.py` (~1758 LOC) is the FSM orchestrator: it
holds the `S_*` state constants, boss tunables, `MIN_DWELL_S`,
the `BotState` / `CraftQueue` / `KeyState` dataclasses, the
`_state` global, `_get_now`, `_choose_next_state`, `_on_enter`,
`_do_auto`, `main`, and `_hotkeys`.  Topical helpers split out
by concern:

| Module | Lines | Responsibility |
|---|---|---|
| `bot_autopilot_http.py` | ~219 | `fetch_state`, `_post_build_starter_base` / `_post_craft` / `_post_install_module` / `_post_deposit_to_station` / `_post_use_quick_use` / `_post_equip_consumables` / `_post_place_qwi`, `_ensure_game_focused` window-focus helper |
| `bot_autopilot_targeting.py` | ~659 | `_nearest_asteroid` / `_nearest_alien` / `_nearest_pickup` selectors with edge-skip pre-filters, blacklist wrappers, `_record_position` + `_detect_stuck`, `_wall_pin_trap_active` + `_maybe_force_wall_pin_escape`, station info helpers, iron / blueprint deposit predicates, `_qwi_ready_to_build`, queue-target helpers |
| `bot_autopilot_movement.py` | ~351 | `_do_goto` / `_do_hold_distance` / `_do_spiral_search`, `_do_mine_nearest` / `_do_attack_nearest` / `_do_engage_boss` / `_do_retreat`, `_do_cycle_weapon` + `_ensure_weapon`, top-level `execute_intent` dispatch |
| `bot_autopilot_actions_station.py` | ~328 | Station `_act_*` handlers: `_act_build_seek`, `_act_deposit`, `_act_craft`, `_act_install`, `_act_build`, `_act_at_station`, `_act_equip_consumables`, `_act_build_qwi` |
| `bot_autopilot_actions_combat.py` | ~357 | Combat `_act_*` handlers: `_act_engage`, `_act_engage_boss`, `_maybe_use_consumables`, `_act_gather`, `_act_idle_at_base` |
| `bot_autopilot_navigation.py` | — | Per-building potential field + cluster centroid + cluster detour waypoint + `find_clear_ring_point` + escape-burst geometry |
| `bot_autopilot_astar.py` | — | Grid-based A\* pathfinder over the building-occupancy grid; `plan_path(state, sx, sy, gx, gy)` + `target_reachable(...)`.  Used by `_do_goto` for routing around the cluster and by `_act_gather` / `_do_mine_nearest` for up-front unreachable-target detection. |
| `bot_autopilot_blacklist.py` | — | Pickup + asteroid blacklist data structures with TTLs |
| `bot_autopilot_telemetry.py` | — | JSONL writer + snapshot ring buffer |

Each helper does `import bot_autopilot as _ap` and qualifies
cross-references as `_ap.X` so that test-time monkey-patching
of orchestrator symbols (`_state`, `MIN_DWELL_S`, etc.) still
threads through.  The orchestrator re-exports every moved
symbol at the bottom so legacy `bot_autopilot.X` imports
(including the bot test suite) keep resolving without change.

# Running

```
# One-terminal combined launch (recommended for normal play):
python bot_run.py

# Or run the two stages separately if you want fine control:
python bot_kickoff.py        # Terminal 1 -- launch game + splash flow
python bot_autopilot.py      # Terminal 2 -- autopilot at 10 Hz

# Strategist (optional, third terminal or Claude):
python bot_strategy_helper.py state
python bot_strategy_helper.py set_intent '{"type": "mine_nearest"}'
```

`bot_run.py` is a thin wrapper that calls `bot_kickoff.main()`
then `bot_autopilot.main()` in sequence.  Both child scripts
remain standalone entry points.

`bot_kickoff.py` enables the bot API by setting `COO_BOT_API=1`
before launching `main.py` as a detached subprocess, drives the
splash → faction (Earth) → ship (Aegis) → character flow, then
loads a random music video from the first 15 in `./yvideos/`.

## `COO_BOT_API` environment variable — the master gate

Two in-process pieces of the bot stack are gated on the
`COO_BOT_API` env var; both check via:

```python
os.environ.get("COO_BOT_API", "").strip() not in ("", "0", "false")
```

| Component | Where | Effect when `COO_BOT_API=1` |
|---|---|---|
| HTTP `/state` + `/intent` server (`bot_api.py`) | starts on `127.0.0.1:8765` from `bot_api.maybe_start()` (`bot_api.py:600`) | The autopilot can poll game state and post intents |
| Combat assist (`bot_combat_assist.py`) | monkey-patches `update_logic.update_weapons` from `bot_combat_assist.install(gv)` (`bot_combat_assist.py:283`) | The ship auto-aims + auto-fires at the nearest hostile every frame |

**Important gotcha — combat assist runs even without
`bot_autopilot.py`.**  The two pieces install independently.  If
`COO_BOT_API` is set in your shell when you launch `python main.py`
manually (no autopilot, no `bot_kickoff.py`):

* The HTTP API starts (harmless if nothing polls it).
* The combat assist hooks into `update_weapons`.
* You will play a game where **the ship shoots at enemies on its
  own without you pressing Space** — even though there's no bot
  process running and no movement keystrokes are being injected.

The reason it's gated this way: the assist deliberately runs at
the game's native ~60 FPS so that bot autopilot (which polls at
10 Hz over HTTP) can rely on accurate weapon timing.  Tying the
assist to the same env var as the API ensures they're enabled /
disabled together.

**To disable the combat assist for normal play**, clear the env
var before launching the game:

```bash
unset COO_BOT_API           # bash / zsh
set COO_BOT_API=            # cmd
$env:COO_BOT_API=$null      # PowerShell
```

`bot_kickoff.py` sets `COO_BOT_API=1` only on the spawned game
**subprocess** (`bot_kickoff.py:50`, `env["COO_BOT_API"] = "1"`),
so a normal kickoff does not leak the variable into the parent
shell.  If you find the variable persistently set in your shell,
check `~/.bashrc` / `~/.zshrc` / Windows User Environment
Variables — something else set it.

# Hotkeys (global, work even with the game focused)

* `Ctrl+Shift+P`  pause / resume the bot
* `Ctrl+Shift+Q`  stop the bot AND kill the game subprocess
* `Ctrl+Shift+R`  (`bot_supervised.py` only) abort current snapshot wait

# In-process combat assist

When `COO_BOT_API=1` is set, `bot_combat_assist.install(gv)`
runs automatically.  It monkey-patches `update_logic.update_weapons`
so each frame:

1. Walks `alien_list` + boss + nebula_boss for the nearest live
   hostile within `DETECT_RANGE` (800 px).
2. Snaps `gv.player.heading` to face it.
3. Auto-cycles to **Energy Blade** (< 100 px) or **Basic Laser**
   (otherwise).
4. Forces `fire=True` for the underlying `update_weapons`.

Movement, abilities, and inventory are NOT touched -- the
strategist + autopilot still own those.  This is a strict
defensive layer that ensures anything close enough to hurt the
player gets shot back at native frame rate (the autopilot's
~100 ms HTTP loop can't react fast enough alone).

Toggle at runtime:

```
python bot_strategy_helper.py assist off
python bot_strategy_helper.py assist on
```

State is exposed under `state.assist`.

# Intent vocabulary

```json
{"type": "auto"}            // default -- nine-state FSM (see below)
{"type": "idle"}
{"type": "goto", "x": 3200, "y": 4000, "radius": 80}
{"type": "mine_nearest"}
{"type": "attack_nearest"}
{"type": "engage_boss"}
{"type": "retreat_to_station"}
{"type": "cycle_weapon", "to": "Mining Beam"}
```

Unknown types are logged and the autopilot falls back to `idle`.

## `auto` finite state machine (default)

`_do_auto` is a ten-state FSM with **asymmetric enter/exit
thresholds** (hysteresis) plus a **MIN_DWELL_S = 0.6 s** gate
on transitions.  `REGEN`, `ENGAGE`, and `ENGAGE_BOSS` are
defensive interrupts: they preempt dwell from any state.  `REGEN`
sits at the top of the priority order so the bot pauses to
recover shields rather than chasing a fight at low health; combat
assist keeps aiming + firing every frame so the bot is still
shooting back while it idles.

| State | Action | Enter when | Exit when |
|---|---|---|---|
| `REGEN` | idle, release all keys, let shields recover.  Combat assist still auto-fires at anything in range. | shields `< 40 %` AND no close threat within `ENGAGE_ENTER_PX` — entry-side mirror suppresses REGEN while engaged so the bot doesn't ping-pong with ENGAGE every tick (telemetry caught 111 transitions in one fight at 0.09 s median dwell pre-fix) | shields `≥ 60 %`, OR (in-REGEN escape valve) close threat appears mid-regen AND shields not recovering since last tick — prevents the deadlock where a bot starting low-shields surrounded by aliens can never reach 60% and dies idling |
| `ENGAGE_BOSS` | station-anchor kite + phase-aware strafe.  Hold at `BOSS_KITE_RANGE_PX` (750 px) from the boss — outside cannon range (700) but inside Basic Laser range — and within `BOSS_KITE_STATION_TETHER_PX` (600 px) of the Home Station so friendly Defense Turrets / Missile Array share DPS.  Phase 2 charge windup => strafe `BOSS_DODGE_PERP_PX` (250 px) perpendicular to the boss-to-bot vector (the 0.8 s × 600 px/s dash misses comfortably).  Phase 3 (no shield regen, halved cooldowns) => press in to `BOSS_PHASE3_PRESS_RANGE_PX` (600 px, just outside spread range).  REGEN entry-side mirror still applies — shield collapse falls out to S_REGEN. | `state.boss` is alive (set by `_boss_state` in `bot_api.py`).  Above ENGAGE so a small alien at 200 px doesn't pull the bot into the boss's cannon range. | boss dies / `state.boss` becomes None |
| `ENGAGE` | If the in-process combat assist has rolled into a melee commitment for this engagement (`state.assist.melee_engaged`), close to ~50 px and let the assist swing the lightsabre.  Otherwise hold ~380 px stand-off with Basic Laser.  Combat assist owns aim + fire + melee weapon-lock. | nearest alien `< 800 px` and not in REGEN/ENGAGE_BOSS | no alien `< 1000 px` |
| `GATHER` | fly to nearest pickup (blueprints win on tie); 60 px stop radius | pickup `< 1500 px` and not in REGEN/ENGAGE | no pickup `< 1700 px` |
| `BUILD` / `BUILD_SEEK` | one-shot starter base (HS + SM + PR + SA2 + RM + 2× T2 + west extension + Basic Crafter); SEEK walks toward less-cluttered space first | ship iron `≥ 1000` and area is clear of asteroids/aliens/pickups within 800 px | `_state.build_done` flips True after first POST |
| `DEPOSIT` | head to Home Station, POST `/deposit_to_station` to dump every item type from ship into station inventory | ship iron `≥ 200` OR any blueprint in ship; cooldown `30 s` since last deposit | POST returns; cooldown re-arms |
| `INSTALL` | head to Home Station, POST `/install_module` for the head of the install queue (broadside → shield_booster → shield_enhancer → armor_plate); pops queue on success | a `mod_<key>` for the install queue head is sitting in station inventory | post-install — falls through to next FSM tick |
| `CRAFT` | head to a non-busy Basic Crafter, POST `/craft` for the head of the craft queue (modules first: armor_plate → engine_booster → shield_booster → shield_enhancer → damage_absorber → broadside; then 5× repair pack; then 5× shield recharge) and pop on success | every blueprint in `MODULE_CRAFT_QUEUE` deposited at station, station iron `≥ 2000` (sticky after first craft), no Basic Crafter currently mid-cycle | POST returns; the 60 s craft timer ticks down on the building while the FSM falls back to MINE / GATHER / SEARCH |
| `MINE` | head to nearest asteroid, hold Mining Beam | asteroids visible and safe | no asteroids visible |
| `HUNT` | close on nearest alien (reuses `_act_engage`'s close-and-fight) | no asteroid visible AND alien within `HUNT_RANGE_PX` (3000 px from `MINE`/`SEARCH`/`GATHER`, or `IDLE_HUNT_RANGE_PX` 9000 px when currently in `IDLE_AT_BASE` or `HUNT` — symmetric so a chase that started wide stays wide until the alien is genuinely out of range) AND not in REGEN/ENGAGE/etc AND `hunt_giveup_until` not active | asteroid appears OR alien drifts past `IDLE_HUNT_RANGE_PX` (then `IDLE_AT_BASE` if HS exists, else `SEARCH`) OR alien closes inside 800 px (then `ENGAGE`) OR ≥3 stuck events in 10 s (latches `hunt_giveup_until` for 30 s, falls through to `IDLE_AT_BASE`) |
| `IDLE_AT_BASE` | navigate to the *outer ring* of the idle zone (one `IDLE_AT_BASE_RADIUS_PX` = 600 px from HS, on the player→HS ray — keeps the bot OUTSIDE the building cluster) and idle there waiting for respawns | no asteroid visible AND no alien within `IDLE_HUNT_RANGE_PX` (9000 px) AND a Home Station exists | asteroid appears (then `MINE`) OR alien comes into 9000 px (then `HUNT`) OR alien closes to 800 px (then `ENGAGE`) |
| `SEARCH` | outward spiral from current position, Mining Beam held; re-anchors at 3000 px | early-game fallback: no asteroid visible AND no alien within 3000 px AND no Home Station yet | asteroid appears OR alien comes into HUNT range OR Home Station built (then `IDLE_AT_BASE`) |

**Post-build workflow** (`CraftQueue`).  Once the starter base is
up and a Basic Crafter exists, the bot drives a serial three-phase
queue between mining runs:

1. **Module craft phase** — gated by 2000 station-iron + every
   `bp_<key>` deposited.  The bot fires one `POST /craft` per
   queue head in this order: `armor_plate`, `engine_booster`,
   `shield_booster`, `shield_enhancer`, `damage_absorber`,
   `broadside`.  Each craft takes 60 s; during that window the
   FSM falls back to `MINE` / `GATHER` / `ENGAGE` so the bot
   gathers resources between visits.  `_any_crafter_busy` keeps
   the queue serial — only one craft runs at a time.
2. **Module install phase** — once a `mod_<key>` lands in station
   inventory, `INSTALL` takes priority over fresh `CRAFT`.  Four
   modules are installed in this order: `broadside`,
   `shield_booster`, `shield_enhancer`, `armor_plate`.  The other
   two (`engine_booster`, `damage_absorber`) stay in station
   storage.
3. **Consumable craft phase** — gated by 2000 station-iron
   (sticky after the first batch).  5 `repair_pack` cycles (25
   total packs) followed by 5 `shield_recharge` cycles (25 total
   recharges).  Same gather-between-visits rhythm as the module
   phase.  `S_DEPOSIT` keeps firing during this phase too, so
   gathered iron + blueprints still flow back to the station.
4. **Equip consumables** (`S_EQUIP_CONSUMABLES`) — once both
   counters in `CraftQueue` hit zero AND the `consumable_phase_started`
   sticky latch is set, the bot navigates to the Home Station and
   `POST /equip_consumables`.  That withdraws **up to** `max_each`
   (default 25) of each consumable from station inventory into the
   ship inventory and binds them to ship quick-use slots
   (`EQUIP_QUICK_USE_REPAIR_SLOT` = 0, `EQUIP_QUICK_USE_SHIELD_SLOT`
   = 1).  Latches `_state.consumables_equipped` on success.

   **`max_each` cap behavior.**  The cap is a *ceiling*, not a
   target — the bot equips `min(station_count, max_each)` of each
   item.  This matters when the auto-heal hook (below) consumed
   some packs during the craft phase: e.g. if the bot took two
   shield-recharge hits during a mining run, the station only has
   23 shield recharges when this state fires, and the bot equips
   23 instead of 25.  The equip step still succeeds, the latch
   still flips, and the FSM moves on — just with a smaller buffer.
   Bumping `max_each` past 25 has no effect (the prior phase only
   produces 25), but a future change that lets the bot top up
   consumables between boss attempts can raise the cap without
   touching the action handler.
5. **Pre-boss mine** (`S_PRE_BOSS_MINE`) — same `_do_mine_nearest`
   action as `S_MINE`; the FSM-level rename makes it explicit that
   the bot is mining toward `QWI_BUILD_IRON_TARGET` (2000 station
   iron) rather than the indefinite mining loop.  Falls through
   when an asteroid is in range and station iron is below the
   target.
6. **Fortify** (`S_FORTIFY`) — station iron staged: the bot
   navigates to the Home Station and `POST /fortify`, which drops
   the 4-turret defensive ring (N / S cardinals + NW / SE corners)
   anchored on the Home Station.  Combined with the 2 starter
   turrets at NE / SW, the cluster reaches the bumped
   `QWI_STAGE_MIN_TURRETS=6` so the next FSM tick clears the
   `_qwi_ready_to_build` gate.  Latches `_state.fortify_done` on
   success or "ring already complete" (idempotent — manual
   placement / loaded saves short-circuit at the top of
   `_choose_next_state`).
7. **Build QWI** (`S_BUILD_QWI`) — fortify done + station iron
   still staged: the bot navigates to the Home Station and
   `POST /place_qwi`.  The QWI's placement chain auto-spawns the
   Double Star boss at the world corner furthest from the station
   (`combat_helpers.spawn_boss`).  Latches `_state.qwi_placed` on
   success; from there the existing `S_ENGAGE_BOSS` handler takes
   over the fight.

**Per-tick consumable auto-use** (`_maybe_use_consumables`).  Runs
**before** the FSM dispatch every tick so the response is
independent of the active state — combat, mining, or boss kite all
benefit.

Each consumable is governed by a **heal-active latch**
(`_state.heal_hp_active`, `_state.heal_shield_active`):

* **Arms** when the value crosses below `CONSUMABLE_USE_*_PCT`
  (0.5).  Emits a `heal_hp_arm` / `heal_shield_arm` telemetry
  event.
* **Disarms** when the value reaches its max.  Emits a
  `heal_hp_disarm` / `heal_shield_disarm` telemetry event.
* While armed, the auto-use loop fires `POST /use_quick_use` on
  each tick (subject to `CONSUMABLE_USE_COOLDOWN_S` = 1.0 s) until
  either the bar is full or the matching consumable runs out.

Without the latch, a single 50 %-heal use only fills the deficit
that tripped the threshold — if HP dropped to 30 % between ticks,
one use lands at 80 %, the next tick reads `80/100 > 0.5` and no
further use fires until HP drops below 50 % again.  The latch
closes that gap so the bot reaches 100 % per the user spec.

Repair pack takes priority over shield recharge when both latches
are armed on the same tick (HP can't passively regen; shields do).
Each fire also emits a `heal_hp_fire` / `heal_shield_fire`
telemetry event with the slot index and the post-fire HP / shield
value.

**Melee commit (per engagement).**  The dice roll for melee
commitment lives in the in-process combat assist
(`bot_combat_assist.tick`), not the autopilot, because combat
assist runs every game frame and would otherwise fight the
autopilot's slower 10 Hz Tab presses for weapon control.

On the tick that transitions no-threat → threat (a "fresh
engagement"), the assist rolls `random.random() <
MELEE_COMMIT_CHANCE` (default 0.5).  On hit it locks the
Energy Blade for the duration of the engagement, force-firing
every frame regardless of distance.  The autopilot reads
`state.assist.melee_engaged` and closes to
`MELEE_STOP_RADIUS_PX` (~50 px) so the swing arc reaches the
target.  The lock survives `MELEE_LOCK_HOLDOVER_S` (0.6 s) of
target-loss before clearing, so a one-frame line-of-sight
gap doesn't drop it mid-fight.

On miss, the autopilot uses ranged engagement with the
laser/melee sub-band hysteresis: enter Energy Blade at `< 100
px`, exit (back to Basic Laser) at `> 130 px`.

The hysteresis bands replace three previous sources of flicker
that the old priority cascade had to mask with ad-hoc timers:

* **mine ↔ engage** at the 800 px ring -- the bot used to
  re-target every tick when an alien drifted near the boundary;
  weapon-switch Tab presses were rate-limited at 250 ms purely
  to hide this.
* **idle ↔ mine** at the 50 % shield threshold -- shields ticking
  across the line during regen would alternate idle/mine each
  frame.
* **spiral teardown** -- the prior cascade called
  `_spiral_reset()` from every other branch, so a brushing
  alien could destroy a 30-second outward sweep.

Combat assist (`bot_combat_assist.py`) still owns aim + fire
override during `ENGAGE`; the FSM owns thrust + weapon
selection.

## Boss fight (`ENGAGE_BOSS`)

The Double Star and Nebula bosses share one engagement handler
(`_act_engage_boss`) because their movement + weapon profiles
are similar (Phase 1 cannon + spread, Phase 2 charge dash, Phase
3 enraged) and the player ship's countermeasures don't change
between them.  The handler embodies four design choices, each
tunable via a constant near the top of `bot_autopilot.py`:

| # | Choice | Where |
|---|---|---|
| 1 | **Pre-trigger staging gate** — `_qwi_ready_to_build(state)` predicate.  Returns `(False, reason)` until a Home Station + at least `QWI_STAGE_MIN_TURRETS` (default 6: 2 starter + 4 fortify) Defense Turret / Turret 2 / Missile Array are placed, and the ship has been upgraded to `QWI_STAGE_MIN_SHIP_LEVEL` (default 2).  The S_FORTIFY phase brings the cluster to that count automatically before BUILD_QWI fires; the spawn flag is one-shot. | `bot_autopilot.py` |
| 2 | **Station-anchor kite** — when a Home Station exists, the kite target is pulled to the side of the boss closest to the station so friendly turret + missile DPS overlaps the bot's Basic Laser line.  Tether: `BOSS_KITE_STATION_TETHER_PX` (default 600 px). | `_act_engage_boss` |
| 3 | **Phase-aware behavior** — Phase 2: when `boss.charging` or `boss.charge_windup > 0`, displace the kite target by `BOSS_DODGE_PERP_PX` (250 px) perpendicular to the boss-to-bot vector.  Sign alternates with windup time so back-to-back charges don't lock to one side.  Phase 3: drop the kite range to `BOSS_PHASE3_PRESS_RANGE_PX` (600 px) — boss has no shield regen, so press the DPS. | `_act_engage_boss` |
| 4 | **REGEN escape valve** — reuses the existing entry-side mirror + in-REGEN escape valve.  Shield collapse during a boss kite drops the bot to S_REGEN; the entry-side mirror prevents thrash with ENGAGE_BOSS the same way it does with ENGAGE. | `_choose_next_state` |

The boss telegraph fields (`charging`, `charge_windup`,
`charge_timer`) are exposed on `/state` by `_boss_state` in
`bot_api.py` — the autopilot reads them to drive the Phase 2
strafe.  The 2 s windup is more than enough lead time for the
10 Hz autopilot loop to react before the 0.8 s × 600 px/s dash
fires.

# Cluster avoidance + corner-pin mitigations

The bot has a layered stack for navigating the player-built
station without pinning on its own corners.  Listed by when each
layer fires, from proactive (avoid the corner) to reactive
(recover from being pinned):

1. **Per-building potential field** (`building_repulsion`,
   `BUILDING_REPULSION_RANGE_PX = 150 px` base).  Each building
   contributes a repulsion vector scaled by `1 - dist/range`;
   adjacent buildings (a corner) sum automatically.
2. **Per-building-type range multiplier**
   (`BUILDING_REPULSION_TYPE_MULTIPLIER`).  Home Station gets
   `1.5x` (= 225 px) — wider field for the cluster centre.
3. **Two-tier target-aware suppression**.
   *Tight tier:* buildings within
   `REPULSION_TARGET_SUPPRESS_PX = 50 px` of the goto target are
   excluded so deposit / craft / install can dock with their
   target building.
   *Cluster tier:* when the goto target is INSIDE the cluster
   centroid radius, ALL buildings in the cluster are excluded so
   the bot can thread through to a target wedged between multiple
   cluster buildings (e.g. a pickup that spawned among the
   station).
4. **Cluster aggregate detour** (`cluster_detour_waypoint`).
   When the goto path crosses within `r + CLUSTER_DETOUR_MARGIN_PX
   = 250 px` of the building cluster centroid, the immediate
   target is redirected to a tangent waypoint on the cluster
   boundary.  Suppressed when the destination IS inside the
   cluster (so docking actions complete normally).
4a. **A\* path planning** (`bot_autopilot_astar.plan_path`).
    Grid-based A\* (80 px cells) over a building-occupancy map of
    the live `/state` snapshot.  When the straight-line bot→target
    segment crosses any blocked cell, `_astar_next_waypoint`
    returns the next intermediate waypoint (after greedy
    line-of-sight smoothing) and `_do_goto` routes through it.
    Cached on `_state.path_*` with a target-drift threshold of
    `ASTAR_REPLAN_TARGET_DRIFT_PX = 80 px` and a `ASTAR_REPLAN_TTL_S
    = 3 s` staleness gate.  Targets that resolve to a building-
    blocked goal cell return ``"unreachable"``; `_act_gather` and
    `_do_mine_nearest` consume that signal via
    `target_reachable(state, sx, sy, gx, gy)` to blacklist the
    target up front rather than letting the bot pin against the
    cluster's repulsion field for tens of seconds (the deadlock
    pattern from PR #60 telemetry).  Boundary cells are NOT
    blocked by default — boundary handling is already covered by
    the `steered_heading` repulsion blend, and including them
    would false-flag legitimate edge-adjacent pickups as
    unreachable.
5. **`IDLE_AT_BASE` outer-ring parking** — idle target sits
   `IDLE_AT_BASE_RADIUS_PX = 600 px` from HS on the player→HS
   ray, so the bot parks *outside* the cluster.
6. **Stuck-detect watchdog + escape burst** — rolling 1.5 s
   position+heading window; on stuck, navigates toward the
   pure repulsion vector until clear of buildings AND edges.
7. **Pickup blacklist** (5 min TTL) and **asteroid blacklist**
   (60 s TTL) — skip targets that caused a prior stuck event.
8. **Acute hunt-stuck giveup** — 3 stuck events in S_HUNT inside
   `HUNT_STUCK_WINDOW_S = 30 s` latches `HUNT_GIVEUP_S = 30 s`.
9. **Long-term per-anchor hunt-stuck giveup** — 3 stuck events
   at the same `HUNT_ANCHOR_GRID_PX = 200 px` cell within
   `HUNT_ANCHOR_TTL_S = 5 min` latches `HUNT_LONG_GIVEUP_S =
   2 min`.  Catches the slow repeated-pin pattern that the
   acute window doesn't see.
10. **World-edge-aware IDLE_AT_BASE outer ring**
    (`find_clear_ring_point`) — when HS sits near a world edge
    the naive player→HS ring projection can land past the
    boundary; the helper sweeps the ring until it finds an
    interior point so the bot doesn't pin trying to navigate
    off-world.
11. **World-edge-aware chase clamping** — `_act_engage`,
    `_do_attack_nearest`, `_do_mine_nearest`, and `_act_gather`
    all clamp the chase target to inside `[STUCK_WORLD_MARGIN_PX,
    world_dim - STUCK_WORLD_MARGIN_PX]` so an edge-adjacent alien /
    asteroid / pickup doesn't pull the bot into the boundary
    repulsion local-minimum trap (goto + repulsion cancel along
    the wall-perpendicular axis → bot drifts along the wall →
    long oscillation before random thrust noise pops it out).
    Mining beam range (400 px) and basic laser (FIRE_RANGE_PX)
    both exceed the 200 px margin so the bot fires through the
    boundary from inside the safety zone.  The fire trigger uses
    the REAL (unclamped) distance so weapon range gating stays
    accurate.
12. **Edge-asteroid pre-filter in `_nearest_asteroid`**
    (`ASTEROID_EDGE_SKIP_PX = 250 px`) — asteroids spawned
    within 250 px of any world boundary are skipped at
    selection time so MINE doesn't ram the wall trying to
    circle them.  Falls back to edge-adjacent picks when no
    interior asteroid is reachable.
13. **Edge-pickup pre-filter in `_nearest_pickup`**
    (`PICKUP_EDGE_SKIP_PX = 200 px`) — same idea for pickups
    that spawned where an alien died right against the world
    boundary.  Slightly tighter margin than the asteroid skip
    because pickups have a despawn timer and are easier to
    wait out than asteroids.

# State JSON schema (`GET /state`)

```json
{
  "ts": 1735200000.123,
  "uptime_s": 42.5,
  "player": {
    "x": 3200, "y": 3200, "heading": 0.0,
    "vel_x": 0, "vel_y": 0,
    "hp": 50, "max_hp": 50,
    "shields": 150, "max_shields": 150,
    "faction": "Earth", "ship_type": "Aegis",
    "ship_level": 1
  },
  "weapon": {"name": "Basic Laser", "idx": 0},
  "ability": {"value": 100, "max": 100},
  "zone": {"id": "ZoneID.MAIN", "world_w": 6400, "world_h": 6400},
  "boss": null,
  "menu": {"build": false, "inventory": false, "escape": false, ...},
  "inventory": {"items": {"iron": 105, "bp_armor_plate": 4, ...}},
  "station_inventory": {"items": {"iron": 2400, "bp_broadside": 1, ...}},
  "module_slots": ["broadside", null, null, null],
  "asteroids": [{"x": ..., "y": ..., "hp": 100, "type": "Asteroid"}, ...],
  "aliens": [...],
  "buildings": [...],
  "iron_pickups": [{"x": ..., "y": ..., "amount": 10, "item_type": "iron"}],
  "blueprint_pickups": [{"x": ..., "y": ..., "item_type": "bp_armor"}],
  "intent": {"type": "auto"},
  "assist": {
    "enabled": true,
    "installed": true,
    "last_threat_dist": 395.7,
    "last_threat_type": "SmallAlienShip",
    "engagements": 218,
    "detect_range": 800.0,
    "laser_range": 1100.0,
    "melee_range": 100.0
  }
}
```

# HTTP endpoints (port 8765, localhost only)

| Method | Path     | Notes |
|--------|----------|-------|
| GET    | `/`      | health check + version |
| GET    | `/health`| same |
| GET    | `/state` | full state JSON (above) |
| GET    | `/intent`| current intent dict |
| POST   | `/intent`| set the next intent (JSON body) |
| POST   | `/assist`| toggle combat assist (`{"enabled": false}`) |
| POST   | `/build` | place a building near the player (`{"type": "Home Station"}`) |
| POST   | `/build_starter_base` | one-shot: place the seven-building starter base + deposit + west extension (no body required) |
| POST   | `/deposit_to_station` | dump every item from ship inventory into the Home Station's inventory (no body required) |
| POST   | `/craft` | start a Basic Crafter cycle (`{"target": "armor_plate"}` or `"repair_pack"` / `"shield_recharge"`) |
| POST   | `/install_module` | install one `mod_<key>` from station into the next free ship slot (`{"mod_key": "broadside"}`) |

# Dependencies

```
pip install pyautogui pygetwindow pynput pillow
```

`bot_api.py` and `bot_strategy_helper.py` use only the standard
library (`http.server`, `urllib`).  `bot_combat_assist.py` is
pure Python with no extra deps.

# Tests

The bot stack is covered by ~129 tests across:

* `unit tests/test_bot_combat_assist.py` -- threat selection,
  weapon switching, tick() per-frame behaviour, menu suppression.
* `unit tests/test_bot_api_state.py` -- per-component
  extractors, sprite + pickup summaries, `get_state` schema.
* `unit tests/test_bot_autopilot_logic.py` -- geometry helpers,
  `_do_auto` cascade per priority, spiral state.
* `unit tests/test_escape_menu_keyboard.py` -- Tab / arrow /
  Enter / ESC across all five menu modes.
* `unit tests/test_splash_keyboard.py` -- splash + Load
  sub-screen keyboard nav.
* `unit tests/integration/test_bot_api_integration.py` -- real
  HTTP server, /health + /state + /intent + /assist round-trips.
* `unit tests/integration/test_performance_bot.py` -- tick
  < 1 ms, get_state < 5 ms, HTTP /state < 50 ms,
  `_do_auto` cascade < 2 ms.

# Implementation notes

* **DPI scaling**: `bot_play.py` calls
  `SetProcessDpiAwareness(2)` and reads the game window's Win32
  client rect (excluding title bar / borders), so click + screenshot
  coords are physical pixels at any DPI scale.
* **Window focus**: `_ensure_game_focused` in
  `bot_autopilot_http.py` re-activates the game window every
  2 s so pyautogui keystrokes keep landing on it even if you
  click elsewhere.
* **Race conditions**: `bot_api.get_state` reads gv attributes
  on the HTTP thread without locking.  All reads are simple
  scalar accesses, so a torn read at worst yields a one-frame-
  stale value.  Don't use the API for atomic decisions -- it's
  an advisory channel.
* **Performance**: `/state` returns ~1 KB at full game load;
  10 Hz polling costs ~0.5 ms / tick on the game side and
  ~10 KB/s of localhost traffic.  Negligible.
