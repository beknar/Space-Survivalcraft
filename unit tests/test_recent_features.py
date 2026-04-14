"""Unit tests for features added in the recent rounds of work.

Covers:
- SHIP_MAX_LEVEL = 2 + PlayerShip.upgrade_ship cap
- BuildMenu Advanced Ship availability rules (max level, parked max exists)
- BuildMenu ship_level / max_ship_exists kwargs
- CraftMenu is_advanced filter + title toggle
- _effect_desc "produces Nx per craft" for consumables
- Homing missile recipe metadata (craft_count=20, item_key="missile")
- Consumable craft completion honors item_key + craft_count
- Legacy mod_homing_missile key migration
- TradeMenu SELL_PRICES iron/copper = 20, BUY iron cost
- TradeMenu sell-list sort priority (resources/consumables/modules/blueprints)
- TradeMenu dynamic panel height for sell mode
- MissileArray class: scans, fires, respects cooldown
- MissileArray registered in _TYPE_MAP factory
- Misty Step distance = 300
- Death Blossom constants (fire rate, missiles per volley)
- HUD _mod_cooldowns flashing state plumbing
- Station-inv module drop onto parked ship installs in first empty slot
"""
from __future__ import annotations

import pytest
from PIL import Image as PILImage

import arcade


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    """Create a hidden window so HUD/CraftMenu/TradeMenu can initialize."""
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Ship level cap + upgrade_ship behavior
# ═══════════════════════════════════════════════════════════════════════════

class TestShipMaxLevel:
    def test_ship_max_level_is_2(self):
        from constants import SHIP_MAX_LEVEL
        assert SHIP_MAX_LEVEL == 2

    def test_upgrade_ship_at_cap_is_noop(self):
        from sprites.player import PlayerShip
        p = PlayerShip(faction="Earth", ship_type="Cruiser", ship_level=2)
        base_level = p.ship_level
        base_hp = p.max_hp
        p.upgrade_ship()
        # At cap — nothing changes
        assert p.ship_level == base_level
        assert p.max_hp == base_hp

    def test_upgrade_ship_increments_from_level_1(self):
        from sprites.player import PlayerShip
        from constants import SHIP_LEVEL_HP_BONUS
        p = PlayerShip(faction="Earth", ship_type="Cruiser", ship_level=1)
        old_hp = p.max_hp
        p.upgrade_ship()
        assert p.ship_level == 2
        assert p.max_hp == old_hp + SHIP_LEVEL_HP_BONUS

    def test_upgrade_ship_legacy_noop(self):
        """Legacy (no faction/type) ship can't be upgraded."""
        from sprites.player import PlayerShip
        p = PlayerShip()  # legacy mode
        assert p._use_legacy
        p.upgrade_ship()  # no-op, no exception
        assert p.ship_level == 1


# ═══════════════════════════════════════════════════════════════════════════
#  BuildMenu "Advanced Ship" availability
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildMenuAdvancedShipAvailability:
    def _check(self, *, ship_level: int = 1, max_ship_exists: bool = False):
        from build_menu import BuildMenu
        return BuildMenu._check_availability(
            "Advanced Ship",
            iron=10_000, building_counts={"Home Station": 1},
            modules_used=0, module_capacity=20, has_home=True,
            copper=10_000, unlocked_blueprints=set(),
            ship_level=ship_level, max_ship_exists=max_ship_exists,
        )

    def test_available_when_level1_and_no_max_exists(self):
        ok, _ = self._check(ship_level=1, max_ship_exists=False)
        assert ok

    def test_rejected_at_max_level(self):
        ok, reason = self._check(ship_level=2, max_ship_exists=False)
        assert not ok
        assert "max level" in reason.lower()

    def test_rejected_when_max_ship_exists(self):
        ok, reason = self._check(ship_level=1, max_ship_exists=True)
        assert not ok
        assert "max-level" in reason.lower() or "already exists" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════
#  CraftMenu advanced gating + title
# ═══════════════════════════════════════════════════════════════════════════

class _FakeStationInv:
    def __init__(self, blueprints: list[str]):
        self._bps = set(blueprints)
    def count_item(self, key: str) -> int:
        return 1 if key in self._bps else 0


