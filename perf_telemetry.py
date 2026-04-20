"""TEMPORARY live-gameplay FPS-drop recorder.

Hooked from ``game_view.on_draw`` at the end of each frame.  Measures
wall-clock frame time with ``time.perf_counter``; when a frame takes
longer than ``DROP_FRAME_TIME`` (= 1/40 s = 25 ms), writes a context
snapshot to ``crash_logs/fps_drops.log``.

The snapshot captures *where* the drop occurred (zone, player world
position, counts of live sprites, which overlays are open, whether
videos are playing) so we can correlate dips with specific code
paths without re-running a profiler.

Delete this module + the two-line hook in ``game_view.on_draw``
(search for ``PERF_TELEMETRY``) to remove.
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_view import GameView

_FPS_THRESHOLD = 40.0
DROP_FRAME_TIME = 1.0 / _FPS_THRESHOLD  # 0.025 s
_LOG_PATH = os.path.join("crash_logs", "fps_drops.log")
# One log line per frame that dips; also emit a summary every
# ``_SUMMARY_INTERVAL`` seconds so the file stays useful on long runs.
_SUMMARY_INTERVAL = 10.0

_last_tick: float | None = None
_session_start: float | None = None
_last_summary: float = 0.0
_frame_no: int = 0
_drop_count: int = 0
_worst_ft: float = 0.0
_worst_frame: int = -1
_log_fh = None


def _open_log():
    global _log_fh, _session_start
    if _log_fh is not None:
        return _log_fh
    os.makedirs("crash_logs", exist_ok=True)
    # Append so successive runs accumulate; truncation is easier by
    # deleting the file manually between sessions.
    # 8 KB buffer (not line-buffered) so drop-cluster cascades don't
    # hit the disk sync for every line — prior line-buffered mode was
    # a positive feedback loop: slow frame → log write → slower → more
    # writes.  The 10-s summary heartbeat below flushes explicitly.
    _log_fh = open(_LOG_PATH, "a", buffering=8192, encoding="utf-8")
    _session_start = time.perf_counter()
    _log_fh.write(
        f"\n=== perf_telemetry session start "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"(threshold={_FPS_THRESHOLD:.0f} FPS / "
        f"{DROP_FRAME_TIME * 1000:.1f} ms) ===\n"
    )
    return _log_fh


def _overlay_flags(gv) -> str:
    """Short tag string of which HUD/overlay modes are active."""
    flags = []
    if getattr(gv, "_player_dead", False):
        flags.append("DEAD")
    em = getattr(gv, "_escape_menu", None)
    if em is not None and getattr(em, "open", False):
        flags.append("ESC")
    dlg = getattr(gv, "_dialogue", None)
    if dlg is not None and getattr(dlg, "open", False):
        flags.append("DLG")
    bm = getattr(gv, "_build_menu", None)
    if bm is not None and getattr(bm, "open", False):
        flags.append("BUILD")
    tm = getattr(gv, "_trade_menu", None)
    if tm is not None and getattr(tm, "open", False):
        flags.append("TRADE")
    cm = getattr(gv, "_craft_menu", None)
    if cm is not None and getattr(cm, "open", False):
        flags.append("CRAFT")
    si = getattr(gv, "_station_inv", None)
    if si is not None and getattr(si, "open", False):
        flags.append("STATION")
    if getattr(gv, "_placement_mode", False):
        flags.append("PLACE")
    if getattr(gv, "_destroy_mode", False):
        flags.append("DESTROY")
    return ",".join(flags) if flags else "-"


def _counts(gv) -> dict[str, int]:
    """Snapshot live-sprite counts — the things most likely to cost
    CPU/GPU time when they spike."""
    zone = getattr(gv, "_zone", None)
    out = {
        "proj_p": len(getattr(gv, "projectile_list", []) or []),
        "proj_a": len(getattr(gv, "alien_projectile_list", []) or []),
        "proj_t": len(getattr(gv, "turret_projectile_list", []) or []),
        "pickups": len(getattr(gv, "iron_pickup_list", []) or []),
        "parked": len(getattr(gv, "_parked_ships", []) or []),
        "buildings": len(getattr(gv, "building_list", []) or []),
        "contrails": len(getattr(gv, "contrail_list", []) or []),
        "explosions": len(getattr(gv, "explosion_list", []) or []),
        "walls": len(getattr(gv, "_force_walls", []) or []),
    }
    # Zone-specific lists hang off the zone object in Zone 2.
    if zone is not None:
        for attr in ("_iron_asteroids", "_double_iron", "_copper_asteroids",
                     "_aliens", "_alien_projectiles", "_wanderers",
                     "_gas_areas", "_wormholes", "_null_fields",
                     "_slipspaces"):
            lst = getattr(zone, attr, None)
            if lst is not None:
                out[attr.lstrip("_")] = len(lst)
    # Fall-back for Zone 1 (shared lists live on gv directly).
    out.setdefault("asteroids",
                   len(getattr(gv, "asteroid_list", []) or []))
    out.setdefault("aliens",
                   len(getattr(gv, "alien_list", []) or []))
    return out


def _videos_active(gv) -> str:
    tags = []
    vp = getattr(gv, "_video_player", None)
    if vp is not None and getattr(vp, "active", False):
        tags.append("MUSIC")
    cvp = getattr(gv, "_char_video_player", None)
    if cvp is not None and getattr(cvp, "active", False):
        tags.append("CHAR")
    return "+".join(tags) if tags else "-"


def _zone_tag(gv) -> str:
    z = getattr(gv, "_zone", None)
    if z is None:
        return "?"
    # Prefer the ZoneState's own short name if it exposes one.
    for attr in ("zone_id", "id", "name"):
        v = getattr(z, attr, None)
        if v is not None:
            return str(v).replace("ZoneID.", "")
    return type(z).__name__


def record_frame(gv) -> None:
    """Called once per frame from ``on_draw``.  Cheap in the common
    path (single perf_counter + subtract + compare)."""
    global _last_tick, _last_summary, _frame_no
    global _drop_count, _worst_ft, _worst_frame

    now = time.perf_counter()
    _frame_no += 1
    if _last_tick is None:
        _last_tick = now
        _last_summary = now
        return
    ft = now - _last_tick
    _last_tick = now

    if ft > DROP_FRAME_TIME:
        _drop_count += 1
        if ft > _worst_ft:
            _worst_ft = ft
            _worst_frame = _frame_no
        fh = _open_log()
        fps = 1.0 / ft if ft > 0 else 0.0
        elapsed = now - (_session_start or now)
        px = getattr(getattr(gv, "player", None), "center_x", 0.0)
        py = getattr(getattr(gv, "player", None), "center_y", 0.0)
        counts = _counts(gv)
        counts_s = " ".join(f"{k}={v}" for k, v in counts.items() if v)
        fh.write(
            f"[{elapsed:8.2f}s f{_frame_no:<6}] "
            f"ft={ft * 1000:6.1f}ms ({fps:5.1f} FPS) "
            f"zone={_zone_tag(gv)} "
            f"pos=({px:7.0f},{py:7.0f}) "
            f"overlays={_overlay_flags(gv)} "
            f"videos={_videos_active(gv)} "
            f"| {counts_s}\n"
        )

    # Periodic summary.
    if now - _last_summary >= _SUMMARY_INTERVAL:
        fh = _open_log()
        elapsed = now - (_session_start or now)
        fh.write(
            f"--- summary @ {elapsed:.1f}s: {_drop_count} drops / "
            f"{_frame_no} frames "
            f"(worst {_worst_ft * 1000:.1f} ms at f{_worst_frame}) ---\n"
        )
        # Explicit flush so a crash mid-run leaves up to 10 s of
        # buffered drop lines on disk, not up to 8 KB.
        try:
            fh.flush()
        except Exception:
            pass
        _last_summary = now
