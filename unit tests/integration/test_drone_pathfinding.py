"""End-to-end integration tests for the companion-drone pathfinder.

The fast unit tests (``unit tests/test_waypoint_planner.py`` +
``test_drone.py`` + ``test_fleet_menu.py``) pin every individual
branch of ``WaypointPlanner.plan()`` and the drone mode machine
against stub state.  These tests exercise the same code paths
through a **real GameView** with a **real Star Maze**, ticking
``gv.on_update`` for many frames so the per-frame integration
(``update_drone`` → ``attach_maze_planner`` → ``follow`` /
``_run_return_home`` → planner → push-out → un-stick nudge)
runs end-to-end exactly as it does in the live game.

Catches the class of bugs the per-branch unit tests can't:

  * Drone fails to actually MOVE through doorways even though the
    planner emits the right waypoints (push-out + planner combine
    badly).
  * Drone enters RETURN_HOME but never returns because the mode
    flips back to FOLLOW under some condition we didn't pin.
  * Fleet menu order applied through ``apply_fleet_order`` doesn't
    propagate into the drone's per-frame mode resolution.
  * Direct RETURN order auto-clears prematurely (the
    "drone within EXIT_DIST" telemetry-pinned regression).

Run with:
    pytest "unit tests/integration/test_drone_pathfinding.py" -v
"""
from __future__ import annotations

import math

import pytest

from constants import (
    DRONE_BREAK_OFF_DIST, DRONE_FOLLOW_DIST,
    DRONE_DETECT_RANGE,
)
from zones import ZoneID
from zones.maze_geometry import find_room_index


# ── Helpers ────────────────────────────────────────────────────────────────


def _spawn_combat_drone(gv, x, y):
    """Drop a CombatDrone at (x, y) and wire it up as the active
    drone.  Same scaffold as test_drone_wall_containment.py."""
    from sprites.drone import CombatDrone
    d = CombatDrone(x, y)
    gv._drone_list.append(d)
    gv._active_drone = d
    return d


def _first_maze(gv):
    """Return the first MazeLayout in the active Star Maze zone."""
    mazes = getattr(gv._zone, "_mazes", None)
    assert mazes, "Star Maze zone exposes no _mazes attribute"
    return mazes[0]


def _room_centre(room):
    return (room.x + room.w * 0.5, room.y + room.h * 0.5)


def _tick(gv, n: int, dt: float = 1 / 60) -> None:
    """Advance the game loop ``n`` frames."""
    for _ in range(n):
        gv.on_update(dt)


def _enter_star_maze(gv):
    if gv._zone.zone_id != ZoneID.STAR_MAZE:
        gv._transition_zone(ZoneID.STAR_MAZE)


# ═══════════════════════════════════════════════════════════════════════════
#  1. Multi-room A* — drone routes through doorways from one room to another
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneMultiRoomNavigation:
    """Drone in room A, player in a non-adjacent room B — over a few
    seconds of ticks the drone should close the room-graph distance
    by traversing doorways instead of grinding on the dividing
    walls."""

    def test_drone_advances_through_at_least_one_doorway(
            self, real_game_view):
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        # Pick two rooms that need at least 2 doorway hops to
        # connect.  ``room_graph`` is built from the carved DFS so
        # a non-adjacent pair is guaranteed in a 5x5 grid.
        room_a_idx = next(
            i for i, n in maze.room_graph.items() if len(n) >= 1)
        non_adj = [
            i for i in range(len(maze.rooms))
            if i != room_a_idx
            and i not in maze.room_graph[room_a_idx]
        ]
        room_b_idx = non_adj[0]
        room_a = maze.rooms[room_a_idx]
        room_b = maze.rooms[room_b_idx]
        ax, ay = _room_centre(room_a)
        bx, by = _room_centre(room_b)
        gv.player.center_x = bx
        gv.player.center_y = by
        d = _spawn_combat_drone(gv, ax, ay)
        # 4 s of ticks = plenty for a 2-room A* path at 450 px/s
        # max speed.
        _tick(gv, 240)
        # Drone has moved out of room A (either reached B or at
        # least crossed through a doorway into a path-room).
        cur_room = find_room_index(d.center_x, d.center_y, maze.rooms)
        assert cur_room != room_a_idx, (
            f"drone never left room {room_a_idx}; "
            f"final pos=({d.center_x:.0f},{d.center_y:.0f}), "
            f"current room={cur_room}")

    def test_drone_eventually_close_to_player_in_far_room(
            self, real_game_view):
        """6 s of ticks should be enough for the drone to either
        reach the player's room or be within slot range — the
        planner + doorway routing should reliably close 3-4 room
        hops."""
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        # Pick the two rooms farthest apart inside the first maze
        # so the path has multiple doorway hops.
        n = len(maze.rooms)
        best_pair = (0, 1)
        best_d = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                a, b = maze.rooms[i], maze.rooms[j]
                d2 = math.hypot(
                    (a.x + a.w * 0.5) - (b.x + b.w * 0.5),
                    (a.y + a.h * 0.5) - (b.y + b.h * 0.5))
                if d2 > best_d:
                    best_d = d2
                    best_pair = (i, j)
        a_idx, b_idx = best_pair
        ax, ay = _room_centre(maze.rooms[a_idx])
        bx, by = _room_centre(maze.rooms[b_idx])
        gv.player.center_x = bx
        gv.player.center_y = by
        d = _spawn_combat_drone(gv, ax, ay)
        start_dist = math.hypot(d.center_x - bx, d.center_y - by)
        _tick(gv, 360)   # 6 s
        end_dist = math.hypot(d.center_x - bx, d.center_y - by)
        # Drone has substantially closed the gap (>= 50 % of the
        # initial straight-line distance).  If it had grinded on a
        # wall the distance would be ~unchanged.
        assert end_dist < start_dist * 0.5, (
            f"drone made no real progress in 6 s: "
            f"start_dist={start_dist:.0f}, end_dist={end_dist:.0f}")


