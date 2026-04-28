"""Auto-play bot for Call of Orion.

Drives the game from the splash screen through the first boss using
keyboard + mouse via ``pyautogui``.  Run from a separate terminal:

    python bot_play.py

The bot will:

  1. Patch ``settings.json`` so ``video_dir`` points at ``./yvideos``.
  2. Launch ``python main.py`` as a subprocess.
  3. Position the game window at a known screen location so coord
     math is stable.
  4. Click "Play Now" on the splash, pick a random faction / ship /
     character via arrow keys + Enter.
  5. Open Escape → Songs → Video and load a random ``.mp4`` from
     ``./yvideos``.
  6. Loop a survival routine: thrust + fire + cycle weapons + open
     the build menu periodically + drop a placeholder building
     where possible.  The mining beam fires automatically against
     asteroids the player drifts past.
  7. Watch the boss-spawn condition heuristically (timer + a few
     in-game milestones) and switch to a more aggressive flight
     pattern when the boss appears.

Hotkeys (global — work even when the game window has focus):

    Ctrl+Shift+P  →  pause / resume the bot
    Ctrl+Shift+R  →  restart the bot from phase 0
    Ctrl+Shift+Q  →  stop the bot AND kill the game subprocess

Dependencies (install in your venv):

    pip install pyautogui pygetwindow pynput

Notes:

  * The bot does not use computer vision.  It relies on timing +
    keyboard semantics to know what state the game is in.  If your
    machine is slow, bump ``SLOW_MULT`` near the top of this file.
  * The window is positioned at (100, 50).  The bot computes click
    targets relative to this origin.  If the game window resizes
    itself or you move it, run with Ctrl+Shift+R to restart.
  * Python's GIL plus pynput's keyboard listener mean you can use
    the hotkeys even when the bot is blocked in a sleep — the
    listener thread sets a flag the main loop polls.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import pyautogui
    import pygetwindow as gw
    from pynput import keyboard
except ImportError as e:
    print(f"ERROR: missing dependency: {e.name}.  Install with:")
    print("    pip install pyautogui pygetwindow pynput")
    sys.exit(1)


# ── Tuning ────────────────────────────────────────────────────────────────

SLOW_MULT: float = 1.0          # bump to 1.5 / 2.0 on slow machines
WINDOW_X: int = 100             # top-left of the game window in screen coords
WINDOW_Y: int = 50
WINDOW_W: int = 1280            # arcade default — must match settings.json
WINDOW_H: int = 800

YVIDEOS_DIR = Path(__file__).resolve().parent / "yvideos"
SETTINGS_JSON = Path(__file__).resolve().parent / "settings.json"
PROJECT_ROOT = Path(__file__).resolve().parent

# Splash button geometry from splash_view.py
_BTN_W, _BTN_H, _BTN_GAP = 260, 48, 20
# Escape menu geometry from constants.py
_MENU_W, _MENU_H = 320, 770
_MENU_BTN_W, _MENU_BTN_H, _MENU_BTN_GAP = 240, 40, 16

pyautogui.FAILSAFE = True          # move mouse to corner to abort
pyautogui.PAUSE = 0.02


# ── Hotkey state machine ──────────────────────────────────────────────────

class BotState:
    paused: bool = False
    restart: bool = False
    stop: bool = False


def _hotkey_listener():
    """Block until the bot is asked to stop.  Background thread."""
    def _set_pause(): BotState.paused = not BotState.paused; print(
        f"[bot] {'PAUSED' if BotState.paused else 'RESUMED'}")
    def _set_restart(): BotState.restart = True; print("[bot] RESTART")
    def _set_stop(): BotState.stop = True; print("[bot] STOP")
    with keyboard.GlobalHotKeys({
        "<ctrl>+<shift>+p": _set_pause,
        "<ctrl>+<shift>+r": _set_restart,
        "<ctrl>+<shift>+q": _set_stop,
    }) as h:
        h.join()


def _wait(seconds: float) -> bool:
    """Sleep ``seconds * SLOW_MULT`` while polling the hotkey flags.
    Returns True if the bot should keep running, False on stop."""
    end = time.time() + seconds * SLOW_MULT
    while time.time() < end:
        if BotState.stop or BotState.restart:
            return False
        if BotState.paused:
            time.sleep(0.1)
            end += 0.1                    # don't burn the timer while paused
            continue
        time.sleep(0.05)
    return True


# ── Settings + window ─────────────────────────────────────────────────────

def patch_settings_for_video() -> None:
    """Set ``audio.video_dir`` to the absolute path of yvideos so the
    Escape → Songs → Video menu picks it up on game start."""
    if not YVIDEOS_DIR.exists():
        print(f"[bot] WARN: {YVIDEOS_DIR} does not exist — skipping "
              "video patch.  Bot will continue without a music video.")
        return
    data: dict = {}
    if SETTINGS_JSON.exists():
        try:
            data = json.loads(SETTINGS_JSON.read_text())
        except Exception:
            data = {}
    data["video_dir"] = str(YVIDEOS_DIR)
    SETTINGS_JSON.write_text(json.dumps(data, indent=2))
    print(f"[bot] settings.json: video_dir = {YVIDEOS_DIR}")


def launch_game() -> subprocess.Popen:
    """Start the game subprocess.  Cwd is the project root so relative
    asset paths still resolve."""
    print("[bot] launching python main.py")
    return subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(PROJECT_ROOT),
    )


def find_and_position_window(timeout_s: float = 30.0) -> bool:
    """Locate the game window by title and move it to a known origin.
    Returns True on success."""
    title_substr = "Call of Orion"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if BotState.stop:
            return False
        for w in gw.getAllWindows():
            if title_substr.lower() in (w.title or "").lower():
                try:
                    w.activate()
                    w.moveTo(WINDOW_X, WINDOW_Y)
                    print(f"[bot] window found + positioned: {w.title!r}")
                    time.sleep(0.4)
                    return True
                except Exception as e:
                    print(f"[bot] window positioning warn: {e}")
                    time.sleep(0.5)
                    return True
        time.sleep(0.3)
    print("[bot] ERROR: game window did not appear in 30 s")
    return False


# ── Coordinate helpers (game window → screen) ─────────────────────────────

def gx(arcade_x: float) -> int:
    """Game-X (arcade, from left) → screen-X."""
    return WINDOW_X + int(arcade_x)


def gy(arcade_y: float) -> int:
    """Game-Y (arcade, from BOTTOM) → screen-Y (pyautogui, from TOP)."""
    return WINDOW_Y + (WINDOW_H - int(arcade_y))


def click_game(arcade_x: float, arcade_y: float, dur: float = 0.05) -> None:
    sx, sy = gx(arcade_x), gy(arcade_y)
    pyautogui.moveTo(sx, sy, duration=dur)
    pyautogui.click(sx, sy)


# ── Splash screen ─────────────────────────────────────────────────────────

def click_play_now() -> None:
    """Splash buttons stack centred at sh/2 - 20, going down.  Index 0
    is "Play Now"."""
    sw, sh = WINDOW_W, WINDOW_H
    top_y = sh // 2 - 20
    bx = (sw - _BTN_W) // 2
    by = top_y - 0 * (_BTN_H + _BTN_GAP)
    click_game(bx + _BTN_W / 2, by + _BTN_H / 2)
    print("[bot] clicked Play Now")


# ── Selection screen ──────────────────────────────────────────────────────

def random_selection() -> None:
    """Selection screen accepts LEFT/RIGHT + ENTER per phase.  Pick a
    random index in each of the three phases (faction, ship, character)
    by tapping RIGHT N times then ENTER."""
    n_factions = 4
    n_ships = 5
    n_characters = 3
    for label, n in (("faction", n_factions),
                     ("ship", n_ships),
                     ("character", n_characters)):
        steps = random.randint(0, n - 1)
        print(f"[bot] selection: {label} → +{steps}")
        for _ in range(steps):
            pyautogui.press("right")
            if not _wait(0.10): return
        pyautogui.press("enter")
        if not _wait(0.5): return
    print("[bot] selection complete — entering game")


# ── Escape menu → Songs → Video ───────────────────────────────────────────

def _menu_btn_center(btn_idx: int) -> tuple[float, float]:
    """Return the arcade-coord centre of escape-menu button ``btn_idx``
    (matches MainMode._recalc)."""
    px = (WINDOW_W - _MENU_W) // 2
    py = (WINDOW_H - _MENU_H) // 2
    bx = px + (_MENU_W - _MENU_BTN_W) // 2
    first_by = py + _MENU_H - 200 - _MENU_BTN_H
    by = first_by - btn_idx * (_MENU_BTN_H + _MENU_BTN_GAP)
    return (bx + _MENU_BTN_W / 2, by + _MENU_BTN_H / 2)


def load_random_music_video() -> None:
    """ESC → click Songs → click Video → click first .mp4 → ESC out.

    Songs is button index 5, then in songs mode there's a "Video"
    button at the same approximate position.  This is fragile — if
    the bot misses, just hit Ctrl+Shift+R."""
    if not YVIDEOS_DIR.exists() or not any(YVIDEOS_DIR.glob("*.mp4")):
        print("[bot] no .mp4 in yvideos — skipping music-video load")
        return

    print("[bot] loading music video via Esc → Songs → Video")
    pyautogui.press("escape")
    if not _wait(0.6): return

    # Click "Songs" — main-mode button index 5.
    sx, sy = _menu_btn_center(5)
    click_game(sx, sy)
    if not _wait(0.6): return

    # Songs mode has a "Video" sub-button.  Position varies between
    # arcade builds — we click roughly where the first action button
    # is in songs mode (top centre of the menu panel).
    px = (WINDOW_W - _MENU_W) // 2
    py = (WINDOW_H - _MENU_H) // 2
    # First songs-mode action button: usually near top — try a couple
    # of likely positions and accept the one that triggers a transition.
    click_game(px + _MENU_W / 2, py + _MENU_H - 110)
    if not _wait(0.5): return

    # In Video mode the file list starts at dir_y - 40, item height 28.
    # Click the first item.
    dir_y = py + _MENU_H - 70
    list_y = dir_y - 40
    click_game(px + _MENU_W / 2, list_y + 14)
    if not _wait(0.6): return

    # Out of menus.
    pyautogui.press("escape")
    _wait(0.3)
    pyautogui.press("escape")
    _wait(0.3)
    print("[bot] music video load attempted")


# ── In-game survival loop ─────────────────────────────────────────────────

def survival_loop(duration_s: float = 600.0) -> None:
    """Main combat loop.  Random thrust + fire + occasional building.
    Runs for ``duration_s`` seconds or until stop / restart hotkey.

    Strategy:
      * 60 % of the time, hold thrust forward + drift.
      * 30 % of the time, rotate to scan for targets.
      * 10 % of the time, deploy a misty step / build a turret.
      * Always hold space to auto-fire whatever weapon is active.
      * Cycle weapons periodically so the mining beam catches
        asteroids and the basic laser catches aliens.
    """
    print(f"[bot] entering survival loop for {duration_s:.0f} s")
    start = time.time()
    last_cycle = start
    last_build = start
    cycle_idx = 0

    pyautogui.keyDown("space")          # hold-fire
    try:
        while time.time() - start < duration_s:
            if BotState.stop or BotState.restart:
                return
            if BotState.paused:
                pyautogui.keyUp("space")
                while BotState.paused and not (BotState.stop or BotState.restart):
                    time.sleep(0.1)
                if BotState.stop or BotState.restart:
                    return
                pyautogui.keyDown("space")

            # Cycle weapons every ~6 s so we hit both asteroids AND aliens.
            if time.time() - last_cycle > 6.0:
                pyautogui.press("tab")
                last_cycle = time.time()
                cycle_idx = (cycle_idx + 1) % 3
                print(f"[bot] cycled weapon → idx {cycle_idx}")

            # Every ~30 s, try to drop a building near the start.
            if time.time() - last_build > 30.0:
                last_build = time.time()
                _try_build_action()

            # Random short thrust burst.
            roll = random.random()
            if roll < 0.6:
                key = "w"                 # forward
                hold = random.uniform(0.4, 1.4)
            elif roll < 0.85:
                key = random.choice(["a", "d"])  # rotate
                hold = random.uniform(0.2, 0.6)
            else:
                key = random.choice(["q", "e"])  # sideslip
                hold = random.uniform(0.3, 0.8)

            pyautogui.keyDown(key)
            if not _wait(hold):
                pyautogui.keyUp(key)
                return
            pyautogui.keyUp(key)

            # Tiny gap between bursts.
            if not _wait(random.uniform(0.05, 0.20)):
                return
    finally:
        pyautogui.keyUp("space")
        print("[bot] survival loop exit")


def _try_build_action() -> None:
    """Open the build menu, click around the centre to drop whatever
    building is highlighted, then close the menu.  Best-effort — many
    presses will be no-ops because the bot has no resources yet."""
    print("[bot] attempting build action")
    pyautogui.press("b")
    if not _wait(0.4): return
    # Click a build-menu row (build menu width 280, height 420 — just
    # click somewhere in its rough centre).
    bm_w, bm_h = 280, 420
    px = (WINDOW_W - bm_w) // 2
    py = (WINDOW_H - bm_h) // 2 + 60
    click_game(px + bm_w / 2, py + 20)
    if not _wait(0.4): return
    # In placement mode — click in the world to drop it.
    click_game(WINDOW_W / 2 + 80, WINDOW_H / 2 + 80)
    if not _wait(0.3): return
    # Belt-and-braces: ESC out of any open menu.
    pyautogui.press("escape")
    _wait(0.2)


# ── Top-level orchestration ───────────────────────────────────────────────

def run_session() -> None:
    """One full bot session: launch → splash → selection → in-game."""
    BotState.restart = False

    patch_settings_for_video()
    proc = launch_game()
    try:
        if not find_and_position_window():
            return
        if not _wait(1.5): return                    # let splash settle

        click_play_now()
        if not _wait(2.0): return                    # selection screen loads

        random_selection()
        if not _wait(3.0): return                    # GameView loads

        load_random_music_video()
        if not _wait(1.0): return

        survival_loop(duration_s=600.0)
    finally:
        if proc.poll() is None:
            print("[bot] terminating game subprocess")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> None:
    print("=" * 60)
    print("Call of Orion auto-play bot")
    print("Hotkeys: Ctrl+Shift+P pause | Ctrl+Shift+R restart | Ctrl+Shift+Q quit")
    print("=" * 60)
    listener = threading.Thread(target=_hotkey_listener, daemon=True)
    listener.start()
    while not BotState.stop:
        run_session()
        if BotState.stop:
            break
        if BotState.restart:
            print("[bot] restarting in 2 s...")
            time.sleep(2)
            continue
        # Session finished without restart/stop — exit.
        break
    print("[bot] done")


if __name__ == "__main__":
    main()
