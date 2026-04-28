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
  5. Open Escape -> Songs -> Video and load a random ``.mp4`` from
     ``./yvideos``.
  6. Loop a survival routine: thrust + fire + cycle weapons + open
     the build menu periodically + drop a placeholder building
     where possible.  The mining beam fires automatically against
     asteroids the player drifts past.
  7. Watch the boss-spawn condition heuristically (timer + a few
     in-game milestones) and switch to a more aggressive flight
     pattern when the boss appears.

Hotkeys (global -- work even when the game window has focus):

    Ctrl+Shift+P  ->  pause / resume the bot
    Ctrl+Shift+R  ->  restart the bot from phase 0
    Ctrl+Shift+Q  ->  stop the bot AND kill the game subprocess

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
    the hotkeys even when the bot is blocked in a sleep -- the
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

# Reconfigure stdout to UTF-8 so the various unicode arrows used in
# log messages don't crash the bot on Windows' default cp1252 console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
WINDOW_X: int = 100             # top-left of the game window CLIENT area in PHYSICAL pixels
WINDOW_Y: int = 50
WINDOW_W: int = 1280            # game window CLIENT width in PHYSICAL pixels
WINDOW_H: int = 800             # game window CLIENT height in PHYSICAL pixels

# The game renders against an arcade-logical 1280x800 coordinate
# system regardless of how Windows DPI scaling stretches the
# rendered output.  Clicks computed from splash_view.py /
# escape_menu/_main_mode.py constants are LOGICAL; they need to
# be scaled by ``WINDOW_W / LOGICAL_W`` to land on the right
# physical pixel after positioning + Windows scaling.
LOGICAL_W: int = 1280
LOGICAL_H: int = 800

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


# ── DPI awareness (Windows) ───────────────────────────────────────────────

