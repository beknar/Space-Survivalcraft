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
