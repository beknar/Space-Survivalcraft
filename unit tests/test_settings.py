"""Tests for settings.py — AudioSettings defaults and mutation."""
from __future__ import annotations

from settings import AudioSettings, audio


class TestAudioSettings:
    def test_default_music_volume(self):
        s = AudioSettings()
        assert s.music_volume == 0.35

    def test_default_sfx_volume(self):
        s = AudioSettings()
        assert s.sfx_volume == 0.60

    def test_mutation_persists(self):
        s = AudioSettings()
        s.music_volume = 0.80
        s.sfx_volume = 0.10
        assert s.music_volume == 0.80
        assert s.sfx_volume == 0.10

    def test_module_level_instance_exists(self):
        assert isinstance(audio, AudioSettings)

    def test_instances_are_independent(self):
        a = AudioSettings()
        b = AudioSettings()
        a.music_volume = 0.99
        assert b.music_volume == 0.35
