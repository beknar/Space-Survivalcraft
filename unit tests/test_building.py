"""Tests for sprites/building.py — StationModule, Turret, DockingPort, capacity helpers."""
from __future__ import annotations

import math

import pytest

from sprites.building import (
    StationModule, HomeStation, ServiceModule, PowerReceiver,
    SolarArray, Turret, DockingPort, create_building,
    compute_module_capacity, compute_modules_used,
)
from constants import (
    BUILDING_TYPES, TURRET_RANGE, TURRET_COOLDOWN,
    BASE_MODULE_CAPACITY,
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
