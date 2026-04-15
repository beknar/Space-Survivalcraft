"""Soak tests for the AI Pilot patrol / engage / return loop.

Spawns AI-piloted parked ships around a Home Station in Zone 2 and
periodically teleports a fresh alien in and out of range so the AI
cycles through all three modes (``patrol`` → engage → fire → ``return``
→ ``patrol``) continuously for 5 minutes.

Fails if FPS drops below 40 or RSS grows by more than 50 MB — the same
thresholds used by every other soak test.

Run with:
    pytest "unit tests/integration/test_soak_ai_pilot.py" -v -s
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


def _get_rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def _measure_fps_quick(gv) -> float:
    return _measure_fps(gv, n_warmup=0, n_measure=FRAMES_PER_SAMPLE)


def _setup_ai_patrol(gv, ai_ship_count: int = 4):
    """Zone 2 + Home Station + ring of AI-piloted parked ships. Returns
    (home_x, home_y) for the churn loop to place/remove aliens near."""
    from sprites.building import create_building
    from sprites.parked_ship import ParkedShip

    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999
    if gv._zone.zone_id != ZoneID.ZONE2:
        gv._transition_zone(ZoneID.ZONE2)

    gv.building_list.clear()
    hx, hy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", tex, hx, hy, scale=0.5))

    gv._parked_ships.clear()
    for i in range(ai_ship_count):
        ang = 2 * math.pi * i / ai_ship_count
        ps = ParkedShip(
            gv._faction, gv._ship_type, 1,
            hx + math.cos(ang) * 250,
            hy + math.sin(ang) * 250,
        )
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.append(ps)
    # Park the player well outside patrol radius so combat on the AI
    # ring doesn't get routed to the player.
    gv.player.center_x = hx + 3000
    gv.player.center_y = hy + 3000
    return hx, hy


def _ai_patrol_churn_tick(gv, home_xy, step: int, dt: float) -> None:
    """One churn tick.

    Every ~2 seconds (120 frames) teleport a single zone-2 alien next to
    one of the AI ships so combat happens; in between, remove all aliens
    so the AI flips into ``return`` and then resumes patrol. Stretches
    the ship through every mode every cycle."""
    gv.player.hp = gv.player.max_hp
    gv.player.shields = gv.player.max_shields
    hx, hy = home_xy

    # Once every ~120 frames, ensure there is exactly one alien right on
    # top of one AI ship so it fires. Off-cycle frames clear the alien
    # list so return-mode can complete.
    zone = gv._zone
    aliens = getattr(zone, "_aliens", None)
    if aliens is not None:
        if step % 120 == 0 and len(gv._parked_ships) > 0:
            target_ship = gv._parked_ships[step // 120 % len(gv._parked_ships)]
            for a in aliens:
                a.center_x = -10000  # park every alien far away
                a.center_y = -10000
            if aliens:
                aliens[0].center_x = target_ship.center_x + 160
                aliens[0].center_y = target_ship.center_y
        elif step % 120 == 60:
            # Push every alien out of range so the AI must return.
            for a in aliens:
                a.center_x = hx + 10000
                a.center_y = hy + 10000

    gv.on_update(dt)
    gv.on_draw()


def _run_ai_soak(gv, label: str, home_xy) -> None:
    dt = 1 / 60
    step = 0

    for _ in range(WARMUP_FRAMES):
        _ai_patrol_churn_tick(gv, home_xy, step, dt)
        step += 1

    fps_start = _measure_fps_quick(gv)
    mem_start = _get_rss_mb()
    print(f"\n  [{label}] START: {fps_start:.1f} FPS, {mem_start:.0f} MB RSS")

    fps_min = fps_start
    frame_count = 0
    soak_start = time.perf_counter()
    last_sample = soak_start

    while True:
        elapsed = time.perf_counter() - soak_start
        if elapsed >= SOAK_DURATION_S:
            break
        for _ in range(60):
            _ai_patrol_churn_tick(gv, home_xy, step, dt)
            step += 1
            frame_count += 1
        now = time.perf_counter()
        if now - last_sample >= SAMPLE_INTERVAL_S:
            fps = _measure_fps_quick(gv)
            mem = _get_rss_mb()
            fps_min = min(fps_min, fps)
            print(f"  [{label}] {elapsed / 60:.1f}m: "
                  f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                  f"(+{mem - mem_start:.1f} MB)")
            last_sample = now

    fps_end = _measure_fps_quick(gv)
    mem_end = _get_rss_mb()
    fps_min = min(fps_min, fps_end)
    mem_growth = mem_end - mem_start
    print(f"  [{label}] END: {fps_end:.1f} FPS, {mem_end:.0f} MB RSS "
          f"(frames={frame_count})")

    assert fps_min >= MIN_FPS, (
        f"{label}: FPS dropped to {fps_min:.1f} "
        f"(threshold: {MIN_FPS})"
    )
    assert mem_growth <= MAX_MEMORY_GROWTH_MB, (
        f"{label}: memory grew by {mem_growth:.1f} MB "
        f"(threshold: {MAX_MEMORY_GROWTH_MB} MB). "
        f"Start={mem_start:.0f} MB, End={mem_end:.0f} MB"
    )


class TestSoakAIPilotPatrolCycle:
    def test_ai_pilot_full_mode_cycle_5min_soak(self, real_game_view):
        """4 AI-piloted parked ships cycle through patrol → engage →
        return → patrol every ~2 seconds for 5 minutes. Catches any
        cumulative leak in projectile spawn + alien-list traversal +
        mode transitions."""
        gv = real_game_view
        home = _setup_ai_patrol(gv, ai_ship_count=4)
        _run_ai_soak(gv, "AI Pilot patrol cycle", home)


class TestSoakAIPilotIdleOrbit:
    def test_ai_pilot_idle_orbit_5min_soak(self, real_game_view):
        """No aliens at all for the whole soak — AI ships just orbit
        the Home Station. Validates that the patrol loop itself has no
        drift or allocation bloat even without combat."""
        gv = real_game_view
        hx, hy = _setup_ai_patrol(gv, ai_ship_count=4)
        zone = gv._zone
        aliens = getattr(zone, "_aliens", None)
        if aliens is not None:
            for a in aliens:
                a.center_x = -10000
                a.center_y = -10000

        def noop(gv, home_xy, step, dt):
            gv.player.hp = gv.player.max_hp
            gv.on_update(dt)
            gv.on_draw()

        dt = 1 / 60
        step = 0
        for _ in range(WARMUP_FRAMES):
            noop(gv, (hx, hy), step, dt)
            step += 1
        fps_start = _measure_fps_quick(gv)
        mem_start = _get_rss_mb()
        print(f"\n  [AI Pilot idle orbit] START: "
              f"{fps_start:.1f} FPS, {mem_start:.0f} MB RSS")
        fps_min = fps_start
        frame_count = 0
        soak_start = time.perf_counter()
        last_sample = soak_start
        while True:
            elapsed = time.perf_counter() - soak_start
            if elapsed >= SOAK_DURATION_S:
                break
            for _ in range(60):
                noop(gv, (hx, hy), step, dt)
                step += 1
                frame_count += 1
            now = time.perf_counter()
            if now - last_sample >= SAMPLE_INTERVAL_S:
                fps = _measure_fps_quick(gv)
                mem = _get_rss_mb()
                fps_min = min(fps_min, fps)
                print(f"  [AI Pilot idle orbit] {elapsed / 60:.1f}m: "
                      f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                      f"(+{mem - mem_start:.1f} MB)")
                last_sample = now
        fps_end = _measure_fps_quick(gv)
        mem_end = _get_rss_mb()
        fps_min = min(fps_min, fps_end)
        mem_growth = mem_end - mem_start
        print(f"  [AI Pilot idle orbit] END: "
              f"{fps_end:.1f} FPS, {mem_end:.0f} MB RSS "
              f"(frames={frame_count})")
        assert fps_min >= MIN_FPS, (
            f"AI Pilot idle orbit: FPS dropped to {fps_min:.1f} "
            f"(threshold: {MIN_FPS})"
        )
        assert mem_growth <= MAX_MEMORY_GROWTH_MB, (
            f"AI Pilot idle orbit: memory grew by {mem_growth:.1f} MB "
            f"(threshold: {MAX_MEMORY_GROWTH_MB} MB)"
        )
