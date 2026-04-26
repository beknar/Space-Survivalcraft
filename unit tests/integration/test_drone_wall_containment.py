"""Integration tests for drone vs Star-Maze-wall containment.

Two failure modes have been seen historically:

1) Slow drift overlap — drone ends a frame partially inside a
   wall AABB without tunneling.  The iterative push-out
   (5 iters in update_logic.update_drone) handles this case.

2) Tunnel-through — the orbit target moves to the far side of a
   wall (player teleport, sudden direction change) and the drone
   crosses the wall in a single tick.  The pre-move snapshot +
   segment-vs-wall revert in update_logic.update_drone handles
   this case.

These tests exercise BOTH modes against a real GameView with a
real Star Maze, real walls, and the real drone update loop —
the fast stub tests in ``unit tests/test_drone_maze_containment.py``
only verify the helper hooks.

Run with:
    pytest "unit tests/integration/test_drone_wall_containment.py" -v
"""
from __future__ import annotations

import pytest

from zones import ZoneID


def _pick_tall_wall(walls):
    """Return the tallest vertical wall in the list — guarantees a
    long thin barrier the drone is forced to cross to follow the
    player teleport."""
    best = None
    best_h = 0.0
    for w in walls:
        if w.h > best_h and w.h > w.w:
            best_h = w.h
            best = w
    return best


def _pick_wide_wall(walls):
    """Return the widest horizontal wall (orthogonal axis test)."""
    best = None
    best_w = 0.0
    for w in walls:
        if w.w > best_w and w.w > w.h:
            best_w = w.w
            best = w
    return best


def _wall_inside(wall, x, y):
    return (wall.x <= x <= wall.x + wall.w
            and wall.y <= y <= wall.y + wall.h)


def _spawn_combat_drone(gv, x, y, orbit_angle: float = 0.0):
    """Spawn a CombatDrone with a deterministic orbit angle so the
    drone's follow-target sits in a known direction relative to the
    player.  ``CombatDrone.__init__`` randomises ``_orbit_angle``;
    overriding it here makes the wall-crossing tests reproducible."""
    from sprites.drone import CombatDrone
    d = CombatDrone(x, y)
    d._orbit_angle = orbit_angle
    gv._drone_list.append(d)
    gv._active_drone = d
    return d


# ── Tunnel-through (fast cross) ──────────────────────────────────────────