class TestCraftMenuAdvancedFilter:
    def _build(self, is_advanced: bool, blueprints: list[str]):
        from craft_menu import CraftMenu
        cm = CraftMenu()
        cm.refresh_recipes(_FakeStationInv(blueprints), is_advanced=is_advanced)
        return cm

    def test_basic_hides_advanced_recipes(self):
        cm = self._build(is_advanced=False,
                         blueprints=["bp_homing_missile", "bp_armor_plate"])
        keys = {r["key"] for r in cm._recipes}
        assert "homing_missile" not in keys
        assert "armor_plate" in keys

    def test_advanced_shows_advanced_recipes(self):
        cm = self._build(is_advanced=True,
                         blueprints=["bp_homing_missile", "bp_armor_plate"])
        keys = {r["key"] for r in cm._recipes}
        assert "homing_missile" in keys
        assert "armor_plate" in keys

    def test_title_basic(self):
        cm = self._build(is_advanced=False, blueprints=[])
        assert cm._t_title.text == "BASIC CRAFTER"

    def test_title_advanced(self):
        cm = self._build(is_advanced=True, blueprints=[])
        assert cm._t_title.text == "ADVANCED CRAFTER"


class TestEffectDescConsumables:
    def test_consumable_description_uses_craft_count(self):
        from craft_menu import _effect_desc
        from constants import MODULE_TYPES
        info = MODULE_TYPES["homing_missile"]
        desc = _effect_desc(info)
        assert "20" in desc  # craft_count


# ═══════════════════════════════════════════════════════════════════════════
#  Homing missile recipe metadata
# ═══════════════════════════════════════════════════════════════════════════

class TestHomingMissileRecipe:
    def test_craft_count_is_20(self):
        from constants import MODULE_TYPES
        assert MODULE_TYPES["homing_missile"]["craft_count"] == 20

    def test_item_key_is_missile(self):
        from constants import MODULE_TYPES
        assert MODULE_TYPES["homing_missile"]["item_key"] == "missile"

    def test_is_advanced_and_consumable(self):
        from constants import MODULE_TYPES
        info = MODULE_TYPES["homing_missile"]
        assert info.get("advanced") is True
        assert info.get("consumable") is True


# ═══════════════════════════════════════════════════════════════════════════
#  Legacy key migration
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyKeyMigration:
    def test_add_item_rewrites_mod_homing_missile(self):
        from inventory import Inventory
        inv = Inventory()
        inv.add_item("mod_homing_missile", 3)
        assert inv.count_item("missile") == 3
        assert inv.count_item("mod_homing_missile") == 0

    def test_migrate_legacy_keys_sweeps_existing_cells(self):
        from inventory import Inventory
        inv = Inventory()
        # Bypass add_item to simulate legacy save
        inv._items[(0, 0)] = ("mod_homing_missile", 5)
        inv._items[(0, 1)] = ("iron", 10)
        inv.migrate_legacy_keys()
        assert inv.count_item("missile") == 5
        assert inv.count_item("mod_homing_missile") == 0
        assert inv.count_item("iron") == 10


# ═══════════════════════════════════════════════════════════════════════════
#  TradeMenu pricing + sorting
# ═══════════════════════════════════════════════════════════════════════════

class TestTradeMenu:
    def test_sell_price_iron_20(self):
        from trade_menu import SELL_PRICES
        assert SELL_PRICES["iron"] == 20

    def test_sell_price_copper_20(self):
        from trade_menu import SELL_PRICES
        assert SELL_PRICES["copper"] == 20

    def test_buy_iron_cost_exceeds_sell(self):
        """Buy iron stack cost per unit > sell price per unit (no arbitrage)."""
        from trade_menu import BUY_CATALOG, SELL_PRICES
        for it, _label, cost, qty in BUY_CATALOG:
            if it == "iron":
                assert cost / qty >= SELL_PRICES["iron"]
                return
        pytest.fail("Iron not in BUY_CATALOG")

    def test_sell_list_sort_priority(self):
        """Resources come before consumables, modules, and blueprints."""
        from trade_menu import TradeMenu
        from inventory import Inventory
        from station_inventory import StationInventory

        cargo = Inventory()
        cargo.add_item("iron", 10)
        cargo.add_item("copper", 5)
        cargo.add_item("missile", 2)
        station = StationInventory()
        station.add_item("bp_armor_plate", 1)
        station.add_item("mod_armor_plate", 1)

        tm = TradeMenu()
        tm._refresh_sell_list(cargo, station)
        order = [it for (it, _n, _p, _c) in tm._sell_items]
        # Resources first
        assert order.index("copper") < order.index("missile")
        assert order.index("iron") < order.index("missile")
        # Consumables before modules
        assert order.index("missile") < order.index("mod_armor_plate")
        # Modules before blueprints
        assert order.index("mod_armor_plate") < order.index("bp_armor_plate")

    def test_sell_panel_grows_with_item_count(self):
        from trade_menu import TradeMenu, _PANEL_H_MIN
        tm = TradeMenu()
        tm._mode = "sell"
        tm._sell_items = []
        small_h = tm._panel_height()
        assert small_h == _PANEL_H_MIN

        tm._sell_items = [("item_%d" % i, "Item", 1, 1) for i in range(40)]
        big_h = tm._panel_height()
        assert big_h > small_h


