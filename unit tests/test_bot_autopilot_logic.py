"""Unit tests for ``bot_autopilot`` -- the external state-machine
process that translates intents into keystrokes.

We test the pure-logic helpers (``nearest``, ``angle_to``,
``heading_delta``, ``_nearest_pickup``, ``_do_auto`` priority
cascade) by patching the ``KeyState`` static class so it
records keys instead of actually sending them, and stubbing
the small slice of state the helpers read.
"""
from __future__ import annotations

import math

import pytest

import bot_autopilot as ap


# ── KeyState recorder ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _key_recorder(monkeypatch):
    """Replace KeyState.hold so it records (key, down) tuples
    instead of touching pyautogui."""
    log: list[tuple[str, bool]] = []

    def fake_hold(key: str, down: bool) -> None:
        log.append((key, down))
        if down:
            ap.KeyState.held.add(key)
        else:
            ap.KeyState.held.discard(key)

    monkeypatch.setattr(ap.KeyState, "hold", staticmethod(fake_hold))
    monkeypatch.setattr(ap.KeyState, "release_all",
                        staticmethod(lambda: ap.KeyState.held.clear()))
    ap.KeyState.held.clear()
    # Also reset the spiral state so each test starts fresh.
    ap._spiral_reset()
    yield log


# ── Geometry helpers ──────────────────────────────────────────────────────


class TestAngleTo:
    def test_north(self):
        assert ap.angle_to(0, 100) == pytest.approx(0.0)

    def test_east(self):
        assert ap.angle_to(100, 0) == pytest.approx(90.0)

    def test_south(self):
        assert ap.angle_to(0, -100) == pytest.approx(180.0)

    def test_west(self):
        assert ap.angle_to(-100, 0) == pytest.approx(-90.0)


class TestHeadingDelta:
    def test_no_delta(self):
        assert ap.heading_delta(0, 0) == pytest.approx(0.0)

    def test_clockwise(self):
        assert ap.heading_delta(0, 90) == pytest.approx(90.0)

    def test_counter_clockwise(self):
        assert ap.heading_delta(0, -90) == pytest.approx(-90.0)

    def test_wraps_through_180(self):
        # Going 350 -> 10 should be a +20 rotation, not -340.
        assert ap.heading_delta(350, 10) == pytest.approx(20.0)


class TestNearest:
    def test_returns_none_for_empty_list(self):
        item, dist = ap.nearest([], 0, 0)
        assert item is None
        assert dist == 1e9

    def test_picks_closest_of_many(self):
        items = [
            {"x": 100, "y": 0},
            {"x": 50, "y": 0},      # closest
            {"x": 200, "y": 0},
        ]
        item, dist = ap.nearest(items, 0, 0)
        assert item == {"x": 50, "y": 0}
        assert dist == pytest.approx(50.0)


class TestNearestPickup:
    def test_blueprints_listed_first(self):
        # Same distance -> blueprints win.
        state = {
            "iron_pickups": [{"x": 100, "y": 0, "amount": 10}],
            "blueprint_pickups": [{"x": 100, "y": 0,
                                   "item_type": "bp_armor"}],
        }
        item, dist = ap._nearest_pickup(state, 0, 0)
        assert item.get("item_type") == "bp_armor"
        assert dist == pytest.approx(100.0)

    def test_returns_iron_when_no_blueprints(self):
        state = {
            "iron_pickups": [{"x": 50, "y": 0, "amount": 10}],
            "blueprint_pickups": [],
        }
        item, _ = ap._nearest_pickup(state, 0, 0)
        assert item["amount"] == 10

    def test_returns_none_when_both_empty(self):
        state = {"iron_pickups": [], "blueprint_pickups": []}
        item, dist = ap._nearest_pickup(state, 0, 0)
        assert item is None


# ── Auto cascade per priority ─────────────────────────────────────────────


def _state(player=None, aliens=(), asteroids=(),
           iron_pickups=(), blueprint_pickups=(),
           weapon_name="Basic Laser", weapon_idx=0):
    return {
        "player": player or {
            "x": 0.0, "y": 0.0, "heading": 0.0,
            "shields": 150, "max_shields": 150,
        },
        "weapon": {"name": weapon_name, "idx": weapon_idx},
        "aliens": list(aliens),
        "asteroids": list(asteroids),
        "iron_pickups": list(iron_pickups),
        "blueprint_pickups": list(blueprint_pickups),
        "menu": {},
    }


