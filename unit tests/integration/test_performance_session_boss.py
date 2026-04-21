"""Performance tests for the boss + drop tweaks landed this session.

Scenario set is worst-case for the new code paths:

  * Nebula boss chasing the player across force walls (segment-cross
    revert + wall-repulsion steering on every frame)
  * Nebula boss with a dense asteroid field along its path (crush
    pass walks + destroys many rocks per frame)
  * HP + shield bar draw overhead (one bar pair per live boss)
  * Station defenders targeting a Nebula boss (turret +
    MissileArray bosses list walk every rescan)

All cases must sustain ``MIN_FPS`` (40) on a reference machine.

Run with:
    pytest "unit tests/integration/test_performance_session_boss.py" -v -s
"""
from __future__ import annotations

import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT, BOSS_DETECT_RANGE,
    FORCE_WALL_LENGTH,
)
from zones import ZoneID

MIN_FPS = 40

from integration.conftest import measure_fps as _measure_fps


# ──────────────────────────────────────────────────────────────────────────
#  Shared setup
# ──────────────────────────────────────────────────────────────────────────

def _setup_nebula_with_station(gv):
    """Zone 2 + Home Station + 2 turrets + Missile Array + Nebula boss
    within aggro range.  Player parked so attacks fire every cooldown."""
    from sprites.building import create_building
    from combat_helpers import spawn_nebula_boss

    gv._transition_zone(ZoneID.ZONE2)
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))
    for bt, ox in (("Turret 1", 80), ("Turret 2", -80),
                    ("Missile Array", 160)):
        t_tex = gv._building_textures[bt]
        laser = gv._turret_laser_tex if "Turret" in bt else None
        gv.building_list.append(create_building(
            bt, t_tex, cx + ox, cy,
            laser_tex=laser, scale=0.5))

    # Wormholes cleared so the centre-parked player doesn't zone-hop.
    gv._wormholes = []
    if hasattr(gv._zone, "_wormholes"):
        gv._zone._wormholes = []

    # Afford + spawn.
    gv.inventory._items[(0, 0)] = ("iron", 500)
    gv.inventory._mark_dirty()
    gv._nebula_boss = None
    assert spawn_nebula_boss(gv) is True

    # Park player so gas + cone + cannon all fire.
    gv.player.center_x = gv._nebula_boss.center_x + (BOSS_DETECT_RANGE * 0.6)
    gv.player.center_y = gv._nebula_boss.center_y
    gv.player.max_hp = gv.player.hp = 999999
    gv.player.max_shields = gv.player.shields = 999999


# ──────────────────────────────────────────────────────────────────────────
#  Force-wall scenarios
# ──────────────────────────────────────────────────────────────────────────

class TestNebulaBossForceWallFps:
    def test_single_wall_between_boss_and_player(self, real_game_view):
        """One force wall dead on the boss's approach vector.  Tests
        the per-frame ``segment_crosses_any_wall`` + wall repulsion
        pass and the position-revert hot path."""
        gv = real_game_view
        _setup_nebula_with_station(gv)
        nb = gv._nebula_boss
        from sprites.force_wall import ForceWall
        mid_x = (nb.center_x + gv.player.center_x) * 0.5
        gv._force_walls.clear()
        gv._force_walls.append(ForceWall(mid_x, nb.center_y, heading=90.0))
        fps = _measure_fps(gv)
        print(f"  [perf-session-boss] nebula + 1 wall: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Nebula + 1 wall: {fps:.1f} FPS < {MIN_FPS}")

    def test_six_walls_worst_case(self, real_game_view):
        """Player stacks six walls in a semi-circle around the station —
        exercises the O(N_walls) per-frame segment-crossing check."""
        gv = real_game_view
        _setup_nebula_with_station(gv)
        from sprites.force_wall import ForceWall
        nb = gv._nebula_boss
        gv._force_walls.clear()
        import math as _math
        for i in range(6):
            theta = i * _math.tau / 6
            x = gv.player.center_x + _math.cos(theta) * 250
            y = gv.player.center_y + _math.sin(theta) * 250
            gv._force_walls.append(
                ForceWall(x, y, heading=_math.degrees(theta) + 90))
        fps = _measure_fps(gv)
        print(f"  [perf-session-boss] nebula + 6 walls: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Nebula + 6 walls: {fps:.1f} FPS < {MIN_FPS}")


