"""Tests for the companion-drone system.

Covers MiningDrone + CombatDrone construction, follow-orbit physics,
take_damage shield routing, deploy_drone gating (inventory check,
weapon-aware variant pick, one-at-a-time replace, no-op same-variant),
and the asteroid / pickup / enemy targeting helpers.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import arcade
import pytest

from constants import (
    DRONE_HP, DRONE_MAX_SPEED, DRONE_FOLLOW_DIST,
    DRONE_FIRE_COOLDOWN, DRONE_LASER_RANGE,
    MINING_DRONE_LASER_DAMAGE, COMBAT_DRONE_LASER_DAMAGE,
    MINING_DRONE_SHIELD, COMBAT_DRONE_SHIELD,
    MINING_DRONE_PICKUP_RADIUS, MINING_DRONE_MINING_RANGE,
    DRONE_SCALE,
)


# ── Construction + scaling ─────────────────────────────────────────────────

class TestDroneConstruction:
    def test_mining_drone_basic_stats(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(100.0, 200.0)
        assert d.hp == DRONE_HP
        assert d.max_hp == DRONE_HP
        assert d.shields == MINING_DRONE_SHIELD == 0
        assert d._mines_rock is True
        assert d._laser_damage == MINING_DRONE_LASER_DAMAGE
        assert d.center_x == 100.0
        assert d.center_y == 200.0

    def test_combat_drone_basic_stats(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        assert d.hp == DRONE_HP
        assert d.shields == COMBAT_DRONE_SHIELD == 25
        assert d._mines_rock is False
        assert d._laser_damage == COMBAT_DRONE_LASER_DAMAGE

    def test_drone_scale_is_quarter_of_player(self):
        # Player ship renders at scale 0.75 on a 128 px sheet (= 96 px
        # on screen); a "1/4 size" drone scales to 0.75 / 4 = 0.1875.
        # Arcade 3 stores scale as a (sx, sy) tuple; both axes match.
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        sx, sy = d.scale
        assert sx == pytest.approx(0.1875)
        assert sy == pytest.approx(0.1875)
        assert DRONE_SCALE == pytest.approx(0.1875)


# ── Damage routing ─────────────────────────────────────────────────────────

class TestDroneDamage:
    def test_mining_drone_no_shield_takes_full_hp_hit(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        d.take_damage(20)
        assert d.hp == DRONE_HP - 20
        assert d.shields == 0

    def test_combat_drone_shield_absorbs_first(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d.take_damage(10)
        assert d.shields == COMBAT_DRONE_SHIELD - 10
        assert d.hp == DRONE_HP

    def test_combat_drone_overflow_falls_through_to_hp(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d.take_damage(COMBAT_DRONE_SHIELD + 12)
        assert d.shields == 0
        assert d.hp == DRONE_HP - 12

    def test_dead_property(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        d.hp = 0
        assert d.dead is True


# ── Follow / slot picking ──────────────────────────────────────────────────

class TestDroneFollow:
    def test_drone_steers_toward_player_offset(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(1000.0, 1000.0)
        # Two-arg signature defaults to LEFT slot of a heading=0 ship —
        # target = (player_x - FOLLOW_DIST, player_y).
        d.follow(0.5, 500.0, 500.0)
        # Drone at (1000, 1000) moving toward (420, 500) — both axes
        # should have decreased.
        assert d.center_x < 1000.0
        assert d.center_y < 1000.0

    def test_step_capped_at_distance_no_overshoot(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        # Big dt would normally overshoot; the per-tick step is
        # min(MAX_SPEED * dt, dist) so the drone arrives exactly at
        # the LEFT slot of a heading=0 player at (FOLLOW_DIST, 0):
        # slot = (-FOLLOW_DIST, 0).
        d.follow(10.0, 0.0, 0.0)
        assert d.center_x == pytest.approx(-DRONE_FOLLOW_DIST, abs=1e-3)
        assert d.center_y == pytest.approx(0.0, abs=1e-3)

    def test_max_speed_per_tick(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        # Player far away → drone moves DRONE_MAX_SPEED * dt this
        # frame regardless of slot.
        d.follow(0.1, 1000.0, 0.0)
        import math
        moved = math.hypot(d.center_x, d.center_y)
        assert moved == pytest.approx(DRONE_MAX_SPEED * 0.1, abs=0.5)


class TestDroneSlotPicking:
    def test_default_slot_is_left_of_player(self):
        """Heading=0 player → LEFT slot is straight west of the player."""
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=500.0, center_y=500.0,
                                  heading=0.0)
        sx, sy = d._pick_follow_slot(player, walls=None)
        assert sx == pytest.approx(500.0 - DRONE_FOLLOW_DIST)
        assert sy == pytest.approx(500.0)

    def test_left_blocked_falls_back_to_right(self):
        """LEFT slot lands inside a wall → drone picks RIGHT instead."""
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=500.0, center_y=500.0,
                                  heading=0.0)
        # Wall covering the LEFT slot at (420, 500).
        walls = [(400.0, 480.0, 40.0, 40.0)]
        sx, sy = d._pick_follow_slot(player, walls)
        assert sx == pytest.approx(500.0 + DRONE_FOLLOW_DIST)
        assert sy == pytest.approx(500.0)

    def test_left_and_right_blocked_falls_back_to_back(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=500.0, center_y=500.0,
                                  heading=0.0)
        # Walls covering BOTH lateral slots — LEFT (420, 500) and
        # RIGHT (580, 500).
        walls = [(400.0, 480.0, 40.0, 40.0),
                 (560.0, 480.0, 40.0, 40.0)]
        sx, sy = d._pick_follow_slot(player, walls)
        # BACK = heading=0 → directly south of player at y - FOLLOW_DIST.
        assert sx == pytest.approx(500.0)
        assert sy == pytest.approx(500.0 - DRONE_FOLLOW_DIST)


class TestDroneFollowAttackMode:
    def test_no_target_keeps_follow_mode(self):
        from sprites.drone import CombatDrone, _BaseDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=0.0, center_y=0.0)
        d._update_mode(player, target=None)
        assert d._mode == _BaseDrone._MODE_FOLLOW

    def test_target_in_range_enters_attack(self):
        from sprites.drone import CombatDrone, _BaseDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=0.0, center_y=0.0)
        target = SimpleNamespace(center_x=100.0, center_y=0.0, hp=100)
        d._update_mode(player, target)
        assert d._mode == _BaseDrone._MODE_ATTACK

    def test_player_far_breaks_off_to_return_home(self):
        from sprites.drone import CombatDrone, _BaseDrone
        from constants import DRONE_BREAK_OFF_DIST
        d = CombatDrone(0.0, 0.0)
        # Player past BREAK_OFF + a target right next to drone.  The
        # >800 px rule wins — drone enters RETURN_HOME and ignores
        # the enemy until it's reeled back in.
        player = SimpleNamespace(
            center_x=DRONE_BREAK_OFF_DIST + 1.0, center_y=0.0)
        target = SimpleNamespace(center_x=50.0, center_y=0.0, hp=100)
        d._mode = _BaseDrone._MODE_ATTACK
        d._update_mode(player, target)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME

    def test_wall_between_drone_and_target_disengages(self):
        """Line-of-sight is broken by a wall between drone and target
        → drone returns to FOLLOW and won't fire."""
        from sprites.drone import CombatDrone, _BaseDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=0.0, center_y=0.0,
                                  heading=0.0)
        # Target 200 px to the east, well within DETECT_RANGE.
        target = SimpleNamespace(center_x=200.0, center_y=0.0, hp=100)
        # Wall sitting between drone (at x=0) and target (at x=200).
        walls = [(80.0, -20.0, 40.0, 40.0)]
        d._update_mode(player, target, walls)
        assert d._mode == _BaseDrone._MODE_FOLLOW

    def test_no_wall_between_drone_and_target_engages(self):
        """Same range, no wall between → drone engages (ATTACK)."""
        from sprites.drone import CombatDrone, _BaseDrone
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(center_x=0.0, center_y=0.0,
                                  heading=0.0)
        target = SimpleNamespace(center_x=200.0, center_y=0.0, hp=100)
        # Wall placed off-axis so it doesn't intersect the drone-to-
        # target segment.
        walls = [(80.0, 200.0, 40.0, 40.0)]
        d._update_mode(player, target, walls)
        assert d._mode == _BaseDrone._MODE_ATTACK


