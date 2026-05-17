"""Tests for the spawn-time path-connectivity guarantee in the gas
cloud warp zone (zones/zone_warp_gas.py)."""
from __future__ import annotations

import random

import arcade
import pytest
from PIL import Image as PILImage

from sprites.gas_area import GasArea
from zones.zone_warp_base import WARP_ZONE_WIDTH, WARP_ZONE_HEIGHT
from zones.zone_warp_gas import GasCloudWarpZone


@pytest.fixture
def tiny_tex() -> arcade.Texture:
    img = PILImage.new("RGBA", (32, 32), (100, 200, 80, 80))
    return arcade.Texture(img)


def _make_zone() -> GasCloudWarpZone:
    """Build a zone instance with an empty cloud list (no setup()) so
    tests can install hand-crafted layouts."""
    z = GasCloudWarpZone()
    z._clouds = arcade.SpriteList()
    return z


# ── _has_path_bottom_to_top ────────────────────────────────────────────────

class TestHasPath:
    def test_empty_zone_is_passable(self):
        z = _make_zone()
        assert z._has_path_bottom_to_top() is True

    def test_full_horizontal_wall_blocks(self, tiny_tex):
        """A row of giant clouds spanning the full width should block."""
        z = _make_zone()
        # 5 clouds of radius ~750 px across width 3200 → ~640 px centres.
        for i in range(5):
            x = (i + 0.5) * (WARP_ZONE_WIDTH / 5)
            y = WARP_ZONE_HEIGHT * 0.5
            z._clouds.append(GasArea(tiny_tex, x, y, size=1500,
                                     world_w=WARP_ZONE_WIDTH,
                                     world_h=WARP_ZONE_HEIGHT))
        assert z._has_path_bottom_to_top() is False

    def test_gap_in_wall_is_passable(self, tiny_tex):
        """A wall with a wide gap (skip middle cloud) is passable."""
        z = _make_zone()
        # Three non-overlapping medium clouds: radius ~500, centres at
        # 533 / 1600 / 2667 across width 3200.  Removing the middle one
        # leaves a ~1100 px gap from x=1067 to x=2133.
        for i in range(3):
            if i == 1:
                continue
            x = (i + 0.5) * (WARP_ZONE_WIDTH / 3)
            y = WARP_ZONE_HEIGHT * 0.5
            z._clouds.append(GasArea(tiny_tex, x, y, size=1000,
                                     world_w=WARP_ZONE_WIDTH,
                                     world_h=WARP_ZONE_HEIGHT))
        assert z._has_path_bottom_to_top() is True


# ── _ensure_path_through ────────────────────────────────────────────────────

class TestEnsurePathThrough:
    def test_no_op_when_already_passable(self, tiny_tex):
        z = _make_zone()
        # A single small cloud in the corner — trivially passable.
        z._clouds.append(GasArea(tiny_tex, 200.0, 200.0, size=160,
                                 world_w=WARP_ZONE_WIDTH,
                                 world_h=WARP_ZONE_HEIGHT))
        original_count = len(z._clouds)
        z._ensure_path_through()
        assert len(z._clouds) == original_count

    def test_opens_path_by_removing_largest(self, tiny_tex):
        """A wall of large clouds gets thinned until a corridor exists."""
        z = _make_zone()
        for i in range(5):
            x = (i + 0.5) * (WARP_ZONE_WIDTH / 5)
            y = WARP_ZONE_HEIGHT * 0.5
            z._clouds.append(GasArea(tiny_tex, x, y, size=1500,
                                     world_w=WARP_ZONE_WIDTH,
                                     world_h=WARP_ZONE_HEIGHT))
        assert z._has_path_bottom_to_top() is False
        z._ensure_path_through()
        assert z._has_path_bottom_to_top() is True
        # Removed at least one cloud, but not all of them.
        assert 0 < len(z._clouds) < 5

    def test_prefers_removing_larger_clouds_first(self, tiny_tex):
        """Given mixed sizes blocking, large clouds should be removed
        before small ones."""
        z = _make_zone()
        # Big wall of large clouds at y = 0.5*H ...
        for i in range(5):
            x = (i + 0.5) * (WARP_ZONE_WIDTH / 5)
            z._clouds.append(GasArea(tiny_tex, x, WARP_ZONE_HEIGHT * 0.5,
                                     size=1500,
                                     world_w=WARP_ZONE_WIDTH,
                                     world_h=WARP_ZONE_HEIGHT))
        # ... plus a few small clouds elsewhere that don't block the path.
        for i in range(3):
            z._clouds.append(GasArea(tiny_tex,
                                     200.0 + i * 200,
                                     WARP_ZONE_HEIGHT * 0.1,
                                     size=160,
                                     world_w=WARP_ZONE_WIDTH,
                                     world_h=WARP_ZONE_HEIGHT))
        small_count_before = sum(1 for c in z._clouds if c.radius < 100)
        z._ensure_path_through()
        small_count_after = sum(1 for c in z._clouds if c.radius < 100)
        assert small_count_after == small_count_before  # small clouds untouched

    def test_terminates_on_pathological_dense_layout(self, tiny_tex):
        """Even a totally walled zone resolves — in the worst case
        every cloud gets removed."""
        z = _make_zone()
        # Pack the whole zone with huge overlapping clouds.
        for r in range(8):
            for c in range(4):
                x = (c + 0.5) * (WARP_ZONE_WIDTH / 4)
                y = (r + 0.5) * (WARP_ZONE_HEIGHT / 8)
                z._clouds.append(GasArea(tiny_tex, x, y, size=1500,
                                         world_w=WARP_ZONE_WIDTH,
                                         world_h=WARP_ZONE_HEIGHT))
        z._ensure_path_through()
        assert z._has_path_bottom_to_top() is True


# ── Integration: setup() invokes the guarantee ─────────────────────────────

class TestSetupGuaranteesPath:
    def test_random_layouts_always_passable(self):
        """Run setup() with several seeds and confirm a path always
        exists at spawn."""
        from unittest.mock import MagicMock

        for seed in range(10):
            random.seed(seed)
            z = GasCloudWarpZone()
            gv = MagicMock()
            z.setup(gv)
            assert z._has_path_bottom_to_top() is True, (
                f"seed={seed} produced a walled gas zone")

    def test_high_danger_layouts_always_passable(self):
        """2× danger spawns more large clouds — still must be passable."""
        from unittest.mock import MagicMock

        for seed in range(10):
            random.seed(seed)
            z = GasCloudWarpZone()
            z._danger = 2.0
            gv = MagicMock()
            z.setup(gv)
            assert z._has_path_bottom_to_top() is True, (
                f"seed={seed} @ 2x danger produced a walled gas zone")
