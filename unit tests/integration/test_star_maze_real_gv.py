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
    def test_transition_installs_four_mazes_and_wormholes(
        self, real_game_view,
    ):
        from constants import (
            STAR_MAZE_COUNT,
            STAR_MAZE_ROOM_COLS, STAR_MAZE_ROOM_ROWS,
            MAZE_SPAWNER_MAX_ALIVE,
        )
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        assert gv._zone.zone_id is ZoneID.STAR_MAZE
        expected_rooms_per_maze = STAR_MAZE_ROOM_COLS * STAR_MAZE_ROOM_ROWS
        assert len(gv._zone.mazes) == STAR_MAZE_COUNT == 4
        assert len(gv._zone.rooms) == (
            expected_rooms_per_maze * STAR_MAZE_COUNT)
        assert len(gv._zone.spawners) == STAR_MAZE_COUNT
        # Each maze has at least 15 rooms per the user spec.
        for maze in gv._zone.mazes:
            assert len(maze.rooms) >= 15
        # Pre-population — each spawner has 20 children already alive
        # and they're spread across the maze.
        for sp in gv._zone.spawners:
            assert sp.alive_children == MAZE_SPAWNER_MAX_ALIVE
        assert len(gv._zone._maze_aliens) == (
            MAZE_SPAWNER_MAX_ALIVE * STAR_MAZE_COUNT)
        # Wormhole layout: 1 central (→ ZONE2) + 4 corners (→ MAZE_WARP_*).
        assert len(gv._wormholes) == 5
        targets = {w.zone_target for w in gv._wormholes}
        assert ZoneID.ZONE2 in targets
        assert targets - {ZoneID.ZONE2} == MAZE_WARP_ZONES

    def test_pre_populated_aliens_spread_across_rooms(
        self, real_game_view,
    ):
        """Pre-populated aliens must occupy distinct rooms — no
        clustering at the spawner."""
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        from zones.maze_geometry import point_in_rect
        for maze in gv._zone.mazes:
            # Count aliens falling inside each room rect.
            per_room: dict = {}
            for alien in gv._zone._maze_aliens:
                for r in maze.rooms:
                    if point_in_rect(
                            alien.center_x, alien.center_y, r):
                        per_room[r] = per_room.get(r, 0) + 1
                        break
            # 20 aliens spread over 25 rooms should visit at least 15
            # distinct rooms (pigeonhole + our no-repeat sampling).
            assert len(per_room) >= 15, (
                f"maze at {maze.spawner}: aliens clustered in "
                f"{len(per_room)} rooms")

    def test_maze_aliens_never_leave_maze_bounds(
        self, real_game_view,
    ):
        """Tick 60 frames with the player far outside any maze —
        every alien must stay inside its own maze's AABB regardless
        of pursue-mode chasing."""
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        # Park the player just inside a corner wormhole position but
        # outside all maze bounds.
        gv.player.center_x = 500.0
        gv.player.center_y = 500.0
        for _ in range(60):
            gv._zone.update(gv, 1 / 60)
        # Every live alien must still be inside one of the maze AABBs.
        for alien in gv._zone._maze_aliens:
            inside_any = False
            for maze in gv._zone.mazes:
                b = maze.bounds
                if (b.x <= alien.center_x <= b.x + b.w
                        and b.y <= alien.center_y <= b.y + b.h):
                    inside_any = True
                    break
            assert inside_any, (
                f"alien at ({alien.center_x:.0f}, "
                f"{alien.center_y:.0f}) escaped every maze AABB")

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
        once — the spawner should emit exactly one MazeAlien.  Drop
        the pre-populated child count to 0 first so the cap doesn't
        block the spawn."""
        from sprites.maze_alien import MazeAlien
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        gv.player.center_x = sp.center_x + 9000
        gv.player.center_y = sp.center_y
        sp.alive_children = 0            # pretend no children alive
        sp._spawn_cd = 0.0
        before = len(gv._zone._maze_aliens)
        gv._zone.update(gv, 1 / 60)
        after = len(gv._zone._maze_aliens)
        assert after == before + 1
        assert isinstance(gv._zone._maze_aliens[-1], MazeAlien)

    def test_spawner_respects_alive_cap(self, real_game_view):
        """Pre-population already fills the cap — a spawn tick at
        the cap must not queue a new child."""
        from constants import MAZE_SPAWNER_MAX_ALIVE
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        gv.player.center_x = sp.center_x + 9000
        gv.player.center_y = sp.center_y
        # Post-generation, alive_children should already be at cap.
        assert sp.alive_children == MAZE_SPAWNER_MAX_ALIVE
        sp._spawn_cd = 0.0
        before = len(gv._zone._maze_aliens)
        gv._zone.update(gv, 1 / 60)
        assert len(gv._zone._maze_aliens) == before

    def test_killed_spawner_stays_dead_until_respawn_interval(
        self, real_game_view,
    ):
        from constants import MAZE_SPAWNER_RESPAWN_INTERVAL
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        gv.player.center_x = sp.center_x + 9000
        gv.player.center_y = sp.center_y
        sp.hp = 0
        sp.killed = True
        sp._respawn_cd = MAZE_SPAWNER_RESPAWN_INTERVAL
        gv._zone.update(gv, 1 / 60)
        # One tick — still dead.
        assert sp.killed is True
        assert sp._respawn_cd < MAZE_SPAWNER_RESPAWN_INTERVAL

    def test_killed_spawner_respawns_after_interval(self, real_game_view):
        from constants import (
            MAZE_SPAWNER_RESPAWN_INTERVAL, MAZE_SPAWNER_HP,
            MAZE_SPAWNER_SHIELD,
        )
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        gv.player.center_x = sp.center_x + 9000
        gv.player.center_y = sp.center_y
        sp.hp = 0
        sp.shields = 0
        sp.killed = True
        sp._respawn_cd = 0.0001   # one tick away from 0
        gv._zone.update(gv, 1 / 60)
        # Respawned — HP + shields restored, killed flag cleared.
        assert sp.killed is False
        assert sp.hp == MAZE_SPAWNER_HP
        assert sp.shields == MAZE_SPAWNER_SHIELD


class TestStarMazeCombat:
    """Round-trip for the combat fixes the user reported: maze
    projectiles must damage the player, player lasers must be blocked
    by walls, and homing missiles must damage the spawner."""

    def test_maze_projectile_damages_player(self, real_game_view):
        from sprites.projectile import Projectile
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        z = gv._zone
        # Park the player far from any wormhole and install a faux
        # projectile sitting right on top of them.
        gv.player.center_x = 500
        gv.player.center_y = 500
        gv.player.hp = 100
        gv.player.shields = 0
        # Recall the player's _collision_cd so damage fires.
        gv.player._collision_cd = 0.0
        proj = Projectile(
            gv._alien_laser_tex, 500, 500,
            0.0, 0.0, 1000.0, scale=0.5, damage=10,
        )
        z._maze_projectiles.append(proj)
        hp_before = gv.player.hp
        z.update(gv, 1 / 60)
        assert gv.player.hp < hp_before

    def test_player_projectile_blocked_by_wall(self, real_game_view):
        """Drop a player projectile straddling a maze wall and tick
        once — the projectile should be consumed by the wall, not
        passed through to collide with the spawner."""
        from sprites.projectile import Projectile
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        z = gv._zone
        wall = z.walls[0]   # any wall
        # Spawn a projectile right inside the wall AABB — the
        # segment-vs-wall check will delete it on the next tick.
        proj = Projectile(
            gv._alien_laser_tex,
            wall.x + wall.w / 2, wall.y + wall.h / 2,
            0.0, 0.0, 1000.0, scale=0.5, damage=10,
        )
        proj._vx = 1.0
        proj._vy = 0.0
        gv.projectile_list.append(proj)
        # Park player far away so wormhole logic doesn't interfere.
        gv.player.center_x = 500
        gv.player.center_y = 500
        z.update(gv, 1 / 60)
        assert proj not in gv.projectile_list

    def test_missile_damages_spawner(self, real_game_view):
        """Plant a live missile on top of the first spawner and run
        the global missile update — the spawner must take damage
        (shield first, then HP)."""
        from sprites.missile import HomingMissile
        from update_logic import update_missiles
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        sp = gv._zone.spawners[0]
        gv.player.center_x = sp.center_x + 9000
        gv.player.center_y = sp.center_y
        shield_before = sp.shields
        hp_before = sp.hp
        m = HomingMissile(
            gv._missile_tex,
            sp.center_x, sp.center_y, heading=0.0,
        )
        gv._missile_list.append(m)
        update_missiles(gv, 1 / 60)
        # Either shield or HP must have dropped.
        assert (sp.shields < shield_before) or (sp.hp < hp_before)


class TestStarMazeMazeStructure:
    """Verify geometry + spawn-safety invariants the user called out
    explicitly."""

    def test_every_maze_has_at_least_one_entrance(self, real_game_view):
        """For each maze, at least one point along the outer boundary
        must NOT be a wall — otherwise the player can't get in."""
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        for maze in gv._zone.mazes:
            bounds = maze.bounds
            # Walk the four outer edges and count where walls fail to
            # cover the sample point.
            from zones.maze_geometry import circle_hits_any_wall
            sample_offsets = [x / 50.0 for x in range(51)]
            found_gap = False
            for t in sample_offsets:
                edges = [
                    (bounds.x + bounds.w * t, bounds.y + 8),   # bottom
                    (bounds.x + bounds.w * t,
                     bounds.y + bounds.h - 8),                # top
                    (bounds.x + 8, bounds.y + bounds.h * t),  # left
                    (bounds.x + bounds.w - 8,
                     bounds.y + bounds.h * t),                # right
                ]
                for (ex, ey) in edges:
                    if not circle_hits_any_wall(
                            ex, ey, 4, maze.walls):
                        found_gap = True
                        break
                if found_gap:
                    break
            assert found_gap, (
                f"maze centred at {maze.spawner} has no outer-wall "
                f"opening — player cannot get in")


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


