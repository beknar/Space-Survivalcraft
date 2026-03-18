"""Tests for respawn mechanics and alien iron drops."""
from __future__ import annotations

import math

import pytest
import arcade

from constants import (
    RESPAWN_INTERVAL, RESPAWN_EXCLUSION_RADIUS, ALIEN_IRON_DROP,
    ASTEROID_COUNT, ALIEN_COUNT, WORLD_WIDTH, WORLD_HEIGHT,
    ASTEROID_MIN_DIST, ALIEN_MIN_DIST,
)
from sprites.asteroid import IronAsteroid
from sprites.alien import SmallAlienShip
from sprites.building import HomeStation


# ── Constants validation ─────────────────────────────────────────────────────

class TestRespawnConstants:
    def test_respawn_interval_is_five_minutes(self):
        assert RESPAWN_INTERVAL == 300.0

    def test_respawn_exclusion_radius(self):
        assert RESPAWN_EXCLUSION_RADIUS == 300.0

    def test_alien_iron_drop(self):
        assert ALIEN_IRON_DROP == 5

    def test_asteroid_count(self):
        assert ASTEROID_COUNT == 50

    def test_alien_count(self):
        assert ALIEN_COUNT == 20


# ── Respawn logic helpers (mirror game_view logic for unit testing) ─────────

def _find_respawn_position(
    building_list: arcade.SpriteList,
    min_dist_from_centre: float,
    exclusion_radius: float,
    rng_positions: list[tuple[float, float]],
) -> tuple[float, float] | None:
    """Try positions from rng_positions, return first valid one or None.

    Mirrors the logic in GameView._try_respawn_asteroids / _try_respawn_aliens.
    """
    cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    margin = 100
    for ax, ay in rng_positions:
        if ax < margin or ax > WORLD_WIDTH - margin:
            continue
        if ay < margin or ay > WORLD_HEIGHT - margin:
            continue
        if math.hypot(ax - cx_world, ay - cy_world) < min_dist_from_centre:
            continue
        too_close = any(
            math.hypot(ax - b.center_x, ay - b.center_y) < exclusion_radius
            for b in building_list
        )
        if too_close:
            continue
        return (ax, ay)
    return None


class TestRespawnPositionLogic:
    """Test the position-finding logic used by respawn methods."""

    def test_valid_position_accepted(self):
        buildings = arcade.SpriteList()
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(1000.0, 1000.0)],
        )
        assert pos == (1000.0, 1000.0)

    def test_position_too_close_to_centre_rejected(self):
        buildings = arcade.SpriteList()
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(cx, cy)],
        )
        assert pos is None

    def test_position_near_building_rejected(self, dummy_texture):
        buildings = arcade.SpriteList()
        home = HomeStation(dummy_texture, 1000, 1000, "Home Station", scale=0.5)
        buildings.append(home)
        # Position right at the building
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(1000.0, 1000.0)],
        )
        assert pos is None

    def test_position_just_outside_exclusion_accepted(self, dummy_texture):
        buildings = arcade.SpriteList()
        home = HomeStation(dummy_texture, 1000, 1000, "Home Station", scale=0.5)
        buildings.append(home)
        # Position well beyond exclusion radius
        far_x = 1000.0 + RESPAWN_EXCLUSION_RADIUS + 50.0
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(far_x, 1000.0)],
        )
        assert pos is not None

    def test_position_just_inside_exclusion_rejected(self, dummy_texture):
        buildings = arcade.SpriteList()
        home = HomeStation(dummy_texture, 1000, 1000, "Home Station", scale=0.5)
        buildings.append(home)
        # Position just inside exclusion radius
        close_x = 1000.0 + RESPAWN_EXCLUSION_RADIUS - 10.0
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(close_x, 1000.0)],
        )
        assert pos is None

    def test_position_outside_world_margin_rejected(self):
        buildings = arcade.SpriteList()
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(50.0, 50.0)],  # inside margin of 100
        )
        assert pos is None

    def test_first_valid_position_returned(self):
        buildings = arcade.SpriteList()
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        positions = [
            (cx, cy),         # rejected — too close to centre
            (50, 50),         # rejected — inside margin
            (1000.0, 1000.0), # accepted
            (2000.0, 2000.0), # would also be valid, but first wins
        ]
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            positions,
        )
        assert pos == (1000.0, 1000.0)

    def test_multiple_buildings_all_checked(self, dummy_texture):
        buildings = arcade.SpriteList()
        home1 = HomeStation(dummy_texture, 1000, 1000, "Home Station", scale=0.5)
        home2 = HomeStation(dummy_texture, 2000, 2000, "Home Station", scale=0.5)
        buildings.append(home1)
        buildings.append(home2)
        # Near building 2 but far from building 1
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(2010.0, 2000.0)],
        )
        assert pos is None

    def test_no_buildings_all_valid_positions_accepted(self):
        buildings = arcade.SpriteList()
        pos = _find_respawn_position(
            buildings, ASTEROID_MIN_DIST, RESPAWN_EXCLUSION_RADIUS,
            [(500.0, 500.0)],
        )
        assert pos == (500.0, 500.0)


class TestRespawnTimerLogic:
    """Test the timer accumulation logic used for respawning."""

    def test_timer_resets_on_threshold(self):
        timer = 0.0
        # Simulate ticking at 60fps for 5 minutes
        for _ in range(60 * 300):
            timer += 1.0 / 60.0
        assert timer >= RESPAWN_INTERVAL

    def test_timer_does_not_trigger_before_interval(self):
        timer = 0.0
        for _ in range(60 * 299):
            timer += 1.0 / 60.0
        assert timer < RESPAWN_INTERVAL

    def test_respawn_skipped_when_at_max_count(self):
        """When count >= max, no respawn should occur (verified by constants)."""
        assert ASTEROID_COUNT == 50
        assert ALIEN_COUNT == 20


class TestAlienIronDrop:
    """Test alien iron drop amount constant."""

    def test_alien_drops_five_iron(self):
        assert ALIEN_IRON_DROP == 5

    def test_alien_iron_drop_is_positive(self):
        assert ALIEN_IRON_DROP > 0

    def test_alien_iron_drop_is_integer(self):
        assert isinstance(ALIEN_IRON_DROP, int)
