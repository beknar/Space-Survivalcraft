"""Video player for Space Survivalcraft — plays video files in the HUD status panel.

Uses pyglet's media player to decode video frames and render them as textures.
Requires FFmpeg shared DLLs in the project root for video frame rendering.
Only active when the game is in fullscreen or borderless display mode.

Performance notes:
- Frames are decoded at the video's native framerate (~24-30 fps), not every game frame
- A single arcade.Texture is created once and updated in-place via atlas
- PIL image buffers are pre-allocated and reused to avoid GC pressure
- The pyglet player.texture property is polled instead of calling update_texture()
"""
from __future__ import annotations

import os
from typing import Optional

import ctypes
import time as _time

import arcade
import pyglet.media
from pyglet import gl

from settings import audio, DISPLAY_WINDOWED

# Supported video extensions — union of WMF and FFmpeg supported formats
_VIDEO_EXTS = {
    ".mp4", ".avi", ".mkv", ".webm", ".mov", ".wmv", ".flv", ".ogv",
    ".m4v", ".3gp", ".3g2", ".asf",
}

# Detect available decoders at import time
_HAS_WMF = False
_HAS_FFMPEG = False
_DECODER_NAME = "none"

try:
    from pyglet.media.codecs.wmf import WMFDecoder  # noqa: F401
    _HAS_WMF = True
    _DECODER_NAME = "WMF"
except ImportError:
    pass

try:
    from pyglet.media.codecs.ffmpeg import FFmpegDecoder  # noqa: F401
    _HAS_FFMPEG = True
    if _DECODER_NAME == "none":
        _DECODER_NAME = "FFmpeg"
except ImportError:
    pass

_VIDEO_AVAILABLE = _HAS_WMF or _HAS_FFMPEG


_CHARACTERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "characters")


def scan_characters_dir() -> list[str]:
    """Return sorted list of character names from characters/ directory.

    Each character is a single video file ``Name.mp4``.
    """
    if not os.path.isdir(_CHARACTERS_DIR):
        return []
    names = []
    for f in sorted(os.listdir(_CHARACTERS_DIR)):
        stem, ext = os.path.splitext(f)
        if ext.lower() in _VIDEO_EXTS:
            names.append(stem)
    return names


def character_video_path(name: str) -> str | None:
    """Return the full path to a character's video file, or None."""
    if not name or not os.path.isdir(_CHARACTERS_DIR):
        return None
    for f in os.listdir(_CHARACTERS_DIR):
        stem, ext = os.path.splitext(f)
        if stem == name and ext.lower() in _VIDEO_EXTS:
            return os.path.join(_CHARACTERS_DIR, f)
    return None


def scan_video_dir(directory: str) -> list[str]:
    """Return sorted list of video filenames in *directory*."""
    if not directory or not os.path.isdir(directory):
        return []
    files = []
    for f in sorted(os.listdir(directory)):
        if os.path.splitext(f)[1].lower() in _VIDEO_EXTS:
            files.append(f)
    return files