class TestDroneTooltip:
    """Hover tooltip wording — the player needs to read HP, shield
    (when present), and AI state at a glance to decide whether to
    recall the drone."""

    def test_combat_drone_default_tooltip_includes_shield_and_following(self):
        from sprites.drone import CombatDrone, drone_tooltip_text
        d = CombatDrone(0.0, 0.0)
        text = drone_tooltip_text(d)
        assert "Combat Drone" in text
        assert f"HP {d.hp}/{d.max_hp}" in text
        # Combat drone has 25 max shields → segment must appear.
        assert "Shield" in text
        assert "Following" in text

    def test_mining_drone_tooltip_omits_shield_when_zero_max(self):
        """Mining drones have ``max_shields = 0`` — the Shield
        segment must not appear in their tooltip."""
        from sprites.drone import MiningDrone, drone_tooltip_text
        d = MiningDrone(0.0, 0.0)
        text = drone_tooltip_text(d)
        assert "Mining Drone" in text
        assert "Shield" not in text

    def test_hunting_status_in_attack_mode(self):
        from sprites.drone import (
            CombatDrone, _BaseDrone, drone_status_label)
        d = CombatDrone(0.0, 0.0)
        d._mode = _BaseDrone._MODE_ATTACK
        assert drone_status_label(d) == "Hunting enemy"

    def test_returning_status_in_return_home_mode(self):
        from sprites.drone import (
            CombatDrone, _BaseDrone, drone_status_label)
        d = CombatDrone(0.0, 0.0)
        d._mode = _BaseDrone._MODE_RETURN_HOME
        assert drone_status_label(d) == "Returning to ship"

    def test_stuck_overrides_other_modes(self):
        """Active stuck cooldown wins over the mode flag — the drone
        is frozen and the player should know."""
        from sprites.drone import (
            CombatDrone, _BaseDrone, drone_status_label)
        d = CombatDrone(0.0, 0.0)
        d._mode = _BaseDrone._MODE_ATTACK
        d._target_cooldown = 3.0
        assert drone_status_label(d) == "Stuck — holding"

    def test_stuck_behind_wall_at_far_distance_status_is_stuck(self):
        """Regression: drone wedged behind a maze wall while the
        player sits 800+ px away in another room.  The planner ticks
        without finding a navigable approach (drone can't reach the
        path's first room because a wall is in the way), and after
        1 s of no-progress the status must read "Stuck" — not
        "Following" / "Returning to ship", which leaves the player
        thinking the drone's still on its way.

        Reproduces the user-reported case end-to-end through the
        WaypointPlanner.  No GameView / arcade window needed."""
        from sprites.drone import (
            CombatDrone, _BaseDrone, drone_status_label)
        from zones.maze_geometry import generate_maze, WaypointPlanner

        # Deterministic maze + the two rooms farthest from each
        # other so the drone-to-player straight-line distance clears
        # the 800 px threshold called out in the user report.
        maze = generate_maze(0.0, 0.0, seed=42)
        import math as _m
        n = len(maze.rooms)
        best_pair = (0, 1)
        best_d = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                a, b = maze.rooms[i], maze.rooms[j]
                d2 = _m.hypot(
                    (a.x + a.w * 0.5) - (b.x + b.w * 0.5),
                    (a.y + a.h * 0.5) - (b.y + b.h * 0.5))
                if d2 > best_d:
                    best_d = d2
                    best_pair = (i, j)
        start_idx, target_idx = best_pair
        sr = maze.rooms[start_idx]
        tr = maze.rooms[target_idx]
        drone_x = sr.x + sr.w * 0.5
        drone_y = sr.y + sr.h * 0.5
        player_x = tr.x + tr.w * 0.5
        player_y = tr.y + tr.h * 0.5

        # Sanity check — the two endpoints are well past 800 px so
        # this matches the user's "800 px away" scenario.
        import math
        assert math.hypot(player_x - drone_x,
                          player_y - drone_y) > 800.0

        d = CombatDrone(drone_x, drone_y)
        d._follow_planner = WaypointPlanner(maze.rooms, maze.room_graph)

        # Run the planner ticks without moving the drone (simulates
        # being wedged on a wall corner).  After the planner-stall
        # threshold (1 s) the status must surface "Stuck".
        dt = 0.05
        for _ in range(int(1.5 / dt)):
            d._follow_planner.plan(
                dt, d.center_x, d.center_y, player_x, player_y)
        assert d._follow_planner._stuck_t >= 1.0, (
            "planner stall timer didn't reach 1 s — test setup "
            "failed to reproduce the stuck condition")

        status = drone_status_label(d)
        assert "Stuck" in status, (
            f"Drone wedged behind a wall {math.hypot(player_x - drone_x, player_y - drone_y):.0f} px from player "
            f"reports status='{status}' instead of a 'Stuck' state. "
            "Planner-stall timer fix lost.")


