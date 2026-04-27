"""Performance integration tests for the active-drone update path.

Pin steady-state FPS while a CombatDrone or MiningDrone is deployed
in the Star Maze — the maze is the most expensive zone for the
planner (it actually runs A* + doorway lookups every frame; in
Zone 1 / Zone 2 the planner is a no-op).

Catches regressions in:

  * ``WaypointPlanner.plan()`` — any branch turning quadratic on
    room count or wall count.
  * ``update_drone`` — per-frame ``attach_maze_planner`` allocation
    if the identity check ever breaks.
  * ``_BaseDrone.follow`` / ``_run_return_home`` — segment-vs-walls
    sweep, slot picker, un-stick nudge tracking.
  * Per-frame map-marker draw of the drone X (minimap + large map).

Run with:
    pytest "unit tests/integration/test_performance_drone.py" -v
"""
from __future__ import annotations

import math

import pytest

from constants import DRONE_BREAK_OFF_DIST
from zones import ZoneID
from integration.conftest import measure_fps as _measure_fps


MIN_FPS = 40


# ── Shared helpers ─────────────────────────────────────────────────────────


def _enter_star_maze(gv):
    if gv._zone.zone_id != ZoneID.STAR_MAZE:
        gv._transition_zone(ZoneID.STAR_MAZE)


def _first_maze(gv):
    mazes = getattr(gv._zone, "_mazes", None)
    assert mazes
    return mazes[0]


def _room_centre(room):
    return (room.x + room.w * 0.5, room.y + room.h * 0.5)


def _deploy_combat_drone(gv, x, y):
    from sprites.drone import CombatDrone
    d = CombatDrone(x, y)
    gv._drone_list.append(d)
    gv._active_drone = d
    return d


def _deploy_mining_drone(gv, x, y):
    from sprites.drone import MiningDrone
    d = MiningDrone(x, y)
    gv._drone_list.append(d)
    gv._active_drone = d
    return d


# ═══════════════════════════════════════════════════════════════════════════
#  Drone in FOLLOW — slot picker + planner no-op (same room as player)
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneFollowSameRoom:
    """Drone trailing the player at a slot inside one room.  The
    planner short-circuits on same-room and the drone runs the
    slot picker every frame against the maze's wall list."""

    def test_combat_drone_following_in_maze_room(self, real_game_view):
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        gv.player.center_x = cx
        gv.player.center_y = cy
        _deploy_combat_drone(gv, cx + 30, cy + 30)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"combat drone following in maze room: "
            f"{fps:.1f} FPS < {MIN_FPS}")

    def test_mining_drone_following_in_maze_room(self, real_game_view):
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        gv.player.center_x = cx
        gv.player.center_y = cy
        _deploy_mining_drone(gv, cx + 30, cy + 30)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"mining drone following in maze room: "
            f"{fps:.1f} FPS < {MIN_FPS}")


# ═══════════════════════════════════════════════════════════════════════════
#  Drone in ATTACK — combat with a maze spawner in detect range
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneAttackInMaze:
    def test_combat_drone_engaging_spawner(self, real_game_view):
        """Drone in ATTACK mode firing every cooldown.  Exercises
        ``_aim_and_fire`` + ``_track_stuck_progress`` + the
        spawner-priority targeting path every frame."""
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        gv.player.center_x = cx
        gv.player.center_y = cy
        d = _deploy_combat_drone(gv, cx + 30, cy + 30)
        # Move the closest spawner right next to the drone so it's
        # in detect range with clear LOS.
        sp = list(gv._zone._spawners)[0]
        sp.center_x = cx + 200
        sp.center_y = cy
        sp.killed = False
        # Pin spawner HP so combat doesn't end early.
        sp.hp = 100000
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"combat drone engaging spawner: "
            f"{fps:.1f} FPS < {MIN_FPS}")


# ═══════════════════════════════════════════════════════════════════════════
#  Drone in RETURN_HOME — A* path through the room graph every frame
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneReturnHomeMultiRoom:
    """RETURN_HOME with the planner re-planning each frame because
    the drone is making real progress through doorways.  This is
    the heaviest planner state — A* runs every REPLAN_INTERVAL
    (0.5 s), and the un-stick nudge tracker fires every frame."""

    def test_combat_drone_return_home_through_maze(
            self, real_game_view):
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        # Drone in one corner room, player past BREAK_OFF in a
        # different room so RETURN_HOME stays engaged the entire
        # measurement window.
        ax, ay = _room_centre(maze.rooms[0])
        bx, by = _room_centre(maze.rooms[-1])
        gv.player.center_x = bx
        gv.player.center_y = by
        d = _deploy_combat_drone(gv, ax, ay)
        # Verify we're actually >800 px apart.
        assert math.hypot(bx - ax, by - ay) > DRONE_BREAK_OFF_DIST
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"combat drone RETURN_HOME through maze: "
            f"{fps:.1f} FPS < {MIN_FPS}")


# ═══════════════════════════════════════════════════════════════════════════
#  Drone in entrance gap — exit-via-outer-point branch
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneAtEntranceGap:
    """Drone at the maze entrance with the player outside — the
    "body in entrance room + target outside" branch fires every
    frame and emits ``entrance_xy_outer``.  Catches any
    allocation in the entrance-routing fast path."""

    def test_combat_drone_at_entrance_with_player_outside(
            self, real_game_view):
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        entrance_room = maze.rooms[maze.entrance_room]
        cx, cy = _room_centre(entrance_room)
        d = _deploy_combat_drone(gv, cx, cy)
        # Player ~400 px past the entrance gap, outside any room.
        outer_dx = (maze.entrance_xy_outer[0]
                    - maze.entrance_xy[0])
        outer_dy = (maze.entrance_xy_outer[1]
                    - maze.entrance_xy[1])
        outer_len = math.hypot(outer_dx, outer_dy)
        nx = outer_dx / outer_len
        ny = outer_dy / outer_len
        gv.player.center_x = maze.entrance_xy[0] + nx * 400
        gv.player.center_y = maze.entrance_xy[1] + ny * 400
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"combat drone at entrance with player outside: "
            f"{fps:.1f} FPS < {MIN_FPS}")


# ═══════════════════════════════════════════════════════════════════════════
#  Drone hover tooltip + map markers — draw cost
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneMapDrawCost:
    """Drone deployed AND map open AND cursor on the drone marker —
    every drone draw path hot at once: in-world sprite, minimap X,
    large-map X, both hover tooltips.  Catches a regression in any
    of the per-frame draw helpers."""

    def test_drone_with_full_screen_map_open(self, real_game_view):
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        gv.player.center_x = cx
        gv.player.center_y = cy
        d = _deploy_combat_drone(gv, cx + 30, cy + 30)
        # Open the large map.
        gv._map_overlay.open = True
        # Move the cursor onto the drone marker to trigger the
        # hover tooltip on the large map.  draw_logic uses
        # gv._hover_screen_x/y; the value just needs to map to a
        # world point near the drone via map_overlay.world_pos_at_screen.
        import arcade
        win = arcade.get_window()
        mx, my, mw, mh = gv._map_overlay._rect(win.width, win.height)
        zw = gv._zone.world_width
        zh = gv._zone.world_height
        gv._hover_screen_x = mx + (d.center_x / zw) * mw
        gv._hover_screen_y = my + (d.center_y / zh) * mh
        # Also mark the in-world hover so both tooltip paths run.
        gv._hover_drone = d
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"drone + map open + hover tooltip: "
            f"{fps:.1f} FPS < {MIN_FPS}")
