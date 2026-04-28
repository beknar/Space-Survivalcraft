"""Unit tests for escape-menu keyboard navigation (a34b61b).

Each escape-menu mode now responds to:

  * Tab / Down / S       focus next button (wraps)
  * Shift+Tab / Up / W   focus previous (wraps)
  * Enter / Space        activate focused button
  * ESC                  back / close

The actions taken on activation depend on the mode -- verified
indirectly by patching the ctx callbacks and asserting they
fire on the expected keys.

These tests stub ``MenuContext`` so we don't need an Arcade
window.  The code under test only reads / writes a few ctx
attributes (hover_idx, set_mode, close_menu, play_click), so
a SimpleNamespace is enough.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import arcade
import pytest


# ── Stub MenuContext ──────────────────────────────────────────────────────


def _ctx(window_w=1280, window_h=800):
    """Build a stub MenuContext with the attributes each mode reads."""
    ctx = SimpleNamespace(
        window=SimpleNamespace(width=window_w, height=window_h),
        hover_idx=-1,
        status_msg="",
        t_status=MagicMock(),
        t_back=MagicMock(),
        t_title=MagicMock(),
        t_info=MagicMock(),
        t_text=MagicMock(),
        recalc=lambda: (480, 15),       # px, py for a centred panel
        set_mode=MagicMock(),
        close_menu=MagicMock(),
        main_menu_fn=MagicMock(),
        play_click=MagicMock(),
        save_fn=MagicMock(),
        load_fn=MagicMock(),
        flash_status=MagicMock(),
        stop_song_fn=MagicMock(),
        other_song_fn=MagicMock(),
        video_play_fn=MagicMock(),
        video_stop_fn=MagicMock(),
        resolution_fn=MagicMock(),
        res_idx=0,
    )
    return ctx


# ── MainMode ──────────────────────────────────────────────────────────────


class TestMainModeKeyboard:
    @pytest.fixture
    def mode(self):
        from escape_menu._main_mode import MainMode
        return MainMode(_ctx())

    def test_tab_from_no_focus_lands_on_resume(self, mode):
        mode.on_key_press(arcade.key.TAB, 0)
        assert mode.ctx.hover_idx == 0

    def test_tab_cycles_forward(self, mode):
        mode.ctx.hover_idx = 2
        mode.on_key_press(arcade.key.TAB, 0)
        assert mode.ctx.hover_idx == 3

    def test_shift_tab_cycles_backward(self, mode):
        mode.ctx.hover_idx = 2
        mode.on_key_press(arcade.key.TAB, arcade.key.MOD_SHIFT)
        assert mode.ctx.hover_idx == 1

    def test_tab_wraps_at_end(self, mode):
        mode.ctx.hover_idx = 6   # last button
        mode.on_key_press(arcade.key.TAB, 0)
        assert mode.ctx.hover_idx == 0

    def test_arrow_down_advances(self, mode):
        mode.ctx.hover_idx = 0
        mode.on_key_press(arcade.key.DOWN, 0)
        assert mode.ctx.hover_idx == 1

    def test_arrow_up_retreats(self, mode):
        mode.ctx.hover_idx = 1
        mode.on_key_press(arcade.key.UP, 0)
        assert mode.ctx.hover_idx == 0

    def test_enter_with_no_focus_activates_resume(self, mode):
        mode.on_key_press(arcade.key.RETURN, 0)
        assert mode.ctx.hover_idx == 0
        mode.ctx.close_menu.assert_called_once()

    def test_enter_on_save_opens_save_mode(self, mode):
        mode.ctx.hover_idx = 1
        mode.on_key_press(arcade.key.RETURN, 0)
        mode.ctx.set_mode.assert_called_with("save")

    def test_space_activates_focused_button(self, mode):
        mode.ctx.hover_idx = 5   # Songs
        mode.on_key_press(arcade.key.SPACE, 0)
        mode.ctx.set_mode.assert_called_with("songs")

    def test_escape_closes_menu(self, mode):
        mode.on_key_press(arcade.key.ESCAPE, 0)
        mode.ctx.close_menu.assert_called_once()


# ── SongsMode ─────────────────────────────────────────────────────────────


class TestSongsModeKeyboard:
    @pytest.fixture
    def mode(self):
        from escape_menu._songs_mode import SongsMode
        return SongsMode(_ctx())

    def test_initial_focus_is_unset(self, mode):
        assert mode._focus_idx == -1

    def test_tab_advances_through_buttons(self, mode):
        for expected in (0, 1, 2, 3, 0):
            mode.on_key_press(arcade.key.TAB, 0)
            assert mode._focus_idx == expected

    def test_enter_on_music_videos_opens_video_mode(self, mode):
        mode._focus_idx = 2
        mode.on_key_press(arcade.key.RETURN, 0)
        mode.ctx.set_mode.assert_called_with("video")

    def test_enter_on_back_returns_to_main(self, mode):
        mode._focus_idx = 3
        mode.on_key_press(arcade.key.RETURN, 0)
        mode.ctx.set_mode.assert_called_with("main")

    def test_enter_on_stop_calls_stop_song_fn(self, mode):
        mode._focus_idx = 0
        mode.on_key_press(arcade.key.RETURN, 0)
        mode.ctx.stop_song_fn.assert_called_once()

    def test_escape_returns_to_main(self, mode):
        mode.on_key_press(arcade.key.ESCAPE, 0)
        mode.ctx.set_mode.assert_called_with("main")


# ── VideoMode ─────────────────────────────────────────────────────────────


class TestVideoModeKeyboard:
    @pytest.fixture
    def mode(self):
        from escape_menu._video_mode import VideoMode
        m = VideoMode(_ctx())
        # Pretend we have 5 video files.
        m._files = [f"track_{i}.mp4" for i in range(5)]
        return m

    def test_focus_count_includes_stop_and_back(self, mode):
        # 5 files + Stop + Back = 7 focusable items.
        assert mode._focus_count() == 7
        assert mode._stop_idx() == 5
        assert mode._back_idx() == 6

    def test_tab_advances_through_files(self, mode):
        for expected in (0, 1, 2, 3, 4, 5, 6, 0):
            mode.on_key_press(arcade.key.TAB, 0)
            assert mode._focus_idx == expected

    def test_enter_on_file_calls_video_play_fn(self, mode):
        mode._focus_idx = 2
        mode.on_key_press(arcade.key.RETURN, 0)
        mode.ctx.video_play_fn.assert_called_once()
        assert "track_2.mp4" in mode.ctx.video_play_fn.call_args.args[0]

    def test_enter_on_stop_calls_video_stop_fn(self, mode):
        from settings import audio
        audio.video_file = "track_0.mp4"   # so stop has something to do
        mode._focus_idx = mode._stop_idx()
        mode.on_key_press(arcade.key.RETURN, 0)
        mode.ctx.video_stop_fn.assert_called_once()

    def test_enter_on_back_returns_to_songs(self, mode):
        mode._focus_idx = mode._back_idx()
        mode.on_key_press(arcade.key.RETURN, 0)
        mode.ctx.set_mode.assert_called_with("songs")

    def test_focus_scrolls_list_to_keep_visible(self, mode):
        # 5 files + 2 buttons = 7 focusable, scroll window is 8 -- so
        # in this stub all rows are visible.  Push files to 20 to
        # exercise scroll.
        mode._files = [f"f_{i}.mp4" for i in range(20)]
        mode._focus_idx = 15
        mode._ensure_focus_visible()
        # focus 15, _MAX_VIS=8 -> scroll should be 15-8+1 = 8
        assert mode._scroll == 8

    def test_editing_dir_swallows_navigation(self, mode):
        mode._editing_dir = True
        # Tab while editing must NOT shift focus.
        mode._focus_idx = -1
        mode.on_key_press(arcade.key.TAB, 0)
        assert mode._focus_idx == -1


# ── HelpMode ──────────────────────────────────────────────────────────────


class TestHelpModeKeyboard:
    @pytest.fixture
    def mode(self):
        from escape_menu._help_mode import HelpMode
        return HelpMode(_ctx())

    @pytest.mark.parametrize("key", [
        arcade.key.ESCAPE, arcade.key.TAB, arcade.key.RETURN,
        arcade.key.ENTER, arcade.key.SPACE,
    ])
    def test_any_navigation_key_returns_to_main(self, mode, key):
        mode.on_key_press(key, 0)
        mode.ctx.set_mode.assert_called_with("main")
