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


class _FakePlayer:
    """A stand-in for ``pyglet.media.Player`` recording lifecycle calls
    without spinning up a real FFmpeg pipeline (which would require a
    GL context in CI)."""

    def __init__(self) -> None:
        self.volume: float = 1.0
        self.deleted: bool = False
        self.paused: bool = False
        self.source = None

    def pause(self) -> None:
        self.paused = True

    def next_source(self) -> None:
        pass

    def delete(self) -> None:
        self.deleted = True


class TestDeferredCleanup:
    """The pyglet FFmpeg VideoPacket heap-corruption bug — killed the
    game once with a Windows fatal 0xc0000374 — was traced to calling
    ``player.delete()`` while the decoder worker thread was mid-packet.
    ``_stop_player`` must now route deletion through a deferred cleanup
    queue that waits ``_CLEANUP_DELAY_S`` before actually calling
    ``.delete()``."""

    def setup_method(self):
        from video_player import VideoPlayer
        VideoPlayer._pending_cleanup = []

    def test_stop_player_defers_delete(self):
        from video_player import VideoPlayer
        vp = VideoPlayer.__new__(VideoPlayer)   # bypass __init__
        vp._player = _FakePlayer()
        vp._source = object()
        vp._last_video_time = 0.0
        fake = vp._player

        vp._stop_player()

        # Player NOT deleted yet — it should be on the pending queue.
        assert fake.deleted is False
        assert fake.paused is True
        assert vp._player is None
        assert len(VideoPlayer._pending_cleanup) == 1
        deadline, enqueued = VideoPlayer._pending_cleanup[0]
        assert enqueued is fake

    def test_drain_deletes_past_deadline(self):
        from video_player import VideoPlayer
        import time as _time
        fake = _FakePlayer()
        VideoPlayer._pending_cleanup.append(
            (_time.monotonic() - 1.0, fake))   # deadline already passed
        VideoPlayer._drain_pending_cleanup()
        assert fake.deleted is True
        assert VideoPlayer._pending_cleanup == []

    def test_drain_keeps_future_deadline(self):
        from video_player import VideoPlayer
        import time as _time
        fake = _FakePlayer()
        VideoPlayer._pending_cleanup.append(
            (_time.monotonic() + 60.0, fake))
        VideoPlayer._drain_pending_cleanup()
        assert fake.deleted is False
        assert len(VideoPlayer._pending_cleanup) == 1

    def test_drain_swallows_delete_exception(self):
        """A broken player raising from ``.delete()`` must not crash the
        game — the whole point of this queue is reliability."""
        from video_player import VideoPlayer
        import time as _time

        class _BrokenPlayer(_FakePlayer):
            def delete(self) -> None:
                raise RuntimeError("boom")

        pl = _BrokenPlayer()
        VideoPlayer._pending_cleanup.append((_time.monotonic() - 1.0, pl))
        VideoPlayer._drain_pending_cleanup()      # must not raise
        assert VideoPlayer._pending_cleanup == []

    def test_stop_defers_standby_player_too(self):
        """``stop()`` must defer the standby player delete as well — a
        pre-built standby has its own FFmpeg worker that needs to drain
        before ``.delete()`` is safe."""
        from video_player import VideoPlayer
        vp = VideoPlayer.__new__(VideoPlayer)
        vp._player = None
        vp._source = None
        vp._last_video_time = -1.0
        vp._segment_mode = True
        vp._standby_player = _FakePlayer()
        standby = vp._standby_player
        vp._standby_source = None
        vp._standby_ready = True
        vp._standby_started = True
        vp.active = False
        vp._current_file = ""
        vp._current_path = ""
        vp._cached_arc_tex = None

        vp.stop()
        assert standby.deleted is False
        assert standby.paused is True
        assert len(VideoPlayer._pending_cleanup) == 1