# ═══════════════════════════════════════════════════════════════════════════
#  2. RETURN_HOME — autonomous mode triggers when player drifts past 800 px
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneAutonomousReturnHome:
    def test_drone_enters_return_home_above_break_off(
            self, real_game_view):
        """Player teleported >800 px from drone → mode flips to
        RETURN_HOME on the next tick."""
        from sprites.drone import _BaseDrone
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        ax, ay = _room_centre(maze.rooms[0])
        gv.player.center_x = ax
        gv.player.center_y = ay
        d = _spawn_combat_drone(gv, ax, ay)
        _tick(gv, 5)   # Settle into FOLLOW.
        # Now teleport the player far away.
        gv.player.center_x = ax + DRONE_BREAK_OFF_DIST + 500
        gv.player.center_y = ay
        _tick(gv, 1)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME

    def test_drone_returns_to_player_from_far_distance(
            self, real_game_view):
        """RETURN_HOME closes the player gap.  Within 6 s the drone
        should have traversed >300 px toward the player's new
        position."""
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        ax, ay = _room_centre(maze.rooms[0])
        gv.player.center_x = ax
        gv.player.center_y = ay
        d = _spawn_combat_drone(gv, ax, ay)
        _tick(gv, 5)
        gv.player.center_x = ax + DRONE_BREAK_OFF_DIST + 500
        gv.player.center_y = ay
        before = (d.center_x, d.center_y)
        _tick(gv, 360)   # 6 s
        moved = math.hypot(
            d.center_x - before[0], d.center_y - before[1])
        assert moved > 300.0, (
            f"drone moved only {moved:.0f} px toward the player "
            f"in 6 s of RETURN_HOME — pathfinding stalled")

    def test_return_home_exits_under_600_with_hysteresis(
            self, real_game_view):
        """Once in RETURN_HOME, the drone holds it down to 600 px
        instead of flipping back at 800 px."""
        from sprites.drone import _BaseDrone
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        ax, ay = _room_centre(maze.rooms[0])
        gv.player.center_x = ax
        gv.player.center_y = ay
        d = _spawn_combat_drone(gv, ax, ay)
        # Force RETURN_HOME by far-teleport, then settle.
        gv.player.center_x = ax + DRONE_BREAK_OFF_DIST + 500
        _tick(gv, 1)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME
        # Pull the player back to 700 px — past EXIT (600) but
        # below BREAK_OFF (800).  Hysteresis should keep RETURN_HOME.
        gv.player.center_x = d.center_x + 700
        gv.player.center_y = d.center_y
        _tick(gv, 1)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME, (
            "RETURN_HOME hysteresis lost — exited at 700 px")


