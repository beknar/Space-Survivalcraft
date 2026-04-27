"""WaypointPlanner — shared room-graph pathfinder used by maze aliens
and player drones to navigate around dungeon walls.

Behaviour pinned by these tests:

  1. Same-room and missing-geometry inputs return None (caller chases
     directly).
  2. Different-room inputs return the next room's centre as the
     waypoint.
  3. After ``FAIL_TIMEOUT`` seconds without the body moving at least
     ``STUCK_DIST`` toward the target, ``gave_up()`` flips True for
     exactly one call, then the planner enters cooldown and returns
     ``None`` until ``COOLDOWN`` elapses.
  4. Real movement resets the stuck timer so the planner doesn't
     give up while the body is making progress.
"""
from __future__ import annotations

import pytest

from zones.maze_geometry import (
    Rect, WaypointPlanner, generate_maze,
)


@pytest.fixture
def maze():
    """A deterministic 5×5 maze centred at (0, 0) for graph tests."""
    return generate_maze(0.0, 0.0, seed=42)


class TestNoOpCases:
    def test_no_geometry_returns_none(self):
        p = WaypointPlanner(None, None)
        assert p.plan(0.016, 0.0, 0.0, 100.0, 100.0) is None
        assert p.gave_up() is False

    def test_same_room_returns_none(self, maze):
        p = WaypointPlanner(maze.rooms, maze.room_graph)
        # Pick a room and put both endpoints inside it.
        r = maze.rooms[0]
        sx = r.x + r.w * 0.3
        sy = r.y + r.h * 0.3
        tx = r.x + r.w * 0.7
        ty = r.y + r.h * 0.7
        assert p.plan(0.016, sx, sy, tx, ty) is None
        assert p.gave_up() is False


class TestProducesWaypoint:
    def test_different_room_returns_next_room_centre(self, maze):
        p = WaypointPlanner(maze.rooms, maze.room_graph)
        # Find any room with at least one neighbour.
        start_idx, neighbours = next(
            (i, n) for i, n in maze.room_graph.items() if n)
        start_room = maze.rooms[start_idx]
        sx = start_room.x + start_room.w * 0.5
        sy = start_room.y + start_room.h * 0.5
        # Put the target in any other room; the next waypoint should
        # be the centre of one of the start room's neighbours.
        target_idx = next(
            i for i in range(len(maze.rooms)) if i != start_idx)
        tr = maze.rooms[target_idx]
        wp = p.plan(0.016, sx, sy,
                    tr.x + tr.w * 0.5, tr.y + tr.h * 0.5)
        assert wp is not None
        wx, wy = wp
        # Waypoint must be the centre of a room (neighbour or further
        # along the path).  Always lies inside one of the rooms.
        assert any(
            r.x <= wx <= r.x + r.w and r.y <= wy <= r.y + r.h
            for r in maze.rooms
        )


