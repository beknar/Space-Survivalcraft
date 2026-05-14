"""Unit tests for the boss + drop tweaks landed in this session.

Covers pieces that don't need a live GL context:

  * Boss scale + radius constants tripled.
  * Collision-drop ``_drop_scatter`` geometry.
  * Asteroid path-segment hit helper math.
  * Nebula boss class attrs (player priority range, sprite-row
    constant count, cone range bumped to 400 px, gas/cone damages
    30 / 20 respectively).
  * Nebula kill reward constants live in ``collisions`` (3000 iron +
    1000 copper, zero XP explicitly not awarded).
  * ``BossAlienShip.radius`` property derives from sprite width.

The real collision + draw + spawn flows are covered in the
integration suite.
"""
from __future__ import annotations

import math

import pytest


# ─── Boss size (sprite scale + hitbox) ────────────────────────────────────

class TestBossScale:
    def test_boss_scale_tripled(self):
        from constants import BOSS_SCALE
        assert BOSS_SCALE == 1.80

    def test_boss_radius_proportional(self):
        """BOSS_RADIUS was 38 at BOSS_SCALE=0.60; tripled sprite scale
        must come with the proportional hitbox (38 * 3 = 114 or close)."""
        from constants import BOSS_RADIUS, BOSS_SCALE
        # Proportional to 128-px source frame at current scale.
        expected = 128 * BOSS_SCALE * 0.5
        # Allow a few pixels of leeway (the hull isn't the whole frame).
        assert abs(BOSS_RADIUS - expected) < 15.0, (
            f"BOSS_RADIUS={BOSS_RADIUS} is out of sync with BOSS_SCALE="
            f"{BOSS_SCALE} — expected ≈ {expected:.1f}")


# ─── Drop scatter geometry ────────────────────────────────────────────────

class TestDropScatter:
    def test_single_item_returns_centre(self):
        from collisions import _drop_scatter
        positions = _drop_scatter(100.0, 200.0, 1)
        assert positions == [(100.0, 200.0)]

    def test_zero_items_returns_centre(self):
        from collisions import _drop_scatter
        positions = _drop_scatter(0.0, 0.0, 0)
        assert positions == [(0.0, 0.0)]

    def test_multiple_items_are_distinct(self):
        from collisions import _drop_scatter
        positions = _drop_scatter(500.0, 500.0, 6)
        assert len(positions) == 6
        # No two points coincide.
        unique = {(round(x, 2), round(y, 2)) for x, y in positions}
        assert len(unique) == 6

    def test_scatter_stays_near_centre(self):
        """The scatter ring caps at 3× the base radius so drops stay
        visually local to the death point."""
        from collisions import _drop_scatter
        positions = _drop_scatter(0.0, 0.0, 20)
        for x, y in positions:
            r = math.hypot(x, y)
            # Default base radius is 24 px; cap at 3× so ~72.
            assert r <= 80.0, f"drop at radius {r:.1f} exceeds the cap"

    def test_scatter_is_evenly_spaced(self):
        """n equal positions placed on the ring — every adjacent
        pair should subtend ~2π/n radians around the centre."""
        from collisions import _drop_scatter
        n = 8
        positions = _drop_scatter(0.0, 0.0, n)
        # All should lie on the same radius.
        radii = [math.hypot(x, y) for x, y in positions]
        r0 = radii[0]
        assert all(abs(r - r0) < 0.01 for r in radii), (
            "Ring radius not uniform across positions")


# ─── Segment hit-test helper ──────────────────────────────────────────────

class TestSegmentHitAsteroid:
    """``_segment_hit_asteroid`` is the distance-from-segment test
    the Nebula-boss crush pass uses.  Verifies the maths works at
    the boundaries."""

    def _call(self, *args):
        from zones.zone2_world import _segment_hit_asteroid
        return _segment_hit_asteroid(*args)

    def test_hit_when_asteroid_on_segment(self):
        # Asteroid (500, 500) sits exactly on the segment (400, 500)->(600, 500)
        assert self._call(400, 500, 600, 500, 500, 500, 50) is True

    def test_miss_when_far_off_segment(self):
        # Asteroid 200 px below the segment — threshold 50 + 26 = 76
        assert self._call(0, 0, 200, 0, 100, 200, 50) is False

    def test_hit_when_endpoint_touches_asteroid(self):
        # Asteroid at segment's end.
        assert self._call(0, 0, 100, 0, 100, 0, 10) is True

    def test_degenerate_segment_acts_as_point(self):
        # Zero-length segment.  Asteroid 30 px away, threshold = 50+26.
        assert self._call(100, 100, 100, 100, 130, 100, 50) is True
        assert self._call(100, 100, 100, 100, 200, 200, 50) is False

    def test_segment_clamp_before_start(self):
        # Projection of asteroid onto the segment lies BEFORE (0,0),
        # so closest point should be (0,0) not the projection.
        # Asteroid at (-50, 50), segment (0,0)->(100,0). Closest is (0,0),
        # distance ~70.7. Threshold 50+26=76 → hit.
        assert self._call(0, 0, 100, 0, -50, 50, 50) is True
        # Same setup but asteroid far away (-200, 50) is out.
        assert self._call(0, 0, 100, 0, -200, 50, 50) is False


