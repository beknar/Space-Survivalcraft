"""Tests for sprites/alien.py — SmallAlienShip AI states and combat."""
from __future__ import annotations

import pytest
import arcade

from constants import (
    ALIEN_HP, ALIEN_DETECT_DIST, ALIEN_FIRE_COOLDOWN,
    ALIEN_BUMP_FLASH, ALIEN_VEL_DAMPING,
    ALIEN_STUCK_TIME, ALIEN_STUCK_DIST,
)
from sprites.alien import SmallAlienShip


@pytest.fixture
def alien(dummy_texture):
    """Create an alien at (1000, 1000) using dummy textures."""
    return SmallAlienShip(dummy_texture, dummy_texture, 1000.0, 1000.0)


@pytest.fixture
def empty_sprite_lists():
    """Return empty SpriteLists for asteroid_list and alien_list."""
    return arcade.SpriteList(), arcade.SpriteList()


class TestAlienInit:
    def test_initial_hp(self, alien):
        assert alien.hp == ALIEN_HP

    def test_initial_state_patrol(self, alien):
        assert alien._state == SmallAlienShip._STATE_PATROL

    def test_initial_velocity_zero(self, alien):
        assert alien.vel_x == 0.0
        assert alien.vel_y == 0.0


class TestAlienStateTransitions:
    def test_transitions_to_pursue(self, alien, empty_sprite_lists):
        """Player within detection range triggers PURSUE."""
        ast_list, al_list = empty_sprite_lists
        # Place player within detect dist
        alien.update_alien(0.1, alien.center_x + 100, alien.center_y, ast_list, al_list)
        assert alien._state == SmallAlienShip._STATE_PURSUE

    def test_stays_patrol_when_far(self, alien, empty_sprite_lists):
        """Player far away keeps alien in PATROL."""
        ast_list, al_list = empty_sprite_lists
        alien.update_alien(0.1, alien.center_x + 5000, alien.center_y, ast_list, al_list)
        assert alien._state == SmallAlienShip._STATE_PATROL

    def test_returns_to_patrol_beyond_leash(self, alien, empty_sprite_lists):
        """Player beyond 3× detection range returns alien to PATROL."""
        ast_list, al_list = empty_sprite_lists
        # Force PURSUE state first
        alien._state = SmallAlienShip._STATE_PURSUE
        leash = ALIEN_DETECT_DIST * 3.0 + 100
        alien.update_alien(0.1, alien.center_x + leash, alien.center_y, ast_list, al_list)
        assert alien._state == SmallAlienShip._STATE_PATROL

    def test_fire_cd_resets_on_detection(self, alien, empty_sprite_lists):
        """Fire cooldown resets to 0 on first detection for immediate shot."""
        ast_list, al_list = empty_sprite_lists
        alien._fire_cd = ALIEN_FIRE_COOLDOWN  # set high
        alien.update_alien(0.1, alien.center_x + 100, alien.center_y, ast_list, al_list)
        # Should have fired (cd was reset to 0, then set to ALIEN_FIRE_COOLDOWN)
        assert alien._fire_cd == ALIEN_FIRE_COOLDOWN


class TestAlienDamage:
    def test_take_damage_reduces_hp(self, alien):
        alien.take_damage(25)
        assert alien.hp == ALIEN_HP - 25

    def test_take_damage_sets_hit_timer(self, alien):
        alien.take_damage(10)
        assert alien._hit_timer == 0.15


class TestAlienCollisionBump:
    def test_collision_bump_sets_timer(self, alien):
        alien.collision_bump()
        assert alien._bump_timer == ALIEN_BUMP_FLASH


class TestAlienVelocityDamping:
    def test_velocity_decays(self, alien, empty_sprite_lists):
        ast_list, al_list = empty_sprite_lists
        alien.vel_x = 100.0
        alien.vel_y = 0.0
        # Place player far away so state stays PATROL (no steering interference)
        alien.update_alien(1.0 / 60.0, 9999, 9999, ast_list, al_list)
        assert alien.vel_x < 100.0

    def test_small_velocity_zeroed(self, alien, empty_sprite_lists):
        ast_list, al_list = empty_sprite_lists
        alien.vel_x = 0.3
        alien.vel_y = 0.0
        alien.update_alien(1.0 / 60.0, 9999, 9999, ast_list, al_list)
        assert alien.vel_x == 0.0


class TestAlienFiring:
    def test_fires_projectile_in_pursue(self, alien, empty_sprite_lists):
        ast_list, al_list = empty_sprite_lists
        # Force pursue with cooldown ready
        alien._state = SmallAlienShip._STATE_PURSUE
        alien._fire_cd = 0.0
        proj = alien.update_alien(0.01, alien.center_x + 100, alien.center_y, ast_list, al_list)
        assert proj is not None

    def test_no_fire_in_patrol(self, alien, empty_sprite_lists):
        ast_list, al_list = empty_sprite_lists
        alien._state = SmallAlienShip._STATE_PATROL
        alien._fire_cd = 0.0
        proj = alien.update_alien(0.01, alien.center_x + 5000, alien.center_y, ast_list, al_list)
        assert proj is None


class TestAlienStuckDetection:
    def test_stuck_fields_initialised(self, alien):
        assert alien._stuck_timer == 0.0
        assert alien._stuck_check_x == alien.center_x
        assert alien._stuck_check_y == alien.center_y

    def test_stuck_constants(self):
        assert ALIEN_STUCK_TIME == 2.0
        assert ALIEN_STUCK_DIST == 10.0

    def test_stuck_timer_accumulates(self, alien, empty_sprite_lists):
        ast_list, al_list = empty_sprite_lists
        alien.update_alien(0.5, 9999, 9999, ast_list, al_list)
        assert alien._stuck_timer > 0.0

    def test_stuck_resets_after_threshold(self, alien, empty_sprite_lists):
        ast_list, al_list = empty_sprite_lists
        # Tick past the stuck timer threshold
        alien._stuck_timer = ALIEN_STUCK_TIME - 0.01
        alien.update_alien(0.02, 9999, 9999, ast_list, al_list)
        assert alien._stuck_timer < 0.1  # reset happened