class TestDoorwayWaypoint:
    """Doorway-aware steering: when crossing rooms, the planner
    should aim at the carved gap in the wall, not the next room's
    centre — straight-line steering between two room centres can
    clip a wall corner and wedge the body forever.
    """

    def test_doorways_present_on_layout(self, maze):
        # Every entry in the room graph should have a corresponding
        # doorway midpoint (graph is symmetric, doorways are keyed
        # by frozenset so both directions resolve to one entry).
        for a, neighbours in maze.room_graph.items():
            for b in neighbours:
                assert frozenset((a, b)) in maze.doorways

    def test_doorway_lies_on_carved_wall_gap(self, maze):
        """Each doorway midpoint must sit between the two rooms it
        connects (axis-overlap with the wall band that was carved out).
        """
        for edge_key, (mx, my) in maze.doorways.items():
            a, b = tuple(edge_key)
            ra, rb = maze.rooms[a], maze.rooms[b]
            # Doorway midpoint must lie inside the union of the two
            # room AABBs along the perpendicular axis (the open gap
            # has the same span as the rooms it connects).
            in_a_or_b = (
                (ra.x <= mx <= ra.x + ra.w
                 and ra.y <= my <= ra.y + ra.h + 32)
                or
                (rb.x <= mx <= rb.x + rb.w
                 and rb.y <= my <= rb.y + rb.h + 32)
                or
                (ra.x - 32 <= mx <= ra.x + ra.w + 32
                 and ra.y - 32 <= my <= ra.y + ra.h + 32))
            assert in_a_or_b, f"doorway {edge_key} at {(mx, my)} not near rooms"

    def test_planner_aims_at_doorway_not_room_centre(self, maze):
        """Adjacent rooms (single-step path) — planner returns the
        doorway midpoint, NOT the next room's centre."""
        # Pick any pair of adjacent rooms.
        start_idx, neighbours = next(
            (i, n) for i, n in maze.room_graph.items() if n)
        target_idx = neighbours[0]
        sr = maze.rooms[start_idx]
        tr = maze.rooms[target_idx]
        sx = sr.x + sr.w * 0.5
        sy = sr.y + sr.h * 0.5
        tx = tr.x + tr.w * 0.5
        ty = tr.y + tr.h * 0.5
        p = WaypointPlanner(maze.rooms, maze.room_graph, maze.doorways)
        wp = p.plan(0.016, sx, sy, tx, ty)
        assert wp is not None
        wx, wy = wp
        door = maze.doorways[frozenset((start_idx, target_idx))]
        # Allow tiny float tolerance.
        assert abs(wx - door[0]) < 0.5
        assert abs(wy - door[1]) < 0.5
        # Confirm it's actually different from the room centre (so
        # we know the test is doing something).
        assert (abs(wx - tx) > 1.0 or abs(wy - ty) > 1.0)

    def test_planner_falls_back_to_room_centre_without_doorways(self, maze):
        """Caller passing no doorway table — planner reverts to the
        legacy room-centre target so older callers keep working."""
        start_idx, neighbours = next(
            (i, n) for i, n in maze.room_graph.items() if n)
        target_idx = neighbours[0]
        sr = maze.rooms[start_idx]
        tr = maze.rooms[target_idx]
        p = WaypointPlanner(maze.rooms, maze.room_graph)  # no doorways
        wp = p.plan(0.016,
                    sr.x + sr.w * 0.5, sr.y + sr.h * 0.5,
                    tr.x + tr.w * 0.5, tr.y + tr.h * 0.5)
        assert wp is not None
        wx, wy = wp
        assert abs(wx - (tr.x + tr.w * 0.5)) < 0.5
        assert abs(wy - (tr.y + tr.h * 0.5)) < 0.5


class TestTargetOutsideMaze:
    """Regression: drone wedged inside the maze + player outside it
    (RETURN order in the wild).  Captured by telemetry 2026-04-26 —
    drone at (2194,3142), player at (1490,3470), planner returned
    `path: []` so the caller chased directly through the wall.
    Fix routes the body to the maze room whose centre is closest to
    the target, so the drone heads for the nearest exit instead of
    grinding on the interior wall."""

    def test_target_outside_routes_to_nearest_room(self, maze):
        """Body inside the maze (east end), target outside the maze
        (far west) — planner should route the body westward through
        rooms toward the nearest exit, NOT return None.

        Reproduces the telemetry scenario: drone at (2194,3142)
        inside maze 1, player at (1490,3470) outside the maze ⇒ old
        planner returned None ⇒ drone tried to fly through the
        west wall and bounced.
        """
        # Body in the FAR east room so the nearest-to-target room
        # (west) is genuinely different from the body's room.
        from zones.maze_geometry import find_room_index
        body_room = maze.rooms[-1]    # last room = east-most column
        sx = body_room.x + body_room.w * 0.5
        sy = body_room.y + body_room.h * 0.5
        tx = maze.bounds.x - 500.0
        ty = sy
        assert find_room_index(tx, ty, maze.rooms) is None
        p = WaypointPlanner(
            maze.rooms, maze.room_graph, maze.doorways)
        wp = p.plan(0.016, sx, sy, tx, ty)
        assert wp is not None, (
            "planner should produce a waypoint when target is "
            "outside the maze and body is across the maze from the "
            "nearest exit room")
        assert p._path != []
        assert p._path[0] in maze.room_graph

    def test_body_outside_target_inside_falls_through(self, maze):
        """Symmetric case — body outside the maze, target inside.
        We don't have a sane fallback here (the body should just
        fly straight at the target), so plan() must return None."""
        room0 = maze.rooms[0]
        tx = room0.x + room0.w * 0.5
        ty = room0.y + room0.h * 0.5
        sx = maze.bounds.x - 500.0
        sy = ty
        p = WaypointPlanner(
            maze.rooms, maze.room_graph, maze.doorways)
        assert p.plan(0.016, sx, sy, tx, ty) is None


