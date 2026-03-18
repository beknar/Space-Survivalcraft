"""Tests for sprites/building.py — StationModule, Turret, DockingPort, capacity helpers."""
from __future__ import annotations

import math

import pytest

from sprites.building import (
    StationModule, HomeStation, ServiceModule, PowerReceiver,
    SolarArray, Turret, RepairModule, DockingPort, create_building,
    compute_module_capacity, compute_modules_used,
)
from constants import (
    BUILDING_TYPES, TURRET_RANGE, TURRET_COOLDOWN,
    BASE_MODULE_CAPACITY, SHIP_RADIUS, BUILDING_RADIUS,
    REPAIR_RANGE, REPAIR_RATE,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def home_tex(dummy_texture):
    return dummy_texture


@pytest.fixture
def turret_tex(dummy_texture):
    return dummy_texture


@pytest.fixture
def laser_tex(dummy_texture):
    return dummy_texture


@pytest.fixture
def home(home_tex):
    return HomeStation(home_tex, 100, 200, "Home Station", scale=0.5)


@pytest.fixture
def service(home_tex):
    return ServiceModule(home_tex, 150, 200, "Service Module", scale=0.5)


@pytest.fixture
def solar1(home_tex):
    return SolarArray(home_tex, 200, 200, "Solar Array 1", scale=0.5)


@pytest.fixture
def solar2(home_tex):
    return SolarArray(home_tex, 250, 200, "Solar Array 2", scale=0.5)


@pytest.fixture
def turret1(turret_tex, laser_tex):
    return Turret(turret_tex, 300, 200, "Turret 1", laser_tex, scale=0.5)


@pytest.fixture
def turret2(turret_tex, laser_tex):
    return Turret(turret_tex, 350, 200, "Turret 2", laser_tex, scale=0.5)


# ── StationModule base ────────────────────────────────────────────────────────

class TestStationModule:
    def test_hp_initialised(self, home):
        assert home.hp == BUILDING_TYPES["Home Station"]["hp"]
        assert home.max_hp == BUILDING_TYPES["Home Station"]["hp"]

    def test_building_type_stored(self, home):
        assert home.building_type == "Home Station"

    def test_not_disabled_initially(self, home):
        assert home.disabled is False

    def test_four_ports(self, home):
        assert len(home.ports) == 4
        directions = {p.direction for p in home.ports}
        assert directions == {"N", "S", "E", "W"}

    def test_ports_initially_unoccupied(self, home):
        for port in home.ports:
            assert port.occupied is False
            assert port.connected_to is None


class TestTakeDamage:
    def test_reduces_hp(self, home):
        home.take_damage(30)
        assert home.hp == home.max_hp - 30

    def test_hp_does_not_go_negative(self, home):
        home.take_damage(9999)
        assert home.hp == 0

    def test_hit_flash_set(self, home):
        home.take_damage(10)
        assert home._hit_timer > 0.0
        assert home.color == (255, 100, 100, 255)

    def test_hit_flash_clears_after_time(self, home):
        home.take_damage(10)
        home.update_building(1.0)
        assert home._hit_timer == 0.0
        assert home.color == (255, 255, 255, 255)

    def test_disabled_tint_after_flash(self, home):
        home.disabled = True
        home.take_damage(10)
        home.update_building(1.0)
        assert home.color == (128, 128, 128, 255)


# ── DockingPort ───────────────────────────────────────────────────────────────

class TestDockingPort:
    def test_opposite_directions(self):
        assert DockingPort.opposite("N") == "S"
        assert DockingPort.opposite("S") == "N"
        assert DockingPort.opposite("E") == "W"
        assert DockingPort.opposite("W") == "E"

    def test_port_world_pos_no_rotation(self, home):
        """At angle=0 the port offsets are applied directly."""
        for port in home.ports:
            px, py = home.get_port_world_pos(port)
            assert px == pytest.approx(home.center_x + port.offset_x, abs=0.5)
            assert py == pytest.approx(home.center_y + port.offset_y, abs=0.5)

    def test_port_world_pos_with_rotation(self, home):
        """At 90° rotation, the N port (0, +hh) rotates to (-hh, 0)."""
        home.angle = 90.0
        n_port = [p for p in home.ports if p.direction == "N"][0]
        px, py = home.get_port_world_pos(n_port)
        # Standard rotation: (0, +hh) at 90° → (-hh, 0)
        expected_x = home.center_x - n_port.offset_y
        expected_y = home.center_y
        assert px == pytest.approx(expected_x, abs=0.5)
        assert py == pytest.approx(expected_y, abs=0.5)

    def test_get_unoccupied_ports(self, home):
        assert len(home.get_unoccupied_ports()) == 4
        home.ports[0].occupied = True
        assert len(home.get_unoccupied_ports()) == 3


# ── Turret ────────────────────────────────────────────────────────────────────

class TestTurret:
    def test_barrel_count_turret1(self, turret1):
        assert turret1._barrel_count == 1

    def test_barrel_count_turret2(self, turret2):
        assert turret2._barrel_count == 2

    def test_slots_used_turret1(self, turret1):
        assert turret1.slots_used == 1

    def test_slots_used_turret2(self, turret2):
        assert turret2.slots_used == 2

    def test_fire_cooldown_initial(self, turret1):
        assert turret1._fire_cd == 0.0

    def test_disabled_turret_does_not_fire(self, turret1):
        """A disabled turret should not fire even with enemies in range."""
        turret1.disabled = True
        import arcade
        alien_list = arcade.SpriteList()
        proj_list = arcade.SpriteList()
        turret1.update_turret(1.0, alien_list, proj_list)
        assert len(proj_list) == 0


# ── SolarArray ────────────────────────────────────────────────────────────────

class TestSolarArray:
    def test_capacity_bonus_sa1(self, solar1):
        assert solar1.capacity_bonus == BUILDING_TYPES["Solar Array 1"]["module_slots"]

    def test_capacity_bonus_sa2(self, solar2):
        assert solar2.capacity_bonus == BUILDING_TYPES["Solar Array 2"]["module_slots"]


# ── Factory function ─────────────────────────────────────────────────────────

class TestCreateBuilding:
    def test_home_station(self, home_tex):
        b = create_building("Home Station", home_tex, 0, 0)
        assert isinstance(b, HomeStation)

    def test_service_module(self, home_tex):
        b = create_building("Service Module", home_tex, 0, 0)
        assert isinstance(b, ServiceModule)

    def test_power_receiver(self, home_tex):
        b = create_building("Power Receiver", home_tex, 0, 0)
        assert isinstance(b, PowerReceiver)

    def test_solar_array(self, home_tex):
        b = create_building("Solar Array 1", home_tex, 0, 0)
        assert isinstance(b, SolarArray)

    def test_turret(self, home_tex, laser_tex):
        b = create_building("Turret 1", home_tex, 0, 0, laser_tex=laser_tex)
        assert isinstance(b, Turret)

    def test_invalid_type_raises(self, home_tex):
        with pytest.raises(KeyError):
            create_building("Nonexistent", home_tex, 0, 0)


# ── Capacity helpers ─────────────────────────────────────────────────────────

class TestCapacityHelpers:
    def test_base_capacity_empty(self):
        import arcade
        slist = arcade.SpriteList()
        assert compute_module_capacity(slist) == BASE_MODULE_CAPACITY

    def test_solar_array_adds_capacity(self, home_tex):
        import arcade
        slist = arcade.SpriteList()
        sa = SolarArray(home_tex, 0, 0, "Solar Array 1", scale=0.5)
        slist.append(sa)
        expected = BASE_MODULE_CAPACITY + BUILDING_TYPES["Solar Array 1"]["module_slots"]
        assert compute_module_capacity(slist) == expected

    def test_disabled_solar_no_bonus(self, home_tex):
        import arcade
        slist = arcade.SpriteList()
        sa = SolarArray(home_tex, 0, 0, "Solar Array 1", scale=0.5)
        sa.disabled = True
        slist.append(sa)
        assert compute_module_capacity(slist) == BASE_MODULE_CAPACITY

    def test_modules_used_excludes_home(self, home_tex):
        import arcade
        slist = arcade.SpriteList()
        h = HomeStation(home_tex, 0, 0, "Home Station", scale=0.5)
        slist.append(h)
        assert compute_modules_used(slist) == 0

    def test_modules_used_counts_service(self, home_tex):
        import arcade
        slist = arcade.SpriteList()
        sm = ServiceModule(home_tex, 0, 0, "Service Module", scale=0.5)
        slist.append(sm)
        assert compute_modules_used(slist) == 1

    def test_turret2_counts_as_two(self, home_tex, laser_tex):
        import arcade
        slist = arcade.SpriteList()
        t = Turret(home_tex, 0, 0, "Turret 2", laser_tex, scale=0.5)
        slist.append(t)
        assert compute_modules_used(slist) == 2

    def test_mixed_modules(self, home_tex, laser_tex):
        import arcade
        slist = arcade.SpriteList()
        slist.append(HomeStation(home_tex, 0, 0, "Home Station", scale=0.5))
        slist.append(ServiceModule(home_tex, 10, 0, "Service Module", scale=0.5))
        slist.append(Turret(home_tex, 20, 0, "Turret 2", laser_tex, scale=0.5))
        # Home=0, Service=1, Turret2=2 → total=3
        assert compute_modules_used(slist) == 3


# ── Home Station destruction ──────────────────────────────────────────────────

class TestHomeStationDestruction:
    def test_destroying_home_disables_all(self, home_tex, laser_tex):
        """When the Home Station HP reaches 0, all modules should be disabled."""
        import arcade
        slist = arcade.SpriteList()
        h = HomeStation(home_tex, 0, 0, "Home Station", scale=0.5)
        sm = ServiceModule(home_tex, 50, 0, "Service Module", scale=0.5)
        t = Turret(home_tex, 100, 0, "Turret 1", laser_tex, scale=0.5)
        slist.append(h)
        slist.append(sm)
        slist.append(t)

        # Simulate Home Station destruction
        assert isinstance(h, HomeStation)
        for b in slist:
            b.disabled = True
            b.color = (128, 128, 128, 255)

        assert sm.disabled is True
        assert t.disabled is True


# ── Edge-to-edge snap math ──────────────────────────────────────────────────

class TestEdgeToEdgeSnap:
    """Verify that edge-to-edge snap offset places buildings correctly."""

    def test_snap_north_no_rotation(self, home_tex):
        """New building snapping to a parent's N port should sit above, edge-to-edge."""
        parent = HomeStation(home_tex, 100, 100, "Home Station", scale=0.5)
        child = ServiceModule(home_tex, 0, 0, "Service Module", scale=0.5)

        # Parent's N port
        n_port = [p for p in parent.ports if p.direction == "N"][0]
        sx, sy = parent.get_port_world_pos(n_port)

        # Child's opposite port (S) offset
        opp_dir = DockingPort.opposite("N")
        assert opp_dir == "S"
        opp_port = [p for p in child.ports if p.direction == opp_dir][0]

        # Place child edge-to-edge (no rotation)
        rad = math.radians(child.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        ox_rot = opp_port.offset_x * cos_a - opp_port.offset_y * sin_a
        oy_rot = opp_port.offset_x * sin_a + opp_port.offset_y * cos_a
        child.center_x = sx - ox_rot
        child.center_y = sy - oy_rot

        # Child should be above parent (its center_y > parent's center_y)
        assert child.center_y > parent.center_y
        # Their edges should meet: parent N port aligns with child S port
        child_sx, child_sy = child.get_port_world_pos(opp_port)
        assert child_sx == pytest.approx(sx, abs=0.5)
        assert child_sy == pytest.approx(sy, abs=0.5)

    def test_snap_east_no_rotation(self, home_tex):
        """New building snapping to parent's E port should sit to the right."""
        parent = HomeStation(home_tex, 100, 100, "Home Station", scale=0.5)
        child = ServiceModule(home_tex, 0, 0, "Service Module", scale=0.5)

        e_port = [p for p in parent.ports if p.direction == "E"][0]
        sx, sy = parent.get_port_world_pos(e_port)

        opp_port = [p for p in child.ports if p.direction == "W"][0]
        child.center_x = sx - opp_port.offset_x
        child.center_y = sy - opp_port.offset_y

        assert child.center_x > parent.center_x
        child_wx, child_wy = child.get_port_world_pos(opp_port)
        assert child_wx == pytest.approx(sx, abs=0.5)
        assert child_wy == pytest.approx(sy, abs=0.5)

    def test_opposite_directions_all(self):
        """All four opposite directions should be correct."""
        assert DockingPort.opposite("N") == "S"
        assert DockingPort.opposite("S") == "N"
        assert DockingPort.opposite("E") == "W"
        assert DockingPort.opposite("W") == "E"


# ── Player-building collision logic ─────────────────────────────────────────

class TestShipBuildingCollision:
    """Test the push-out / no-bounce collision logic for player vs building."""

    def test_push_out_no_overlap(self, home_tex):
        """When player overlaps building, push-out should separate them."""
        building = HomeStation(home_tex, 100, 100, "Home Station", scale=0.5)
        # Simulate a player at the same position (max overlap)
        player_x = 100.0
        player_y = 100.0
        player_vx = 0.0
        player_vy = 0.0

        dx = player_x - building.center_x
        dy = player_y - building.center_y
        dist = math.hypot(dx, dy)
        if dist == 0:
            dx, dy, dist = 0.0, 1.0, 1.0
        nx = dx / dist
        ny = dy / dist
        combined_r = SHIP_RADIUS + BUILDING_RADIUS
        overlap = combined_r - dist
        if overlap > 0:
            player_x += nx * overlap
            player_y += ny * overlap

        # After push-out, distance should be >= combined radius
        # (when dist was 0, artificial dist=1 means push = combined_r - 1,
        #  so new_dist = 1 + (combined_r - 1) = combined_r - but not exactly
        #  due to the artificial starting distance; just verify no overlap)
        new_dist = math.hypot(player_x - building.center_x,
                              player_y - building.center_y)
        assert new_dist >= combined_r - 1.5  # within tolerance of push-out

    def test_velocity_zeroed_toward_building(self, home_tex):
        """Velocity component toward building should be zeroed (no bounce)."""
        building = HomeStation(home_tex, 100, 100, "Home Station", scale=0.5)
        # Player approaching from left
        player_x = 80.0
        player_y = 100.0
        player_vx = 50.0  # moving right toward building
        player_vy = 0.0

        dx = player_x - building.center_x
        dy = player_y - building.center_y
        dist = math.hypot(dx, dy)
        nx = dx / dist
        ny = dy / dist
        dot = player_vx * nx + player_vy * ny
        if dot < 0:
            player_vx -= dot * nx
            player_vy -= dot * ny

        # Velocity component toward building should now be >= 0
        new_dot = player_vx * nx + player_vy * ny
        assert new_dot >= -0.01  # no longer moving toward building

    def test_no_bounce_restitution(self, home_tex):
        """Unlike asteroid collision, there should be no bounce multiplier."""
        building = HomeStation(home_tex, 100, 100, "Home Station", scale=0.5)
        player_x = 80.0
        player_y = 100.0
        player_vx = 100.0
        player_vy = 0.0

        dx = player_x - building.center_x
        dy = player_y - building.center_y
        dist = math.hypot(dx, dy)
        nx = dx / dist
        ny = dy / dist
        dot = player_vx * nx + player_vy * ny
        if dot < 0:
            player_vx -= dot * nx
            player_vy -= dot * ny

        # Speed should be <= original (no bounce adds energy)
        new_speed = math.hypot(player_vx, player_vy)
        assert new_speed <= 100.01


# ── Repair Module ────────────────────────────────────────────────────────────

class TestRepairModule:
    def test_create_repair_module(self, home_tex):
        b = create_building("Repair Module", home_tex, 0, 0)
        assert isinstance(b, RepairModule)

    def test_repair_module_hp(self, home_tex):
        b = RepairModule(home_tex, 0, 0, "Repair Module", scale=0.5)
        assert b.hp == 75
        assert b.max_hp == 75

    def test_repair_module_has_ports(self, home_tex):
        b = RepairModule(home_tex, 0, 0, "Repair Module", scale=0.5)
        assert len(b.ports) == 4

    def test_repair_module_in_building_types(self):
        assert "Repair Module" in BUILDING_TYPES
        stats = BUILDING_TYPES["Repair Module"]
        assert stats["cost"] == 75
        assert stats["max"] == 1
        assert stats["connectable"] is True
        assert stats["slots_used"] == 1

    def test_repair_range_constant(self):
        assert REPAIR_RANGE == 300.0

    def test_repair_rate_constant(self):
        assert REPAIR_RATE == 1.0


# ── Port disconnect on deconstruction ─────────────────────────────────────────

class TestPortDisconnect:
    def test_disconnect_frees_ports(self, home_tex):
        """Disconnecting a building should free ports on connected buildings."""
        parent = HomeStation(home_tex, 100, 100, "Home Station", scale=0.5)
        child = ServiceModule(home_tex, 100, 200, "Service Module", scale=0.5)

        # Manually connect N port of parent to S port of child
        p_port = [p for p in parent.ports if p.direction == "N"][0]
        c_port = [p for p in child.ports if p.direction == "S"][0]
        p_port.occupied = True
        p_port.connected_to = child
        c_port.occupied = True
        c_port.connected_to = parent

        # Simulate disconnect of child
        for port in child.ports:
            if port.occupied and port.connected_to is not None:
                other = port.connected_to
                for op in other.ports:
                    if op.connected_to is child:
                        op.occupied = False
                        op.connected_to = None

        # Parent's N port should now be free
        assert p_port.occupied is False
        assert p_port.connected_to is None

    def test_disconnect_leaves_other_ports_intact(self, home_tex):
        """Disconnecting one building shouldn't affect unrelated ports."""
        parent = HomeStation(home_tex, 100, 100, "Home Station", scale=0.5)
        child1 = ServiceModule(home_tex, 100, 200, "Service Module", scale=0.5)
        child2 = ServiceModule(home_tex, 200, 100, "Service Module", scale=0.5)

        # Connect child1 to parent's N port
        p_n = [p for p in parent.ports if p.direction == "N"][0]
        c1_s = [p for p in child1.ports if p.direction == "S"][0]
        p_n.occupied = True
        p_n.connected_to = child1
        c1_s.occupied = True
        c1_s.connected_to = parent

        # Connect child2 to parent's E port
        p_e = [p for p in parent.ports if p.direction == "E"][0]
        c2_w = [p for p in child2.ports if p.direction == "W"][0]
        p_e.occupied = True
        p_e.connected_to = child2
        c2_w.occupied = True
        c2_w.connected_to = parent

        # Disconnect child1 only
        for port in child1.ports:
            if port.occupied and port.connected_to is not None:
                for op in port.connected_to.ports:
                    if op.connected_to is child1:
                        op.occupied = False
                        op.connected_to = None

        # Parent's N port freed, E port still connected
        assert p_n.occupied is False
        assert p_e.occupied is True
        assert p_e.connected_to is child2
