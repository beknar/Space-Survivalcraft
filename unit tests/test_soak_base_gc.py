"""Tests for the gc-stabilization in ``integration/_soak_base.get_rss_mb``.

The 5-minute Zone 2 soak occasionally tripped the 50 MB memory
growth ceiling on full integration runs (one run hit +56 MB after
months of +8 / +13 MB).  Forcing ``gc.collect()`` before reading
RSS makes start/end measurements compare two GC-stabilized
snapshots, killing the variance.

These tests live in the fast suite so they run on every commit.
"""
from __future__ import annotations

import os
import sys

import pytest

# Make integration package importable from the fast-suite directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "integration"))

from integration._soak_base import get_rss_mb


class TestGetRssMb:
    def test_default_stabilizes_with_gc_collect(self, monkeypatch):
        """``get_rss_mb()`` (no kwargs) must run ``gc.collect()`` so
        the returned RSS reflects a freshly-collected heap."""
        import gc as _gc
        calls = {"n": 0}
        real = _gc.collect

        def spy(*a, **kw):
            calls["n"] += 1
            return real(*a, **kw)

        monkeypatch.setattr(_gc, "collect", spy)
        get_rss_mb()
        assert calls["n"] == 1, (
            "get_rss_mb did not call gc.collect — RSS measurements "
            "will swing with whenever automatic GC happened to fire")

    def test_stabilize_false_skips_gc(self, monkeypatch):
        """The escape hatch must work — ``stabilize=False`` returns
        raw OS-level RSS without paying for a collection cycle."""
        import gc as _gc
        calls = {"n": 0}

        def spy(*a, **kw):
            calls["n"] += 1
            return 0

        monkeypatch.setattr(_gc, "collect", spy)
        get_rss_mb(stabilize=False)
        assert calls["n"] == 0

    def test_returns_megabytes_as_float(self):
        rss = get_rss_mb()
        assert isinstance(rss, float)
        # Sanity bounds — anything within a couple decades of MB is fine.
        assert 1.0 < rss < 100_000.0

    def test_repeated_calls_return_close_values(self):
        """Two back-to-back stabilized RSS reads should agree within
        a small slack (no foreign allocator activity in between)."""
        a = get_rss_mb()
        b = get_rss_mb()
        assert abs(a - b) < 5.0, (
            f"Stabilized RSS swung from {a:.1f} to {b:.1f} MB — "
            f"GC stabilization may not be working")