class TestMazeEntrance:
    def test_layout_records_entrance(self, maze):
        """generate_maze populates entrance_room + entrance_xy."""
        assert 0 <= maze.entrance_room < len(maze.rooms)
        ex, ey = maze.entrance_xy
        # Entrance midpoint must lie on the maze's outer boundary.
        b = maze.bounds
        on_boundary = (
            abs(ex - b.x) < 32 or abs(ex - (b.x + b.w)) < 32
            or abs(ey - b.y) < 32 or abs(ey - (b.y + b.h)) < 32)
        assert on_boundary, (
            f"entrance_xy={maze.entrance_xy} not on maze boundary "
            f"{maze.bounds}")


class TestPlannerWallBandFallback:
    """Telemetry-pinned regression (drone_return_telemetry.log,
    2026-04-26 20:03): drone wedged at x=2185 inside maze 1's west
    outer wall (which spans 2154→2186) — find_room_index returned
    None, planner returned None, drone bounced on the wall.  Fix
    snaps the body's source room to the nearest room when the body
    is within wall_thickness slack of one."""

    def test_body_in_wall_band_snaps_to_nearest_room(self, maze):
        from zones.maze_geometry import (
            find_room_index, WaypointPlanner)
        room0 = maze.rooms[0]
        # Place body 1 px outside the room's west edge — inside the
        # outer wall, ``find_room_index`` returns None.
        sx = room0.x - 1.0
        sy = room0.y + room0.h * 0.5
        assert find_room_index(sx, sy, maze.rooms) is None
        # Target in any other room so a non-trivial route exists.
        target_idx = next(
            i for i in range(len(maze.rooms))
            if i != 0 and i in maze.room_graph[0])
        tr = maze.rooms[target_idx]
        tx = tr.x + tr.w * 0.5
        ty = tr.y + tr.h * 0.5
        p = WaypointPlanner(
            maze.rooms, maze.room_graph, maze.doorways)
        wp = p.plan(0.016, sx, sy, tx, ty)
        assert wp is not None, (
            "planner should snap a wall-band body to the nearest "
            "room and emit a waypoint, not return None")


