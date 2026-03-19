"""Space Survivalcraft -- main entry point."""
from __future__ import annotations

import arcade

from constants import SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE
from splash_view import SplashView


def main() -> None:
    from settings import audio
    window = arcade.Window(audio.screen_width, audio.screen_height, SCREEN_TITLE)
    if audio.fullscreen:
        window.set_fullscreen(True)
    window.show_view(SplashView())
    arcade.run()


if __name__ == "__main__":
    main()