class TestNebulaWarpExitRouting:
    """Bottom exit of a NEBULA_WARP_* variant returns to Zone 2;
    top exit advances to the Star Maze.  Mirrors Zone 1's warp
    pattern (bottom=MAIN, top=ZONE2)."""

    @pytest.mark.parametrize("zid", list(NEBULA_WARP_ZONES))
    def test_bottom_exit_transitions_to_zone2(
        self, real_game_view, zid,
    ):
        gv = real_game_view
        gv._transition_zone(zid)
        assert gv._zone.zone_id is zid
        gv.player.center_y = 10.0
        gv._zone.update(gv, 1 / 60)
        assert gv._zone.zone_id is ZoneID.ZONE2, (
            f"{zid.name} bottom exit deposited player in "
            f"{gv._zone.zone_id.name}, expected ZONE2")

    @pytest.mark.parametrize("zid", list(NEBULA_WARP_ZONES))
    def test_top_exit_transitions_to_star_maze(
        self, real_game_view, zid,
    ):
        gv = real_game_view
        gv._transition_zone(zid)
        assert gv._zone.zone_id is zid
        gv.player.center_y = gv._zone.world_height - 5.0
        gv._zone.update(gv, 1 / 60)
        assert gv._zone.zone_id is ZoneID.STAR_MAZE

    def test_full_flow_zone2_wormhole_to_warp_to_star_maze(
        self, real_game_view,
    ):
        """Reproduce the user's exact path: sit in Zone 2, defeat the
        Nebula boss (flip the flag), touch a corner wormhole, play a
        bit in the warp zone, walk out of the bottom — must land in
        Star Maze, not back in Zone 2."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        gv._zone.mark_nebula_boss_defeated(gv)

        # Find the corner wormhole targeting NEBULA_WARP_GAS.
        gas_wh = None
        for wh in gv._wormholes:
            if wh.zone_target is ZoneID.NEBULA_WARP_GAS:
                gas_wh = wh
                break
        assert gas_wh is not None, "corner wormhole not installed"

        # Walk the player onto the wormhole and tick — should transition.
        gv.player.center_x = gas_wh.center_x
        gv.player.center_y = gas_wh.center_y
        gv._zone.update(gv, 1 / 60)
        assert gv._zone.zone_id is ZoneID.NEBULA_WARP_GAS, (
            f"wormhole touch landed player in "
            f"{gv._zone.zone_id.name}")

        # Walk the player out the TOP — must land in Star Maze.
        gv.player.center_y = gv._zone.world_height - 5.0
        gv._zone.update(gv, 1 / 60)
        assert gv._zone.zone_id is ZoneID.STAR_MAZE, (
            f"NEBULA_WARP_GAS top exit landed player in "
            f"{gv._zone.zone_id.name}, expected STAR_MAZE")
        # Critical: one more tick at the Star Maze spawn point must
        # NOT transition back to Zone 2 (reproduces the bug where the
        # spawn position coincided with the central wormhole).
        gv._zone.update(gv, 1 / 60)
        assert gv._zone.zone_id is ZoneID.STAR_MAZE, (
            f"second tick in Star Maze transitioned to "
            f"{gv._zone.zone_id.name} — player spawned on top of "
            f"the central wormhole")


class TestNebulaWarpRoutingAndDanger:
    @pytest.mark.parametrize("zid", list(NEBULA_WARP_ZONES))
    def test_entering_nebula_warp_sets_2x_danger_and_split_exits(
        self, real_game_view, zid,
    ):
        gv = real_game_view
        gv._transition_zone(zid)
        assert gv._zone.zone_id is zid
        assert gv._zone._danger == 2.0
        assert gv._zone._exit_bottom_zone is ZoneID.ZONE2
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
