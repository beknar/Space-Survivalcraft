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
              bot_autopilot.py (reflex layer)
                        |
                pyautogui keyDown/keyUp
                        v
                  Game window
```

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

`_do_auto` is a nine-state FSM with **asymmetric enter/exit
thresholds** (hysteresis) plus a **MIN_DWELL_S = 0.6 s** gate
on transitions.  `REGEN` and `ENGAGE` are defensive interrupts:
they preempt dwell from any state.  `REGEN` sits at the top of
the priority order so the bot pauses to recover shields rather
than chasing a fight at low health; combat assist keeps aiming
+ firing every frame so the bot is still shooting back while
it idles.

| State | Action | Enter when | Exit when |
|---|---|---|---|
| `REGEN` | idle, release all keys, let shields recover.  Combat assist still auto-fires at anything in range. | shields `< 40 %` (any state) | shields `≥ 60 %`, OR (escape valve) close threat within `ENGAGE_ENTER_PX` AND shields not recovering since last tick — prevents the deadlock where a bot starting low-shields surrounded by aliens can never reach 60% and dies idling |
| `ENGAGE` | If the in-process combat assist has rolled into a melee commitment for this engagement (`state.assist.melee_engaged`), close to ~50 px and let the assist swing the lightsabre.  Otherwise hold ~380 px stand-off with Basic Laser.  Combat assist owns aim + fire + melee weapon-lock. | nearest alien `< 800 px` and not in REGEN | no alien `< 1000 px` |
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
5. **`IDLE_AT_BASE` outer-ring parking** — idle target sits
   `IDLE_AT_BASE_RADIUS_PX = 600 px` from HS on the player→HS
   ray, so the bot parks *outside* the cluster.
6. **Stuck-detect watchdog + escape burst** — rolling 1.5 s
   position+heading window; on stuck, navigates toward the
   pure repulsion vector until clear of buildings AND edges.
7. **Pickup blacklist** (5 min TTL) and **asteroid blacklist**
   (60 s TTL) — skip targets that caused a prior stuck event.
8. **Acute hunt-stuck giveup** — 3 stuck events in S_HUNT inside
   `HUNT_STUCK_WINDOW_S = 10 s` latches `HUNT_GIVEUP_S = 30 s`.
9. **Long-term per-anchor hunt-stuck giveup** — 3 stuck events
   at the same `HUNT_ANCHOR_GRID_PX = 100 px` cell within
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
* **Window focus**: `bot_autopilot.py` re-activates the game
  window every 2 s so pyautogui keystrokes keep landing on it
  even if you click elsewhere.
* **Race conditions**: `bot_api.get_state` reads gv attributes
  on the HTTP thread without locking.  All reads are simple
  scalar accesses, so a torn read at worst yields a one-frame-
  stale value.  Don't use the API for atomic decisions -- it's
  an advisory channel.
* **Performance**: `/state` returns ~1 KB at full game load;
  10 Hz polling costs ~0.5 ms / tick on the game side and
  ~10 KB/s of localhost traffic.  Negligible.