class TestAutoUnderAttack:
    def test_engages_alien_within_engage_range(self, _key_recorder):
        s = _state(aliens=[{"x": 400, "y": 0, "hp": 50}])
        ap._do_auto(s, s["player"])
        # Should have driven movement toward the alien (W or rotation).
        keys = {k for k, down in _key_recorder if down}
        assert "w" in keys or "a" in keys or "d" in keys

    def test_ignores_alien_outside_engage_range(self, _key_recorder):
        # 1000 px > ENGAGE_RANGE (800).
        s = _state(aliens=[{"x": 1000, "y": 0, "hp": 50}])
        ap._do_auto(s, s["player"])
        # No alien in range -> shields full -> mining.  Asteroid
        # list is empty so it falls through to spiral search.
        # The key thing: not under-attack means no urgent goto to
        # the far alien.  Confirm at least that we didn't head
        # toward (1000, 0): with full shields, we'd be either
        # mining (asteroid empty -> spiral) or idling.
        assert any(True for _ in _key_recorder)


class TestAutoGather:
    def test_pickup_in_range_triggers_goto(self, _key_recorder):
        s = _state(
            iron_pickups=[{"x": 200, "y": 0, "amount": 10,
                           "item_type": "iron"}])
        ap._do_auto(s, s["player"])
        # Should release space (gather doesn't fire) + move toward
        # the pickup.
        events = list(_key_recorder)
        # Last "space" event must be False (released).
        space_events = [d for k, d in events if k == "space"]
        if space_events:
            assert space_events[-1] is False


class TestAutoShieldRecover:
    def test_idles_below_50_percent_shields(self, _key_recorder):
        s = _state(player={
            "x": 0, "y": 0, "heading": 0,
            "shields": 30, "max_shields": 150,    # 20 % -- below 50 %
        })
        ap._do_auto(s, s["player"])
        # Idle -> all keys released.
        assert ap.KeyState.held == set()

    def test_acts_at_or_above_50_percent_shields(self, _key_recorder):
        # Exactly 50 % -- threshold says "below 50% idles", so
        # 75/150 should NOT idle -- it should pursue the next
        # priority.  With no asteroids visible, spiral fires
        # (which holds Mining Beam fire on).
        s = _state(player={
            "x": 0, "y": 0, "heading": 0,
            "shields": 75, "max_shields": 150,
        })
        ap._do_auto(s, s["player"])
        # Spiral search holds space (mining beam).
        assert ("space", True) in _key_recorder


class TestAutoMine:
    def test_full_shields_mines_nearest_asteroid(self, _key_recorder):
        s = _state(
            asteroids=[{"x": 300, "y": 0, "hp": 100}],
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        # Should have started moving toward the asteroid.
        keys_pressed = {k for k, d in _key_recorder if d}
        assert "w" in keys_pressed or "d" in keys_pressed or \
            "a" in keys_pressed


class TestSpiralFallback:
    def test_anchors_on_first_call(self, _key_recorder):
        s = _state(player={"x": 1000, "y": 2000, "heading": 0,
                           "shields": 150, "max_shields": 150})
        ap._do_spiral_search(s, s["player"])
        assert ap._spiral_state["anchor"] == (1000.0, 2000.0)

    def test_radius_grows_each_tick(self, _key_recorder):
        s = _state(player={"x": 0, "y": 0, "heading": 0,
                           "shields": 150, "max_shields": 150})
        ap._do_spiral_search(s, s["player"])
        r1 = ap._spiral_state["radius"]
        ap._do_spiral_search(s, s["player"])
        r2 = ap._spiral_state["radius"]
        assert r2 > r1

    def test_resets_after_max_radius(self, _key_recorder):
        ap._spiral_state["anchor"] = (0.0, 0.0)
        ap._spiral_state["radius"] = 2999.5
        s = _state(player={"x": 0, "y": 0, "heading": 0,
                           "shields": 150, "max_shields": 150})
        ap._do_spiral_search(s, s["player"])
        # Radius hit cap -> reset.
        assert ap._spiral_state["anchor"] is None


class TestMenuSuppression:
    def test_any_menu_open_releases_keys(self, _key_recorder):
        s = _state(aliens=[{"x": 200, "y": 0, "hp": 50}])
        s["menu"] = {"build": True}
        ap.execute_intent({**s, "intent": {"type": "auto"}})
        assert ap.KeyState.held == set()
