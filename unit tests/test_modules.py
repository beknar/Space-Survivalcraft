"""Tests for ship module system — constants, apply_modules, consolidate."""
from __future__ import annotations

import pytest

from constants import (
    MODULE_TYPES, MODULE_SLOT_COUNT,
    PLAYER_MAX_HP, PLAYER_MAX_SHIELD,
    ROT_SPEED, THRUST, BRAKE, MAX_SPD, DAMPING,
    WORLD_WIDTH, WORLD_HEIGHT,
    MAX_STACK, MAX_STACK_DEFAULT,
    BROADSIDE_COOLDOWN, BROADSIDE_DAMAGE, BROADSIDE_SPEED, BROADSIDE_RANGE,
)
from sprites.player import PlayerShip
from inventory import Inventory
from station_inventory import StationInventory


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ship(dummy_texture):
    """Create a legacy PlayerShip with base stats for module testing."""
    import arcade
    s = PlayerShip.__new__(PlayerShip)
    arcade.Sprite.__init__(s, path_or_texture=dummy_texture, scale=1.5)
    s._use_legacy = True
    s._frames = [[dummy_texture]]
    s._rot_speed = ROT_SPEED
    s._thrust = THRUST
    s._brake = BRAKE
    s._max_spd = MAX_SPD
    s._damping = DAMPING
    s.hp = PLAYER_MAX_HP
    s.max_hp = PLAYER_MAX_HP
    s.shields = PLAYER_MAX_SHIELD
    s.max_shields = PLAYER_MAX_SHIELD
    s._base_max_hp = PLAYER_MAX_HP
    s._base_max_spd = MAX_SPD
    s._base_max_shields = PLAYER_MAX_SHIELD
    s._base_shield_regen = 0.5
    s._shield_regen = 0.5
    s.shield_absorb = 0
    s._shield_acc = 0.0
    s._collision_cd = 0.0
    s.guns = 1
    s.center_x = WORLD_WIDTH / 2
    s.center_y = WORLD_HEIGHT / 2
    s.world_width = WORLD_WIDTH
    s.world_height = WORLD_HEIGHT
    s.vel_x = 0.0
    s.vel_y = 0.0
    s.heading = 0.0
    s._intensity = 0.0
    s._anim_timer = 0.0
    s._anim_col = 0
    return s


@pytest.fixture
def inv():
    return Inventory(iron_icon=None)


@pytest.fixture
def station_inv():
    return StationInventory(iron_icon=None)


# ── MODULE_TYPES constant tests ──────────────────────────────────────────

class TestModuleTypesConstants:
    def test_six_module_types(self):
        assert len(MODULE_TYPES) == 6

    def test_all_have_required_keys(self):
        for key, info in MODULE_TYPES.items():
            assert "label" in info
            assert "effect" in info
            assert "value" in info
            assert "craft_cost" in info
            assert "icon" in info

    def test_craft_costs_positive(self):
        for key, info in MODULE_TYPES.items():
            assert info["craft_cost"] > 0

    def test_slot_count_is_four(self):
        assert MODULE_SLOT_COUNT == 4

    def test_broadside_constants(self):
        assert BROADSIDE_COOLDOWN > 0
        assert BROADSIDE_DAMAGE > 0
        assert BROADSIDE_SPEED > 0
        assert BROADSIDE_RANGE > 0


# ── apply_modules tests ──────────────────────────────────────────────────

class TestApplyModules:
    def test_no_modules_keeps_base_stats(self, ship):
        ship.apply_modules([None, None, None, None])
        assert ship.max_hp == PLAYER_MAX_HP
        assert ship._max_spd == MAX_SPD
        assert ship.max_shields == PLAYER_MAX_SHIELD
        assert ship._shield_regen == 0.5
        assert ship.shield_absorb == 0

    def test_armor_plate_adds_hp(self, ship):
        ship.apply_modules(["armor_plate", None, None, None])
        assert ship.max_hp == PLAYER_MAX_HP + 20

    def test_engine_booster_adds_speed(self, ship):
        ship.apply_modules([None, "engine_booster", None, None])
        assert ship._max_spd == MAX_SPD + 50

    def test_shield_booster_adds_shields(self, ship):
        ship.apply_modules([None, None, "shield_booster", None])
        assert ship.max_shields == PLAYER_MAX_SHIELD + 20

    def test_shield_enhancer_adds_regen(self, ship):
        ship.apply_modules(["shield_enhancer", None, None, None])
        assert ship._shield_regen == 0.5 + 3.0

    def test_damage_absorber_sets_absorb(self, ship):
        ship.apply_modules(["damage_absorber", None, None, None])
        assert ship.shield_absorb == 3

    def test_broadside_no_stat_change(self, ship):
        ship.apply_modules(["broadside", None, None, None])
        assert ship.max_hp == PLAYER_MAX_HP
        assert ship._max_spd == MAX_SPD

    def test_multiple_modules(self, ship):
        ship.apply_modules(["armor_plate", "engine_booster", "shield_booster", "damage_absorber"])
        assert ship.max_hp == PLAYER_MAX_HP + 20
        assert ship._max_spd == MAX_SPD + 50
        assert ship.max_shields == PLAYER_MAX_SHIELD + 20
        assert ship.shield_absorb == 3

    def test_clamps_hp_to_new_max(self, ship):
        ship.apply_modules(["armor_plate", None, None, None])
        ship.hp = ship.max_hp  # full HP with armor
        ship.apply_modules([None, None, None, None])  # remove armor
        assert ship.hp <= ship.max_hp
        assert ship.max_hp == PLAYER_MAX_HP

    def test_clamps_shields_to_new_max(self, ship):
        ship.apply_modules(["shield_booster", None, None, None])
        ship.shields = ship.max_shields
        ship.apply_modules([None, None, None, None])
        assert ship.shields <= ship.max_shields

    def test_resets_to_base_on_reapply(self, ship):
        ship.apply_modules(["armor_plate", None, None, None])
        ship.apply_modules([None, None, None, None])
        assert ship.max_hp == PLAYER_MAX_HP
        assert ship.shield_absorb == 0

    def test_unknown_module_ignored(self, ship):
        ship.apply_modules(["nonexistent_module", None, None, None])
        assert ship.max_hp == PLAYER_MAX_HP


