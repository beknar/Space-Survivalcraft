"""Tests for constants.py — data validation for FACTIONS, SHIP_TYPES, and physics constants."""
from __future__ import annotations

from constants import (
    FACTIONS, SHIP_TYPES, CONTRAIL_COLOURS,
    SCREEN_WIDTH, SCREEN_HEIGHT, WORLD_WIDTH, WORLD_HEIGHT,
    ROT_SPEED, THRUST, BRAKE, MAX_SPD, DAMPING,
    ASTEROID_HP, ASTEROID_COUNT, ASTEROID_IRON_YIELD,
    ALIEN_HP, ALIEN_COUNT, ALIEN_SPEED, ALIEN_DETECT_DIST,
    ALIEN_LASER_DAMAGE, ALIEN_LASER_RANGE, ALIEN_LASER_SPEED,
    ALIEN_FIRE_COOLDOWN,
    SAVE_SLOT_COUNT,
    INV_COLS, INV_ROWS,
    SHIP_RADIUS, ASTEROID_RADIUS, ALIEN_RADIUS,
    NOSE_OFFSET, GUN_LATERAL_OFFSET,
    EXPLOSION_FRAMES, EXPLOSION_FPS,
    SHIELD_COLS, SHIELD_ROWS, SHIELD_ANIM_FPS, SHIELD_HIT_FLASH,
)


# ── FACTIONS ──────────────────────────────────────────────────────────────────

class TestFactions:
    def test_faction_count(self):
        assert len(FACTIONS) == 4

    def test_faction_names(self):
        expected = {"Earth", "Colonial", "Heavy World", "Ascended"}
        assert set(FACTIONS.keys()) == expected

    def test_faction_values_are_png_filenames(self):
        for name, filename in FACTIONS.items():
            assert filename.endswith(".png"), f"{name} file must be .png"
            assert "128x128" in filename, f"{name} should reference 128x128 sheet"


# ── SHIP_TYPES ────────────────────────────────────────────────────────────────

class TestShipTypes:
    REQUIRED_KEYS = {
        "row", "hp", "shields", "shield_regen",
        "rot_speed", "thrust", "brake", "max_speed", "damping", "guns",
    }

    def test_ship_type_count(self):
        assert len(SHIP_TYPES) == 5

    def test_ship_type_names(self):
        expected = {"Cruiser", "Bastion", "Aegis", "Striker", "Thunderbolt"}
        assert set(SHIP_TYPES.keys()) == expected

    def test_all_keys_present(self):
        for name, stats in SHIP_TYPES.items():
            missing = self.REQUIRED_KEYS - set(stats.keys())
            assert not missing, f"{name} missing keys: {missing}"

    def test_hp_positive(self):
        for name, stats in SHIP_TYPES.items():
            assert stats["hp"] > 0, f"{name} HP must be > 0"

    def test_shields_non_negative(self):
        for name, stats in SHIP_TYPES.items():
            assert stats["shields"] >= 0, f"{name} shields must be >= 0"

    def test_damping_in_range(self):
        for name, stats in SHIP_TYPES.items():
            assert 0 < stats["damping"] < 1, f"{name} damping must be 0..1"

    def test_guns_valid(self):
        for name, stats in SHIP_TYPES.items():
            assert stats["guns"] in {1, 2}, f"{name} guns must be 1 or 2"

    def test_thunderbolt_has_two_guns(self):
        assert SHIP_TYPES["Thunderbolt"]["guns"] == 2

    def test_max_speed_positive(self):
        for name, stats in SHIP_TYPES.items():
            assert stats["max_speed"] > 0, f"{name} max_speed must be > 0"

    def test_thrust_positive(self):
        for name, stats in SHIP_TYPES.items():
            assert stats["thrust"] > 0, f"{name} thrust must be > 0"

    def test_brake_positive(self):
        for name, stats in SHIP_TYPES.items():
            assert stats["brake"] > 0, f"{name} brake must be > 0"

    def test_shield_regen_positive(self):
        for name, stats in SHIP_TYPES.items():
            assert stats["shield_regen"] > 0, f"{name} shield_regen must be > 0"


# ── CONTRAIL COLOURS ──────────────────────────────────────────────────────────

class TestContrailColours:
    def test_every_ship_has_contrail(self):
        for ship in SHIP_TYPES:
            assert ship in CONTRAIL_COLOURS, f"{ship} missing contrail colour"

    def test_colours_are_rgb_tuples(self):
        for ship, (start, end) in CONTRAIL_COLOURS.items():
            assert len(start) == 3, f"{ship} start colour must be (r, g, b)"
            assert len(end) == 3, f"{ship} end colour must be (r, g, b)"
            for c in start + end:
                assert 0 <= c <= 255, f"{ship} colour component out of range"


# ── WORLD / SCREEN DIMENSIONS ─────────────────────────────────────────────────

class TestDimensions:
    def test_screen_positive(self):
        assert SCREEN_WIDTH > 0
        assert SCREEN_HEIGHT > 0

    def test_world_positive(self):
        assert WORLD_WIDTH > 0
        assert WORLD_HEIGHT > 0

    def test_world_larger_than_screen(self):
        assert WORLD_WIDTH > SCREEN_WIDTH
        assert WORLD_HEIGHT > SCREEN_HEIGHT


# ── PHYSICS CONSTANTS ─────────────────────────────────────────────────────────

class TestPhysics:
    def test_rot_speed_positive(self):
        assert ROT_SPEED > 0

    def test_thrust_positive(self):
        assert THRUST > 0

    def test_brake_positive(self):
        assert BRAKE > 0

    def test_max_speed_positive(self):
        assert MAX_SPD > 0

    def test_damping_in_range(self):
        assert 0 < DAMPING < 1

    def test_radii_positive(self):
        assert SHIP_RADIUS > 0
        assert ASTEROID_RADIUS > 0
        assert ALIEN_RADIUS > 0

    def test_nose_offset_positive(self):
        assert NOSE_OFFSET > 0

    def test_gun_lateral_offset_positive(self):
        assert GUN_LATERAL_OFFSET > 0


# ── MISCELLANEOUS ─────────────────────────────────────────────────────────────

class TestMisc:
    def test_asteroid_hp_positive(self):
        assert ASTEROID_HP > 0

    def test_asteroid_count_positive(self):
        assert ASTEROID_COUNT > 0

    def test_asteroid_iron_yield_positive(self):
        assert ASTEROID_IRON_YIELD > 0

    def test_alien_hp_positive(self):
        assert ALIEN_HP > 0

    def test_alien_count_positive(self):
        assert ALIEN_COUNT > 0

    def test_alien_speed_positive(self):
        assert ALIEN_SPEED > 0

    def test_alien_detect_dist_positive(self):
        assert ALIEN_DETECT_DIST > 0

    def test_alien_laser_stats_positive(self):
        assert ALIEN_LASER_DAMAGE > 0
        assert ALIEN_LASER_RANGE > 0
        assert ALIEN_LASER_SPEED > 0
        assert ALIEN_FIRE_COOLDOWN > 0

    def test_save_slot_count(self):
        assert SAVE_SLOT_COUNT == 10

    def test_inventory_grid(self):
        assert INV_COLS == 5
        assert INV_ROWS == 5

    def test_explosion_frames_positive(self):
        assert EXPLOSION_FRAMES > 0
        assert EXPLOSION_FPS > 0

    def test_shield_sheet_dimensions(self):
        assert SHIELD_COLS > 0
        assert SHIELD_ROWS > 0
        assert SHIELD_ANIM_FPS > 0
        assert SHIELD_HIT_FLASH > 0
