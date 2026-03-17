"""Tests for sprites/shield.py — ShieldSprite visibility and hit flash."""
from __future__ import annotations

import pytest

from constants import SHIELD_HIT_FLASH
from sprites.shield import ShieldSprite


@pytest.fixture
def shield(dummy_texture_list):
    return ShieldSprite(dummy_texture_list)


class TestShieldVisibility:
    def test_invisible_when_depleted(self, shield):
        shield.update_shield(0.1, 100, 100, shields=0)
        assert shield.color[3] == 0

    def test_visible_when_has_shields(self, shield):
        shield.update_shield(0.1, 100, 100, shields=50)
        assert shield.color[3] == 200

    def test_reappears_when_regen(self, shield):
        shield.update_shield(0.1, 100, 100, shields=0)
        assert shield.color[3] == 0
        shield.update_shield(0.1, 100, 100, shields=10)
        assert shield.color[3] == 200


class TestShieldHitFlash:
    def test_hit_flash_sets_timer(self, shield):
        shield.hit_flash()
        assert shield._hit_timer == SHIELD_HIT_FLASH

    def test_alpha_pulses_during_flash(self, shield):
        shield.hit_flash()
        shield.update_shield(0.01, 100, 100, shields=50)
        # During flash, alpha should be > 200
        assert shield.color[3] > 200

    def test_alpha_returns_to_normal_after_flash(self, shield):
        shield.hit_flash()
        # Update long enough for flash to expire
        shield.update_shield(SHIELD_HIT_FLASH + 0.1, 100, 100, shields=50)
        assert shield.color[3] == 200


class TestShieldTracking:
    def test_follows_ship_position(self, shield):
        shield.update_shield(0.1, 300, 400, shields=100)
        assert shield.center_x == 300
        assert shield.center_y == 400


class TestShieldAnimation:
    def test_frame_advances(self, shield):
        shield.update_shield(0.5, 100, 100, shields=100)
        # With SHIELD_ANIM_FPS=8, 0.5s should advance several frames
        assert shield._frame_idx > 0
