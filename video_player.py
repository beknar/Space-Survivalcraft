"""Video player for Space Survivalcraft — plays video files in the HUD status panel.

Uses pyglet's media player to decode video frames and render them as textures.
Requires FFmpeg to be installed on the system for video format support.
Only active when the game is in fullscreen or borderless display mode.
"""
from __future__ import annotations

import os
from typing import Optional

import arcade
import pyglet.media

from settings import audio, DISPLAY_WINDOWED

# Supported video extensions
_VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".webm", ".mov", ".wmv", ".flv", ".ogv"}

# Check if FFmpeg is available at import time
_FFMPEG_AVAILABLE = False
try:
    from pyglet.media.codecs.ffmpeg import FFmpegDecoder  # noqa: F401
    _FFMPEG_AVAILABLE = True
except ImportError:
    pass


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

    @property
    def is_fullscreen(self) -> bool:
        """True if the display mode allows video playback."""
        return audio.display_mode != DISPLAY_WINDOWED

    @staticmethod
    def ffmpeg_available() -> bool:
        """Return True if FFmpeg codec is available."""
        return _FFMPEG_AVAILABLE

    def play(self, filepath: str, volume: float = 0.35) -> bool:
        """Start playing a video file.  Returns True on success."""
        self.error = ""
        if not _FFMPEG_AVAILABLE:
            self.error = "FFmpeg not installed"
            print(f"[VideoPlayer] {self.error}")
            return False
        if not os.path.isfile(filepath):
            self.error = f"File not found: {filepath}"
            print(f"[VideoPlayer] {self.error}")
            return False
        self.stop()
        try:
            self._source = pyglet.media.load(filepath)
            if self._source.video_format is None:
                self.error = "No video stream found"
                print(f"[VideoPlayer] {self.error}")
                return False
            self._player = pyglet.media.Player()
            self._player.queue(self._source)
            self._player.volume = volume
            self._player.play()
            self._current_file = os.path.basename(filepath)
            self.active = True
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

    def update(self, volume: float) -> None:
        """Sync volume and check if playback ended (loop)."""
        if self._player is not None and self.active:
            self._player.volume = volume
            # Loop: if finished, seek back to start
            if not self._player.playing and self._source is not None:
                try:
                    self._player.seek(0.0)
                    self._player.play()
                except Exception:
                    pass

    def get_texture(self) -> Optional[pyglet.image.Texture]:
        """Return the current video frame texture, or None."""
        if self._player is None or not self.active:
            return None
        try:
            return self._player.get_texture()
        except Exception:
            return None

    @property
    def track_name(self) -> str:
        """Return the current video filename for display."""
        return self._current_file if self.active else ""

    def draw_in_hud(self, x: float, y: float, size: float) -> None:
        """Draw the current video frame at (x, y) with the given square size."""
        tex = self.get_texture()
        if tex is None:
            return
        # Convert pyglet texture to arcade-compatible drawing
        # pyglet textures can be drawn directly via OpenGL, but for simplicity
        # we use pyglet's blit which works within arcade's GL context
        try:
            tex.blit(x, y, width=int(size), height=int(size))
        except Exception:
            pass
