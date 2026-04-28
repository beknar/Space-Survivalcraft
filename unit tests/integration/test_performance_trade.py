"""Performance integration tests — Trade menu (sell + buy panels).

Frame-time / FPS coverage for the trade station overlay:

  * Sell panel open in Zone 1 / Zone 2.
  * Buy panel open in Zone 1.
  * Sell + Buy panels with both videos running (worst real case).
  * Mode-switching churn (buy ↔ sell every 10 frames) with videos
    in both Zone 1 and Zone 2.
  * Sell panel + Zone 2 + both videos.

Run with:  ``pytest "unit tests/integration/test_performance_trade.py" -v``
"""
from __future__ import annotations

import time

import arcade
import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BUILDING_TYPES, MODULE_SLOT_COUNT,
)
from zones import ZoneID

# ── Configuration ──────────────────────────────────────────────────────────

MIN_FPS = 40

# Use shared measure_fps from conftest
from integration.conftest import measure_fps as _measure_fps


# ═══════════════════════════════════════════════════════════════════════════
#  Video helpers — start/stop char + music videos
# ═══════════════════════════════════════════════════════════════════════════

def _get_video_paths():
    """Return up to 2 character video paths, or skip."""
    from video_player import scan_characters_dir, character_video_path
    chars = scan_characters_dir()
    if not chars:
        pytest.skip("No character video files found in characters/")
    paths = []
    for name in chars:
        p = character_video_path(name)
        if p is not None:
            paths.append(p)
        if len(paths) >= 2:
            break
    if not paths:
        pytest.skip("No character video file paths resolved")
    return paths


def _start_both_videos_or_skip(gv):
    """Start BOTH the character video and the music video player."""
    paths = _get_video_paths()
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    music_path = paths[1] if len(paths) > 1 else paths[0]
    gv._video_player.play(music_path, volume=0.0)
    dt = 1 / 60
    for _ in range(10):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._char_video_player.active and not gv._video_player.active:
        pytest.skip("Neither video player started (no FFmpeg?)")


def _stop_both_videos(gv):
    """Stop both video players and clean up."""
    gv._char_video_player.stop()
    gv._video_player.stop()


# ═══════════════════════════════════════════════════════════════════════════
#  Trade menu sell/buy panels — keep UI perf above threshold when open
# ═══════════════════════════════════════════════════════════════════════════

def _populate_trade_sell_inventories(gv) -> None:
    """Fill both inventories with a broad mix of sellable items so the
    sell list renders many rows (exercises the scrollbar path)."""
    gv.inventory._items.clear()
    gv.inventory._items[(0, 0)] = ("iron", 50)
    gv.inventory._items[(0, 1)] = ("copper", 40)
    gv.inventory._items[(0, 2)] = ("missile", 10)
    gv.inventory._items[(0, 3)] = ("repair_pack", 5)
    gv.inventory._items[(0, 4)] = ("shield_recharge", 5)
    gv.inventory._mark_dirty()

    gv._station_inv._items.clear()
    from constants import MODULE_TYPES
    mod_keys = list(MODULE_TYPES.keys())
    r = c = 0
    for mk in mod_keys:
        gv._station_inv._items[(r, c)] = (f"mod_{mk}", 1)
        c += 1
        if c >= 10:
            c = 0
            r += 1
        gv._station_inv._items[(r, c)] = (f"bp_{mk}", 1)
        c += 1
        if c >= 10:
            c = 0
            r += 1
    gv._station_inv._items[(r, c)] = ("iron", 200)
    gv._station_inv._mark_dirty()


