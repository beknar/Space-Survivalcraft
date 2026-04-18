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
