"""Tests for video_player.py — character scanning functions."""
from __future__ import annotations

import os
import tempfile
import pytest

from video_player import scan_characters_dir, character_video_path, _CHARACTERS_DIR


class TestScanCharactersDir:
    def test_returns_list(self):
        result = scan_characters_dir()
        assert isinstance(result, list)

    def test_names_are_strings(self):
        for name in scan_characters_dir():
            assert isinstance(name, str)

    def test_sorted(self):
        result = scan_characters_dir()
        assert result == sorted(result)

    def test_no_extensions_in_names(self):
        for name in scan_characters_dir():
            assert "." not in name


class TestCharacterVideoPath:
    def test_empty_name_returns_none(self):
        assert character_video_path("") is None

    def test_nonexistent_name_returns_none(self):
        assert character_video_path("__nonexistent_character_xyz__") is None

    def test_valid_name_returns_path(self):
        chars = scan_characters_dir()
        if chars:
            path = character_video_path(chars[0])
            assert path is not None
            assert os.path.isfile(path)

    def test_path_contains_name(self):
        chars = scan_characters_dir()
        if chars:
            path = character_video_path(chars[0])
            assert chars[0] in os.path.basename(path)
