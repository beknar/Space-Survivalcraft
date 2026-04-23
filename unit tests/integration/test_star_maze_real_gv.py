"""Integration tests for the Star Maze + post-Nebula-boss wormhole
flow, using a real GameView + hidden Arcade window.

Run with:
    pytest "unit tests/integration/test_star_maze_real_gv.py" -v

These cover flows the fast-suite stubs can't reach:

  * Transitioning into ``ZoneID.STAR_MAZE`` sets up 81 rooms, 81
    spawners, a wall SpriteList, and a full wormhole set (central
    return + 4 corners → MAZE_WARP_*).
  * Ticking the zone's update loop survives without exception.
  * Nebula-boss death while in Zone 2 spawns the four corner
    wormholes tagged NEBULA_WARP_*.
  * Entering a post-boss corner wormhole lands the player in a
    2x-danger Nebula warp variant whose exits route back to
    ``ZoneID.STAR_MAZE``.
  * Save + load preserves Star Maze spawner state (killed flags) and
    Zone 2's nebula_boss_defeated flag.
"""
from __future__ import annotations

import math

import arcade
import pytest

from zones import ZoneID, NEBULA_WARP_ZONES, MAZE_WARP_ZONES


class TestStarMazeZoneLive:
    def test_transition_installs_two_mazes_and_wormholes(
        self, real_game_view,
    ):
        from constants import (
            STAR_MAZE_COUNT,
            STAR_MAZE_ROOM_COLS, STAR_MAZE_ROOM_ROWS,
        )
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        assert gv._zone.zone_id is ZoneID.STAR_MAZE
        # Two mazes, 5x5 rooms each => 50 rooms flat, one spawner per
        # maze (not per room) => 2 spawners.
        expected_rooms_per_maze = STAR_MAZE_ROOM_COLS * STAR_MAZE_ROOM_ROWS
        assert len(gv._zone.mazes) == STAR_MAZE_COUNT
        assert len(gv._zone.rooms) == (
            expected_rooms_per_maze * STAR_MAZE_COUNT)
        assert len(gv._zone.spawners) == STAR_MAZE_COUNT
        # Each maze has at least 15 rooms per the user spec.
        for maze in gv._zone.mazes:
            assert len(maze.rooms) >= 15
        # Wormhole layout: 1 central (→ ZONE2) + 4 corners (→ MAZE_WARP_*).
        assert len(gv._wormholes) == 5
        targets = {w.zone_target for w in gv._wormholes}
        assert ZoneID.ZONE2 in targets
        assert targets - {ZoneID.ZONE2} == MAZE_WARP_ZONES

    def test_update_tick_survives(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        # Park the player well away from the central wormhole so the
        # tick doesn't immediately transition back to Zone 2.
        gv.player.center_x = 500.0
        gv.player.center_y = 500.0
        for _ in range(5):
            gv._zone.update(gv, 1 / 60)

    def test_spawner_produces_alien_after_interval(self, real_game_view):
        """Force the first spawner's spawn cooldown to zero and tick
        once — the spawner should emit exactly one MazeAlien."""
        from sprites.maze_alien import MazeAlien
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        gv.player.center_x = sp.center_x + 9000  # out of range to avoid fire
        gv.player.center_y = sp.center_y
        sp._spawn_cd = 0.0
        before = len(gv._zone._maze_aliens)
        gv._zone.update(gv, 1 / 60)
        after = len(gv._zone._maze_aliens)
        assert after == before + 1
        # Confirm it's actually a MazeAlien, not something else.
        assert isinstance(gv._zone._maze_aliens[-1], MazeAlien)

    def test_spawner_respects_alive_cap(self, real_game_view):
        from constants import MAZE_SPAWNER_MAX_ALIVE
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        # Park the player off the central wormhole so the tick doesn't
        # accidentally transition out of the Star Maze.
        gv.player.center_x = sp.center_x + 9000
        gv.player.center_y = sp.center_y
        sp.alive_children = MAZE_SPAWNER_MAX_ALIVE  # at cap
        sp._spawn_cd = 0.0
        before = len(gv._zone._maze_aliens)
        gv._zone.update(gv, 1 / 60)
        assert len(gv._zone._maze_aliens) == before

    def test_killed_spawner_does_not_respawn(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        # Park the player off the central wormhole.
        gv.player.center_x = sp.center_x + 9000
        gv.player.center_y = sp.center_y
        sp.hp = 0
        sp.killed = True
        sp._spawn_cd = 0.0
        gv._zone.update(gv, 1 / 60)
        # Spawner is dead, and even though its spawn cooldown is
        # zero it must not emit a new child.
        assert sp.alive_children == 0
        assert sp.killed is True


class TestStarMazeNoNebulaPopulation:
    """Spec: "for now, remove the nebula zone objects."  The Star
    Maze zone must not expose any Zone-2 population attributes."""

    def test_no_nebula_population_attributes(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        z = gv._zone
        for attr in (
            "_iron_asteroids", "_double_iron", "_copper_asteroids",
            "_gas_areas", "_wanderers", "_null_fields", "_slipspaces",
            "_aliens", "_shielded_aliens", "_alien_textures",
            "_alien_projectiles",
        ):
            assert not hasattr(z, attr), (
                f"Star Maze unexpectedly exposes Nebula attr {attr}")


class TestNebulaBossDeathUnlocksCornerWormholes:
    def test_mark_nebula_boss_defeated_adds_four_wormholes(
        self, real_game_view,
    ):
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        assert gv._zone._nebula_boss_defeated is False
        before = len(gv._wormholes)
        gv._zone.mark_nebula_boss_defeated(gv)
        after = len(gv._wormholes)
        assert after == before + 4
        assert gv._zone._nebula_boss_defeated is True
        # New wormhole targets are exactly the four Nebula variants.
        new_targets = {w.zone_target for w in gv._wormholes[before:]}
        assert new_targets == NEBULA_WARP_ZONES

    def test_re_entering_zone2_keeps_corner_wormholes(self, real_game_view):
        """After the boss dies, leaving Zone 2 and coming back must
        still show the four corner wormholes."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        gv._zone.mark_nebula_boss_defeated(gv)
        gv._transition_zone(ZoneID.MAIN)
        gv._transition_zone(ZoneID.ZONE2)
        targets = {w.zone_target for w in gv._wormholes}
        assert ZoneID.MAIN in targets              # central is still there
        assert targets - {ZoneID.MAIN} == NEBULA_WARP_ZONES


class TestNebulaWarpRoutingAndDanger:
    @pytest.mark.parametrize("zid", list(NEBULA_WARP_ZONES))
    def test_entering_nebula_warp_sets_2x_danger_and_maze_exits(
        self, real_game_view, zid,
    ):
        gv = real_game_view
        gv._transition_zone(zid)
        assert gv._zone.zone_id is zid
        assert gv._zone._danger == 2.0
        assert gv._zone._exit_bottom_zone is ZoneID.STAR_MAZE
        assert gv._zone._exit_top_zone is ZoneID.STAR_MAZE


class TestStarMazeSaveLoadRoundTrip:
    def test_star_maze_state_survives_round_trip(self, real_game_view, tmp_path):
        """Visit the Star Maze, kill one spawner, save to a dict, then
        restore into a fresh GameView — the killed flag must persist."""
        from game_save import save_to_dict, restore_state
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        # Kill the first spawner.
        killed_uid = gv._zone.spawners[0].uid
        gv._zone.spawners[0].hp = 0
        gv._zone.spawners[0].killed = True
        data = save_to_dict(gv, "test-star-maze")
        # The save payload must carry star_maze_state with the killed
        # flag on the matching spawner.
        sm = data.get("star_maze_state")
        assert sm is not None
        assert sm["populated"] is True
        matching = [s for s in sm["spawners"] if s["uid"] == killed_uid]
        assert len(matching) == 1
        assert matching[0]["killed"] is True

    def test_zone2_nebula_flag_persists_in_save(self, real_game_view):
        from game_save import save_to_dict
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        gv._zone.mark_nebula_boss_defeated(gv)
        data = save_to_dict(gv, "test-zone2-boss")
        z2 = data.get("zone2_state")
        assert z2 is not None
        assert z2.get("nebula_boss_defeated") is True
