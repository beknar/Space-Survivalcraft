"""Tests for BlueprintPickup — spinning animation, module_type, item_type."""
from __future__ import annotations

import pytest

from constants import BLUEPRINT_SPIN_SPEED
from sprites.pickup import BlueprintPickup


@pytest.fixture
def bp(dummy_texture):
    return BlueprintPickup(dummy_texture, 500.0, 500.0, "armor_plate")


class TestBlueprintInit:
    def test_module_type(self, bp):
        assert bp.module_type == "armor_plate"

    def test_item_type_prefix(self, bp):
        assert bp.item_type == "bp_armor_plate"

    def test_amount_is_one(self, bp):
        assert bp.amount == 1

    def test_different_module(self, dummy_texture):
        p = BlueprintPickup(dummy_texture, 0, 0, "broadside")
        assert p.module_type == "broadside"
        assert p.item_type == "bp_broadside"


class TestBlueprintSpin:
    def test_spins_on_update(self, bp):
        initial_angle = bp.angle
        bp.update_pickup(1.0, 9999, 9999)
        expected = (initial_angle + BLUEPRINT_SPIN_SPEED * 1.0) % 360
        assert abs(bp.angle - expected) < 0.1

    def test_spin_accumulates(self, bp):
        for _ in range(10):
            bp.update_pickup(0.1, 9999, 9999)
        expected = (BLUEPRINT_SPIN_SPEED * 1.0) % 360
        assert abs(bp.angle - expected) < 1.0

    def test_still_collectible(self, bp):
        bp._flying = True
        result = bp.update_pickup(1.0, 500.0, 500.0, ship_radius=0.0)
        assert result is True


class TestBlueprintLifetime:
    def test_expires_with_lifetime(self, dummy_texture):
        p = BlueprintPickup(dummy_texture, 500, 500, "engine_booster", lifetime=3.0)
        p.update_pickup(4.0, 9999, 9999)
        assert p._age >= p._lifetime
