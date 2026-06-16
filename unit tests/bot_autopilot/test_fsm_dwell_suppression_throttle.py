"""Throttle for the ``transition_suppressed_by_dwell`` telemetry.

Regression guard for the 2026-06-15 fix.  The suppressed-transition
log used to fire once per poll tick (~10 Hz) for the whole
MIN_DWELL_S window, so a single ~1 s suppression episode wrote
~10 near-identical ~40-field snapshot lines (a captured 2 h session
logged 1342 of them — about a third of the whole stream).  The
throttle logs only the FIRST tick of each distinct
``(from_state, desired)`` suppression episode and resets the episode
signature whenever the FSM is not suppressing.
"""
from __future__ import annotations

import pytest

import bot_autopilot as ap

from _helpers import _state


def _suppress_count(events):
    return sum(1 for e in events
               if e[0] == "transition_suppressed_by_dwell")


@pytest.fixture
def _telemetry_spy(monkeypatch):
    """Record (event, kwargs) for every ``_telemetry_log`` call."""
    events: list = []
    monkeypatch.setattr(
        ap, "_telemetry_log",
        lambda event, **kw: events.append((event, kw)))
    return events


def _settle_in_mine(clock):
    """Put the FSM in a non-first-tick S_MINE so the next
    ``_step_fsm`` exercises the dwell branch, not the first-tick one."""
    ap._fsm["state"] = ap.S_MINE
    ap._fsm["entered_at"] = clock[0]
    ap._fsm["suppress_sig"] = None
    ap._fsm["suppress_log_at"] = 0.0


class TestDwellSuppressionThrottle:
    def test_intra_episode_suppression_logged_once(
            self, _clock, _telemetry_spy, monkeypatch):
        """Ten ticks inside one dwell window with the same desired
        state log exactly one suppressed-transition line, not ten."""
        # FSM persistently wants GATHER while parked in MINE.  GATHER
        # is not a dwell-bypass state, so the transition is suppressed
        # until dwell >= MIN_DWELL_S.
        monkeypatch.setattr(ap, "_choose_next_state",
                            lambda state, p, cur: ap.S_GATHER)
        _settle_in_mine(_clock)
        s = _state(iron=10)
        p = s["player"]

        # Walk 10 ticks of 0.05 s — total 0.5 s, safely under the
        # 1.0 s MIN_DWELL floor so every tick hits the suppress branch.
        for _ in range(10):
            _clock[0] += 0.05
            ap._step_fsm(s, p, _clock[0])

        assert _suppress_count(_telemetry_spy) == 1
        # Still parked in MINE (dwell never reached the floor).
        assert ap._fsm["state"] == ap.S_MINE

    def test_changed_desired_logs_a_new_episode(
            self, _clock, _telemetry_spy, monkeypatch):
        """A different (from, desired) signature inside the same dwell
        window logs a fresh suppressed line."""
        desired = [ap.S_GATHER]
        monkeypatch.setattr(ap, "_choose_next_state",
                            lambda state, p, cur: desired[0])
        _settle_in_mine(_clock)
        s = _state(iron=10)
        p = s["player"]

        for _ in range(4):
            _clock[0] += 0.05
            ap._step_fsm(s, p, _clock[0])
        assert _suppress_count(_telemetry_spy) == 1

        # FSM now wants HUNT instead — new signature, new log, even
        # though we're still inside the same dwell window.
        desired[0] = ap.S_HUNT
        for _ in range(4):
            _clock[0] += 0.05
            ap._step_fsm(s, p, _clock[0])
        assert _suppress_count(_telemetry_spy) == 2

    def test_settling_resets_episode_so_repeat_relogs(
            self, _clock, _telemetry_spy, monkeypatch):
        """When the FSM settles (desired == cur) the episode signature
        clears, so a later identical suppression logs its first tick
        again rather than being deduped against the old episode."""
        desired = [ap.S_GATHER]
        monkeypatch.setattr(ap, "_choose_next_state",
                            lambda state, p, cur: desired[0])
        _settle_in_mine(_clock)
        s = _state(iron=10)
        p = s["player"]

        _clock[0] += 0.05
        ap._step_fsm(s, p, _clock[0])
        assert _suppress_count(_telemetry_spy) == 1

        # FSM settles back onto MINE for a tick (desired == cur):
        # no suppression, signature resets.
        desired[0] = ap.S_MINE
        _clock[0] += 0.05
        ap._step_fsm(s, p, _clock[0])
        assert _suppress_count(_telemetry_spy) == 1
        assert ap._fsm["suppress_sig"] is None

        # Wants GATHER again — fresh episode, logs its first tick.
        desired[0] = ap.S_GATHER
        _clock[0] += 0.05
        ap._step_fsm(s, p, _clock[0])
        assert _suppress_count(_telemetry_spy) == 2

    def test_real_transition_clears_episode_signature(
            self, _clock, _telemetry_spy, monkeypatch):
        """Once dwell elapses and the transition actually fires, the
        suppress signature is cleared (the episode is over)."""
        monkeypatch.setattr(ap, "_choose_next_state",
                            lambda state, p, cur: ap.S_GATHER)
        _settle_in_mine(_clock)
        s = _state(iron=10)
        p = s["player"]

        _clock[0] += 0.05
        ap._step_fsm(s, p, _clock[0])
        assert ap._fsm["suppress_sig"] == (ap.S_MINE, ap.S_GATHER)

        # Cross the MIN_DWELL floor — the transition to GATHER fires.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._step_fsm(s, p, _clock[0])
        assert ap._fsm["state"] == ap.S_GATHER
        assert ap._fsm["suppress_sig"] is None