class TestDroneUnstickNudge:
    """Safety-net nudge — when the drone hasn't physically moved for
    half a second while it should be heading somewhere, slide one
    frame perpendicular to the steering vector to dislodge from a
    wall corner."""

    def _drone(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        return d

    def test_nudge_does_not_fire_immediately(self):
        """First call only sets the anchor — must not return True."""
        d = self._drone()
        fired = d._try_unstick_nudge(0.05, 100.0, 0.0)
        assert fired is False

    def test_nudge_does_not_fire_when_drone_is_progressing(self):
        """Drone making real progress (>NUDGE_DIST in <NUDGE_TIME)
        must reset the timer, not nudge."""
        d = self._drone()
        d._try_unstick_nudge(0.05, 100.0, 0.0)  # anchor
        # Move past the threshold.
        d.center_x = 50.0
        fired = d._try_unstick_nudge(0.05, 100.0, 0.0)
        assert fired is False
        assert d._nudge_timer == 0.0

    def test_nudge_fires_after_half_second_of_no_movement(self):
        """Drone wedged at the same coords for 0.5+ s while wanting
        to head somewhere → nudge perpendicular for one frame."""
        from sprites.drone import _BaseDrone
        d = self._drone()
        # First call anchors at the origin.
        d._try_unstick_nudge(0.05, 100.0, 0.0)
        before = (d.center_x, d.center_y)
        fired_any = False
        # Tick for >= NUDGE_TIME without moving.
        for _ in range(int(_BaseDrone._NUDGE_TIME / 0.05) + 2):
            if d._try_unstick_nudge(0.05, 100.0, 0.0):
                fired_any = True
                break
        assert fired_any is True, "no nudge fired after wedge timeout"
        moved = (d.center_x - before[0]) ** 2 + (d.center_y - before[1]) ** 2
        assert moved > 0.0, "nudge fired but drone didn't move"

    def test_nudge_alternates_sides(self):
        """Two consecutive nudges should fire from opposite sides so
        a corner that blocks the right slide doesn't strand the drone."""
        from sprites.drone import _BaseDrone
        d = self._drone()
        d._try_unstick_nudge(0.05, 100.0, 0.0)  # anchor
        for _ in range(int(_BaseDrone._NUDGE_TIME / 0.05) + 2):
            if d._try_unstick_nudge(0.05, 100.0, 0.0):
                first_dir = d._nudge_dir   # was flipped on fire
                break
        # Hold position again until the next nudge fires.
        d.center_x = d.center_y = 0.0   # back to origin
        d._nudge_anchor_x = d._nudge_anchor_y = 0.0
        for _ in range(int(_BaseDrone._NUDGE_TIME / 0.05) + 2):
            if d._try_unstick_nudge(0.05, 100.0, 0.0):
                second_dir = d._nudge_dir
                break
        # Direction toggles each fire.
        assert first_dir != second_dir


class TestDroneReturnHomeMode:
    """Drone enters RETURN_HOME at >800 px from the player and stays
    in it (with hysteresis) until back inside 600 px.  RETURN_HOME
    ignores enemies entirely and keeps re-trying A* even after the
    planner gives up — the cooldown freeze that protects FOLLOW from
    grinding doesn't apply when the drone is trying to reunite with
    a player on the other side of the map."""

    def test_far_player_triggers_return_home(self):
        from sprites.drone import CombatDrone, _BaseDrone
        from constants import DRONE_BREAK_OFF_DIST
        d = CombatDrone(0.0, 0.0)
        # Player 900 px away — past BREAK_OFF (800).
        player = SimpleNamespace(
            center_x=DRONE_BREAK_OFF_DIST + 100.0, center_y=0.0,
            heading=0.0)
        # Even with an in-range target, mode must be RETURN_HOME.
        target = SimpleNamespace(center_x=50.0, center_y=0.0, hp=100)
        d._update_mode(player, target, walls=None)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME

    def test_return_home_hysteresis_holds_past_break_off(self):
        """Once in RETURN_HOME, the drone holds it down to 600 px
        instead of flipping back at 800 px."""
        from sprites.drone import CombatDrone, _BaseDrone
        d = CombatDrone(0.0, 0.0)
        d._mode = _BaseDrone._MODE_RETURN_HOME
        # Player at 700 px — below BREAK_OFF (800) but above EXIT
        # (600).  Should remain RETURN_HOME.
        player = SimpleNamespace(
            center_x=700.0, center_y=0.0, heading=0.0)
        d._update_mode(player, target=None, walls=None)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME

    def test_return_home_exits_at_close_range(self):
        from sprites.drone import CombatDrone, _BaseDrone
        d = CombatDrone(0.0, 0.0)
        d._mode = _BaseDrone._MODE_RETURN_HOME
        # Player at 500 px — inside EXIT (600) → should drop back to
        # FOLLOW with no target, or ATTACK if a target's in range.
        player = SimpleNamespace(
            center_x=500.0, center_y=0.0, heading=0.0)
        d._update_mode(player, target=None, walls=None)
        assert d._mode == _BaseDrone._MODE_FOLLOW

    def test_return_home_clears_planner_cooldown_each_frame(self):
        """The 5-s give-up freeze in WaypointPlanner must be reset
        every tick while RETURN_HOME is active so the drone keeps
        trying to A* its way back to the player."""
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        # Pretend the planner just gave up — cooldown active.
        d._follow_planner._cooldown_t = 4.5
        player = SimpleNamespace(
            center_x=2000.0, center_y=2000.0, heading=0.0)
        d._run_return_home(
            1 / 60, player.center_x, player.center_y, player,
            walls=None)
        # After one tick of RETURN_HOME the cooldown is wiped.
        assert d._follow_planner._cooldown_t == 0.0

    def test_return_home_moves_toward_player(self):
        """With no walls and a far-away player, the drone steps
        directly toward the player position."""
        from sprites.drone import CombatDrone
        import math
        d = CombatDrone(0.0, 0.0)
        player = SimpleNamespace(
            center_x=1000.0, center_y=0.0, heading=0.0)
        before = (d.center_x, d.center_y)
        d._run_return_home(
            0.1, player.center_x, player.center_y, player,
            walls=None)
        moved = math.hypot(d.center_x - before[0],
                           d.center_y - before[1])
        # DRONE_MAX_SPEED * dt per tick = 45 px at 0.1 s.
        assert moved > 30.0
        # Movement is along the +x axis (toward the player).
        assert d.center_x > 0.0


class TestCombatDronePrioritizesSpawners:
    """Maze spawners are priority targets for the combat drone —
    killing one halts its laser fire AND its alien drip, so it's
    much more impactful than picking off the next maze alien."""

    def _drone_at(self, x, y):
        from sprites.drone import CombatDrone
        return CombatDrone(x, y)

    def test_spawner_in_range_picked_over_closer_alien(self):
        """Spawner at 200 px and alien at 50 px — drone targets the
        spawner because it's the priority class, not the closest."""
        drone = self._drone_at(0.0, 0.0)
        spawner = SimpleNamespace(
            center_x=200.0, center_y=0.0, hp=500, killed=False)
        alien = SimpleNamespace(
            center_x=50.0, center_y=0.0, hp=60, killed=False)
        zone = SimpleNamespace(
            _spawners=[spawner],
            iter_enemies=lambda: iter([alien]))
        gv = SimpleNamespace(
            _zone=zone, alien_list=[alien],
            _boss=None, _nebula_boss=None)
        assert drone._nearest_enemy(gv) is spawner

    def test_killed_spawner_skipped(self):
        """A spawner currently in its dead/respawning phase should
        not be picked even though it's still in the list."""
        drone = self._drone_at(0.0, 0.0)
        dead = SimpleNamespace(
            center_x=200.0, center_y=0.0, hp=500, killed=True)
        alien = SimpleNamespace(
            center_x=50.0, center_y=0.0, hp=60)
        zone = SimpleNamespace(
            _spawners=[dead],
            iter_enemies=lambda: iter([alien]))
        gv = SimpleNamespace(
            _zone=zone, alien_list=[alien],
            _boss=None, _nebula_boss=None)
        assert drone._nearest_enemy(gv) is alien

    def test_spawner_out_of_range_falls_back_to_alien(self):
        """Spawner exists but sits beyond DRONE_DETECT_RANGE — drone
        falls through to the standard nearest-enemy pass and picks
        the in-range alien."""
        from constants import DRONE_DETECT_RANGE
        drone = self._drone_at(0.0, 0.0)
        far_sp = SimpleNamespace(
            center_x=DRONE_DETECT_RANGE + 100.0, center_y=0.0,
            hp=500, killed=False)
        alien = SimpleNamespace(
            center_x=50.0, center_y=0.0, hp=60)
        zone = SimpleNamespace(
            _spawners=[far_sp],
            iter_enemies=lambda: iter([alien]))
        gv = SimpleNamespace(
            _zone=zone, alien_list=[alien],
            _boss=None, _nebula_boss=None)
        assert drone._nearest_enemy(gv) is alien

    def test_no_spawners_attr_safe(self):
        """Zones without ``_spawners`` (Zone 1, Zone 2) are handled
        gracefully — drone falls through to the alien pass."""
        drone = self._drone_at(0.0, 0.0)
        alien = SimpleNamespace(
            center_x=50.0, center_y=0.0, hp=60)
        zone = SimpleNamespace(iter_enemies=lambda: iter([alien]))
        gv = SimpleNamespace(
            _zone=zone, alien_list=[alien],
            _boss=None, _nebula_boss=None)
        assert drone._nearest_enemy(gv) is alien


class TestDroneStackAndSave:
    def test_drone_max_stack_is_100(self):
        """Both drone consumables stack 100-deep per the spec."""
        from constants import MAX_STACK
        assert MAX_STACK["mining_drone"] == 100
        assert MAX_STACK["combat_drone"] == 100

    def test_serialize_active_drone_none_when_no_drone(self):
        from game_save import _serialize_active_drone
        gv = SimpleNamespace(_active_drone=None)
        assert _serialize_active_drone(gv) is None

    def test_serialize_round_trip_combat_drone(self):
        from game_save import (
            _serialize_active_drone, _restore_active_drone)
        from sprites.drone import CombatDrone
        d = CombatDrone(1234.0, 5678.0)
        d.hp = 42
        d.shields = 7
        gv = SimpleNamespace(_active_drone=d)
        blob = _serialize_active_drone(gv)
        assert blob["variant"] == "combat"
        assert blob["x"] == 1234.0
        assert blob["y"] == 5678.0
        assert blob["hp"] == 42
        assert blob["shields"] == 7
        # Reaction + direct order are persisted alongside HP since
        # the Fleet menu was added; default values are fine here.
        assert "reaction" in blob
        assert "direct_order" in blob
        # Round-trip into a fresh gv with the sprite-list scaffolding.
        gv2 = SimpleNamespace(
            _active_drone=None,
            _drone_list=arcade.SpriteList())
        _restore_active_drone(gv2, blob)
        assert gv2._active_drone is not None
        assert gv2._active_drone.__class__.__name__ == "CombatDrone"
        assert gv2._active_drone.center_x == 1234.0
        assert gv2._active_drone.center_y == 5678.0
        assert gv2._active_drone.hp == 42
        assert gv2._active_drone.shields == 7

    def test_serialize_round_trip_mining_drone(self):
        from game_save import (
            _serialize_active_drone, _restore_active_drone)
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        d.hp = 10
        gv = SimpleNamespace(_active_drone=d)
        blob = _serialize_active_drone(gv)
        assert blob["variant"] == "mining"
        gv2 = SimpleNamespace(
            _active_drone=None,
            _drone_list=arcade.SpriteList())
        _restore_active_drone(gv2, blob)
        assert gv2._active_drone.__class__.__name__ == "MiningDrone"
        assert gv2._active_drone.hp == 10


class TestPlayerProjectileVsAIShip:
    def test_player_lasers_skip_ai_piloted_parked_ship(self):
        """``handle_parked_ship_damage`` must not damage parked ships
        whose ``has_ai_pilot`` flag is True — the player's own
        weapons are friendly fire and should pass straight through.
        Unmanned parked ships still take the hit so the player can
        deliberately clear an old hull."""
        import collisions
        from sprites.explosion import HitSpark   # imported to verify no spark added

        # Build a minimal stub gv with a parked-ship sprite list and
        # one AI-piloted ship at (0, 0).
        ai_ship = SimpleNamespace(
            center_x=0.0, center_y=0.0, hp=100,
            has_ai_pilot=True,
            taken=[])
        ai_ship.take_damage = lambda amt: ai_ship.taken.append(amt)
        # Use a real arcade SpriteList so collision_with_list runs.
        ship_list = arcade.SpriteList()
        # Inject the stub via attribute hack: we monkeypatch the
        # collision helper itself so we don't need actual sprites.
        proj = SimpleNamespace(damage=10,
                                center_x=0.0, center_y=0.0,
                                remove_from_sprite_lists=lambda: None)
        proj_list = [proj]

        gv = SimpleNamespace(
            _parked_ships=ship_list,
            alien_projectile_list=[],
            projectile_list=proj_list,
            _boss=None,
            _boss_projectile_list=[],
            hit_sparks=[])

        # Patch the arcade collision call to return our stub ship.
        original = arcade.check_for_collision_with_list
        try:
            arcade.check_for_collision_with_list = lambda p, lst: (
                [ai_ship] if lst is ship_list and p is proj else [])
            # Make the parked-ships list non-empty (length check).
            class _Patched:
                def __len__(self):
                    return 1
            gv._parked_ships = _Patched()
            collisions.handle_parked_ship_damage(gv)
        finally:
            arcade.check_for_collision_with_list = original

        assert ai_ship.taken == [], (
            "AI-piloted ship took player friendly fire — should be "
            "immune.")
        assert gv.hit_sparks == [], (
            "No impact spark should fire on a friendly-fire pass-through")


# ── Fire path ──────────────────────────────────────────────────────────────

class TestDroneFire:
    def test_fire_returns_projectile_when_off_cooldown(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        proj = d._aim_and_fire(100.0, 0.0)
        assert proj is not None
        assert proj.damage == COMBAT_DRONE_LASER_DAMAGE
        # Cooldown was armed
        assert d._fire_cd == pytest.approx(DRONE_FIRE_COOLDOWN)

    def test_fire_blocked_by_cooldown(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d._fire_cd = 0.3
        assert d._aim_and_fire(100.0, 0.0) is None

    def test_fire_blocked_when_target_out_of_range(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        far = DRONE_LASER_RANGE + 100.0
        assert d._aim_and_fire(far, 0.0) is None

    def test_mining_drone_projectile_flagged_mines_rock(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        proj = d._aim_and_fire(50.0, 0.0)
        assert proj is not None
        assert proj.mines_rock is True
        assert proj.damage == MINING_DRONE_LASER_DAMAGE

    def test_combat_drone_projectile_not_mining(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        proj = d._aim_and_fire(50.0, 0.0)
        assert proj.mines_rock is False


# ── Mining-drone targeting ─────────────────────────────────────────────────

class TestMiningDroneTargeting:
    def _gv_with_asteroids(self, *positions):
        gv = SimpleNamespace(
            _zone=SimpleNamespace(
                _iron_asteroids=[],
                _double_iron=[],
                _copper_asteroids=[],
            ),
        )
        for x, y in positions:
            gv._zone._iron_asteroids.append(
                SimpleNamespace(center_x=x, center_y=y))
        return gv

    def test_picks_nearest_asteroid_in_range(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        gv = self._gv_with_asteroids((100.0, 0.0), (200.0, 0.0))
        target = d._nearest_asteroid(gv)
        assert target.center_x == 100.0

    def test_returns_none_when_no_asteroids_in_range(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        gv = self._gv_with_asteroids((MINING_DRONE_MINING_RANGE + 50.0, 0.0))
        assert d._nearest_asteroid(gv) is None

    def test_pickup_vacuum_flags_nearby_pickups(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        # Stub a pickup with the bare interface update_drone touches.
        nearby = SimpleNamespace(center_x=50.0, center_y=0.0, _flying=False)
        far = SimpleNamespace(
            center_x=MINING_DRONE_PICKUP_RADIUS + 50.0,
            center_y=0.0, _flying=False,
        )
        gv = SimpleNamespace(
            iron_pickup_list=[nearby, far],
            blueprint_pickup_list=[],
            player=SimpleNamespace(center_x=0.0, center_y=0.0),
            _zone=SimpleNamespace(
                _iron_asteroids=[],
                _double_iron=[],
                _copper_asteroids=[],
            ),
        )
        d.update_drone(0.016, gv)
        assert nearby._flying is True
        assert far._flying is False


# ── Combat-drone targeting ─────────────────────────────────────────────────

class TestCombatDroneTargeting:
    def test_picks_nearest_alive_enemy(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        # Fake aliens — nearest is at (100, 0); the dead one at (50, 0)
        # must be skipped (hp <= 0).
        alive = SimpleNamespace(center_x=100.0, center_y=0.0, hp=10)
        dead = SimpleNamespace(center_x=50.0, center_y=0.0, hp=0)
        gv = SimpleNamespace(
            alien_list=[dead, alive],
            _boss=None,
            _nebula_boss=None,
        )
        target = d._nearest_enemy(gv)
        assert target is alive

    def test_returns_none_when_no_enemies_in_range(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        gv = SimpleNamespace(alien_list=[], _boss=None, _nebula_boss=None)
        assert d._nearest_enemy(gv) is None

    def test_includes_boss_as_target(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        gv = SimpleNamespace(
            alien_list=[],
            _boss=SimpleNamespace(center_x=200.0, center_y=0.0, hp=2000),
            _nebula_boss=None,
        )
        assert d._nearest_enemy(gv) is gv._boss

    def _zone_with(self, aliens=(), maze_aliens=(), stalkers=()):
        # Build a stub zone exposing the same iter_enemies contract
        # ZoneState provides — yields each list deduped by id.
        from zones import ZoneState
        z = SimpleNamespace(
            _aliens=list(aliens),
            _maze_aliens=list(maze_aliens),
            _stalkers=list(stalkers),
            iter_enemies=lambda: ZoneState.iter_enemies(z),
        )
        return z

    def test_includes_zone_aliens_when_alien_list_swapped(self):
        # Regression: in the Star Maze, gv.alien_list is swapped to
        # ``self._maze_aliens`` mid-frame.  The drone must still see
        # ``zone._aliens`` (Z2 aliens) and ``zone._stalkers``.
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        z2_alien = SimpleNamespace(center_x=120.0, center_y=0.0, hp=50)
        stalker = SimpleNamespace(center_x=80.0, center_y=0.0, hp=75)
        zone = self._zone_with(aliens=[z2_alien], stalkers=[stalker])
        gv = SimpleNamespace(
            alien_list=[],   # empty: simulates the post-swap state
            _zone=zone,
            _boss=None,
            _nebula_boss=None,
        )
        # Stalker is closer (80 vs 120) — must be picked.
        assert d._nearest_enemy(gv) is stalker

    def test_includes_zone_maze_aliens(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        maze_alien = SimpleNamespace(center_x=50.0, center_y=0.0, hp=60)
        zone = self._zone_with(maze_aliens=[maze_alien])
        gv = SimpleNamespace(
            alien_list=[],
            _zone=zone,
            _boss=None,
            _nebula_boss=None,
        )
        assert d._nearest_enemy(gv) is maze_alien

    def test_dedupes_when_alien_list_is_zone_list(self):
        # If gv.alien_list IS the same object as zone._aliens (Zone 2
        # default), the drone must not double-count it.  Use the
        # alien's id() to dedupe — same alive count as the source.
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        a = SimpleNamespace(center_x=100.0, center_y=0.0, hp=50)
        zone_aliens = [a]
        zone = SimpleNamespace(
            _aliens=zone_aliens,
            _maze_aliens=[],
            _stalkers=[],
        )
        gv = SimpleNamespace(
            alien_list=zone_aliens,    # same list
            _zone=zone,
            _boss=None,
            _nebula_boss=None,
        )
        # Should still pick alien `a` (no exception, no double-count).
        assert d._nearest_enemy(gv) is a


# ── deploy_drone ──────────────────────────────────────────────────────────

class _StubInventory:
    def __init__(self, items=None):
        self._items = items or {}

    def count_item(self, name):
        return self._items.get(name, 0)

    def remove_item(self, name, qty):
        self._items[name] = max(0, self._items.get(name, 0) - qty)

    def add_item(self, name, qty=1):
        self._items[name] = self._items.get(name, 0) + qty


def _make_deploy_gv(*, mines_rock: bool, items=None):
    """Minimal GV for testing deploy_drone."""
    gv = SimpleNamespace(
        _escape_menu=SimpleNamespace(open=False),
        _player_dead=False,
        _active_weapon=SimpleNamespace(mines_rock=mines_rock),
        inventory=_StubInventory(items or {"mining_drone": 5,
                                            "combat_drone": 5}),
        player=SimpleNamespace(center_x=500.0, center_y=500.0),
        _drone_list=arcade.SpriteList(),
        _active_drone=None,
        _flash_msg="",
        _flash_timer=0.0,
        _zone=SimpleNamespace(zone_id=None),
        _null_fields=[],
    )
    return gv


class TestDeployDrone:
    def test_mining_beam_active_deploys_mining_drone(self):
        from combat_helpers import deploy_drone
        gv = _make_deploy_gv(mines_rock=True)
        deploy_drone(gv)
        assert gv._active_drone is not None
        assert type(gv._active_drone).__name__ == "MiningDrone"
        assert gv.inventory.count_item("mining_drone") == 4

    def test_basic_laser_active_deploys_combat_drone(self):
        from combat_helpers import deploy_drone
        gv = _make_deploy_gv(mines_rock=False)
        deploy_drone(gv)
        assert type(gv._active_drone).__name__ == "CombatDrone"
        assert gv.inventory.count_item("combat_drone") == 4

    def test_same_variant_press_is_noop_no_consume(self):
        from combat_helpers import deploy_drone
        gv = _make_deploy_gv(mines_rock=True)
        deploy_drone(gv)  # mining drone deployed
        assert gv.inventory.count_item("mining_drone") == 4
        deploy_drone(gv)  # press R again — no-op
        assert gv.inventory.count_item("mining_drone") == 4
        assert len(gv._drone_list) == 1

    def test_other_variant_press_replaces_active_drone(self):
        # The swap path now REFUNDS the displaced drone instead of
        # destroying it.  Net result of the round trip: -1 of the
        # new variant, 0 of the old variant.
        from combat_helpers import deploy_drone
        gv = _make_deploy_gv(mines_rock=True)
        deploy_drone(gv)
        first = gv._active_drone
        assert gv.inventory.count_item("mining_drone") == 4
        # Switch weapon — basic laser now active
        gv._active_weapon = SimpleNamespace(mines_rock=False)
        deploy_drone(gv)
        assert type(gv._active_drone).__name__ == "CombatDrone"
        assert gv._active_drone is not first
        # Old mining drone refunded back to 5; new combat drone consumed.
        assert gv.inventory.count_item("mining_drone") == 5
        assert gv.inventory.count_item("combat_drone") == 4
        assert len(gv._drone_list) == 1   # old one removed

    def test_no_inventory_leaves_drone_unchanged(self):
        from combat_helpers import deploy_drone
        gv = _make_deploy_gv(mines_rock=True,
                              items={"mining_drone": 0, "combat_drone": 5})
        deploy_drone(gv)
        assert gv._active_drone is None
        assert gv._flash_msg != ""    # got a flash message

    def test_blocked_by_escape_menu(self):
        from combat_helpers import deploy_drone
        gv = _make_deploy_gv(mines_rock=False)
        gv._escape_menu.open = True
        deploy_drone(gv)
        assert gv._active_drone is None

    def test_blocked_by_player_dead(self):
        from combat_helpers import deploy_drone
        gv = _make_deploy_gv(mines_rock=False)
        gv._player_dead = True
        deploy_drone(gv)
        assert gv._active_drone is None


# ── Constants registration ────────────────────────────────────────────────

class TestModuleTypeRegistration:
    def test_mining_drone_in_module_types(self):
        from constants import MODULE_TYPES
        m = MODULE_TYPES["mining_drone"]
        assert m["consumable"] is True
        assert m["item_key"] == "mining_drone"
        assert m["craft_cost"] == 200
        assert m["craft_cost_copper"] == 100
        assert m["advanced"] is True

    def test_combat_drone_in_module_types(self):
        from constants import MODULE_TYPES
        m = MODULE_TYPES["combat_drone"]
        assert m["consumable"] is True
        assert m["item_key"] == "combat_drone"
        assert m["craft_cost"] == 200
        assert m["craft_cost_copper"] == 100

    def test_both_drones_zone_gated(self):
        from constants import ZONE_GATED_MODULES
        assert "mining_drone" in ZONE_GATED_MODULES
        assert "combat_drone" in ZONE_GATED_MODULES
