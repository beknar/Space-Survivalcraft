"""Resolution-perf for the Double Star boss combat scene.

Each supported resolution preset is exercised with a full boss
combat scene (boss spawned + station + turrets + Zone 1 entities).
A regression in resolution-dependent draw cost (e.g. boss
projectile shaders that scale with framebuffer size) shows up as
a named test failure rather than a vague FPS dip in the catch-all
boss perf test.

These tests resize the shared hidden window via ``apply_resolution``
between cases — must run sequentially for the same reasons as
``test_resolution_perf.py``.

Run with:
    pytest "unit tests/integration/test_resolution_perf_boss.py" -v -s
"""
from __future__ import annotations

import arcade
import pytest

from constants import RESOLUTION_PRESETS, WORLD_WIDTH, WORLD_HEIGHT
from settings import apply_resolution
from zones import ZoneID

MIN_FPS = 40

from integration.conftest import measure_fps


def _measure_fps(gv) -> float:
    return measure_fps(gv, n_warmup=20, n_measure=60)


_RES_IDS = [f"{w}x{h}" for w, h in RESOLUTION_PRESETS]


@pytest.fixture
def gv_with_boss_at_resolution(real_window, request):
    """Create a GameView at the requested resolution AND spawn the
    boss + a small station so every test case starts from the same
    fully-loaded boss combat scene."""
    width, height = request.param
    apply_resolution(real_window, width, height, display_mode="windowed")

    from game_view import GameView
    from sprites.building import create_building
    from combat_helpers import spawn_boss

    gv = GameView(faction="Earth", ship_type="Cruiser", skip_music=True)
    real_window.show_view(gv)

    if gv._zone.zone_id != ZoneID.MAIN:
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

    # Small station (Home + 2 turrets) so the boss has a target and
    # the station turrets contribute draw-call load.
    gv.building_list.clear()
    home_tex = gv._building_textures["Home Station"]
    home = create_building("Home Station", home_tex,
                           WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                           scale=0.5)
    gv.building_list.append(home)
    for bt, ox in (("Turret 1", 80), ("Turret 2", -80)):
        t_tex = gv._building_textures[bt]
        b = create_building(bt, t_tex,
                            WORLD_WIDTH / 2 + ox,
                            WORLD_HEIGHT / 2,
                            laser_tex=gv._turret_laser_tex, scale=0.5)
        gv.building_list.append(b)

    gv._boss = None
    gv._boss_spawned = False
    gv._boss_defeated = False
    gv._boss_list.clear()
    gv._boss_projectile_list.clear()
    spawn_boss(gv, WORLD_WIDTH / 2, WORLD_HEIGHT / 2)

    yield gv

    apply_resolution(real_window, 800, 600, display_mode="windowed")


# ═══════════════════════════════════════════════════════════════════════════
#  Boss combat at each supported resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestResolutionBossCombat:
    @pytest.mark.parametrize(
        "gv_with_boss_at_resolution", RESOLUTION_PRESETS, ids=_RES_IDS,
        indirect=True,
    )
    def test_boss_combat_at_resolution(self, gv_with_boss_at_resolution):
        """Boss combat must hold above 40 FPS at every supported
        resolution.  Catches resolution-dependent draw regressions
        in the boss / projectile / turret render paths."""
        gv = gv_with_boss_at_resolution
        w, h = gv.window.width, gv.window.height

        fps = _measure_fps(gv)
        print(f"  [res-perf-boss] {w}x{h} boss combat: {fps:.1f} FPS")

        assert fps >= MIN_FPS, (
            f"{w}x{h} boss combat: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Boss combat in Phase 3 (enraged, halved cooldowns) at each resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestResolutionBossPhase3:
    @pytest.mark.parametrize(
        "gv_with_boss_at_resolution", RESOLUTION_PRESETS, ids=_RES_IDS,
        indirect=True,
    )
    def test_boss_phase3_combat_at_resolution(
            self, gv_with_boss_at_resolution):
        """Phase 3 doubles weapon fire rate, so the projectile list
        averages ~2× the size relative to Phase 1.  Tests that the
        per-resolution headroom holds with the hottest combat load."""
        from constants import BOSS_PHASE3_HP
        gv = gv_with_boss_at_resolution
        # Force Phase 3 by setting HP below the 25% threshold.
        gv._boss.hp = max(1, int(gv._boss.max_hp * (BOSS_PHASE3_HP - 0.05)))
        gv._boss._update_phase()
        assert gv._boss._phase == 3
        # Park the player within boss aggro range so weapons fire.
        gv.player.center_x = gv._boss.center_x + 400
        gv.player.center_y = gv._boss.center_y
        # Make invulnerable so the soak-style combat doesn't kill the
        # measurement halfway through.
        gv.player.max_hp = 999999
        gv.player.hp = 999999
        gv.player.max_shields = 999999
        gv.player.shields = 999999

        w, h = gv.window.width, gv.window.height
        fps = _measure_fps(gv)
        print(f"  [res-perf-boss-p3] {w}x{h} phase 3: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"{w}x{h} boss phase 3: {fps:.1f} FPS < {MIN_FPS}"
        )
