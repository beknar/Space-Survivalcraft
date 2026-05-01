"""Combined launcher: runs ``bot_kickoff`` then ``bot_autopilot`` in
one terminal so the user doesn't have to manage two windows.

Both ``bot_kickoff.py`` and ``bot_autopilot.py`` remain standalone
entry points -- this script just imports and calls their ``main()``
functions in sequence.  Run any of:

    python bot_run.py        # kickoff + autopilot in one shot
    python bot_kickoff.py    # kickoff only (e.g. headless data
                              # gathering)
    python bot_autopilot.py  # autopilot only (e.g. attaching to a
                              # game already running with COO_BOT_API=1)

Sequence:

    1. ``bot_kickoff.main()`` -- launches main.py with
       ``COO_BOT_API=1`` as a detached child, drives the splash +
       random selection + music video, then returns once the
       game is in the in-game state.
    2. ``bot_autopilot.main()`` -- connects to the in-process
       HTTP API, polls ``/state`` at 10 Hz, drives keystrokes
       through pyautogui.  Blocks until Ctrl+Shift+Q or Ctrl+C.
"""
from __future__ import annotations

import sys


# UTF-8 stdout for the same Unicode-tolerant logging both child
# scripts use.  Done before the imports below so any banner they
# print at import time renders cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot_autopilot
import bot_kickoff


def main() -> None:
    print("=" * 60)
    print("Call of Orion -- bot run (kickoff + autopilot)")
    print("=" * 60)
    bot_kickoff.main()
    # bot_kickoff.main() returns once the game is in-game.  The
    # game subprocess is detached and will keep running.  Hand
    # off to the autopilot, which blocks until Ctrl+Shift+Q.
    print()
    print("[bot_run] kickoff complete -- starting autopilot")
    print()
    bot_autopilot.main()


if __name__ == "__main__":
    main()