# ──────────────────────────────────────────────────────────────────────────
#  Asteroid crush
# ──────────────────────────────────────────────────────────────────────────

class TestNebulaBossAsteroidCrushFps:
    def test_dense_asteroid_field_in_path(self, real_game_view):
        """Sprinkle 30 asteroids around the boss-to-player corridor so
        the per-frame crush pass has plenty of near hits."""
        gv = real_game_view
        _setup_nebula_with_station(gv)
        from sprites.asteroid import IronAsteroid
        from sprites.copper_asteroid import CopperAsteroid
        z = gv._zone
        z._iron_asteroids.clear()
        z._copper_asteroids.clear()
        z._double_iron.clear()
        z._wanderers.clear()
        nb = gv._nebula_boss
        import random
        random.seed(42)
        for _ in range(20):
            ox = random.uniform(-400, 400)
            oy = random.uniform(-400, 400)
            z._iron_asteroids.append(
                IronAsteroid(z._iron_tex, nb.center_x + ox, nb.center_y + oy))
        for _ in range(10):
            ox = random.uniform(-400, 400)
            oy = random.uniform(-400, 400)
            z._copper_asteroids.append(
                CopperAsteroid(z._copper_tex,
                                nb.center_x + ox, nb.center_y + oy))
        fps = _measure_fps(gv)
        print(f"  [perf-session-boss] nebula + 30 nearby asteroids: "
              f"{fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Nebula crush pass: {fps:.1f} FPS < {MIN_FPS}")


# ──────────────────────────────────────────────────────────────────────────
#  Both bosses alive — HP/shield bars draw for each
# ──────────────────────────────────────────────────────────────────────────

class TestBossHealthBarsFps:
    def test_double_and_nebula_boss_bars(self, real_game_view):
        """Both bosses alive + station + turrets.  The new
        ``_draw_boss_health_bars`` pass iterates both bosses and
        renders HP + shield bars each frame."""
        gv = real_game_view
        _setup_nebula_with_station(gv)
        # Also spawn the Double Star boss so both bars render.
        from combat_helpers import spawn_boss
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        spawn_boss(gv, cx, cy)
        fps = _measure_fps(gv)
        print(f"  [perf-session-boss] both bosses + bars: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Both bosses health-bar draw: {fps:.1f} FPS < {MIN_FPS}")


# ──────────────────────────────────────────────────────────────────────────
#  Station defenders scanning both boss-targets every frame
# ──────────────────────────────────────────────────────────────────────────

class TestStationDefendersVsNebulaFps:
    def test_many_turrets_targeting_nebula(self, real_game_view):
        """6 turrets + 2 missile arrays active, rescan walks
        ``bosses=[gv._boss, gv._nebula_boss]`` — verifies the widened
        target-selection path holds FPS under load."""
        gv = real_game_view
        _setup_nebula_with_station(gv)
        from sprites.building import create_building
        nb = gv._nebula_boss
        # Add 4 extra turrets ringing the boss.
        import math as _math
        for i in range(4):
            theta = i * _math.tau / 4
            ox = _math.cos(theta) * 200
            oy = _math.sin(theta) * 200
            t = create_building(
                "Turret 2", gv._building_textures["Turret 2"],
                nb.center_x + ox, nb.center_y + oy,
                laser_tex=gv._turret_laser_tex, scale=0.5)
            gv.building_list.append(t)
        fps = _measure_fps(gv)
        print(f"  [perf-session-boss] 6 turrets vs nebula: {fps:.1f} FPS")
        assert fps >= MIN_FPS, (
            f"Turret-heavy nebula encounter: {fps:.1f} FPS < {MIN_FPS}")
