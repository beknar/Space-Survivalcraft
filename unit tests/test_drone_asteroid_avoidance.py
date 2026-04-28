"""Tests for the drone-vs-asteroid collision + routing fix.

Drones now push out of asteroid overlap on every tick, bias their
steering vector away from nearby rocks, and the mining drone
includes wandering magnetic asteroids in its target search.
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest


def _stub_asteroid(x, y):
    return SimpleNamespace(center_x=float(x), center_y=float(y))


# ── Push-out collision ────────────────────────────────────────────────────


class TestDroneAsteroidPushout:
    def test_drone_pushed_out_of_overlap(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        # Asteroid centred 5 px away — well inside ``DRONE_RADIUS +
        # ASTEROID_RADIUS``, so push-out should fire and clear the
        # overlap.
        a = _stub_asteroid(5.0, 0.0)
        fired = d._apply_asteroid_pushout([a])
        assert fired is True
        # Drone is now at least the combined-radius away.
        from constants import ASTEROID_RADIUS
        clearance = (
            (d.center_x - a.center_x) ** 2
            + (d.center_y - a.center_y) ** 2) ** 0.5
        assert clearance >= d.radius + ASTEROID_RADIUS - 0.5

    def test_no_push_when_clear(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        a = _stub_asteroid(500.0, 500.0)
        before = (d.center_x, d.center_y)
        fired = d._apply_asteroid_pushout([a])
        assert fired is False
        assert (d.center_x, d.center_y) == before

    def test_empty_list_safe(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        assert d._apply_asteroid_pushout([]) is False
        assert d._apply_asteroid_pushout(None or ()) is False


# ── Avoidance steering ────────────────────────────────────────────────────


class TestDroneAsteroidAvoidance:
    def test_steering_biases_away_from_nearby_asteroid(self):
        """Asteroid placed in the steering direction → returned
        vector should rotate AWAY from it."""
        from sprites.drone import CombatDrone
        import math
        d = CombatDrone(0.0, 0.0)
        # Heading east (1, 0); asteroid north-east of drone, just
        # inside the avoid radius.
        a = _stub_asteroid(40.0, 20.0)
        nx, ny = d._asteroid_avoidance([a], 1.0, 0.0)
        # Result still mostly east but biased south (away from the
        # asteroid).
        assert nx > 0.0
        assert ny < 0.0
        # Unit vector.
        assert math.isclose(math.hypot(nx, ny), 1.0, rel_tol=0.01)

    def test_steering_unchanged_when_asteroids_far(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        a = _stub_asteroid(800.0, 0.0)
        nx, ny = d._asteroid_avoidance([a], 1.0, 0.0)
        assert (nx, ny) == (1.0, 0.0)


# ── Mining drone targets wandering magnetic asteroids ─────────────────────


class TestMiningDroneTargetsWanderers:
    def test_wanderer_picked_when_in_range(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        wanderer = _stub_asteroid(150.0, 0.0)
        zone = SimpleNamespace(
            _iron_asteroids=[],
            _double_iron=[],
            _copper_asteroids=[],
            _wanderers=[wanderer])
        gv = SimpleNamespace(_zone=zone, asteroid_list=[])
        target = d._nearest_asteroid(gv)
        assert target is wanderer

    def test_static_asteroid_still_preferred_when_closer(self):
        """If both a static rock and a wanderer are in range, the
        nearest one wins regardless of source list."""
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        close_iron = _stub_asteroid(80.0, 0.0)
        far_wanderer = _stub_asteroid(300.0, 0.0)
        zone = SimpleNamespace(
            _iron_asteroids=[close_iron],
            _double_iron=[],
            _copper_asteroids=[],
            _wanderers=[far_wanderer])
        gv = SimpleNamespace(_zone=zone, asteroid_list=[])
        assert d._nearest_asteroid(gv) is close_iron


# ── _iter_asteroids helper ────────────────────────────────────────────────


class TestIterAsteroidsHelper:
    def test_combines_zone1_and_zone2_lists(self):
        from sprites.drone import _iter_asteroids
        z1_rock = _stub_asteroid(10, 10)
        z2_iron = _stub_asteroid(20, 20)
        z2_wanderer = _stub_asteroid(30, 30)
        zone = SimpleNamespace(
            _iron_asteroids=[z2_iron],
            _wanderers=[z2_wanderer])
        gv = SimpleNamespace(_zone=zone, asteroid_list=[z1_rock])
        out = _iter_asteroids(gv)
        assert z1_rock in out
        assert z2_iron in out
        assert z2_wanderer in out

    def test_no_zone_returns_just_gv_list(self):
        from sprites.drone import _iter_asteroids
        z1_rock = _stub_asteroid(10, 10)
        gv = SimpleNamespace(asteroid_list=[z1_rock])
        out = _iter_asteroids(gv)
        assert out == [z1_rock]

    def test_empty_safe(self):
        from sprites.drone import _iter_asteroids
        gv = SimpleNamespace()
        assert _iter_asteroids(gv) == []