class TestRunSoakWarmupSamples:
    """The warmup-grace-window fix for cold-start FPS dips.

    The 2026-04-18 night run saw 3 soak failures (StationInfoZone2,
    StationShield, TelemetryNoCrash) all dipping below the 40 FPS
    floor on the very first sample while steady-state held above
    100.  ``run_soak`` now excludes the first ``warmup_samples``
    readings from the minimum-FPS check so those cold-start dips
    no longer fail the suite.

    NOTE: these tests pass ``duration_s=0`` explicitly — the default
    is captured at function-definition time so monkeypatching
    ``SOAK_DURATION_S`` on the module doesn't affect the default.
    """

    @staticmethod
    def _patch(monkeypatch, fps_values):
        """Install a FPS iterator + constant-RSS stub + zero warmup
        frames so the call completes in well under a second."""
        from integration import _soak_base as _sb
        it = iter(fps_values)
        monkeypatch.setattr(
            _sb, "measure_fps_quick", lambda *_a, **_kw: next(it))
        monkeypatch.setattr(_sb, "get_rss_mb", lambda *_a, **_kw: 100.0)
        monkeypatch.setattr(_sb, "WARMUP_FRAMES", 0)
        return _sb

    def test_warmup_samples_one_excludes_start_cold_dip(self, monkeypatch):
        """START = 10 FPS (cold), END = 100 FPS (steady).  With
        warmup_samples=1 the 10 is excluded → passes at 40 floor.

        END now consumes 3 samples (median-of-three, see
        ``TestRunSoakEndMedianSampling``); supply enough values."""
        _sb = self._patch(monkeypatch, [10.0, 100.0, 100.0, 100.0])
        _sb.run_soak(
            object(), "warmup=1",
            lambda dt: None,
            min_fps=40, max_memory_growth_mb=10_000,
            duration_s=0, warmup_samples=1)

    def test_warmup_samples_zero_catches_start_dip(self, monkeypatch):
        """With warmup_samples=0 the 10 FPS START is INCLUDED in
        the floor check → test fails loudly."""
        _sb = self._patch(monkeypatch, [10.0, 100.0, 100.0, 100.0])
        with pytest.raises(AssertionError, match="FPS dropped to"):
            _sb.run_soak(
                object(), "warmup=0",
                lambda dt: None,
                min_fps=40, max_memory_growth_mb=10_000,
                duration_s=0, warmup_samples=0)

    def test_warmup_samples_defaults_to_one(self, monkeypatch):
        """Default behaviour: START is excluded so cold-start dips
        don't fail.  Mirrors the real 2026-04-18 night pattern
        where TestSoakStationInfoZone2 dipped to 39.1 FPS at START
        but steady-state held at 125+."""
        _sb = self._patch(monkeypatch, [39.1, 125.0, 125.0, 125.0])
        _sb.run_soak(
            object(), "real-world",
            lambda dt: None,
            min_fps=40, max_memory_growth_mb=10_000,
            duration_s=0)   # warmup_samples defaults to 1

    def test_end_sample_still_enforced(self, monkeypatch):
        """The END sample ALWAYS counts toward the floor — without
        that, a soak that regresses by the end could hide behind
        the warmup grace.

        END is now the median of 3 samples; supply 3 sustained
        below-floor reads so the median = 30 fails the floor."""
        _sb = self._patch(monkeypatch, [100.0, 30.0, 30.0, 30.0])
        with pytest.raises(AssertionError, match="FPS dropped to 30"):
            _sb.run_soak(
                object(), "end-regression",
                lambda dt: None,
                min_fps=40, max_memory_growth_mb=10_000,
                duration_s=0)

    def test_mid_sample_regression_still_caught(self, monkeypatch):
        """Steady-state dips (any sample after warmup_samples) must
        still fail the floor — the grace window is only for cold
        start, not a permanent get-out-of-jail card."""
        from integration import _soak_base as _sb
        # Enough FPS entries for a couple of loop ticks worth of
        # sampling: START, one mid sample (the 15 dip), then 3
        # END samples (median-of-three).
        import itertools
        fps_stream = itertools.chain(
            iter([100.0, 15.0]),       # START, then mid-sample dip
            itertools.repeat(100.0),   # any further samples + END
        )
        monkeypatch.setattr(
            _sb, "measure_fps_quick", lambda *_a, **_kw: next(fps_stream))
        monkeypatch.setattr(_sb, "get_rss_mb", lambda *_a, **_kw: 100.0)
        monkeypatch.setattr(_sb, "WARMUP_FRAMES", 0)
        monkeypatch.setattr(_sb, "SAMPLE_INTERVAL_S", 0)

        with pytest.raises(AssertionError, match="FPS dropped to 15"):
            _sb.run_soak(
                object(), "mid-regression",
                lambda dt: None,
                min_fps=40, max_memory_growth_mb=10_000,
                duration_s=0.05)