class TestDroneTunnelThrough:
    """Drone must NOT pass through a maze wall when its orbit target
    is teleported to the opposite side."""

    def test_vertical_wall_left_to_right(self, real_game_view):
        # Place player + drone on the LEFT, teleport the player
        # RIGHT, and force the orbit target to point RIGHT through
        # the wall.  Containment must keep the drone on the left.
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        wall = _pick_tall_wall(gv._zone._walls)
        assert wall is not None, "no vertical wall in zone"
        left_x = wall.x - 100.0
        mid_y = wall.y + wall.h / 2
        gv.player.center_x = left_x
        gv.player.center_y = mid_y
        # Orbit angle 0 → target offset at (+FOLLOW_DIST, 0) — RIGHT
        # of the player, so the drone is dragged toward the wall.
        d = _spawn_combat_drone(gv, left_x, mid_y, orbit_angle=0.0)
        gv.player.center_x = wall.x + wall.w + 100.0
        import update_logic
        for _ in range(60):
            update_logic.update_drone(gv, 1 / 60)
            assert d.center_x <= wall.x + wall.w, (
                f"drone tunneled through wall: x={d.center_x:.1f}, "
                f"wall right edge={wall.x + wall.w}"
            )

    def test_vertical_wall_right_to_left(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        wall = _pick_tall_wall(gv._zone._walls)
        right_x = wall.x + wall.w + 100.0
        mid_y = wall.y + wall.h / 2
        gv.player.center_x = right_x
        gv.player.center_y = mid_y
        # Orbit angle 180 → target offset at (-FOLLOW_DIST, 0) — LEFT.
        d = _spawn_combat_drone(gv, right_x, mid_y, orbit_angle=180.0)
        gv.player.center_x = wall.x - 100.0
        import update_logic
        for _ in range(60):
            update_logic.update_drone(gv, 1 / 60)
            assert d.center_x >= wall.x, (
                f"drone tunneled left through wall: x={d.center_x:.1f}, "
                f"wall left edge={wall.x}"
            )

    def test_horizontal_wall_bottom_to_top(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        wall = _pick_wide_wall(gv._zone._walls)
        assert wall is not None, "no horizontal wall in zone"
        below_y = wall.y - 100.0
        mid_x = wall.x + wall.w / 2
        gv.player.center_x = mid_x
        gv.player.center_y = below_y
        # Orbit angle 90 → target offset at (0, +FOLLOW_DIST) — UP.
        d = _spawn_combat_drone(gv, mid_x, below_y, orbit_angle=90.0)
        gv.player.center_y = wall.y + wall.h + 100.0
        import update_logic
        for _ in range(60):
            update_logic.update_drone(gv, 1 / 60)
            assert d.center_y <= wall.y + wall.h, (
                f"drone tunneled up through wall: y={d.center_y:.1f}, "
                f"wall top edge={wall.y + wall.h}"
            )


# ── Drift overlap ────────────────────────────────────────────────────────

class TestDroneSlowOverlap:
    """A drone parked at the edge of a wall must be pushed clear by
    the iterative containment pass — it should never end a frame
    with its centre inside a wall AABB."""

    def test_drone_pushed_out_when_spawned_inside_wall(
        self, real_game_view,
    ):
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        wall = _pick_tall_wall(gv._zone._walls)
        # Park the player just outside the wall + drop the drone
        # directly inside the wall AABB.  After one update tick
        # the drone must be outside.
        gv.player.center_x = wall.x - 100.0
        gv.player.center_y = wall.y + wall.h / 2
        d = _spawn_combat_drone(
            gv, wall.x + wall.w / 2, wall.y + wall.h / 2)
        import update_logic
        update_logic.update_drone(gv, 1 / 60)
        assert not _wall_inside(wall, d.center_x, d.center_y), (
            f"drone still inside wall after push-out: "
            f"({d.center_x:.1f}, {d.center_y:.1f})"
        )

    def test_drone_never_ends_frame_inside_any_wall(
        self, real_game_view,
    ):
        """Stress test — fly the player back and forth across a
        wall boundary and confirm the drone is never inside ANY
        wall at end-of-frame across many ticks."""
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        wall = _pick_tall_wall(gv._zone._walls)
        mid_y = wall.y + wall.h / 2
        d = _spawn_combat_drone(
            gv, wall.x - 100.0, mid_y)
        import update_logic
        # 5 iterations of "teleport across, settle, teleport back".
        for _cycle in range(5):
            gv.player.center_x = wall.x + wall.w + 80.0
            gv.player.center_y = mid_y
            for _ in range(20):
                update_logic.update_drone(gv, 1 / 60)
                for w in gv._zone._walls:
                    assert not _wall_inside(w, d.center_x, d.center_y), (
                        f"drone inside wall at "
                        f"({d.center_x:.1f}, {d.center_y:.1f})"
                    )
            gv.player.center_x = wall.x - 80.0
            for _ in range(20):
                update_logic.update_drone(gv, 1 / 60)
                for w in gv._zone._walls:
                    assert not _wall_inside(w, d.center_x, d.center_y)


# ── Mining drone parity ──────────────────────────────────────────────────

class TestMiningDroneAlsoBlocked:
    """The same containment must apply to the mining drone — both
    drone classes share update_logic.update_drone."""

    def test_mining_drone_does_not_tunnel(self, real_game_view):
        from sprites.drone import MiningDrone
        gv = real_game_view
        gv._transition_zone(ZoneID.STAR_MAZE)
        wall = _pick_tall_wall(gv._zone._walls)
        gv.player.center_x = wall.x - 100.0
        gv.player.center_y = wall.y + wall.h / 2
        d = MiningDrone(wall.x - 100.0, wall.y + wall.h / 2)
        d._orbit_angle = 0.0  # target offset RIGHT
        gv._drone_list.append(d)
        gv._active_drone = d
        gv.player.center_x = wall.x + wall.w + 100.0
        import update_logic
        for _ in range(60):
            update_logic.update_drone(gv, 1 / 60)
            assert d.center_x <= wall.x + wall.w
