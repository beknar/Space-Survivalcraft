"""One-shot telemetry recorder for diagnosing the "drone won't
return" bug.

Activated whenever the player issues a RETURN order from the Fleet
Control menu.  Each frame the drone's RETURN_HOME loop pushes a
snapshot row to ``drone_return_telemetry.log`` in the working
directory.  Recording stops automatically when:

  * the direct order clears (drone is back inside the close-range
    threshold and the mode machine drops the "return" flag), OR
  * the drone is replaced / recalled, OR
  * the player issues a different order.

Each row is one JSON object — the file is JSON-Lines, so it can be
inspected by hand or fed to ``jq`` / ``pandas.read_json(lines=True)``.

Fields per snapshot:

  * ``t``     wall-clock seconds since recording started
  * ``frame`` 0-based frame index
  * ``mode``  drone mode label (FOLLOW / ATTACK / RETURN_HOME)
  * ``dir``   active direct order ("return" / "attack" / None)
  * ``rxn``   reaction ("attack" / "follow")
  * ``pos``   drone (x, y)
  * ``ply``   player (x, y)
  * ``dist``  drone-to-player distance
  * ``moved`` distance moved since previous frame
  * ``wp``    waypoint emitted by the planner this frame (or None)
  * ``cd``    planner cooldown timer
  * ``stuck`` planner no-progress timer
  * ``path``  planner path (truncated to first 4 entries) or empty
  * ``nudge`` whether the un-stick nudge fired this frame

The file is appended-to across recordings; a header row marks the
boundary between sessions so you can ``grep`` for the start of the
last attempt.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any


_LOG_FILENAME = "drone_return_telemetry.log"
_state: dict[str, Any] = {
    "active": False,
    "frame": 0,
    "t0": 0.0,
    "prev_pos": (0.0, 0.0),
}


def _path() -> str:
    return os.path.join(os.getcwd(), _LOG_FILENAME)


def is_recording() -> bool:
    return _state["active"]


def start(reason: str = "") -> None:
    """Begin a new recording session.  Writes a one-line header so
    later inspection can tell sessions apart.  Idempotent — a second
    ``start`` while already recording bumps the header but doesn't
    reset the file (preserves prior data)."""
    _state["active"] = True
    _state["frame"] = 0
    _state["t0"] = time.perf_counter()
    _state["prev_pos"] = (0.0, 0.0)
    try:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "header": True,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason,
            }) + "\n")
    except OSError:
        # Disk full / permission denied — silently disable so the
        # game doesn't crash mid-mission for a debug log write.
        _state["active"] = False


def stop(reason: str = "") -> None:
    """Stop recording.  Appends a footer row so the log shows why
    the session ended."""
    if not _state["active"]:
        return
    _state["active"] = False
    try:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "footer": True,
                "frames": _state["frame"],
                "duration": time.perf_counter() - _state["t0"],
                "reason": reason,
            }) + "\n")
    except OSError:
        pass


def record_frame(
    drone,
    player,
    waypoint,
    nudge_fired: bool,
) -> None:
    """Append one snapshot row.  No-op when not recording.  Caller
    passes the planner result + nudge flag from the most recent
    update tick."""
    if not _state["active"]:
        return
    frame = _state["frame"]
    _state["frame"] = frame + 1
    px, py = _state["prev_pos"] if frame > 0 else (drone.center_x,
                                                     drone.center_y)
    moved = ((drone.center_x - px) ** 2
             + (drone.center_y - py) ** 2) ** 0.5
    _state["prev_pos"] = (drone.center_x, drone.center_y)
    planner = getattr(drone, "_follow_planner", None)
    path = []
    if planner is not None:
        path = list(getattr(planner, "_path", []))[:4]
    import math as _m
    row = {
        "frame": frame,
        "t": round(time.perf_counter() - _state["t0"], 3),
        "mode": _mode_label(drone),
        "dir": getattr(drone, "_direct_order", None),
        "rxn": getattr(drone, "_reaction", None),
        "pos": [round(drone.center_x, 1), round(drone.center_y, 1)],
        "ply": [round(player.center_x, 1), round(player.center_y, 1)],
        "dist": round(_m.hypot(player.center_x - drone.center_x,
                               player.center_y - drone.center_y), 1),
        "moved": round(moved, 2),
        "wp": (None if waypoint is None
                else [round(waypoint[0], 1), round(waypoint[1], 1)]),
        "cd": (round(getattr(planner, "_cooldown_t", 0.0), 2)
                if planner is not None else None),
        "stuck": (round(getattr(planner, "_stuck_t", 0.0), 2)
                  if planner is not None else None),
        "path": path,
        "nudge": bool(nudge_fired),
    }
    try:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        _state["active"] = False


def _mode_label(drone) -> str:
    from sprites.drone import _BaseDrone
    m = getattr(drone, "_mode", None)
    return {
        _BaseDrone._MODE_FOLLOW: "FOLLOW",
        _BaseDrone._MODE_ATTACK: "ATTACK",
        _BaseDrone._MODE_RETURN_HOME: "RETURN_HOME",
    }.get(m, str(m))
