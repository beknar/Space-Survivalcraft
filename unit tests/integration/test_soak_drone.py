"""5-minute soak tests for the active-drone update path.

Covers the scenarios most likely to surface long-tail leaks /
allocation bloat in the planner + drone integration:

  1. **Drone-only Star Maze idle** — drone deployed, player parked
     in a maze room.  Steady-state FOLLOW + slot picker every
     frame.
  2. **RETURN_HOME ping-pong** — teleport the player every 3 s
     between two rooms past the BREAK_OFF distance from the
     drone.  Forces the planner to A*-replan every cycle and the
     drone's ``_run_return_home`` cooldown wipe to fire
     constantly.
  3. **Maze entry / exit ping-pong** — teleport the player every
     3 s between inside-maze and outside-maze.  Hits the
     entrance-routing branch (``entrance_xy_outer`` → outer
     point past the gap) and the entry branch (body outside,
     target inside) in alternation, exactly the path the user
     reported as "spinning at the entrance".
  4. **Drone combat churn** — drone in ATTACK mode firing on a
     spawner whose HP is pinned.  Per-frame ``_aim_and_fire`` +
     ``_track_stuck_progress`` for 5 minutes.
  5. **Fleet menu order churn** — apply RETURN / ATTACK /
     FOLLOW_ONLY / ATTACK_ONLY in rotation every 5 s for 5
     minutes, with a moving player.  Catches state-mutation
     leaks in ``apply_fleet_order`` or any code path that
     allocates per order change.

Shared thresholds + loop live in ``_soak_base.py``.

Run with:
    pytest "unit tests/integration/test_soak_drone.py" -v -s
"""
from __future__ import annotations

import math

from constants import DRONE_BREAK_OFF_DIST
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


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


def _setup_drone_in_maze(gv):
    """Star Maze + invulnerable player + deployed combat drone in
    the centre of the first maze room."""
    make_invulnerable(gv)
    _enter_star_maze(gv)
    maze = _first_maze(gv)
    cx, cy = _room_centre(maze.rooms[0])
    gv.player.center_x = cx
    gv.player.center_y = cy
    d = _deploy_combat_drone(gv, cx + 30, cy + 30)
    return maze, d


# ═══════════════════════════════════════════════════════════════════════════
#  1. Idle FOLLOW — drone trails a stationary player
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDroneIdleFollow:
    def test_drone_idle_follow_5min_soak(self, real_game_view):
        """Drone in FOLLOW for 5 minutes with the player stationary
        inside a maze room.  Pins the slot picker + planner no-op
        path against any per-frame allocation."""
        gv = real_game_view
        _setup_drone_in_maze(gv)

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Drone idle FOLLOW", tick)


# ═══════════════════════════════════════════════════════════════════════════
#  2. RETURN_HOME ping-pong — teleport the player past BREAK_OFF
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDroneReturnHomePingPong:
    def test_drone_return_home_ping_pong_5min_soak(
            self, real_game_view):
        """Teleport the player every 3 s between two rooms past
        the 800 px break-off so the drone cycles RETURN_HOME →
        FOLLOW → RETURN_HOME continuously.  Hits the planner's
        A* replan + cooldown wipe + un-stick nudge tracker
        every 3-second window for 5 minutes."""
        gv = real_game_view
        maze, d = _setup_drone_in_maze(gv)
        ax, ay = _room_centre(maze.rooms[0])
        bx, by = _room_centre(maze.rooms[-1])
        # Confirm the two anchor points are far enough apart.
        assert math.hypot(bx - ax, by - ay) > DRONE_BREAK_OFF_DIST
        step = {"n": 0, "side": 0}

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            # 3 s @ 60 fps = 180 frames.
            if step["n"] % 180 == 0:
                if step["side"] == 0:
                    gv.player.center_x = ax
                    gv.player.center_y = ay
                else:
                    gv.player.center_x = bx
                    gv.player.center_y = by
                step["side"] = 1 - step["side"]
            gv.on_update(dt)
            gv.on_draw()
            step["n"] += 1

        run_soak(gv, "Drone RETURN_HOME ping-pong", tick)


