"""Fast unit tests for Planets Phase 5 — base building + power grid +
surface defenses (docs/planets.md section 10).

Covers the spec table, the cached asset loader, the pure power-grid /
budget / placement logic in ``planet_base``, the ``PlanetaryBuilding``
sprite (armor, turret fire), and the surface-zone integration (placement,
turret firing, Arc-Tower spawn suppression, Shield-Generator bubble,
Home-Base respawn, build-menu toggle).  Zone-wide soak/perf is out of scope
per the task (unit + integration only).
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest

import constants as C
import specs
from specs import (
    PLANETARY_BUILDINGS, PLANETARY_BUILD_ORDER, PlanetaryBuildingSpec,
    HOME_BASE, WIND_FARM, SOLAR_FARM, FISSION_REACTOR,
    GROUND_TURRET_1, GROUND_TURRET_2, ARC_TOWER, SHIELD_GENERATOR, POWER_LINE,
)
import planet_base as pb
from sprites.planet_building import (
    load_planet_building_assets, PlanetaryBuilding, create_planet_building,
)
from zones.zone_planetary_surface import PlanetarySurfaceZone


# ── Test doubles ──────────────────────────────────────────────────────────────

class FakeInv:
    def __init__(self, iron=0, copper=0, silicon=0):
        self.amounts = {"iron": iron, "copper": copper, "silicon": silicon}

    def count_item(self, k):
        return self.amounts.get(k, 0)

    def add_item(self, k, n):
        self.amounts[k] = self.amounts.get(k, 0) + n

    def remove_item(self, k, n):
        have = self.amounts.get(k, 0)
        take = min(have, n)
        self.amounts[k] = have - take
        return take


class FakeEnemy:
    """Lightweight stand-in for SurfaceEnemy in defense tests."""
    def __init__(self, x, y, hp=100, dmg=10):
        self.center_x = x
        self.center_y = y
        self.hp = hp
        self.state = "alive"
        self.radius = C.SURFACE_ENEMY_RADIUS
        self.spec = SimpleNamespace(damage=dmg, tier="A")

    def take_damage(self, amount):
        self.hp -= max(1, int(amount))
        if self.hp <= 0:
            self.state = "dying"


def _spec_building(spec, x, y):
    return create_planet_building(spec, load_planet_building_assets(), x, y)


def _zone_with_assets():
    z = PlanetarySurfaceZone()
    z._building_assets = load_planet_building_assets()
    return z


# ── Specs + constants ─────────────────────────────────────────────────────────

class TestSpecs:
    def test_nine_buildings_in_order(self):
        assert len(PLANETARY_BUILD_ORDER) == 9
        assert list(PLANETARY_BUILDINGS) == [
            "home_base", "power_line", "wind_farm", "solar_farm",
            "fission_reactor", "ground_turret_1", "ground_turret_2",
            "arc_tower", "shield_generator"]

    def test_home_base_hp_uses_appendix_a_fix(self):
        # docs Appendix A #3: literal 10 is a likely missing zero; we use 1000.
        assert HOME_BASE.hp == 1000

    def test_budget_bonuses(self):
        assert HOME_BASE.budget_bonus == 5
        assert WIND_FARM.budget_bonus == 5
        assert SOLAR_FARM.budget_bonus == 10
        assert FISSION_REACTOR.budget_bonus == 15
        assert GROUND_TURRET_1.budget_bonus == 0

    def test_power_roles(self):
        assert HOME_BASE.power_role == "provides"
        assert FISSION_REACTOR.power_role == "provides"
        assert POWER_LINE.power_role == "conduit"
        assert GROUND_TURRET_1.power_role == "needs"
        assert SHIELD_GENERATOR.power_role == "needs"

    def test_turret_barrels(self):
        assert GROUND_TURRET_1.barrels == 1
        assert GROUND_TURRET_2.barrels == 2

    def test_max_counts(self):
        assert HOME_BASE.max_count == 1
        assert SHIELD_GENERATOR.max_count == 1
        assert ARC_TOWER.max_count == 2
        assert GROUND_TURRET_1.max_count is None


# ── Asset loader ──────────────────────────────────────────────────────────────

class TestAssets:
    def test_loads_textured_buildings_plus_extras(self):
        a = load_planet_building_assets()
        for key, spec in PLANETARY_BUILDINGS.items():
            if spec.png:
                assert key in a
        assert "_turret_laser" in a
        assert "_power_line" in a

    def test_loader_is_cached(self):
        assert load_planet_building_assets() is load_planet_building_assets()


# ── Power grid (pure) ─────────────────────────────────────────────────────────

class TestPowerGrid:
    def test_provider_always_powered(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        pb.compute_power([home])
        assert home.powered is True

    def test_consumer_near_provider_is_powered(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        turret = _spec_building(GROUND_TURRET_1, 1000 + 100, 1000)
        pb.compute_power([home, turret])
        assert turret.powered is True

    def test_consumer_far_from_provider_is_unpowered(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        turret = _spec_building(GROUND_TURRET_1, 1000 + 400, 1000)  # > link
        pb.compute_power([home, turret])
        assert turret.powered is False

    def test_power_line_chain_extends_reach(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        line = _spec_building(POWER_LINE, 1000 + 200, 1000)
        turret = _spec_building(GROUND_TURRET_1, 1000 + 400, 1000)
        pb.compute_power([home, line, turret])
        assert line.powered and turret.powered

    def test_isolated_consumer_no_provider(self):
        turret = _spec_building(GROUND_TURRET_1, 1000, 1000)
        pb.compute_power([turret])
        assert turret.powered is False


# ── Budget + menu availability (pure) ─────────────────────────────────────────

class TestBudget:
    def test_budget_and_slots(self):
        home = _spec_building(HOME_BASE, 0, 0)
        wind = _spec_building(WIND_FARM, 50, 0)
        turret = _spec_building(GROUND_TURRET_1, 100, 0)
        bs = [home, wind, turret]
        assert pb.build_budget(bs) == 10        # 5 home + 5 wind
        assert pb.slots_used(bs) == 2           # wind 1 + turret 1
        assert pb.budget_remaining(bs) == 8

    def test_home_first_rule(self):
        ok, reason = pb.menu_availability(
            GROUND_TURRET_1, [], 999, 999, 999)
        assert not ok and "Home Base" in reason

    def test_home_only_once(self):
        home = _spec_building(HOME_BASE, 0, 0)
        ok, reason = pb.menu_availability(HOME_BASE, [home], 999, 999, 999)
        assert not ok

    def test_max_count_block(self):
        home = _spec_building(HOME_BASE, 0, 0)
        sg = _spec_building(SHIELD_GENERATOR, 50, 0)
        ok, _ = pb.menu_availability(SHIELD_GENERATOR, [home, sg], 999, 999, 999)
        assert not ok

    def test_budget_block(self):
        # Home alone gives budget 5; a 2-slot fission needs headroom — ok.
        home = _spec_building(HOME_BASE, 0, 0)
        # Spend the whole budget with five 1-slot turrets, then the sixth
        # has no budget.
        bs = [home]
        for i in range(5):
            bs.append(_spec_building(GROUND_TURRET_1, 10 * i, 0))
        ok, reason = pb.menu_availability(
            GROUND_TURRET_1, bs, 999, 999, 999)
        assert not ok and "budget" in reason.lower()

    def test_affordability_block(self):
        home = _spec_building(HOME_BASE, 0, 0)
        ok, reason = pb.menu_availability(WIND_FARM, [home], 0, 0, 0)
        assert not ok and "resource" in reason.lower()


# ── Placement (spatial) ───────────────────────────────────────────────────────

class TestPlacement:
    def test_within_bounds_and_home_radius(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        ok, _ = pb.can_place_at(
            GROUND_TURRET_1, 1100, 1000, [home],
            4000, 4000, 999, 999, 999)
        assert ok

    def test_too_far_from_home(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        ok, reason = pb.can_place_at(
            GROUND_TURRET_1, 1000 + C.PB_HOME_RADIUS + 50, 1000, [home],
            4000, 4000, 999, 999, 999)
        assert not ok and "Home Base" in reason

    def test_collision_spacing(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        wind = _spec_building(WIND_FARM, 1100, 1000)
        ok, reason = pb.can_place_at(
            SOLAR_FARM, 1105, 1000, [home, wind],
            4000, 4000, 999, 999, 999)
        assert not ok and "close" in reason.lower()

    def test_power_line_ignores_collision(self):
        home = _spec_building(HOME_BASE, 1000, 1000)
        ok, _ = pb.can_place_at(
            POWER_LINE, 1005, 1000, [home],
            4000, 4000, 999, 999, 999)
        assert ok

    def test_arc_blocks_only_when_powered(self):
        arc = _spec_building(ARC_TOWER, 1000, 1000)
        arc.powered = False
        assert pb.arc_blocks(1050, 1000, [arc]) is False
        arc.powered = True
        assert pb.arc_blocks(1050, 1000, [arc]) is True
        assert pb.arc_blocks(1000 + ARC_TOWER.block_radius + 10, 1000,
                             [arc]) is False


# ── PlanetaryBuilding sprite ──────────────────────────────────────────────────

class TestBuildingSprite:
    def test_armor_reduces_damage(self):
        b = _spec_building(FISSION_REACTOR, 0, 0)   # armor 2
        b.take_damage(10)
        assert b.hp == FISSION_REACTOR.hp - 8

    def test_armor_min_one(self):
        b = _spec_building(FISSION_REACTOR, 0, 0)
        b.take_damage(1)
        assert b.hp == FISSION_REACTOR.hp - 1

    def test_turret_fires_when_powered(self):
        t = _spec_building(GROUND_TURRET_1, 1000, 1000)
        t.powered = True
        out = arcade.SpriteList()
        e = FakeEnemy(1050, 1000)
        t.update_turret(1 / 60, [e], out, load_planet_building_assets()["_turret_laser"])
        assert len(out) == 1
        assert t._fire_cd > 0.0

    def test_turret_silent_when_unpowered(self):
        t = _spec_building(GROUND_TURRET_1, 1000, 1000)
        t.powered = False
        out = arcade.SpriteList()
        t.update_turret(1 / 60, [FakeEnemy(1050, 1000)], out,
                        load_planet_building_assets()["_turret_laser"])
        assert len(out) == 0

    def test_turret_out_of_range_holds_fire(self):
        t = _spec_building(GROUND_TURRET_1, 1000, 1000)
        t.powered = True
        out = arcade.SpriteList()
        far = FakeEnemy(1000 + GROUND_TURRET_1.detect + 50, 1000)
        t.update_turret(1 / 60, [far], out,
                        load_planet_building_assets()["_turret_laser"])
        assert len(out) == 0

    def test_double_barrel_fires_two(self):
        t = _spec_building(GROUND_TURRET_2, 1000, 1000)
        t.powered = True
        out = arcade.SpriteList()
        t.update_turret(1 / 60, [FakeEnemy(1050, 1000)], out,
                        load_planet_building_assets()["_turret_laser"])
        assert len(out) == 2


# ── Zone integration ──────────────────────────────────────────────────────────

class TestZonePlacement:
    def test_place_home_base_deducts_and_powers(self, stub_gv):
        z = _zone_with_assets()
        stub_gv.inventory = FakeInv(iron=200, copper=200, silicon=200)
        z._placing = "home_base"
        z._place_building(stub_gv, 1000, 1000)
        assert len(z._buildings) == 1
        assert z._buildings[0].spec.kind == "home"
        assert z._buildings[0].powered is True
        assert stub_gv.inventory.count_item("iron") == 100  # 200 - 100

    def test_cannot_place_without_home(self, stub_gv):
        z = _zone_with_assets()
        stub_gv.inventory = FakeInv(iron=999, copper=999, silicon=999)
        z._placing = "ground_turret_1"
        z._place_building(stub_gv, 1000, 1000)
        assert len(z._buildings) == 0
        assert stub_gv.calls["flash"]            # rejection flashed

    def test_insufficient_resources_rejected(self, stub_gv):
        z = _zone_with_assets()
        stub_gv.inventory = FakeInv(iron=0, copper=0, silicon=0)
        z._placing = "home_base"
        z._place_building(stub_gv, 1000, 1000)
        assert len(z._buildings) == 0


class TestZoneDefenses:
    def _base_with_turret(self, stub_gv):
        z = _zone_with_assets()
        stub_gv.inventory = FakeInv(iron=9999, copper=9999, silicon=9999)
        z._buildings.append(_spec_building(HOME_BASE, 1000, 1000))
        z._buildings.append(_spec_building(GROUND_TURRET_1, 1100, 1000))
        pb.compute_power(z._buildings)
        return z

    def test_powered_turret_fires_on_enemy(self, stub_gv):
        z = self._base_with_turret(stub_gv)
        # Far enough that the fresh shot is still in flight after one tick.
        e = FakeEnemy(1100, 1180)
        z._enemies = [e]
        z._update_buildings(stub_gv, 1 / 60, 1000.0, 1000.0)
        assert len(z._building_projectiles) >= 1

    def test_powered_turret_damages_close_enemy(self, stub_gv):
        z = self._base_with_turret(stub_gv)
        e = FakeEnemy(1130, 1000)              # close — shot connects same tick
        z._enemies = [e]
        z._update_buildings(stub_gv, 1 / 60, 1000.0, 1000.0)
        assert e.hp < 100                       # turret -> projectile -> enemy

    def test_unpowered_turret_does_not_fire(self, stub_gv):
        z = _zone_with_assets()
        z._buildings.append(_spec_building(HOME_BASE, 1000, 1000))
        # Turret far from home -> unpowered.
        z._buildings.append(_spec_building(GROUND_TURRET_1, 1000, 1600))
        pb.compute_power(z._buildings)
        z._enemies = [FakeEnemy(1000, 1650)]
        z._update_buildings(stub_gv, 1 / 60, 1000.0, 1000.0)
        assert len(z._building_projectiles) == 0

    def test_arc_tower_wiring_suppresses_spawn(self, stub_gv, monkeypatch):
        z = _zone_with_assets()
        z._enemy_assets = {}      # not used — arc_blocks short-circuits
        # Force the whole field to read as arc-suppressed.
        monkeypatch.setattr(
            "planet_base.arc_blocks", lambda x, y, bs: True)
        before = len(z._enemies)
        z._spawn_enemy("A", 0.0, 0.0)
        assert len(z._enemies) == before     # nothing spawned

    def test_shield_bubble_pushes_enemy_out(self, stub_gv):
        z = _zone_with_assets()
        sg = _spec_building(SHIELD_GENERATOR, 1000, 1000)
        sg.powered = True
        z._buildings.append(sg)
        e = FakeEnemy(1100, 1000)            # well inside the 500px bubble
        z._enemies = [e]
        z._update_buildings(stub_gv, 1 / 60, 1000.0, 1000.0)
        import math
        d = math.hypot(e.center_x - 1000, e.center_y - 1000)
        assert d >= SHIELD_GENERATOR.bubble_radius - 1.0

    def test_shield_absorbs_enemy_projectile(self, stub_gv):
        z = _zone_with_assets()
        sg = _spec_building(SHIELD_GENERATOR, 1000, 1000)
        sg.powered = True
        z._buildings.append(sg)
        proj = SimpleNamespace(center_x=1050.0, center_y=1000.0, damage=30)
        proj.remove_from_sprite_lists = lambda: z._enemy_projectiles.remove(proj) \
            if proj in z._enemy_projectiles else None
        # Use a plain list so the SimpleNamespace projectile is iterable.
        z._enemy_projectiles = [proj]
        before = sg.shield_hp
        z._update_buildings(stub_gv, 1 / 60, 1000.0, 1000.0)
        assert sg.shield_hp == before - 30

    def test_enemy_contact_damages_building(self, stub_gv):
        z = _zone_with_assets()
        home = _spec_building(HOME_BASE, 1000, 1000)
        z._buildings.append(home)
        z._enemies = [FakeEnemy(1000, 1000, dmg=20)]   # overlapping
        hp0 = home.hp
        z._update_buildings(stub_gv, 1 / 60, 1000.0, 1000.0)
        assert home.hp < hp0


class TestZoneRespawnAndMenu:
    def test_respawn_at_home_base(self, stub_gv):
        z = _zone_with_assets()
        home = _spec_building(HOME_BASE, 800, 900)
        z._buildings.append(home)
        z._respawn_player(stub_gv)
        assert abs(stub_gv.player.center_x - 800) < 1.0
        assert stub_gv.player.center_y > 900     # placed just above the base

    def test_respawn_midfield_without_home(self, stub_gv):
        z = _zone_with_assets()
        z._respawn_player(stub_gv)
        assert stub_gv.player.center_x == z.world_width / 2
        assert stub_gv.player.center_y == z.world_height / 2

    def test_build_menu_toggle(self, stub_gv):
        z = _zone_with_assets()
        assert z._build_menu.open is False
        z.toggle_build_menu(stub_gv)
        assert z._build_menu.open is True
        z.toggle_build_menu(stub_gv)
        assert z._build_menu.open is False

    def test_toggle_cancels_active_placement(self, stub_gv):
        z = _zone_with_assets()
        z._placing = "home_base"
        z.toggle_build_menu(stub_gv)
        assert z._placing is None

    def test_menu_click_enters_placement(self, stub_gv):
        z = _zone_with_assets()
        stub_gv.inventory = FakeInv(iron=999, copper=999, silicon=999)
        z._build_menu.open = True
        # Click the first row (Home Base) — compute its centre via the menu.
        rx, ry, rw, rh = z._build_menu._row_rect(0)
        consumed = z.handle_surface_mouse_press(stub_gv, rx + 5, ry + rh / 2)
        assert consumed is True
        assert z._placing == "home_base"

    def test_click_while_placing_places(self, stub_gv):
        z = _zone_with_assets()
        stub_gv.inventory = FakeInv(iron=999, copper=999, silicon=999)
        z._placing = "home_base"
        consumed = z.handle_surface_mouse_press(stub_gv, 1500, 1500)
        assert consumed is True
        assert len(z._buildings) == 1
