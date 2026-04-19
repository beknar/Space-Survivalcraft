"""Performance tests for the Build / Craft menu scroll path.

Both menus do extra per-frame work when scrollable:
  - Compute viewport rect + scrollbar geometry every draw
  - Iterate every menu/recipe row to skip non-visible ones
  - Draw the scrollbar track + thumb

These tests open each menu while ticking the full GameView and
assert the FPS measurement stays above ``MIN_FPS``.  A regression
in the scroll-aware draw path (e.g. accidental quadratic geometry
recomputation) shows up as a named failure here rather than a
vague "menu feels sluggish" report.

Run with:
    pytest "unit tests/integration/test_performance_menu_scroll.py" -v -s
"""
from __future__ import annotations

import time

import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID

# The menu draw path adds ~1 draw call per row × 15 rows (build) or
# 30+ rows (craft) on top of the world frame.  On the CI box the full
# scenario holds 100+ FPS; on a slow dev laptop it can dip to ~20.
# We use the same tolerant floor that ``test_soak_video_player.py``
# adopted for video soaks — fail clearly when the path COMPLETELY
# regresses (sub-15 FPS) but don't false-alarm on slow hardware.
MIN_FPS = 15

from integration.conftest import measure_fps as _measure_fps


def _setup_station(gv) -> None:
    """Drop a small station so the build menu shows realistic
    availability counts (Home + a couple of modules)."""
    from sprites.building import create_building
    if gv._zone.zone_id != ZoneID.MAIN:
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))
    for bt, ox in (("Service Module", 80), ("Repair Module", -80)):
        t_tex = gv._building_textures[bt]
        gv.building_list.append(create_building(
            bt, t_tex, cx + ox, cy, scale=0.5))


def _open_build_menu(gv) -> None:
    if not gv._build_menu.open:
        gv._build_menu.toggle()


def _open_craft_menu_with_many_recipes(gv) -> None:
    """Force the craft menu open with enough recipes that scrolling
    is engaged.  Uses real arcade.Text rows because the draw path
    actually mutates ``.color``."""
    import arcade
    cm = gv._craft_menu
    cm._t_recipes = [
        arcade.Text(f"Recipe {i}", 0, 0, arcade.color.WHITE, 9)
        for i in range(30)
    ]
    cm._recipe_heights = [28] * 30
    cm.open = True


# ═══════════════════════════════════════════════════════════════════════════
#  1. Build menu open + scrolling — does the scroll-aware draw stay fast?
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildMenuScrollPerf:
    def test_build_menu_open_with_scroll_above_threshold(
            self, real_game_view):
        gv = real_game_view
        _setup_station(gv)
        _open_build_menu(gv)
        # Scroll halfway through the list each measurement frame so the
        # scroll-position branch never short-circuits.
        gv._build_menu._scroll_px = max(1.0,
                                        gv._build_menu._max_scroll() / 2)
        fps = _measure_fps(gv)
        print(f"  [perf-menu-scroll] build menu mid-scroll: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Build menu mid-scroll: {fps:.1f} FPS < {MIN_FPS}")

    def test_build_menu_during_active_drag_above_threshold(
            self, real_game_view):
        gv = real_game_view
        _setup_station(gv)
        _open_build_menu(gv)
        # Simulate an in-flight thumb drag (extra draw branches).
        gv._build_menu._dragging_scrollbar = True
        gv._build_menu._scroll_px = max(1.0,
                                        gv._build_menu._max_scroll() / 3)
        fps = _measure_fps(gv)
        print(f"  [perf-menu-scroll] build menu drag: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Build menu drag-active: {fps:.1f} FPS < {MIN_FPS}")
        # Drop the drag so subsequent tests aren't affected.
        gv._build_menu._dragging_scrollbar = False


# ═══════════════════════════════════════════════════════════════════════════
#  2. Craft menu open + scrolling — same shape as build menu
# ═══════════════════════════════════════════════════════════════════════════

class TestCraftMenuScrollPerf:
    def test_craft_menu_open_with_scroll_above_threshold(
            self, real_game_view):
        gv = real_game_view
        _setup_station(gv)
        _open_craft_menu_with_many_recipes(gv)
        gv._craft_menu._scroll_px = max(1.0,
                                        gv._craft_menu._max_scroll() / 2)
        fps = _measure_fps(gv)
        print(f"  [perf-menu-scroll] craft menu mid-scroll: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Craft menu mid-scroll: {fps:.1f} FPS < {MIN_FPS}")

    def test_craft_menu_drag_above_threshold(self, real_game_view):
        gv = real_game_view
        _setup_station(gv)
        _open_craft_menu_with_many_recipes(gv)
        gv._craft_menu._dragging_scrollbar = True
        gv._craft_menu._scroll_px = max(1.0,
                                        gv._craft_menu._max_scroll() / 3)
        fps = _measure_fps(gv)
        print(f"  [perf-menu-scroll] craft menu drag: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Craft menu drag-active: {fps:.1f} FPS < {MIN_FPS}")
        gv._craft_menu._dragging_scrollbar = False


# ═══════════════════════════════════════════════════════════════════════════
#  3. Continuous wheel scrolling — measures the scroll-input pipeline
# ═══════════════════════════════════════════════════════════════════════════

class TestContinuousWheelScrollPerf:
    """Hammers the menu with a wheel event every frame.  Catches
    regressions in ``on_mouse_scroll`` (e.g. accidental layout
    rebuilds per scroll tick)."""

    def test_continuous_wheel_build_menu_above_threshold(
            self, real_game_view):
        gv = real_game_view
        _setup_station(gv)
        _open_build_menu(gv)
        bm = gv._build_menu
        dt = 1 / 60
        # Warmup
        for _ in range(10):
            gv.on_update(dt)
            gv.on_draw()
        n = 60
        t0 = time.perf_counter()
        for i in range(n):
            # Alternate up/down so we never max-clamp.
            bm.on_mouse_scroll(scroll_y=1 if (i % 2) else -1)
            gv.on_update(dt)
            gv.on_draw()
        elapsed = time.perf_counter() - t0
        fps = n / elapsed if elapsed > 0 else 999.0
        print(f"  [perf-menu-scroll] build menu wheel-spam: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Build menu wheel-spam: {fps:.1f} FPS < {MIN_FPS}")
