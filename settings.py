"""Global game settings for Space Survivalcraft.

Runtime-mutable volume levels and resolution shared across all views.
Persistent configuration is stored in ``config.json`` in the project root.
"""
from __future__ import annotations

import json
import os


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
        self.video_dir: str = ""           # directory containing video files
        self.video_file: str = ""          # currently selected video filename
        self.show_fps: bool = False        # FPS counter toggle
        self.autoplay_ost: bool = True     # play OST music on game start
        self.character_name: str = ""      # selected character from characters/
        self.simulate_all_zones: bool = False  # tick inactive zones in background


# Module-level instance used everywhere
audio = AudioSettings()

# ── Persistent configuration file ────────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def save_config() -> None:
    """Write current settings to config.json."""
    data = {
        "music_volume": audio.music_volume,
        "sfx_volume": audio.sfx_volume,
        "video_dir": audio.video_dir,
        "show_fps": getattr(audio, "show_fps", False),
        "autoplay_ost": getattr(audio, "autoplay_ost", True),
        "character_name": audio.character_name,
        "simulate_all_zones": getattr(audio, "simulate_all_zones", False),
    }
    with open(_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def load_config() -> None:
    """Read config.json and apply settings to the audio singleton."""
    if not os.path.isfile(_CONFIG_PATH):
        return
    try:
        with open(_CONFIG_PATH, "r") as f:
            data = json.load(f)
        audio.music_volume = data.get("music_volume", audio.music_volume)
        audio.sfx_volume = data.get("sfx_volume", audio.sfx_volume)
        audio.video_dir = data.get("video_dir", audio.video_dir)
        audio.show_fps = data.get("show_fps", False)
        audio.autoplay_ost = data.get("autoplay_ost", True)
        audio.character_name = data.get("character_name", "")
        audio.simulate_all_zones = data.get("simulate_all_zones", False)
    except (json.JSONDecodeError, OSError):
        pass  # corrupt or unreadable — use defaults


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
