"""Supervised auto-play bot — Claude is the loop.

Companion to ``bot_play.py``.  Where ``bot_play.py`` runs an
autonomous strategy in pure code, this script delegates the
**decisions** to a remote operator (typically Claude in
Claude Code) via a screenshot ↔ command file-exchange protocol.

Architecture:

    ┌──────────────┐   snapshot_<id>.png    ┌─────────┐
    │  bot_super-  │──────────────────────▶ │ Claude  │
    │  vised.py    │                        │ reads + │
    │  (this file) │◀── command_<id>.json ──│ writes  │
    └──────────────┘                        └─────────┘

The bot loop:

  1. Take a screenshot of the game window.
  2. Save as ``bot_io/snapshot_<id>.png``.
  3. Update ``bot_io/status.json`` with the current id, phase,
     and timestamp.
  4. Wait for ``bot_io/command_<id>.json`` to appear (or for
     ``DEFAULT_DECISION_TIMEOUT_S`` to elapse — in which case
     the bot just takes another snapshot).
  5. Execute every action in the command file in order.
  6. Loop.

Claude's loop (run from a separate Claude Code session):

  1. Read ``bot_io/status.json`` to find the current snapshot id.
  2. Read ``bot_io/snapshot_<id>.png``.
  3. Analyse the image (HP, enemies, position, menu state).
  4. Write ``bot_io/command_<id>.json`` with the next actions.
  5. Loop.

Command schema (``command_<id>.json``):

    {
      "snapshot_id": <int>,             // must match the snapshot
      "actions": [
        {"type": "press", "key": "w", "duration": 1.0},
        {"type": "tap", "key": "tab"},
        {"type": "click", "x": 640, "y": 400},  // game-window coords
        {"type": "click_screen", "x": 740, "y": 450},  // raw screen
        {"type": "hold", "key": "space", "down": true},
        {"type": "hold", "key": "space", "down": false},
        {"type": "wait", "seconds": 0.5},
        {"type": "type", "text": "hello"},
        {"type": "note", "text": "Boss is at top-right"}
      ],
      "screenshot_after_s": 2.0          // optional, default 2.0
    }

Hotkeys (same as bot_play.py — global):

    Ctrl+Shift+P  pause / resume
    Ctrl+Shift+R  abort current snapshot wait + take fresh shot
    Ctrl+Shift+Q  stop the bot AND kill the game

Run from a terminal:

    pip install pyautogui pygetwindow pynput pillow
    python bot_supervised.py

The bot will launch the game, drive splash → selection (random),
load a music video, then enter the supervised loop.  Claude takes
over from there.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

try:
    import pyautogui
    from pynput import keyboard
except ImportError as e:
    print(f"ERROR: missing dependency: {e.name}.  Install with:")
    print("    pip install pyautogui pygetwindow pynput pillow")
    sys.exit(1)

# Reuse helpers from the autonomous bot.  Keeps the launch +
# window + splash + selection code in one place.
import bot_play
from bot_play import (
    BotState, _wait, click_game, gx, gy,
    WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H,
    patch_settings_for_video, launch_game, find_and_position_window,
    click_play_now, random_selection, load_random_music_video,
)


# ── IO directory ──────────────────────────────────────────────────────────

BOT_IO_DIR = Path(__file__).resolve().parent / "bot_io"
STATUS_FILE = BOT_IO_DIR / "status.json"
DEFAULT_SCREENSHOT_AFTER_S: float = 2.0
DEFAULT_DECISION_TIMEOUT_S: float = 60.0   # take a new snapshot if Claude is slow


def _ensure_io_dir() -> None:
    BOT_IO_DIR.mkdir(exist_ok=True)
    # Wipe stale snapshots / commands from prior runs so id numbering
    # always starts fresh.
    for p in BOT_IO_DIR.glob("snapshot_*.png"):
        p.unlink()
    for p in BOT_IO_DIR.glob("command_*.json"):
        p.unlink()


# ── Screenshot ────────────────────────────────────────────────────────────

def take_snapshot(snapshot_id: int) -> Path:
    """Capture the game window (region: WINDOW_X..+W, WINDOW_Y..+H)
    and save under ``bot_io/snapshot_<id>.png``."""
    region = (WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H)
    img = pyautogui.screenshot(region=region)
    path = BOT_IO_DIR / f"snapshot_{snapshot_id:04d}.png"
    img.save(path)
    return path


def write_status(snapshot_id: int, phase: str,
                 last_command_id: int | None) -> None:
    """Update status.json so Claude knows what to read next."""
    STATUS_FILE.write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "snapshot_path": str(BOT_IO_DIR / f"snapshot_{snapshot_id:04d}.png"),
        "phase": phase,
        "last_command_id": last_command_id,
        "timestamp": time.time(),
        "paused": BotState.paused,
        "stop": BotState.stop,
    }, indent=2))


# ── Command polling ───────────────────────────────────────────────────────

def wait_for_command(snapshot_id: int,
                     timeout_s: float = DEFAULT_DECISION_TIMEOUT_S) -> dict | None:
    """Poll for ``command_<id>.json`` matching ``snapshot_id``.
    Returns the parsed command dict, or None on timeout / hotkey
    interrupt."""
    cmd_path = BOT_IO_DIR / f"command_{snapshot_id:04d}.json"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if BotState.stop or BotState.restart:
            return None
        if BotState.paused:
            time.sleep(0.1)
            deadline += 0.1
            continue
        if cmd_path.exists():
            try:
                data = json.loads(cmd_path.read_text())
            except json.JSONDecodeError:
                # File still being written — wait a beat.
                time.sleep(0.1)
                continue
            if data.get("snapshot_id") == snapshot_id:
                return data
            # Mismatched id (probably stale) — ignore + keep waiting.
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    print(f"[bot] command timeout for snapshot {snapshot_id}")
    return None


# ── Action execution ──────────────────────────────────────────────────────

def execute_actions(actions: list[dict]) -> None:
    """Run each action in sequence.  Unknown action types are logged
    and skipped (so a typo doesn't kill the session)."""
    for i, act in enumerate(actions):
        if BotState.stop or BotState.restart:
            return
        atype = act.get("type", "").lower()
        try:
            if atype == "press":
                key = act["key"]
                duration = float(act.get("duration", 0.0))
                if duration > 0.0:
                    pyautogui.keyDown(key)
                    if not _wait(duration):
                        pyautogui.keyUp(key)
                        return
                    pyautogui.keyUp(key)
                else:
                    pyautogui.press(key)
            elif atype == "tap":
                pyautogui.press(act["key"])
            elif atype == "hold":
                key = act["key"]
                if act.get("down", True):
                    pyautogui.keyDown(key)
                else:
                    pyautogui.keyUp(key)
            elif atype == "click":
                # Game-window coords (arcade-style: y from BOTTOM).
                click_game(float(act["x"]), float(act["y"]))
            elif atype == "click_screen":
                # Raw screen coords (pyautogui-style: y from TOP).
                pyautogui.click(int(act["x"]), int(act["y"]))
            elif atype == "move":
                pyautogui.moveTo(gx(float(act["x"])), gy(float(act["y"])),
                                 duration=float(act.get("duration", 0.1)))
            elif atype == "wait":
                if not _wait(float(act["seconds"])):
                    return
            elif atype == "type":
                pyautogui.typewrite(act["text"], interval=0.02)
            elif atype == "note":
                # Logging hook for Claude — surfaced in stdout so the
                # operator can correlate decisions with timestamps.
                print(f"[bot] note: {act.get('text', '')}")
            else:
                print(f"[bot] WARN: unknown action[{i}] type={atype!r}")
        except Exception as e:
            print(f"[bot] action[{i}] {atype!r} failed: {e}")


# ── Supervised loop ───────────────────────────────────────────────────────

def supervised_loop(max_iterations: int = 10000) -> None:
    """Snapshot → wait-for-command → execute → repeat."""
    print(f"[bot] supervised loop: io dir = {BOT_IO_DIR}")
    print("[bot] Claude reads:  bot_io/status.json + snapshot_<id>.png")
    print("[bot] Claude writes: bot_io/command_<id>.json")
    snapshot_id = 0
    last_command_id: int | None = None
    next_screenshot_after_s = 0.0

    while snapshot_id < max_iterations:
        if BotState.stop:
            return
        if BotState.paused:
            time.sleep(0.2)
            continue

        if next_screenshot_after_s > 0.0:
            if not _wait(next_screenshot_after_s):
                if BotState.stop:
                    return
                # Restart hotkey only — drop into a fresh snapshot.
                BotState.restart = False

        snap_path = take_snapshot(snapshot_id)
        write_status(snapshot_id, phase="in_game",
                     last_command_id=last_command_id)
        print(f"[bot] snapshot {snapshot_id:04d} → {snap_path.name}")

        cmd = wait_for_command(snapshot_id)
        if cmd is None:
            # Timeout / interrupt — treat as a no-op tick and move on.
            next_screenshot_after_s = DEFAULT_SCREENSHOT_AFTER_S
            snapshot_id += 1
            continue

        actions = cmd.get("actions", [])
        next_screenshot_after_s = float(
            cmd.get("screenshot_after_s", DEFAULT_SCREENSHOT_AFTER_S))
        print(f"[bot] command {snapshot_id:04d}: "
              f"{len(actions)} action(s), next snapshot in "
              f"{next_screenshot_after_s:.1f}s")
        execute_actions(actions)
        last_command_id = snapshot_id
        snapshot_id += 1


# ── Top-level orchestration ───────────────────────────────────────────────

def run_session() -> None:
    BotState.restart = False
    _ensure_io_dir()
    patch_settings_for_video()
    proc = launch_game()
    try:
        if not find_and_position_window():
            return
        if not _wait(1.5): return
        click_play_now()
        if not _wait(2.0): return
        random_selection()
        if not _wait(3.0): return
        load_random_music_video()
        if not _wait(1.0): return
        supervised_loop()
    finally:
        if proc.poll() is None:
            print("[bot] terminating game subprocess")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


def main() -> None:
    print("=" * 60)
    print("Call of Orion — supervised auto-play bot")
    print("Hotkeys: Ctrl+Shift+P pause | Ctrl+Shift+R fresh-shot | Ctrl+Shift+Q quit")
    print(f"IO dir : {BOT_IO_DIR}")
    print("=" * 60)
    listener = threading.Thread(
        target=bot_play._hotkey_listener, daemon=True)
    listener.start()
    while not BotState.stop:
        run_session()
        if BotState.stop:
            break
        if BotState.restart:
            print("[bot] restarting in 2 s...")
            time.sleep(2)
            continue
        break
    print("[bot] done")


if __name__ == "__main__":
    main()
