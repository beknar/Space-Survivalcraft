"""Tests for sprites/player.py — PlayerShip physics and properties."""
from __future__ import annotations

import math
import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    ROT_SPEED, THRUST, BRAKE, MAX_SPD, DAMPING,
    PLAYER_MAX_HP, PLAYER_MAX_SHIELD,
    NOSE_OFFSET, GUN_LATERAL_OFFSET,
)
from sprites.player import PlayerShip


@pytest.fixture
def ship(dummy_texture):
    """Create a PlayerShip in legacy mode using a dummy texture."""
    # Patch the legacy loader to use our dummy texture instead of loading a file
    s = PlayerShip.__new__(PlayerShip)
    # Manually initialise the Sprite base via arcade.Sprite.__init__
    import arcade
    arcade.Sprite.__init__(s, path_or_texture=dummy_texture, scale=1.5)
    s._use_legacy = True
    s._frames = [[dummy_texture] * PlayerShip._LEGACY_COLS]
    s._rot_speed = ROT_SPEED
    s._thrust = THRUST
    s._brake = BRAKE
    s._max_spd = MAX_SPD
    s._damping = DAMPING
    s.hp = PLAYER_MAX_HP
    s.max_hp = PLAYER_MAX_HP
    s.shields = PLAYER_MAX_SHIELD
    s.max_shields = PLAYER_MAX_SHIELD
    s._shield_regen = 0.5
    s._base_max_hp = PLAYER_MAX_HP
    s._base_max_spd = MAX_SPD
    s._base_max_shields = PLAYER_MAX_SHIELD
    s._base_shield_regen = 0.5
    s.shield_absorb = 0
    s._shield_acc = 0.0
    s._collision_cd = 0.0
    s.guns = 1
    s.center_x = WORLD_WIDTH / 2
    s.center_y = WORLD_HEIGHT / 2
    s.vel_x = 0.0
    s.vel_y = 0.0
    s.heading = 0.0
    s._intensity = 0.0
    s._anim_timer = 0.0
    s._anim_col = 0
    return s


class TestPlayerDefaults:
    def test_default_hp(self, ship):
        assert ship.hp == 100
        assert ship.max_hp == 100

    def test_default_shields(self, ship):
        assert ship.shields == 100
        assert ship.max_shields == 100

    def test_default_guns(self, ship):
        assert ship.guns == 1

    def test_start_position(self, ship):
        assert ship.center_x == WORLD_WIDTH / 2
        assert ship.center_y == WORLD_HEIGHT / 2

    def test_initial_velocity_zero(self, ship):
        assert ship.vel_x == 0.0
        assert ship.vel_y == 0.0

    def test_initial_heading_zero(self, ship):
        assert ship.heading == 0.0


class TestRotation:
    def test_rotate_left(self, ship):
        ship.apply_input(1.0, rotate_left=True, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=False)
        # Heading decreases (wraps via modulo 360)
        expected = (0.0 - ROT_SPEED * 1.0) % 360
        assert abs(ship.heading - expected) < 0.01

    def test_rotate_right(self, ship):
        ship.apply_input(1.0, rotate_left=False, rotate_right=True,
                         thrust_fwd=False, thrust_bwd=False)
        expected = (ROT_SPEED * 1.0) % 360
        assert abs(ship.heading - expected) < 0.01

    def test_rotate_wraps(self, ship):
        """Rotating left past 0 should wrap to near 360."""
        ship.heading = 10.0
        ship.apply_input(1.0, rotate_left=True, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=False)
        assert ship.heading >= 0.0
        assert ship.heading < 360.0


