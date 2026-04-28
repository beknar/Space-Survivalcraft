# Bot architecture — three flavours

Three bots ship with the project, each tuned for a different
operator latency budget.

| Bot | Operator | Cadence | Strengths |
|---|---|---|---|
| `bot_play.py` | none (autonomous) | game-loop | Always-on baseline.  Random thrust + fire + occasional build.  Good for soak tests of the game itself. |
| `bot_supervised.py` + screenshots | Claude (manual) | 3-5 s | Snapshot ↔ command-file protocol.  Claude sees pixels.  Slow but no game changes required. |
| `bot_api.py` + `bot_autopilot.py` + Claude | hybrid | 10 Hz local + 5-10 s remote | **Recommended.**  Game broadcasts JSON state, autopilot handles reflexes, Claude sets high-level intent. |

## API + autopilot architecture (recommended)

```
              Claude (5-10 s, sets intents)
                        |
                  POST /intent
                        v
   +-------------- bot_api.py (in-game HTTP server) -------------+
   |    GET /state -> {player, enemies, asteroids, ...}          |
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

### Run it

```
# Terminal 1 -- game with API enabled
set COO_BOT_API=1
python main.py

# Terminal 2 -- local autopilot (translates intents to keys)
python bot_autopilot.py

# Terminal 3 (or Claude) -- strategist
python bot_strategy_helper.py state
python bot_strategy_helper.py set_intent "{\"type\": \"mine_nearest\"}"
```

### Intent vocabulary

```
{"type": "idle"}
{"type": "goto", "x": 3200, "y": 4000, "radius": 80}
{"type": "mine_nearest"}
{"type": "attack_nearest"}
{"type": "engage_boss"}
{"type": "retreat_to_station"}
{"type": "cycle_weapon", "to": "Mining Beam"}
```

Unknown types are logged + autopilot falls back to `idle`.

### State JSON (compact view)

```json
{
  "ts": 1735200000.123,
  "uptime_s": 42.5,
  "player": {
    "x": 3200, "y": 3200, "heading": 0.0,
    "vel_x": 0, "vel_y": 0,
    "hp": 50, "max_hp": 50,
    "shields": 150, "max_shields": 150,
    "faction": "Colonial", "ship_type": "Aegis",
    "ship_level": 1
  },
  "weapon": {"name": "Basic Laser", "idx": 0},
  "ability": {"value": 100, "max": 100},
  "zone": {"id": "ZoneID.MAIN", "world_w": 6400, "world_h": 6400},
  "boss": null,
  "menu": {"build": false, "inventory": false, ...},
  "inventory": {"items": {"iron": 0}},
  "asteroids": [{"x": ..., "y": ..., "hp": 100, "type": "Asteroid"}, ...],
  "aliens": [...],
  "buildings": [...],
  "intent": {"type": "idle"}
}
```

### Claude workflow

```python
# 1. Read state
import bot_strategy_helper as h
print(h.summary())

# 2. Decide -- e.g. low shields, retreat
h.set_intent({"type": "retreat_to_station"})

# ... wait 3-5 s ...

# 3. Read again
print(h.summary())
# shields recovered -> back to mining
h.set_intent({"type": "mine_nearest"})
```

Intent persists -- autopilot keeps executing the last one until
Claude posts a new one.  Set `idle` to release all keys and
just drift.

### Hotkeys

Both `bot_play` / `bot_supervised` and `bot_autopilot` use
**pynput global hotkeys**:

* `Ctrl+Shift+P`  pause / resume
* `Ctrl+Shift+Q`  stop the bot

For `bot_supervised`, also:

* `Ctrl+Shift+R`  abort current snapshot wait, take fresh shot

## Dependencies

```
pip install pyautogui pygetwindow pynput pillow
```

`bot_api.py` and `bot_strategy_helper.py` use only the standard
library (`http.server`, `urllib`).

## Implementation notes

- **DPI scaling**: bot_play.py / bot_supervised.py call
  `SetProcessDpiAwareness(2)` and read the game's Win32 client
  rect, so coordinate math works at any DPI scale.  The autopilot
  inherits this via pyautogui's per-process DPI mode.
- **Race conditions**: bot_api reads gv attributes on the HTTP
  thread without locking.  All reads are simple-type accesses,
  so a torn read at worst returns a one-frame-stale value.
  Don't use the API for atomic decisions -- it's an advisory
  channel.
- **Performance**: `/state` returns ~1 KB at full game load.
  Polling at 10 Hz costs ~0.5 ms / tick on the game side and
  ~10 KB/s of localhost traffic.  Negligible.
