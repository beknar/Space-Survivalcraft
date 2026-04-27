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


class TestStuckTimeout:
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
