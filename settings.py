"""Global game settings for Space Survivalcraft.

Runtime-mutable volume levels and resolution shared across all views.
"""
from __future__ import annotations


# Display mode constants
DISPLAY_WINDOWED = "windowed"
DISPLAY_FULLSCREEN = "fullscreen"
DISPLAY_BORDERLESS = "borderless"


class AudioSettings:
    """Singleton-like container for volume levels and display settings."""

    def __init__(self) -> None:
        self.music_volume: float = 0.35   # 0.0 – 1.0
        self.sfx_volume: float = 0.60     # 0.0 – 1.0
        self.screen_width: int = 1280
        self.screen_height: int = 800
        self.fullscreen: bool = False
        self.display_mode: str = DISPLAY_WINDOWED


# Module-level instance used everywhere
audio = AudioSettings()


def apply_resolution(
    window,
    width: int,
    height: int,
    fullscreen: bool = False,
    display_mode: str | None = None,
) -> None:
    """Update constants and resize the window to the new resolution.

    *display_mode* can be "windowed", "fullscreen", or "borderless".
    For backward compat, *fullscreen* bool is used if *display_mode* is None.
    """
    import constants
    constants.SCREEN_WIDTH = width
    constants.SCREEN_HEIGHT = height
    audio.screen_width = width
    audio.screen_height = height

    if display_mode is None:
        display_mode = DISPLAY_FULLSCREEN if fullscreen else DISPLAY_WINDOWED
    audio.display_mode = display_mode
    audio.fullscreen = display_mode != DISPLAY_WINDOWED

    if display_mode == DISPLAY_FULLSCREEN:
        window.set_fullscreen(True)
    elif display_mode == DISPLAY_BORDERLESS:
        # Borderless windowed: find the screen containing the window
        import pyglet.display as _disp
        screens = _disp.get_display().get_screens()
        # Pick screen containing window centre; fall back to primary
        screen = screens[0] if screens else None
        try:
            wx = window.get_location()[0] + window.width // 2
            wy = window.get_location()[1] + window.height // 2
            for s in screens:
                if (s.x <= wx < s.x + s.width and
                        s.y <= wy < s.y + s.height):
                    screen = s
                    break
        except Exception:
            pass
        window.set_fullscreen(True, screen=screen)
    else:
        # Windowed
        window.set_fullscreen(False)
        window.set_size(width, height)