# ═══════════════════════════════════════════════════════════════════════════
#  3. Maze entry — drone outside the maze, target inside
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneEntersMaze:
    def test_drone_outside_player_inside_drone_enters_maze(
            self, real_game_view):
        """Drone parked just outside the maze entrance, player in
        the entrance room — within 4 s the drone should cross the
        entrance gap and end up inside a room."""
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        entrance_room = maze.rooms[maze.entrance_room]
        ex, ey = maze.entrance_xy
        # Player inside the entrance room.
        px, py = _room_centre(entrance_room)
        gv.player.center_x = px
        gv.player.center_y = py
        # Drone parked outside the maze along the entrance outward
        # axis at ~150 px past the gap.
        outer_dx = maze.entrance_xy_outer[0] - ex
        outer_dy = maze.entrance_xy_outer[1] - ey
        outer_len = math.hypot(outer_dx, outer_dy)
        nx = outer_dx / outer_len
        ny = outer_dy / outer_len
        d = _spawn_combat_drone(gv, ex + nx * 150, ey + ny * 150)
        _tick(gv, 240)   # 4 s.
        # Drone is now inside SOME maze room (any room — the
        # entrance was the only opening).
        room = find_room_index(d.center_x, d.center_y, maze.rooms)
        assert room is not None, (
            f"drone never entered the maze: pos=("
            f"{d.center_x:.0f},{d.center_y:.0f})")


# ═══════════════════════════════════════════════════════════════════════════
#  4. Maze exit — drone inside the maze, target outside
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneExitsMaze:
    def test_drone_in_entrance_room_with_target_outside_exits(
            self, real_game_view):
        """Drone in the entrance room, player outside the maze on
        the entrance side — the drone should cross the gap to
        open space within 4 s."""
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        entrance_room = maze.rooms[maze.entrance_room]
        cx, cy = _room_centre(entrance_room)
        d = _spawn_combat_drone(gv, cx, cy)
        # Player on the outside side of the entrance gap, far past
        # the wall band.
        outer_dx = maze.entrance_xy_outer[0] - maze.entrance_xy[0]
        outer_dy = maze.entrance_xy_outer[1] - maze.entrance_xy[1]
        outer_len = math.hypot(outer_dx, outer_dy)
        nx = outer_dx / outer_len
        ny = outer_dy / outer_len
        gv.player.center_x = maze.entrance_xy[0] + nx * 400
        gv.player.center_y = maze.entrance_xy[1] + ny * 400
        _tick(gv, 240)
        # Drone is now OUTSIDE every maze room (find_room_index
        # returns None for points past the outer wall + slack).
        room = find_room_index(d.center_x, d.center_y, maze.rooms)
        assert room is None, (
            f"drone failed to exit the maze: still inside "
            f"room {room} at ({d.center_x:.0f},{d.center_y:.0f})")


# ═══════════════════════════════════════════════════════════════════════════
#  5. Fleet menu — direct orders propagate through input dispatch
# ═══════════════════════════════════════════════════════════════════════════


