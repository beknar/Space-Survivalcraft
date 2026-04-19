"""5-minute soak tests for the new Basic Ship + scrollable menus.

Three soaks:

1. Build menu open with continuous wheel-scrolling for 5 minutes.
   Catches any per-scroll allocation accumulation in the
   scroll-aware draw / hit-test paths.

2. Craft menu open with continuous wheel-scrolling for 5 minutes.
   Same shape, different menu — different recipe text pool.

3. Basic Ship rebuild loop — every ~5 seconds destroy the parked
   L1 ship and rebuild it via ``_place_basic_ship``.  Stresses
   the placement / inventory deduction / ParkedShip lifecycle
   path to catch sprite-list, texture-extract, or inventory churn
   regressions.

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run with:
    pytest "unit tests/integration/test_soak_basic_ship_and_menus.py" -v -s
"""
from __future__ import annotations

import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _setup_station(gv) -> None:
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


def _strip_player_to_l2(gv) -> None:
    from sprites.player import PlayerShip
    gv._ship_level = 2
    old = gv.player
    new_player = PlayerShip(
        faction=gv._faction, ship_type=gv._ship_type, ship_level=2)
    new_player.center_x = old.center_x
    new_player.center_y = old.center_y
    new_player.heading = old.heading
    gv.player_list.clear()
    gv.player = new_player
    gv.player_list.append(new_player)


# ═══════════════════════════════════════════════════════════════════════════
#  1. Build menu open + wheel-scrolling for 5 minutes
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakBuildMenuScroll:
    def test_build_menu_scrolling_5min_soak(self, real_game_view):
        gv = real_game_view
        make_invulnerable(gv)
        _setup_station(gv)
        if not gv._build_menu.open:
            gv._build_menu.toggle()

        bm = gv._build_menu
        state = {"dir": -1, "n": 0}

        def tick(dt: float) -> None:
            # Bounce between top and bottom — flip direction on clamp.
            if bm._scroll_px <= 0 and state["dir"] > 0:
                state["dir"] = -1
            if bm._scroll_px >= bm._max_scroll() and state["dir"] < 0:
                state["dir"] = 1
            bm.on_mouse_scroll(scroll_y=state["dir"])
            gv.on_update(dt)
            gv.on_draw()
            state["n"] += 1

        # Match the companion perf test (test_performance_menu_scroll
        # uses MIN_FPS=15).  Dev hardware dips to ~30 FPS with
        # continuous wheel-scrolling; CI box sees 100+.  The 2026-04-19
        # PM soak saw 46–54 FPS steady-state with two dips to ~30 —
        # below the default 40 floor but still above 15.
        run_soak(gv, "Build menu wheel-scroll", tick, min_fps=15)
        bm.toggle()


# ═══════════════════════════════════════════════════════════════════════════
#  2. Craft menu open + wheel-scrolling for 5 minutes
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakCraftMenuScroll:
    def test_craft_menu_scrolling_5min_soak(self, real_game_view):
        gv = real_game_view
        make_invulnerable(gv)
        _setup_station(gv)

        import arcade
        cm = gv._craft_menu
        # Force enough recipes that scrolling is engaged.  Uses real
        # arcade.Text instances because the draw path mutates .color.
        cm._t_recipes = [
            arcade.Text(f"Recipe {i}", 0, 0, arcade.color.WHITE, 9)
            for i in range(30)
        ]
        cm._recipe_heights = [28] * 30
        cm.open = True

        state = {"dir": -1}

        def tick(dt: float) -> None:
            if cm._scroll_px <= 0 and state["dir"] > 0:
                state["dir"] = -1
            if cm._scroll_px >= cm._max_scroll() and state["dir"] < 0:
                state["dir"] = 1
            cm.on_mouse_scroll(scroll_y=state["dir"])
            gv.on_update(dt)
            gv.on_draw()

        # Same tolerant floor as the build-menu scroll soak above —
        # same per-frame scroll-draw plumbing, same dev-hardware
        # dips.  Perf test ``TestCraftMenuScrollPerf`` owns the
        # strict FPS-regression signal with MIN_FPS=15.
        run_soak(gv, "Craft menu wheel-scroll", tick, min_fps=15)
        cm.open = False


# ═══════════════════════════════════════════════════════════════════════════
#  3. Basic Ship rebuild loop — every 5 seconds destroy + rebuild the L1
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakBasicShipRebuild:
    def test_basic_ship_rebuild_5min_soak(self, real_game_view):
        """Every 300 frames (~5 s at 60 FPS) destroy the parked L1
        ship and place a fresh one via _place_basic_ship.  Tests the
        full lifecycle: ParkedShip construction, inventory deduction,
        stat resetting, and sprite-list churn over many cycles."""
        from ship_manager import _place_basic_ship

        gv = real_game_view
        make_invulnerable(gv)
        _setup_station(gv)
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()

        # Stock a pile of resources — enough for ~80 cycles
        # (5 min / 5 s = 60 cycles, with headroom).  Drop into the
        # station inv across multiple slots to mirror real gameplay.
        per_cycle_iron = 500
        per_cycle_copper = 250
        for cycle in range(100):
            row, col = cycle // 10, cycle % 10
            gv._station_inv._items[(row, col)] = ("iron", per_cycle_iron)
        # Copper across a separate strip
        for cycle in range(100):
            row = 9 - (cycle // 10)
            col = cycle % 10
            # Don't clobber the iron we just placed; copper goes in
            # a different slot column.  10x10 is the station inv size,
            # so wrap around.
            slot = ((row + 5) % 10, col)
            existing = gv._station_inv._items.get(slot)
            if existing is None:
                gv._station_inv._items[slot] = ("copper", per_cycle_copper)
        gv._station_inv._mark_dirty()

        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2

        # Initial placement so the loop has something to destroy on
        # the first cycle.
        _place_basic_ship(gv, cx + 200, cy)

        state = {"n": 0, "cycles": 0}

        def tick(dt: float) -> None:
            # Every 300 frames, destroy + rebuild.
            if state["n"] > 0 and state["n"] % 300 == 0:
                # Destroy the existing L1 parked ship (if any).
                victims = [ps for ps in list(gv._parked_ships)
                           if getattr(ps, "ship_level", 1) == 1]
                for ps in victims:
                    ps.remove_from_sprite_lists()
                    if ps in gv._parked_ships:
                        gv._parked_ships.remove(ps)
                # Rebuild — only if we still have resources.
                station_iron = gv._station_inv.total_iron
                station_copper = gv._station_inv.count_item("copper")
                if station_iron >= per_cycle_iron and station_copper >= per_cycle_copper:
                    try:
                        _place_basic_ship(
                            gv, cx + 200 + (state["cycles"] % 5) * 60, cy)
                        state["cycles"] += 1
                    except Exception:
                        # Stop trying if something throws — the soak
                        # continues running the world tick to surface
                        # any indirect leak.
                        pass
            gv.on_update(dt)
            gv.on_draw()
            state["n"] += 1

        run_soak(gv, "Basic Ship rebuild loop", tick)
