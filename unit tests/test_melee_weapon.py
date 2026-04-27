"""Energy-blade (melee) weapon — persistent sword that swings on fire.

Pin: load-weapons inventory + cycle, persistent blade lifecycle
(visible when active, hidden when not), idle pose (50/80 px ahead
+ aligned with heading), swing animation triggered by fire,
ship-type-aware reach + damage, AOE damage one-hit-per-enemy
per swing, sword scaled to half the player ship.
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
        assert "Melee" in [w.name for w in weapons]

    def test_melee_appears_after_basic_and_mining(self):
        from world_setup import load_weapons
        weapons = load_weapons(gun_count=1)
        assert [w.name for w in weapons] == [
            "Basic Laser", "Mining Beam", "Melee"]

    def test_dual_gun_ship_has_one_melee_per_gun_block(self):
        from world_setup import load_weapons
        weapons = load_weapons(gun_count=2)
        assert [w.name for w in weapons] == [
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
        assert gv._active_weapon.name == "Basic Laser"
        gv._cycle_weapon()
        assert gv._active_weapon.name == "Mining Beam"
        gv._cycle_weapon()
        assert gv._active_weapon.name == "Melee"
        gv._cycle_weapon()
        assert gv._active_weapon.name == "Basic Laser"


# ── Persistent blade lifecycle ───────────────────────────────────────────


class TestBladeLifecycle:
    def test_blade_appears_when_melee_is_active(self):
        from update_logic import update_weapons
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        # Cycle to Melee (Basic → Mining → Melee).
        gv._cycle_weapon(); gv._cycle_weapon()
        update_weapons(gv, 1 / 60, fire=False)
        assert gv._active_blade is not None
        assert gv._active_blade in gv._melee_swings

    def test_blade_disappears_when_other_weapon_active(self):
        from update_logic import update_weapons
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()       # to Melee
        update_weapons(gv, 1 / 60, fire=False)       # blade spawns
        assert gv._active_blade is not None
        gv._cycle_weapon()                            # back to Basic Laser
        update_weapons(gv, 1 / 60, fire=False)
        assert gv._active_blade is None
        assert len(gv._melee_swings) == 0


# ── Idle pose: blade in front of ship at the right offset ────────────────


class TestBladeIdlePose:
    def _setup_with_melee_active(self, ship_type):
        from update_logic import update_weapons
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type=ship_type,
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        # Park player at a deterministic position + heading.
        gv.player.center_x = 1000.0
        gv.player.center_y = 2000.0
        gv.player.heading = 0.0
        update_weapons(gv, 1 / 60, fire=False)
        return gv

    def test_blade_offset_is_base_hit_radius_for_non_bastion(self):
        """Blade rests at MELEE_HIT_RADIUS (80 px) ahead of the
        non-Bastion ship's nose."""
        from constants import MELEE_HIT_RADIUS
        gv = self._setup_with_melee_active("Cruiser")
        b = gv._active_blade
        assert b.center_x == pytest.approx(1000.0)
        assert b.center_y == pytest.approx(2000.0 + MELEE_HIT_RADIUS)
        assert b.hit_radius == MELEE_HIT_RADIUS

    def test_blade_offset_is_bastion_hit_radius_for_bastion(self):
        """Bastion gets a longer reach — blade rests at
        MELEE_BASTION_HIT_RADIUS (110 px) ahead."""
        from constants import MELEE_BASTION_HIT_RADIUS
        gv = self._setup_with_melee_active("Bastion")
        b = gv._active_blade
        assert b.center_y == pytest.approx(
            2000.0 + MELEE_BASTION_HIT_RADIUS)
        assert b.hit_radius == MELEE_BASTION_HIT_RADIUS

    def test_blade_idle_angle_aligned_with_heading(self):
        """Idle blade renders aligned with the ship's heading.
        The sword PNG is drawn diagonally so the rendered angle
        is ``heading + MELEE_TEX_ANGLE_OFFSET`` (the offset
        compensates for the texture's native tilt)."""
        from constants import MELEE_TEX_ANGLE_OFFSET
        gv = self._setup_with_melee_active("Cruiser")
        assert gv._active_blade.angle == pytest.approx(
            gv.player.heading + MELEE_TEX_ANGLE_OFFSET)


class TestBladeReachConstants:
    def test_base_reach_is_80_px(self):
        from constants import MELEE_HIT_RADIUS
        assert MELEE_HIT_RADIUS == 80.0

    def test_bastion_reach_is_110_px(self):
        from constants import MELEE_BASTION_HIT_RADIUS
        assert MELEE_BASTION_HIT_RADIUS == 110.0

    def test_tex_angle_offset_present(self):
        """Some non-zero offset must exist or the diagonally-
        drawn sword PNG will render tilted right of the ship's
        spine (the regression we're fixing here)."""
        from constants import MELEE_TEX_ANGLE_OFFSET
        assert MELEE_TEX_ANGLE_OFFSET != 0.0


