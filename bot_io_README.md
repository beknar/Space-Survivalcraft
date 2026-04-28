# `bot_io/` — supervised-bot file-exchange protocol

This directory is the message bus between `bot_supervised.py` (the
runtime) and a remote operator (Claude in Claude Code).  Both sides
communicate by reading + writing files in this directory.

## Files written by the bot

### `status.json`

Updated every iteration, **before** waiting for a command.

```json
{
  "snapshot_id": 7,
  "snapshot_path": ".../bot_io/snapshot_0007.png",
  "phase": "in_game",
  "last_command_id": 6,
  "timestamp": 1735200000.123,
  "paused": false,
  "stop": false
}
```

The operator should read `status.json` first to learn the current
`snapshot_id`, then read `snapshot_<id>.png`.

### `snapshot_<id>.png`

Raw screenshot of the game window (1280 × 800 by default — matches
`bot_play.WINDOW_W / WINDOW_H`).

The bot keeps every snapshot for the session; the operator can
diff old vs new if useful.

## Files written by the operator

### `command_<id>.json`

Must match the `snapshot_id` from `status.json`.  The bot polls
for this file with a 60 s timeout — if it doesn't appear, the
bot takes a fresh snapshot and increments `snapshot_id`.

```json
{
  "snapshot_id": 7,
  "actions": [
    {"type": "hold", "key": "space", "down": true},
    {"type": "press", "key": "w", "duration": 1.5},
    {"type": "tap", "key": "tab"},
    {"type": "click", "x": 640, "y": 400},
    {"type": "wait", "seconds": 0.3},
    {"type": "note", "text": "engaging asteroid cluster NE"}
  ],
  "screenshot_after_s": 2.0
}
```

`screenshot_after_s` is optional — defaults to 2.0 s.  Use
shorter values (0.3 – 0.8) when the game state is fluid (combat),
longer (3 – 5 s) when waiting for something to happen
(asteroid drift, boss spawn).

## Action types

| `type`         | Required keys     | Notes |
|----------------|-------------------|-------|
| `press`        | `key`, `duration` | Hold key for `duration` seconds, then release.  Use `duration: 0` (or omit) for a single tap. |
| `tap`          | `key`             | Single press + release (same as `press` with no duration). |
| `hold`         | `key`, `down`     | Persistent keyDown / keyUp.  Use to maintain auto-fire across multiple frames. |
| `click`        | `x`, `y`          | Game-window coordinates (arcade-style: y from BOTTOM, 0 to 800). |
| `click_screen` | `x`, `y`          | Raw screen coordinates (pyautogui-style: y from TOP). |
| `move`         | `x`, `y`, `duration` | Move mouse to game-window coord without clicking. |
| `wait`         | `seconds`         | Sleep before the next action. |
| `type`         | `text`            | Type a string (for save-slot names etc.). |
| `note`         | `text`            | No-op — printed to bot stdout for telemetry. |

Unknown action types are logged + skipped.

## Operator workflow (Claude side)

```python
# 1. Read status to find current snapshot id.
import json, pathlib
status = json.loads(pathlib.Path("bot_io/status.json").read_text())
snap_id = status["snapshot_id"]

# 2. Read the screenshot.
#    In Claude Code: Read("bot_io/snapshot_0007.png")
#    The Read tool returns the image as a multimodal block.

# 3. Decide what to do.  Plan a list of actions.

# 4. Write the command file atomically.
cmd = {
    "snapshot_id": snap_id,
    "actions": [
        {"type": "hold", "key": "space", "down": True},
        {"type": "press", "key": "w", "duration": 1.0},
    ],
    "screenshot_after_s": 1.5,
}
pathlib.Path(f"bot_io/command_{snap_id:04d}.json").write_text(
    json.dumps(cmd, indent=2))

# 5. Loop — re-read status until snap_id increments,
#    then repeat.
```

## Tips

- **Auto-fire**: send `{"type": "hold", "key": "space", "down": true}`
  once at the start of combat, leave it on, and toggle off only
  when entering a menu / inventory / build mode.  Saves dozens of
  per-frame action entries.

- **Weapon cycling**: `{"type": "tap", "key": "tab"}` cycles
  Basic Laser → Mining Beam → Energy Blade.  Tab again to wrap.

- **Reading HP**: the HP bar is on the left side of the screen,
  inside the status panel.  Look at the green bar's fill ratio in
  the screenshot to estimate HP %.

- **Reading minimap**: bottom-right of the screen.  Red dots are
  enemies, blue dots are buildings, the player is the bright dot
  at the centre.

- **Aborting**: the operator can write a command with a single
  `{"type": "tap", "key": "escape"}` to bail out of any open menu,
  then re-plan.

- **Game window position**: top-left corner is at screen (100, 50)
  unless you bumped `bot_play.WINDOW_X / WINDOW_Y`.  Game-window
  click coords always assume 1280 × 800.