def set_dpi_awareness() -> None:
    """On Windows with display scaling != 100 %, ``pygetwindow``
    reports / sets logical pixels while ``pyautogui`` operates in
    physical pixels.  That mismatch makes the bot's screenshots,
    clicks, and window-positioning land on the wrong area of the
    screen -- observed end-to-end as "the bot screenshots the
    desktop and clicks miss the game window".

    Calling ``SetProcessDpiAwareness(2)`` (PROCESS_PER_MONITOR_DPI_AWARE)
    flips this process into physical-pixel mode for both libraries,
    so every coordinate uses the same units.

    Idempotent + no-op on non-Windows.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE.  Falls back to the older
        # SetProcessDPIAware() if shcore isn't available (pre-Win 8.1).
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
        print("[bot] DPI awareness set: physical-pixel coords")
    except Exception as e:
        print(f"[bot] WARN: SetProcessDpiAwareness failed: {e}")


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
    Escape -> Songs -> Video menu picks it up on game start."""
    if not YVIDEOS_DIR.exists():
        print(f"[bot] WARN: {YVIDEOS_DIR} does not exist -- skipping "
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
    """Locate the game window by title, move it to a known origin,
    then **read back** its actual position + size and update the
    module-level ``WINDOW_X / WINDOW_Y / WINDOW_W / WINDOW_H``
    globals so every subsequent click and screenshot uses the
    real coordinates (not the request).  This catches:

      * DPI scaling making moveTo land on a different physical pixel.
      * Windows snapping the window to a monitor edge / taskbar.
      * The arcade view choosing a different size than 1280x800
        because of resolution presets in settings.json.

    Also runs a probe screenshot + uniformity check: if the captured
    region is mostly the same colour, the game window is almost
    certainly NOT at the captured location.  Returns False so the
    bot can bail out cleanly instead of writing 100 desktop snapshots.
    """
    global WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H
    title_substr = "Call of Orion"
    deadline = time.time() + timeout_s
    target = None
    while time.time() < deadline:
        if BotState.stop:
            return False
        for w in gw.getAllWindows():
            if title_substr.lower() in (w.title or "").lower():
                target = w
                break
        if target is not None:
            break
        time.sleep(0.3)
    if target is None:
        print("[bot] ERROR: game window did not appear in 30 s")
        return False

    try:
        target.activate()
        target.moveTo(WINDOW_X, WINDOW_Y)
        time.sleep(0.5)            # let Windows settle the move
        # Prefer the Win32 CLIENT rect (excludes title bar + borders)
        # so click coords land inside the actual game viewport, not
        # on the chrome.  Fall back to pygetwindow's full-window rect
        # on non-Windows.
        client = _get_client_rect_via_win32(target)
        if client is not None:
            actual_x, actual_y, actual_w, actual_h = client
            print(f"[bot] window {target.title!r} CLIENT rect: "
                  f"({actual_x},{actual_y}) size {actual_w}x{actual_h}")
        else:
            actual_x, actual_y = int(target.left), int(target.top)
            actual_w, actual_h = int(target.width), int(target.height)
            print(f"[bot] window {target.title!r} (full rect) "
                  f"({actual_x},{actual_y}) size {actual_w}x{actual_h}")
        WINDOW_X, WINDOW_Y = actual_x, actual_y
        WINDOW_W, WINDOW_H = actual_w, actual_h
    except Exception as e:
        # SetForegroundWindow on Windows often returns success-as-error
        # ("The operation completed successfully") via pygetwindow's
        # WindowsError translation.  Don't treat this as fatal -- the
        # window is usually positioned correctly anyway, and we still
        # try the client rect probe below.
        print(f"[bot] window positioning warn: {e}")
        client = _get_client_rect_via_win32(target)
        if client is not None:
            WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H = client
            print(f"[bot] window CLIENT rect (post-warn): "
                  f"({WINDOW_X},{WINDOW_Y}) size {WINDOW_W}x{WINDOW_H}")

    # Probe the captured region -- if it's nearly-uniform, we're
    # almost certainly screenshotting the desktop, not the game.
    if not _probe_screenshot_looks_like_game():
        print("[bot] ERROR: probe screenshot looks uniform -- coords "
              "still wrong.  Run with the game window visible on the "
              "primary monitor and try again.")
        return False
    return True


def _get_client_rect_via_win32(target) -> tuple[int, int, int, int] | None:
    """Return (left, top, width, height) of the window's CLIENT
    area in physical screen pixels using Win32 GetClientRect +
    ClientToScreen.  None on non-Windows or on failure."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = getattr(target, "_hWnd", None) or getattr(
            target, "hWnd", None)
        if hwnd is None:
            return None
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetClientRect(
                hwnd, ctypes.byref(rect)):
            return None
        pt = wintypes.POINT(rect.left, rect.top)
        if not ctypes.windll.user32.ClientToScreen(
                hwnd, ctypes.byref(pt)):
            return None
        return (pt.x, pt.y,
                rect.right - rect.left,
                rect.bottom - rect.top)
    except Exception as e:
        print(f"[bot] client-rect probe failed: {e}")
        return None


def _probe_screenshot_looks_like_game(min_unique_colors: int = 200) -> bool:
    """Take a screenshot of the configured game-window region and
    count distinct colours.  The game (HUD + starfield + UI) easily
    produces 1000+ unique colours; the desktop in any region of a
    typical wallpaper produces far fewer in the tested area.  Below
    the threshold -> probably not the game.
    """
    try:
        region = (WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H)
        img = pyautogui.screenshot(region=region)
        # Sample every 10th pixel along each axis to keep the count cheap.
        thumb = img.resize((img.width // 10, img.height // 10))
        colors = thumb.getcolors(maxcolors=thumb.width * thumb.height)
        if colors is None:
            # Pillow returns None when the unique-color count exceeds
            # ``maxcolors``; we asked for the max possible, so this
            # only happens for highly varied images = definitely a game.
            return True
        n_unique = len(colors)
        print(f"[bot] probe screenshot: {n_unique} unique colours "
              f"(threshold {min_unique_colors})")
        return n_unique >= min_unique_colors
    except Exception as e:
        print(f"[bot] probe failed (assume OK): {e}")
        return True


# ── Coordinate helpers (game window -> screen) ─────────────────────────────

def gx(arcade_x: float) -> int:
    """Game-X (arcade-logical, 0..LOGICAL_W) -> physical screen-X.
    Scales by the actual client-area width to handle Windows DPI."""
    scale = WINDOW_W / LOGICAL_W
    return WINDOW_X + int(arcade_x * scale)


def gy(arcade_y: float) -> int:
    """Game-Y (arcade-logical, 0..LOGICAL_H, from BOTTOM) ->
    physical screen-Y (pyautogui, from TOP).  Scales by the
    actual client-area height to handle Windows DPI."""
    scale = WINDOW_H / LOGICAL_H
    return WINDOW_Y + int((LOGICAL_H - arcade_y) * scale)


def click_game(arcade_x: float, arcade_y: float, dur: float = 0.05) -> None:
    sx, sy = gx(arcade_x), gy(arcade_y)
    pyautogui.moveTo(sx, sy, duration=dur)
    pyautogui.click(sx, sy)


# ── Splash screen ─────────────────────────────────────────────────────────

def click_play_now() -> None:
    """Splash buttons stack centred at sh/2 - 20, going down.  Index 0
    is "Play Now".  Coords below are in arcade-LOGICAL units
    (1280x800); ``click_game`` -> ``gx/gy`` scales them to the
    actual physical client-area pixel."""
    sw, sh = LOGICAL_W, LOGICAL_H
    top_y = sh // 2 - 20
    bx = (sw - _BTN_W) // 2
    by = top_y - 0 * (_BTN_H + _BTN_GAP)
    click_game(bx + _BTN_W / 2, by + _BTN_H / 2)
    print("[bot] clicked Play Now")


# ── Selection screen ──────────────────────────────────────────────────────

def random_selection(faction_idx: int | None = None,
                     ship_idx: int | None = None,
                     character_idx: int | None = None) -> None:
    """Selection screen accepts LEFT/RIGHT + ENTER per phase.  Each
    phase index defaults to a uniform random choice; pass an int
    to pin that phase deterministically.  Index conventions:

      faction:    0=Earth, 1=Colonial, 2=Heavy World, 3=Ascended
      ship:       0=Cruiser, 1=Bastion, 2=Aegis, 3=Striker, 4=Thunderbolt
      character:  0..2 (Debra / Ellie / Tara — order matches
                  ``character_data.CHARACTERS``)
    """
    n_factions = 4
    n_ships = 5
    n_characters = 3
    plan = [
        ("faction",   faction_idx,   n_factions),
        ("ship",      ship_idx,      n_ships),
        ("character", character_idx, n_characters),
    ]
    for label, fixed, n in plan:
        steps = fixed if fixed is not None else random.randint(0, n - 1)
        steps = max(0, min(n - 1, steps))
        print(f"[bot] selection: {label} -> +{steps}")
        for _ in range(steps):
            pyautogui.press("right")
            if not _wait(0.10): return
        pyautogui.press("enter")
        if not _wait(0.5): return
    print("[bot] selection complete -- entering game")


# ── Escape menu -> Songs -> Video ───────────────────────────────────────────

def _menu_btn_center(btn_idx: int) -> tuple[float, float]:
    """Return the arcade-LOGICAL-coord centre of escape-menu
    button ``btn_idx`` (matches MainMode._recalc).  ``click_game``
    will scale to physical via gx/gy."""
    px = (LOGICAL_W - _MENU_W) // 2
    py = (LOGICAL_H - _MENU_H) // 2
    bx = px + (_MENU_W - _MENU_BTN_W) // 2
    first_by = py + _MENU_H - 200 - _MENU_BTN_H
    by = first_by - btn_idx * (_MENU_BTN_H + _MENU_BTN_GAP)
    return (bx + _MENU_BTN_W / 2, by + _MENU_BTN_H / 2)


def load_random_music_video() -> None:
    """ESC -> Tab to Songs -> Enter -> Tab to Music Videos -> Enter ->
    Enter on first file -> ESC out.

    Uses the keyboard navigation added to the escape-menu modes
    (commits a34b61b + 13b6aae) so coord math + window-pos
    fragility are eliminated -- every press is a deterministic
    pyautogui keystroke that the menu's on_key_press handler
    consumes.

    Main-mode button order (per ``escape_menu/_main_mode._BUTTONS``):
        0=Resume, 1=Save, 2=Load, 3=Video Properties,
        4=Help,   5=Songs, 6=Main Menu

    Songs-mode focus order (per ``_songs_mode._activate_focus``):
        0=Stop Song, 1=Other Song, 2=Music Videos, 3=Back

    Video-mode keyboard focus is -1 on entry; a single Enter
    selects file index 0 (the first .mp4)."""
    if not YVIDEOS_DIR.exists() or not any(YVIDEOS_DIR.glob("*.mp4")):
        print("[bot] no .mp4 in yvideos -- skipping music-video load")
        return

    print("[bot] loading music video via Esc -> Tab/Enter chain")
    # Open escape menu.
    pyautogui.press("escape")
    if not _wait(0.6): return

    # Main mode: Tab from focus=-1 lands on idx 0 (Resume), so 6
    # Tabs total to reach Songs (idx 5).
    for _ in range(6):
        pyautogui.press("tab")
        if not _wait(0.05): return
    pyautogui.press("enter")
    if not _wait(0.4): return

    # Songs mode: 3 Tabs lands on Music Videos (idx 2).
    for _ in range(3):
        pyautogui.press("tab")
        if not _wait(0.05): return
    pyautogui.press("enter")
    if not _wait(0.5): return

    # Video mode: bare Enter focuses + activates the first file.
    pyautogui.press("enter")
    if not _wait(0.4): return

    # Out of menus -- two ESCs to dismiss songs + main.
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
                print(f"[bot] cycled weapon -> idx {cycle_idx}")

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
    building is highlighted, then close the menu.  Best-effort -- many
    presses will be no-ops because the bot has no resources yet."""
    print("[bot] attempting build action")
    pyautogui.press("b")
    if not _wait(0.4): return
    # Click a build-menu row (build menu width 280, height 420 -- just
    # click somewhere in its rough centre).  Arcade-LOGICAL coords.
    bm_w, bm_h = 280, 420
    px = (LOGICAL_W - bm_w) // 2
    py = (LOGICAL_H - bm_h) // 2 + 60
    click_game(px + bm_w / 2, py + 20)
    if not _wait(0.4): return
    # In placement mode -- click in the world to drop it.
    click_game(LOGICAL_W / 2 + 80, LOGICAL_H / 2 + 80)
    if not _wait(0.3): return
    # Belt-and-braces: ESC out of any open menu.
    pyautogui.press("escape")
    _wait(0.2)


# ── Top-level orchestration ───────────────────────────────────────────────

def run_session() -> None:
    """One full bot session: launch -> splash -> selection -> in-game."""
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
    set_dpi_awareness()
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
        # Session finished without restart/stop -- exit.
        break
    print("[bot] done")


if __name__ == "__main__":
    main()
