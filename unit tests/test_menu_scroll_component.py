"""Unit tests for the shared ``menu_scroll.ScrollState`` component.

These tests exercise the scroll logic without a GL context — the
component is pure state + math + a tiny draw path that's only
hit inside integration tests.
"""
from __future__ import annotations

import pytest

from menu_scroll import ScrollState, SCROLL_THUMB_MIN_H, SCROLL_W


# ── Basic state ───────────────────────────────────────────────────────────

class TestScrollStateBasics:
    def test_starts_at_zero(self):
        s = ScrollState()
        assert s.scroll_px == 0.0
        assert s.dragging is False

    def test_line_h_default_and_override(self):
        assert ScrollState().line_h == 28
        assert ScrollState(line_h=48).line_h == 48

    def test_needs_false_when_fits(self):
        s = ScrollState()
        assert s.needs(content_h=100, viewport_h=200) is False

    def test_needs_true_when_overflows(self):
        s = ScrollState()
        assert s.needs(content_h=500, viewport_h=200) is True

    def test_max_scroll_zero_when_fits(self):
        s = ScrollState()
        assert s.max_scroll(100, 200) == 0.0

    def test_max_scroll_overflow_amount(self):
        s = ScrollState()
        assert s.max_scroll(500, 200) == 300.0


# ── Clamping ───────────────────────────────────────────────────────────────

class TestClamp:
    def test_clamp_negative_to_zero(self):
        s = ScrollState()
        s.scroll_px = -50.0
        s.clamp(500, 200)
        assert s.scroll_px == 0.0

    def test_clamp_beyond_max(self):
        s = ScrollState()
        s.scroll_px = 10_000.0
        s.clamp(500, 200)
        assert s.scroll_px == 300.0

    def test_clamp_within_range_unchanged(self):
        s = ScrollState()
        s.scroll_px = 100.0
        s.clamp(500, 200)
        assert s.scroll_px == 100.0


# ── Mouse wheel ────────────────────────────────────────────────────────────

class TestOnWheel:
    def test_wheel_down_increases_scroll(self):
        s = ScrollState(line_h=30)
        s.on_wheel(scroll_y=-1, content_h=500, viewport_h=200)
        assert s.scroll_px == 30.0

    def test_wheel_up_decreases_scroll(self):
        s = ScrollState(line_h=30)
        s.scroll_px = 60.0
        s.on_wheel(scroll_y=1, content_h=500, viewport_h=200)
        assert s.scroll_px == 30.0

    def test_wheel_clamps_at_zero(self):
        s = ScrollState(line_h=30)
        s.scroll_px = 0.0
        s.on_wheel(scroll_y=5, content_h=500, viewport_h=200)
        assert s.scroll_px == 0.0

    def test_wheel_clamps_at_max(self):
        s = ScrollState(line_h=30)
        for _ in range(20):
            s.on_wheel(scroll_y=-1, content_h=500, viewport_h=200)
        assert s.scroll_px == 300.0

    def test_wheel_no_op_when_fits(self):
        s = ScrollState(line_h=30)
        s.on_wheel(scroll_y=-1, content_h=100, viewport_h=200)
        assert s.scroll_px == 0.0


# ── Scrollbar press / drag / release ───────────────────────────────────────

class TestOnPress:
    def test_press_on_thumb_starts_drag(self):
        s = ScrollState()
        track = (100, 0, 10, 200)
        thumb = s.thumb_rect(track, content_h=500)
        thx, thy, thw, thh = thumb
        assert s.on_press(
            thx + thw / 2, thy + thh / 2, track, 500) is True
        assert s.dragging is True

    def test_press_above_thumb_pages_up(self):
        """When scrolled to max, clicking above the thumb pages up."""
        s = ScrollState()
        track = (100, 0, 10, 200)
        s.scroll_px = 300.0
        thx, thy, thw, thh = s.thumb_rect(track, 500)
        # Click well above the thumb top.
        click_y = min(thy + thh + 30, track[1] + track[3] - 1)
        prev = s.scroll_px
        s.on_press(thx + thw / 2, click_y, track, 500)
        assert s.scroll_px < prev
        assert s.dragging is False

    def test_press_below_thumb_pages_down(self):
        s = ScrollState()
        track = (100, 0, 10, 200)
        s.scroll_px = 0.0
        thx, thy, thw, thh = s.thumb_rect(track, 500)
        click_y = max(thy - 30, track[1] + 1)
        s.on_press(thx + thw / 2, click_y, track, 500)
        assert s.scroll_px > 0
        assert s.dragging is False

    def test_press_outside_track_returns_false(self):
        s = ScrollState()
        track = (100, 0, 10, 200)
        assert s.on_press(500, 50, track, 500) is False
        assert s.dragging is False

    def test_press_when_no_scroll_needed_returns_false(self):
        """Press when content fits — scrollbar isn't drawn, so hit
        tests must short-circuit."""
        s = ScrollState()
        track = (100, 0, 10, 200)
        assert s.on_press(105, 50, track, content_h=100) is False


class TestOnReleaseAndMotion:
    def test_release_clears_dragging(self):
        s = ScrollState()
        s.dragging = True
        s.on_release()
        assert s.dragging is False

    def test_motion_without_drag_is_noop(self):
        s = ScrollState()
        s.scroll_px = 100.0
        track = (0, 0, 10, 200)
        s.on_motion(mouse_y=50, track_rect=track, content_h=500)
        assert s.scroll_px == 100.0

    def test_drag_then_motion_updates_scroll(self):
        s = ScrollState()
        track = (100, 0, 10, 200)
        thx, thy, thw, thh = s.thumb_rect(track, 500)
        anchor_y = thy + thh / 2
        s.on_press(thx + thw / 2, anchor_y, track, 500)
        assert s.dragging is True
        # Move down by 100 px → scroll_px increases.
        s.on_motion(
            mouse_y=anchor_y - 100, track_rect=track, content_h=500)
        assert s.scroll_px > 0


# ── Thumb sizing ───────────────────────────────────────────────────────────

class TestThumbRect:
    def test_thumb_fills_track_when_no_scroll(self):
        s = ScrollState()
        track = (100, 0, 10, 200)
        assert s.thumb_rect(track, content_h=100) == (100, 0, 10, 200)

    def test_thumb_height_minimum_enforced(self):
        """Very tall content → tiny proportional thumb, but clamped
        to SCROLL_THUMB_MIN_H so users can still grab it."""
        s = ScrollState()
        track = (0, 0, 10, 100)
        _, _, _, thumb_h = s.thumb_rect(track, content_h=100_000)
        assert thumb_h >= SCROLL_THUMB_MIN_H

    def test_scroll_module_exports_scroll_w(self):
        """The shared SCROLL_W constant is re-used by both build_menu
        and craft_menu — must remain a simple int."""
        assert isinstance(SCROLL_W, int)
        assert SCROLL_W > 0
