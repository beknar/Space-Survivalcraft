"""Space Survivalcraft -- main entry point."""
from __future__ import annotations

# Telemetry must initialise BEFORE arcade / pyglet load any C
# extensions so faulthandler is armed when the OpenGL context / ffmpeg
# / audio backends come up (those are where most silent crashes
# originate).  See telemetry.py for the full story.
from telemetry import init_crash_telemetry, mark_clean_shutdown
init_crash_telemetry()

import arcade
import pyglet.clock

from constants import SCREEN_TITLE
from splash_view import SplashView


def _patch_pyglet_clock() -> None:
    """Patch pyglet's clock to handle list-mutation RuntimeError.

    pyglet's FFmpeg video player schedules callbacks on the clock, and
    when Arcade's dispatch cycle modifies the same heap concurrently,
    pyglet raises 'list changed size during iteration'.  This patch
    wraps call_scheduled_functions to catch and retry on that error.
    """
    original = pyglet.clock.Clock.call_scheduled_functions

    def safe_call(self, dt):  # type: ignore
        try:
            return original(self, dt)
        except RuntimeError:
            return 0  # skip this tick; next frame will catch up

    pyglet.clock.Clock.call_scheduled_functions = safe_call


def main() -> None:
    _patch_pyglet_clock()
    from settings import audio, load_config
    load_config()
    window = arcade.Window(audio.screen_width, audio.screen_height, SCREEN_TITLE)
    if audio.fullscreen:
        window.set_fullscreen(True)
    window.show_view(SplashView())
    try:
        arcade.run()
    finally:
        # Normal quit path — mark the atexit flight-recorder entry as
        # clean so it's distinguishable from a crash on the next boot.
        mark_clean_shutdown()


if __name__ == "__main__":
    main()
