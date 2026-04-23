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
    def test_transition_installs_rooms_walls_spawners_wormholes(
        self, real_game_view,
    ):
        from constants import STAR_MAZE_ROOM_COLS, STAR_MAZE_ROOM_ROWS
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        assert gv._zone.zone_id is ZoneID.STAR_MAZE
        expected_rooms = STAR_MAZE_ROOM_COLS * STAR_MAZE_ROOM_ROWS
        # One spawner per room.
        assert len(gv._zone.rooms) == expected_rooms
        assert len(gv._zone.spawners) == expected_rooms
        # Each room contributes 6-8 wall segments after door cuts.
        assert len(gv._zone.walls) >= expected_rooms * 6
        # Wormhole layout: 1 central (→ ZONE2) + 4 corners (→ MAZE_WARP_*).
        assert len(gv._wormholes) == 5
        targets = {w.zone_target for w in gv._wormholes}
        assert ZoneID.ZONE2 in targets
        assert targets - {ZoneID.ZONE2} == MAZE_WARP_ZONES

    def test_update_tick_survives(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        # Move the player to a known safe central location so the
        # wall-collision path has content to run against.
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2
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
        sp.alive_children = MAZE_SPAWNER_MAX_ALIVE  # at cap
        sp._spawn_cd = 0.0
        before = len(gv._zone._maze_aliens)
        gv._zone.update(gv, 1 / 60)
        # With the spawner already at cap, the update must not queue
        # a new child — should_spawn comes back False.
        assert len(gv._zone._maze_aliens) == before

    def test_killed_spawner_does_not_respawn(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        sp.hp = 0
        sp.killed = True
        sp._spawn_cd = 0.0
        gv._zone.update(gv, 1 / 60)
        # Spawner is dead, and even though its spawn cooldown is
        # zero it must not emit a new child.
        assert sp.alive_children == 0
        assert sp.killed is True


class TestStarMazeNebulaPopulation:
    """The Star Maze should carry the same Nebula-style population as
    Zone 2 but everything must stay outside the maze-room AABBs."""

    def test_counts_match_zone2_spec(self, real_game_view):
        from constants import (
            ASTEROID_COUNT, DOUBLE_IRON_COUNT, COPPER_ASTEROID_COUNT,
            GAS_AREA_COUNT, WANDERING_COUNT,
            Z2_SHIELDED_COUNT, Z2_FAST_COUNT,
            Z2_GUNNER_COUNT, Z2_RAMMER_COUNT,
            NULL_FIELD_COUNT, SLIPSPACE_COUNT,
        )
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        z = gv._zone
        assert len(z._iron_asteroids) == ASTEROID_COUNT
        assert len(z._double_iron) == DOUBLE_IRON_COUNT
        assert len(z._copper_asteroids) == COPPER_ASTEROID_COUNT
        assert len(z._gas_areas) == GAS_AREA_COUNT
        assert len(z._wanderers) == WANDERING_COUNT
        expected_aliens = (Z2_SHIELDED_COUNT + Z2_FAST_COUNT
                           + Z2_GUNNER_COUNT + Z2_RAMMER_COUNT)
        assert len(z._aliens) == expected_aliens
        assert len(z._null_fields) == NULL_FIELD_COUNT
        assert len(z._slipspaces) == SLIPSPACE_COUNT

    def test_no_population_inside_maze_rooms(self, real_game_view):
        """Every Nebula entity must spawn outside the 5×5 grid of
        maze rooms (plus the 40 px margin applied in the filter)."""
        from zones.maze_geometry import point_inside_any_room_interior
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        z = gv._zone
        rooms = z.rooms

        def _assert_outside(iter_, label):
            violations = [
                (e.center_x, e.center_y)
                for e in iter_
                if point_inside_any_room_interior(
                    e.center_x, e.center_y, rooms)
            ]
            assert not violations, (
                f"{label}: {len(violations)} entity/entities landed "
                f"inside a maze room (first: {violations[:3]})"
            )

        _assert_outside(z._iron_asteroids, "iron_asteroids")
        _assert_outside(z._double_iron, "double_iron")
        _assert_outside(z._copper_asteroids, "copper_asteroids")
        _assert_outside(z._wanderers, "wanderers")
        _assert_outside(z._aliens, "zone2_aliens")
        _assert_outside(z._gas_areas, "gas_areas")
        _assert_outside(z._slipspaces, "slipspaces")
        # null_fields are plain objects with center_x/center_y too.
        _assert_outside(z._null_fields, "null_fields")


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
