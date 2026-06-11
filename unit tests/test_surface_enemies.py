"""Fast unit tests for Planets Phase 3 — on-foot surface enemies.

Covers the spec table, the cached asset loader, SurfaceEnemy combat
(armor-reduced damage, the four attack behaviours, pursue movement,
death/reap), and the boomerang ThrownAxe.  Zone-level spawn budgets +
combat are exercised by the integration suite.
"""
from __future__ import annotations

import arcade

import specs
from specs import (
    SURFACE_ENEMIES, SURFACE_TIER_ROSTER, SURFACE_TIER_MAX,
    ICE_CROWN, ORANGE_HELMET, ICE_CAT, HORNED_BITER, HORNED_BREATHER,
)
from sprites.surface_enemy import (
    load_surface_enemy_assets, SurfaceEnemy, ThrownAxe,
)


def _enemy(spec, x=1000.0, y=1000.0):
    assets = load_surface_enemy_assets()
    return SurfaceEnemy(spec, assets[spec.key], x, y, 4000.0, 4000.0)


# ── Specs + roster ──────────────────────────────────────────────────────────

class TestSpecs:
    def test_eight_enemies(self):
        assert len(SURFACE_ENEMIES) == 8

    def test_tier_budgets(self):
        assert SURFACE_TIER_MAX == {"A": 10, "B": 7, "C": 4}

    def test_roster_membership(self):
        assert [s.key for s in SURFACE_TIER_ROSTER["A"]] == [
            "ice_crown", "orange_helmet", "ice_cat", "teal_cat"]
        assert [s.key for s in SURFACE_TIER_ROSTER["B"]] == [
            "horned_helmet", "voodoo"]
        assert [s.key for s in SURFACE_TIER_ROSTER["C"]] == [
            "horned_breather", "horned_biter"]

    def test_attack_kinds(self):
        assert ICE_CROWN.attack_kind == "throw_return"
        assert ORANGE_HELMET.attack_kind == "projectile"
        assert ICE_CAT.attack_kind == "bump"
        assert HORNED_BITER.attack_kind == "melee"

    def test_drop_fields_present_and_scale_with_tier(self):
        for spec in SURFACE_ENEMIES.values():
            assert spec.iron_drop > 0 and spec.xp > 0
        assert HORNED_BITER.iron_drop > ICE_CAT.iron_drop      # C > A
        assert HORNED_BREATHER.xp > ORANGE_HELMET.xp


class TestOnFootMeleeWeapons:
    def test_four_weapons_with_melee_flags(self):
        from world_setup import load_on_foot_weapons
        ws = load_on_foot_weapons()
        assert [w.name for w in ws] == [
            "Basic Laser Rifle", "Portable Mining Beam",
            "Electron Sword", "Electron Pick Axe"]
        # The two melee weapons are flagged so update_weapons skips firing.
        assert getattr(ws[2], "_on_foot_melee", False) is True
        assert getattr(ws[3], "_on_foot_melee", False) is True
        assert getattr(ws[0], "_on_foot_melee", False) is False


# ── Asset loader ────────────────────────────────────────────────────────────

class TestAssets:
    def test_loads_all_eight(self):
        a = load_surface_enemy_assets()
        assert set(a.keys()) == set(SURFACE_ENEMIES.keys())

    def test_frame_sets(self):
        a = load_surface_enemy_assets()
        assert len(a["ice_crown"]["idle"]) == 4
        assert len(a["ice_crown"]["move"]) == 6        # walk
        assert len(a["ice_cat"]["move"]) == 4          # run
        assert a["horned_breather"]["attack"] is not None  # has attack frames
        assert a["ice_crown"]["attack"] is None
        assert a["orange_helmet"]["bullet"] is not None
        assert a["ice_crown"]["axe"] is not None

    def test_loader_is_cached(self):
        assert load_surface_enemy_assets() is load_surface_enemy_assets()


