"""Regression test: a player base built in the Star Maze must
survive a save / load round-trip.

Pre-fix, ``StarMazeZone`` had no ``_building_stash`` mechanism (and
``_save_star_maze_state`` didn't persist buildings at all), so the
maze base disappeared the moment the player left the zone OR
reloaded a save made while in the zone.  This test exercises the
end-to-end save/load flow with a real GameView to lock in the fix.
"""
from __future__ import annotations

import arcade
import pytest


def _build_in_star_maze():
    """Spin up a GameView, jump to the Star Maze, drop a Home
    Station + a Turret in the maze, and return both the gv and
    the in-maze coordinates."""
    from game_view import GameView
    from zones import ZoneID
    from sprites.building import create_building
    gv = GameView(faction="Earth", ship_type="Cruiser", ship_level=1)
    gv._transition_zone(ZoneID.STAR_MAZE, "bottom")
    home_tex = gv._building_textures["Home Station"]
    turret_tex = gv._building_textures["Turret 1"]
    home = create_building("Home Station", home_tex,
                            6000.0, 6000.0, scale=0.5)
    turret = create_building("Turret 1", turret_tex,
                              6100.0, 6000.0,
                              laser_tex=gv._turret_laser_tex,
                              scale=0.5)
    gv.building_list.append(home)
    gv.building_list.append(turret)
    return gv


# ── Stash mechanism ──────────────────────────────────────────────────────

class TestStarMazeBuildingStash:
    def test_setup_then_teardown_stashes_buildings(self):
        gv = _build_in_star_maze()
        assert len(gv.building_list) == 2
        # Leave the zone — Star Maze.teardown should stash and reset.
        gv._zone.teardown(gv)
        # Active building list now empty…
        assert len(gv.building_list) == 0
        # …but the stash carries them.
        assert gv._zone._building_stash is not None
        assert len(gv._zone._building_stash["building_list"]) == 2

    def test_returning_restores_buildings_from_stash(self):
        gv = _build_in_star_maze()
        gv._zone.teardown(gv)
        # Re-entry uses the same persistent zone instance.
        gv._zone.setup(gv)
        assert len(gv.building_list) == 2
        # Stash consumed.
        assert gv._zone._building_stash is None


# ── Save / load round-trip ───────────────────────────────────────────────

class TestStarMazeBuildingSaveLoad:
    def test_save_then_load_preserves_maze_base(self):
        from game_view import GameView
        from game_save import save_to_dict, restore_state
        from sprites.building import HomeStation
        gv = _build_in_star_maze()
        # Sanity check before we save.
        assert any(isinstance(b, HomeStation)
                    for b in gv.building_list)
        data = save_to_dict(gv, "regression")
        # Build a fresh GameView in MAIN, then load the save —
        # mirrors the slot-load flow exactly.
        gv2 = GameView(faction="Earth", ship_type="Cruiser",
                        ship_level=1)
        restore_state(gv2, data)
        from zones import ZoneID
        assert gv2._zone.zone_id is ZoneID.STAR_MAZE
        # Maze base must be on the active building list, NOT lost
        # in MainZone's stash.
        homes = [b for b in gv2.building_list
                 if isinstance(b, HomeStation)]
        assert len(homes) == 1, (
            f"expected 1 Home Station in Star Maze, got "
            f"{len(homes)} — full list: {[type(b).__name__ for b in gv2.building_list]}"
        )
        assert len(gv2.building_list) == 2

    def test_save_state_includes_buildings_field(self):
        from game_save import _save_star_maze_state
        gv = _build_in_star_maze()
        sm_state = _save_star_maze_state(gv)
        assert sm_state is not None
        # New "buildings" list must round-trip the active maze base.
        assert "buildings" in sm_state
        assert len(sm_state["buildings"]) == 2
        types = sorted(b["type"] for b in sm_state["buildings"])
        assert types == ["Home Station", "Turret 1"]

    def test_save_after_leaving_reads_from_stash(self):
        # Player builds in Star Maze, leaves to Main, then saves.
        # The save must read buildings from Star Maze's _building_stash
        # (not gv.building_list, which now holds Zone 1 buildings).
        from game_save import _save_star_maze_state
        from zones import ZoneID
        gv = _build_in_star_maze()
        # Hop out via wormhole-style transition.
        gv._transition_zone(ZoneID.MAIN, "wormhole_return")
        # Active building list now holds Main Zone state, NOT maze.
        assert gv._zone.zone_id is ZoneID.MAIN
        sm_state = _save_star_maze_state(gv)
        assert sm_state is not None
        # Star Maze stash should still have the 2 buildings.
        assert len(sm_state["buildings"]) == 2
