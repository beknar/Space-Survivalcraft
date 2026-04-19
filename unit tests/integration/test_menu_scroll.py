"""Integration tests for BuildMenu / CraftMenu scrolling.

Both menus support:
  - Mouse wheel — one row per click
  - Click on scrollbar TRACK above/below thumb — page jump
  - Click + drag the THUMB — smooth scroll

These tests need a real Arcade window because both menus instantiate
``arcade.Text`` in their constructors (no GL context = no font cache).
We use the session-scoped ``real_window`` fixture from conftest.

The actual draw path is exercised indirectly when the menus are open
during the perf/soak combo tests; here we just lock the public scroll
API + the geometry math.
"""
from __future__ import annotations

import pytest


# ── BuildMenu scrolling ─────────────────────────────────────────────────────

class TestBuildMenuScroll:
    @pytest.fixture
    def menu(self, real_window):
        from build_menu import BuildMenu
        bm = BuildMenu()
        bm.open = True
        bm._update_layout()
        return bm

    def test_scrollbar_appears_when_content_exceeds_panel(self, menu, real_window):
        """With 15 menu rows × 48 px = 720 px of content, the panel
        capped to ~92% of an 600-px window must scroll.  If the
        window is taller than the content, this test would not apply."""
        # Tall enough content vs whatever the test window happens to be.
        if menu._content_h <= menu._viewport_rect()[3]:
            pytest.skip("test window taller than full menu content")
        assert menu._needs_scrollbar() is True

    def test_no_scrollbar_when_content_fits(self, menu):
        menu._content_h = 10
        menu._update_layout()
        assert menu._needs_scrollbar() is False

    def test_mouse_wheel_scrolls_down(self, menu):
        if not menu._needs_scrollbar():
            pytest.skip("scroll not needed in this window")
        before = menu._scroll_px
        menu.on_mouse_scroll(scroll_y=-1)
        assert menu._scroll_px > before

    def test_mouse_wheel_scrolls_up(self, menu):
        if not menu._needs_scrollbar():
            pytest.skip("scroll not needed in this window")
        menu.on_mouse_scroll(scroll_y=-3)
        prev = menu._scroll_px
        menu.on_mouse_scroll(scroll_y=1)
        assert menu._scroll_px < prev

    def test_scroll_clamps_at_zero(self, menu):
        menu._scroll_px = 0.0
        menu.on_mouse_scroll(scroll_y=10)
        assert menu._scroll_px == 0.0

    def test_scroll_clamps_at_max(self, menu):
        if not menu._needs_scrollbar():
            pytest.skip("scroll not needed in this window")
        for _ in range(50):
            menu.on_mouse_scroll(scroll_y=-10)
        assert menu._scroll_px == menu._max_scroll()

    def test_thumb_drag_sets_scroll_position(self, menu):
        if not menu._needs_scrollbar():
            pytest.skip("scroll not needed in this window")
        menu._scroll_px = 0.0
        thx, thy, thw, thh = menu._scrollbar_thumb_rect()
        anchor_y = thy + thh / 2
        assert menu._handle_scrollbar_press(thx + thw / 2, anchor_y) is True
        assert menu._dragging_scrollbar is True
        # Drag DOWN (mouse moves to lower y) increases scroll_px.
        menu.on_mouse_motion(thx + thw / 2, anchor_y - 100)
        assert menu._scroll_px > 0
        menu.on_mouse_release(thx + thw / 2, anchor_y - 100)
        assert menu._dragging_scrollbar is False

    def test_track_click_above_thumb_scrolls_up_by_page(self, menu):
        if not menu._needs_scrollbar():
            pytest.skip("scroll not needed in this window")
        menu._scroll_px = menu._max_scroll()
        prev = menu._scroll_px
        tx, ty, tw, th = menu._scrollbar_rect()
        thx, thy, thw, thh = menu._scrollbar_thumb_rect()
        click_y = min(thy + thh + 30, ty + th - 1)
        menu._handle_scrollbar_press(tx + tw / 2, click_y)
        assert menu._scroll_px < prev
        assert menu._dragging_scrollbar is False

    def test_track_click_below_thumb_scrolls_down_by_page(self, menu):
        if not menu._needs_scrollbar():
            pytest.skip("scroll not needed in this window")
        menu._scroll_px = 0.0
        tx, ty, tw, th = menu._scrollbar_rect()
        thx, thy, thw, thh = menu._scrollbar_thumb_rect()
        click_y = max(thy - 30, ty + 1)
        menu._handle_scrollbar_press(tx + tw / 2, click_y)
        assert menu._scroll_px > 0
        assert menu._dragging_scrollbar is False

    def test_row_y_changes_with_scroll(self, menu):
        if not menu._needs_scrollbar():
            pytest.skip("scroll not needed in this window")
        from build_menu import _MENU_ORDER
        _, y0, _, _ = menu._item_rect(len(_MENU_ORDER) - 1)
        menu._scroll_px = 100.0
        _, y1, _, _ = menu._item_rect(len(_MENU_ORDER) - 1)
        assert y1 != y0


# ── CraftMenu scrolling ────────────────────────────────────────────────────

class TestCraftMenuScroll:
    @pytest.fixture
    def menu_many(self, real_window):
        from craft_menu import CraftMenu
        cm = CraftMenu()
        cm._t_recipes = list(range(30))
        cm._recipe_heights = [28] * 30
        return cm

    @pytest.fixture
    def menu_few(self, real_window):
        from craft_menu import CraftMenu
        cm = CraftMenu()
        cm._t_recipes = list(range(2))
        cm._recipe_heights = [28, 28]
        return cm

    def test_scrollbar_appears_when_many_recipes(self, menu_many):
        assert menu_many._needs_scrollbar() is True

    def test_no_scrollbar_when_few_recipes(self, menu_few):
        assert menu_few._needs_scrollbar() is False

    def test_mouse_wheel_scrolls(self, menu_many):
        menu_many.open = True
        before = menu_many._scroll_px
        menu_many.on_mouse_scroll(scroll_y=-1)
        assert menu_many._scroll_px > before

    def test_wheel_noop_when_closed(self, menu_many):
        menu_many.open = False
        menu_many.on_mouse_scroll(scroll_y=-5)
        assert menu_many._scroll_px == 0.0

    def test_wheel_noop_when_no_scroll_needed(self, menu_few):
        menu_few.open = True
        menu_few.on_mouse_scroll(scroll_y=-5)
        assert menu_few._scroll_px == 0.0

    def test_scroll_clamps_at_max(self, menu_many):
        menu_many.open = True
        for _ in range(50):
            menu_many.on_mouse_scroll(scroll_y=-10)
        assert menu_many._scroll_px == menu_many._max_scroll()

    def test_thumb_drag_sets_scroll(self, menu_many):
        menu_many.open = True
        menu_many._scroll_px = 0.0
        thx, thy, thw, thh = menu_many._scrollbar_thumb_rect()
        anchor_y = thy + thh / 2
        assert menu_many._handle_scrollbar_press(thx + thw / 2, anchor_y) is True
        assert menu_many._dragging_scrollbar is True
        menu_many.on_mouse_motion(thx + thw / 2, anchor_y - 80)
        assert menu_many._scroll_px > 0
        menu_many.on_mouse_release(thx + thw / 2, anchor_y - 80)
        assert menu_many._dragging_scrollbar is False