# ═══════════════════════════════════════════════════════════════════════════
#  3. Entry/exit ping-pong — drone crosses the entrance gap repeatedly
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDroneEntryExitPingPong:
    def test_drone_entry_exit_5min_soak(self, real_game_view):
        """Teleport the player every 3 s between INSIDE the entrance
        room and OUTSIDE the maze on the entrance side.  The drone
        repeatedly traverses the entrance gap in both directions —
        the path the user originally reported as "spins at the
        entrance for 5 s".  Pins that no per-frame allocation or
        planner state leak builds up across hundreds of crossings."""
        gv = real_game_view
        maze, d = _setup_drone_in_maze(gv)
        # Anchor 1: inside the entrance room.
        in_x, in_y = _room_centre(maze.rooms[maze.entrance_room])
        # Anchor 2: outside the maze along the entrance outward axis.
        outer_dx = maze.entrance_xy_outer[0] - maze.entrance_xy[0]
        outer_dy = maze.entrance_xy_outer[1] - maze.entrance_xy[1]
        outer_len = math.hypot(outer_dx, outer_dy)
        nx = outer_dx / outer_len
        ny = outer_dy / outer_len
        out_x = maze.entrance_xy[0] + nx * 450
        out_y = maze.entrance_xy[1] + ny * 450
        step = {"n": 0, "outside": False}

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            if step["n"] % 180 == 0:
                if step["outside"]:
                    gv.player.center_x = out_x
                    gv.player.center_y = out_y
                else:
                    gv.player.center_x = in_x
                    gv.player.center_y = in_y
                step["outside"] = not step["outside"]
            gv.on_update(dt)
            gv.on_draw()
            step["n"] += 1

        run_soak(gv, "Drone entry/exit ping-pong", tick)


# ═══════════════════════════════════════════════════════════════════════════
#  4. ATTACK churn — drone firing every cooldown on a pinned-HP spawner
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDroneAttackChurn:
    def test_drone_attack_churn_5min_soak(self, real_game_view):
        """Drone in ATTACK mode firing on a spawner for 5 minutes.
        Pinned spawner HP keeps combat hot the whole window so
        ``_aim_and_fire``, ``_track_stuck_progress``, projectile
        creation, and the spawner-priority targeting path all run
        continuously."""
        gv = real_game_view
        maze, d = _setup_drone_in_maze(gv)
        cx, cy = _room_centre(maze.rooms[0])
        # Move the closest spawner inside detect range with clear LOS.
        sp = list(gv._zone._spawners)[0]
        sp.center_x = cx + 200
        sp.center_y = cy
        sp.killed = False
        target_hp = 100000
        sp.hp = target_hp

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            sp.hp = target_hp           # pin so combat doesn't end
            sp.killed = False
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Drone ATTACK churn", tick)


# ═══════════════════════════════════════════════════════════════════════════
#  5. Fleet order rotation — RETURN / ATTACK / FOLLOW_ONLY / ATTACK_ONLY
# ═══════════════════════════════════════════════════════════════════════════


class TestSoakDroneFleetOrderRotation:
    def test_drone_fleet_order_rotation_5min_soak(
            self, real_game_view):
        """Cycle through every Fleet menu order every 5 s for 5
        minutes with a moving player.  Catches any state-mutation
        leak in ``apply_fleet_order`` and verifies the mode
        machine handles back-to-back order swaps without
        accumulating side-effects."""
        from combat_helpers import apply_fleet_order
        gv = real_game_view
        maze, d = _setup_drone_in_maze(gv)
        ax, ay = _room_centre(maze.rooms[0])
        bx, by = _room_centre(maze.rooms[-1])
        orders = ["return", "attack", "follow_only", "attack_only"]
        step = {"n": 0, "order_idx": 0, "side": 0}

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            # Rotate the order every 5 s = 300 frames.
            if step["n"] % 300 == 0:
                apply_fleet_order(
                    gv, orders[step["order_idx"]
                                % len(orders)])
                step["order_idx"] += 1
            # Move the player every 2 s = 120 frames so RETURN /
            # ATTACK have something to react to.
            if step["n"] % 120 == 0:
                if step["side"] == 0:
                    gv.player.center_x = ax
                    gv.player.center_y = ay
                else:
                    gv.player.center_x = bx
                    gv.player.center_y = by
                step["side"] = 1 - step["side"]
            gv.on_update(dt)
            gv.on_draw()
            step["n"] += 1

        run_soak(gv, "Drone Fleet order rotation", tick)
