"""Tests for sprites.gas_area.GasArea.

Covers contains_point, rotation tick, immobile no-drift, mobile drift,
and bouncing off world edges.  Uses a tiny PIL-backed texture instead
of generating the real gas cloud (the procedural gen is slow and not
relevant to behaviour tests).
"""
from __future__ import annotations

import math

import arcade
import pytest
from PIL import Image as PILImage

from sprites.gas_area import GasArea


@pytest.fixture
def tiny_tex() -> arcade.Texture:
    img = PILImage.new("RGBA", (32, 32), (100, 200, 80, 80))
    return arcade.Texture(img)


# ── contains_point ─────────────────────────────────────────────────────────

class TestContainsPoint:
    def test_centre_is_inside(self, tiny_tex):
        g = GasArea(tiny_tex, 1000.0, 1000.0, size=200)
        assert g.contains_point(1000.0, 1000.0) is True

    def test_point_on_radius_edge_excluded(self, tiny_tex):
        # contains_point uses strict `<`, not `<=`
        g = GasArea(tiny_tex, 0.0, 0.0, size=200)
        assert g.contains_point(100.0, 0.0) is False

    def test_point_well_outside(self, tiny_tex):
        g = GasArea(tiny_tex, 0.0, 0.0, size=200)
        assert g.contains_point(500.0, 500.0) is False

    def test_radius_matches_half_size(self, tiny_tex):
        g = GasArea(tiny_tex, 0.0, 0.0, size=300)
        assert g.radius == pytest.approx(150.0)


# ── Rotation ───────────────────────────────────────────────────────────────

class TestRotation:
    def test_angle_advances_each_tick(self, tiny_tex):
        g = GasArea(tiny_tex, 0.0, 0.0, size=200, mobile=False)
        g._rot_speed = 30.0  # deterministic
        g.angle = 0.0
        g.update_gas(1.0)
        assert g.angle == pytest.approx(30.0)

    def test_angle_wraps_at_360(self, tiny_tex):
        g = GasArea(tiny_tex, 0.0, 0.0, size=200, mobile=False)
        g._rot_speed = 100.0
        g.angle = 350.0
        g.update_gas(1.0)
        assert g.angle == pytest.approx(90.0)


# ── Mobility ───────────────────────────────────────────────────────────────

class TestImmobile:
    def test_position_does_not_change(self, tiny_tex):
        g = GasArea(tiny_tex, 1000.0, 1000.0, size=200, mobile=False)
        for _ in range(10):
            g.update_gas(0.1)
        assert g.center_x == 1000.0
        assert g.center_y == 1000.0

    def test_drift_speed_is_zero(self, tiny_tex):
        g = GasArea(tiny_tex, 0.0, 0.0, mobile=False)
        assert g._drift_speed == 0.0


class TestMobileDrift:
    def test_drift_speed_is_60(self, tiny_tex):
        g = GasArea(tiny_tex, 1000.0, 1000.0, size=200, mobile=True)
        assert g._drift_speed == pytest.approx(60.0)

    def test_position_changes_when_mobile(self, tiny_tex):
        g = GasArea(tiny_tex, 3000.0, 3000.0, size=200, mobile=True,
                    world_w=6400, world_h=6400)
        g._brownian_timer = 999.0  # don't randomise mid-test
        g._drift_x = 60.0
        g._drift_y = 0.0
        g.update_gas(1.0)
        assert g.center_x == pytest.approx(3060.0)
        assert g.center_y == pytest.approx(3000.0)

    def test_brownian_resets_after_timer_expires(self, tiny_tex):
        g = GasArea(tiny_tex, 3000.0, 3000.0, size=200, mobile=True)
        g._brownian_timer = 0.05
        g.update_gas(0.1)  # drives timer to <= 0
        # New random direction; speed magnitude preserved
        speed = math.hypot(g._drift_x, g._drift_y)
        assert speed == pytest.approx(60.0, rel=1e-3)
        assert g._brownian_timer > 0.0


# ── World-edge bouncing ────────────────────────────────────────────────────

class TestEdgeBouncing:
    def test_left_edge_bounces_to_positive_x(self, tiny_tex):
        g = GasArea(tiny_tex, 50.0, 3000.0, size=200, mobile=True,
                    world_w=6400, world_h=6400)
        g._brownian_timer = 999.0
        g._drift_x = -120.0
        g._drift_y = 0.0
        g.update_gas(1.0)
        assert g.center_x == pytest.approx(g.radius)
        assert g._drift_x > 0  # bounced

    def test_right_edge_bounces_to_negative_x(self, tiny_tex):
        g = GasArea(tiny_tex, 6300.0, 3000.0, size=200, mobile=True,
                    world_w=6400, world_h=6400)
        g._brownian_timer = 999.0
        g._drift_x = 200.0
        g._drift_y = 0.0
        g.update_gas(1.0)
        assert g.center_x == pytest.approx(6400 - g.radius)
        assert g._drift_x < 0

    def test_bottom_edge_bounces_to_positive_y(self, tiny_tex):
        g = GasArea(tiny_tex, 3000.0, 50.0, size=200, mobile=True,
                    world_w=6400, world_h=6400)
        g._brownian_timer = 999.0
        g._drift_x = 0.0
        g._drift_y = -120.0
        g.update_gas(1.0)
        assert g.center_y == pytest.approx(g.radius)
        assert g._drift_y > 0

    def test_top_edge_bounces_to_negative_y(self, tiny_tex):
        g = GasArea(tiny_tex, 3000.0, 6300.0, size=200, mobile=True,
                    world_w=6400, world_h=6400)
        g._brownian_timer = 999.0
        g._drift_x = 0.0
        g._drift_y = 200.0
        g.update_gas(1.0)
        assert g.center_y == pytest.approx(6400 - g.radius)
        assert g._drift_y < 0
