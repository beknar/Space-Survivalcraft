"""Performance tests across all supported resolutions.

Each resolution preset is tested with a Zone 1 gameplay scenario. The
hidden Arcade window is resized via ``apply_resolution`` between tests.
These MUST run sequentially (not in parallel) because:
1. Arcade allows only one Window per process
2. apply_resolution mutates global constants (SCREEN_WIDTH/HEIGHT)
3. The shared session window cannot be resized concurrently

Run with:  ``pytest "unit tests/integration/test_resolution_perf.py" -v -s``
"""
from __future__ import annotations

import time

import arcade
import pytest

from constants import RESOLUTION_PRESETS, WORLD_WIDTH, WORLD_HEIGHT
from settings import apply_resolution
from zones import ZoneID

MIN_FPS = 40

from integration.conftest import measure_fps


def _measure_fps(gv) -> float:
    return measure_fps(gv, n_warmup=20, n_measure=60)


# Build test IDs like "1280x800", "1920x1080", etc.
_RES_IDS = [f"{w}x{h}" for w, h in RESOLUTION_PRESETS]


@pytest.fixture
def gv_at_resolution(real_window, request):
    """Create a GameView at the requested resolution.

    The window is resized before constructing the GameView so all UI
    layout math uses the correct dimensions. After the test, the window
    is restored to the default 800×600 to avoid polluting later tests.
    """
    width, height = request.param
    # Resize the hidden window — apply_resolution(window, w, h, ...) handles
    # constants + window.set_size
    apply_resolution(real_window, width, height, display_mode="windowed")

    from game_view import GameView
    gv = GameView(faction="Earth", ship_type="Cruiser", skip_music=True)
    real_window.show_view(gv)
    yield gv

    # Restore default size
    apply_resolution(real_window, 800, 600, display_mode="windowed")


# ═══════════════════════════════════════════════════════════════════════════
#  Zone 1 gameplay at each resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestResolutionZone1:
    @pytest.mark.parametrize(
        "gv_at_resolution", RESOLUTION_PRESETS, ids=_RES_IDS,
        indirect=True,
    )
    def test_zone1_at_resolution(self, gv_at_resolution):
        """Zone 1 gameplay must stay above 40 FPS at each supported
        resolution. Higher resolutions render more background tiles and
        more visible sprites — this catches resolution-scaling regressions."""
        gv = gv_at_resolution
        w, h = gv.window.width, gv.window.height

        fps = _measure_fps(gv)
        print(f"  [res-perf] {w}x{h}: {fps:.1f} FPS")

        assert fps >= MIN_FPS, (
            f"{w}x{h}: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Zone 2 full population at each resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestResolutionZone2:
    @pytest.mark.parametrize(
        "gv_at_resolution", RESOLUTION_PRESETS, ids=_RES_IDS,
        indirect=True,
    )
    def test_zone2_at_resolution(self, gv_at_resolution):
        """Zone 2 (Nebula) with ~60 aliens + ~150 asteroids at each
        resolution. The heaviest zone tests resolution-dependent draw
        cost scaling."""
        gv = gv_at_resolution
        gv._transition_zone(ZoneID.ZONE2)
        w, h = gv.window.width, gv.window.height

        fps = _measure_fps(gv)
        print(f"  [res-perf] {w}x{h} Zone 2: {fps:.1f} FPS")

        assert fps >= MIN_FPS, (
            f"{w}x{h} Zone 2: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
