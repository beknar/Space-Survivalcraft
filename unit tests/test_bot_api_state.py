"""Unit tests for ``bot_api`` -- focused on the pure state-
extraction helpers (``_player_state``, ``_weapon_state``, ...,
``get_state``) and the intent storage.  No HTTP server is
spun up here -- network behaviour is tested separately in
the integration suite.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot_api


# ── Stub builders ─────────────────────────────────────────────────────────


def _gv(**overrides):
    weapons = overrides.pop("_weapons", [
        SimpleNamespace(name="Basic Laser"),
        SimpleNamespace(name="Mining Beam"),
        SimpleNamespace(name="Melee"),
    ])
    weapon_idx = overrides.pop("_weapon_idx", 0)
    base = dict(
        player=SimpleNamespace(
            center_x=3200.0, center_y=3200.0, heading=45.0,
            vel_x=10.0, vel_y=20.0,
            hp=80, max_hp=100, shields=120, max_shields=150,
        ),
        _weapons=weapons,
        _weapon_idx=weapon_idx,
        _ability_meter=75,
        _ability_meter_max=100,
        _faction="Earth",
        _ship_type="Aegis",
        _ship_level=1,
        _zone=SimpleNamespace(
            zone_id="ZoneID.MAIN", world_width=6400, world_height=6400),
        _boss=None,
        _nebula_boss=None,
        alien_list=[],
        asteroid_list=[],
        building_list=[],
        iron_pickup_list=[],
        blueprint_pickup_list=[],
        inventory=SimpleNamespace(_items={}, _open=False),
        _build_menu_open=False,
        _escape_menu_open=False,
        _player_dead=False,
        _dialogue_open=False,
    )
    base.update(overrides)
    gv = SimpleNamespace(**base)
    gv._active_weapon = weapons[weapon_idx]
    return gv


def _sprite(x, y, **kwargs):
    base = dict(center_x=float(x), center_y=float(y), hp=100)
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── Per-component extractors ──────────────────────────────────────────────


class TestPlayerState:
    def test_full_player_block(self):
        gv = _gv()
        s = bot_api._player_state(gv)
        assert s["x"] == 3200.0
        assert s["y"] == 3200.0
        assert s["heading"] == 45.0
        assert s["vel_x"] == 10.0
        assert s["vel_y"] == 20.0
        assert s["hp"] == 80
        assert s["max_hp"] == 100
        assert s["shields"] == 120
        assert s["max_shields"] == 150
        assert s["faction"] == "Earth"
        assert s["ship_type"] == "Aegis"

    def test_missing_attrs_default_safely(self):
        # Half-built gv -- player is just a stub with no attrs.
        gv = SimpleNamespace(player=SimpleNamespace())
        s = bot_api._player_state(gv)
        # Defaults should be 0 rather than crashing.
        assert s["x"] == 0.0
        assert s["hp"] == 0


class TestWeaponState:
    def test_returns_active_weapon_name_and_idx(self):
        gv = _gv(_weapon_idx=1)
        s = bot_api._weapon_state(gv)
        assert s["name"] == "Mining Beam"
        assert s["idx"] == 1

    def test_handles_missing_active_weapon(self):
        gv = SimpleNamespace()  # no _active_weapon at all
        s = bot_api._weapon_state(gv)
        assert s["name"] == "Unknown"


class TestAbilityState:
    def test_value_and_max(self):
        gv = _gv()
        s = bot_api._ability_state(gv)
        assert s["value"] == 75
        assert s["max"] == 100


class TestZoneState:
    def test_returns_zone_block(self):
        gv = _gv()
        s = bot_api._zone_state(gv)
        assert s["id"] == "ZoneID.MAIN"
        assert s["world_w"] == 6400
        assert s["world_h"] == 6400

    def test_no_zone_returns_empty(self):
        gv = SimpleNamespace()
        s = bot_api._zone_state(gv)
        assert s == {}


class TestBossState:
    def test_returns_none_when_no_boss(self):
        assert bot_api._boss_state(_gv()) is None

    def test_returns_block_for_alive_boss(self):
        boss = SimpleNamespace(
            center_x=1000, center_y=2000, hp=500, max_hp=1000,
            _phase=2, alive=True)
        s = bot_api._boss_state(_gv(_boss=boss))
        assert s["x"] == 1000.0
        assert s["hp"] == 500
        assert s["phase"] == 2

    def test_skips_dead_boss(self):
        boss = SimpleNamespace(center_x=0, center_y=0, hp=0,
                               max_hp=1000, alive=False)
        assert bot_api._boss_state(_gv(_boss=boss)) is None


class TestInventoryState:
    def test_aggregates_items_by_name(self):
        gv = _gv(inventory=SimpleNamespace(_items={
            (0, 0): ("iron", 50),
            (0, 1): ("iron", 30),
            (1, 0): ("bp_armor_plate", 1),
        }, _open=False))
        s = bot_api._inventory_state(gv)
        assert s["items"] == {"iron": 80, "bp_armor_plate": 1}

    def test_missing_inventory_returns_empty(self):
        s = bot_api._inventory_state(SimpleNamespace())
        assert s == {}


class TestMenuState:
    def test_reports_each_modal_independently(self):
        gv = _gv(
            _build_menu_open=True,
            _escape_menu_open=False,
            inventory=SimpleNamespace(_items={}, _open=True),
        )
        s = bot_api._menu_state(gv)
        assert s["build"] is True
        assert s["inventory"] is True
        assert s["escape"] is False


# ── Sprite + pickup summaries ─────────────────────────────────────────────


class TestSpriteSummary:
    def test_basic_fields(self):
        sp = _sprite(100, 200, hp=42)
        s = bot_api._sprite_summary(sp)
        assert s == {"x": 100.0, "y": 200.0, "hp": 42, "type": "SimpleNamespace"}

    def test_list_summary_caps_at_max(self):
        lst = [_sprite(i, 0) for i in range(150)]
        s = bot_api._list_summary(lst, max_items=50)
        assert len(s) == 50

    def test_list_summary_handles_none(self):
        assert bot_api._list_summary(None) == []


class TestPickupSummary:
    def test_includes_amount_and_item_type(self):
        pickup = SimpleNamespace(
            center_x=500, center_y=600, amount=10, item_type="iron")
        s = bot_api._pickup_summary(pickup)
        assert s["amount"] == 10
        assert s["item_type"] == "iron"
        assert s["x"] == 500.0

    def test_pickup_list_caps_at_max(self):
        lst = [SimpleNamespace(center_x=i, center_y=0,
                               amount=1, item_type="iron")
               for i in range(300)]
        s = bot_api._pickup_list(lst, max_items=200)
        assert len(s) == 200


# ── get_state end-to-end ──────────────────────────────────────────────────


class TestGetState:
    def test_state_contains_all_top_level_keys(self):
        gv = _gv()
        s = bot_api.get_state(gv)
        # Every documented key must be present (so consumers can
        # rely on the schema even when sub-blocks are empty).
        for k in ("ts", "uptime_s", "player", "weapon", "ability",
                  "zone", "boss", "menu", "inventory", "intent",
                  "asteroids", "aliens", "buildings",
                  "iron_pickups", "blueprint_pickups", "assist"):
            assert k in s, f"missing key {k!r} in get_state output"

    def test_intent_round_trip(self):
        # Stub gv minimal -- we just want to see intent reflected.
        gv = _gv()
        bot_api._intent.clear()
        bot_api._intent.update({"type": "mine_nearest"})
        s = bot_api.get_state(gv)
        assert s["intent"] == {"type": "mine_nearest"}

    def test_pickups_appear_in_state(self):
        iron = SimpleNamespace(
            center_x=10, center_y=20, amount=10, item_type="iron")
        bp = SimpleNamespace(
            center_x=30, center_y=40, amount=1,
            item_type="bp_engine_booster")
        gv = _gv(iron_pickup_list=[iron],
                 blueprint_pickup_list=[bp])
        s = bot_api.get_state(gv)
        assert s["iron_pickups"][0]["item_type"] == "iron"
        assert s["blueprint_pickups"][0]["item_type"] == \
            "bp_engine_booster"

    def test_extractors_dont_crash_on_partial_gv(self):
        # gv missing several attributes -- should still return
        # a complete dict, with empty defaults where data is absent.
        gv = SimpleNamespace(player=SimpleNamespace())
        s = bot_api.get_state(gv)
        assert isinstance(s, dict)
        assert s["asteroids"] == []
        assert s["zone"] == {}