# ── Bastion bonus ────────────────────────────────────────────────────────


class TestBastionBonus:
    def test_bastion_blade_carries_bonus_damage(self):
        from update_logic import update_weapons
        from constants import (MELEE_DAMAGE, MELEE_BASTION_DAMAGE_BONUS)
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Bastion",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        update_weapons(gv, 1 / 60, fire=False)
        assert gv._active_blade.damage == (
            MELEE_DAMAGE + MELEE_BASTION_DAMAGE_BONUS)


# ── Swing animation triggered by fire ────────────────────────────────────


class TestSwingTriggeredByFire:
    def test_fire_starts_swing_animation(self):
        from update_logic import update_weapons
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        update_weapons(gv, 1 / 60, fire=False)
        assert gv._active_blade.is_swinging is False
        update_weapons(gv, 1 / 60, fire=True)
        assert gv._active_blade.is_swinging is True

    def test_swing_animation_ends_after_lifetime(self):
        from update_logic import update_weapons
        from constants import MELEE_SWING_LIFETIME
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        update_weapons(gv, 1 / 60, fire=True)   # spawn + swing
        # Tick past the swing lifetime.
        update_weapons(gv, MELEE_SWING_LIFETIME + 0.05,
                        fire=False)
        assert gv._active_blade.is_swinging is False
        # Blade is still on screen — only the animation ended.
        assert gv._active_blade is not None


# ── AOE damage during swing ──────────────────────────────────────────────


class TestSwingDealsDamage:
    def test_enemy_inside_radius_takes_damage_during_swing(self):
        from update_logic import update_weapons
        from constants import MELEE_DAMAGE
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        # Stub enemy 30 px ahead of where the blade idles (which
        # is 50 px ahead of the ship).  So enemy at ship+80
        # should be inside the 50 px hit radius around the blade.
        target = SimpleNamespace(
            center_x=gv.player.center_x,
            center_y=gv.player.center_y + 80.0,
            hp=200, _ticks=0)
        target.take_damage = lambda dmg: setattr(
            target, "hp", target.hp - dmg) or setattr(
            target, "_ticks", target._ticks + 1)
        target.remove_from_sprite_lists = lambda: None
        gv.alien_list = [target]
        # Trigger a swing.
        update_weapons(gv, 1 / 60, fire=True)
        assert target._ticks == 1
        assert target.hp == 200 - MELEE_DAMAGE

    def test_idle_blade_does_no_damage(self):
        from update_logic import update_weapons
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        target = SimpleNamespace(
            center_x=gv.player.center_x,
            center_y=gv.player.center_y + 80.0,
            hp=200)
        target.take_damage = lambda dmg: setattr(
            target, "hp", target.hp - dmg)
        target.remove_from_sprite_lists = lambda: None
        gv.alien_list = [target]
        # Tick WITHOUT firing — blade idles, no damage.
        update_weapons(gv, 1 / 60, fire=False)
        assert target.hp == 200

    def test_enemy_hit_at_most_once_per_swing(self):
        from update_logic import update_weapons
        from game_view import GameView
        from constants import MELEE_DAMAGE
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        target = SimpleNamespace(
            center_x=gv.player.center_x,
            center_y=gv.player.center_y + 80.0,
            hp=500, _ticks=0)
        target.take_damage = lambda dmg: setattr(
            target, "hp", target.hp - dmg) or setattr(
            target, "_ticks", target._ticks + 1)
        target.remove_from_sprite_lists = lambda: None
        gv.alien_list = [target]
        # Fire once, then tick the swing across multiple frames
        # (no further fire input).  The enemy should be hit once
        # — not once per frame of the swing animation.
        update_weapons(gv, 1 / 60, fire=True)
        for _ in range(10):
            update_weapons(gv, 1 / 60, fire=False)
        assert target._ticks == 1
        assert target.hp == 500 - MELEE_DAMAGE


# ── Sword scale = half the ship ──────────────────────────────────────────


class TestSwordHalfShipSize:
    def test_blade_scale_is_half_of_player_ship(self):
        """Player renders at 128 px sheet × 0.75 scale = 96 px.
        Sword PNG is 128 px native, so scale 0.375 puts the blade
        at exactly 48 px = half the ship's rendered size."""
        from update_logic import update_weapons
        from game_view import GameView
        from constants import MELEE_SCALE
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        update_weapons(gv, 1 / 60, fire=False)
        # MELEE_SCALE constant pinned to 0.375.
        assert MELEE_SCALE == pytest.approx(0.375)
        # Blade carries the same scale.
        assert gv._active_blade.scale_x == pytest.approx(0.375)
