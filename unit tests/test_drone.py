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


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


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

    def test_player_far_breaks_off_back_to_follow(self):
        from sprites.drone import CombatDrone, _BaseDrone
        from constants import DRONE_BREAK_OFF_DIST
        d = CombatDrone(0.0, 0.0)
        # Player at exactly the break-off distance + 1 px → drone
        # must be in FOLLOW even with a target right next to it.
        player = SimpleNamespace(
            center_x=DRONE_BREAK_OFF_DIST + 1.0, center_y=0.0)
        target = SimpleNamespace(center_x=50.0, center_y=0.0, hp=100)
        d._mode = _BaseDrone._MODE_ATTACK
        d._update_mode(player, target)
        assert d._mode == _BaseDrone._MODE_FOLLOW

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
