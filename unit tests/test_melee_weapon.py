"""Energy-blade (melee) weapon — third basic weapon for every ship.

Pin the load-weapons inventory, the spawn helper's
ship-type-aware reach + damage, the per-frame swing tick (anchor
to ship + lifetime), the AOE damage pass (one hit per enemy per
swing), and the cycle order through Tab.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import patch

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


# ── Weapon list inventory ─────────────────────────────────────────────────


class TestLoadWeaponsIncludesMelee:
    def test_melee_present_in_load_weapons_output(self):
        from world_setup import load_weapons
        weapons = load_weapons(gun_count=1)
        names = [w.name for w in weapons]
        assert "Melee" in names

    def test_melee_appears_after_basic_and_mining(self):
        """Cycle order is Basic → Mining → Melee — pin the index
        layout so Tab cycles through all three."""
        from world_setup import load_weapons
        weapons = load_weapons(gun_count=1)
        names = [w.name for w in weapons]
        assert names == ["Basic Laser", "Mining Beam", "Melee"]

    def test_dual_gun_ship_has_one_melee_per_gun_block(self):
        """Per-group block size matches gun_count so the cycle
        math (idx += gun_count) lands cleanly on each group."""
        from world_setup import load_weapons
        weapons = load_weapons(gun_count=2)
        names = [w.name for w in weapons]
        assert names == [
            "Basic Laser", "Basic Laser",
            "Mining Beam", "Mining Beam",
            "Melee", "Melee",
        ]

    def test_melee_weapon_stats(self):
        from world_setup import load_weapons
        from constants import MELEE_COOLDOWN, MELEE_DAMAGE
        weapons = load_weapons(gun_count=1)
        melee = next(w for w in weapons if w.name == "Melee")
        assert melee.cooldown == MELEE_COOLDOWN
        assert melee.damage == MELEE_DAMAGE


# ── HUD label ─────────────────────────────────────────────────────────────


class TestHUDShowsMelee:
    def test_active_weapon_name_is_melee_after_two_cycles(self):
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        # Start: Basic Laser.  Cycle once → Mining Beam.  Cycle
        # again → Melee.
        assert gv._active_weapon.name == "Basic Laser"
        gv._cycle_weapon()
        assert gv._active_weapon.name == "Mining Beam"
        gv._cycle_weapon()
        assert gv._active_weapon.name == "Melee"
        # Cycling once more returns to Basic Laser.
        gv._cycle_weapon()
        assert gv._active_weapon.name == "Basic Laser"


# ── Swing spawn position ──────────────────────────────────────────────────


class TestSwingSpawnsAtNoseOffset:
    def test_swing_appears_50_px_ahead_for_non_bastion(self):
        from sprites.melee import MeleeSwing
        from constants import MELEE_HIT_RADIUS, MELEE_DAMAGE
        # Stub ship at origin facing north (heading=0).
        ship = SimpleNamespace(
            center_x=100.0, center_y=200.0, heading=0.0)
        # Need a real Texture so arcade.Sprite construction works.
        tex = arcade.make_soft_circle_texture(8, arcade.color.WHITE)
        sw = MeleeSwing(tex, ship, offset=MELEE_HIT_RADIUS,
                         damage=MELEE_DAMAGE,
                         hit_radius=MELEE_HIT_RADIUS)
        # Heading 0 = +y forward, so swing sits 50 px north of ship.
        assert sw.center_x == pytest.approx(100.0)
        assert sw.center_y == pytest.approx(200.0 + MELEE_HIT_RADIUS)

    def test_swing_appears_80_px_ahead_for_bastion(self):
        """Bastion gets a longer reach — swing distance from the
        ship matches MELEE_BASTION_HIT_RADIUS."""
        from sprites.melee import MeleeSwing
        from constants import (MELEE_BASTION_HIT_RADIUS,
                                MELEE_DAMAGE,
                                MELEE_BASTION_DAMAGE_BONUS)
        ship = SimpleNamespace(
            center_x=0.0, center_y=0.0, heading=0.0)
        tex = arcade.make_soft_circle_texture(8, arcade.color.WHITE)
        sw = MeleeSwing(
            tex, ship, offset=MELEE_BASTION_HIT_RADIUS,
            damage=MELEE_DAMAGE + MELEE_BASTION_DAMAGE_BONUS,
            hit_radius=MELEE_BASTION_HIT_RADIUS)
        assert sw.center_y == pytest.approx(MELEE_BASTION_HIT_RADIUS)
        assert sw.damage == MELEE_DAMAGE + MELEE_BASTION_DAMAGE_BONUS


# ── Bastion bonus via _spawn_melee_swing ─────────────────────────────────


class TestBastionBonusApplied:
    def test_non_bastion_gets_base_damage_and_radius(self):
        from update_logic import _spawn_melee_swing
        from constants import MELEE_DAMAGE, MELEE_HIT_RADIUS
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        tex = arcade.make_soft_circle_texture(8, arcade.color.WHITE)
        _spawn_melee_swing(gv, tex)
        sw = gv._melee_swings[-1]
        assert sw.damage == MELEE_DAMAGE
        assert sw.hit_radius == MELEE_HIT_RADIUS

    def test_bastion_gets_bonus_damage_and_extended_radius(self):
        from update_logic import _spawn_melee_swing
        from constants import (MELEE_DAMAGE, MELEE_BASTION_DAMAGE_BONUS,
                                MELEE_BASTION_HIT_RADIUS)
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Bastion",
                       skip_music=True)
        tex = arcade.make_soft_circle_texture(8, arcade.color.WHITE)
        _spawn_melee_swing(gv, tex)
        sw = gv._melee_swings[-1]
        assert sw.damage == MELEE_DAMAGE + MELEE_BASTION_DAMAGE_BONUS
        assert sw.hit_radius == MELEE_BASTION_HIT_RADIUS


# ── AOE damage pass ──────────────────────────────────────────────────────


class TestSwingDamagesEnemiesInRadius:
    def test_enemy_inside_radius_takes_damage_once_per_swing(self):
        from update_logic import _spawn_melee_swing, update_melee_swings
        from constants import MELEE_DAMAGE
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        # Stub enemy 30 px ahead of the player (well inside 50 px).
        # Use SimpleNamespace + a stub take_damage that records the
        # hit count.  alien_list isn't used by the AOE pass for
        # damage routing — it just iterates whatever lists the zone
        # exposes.  Inject our enemy via the Zone-1 alien_list.
        ship = gv.player
        target = SimpleNamespace(
            center_x=ship.center_x,
            center_y=ship.center_y + 30.0,
            hp=200, _ticks=0)
        target.take_damage = lambda dmg: setattr(
            target, "hp", target.hp - dmg) or setattr(
            target, "_ticks", target._ticks + 1)
        target.remove_from_sprite_lists = lambda: None
        # Swap a list-like alien_list so iteration works.
        gv.alien_list = [target]
        tex = arcade.make_soft_circle_texture(8, arcade.color.WHITE)
        _spawn_melee_swing(gv, tex)
        # First tick — target takes one hit.
        update_melee_swings(gv, 0.05)
        assert target._ticks == 1
        assert target.hp == 200 - MELEE_DAMAGE
        # Second tick (still within swing lifetime) — target NOT
        # hit again because the swing remembers its victims.
        update_melee_swings(gv, 0.05)
        assert target._ticks == 1

    def test_enemy_outside_radius_takes_no_damage(self):
        from update_logic import _spawn_melee_swing, update_melee_swings
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        ship = gv.player
        target = SimpleNamespace(
            center_x=ship.center_x + 500.0,
            center_y=ship.center_y, hp=100)
        target.take_damage = lambda dmg: setattr(
            target, "hp", target.hp - dmg)
        target.remove_from_sprite_lists = lambda: None
        gv.alien_list = [target]
        tex = arcade.make_soft_circle_texture(8, arcade.color.WHITE)
        _spawn_melee_swing(gv, tex)
        update_melee_swings(gv, 0.05)
        assert target.hp == 100


# ── Lifetime / cull ──────────────────────────────────────────────────────


class TestSwingLifetime:
    def test_swing_culled_after_lifetime(self):
        from update_logic import _spawn_melee_swing, update_melee_swings
        from constants import MELEE_SWING_LIFETIME
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        tex = arcade.make_soft_circle_texture(8, arcade.color.WHITE)
        _spawn_melee_swing(gv, tex)
        assert len(gv._melee_swings) == 1
        # Tick past the lifetime in one call so the swing expires.
        update_melee_swings(gv, MELEE_SWING_LIFETIME + 0.05)
        assert len(gv._melee_swings) == 0