class TestThrust:
    def test_thrust_forward_increases_velocity(self, ship):
        ship.heading = 0.0  # nose points +Y
        ship.apply_input(1.0, rotate_left=False, rotate_right=False,
                         thrust_fwd=True, thrust_bwd=False)
        # sin(0)=0, cos(0)=1 → vel_y should increase
        assert ship.vel_y > 0.0

    def test_brake_decreases_velocity(self, ship):
        ship.heading = 0.0
        ship.vel_y = 200.0
        ship.apply_input(1.0, rotate_left=False, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=True)
        # Braking should reduce vel_y
        assert ship.vel_y < 200.0

    def test_thrust_at_angle(self, ship):
        ship.heading = 90.0  # nose points +X
        ship.apply_input(0.1, rotate_left=False, rotate_right=False,
                         thrust_fwd=True, thrust_bwd=False)
        # sin(90)=1 → vel_x should increase; cos(90)≈0 → vel_y stays ~0
        assert ship.vel_x > 0.0
        assert abs(ship.vel_y) < 1.0


class TestSpeedCap:
    def test_speed_capped_at_max(self, ship):
        ship.vel_x = MAX_SPD * 2
        ship.vel_y = 0.0
        ship.apply_input(0.001, rotate_left=False, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=False)
        speed = math.hypot(ship.vel_x, ship.vel_y)
        # After capping + damping, should be at or below max
        assert speed <= MAX_SPD + 0.01


class TestDamping:
    def test_velocity_decays(self, ship):
        ship.vel_x = 100.0
        ship.vel_y = 0.0
        ship.apply_input(1.0, rotate_left=False, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=False)
        assert ship.vel_x < 100.0


class TestPositionClamping:
    def test_clamps_to_world_left(self, ship):
        ship.center_x = -100
        ship.vel_x = 0.0
        ship.apply_input(0.01, rotate_left=False, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=False)
        assert ship.center_x >= ship.width / 2

    def test_clamps_to_world_right(self, ship):
        ship.center_x = WORLD_WIDTH + 100
        ship.vel_x = 0.0
        ship.apply_input(0.01, rotate_left=False, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=False)
        assert ship.center_x <= WORLD_WIDTH - ship.width / 2


class TestNosePosition:
    def test_nose_at_heading_zero(self, ship):
        ship.heading = 0.0
        ship.center_x = 100.0
        ship.center_y = 100.0
        # nose should be NOSE_OFFSET above centre
        assert abs(ship.nose_x - 100.0) < 0.01
        assert abs(ship.nose_y - (100.0 + NOSE_OFFSET)) < 0.01

    def test_nose_at_heading_90(self, ship):
        ship.heading = 90.0
        ship.center_x = 100.0
        ship.center_y = 100.0
        assert abs(ship.nose_x - (100.0 + NOSE_OFFSET)) < 0.01
        assert abs(ship.nose_y - 100.0) < 0.5


class TestGunSpawnPoints:
    def test_single_gun_returns_one_point(self, ship):
        ship.guns = 1
        pts = ship.gun_spawn_points()
        assert len(pts) == 1

    def test_dual_gun_returns_two_points(self, ship):
        ship.guns = 2
        pts = ship.gun_spawn_points()
        assert len(pts) == 2

    def test_dual_gun_points_symmetric(self, ship):
        ship.guns = 2
        ship.heading = 0.0
        ship.center_x = 500.0
        ship.center_y = 500.0
        pts = ship.gun_spawn_points()
        # Both should have the same Y (forward), different X (lateral offset)
        assert abs(pts[0][1] - pts[1][1]) < 0.01
        assert abs(pts[0][0] - pts[1][0]) > 0.01


class TestThrustIntensity:
    def test_ramps_up(self, ship):
        assert ship.thrust_intensity == 0.0
        ship.apply_input(1.0, rotate_left=False, rotate_right=False,
                         thrust_fwd=True, thrust_bwd=False)
        assert ship.thrust_intensity > 0.0

    def test_ramps_down(self, ship):
        ship._intensity = 1.0
        ship.apply_input(1.0, rotate_left=False, rotate_right=False,
                         thrust_fwd=False, thrust_bwd=False)
        assert ship.thrust_intensity < 1.0

    def test_capped_at_one(self, ship):
        ship._intensity = 0.9
        ship.apply_input(10.0, rotate_left=False, rotate_right=False,
                         thrust_fwd=True, thrust_bwd=False)
        assert ship.thrust_intensity <= 1.0
