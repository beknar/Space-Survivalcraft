"""Tests for asteroid yield constants and alien-asteroid damage."""
from __future__ import annotations

import pytest
from PIL import Image as PILImage

import arcade

from constants import (
    ASTEROID_IRON_YIELD, DOUBLE_IRON_YIELD,
    COPPER_YIELD, COPPER_IRON_YIELD,
    WANDERING_IRON_YIELD, WANDERING_HP,
    ALIEN_ASTEROID_DAMAGE, ALIEN_HP,
)


# ═══════════════════════════════════════════════════════════════════════════
#  Yield constants
# ═══════════════════════════════════════════════════════════════════════════

class TestYieldConstants:
    def test_iron_asteroid_yields_10(self):
        assert ASTEROID_IRON_YIELD == 10

    def test_double_iron_yields_20(self):
        assert DOUBLE_IRON_YIELD == 20

    def test_copper_yields_10_copper(self):
        assert COPPER_YIELD == 10

    def test_copper_also_yields_5_iron(self):
        assert COPPER_IRON_YIELD == 5

    def test_wandering_asteroid_yields_15_iron(self):
        assert WANDERING_IRON_YIELD == 15

    def test_wandering_asteroid_hp(self):
        assert WANDERING_HP == 150


# ═══════════════════════════════════════════════════════════════════════════
#  Alien-asteroid damage
# ═══════════════════════════════════════════════════════════════════════════

class TestAlienAsteroidDamage:
    def test_alien_asteroid_damage_constant(self):
        assert ALIEN_ASTEROID_DAMAGE == 10

    def test_alien_survives_one_asteroid_hit(self):
        """Standard alien has 50 HP, one hit does 10 damage — should survive."""
        assert ALIEN_HP > ALIEN_ASTEROID_DAMAGE

    def test_alien_dies_after_enough_hits(self):
        """5 hits × 10 damage = 50 HP = dead standard alien."""
        hits_to_kill = ALIEN_HP // ALIEN_ASTEROID_DAMAGE
        assert hits_to_kill == 5


# ═══════════════════════════════════════════════════════════════════════════
#  Alien-asteroid collision handler (Zone 1)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def dummy_texture():
    img = PILImage.new("RGBA", (32, 32), (200, 0, 0, 255))
    return arcade.Texture(img)


class TestAlienAsteroidCollision:
    def test_collision_deals_damage_to_alien(self, stub_gv, dummy_texture):
        """Alien colliding with an asteroid takes ALIEN_ASTEROID_DAMAGE."""
        from sprites.alien import SmallAlienShip
        from sprites.asteroid import IronAsteroid
        from collisions import handle_alien_asteroid_collision

        alien = SmallAlienShip(dummy_texture, dummy_texture, 100.0, 100.0)
        original_hp = alien.hp
        stub_gv.alien_list.append(alien)

        asteroid = IronAsteroid(dummy_texture, 100.0, 100.0)
        stub_gv.asteroid_list.append(asteroid)

        # Force overlapping position so collision triggers
        alien.center_x = asteroid.center_x
        alien.center_y = asteroid.center_y

        handle_alien_asteroid_collision(stub_gv)

        assert alien.hp <= original_hp - ALIEN_ASTEROID_DAMAGE

    def test_alien_killed_by_asteroid_drops_loot(self, stub_gv, dummy_texture):
        """Alien killed by asteroid collision spawns iron + explosion."""
        from sprites.alien import SmallAlienShip
        from sprites.asteroid import IronAsteroid
        from collisions import handle_alien_asteroid_collision

        alien = SmallAlienShip(dummy_texture, dummy_texture, 100.0, 100.0)
        alien.hp = 1  # about to die
        stub_gv.alien_list.append(alien)

        asteroid = IronAsteroid(dummy_texture, 100.0, 100.0)
        stub_gv.asteroid_list.append(asteroid)
        alien.center_x = asteroid.center_x
        alien.center_y = asteroid.center_y

        handle_alien_asteroid_collision(stub_gv)

        assert len(stub_gv.alien_list) == 0  # alien removed
        assert len(stub_gv.calls["explosion"]) > 0
        assert len(stub_gv.calls["iron_pickup"]) > 0


# ═══════════════════════════════════════════════════════════════════════════
#  Zone 2 alien obstacle avoidance
# ═══════════════════════════════════════════════════════════════════════════

class TestZone2AlienAvoidance:
    def test_avoidance_steers_away_from_asteroid(self, dummy_texture):
        """Zone 2 alien's _compute_avoidance adds repulsion near an asteroid."""
        from sprites.zone2_aliens import Zone2Alien

        alien = Zone2Alien(dummy_texture, dummy_texture, 100.0, 100.0,
                           speed=80, has_guns=True)
        asteroid_list = arcade.SpriteList()
        # Place asteroid very close to alien
        ast = arcade.Sprite(path_or_texture=dummy_texture)
        ast.center_x = 110.0
        ast.center_y = 100.0
        asteroid_list.append(ast)

        # Base direction: straight right (toward asteroid)
        sx, sy = alien._compute_avoidance(1.0, 0.0, asteroid_list)

        # Should steer away (sx should be less than 1.0 / negative)
        assert sx < 1.0  # avoidance reduced the rightward component

    def test_avoidance_no_effect_when_far(self, dummy_texture):
        """No avoidance adjustment when asteroid is far away."""
        from sprites.zone2_aliens import Zone2Alien

        alien = Zone2Alien(dummy_texture, dummy_texture, 100.0, 100.0,
                           speed=80, has_guns=True)
        asteroid_list = arcade.SpriteList()
        ast = arcade.Sprite(path_or_texture=dummy_texture)
        ast.center_x = 5000.0  # very far
        ast.center_y = 5000.0
        asteroid_list.append(ast)

        sx, sy = alien._compute_avoidance(1.0, 0.0, asteroid_list)

        # Should be unchanged
        assert abs(sx - 1.0) < 0.01
        assert abs(sy - 0.0) < 0.01

    def test_avoidance_empty_list(self, dummy_texture):
        """No crash with empty asteroid list."""
        from sprites.zone2_aliens import Zone2Alien

        alien = Zone2Alien(dummy_texture, dummy_texture, 100.0, 100.0,
                           speed=80, has_guns=True)
        sx, sy = alien._compute_avoidance(1.0, 0.0, arcade.SpriteList())
        assert sx == 1.0
        assert sy == 0.0
