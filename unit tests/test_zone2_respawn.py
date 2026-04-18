"""Tests for the Zone 2 asteroid respawn pass.

Nebula asteroids regenerate on the same ``RESPAWN_INTERVAL`` cadence
as Zone 1 iron: one sprite per type per minute, wrapped in the alien
respawn hook that already runs every 60 s in
``zones.zone2.Zone2.update``.
"""
from __future__ import annotations

import math

import arcade
import pytest

from constants import (
    ASTEROID_COUNT, DOUBLE_IRON_COUNT, COPPER_ASTEROID_COUNT,
    WANDERING_COUNT, RESPAWN_EXCLUSION_RADIUS,
)
from types import SimpleNamespace

from sprites.asteroid import IronAsteroid
from zones.zone2 import Zone2
from zones.zone2_world import try_respawn, _find_respawn_pos


def _fake_building(x: float, y: float):
    """_find_respawn_pos only reads center_x/center_y, so a namespace
    is enough to act as a stand-in for a real StationModule."""
    return SimpleNamespace(center_x=x, center_y=y)


@pytest.fixture
def empty_zone2(dummy_texture) -> Zone2:
    """Zone 2 with empty sprite lists + dummy textures wired up."""
    zone = Zone2()
    zone._iron_tex = dummy_texture
    zone._copper_tex = dummy_texture
    zone._copper_pickup_tex = dummy_texture
    zone._wanderer_tex = dummy_texture
    zone._alien_laser_tex = dummy_texture
    zone._alien_textures = {
        "shielded": dummy_texture, "fast": dummy_texture,
        "gunner": dummy_texture, "rammer": dummy_texture,
    }
    zone._populated = True
    return zone


class TestAsteroidRespawnAtCap:
    def test_iron_at_cap_no_spawn(self, empty_zone2, stub_gv, dummy_texture):
        for _ in range(ASTEROID_COUNT):
            empty_zone2._iron_asteroids.append(
                IronAsteroid(dummy_texture, 500.0, 500.0))
        try_respawn(empty_zone2, stub_gv)
        assert len(empty_zone2._iron_asteroids) == ASTEROID_COUNT

    def test_all_types_at_cap_no_spawn(
            self, empty_zone2, stub_gv, dummy_texture):
        from sprites.copper_asteroid import CopperAsteroid
        from sprites.wandering_asteroid import WanderingAsteroid
        for _ in range(ASTEROID_COUNT):
            empty_zone2._iron_asteroids.append(
                IronAsteroid(dummy_texture, 500.0, 500.0))
        for _ in range(DOUBLE_IRON_COUNT):
            empty_zone2._double_iron.append(
                IronAsteroid(dummy_texture, 500.0, 500.0))
        for _ in range(COPPER_ASTEROID_COUNT):
            empty_zone2._copper_asteroids.append(
                CopperAsteroid(dummy_texture, 500.0, 500.0))
        for _ in range(WANDERING_COUNT):
            empty_zone2._wanderers.append(WanderingAsteroid(
                dummy_texture, 500.0, 500.0,
                empty_zone2.world_width, empty_zone2.world_height))

        try_respawn(empty_zone2, stub_gv)
        assert len(empty_zone2._iron_asteroids) == ASTEROID_COUNT
        assert len(empty_zone2._double_iron) == DOUBLE_IRON_COUNT
        assert len(empty_zone2._copper_asteroids) == COPPER_ASTEROID_COUNT
        assert len(empty_zone2._wanderers) == WANDERING_COUNT


