"""Regression test: combat / mining drones must not penetrate
maze walls in the Star Maze.

The drone follows the player at a 160-px orbit offset, so when
the player flies tangent to a maze structure the orbit point can
land inside a wall — without containment, the drone teleports
right through the dungeon geometry.

``update_logic.update_drone`` now consults the active zone's
``_push_out_of_walls`` helper (Star Maze exposes one; other zones
don't) and pushes the drone back out of any wall it overlaps.
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest


# ── Direct push-out behaviour against a synthetic wall ──────────────────

class TestDronePushOutOfWall:
    def test_drone_inside_wall_is_pushed_out(self):
        from sprites.drone import CombatDrone
        from constants import DRONE_RADIUS
        # Build a wall AABB that the drone's centre is sitting inside.
        Wall = SimpleNamespace
        wall = Wall(x=100.0, y=100.0, w=200.0, h=200.0)
        d = CombatDrone(150.0, 150.0)
        # Stand-in zone with the maze-style wall list + push-out.
        from zones.star_maze import StarMazeZone
        zone = StarMazeZone.__new__(StarMazeZone)
        zone._walls = [wall]
        zone._wall_grid = {}      # empty → _walls_near returns _walls
        zone._wall_grid_cell = 48
        # Real method — bound to our synthetic instance.
        StarMazeZone._push_out_of_walls(zone, [d], DRONE_RADIUS)
        # Drone centre should be outside the wall AABB (with radius
        # margin).  All four edges are equidistant so the resolver
        # picks one — assert the centre is no longer inside.
        outside = (d.center_x <= wall.x - DRONE_RADIUS
                    or d.center_x >= wall.x + wall.w + DRONE_RADIUS
                    or d.center_y <= wall.y - DRONE_RADIUS
                    or d.center_y >= wall.y + wall.h + DRONE_RADIUS)
        assert outside, (
            f"drone still inside wall: ({d.center_x}, {d.center_y})")

    def test_drone_grazing_wall_is_pushed_clear(self):
        from sprites.drone import CombatDrone
        from constants import DRONE_RADIUS
        Wall = SimpleNamespace
        wall = Wall(x=0.0, y=0.0, w=100.0, h=100.0)
        # Drone centre at (105, 50) — wall edge at x=100, drone radius
        # 7, so the drone overlaps by 2 px.  Push-out should clear it
        # to at least x = 100 + DRONE_RADIUS + 1.
        d = CombatDrone(105.0, 50.0)
        from zones.star_maze import StarMazeZone
        zone = StarMazeZone.__new__(StarMazeZone)
        zone._walls = [wall]
        zone._wall_grid = {}      # empty → _walls_near returns _walls
        zone._wall_grid_cell = 48
        StarMazeZone._push_out_of_walls(zone, [d], DRONE_RADIUS)
        assert d.center_x >= 100.0 + DRONE_RADIUS, (
            f"drone not pushed clear: x={d.center_x}")


# ── update_drone wires the containment hook ─────────────────────────────

class TestUpdateDroneCallsZonePushOut:
    def test_skipped_when_zone_lacks_push_out_helper(self):
        # Zones without walls (Zone 1, Zone 2) don't expose
        # _push_out_of_walls — update_drone must not crash.
        from update_logic import update_drone
        from sprites.drone import CombatDrone
        d = CombatDrone(100.0, 100.0)
        gv = SimpleNamespace(
            _active_drone=d,
            player=SimpleNamespace(center_x=0.0, center_y=0.0),
            _zone=SimpleNamespace(),  # no _push_out_of_walls attr
            projectile_list=arcade.SpriteList(),
            alien_list=[],
            _boss=None,
            _nebula_boss=None,
            iron_pickup_list=[],
            blueprint_pickup_list=[],
            alien_projectile_list=arcade.SpriteList(),
            _boss_projectile_list=arcade.SpriteList(),
            _drone_list=arcade.SpriteList(),
        )
        gv._drone_list.append(d)
        update_drone(gv, 0.016)   # must not raise
        assert gv._active_drone is d   # drone alive

    def test_invokes_push_out_when_zone_provides_it(self):
        # Zone exposes a recording stub for _push_out_of_walls.  After
        # update_drone runs, the stub must have been called with a
        # one-element list containing the drone + the drone's radius.
        from update_logic import update_drone
        from sprites.drone import CombatDrone
        from constants import DRONE_RADIUS
        d = CombatDrone(100.0, 100.0)
        calls = []
        zone = SimpleNamespace(
            _push_out_of_walls=lambda entities, r: calls.append(
                (list(entities), r)),
        )
        gv = SimpleNamespace(
            _active_drone=d,
            player=SimpleNamespace(center_x=0.0, center_y=0.0),
            _zone=zone,
            projectile_list=arcade.SpriteList(),
            alien_list=[],
            _boss=None,
            _nebula_boss=None,
            iron_pickup_list=[],
            blueprint_pickup_list=[],
            alien_projectile_list=arcade.SpriteList(),
            _boss_projectile_list=arcade.SpriteList(),
            _drone_list=arcade.SpriteList(),
        )
        gv._drone_list.append(d)
        update_drone(gv, 0.016)
        assert len(calls) == 1
        entities, r = calls[0]
        assert entities == [d]
        assert r == DRONE_RADIUS
