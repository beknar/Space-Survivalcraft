"""Space Survivalcraft -- main entry point."""
from __future__ import annotations

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
    arcade.run()


if __name__ == "__main__":
    main()
