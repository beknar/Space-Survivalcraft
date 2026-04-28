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

    def test_blade_handle_at_base_hit_radius_for_non_bastion(self):
        """Handle (pivot) sits at MELEE_HIT_RADIUS (80 px) ahead
        of the non-Bastion ship's nose; the blade extends further
        forward from there."""
        from constants import MELEE_HIT_RADIUS
        gv = self._setup_with_melee_active("Cruiser")
        b = gv._active_blade
        hx, hy = b.handle_pos
        assert hx == pytest.approx(1000.0)
        assert hy == pytest.approx(2000.0 + MELEE_HIT_RADIUS)
        assert b.hit_radius == MELEE_HIT_RADIUS

    def test_blade_handle_at_bastion_hit_radius_for_bastion(self):
        """Bastion gets a longer reach — handle sits at
        MELEE_BASTION_HIT_RADIUS (110 px) ahead."""
        from constants import MELEE_BASTION_HIT_RADIUS
        gv = self._setup_with_melee_active("Bastion")
        b = gv._active_blade
        _, hy = b.handle_pos
        assert hy == pytest.approx(2000.0 + MELEE_BASTION_HIT_RADIUS)
        assert b.hit_radius == MELEE_BASTION_HIT_RADIUS

    def test_blade_sprite_center_offset_forward_from_handle(self):
        """Sprite centre is half a blade-length AHEAD of the
        handle — that's what gives the swing-from-handle effect.
        The sprite rotates around its centre, so for the visible
        rotation pivot to be at the handle the centre has to
        slide forward by half the sprite's height."""
        gv = self._setup_with_melee_active("Cruiser")
        b = gv._active_blade
        hx, hy = b.handle_pos
        # Heading=0 → blade extends straight up → centre at
        # handle + (0, half_height).
        assert b.center_x == pytest.approx(hx)
        assert b.center_y == pytest.approx(hy + b.height * 0.5)

    def test_blade_idle_angle_aligned_with_heading(self):
        """Idle blade renders aligned with the ship's heading.
        Lightsabre PNGs are drawn vertically so the rendered angle
        equals ``heading + MELEE_TEX_ANGLE_OFFSET`` (offset is
        currently zero — kept as a constant in case a future
        sword sprite needs compensation)."""
        from constants import MELEE_TEX_ANGLE_OFFSET
        gv = self._setup_with_melee_active("Cruiser")
        assert gv._active_blade.angle == pytest.approx(
            gv.player.heading + MELEE_TEX_ANGLE_OFFSET)


class TestHandleStaysFixedDuringSwing:
    def test_handle_position_invariant_across_swing_animation(self):
        """The whole point of swinging from the handle is that
        the handle stays put while the tip arcs through the air.
        Tick a swing across multiple frames; the handle position
        must be identical (or near-identical) at every step
        because the ship hasn't moved."""
        from update_logic import update_weapons
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        # Park the player so handle is at a known location.
        gv.player.center_x = 500.0
        gv.player.center_y = 600.0
        gv.player.heading = 0.0
        update_weapons(gv, 1 / 60, fire=True)   # spawn + start swing
        b = gv._active_blade
        handle_at_start = b.handle_pos
        # Tick across the swing without moving the player.
        for _ in range(8):
            update_weapons(gv, 1 / 60, fire=False)
            assert b.handle_pos == pytest.approx(handle_at_start), (
                "handle moved during the swing animation — the "
                "pivot is wandering, not staying put")

    def test_sprite_center_moves_during_swing(self):
        """Sanity check on the inverse: the sprite's centre DOES
        move during the swing animation (it traces a small arc
        as the tip swings).  If this stayed put we'd be back to
        rotating around the middle."""
        from update_logic import update_weapons
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        update_weapons(gv, 1 / 60, fire=True)
        b = gv._active_blade
        center_at_start = (b.center_x, b.center_y)
        # Tick a couple of frames into the swing so the rotation
        # has moved the sprite centre away from its starting pose.
        for _ in range(4):
            update_weapons(gv, 1 / 60, fire=False)
        assert ((b.center_x, b.center_y) != pytest.approx(
            center_at_start)), (
            "sprite centre stayed put — pivot-from-handle math "
            "isn't running")


