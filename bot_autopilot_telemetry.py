"""JSONL telemetry stream for bot_autopilot.

Owns the disk writer + per-line snapshot dict.  Split out of
``bot_autopilot.py`` so the autopilot module stays a focused FSM
dispatcher and the I/O surface is isolated for testing /
monkey-patching.

The writer is best-effort: a failed write prints a warning and
moves on.  Production writes go to ``bot_io/autopilot_telemetry.jsonl``;
tests monkey-patch ``telemetry_init`` and ``telemetry_log`` to no-ops
(see ``unit tests/conftest.py::_silence_bot_telemetry``).

Volume: ~50-150 lines per minute of normal play (one per state
transition + one snapshot every 5 s).  Safe to leave on.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any, Callable

_TELEMETRY_PATH = os.path.join("bot_io", "autopilot_telemetry.jsonl")
_telemetry_lock = threading.Lock()
_telemetry_started = False
_telemetry_last_snapshot_at: float = 0.0
TELEMETRY_SNAPSHOT_INTERVAL_S: float = 5.0


def _now_monotonic() -> float:
    """Late-bound clock — bot_autopilot may monkey-patch
    ``bot_autopilot._get_now`` in tests; we honour the override
    by reading it through a lazy import."""
    try:
        import bot_autopilot
        return bot_autopilot._get_now()
    except Exception:
        return time.monotonic()


def telemetry_init() -> None:
    """Create bot_io/ + write a session_start marker exactly once
    per autopilot process.  Safe to call repeatedly."""
    global _telemetry_started
    if _telemetry_started:
        return
    _telemetry_started = True
    try:
        os.makedirs("bot_io", exist_ok=True)
        with _telemetry_lock, open(_TELEMETRY_PATH, "a",
                                    encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "monotonic": _now_monotonic(),
                "event": "session_start",
                "pid": os.getpid(),
            }) + "\n")
    except Exception as e:
        print(f"[autopilot] telemetry init error: {e}")


def telemetry_log(event: str, **fields: Any) -> None:
    """Append one JSONL line to the telemetry stream.  Never raises
    into the caller — a failed write prints a warning and moves on."""
    try:
        line = json.dumps({
            "ts": time.time(),
            "monotonic": _now_monotonic(),
            "event": event,
            **fields,
        })
        with _telemetry_lock, open(_TELEMETRY_PATH, "a",
                                    encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[autopilot] telemetry write error: {e}")


def make_snapshot_fields(
    state: dict,
    p: dict,
    bot_state: Any,
    deposit_cooldown_s: float,
    find_home_station: Callable[[dict], dict | None],
    get_now: Callable[[], float],
) -> dict:
    """Compact dump of the conditions that drive the FSM.  Used by
    state_transition + periodic snapshot events so each line is
    self-contained for offline analysis."""
    items = (state.get("inventory") or {}).get("items") or {}
    sitems = (state.get("station_inventory") or {}).get("items") or {}
    hs = find_home_station(state)
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hs_dist = None
    if hs is not None:
        hs_dist = math.hypot(
            float(hs.get("x", 0.0)) - px,
            float(hs.get("y", 0.0)) - py)
    now = get_now()
    deposit_cooldown_remaining = max(
        0.0, deposit_cooldown_s - (now - bot_state.last_deposit_at))
    return {
        "px": round(px, 1),
        "py": round(py, 1),
        "ship_iron": int(items.get("iron", 0)),
        "ship_blueprints": sum(
            v for k, v in items.items() if k.startswith("bp_")),
        "ship_modules": sum(
            v for k, v in items.items() if k.startswith("mod_")),
        "station_iron": int(sitems.get("iron", 0)),
        "buildings_count": len(state.get("buildings") or []),
        "has_home_station": hs is not None,
        "hs_dist": None if hs_dist is None else round(hs_dist, 1),
        "asteroids_count": len(state.get("asteroids") or []),
        "aliens_count": len(state.get("aliens") or []),
        "iron_pickups_count": len(state.get("iron_pickups") or []),
        "blueprint_pickups_count": len(state.get("blueprint_pickups") or []),
        "shields": int(p.get("shields", 0)),
        "max_shields": int(p.get("max_shields", 1)),
        "build_done": bot_state.build_done,
        "last_deposit_at": bot_state.last_deposit_at,
        "deposit_cooldown_remaining_s": round(deposit_cooldown_remaining, 2),
        "modules_to_craft_left": len(bot_state.queue.modules_to_craft),
        "modules_to_install_left": len(bot_state.queue.modules_to_install),
        "module_phase_started": bot_state.queue.module_phase_started,
        "consumable_phase_started": bot_state.queue.consumable_phase_started,
    }


def reset_for_test() -> None:
    """Test-only: clear the one-shot ``session_start`` latch + the
    snapshot throttle so a fresh test sees the writer behave like
    a brand-new process.  Production code never calls this."""
    global _telemetry_started, _telemetry_last_snapshot_at
    _telemetry_started = False
    _telemetry_last_snapshot_at = 0.0
