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
        assert s == {
            "x": 100.0, "y": 200.0, "hp": 42,
            "type": "SimpleNamespace",
            "building_type": "",   # empty for non-buildings
            "crafting": False,
            "craft_target": "",
            "disabled": False,
        }

    def test_building_type_surfaces(self):
        """Building sprites carry a ``building_type`` attribute set
        by building_manager — bot_api forwards it so the bot can
        find specific buildings (the Home Station, especially)."""
        sp = _sprite(500, 500, hp=100, building_type="Home Station")
        s = bot_api._sprite_summary(sp)
        assert s["building_type"] == "Home Station"

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


class TestZoneAwareLists:
    """The bot's /state must mirror the minimap's zone-aware view —
    in Zone 2 / Star Maze / warp zones, aliens + asteroids live on
    the zone, not on gv.alien_list / gv.asteroid_list.  Without
    this fix the bot was blind in non-MAIN zones and the FSM would
    flap between SEARCH and idle even though the minimap clearly
    showed enemies + rocks."""

    def test_zone_two_aliens_surface_in_state(self, monkeypatch):
        """When ``_minimap_enemies`` returns the zone's aliens, the
        bot's /state.aliens reflects those entries — not the empty
        ``gv.alien_list`` that Zone 2 keeps for compatibility."""
        zone_aliens = [
            _sprite(2000, 2000), _sprite(2500, 2500),
        ]
        # Stub draw_logic._minimap_enemies to simulate Zone 2
        # behavior without instantiating a real zone.
        import draw_logic
        monkeypatch.setattr(
            draw_logic, "_minimap_enemies",
            lambda gv: zone_aliens)
        gv = _gv(alien_list=[])
        s = bot_api.get_state(gv)
        assert len(s["aliens"]) == 2
        assert s["aliens"][0]["x"] == 2000
        assert s["aliens"][1]["x"] == 2500

    def test_zone_two_asteroids_surface_in_state(self, monkeypatch):
        """Same fix for asteroids — _minimap_obstacles returns the
        zone's iron + copper asteroid chain in Zone 2 / Star Maze."""
        zone_obstacles = [
            _sprite(3000, 3000), _sprite(3100, 3050),
            _sprite(3200, 3100),
        ]
        import draw_logic
        monkeypatch.setattr(
            draw_logic, "_minimap_obstacles",
            lambda gv: zone_obstacles)
        gv = _gv(asteroid_list=[])
        s = bot_api.get_state(gv)
        assert len(s["asteroids"]) == 3

    def test_falls_back_to_gv_lists_when_aggregator_fails(
            self, monkeypatch):
        """If draw_logic's helpers raise (e.g. attribute access
        on a half-initialised zone), the bot must still serve a
        valid /state by falling back to gv.alien_list /
        gv.asteroid_list — never crash the API."""
        import draw_logic
        def _boom(gv):
            raise RuntimeError("zone not ready")
        monkeypatch.setattr(draw_logic, "_minimap_enemies", _boom)
        monkeypatch.setattr(draw_logic, "_minimap_obstacles", _boom)
        gv = _gv(
            alien_list=[_sprite(100, 100)],
            asteroid_list=[_sprite(200, 200)],
        )
        s = bot_api.get_state(gv)
        # Fallback served the gv lists.
        assert len(s["aliens"]) == 1
        assert len(s["asteroids"]) == 1


class TestMainThreadQueue:
    """``submit_to_main_thread`` queues a callable for the next
    ``pump_main_thread_queue`` call — required so HTTP handlers
    that need GL-backed mutation (sprite spawn, building
    placement) run on the GL-context thread instead of crashing
    with GL_INVALID_OPERATION (0x1282)."""

    def test_callable_runs_on_pump(self):
        # Reset queue so prior tests don't leak.
        with bot_api._main_thread_queue_lock:
            bot_api._main_thread_queue.clear()
        ran: list = []
        done, _ = bot_api.submit_to_main_thread(
            lambda gv: ran.append(gv) or "result")
        # Hasn't run yet — callable is pending.
        assert ran == []
        assert not done.is_set()
        # Pump runs it on the (test) main thread.
        bot_api.pump_main_thread_queue("fake_gv")
        assert ran == ["fake_gv"]
        assert done.is_set()

    def test_result_value_propagates(self):
        with bot_api._main_thread_queue_lock:
            bot_api._main_thread_queue.clear()
        done, result = bot_api.submit_to_main_thread(
            lambda gv: 42)
        bot_api.pump_main_thread_queue(None)
        assert done.is_set()
        assert result["value"] == 42
        assert result["error"] is None

    def test_exception_captured_into_result(self):
        with bot_api._main_thread_queue_lock:
            bot_api._main_thread_queue.clear()
        def _boom(gv):
            raise RuntimeError("kaboom")
        done, result = bot_api.submit_to_main_thread(_boom)
        bot_api.pump_main_thread_queue(None)
        assert done.is_set()
        assert result["value"] is None
        assert isinstance(result["error"], RuntimeError)
        assert "kaboom" in str(result["error"])

    def test_pump_with_empty_queue_is_no_op(self):
        with bot_api._main_thread_queue_lock:
            bot_api._main_thread_queue.clear()
        # Should not raise.
        bot_api.pump_main_thread_queue(None)

    def test_pump_drains_in_fifo_order(self):
        with bot_api._main_thread_queue_lock:
            bot_api._main_thread_queue.clear()
        order: list = []
        bot_api.submit_to_main_thread(lambda gv: order.append(1))
        bot_api.submit_to_main_thread(lambda gv: order.append(2))
        bot_api.submit_to_main_thread(lambda gv: order.append(3))
        bot_api.pump_main_thread_queue(None)
        assert order == [1, 2, 3]