class TestFleetMenuOrdersThroughDispatch:
    """``apply_fleet_order`` is the seam between the menu UI and
    the drone state.  These tests run the drone for a few frames
    after the order is applied and assert the per-frame mode
    machine actually honours it (no surprise interaction with
    autonomous resolution)."""

    def test_return_order_forces_return_home_even_with_target(
            self, real_game_view):
        from combat_helpers import apply_fleet_order
        from sprites.drone import _BaseDrone
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        d = _spawn_combat_drone(gv, cx, cy)
        # Park the player near the drone.
        gv.player.center_x = cx + 50
        gv.player.center_y = cy
        # ATTACK direct order would normally fire when a target is
        # in range — RETURN should override.  Apply RETURN; teleport
        # the player FAR so distance keeps RETURN_HOME engaged.
        apply_fleet_order(gv, "return")
        gv.player.center_x = cx + DRONE_BREAK_OFF_DIST + 800
        _tick(gv, 5)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME
        assert d._direct_order == "return"

    def test_attack_order_engages_outside_break_off_dist(
            self, real_game_view):
        """ATTACK direct order ignores the 800 px break-off so the
        drone roams to engage."""
        from combat_helpers import apply_fleet_order
        from sprites.drone import _BaseDrone
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        d = _spawn_combat_drone(gv, cx, cy)
        # Player far away.
        gv.player.center_x = cx + DRONE_BREAK_OFF_DIST + 200
        gv.player.center_y = cy
        # Spawner inside the same room as the drone — guaranteed
        # in-range target with clear LOS.
        spawners = list(gv._zone._spawners)
        # Move the closest spawner right next to the drone.
        sp = spawners[0]
        sp.center_x = cx + 80
        sp.center_y = cy
        sp.killed = False
        # Set ATTACK before the player gets teleported, since ATTACK
        # only ignores break-off when set.
        apply_fleet_order(gv, "attack")
        _tick(gv, 5)
        # Drone should NOT be in RETURN_HOME (ATTACK overrides).
        assert d._mode == _BaseDrone._MODE_ATTACK

    def test_follow_only_reaction_blocks_attack_engagement(
            self, real_game_view):
        from combat_helpers import apply_fleet_order
        from sprites.drone import _BaseDrone
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        d = _spawn_combat_drone(gv, cx, cy)
        gv.player.center_x = cx
        gv.player.center_y = cy
        # Move a spawner right next to the drone.
        sp = list(gv._zone._spawners)[0]
        sp.center_x = cx + 100
        sp.center_y = cy
        sp.killed = False
        apply_fleet_order(gv, "follow_only")
        _tick(gv, 5)
        # Reaction "follow" must keep the drone in FOLLOW even with
        # a target in detect range and clear LOS.
        assert d._mode == _BaseDrone._MODE_FOLLOW

    def test_direct_return_clears_only_on_close_and_los(
            self, real_game_view):
        """RETURN must NOT auto-clear when the drone is wedged
        against a wall just inside the close-range threshold —
        the order has to stick until LOS is also clear.  This is
        the telemetry-pinned 20:20 regression."""
        from combat_helpers import apply_fleet_order
        gv = real_game_view
        _enter_star_maze(gv)
        # Pick a tall wall and place the drone on one side, the
        # player on the other side, separated by ~100 px (well
        # under the 160 px clear-distance).
        walls = gv._zone._walls
        wall = next(
            (w for w in walls if w.h > w.w and w.h > 200), None)
        assert wall is not None
        wmid_y = wall.y + wall.h / 2
        gv.player.center_x = wall.x - 60
        gv.player.center_y = wmid_y
        d = _spawn_combat_drone(
            gv, wall.x + wall.w + 60, wmid_y)
        apply_fleet_order(gv, "return")
        _tick(gv, 5)
        # Order MUST persist — drone is close (~140 px) but a wall
        # blocks LOS.
        assert d._direct_order == "return", (
            "RETURN order auto-cleared while a wall blocks LOS — "
            "telemetry regression 2026-04-26 20:20")


# ═══════════════════════════════════════════════════════════════════════════
#  6. Friendly fire pass-through (in-world, end-to-end)
# ═══════════════════════════════════════════════════════════════════════════


class TestPlayerLasersPassThroughAIShip:
    """Fast unit tests pin the collision branch; this one runs a
    real ParkedShip through ``handle_parked_ship_damage`` with a
    real player projectile to confirm the friendly-fire skip
    actually fires under live integration."""

    def test_ai_pilot_ship_takes_no_damage_from_player_laser(
            self, real_game_view):
        from sprites.parked_ship import ParkedShip
        from sprites.projectile import Projectile
        gv = real_game_view
        # Zone 1 is fine — the friendly-fire branch is zone-
        # agnostic and avoids the Star Maze's wall/projectile
        # blocking pipeline.
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        ps = ParkedShip(
            gv._faction, gv._ship_type, 1, 3000.0, 3000.0)
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.append(ps)
        before_hp = ps.hp
        # Spawn a player projectile parked on top of the AI ship.
        proj_tex = gv._active_weapon._texture
        proj = Projectile(
            proj_tex, ps.center_x, ps.center_y,
            heading=0.0, speed=1.0, max_dist=1000.0,
            scale=1.0, damage=10.0)
        gv.projectile_list.append(proj)
        # One tick of the collision pipeline.
        from collisions import handle_parked_ship_damage
        handle_parked_ship_damage(gv)
        # AI ship took no damage; projectile still alive (passed
        # through, not consumed).
        assert ps.hp == before_hp


