"""Tests for the alien-laser SFX throttle in update_logic.

The throttle exists so dozens of simultaneous alien shots don't pile
into a wall of audio.  These tests verify the cooldown gate logic
without actually playing any sound (arcade.play_sound is patched).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from update_logic import play_alien_laser_sound, _ALIEN_LASER_SND_INTERVAL


def _gv():
    return SimpleNamespace(
        _alien_laser_snd=object(),   # any non-None sentinel
        _alien_laser_snd_cd=0.0,
    )


class TestAlienLaserSoundThrottle:
    def test_first_call_plays_and_arms_cooldown(self):
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_alien_laser_sound(gv)
            assert ps.call_count == 1
        assert gv._alien_laser_snd_cd == pytest.approx(
            _ALIEN_LASER_SND_INTERVAL)

    def test_repeat_call_inside_cooldown_is_skipped(self):
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_alien_laser_sound(gv)
            play_alien_laser_sound(gv)
            play_alien_laser_sound(gv)
            assert ps.call_count == 1   # second + third skipped

    def test_no_sound_loaded_is_safe(self):
        gv = SimpleNamespace()  # no _alien_laser_snd attr
        with patch("arcade.play_sound") as ps:
            play_alien_laser_sound(gv)   # must not raise
            assert ps.call_count == 0

    def test_after_cooldown_decay_plays_again(self):
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_alien_laser_sound(gv)
            # Simulate the update_timers tick that decays the cooldown.
            gv._alien_laser_snd_cd = 0.0
            play_alien_laser_sound(gv)
            assert ps.call_count == 2


class TestSfxAlienLaserConstant:
    def test_path_is_the_ricochet_asset(self):
        from constants import SFX_ALIEN_LASER
        assert SFX_ALIEN_LASER.endswith(
            "Sci-Fi Laser Weapon Ricochet 1.wav")

    def test_path_under_stormwave_energy_weapons(self):
        from constants import SFX_ALIEN_LASER
        assert "Energy Weapons" in SFX_ALIEN_LASER
        assert "Stormwave" in SFX_ALIEN_LASER
