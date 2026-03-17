"""Tests for damage routing — shields absorb first, overflow to HP."""
from __future__ import annotations

import pytest
import arcade

from sprites.player import PlayerShip
from sprites.shield import ShieldSprite
from sprites.explosion import FireSpark


class MockShield:
    """Minimal mock for ShieldSprite (avoids needing textures for hit_flash)."""
    def __init__(self):
        self.flashed = False

    def hit_flash(self):
        self.flashed = True


@pytest.fixture
def player(dummy_texture):
    """Create a minimal PlayerShip for damage testing."""
    s = PlayerShip.__new__(PlayerShip)
    arcade.Sprite.__init__(s, path_or_texture=dummy_texture, scale=1.0)
    s._use_legacy = True
    s._frames = []
    s.hp = 100
    s.max_hp = 100
    s.shields = 100
    s.max_shields = 100
    s._shield_acc = 0.0
    s._collision_cd = 0.0
    s._rot_speed = 150.0
    s._thrust = 250.0
    s._brake = 125.0
    s._max_spd = 450.0
    s._damping = 0.98875
    s._shield_regen = 0.5
    s.guns = 1
    s.vel_x = 0.0
    s.vel_y = 0.0
    s.heading = 0.0
    s._intensity = 0.0
    s._anim_timer = 0.0
    s._anim_col = 0
    s.center_x = 3200.0
    s.center_y = 3200.0
    return s


def apply_damage(player, amount, shield_sprite=None, fire_sparks=None):
    """Simulate _apply_damage_to_player logic from GameView.

    This mirrors the actual damage routing in game_view.py without
    requiring a full GameView instance.
    """
    shield_hit = False
    hull_hit = False

    if player.shields > 0:
        absorbed = min(player.shields, amount)
        player.shields -= absorbed
        amount -= absorbed
        shield_hit = True
        if shield_sprite is not None:
            shield_sprite.hit_flash()

    if amount > 0:
        player.hp = max(0, player.hp - amount)
        hull_hit = True
        if fire_sparks is not None:
            fire_sparks.append(FireSpark(player.center_x, player.center_y))

    return shield_hit, hull_hit


class TestDamageRouting:
    def test_shields_absorb_first(self, player):
        apply_damage(player, 30)
        assert player.shields == 70
        assert player.hp == 100

    def test_shield_overflow_to_hp(self, player):
        player.shields = 20
        apply_damage(player, 50)
        assert player.shields == 0
        assert player.hp == 70

    def test_full_shield_absorption(self, player):
        apply_damage(player, 50)
        assert player.shields == 50
        assert player.hp == 100

    def test_zero_shields_all_to_hp(self, player):
        player.shields = 0
        apply_damage(player, 30)
        assert player.shields == 0
        assert player.hp == 70

    def test_hp_reaches_zero(self, player):
        player.shields = 0
        apply_damage(player, 150)
        assert player.hp == 0

    def test_hp_does_not_go_negative(self, player):
        player.shields = 0
        apply_damage(player, 999)
        assert player.hp == 0


class TestDamageEffects:
    def test_shield_flash_on_shield_hit(self, player):
        mock_shield = MockShield()
        apply_damage(player, 10, shield_sprite=mock_shield)
        assert mock_shield.flashed is True

    def test_no_shield_flash_when_shields_zero(self, player):
        player.shields = 0
        mock_shield = MockShield()
        apply_damage(player, 10, shield_sprite=mock_shield)
        assert mock_shield.flashed is False

    def test_fire_sparks_on_hull_damage(self, player):
        player.shields = 0
        sparks = []
        apply_damage(player, 10, fire_sparks=sparks)
        assert len(sparks) == 1

    def test_no_fire_sparks_on_shield_only(self, player):
        sparks = []
        apply_damage(player, 10, fire_sparks=sparks)
        assert len(sparks) == 0
