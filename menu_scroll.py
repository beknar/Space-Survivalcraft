"""Shared scrollbar + wheel-scroll behaviour for menu overlays.

Both ``BuildMenu`` and ``CraftMenu`` had ~140 lines of duplicated
scroll plumbing (state + geometry + press/motion/release handlers
+ draw).  This module consolidates it into one ``ScrollState``
collaborator that menus compose.

Usage pattern:
    self._scroll = ScrollState(line_h=28)

    # Per-frame: the menu supplies the viewport dimensions since
    # those depend on its layout, which can change when the window
    # resizes.

    def on_mouse_scroll(self, scroll_y):
        self._scroll.on_wheel(scroll_y,
                              self._content_h(),
                              self._viewport_h())

    def on_mouse_press(self, x, y, ...):
        if self._scroll.on_press(x, y,
                                 self._scrollbar_track_rect(),
                                 self._content_h()):
            return None   # scrollbar consumed the click
        # ... normal row hit-testing ...

    def on_mouse_release(self, x, y):
        self._scroll.on_release()

    def on_mouse_motion(self, x, y):
        self._scroll.on_motion(
            y, self._scrollbar_track_rect(), self._content_h())

    def draw(self):
        # ... menu body ...
        self._scroll.draw(self._scrollbar_track_rect(), self._content_h())
"""
from __future__ import annotations

import arcade


SCROLL_W: int = 10
SCROLL_THUMB_MIN_H: int = 22


class ScrollState:
    """Scroll state + scrollbar geometry + mouse-event handling.

    All public methods take the current ``content_h`` (total
    scrollable content height in pixels) and/or a ``track_rect``
    ``(x, y, w, h)`` because those depend on the menu's layout and
    can change per frame (window resize, dynamic recipe list, etc.).
    """

    def __init__(self, line_h: int = 28) -> None:
        self.scroll_px: float = 0.0
        self.dragging: bool = False
        self._drag_anchor_y: float = 0.0
        self._drag_anchor_scroll: float = 0.0
        self.line_h: int = line_h

    # ── Queries ────────────────────────────────────────────────────────────

    def needs(self, content_h: float, viewport_h: float) -> bool:
        return content_h > viewport_h

    def max_scroll(self, content_h: float, viewport_h: float) -> float:
        return max(0.0, content_h - viewport_h)

    def clamp(self, content_h: float, viewport_h: float) -> None:
        self.scroll_px = max(
            0.0, min(self.max_scroll(content_h, viewport_h), self.scroll_px))

    def thumb_rect(self, track_rect: tuple[float, float, float, float],
                   content_h: float) -> tuple[float, float, float, float]:
        tx, ty, tw, th = track_rect
        max_scroll = self.max_scroll(content_h, th)
        if max_scroll <= 0:
            return tx, ty, tw, th
        ratio = th / (th + max_scroll)
        thumb_h = max(SCROLL_THUMB_MIN_H, int(th * ratio))
        thumb_y = ty + th - thumb_h - int(
            (th - thumb_h) * (self.scroll_px / max_scroll))
        return tx, thumb_y, tw, thumb_h

    # ── Event handlers ─────────────────────────────────────────────────────

    def on_wheel(self, scroll_y: float,
                 content_h: float, viewport_h: float) -> None:
        """Mouse-wheel tick.  ``scroll_y > 0`` reveals earlier
        content; ``< 0`` reveals later content.  No-op when the list
        fits in the viewport."""
        if not self.needs(content_h, viewport_h):
            return
        self.scroll_px -= scroll_y * self.line_h
        self.clamp(content_h, viewport_h)

    def on_release(self) -> None:
        self.dragging = False

    def on_motion(self, mouse_y: float,
                  track_rect: tuple[float, float, float, float],
                  content_h: float) -> None:
        """Drag-scroll while a thumb drag is in flight.  No-op
        otherwise."""
        if not self.dragging:
            return
        tx, ty, tw, th = track_rect
        max_scroll = self.max_scroll(content_h, th)
        if max_scroll <= 0:
            return
        delta = self._drag_anchor_y - mouse_y
        ratio = th / (th + max_scroll)
        thumb_h = max(SCROLL_THUMB_MIN_H, int(th * ratio))
        movable = max(1, th - thumb_h)
        self.scroll_px = (self._drag_anchor_scroll
                          + (delta / movable) * max_scroll)
        self.clamp(content_h, th)

    def on_press(self, x: float, y: float,
                 track_rect: tuple[float, float, float, float],
                 content_h: float) -> bool:
        """Handle a click on the scrollbar.  Returns True if the
        click hit the scrollbar (thumb drag started, or the track
        was page-clicked) so the caller knows to stop hit-testing
        the rows underneath it."""
        tx, ty, tw, th = track_rect
        if not self.needs(content_h, th):
            return False
        if not (tx <= x <= tx + tw and ty <= y <= ty + th):
            return False
        thx, thy, thw, thh = self.thumb_rect(track_rect, content_h)
        if thy <= y <= thy + thh:
            self.dragging = True
            self._drag_anchor_y = y
            self._drag_anchor_scroll = self.scroll_px
            return True
        # Click above thumb → page up; below → page down.
        page = max(self.line_h, th - self.line_h)
        if y > thy + thh:
            self.scroll_px -= page
        else:
            self.scroll_px += page
        self.clamp(content_h, th)
        return True

    # ── Drawing ───────────────────────────────────────────────────────────

    def draw(self, track_rect: tuple[float, float, float, float],
             content_h: float) -> None:
        tx, ty, tw, th = track_rect
        if not self.needs(content_h, th):
            return
        arcade.draw_rect_filled(
            arcade.LBWH(tx, ty, tw, th), (20, 30, 50, 220))
        thx, thy, thw, thh = self.thumb_rect(track_rect, content_h)
        color = ((180, 220, 255, 240) if self.dragging
                 else (120, 160, 220, 240))
        arcade.draw_rect_filled(
            arcade.LBWH(thx, thy, thw, thh), color)
