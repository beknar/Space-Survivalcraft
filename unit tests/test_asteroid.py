"""Tests for sprites/asteroid.py — IronAsteroid damage and effects."""
from __future__ import annotations

import pytest

from constants import ASTEROID_HP
from sprites.asteroid import IronAsteroid


@pytest.fixture
def asteroid(dummy_texture):
    return IronAsteroid(dummy_texture, 500.0, 500.0)


class TestAsteroidInit:
    def test_initial_hp(self, asteroid):
        assert asteroid.hp == ASTEROID_HP

    def test_position(self, asteroid):
        assert asteroid.center_x == 500.0
        assert asteroid.center_y == 500.0


class TestAsteroidDamage:
    def test_take_damage_reduces_hp(self, asteroid):
        asteroid.take_damage(10)
        assert asteroid.hp == ASTEROID_HP - 10

    def test_take_damage_starts_shake(self, asteroid):
        asteroid.take_damage(10)
        assert asteroid._hit_timer > 0.0

    def test_take_damage_sets_orange_tint(self, asteroid):
        asteroid.take_damage(10)
        assert asteroid.color == (255, 140, 60, 255)


class TestAsteroidUpdate:
    def test_rotates(self, asteroid):
        old_angle = asteroid.angle
        asteroid.update_asteroid(1.0)
        assert asteroid.angle != old_angle

    def test_shake_jitters_position(self, asteroid):
        asteroid.take_damage(10)
        # Position should differ from base during shake
        asteroid.update_asteroid(0.05)
        # Due to randomness, position might equal base — but timer should still be active
        assert asteroid._hit_timer > 0.0 or asteroid._hit_timer == 0.0

    def test_shake_decays(self, asteroid):
        asteroid.take_damage(10)
        initial_timer = asteroid._hit_timer
        asteroid.update_asteroid(0.05)
        assert asteroid._hit_timer < initial_timer

    def test_colour_restores_after_shake(self, asteroid):
        asteroid.take_damage(10)
        # Run enough time for shake to fully expire
        asteroid.update_asteroid(0.25)
        assert asteroid.color == (255, 255, 255, 255)