class TestPlannerRoutesThroughEntrance:
    """When the target sits outside the maze entirely, the planner
    must route the body to the maze entrance — the geographically
    nearest room is often a sealed dead-end."""

    def test_target_outside_routes_to_entrance_room(self, maze):
        from zones.maze_geometry import WaypointPlanner
        # Build the per-room exit lookup the live caller wires up.
        room_to_exit = {i: maze.entrance_room
                        for i in range(len(maze.rooms))}
        exit_xy = {i: maze.entrance_xy
                   for i in range(len(maze.rooms))}
        # Pick a body room that's NOT the entrance and target far
        # outside the maze.
        body_idx = next(
            i for i in range(len(maze.rooms))
            if i != maze.entrance_room)
        br = maze.rooms[body_idx]
        sx = br.x + br.w * 0.5
        sy = br.y + br.h * 0.5
        tx = maze.bounds.x - 800.0
        ty = sy
        p = WaypointPlanner(
            maze.rooms, maze.room_graph, maze.doorways,
            room_to_exit, exit_xy)
        # Force a plan + walk the path; the path must end at the
        # entrance room (not whatever room is geographically
        # closest to the off-the-map target).
        p.plan(0.016, sx, sy, tx, ty)
        assert p._path != []
        assert p._path[-1] == maze.entrance_room

    def test_body_at_entrance_with_target_outside_emits_exit_xy(self, maze):
        """When the body has reached the entrance room the planner
        emits the entrance gap midpoint as the waypoint, so the
        drone crosses the outer wall instead of bouncing on it."""
        from zones.maze_geometry import WaypointPlanner
        room_to_exit = {i: maze.entrance_room
                        for i in range(len(maze.rooms))}
        exit_xy = {i: maze.entrance_xy
                   for i in range(len(maze.rooms))}
        er = maze.rooms[maze.entrance_room]
        sx = er.x + er.w * 0.5
        sy = er.y + er.h * 0.5
        # Target outside the maze.
        tx = maze.bounds.x - 800.0
        ty = sy
        p = WaypointPlanner(
            maze.rooms, maze.room_graph, maze.doorways,
            room_to_exit, exit_xy)
        wp = p.plan(0.016, sx, sy, tx, ty)
        assert wp is not None
        assert wp == maze.entrance_xy

    def test_body_at_entrance_gap_emits_target_position(self, maze):
        """Telemetry regression (drone_return_telemetry.log,
        2026-04-26 20:20): drone parked at exactly the entrance
        midpoint (2170, 3332) for 326 frames.  The planner kept
        emitting the entrance midpoint as the waypoint while the
        drone was already standing on it, so the update loop's
        ``dist <= 0.001`` early-out kept the drone frozen.

        Now: when the body is within DOORWAY_ARRIVAL_RADIUS of the
        entrance midpoint and target is outside the maze, the
        planner emits the TARGET position — the entrance gap is
        clear, the drone can fly straight out of it toward the
        player.
        """
        from zones.maze_geometry import WaypointPlanner
        room_to_exit = {i: maze.entrance_room
                        for i in range(len(maze.rooms))}
        exit_xy = {i: maze.entrance_xy
                   for i in range(len(maze.rooms))}
        # Body sitting EXACTLY at the entrance midpoint.
        sx, sy = maze.entrance_xy
        # Target outside the maze, opposite side from the entrance
        # axis — far enough to be in open space.
        tx = maze.bounds.x - 800.0
        ty = sy
        p = WaypointPlanner(
            maze.rooms, maze.room_graph, maze.doorways,
            room_to_exit, exit_xy)
        wp = p.plan(0.016, sx, sy, tx, ty)
        assert wp is not None
        # Must NOT be the entrance midpoint (that's where we are).
        assert wp != maze.entrance_xy, (
            "planner emitted the body's own position as waypoint — "
            "drone-loop's dist-zero early-out would freeze it")
        # The waypoint should be the target (or at least pointing
        # in the target's direction).
        assert wp == (tx, ty)