class TestRunSoakEndMedianSampling:
    """The 2026-05-22 fix: END FPS is the median of three back-to-
    back samples, not a single measurement.  A one-off frame stall
    in a single 60-frame END window no longer produces a misleading
    FPS number unrepresentative of steady-state.  Captured pathology:
    the 2026-05-19 cycle's VideoPlayer END dropped from 239.8 -> 13.8
    because one frame absorbed a multi-player cleanup; the 9 mid-soak
    samples all held 253-289 FPS."""

    @staticmethod
    def _patch(monkeypatch, fps_values):
        from integration import _soak_base as _sb
        it = iter(fps_values)
        monkeypatch.setattr(
            _sb, "measure_fps_quick", lambda *_a, **_kw: next(it))
        monkeypatch.setattr(_sb, "get_rss_mb", lambda *_a, **_kw: 100.0)
        monkeypatch.setattr(_sb, "WARMUP_FRAMES", 0)
        return _sb

    def test_end_median_robust_to_single_low_sample(
            self, monkeypatch):
        """One bad END sample sandwiched between two good ones --
        the median picks the good value and the test passes the
        floor.  Reproduces the VideoPlayer 13.8-vs-260 scenario."""
        # START 100, END samples [200, 13, 200] -- median 200.
        _sb = self._patch(monkeypatch, [100.0, 200.0, 13.0, 200.0])
        _sb.run_soak(
            object(), "single-stall",
            lambda dt: None,
            min_fps=40, max_memory_growth_mb=10_000,
            duration_s=0)

    def test_end_median_robust_to_single_high_sample(
            self, monkeypatch):
        """Symmetric: a sustained END regression must NOT be masked
        by one fluke high sample.  END samples [10, 10, 200] --
        median 10 catches the regression."""
        _sb = self._patch(monkeypatch, [100.0, 10.0, 10.0, 200.0])
        with pytest.raises(AssertionError, match="FPS dropped to 10"):
            _sb.run_soak(
                object(), "sustained-end-regression",
                lambda dt: None,
                min_fps=40, max_memory_growth_mb=10_000,
                duration_s=0)

    def test_end_median_takes_middle_value_when_sorted(
            self, monkeypatch):
        """Median is the middle of three sorted values regardless
        of input order -- pins the math, not a specific ordering."""
        # END samples [100, 50, 75] sort to [50, 75, 100], median 75.
        _sb = self._patch(monkeypatch, [200.0, 100.0, 50.0, 75.0])
        # min_fps=70 → 75 passes, 50 would have failed under
        # single-sample.
        _sb.run_soak(
            object(), "median-middle",
            lambda dt: None,
            min_fps=70, max_memory_growth_mb=10_000,
            duration_s=0)

    def test_end_median_with_all_three_samples_below_floor_fails(
            self, monkeypatch):
        """Sustained END regression -- all three samples below
        floor -- the median is below floor too, test fails.  This
        is the case the median protects against false negatives
        for: a real end-of-soak regression still gets caught."""
        _sb = self._patch(monkeypatch, [100.0, 20.0, 25.0, 22.0])
        with pytest.raises(AssertionError, match="FPS dropped to"):
            _sb.run_soak(
                object(), "all-three-below",
                lambda dt: None,
                min_fps=40, max_memory_growth_mb=10_000,
                duration_s=0)

    def test_end_consumes_exactly_three_samples(
            self, monkeypatch):
        """Pin the exact call count -- a future "compromise" between
        speed and robustness might be tempted to drop back to one
        or scale up to many, both of which break the cost / variance
        balance.  Three is the smallest odd count that gives median
        outlier-robustness."""
        from integration import _soak_base as _sb
        calls = {"n": 0}
        # START sample is also via measure_fps_quick -- count is
        # 1 + 3 = 4 total for a duration_s=0 soak (no mid samples).
        fps_stream = iter([100.0] * 10)

        def counter(*a, **kw):
            calls["n"] += 1
            return next(fps_stream)

        monkeypatch.setattr(_sb, "measure_fps_quick", counter)
        monkeypatch.setattr(_sb, "get_rss_mb", lambda *_a, **_kw: 100.0)
        monkeypatch.setattr(_sb, "WARMUP_FRAMES", 0)
        _sb.run_soak(
            object(), "call-count",
            lambda dt: None,
            min_fps=40, max_memory_growth_mb=10_000,
            duration_s=0)
        # 1 START + 3 END = 4.
        assert calls["n"] == 4, (
            f"expected 1 START + 3 END measure_fps_quick calls, "
            f"got {calls['n']}")
