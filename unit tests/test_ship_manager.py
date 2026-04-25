"""Tests for ship_manager helpers.

count_l1_ships is already covered in test_basic_ship_build.py.  This
file targets the rest of the surface: cost-validation early-exits in
_upgrade_ship, _resize_module_slots preserving entries, _place_basic_ship
appending a parked ship without touching the player, and the
_deduct_ship_cost shim.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image as PILImage

import arcade

from constants import (
    BUILDING_TYPES, MODULE_SLOT_COUNT, SHIP_LEVEL_MODULE_BONUS,
    SHIP_MAX_LEVEL,
)


# ── Stubs ──────────────────────────────────────────────────────────────────

class _StubInventory:
    def __init__(self, iron: int = 0, copper: int = 0):
        self._items: dict = {}
        self.total_iron = iron
        self._copper = copper

    def count_item(self, name: str) -> int:
        return self._copper if name == "copper" else 0

    def remove_item(self, name: str, qty: int) -> None:
        if name == "iron":
            self.total_iron = max(0, self.total_iron - qty)
        elif name == "copper":
            self._copper = max(0, self._copper - qty)

    def _mark_dirty(self):
        pass


class _StubHud:
    def __init__(self, n: int = MODULE_SLOT_COUNT):
        self._mod_slots: list = [None] * n
        self._count = n

    def set_module_count(self, n: int) -> None:
        self._count = n


class _StubPlayer:
    def __init__(self):
        self.applied_modules = None
        self.upgraded = 0

    def apply_modules(self, slots):
        self.applied_modules = list(slots)

    def upgrade_ship(self):
        self.upgraded += 1


def _make_gv(*, iron=10_000, copper=10_000, ship_level=1,
             module_slots=None) -> SimpleNamespace:
    return SimpleNamespace(
        inventory=_StubInventory(iron, copper),
        _station_inv=_StubInventory(0, 0),
        _ship_level=ship_level,
        _char_level=1,
        _ability_meter=0.0,
        _ability_meter_max=100.0,
        _module_slots=module_slots or [None] * MODULE_SLOT_COUNT,
        _flash_msg="",
        _flash_timer=0.0,
        _hud=_StubHud(MODULE_SLOT_COUNT),
        _faction="Earth",
        _ship_type="Cruiser",
        _parked_ships=[],
        player=_StubPlayer(),
    )


# ── _deduct_ship_cost ──────────────────────────────────────────────────────

class TestDeductShipCost:
    def test_deducts_from_ship_inventory_first(self):
        from ship_manager import _deduct_ship_cost
        gv = _make_gv(iron=500, copper=200)
        gv._station_inv = _StubInventory(iron=10_000, copper=10_000)
        _deduct_ship_cost(gv, 300, 100)
        assert gv.inventory.total_iron == 200
        assert gv._station_inv.total_iron == 10_000  # untouched

    def test_falls_back_to_station_when_ship_short(self):
        from ship_manager import _deduct_ship_cost
        gv = _make_gv(iron=100, copper=50)
        gv._station_inv = _StubInventory(iron=1000, copper=500)
        _deduct_ship_cost(gv, 400, 200)
        assert gv.inventory.total_iron == 0
        assert gv._station_inv.total_iron == 700  # 1000 - (400-100)
        assert gv._station_inv._copper == 350     # 500 - (200-50)


# ── _resize_module_slots ───────────────────────────────────────────────────

class TestResizeModuleSlots:
    def test_grow_preserves_existing_entries(self):
        from ship_manager import _resize_module_slots
        gv = _make_gv()
        gv._module_slots = ["mod_a", "mod_b", None, None]
        _resize_module_slots(gv, 6)
        assert len(gv._module_slots) == 6
        assert gv._module_slots[:2] == ["mod_a", "mod_b"]
        assert gv._module_slots[2:] == [None] * 4

    def test_shrink_drops_trailing_entries(self):
        from ship_manager import _resize_module_slots
        gv = _make_gv()
        gv._module_slots = ["a", "b", "c", "d"]
        _resize_module_slots(gv, 2)
        assert gv._module_slots == ["a", "b"]

    def test_calls_player_apply_modules(self):
        from ship_manager import _resize_module_slots
        gv = _make_gv()
        gv._module_slots = ["x", None]
        _resize_module_slots(gv, 4)
        assert gv.player.applied_modules == ["x", None, None, None]

    def test_updates_hud_count_and_mirror(self):
        from ship_manager import _resize_module_slots
        gv = _make_gv()
        _resize_module_slots(gv, 8)
        assert gv._hud._count == 8
        assert gv._hud._mod_slots == gv._module_slots


# ── _upgrade_ship cost-validation early exits ──────────────────────────────

class TestUpgradeShipGuards:
    def test_max_level_guard(self):
        from ship_manager import _upgrade_ship
        gv = _make_gv(ship_level=SHIP_MAX_LEVEL)
        _upgrade_ship(gv)
        assert "maximum" in gv._flash_msg
        assert gv._ship_level == SHIP_MAX_LEVEL  # unchanged
        assert gv.player.upgraded == 0

    def test_insufficient_iron_blocks_upgrade(self):
        from ship_manager import _upgrade_ship
        gv = _make_gv(iron=10, copper=10_000, ship_level=1)
        _upgrade_ship(gv)
        assert "iron" in gv._flash_msg.lower()
        assert gv._ship_level == 1
        assert gv.player.upgraded == 0

    def test_insufficient_copper_blocks_upgrade(self):
        from ship_manager import _upgrade_ship
        gv = _make_gv(iron=10_000, copper=0, ship_level=1)
        _upgrade_ship(gv)
        assert "copper" in gv._flash_msg.lower()
        assert gv._ship_level == 1
        assert gv.player.upgraded == 0


# ── _upgrade_ship full success path ────────────────────────────────────────

class TestUpgradeShipSuccess:
    def test_upgrade_increments_level_and_expands_slots(self):
        from ship_manager import _upgrade_ship
        gv = _make_gv(iron=10_000, copper=10_000, ship_level=1)
        _upgrade_ship(gv)
        assert gv._ship_level == 2
        assert gv.player.upgraded == 1
        # New slot count = base + (level-1) * bonus
        assert len(gv._module_slots) == (
            MODULE_SLOT_COUNT + 1 * SHIP_LEVEL_MODULE_BONUS)

    def test_upgrade_deducts_iron_and_copper(self):
        from ship_manager import _upgrade_ship
        from character_data import build_cost_multiplier
        from settings import audio
        gv = _make_gv(iron=10_000, copper=10_000)
        stats = BUILDING_TYPES["Advanced Ship"]
        mult = build_cost_multiplier(audio.character_name, gv._char_level)
        expected_iron = int(stats["cost"] * mult)
        expected_copper = int(stats.get("cost_copper", 0) * mult)

        _upgrade_ship(gv)
        assert gv.inventory.total_iron == 10_000 - expected_iron
        assert gv.inventory._copper == 10_000 - expected_copper

    def test_upgrade_flash_msg_set(self):
        from ship_manager import _upgrade_ship
        gv = _make_gv(iron=10_000, copper=10_000)
        _upgrade_ship(gv)
        assert "level 2" in gv._flash_msg


# ── _place_basic_ship ──────────────────────────────────────────────────────

class TestPlaceBasicShip:
    def test_appends_parked_ship(self, monkeypatch):
        # Patch ParkedShip's texture extractor so no PNG load is attempted
        from sprites.player import PlayerShip
        img = PILImage.new("RGBA", (32, 32), (0, 200, 255, 255))
        monkeypatch.setattr(
            PlayerShip, "_extract_ship_texture",
            staticmethod(lambda *a, **kw: arcade.Texture(img)))

        from ship_manager import _place_basic_ship
        gv = _make_gv(iron=10_000, copper=10_000)
        _place_basic_ship(gv, 1234.0, 5678.0)
        assert len(gv._parked_ships) == 1
        ps = gv._parked_ships[0]
        assert ps.center_x == 1234.0
        assert ps.center_y == 5678.0
        assert ps.ship_level == 1

    def test_deducts_basic_ship_cost(self, monkeypatch):
        from sprites.player import PlayerShip
        img = PILImage.new("RGBA", (32, 32), (0, 200, 255, 255))
        monkeypatch.setattr(
            PlayerShip, "_extract_ship_texture",
            staticmethod(lambda *a, **kw: arcade.Texture(img)))

        from ship_manager import _place_basic_ship
        from character_data import build_cost_multiplier
        from settings import audio
        gv = _make_gv(iron=10_000, copper=10_000)
        stats = BUILDING_TYPES["Basic Ship"]
        mult = build_cost_multiplier(audio.character_name, gv._char_level)
        iron_cost = int(stats["cost"] * mult)
        copper_cost = int(stats.get("cost_copper", 0) * mult)

        _place_basic_ship(gv, 0.0, 0.0)
        assert gv.inventory.total_iron == 10_000 - iron_cost
        assert gv.inventory._copper == 10_000 - copper_cost

    def test_does_not_modify_player(self, monkeypatch):
        from sprites.player import PlayerShip
        img = PILImage.new("RGBA", (32, 32), (0, 200, 255, 255))
        monkeypatch.setattr(
            PlayerShip, "_extract_ship_texture",
            staticmethod(lambda *a, **kw: arcade.Texture(img)))

        from ship_manager import _place_basic_ship
        gv = _make_gv(iron=10_000, copper=10_000, ship_level=2)
        _place_basic_ship(gv, 100.0, 100.0)
        assert gv._ship_level == 2
        assert gv.player.upgraded == 0


# ── _place_new_ship ────────────────────────────────────────────────────────

class TestPlaceNewShip:
    def test_parks_old_ship_at_player_position_and_teleports(
            self, monkeypatch):
        from sprites.player import PlayerShip
        img = PILImage.new("RGBA", (32, 32), (0, 200, 255, 255))
        monkeypatch.setattr(
            PlayerShip, "_extract_ship_texture",
            staticmethod(lambda *a, **kw: arcade.Texture(img)))

        from ship_manager import _place_new_ship
        gv = _make_gv(iron=10_000, copper=10_000, ship_level=1)
        # Give the player a position the parked ship should inherit
        gv.player.center_x = 200.0
        gv.player.center_y = 300.0
        gv.player.heading = 0.0
        gv.player.hp = 100
        gv.player.max_hp = 100
        gv.player.shields = 50
        gv.player.max_shields = 50
        gv.player.vel_x = 99.0
        gv.player.vel_y = 99.0

        _place_new_ship(gv, 1500.0, 1600.0)

        assert len(gv._parked_ships) == 1
        parked = gv._parked_ships[0]
        # Old ship now parked at the original player position
        assert parked.center_x == 200.0
        assert parked.center_y == 300.0
        assert parked.ship_level == 1
        # Player teleported to placement spot, velocity zeroed
        assert gv.player.center_x == 1500.0
        assert gv.player.center_y == 1600.0
        assert gv.player.vel_x == 0.0
        assert gv.player.vel_y == 0.0
        # Level incremented + module slots expanded
        assert gv._ship_level == 2
        assert gv.player.upgraded == 1
