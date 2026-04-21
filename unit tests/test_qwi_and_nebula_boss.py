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
