"""Unit tests for the helpers extracted in the 2026-04-19 five-way refactor.

Covers:
* ``inventory_ops.deduct_resources``
* ``combat_helpers._furthest_corner_from``
* ``update_logic._boss_update_context``
* ``building_manager._check_resources`` + ``_flash_fail``

Each helper already ships covered indirectly through higher-level
flows; these direct tests lock the units in so future edits get a
sharper failure signal than "the Basic Ship integration test broke".
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
#  1. inventory_ops.deduct_resources
# ═══════════════════════════════════════════════════════════════════════════


def _make_gv_with_inventories(ship_iron: int = 0,
                              station_iron: int = 0,
                              ship_copper: int = 0,
                              station_copper: int = 0):
    """Stand-in GameView with mock ship + station inventories.  The
    ``.total_iron`` attribute on ``Inventory`` is a property in real
    code; we pin it as a simple attribute on the mocks."""
    def _make(iron: int, copper: int):
        inv = MagicMock()
        inv.total_iron = iron
        inv.count_item = MagicMock(return_value=copper)
        inv.remove_item = MagicMock()
        return inv

    return SimpleNamespace(
        inventory=_make(ship_iron, ship_copper),
        _station_inv=_make(station_iron, station_copper),
    )


class TestDeductResources:
    def test_iron_only_from_ship_when_ship_has_enough(self):
        from inventory_ops import deduct_resources
        gv = _make_gv_with_inventories(ship_iron=100, station_iron=100)
        deduct_resources(gv, iron=50, copper=0)
        gv.inventory.remove_item.assert_called_once_with("iron", 50)
        gv._station_inv.remove_item.assert_not_called()

    def test_iron_falls_back_to_station_when_ship_short(self):
        """Ship has 30, station has 100, we need 80 — ship drains
        first then station covers the 50-iron shortfall."""
        from inventory_ops import deduct_resources
        gv = _make_gv_with_inventories(ship_iron=30, station_iron=100)
        deduct_resources(gv, iron=80, copper=0)
        gv.inventory.remove_item.assert_called_once_with("iron", 30)
        gv._station_inv.remove_item.assert_called_once_with("iron", 50)

    def test_iron_only_from_station_when_ship_empty(self):
        from inventory_ops import deduct_resources
        gv = _make_gv_with_inventories(ship_iron=0, station_iron=200)
        deduct_resources(gv, iron=100, copper=0)
        gv.inventory.remove_item.assert_not_called()
        gv._station_inv.remove_item.assert_called_once_with("iron", 100)

    def test_copper_path_mirrors_iron(self):
        from inventory_ops import deduct_resources
        gv = _make_gv_with_inventories(
            ship_iron=50, station_iron=0,
            ship_copper=5, station_copper=100)
        deduct_resources(gv, iron=0, copper=30)
        # Ship has 5 copper → drains that first, station covers 25.
        gv.inventory.remove_item.assert_called_once_with("copper", 5)
        gv._station_inv.remove_item.assert_called_once_with("copper", 25)

    def test_iron_and_copper_together(self):
        from inventory_ops import deduct_resources
        gv = _make_gv_with_inventories(
            ship_iron=100, station_iron=0,
            ship_copper=0, station_copper=50)
        deduct_resources(gv, iron=50, copper=25)
        gv.inventory.remove_item.assert_called_once_with("iron", 50)
        gv._station_inv.remove_item.assert_called_once_with("copper", 25)

    def test_zero_iron_zero_copper_is_noop(self):
        from inventory_ops import deduct_resources
        gv = _make_gv_with_inventories(ship_iron=100, station_iron=100)
        deduct_resources(gv, iron=0, copper=0)
        gv.inventory.remove_item.assert_not_called()
        gv._station_inv.remove_item.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
#  2. combat_helpers._furthest_corner_from
# ═══════════════════════════════════════════════════════════════════════════


class TestFurthestCornerFrom:
    def test_returns_opposite_corner_when_home_in_nw(self):
        """Home in the NW (low x, high y) → boss spawns SE."""
        from combat_helpers import _furthest_corner_from
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        corner = _furthest_corner_from(200.0, WORLD_HEIGHT - 200.0)
        assert corner == (WORLD_WIDTH - 100.0, 100.0)

    def test_returns_opposite_corner_when_home_in_se(self):
        from combat_helpers import _furthest_corner_from
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        corner = _furthest_corner_from(
            WORLD_WIDTH - 200.0, 200.0)
        assert corner == (100.0, WORLD_HEIGHT - 100.0)

    def test_returns_a_valid_corner_when_home_at_centre(self):
        """All four corners are equidistant — any one of them is
        a valid return, so just assert membership."""
        from combat_helpers import _furthest_corner_from
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        corner = _furthest_corner_from(WORLD_WIDTH / 2, WORLD_HEIGHT / 2)
        valid = {
            (100.0, 100.0),
            (WORLD_WIDTH - 100.0, 100.0),
            (100.0, WORLD_HEIGHT - 100.0),
            (WORLD_WIDTH - 100.0, WORLD_HEIGHT - 100.0),
        }
        assert corner in valid

    def test_corner_always_inset_100px_from_world_edge(self):
        """Regression guard: the 100 px inset is load-bearing — it
        prevents the boss from spawning clipped against the world
        border.  Whichever corner we return must honour it."""
        from combat_helpers import _furthest_corner_from
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        x, y = _furthest_corner_from(500.0, 500.0)
        assert x in (100.0, WORLD_WIDTH - 100.0)
        assert y in (100.0, WORLD_HEIGHT - 100.0)


# ═══════════════════════════════════════════════════════════════════════════
#  3. update_logic._boss_update_context
# ═══════════════════════════════════════════════════════════════════════════


def _gv_for_boss_ctx(*, home_position=None, home_disabled=False,
                     player_pos=(3200.0, 3200.0),
                     cloaked=False):
    """Build a stand-in GameView for ``_boss_update_context``.

    Bypasses the full home-station isinstance check by using a real
    HomeStation-subclass-with-minimal-init pattern — since a real
    HomeStation carries arcade.Sprite slots we can't cheaply mock,
    we monkeypatch ``update_logic.HomeStation`` in the caller."""
    class _FakeHome:
        def __init__(self, x, y, disabled):
            self.center_x = x
            self.center_y = y
            self.disabled = disabled

    blist = []
    if home_position is not None:
        blist.append(_FakeHome(home_position[0], home_position[1],
                                home_disabled))

    player = SimpleNamespace(
        center_x=player_pos[0], center_y=player_pos[1])
    # cloak sentinel — update_logic.player_is_cloaked reads zone
    # state; we short-circuit via a monkey-patched module attr.
    return SimpleNamespace(
        building_list=blist,
        player=player,
        _null_fields=[] if not cloaked else ["cloaked-marker"],
        _zone=SimpleNamespace(zone_id=None, _null_fields=None),
        _player_dead=False,
    )


class TestBossUpdateContext:
    def test_falls_back_to_world_centre_when_no_home(self, monkeypatch):
        """No HomeStation in building_list → station coords default to
        the world centre so the boss still has somewhere to aim."""
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        import update_logic as _ul
        # Swap HomeStation for a sentinel that nothing in gv.building_list
        # is an isinstance of (so the loop never matches).
        monkeypatch.setattr(_ul, "HomeStation", type("NotAnyone", (), {}))
        gv = _gv_for_boss_ctx(home_position=None,
                              player_pos=(3200.0, 3200.0))
        sx, sy, px, py = _ul._boss_update_context(gv)
        assert sx == WORLD_WIDTH / 2
        assert sy == WORLD_HEIGHT / 2
        assert (px, py) == (3200.0, 3200.0)

    def test_uses_active_home_position(self, monkeypatch):
        import update_logic as _ul
        # Stub HomeStation so our _FakeHome counts as one.
        from sprites.building import HomeStation as _HS
        # Easier: keep the real HomeStation reference and wrap our
        # fake in a subclass.
        class _FakeHome(_HS.__base__):       # inherits arcade.Sprite
            pass
        # The fixture above uses _FakeHome INSIDE it — swap instead to
        # make isinstance(_FakeHome_instance, HomeStation) true via
        # monkey-patching the ``HomeStation`` name in update_logic
        # to accept anything with center_x + center_y + disabled.
        class _StubHomeStation:
            def __init_subclass__(cls, **kw):
                pass
        # Simpler: just monkeypatch isinstance check site.  We
        # replace ``HomeStation`` in update_logic with a class whose
        # __instancecheck__ matches our duck.
        class _DuckHome:
            __slots__ = ()
            @classmethod
            def __instancecheck__(cls, obj):
                return hasattr(obj, "center_x") and hasattr(obj, "disabled")
        # ``isinstance`` on a class uses ``type(cls).__instancecheck__``,
        # so the custom hook has to live on a metaclass.
        class _DuckMeta(type):
            def __instancecheck__(cls, obj):
                return hasattr(obj, "center_x") and hasattr(obj, "disabled")
        class _DuckClass(metaclass=_DuckMeta):
            pass
        monkeypatch.setattr(_ul, "HomeStation", _DuckClass)
        gv = _gv_for_boss_ctx(home_position=(500.0, 600.0))
        sx, sy, px, py = _ul._boss_update_context(gv)
        assert (sx, sy) == (500.0, 600.0)

    def test_skips_disabled_home(self, monkeypatch):
        """A disabled Home Station must not be used — falls through
        to the world-centre default."""
        import update_logic as _ul
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        class _DuckMeta(type):
            def __instancecheck__(cls, obj):
                return hasattr(obj, "center_x") and hasattr(obj, "disabled")
        class _DuckClass(metaclass=_DuckMeta):
            pass
        monkeypatch.setattr(_ul, "HomeStation", _DuckClass)
        gv = _gv_for_boss_ctx(home_position=(500.0, 600.0),
                              home_disabled=True)
        sx, sy, _px, _py = _ul._boss_update_context(gv)
        assert sx == WORLD_WIDTH / 2
        assert sy == WORLD_HEIGHT / 2

    def test_cloaked_player_gets_far_away_coords(self, monkeypatch):
        """When the player is cloaked, the boss should see them a
        billion px away (keeps AI in patrol)."""
        import update_logic as _ul
        # Bypass the full cloak check by monkeypatching.
        monkeypatch.setattr(_ul, "player_is_cloaked", lambda gv: True)
        gv = _gv_for_boss_ctx(player_pos=(1000.0, 2000.0))
        _sx, _sy, px, py = _ul._boss_update_context(gv)
        assert px > 1e8
        assert py > 1e8


# ═══════════════════════════════════════════════════════════════════════════
#  4. building_manager._check_resources + _flash_fail
# ═══════════════════════════════════════════════════════════════════════════


def _gv_for_check_resources(iron_ship=0, iron_station=0,
                            copper_ship=0, copper_station=0):
    inv = MagicMock()
    inv.total_iron = iron_ship
    inv.count_item = MagicMock(return_value=copper_ship)
    station = MagicMock()
    station.total_iron = iron_station
    station.count_item = MagicMock(return_value=copper_station)
    return SimpleNamespace(
        inventory=inv,
        _station_inv=station,
        _char_level=1,
        _flash_msg="",
        _flash_timer=0.0,
    )


class TestCheckResources:
    def test_passes_when_enough_iron_and_copper(self, monkeypatch):
        import building_manager as _bm
        # Shim the character-level cost multiplier so the test doesn't
        # depend on the currently-selected character.
        monkeypatch.setattr(
            _bm, "build_cost_multiplier", lambda name, lv: 1.0,
            raising=False)
        from character_data import build_cost_multiplier as _real
        monkeypatch.setattr(
            "character_data.build_cost_multiplier",
            lambda *a, **kw: 1.0)
        gv = _gv_for_check_resources(iron_ship=5000, copper_ship=5000)
        # "Advanced Crafter" costs 1000 iron + 500 copper.
        assert _bm._check_resources(gv, "Advanced Crafter") is True
        assert gv._flash_msg == ""

    def test_fails_when_iron_short(self, monkeypatch):
        import building_manager as _bm
        monkeypatch.setattr(
            "character_data.build_cost_multiplier",
            lambda *a, **kw: 1.0)
        gv = _gv_for_check_resources(iron_ship=10, iron_station=10)
        assert _bm._check_resources(gv, "Advanced Crafter") is False
        assert "iron" in gv._flash_msg.lower()
        assert gv._flash_timer > 0.0

    def test_fails_when_copper_short(self, monkeypatch):
        import building_manager as _bm
        monkeypatch.setattr(
            "character_data.build_cost_multiplier",
            lambda *a, **kw: 1.0)
        gv = _gv_for_check_resources(
            iron_ship=5000, copper_ship=10)
        assert _bm._check_resources(gv, "Advanced Crafter") is False
        assert "copper" in gv._flash_msg.lower()

    def test_no_copper_check_for_copperless_building(self, monkeypatch):
        """Buildings without a ``cost_copper`` entry (e.g. Service
        Module) must not trip the copper branch."""
        import building_manager as _bm
        monkeypatch.setattr(
            "character_data.build_cost_multiplier",
            lambda *a, **kw: 1.0)
        gv = _gv_for_check_resources(iron_ship=500)  # no copper
        # Service Module is 25 iron + 0 copper.
        assert _bm._check_resources(gv, "Service Module") is True


class TestFlashFail:
    def test_sets_message_and_timer(self):
        from building_manager import _flash_fail
        gv = SimpleNamespace(_flash_msg="", _flash_timer=0.0)
        _flash_fail(gv, "Test msg!")
        assert gv._flash_msg == "Test msg!"
        assert gv._flash_timer == 2.0

    def test_custom_duration(self):
        from building_manager import _flash_fail
        gv = SimpleNamespace(_flash_msg="", _flash_timer=0.0)
        _flash_fail(gv, "Boom", duration=5.0)
        assert gv._flash_timer == 5.0
