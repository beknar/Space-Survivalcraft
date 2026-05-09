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


# ── Splash → load → GameView constructor kwargs ───────────────────────────


class TestSplashDoLoadCharacterName:
    """Pins ``splash_view._do_load`` passing ``character_name``
    through to the GameView constructor.  Caught from the 2026-05-09
    user report: loading slot 3 (saved as Ellie) from the splash
    screen showed Debra's character video because the splash path
    skipped the kwarg, leaving ``audio.character_name`` at its
    config-persisted value (Debra) when ``_start_character_video``
    fired during init.  The in-game ``load_game`` path already
    passes the kwarg correctly; this test pins the splash path."""

    def _stub_save(self, tmp_path, slot: int, **fields) -> None:
        """Write a synthetic save file in the slot's location so
        ``_do_load`` can read it."""
        import json
        import os
        save_dir = tmp_path / "saves"
        save_dir.mkdir(exist_ok=True)
        path = save_dir / f"save_slot_{slot + 1:02d}.json"
        with open(path, "w") as f:
            json.dump(fields, f)
        return str(path)

    def test_do_load_passes_character_name_kwarg(
            self, splash, tmp_path, monkeypatch):
        """When the save has ``character_name='Ellie'``, the
        GameView constructor must receive that exact kwarg so the
        constructor's ``_start_character_video`` plays the right
        video.  Without the kwarg the global ``audio.character_name``
        keeps its prior value and the wrong video plays until the
        next state transition (which never restarts the video)."""
        # Set up a synthetic slot with Ellie saved there.
        save_path = self._stub_save(
            tmp_path, slot=2,
            faction="Ascended", ship_type="Thunderbolt",
            ship_level=2, character_name="Ellie")
        # Redirect the splash's _SAVE_DIR lookup to our temp dir so
        # ``_do_load`` reads our synthetic file.
        import splash_view
        monkeypatch.setattr(splash_view, "_SAVE_DIR",
                            str(tmp_path / "saves"))

        # Mock GameView so we can capture constructor kwargs without
        # building a real game.  Patch through ``sys.modules`` because
        # ``_do_load`` imports GameView lazily.
        import sys
        fake_view_instance = MagicMock()
        fake_gv_class = MagicMock(return_value=fake_view_instance)
        # The implementation also calls ``GameView._restore_state``
        # as a static lookup — give the mock that method.
        fake_gv_class._restore_state = MagicMock()
        with patch.dict(sys.modules,
                        {"game_view": MagicMock(GameView=fake_gv_class)}):
            splash.window.show_view = MagicMock()
            splash._do_load(slot=2)

        # GameView was called once with character_name="Ellie".
        fake_gv_class.assert_called_once()
        kwargs = fake_gv_class.call_args.kwargs
        assert kwargs.get("character_name") == "Ellie", (
            f"splash_view._do_load must forward character_name "
            f"to the GameView constructor (got kwargs={kwargs!r}).  "
            f"Without this, the constructor's _start_character_video "
            f"reads the stale audio.character_name and plays the "
            f"wrong character's video.")
        assert kwargs.get("faction") == "Ascended"
        assert kwargs.get("ship_type") == "Thunderbolt"
        assert kwargs.get("ship_level") == 2

    def test_do_load_handles_missing_character_name_field(
            self, splash, tmp_path, monkeypatch):
        """Legacy save files (created before character selection
        was added) don't have a ``character_name`` field.  The
        splash loader must still pass ``character_name=""`` so the
        constructor explicitly resets the global rather than
        inheriting the prior session's character."""
        self._stub_save(
            tmp_path, slot=0,
            faction="Earth", ship_type="Aegis", ship_level=1)
        import splash_view
        monkeypatch.setattr(splash_view, "_SAVE_DIR",
                            str(tmp_path / "saves"))

        import sys
        fake_view_instance = MagicMock()
        fake_gv_class = MagicMock(return_value=fake_view_instance)
        fake_gv_class._restore_state = MagicMock()
        with patch.dict(sys.modules,
                        {"game_view": MagicMock(GameView=fake_gv_class)}):
            splash.window.show_view = MagicMock()
            splash._do_load(slot=0)

        kwargs = fake_gv_class.call_args.kwargs
        # ``data.get("character_name", "")`` defaults to empty
        # string; the kwarg MUST be passed (not omitted) so the
        # constructor's ``if character_name is not None`` branch
        # fires and resets the global.
        assert "character_name" in kwargs
        assert kwargs["character_name"] == ""