# ── Damage + death ──────────────────────────────────────────────────────────

class TestDamage:
    def test_armor_reduces_damage(self):
        e = _enemy(ORANGE_HELMET)        # hp 40, armor 1
        e.take_damage(10)
        assert e.hp == 40 - 9            # 10 - 1 armor

    def test_armor_never_below_one(self):
        e = _enemy(HORNED_BITER)         # armor 2
        e.take_damage(1)
        assert e.hp == HORNED_BITER.hp - 1

    def test_lethal_damage_starts_dying(self):
        e = _enemy(ICE_CAT)
        e.take_damage(999)
        assert e.state == "dying"
        assert e.dead is False

    def test_dying_reaps_after_linger(self):
        e = _enemy(ICE_CAT)
        e.take_damage(999)
        e.update_enemy(5.0, 1000.0, 1000.0)   # > dead-linger
        assert e.dead is True


# ── Attack behaviours ───────────────────────────────────────────────────────

class TestAttacks:
    def test_projectile_fires_in_range(self):
        e = _enemy(ORANGE_HELMET, 1000.0, 1000.0)
        e._atk_cd = 0.0
        projs, axes, contact = e.update_enemy(1 / 60, 1050.0, 1000.0)  # 50px
        assert len(projs) == 1 and not axes and contact == 0

    def test_throw_return_throws_axe(self):
        e = _enemy(ICE_CROWN, 1000.0, 1000.0)
        e._atk_cd = 0.0
        projs, axes, contact = e.update_enemy(1 / 60, 1060.0, 1000.0)  # 60px
        assert len(axes) == 1 and not projs

    def test_ice_crown_spear_at_close_range(self):
        e = _enemy(ICE_CROWN, 1000.0, 1000.0)
        e._atk_cd = 99.0                 # axe on cooldown; isolate the spear
        e._melee_cd = 0.0
        _, _, contact = e.update_enemy(1 / 60, 1020.0, 1000.0)  # 20px
        assert contact == ICE_CROWN.melee_damage

    def test_bump_contact_damage(self):
        e = _enemy(ICE_CAT, 1000.0, 1000.0)
        e._atk_cd = 0.0
        _, _, contact = e.update_enemy(1 / 60, 1010.0, 1000.0)  # contact
        assert contact == ICE_CAT.damage

    def test_melee_contact_in_range(self):
        e = _enemy(HORNED_BITER, 1000.0, 1000.0)
        e._atk_cd = 0.0
        _, _, contact = e.update_enemy(1 / 60, 1020.0, 1000.0)
        assert contact == HORNED_BITER.damage

    def test_pursues_when_out_of_range(self):
        e = _enemy(HORNED_BREATHER, 1000.0, 1000.0)
        projs, axes, contact = e.update_enemy(0.5, 2000.0, 1000.0)  # far right
        assert e.center_x > 1000.0       # moved toward player
        assert not projs and not axes and contact == 0


# ── ThrownAxe boomerang ─────────────────────────────────────────────────────

class TestThrownAxe:
    def test_out_then_back_then_dead(self):
        e = _enemy(ICE_CROWN, 1000.0, 1000.0)
        axe = ThrownAxe(load_surface_enemy_assets()["ice_crown"]["axe"],
                        e, 1080.0, 1000.0, damage=10)
        assert axe._phase == "out"
        for _ in range(600):             # plenty of frames to fly out + back
            axe.update_axe(1 / 60)
            if axe.dead:
                break
        assert axe.dead is True

    def test_reaches_target_then_returns(self):
        e = _enemy(ICE_CROWN, 1000.0, 1000.0)
        axe = ThrownAxe(load_surface_enemy_assets()["ice_crown"]["axe"],
                        e, 1080.0, 1000.0, damage=10)
        # March outbound until it flips to the return phase.
        for _ in range(120):
            axe.update_axe(1 / 60)
            if axe._phase == "back":
                break
        assert axe._phase == "back"
