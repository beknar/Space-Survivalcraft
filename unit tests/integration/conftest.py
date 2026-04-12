"""Integration-test fixtures: spin up a real (hidden) Arcade window once
per test session so we can construct GameView and tick its update loop
end-to-end. Slow (~1 s setup) but the only way to catch bugs that the
SimpleNamespace stubs can't see.
"""
from __future__ import annotations

import os
import sys

import pytest

# Make project root importable AND add it as a DLL search directory so
# FFmpeg shared libraries (avcodec-62.dll etc.) in the project root are
# found when pyglet imports the FFmpegDecoder at video_player module level.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _PROJECT_ROOT)
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(_PROJECT_ROOT)

import arcade


@pytest.fixture(scope="session")
def real_window():
    """A single hidden Arcade window shared by all integration tests in
    the session. Visible=False keeps it off-screen so CI environments and
    local runs don't pop a window up."""
    win = arcade.Window(800, 600, "integration-test", visible=False)
    yield win
    try:
        win.close()
    except Exception:
        pass


@pytest.fixture
def real_game_view(real_window):
    """A real GameView wired to the hidden test window. ``skip_music=True``
    avoids loading the background-music tracks (slow + noisy).

    Note: this constructs the *full* game state including textures, audio,
    and zone setup, so each test costs ~50–100 ms even with the window
    fixture cached. Use sparingly — branch coverage belongs in the fast
    stub-based suite under ``unit tests/test_zone2_update.py``."""
    from game_view import GameView
    gv = GameView(faction="Earth", ship_type="Cruiser", skip_music=True)
    real_window.show_view(gv)
    yield gv
    # GameView doesn't have an explicit teardown — let GC handle the
    # sprite lists. Window stays alive for next test.
