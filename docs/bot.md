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
# Terminal 1 -- launch game (with API) + drive splash + load music video
python bot_kickoff.py

# Terminal 2 -- autopilot at 10 Hz (defaults to "auto" intent)
python bot_autopilot.py

# Terminal 3 (or Claude) -- strategist
python bot_strategy_helper.py state
python bot_strategy_helper.py set_intent '{"type": "mine_nearest"}'
```

`bot_kickoff.py` enables the bot API by setting `COO_BOT_API=1`
before launching `main.py` as a detached subprocess, drives the
splash → faction (Earth) → ship (Aegis) → character flow, then
loads a random music video from the first 15 in `./yvideos/`.

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
{"type": "auto"}            // default -- five-state FSM (see below)
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

`_do_auto` is a five-state FSM with **asymmetric enter/exit
thresholds** (hysteresis) plus a **MIN_DWELL_S = 0.6 s** gate
on every non-`ENGAGE` transition.  `ENGAGE` is the defensive
interrupt: it preempts dwell from any state.

| State | Action | Enter when | Exit when |
|---|---|---|---|
| `ENGAGE` | maintain ~380 px stand-off, combat assist owns aim + fire | nearest alien `< 800 px` (any state) | no alien `< 1000 px` |
| `GATHER` | fly to nearest pickup (blueprints win on tie); 60 px stop radius | pickup `< 1500 px` and not in ENGAGE | no pickup `< 1700 px` |
| `REGEN` | idle, release all keys, let shields recover | shields `< 40 %` and safe | shields `≥ 60 %` |
| `MINE` | head to nearest asteroid, hold Mining Beam | asteroids visible and safe | no asteroids visible |
| `SEARCH` | outward spiral from current position, Mining Beam held; re-anchors at 3000 px | no asteroids visible and not in any other state | asteroid appears |

Within `ENGAGE`, weapon choice has its own sub-band: enter
Energy Blade at `< 100 px`, exit (back to Basic Laser) at
`> 130 px`.

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