class TestAsteroidRespawnBelowCap:
    def test_iron_below_cap_spawns_one(
            self, empty_zone2, stub_gv, dummy_texture):
        try_respawn(empty_zone2, stub_gv)
        assert len(empty_zone2._iron_asteroids) == 1

    def test_all_types_below_cap_each_spawn_one(
            self, empty_zone2, stub_gv, dummy_texture):
        try_respawn(empty_zone2, stub_gv)
        assert len(empty_zone2._iron_asteroids) == 1
        assert len(empty_zone2._double_iron) == 1
        assert len(empty_zone2._copper_asteroids) == 1
        assert len(empty_zone2._wanderers) == 1

    def test_double_iron_respawn_has_doubled_hp(
            self, empty_zone2, stub_gv, dummy_texture):
        from constants import DOUBLE_IRON_HP, DOUBLE_IRON_SCALE
        try_respawn(empty_zone2, stub_gv)
        a = empty_zone2._double_iron[0]
        assert a.hp == DOUBLE_IRON_HP
        # arcade.Sprite.scale stores the assigned value as (sx, sy)
        assert a.scale[0] == DOUBLE_IRON_SCALE

    def test_respawn_invalidates_minimap_cache(
            self, empty_zone2, stub_gv, dummy_texture):
        empty_zone2._minimap_cache = object()
        try_respawn(empty_zone2, stub_gv)
        assert empty_zone2._minimap_cache is None


class TestAsteroidRespawnSlowFills:
    """Sixty ticks — one missing iron asteroid — must refill exactly once
    per tick, mirroring Zone 1's one-per-interval cadence."""

    def test_n_ticks_fills_n_iron(
            self, empty_zone2, stub_gv, dummy_texture):
        missing = 5
        for _ in range(ASTEROID_COUNT - missing):
            empty_zone2._iron_asteroids.append(
                IronAsteroid(dummy_texture, 500.0, 500.0))
        for i in range(missing):
            try_respawn(empty_zone2, stub_gv)
            assert len(empty_zone2._iron_asteroids) == ASTEROID_COUNT - missing + i + 1
        # One extra tick must not overshoot the cap.
        try_respawn(empty_zone2, stub_gv)
        assert len(empty_zone2._iron_asteroids) == ASTEROID_COUNT


class TestRespawnAvoidsBuildings:
    def test_find_respawn_pos_returns_none_when_world_is_all_excluded(
            self, empty_zone2, stub_gv, dummy_texture):
        """Plant one building at every possible respawn position so the
        exclusion radius covers the world — helper must give up."""
        # Very small zone so we can cover it by blanketing the grid.
        empty_zone2.world_width = 400
        empty_zone2.world_height = 400
        # building_list is a SpriteList on the stub; swap it for a list so
        # we can drop plain namespaces in without re-creating sprites.
        stub_gv.building_list = [
            _fake_building(x, y)
            for x in range(0, 400, 50)
            for y in range(0, 400, 50)
        ]
        pos = _find_respawn_pos(empty_zone2, stub_gv, attempts=20)
        assert pos is None

    def test_find_respawn_pos_clears_building_exclusion_zone(
            self, empty_zone2, stub_gv, dummy_texture):
        """A single building in a large empty zone — every returned
        position must sit outside RESPAWN_EXCLUSION_RADIUS of it."""
        hs = _fake_building(3200.0, 3200.0)
        stub_gv.building_list = [hs]
        for _ in range(50):
            pos = _find_respawn_pos(empty_zone2, stub_gv)
            assert pos is not None
            d = math.hypot(pos[0] - hs.center_x, pos[1] - hs.center_y)
            assert d >= RESPAWN_EXCLUSION_RADIUS, (
                f"respawn at {pos} was {d:.0f} px from building "
                f"(< {RESPAWN_EXCLUSION_RADIUS})")


class TestRespawnStillHandlesAliens:
    """Regression — extending try_respawn must not break the alien
    top-up that was its original job."""

    def test_aliens_still_respawn_when_below_cap(
            self, empty_zone2, stub_gv, dummy_texture):
        try_respawn(empty_zone2, stub_gv)
        # One of each alien class.
        from constants import (
            Z2_SHIELDED_COUNT, Z2_FAST_COUNT,
            Z2_GUNNER_COUNT, Z2_RAMMER_COUNT,
        )
        total_expected = 4  # one per type since every list started empty
        # (any alien caps that happen to be zero would break this — none are)
        assert Z2_SHIELDED_COUNT > 0 and Z2_FAST_COUNT > 0
        assert Z2_GUNNER_COUNT > 0 and Z2_RAMMER_COUNT > 0
        assert len(empty_zone2._aliens) == total_expected
