"""Per-frame telemetry recorder for diagnosing drone behaviour bugs.

Active for the lifetime of any deployed drone — starts on
``deploy_drone``, stops on ``recall_drone`` or drone destruction.
Each frame ``_BaseDrone.update_drone`` (combat or mining) calls
``record_frame(drone, gv)`` and one snapshot row is appended to
``drone_telemetry.log`` in the working directory.

This is the second-generation recorder (the first lived only for
RETURN orders and was removed in commit ``37e6e41`` once the
return-order bugs were fixed).  Resurrected to diagnose the
"drone wanders in the Nebula instead of following" report — the
trigger now covers FOLLOW + ATTACK + RETURN_HOME so the recorder
captures whatever state the drone is actually in when it
misbehaves.

Each row is a JSON object — the file is JSON-Lines, so it can be
inspected by hand or fed to ``jq`` / ``pandas.read_json(lines=True)``.

Fields per snapshot:

  * ``t``     wall-clock seconds since recording started
  * ``frame`` 0-based frame index
  * ``zone``  active zone id name (e.g. "ZONE2", "STAR_MAZE")
  * ``mode``  drone mode label (FOLLOW / ATTACK / RETURN_HOME)
  * ``dir``   active direct order ("return" / "attack" / None)
  * ``rxn``   reaction ("attack" / "follow")
  * ``slot``  current follow slot (LEFT / RIGHT / BACK)
  * ``pos``   drone (x, y)
  * ``ply``   player (x, y)
  * ``dist``  drone-to-player distance
  * ``moved`` distance moved since previous frame
  * ``wp``    last steering target the drone aimed at this frame
  * ``cd``    planner cooldown timer
  * ``stuck`` planner no-progress timer
  * ``path``  planner path (truncated to first 4 entries) or empty
  * ``nudge_t`` un-stick nudge timer
  * ``walls`` count of walls within 200 px of the drone
  * ``ast``   count of asteroids within 200 px of the drone
  * ``tcd``   ``_target_cooldown`` (drone in stuck-with-target freeze)

The file is appended-to across recordings; a header row marks the
boundary between sessions so you can ``grep`` for the start of the
last attempt.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any


_LOG_FILENAME = "drone_telemetry.log"
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


def record_frame(drone, gv) -> None:
    """Append one snapshot row for the active drone.  No-op when not
    recording.  Called from both ``MiningDrone.update_drone`` and
    ``CombatDrone.update_drone`` after the per-frame movement runs
    so ``moved`` reflects this frame's progress."""
    if not _state["active"] or drone is None:
        return
    frame = _state["frame"]
    _state["frame"] = frame + 1
    px, py = (_state["prev_pos"]
              if frame > 0 else (drone.center_x, drone.center_y))
    moved = ((drone.center_x - px) ** 2
             + (drone.center_y - py) ** 2) ** 0.5
    _state["prev_pos"] = (drone.center_x, drone.center_y)
    planner = getattr(drone, "_follow_planner", None)
    path = []
    if planner is not None:
        path = list(getattr(planner, "_path", []))[:4]
    import math as _m
    player = getattr(gv, "player", None)
    if player is not None:
        ply = (round(player.center_x, 1), round(player.center_y, 1))
        dist = round(_m.hypot(player.center_x - drone.center_x,
                              player.center_y - drone.center_y), 1)
    else:
        ply = (0.0, 0.0)
        dist = 0.0
    last_wp = getattr(drone, "_last_steer_target", None)
    walls = 0
    asts = 0
    zone = getattr(gv, "_zone", None)
    zone_name = getattr(getattr(zone, "zone_id", None), "name", "?")
    # Cheap O(N) counts of nearby walls + asteroids for context.
    for w in (getattr(zone, "_walls", None) or [])[:500]:
        if (_m.hypot(drone.center_x - (w[0] + w[2] * 0.5),
                     drone.center_y - (w[1] + w[3] * 0.5))
                < 200.0):
            walls += 1
    from sprites.drone import _iter_asteroids
    for a in _iter_asteroids(gv)[:500]:
        if (_m.hypot(drone.center_x - a.center_x,
                     drone.center_y - a.center_y) < 200.0):
            asts += 1
    row = {
        "frame": frame,
        "t": round(time.perf_counter() - _state["t0"], 3),
        "zone": zone_name,
        "mode": _mode_label(drone),
        "dir": getattr(drone, "_direct_order", None),
        "rxn": getattr(drone, "_reaction", None),
        "slot": _slot_label(drone),
        "pos": [round(drone.center_x, 1), round(drone.center_y, 1)],
        "ply": [ply[0], ply[1]],
        "dist": dist,
        "moved": round(moved, 2),
        "wp": (None if last_wp is None
                else [round(last_wp[0], 1), round(last_wp[1], 1)]),
        "cd": (round(getattr(planner, "_cooldown_t", 0.0), 2)
                if planner is not None else None),
        "stuck": (round(getattr(planner, "_stuck_t", 0.0), 2)
                  if planner is not None else None),
        "path": path,
        "nudge_t": round(getattr(drone, "_nudge_timer", 0.0), 2),
        "walls": walls,
        "ast": asts,
        "tcd": round(getattr(drone, "_target_cooldown", 0.0), 2),
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


def _slot_label(drone) -> str:
    from sprites.drone import _BaseDrone
    s = getattr(drone, "_slot", None)
    return {
        _BaseDrone._SLOT_LEFT: "LEFT",
        _BaseDrone._SLOT_RIGHT: "RIGHT",
        _BaseDrone._SLOT_BACK: "BACK",
    }.get(s, str(s))
