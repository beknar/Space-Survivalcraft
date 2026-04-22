"""Zone-gated drops, recipes, and build-menu rows.

Nebula-gated blueprints (rear_turret, homing_missile, misty_step,
force_wall, death_blossom, ai_pilot, advanced_crafter) and the six
Nebula-gated buildings must not appear in Zone 1.  The Quantum Wave
Integrator is Nebula-only (not even in the post-Nebula warp zones).
"""
from __future__ import annotations

import types

import arcade
import pytest

from constants import (
    MODULE_TYPES, ZONE_GATED_MODULES, ZONE_GATED_BUILDINGS,
    ZONE2_ONLY_BUILDINGS,
)
from zones import ZoneID
from build_menu import BuildMenu, _visible_menu_order, _MENU_ORDER


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    """Hidden window so ``BuildMenu`` / ``CraftMenu`` can create their
    ``arcade.Text`` labels (pyglet defers layout to first access, which
    requires a live GL window)."""
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


# ── Module-level constant sanity ──────────────────────────────────────────

class TestGatedSetsSanity:
    def test_all_gated_module_keys_exist(self):
        for key in ZONE_GATED_MODULES:
            assert key in MODULE_TYPES, (
                f"{key} listed as gated but missing from MODULE_TYPES"
            )

    def test_gated_modules_match_user_spec(self):
        assert ZONE_GATED_MODULES == frozenset({
            "rear_turret", "homing_missile", "misty_step",
            "force_wall", "death_blossom", "ai_pilot",
            "advanced_crafter",
        })

    def test_gated_buildings_match_user_spec(self):
        assert ZONE_GATED_BUILDINGS == frozenset({
            "Advanced Crafter", "Fission Generator",
            "Basic Ship", "Advanced Ship",
            "Shield Generator", "Missile Array",
        })

    def test_qwi_is_zone2_only(self):
        assert ZONE2_ONLY_BUILDINGS == frozenset({"Quantum Wave Integrator"})


# ── Visible menu order by zone ────────────────────────────────────────────

class TestVisibleMenuOrder:
    def _names(self, zone_id) -> list[str]:
        return [name for _, name in _visible_menu_order(zone_id)]

    def test_none_returns_full_list(self):
        assert self._names(None) == list(_MENU_ORDER)

    def test_main_hides_gated_and_qwi(self):
        names = self._names(ZoneID.MAIN)
        for b in ZONE_GATED_BUILDINGS:
            assert b not in names, f"{b} should be hidden in Zone 1"
        for b in ZONE2_ONLY_BUILDINGS:
            assert b not in names, f"{b} should be hidden in Zone 1"
        # The early-game core is still there.
        assert "Home Station" in names
        assert "Basic Crafter" in names
        assert "Turret 1" in names

    def test_nebula_shows_everything(self):
        names = self._names(ZoneID.ZONE2)
        assert names == list(_MENU_ORDER)

    def test_warp_zones_show_gated_but_hide_qwi(self):
        for wz in (ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
                   ZoneID.WARP_GAS, ZoneID.WARP_ENEMY):
            names = self._names(wz)
            for b in ZONE_GATED_BUILDINGS:
                assert b in names, f"{b} must be buildable in {wz}"
            assert "Quantum Wave Integrator" not in names, (
                f"QWI must be hidden in {wz} — Nebula-only"
            )

    def test_orig_idx_is_position_in_full_menu(self):
        for orig_idx, name in _visible_menu_order(ZoneID.MAIN):
            assert _MENU_ORDER[orig_idx] == name


# ── Build menu state on zone change ───────────────────────────────────────

class TestBuildMenuZoneSync:
    def test_sync_zone_updates_visible_count(self):
        bm = BuildMenu()
        bm._sync_zone(ZoneID.MAIN)
        count_main = bm._last_visible_count
        bm._sync_zone(ZoneID.ZONE2)
        count_nebula = bm._last_visible_count
        assert count_nebula > count_main
        assert count_nebula == len(_MENU_ORDER)

    def test_sync_zone_resets_hover_on_change(self):
        bm = BuildMenu()
        bm._sync_zone(ZoneID.ZONE2)
        bm._hover_idx = 5
        bm._hover_destroy = True
        bm._sync_zone(ZoneID.MAIN)
        assert bm._hover_idx == -1
        assert bm._hover_destroy is False

    def test_sync_zone_keeps_hover_when_zone_unchanged(self):
        bm = BuildMenu()
        bm._sync_zone(ZoneID.ZONE2)
        bm._hover_idx = 3
        bm._sync_zone(ZoneID.ZONE2)
        assert bm._hover_idx == 3

    def test_content_h_shrinks_in_main(self):
        bm = BuildMenu()
        bm._sync_zone(ZoneID.ZONE2)
        h_nebula = bm._content_h
        bm._sync_zone(ZoneID.MAIN)
        h_main = bm._content_h
        assert h_main < h_nebula


# ── Blueprint drop pool ───────────────────────────────────────────────────

class _StubPickupList(list):
    def append(self, bp):  # keep list semantics
        super().append(bp)


def _real_texture():
    """Produce a minimal real ``arcade.Texture`` — ``BlueprintPickup``
    reads ``.width`` / ``.height`` on construction, so a sentinel object
    isn't enough."""
    from PIL import Image as PILImage
    return arcade.Texture(PILImage.new("RGBA", (32, 32), (0, 0, 0, 0)))