# ═══════════════════════════════════════════════════════════════════════════
#  7. Save / load round-trip — drone position + orders persist
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneSaveLoadIntegration:
    def test_active_drone_round_trips_through_save_dict(
            self, real_game_view):
        """End-to-end save → load via ``save_to_dict`` /
        ``restore_state`` — drone variant, position, HP, shields,
        reaction, and any standing direct order all survive."""
        from game_save import save_to_dict, restore_state
        from sprites.drone import _BaseDrone
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        gv.player.center_x = cx
        gv.player.center_y = cy
        d = _spawn_combat_drone(gv, cx + 30, cy + 30)
        d.hp = 42
        d.shields = 7
        d._reaction = "follow"
        d._direct_order = "return"
        # Save → wipe the live drone → restore.
        blob = save_to_dict(gv, "drone-roundtrip")
        gv._drone_list.clear()
        gv._active_drone = None
        restore_state(gv, blob)
        restored = gv._active_drone
        assert restored is not None
        assert isinstance(restored, _BaseDrone)
        assert restored.hp == 42
        assert restored.shields == 7
        assert restored._reaction == "follow"
        assert restored._direct_order == "return"
        assert abs(restored.center_x - (cx + 30)) < 1.0
        assert abs(restored.center_y - (cy + 30)) < 1.0


# ═══════════════════════════════════════════════════════════════════════════
#  8. Slot picker fallback — wall blocks LEFT, drone uses RIGHT
# ═══════════════════════════════════════════════════════════════════════════


class TestDroneSlotFallbackInLiveZone:
    """Pre-existing unit test pins the slot picker against a stub
    walls list.  This one drives it through ``follow()`` against
    the real Star Maze wall list to catch any drift between the
    stub format and the live zone's Rect format (named-tuple
    indexed positionally)."""

    def test_drone_picks_back_slot_when_left_and_right_blocked(
            self, real_game_view):
        from sprites.drone import _BaseDrone
        gv = real_game_view
        _enter_star_maze(gv)
        # Find a horizontal corridor between two parallel walls so
        # both the LEFT and RIGHT slots land in geometry.  Use the
        # narrow gaps between adjacent rooms.
        maze = _first_maze(gv)
        # Park the player in the centre of an interior room with
        # heading=0 so LEFT / RIGHT slots are west / east of the
        # player.  The room is 300 px wide; LEFT is 80 px west.
        room = maze.rooms[0]
        gv.player.center_x = room.x + room.w * 0.5
        gv.player.center_y = room.y + room.h * 0.5
        gv.player.heading = 0.0
        d = _spawn_combat_drone(
            gv, gv.player.center_x, gv.player.center_y)
        # Synthesise a wall directly west AND east of the player so
        # the LEFT and RIGHT slots are both blocked.  We push them
        # into the active zone's wall list (drone reads that via
        # ``_walls_from_zone``).
        from zones.maze_geometry import Rect
        py = gv.player.center_y
        gv._zone._walls.append(
            Rect(gv.player.center_x - 100, py - 30, 40, 60))
        gv._zone._walls.append(
            Rect(gv.player.center_x + 60, py - 30, 40, 60))
        _tick(gv, 5)
        # Drone settled into BACK slot (south of player at heading 0).
        assert d._slot == _BaseDrone._SLOT_BACK, (
            f"drone in slot {d._slot}; expected BACK ({_BaseDrone._SLOT_BACK})")


# ═══════════════════════════════════════════════════════════════════════════
#  9. Doorway-arrival path advance (live)
# ═══════════════════════════════════════════════════════════════════════════


class TestDoorwayArrivalLive:
    """Telemetry-pinned regression (drone_return_telemetry.log,
    2026-04-26 20:14): drone parked exactly on a doorway midpoint
    for 27 s because the planner kept emitting the same midpoint
    as the waypoint.  Live equivalent: spawn the drone right on
    a known doorway and tick — within 1 s the drone must have
    moved past it."""

    def test_drone_does_not_park_on_doorway_midpoint(
            self, real_game_view):
        gv = real_game_view
        _enter_star_maze(gv)
        maze = _first_maze(gv)
        # Pick any doorway and the two rooms it connects.
        edge_key = next(iter(maze.doorways))
        a, b = tuple(edge_key)
        door = maze.doorways[edge_key]
        # Player in room b (the destination) so the drone has a
        # reason to traverse the doorway from a side.
        room_b = maze.rooms[b]
        gv.player.center_x = room_b.x + room_b.w * 0.5
        gv.player.center_y = room_b.y + room_b.h * 0.5
        # Drone planted exactly on the doorway midpoint.
        d = _spawn_combat_drone(gv, door[0], door[1])
        start = (d.center_x, d.center_y)
        _tick(gv, 60)   # 1 s.
        moved = math.hypot(
            d.center_x - start[0], d.center_y - start[1])
        assert moved > 30.0, (
            f"drone parked on doorway midpoint ({door[0]:.0f},"
            f"{door[1]:.0f}) moved only {moved:.1f} px in 1 s — "
            f"doorway-arrival path advance failed end-to-end")
