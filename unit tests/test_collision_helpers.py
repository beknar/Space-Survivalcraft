"""Tests for collisions.resolve_overlap and collisions.reflect_velocity.

These two helpers were extracted from six near-duplicate collision handlers
during the refactor. They're pure math, no Arcade window required, and are
called from many places — so locking down their behaviour matters.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from collisions import resolve_overlap, reflect_velocity


def _body(x: float = 0.0, y: float = 0.0,
          vx: float = 0.0, vy: float = 0.0) -> SimpleNamespace:
    """Build a minimal duck-typed body with the attributes the helpers touch."""
    return SimpleNamespace(center_x=x, center_y=y, vel_x=vx, vel_y=vy)


# ── resolve_overlap ────────────────────────────────────────────────────────

class TestResolveOverlapDetection:
    def test_returns_none_when_apart(self):
        a = _body(0, 0)
        b = _body(100, 0)
        assert resolve_overlap(a, b, 10, 10) is None

    def test_returns_none_at_exact_contact(self):
        # Touching but not overlapping → no contact reported
        a = _body(0, 0)
        b = _body(20, 0)
        assert resolve_overlap(a, b, 10, 10) is None

    def test_returns_normal_when_overlapping(self):
        a = _body(0, 0)
        b = _body(15, 0)
        contact = resolve_overlap(a, b, 10, 10)
        assert contact is not None
        nx, ny = contact
        # Normal points FROM b TO a → a is at -x relative to b → nx ≈ -1
        assert nx == pytest.approx(-1.0)
        assert ny == pytest.approx(0.0)

    def test_handles_identical_position(self):
        # Degenerate case: bodies stacked exactly. Helper must not divide by 0.
        a = _body(50, 50)
        b = _body(50, 50)
        contact = resolve_overlap(a, b, 10, 10)
        assert contact is not None
        nx, ny = contact
        # Any unit vector is acceptable; we just require a finite answer.
        assert math.isfinite(nx)
        assert math.isfinite(ny)


class TestResolveOverlapPushApart:
    def test_one_body_push(self):
        # push_a=1.0, push_b=0.0 → a moves the full overlap, b stays put
        a = _body(0, 0)
        b = _body(15, 0)
        resolve_overlap(a, b, 10, 10, push_a=1.0, push_b=0.0)
        # a should move to x = -5 (overlap of 5 along nx=-1)
        assert a.center_x == pytest.approx(-5.0)
        assert a.center_y == pytest.approx(0.0)
        assert b.center_x == pytest.approx(15.0)
        assert b.center_y == pytest.approx(0.0)

    def test_symmetric_push(self):
        # push_a=0.5, push_b=0.5 → both move half the overlap
        a = _body(0, 0)
        b = _body(15, 0)
        resolve_overlap(a, b, 10, 10, push_a=0.5, push_b=0.5)
        assert a.center_x == pytest.approx(-2.5)
        assert b.center_x == pytest.approx(17.5)

    def test_asymmetric_60_40_push(self):
        # Wanderer collision uses 0.6 / 0.4
        a = _body(0, 0)
        b = _body(10, 0)
        resolve_overlap(a, b, 10, 10, push_a=0.6, push_b=0.4)
        # Overlap = 10, push_a=0.6 → a moves -6, b moves +4
        assert a.center_x == pytest.approx(-6.0)
        assert b.center_x == pytest.approx(14.0)


# ── reflect_velocity ───────────────────────────────────────────────────────

class TestReflectVelocity:
    def test_head_on_bounce_inverts(self):
        # Body moving +x into a wall whose normal points -x (back at body).
        # With bounce=1.0, velocity should fully invert.
        obj = _body(vx=10.0, vy=0.0)
        dot = reflect_velocity(obj, nx=-1.0, ny=0.0, bounce=1.0)
        assert dot == pytest.approx(-10.0)
        assert obj.vel_x == pytest.approx(-10.0)
        assert obj.vel_y == pytest.approx(0.0)

    def test_zero_bounce_stops_motion_into_normal(self):
        # bounce=0 → only the inward velocity component is removed
        obj = _body(vx=10.0, vy=5.0)
        reflect_velocity(obj, nx=-1.0, ny=0.0, bounce=0.0)
        # Inward x cancelled, perpendicular y preserved
        assert obj.vel_x == pytest.approx(0.0)
        assert obj.vel_y == pytest.approx(5.0)

    def test_partial_bounce(self):
        # bounce=0.5 → half-elastic bounce
        obj = _body(vx=10.0, vy=0.0)
        reflect_velocity(obj, nx=-1.0, ny=0.0, bounce=0.5)
        assert obj.vel_x == pytest.approx(-5.0)

    def test_no_op_when_moving_away(self):
        # Already moving away from the surface — should not be touched
        obj = _body(vx=-10.0, vy=0.0)
        dot = reflect_velocity(obj, nx=-1.0, ny=0.0, bounce=1.0)
        assert dot == pytest.approx(10.0)  # positive = moving away
        assert obj.vel_x == pytest.approx(-10.0)  # unchanged
        assert obj.vel_y == pytest.approx(0.0)

    def test_diagonal_normal(self):
        # 45° wall, body moving straight right, should bounce up-left
        obj = _body(vx=10.0, vy=0.0)
        n = math.sqrt(0.5)
        reflect_velocity(obj, nx=-n, ny=n, bounce=1.0)
        # Reflection: v - (1 + bounce) * (v · n) * n
        # v · n = 10 * -n = -10n; (1+1) * -10n * n = -20*0.5 = -10 in x, +10 in y... let's verify
        # vel_x -= 2 * (-10n) * (-n) = vel_x - 2*10*0.5 = 10 - 10 = 0
        # vel_y -= 2 * (-10n) * (n) = vel_y - (-10) = 10
        assert obj.vel_x == pytest.approx(0.0, abs=1e-9)
        assert obj.vel_y == pytest.approx(10.0, abs=1e-9)


# ── End-to-end: a single full collision step ──────────────────────────────

class TestFullCollisionRoundTrip:
    def test_ship_into_static_asteroid(self):
        # Player moving right, hits static asteroid; should be pushed left and
        # bounce back along x.
        ship = _body(x=0.0, y=0.0, vx=50.0, vy=0.0)
        rock = _body(x=15.0, y=0.0)
        contact = resolve_overlap(ship, rock, 10, 10, push_a=1.0, push_b=0.0)
        assert contact is not None
        nx, ny = contact
        reflect_velocity(ship, nx, ny, bounce=0.5)
        # Ship pushed away from rock and now moving away
        assert ship.center_x < 0.0
        assert ship.vel_x < 0.0
        assert rock.center_x == pytest.approx(15.0)  # rock unmoved