class _StubGameView:
    """Minimal stub — spawn_blueprint_pickup only touches these fields."""
    def __init__(self, zone_id):
        self._zone = types.SimpleNamespace(zone_id=zone_id)
        self._blueprint_drop_tex = {}
        self._blueprint_tex = _real_texture()
        self.blueprint_pickup_list = _StubPickupList()


class TestBlueprintDropPool:
    def test_main_zone_never_drops_gated(self):
        from combat_helpers import spawn_blueprint_pickup
        gv = _StubGameView(ZoneID.MAIN)
        for _ in range(300):
            spawn_blueprint_pickup(gv, 0, 0)
        types_dropped = {bp.module_type for bp in gv.blueprint_pickup_list}
        assert types_dropped.isdisjoint(ZONE_GATED_MODULES)
        # Non-gated keys should still drop.
        assert types_dropped, "Expected at least some drops"

    def test_nebula_can_drop_gated(self):
        from combat_helpers import spawn_blueprint_pickup
        gv = _StubGameView(ZoneID.ZONE2)
        for _ in range(300):
            spawn_blueprint_pickup(gv, 0, 0)
        types_dropped = {bp.module_type for bp in gv.blueprint_pickup_list}
        # Over 300 samples every gated key should land at least once.
        for key in ZONE_GATED_MODULES:
            assert key in types_dropped, (
                f"{key} should drop in Nebula but never did in 300 rolls"
            )

    def test_warp_zones_can_drop_gated(self):
        from combat_helpers import spawn_blueprint_pickup
        gv = _StubGameView(ZoneID.WARP_GAS)
        for _ in range(300):
            spawn_blueprint_pickup(gv, 0, 0)
        types_dropped = {bp.module_type for bp in gv.blueprint_pickup_list}
        # At least one gated key within 300 rolls.
        assert types_dropped & ZONE_GATED_MODULES


# ── Craft menu recipe visibility ──────────────────────────────────────────

class _FakeStationInv:
    def __init__(self, unlocked_keys):
        self._unlocked_keys = set(unlocked_keys)

    def count_item(self, key):
        if key.startswith("bp_") and key[3:] in self._unlocked_keys:
            return 1
        return 0


class TestCraftMenuZoneGate:
    def test_gated_recipe_hidden_in_main(self):
        from craft_menu import CraftMenu
        cm = CraftMenu()
        inv = _FakeStationInv({"homing_missile", "armor_plate"})
        cm.refresh_recipes(inv, is_advanced=True, zone_id=ZoneID.MAIN)
        keys = [r["key"] for r in cm._recipes]
        assert "homing_missile" not in keys
        assert "armor_plate" in keys

    def test_gated_recipe_visible_in_nebula(self):
        from craft_menu import CraftMenu
        cm = CraftMenu()
        inv = _FakeStationInv({"homing_missile", "armor_plate"})
        cm.refresh_recipes(inv, is_advanced=True, zone_id=ZoneID.ZONE2)
        keys = [r["key"] for r in cm._recipes]
        assert "homing_missile" in keys
        assert "armor_plate" in keys

    def test_zone_id_none_preserves_legacy_behaviour(self):
        """Callers that don't pass ``zone_id`` must see every unlocked
        recipe — a past drop in Nebula shouldn't vanish in tests."""
        from craft_menu import CraftMenu
        cm = CraftMenu()
        inv = _FakeStationInv({"homing_missile"})
        cm.refresh_recipes(inv, is_advanced=True)
        keys = [r["key"] for r in cm._recipes]
        assert "homing_missile" in keys

    def test_unlock_persistence_across_zones(self):
        """A blueprint picked up in Nebula stays unlocked even after
        the player warps to Zone 1 — it just doesn't show in the
        recipe list while they're there."""
        from craft_menu import CraftMenu
        cm = CraftMenu()
        # Unlock in Nebula.
        nebula_inv = _FakeStationInv({"homing_missile"})
        cm.refresh_recipes(nebula_inv, is_advanced=True, zone_id=ZoneID.ZONE2)
        assert "homing_missile" in cm._unlocked
        # Warp to Zone 1 — station inv no longer has the blueprint item
        # (e.g. it was crafted + consumed) but the unlock sticks.
        empty_inv = _FakeStationInv(set())
        cm.refresh_recipes(empty_inv, is_advanced=True, zone_id=ZoneID.MAIN)
        assert "homing_missile" in cm._unlocked
        keys = [r["key"] for r in cm._recipes]
        assert "homing_missile" not in keys  # hidden in Zone 1
        # Warp back — it returns.
        cm.refresh_recipes(empty_inv, is_advanced=True, zone_id=ZoneID.ZONE2)
        keys = [r["key"] for r in cm._recipes]
        assert "homing_missile" in keys


# ── on_mouse_press gating via zone ────────────────────────────────────────

class TestBuildMenuClickGating:
    """Defence in depth — even if a hidden row were somehow clicked at
    its old on-screen position, ``on_mouse_press`` iterates the visible
    order and can't route that click to a filtered-out building."""

    def test_hidden_rows_not_iterated(self):
        bm = BuildMenu()
        bm._sync_zone(ZoneID.MAIN)
        names = [n for _, n in bm._visible_order()]
        for b in ZONE_GATED_BUILDINGS:
            assert b not in names
        assert "Quantum Wave Integrator" not in names
