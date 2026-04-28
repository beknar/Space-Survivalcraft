"""Capture the game window to ``bot_io/BOTVIDEO-<...>.mp4``.

Spawns ``ffmpeg`` with the Windows ``gdigrab`` capture device
pointed at the "Call of Orion" window's client rect.  Polls
for the window once a second; once it appears, starts the
capture; once it disappears for more than ``GAME_GONE_GRACE_S``
seconds, sends ``q`` to ffmpeg's stdin so ffmpeg cleanly
finalises the MP4 container (faststart + moov atom written) and
the recorder exits.

Run alongside the autopilot:

    python bot_video_recorder.py            # foreground, exits with game
    python bot_video_recorder.py &          # background

``bot_kickoff.py`` launches it automatically (detached, so it
keeps recording after kickoff exits) -- that path is the
default in normal bot runs.

Hotkey:
    Ctrl+Shift+Q   stop the recorder + close out the MP4

Requirements:
  * ffmpeg on PATH (``ffmpeg -version`` works in your shell).
    Install: https://www.gyan.dev/ffmpeg/builds/ on Windows.
  * pygetwindow (already a bot dependency).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import pygetwindow as gw
    from pynput import keyboard
except ImportError as e:
    print(f"ERROR: missing dependency: {e.name}.")
    print("  pip install pygetwindow pynput")
    sys.exit(1)


# ── Tuning ────────────────────────────────────────────────────────────────

WINDOW_TITLE = "Call of Orion"
PROJECT_ROOT = Path(__file__).resolve().parent
BOT_IO_DIR = PROJECT_ROOT / "bot_io"

FRAME_RATE: int = 30                  # capture fps
GAME_GONE_GRACE_S: float = 5.0        # window absent this long -> stop
WINDOW_FIND_TIMEOUT_S: float = 60.0   # give up if the game never appears


class State:
    stop: bool = False


def _hotkeys():
    def _stop():
        State.stop = True
        print("[recorder] STOP")
    with keyboard.GlobalHotKeys({
        "<ctrl>+<shift>+q": _stop,
    }) as h:
        h.join()


# ── Window discovery ──────────────────────────────────────────────────────

def find_game_window():
    if gw is None:
        return None
    try:
        for w in gw.getAllWindows():
            if WINDOW_TITLE.lower() in (w.title or "").lower():
                return w
    except Exception:
        pass
    return None


def get_client_rect(target) -> tuple[int, int, int, int] | None:
    """Win32 GetClientRect + ClientToScreen for the actual game
    viewport (excludes title bar / borders).  Falls back to
    pygetwindow's full-window rect on failure."""
    if sys.platform != "win32":
        return _full_rect(target)
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = getattr(target, "_hWnd", None) or getattr(target, "hWnd", None)
        if hwnd is None:
            return _full_rect(target)
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return _full_rect(target)
        pt = wintypes.POINT(rect.left, rect.top)
        if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            return _full_rect(target)
        return (pt.x, pt.y,
                rect.right - rect.left,
                rect.bottom - rect.top)
    except Exception:
        return _full_rect(target)


def _full_rect(target) -> tuple[int, int, int, int] | None:
    try:
        return (int(target.left), int(target.top),
                int(target.width), int(target.height))
    except Exception:
        return None


# ── ffmpeg launcher ───────────────────────────────────────────────────────

def _ffmpeg_path() -> str | None:
    """Find the ffmpeg binary.  Tries PATH first, then a couple
    of well-known winget install locations on Windows so a fresh
    install works in the current shell without waiting for the
    PATH update to propagate."""
    p = shutil.which("ffmpeg")
    if p:
        return p
    if sys.platform != "win32":
        return None
    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        winget_root = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.exists():
            # Gyan.FFmpeg drops binaries into a versioned dir like
            # ``Gyan.FFmpeg_<source>\ffmpeg-<ver>-full_build\bin\``.
            candidates.extend(
                winget_root.glob(
                    "Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"))
            candidates.extend(
                winget_root.glob(
                    "Gyan.FFmpeg*/bin/ffmpeg.exe"))
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "ffmpeg" / "bin" / "ffmpeg.exe")
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _output_path() -> Path:
    BOT_IO_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return BOT_IO_DIR / f"BOTVIDEO-{stamp}.mp4"


