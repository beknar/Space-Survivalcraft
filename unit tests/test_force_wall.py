"""Tests for sprites.force_wall.ForceWall.

Covers endpoint geometry (perpendicular to heading), lifetime + dead
flag transition, closest_point clamping at segment ends, blocks_point
radius gate, side_of sign convention, and segment_crosses true-cross
vs near-miss cases.  All pure-math; no Arcade window needed.
"""
from __future__ import annotations

import math

import pytest

from constants import FORCE_WALL_LENGTH, FORCE_WALL_DURATION
from sprites.force_wall import ForceWall


HALF = FORCE_WALL_LENGTH / 2


# ── Endpoint geometry ──────────────────────────────────────────────────────

class TestEndpointGeometry:
    def test_heading_zero_extends_along_x(self):
        w = ForceWall(0.0, 0.0, 0.0)
        assert w.x1 == pytest.approx(HALF)
        assert w.y1 == pytest.approx(0.0)
        assert w.x2 == pytest.approx(-HALF)
        assert w.y2 == pytest.approx(0.0)

    def test_heading_90_extends_along_negative_y(self):
        w = ForceWall(0.0, 0.0, 90.0)
        assert w.x1 == pytest.approx(0.0, abs=1e-9)
        assert w.x2 == pytest.approx(0.0, abs=1e-9)
        # cos(90) ~ 0, -sin(90) = -1 → y1 = -HALF, y2 = +HALF
        assert w.y1 == pytest.approx(-HALF)
        assert w.y2 == pytest.approx(HALF)

    def test_endpoints_centered_on_origin(self):
        w = ForceWall(500.0, 700.0, 33.0)
        # Midpoint of endpoints == (x, y)
        assert (w.x1 + w.x2) / 2 == pytest.approx(500.0)
        assert (w.y1 + w.y2) / 2 == pytest.approx(700.0)

    def test_endpoint_separation_equals_length(self):
        w = ForceWall(100.0, 100.0, 47.5)
        d = math.hypot(w.x2 - w.x1, w.y2 - w.y1)
        assert d == pytest.approx(FORCE_WALL_LENGTH)


# ── Lifetime ───────────────────────────────────────────────────────────────

class TestLifetime:
    def test_starts_alive(self):
        w = ForceWall(0.0, 0.0, 0.0)
        assert w.dead is False

    def test_dead_after_full_duration(self):
        w = ForceWall(0.0, 0.0, 0.0)
        w.update(FORCE_WALL_DURATION + 0.001)
        assert w.dead is True

    def test_alive_just_before_expiry(self):
        w = ForceWall(0.0, 0.0, 0.0)
        w.update(FORCE_WALL_DURATION - 0.5)
        assert w.dead is False

    def test_draw_returns_silently_when_dead(self):
        w = ForceWall(0.0, 0.0, 0.0)
        w.dead = True
        # Should not call any arcade primitives — bail out at top.
        w.draw()  # no exception => pass


# ── closest_point ──────────────────────────────────────────────────────────

class TestClosestPoint:
    def test_perpendicular_foot_on_segment(self):
        # Horizontal wall at y=0 from x=-HALF to x=+HALF
        w = ForceWall(0.0, 0.0, 0.0)
        cx, cy, d = w.closest_point(50.0, 30.0)
        assert cx == pytest.approx(50.0)
        assert cy == pytest.approx(0.0)
        assert d == pytest.approx(30.0)

    def test_clamps_to_endpoint_left(self):
        w = ForceWall(0.0, 0.0, 0.0)
        # Way past the negative end of the wall
        cx, cy, d = w.closest_point(-(HALF + 100.0), 0.0)
        # Closest point clamps to one of the endpoints (whichever is at -HALF)
        end = min(w.x1, w.x2)
        assert cx == pytest.approx(end)
        assert cy == pytest.approx(0.0)
        assert d == pytest.approx(100.0)

    def test_clamps_to_endpoint_right(self):
        w = ForceWall(0.0, 0.0, 0.0)
        cx, cy, d = w.closest_point(HALF + 50.0, 0.0)
        end = max(w.x1, w.x2)
        assert cx == pytest.approx(end)
        assert d == pytest.approx(50.0)

    def test_zero_length_wall_returns_endpoint(self):
        # Synthetically degenerate wall — defensive branch in closest_point
        w = ForceWall(0.0, 0.0, 0.0)
        w.x1 = w.x2 = 0.0
        w.y1 = w.y2 = 0.0
        cx, cy, d = w.closest_point(3.0, 4.0)
        assert (cx, cy) == (0.0, 0.0)
        assert d == pytest.approx(5.0)


# ── blocks_point ───────────────────────────────────────────────────────────

class TestBlocksPoint:
    def test_inside_radius_blocks(self):
        w = ForceWall(0.0, 0.0, 0.0)
        assert w.blocks_point(0.0, 10.0, radius=20.0) is True

    def test_outside_radius_does_not_block(self):
        w = ForceWall(0.0, 0.0, 0.0)
        assert w.blocks_point(0.0, 30.0, radius=20.0) is False

    def test_default_radius_20(self):
        w = ForceWall(0.0, 0.0, 0.0)
        assert w.blocks_point(0.0, 19.0) is True
        assert w.blocks_point(0.0, 20.0) is False  # strict < radius


# ── side_of + segment_crosses ──────────────────────────────────────────────

class TestSideOf:
    def test_opposite_sides_have_opposite_signs(self):
        # Horizontal wall, +y vs -y are opposite sides
        w = ForceWall(0.0, 0.0, 0.0)
        s_above = w.side_of(0.0, 50.0)
        s_below = w.side_of(0.0, -50.0)
        assert (s_above > 0) != (s_below > 0)

    def test_point_on_line_returns_zero(self):
        w = ForceWall(0.0, 0.0, 0.0)
        assert w.side_of(123.0, 0.0) == 0.0


class TestSegmentCrosses:
    def test_perpendicular_segment_crosses(self):
        w = ForceWall(0.0, 0.0, 0.0)  # horizontal wall on x-axis
        assert w.segment_crosses(0.0, -10.0, 0.0, 10.0) is True

    def test_parallel_segment_does_not_cross(self):
        w = ForceWall(0.0, 0.0, 0.0)
        # Parallel above the wall — both endpoints same side
        assert w.segment_crosses(-50.0, 5.0, 50.0, 5.0) is False

    def test_segment_past_wall_end_does_not_cross(self):
        w = ForceWall(0.0, 0.0, 0.0)  # wall x in [-HALF, HALF], y=0
        # Vertical segment way past the wall's right end
        assert w.segment_crosses(HALF + 100, -10.0, HALF + 100, 10.0) is False

    def test_segment_with_endpoint_on_wall_does_not_count_as_cross(self):
        # Touching is not crossing — guard against floating-point flake
        w = ForceWall(0.0, 0.0, 0.0)
        assert w.segment_crosses(0.0, 0.0, 0.0, 10.0) is False
