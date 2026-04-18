"""Unit tests for the NullField stealth patch.

Covers:
- Sprite lifecycle (size clamp, dot pool, contains_point, disable timer,
  active/disabled states).
- `update_logic` helpers: active_null_fields, find_null_field_at,
  player_is_cloaked, disable_null_field_around_player.
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import arcade
import pytest


# ── NullField sprite ─────────────────────────────────────────────────────


class TestNullFieldSprite:
    def test_size_clamped_to_range(self):
        from sprites.null_field import NullField
        from constants import NULL_FIELD_SIZE_MIN, NULL_FIELD_SIZE_MAX
        assert NullField(0.0, 0.0, size=64).size == NULL_FIELD_SIZE_MIN
        assert NullField(0.0, 0.0, size=9999).size == NULL_FIELD_SIZE_MAX
        assert NullField(0.0, 0.0, size=160).size == 160

    def test_size_defaults_to_random_in_range(self):
        from sprites.null_field import NullField
        from constants import NULL_FIELD_SIZE_MIN, NULL_FIELD_SIZE_MAX
        r = random.Random(42)
        for _ in range(20):
            nf = NullField(0.0, 0.0, rng=r)
            assert NULL_FIELD_SIZE_MIN <= nf.size <= NULL_FIELD_SIZE_MAX

    def test_dot_pool_matches_constant(self):
        from sprites.null_field import NullField
        from constants import NULL_FIELD_DOT_COUNT
        nf = NullField(0.0, 0.0, size=200)
        assert len(nf._dots) == NULL_FIELD_DOT_COUNT

    def test_dots_fit_within_radius(self):
        from sprites.null_field import NullField
        import math
        nf = NullField(1000.0, 1000.0, size=256, rng=random.Random(0))
        for dx, dy, _ in nf._dots:
            assert math.hypot(dx, dy) <= nf.radius + 0.001

    def test_contains_point_inside(self):
        from sprites.null_field import NullField
        nf = NullField(100.0, 200.0, size=200)
        assert nf.contains_point(100.0, 200.0) is True   # centre
        assert nf.contains_point(150.0, 200.0) is True   # 50 px east
        assert nf.contains_point(100.0, 300.0) is True   # edge

    def test_contains_point_outside(self):
        from sprites.null_field import NullField
        nf = NullField(100.0, 200.0, size=200)
        assert nf.contains_point(400.0, 200.0) is False
        assert nf.contains_point(100.0, 9999.0) is False

    def test_starts_active(self):
        from sprites.null_field import NullField
        nf = NullField(0.0, 0.0, size=200)
        assert nf.active is True
        assert nf.disabled_seconds_remaining == 0.0

    def test_trigger_disable_starts_timer(self):
        from sprites.null_field import NullField
        from constants import NULL_FIELD_DISABLE_S
        nf = NullField(0.0, 0.0, size=200)
        nf.trigger_disable()
        assert nf.active is False
        assert nf.disabled_seconds_remaining == pytest.approx(
            NULL_FIELD_DISABLE_S)

    def test_update_decrements_disable_timer(self):
        from sprites.null_field import NullField
        from constants import NULL_FIELD_DISABLE_S
        nf = NullField(0.0, 0.0, size=200)
        nf.trigger_disable()
        nf.update_null_field(1.0)
        assert nf.disabled_seconds_remaining == pytest.approx(
            NULL_FIELD_DISABLE_S - 1.0)

    def test_disable_timer_never_goes_negative(self):
        from sprites.null_field import NullField
        nf = NullField(0.0, 0.0, size=200)
        nf.trigger_disable()
        nf.update_null_field(999.0)
        assert nf.disabled_seconds_remaining == 0.0
        assert nf.active is True

    def test_trigger_disable_while_already_disabled_refreshes(self):
        """Re-triggering within the penalty extends — never stacks."""
        from sprites.null_field import NullField
        from constants import NULL_FIELD_DISABLE_S
        nf = NullField(0.0, 0.0, size=200)
        nf.trigger_disable()
        nf.update_null_field(10.0)
        # 20 s remaining; re-trigger must reset to the full penalty.
        nf.trigger_disable()
        assert nf.disabled_seconds_remaining == pytest.approx(
            NULL_FIELD_DISABLE_S)


# ── update_logic helpers ──────────────────────────────────────────────────


class _StubPlayer:
    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self.center_x = x
        self.center_y = y


def _make_gv_with_fields(fields):
    zone = SimpleNamespace(_null_fields=None, zone_id=None)
    return SimpleNamespace(
        player=_StubPlayer(),
        _zone=zone,
        _null_fields=list(fields),
        _player_dead=False,
    )


class TestActiveNullFields:
    def test_prefers_zone_list_when_present(self):
        from sprites.null_field import NullField
        from update_logic import active_null_fields
        gv = _make_gv_with_fields([NullField(0.0, 0.0, size=200)])
        z2_field = NullField(1000.0, 1000.0, size=200)
        gv._zone._null_fields = [z2_field]
        assert active_null_fields(gv) == [z2_field]

    def test_falls_back_to_zone1_list(self):
        from sprites.null_field import NullField
        from update_logic import active_null_fields
        gv = _make_gv_with_fields([NullField(10.0, 10.0, size=200)])
        result = active_null_fields(gv)
        assert len(result) == 1
        assert result[0].center_x == 10.0

    def test_empty_when_no_fields_anywhere(self):
        from update_logic import active_null_fields
        gv = _make_gv_with_fields([])
        assert active_null_fields(gv) == []


class TestPlayerIsCloaked:
    def test_inside_active_field_cloaks(self):
        from sprites.null_field import NullField
        from update_logic import player_is_cloaked
        gv = _make_gv_with_fields([NullField(500.0, 500.0, size=200)])
        gv.player.center_x = 500.0
        gv.player.center_y = 500.0
        assert player_is_cloaked(gv) is True

    def test_outside_field_does_not_cloak(self):
        from sprites.null_field import NullField
        from update_logic import player_is_cloaked
        gv = _make_gv_with_fields([NullField(500.0, 500.0, size=200)])
        gv.player.center_x = 9999.0
        gv.player.center_y = 0.0
        assert player_is_cloaked(gv) is False

    def test_disabled_field_does_not_cloak(self):
        from sprites.null_field import NullField
        from update_logic import player_is_cloaked
        nf = NullField(500.0, 500.0, size=200)
        nf.trigger_disable()
        gv = _make_gv_with_fields([nf])
        gv.player.center_x = 500.0
        gv.player.center_y = 500.0
        assert player_is_cloaked(gv) is False

    def test_dead_player_is_not_cloaked(self):
        from sprites.null_field import NullField
        from update_logic import player_is_cloaked
        gv = _make_gv_with_fields([NullField(500.0, 500.0, size=200)])
        gv.player.center_x = 500.0
        gv.player.center_y = 500.0
        gv._player_dead = True
        assert player_is_cloaked(gv) is False


class TestFindNullFieldAt:
    def test_returns_field_containing_point(self):
        from sprites.null_field import NullField
        from update_logic import find_null_field_at
        a = NullField(0.0, 0.0, size=200)
        b = NullField(1000.0, 0.0, size=200)
        gv = _make_gv_with_fields([a, b])
        assert find_null_field_at(gv, 5.0, 5.0) is a
        assert find_null_field_at(gv, 1005.0, 0.0) is b
        assert find_null_field_at(gv, 500.0, 0.0) is None


class TestDisableAroundPlayer:
    def test_fires_from_inside_disables_field(self):
        from sprites.null_field import NullField
        from update_logic import disable_null_field_around_player
        nf = NullField(0.0, 0.0, size=200)
        gv = _make_gv_with_fields([nf])
        gv.player.center_x = 10.0
        gv.player.center_y = 10.0
        disable_null_field_around_player(gv)
        assert nf.active is False

    def test_fires_from_outside_is_noop(self):
        from sprites.null_field import NullField
        from update_logic import disable_null_field_around_player
        nf = NullField(0.0, 0.0, size=200)
        gv = _make_gv_with_fields([nf])
        gv.player.center_x = 9999.0
        disable_null_field_around_player(gv)
        assert nf.active is True


class TestUpdateNullFields:
    def test_advances_zone1_and_zone2_fields(self):
        from sprites.null_field import NullField
        from update_logic import update_null_fields
        z1 = NullField(0.0, 0.0, size=200)
        z2 = NullField(0.0, 0.0, size=200)
        z1.trigger_disable()
        z2.trigger_disable()
        gv = _make_gv_with_fields([z1])
        gv._zone._null_fields = [z2]
        update_null_fields(gv, 1.0)
        from constants import NULL_FIELD_DISABLE_S
        assert z1.disabled_seconds_remaining == pytest.approx(
            NULL_FIELD_DISABLE_S - 1.0)
        assert z2.disabled_seconds_remaining == pytest.approx(
            NULL_FIELD_DISABLE_S - 1.0)

    def test_shared_field_only_advanced_once(self):
        """If the same NullField instance appears on both gv and zone,
        update_null_fields must not tick it twice in one frame."""
        from sprites.null_field import NullField
        from update_logic import update_null_fields
        nf = NullField(0.0, 0.0, size=200)
        nf.trigger_disable()
        gv = _make_gv_with_fields([nf])
        gv._zone._null_fields = [nf]
        update_null_fields(gv, 1.0)
        from constants import NULL_FIELD_DISABLE_S
        assert nf.disabled_seconds_remaining == pytest.approx(
            NULL_FIELD_DISABLE_S - 1.0)


# ── Populator ────────────────────────────────────────────────────────────


class TestPopulateNullFields:
    def test_count_matches_constant_by_default(self):
        from world_setup import populate_null_fields
        from constants import NULL_FIELD_COUNT
        fields = populate_null_fields(6400.0, 6400.0,
                                       rng=random.Random(0))
        assert len(fields) == NULL_FIELD_COUNT

    def test_honours_explicit_count(self):
        from world_setup import populate_null_fields
        fields = populate_null_fields(
            6400.0, 6400.0, count=5, rng=random.Random(0))
        assert len(fields) == 5

    def test_fields_placed_inside_world(self):
        from world_setup import populate_null_fields
        w, h = 6400.0, 6400.0
        fields = populate_null_fields(w, h, rng=random.Random(123))
        margin = 180.0
        for nf in fields:
            assert margin <= nf.center_x <= w - margin
            assert margin <= nf.center_y <= h - margin