class TestDoorwayArrival:
    """Telemetry-pinned regression (drone_return_telemetry.log,
    2026-04-26 20:14): drone sat exactly on the doorway midpoint
    between rooms 1 and 2 for 27 s.  The planner kept emitting the
    same doorway as the waypoint — distance to waypoint = 0, drone
    refused to move.  Fix advances the path when the body is within
    ``_DOORWAY_ARRIVAL_RADIUS`` of the current doorway."""

    def test_at_doorway_path_advances_to_next_step(self, maze):
        # Pick a 3-step path: A → B → C with B reachable from A and
        # C reachable from B.
        a, neighbours_a = next(
            (i, n) for i, n in maze.room_graph.items() if len(n) >= 1)
        b = neighbours_a[0]
        # Find a neighbour of b that isn't a (so a 3-step path exists).
        c = next((n for n in maze.room_graph[b] if n != a), None)
        if c is None:
            pytest.skip("seed-42 maze didn't produce a 3-step path "
                         "from any starting room")
        ra = maze.rooms[a]
        # Place body exactly at the A↔B doorway midpoint.
        door_ab = maze.doorways[frozenset((a, b))]
        door_bc = maze.doorways.get(frozenset((b, c)))
        rb = maze.rooms[b]
        target_in_b = (rb.x + rb.w * 0.5, rb.y + rb.h * 0.5)
        p = WaypointPlanner(
            maze.rooms, maze.room_graph, maze.doorways)
        # Seed the path so the planner has a known sequence.
        p._path = [a, b, c]
        p._path_target_room = c
        p._replan_t = WaypointPlanner.REPLAN_INTERVAL
        # Body sitting on the A↔B doorway → planner should advance
        # past A and emit either the B↔C doorway or the centre of c.
        wp = p.plan(0.016, door_ab[0], door_ab[1],
                    target_in_b[0], target_in_b[1])
        assert wp is not None
        # Path must have shrunk by at least one step.
        assert p._path[0] != a, (
            f"path didn't advance past entered room {a}: "
            f"path={p._path}")
        # The new waypoint must NOT equal the doorway we just
        # arrived at — that's the whole point of advancing.
        assert wp != door_ab
    def test_no_progress_for_5_seconds_triggers_give_up(self, maze):
        p = WaypointPlanner(maze.rooms, maze.room_graph)
        # Pick start + target in different rooms.
        start_idx, neighbours = next(
            (i, n) for i, n in maze.room_graph.items() if n)
        target_idx = next(
            i for i in range(len(maze.rooms))
            if i != start_idx and i not in neighbours)
        sr = maze.rooms[start_idx]
        tr = maze.rooms[target_idx]
        sx = sr.x + sr.w * 0.5
        sy = sr.y + sr.h * 0.5
        tx = tr.x + tr.w * 0.5
        ty = tr.y + tr.h * 0.5

        # Tick for FAIL_TIMEOUT seconds at fixed (sx, sy) — body has
        # made zero progress.  Each frame the planner should still
        # produce a waypoint, until the give-up threshold is crossed.
        dt = 0.05
        ticks = int(WaypointPlanner.FAIL_TIMEOUT / dt) + 2
        gave_up_seen = False
        for _ in range(ticks):
            p.plan(dt, sx, sy, tx, ty)
            if p.gave_up():
                gave_up_seen = True
                break
        assert gave_up_seen, "planner should have given up by now"
        assert p.cooling_down() is True
        # During cooldown plan() must return None.
        assert p.plan(dt, sx, sy, tx, ty) is None

    def test_progress_resets_stuck_timer(self, maze):
        p = WaypointPlanner(maze.rooms, maze.room_graph)
        start_idx, neighbours = next(
            (i, n) for i, n in maze.room_graph.items() if n)
        target_idx = next(
            i for i in range(len(maze.rooms))
            if i != start_idx and i not in neighbours)
        sr = maze.rooms[start_idx]
        tr = maze.rooms[target_idx]
        sx = sr.x + sr.w * 0.5
        sy = sr.y + sr.h * 0.5
        tx = tr.x + tr.w * 0.5
        ty = tr.y + tr.h * 0.5

        # Move forward by STUCK_DIST every second so the timer keeps
        # resetting.  Tick for 2× the fail timeout — still no give-up.
        dt = 0.05
        total = 0.0
        gave_up_seen = False
        while total < WaypointPlanner.FAIL_TIMEOUT * 2:
            sx += WaypointPlanner.STUCK_DIST * dt   # ~30 px/s
            p.plan(dt, sx, sy, tx, ty)
            if p.gave_up():
                gave_up_seen = True
                break
            total += dt
        assert gave_up_seen is False, (
            "planner gave up despite continuous movement — stuck "
            "timer is not resetting on progress")
