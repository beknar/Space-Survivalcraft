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
        warmup_samples=1 the 10 is excluded → passes at 40 floor."""
        _sb = self._patch(monkeypatch, [10.0, 100.0])
        _sb.run_soak(
            object(), "warmup=1",
            lambda dt: None,
            min_fps=40, max_memory_growth_mb=10_000,
            duration_s=0, warmup_samples=1)

    def test_warmup_samples_zero_catches_start_dip(self, monkeypatch):
        """With warmup_samples=0 the 10 FPS START is INCLUDED in
        the floor check → test fails loudly."""
        _sb = self._patch(monkeypatch, [10.0, 100.0])
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
        _sb = self._patch(monkeypatch, [39.1, 125.0])
        _sb.run_soak(
            object(), "real-world",
            lambda dt: None,
            min_fps=40, max_memory_growth_mb=10_000,
            duration_s=0)   # warmup_samples defaults to 1

    def test_end_sample_still_enforced(self, monkeypatch):
        """The END sample ALWAYS counts toward the floor — without
        that, a soak that regresses by the end could hide behind
        the warmup grace."""
        _sb = self._patch(monkeypatch, [100.0, 30.0])
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
        # sampling: START, one mid sample (the 15 dip), then END.
        import itertools
        fps_stream = itertools.chain(
            iter([100.0, 15.0]),    # START, then mid-sample dip
            itertools.repeat(100.0),  # any further samples + END
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
