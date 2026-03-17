"""Tests for sprites/projectile.py — Projectile movement and Weapon cooldown."""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import arcade
import pytest

from sprites.projectile import Projectile, Weapon


@pytest.fixture
def proj(dummy_texture):
    """A projectile heading north (0°) at 100 px/s with 500 px range."""
    return Projectile(
        texture=dummy_texture,
        x=100.0, y=100.0,
        heading=0.0, speed=100.0,
        max_dist=500.0, scale=1.0,
        mines_rock=False, damage=25.0,
    )


@pytest.fixture
def weapon(dummy_texture):
    """A weapon with 0.3s cooldown."""
    snd = MagicMock(spec=arcade.Sound)
    return Weapon(
        name="Test Laser",
        texture=dummy_texture,
        sound=snd,
        cooldown=0.30,
        damage=25.0,
        projectile_speed=900.0,
        max_range=1200.0,
        proj_scale=1.0,
        mines_rock=False,
    )


class TestProjectileMovement:
    def test_moves_north(self, proj):
        """Heading 0° → +Y direction."""
        old_y = proj.center_y
        proj.update_projectile(1.0)
        assert proj.center_y > old_y

    def test_moves_east(self, dummy_texture):
        """Heading 90° → +X direction."""
        p = Projectile(dummy_texture, 100, 100, 90.0, 100.0, 500.0)
        old_x = p.center_x
        p.update_projectile(1.0)
        assert p.center_x > old_x

    def test_distance_tracking(self, proj):
        proj.update_projectile(1.0)
        # Should have travelled ~100 px
        assert abs(proj._dist_travelled - 100.0) < 1.0

    def test_speed_precomputed(self, proj):
        assert abs(proj._speed - 100.0) < 0.01

    def test_damage_attribute(self, proj):
        assert proj.damage == 25.0

    def test_mines_rock_flag(self, proj):
        assert proj.mines_rock is False


class TestWeaponFire:
    def test_fire_off_cooldown(self, weapon):
        result = weapon.fire(100.0, 100.0, 0.0)
        assert result is not None
        assert isinstance(result, Projectile)

    def test_fire_on_cooldown(self, weapon):
        weapon.fire(100.0, 100.0, 0.0)
        result = weapon.fire(100.0, 100.0, 0.0)
        assert result is None

    def test_cooldown_resets_after_wait(self, weapon):
        weapon.fire(100.0, 100.0, 0.0)
        weapon.update(0.5)  # wait past cooldown
        result = weapon.fire(100.0, 100.0, 0.0)
        assert result is not None

    def test_cooldown_ticks_down(self, weapon):
        weapon._timer = 0.30
        weapon.update(0.10)
        assert abs(weapon._timer - 0.20) < 0.001

    def test_projectile_carries_damage(self, weapon):
        proj = weapon.fire(100.0, 100.0, 0.0)
        assert proj.damage == 25.0