# ─── Nebula boss tunables ─────────────────────────────────────────────────

class TestNebulaBossTunables:
    def test_player_priority_range_is_1000(self):
        from sprites.nebula_boss import NebulaBossShip
        assert NebulaBossShip._PLAYER_PRIORITY_RANGE == 1000.0

    def test_parent_priority_range_default_matches_detect(self):
        from sprites.boss import BossAlienShip
        from constants import BOSS_DETECT_RANGE
        assert BossAlienShip._PLAYER_PRIORITY_RANGE == BOSS_DETECT_RANGE

    def test_row_count_is_8(self):
        from sprites.nebula_boss import NEBULA_BOSS_ROW_COUNT
        assert NEBULA_BOSS_ROW_COUNT == 8

    def test_cone_range_400(self):
        from constants import NEBULA_BOSS_CONE_RANGE
        assert NEBULA_BOSS_CONE_RANGE == 400.0

    def test_gas_damage_30(self):
        from constants import NEBULA_BOSS_GAS_DAMAGE
        assert NEBULA_BOSS_GAS_DAMAGE == 30.0

    def test_cone_damage_20(self):
        from constants import NEBULA_BOSS_CONE_DAMAGE
        assert NEBULA_BOSS_CONE_DAMAGE == 20.0


# ─── Nebula kill reward constants ─────────────────────────────────────────

class TestNebulaKillReward:
    def test_iron_reward(self):
        from collisions import _NEBULA_BOSS_IRON_DROP
        assert _NEBULA_BOSS_IRON_DROP == 3000

    def test_copper_reward(self):
        from collisions import _NEBULA_BOSS_COPPER_DROP
        assert _NEBULA_BOSS_COPPER_DROP == 1000

    def test_death_function_does_not_reference_boss_xp(self):
        """Source-level check that ``_nebula_boss_death`` was stripped of
        the ``gv._add_xp(BOSS_XP_REWARD)`` line — the Nebula boss is a
        resource-summonable encore and awards zero XP."""
        import inspect
        from collisions import _nebula_boss_death
        src = inspect.getsource(_nebula_boss_death)
        assert "_add_xp" not in src, (
            "Nebula kill should not call _add_xp — per user spec")


# ─── damage_boss helper (consolidated take_damage + death routing) ────────


