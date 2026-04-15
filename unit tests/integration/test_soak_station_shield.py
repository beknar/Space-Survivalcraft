"""Soak test for the station shield + shielded AI fleet.

Run explicitly with:
    pytest "unit tests/integration/test_soak_station_shield.py" -v -s

Builds a Home Station + Shield Generator in the Nebula, spawns four
AI-piloted parked ships with their yellow bubbles, and alternates
between (a) pelting the station shield with alien fire so the absorb
path is hot and (b) letting the shield sit dormant so the sprite
draw + idle tick is exercised. Runs for 5 minutes and fails if FPS
drops below 40 or RSS grows by more than 50 MB.
"""
from __future__ import annotations

import math
import os
import time

import psutil

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID
from integration.conftest import measure_fps as _measure_fps


SOAK_DURATION_S = 300
SAMPLE_INTERVAL_S = 30
FRAMES_PER_SAMPLE = 60
WARMUP_FRAMES = 30
MIN_FPS = 40
MAX_MEMORY_GROWTH_MB = 50


def _rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def _fps(gv) -> float:
    return _measure_fps(gv, n_warmup=0, n_measure=FRAMES_PER_SAMPLE)


def _setup_shielded_zone2(gv):
    """Zone 2 + Home Station + Shield Generator + 4 AI-piloted ships."""
    from sprites.building import create_building
    from sprites.parked_ship import ParkedShip

    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999
    if gv._zone.zone_id != ZoneID.ZONE2:
        gv._transition_zone(ZoneID.ZONE2)

    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    hs_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", hs_tex, cx, cy, scale=0.5))
    sg_tex = gv._building_textures["Shield Generator"]
    gv.building_list.append(create_building(
        "Shield Generator", sg_tex, cx + 90, cy, scale=0.5))
    gv._station_shield_hp = 0
    gv._station_shield_sprite = None

    gv._parked_ships.clear()
    for i in range(4):
        ang = 2 * math.pi * i / 4
        ps = ParkedShip(
            gv._faction, gv._ship_type, 1,
            cx + math.cos(ang) * 260,
            cy + math.sin(ang) * 260,
        )
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.append(ps)

    gv.player.center_x = cx + 4000
    gv.player.center_y = cy + 4000
    return cx, cy


def _churn_tick(gv, cx, cy, step: int, dt: float) -> None:
    """Alternate between flooding the station shield with alien fire and
    letting it sit dormant so both code paths run."""
    from sprites.projectile import Projectile
    from constants import ALIEN_LASER_SPEED, ALIEN_LASER_RANGE

    gv.player.hp = gv.player.max_hp
    gv.player.shields = gv.player.max_shields

    if step % 60 == 0:
        # Top up the station shield so the absorb path keeps firing.
        gv._station_shield_hp = max(gv._station_shield_hp, 80)
        # Inject a laser aimed at the station every second.
        proj = Projectile(
            gv._alien_laser_tex, cx + 500.0, cy, 270,
            ALIEN_LASER_SPEED, ALIEN_LASER_RANGE, damage=10)
        gv.alien_projectile_list.append(proj)
    gv.on_update(dt)
    gv.on_draw()


def _run(gv, label: str, cx: float, cy: float) -> None:
    dt = 1 / 60
    step = 0
    for _ in range(WARMUP_FRAMES):
        _churn_tick(gv, cx, cy, step, dt)
        step += 1

    fps_start = _fps(gv)
    mem_start = _rss_mb()
    print(f"\n  [{label}] START: {fps_start:.1f} FPS, "
          f"{mem_start:.0f} MB RSS")

    fps_min = fps_start
    frame_count = 0
    soak_start = time.perf_counter()
    last_sample = soak_start

    while True:
        elapsed = time.perf_counter() - soak_start
        if elapsed >= SOAK_DURATION_S:
            break
        for _ in range(60):
            _churn_tick(gv, cx, cy, step, dt)
            step += 1
            frame_count += 1
        now = time.perf_counter()
        if now - last_sample >= SAMPLE_INTERVAL_S:
            fps = _fps(gv)
            mem = _rss_mb()
            fps_min = min(fps_min, fps)
            print(f"  [{label}] {elapsed / 60:.1f}m: "
                  f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                  f"(+{mem - mem_start:.1f} MB)")
            last_sample = now

    fps_end = _fps(gv)
    mem_end = _rss_mb()
    fps_min = min(fps_min, fps_end)
    mem_growth = mem_end - mem_start
    print(f"  [{label}] END: {fps_end:.1f} FPS, {mem_end:.0f} MB RSS "
          f"(frames={frame_count})")

    assert fps_min >= MIN_FPS, (
        f"{label}: FPS dropped to {fps_min:.1f} "
        f"(threshold: {MIN_FPS})")
    assert mem_growth <= MAX_MEMORY_GROWTH_MB, (
        f"{label}: memory grew by {mem_growth:.1f} MB "
        f"(threshold: {MAX_MEMORY_GROWTH_MB} MB). "
        f"Start={mem_start:.0f} MB, End={mem_end:.0f} MB")


class TestSoakStationShield:
    def test_station_shield_and_shielded_fleet_5min_soak(
            self, real_game_view):
        """5-minute soak with the station shield cycling between absorb
        and idle, the 4-ship shielded AI fleet patrolling, and Zone 2
        gameplay ticking in the background."""
        gv = real_game_view
        cx, cy = _setup_shielded_zone2(gv)
        _run(gv, "Station shield + AI fleet", cx, cy)
