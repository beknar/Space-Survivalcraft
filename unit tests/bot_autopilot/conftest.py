"""Shared fixtures for the split bot-autopilot FSM tests.

Lifted from ``test_bot_autopilot_fsm.py`` in the 2026-05-24 PR 4
refactor.  The autouse fixtures here apply only to tests under
this directory (pytest's conftest scoping rule) so the rest of
the unit suite is unaffected.

The ``_state`` / ``_boss`` / ``_hs_building`` etc. plain-function
helpers live in ``_helpers.py`` so test files can import them
directly.  ``conftest.py`` prepends this directory to ``sys.path``
so ``from _helpers import ...`` works.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pytest

import bot_autopilot as ap


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    """Patch ``ap._get_now`` so tests control the clock that the
    FSM reads.  Tests advance ``clock[0]`` to walk through dwell
    boundaries deterministically."""
    clock = [1000.0]
    monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
    yield clock


@pytest.fixture(autouse=True)
def _key_recorder(monkeypatch):
    """Stub KeyState so tests don't touch pyautogui."""
    monkeypatch.setattr(
        ap.KeyState, "hold",
        staticmethod(lambda key, down: None))
    monkeypatch.setattr(
        ap.KeyState, "release_all",
        staticmethod(lambda: None))
    ap.KeyState.held.clear()
    ap._fsm_reset()
    yield


@pytest.fixture
def _fresh_bot_state(monkeypatch):
    """Reset BotState boss-prep flags between tests so latches don't
    leak across the boss-prep pipeline tests."""
    ap._state.consumables_equipped = False
    ap._state.fortify_done = False
    ap._state.qwi_placed = False
    ap._state.last_consumable_use_at = 0.0
    ap._state.heal_hp_active = False
    ap._state.heal_shield_active = False
    ap._state.queue = ap.CraftQueue()
    ap._state.build_done = True   # skip the BUILD branch
    yield
    ap._state.consumables_equipped = False
    ap._state.fortify_done = False
    ap._state.qwi_placed = False
    ap._state.last_consumable_use_at = 0.0
    ap._state.heal_hp_active = False
    ap._state.heal_shield_active = False
    ap._state.queue = ap.CraftQueue()