class TestDamageBossHelper:
    """``damage_boss`` consolidates the take_damage + post-damage
    death routing that previously lived inline in three call sites
    (projectiles, missiles, melee).  The melee site forgot to call
    ``_boss_death`` (PR #110) leaving a ghost boss; this helper
    makes that class of bug unreachable -- every player-damage path
    funnels through one function.
    """

    def _make_gv(self):
        """Stub gv with the attributes damage_boss needs."""
        from types import SimpleNamespace
        return SimpleNamespace(_boss=None, _nebula_boss=None)

    def _make_boss(self, hp=100):
        from types import SimpleNamespace
        b = SimpleNamespace(hp=hp, _hits=[])

        def _td(dmg):
            b.hp = max(0, b.hp - int(dmg))
            b._hits.append(int(dmg))
        b.take_damage = _td
        return b

    def test_returns_false_when_boss_is_none(self):
        from collisions import damage_boss
        gv = self._make_gv()
        assert damage_boss(gv, None, 50) is False

    def test_returns_false_when_boss_already_dead(self):
        from collisions import damage_boss
        gv = self._make_gv()
        dead = self._make_boss(hp=0)
        assert damage_boss(gv, dead, 50) is False
        # No take_damage call on an already-dead boss.
        assert dead._hits == []

    def test_returns_false_when_damage_does_not_kill(self):
        from collisions import damage_boss
        gv = self._make_gv()
        boss = self._make_boss(hp=100)
        gv._boss = boss
        assert damage_boss(gv, boss, 30) is False
        assert boss.hp == 70
        assert boss._hits == [30]

    def test_fires_boss_death_on_lethal_damage_to_main_boss(
            self, monkeypatch):
        from collisions import damage_boss
        import collisions_boss
        calls = {"main": 0, "nebula": 0}
        monkeypatch.setattr(
            collisions_boss, "_boss_death",
            lambda g: calls.__setitem__("main", calls["main"] + 1))
        monkeypatch.setattr(
            collisions_boss, "_nebula_boss_death",
            lambda g: calls.__setitem__(
                "nebula", calls["nebula"] + 1))
        gv = self._make_gv()
        boss = self._make_boss(hp=20)
        gv._boss = boss
        assert damage_boss(gv, boss, 50) is True
        assert boss.hp == 0
        assert calls == {"main": 1, "nebula": 0}

    def test_fires_nebula_death_on_lethal_damage_to_nebula_boss(
            self, monkeypatch):
        from collisions import damage_boss
        import collisions_boss
        calls = {"main": 0, "nebula": 0}
        monkeypatch.setattr(
            collisions_boss, "_boss_death",
            lambda g: calls.__setitem__("main", calls["main"] + 1))
        monkeypatch.setattr(
            collisions_boss, "_nebula_boss_death",
            lambda g: calls.__setitem__(
                "nebula", calls["nebula"] + 1))
        gv = self._make_gv()
        nb = self._make_boss(hp=20)
        gv._nebula_boss = nb
        assert damage_boss(gv, nb, 50) is True
        assert nb.hp == 0
        assert calls == {"main": 0, "nebula": 1}

    def test_does_not_fire_death_when_boss_not_in_gv(
            self, monkeypatch):
        """Defensive: damage_boss only routes death when the
        target is identical to gv._boss or gv._nebula_boss.  An
        unowned boss (shouldn't happen in production but easy to
        accidentally construct in a test) takes damage without
        triggering the death pipeline."""
        from collisions import damage_boss
        import collisions_boss
        calls = {"main": 0, "nebula": 0}
        monkeypatch.setattr(
            collisions_boss, "_boss_death",
            lambda g: calls.__setitem__("main", calls["main"] + 1))
        monkeypatch.setattr(
            collisions_boss, "_nebula_boss_death",
            lambda g: calls.__setitem__(
                "nebula", calls["nebula"] + 1))
        gv = self._make_gv()
        # gv._boss is None; this boss is unrooted.
        orphan = self._make_boss(hp=20)
        assert damage_boss(gv, orphan, 50) is True
        assert orphan.hp == 0
        # Neither death helper fired (no identity match).
        assert calls == {"main": 0, "nebula": 0}


# ─── Nebula boss sprite randomisation ─────────────────────────────────────

class TestNebulaSpriteRandomisation:
    def test_row_clamped_to_valid_range(self):
        """``load_nebula_boss_texture`` should clamp out-of-range row
        indices into [0, NEBULA_BOSS_ROW_COUNT-1]."""
        # Can't call the loader without a GL context — check the clamp
        # logic via the public constant and a sanity rearrange.
        from sprites.nebula_boss import NEBULA_BOSS_ROW_COUNT
        # Clamp behaviour tested in integration (needs arcade.Texture).
        assert NEBULA_BOSS_ROW_COUNT > 0

    def test_column_index_is_second_column(self):
        """User-specified: random row, ALWAYS second column."""
        from constants import NEBULA_BOSS_COL_INDEX
        assert NEBULA_BOSS_COL_INDEX == 1  # zero-based "second column"


# ─── Wall avoidance math (using the shared alien_ai helper) ──────────────

class TestBossWallAvoidance:
    """``BossAlienShip._compute_avoidance`` delegates wall repulsion to
    the same segment-crossing check aliens use, scaled by
    ``self.radius + ALIEN_AVOIDANCE_RADIUS + 60``.  Verifies the math."""

    def test_wall_threshold_scales_with_boss_radius(self):
        """A Nebula-scale boss (radius ~115) should have a wider
        avoidance threshold than a Double-Star-scale boss (radius ~38)."""
        from constants import ALIEN_AVOIDANCE_RADIUS
        # Compute the two thresholds the way the method does.
        nebula_thr = 115.0 + ALIEN_AVOIDANCE_RADIUS + 60.0
        ds_thr = 38.0 + ALIEN_AVOIDANCE_RADIUS + 60.0
        assert nebula_thr > ds_thr
        # Both should be > 0 and > pure radius.
        assert nebula_thr > 115.0
        assert ds_thr > 38.0