# ── Sideslip tests ───────────────────────────────────────────────────────

class TestSideslip:
    def test_slip_left_changes_velocity(self, ship):
        ship.heading = 0.0
        ship.apply_input(1.0, False, False, False, False, slip_left=True)
        assert ship.vel_x != 0.0 or ship.vel_y != 0.0

    def test_slip_right_opposite_to_left(self, ship):
        s1 = PlayerShip.__new__(PlayerShip)
        import arcade
        from PIL import Image as PILImage
        tex = arcade.Texture(PILImage.new("RGBA", (32, 32), (255, 0, 0, 255)))
        arcade.Sprite.__init__(s1, path_or_texture=tex, scale=1.5)
        for attr in ['_use_legacy', '_frames', '_rot_speed', '_thrust', '_brake',
                     '_max_spd', '_damping', 'hp', 'max_hp', 'shields', 'max_shields',
                     '_base_max_hp', '_base_max_spd', '_base_max_shields',
                     '_base_shield_regen', '_shield_regen', 'shield_absorb',
                     '_shield_acc', '_collision_cd', 'guns', 'vel_x', 'vel_y',
                     'heading', '_intensity', '_anim_timer', '_anim_col',
                     'world_width', 'world_height']:
            setattr(s1, attr, getattr(ship, attr))
        s1.center_x = ship.center_x
        s1.center_y = ship.center_y

        ship.apply_input(1.0, False, False, False, False, slip_left=True)
        s1.apply_input(1.0, False, False, False, False, slip_right=True)
        # Velocities should be in opposite lateral directions
        # (vel_x should have opposite signs for left vs right slip)
        assert ship.vel_x * s1.vel_x < 0 or ship.vel_y * s1.vel_y < 0


# ── Inventory consolidate tests ──────────────────────────────────────────

class TestInventoryConsolidate:
    def test_merges_same_type(self, inv):
        inv._items[(0, 0)] = ("iron", 50)
        inv._items[(0, 1)] = ("iron", 30)
        inv._items[(1, 0)] = ("iron", 20)
        inv.consolidate()
        total = sum(ct for _, ct in inv._items.values())
        assert total == 100
        types = set(it for it, _ in inv._items.values())
        assert types == {"iron"}

    def test_respects_max_stack(self, inv):
        inv._items[(0, 0)] = ("repair_pack", 80)
        inv._items[(0, 1)] = ("repair_pack", 50)
        inv.consolidate()
        total = sum(ct for _, ct in inv._items.values())
        assert total == 130
        max_s = MAX_STACK.get("repair_pack", MAX_STACK_DEFAULT)
        for _, ct in inv._items.values():
            assert ct <= max_s

    def test_different_types_preserved(self, inv):
        inv._items[(0, 0)] = ("iron", 50)
        inv._items[(0, 1)] = ("repair_pack", 3)
        inv.consolidate()
        types = set(it for it, _ in inv._items.values())
        assert "iron" in types
        assert "repair_pack" in types

    def test_empty_inventory(self, inv):
        inv.consolidate()
        assert len(inv._items) == 0


class TestStationInventoryConsolidate:
    def test_merges_iron(self, station_inv):
        station_inv._items[(0, 0)] = ("iron", 100)
        station_inv._items[(0, 1)] = ("iron", 200)
        station_inv._items[(0, 2)] = ("iron", 300)
        station_inv.consolidate()
        total = sum(ct for _, ct in station_inv._items.values())
        assert total == 600

    def test_blueprint_max_stack(self, station_inv):
        # Add 15 of a blueprint (max stack = 10)
        station_inv._items[(0, 0)] = ("bp_armor_plate", 8)
        station_inv._items[(0, 1)] = ("bp_armor_plate", 7)
        station_inv.consolidate()
        total = sum(ct for it, ct in station_inv._items.values()
                    if it == "bp_armor_plate")
        assert total == 15
        for _, ct in station_inv._items.values():
            assert ct <= MAX_STACK_DEFAULT


# ── Stack limit constants ────────────────────────────────────────────────

class TestStackLimits:
    def test_iron_stack_limit(self):
        assert MAX_STACK["iron"] == 999

    def test_repair_pack_stack_limit(self):
        assert MAX_STACK["repair_pack"] == 99

    def test_default_stack_limit(self):
        assert MAX_STACK_DEFAULT == 10
