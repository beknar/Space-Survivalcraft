"""Per-phase performance tests for the Double Star boss.

The catch-all ``TestZone1WithBoss`` perf test in
``test_performance.py`` spawns the boss in Phase 1 and never pushes
HP across the 50% / 25% thresholds.  Phase 2 adds the charge dash
attack + faster movement + 2× shield regen; Phase 3 enrages with
halved weapon cooldowns and zero shield regen.  Each phase exercises
a distinct combat pipeline that can regress independently.

These tests force the boss into the target phase by setting HP just
under the threshold and calling ``_update_phase``, then measure FPS
with the player invulnerable nearby so the combat path is hot.

Run with:
    pytest "unit tests/integration/test_performance_boss_phases.py" -v -s
"""
from __future__ import annotations

import time

import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT, BOSS_PHASE2_HP, BOSS_PHASE3_HP,
    BOSS_DETECT_RANGE, BOSS_CHARGE_COOLDOWN,
)
from zones import ZoneID
from integration.conftest import measure_fps as _measure_fps

MIN_FPS = 40


def _setup_boss_combat(gv):
    """Common scenery — Zone 1, station + 2 turrets, boss spawned at
    world centre, player invulnerable and parked just inside aggro
    range so the boss fires every cooldown."""
    from sprites.building import create_building
    from combat_helpers import spawn_boss

    if gv._zone.zone_id != ZoneID.MAIN:
        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

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

    # Park the player within BOSS_DETECT_RANGE so the boss aggros.
    gv.player.center_x = gv._boss.center_x + (BOSS_DETECT_RANGE * 0.6)
    gv.player.center_y = gv._boss.center_y

    # Invulnerable for the duration of the measurement.
    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999


def _force_phase(gv, phase: int) -> None:
    """Coerce the boss into the requested phase by dropping HP below
    the threshold and calling _update_phase."""
    if phase == 2:
        gv._boss.hp = max(1, int(gv._boss.max_hp * (BOSS_PHASE2_HP - 0.05)))
    elif phase == 3:
        gv._boss.hp = max(1, int(gv._boss.max_hp * (BOSS_PHASE3_HP - 0.05)))
    else:
        raise ValueError(phase)
    gv._boss._update_phase()
    assert gv._boss._phase == phase


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 2 — charge attack windup + dash
# ═══════════════════════════════════════════════════════════════════════════

class TestBossPhase2Combat:
    def test_phase2_with_charge_active_above_threshold(
            self, real_game_view):
        """Phase 2 with the boss mid-charge.  We force the charge state
        directly so the measurement window is guaranteed to include
        the windup (visual telegraph) AND the dash (max-speed move).
        Without forcing, the 8 s charge cooldown would mean only 1
        charge per measurement."""
        gv = real_game_view
        _setup_boss_combat(gv)
        _force_phase(gv, 2)

        # Force into charge state — windup phase first, then the
        # measurement loop will also see the dash phase.
        boss = gv._boss
        boss._charging = True
        boss._charge_windup = 1.0      # 1 s of windup → catches in measurement
        boss._charge_timer = 0.8       # full dash duration
        boss._charge_cd = BOSS_CHARGE_COOLDOWN  # don't trigger another mid-measurement

        # Direction toward player, like _update_charge sets it
        import math as _math
        dx = gv.player.center_x - boss.center_x
        dy = gv.player.center_y - boss.center_y
        dist = _math.hypot(dx, dy)
        boss._charge_dir_x = dx / max(1.0, dist)
        boss._charge_dir_y = dy / max(1.0, dist)

        fps = _measure_fps(gv)
        print(f"  [perf-boss-p2] charge windup+dash: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Boss phase 2 (charge): {fps:.1f} FPS < {MIN_FPS}")

    def test_phase2_steady_state_above_threshold(
            self, real_game_view):
        """Phase 2 without an active charge — steady-state combat with
        2× shield regen and BOSS_SPEED_P2 movement.  Catches regressions
        in the per-tick phase branching that wouldn't show up while
        the charge animation dominates."""
        gv = real_game_view
        _setup_boss_combat(gv)
        _force_phase(gv, 2)

        fps = _measure_fps(gv)
        print(f"  [perf-boss-p2] steady state: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Boss phase 2 (steady): {fps:.1f} FPS < {MIN_FPS}")


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 3 — enraged: halved cooldowns, no shield regen
# ═══════════════════════════════════════════════════════════════════════════

class TestBossPhase3Combat:
    def test_phase3_enraged_above_threshold(self, real_game_view):
        """Phase 3 doubles cannon + spread fire rate, which doubles
        average projectile-list size.  Most likely place for a
        per-projectile cost regression to surface."""
        gv = real_game_view
        _setup_boss_combat(gv)
        _force_phase(gv, 3)

        fps = _measure_fps(gv)
        print(f"  [perf-boss-p3] enraged combat: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Boss phase 3 (enraged): {fps:.1f} FPS < {MIN_FPS}")

    def test_phase3_with_charge_active_above_threshold(
            self, real_game_view):
        """Phase 3 + active charge — worst-case combat scene: enraged
        weapon fire rate AND a dash in-flight.  Combines both Phase 3
        weapon doubling and the Phase-2-and-up charge cost."""
        gv = real_game_view
        _setup_boss_combat(gv)
        _force_phase(gv, 3)

        boss = gv._boss
        boss._charging = True
        boss._charge_windup = 1.0
        boss._charge_timer = 0.8
        boss._charge_cd = BOSS_CHARGE_COOLDOWN

        import math as _math
        dx = gv.player.center_x - boss.center_x
        dy = gv.player.center_y - boss.center_y
        dist = _math.hypot(dx, dy)
        boss._charge_dir_x = dx / max(1.0, dist)
        boss._charge_dir_y = dy / max(1.0, dist)

        fps = _measure_fps(gv)
        print(f"  [perf-boss-p3-charge] worst-case: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Boss phase 3 (enraged + charging): {fps:.1f} FPS < {MIN_FPS}")
