"""Unit tests for splash-view keyboard navigation (24a27a6).

Mirrors the escape-menu pattern: Tab / arrows / Enter / Space
move + activate buttons; ESC exits the splash (or backs out
of the Load sub-screen).

Stubs the music + click sounds so we don't need an audio
context.  Uses the shared ``arcade_window`` fixture from
conftest.py for the GL context.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import arcade
import pytest


# ── SplashView builder ────────────────────────────────────────────────────


@pytest.fixture
def splash():
    """Build a SplashView with audio + music side effects mocked."""
    with patch("splash_view.arcade.play_sound") as _ps, \
         patch("splash_view.arcade.load_sound") as _ls, \
         patch("splash_view.arcade.stop_sound"), \
         patch("splash_view.collect_music_tracks", return_value=[]):
        _ls.return_value = MagicMock()
        _ps.return_value = MagicMock()
        from splash_view import SplashView
        view = SplashView()
        # Keep the patches in scope for assertions inside the test.
        view._stop_music = MagicMock()
        yield view


# ── Main splash navigation ────────────────────────────────────────────────


class TestSplashKeyboardNav:
    def test_initial_focus_is_unset(self, splash):
        assert splash._hover_idx == -1

    def test_tab_from_unset_focuses_first_button(self, splash):
        splash.on_key_press(arcade.key.TAB, 0)
        assert splash._hover_idx == 0

    def test_tab_advances_through_4_buttons(self, splash):
        for expected in (0, 1, 2, 3, 0):
            splash.on_key_press(arcade.key.TAB, 0)
            assert splash._hover_idx == expected

    def test_shift_tab_retreats(self, splash):
        splash._hover_idx = 2
        splash.on_key_press(arcade.key.TAB, arcade.key.MOD_SHIFT)
        assert splash._hover_idx == 1

    def test_arrow_down_advances(self, splash):
        splash._hover_idx = 1
        splash.on_key_press(arcade.key.DOWN, 0)
        assert splash._hover_idx == 2

    def test_arrow_up_at_zero_wraps(self, splash):
        splash._hover_idx = 0
        splash.on_key_press(arcade.key.UP, 0)
        assert splash._hover_idx == 3

    def test_escape_exits_game(self, splash):
        with patch("splash_view.arcade.exit") as ex:
            splash.on_key_press(arcade.key.ESCAPE, 0)
            ex.assert_called_once()

    def test_enter_with_no_focus_focuses_play_now(self, splash):
        # Bare Enter on first open should land on Play Now (idx 0)
        # so a blind tap takes the user into the game.  Splash
        # imports SelectionView lazily inside _activate_menu, so
        # patch it via sys.modules.
        import sys
        fake = MagicMock()
        with patch.dict(sys.modules, {"selection_view":
                                       MagicMock(SelectionView=fake)}):
            splash.window.show_view = MagicMock()
            splash.on_key_press(arcade.key.RETURN, 0)
            assert splash._hover_idx == 0
            splash.window.show_view.assert_called_once()

    def test_enter_on_options_loads_options_view(self, splash):
        splash._hover_idx = 2
        import sys
        fake = MagicMock()
        with patch.dict(sys.modules, {"options_view":
                                       MagicMock(OptionsView=fake)}):
            splash.window.show_view = MagicMock()
            splash.on_key_press(arcade.key.RETURN, 0)
            splash.window.show_view.assert_called_once()
            splash._stop_music.assert_called_once()

    def test_enter_on_exit_calls_arcade_exit(self, splash):
        splash._hover_idx = 3
        with patch("splash_view.arcade.exit") as ex:
            splash.on_key_press(arcade.key.RETURN, 0)
            ex.assert_called_once()


# ── Load sub-screen navigation ────────────────────────────────────────────


class TestSplashLoadKeyboard:
    def test_escape_in_load_returns_to_splash(self, splash):
        splash._show_load = True
        splash._load_hover = 0
        splash.on_key_press(arcade.key.ESCAPE, 0)
        assert splash._show_load is False
        assert splash._load_hover == -1

    def test_tab_in_load_advances_through_slots_and_back(self, splash):
        from constants import SAVE_SLOT_COUNT
        splash._show_load = True
        splash._load_hover = -1
        # First Tab focuses slot 0.
        splash.on_key_press(arcade.key.TAB, 0)
        assert splash._load_hover == 0
        # Tab through to the last slot.
        for i in range(1, SAVE_SLOT_COUNT):
            splash.on_key_press(arcade.key.TAB, 0)
            assert splash._load_hover == i
        # Next Tab lands on the Back button (id 100).
        splash.on_key_press(arcade.key.TAB, 0)
        assert splash._load_hover == 100
        # Wraps back to slot 0.
        splash.on_key_press(arcade.key.TAB, 0)
        assert splash._load_hover == 0

    def test_enter_on_back_returns_to_splash(self, splash):
        splash._show_load = True
        splash._load_hover = 100
        splash.on_key_press(arcade.key.RETURN, 0)
        assert splash._show_load is False
        assert splash._load_hover == -1