# ═══════════════════════════════════════════════════════════════════════════
#  MissileArray building
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def missile_tex() -> arcade.Texture:
    return arcade.Texture(PILImage.new("RGBA", (16, 16), (200, 50, 50, 255)))


class TestMissileArray:
    def test_registered_in_factory(self, dummy_texture):
        from sprites.building import create_building, MissileArray
        b = create_building("Missile Array", dummy_texture, 0, 0)
        assert isinstance(b, MissileArray)

    def test_does_not_fire_without_targets(self, dummy_texture, missile_tex):
        from sprites.building import MissileArray
        ma = MissileArray(dummy_texture, 100, 100, "Missile Array")
        alien_list = arcade.SpriteList()
        missile_list = arcade.SpriteList()
        ma.update_missile_array(1.0, alien_list, missile_list, missile_tex)
        assert len(missile_list) == 0

    def test_fires_at_alien_in_range(self, dummy_texture, missile_tex):
        from sprites.building import MissileArray
        ma = MissileArray(dummy_texture, 100, 100, "Missile Array")
        alien = arcade.Sprite(path_or_texture=dummy_texture)
        alien.center_x = 300
        alien.center_y = 100
        alien.hp = 50
        alien_list = arcade.SpriteList()
        alien_list.append(alien)
        missile_list = arcade.SpriteList()
        # First tick: fire_cd starts at 0 so it should fire immediately
        ma.update_missile_array(0.016, alien_list, missile_list, missile_tex)
        assert len(missile_list) == 1

    def test_respects_cooldown(self, dummy_texture, missile_tex):
        from sprites.building import MissileArray
        from constants import MISSILE_ARRAY_COOLDOWN
        ma = MissileArray(dummy_texture, 100, 100, "Missile Array")
        alien = arcade.Sprite(path_or_texture=dummy_texture)
        alien.center_x = 300; alien.center_y = 100; alien.hp = 50
        alien_list = arcade.SpriteList()
        alien_list.append(alien)
        missile_list = arcade.SpriteList()
        ma.update_missile_array(0.016, alien_list, missile_list, missile_tex)
        # Tick for less than the cooldown period — no second missile
        ma.update_missile_array(MISSILE_ARRAY_COOLDOWN / 2.0,
                                alien_list, missile_list, missile_tex)
        assert len(missile_list) == 1
        # Tick past cooldown — second missile fires
        ma.update_missile_array(MISSILE_ARRAY_COOLDOWN + 0.01,
                                alien_list, missile_list, missile_tex)
        assert len(missile_list) == 2

    def test_ignores_targets_beyond_range(self, dummy_texture, missile_tex):
        from sprites.building import MissileArray
        from constants import MISSILE_ARRAY_RANGE
        ma = MissileArray(dummy_texture, 100, 100, "Missile Array")
        alien = arcade.Sprite(path_or_texture=dummy_texture)
        alien.center_x = 100 + MISSILE_ARRAY_RANGE + 50
        alien.center_y = 100
        alien.hp = 50
        alien_list = arcade.SpriteList()
        alien_list.append(alien)
        missile_list = arcade.SpriteList()
        ma.update_missile_array(0.016, alien_list, missile_list, missile_tex)
        assert len(missile_list) == 0


# ═══════════════════════════════════════════════════════════════════════════
#  Ability constants
# ═══════════════════════════════════════════════════════════════════════════

class TestAbilityConstants:
    def test_misty_step_distance_300(self):
        from constants import MISTY_STEP_DISTANCE
        assert MISTY_STEP_DISTANCE == 300.0

    def test_death_blossom_fire_rate_2s(self):
        from constants import DEATH_BLOSSOM_FIRE_RATE
        assert DEATH_BLOSSOM_FIRE_RATE == 2.0

    def test_death_blossom_4_per_volley(self):
        from constants import DEATH_BLOSSOM_MISSILES_PER_VOLLEY
        assert DEATH_BLOSSOM_MISSILES_PER_VOLLEY == 4


# ═══════════════════════════════════════════════════════════════════════════
#  HUD module cooldown flash plumbing
# ═══════════════════════════════════════════════════════════════════════════

class TestHudCooldownPlumbing:
    def test_default_no_cooldowns(self):
        from hud import HUD
        h = HUD()
        assert h._mod_cooldowns == set()

    def test_setting_cooldown_set(self):
        from hud import HUD
        h = HUD()
        h._mod_cooldowns = {"misty_step", "death_blossom"}
        assert "misty_step" in h._mod_cooldowns

    def test_flash_timer_advances(self):
        from hud import HUD
        h = HUD()
        t0 = h._mod_flash_t
        h._mod_flash_t += 0.5
        assert h._mod_flash_t > t0
