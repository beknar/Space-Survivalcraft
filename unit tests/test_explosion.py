"""Tests for sprites/explosion.py — Explosion, HitSpark, FireSpark lifecycle."""
from __future__ import annotations

import pytest

from sprites.explosion import Explosion, HitSpark, FireSpark


class TestHitSpark:
    def test_not_dead_initially(self):
        spark = HitSpark(100, 100)
        assert spark.dead is False

    def test_not_dead_before_duration(self):
        spark = HitSpark(100, 100)
        spark.update(HitSpark.DURATION * 0.5)
        assert spark.dead is False

    def test_dead_after_duration(self):
        spark = HitSpark(100, 100)
        spark.update(HitSpark.DURATION + 0.01)
        assert spark.dead is True

    def test_position_stored(self):
        spark = HitSpark(42.0, 99.0)
        assert spark.x == 42.0
        assert spark.y == 99.0


class TestFireSpark:
    def test_creates_particles(self):
        fs = FireSpark(100, 100)
        assert len(fs._particles) == FireSpark.PARTICLE_COUNT

    def test_not_dead_initially(self):
        fs = FireSpark(100, 100)
        assert fs.dead is False

    def test_dead_after_all_particles_expire(self):
        fs = FireSpark(100, 100)
        # Update well past the maximum particle lifetime
        fs.update(FireSpark.DURATION + 1.0)
        assert fs.dead is True

    def test_particles_move(self):
        fs = FireSpark(100, 100)
        old_positions = [(p.x, p.y) for p in fs._particles]
        fs.update(0.1)
        new_positions = [(p.x, p.y) for p in fs._particles]
        # At least some particles should have moved
        moved = sum(1 for o, n in zip(old_positions, new_positions) if o != n)
        assert moved > 0


class TestExplosion:
    def test_starts_at_frame_zero(self, dummy_texture_list):
        exp = Explosion(dummy_texture_list, 100, 100)
        assert exp._frame_idx == 0

    def test_advances_frames(self, dummy_texture_list):
        exp = Explosion(dummy_texture_list, 100, 100)
        # Update well past one frame interval
        exp.update_explosion(0.5)
        assert exp._frame_idx > 0

    def test_position(self, dummy_texture_list):
        exp = Explosion(dummy_texture_list, 42, 99)
        assert exp.center_x == 42
        assert exp.center_y == 99
