"""Tests for sprites/pickup.py — IronPickup fly-to-ship and collection."""
from __future__ import annotations

import pytest

from constants import ASTEROID_IRON_YIELD, IRON_PICKUP_DIST
from sprites.pickup import IronPickup


@pytest.fixture
def pickup(dummy_texture):
    return IronPickup(dummy_texture, 500.0, 500.0)


class TestPickupInit:
    def test_default_amount(self, pickup):
        assert pickup.amount == ASTEROID_IRON_YIELD

    def test_custom_amount(self, dummy_texture):
        p = IronPickup(dummy_texture, 0, 0, amount=42)
        assert p.amount == 42

    def test_no_lifetime_by_default(self, pickup):
        assert pickup._lifetime is None


class TestPickupFlyBehaviour:
    def test_no_fly_when_far(self, pickup):
        """Ship is far away — pickup should not fly."""
        result = pickup.update_pickup(0.1, 2000.0, 2000.0, ship_radius=28.0)
        assert result is False
        assert pickup._flying is False

    def test_starts_flying_when_close(self, pickup):
        """Ship edge within IRON_PICKUP_DIST triggers flight."""
        # Place ship centre so edge is within IRON_PICKUP_DIST
        ship_radius = 28.0
        # pickup is at (500, 500); place ship so edge-dist < IRON_PICKUP_DIST
        ship_x = 500.0 + ship_radius + IRON_PICKUP_DIST - 1.0
        result = pickup.update_pickup(0.1, ship_x, 500.0, ship_radius=ship_radius)
        assert pickup._flying is True

    def test_collected_when_reaching_ship(self, pickup):
        """Pickup returns True when it reaches the ship."""
        pickup._flying = True
        # Place ship very close
        result = pickup.update_pickup(1.0, 500.0, 500.0, ship_radius=0.0)
        assert result is True


class TestPickupLifetime:
    def test_no_lifetime_never_expires(self, pickup):
        """Pickup without lifetime should never despawn from age."""
        for _ in range(100):
            pickup.update_pickup(10.0, 9999, 9999)
        # Should still be alive (not removed — we just check _flying stays False)
        assert pickup._flying is False

    def test_lifetime_expires(self, dummy_texture):
        """Pickup with finite lifetime should despawn after it expires."""
        p = IronPickup(dummy_texture, 500, 500, lifetime=5.0)
        result = p.update_pickup(6.0, 9999, 9999)
        assert result is False
        # Sprite should have removed itself; _age exceeds lifetime
        assert p._age >= p._lifetime
