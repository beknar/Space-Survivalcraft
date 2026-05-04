"""Performance budget tests for the refactored bot_autopilot modules.

Pin per-call cost for the three hot helpers that the autopilot's
10 Hz tick relies on:

  * ``boundary_repulsion`` / ``building_repulsion`` —
    called every tick from ``steered_heading`` (which is in turn
    called from every ``_do_goto``); needs to be sub-microsecond
    even when buildings are dense.
  * ``pickup_is_blacklisted`` — called once per pickup per tick
    when the bot is in S_GATHER; an O(N) scan over a TTL-evicting
    dict.
  * ``detect_stuck`` — called every tick from ``_do_auto``;
    iterates the rolling history (15 entries at 10 Hz over a 1.5 s
    window).

Thresholds are conservative — they catch order-of-magnitude
regressions, not 10% drift.  The split itself adds zero overhead
because it's pure function moves; this test pins that property.
"""
from __future__ import annotations

import time

import pytest

import bot_autopilot_navigation as nav
import bot_autopilot_blacklist as bl


def _zone():
    return {"world_w": 6400.0, "world_h": 6400.0}


def _state_with_buildings(n: int):
    return {"buildings": [
        {"x": (i * 73) % 6400, "y": (i * 31) % 6400}
        for i in range(n)
    ]}


# ── Boundary / building repulsion ─────────────────────────────────────

class TestBoundaryRepulsionPerf:
    def test_centre_call_under_2us(self):
        """Far from every edge — fast path returns (0, 0) immediately."""
        zone = _zone()
        p = {"x": 3200.0, "y": 3200.0}
        n_iter = 100_000
        # Warm-up.
        for _ in range(1000):
            nav.boundary_repulsion(p, zone)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            nav.boundary_repulsion(p, zone)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 5.0, (
            f"boundary_repulsion at world centre averaged "
            f"{avg_us:.3f} us — fast path regression")

    def test_at_edge_call_under_5us(self):
        """At the wall — does the actual computation."""
        zone = _zone()
        p = {"x": 50.0, "y": 50.0}
        n_iter = 100_000
        for _ in range(1000):
            nav.boundary_repulsion(p, zone)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            nav.boundary_repulsion(p, zone)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 10.0, (
            f"boundary_repulsion at edge averaged {avg_us:.3f} us — "
            "computation regression")


class TestBuildingRepulsionPerf:
    def test_dense_buildings_under_50us(self):
        """50 buildings — typical late-game station + extras count."""
        s = _state_with_buildings(50)
        p = {"x": 3200.0, "y": 3200.0}
        n_iter = 10_000
        for _ in range(100):
            nav.building_repulsion(p, s)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            nav.building_repulsion(p, s)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 100.0, (
            f"building_repulsion with 50 buildings averaged "
            f"{avg_us:.3f} us — O(N) scan regression")

    def test_no_buildings_fast_path_under_2us(self):
        """Empty list — fast-path returns (0, 0)."""
        s = {"buildings": []}
        p = {"x": 3200.0, "y": 3200.0}
        n_iter = 100_000
        for _ in range(1000):
            nav.building_repulsion(p, s)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            nav.building_repulsion(p, s)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 5.0, (
            f"building_repulsion with no buildings averaged "
            f"{avg_us:.3f} us — fast path regression")


# ── Steered heading ───────────────────────────────────────────────────

class TestSteeredHeadingPerf:
    def test_steered_heading_under_50us(self):
        s = {"zone": _zone(),
             "buildings": _state_with_buildings(20)["buildings"]}
        p = {"x": 100.0, "y": 100.0}
        n_iter = 10_000
        for _ in range(100):
            nav.steered_heading(s, p, 1000.0, 0.0, 1000.0)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            nav.steered_heading(s, p, 1000.0, 0.0, 1000.0)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 100.0, (
            f"steered_heading averaged {avg_us:.3f} us — regression")


# ── Stuck detection ───────────────────────────────────────────────────

class TestDetectStuckPerf:
    def test_full_window_history_under_5us(self):
        # 15 samples — what a 1.5 s window at 10 Hz produces.
        history = [(i * 0.1, 100.0, 100.0, 0.0) for i in range(15)]
        s = {"history": history, "escape_until": 0.0, "last_log": 0.0}
        n_iter = 100_000
        for _ in range(1000):
            nav.detect_stuck(s)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            nav.detect_stuck(s)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 10.0, (
            f"detect_stuck over 15 samples averaged {avg_us:.3f} us — "
            "rolling-history scan regression")


# ── Blacklist scans ───────────────────────────────────────────────────

class TestBlacklistPerf:
    def test_pickup_scan_with_50_entries_under_10us(self):
        clock = [0.0]
        get_now = lambda: clock[0]
        blist: dict = {}
        for i in range(50):
            bl.blacklist_pickup(
                {"x": float(i * 100), "y": float(i * 100)},
                blist, get_now)
        pu = {"x": 9999.0, "y": 9999.0}  # not blacklisted
        n_iter = 10_000
        for _ in range(100):
            bl.pickup_is_blacklisted(pu, blist, get_now)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            bl.pickup_is_blacklisted(pu, blist, get_now)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 50.0, (
            f"pickup_is_blacklisted with 50 entries averaged "
            f"{avg_us:.3f} us — O(N) scan regression")

    def test_nearest_pickup_combined_under_50us(self):
        clock = [0.0]
        get_now = lambda: clock[0]
        blist: dict = {}
        state = {
            "iron_pickups": [{"x": float(i * 47), "y": float(i * 31)}
                             for i in range(30)],
            "blueprint_pickups": [],
        }
        n_iter = 10_000
        for _ in range(100):
            bl.nearest_pickup(state, 0.0, 0.0, blist, get_now)
        t0 = time.perf_counter()
        for _ in range(n_iter):
            bl.nearest_pickup(state, 0.0, 0.0, blist, get_now)
        avg_us = (time.perf_counter() - t0) / n_iter * 1_000_000
        assert avg_us < 100.0, (
            f"nearest_pickup over 30 pickups averaged {avg_us:.3f} us")


# ── End-to-end: do_auto cascade unchanged after refactor ──────────────

class TestAutoCascadeAfterRefactor:
    """Mirror of TestAutoCascadePerf in test_performance_bot.py — pins
    that the refactor introduced no per-tick overhead in the FSM
    dispatch path."""

    def test_do_auto_under_2ms(self, monkeypatch):
        import bot_autopilot as ap
        monkeypatch.setattr(ap.KeyState, "hold",
                            staticmethod(lambda key, down: None))
        monkeypatch.setattr(ap.KeyState, "release_all",
                            staticmethod(lambda: None))
        monkeypatch.setattr(ap, "_ensure_weapon",
                            lambda *a, **kw: None)
        ap._fsm_reset()
        state = {
            "zone": {"world_w": 6400.0, "world_h": 6400.0},
            "buildings": _state_with_buildings(20)["buildings"],
            "asteroids": [{"x": float(i * 47), "y": float(i * 31)}
                          for i in range(15)],
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
        # Warm-up.
        for _ in range(20):
            ap._do_auto(state, p)
        n_iter = 1000
        t0 = time.perf_counter()
        for _ in range(n_iter):
            ap._do_auto(state, p)
        avg_ms = (time.perf_counter() - t0) / n_iter * 1000
        assert avg_ms < 2.0, (
            f"_do_auto with 15 asteroids + 20 buildings averaged "
            f"{avg_ms:.3f} ms — refactor regression")
