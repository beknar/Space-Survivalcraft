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
import sys
import time as _time
from typing import Optional

import arcade
import pyglet.media

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

    def __init__(self) -> None:
        self._player: Optional[pyglet.media.Player] = None
        self._source: Optional[pyglet.media.Source] = None
        self.active: bool = False
        self._current_file: str = ""
        self.error: str = ""  # last error message for UI display
        self._cached_arc_tex: Optional[arcade.Texture] = None
        self._last_tex_id: int = -1  # tracks which pyglet texture we last converted
        self._draw_ok_logged: bool = False
        self._draw_err_logged: bool = False
        self._frame_count: int = 0
        # Pre-allocated PIL buffer for frame conversion (avoids GC pressure)
        self._pil_buf: Optional[object] = None  # PIL Image, reused
        self._pil_buf_size: tuple[int, int] = (0, 0)
        # Performance tracking
        self._perf_converts: int = 0
        self._perf_skips: int = 0
        self._perf_timer: float = 0.0

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
        self.stop()
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
            self.active = True
            vf = self._source.video_format
            print(f"[VideoPlayer] Playing: {self._current_file} (decoder: FFmpeg)")
            print(f"[VideoPlayer] Video format: {vf.width}x{vf.height}")
            self._frame_count = 0
            self._draw_ok_logged = False
            self._draw_err_logged = False
            self._last_tex_id = -1
            self._perf_converts = 0
            self._perf_skips = 0
            self._perf_timer = _time.perf_counter()
            return True
        except Exception as e:
            self.error = str(e)
            print(f"[VideoPlayer] Error: {e}")
            self.active = False
            return False

    def stop(self) -> None:
        """Stop playback and release resources."""
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
            try:
                self._player.delete()
            except Exception:
                pass
            self._player = None
        self._source = None
        self.active = False
        self._current_file = ""
        # Free cached GL texture from atlas
        if self._cached_arc_tex is not None:
            try:
                atlas = arcade.get_window().ctx.default_atlas
                atlas.remove(self._cached_arc_tex)
            except Exception:
                pass
            self._cached_arc_tex = None
        self._last_tex_id = -1
        self._pil_buf = None
        self._pil_buf_size = (0, 0)

    def update(self, volume: float) -> None:
        """Sync volume and check if playback ended (loop)."""
        if self._player is not None and self.active:
            try:
                self._player.volume = volume
                if not self._player.playing and self._source is not None:
                    self._player.seek(0.0)
                    self._player.play()
            except RuntimeError:
                pass
            except Exception:
                pass

    @property
    def track_name(self) -> str:
        """Return the current video filename for display."""
        return self._current_file if self.active else ""

    def draw_in_hud(self, x: float, y: float, max_w: float) -> None:
        """Draw the current video frame at (x, y) fitting within max_w.

        Only converts a new frame when pyglet's texture object ID changes,
        meaning the FFmpeg decoder has decoded a new frame. Reuses a single
        arcade.Texture and pre-allocated PIL buffer to minimise allocations.
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
                if self._player is not None:
                    try:
                        print(f"[VideoPlayer] Player playing: {self._player.playing}, time: {self._player.time:.2f}")
                    except Exception:
                        pass
            return

        # Only convert when pyglet gives us a NEW texture object
        tex_id = id(pyglet_tex)
        if tex_id != self._last_tex_id or self._cached_arc_tex is None:
            self._last_tex_id = tex_id
            self._perf_converts += 1
            try:
                from PIL import Image as PILImage
                img_data = pyglet_tex.get_image_data()
                w, h = img_data.width, img_data.height
                raw = img_data.get_data("RGBA", w * 4)

                # Reuse PIL buffer if same size, otherwise allocate
                if self._pil_buf_size != (w, h):
                    self._pil_buf = PILImage.frombytes("RGBA", (w, h), raw)
                    self._pil_buf_size = (w, h)
                else:
                    self._pil_buf.frombytes(raw)

                # Downscale to max 200px wide
                if w > 200:
                    ratio = 200 / w
                    new_h = int(h * ratio)
                    display_img = self._pil_buf.resize((200, new_h), PILImage.NEAREST)
                else:
                    display_img = self._pil_buf

                if self._cached_arc_tex is None:
                    self._cached_arc_tex = arcade.Texture(
                        display_img,
                        hit_box_algorithm=None,
                        hash="_vidframe_singleton",
                    )
                    if not self._draw_ok_logged:
                        print(f"[VideoPlayer] First frame drawn OK ({w}x{h})")
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
                    print(f"[VideoPlayer] Draw error: {type(e).__name__}: {e}")
                    self._draw_err_logged = True
                return
        else:
            self._perf_skips += 1

        # Log performance every 10 seconds
        now = _time.perf_counter()
        if now - self._perf_timer >= 10.0:
            total = self._perf_converts + self._perf_skips
            if total > 0:
                print(f"[VideoPerf] 10s: converts={self._perf_converts} "
                      f"skips={self._perf_skips} "
                      f"ratio={self._perf_skips/total*100:.0f}% skipped")
            self._perf_converts = 0
            self._perf_skips = 0
            self._perf_timer = now

        if self._cached_arc_tex is not None:
            draw_w = int(max_w)
            draw_h = int(max_w * 9 / 16)
            arcade.draw_texture_rect(
                self._cached_arc_tex,
                arcade.LBWH(x, y, draw_w, draw_h),
            )
