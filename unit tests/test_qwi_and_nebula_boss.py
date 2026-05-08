"""Unit tests for the Quantum Wave Integrator + Nebula boss feature.

Tests that don't need a live GL context:
  - QWI BUILDING_TYPES entry (costs, flags, custom asset path)
  - QWI appears in the build-menu order
  - Nebula boss constants (gas + cone tunables)
  - GasCloudProjectile velocity, lifetime, contains_point
  - NebulaBossShip.cone_contains_point geometry
  - QWIMenu action API (button click returns 'spawn_nebula_boss')
  - spawn_nebula_boss gating (resource / no-home / double-summon)

Tests that DO need a GL context (actual QWIMenu / NebulaBossShip /
GasCloudProjectile construction) live in the integration suite.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ── QWI constants + BUILDING_TYPES entry ──────────────────────────────────

class TestQWIConstants:
    def test_in_building_types(self):
        from constants import BUILDING_TYPES
        assert "Quantum Wave Integrator" in BUILDING_TYPES

    def test_cost_1000_iron_2000_copper(self):
        from constants import BUILDING_TYPES
        qwi = BUILDING_TYPES["Quantum Wave Integrator"]
        assert qwi["cost"] == 1000
        assert qwi["cost_copper"] == 2000

    def test_max_one(self):
        from constants import BUILDING_TYPES
        assert BUILDING_TYPES["Quantum Wave Integrator"]["max"] == 1

    def test_free_place_flag(self):
        from constants import BUILDING_TYPES
        qwi = BUILDING_TYPES["Quantum Wave Integrator"]
        assert qwi["free_place"] is True
        # Does NOT consume module slots.
        assert qwi["slots_used"] == 0

    def test_is_qwi_flag(self):
        from constants import BUILDING_TYPES
        assert BUILDING_TYPES["Quantum Wave Integrator"].get("is_qwi") is True

    def test_png_path_overrides_default_dir(self):
        """The QWI uses an asset outside BUILDING_DIR, so it needs a
        full ``png_path`` override."""
        import os
        from constants import BUILDING_TYPES
        qwi = BUILDING_TYPES["Quantum Wave Integrator"]
        assert "png_path" in qwi
        assert os.path.isfile(qwi["png_path"])

    def test_place_radius_is_300(self):
        from constants import QWI_PLACE_RADIUS
        assert QWI_PLACE_RADIUS == 300.0

    def test_spawn_cost_is_100_iron(self):
        from constants import QWI_SPAWN_NEBULA_BOSS_IRON_COST
        assert QWI_SPAWN_NEBULA_BOSS_IRON_COST == 100

    def test_qwi_in_build_menu_order(self):
        from build_menu import _MENU_ORDER
        assert "Quantum Wave Integrator" in _MENU_ORDER


class TestQWICopperCostZoneAware:
    """The QWI's 2000-copper cost is waived in Zone 1 because copper
    is only mineable in Zone 2 / Star Maze, and Zone 2 access is
    gated behind defeating the Double Star boss — which the QWI
    itself spawns.  Without the waiver the boss fight is
    un-triggerable from the starting zone.  Cost is preserved when
    the QWI is placed elsewhere (Zone 2)."""

    def test_waived_in_zone1(self):
        from building_manager import effective_copper_cost
        from zones.zone1_main import MainZone
        gv = SimpleNamespace(_zone=MainZone())
        assert effective_copper_cost(gv, "Quantum Wave Integrator") == 0

    def test_preserved_in_zone2(self):
        from building_manager import effective_copper_cost
        # Use a stand-in object that isn't a MainZone — the helper
        # only special-cases MainZone, so any other type triggers the
        # full-cost branch.
        gv = SimpleNamespace(_zone=object())
        assert effective_copper_cost(
            gv, "Quantum Wave Integrator") == 2000

    def test_other_buildings_unaffected_by_zone(self):
        from building_manager import effective_copper_cost
        from zones.zone1_main import MainZone
        from constants import BUILDING_TYPES
        non_qwi_with_copper = next(
            (k for k, v in BUILDING_TYPES.items()
             if v.get("cost_copper", 0) > 0 and not v.get("is_qwi")),
            None,
        )
        if non_qwi_with_copper is None:
            pytest.skip("no non-QWI building with copper cost")
        base = BUILDING_TYPES[non_qwi_with_copper]["cost_copper"]
        gv_main = SimpleNamespace(_zone=MainZone())
        gv_other = SimpleNamespace(_zone=object())
        assert effective_copper_cost(
            gv_main, non_qwi_with_copper) == base
        assert effective_copper_cost(
            gv_other, non_qwi_with_copper) == base

    def test_zero_cost_buildings_return_zero(self):
        from building_manager import effective_copper_cost
        from zones.zone1_main import MainZone
        from constants import BUILDING_TYPES
        free_b = next(
            (k for k, v in BUILDING_TYPES.items()
             if v.get("cost_copper", 0) == 0),
            None,
        )
        assert free_b is not None
        gv = SimpleNamespace(_zone=MainZone())
        assert effective_copper_cost(gv, free_b) == 0


class TestQWIBuildMenuZoneAware:
    """Mirror of the cost waiver in the build menu's display gate.

    Without these tests, ``BuildMenu._check_availability`` could grey
    out the QWI row in Zone 1 with "Need 2000 copper" even though the
    underlying placement path waives the cost — the user would see
    the option as un-buildable.
    """

    def _common_kwargs(self, **overrides):
        kwargs = dict(
            iron=10000,
            building_counts={"Home Station": 1},
            modules_used=0,
            module_capacity=10,
            has_home=True,
            copper=0,
            unlocked_blueprints=set(),
            ship_level=1,
            max_ship_exists=False,
            l1_ship_exists=False,
        )
        kwargs.update(overrides)
        return kwargs

    def test_menu_available_in_zone1_with_zero_copper(self):
        from build_menu import BuildMenu
        from zones import ZoneID
        avail, reason = BuildMenu._check_availability(
            "Quantum Wave Integrator",
            zone_id=ZoneID.MAIN,
            **self._common_kwargs(),
        )
        assert avail is True, f"unexpectedly unavailable: {reason!r}"

    def test_menu_unavailable_in_zone2_without_copper(self):
        from build_menu import BuildMenu
        from zones import ZoneID
        avail, reason = BuildMenu._check_availability(
            "Quantum Wave Integrator",
            zone_id=ZoneID.ZONE2,
            **self._common_kwargs(copper=0),
        )
        assert avail is False
        assert "copper" in reason.lower()

    def test_menu_available_in_zone2_with_full_copper(self):
        from build_menu import BuildMenu
        from zones import ZoneID
        avail, reason = BuildMenu._check_availability(
            "Quantum Wave Integrator",
            zone_id=ZoneID.ZONE2,
            **self._common_kwargs(copper=2000),
        )
        assert avail is True, f"unexpectedly unavailable: {reason!r}"

    def test_other_buildings_with_copper_unaffected_in_zone1(self):
        """The QWI waiver must NOT bleed into other buildings that
        also have a copper cost (e.g. modules / advanced structures
        gated on Zone-2 resources by design)."""
        from build_menu import BuildMenu
        from zones import ZoneID
        from constants import BUILDING_TYPES
        non_qwi_bt = next(
            ((k, v) for k, v in BUILDING_TYPES.items()
             if v.get("cost_copper", 0) > 0 and not v.get("is_qwi")),
            None,
        )
        if non_qwi_bt is None:
            import pytest
            pytest.skip("no non-QWI building with copper cost")
        non_qwi, stats = non_qwi_bt
        # Pre-satisfy the blueprint gate so the copper check is the
        # binding constraint we're verifying.
        bp = stats.get("requires_blueprint")
        unlocked = {bp} if bp else set()
        avail, reason = BuildMenu._check_availability(
            non_qwi,
            zone_id=ZoneID.MAIN,
            **self._common_kwargs(copper=0, unlocked_blueprints=unlocked),
        )
        assert avail is False
        assert "copper" in reason.lower()


# ── Nebula boss constants ──────────────────────────────────────────────────

class TestNebulaBossConstants:
    def test_gas_speed_is_half_basic_laser(self):
        """User spec: gas moves at half the speed of the basic laser."""
        from constants import (
            NEBULA_BOSS_GAS_SPEED, BOSS_CANNON_SPEED,
        )
        assert NEBULA_BOSS_GAS_SPEED == BOSS_CANNON_SPEED / 2.0

    def test_gas_range_is_500(self):
        from constants import NEBULA_BOSS_GAS_RANGE
        assert NEBULA_BOSS_GAS_RANGE == 500.0

    def test_slow_factor_is_half(self):
        from constants import NEBULA_BOSS_SLOW_FACTOR
        assert NEBULA_BOSS_SLOW_FACTOR == 0.5

    def test_cone_range_is_400(self):
        # Doubled from 200 per user tuning — the Nebula boss's cone
        # AoE is meant to be a real threat rather than a glancing
        # close-range hazard.
        from constants import NEBULA_BOSS_CONE_RANGE
        assert NEBULA_BOSS_CONE_RANGE == 400.0

    def test_cone_width_is_200(self):
        from constants import NEBULA_BOSS_CONE_WIDTH
        assert NEBULA_BOSS_CONE_WIDTH == 200.0

    def test_boss_sheet_column_is_second(self):
        """User spec: 'one of the eight images in the second column'
        — zero-indexed that's column 1."""
        from constants import NEBULA_BOSS_COL_INDEX
        assert NEBULA_BOSS_COL_INDEX == 1

    def test_boss_asset_exists(self):
        import os
        from constants import NEBULA_BOSS_PNG
        assert os.path.isfile(NEBULA_BOSS_PNG)


# ── spawn_nebula_boss gating ───────────────────────────────────────────────
#
# The resource + no-home-station + double-summon gates for
# spawn_nebula_boss are exercised in the integration suite
# (test_qwi_and_nebula_boss.py) where a real HomeStation sprite can
# satisfy the ``isinstance(b, HomeStation)`` check.  Unit-level
# simulation is impractical because ``HomeStation`` inherits from
# ``arcade.Sprite``, whose C-slot layout can't be faked with a
# namespace.


# GasCloudProjectile / NebulaBossShip / QWIMenu construction needs a
# GL context; their unit-scope tests live in
# ``integration/test_qwi_and_nebula_boss.py`` alongside the full
# GameView-driven tests.
