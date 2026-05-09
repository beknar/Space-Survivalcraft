"""Tests for the generic save/restore helper extracted in the refactor.

`game_save._restore_sprite_list` is the small generic helper now used to
restore Zone 1 asteroids and all four Zone 2 entity lists. The factory
pattern is trivially correct but worth locking down so a future change
can't silently break the contract (clear-then-append-via-factory).
"""
from __future__ import annotations

import pytest

from game_save import _restore_sprite_list


class _FakeList(list):
    """A list that mimics the bits of arcade.SpriteList that the helper uses."""

    def append(self, item) -> None:  # type: ignore[override]
        super().append(item)


class TestRestoreSpriteList:
    def test_clears_existing_entries_first(self):
        target = _FakeList()
        target.extend([{"prev": True}, {"prev": True}])
        _restore_sprite_list(target, [{"x": 1}], lambda e: e)
        assert len(target) == 1
        assert target[0] == {"x": 1}  # old entries gone

    def test_factory_called_per_entry(self):
        target = _FakeList()
        calls = []

        def factory(entry):
            calls.append(entry)
            return entry

        entries = [{"a": 1}, {"a": 2}, {"a": 3}]
        _restore_sprite_list(target, entries, factory)
        assert calls == entries
        assert len(target) == 3

    def test_factory_returning_none_is_skipped(self):
        # Mirrors zone 2 alien restore: missing texture → factory returns None
        target = _FakeList()
        _restore_sprite_list(target, [{"k": 1}, {"k": 2}, {"k": 3}],
                             lambda e: None if e["k"] == 2 else e)
        assert len(target) == 2
        assert target[0]["k"] == 1
        assert target[1]["k"] == 3

    def test_empty_entries_clears_target(self):
        target = _FakeList()
        target.extend([1, 2, 3])
        _restore_sprite_list(target, [], lambda e: e)
        assert len(target) == 0

    def test_factory_receives_each_entry_object(self):
        # Identity check — the helper must pass the literal entry, not a copy
        target = _FakeList()
        entry = {"id": object()}
        seen = []
        _restore_sprite_list(target, [entry], lambda e: seen.append(e) or e)
        assert seen[0] is entry


# ── Building-exclusion reject for load-time respawn ───────────────────────


from types import SimpleNamespace
from game_save import (_building_reject_fn,
                        _LOAD_STATION_EXCLUSION_PX as EX_PX)


class TestBuildingRejectFn:
    """Pins ``_building_reject_fn``: builds a callable that rejects
    candidate (x, y) positions within ``_LOAD_STATION_EXCLUSION_PX``
    of any player-built station structure.  Used by the Zone 1 + Zone 2
    load paths so re-spawned null fields and slipspaces don't land on
    top of the player's base.  Caught from 2026-05-09 user request."""

    def test_empty_buildings_returns_none(self):
        assert _building_reject_fn([]) is None
        assert _building_reject_fn(None) is None

    def test_dict_buildings_inside_exclusion_rejected(self):
        # Save-data shape: [{"x": ..., "y": ...}]
        reject = _building_reject_fn([{"x": 1000.0, "y": 1000.0}])
        assert reject is not None
        # Just inside the exclusion radius.
        assert reject(1000.0 + EX_PX - 1.0, 1000.0) is True
        assert reject(1000.0, 1000.0) is True

    def test_dict_buildings_outside_exclusion_accepted(self):
        reject = _building_reject_fn([{"x": 1000.0, "y": 1000.0}])
        # Just past the exclusion radius — accepted.
        assert reject(1000.0 + EX_PX + 1.0, 1000.0) is False
        assert reject(0.0, 0.0) is False

    def test_sprite_buildings_use_center_coords(self):
        # Live sprite shape: object with .center_x / .center_y.
        b = SimpleNamespace(center_x=2000.0, center_y=2000.0)
        reject = _building_reject_fn([b])
        assert reject(2000.0, 2000.0) is True
        assert reject(2000.0 + EX_PX + 1.0, 2000.0) is False

    def test_multiple_buildings_any_match_rejects(self):
        reject = _building_reject_fn([
            {"x": 0.0, "y": 0.0},
            {"x": 5000.0, "y": 5000.0},
        ])
        # Inside the second building's exclusion zone.
        assert reject(5000.0, 5000.0) is True
        # Outside both — accepted.
        assert reject(2500.0, 2500.0) is False

    def test_at_exclusion_boundary_is_accepted(self):
        """Comparison is ``< r2`` (strict less-than), so a candidate
        at exactly ``exclusion_px`` is accepted.  Pins the boundary."""
        reject = _building_reject_fn([{"x": 0.0, "y": 0.0}])
        # Distance exactly EX_PX — should NOT be rejected.
        assert reject(EX_PX, 0.0) is False

    def test_custom_exclusion_px_overrides_default(self):
        reject = _building_reject_fn(
            [{"x": 0.0, "y": 0.0}], exclusion_px=100.0)
        # Inside 100 but outside 200.
        assert reject(99.0, 0.0) is True
        assert reject(101.0, 0.0) is False


