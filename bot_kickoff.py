"""One-shot launcher: start the game with COO_BOT_API=1, drive
splash + random selection + music video, then exit -- leaving
the game process running detached so the autopilot can take over.

Companion script for the API+autopilot architecture.

Run:
    python bot_kickoff.py
    # then in another terminal:
    python bot_autopilot.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

# UTF-8 stdout for unicode-tolerant logging.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot_play
from bot_play import (
    set_dpi_awareness,
    patch_settings_for_video,
    find_and_position_window,
    click_play_now,
    random_selection,
    load_random_music_video,
    _wait,
    PROJECT_ROOT,
)


def main() -> None:
    print("=" * 60)
    print("Call of Orion -- bot kickoff")
    print("=" * 60)
    set_dpi_awareness()
    patch_settings_for_video()

    # Launch the game with COO_BOT_API=1 so the HTTP API is up
    # by the time we reach the in-game state.  DETACHED_PROCESS
    # on Windows so the game keeps running after this script exits.
    env = dict(os.environ)
    env["COO_BOT_API"] = "1"
    creationflags = 0
    stdio: dict = {}
    if sys.platform == "win32":
        # DETACHED_PROCESS (0x8) | CREATE_NEW_PROCESS_GROUP (0x200)
        # so the game survives the parent's exit AND has its stdio
        # detached.  Without DETACHED_PROCESS, a child print() to
        # a closed parent stdout will SIGPIPE the game.
        creationflags = 0x00000008 | 0x00000200
        # Redirect stdio to a log file so we can debug crashes after
        # the parent exits.
        log_path = PROJECT_ROOT / "bot_io" / "game_stdout.log"
        log_path.parent.mkdir(exist_ok=True)
        log_fh = open(log_path, "w", encoding="utf-8")
        stdio = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_fh,
            "stderr": subprocess.STDOUT,
        }
        print(f"[kickoff] game stdout -> {log_path}")
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(PROJECT_ROOT),
        env=env,
        creationflags=creationflags,
        **stdio,
    )
    print(f"[kickoff] launched game pid={proc.pid}")

    if not find_and_position_window():
        print("[kickoff] window not found; aborting")
        return
    if not _wait(1.5):
        return
    click_play_now()
    if not _wait(2.0):
        return
    # Earth (0) + Aegis (2); character left random.
    random_selection(faction_idx=0, ship_idx=2)
    if not _wait(3.0):
        return
    load_random_music_video()
    if not _wait(1.0):
        return
    print("[kickoff] in-game; game pid still running, exiting")
    print("[kickoff] next: python bot_autopilot.py")


if __name__ == "__main__":
    main()
