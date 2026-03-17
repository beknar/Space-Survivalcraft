"""Tests for world_setup._track_name_from_path — music track name parsing."""
from __future__ import annotations

from world_setup import _track_name_from_path


class TestTrackNameFromPath:
    def test_vol1_action_loop(self):
        path = r"C:\music\Antimatter Fountain [Action Loop].wav"
        assert _track_name_from_path(path) == "Antimatter Fountain [Action]"

    def test_vol1_ambient_loop(self):
        path = "/music/Deep Space Echo [Ambient Loop].wav"
        assert _track_name_from_path(path) == "Deep Space Echo [Ambient]"

    def test_vol2_loop_suffix(self):
        path = "/music/subdir/Comet Tail_loop.wav"
        assert _track_name_from_path(path) == "Comet Tail"

    def test_vol2_short_loop(self):
        path = "/music/subdir/Solar Winds_short_loop.wav"
        assert _track_name_from_path(path) == "Solar Winds"

    def test_plain_name_no_suffix(self):
        path = "/music/Epic Battle.wav"
        assert _track_name_from_path(path) == "Epic Battle"

    def test_mp3_extension(self):
        path = "/music/Track Name.mp3"
        assert _track_name_from_path(path) == "Track Name"

    def test_windows_path(self):
        path = r"C:\Users\music\Galaxy Drift [Action Loop].wav"
        assert _track_name_from_path(path) == "Galaxy Drift [Action]"

    def test_just_filename(self):
        path = "Simple_loop.wav"
        assert _track_name_from_path(path) == "Simple"
