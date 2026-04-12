"""Base class for non-pausing game overlays (craft, trade, build menus).

Provides shared boilerplate: open/close toggle, window reference, and
title + close-hint arcade.Text objects. Subclasses set ``_title_text``
and ``_close_text`` in their ``__init__`` before calling ``super()``.
"""
from __future__ import annotations

import arcade


class MenuOverlay:
    """Common base for right-side / centre overlay menus."""

    # Subclasses override these before calling super().__init__()
    _title_text: str = "MENU"
    _close_text: str = "ESC to close"

    def __init__(self) -> None:
        self.open: bool = False
        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None

        self._t_title = arcade.Text(
            self._title_text, 0, 0,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_close = arcade.Text(
            self._close_text, 0, 0,
            (120, 120, 120), 8, anchor_x="center",
        )
        self._t_line = arcade.Text("", 0, 0, arcade.color.WHITE, 9)
        self._t_btn = arcade.Text("", 0, 0, arcade.color.WHITE, 11,
                                  bold=True, anchor_x="center",
                                  anchor_y="center")

    def toggle(self, **kwargs) -> None:
        """Toggle open/close. Subclasses can override to accept extra args."""
        self.open = not self.open
