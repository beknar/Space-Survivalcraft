"""Performance budget tests for the bot stack.

These pin per-tick CPU + per-request latency for the three
hot paths the bot relies on:

  * ``bot_combat_assist.tick``  -- runs inside the game loop,
    must be sub-millisecond at typical alien counts.
  * ``bot_api.get_state``       -- HTTP handler reads it on
    every poll; serialise time must be modest.
  * ``bot_api.start_api`` round-trip latency over localhost.

Thresholds are conservative so the tests don't go green/red
based on machine load -- they catch order-of-magnitude
regressions, not 10 % drift.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib.request import urlopen

import pytest


# ── Stub builders (mirrors test_bot_api_integration) ──────────────────────


def _alien(x, y):
    return SimpleNamespace(center_x=x, center_y=y, hp=50)


def _gv_with_n_aliens(n: int):
    weapons = [
        SimpleNamespace(name="Basic Laser"),
        SimpleNamespace(name="Mining Beam"),
        SimpleNamespace(name="Melee"),
    ]
    aliens = [_alien((i * 71) % 800, (i * 53) % 800) for i in range(n)]
    asteroids = [
        SimpleNamespace(center_x=(i * 47) % 6000,
                        center_y=(i * 31) % 6000, hp=100)
        for i in range(75)
    ]
    gv = SimpleNamespace(
        player=SimpleNamespace(
            center_x=400.0, center_y=400.0, heading=0.0,
            vel_x=0.0, vel_y=0.0,
            hp=100, max_hp=100, shields=150, max_shields=150,
            guns=1,
        ),
        _weapons=weapons,
        _weapon_idx=0,
        _ability_meter=100,
        _ability_meter_max=100,
        _faction="Earth",
        _ship_type="Aegis",
        _ship_level=1,
        _zone=SimpleNamespace(
            zone_id="ZoneID.MAIN", world_width=6400, world_height=6400),
        _boss=None,
        _nebula_boss=None,
        alien_list=aliens,
        asteroid_list=asteroids,
        building_list=[],
        iron_pickup_list=[],
        blueprint_pickup_list=[],
        inventory=SimpleNamespace(_items={}, _open=False),
        _build_menu_open=False,
        _escape_menu_open=False,
        _player_dead=False,
        _dialogue_open=False,
    )
    gv._active_weapon = weapons[0]
    return gv


# ── combat assist tick ────────────────────────────────────────────────────


class TestCombatAssistTickPerf:
    """tick() must be sub-millisecond -- it runs inside
    update_weapons every game frame.  Budget covers the
    "30 aliens within range" case (Zone 1 default density)."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        import bot_combat_assist as ca
        ca._state.update({
            "enabled": True, "fired_this_tick": False,
            "last_threat_dist": -1.0, "last_threat_type": "",
            "last_aim_heading": 0.0, "engagements": 0,
            "_holdover_until": 0.0,
        })
        yield

    @pytest.mark.parametrize("n_aliens", [10, 30, 100])
    def test_tick_under_1ms(self, n_aliens):
        import bot_combat_assist as ca
        gv = _gv_with_n_aliens(n_aliens)
        # Warm up to avoid JIT/cache effects in the measurement.
        for _ in range(50):
            ca.tick(gv, 1 / 60, original_fire=False)
        # Measure.
        n_iter = 1000
        t0 = time.perf_counter()
        for _ in range(n_iter):
            ca.tick(gv, 1 / 60, original_fire=False)
        elapsed = time.perf_counter() - t0
        avg_us = (elapsed / n_iter) * 1e6
        # Generous budget: 1 ms / tick at 100 aliens.  Under the
        # 60-FPS frame budget of 16.6 ms by 16x even in worst case.
        assert avg_us < 1000, (
            f"combat_assist.tick at n={n_aliens} aliens averaged "
            f"{avg_us:.1f} us -- regression?")


# ── bot_api.get_state extraction ──────────────────────────────────────────


class TestGetStatePerf:
    """get_state walks every sprite list -- budget covers the
    Zone 1 default population (75 asteroids + 30 aliens) plus
    a few buildings + pickups."""

    def test_get_state_under_5ms(self):
        import bot_api
        gv = _gv_with_n_aliens(30)
        # Warm-up.
        for _ in range(20):
            bot_api.get_state(gv)
        n_iter = 200
        t0 = time.perf_counter()
        for _ in range(n_iter):
            bot_api.get_state(gv)
        avg_ms = (time.perf_counter() - t0) / n_iter * 1000
        assert avg_ms < 5.0, (
            f"bot_api.get_state averaged {avg_ms:.2f} ms -- "
            f"too slow for 10 Hz polling")


# ── bot_api round-trip latency ────────────────────────────────────────────


class TestBotApiHTTPLatency:
    """End-to-end localhost latency for the autopilot's poll
    loop.  Must comfortably fit inside its 100 ms tick budget."""

    @pytest.fixture(scope="class")
    def server(self):
        import bot_api
        gv = _gv_with_n_aliens(30)
        bot_api.start_api(gv, host="127.0.0.1", port=18766)
        # Wait for socket to bind.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                with urlopen(
                        "http://127.0.0.1:18766/health", timeout=0.5) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.05)
        yield gv
        bot_api.stop_api()

    def test_state_round_trip_under_50ms(self, server):
        # Warm-up.
        for _ in range(5):
            with urlopen("http://127.0.0.1:18766/state", timeout=2) as r:
                r.read()
        n_iter = 50
        t0 = time.perf_counter()
        for _ in range(n_iter):
            with urlopen("http://127.0.0.1:18766/state", timeout=2) as r:
                _ = json.loads(r.read())
        avg_ms = (time.perf_counter() - t0) / n_iter * 1000
        assert avg_ms < 50.0, (
            f"/state HTTP round-trip averaged {avg_ms:.2f} ms -- "
            f"would tank the autopilot's 10 Hz poll")


# ── autopilot _do_auto cascade ────────────────────────────────────────────


class TestAutoCascadePerf:
    """_do_auto is the autopilot's per-tick decision path.  Even
    though it runs at 10 Hz (way below frame rate) it should
    still be fast enough that the tick budget is dominated by
    the HTTP fetch, not the logic."""

    @pytest.fixture(autouse=True)
    def _stub_keystate(self, monkeypatch):
        import bot_autopilot as ap
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda key, down: None))
        monkeypatch.setattr(
            ap.KeyState, "release_all",
            staticmethod(lambda: None))
        ap._spiral_reset()
        yield

    def test_auto_cascade_under_2ms(self):
        import bot_autopilot as ap
        gv = _gv_with_n_aliens(30)
        # Build a state dict from the stub gv -- mirrors the API.
        import bot_api
        state = bot_api.get_state(gv)
        state["intent"] = {"type": "auto"}
        # Warm-up.
        for _ in range(20):
            ap.execute_intent(state)
        n_iter = 1000
        t0 = time.perf_counter()
        for _ in range(n_iter):
            ap.execute_intent(state)
        avg_ms = (time.perf_counter() - t0) / n_iter * 1000
        assert avg_ms < 2.0, (
            f"_do_auto cascade averaged {avg_ms:.3f} ms -- "
            f"regression in the autopilot decision path")
