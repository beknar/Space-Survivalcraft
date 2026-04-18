"""Crash telemetry — faulthandler + flight recorder + excepthooks.

Four defences against silent crashes, all funnelled into
``crash_logs/`` at the project root:

1. ``faulthandler``  — Python stdlib. Writes a C-level traceback to
   ``crash_logs/faulthandler.log`` on SIGSEGV/SIGFPE/SIGABRT (the
   most common cause of "process just vanished" on a Python game
   that leans on pyglet + OpenGL + ffmpeg).  Also dumps every thread
   every 30 s so a frozen game tells us where it hung.

2. ``FlightRecorder``  — a 1-Hz rolling state log (frame counter,
   zone, player pos, key list sizes, RSS MB).  Flushed and fsynced
   once a second so the last entry survives a hard crash.  Rotates
   at 5 MB to bound disk use.

3. ``sys.excepthook`` + ``threading.excepthook``  — belt-and-braces
   for the minority of crashes that ARE Python exceptions being
   swallowed somewhere (background thread, atexit handler).  Both
   tracebacks land in ``crash_logs/exceptions.log``.

4. ``attach_procdump.bat``  — standalone helper that attaches
   Microsoft's ProcDump to the running python.exe so a native
   minidump gets written if faulthandler itself dies.  Run it only
   if #1 doesn't catch the next crash.

The ``init_crash_telemetry()`` entry point must run BEFORE arcade /
pyglet import anything C-backed; ``main.py`` calls it first thing.
``record_frame(gv)`` is called from ``GameView.on_update`` every
frame and is a no-op if telemetry wasn't initialised.

Every function in this module is written to NEVER raise — a bug in
the telemetry must not take the game down.
"""
from __future__ import annotations

import atexit
import faulthandler
import json
import os
import sys
import threading
import time
import traceback
from typing import Optional

import psutil

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "crash_logs")

_recorder: "FlightRecorder | None" = None
_faulthandler_file = None  # kept alive for process lifetime
_exception_log_path: str | None = None
_clean_shutdown: bool = False


# ── Flight recorder ───────────────────────────────────────────────────────

