"""Shared scaffolding for the soak/endurance test files.

Every ``test_soak*.py`` module imports these constants + helpers so a
single knob controls soak duration / FPS thresholds / memory budgets,
and the measurement loop is defined exactly once.  Intentionally a
leading-underscore file so pytest doesn't try to collect it as tests.
"""
from __future__ import annotations

import os
import time
from typing import Callable

import psutil

from integration.conftest import measure_fps as _measure_fps


# ── Configuration (shared across every soak test) ─────────────────────────

SOAK_DURATION_S: int = 300          # 5 minutes
SAMPLE_INTERVAL_S: int = 30         # FPS + RSS sample cadence
FRAMES_PER_SAMPLE: int = 60         # frames averaged per FPS sample
WARMUP_FRAMES: int = 30             # frames ticked before the first sample
MIN_FPS: int = 40                   # fail threshold — min FPS
MAX_MEMORY_GROWTH_MB: int = 50      # fail threshold — RSS growth


# ── Measurement helpers ───────────────────────────────────────────────────

def get_rss_mb() -> float:
    """Current process RSS in megabytes."""
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def measure_fps_quick(gv, n: int = FRAMES_PER_SAMPLE) -> float:
    """Quick FPS sample without warmup (soak tests warm up separately)."""
    return _measure_fps(gv, n_warmup=0, n_measure=n)


def make_invulnerable(gv) -> None:
    """Disable player death for the duration of a soak test.  Without
    this, continuous combat kills the player in ~30 s and the test
    spends the remaining 4.5 minutes in the death-screen state."""
    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999


# ── Core loop ─────────────────────────────────────────────────────────────

def run_soak(
    gv,
    label: str,
    churn_tick: Callable[[float], None],
    min_fps: int = MIN_FPS,
    max_memory_growth_mb: int = MAX_MEMORY_GROWTH_MB,
    duration_s: int = SOAK_DURATION_S,
) -> None:
    """Run ``churn_tick(dt)`` for ``duration_s`` seconds, sampling FPS +
    RSS every ``SAMPLE_INTERVAL_S``.  Raises AssertionError if FPS drops
    below ``min_fps`` or RSS grows past ``max_memory_growth_mb``.

    ``churn_tick`` is responsible for advancing the game (``gv.on_update``
    + ``gv.on_draw``) and doing any scenario-specific work (spawning
    projectiles, toggling the dialogue overlay, etc.).
    """
    dt = 1 / 60

    for _ in range(WARMUP_FRAMES):
        churn_tick(dt)

    fps_start = measure_fps_quick(gv)
    mem_start = get_rss_mb()
    print(f"\n  [{label}] START: {fps_start:.1f} FPS, "
          f"{mem_start:.0f} MB RSS")

    fps_min = fps_start
    frame_count = 0
    soak_start = time.perf_counter()
    last_sample = soak_start

    while True:
        elapsed = time.perf_counter() - soak_start
        if elapsed >= duration_s:
            break
        for _ in range(60):
            churn_tick(dt)
            frame_count += 1
        now = time.perf_counter()
        if now - last_sample >= SAMPLE_INTERVAL_S:
            fps = measure_fps_quick(gv)
            mem = get_rss_mb()
            fps_min = min(fps_min, fps)
            print(f"  [{label}] {elapsed / 60:.1f}m: "
                  f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                  f"(+{mem - mem_start:.1f} MB)")
            last_sample = now

    fps_end = measure_fps_quick(gv)
    mem_end = get_rss_mb()
    fps_min = min(fps_min, fps_end)
    mem_growth = mem_end - mem_start
    print(f"  [{label}] END: {fps_end:.1f} FPS, {mem_end:.0f} MB RSS "
          f"(frames={frame_count})")

    assert fps_min >= min_fps, (
        f"{label}: FPS dropped to {fps_min:.1f} "
        f"(threshold: {min_fps})")
    assert mem_growth <= max_memory_growth_mb, (
        f"{label}: memory grew by {mem_growth:.1f} MB "
        f"(threshold: {max_memory_growth_mb} MB). "
        f"Start={mem_start:.0f} MB, End={mem_end:.0f} MB")