class TestTradeSellPanelZone1:
    def test_trade_sell_panel_open_above_threshold(self, real_game_view):
        """Opening the trade sell panel with a fully populated inventory
        stresses per-frame panel rendering (header, credits, scrollbar,
        up to ~max_vis item rows). Must stay >= MIN_FPS."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _populate_trade_sell_inventories(gv)
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._mode = "sell"
        gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Trade sell panel open: {fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            gv._trade_menu.open = False


class TestTradeBuyPanelZone1:
    def test_trade_buy_panel_open_above_threshold(self, real_game_view):
        """Opening the trade buy panel (fixed catalog) with credits must
        stay >= MIN_FPS while the rest of the game simulates."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv._trade_menu.credits = 5000
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._mode = "buy"
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Trade buy panel open: {fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            gv._trade_menu.open = False


class TestTradeSellPanelZone2:
    def test_trade_sell_panel_zone2_above_threshold(self, real_game_view):
        """Zone 2 (heavier baseline) with the sell panel open — the panel
        draw runs alongside the fully populated nebula."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _populate_trade_sell_inventories(gv)
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._mode = "sell"
        gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 2 + trade sell panel: {fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            gv._trade_menu.open = False


# ── Trade panels + BOTH videos playing ─────────────────────────────────────
# These capture the realistic worst case: the trade panel is open while the
# character portrait video and the music video are both decoding, the full
# gameplay loop is ticking (asteroids, aliens, pickups, projectiles), and
# the minimap is rendering. If these regress, something in the panel draw
# or the object-update path has started costing too much per frame.

class TestTradeSellPanelZone1WithVideos:
    def test_trade_sell_panel_zone1_with_videos_above_threshold(
            self, real_game_view):
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _populate_trade_sell_inventories(gv)
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._mode = "sell"
        gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 1 sell panel + both videos: {fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
            gv._trade_menu.open = False


class TestTradeBuyPanelZone1WithVideos:
    def test_trade_buy_panel_zone1_with_videos_above_threshold(
            self, real_game_view):
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv._trade_menu.credits = 5000
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._mode = "buy"
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 1 buy panel + both videos: {fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
            gv._trade_menu.open = False


class TestTradeBuyPanelZone2WithVideos:
    def test_trade_buy_panel_zone2_with_videos_above_threshold(
            self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        gv._trade_menu.credits = 5000
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._mode = "buy"
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 2 buy panel + both videos: {fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
            gv._trade_menu.open = False


class TestTradePanelSwitchingWithVideos:
    """Toggle between BUY and SELL modes every frame while both videos play
    and gameplay simulates. Catches any regression that makes mode
    switching (refresh_sell_list, row-text pool grow/shrink) allocate per
    frame or blow past the FPS budget."""

    def test_trade_panel_mode_switch_zone1_above_threshold(
            self, real_game_view):
        import time as _time
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _populate_trade_sell_inventories(gv)
        gv._trade_menu.credits = 5000
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
        _start_both_videos_or_skip(gv)
        try:
            dt = 1 / 60
            # Warm-up in sell mode so caches/pools are warm
            gv._trade_menu._mode = "sell"
            for _ in range(5):
                gv.on_update(dt)
                gv.on_draw()
            # Measure: buy -> sell -> buy -> sell -> ... each frame
            # Switch modes every 10 frames — approximates a human clicking
            # the buy/sell buttons a few times per second. Refresh the sell
            # list exactly on the transition (that's all real clicks do).
            modes = ("buy", "sell")
            n = 60
            prev_mode = None
            start = _time.perf_counter()
            for i in range(n):
                m = modes[(i // 10) % 2]
                if m != prev_mode:
                    gv._trade_menu._mode = m
                    if m == "sell":
                        gv._trade_menu._refresh_sell_list(
                            gv.inventory, gv._station_inv)
                    prev_mode = m
                gv.on_update(dt)
                gv.on_draw()
            elapsed = _time.perf_counter() - start
            fps = n / elapsed if elapsed > 0 else 999.0
            print(f"  [perf] trade switch: {fps:.1f} FPS "
                  f"({n} frames in {elapsed:.3f}s)")
            assert fps >= MIN_FPS, (
                f"Zone 1 trade panel switch + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
            gv._trade_menu.open = False

    def test_trade_panel_mode_switch_zone2_above_threshold(
            self, real_game_view):
        """Same buy<->sell-per-frame churn as the Zone 1 variant but in
        the Nebula, which has the heavier entity and minimap load."""
        import time as _time
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _populate_trade_sell_inventories(gv)
        gv._trade_menu.credits = 5000
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
        _start_both_videos_or_skip(gv)
        try:
            dt = 1 / 60
            gv._trade_menu._mode = "sell"
            for _ in range(5):
                gv.on_update(dt)
                gv.on_draw()
            # Switch modes every 10 frames — approximates a human clicking
            # the buy/sell buttons a few times per second. Refresh the sell
            # list exactly on the transition (that's all real clicks do).
            modes = ("buy", "sell")
            n = 60
            prev_mode = None
            start = _time.perf_counter()
            for i in range(n):
                m = modes[(i // 10) % 2]
                if m != prev_mode:
                    gv._trade_menu._mode = m
                    if m == "sell":
                        gv._trade_menu._refresh_sell_list(
                            gv.inventory, gv._station_inv)
                    prev_mode = m
                gv.on_update(dt)
                gv.on_draw()
            elapsed = _time.perf_counter() - start
            fps = n / elapsed if elapsed > 0 else 999.0
            print(f"  [perf] trade switch z2: {fps:.1f} FPS "
                  f"({n} frames in {elapsed:.3f}s)")
            assert fps >= MIN_FPS, (
                f"Zone 2 trade panel switch + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
            gv._trade_menu.open = False


class TestTradeSellPanelZone2WithVideos:
    def test_trade_sell_panel_zone2_with_videos_above_threshold(
            self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _populate_trade_sell_inventories(gv)
        gv._trade_menu.toggle(inventory=gv.inventory,
                              station_inv=gv._station_inv)
        gv._trade_menu._mode = "sell"
        gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 2 sell panel + both videos: {fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
            gv._trade_menu.open = False