class FlightRecorder:
    """1-Hz rolling log of recent game state.

    Buffers entries in memory between flushes so the hot path only
    pays a dict-build + append per frame; flushes (with fsync) once a
    second so at most ~60 frames of state are lost if the process
    dies between flushes.  The file rotates to ``<path>.1`` at
    ``max_bytes`` so long sessions can't fill the disk.
    """

    def __init__(self, path: str,
                 flush_every_s: float = 1.0,
                 max_bytes: int = 5_000_000) -> None:
        self._path = path
        self._flush_every_s = flush_every_s
        self._max_bytes = max_bytes
        self._buf: list[str] = []
        self._last_flush = time.monotonic()
        self._frame = 0
        self._proc = psutil.Process(os.getpid())
        self._start = time.perf_counter()
        # Cached RSS in MB — refreshed on each periodic flush rather
        # than every frame.  The psutil syscall costs ~3 µs/call and
        # RSS changes on a seconds timescale, so sampling at 60 Hz is
        # pure waste.
        self._cached_rss_mb: int = self._proc.memory_info().rss // (1024 * 1024)
        # Line-buffered so a crash mid-write at least keeps complete
        # lines intact on disk.
        self._file = open(path, "a", encoding="utf-8", buffering=1)

    def record(self, gv) -> None:
        """Append one frame of state.  Swallows every exception so a
        telemetry bug never crashes the game."""
        try:
            self._frame += 1
            zone = getattr(gv, "_zone", None)
            zone_name = getattr(getattr(zone, "zone_id", None),
                                "name", None)
            player = getattr(gv, "player", None)
            px = getattr(player, "center_x", 0.0)
            py = getattr(player, "center_y", 0.0)
            hp = getattr(player, "hp", 0)
            shields = getattr(player, "shields", 0)
            rss_mb = self._cached_rss_mb
            entry = {
                "t": round(time.perf_counter() - self._start, 3),
                "f": self._frame,
                "z": zone_name,
                "px": round(px, 1),
                "py": round(py, 1),
                "hp": hp,
                "sh": shields,
                "rss": rss_mb,
                "proj": len(getattr(gv, "projectile_list", []) or []),
                "alien": len(getattr(gv, "alien_list", []) or []),
                "apj": len(getattr(gv, "alien_projectile_list", []) or []),
                "expl": len(getattr(gv, "explosion_list", []) or []),
                "bld": len(getattr(gv, "building_list", []) or []),
            }
            self._buf.append(json.dumps(entry, separators=(",", ":")))
            now = time.monotonic()
            if now - self._last_flush >= self._flush_every_s:
                # Refresh the cached RSS at flush time too so the next
                # second's entries reflect recent memory growth.
                try:
                    self._cached_rss_mb = (
                        self._proc.memory_info().rss // (1024 * 1024))
                except Exception:
                    pass
                self._flush()
                self._last_flush = now
        except Exception:  # noqa: BLE001 — telemetry must not crash the game
            pass

    def note(self, tag: str, **payload) -> None:
        """Log a one-off tagged event (e.g. zone transition, video
        start).  Flushed with the next periodic flush."""
        try:
            entry = {"t": round(time.perf_counter() - self._start, 3),
                     "tag": tag, **payload}
            self._buf.append(json.dumps(entry, separators=(",", ":")))
        except Exception:
            pass

    def _flush(self) -> None:
        if not self._buf:
            return
        try:
            self._file.write("\n".join(self._buf))
            self._file.write("\n")
            # Plain flush() only — the OS kernel buffer outlives the
            # Python process even on a hard crash (Windows 0xc0000374
            # included), so os.fsync() is a ~7 ms/s tax that only
            # defends against power loss, which isn't our threat
            # model.  close() on shutdown still fsyncs implicitly.
            self._file.flush()
            self._buf.clear()
            if self._file.tell() >= self._max_bytes:
                self._rotate()
        except Exception:
            # Drop the buffer rather than keep growing it forever.
            self._buf.clear()

    def _rotate(self) -> None:
        try:
            self._file.close()
            old = self._path + ".1"
            if os.path.exists(old):
                os.remove(old)
            os.rename(self._path, old)
            self._file = open(self._path, "a", encoding="utf-8",
                              buffering=1)
        except Exception:
            pass

    def close(self, clean: bool = False) -> None:
        try:
            self.note("SHUTDOWN", clean=clean)
            self._flush()
            self._file.close()
        except Exception:
            pass


# ── Public API ────────────────────────────────────────────────────────────

def init_crash_telemetry() -> None:
    """Wire up faulthandler + excepthooks + flight recorder.

    Safe to call more than once; subsequent calls are no-ops.
    """
    global _recorder, _faulthandler_file, _exception_log_path
    if _recorder is not None:
        return

    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
    except Exception:
        # If we can't create the log dir we can't do anything useful;
        # don't crash the game over it.
        return

    _install_faulthandler()
    _install_excepthooks()
    _recorder = _make_recorder()
    atexit.register(_on_exit)


def record_frame(gv) -> None:
    """Per-frame hook.  No-op if telemetry wasn't initialised."""
    r = _recorder
    if r is not None:
        r.record(gv)


def note(tag: str, **payload) -> None:
    """Log a one-off tagged event."""
    r = _recorder
    if r is not None:
        r.note(tag, **payload)


def mark_clean_shutdown() -> None:
    """Call from the game's clean-quit path so the atexit marker
    knows the next ``SHUTDOWN`` entry is intentional rather than a
    crash."""
    global _clean_shutdown
    _clean_shutdown = True


# ── Internals ─────────────────────────────────────────────────────────────

def _install_faulthandler() -> None:
    global _faulthandler_file
    try:
        path = os.path.join(_LOG_DIR, "faulthandler.log")
        # Append so prior crashes stay on disk for comparison.
        _faulthandler_file = open(path, "a", encoding="utf-8",
                                   buffering=1)
        _faulthandler_file.write(
            f"\n=== faulthandler session {time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"pid={os.getpid()} ===\n")
        _faulthandler_file.flush()
        faulthandler.enable(file=_faulthandler_file,
                            all_threads=True)
        # NOTE: we used to also call faulthandler.dump_traceback_later(
        # 30, repeat=True) as a "if the game freezes, log where it
        # hung" hang detector.  That was REMOVED on 2026-04-18 after
        # two crashes (FFmpeg heap corruption + OpenGL VAO access
        # violation) both fired during the timer's stack-dump tick.
        # The dumper walks every Python thread's stack from a separate
        # native thread; on Windows, doing that while a thread is mid-
        # call into a C extension that holds an internal lock (pyglet
        # OpenGL bindings, FFmpeg, audio backends) reads freed/garbage
        # state and produces exactly the access-violation pattern we
        # observed.  faulthandler.enable() above is enough to catch
        # real native crashes — only the periodic hang dump is unsafe.
    except Exception:
        pass


def _install_excepthooks() -> None:
    global _exception_log_path
    try:
        _exception_log_path = os.path.join(_LOG_DIR, "exceptions.log")
    except Exception:
        return

    prev_sys_hook = sys.excepthook

    def _sys_hook(exc_type, exc, tb) -> None:
        _log_exception("sys.excepthook", exc_type, exc, tb)
        try:
            prev_sys_hook(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _sys_hook

    # threading.excepthook (Python 3.8+)
    if hasattr(threading, "excepthook"):
        prev_thread_hook = threading.excepthook

        def _thread_hook(args) -> None:
            _log_exception(f"thread:{args.thread.name}",
                           args.exc_type, args.exc_value,
                           args.exc_traceback)
            try:
                prev_thread_hook(args)
            except Exception:
                pass

        threading.excepthook = _thread_hook


def _log_exception(source: str, exc_type, exc, tb) -> None:
    if _exception_log_path is None:
        return
    try:
        with open(_exception_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"[{source}] pid={os.getpid()} ===\n")
            traceback.print_exception(exc_type, exc, tb, file=f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception:
        pass


def _make_recorder() -> Optional[FlightRecorder]:
    try:
        path = os.path.join(_LOG_DIR, "flight.jsonl")
        r = FlightRecorder(path)
        r.note("BOOT", pid=os.getpid(),
               time=time.strftime('%Y-%m-%d %H:%M:%S'))
        return r
    except Exception:
        return None


def _on_exit() -> None:
    r = _recorder
    if r is not None:
        r.close(clean=_clean_shutdown)
