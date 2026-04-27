"""Tests for the Star Maze corner-wormhole boss-gating.

Per spec: the four corner wormholes in the Star Maze (chaining to
``MAZE_WARP_*`` zones) should NOT appear until the player has
defeated the Nebula boss inside the Star Maze.  The central return
wormhole back to Zone 2 is always available.
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


def _stub_gv():
    """Minimal GameView stub for setup/mark hooks."""
    return SimpleNamespace(
        _wormholes=[],
        _wormhole_list=arcade.SpriteList())


# ── Default state on construction ─────────────────────────────────────────


class TestStarMazeBossDefaultState:
    def test_default_flag_is_false(self):
        from zones.star_maze import StarMazeZone
        z = StarMazeZone()
        assert z._nebula_boss_defeated is False


# ── _build_corner_wormholes returns the expected 4 entries ────────────────


class TestBuildCornerWormholes:
    def test_returns_four_corner_wormholes_with_targets(self):
        from zones.star_maze import StarMazeZone
        from zones import ZoneID
        z = StarMazeZone()
        cwhs = z._build_corner_wormholes()
        assert len(cwhs) == 4
        targets = {cwh.zone_target for cwh in cwhs}
        assert targets == {
            ZoneID.MAZE_WARP_METEOR,
            ZoneID.MAZE_WARP_LIGHTNING,
            ZoneID.MAZE_WARP_GAS,
            ZoneID.MAZE_WARP_ENEMY,
        }


# ── mark_nebula_boss_defeated ─────────────────────────────────────────────


class TestMarkNebulaBossDefeated:
    def test_first_call_flips_flag_and_appends_corner_wormholes(self):
        from zones.star_maze import StarMazeZone
        z = StarMazeZone()
        gv = _stub_gv()
        # Start with just the central wormhole present (any sprite).
        from sprites.wormhole import Wormhole
        central = Wormhole(0.0, 0.0)
        gv._wormholes.append(central)
        gv._wormhole_list.append(central)
        z.mark_nebula_boss_defeated(gv)
        assert z._nebula_boss_defeated is True
        # Central + four corners.
        assert len(gv._wormholes) == 5
        assert len(gv._wormhole_list) == 5

    def test_second_call_is_no_op(self):
        from zones.star_maze import StarMazeZone
        z = StarMazeZone()
        gv = _stub_gv()
        z.mark_nebula_boss_defeated(gv)
        count_after_first = len(gv._wormholes)
        z.mark_nebula_boss_defeated(gv)
        assert len(gv._wormholes) == count_after_first


# ── Save/load round-trip ──────────────────────────────────────────────────


class TestStarMazeBossDefeatedPersists:
    def test_save_dict_carries_flag(self):
        """Star Maze save dict carries the flag so the unlock
        survives reloading the game."""
        # Construct a populated zone manually rather than going
        # through GameView.
        from zones.star_maze import StarMazeZone
        from game_save import _save_star_maze_state
        z = StarMazeZone()
        z._populated = True
        z._nebula_boss_defeated = True
        # Stub gv.zone-id so the save reads from this zone.
        from zones import ZoneID
        gv = SimpleNamespace(
            _zone=SimpleNamespace(zone_id=ZoneID.STAR_MAZE),
            _star_maze=z,
            building_list=[],
            _trade_station=None)
        # _save_star_maze_state reads gv._zone.zone_id; if it's
        # STAR_MAZE the buildings come from gv.building_list.  Patch
        # gv._zone to reference the same zone.
        gv._zone = z
        gv._zone.zone_id = ZoneID.STAR_MAZE
        z._spawners = arcade.SpriteList()
        z._fog_grid = []
        z._fog_revealed = 0
        blob = _save_star_maze_state(gv)
        assert blob is not None
        assert blob["nebula_boss_defeated"] is True

    def test_restore_picks_up_flag(self):
        from game_save import _restore_star_maze_full
        gv = SimpleNamespace(
            _star_maze=None)
        # Minimal state — populated False so the heavy regen path
        # is skipped, but the flag should still be restored before
        # that branch runs.
        state = {"world_seed": 0, "populated": False,
                  "nebula_boss_defeated": True,
                  "spawners": [], "fog_grid": None,
                  "buildings": [], "trade_station": None}
        _restore_star_maze_full(gv, state)
        assert gv._star_maze is not None
        assert gv._star_maze._nebula_boss_defeated is True
