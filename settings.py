"""Global game settings for Space Survivalcraft.

Runtime-mutable volume levels and resolution shared across all views.
"""
from __future__ import annotations


class AudioSettings:
    """Singleton-like container for volume levels and display settings."""

    def __init__(self) -> None:
        self.music_volume: float = 0.35   # 0.0 – 1.0
        self.sfx_volume: float = 0.60     # 0.0 – 1.0
        self.screen_width: int = 1280
        self.screen_height: int = 800
        self.fullscreen: bool = False


# Module-level instance used everywhere
audio = AudioSettings()


def apply_resolution(window, width: int, height: int, fullscreen: bool) -> None:
    """Update constants and resize the window to the new resolution."""
    import constants
    constants.SCREEN_WIDTH = width
    constants.SCREEN_HEIGHT = height
    audio.screen_width = width
    audio.screen_height = height
    audio.fullscreen = fullscreen
    if fullscreen:
        window.set_fullscreen(True)
    else:
        window.set_fullscreen(False)
        window.set_size(width, height)
