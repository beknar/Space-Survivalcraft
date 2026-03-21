"""Video player for Space Survivalcraft — plays video files in the HUD status panel.

Uses pyglet's media player to decode video frames and render them as textures.
On Windows, uses the built-in WMF (Windows Media Foundation) decoder for
MP4, AVI, WMV, and other formats without requiring FFmpeg.
Falls back to FFmpeg if WMF is unavailable.
Only active when the game is in fullscreen or borderless display mode.
"""
from __future__ import annotations

import os
import sys
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
        self._last_video_time: float = -1.0

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
            # Use FFmpeg decoder explicitly for video (WMF doesn't provide
            # video textures via get_texture, only audio)
            decoder = None
            if _HAS_FFMPEG:
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
            used_decoder = "FFmpeg" if decoder else _DECODER_NAME
            print(f"[VideoPlayer] Playing: {self._current_file} (decoder: {used_decoder})")
            print(f"[VideoPlayer] Video format: {vf.width}x{vf.height}")
            self._frame_count = 0
            self._draw_ok_logged = False
            self._draw_err_logged = False
            return True
        except Exception as e:
            self.error = str(e)
            print(f"[VideoPlayer] Error: {e}")
            self.active = False
            return False

    def stop(self) -> None:
        """Stop playback and release resources."""
        if self._player is not None:
            self._player.pause()
            self._player = None
        self._source = None
        self.active = False
        self._current_file = ""
        self._cached_arc_tex = None
        self._last_video_time = -1.0

    def update(self, volume: float) -> None:
        """Sync volume and check if playback ended (loop)."""
        if self._player is not None and self.active:
            try:
                self._player.volume = volume
                # Loop: if finished, seek back to start
                if not self._player.playing and self._source is not None:
                    self._player.seek(0.0)
                    self._player.play()
            except RuntimeError:
                pass  # pyglet clock list mutation — safe to skip one frame
            except Exception:
                pass

    def get_texture(self) -> Optional[pyglet.image.Texture]:
        """Return the current video frame texture, or None.

        Uses player.texture property (not get_texture method) and
        calls update_texture() first to force frame decode.
        """
        if self._player is None or not self.active:
            return None
        try:
            self._player.update_texture()
            return self._player.texture
        except RuntimeError:
            return None  # pyglet clock reentrancy — skip this frame
        except Exception:
            return None

    @property
    def track_name(self) -> str:
        """Return the current video filename for display."""
        return self._current_file if self.active else ""

    def draw_in_hud(self, x: float, y: float, max_w: float) -> None:
        """Draw the current video frame at (x, y) fitting within max_w.

        Maintains 16:9 aspect ratio.  Caches the arcade.Texture and only
        rebuilds it when the video time changes (new frame decoded).
        """
        pyglet_tex = self.get_texture()
        if pyglet_tex is None:
            self._frame_count = getattr(self, '_frame_count', 0) + 1
            if self._frame_count == 60:
                print(f"[VideoPlayer] Warning: texture is None after 60 frames")
                if self._player is not None:
                    print(f"[VideoPlayer] Player playing: {self._player.playing}, time: {self._player.time:.2f}")
            return

        # Only rebuild the arcade texture when a new video frame is available
        # (videos are typically 24-30fps, no need to convert every game frame)
        try:
            current_time = self._player.time if self._player else 0.0
        except RuntimeError:
            current_time = self._last_video_time
        last_time = getattr(self, '_last_video_time', -1.0)

        if current_time != last_time or self._cached_arc_tex is None:
            self._last_video_time = current_time
            try:
                from PIL import Image as PILImage
                img_data = pyglet_tex.get_image_data()
                raw = img_data.get_data("RGBA", img_data.width * 4)
                pil_img = PILImage.frombytes(
                    "RGBA", (img_data.width, img_data.height), raw,
                )
                # Downscale to max 200px wide for HUD display (saves GPU/CPU at 4K)
                if pil_img.width > 200:
                    ratio = 200 / pil_img.width
                    new_h = int(pil_img.height * ratio)
                    pil_img = pil_img.resize((200, new_h), PILImage.NEAREST)
                self._cached_arc_tex = arcade.Texture(pil_img)
                if not self._draw_ok_logged:
                    print(f"[VideoPlayer] First frame drawn OK ({img_data.width}x{img_data.height})")
                    self._draw_ok_logged = True
            except Exception as e:
                if not self._draw_err_logged:
                    print(f"[VideoPlayer] Draw error: {type(e).__name__}: {e}")
                    self._draw_err_logged = True
                return

        if self._cached_arc_tex is not None:
            draw_w = int(max_w)
            draw_h = int(max_w * 9 / 16)
            arcade.draw_texture_rect(
                self._cached_arc_tex,
                arcade.LBWH(x, y, draw_w, draw_h),
            )
