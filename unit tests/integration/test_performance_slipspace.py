"""Performance integration tests — slipspace minimap markers.

Frame-time / FPS coverage for the per-zone slipspace markers added
to the minimap (a few extra ``draw_points`` and
``draw_circle_outline`` calls per frame):

  * Zone 2 with all 15 slipspace markers rendering.

Run with:  ``pytest "unit tests/integration/test_performance_slipspace.py" -v``
"""
from __future__ import annotations

import time

import arcade
import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BUILDING_TYPES, MODULE_SLOT_COUNT,
)
from zones import ZoneID

# ── Configuration ──────────────────────────────────────────────────────────

MIN_FPS = 40

# Use shared measure_fps from conftest
from integration.conftest import measure_fps as _measure_fps


# ═══════════════════════════════════════════════════════════════════════════
#  Slipspace minimap markers
# ═══════════════════════════════════════════════════════════════════════════

class TestSlipspaceMinimapDrawFps:
    """Adding 15 slipspace markers per zone to the minimap is a few
    extra draw_points + draw_circle_outline calls per frame.  Make
    sure that doesn't regress measurable FPS."""

    def test_zone2_with_slipspace_markers_above_threshold(
            self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        # Sanity: live zone has slipspaces populated.
        from draw_logic import _slipspace_positions
        assert len(_slipspace_positions(gv)) > 0
        fps = _measure_fps(gv)
        print(f"  [perf] zone2 with slipspace markers: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Zone 2 minimap with slipspace markers: "
            f"{fps:.1f} FPS < {MIN_FPS}")
