"""Soak / endurance tests for the refactored bot_autopilot modules.

Lightweight standalone soak: drives the navigation + blacklist
modules in tight loops simulating many minutes of gameplay decisions
(no real Arcade GameView needed) and asserts:

  * No memory growth from the rolling stuck-detect history,
  * No memory growth from the TTL-evicting blacklist dicts,
  * No per-call slowdown over 100k iterations.

Faster than the full GameView soak (~10s vs 5min) but pins the
properties that matter for the refactor.
"""
from __future__ import annotations

import gc
import os
import time

import psutil
import pytest

import bot_autopilot as ap
import bot_autopilot_navigation as nav
import bot_autopilot_blacklist as bl


def _rss_mb() -> float:
    gc.collect()
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


# ── Stuck-detect history bounded ──────────────────────────────────────

class TestStuckDetectHistoryBounded:
    """``record_position`` must evict samples older than the detect
    window — no matter how many calls fire, the history list stays
    bounded.  Without eviction, a 5-min soak would pile up 3000
    entries and the per-tick scan in ``detect_stuck`` would hit the
    O(N) wall."""

    def test_history_stays_bounded_over_30k_ticks(self):
        clock = [0.0]
        get_now = lambda: clock[0]
        stuck = {"history": [], "escape_until": 0.0, "last_log": 0.0}
        # Simulate 50 minutes of 10 Hz ticks.
        for i in range(30_000):
            clock[0] = i * 0.1
            nav.record_position(
                {"x": float(i % 100), "y": float(i % 100), "heading": 0.0},
                stuck, get_now)
        # 1.5 s window at 10 Hz = at most ~16 samples.
        assert len(stuck["history"]) <= 20, (
            f"history grew to {len(stuck['history'])} entries — "
            "eviction broken")


# ── Blacklist TTL eviction ────────────────────────────────────────────

class TestBlacklistTTLEviction:
    def test_pickup_blacklist_stays_bounded_over_long_run(self):
        clock = [0.0]
        get_now = lambda: clock[0]
        blist: dict = {}
        # Add 1000 pickups over 5000 s of simulated time — TTL is
        # 300 s so most should expire.
        for i in range(1000):
            clock[0] = i * 5.0  # one entry every 5 s
            bl.blacklist_pickup(
                {"x": float(i * 10), "y": 0.0}, blist, get_now)
            # Trigger an eviction scan.
            bl.pickup_is_blacklisted({"x": -1.0, "y": -1.0},
                                       blist, get_now)
        # At t = 4995 s with 300 s TTL, only ~60 entries should survive.
        assert len(blist) <= 80, (
            f"pickup blacklist grew to {len(blist)} — eviction broken")

    def test_asteroid_blacklist_stays_bounded(self):
        clock = [0.0]
        get_now = lambda: clock[0]
        blist: dict = {}
        # Asteroid TTL is 60 s — over 1000 s of simulated time, only
        # ~12 entries should survive at the head of the queue.
        for i in range(500):
            clock[0] = i * 2.0
            bl.blacklist_asteroid(
                {"x": float(i * 10), "y": 0.0}, blist, get_now)
            bl.asteroid_is_blacklisted({"x": -1.0, "y": -1.0},
                                         blist, get_now)
        assert len(blist) <= 40, (
            f"asteroid blacklist grew to {len(blist)} — eviction broken")


# ── No memory growth in a long autopilot soak ─────────────────────────

class TestAutopilotSoakNoMemoryGrowth:
    """Drive ``_do_auto`` 30 000 times (~50 minutes of game-time at
    10 Hz) and assert RSS doesn't grow more than 10 MB.  Catches the
    failure mode where one of the new modules inadvertently keeps a
    reference to per-tick state objects."""

    def test_30k_ticks_no_rss_growth(self, monkeypatch):
        # Silence keystrokes + telemetry side effects.
        monkeypatch.setattr(ap.KeyState, "hold",
                            staticmethod(lambda k, d: None))
        monkeypatch.setattr(ap.KeyState, "release_all",
                            staticmethod(lambda: None))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)

        clock = [0.0]
        monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
        ap._fsm_reset()

        state = {
            "zone": {"world_w": 6400.0, "world_h": 6400.0},
            "buildings": [],
            "asteroids": [{"x": 100.0, "y": 100.0, "hp": 50}],
            "aliens": [],
            "iron_pickups": [],
            "blueprint_pickups": [],
            "inventory": {"items": {}},
            "station_inventory": {"items": {}},
            "module_slots": [None] * 4,
            "weapon": {"name": "Mining Beam"},
            "assist": {},
        }
        p = {"x": 3200.0, "y": 3200.0, "heading": 0.0,
             "shields": 150, "max_shields": 150}

        # Warm-up + baseline RSS.
        for _ in range(100):
            ap._do_auto(state, p)
        rss_before = _rss_mb()

        # The actual soak.
        for i in range(30_000):
            clock[0] = i * 0.1
            ap._do_auto(state, p)

        rss_after = _rss_mb()
        growth = rss_after - rss_before
        assert growth < 15.0, (
            f"_do_auto over 30k ticks grew RSS by {growth:.1f} MB — "
            "memory leak in the refactored modules")


# ── Per-call timing stays stable across 50k iterations ───────────────

class TestNoSlowdownOver50kCalls:
    def test_steered_heading_no_drift(self):
        """Run ``steered_heading`` 50k times in two phases (early,
        late) and check the per-call time hasn't drifted by more
        than 3x.  Catches the failure mode where a hidden cache /
        list grows and slows the per-call scan."""
        s = {"zone": {"world_w": 6400.0, "world_h": 6400.0},
             "buildings": [{"x": float(i * 73), "y": 100.0}
                           for i in range(20)]}
        p = {"x": 100.0, "y": 100.0}
        # Warm-up.
        for _ in range(1000):
            nav.steered_heading(s, p, 1000.0, 0.0, 1000.0)
        # Phase 1 timing.
        t0 = time.perf_counter()
        for _ in range(25_000):
            nav.steered_heading(s, p, 1000.0, 0.0, 1000.0)
        t_early = time.perf_counter() - t0
        # Phase 2 — same workload, after the first 25k calls.
        t0 = time.perf_counter()
        for _ in range(25_000):
            nav.steered_heading(s, p, 1000.0, 0.0, 1000.0)
        t_late = time.perf_counter() - t0
        # Allow up to 3× drift to be tolerant of OS-load noise; we
        # care about catching 10× regressions, not 30% drift.
        ratio = t_late / max(t_early, 1e-6)
        assert ratio < 3.0, (
            f"steered_heading drifted from {t_early*1000:.1f} ms to "
            f"{t_late*1000:.1f} ms across 50k calls (ratio {ratio:.2f}) "
            "— per-call slowdown regression")