class VideoPlayer:
    """Manages video playback and renders the current frame as a texture.

    The video replaces the background music when active.  The video frame
    is drawn as a small square inside the HUD status panel.
    """

    _instance_counter: int = 0
    _frame_id: int = 0         # incremented each game frame
    _frame_converted: int = -1  # frame_id of last conversion (any instance)

    # Deferred player teardown — calling ``player.delete()`` synchronously
    # while its pyglet worker thread is still mid-packet has been observed
    # to heap-corrupt the process (Windows fatal 0xc0000374 inside
    # ``ffmpeg_unref_packet``).  We pause + zero volume + push the player
    # onto this queue and let the worker drain before we actually free
    # it two seconds later on the main thread.
    _pending_cleanup: list = []           # list[(deadline_monotonic, player)]
    _CLEANUP_DELAY_S: float = 2.0

    def __init__(self, convert_fps: float = 15.0) -> None:
        VideoPlayer._instance_counter += 1
        self._tex_hash = f"_vidframe_{VideoPlayer._instance_counter}"
        self._player: Optional[pyglet.media.Player] = None
        self._source: Optional[pyglet.media.Source] = None
        self.active: bool = False
        self._current_file: str = ""
        self._current_path: str = ""  # full path for re-loading on loop
        self.error: str = ""  # last error message for UI display
        self._cached_arc_tex: Optional[arcade.Texture] = None
        self._last_video_time: float = -1.0  # tracks player.time to detect new frames
        self._convert_interval: float = 1.0 / convert_fps
        self._convert_cooldown: float = 0.0
        self._blit_pending: bool = False  # True = blit done, readback next frame
        self._draw_ok_logged: bool = False
        self._draw_err_logged: bool = False
        self._frame_count: int = 0
        # Segment playback: single player, continuous loop, no seeking
        self._segment_mode: bool = False
        # Pre-built standby player for seamless loop restart
        self._standby_player: Optional[pyglet.media.Player] = None
        self._standby_source: Optional[pyglet.media.Source] = None
        self._standby_ready: bool = False
        self._standby_started: bool = False
        # GPU blit downscale resources
        self._read_fbo: int = 0
        self._draw_fbo: int = 0
        self._small_tex: int = 0
        self._small_w: int = 200
        self._small_h: int = 200  # square FBO; blit stretches to fit
        self._pixel_buf: Optional[ctypes.Array] = None

    @property
    def is_fullscreen(self) -> bool:
        """True if the display mode allows video playback."""
        return audio.display_mode != DISPLAY_WINDOWED

    @staticmethod
    def video_available() -> bool:
        """Return True if any video decoder is available."""
        return _VIDEO_AVAILABLE

    @staticmethod
    def decoder_name() -> str:
        """Return the name of the active video decoder."""
        return _DECODER_NAME

    def play(self, filepath: str, volume: float = 0.35) -> bool:
        """Start playing a video file.  Returns True on success."""
        self.error = ""
        if not _HAS_FFMPEG:
            self.error = "FFmpeg required for video display"
            print(f"[VideoPlayer] {self.error} (WMF only supports audio)")
            return False
        if not os.path.isfile(filepath):
            self.error = f"File not found"
            print(f"[VideoPlayer] File not found: {filepath}")
            return False
        # Tear down old player but keep cached texture for seamless transition
        self._stop_player()
        try:
            from pyglet.media.codecs.ffmpeg import FFmpegDecoder
            decoder = FFmpegDecoder()
            self._source = pyglet.media.load(filepath, decoder=decoder)
            if self._source.video_format is None:
                self.error = "No video stream in file"
                print(f"[VideoPlayer] {self.error}: {filepath}")
                return False
            self._player = pyglet.media.Player()
            self._player.queue(self._source)
            self._player.volume = volume
            self._player.play()
            self._current_file = os.path.basename(filepath)
            self._current_path = filepath
            self.active = True
            vf = self._source.video_format
            print(f"[VideoPlayer] Playing: {self._current_file} (decoder: FFmpeg)")
            print(f"[VideoPlayer] Video format: {vf.width}x{vf.height}")
            self._frame_count = 0
            self._draw_ok_logged = False
            self._draw_err_logged = False
            self._last_video_time = -1.0
            return True
        except Exception as e:
            self.error = str(e)
            print(f"[VideoPlayer] Error: {e}")
            self.active = False
            return False

    def swap(self, filepath: str, volume: float = 0.0) -> bool:
        """Switch to a new video file with minimal gap.

        Creates the new player and starts decoding *before* tearing down the
        old one, so FFmpeg has a head start on the first frame.  The cached
        arcade texture is preserved throughout.
        """
        if not _HAS_FFMPEG or not os.path.isfile(filepath):
            return False
        try:
            from pyglet.media.codecs.ffmpeg import FFmpegDecoder
            decoder = FFmpegDecoder()
            new_source = pyglet.media.load(filepath, decoder=decoder)
            if new_source.video_format is None:
                return False
            new_player = pyglet.media.Player()
            new_player.queue(new_source)
            new_player.volume = volume
            new_player.play()
        except Exception:
            return False
        # New player is decoding — now tear down the old one
        self._stop_player()
        self._player = new_player
        self._source = new_source
        self._current_file = os.path.basename(filepath)
        self._current_path = filepath
        self.active = True
        self._frame_count = 0
        self._last_video_time = -1.0
        return True

    def _stop_player(self) -> None:
        """Tear down the pyglet player only, preserving the cached texture.

        NOTE: the actual ``player.delete()`` call is deferred via
        ``_pending_cleanup`` to avoid racing pyglet's FFmpeg worker
        thread — see the class docstring for the heap-corruption
        rationale."""
        if self._player is not None:
            try:
                self._player.volume = 0.0
                self._player.pause()
            except Exception:
                pass
            try:
                while self._player.source:
                    self._player.next_source()
            except Exception:
                pass
            VideoPlayer._pending_cleanup.append(
                (_time.monotonic() + VideoPlayer._CLEANUP_DELAY_S,
                 self._player))
            self._player = None
        self._source = None
        self._last_video_time = -1.0

    @classmethod
    def _drain_pending_cleanup(cls) -> None:
        """Actually ``.delete()`` players whose quiescence window has
        passed.  Called from per-frame update paths so the cleanup runs
        on the main thread alongside pyglet's clock dispatch."""
        if not cls._pending_cleanup:
            return
        now = _time.monotonic()
        survivors = []
        for deadline, pl in cls._pending_cleanup:
            if now >= deadline:
                try:
                    pl.delete()
                except Exception:
                    pass
            else:
                survivors.append((deadline, pl))
        cls._pending_cleanup = survivors

    def stop(self) -> None:
        """Stop playback and release all resources including cached texture."""
        self._stop_player()
        self._segment_mode = False
        if self._standby_player is not None:
            # Defer via the same cleanup queue — a standby player that
            # was pre-built but never played still has an FFmpeg worker
            # and must be drained the same way.
            try:
                self._standby_player.volume = 0.0
                self._standby_player.pause()
            except Exception:
                pass
            VideoPlayer._pending_cleanup.append(
                (_time.monotonic() + VideoPlayer._CLEANUP_DELAY_S,
                 self._standby_player))
        self._standby_player = None
        self._standby_source = None
        self._standby_ready = False
        self._standby_started = False
        self.active = False
        self._current_file = ""
        self._current_path = ""
        # Free cached GL texture from atlas
        if self._cached_arc_tex is not None:
            try:
                atlas = arcade.get_window().ctx.default_atlas
                atlas.remove(self._cached_arc_tex)
            except Exception:
                pass
            self._cached_arc_tex = None
        self._last_video_time = -1.0

    def play_segments(self, filepath: str, volume: float = 0.0,
                      segment_duration: float = 10.0) -> bool:
        """Start playing a video as a continuous loop.

        Seeks once to a random position at startup (one-time cost), then
        plays forward continuously.  The ``_restart_for_loop`` mechanism
        handles looping back to the start when the source is exhausted.
        Zero seeks happen during gameplay — completely stall-free.
        """
        if not self.play(filepath, volume):
            return False
        dur = getattr(self._source, 'duration', None)
        if dur is None or dur <= segment_duration:
            self._segment_mode = True
            return True
        self._segment_mode = True
        # Play from 0:00 — no seek, no startup stall. The video content
        # varies naturally as it progresses through the file.
        return True

    def has_finished(self) -> bool:
        """Return True if the video has finished playing (source exhausted)."""
        if self._player is None or not self.active:
            return False
        if self._segment_mode:
            return False  # segment mode loops via update_volume
        try:
            return not self._player.playing
        except Exception:
            return False

    def update_volume(self, volume: float) -> None:
        """Sync volume; in segment mode, pre-build standby and loop seamlessly."""
        # Drain deferred cleanups (see ``update`` for the rationale).
        VideoPlayer._drain_pending_cleanup()
        if self._player is None or not self.active:
            return
        try:
            self._player.volume = volume
        except Exception:
            pass
        if self._segment_mode and self._current_path:
            # Kick off standby build when ~5 seconds from the end
            if not self._standby_started and not self._standby_ready:
                dur = getattr(self._source, 'duration', None)
                if dur and dur > 0:
                    try:
                        cur = self._player.time
                    except Exception:
                        cur = 0
                    if cur > dur - 5.0:
                        self._build_standby()
            # If bg source is loaded, finalize the player on main thread
            if self._standby_source is not None and self._standby_player is None and not self._standby_ready:
                # Source loaded by bg thread — create player on main thread
                # but DON'T play() yet to avoid decoder spike
                try:
                    p = pyglet.media.Player()
                    p.queue(self._standby_source)
                    p.volume = 0.0
                    self._standby_player = p
                    self._standby_ready = True
                except Exception:
                    self._standby_source = None
                    self._standby_started = False
            # Loop when source exhausted
            try:
                playing = self._player.playing
            except Exception:
                playing = True
            if not playing:
                self._restart_for_loop(volume)

    def _build_standby(self) -> None:
        """Load the next source in a background thread (file I/O only)."""
        self._standby_started = True
        filepath = self._current_path
        import threading

        def _worker():
            try:
                from pyglet.media.codecs.ffmpeg import FFmpegDecoder
                self._standby_source = pyglet.media.load(
                    filepath, decoder=FFmpegDecoder())
            except Exception:
                self._standby_source = None

        threading.Thread(target=_worker, daemon=True).start()

    def update(self, volume: float) -> None:
        """Sync volume and check if playback ended (loop)."""
        # Always drain the deferred cleanup queue — the whole queue
        # exists to let the FFmpeg worker thread quiesce before we free
        # a retired player, so this has to run on every frame.
        VideoPlayer._drain_pending_cleanup()
        if self._player is not None and self.active:
            try:
                self._player.volume = volume
                if not self._player.playing and self._current_path:
                    # Source exhausted — fully recreate player to avoid
                    # decoder artifacts that accumulate across re-queues
                    self._restart_for_loop(volume)
            except RuntimeError:
                pass
            except Exception:
                pass

    def _restart_for_loop(self, volume: float) -> None:
        """Swap in the standby player for seamless loop.

        If the standby is ready (pre-built ~5 s before end), the swap is
        just a reference assignment — no loading or player creation.
        Falls back to synchronous build if standby isn't ready.
        """
        path = self._current_path
        name = self._current_file
        if self._standby_ready and self._standby_player is not None:
            new_player = self._standby_player
            new_source = self._standby_source
            new_player.volume = volume
            new_player.play()
        else:
            # Fallback: synchronous build
            try:
                from pyglet.media.codecs.ffmpeg import FFmpegDecoder
                new_source = pyglet.media.load(path, decoder=FFmpegDecoder())
                new_player = pyglet.media.Player()
                new_player.queue(new_source)
                new_player.volume = volume
                new_player.play()
            except Exception:
                self.active = False
                return
        # Reset standby state
        self._standby_player = None
        self._standby_source = None
        self._standby_ready = False
        self._standby_started = False
        # Tear down old player
        self._stop_player()
        self._player = new_player
        self._source = new_source
        self._current_path = path
        self._current_file = name
        self._last_video_time = -1.0

    @property
    def track_name(self) -> str:
        """Return the current video filename for display."""
        return self._current_file if self.active else ""

    def _ensure_blit_fbo(self) -> None:
        """Lazily create the GL framebuffers used for GPU-side downscale."""
        if self._read_fbo:
            return
        # Read FBO (source video texture will be attached per-frame)
        fbo = gl.GLuint()
        gl.glGenFramebuffers(1, ctypes.byref(fbo))
        self._read_fbo = fbo.value
        # Small target texture
        tex = gl.GLuint()
        gl.glGenTextures(1, ctypes.byref(tex))
        tex_id = tex.value
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8,
                        self._small_w, self._small_h, 0,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self._small_tex = tex_id
        # Draw FBO (small target)
        dfbo = gl.GLuint()
        gl.glGenFramebuffers(1, ctypes.byref(dfbo))
        dfbo_id = dfbo.value
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, dfbo_id)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, tex_id, 0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        self._draw_fbo = dfbo_id
        # Pre-allocate pixel readback buffer
        self._pixel_buf = (gl.GLubyte * (self._small_w * self._small_h * 4))()

    def draw_in_hud(self, x: float, y: float, max_w: float,
                    aspect: float = 16 / 9) -> None:
        """Draw the current video frame at (x, y) fitting within max_w.

        *aspect* is width/height ratio (default 16:9).  Pass 1.0 for square.
        Uses GPU-side blit to downscale the video texture, then reads back
        only the small result (~90 KB instead of ~8 MB for 1440p sources).
        """
        if self._player is None or not self.active:
            return

        # Get the pyglet texture — this is the decoded video frame
        try:
            pyglet_tex = self._player.texture
        except Exception:
            pyglet_tex = None

        if pyglet_tex is None:
            self._frame_count += 1
            if self._frame_count == 60 and not self._draw_ok_logged:
                print(f"[VideoPlayer] Warning: texture is None after 60 frames")
            # Draw cached texture while waiting for first frame of new video
            if self._cached_arc_tex is not None:
                draw_w = int(max_w)
                draw_h = int(max_w / aspect)
                arcade.draw_texture_rect(
                    self._cached_arc_tex,
                    arcade.LBWH(x, y, draw_w, draw_h),
                )
            return

        # Throttle conversion to 15 fps max
        now = _time.monotonic()
        need_first = self._cached_arc_tex is None
        if not need_first and (now - self._convert_cooldown) < self._convert_interval:
            if self._cached_arc_tex is not None:
                draw_w = int(max_w)
                draw_h = int(max_w / aspect)
                arcade.draw_texture_rect(
                    self._cached_arc_tex,
                    arcade.LBWH(x, y, draw_w, draw_h),
                )
            return
        try:
            current_time = self._player.time
        except Exception:
            current_time = self._last_video_time
        new_frame = (current_time != self._last_video_time) or need_first
        # Only one VideoPlayer may convert per frame (GPU blit is expensive)
        if new_frame and VideoPlayer._frame_converted == VideoPlayer._frame_id:
            new_frame = False

        # Two-frame pipeline: blit on frame N, readback on frame N+1
        # This avoids GPU pipeline stalls from synchronous glReadPixels
        if self._blit_pending and VideoPlayer._frame_converted != VideoPlayer._frame_id:
            # Frame N+1: readback the previously blitted pixels
            VideoPlayer._frame_converted = VideoPlayer._frame_id
            self._blit_pending = False
            try:
                self._ensure_blit_fbo()
                prev_fbo = gl.GLint()
                gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING, ctypes.byref(prev_fbo))
                gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self._draw_fbo)
                gl.glReadPixels(0, 0, self._small_w, self._small_h,
                                gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, self._pixel_buf)
                gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, prev_fbo.value)

                from PIL import Image as PILImage
                display_img = PILImage.frombytes(
                    "RGBA", (self._small_w, self._small_h),
                    bytes(self._pixel_buf))
                if self._cached_arc_tex is None:
                    self._cached_arc_tex = arcade.Texture(
                        display_img, hit_box_algorithm=None, hash=self._tex_hash)
                    if not self._draw_ok_logged:
                        print(f"[VideoPlayer] First frame OK "
                              f"({self._small_w}x{self._small_h})")
                        self._draw_ok_logged = True
                else:
                    self._cached_arc_tex.image = display_img
                    try:
                        atlas = arcade.get_window().ctx.default_atlas
                        atlas.update_texture_image(self._cached_arc_tex)
                    except Exception:
                        pass
            except Exception as e:
                if not self._draw_err_logged:
                    print(f"[VideoPlayer] Readback error: {type(e).__name__}: {e}")
                    self._draw_err_logged = True

        if new_frame:
            # Frame N: blit only (async GPU operation, no readback stall)
            self._last_video_time = current_time
            self._convert_cooldown = now
            VideoPlayer._frame_converted = VideoPlayer._frame_id
            try:
                self._ensure_blit_fbo()
                src_w = pyglet_tex.width
                src_h = pyglet_tex.height
                prev_fbo = gl.GLint()
                gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING, ctypes.byref(prev_fbo))
                gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self._read_fbo)
                gl.glFramebufferTexture2D(
                    gl.GL_READ_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                    gl.GL_TEXTURE_2D, pyglet_tex.id, 0)
                gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, self._draw_fbo)
                gl.glBlitFramebuffer(
                    0, 0, src_w, src_h,
                    0, 0, self._small_w, self._small_h,
                    gl.GL_COLOR_BUFFER_BIT, gl.GL_LINEAR)
                gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, prev_fbo.value)
                self._blit_pending = True
            except Exception as e:
                if not self._draw_err_logged:
                    print(f"[VideoPlayer] Blit error: {type(e).__name__}: {e}")
                    self._draw_err_logged = True

        if self._cached_arc_tex is not None:
            draw_w = int(max_w)
            draw_h = int(max_w / aspect)
            arcade.draw_texture_rect(
                self._cached_arc_tex,
                arcade.LBWH(x, y, draw_w, draw_h),
            )
