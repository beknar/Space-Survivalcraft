"""Unit tests pinning the ``bot_autopilot_blacklist`` module API.

Companion to the blacklist test classes in ``test_bot_autopilot_fsm.py``.
The FSM tests exercise blacklist behaviour through the ``ap._blacklist_pickup``
re-export shim; these tests target the underlying module so the seam
stays stable across future refactors.
"""
from __future__ import annotations

import pytest

import bot_autopilot_blacklist as bl


@pytest.fixture
def clock():
    """Mutable clock the tests can advance manually."""
    return [0.0]


@pytest.fixture
def get_now(clock):
    return lambda: clock[0]


# ── Pickup blacklist ──────────────────────────────────────────────────

class TestPickupBlacklist:
    def test_empty_blacklist_never_matches(self, get_now):
        assert bl.pickup_is_blacklisted(
            {"x": 0.0, "y": 0.0}, {}, get_now) is False

    def test_blacklisted_pickup_matches_exact_pos(self, clock, get_now):
        blist: dict = {}
        bl.blacklist_pickup({"x": 100.0, "y": 0.0}, blist, get_now)
        assert bl.pickup_is_blacklisted(
            {"x": 100.0, "y": 0.0}, blist, get_now) is True

    def test_radius_covers_close_pickup(self, clock, get_now):
        blist: dict = {}
        bl.blacklist_pickup({"x": 100.0, "y": 0.0}, blist, get_now)
        # Within PICKUP_BLACKLIST_RADIUS_PX (60 px) — should match.
        assert bl.pickup_is_blacklisted(
            {"x": 130.0, "y": 0.0}, blist, get_now) is True
        # Outside the radius — should not.
        assert bl.pickup_is_blacklisted(
            {"x": 200.0, "y": 0.0}, blist, get_now) is False

    def test_entries_expire(self, clock, get_now):
        blist: dict = {}
        bl.blacklist_pickup({"x": 100.0, "y": 0.0}, blist, get_now)
        assert bl.pickup_is_blacklisted(
            {"x": 100.0, "y": 0.0}, blist, get_now) is True
        clock[0] += bl.PICKUP_BLACKLIST_TTL_S + 1.0
        assert bl.pickup_is_blacklisted(
            {"x": 100.0, "y": 0.0}, blist, get_now) is False
        # Lazy eviction cleared the entry.
        assert len(blist) == 0

    def test_position_rounded_to_10px_grid(self, clock, get_now):
        """Two adds within 5 px coalesce into one entry."""
        blist: dict = {}
        bl.blacklist_pickup({"x": 100.0, "y": 0.0}, blist, get_now)
        bl.blacklist_pickup({"x": 103.0, "y": 0.0}, blist, get_now)
        assert len(blist) == 1


class TestNearestPickup:
    def test_blacklisted_pickup_skipped(self, clock, get_now):
        blist: dict = {}
        bl.blacklist_pickup({"x": 100.0, "y": 0.0}, blist, get_now)
        state = {
            "iron_pickups": [{"x": 100.0, "y": 0.0}, {"x": 500.0, "y": 0.0}],
            "blueprint_pickups": [],
        }
        pu, d = bl.nearest_pickup(state, 0.0, 0.0, blist, get_now)
        assert pu == {"x": 500.0, "y": 0.0}
        assert d == pytest.approx(500.0)

    def test_blueprints_sort_first(self, get_now):
        blist: dict = {}
        state = {
            "iron_pickups": [{"x": 100.0, "y": 0.0}],
            "blueprint_pickups": [{"x": 100.0, "y": 0.0}],
        }
        pu, _ = bl.nearest_pickup(state, 0.0, 0.0, blist, get_now)
        # The bp comes first in the merged candidates list, so the
        # equally-close blueprint wins.
        assert pu in state["blueprint_pickups"]


# ── Asteroid blacklist ────────────────────────────────────────────────

class TestAsteroidBlacklist:
    def test_empty_never_matches(self, get_now):
        assert bl.asteroid_is_blacklisted(
            {"x": 0.0, "y": 0.0}, {}, get_now) is False

    def test_blacklist_round_trips(self, clock, get_now):
        blist: dict = {}
        bl.blacklist_asteroid({"x": 50.0, "y": 50.0}, blist, get_now)
        assert bl.asteroid_is_blacklisted(
            {"x": 50.0, "y": 50.0}, blist, get_now) is True

    def test_asteroid_radius_smaller_than_pickup(self, clock, get_now):
        """Asteroid blacklist uses a 40 px radius vs pickup's 60 px."""
        blist: dict = {}
        bl.blacklist_asteroid({"x": 100.0, "y": 0.0}, blist, get_now)
        # Inside 40 px — match.
        assert bl.asteroid_is_blacklisted(
            {"x": 130.0, "y": 0.0}, blist, get_now) is True
        # Outside 40 px — no match (would have matched pickup).
        assert bl.asteroid_is_blacklisted(
            {"x": 145.0, "y": 0.0}, blist, get_now) is False

    def test_asteroid_ttl_shorter_than_pickup(self):
        """Asteroid TTL (60 s) is much shorter than pickup TTL (300 s).
        Asteroids may be reachable from a different angle later."""
        assert bl.ASTEROID_BLACKLIST_TTL_S < bl.PICKUP_BLACKLIST_TTL_S


class TestNearestAsteroid:
    def test_blacklisted_asteroid_skipped(self, clock, get_now):
        blist: dict = {}
        bl.blacklist_asteroid({"x": 100.0, "y": 0.0}, blist, get_now)
        state = {
            "asteroids": [{"x": 100.0, "y": 0.0}, {"x": 800.0, "y": 0.0}],
        }
        ast, d = bl.nearest_asteroid(state, 0.0, 0.0, blist, get_now)
        assert ast == {"x": 800.0, "y": 0.0}
        assert d == pytest.approx(800.0)

    def test_no_asteroids_returns_none(self, get_now):
        ast, d = bl.nearest_asteroid({}, 0.0, 0.0, {}, get_now)
        assert ast is None


# ── Generic nearest helper ────────────────────────────────────────────

class TestNearest:
    def test_empty_list_returns_none(self):
        sp, d = bl.nearest([], 0.0, 0.0)
        assert sp is None
        assert d == 1e9  # default max

    def test_picks_closest(self):
        items = [{"x": 100.0, "y": 0.0}, {"x": 50.0, "y": 0.0}]
        sp, d = bl.nearest(items, 0.0, 0.0)
        assert sp == {"x": 50.0, "y": 0.0}
        assert d == pytest.approx(50.0)