class TestRegenerateNullFieldsWithReject:
    """Pins that ``_regenerate_null_fields`` honours the
    ``building_reject`` parameter — a re-spawned null field must
    never land within the exclusion radius of any provided building.
    """

    def test_regenerated_fields_avoid_buildings(self):
        from game_save import _regenerate_null_fields
        # Stub a Zone 2-shaped object with a deterministic seed.
        zone = SimpleNamespace(
            world_width=6400.0, world_height=6400.0, _world_seed=42)
        # Place buildings clustered around (3200, 3200).  Any null
        # field within EX_PX of any of these positions is a bug.
        building_dicts = [
            {"x": 3200.0, "y": 3200.0},
            {"x": 3260.0, "y": 3200.0},
            {"x": 3200.0, "y": 3260.0},
        ]
        reject = _building_reject_fn(building_dicts)
        _regenerate_null_fields(zone, building_reject=reject)
        # Zone now has a fresh null-field list.  Verify exclusion.
        for nf in zone._null_fields:
            for b in building_dicts:
                d_sq = (nf.center_x - b["x"]) ** 2 \
                       + (nf.center_y - b["y"]) ** 2
                assert d_sq >= EX_PX * EX_PX, (
                    f"null field at ({nf.center_x:.0f}, "
                    f"{nf.center_y:.0f}) is within {EX_PX} px of "
                    f"building at ({b['x']:.0f}, {b['y']:.0f})")

    def test_no_reject_keeps_original_behaviour(self):
        """Passing ``building_reject=None`` (or omitting it) gives the
        unchanged seed-deterministic layout."""
        from game_save import _regenerate_null_fields
        zone_a = SimpleNamespace(
            world_width=6400.0, world_height=6400.0, _world_seed=42)
        zone_b = SimpleNamespace(
            world_width=6400.0, world_height=6400.0, _world_seed=42)
        _regenerate_null_fields(zone_a)
        _regenerate_null_fields(zone_b, building_reject=None)
        positions_a = [(nf.center_x, nf.center_y)
                       for nf in zone_a._null_fields]
        positions_b = [(nf.center_x, nf.center_y)
                       for nf in zone_b._null_fields]
        assert positions_a == positions_b


class TestRegenerateSlipspacesWithReject:
    """Symmetric pin for ``_regenerate_slipspaces``."""

    def test_regenerated_slipspaces_avoid_buildings(self):
        from game_save import _regenerate_slipspaces
        # Stub a Zone 2-shaped object.  The slipspace generator only
        # reads world_width / height / _world_seed and writes back
        # ``_slipspaces``; it loads the texture itself via
        # ``load_slipspace_assets``.
        zone = SimpleNamespace(
            world_width=6400.0, world_height=6400.0, _world_seed=99)
        view = SimpleNamespace()  # not actually consumed by the function
        building_dicts = [
            {"x": 4000.0, "y": 4000.0},
            {"x": 4100.0, "y": 4000.0},
        ]
        reject = _building_reject_fn(building_dicts)
        _regenerate_slipspaces(zone, view, building_reject=reject)
        for ss in zone._slipspaces:
            for b in building_dicts:
                d_sq = (ss.center_x - b["x"]) ** 2 \
                       + (ss.center_y - b["y"]) ** 2
                assert d_sq >= EX_PX * EX_PX, (
                    f"slipspace at ({ss.center_x:.0f}, "
                    f"{ss.center_y:.0f}) is within {EX_PX} px of "
                    f"building at ({b['x']:.0f}, {b['y']:.0f})")
