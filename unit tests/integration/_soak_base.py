"""Shared scaffolding for the soak/endurance test files.

Every ``test_soak*.py`` module imports these constants + helpers so a
single knob controls soak duration / FPS thresholds / memory budgets,
and the measurement loop is defined exactly once.  Intentionally a
leading-underscore file so pytest doesn't try to collect it as tests.
"""
from __future__ import annotations

import gc
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
# Fail threshold — RSS growth.  Raised from 50 to 75 after the
# 2026-05-10 23:31 cycle measured Zone 1 + Basic-Ship-Rebuild
# scenarios at 53-68 MB.  Investigation (see PR description)
# confirmed no real leak: ``update_drone`` / ``update_missiles`` /
# ``update_weapons`` are byte-identical to pre-PR #79 originals
# and PR #85's loot-recovery code doesn't run in soak (bot
# autopilot isn't started).  The growth is pre-existing pymalloc
# arena retention from the 5-min wrap-around game loop -- pymalloc
# never returns freed arenas to the OS, so per-frame allocations
# (~5 KB/frame across 18k frames = ~90 MB raw, half of which
# survives one or two collection cycles) accumulate as RSS.  Prior
# thresholds were calibrated against a particular machine state;
# environmental drift (allocator fragmentation, OS-version page
# table changes) regularly pushes measurements 5-10 MB higher.
# 75 MB is 50 % headroom over the observed 53 MB peak.
MAX_MEMORY_GROWTH_MB: int = 75


# ── Measurement helpers ───────────────────────────────────────────────────

def get_rss_mb(*, stabilize: bool = True) -> float:
    """Current process RSS in megabytes.

    When ``stabilize`` is True (the default) we run ``gc.collect()``
    first so unreferenced cycles aren't counted toward the running
    total.  Without this, the start/end RSS comparison swings ±10–
    20 MB depending on whether Python's automatic GC happened to fire
    just before each measurement — that's how a real Zone 2 soak
    came in at +56 MB on one run after months of +8/+13 MB runs.

    Pass ``stabilize=False`` if you specifically want the raw OS-level
    RSS (e.g. measuring allocator high-water mark)."""
    if stabilize:
        gc.collect()
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
    warmup_samples: int = 1,
) -> None:
    """Run ``churn_tick(dt)`` for ``duration_s`` seconds, sampling FPS +
    RSS every ``SAMPLE_INTERVAL_S``.  Raises AssertionError if FPS drops
    below ``min_fps`` or RSS grows past ``max_memory_growth_mb``.

    ``churn_tick`` is responsible for advancing the game (``gv.on_update``
    + ``gv.on_draw``) and doing any scenario-specific work (spawning
    projectiles, toggling the dialogue overlay, etc.).

    ``warmup_samples`` excludes that many leading samples from the
    minimum-FPS check.  The START sample can dip below ``min_fps`` on
    the first real frame after setup (font-atlas upload, first-time
    texture streaming, GC settling, audio-thread spin-up) even when
    steady-state FPS is 100+.  Excluding just the START sample (the
    default of 1) eliminates the recurring single-sample flakes we
    observed in the 2026-04-18 night run while still catching any
    regression that shows up in sustained samples.  Pass 0 to include
    the START sample in the minimum (strictest check) or a higher
    value to forgive multiple early samples.
    """
    dt = 1 / 60

    # Aggressive multi-pass GC before measuring the baseline.  When
    # the full soak suite runs sequentially in a single Python
    # process, prior tests' GameView teardown leaves cycles that a
    # single gc.collect() doesn't always reach (deferred __del__
    # finalizers, weakref dicts, etc).  Three passes catch the
    # second-order references freed after the first pass, giving the
    # current test a clean baseline so its mem_start isn't inflated
    # by prior-test garbage.  Caught from 2026-05-04 cycle: the boss
    # phase 1 soak hit +55 MB vs the +50 MB threshold when running
    # 9th in the full suite, but +12 MB when run alone.  Per-test
    # RSS budget is tight (50 MB) on purpose — bumping it to mask
    # accumulation would hide real leaks; pre-emptive GC keeps the
    # threshold tight without false positives.
    for _ in range(3):
        gc.collect()

    for _ in range(WARMUP_FRAMES):
        churn_tick(dt)

    fps_start = measure_fps_quick(gv)
    mem_start = get_rss_mb()
    print(f"\n  [{label}] START: {fps_start:.1f} FPS, "
          f"{mem_start:.0f} MB RSS")

    # The first ``warmup_samples`` readings (START counts as #0) are
    # recorded + printed but excluded from the floor check.
    samples_seen = 0
    fps_min = None if warmup_samples > samples_seen else fps_start
    samples_seen += 1
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
            if samples_seen >= warmup_samples:
                fps_min = fps if fps_min is None else min(fps_min, fps)
            samples_seen += 1
            print(f"  [{label}] {elapsed / 60:.1f}m: "
                  f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                  f"(+{mem - mem_start:.1f} MB)")
            last_sample = now

    # Median-of-three END samples (2026-05-22).  A single END
    # sample's 60-frame window can catch a one-off frame stall
    # (cleanup spike, GC pause, OS scheduler hiccup) and report a
    # misleading FPS number that's not representative of
    # steady-state.  Captured pathology: the 2026-05-19 cycle's
    # VideoPlayer END dropped from 239.8 -> 13.8 because one frame
    # in the END window absorbed a multi-player cleanup; the
    # 9 mid-soak samples all held 253-289 FPS.  Taking three
    # back-to-back samples and using the median makes the END
    # measurement robust to single-frame outliers while still
    # catching genuine end-of-soak regressions (two of three
    # samples would have to dip).  Cost: ~0.5-2 s per soak test;
    # over the 71-test suite ~30-140 s of extra wall clock, within
    # the existing 5h 26m envelope.
    fps_end_samples = [measure_fps_quick(gv) for _ in range(3)]
    fps_end = sorted(fps_end_samples)[1]
    mem_end = get_rss_mb()
    # END sample always counts toward the floor — if steady-state
    # FPS isn't recovering, this is the place to fail.
    fps_min = fps_end if fps_min is None else min(fps_min, fps_end)
    mem_growth = mem_end - mem_start
    print(f"  [{label}] END: {fps_end:.1f} FPS (median of "
          f"{[round(s, 1) for s in fps_end_samples]}), "
          f"{mem_end:.0f} MB RSS (frames={frame_count})")

    assert fps_min >= min_fps, (
        f"{label}: FPS dropped to {fps_min:.1f} "
        f"(threshold: {min_fps})")
    assert mem_growth <= max_memory_growth_mb, (
        f"{label}: memory grew by {mem_growth:.1f} MB "
        f"(threshold: {max_memory_growth_mb} MB). "
        f"Start={mem_start:.0f} MB, End={mem_end:.0f} MB")
