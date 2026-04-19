"""Tests for the new "Basic Ship" build flow.

Adds a new build menu entry that costs half the Advanced Ship to
rebuild a destroyed L1 AI scout.  Only buildable when no other L1
ship exists.

Covers:
  - Constants entry: half cost, is_ship + is_basic_ship flags
  - count_l1_ships(gv) — player + parked sum
  - _check_availability gates l1_ship_exists correctly
  - _MENU_ORDER contains "Basic Ship"
  - _place_basic_ship deducts cost + appends a fresh L1 parked ship
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# ── Constants ─────────────────────────────────────────────────────────────

class TestBasicShipConstants:
    def test_basic_ship_in_building_types(self):
        from constants import BUILDING_TYPES
        assert "Basic Ship" in BUILDING_TYPES

    def test_basic_ship_costs_half_advanced(self):
        from constants import BUILDING_TYPES
        basic = BUILDING_TYPES["Basic Ship"]
        adv = BUILDING_TYPES["Advanced Ship"]
        assert basic["cost"] == adv["cost"] // 2
        assert basic.get("cost_copper", 0) == adv.get("cost_copper", 0) // 2

    def test_basic_ship_flagged_as_basic_ship_and_is_ship(self):
        from constants import BUILDING_TYPES
        b = BUILDING_TYPES["Basic Ship"]
        assert b.get("is_ship") is True
        assert b.get("is_basic_ship") is True
        # Doesn't count toward station module slots — it's a placement
        # spawn, not a docked module.
        assert b["slots_used"] == 0
        assert b.get("free_place") is True


# ── count_l1_ships helper ─────────────────────────────────────────────────

class TestCountL1Ships:
    def _gv(self, *, player_level: int = 1, parked_levels=()):
        parked = []
        for lv in parked_levels:
            parked.append(SimpleNamespace(ship_level=lv))
        return SimpleNamespace(
            _ship_level=player_level,
            _parked_ships=parked,
            _player_dead=False,
        )

    def test_player_l1_with_no_parked(self):
        from ship_manager import count_l1_ships
        assert count_l1_ships(self._gv(player_level=1)) == 1

    def test_player_l2_with_no_parked(self):
        from ship_manager import count_l1_ships
        assert count_l1_ships(self._gv(player_level=2)) == 0

    def test_player_l2_with_one_parked_l1(self):
        from ship_manager import count_l1_ships
        assert count_l1_ships(
            self._gv(player_level=2, parked_levels=(1,))) == 1

    def test_player_l2_after_l1_destroyed(self):
        """The exact scenario the new Basic Ship flow targets — player
        upgraded to L2, parked L1 was killed, so count drops to 0 and
        the build menu unlocks Basic Ship."""
        from ship_manager import count_l1_ships
        assert count_l1_ships(
            self._gv(player_level=2, parked_levels=())) == 0

    def test_dead_player_does_not_count(self):
        from ship_manager import count_l1_ships
        gv = self._gv(player_level=1)
        gv._player_dead = True
        assert count_l1_ships(gv) == 0

    def test_multiple_parked_l1_ships_count_each(self):
        from ship_manager import count_l1_ships
        assert count_l1_ships(
            self._gv(player_level=1, parked_levels=(1, 1, 2))) == 3


# ── BuildMenu availability ────────────────────────────────────────────────

class TestBuildMenuBasicShipAvailability:
    def _check(self, *, l1_ship_exists: bool, iron: int = 10_000,
               copper: int = 10_000):
        from build_menu import BuildMenu
        return BuildMenu._check_availability(
            "Basic Ship",
            iron=iron, building_counts={"Home Station": 1},
            modules_used=0, module_capacity=20, has_home=True,
            copper=copper, unlocked_blueprints=set(),
            ship_level=2, max_ship_exists=False,
            l1_ship_exists=l1_ship_exists,
        )

    def test_available_when_no_l1_ship_exists(self):
        ok, _ = self._check(l1_ship_exists=False)
        assert ok

    def test_rejected_when_l1_ship_already_exists(self):
        ok, reason = self._check(l1_ship_exists=True)
        assert not ok
        assert "L1" in reason or "level-1" in reason.lower()

    def test_rejected_when_no_home_station(self):
        from build_menu import BuildMenu
        ok, reason = BuildMenu._check_availability(
            "Basic Ship",
            iron=10_000, building_counts={},
            modules_used=0, module_capacity=20, has_home=False,
            copper=10_000, unlocked_blueprints=set(),
            ship_level=2, max_ship_exists=False, l1_ship_exists=False,
        )
        assert not ok
        assert "Home Station" in reason

    def test_rejected_when_iron_insufficient(self):
        ok, reason = self._check(l1_ship_exists=False, iron=100)
        assert not ok
        assert "iron" in reason.lower()

    def test_rejected_when_copper_insufficient(self):
        ok, reason = self._check(l1_ship_exists=False, copper=10)
        assert not ok
        assert "copper" in reason.lower()

    def test_existing_advanced_ship_check_still_passes(self):
        """Regression — adding the l1 kwarg must not break the
        Advanced Ship availability check."""
        from build_menu import BuildMenu
        ok, _ = BuildMenu._check_availability(
            "Advanced Ship",
            iron=10_000, building_counts={"Home Station": 1},
            modules_used=0, module_capacity=20, has_home=True,
            copper=10_000, unlocked_blueprints=set(),
            ship_level=1, max_ship_exists=False, l1_ship_exists=True,
        )
        assert ok


# ── Menu order ────────────────────────────────────────────────────────────

class TestMenuOrder:
    def test_basic_ship_in_menu_order(self):
        from build_menu import _MENU_ORDER
        assert "Basic Ship" in _MENU_ORDER

    def test_basic_ship_before_advanced_ship(self):
        from build_menu import _MENU_ORDER
        assert _MENU_ORDER.index("Basic Ship") < _MENU_ORDER.index("Advanced Ship")
