"""Space Survivalcraft -- main entry point."""
from __future__ import annotations

import arcade

from constants import SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE
from selection_view import SelectionView


def main() -> None:
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
    window.show_view(SelectionView())
    arcade.run()


if __name__ == "__main__":
    main()
