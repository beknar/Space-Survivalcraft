"""Tests for the Stalker enemy + its homing-missile fire path.

Stalkers live in the Star Maze and fire HomingMissile instances at
the player at a 1.6 s cadence.  These tests pin construction stats,
state-machine transitions (PATROL <-> PURSUE), the fire gate
(state + range + cooldown), and that the constants match the spec.
"""
from __future__ import annotations

import math

import arcade
import pytest

from constants import (
    STALKER_HP, STALKER_SPEED, STALKER_RADIUS, STALKER_COUNT,
    STALKER_DETECT_DIST, STALKER_FIRE_COOLDOWN, STALKER_FIRE_RANGE,
    STALKER_IRON_DROP, STALKER_XP, STALKER_SHEET_ROW, STALKER_SHEET_COL,
    STALKER_PNG, MISSILE_DAMAGE, MISSILE_SPEED, MISSILE_RANGE,
    MISSILE_TURN_RATE,
)


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


@pytest.fixture
def missile_tex():
    from PIL import Image
    return arcade.Texture(Image.new("RGBA", (8, 8), (200, 50, 50, 255)))


# ── Spec-pinning ──────────────────────────────────────────────────────────

class TestStalkerStats:
    def test_count(self): assert STALKER_COUNT == 15
    def test_hp(self): assert STALKER_HP == 75
    def test_speed(self): assert STALKER_SPEED == 100.0
    def test_iron_drop(self): assert STALKER_IRON_DROP == 90
    def test_xp_reward(self): assert STALKER_XP == 30
    def test_fire_cooldown(self): assert STALKER_FIRE_COOLDOWN == 1.6
    def test_sheet_row_third_from_top(self): assert STALKER_SHEET_ROW == 2
    def test_sheet_col_third(self): assert STALKER_SHEET_COL == 2

    def test_asset_path(self):
        # User-spec asset path.
        assert STALKER_PNG.endswith("faction_6_monsters_128x128.png")


class TestStalkerMissileSpec:
    """Stalker missiles inherit the player's missile stats verbatim."""

    def test_damage_matches_player_missile(self):
        # Same MISSILE_DAMAGE constant feeds both factions, so this
        # is true by construction; pinning it prevents accidental drift.
        assert MISSILE_DAMAGE == 50.0

    def test_speed_range_turn_unchanged(self):
        assert MISSILE_SPEED == 400.0
        assert MISSILE_RANGE == 1500.0
        assert MISSILE_TURN_RATE == 180.0


# ── Construction ──────────────────────────────────────────────────────────

class TestStalkerConstruction:
    def test_basic_stats(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 100.0, 200.0)
        assert s.hp == STALKER_HP
        assert s.max_hp == STALKER_HP
        assert s.shields == 0
        assert s.center_x == 100.0
        assert s.center_y == 200.0
        assert s.radius == STALKER_RADIUS

    def test_starts_in_patrol(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        assert s._state == s._STATE_PATROL


# ── State machine ─────────────────────────────────────────────────────────

class TestStalkerStateMachine:
    def test_patrol_to_pursue_within_detect(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        # Player just inside detect range.
        empty = arcade.SpriteList()
        s.update_alien(0.016, STALKER_DETECT_DIST - 50, 0.0, empty, empty)
        assert s._state == s._STATE_PURSUE

    def test_patrol_stays_when_player_far(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        empty = arcade.SpriteList()
        s.update_alien(0.016, STALKER_DETECT_DIST * 2, 0.0, empty, empty)
        assert s._state == s._STATE_PATROL

    def test_pursue_drops_back_to_patrol_at_3x_detect(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        s._state = s._STATE_PURSUE
        empty = arcade.SpriteList()
        s.update_alien(0.016, STALKER_DETECT_DIST * 3.5, 0.0, empty, empty)
        assert s._state == s._STATE_PATROL


# ── Fire path ─────────────────────────────────────────────────────────────

class TestStalkerFire:
    def test_fires_in_pursue_when_off_cooldown(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        s._state = s._STATE_PURSUE
        s._fire_cd = 0.0
        empty = arcade.SpriteList()
        fired = s.update_alien(
            0.016, STALKER_FIRE_RANGE - 100, 0.0, empty, empty)
        assert len(fired) == 1
        # Fired object is a HomingMissile carrying the spec damage.
        from sprites.missile import HomingMissile
        assert isinstance(fired[0], HomingMissile)
        assert fired[0].damage == MISSILE_DAMAGE
        # Cooldown was armed.
        assert s._fire_cd == pytest.approx(STALKER_FIRE_COOLDOWN)

    def test_no_fire_in_patrol(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        # State stays PATROL because player is far away.
        empty = arcade.SpriteList()
        fired = s.update_alien(
            0.016, STALKER_DETECT_DIST * 2, 0.0, empty, empty)
        assert fired == []

    def test_no_fire_during_cooldown(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        s._state = s._STATE_PURSUE
        s._fire_cd = 0.5
        empty = arcade.SpriteList()
        fired = s.update_alien(
            0.016, STALKER_FIRE_RANGE - 100, 0.0, empty, empty)
        assert fired == []

    def test_no_fire_out_of_range(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        s._state = s._STATE_PURSUE
        s._fire_cd = 0.0
        empty = arcade.SpriteList()
        fired = s.update_alien(
            0.016, STALKER_FIRE_RANGE + 200, 0.0, empty, empty)
        assert fired == []

    def test_take_damage_accumulates(self, missile_tex):
        from sprites.stalker import Stalker
        s = Stalker(missile_tex, 0.0, 0.0)
        s.take_damage(25)
        s.take_damage(10)
        assert s.hp == STALKER_HP - 35


# ── Drone SFX wiring ──────────────────────────────────────────────────────

class TestDroneSfxConstants:
    def test_mining_drone_sfx_path(self):
        from constants import SFX_MINING_DRONE_LASER
        assert SFX_MINING_DRONE_LASER.endswith(
            "Sci-Fi Radiation Weapon Shot 1.wav")

    def test_combat_drone_sfx_path(self):
        from constants import SFX_COMBAT_DRONE_LASER
        # The user wrote "Samll" — actual file is "Small".  We map
        # to the correct filename.
        assert SFX_COMBAT_DRONE_LASER.endswith(
            "Sci-Fi Small Energy Weapon Shot 1.wav")


class TestDroneFireSfxAttached:
    def test_mining_drone_has_fire_snd(self):
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        assert d._fire_snd is not None

    def test_combat_drone_has_fire_snd(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        assert d._fire_snd is not None