class TestBladeReachConstants:
    def test_base_reach_is_80_px(self):
        from constants import MELEE_HIT_RADIUS
        assert MELEE_HIT_RADIUS == 80.0

    def test_bastion_reach_is_110_px(self):
        from constants import MELEE_BASTION_HIT_RADIUS
        assert MELEE_BASTION_HIT_RADIUS == 110.0

    def test_tex_angle_offset_defined(self):
        """``MELEE_TEX_ANGLE_OFFSET`` must exist as a float so the
        per-frame angle math in ``MeleeBlade._update_pose`` has a
        defined value to add.  The current lightsabre PNG is drawn
        vertically and needs no compensation, so the offset is
        zero — but a future sword sprite drawn at an angle would
        need this to be set without any other code changes."""
        from constants import MELEE_TEX_ANGLE_OFFSET
        assert isinstance(MELEE_TEX_ANGLE_OFFSET, float)

    def test_swing_arc_is_75_to_minus_75(self):
        """Total swing arc is 150° (from -75° to +75° relative to
        the ship's heading).  Pinned by user spec for the
        lightsabre weapon."""
        from constants import MELEE_SWING_ARC
        assert MELEE_SWING_ARC == 150.0


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
    def test_blade_scale_matches_constant(self):
        """The active blade picks up ``MELEE_SCALE`` from
        constants — pinning the relationship so a scale tweak in
        one place propagates to the rendered sprite without any
        per-callsite override.  Lightsabre PNG is ~440x1812 px;
        at scale 0.052 the rendered tip-to-handle is ≈ 95 px,
        roughly the player-ship height."""
        from update_logic import update_weapons
        from game_view import GameView
        from constants import MELEE_SCALE
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()
        update_weapons(gv, 1 / 60, fire=False)
        assert gv._active_blade.scale_x == pytest.approx(MELEE_SCALE)


# ── Per-faction lightsabre sprite ────────────────────────────────────────


class TestPerFactionMeleeSprite:
    """Each faction gets its own lightsabre PNG.  Verify
    ``load_weapons`` reads ``MELEE_SWORD_PNG_BY_FACTION`` and
    that the texture on the Melee weapon matches the faction's
    expected file."""

    @pytest.mark.parametrize(
        "faction,expected_filename",
        [
            ("Earth",       "Sabers-06.png"),
            ("Colonial",    "Sabers-05.png"),
            ("Heavy World", "Sabers-02.png"),
            ("Ascended",    "Sabers-03.png"),
        ],
    )
    def test_melee_texture_matches_faction(
            self, faction, expected_filename):
        from world_setup import load_weapons
        weapons = load_weapons(gun_count=1, faction=faction)
        melee = next(w for w in weapons if w.name == "Melee")
        # arcade textures expose the file path via ``file_path``
        # (Path object on 3.x).  Just check the filename ends with
        # the expected lightsabre PNG.
        path = str(getattr(melee._texture, "file_path", "") or "")
        assert path.endswith(expected_filename), (
            f"faction {faction!r}: melee texture path "
            f"{path!r} does not end with {expected_filename!r}")

    def test_unknown_faction_falls_back_to_default(self):
        """Unknown / None faction must not crash — falls back to
        ``MELEE_SWORD_PNG`` (the Earth lightsabre)."""
        from world_setup import load_weapons
        from constants import MELEE_SWORD_PNG
        weapons = load_weapons(gun_count=1, faction="NotARealFaction")
        melee = next(w for w in weapons if w.name == "Melee")
        path = str(getattr(melee._texture, "file_path", "") or "")
        assert path == MELEE_SWORD_PNG
