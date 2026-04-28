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
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP so the game survives the parent's exit.
        creationflags = 0x00000200    # CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(PROJECT_ROOT),
        env=env,
        creationflags=creationflags,
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
    random_selection()
    if not _wait(3.0):
        return
    load_random_music_video()
    if not _wait(1.0):
        return
    print("[kickoff] in-game; game pid still running, exiting")
    print("[kickoff] next: python bot_autopilot.py")


if __name__ == "__main__":
    main()
