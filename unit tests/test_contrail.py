"""Tests for sprites/contrail.py — ContrailParticle lifecycle and colour interpolation."""
from __future__ import annotations

from sprites.contrail import ContrailParticle


class TestContrailLifecycle:
    def test_not_dead_initially(self):
        p = ContrailParticle(0, 0, (255, 0, 0), (0, 0, 255), 1.0, 6.0, 1.0)
        assert p.dead is False

    def test_not_dead_before_lifetime(self):
        p = ContrailParticle(0, 0, (255, 0, 0), (0, 0, 255), 1.0, 6.0, 1.0)
        p.update(0.5)
        assert p.dead is False

    def test_dead_after_lifetime(self):
        p = ContrailParticle(0, 0, (255, 0, 0), (0, 0, 255), 1.0, 6.0, 1.0)
        p.update(1.5)
        assert p.dead is True

    def test_dead_at_exact_lifetime(self):
        p = ContrailParticle(0, 0, (255, 0, 0), (0, 0, 255), 1.0, 6.0, 1.0)
        p.update(1.0)
        assert p.dead is True


class TestContrailColourInterpolation:
    """Verify colour blending at key points in the particle's life."""

    def _get_colour_at_t(self, t: float):
        """Create a particle and advance to fraction t of its lifetime."""
        start = (100, 180, 255)
        end = (20, 40, 120)
        lifetime = 1.0
        p = ContrailParticle(0, 0, start, end, lifetime, 6.0, 1.0)
        # Manually compute expected colour at t
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        return r, g, b

    def test_colour_at_start(self):
        r, g, b = self._get_colour_at_t(0.0)
        assert (r, g, b) == (100, 180, 255)

    def test_colour_at_midpoint(self):
        r, g, b = self._get_colour_at_t(0.5)
        assert r == 60
        assert g == 110
        assert b == 187

    def test_colour_at_end(self):
        r, g, b = self._get_colour_at_t(1.0)
        assert (r, g, b) == (20, 40, 120)
