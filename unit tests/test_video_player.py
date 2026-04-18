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
        self.next_source_calls: int = 0
        # Truthy so ``while self._player.source: next_source()`` would
        # loop forever if it were ever re-introduced — the test below
        # locks the regression in.
        self.source = object()

    def pause(self) -> None:
        self.paused = True

    def next_source(self) -> None:
        # Record the call AND clear .source so a hypothetical
        # ``while self._player.source: next_source()`` loop only runs
        # once, but the call count assertion still catches it.
        self.next_source_calls += 1
        self.source = None

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


class TestStopPlayerDoesNotDrainSourceQueue:
    """Regression — ``_stop_player`` used to drain the source queue
    with ``while self._player.source: self._player.next_source()`` to
    "tidy up" before deferring the delete.  That caused a Windows
    fatal 0xc0000374 (heap corruption) inside ``ffmpeg_read`` on the
    pyglet media worker thread: ``pause()`` doesn't synchronise with
    the worker, so the worker could be mid-read on the very source
    that ``next_source()`` was popping off the player's queue.  Letting
    ``Player.delete()`` drain the queue 2 s later (via
    ``_pending_cleanup``) is safe because pyglet's own teardown path
    waits the worker out.

    These tests lock the fix so future "cleanup" tweaks can't bring
    the bug back."""

    def setup_method(self):
        from video_player import VideoPlayer
        VideoPlayer._pending_cleanup = []

    def test_stop_player_does_not_call_next_source(self):
        from video_player import VideoPlayer
        vp = VideoPlayer.__new__(VideoPlayer)
        vp._player = _FakePlayer()
        vp._source = object()
        vp._last_video_time = 0.0
        fake = vp._player
        # Make sure .source is truthy so a hypothetical loop would fire.
        assert fake.source is not None

        vp._stop_player()

        assert fake.next_source_calls == 0, (
            "_stop_player called next_source — that races the pyglet "
            "media worker thread and produces heap corruption inside "
            "ffmpeg_read.  Let Player.delete() drain the queue instead.")

    def test_stop_player_still_pauses_and_zeros_volume(self):
        """The two operations that ARE safe must still happen — they're
        what tells pyglet's worker thread to stop pulling buffers for
        XAudio2."""
        from video_player import VideoPlayer
        vp = VideoPlayer.__new__(VideoPlayer)
        vp._player = _FakePlayer()
        vp._source = object()
        vp._last_video_time = 0.0
        fake = vp._player
        fake.volume = 0.7

        vp._stop_player()

        assert fake.paused is True
        assert fake.volume == 0.0
        # Still queued for deferred delete.
        assert len(VideoPlayer._pending_cleanup) == 1
        assert VideoPlayer._pending_cleanup[0][1] is fake

    def test_video_player_module_does_not_call_next_source(self):
        """Grep-style guard: if anyone re-adds ``next_source()`` to
        ``video_player.py`` they should fail loudly so the rationale
        in the comment block gets re-read.  We only ban active call
        sites — comments and docstrings are allowed to mention it."""
        import inspect
        import video_player as _vp
        src = inspect.getsource(_vp)
        offending = [
            ln for ln in src.splitlines()
            if "next_source(" in ln and not ln.strip().startswith("#")
        ]
        assert offending == [], (
            "video_player.py contains a call to next_source — that "
            "races the pyglet media worker thread.  Offending lines:\n"
            + "\n  ".join(offending))