def start_ffmpeg(rect: tuple[int, int, int, int],
                 out_path: Path) -> subprocess.Popen | None:
    """Spawn ffmpeg capturing the given screen rect to ``out_path``.

    Uses libx264 + ultrafast preset + yuv420p so output plays in
    every video player + browser.  ``-movflags +faststart`` puts
    the moov atom at the head of the file so the MP4 is
    streamable even if the recorder gets killed mid-write."""
    ffm = _ffmpeg_path()
    if ffm is None:
        print("[recorder] ffmpeg not on PATH -- cannot record video.  "
              "Install: https://www.gyan.dev/ffmpeg/builds/")
        return None
    x, y, w, h = rect
    # gdigrab requires even dimensions for libx264 yuv420p output.
    w -= w % 2
    h -= h % 2
    cmd = [
        ffm,
        "-y",                          # overwrite if file exists
        "-loglevel", "error",
        "-f", "gdigrab",
        "-framerate", str(FRAME_RATE),
        "-offset_x", str(x),
        "-offset_y", str(y),
        "-video_size", f"{w}x{h}",
        "-i", "desktop",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"[recorder] capturing {w}x{h} @ ({x},{y}) -> {out_path.name}")
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("[recorder] ffmpeg launch failed -- binary missing")
        return None
    except Exception as e:
        print(f"[recorder] ffmpeg launch failed: {e}")
        return None


def stop_ffmpeg(proc: subprocess.Popen | None,
                grace_s: float = 6.0) -> None:
    """Cleanly close out the MP4 by sending 'q' to ffmpeg.  Falls
    back to terminate then kill if ffmpeg doesn't exit on its own."""
    if proc is None or proc.poll() is not None:
        return
    print("[recorder] finalising MP4 ...")
    try:
        if proc.stdin is not None:
            try:
                proc.stdin.write(b"q")
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.stdin.close()
            except Exception:
                pass
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        print("[recorder] ffmpeg didn't finalise in time -- terminating")
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── Main loop ─────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Call of Orion -- video recorder")
    print(f"Output dir: {BOT_IO_DIR}")
    print("Hotkey: Ctrl+Shift+Q to stop + finalise the MP4")
    print("=" * 60)
    if _ffmpeg_path() is None:
        print("[recorder] ABORT: ffmpeg not on PATH.")
        sys.exit(2)
    threading.Thread(target=_hotkeys, daemon=True).start()

    deadline = time.time() + WINDOW_FIND_TIMEOUT_S
    target = None
    while time.time() < deadline and not State.stop:
        target = find_game_window()
        if target is not None:
            break
        time.sleep(0.5)
    if target is None:
        print(f"[recorder] no '{WINDOW_TITLE}' window in "
              f"{WINDOW_FIND_TIMEOUT_S:.0f}s -- aborting")
        return

    # Give the window a beat to settle on screen so we capture
    # the real client rect, not a transient mid-resize one.
    time.sleep(1.0)
    rect = get_client_rect(target)
    if rect is None:
        print("[recorder] could not read client rect -- aborting")
        return

    out_path = _output_path()
    proc = start_ffmpeg(rect, out_path)
    if proc is None:
        return

    last_seen = time.time()
    while not State.stop:
        if proc.poll() is not None:
            print(f"[recorder] ffmpeg exited (code {proc.returncode}) -- stopping")
            break
        if find_game_window() is None:
            if time.time() - last_seen > GAME_GONE_GRACE_S:
                print("[recorder] game window gone -- finalising MP4")
                break
        else:
            last_seen = time.time()
        time.sleep(1.0)
    stop_ffmpeg(proc)
    if out_path.exists():
        sz = out_path.stat().st_size
        print(f"[recorder] saved: {out_path.name} ({sz / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
