"""REGEN priority tests (recovery, escape valve, HS drive).

Carved out of ``test_bot_autopilot_fsm.py`` in the 2026-05-24 PR 4
refactor.  Shared fixtures + state factories live in
``conftest.py`` and ``_helpers.py`` in this directory.
"""
from __future__ import annotations

import math

import pytest

import bot_autopilot as ap

from _helpers import (
    _state, _hs_building, _crafter_building,
    _all_blueprints_in_station, _boss,
    _drained_consumable_queue,
)




# ── REGEN hysteresis ──────────────────────────────────────────────────────


class TestRegenHysteresis:
    def test_enters_below_40_pct(self, _clock):
        s = _state(player={
            "x": 0, "y": 0, "heading": 0,
            "shields": 50, "max_shields": 150,   # 33 %
        })
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_holds_in_band_between_40_and_60_pct(self, _clock):
        """REGEN entered at 33 % -- recovering to 50 % must NOT
        exit yet (exit band is 60 %)."""
        s = _state(player={
            "x": 0, "y": 0, "heading": 0,
            "shields": 50, "max_shields": 150,
        })
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Recovered to 50 % -- still inside hysteresis band.
        s["player"]["shields"] = 75
        _clock[0] += ap.MIN_DWELL_S + 0.1   # past dwell, hysteresis owns it
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "REGEN must hold until shields >= 60 %")

    def test_exits_at_or_above_60_pct(self, _clock):
        s = _state(player={
            "x": 0, "y": 0, "heading": 0,
            "shields": 50, "max_shields": 150,
        })
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        s["player"]["shields"] = 100   # 67 %, past exit band
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN


# ── REGEN escape valve (2026-05-04 deadlock fix) ─────────────────────



# ── REGEN escape valve (2026-05-04 deadlock fix) ─────────────────────

class TestRegenEscapeValve:
    """When the bot is in S_REGEN with a close threat AND shields
    aren't recovering between ticks, the FSM must let ENGAGE preempt
    REGEN.  Without this the bot deadlocks: shields can't reach the
    60% exit threshold while being shot, REGEN keeps the bot idle,
    bot keeps taking damage forever.  Telemetry caught this clearly:
    78 s session, 23 stuck_detected events all in REGEN at shields=0,
    0 iron collected."""

    def test_close_threat_and_falling_shields_breaks_regen(self, _clock):
        """Bot enters REGEN cleanly (no threat), then a threat
        appears mid-regen and shields aren't recovering — after
        the REGEN_NO_PROGRESS_TIMEOUT_S hysteresis window expires,
        the escape valve fires and ENGAGE preempts.

        (The entry-side mirror now also suppresses REGEN entry
        when threatened, so the original "enter REGEN with threat
        already close" path is gone — see TestRegenEntryWhileThreatenedSuppressed.
        This test exercises the in-REGEN escape valve for the
        case where the threat appears AFTER REGEN entry.)"""
        # Step 1: enter REGEN cleanly with no close threat.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],  # far
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Step 2: an alien closes in mid-regen, shields drop AND
        # stay no-progress for past the hysteresis window.
        _clock[0] += ap.REGEN_NO_PROGRESS_TIMEOUT_S + 0.2
        s["aliens"] = [{"x": 500, "y": 0, "hp": 50}]  # now close
        s["player"]["shields"] = 40  # dropped from 50
        ap._do_auto(s, s["player"])
        # In-REGEN escape valve fires — ENGAGE preempts REGEN.
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "REGEN deadlock — bot took damage but stayed in REGEN")

    def test_close_threat_but_shields_recovering_stays_regen(self, _clock):
        """Sanity: if shields ARE recovering despite a close alien
        appearing mid-regen, REGEN holds normally."""
        # Enter REGEN cleanly first.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Alien closes in but shields are RECOVERING (alien firing
        # past us, missing — combat assist in our favour).
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s["aliens"] = [{"x": 500, "y": 0, "hp": 50}]
        s["player"]["shields"] = 60  # rose from 50
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_no_close_threat_stays_regen_even_if_shields_flat(self, _clock):
        """Sanity: no alien nearby → no escape valve, REGEN holds
        even if shields plateau briefly (regen tick boundary)."""
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],  # far
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s["player"]["shields"] = 50  # unchanged
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_last_regen_shields_resets_on_exit(self, _clock):
        """When REGEN exits cleanly (shields recovered past 60%),
        ``last_regen_shields`` resets to 0 so a future REGEN entry
        starts the trend-tracking fresh."""
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        assert ap._state.last_regen_shields == 50
        # Shields recover past exit threshold.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s["player"]["shields"] = 100  # 67%
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN
        assert ap._state.last_regen_shields == 0

    def test_last_regen_shields_resets_on_fsm_reset(self):
        ap._state.last_regen_shields = 99
        ap._fsm_reset()
        assert ap._state.last_regen_shields == 0

    def test_close_boss_counts_as_threat_for_escape_valve(
            self, _clock, monkeypatch):
        """User-spec follow-up (2026-05-11): the escape valve must
        treat the boss as a threat too -- otherwise the bot sits in
        REGEN at point-blank cannon range, takes damage continuously,
        and dies because ``nearest(aliens, ...)`` returns None.
        Telemetry showed 86 shields drained over 28 s of REGEN with
        no aliens nearby, then player_death."""
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        # Enter REGEN cleanly (no boss, no alien).  Home Station
        # present so the post-escape engage_boss path isn't blocked
        # by the seventeenth-pass no-HS suppression.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            buildings=[{"x": 5000.0, "y": 5000.0,
                        "building_type": "Home Station"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # A boss appears within ENGAGE_ENTER_PX and shields keep
        # dropping.  Wait past REGEN_NO_PROGRESS_TIMEOUT_S so the
        # hysteresis window expires; escape valve must then fire
        # even though aliens=[].
        _clock[0] += ap.REGEN_NO_PROGRESS_TIMEOUT_S + 0.2
        s["boss"] = _boss(x=500.0, y=0.0)  # within ENGAGE_ENTER_PX (800)
        s["player"]["shields"] = 40  # dropped from 50
        ap._do_auto(s, s["player"])
        # Cascade picks S_ENGAGE_BOSS (above REGEN now that the
        # escape valve fired).
        assert ap._fsm["state"] == ap.S_ENGAGE_BOSS, (
            "REGEN deadlock at boss point-blank range -- escape "
            "valve must count the boss as a threat")




class TestRegenEscapeValveHysteresis:
    """2026-05-13 fifteenth telemetry pass: the escape valve used
    to fire on a SINGLE tick where ``shields_recovering`` was
    False.  Captured pathology: shields 50 → 68 over 12 s
    (clearly recovering), one damage spike on one tick flipped
    ``shields_recovering`` to False, escape valve fired, bot
    exited REGEN into recover_loot, then died 3 more times in
    rapid succession to the boss attacking the station.

    Fix: require ``REGEN_NO_PROGRESS_TIMEOUT_S`` seconds of
    sustained no-progress before the valve fires.  A brief dip
    or stall doesn't bounce the bot out of REGEN.
    """

    def test_constants_pinned(self):
        """The hysteresis window must be > 0 (otherwise no
        hysteresis at all) and reasonably short (< 5 s, otherwise
        the bot deadlocks in REGEN under a sustained attack)."""
        assert 0.0 < ap.REGEN_NO_PROGRESS_TIMEOUT_S < 5.0

    def test_single_tick_dip_does_not_fire_escape_valve(
            self, _clock):
        """Brief damage spike while overall recovering must NOT
        kick the bot out of REGEN.  This is the 2026-05-13 log
        pathology: shields trending up but a single tick had no
        gain (damage offset regen), the escape valve fired."""
        # Step 1: enter REGEN cleanly with no threat.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],  # far
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Step 2: alien closes mid-regen, shields took a brief dip
        # (single tick of no progress), but BEFORE the hysteresis
        # window expires.
        _clock[0] += 0.3  # well under REGEN_NO_PROGRESS_TIMEOUT_S
        s["aliens"] = [{"x": 500, "y": 0, "hp": 50}]
        s["player"]["shields"] = 48  # tiny dip
        ap._do_auto(s, s["player"])
        # Hysteresis: still in REGEN despite the dip.
        assert ap._fsm["state"] == ap.S_REGEN, (
            "single-tick damage spike must not kick bot out of "
            "REGEN -- hysteresis window required before escape "
            "valve fires")

    def test_sustained_no_progress_fires_after_timeout(
            self, _clock):
        """Sustained no-progress for the full hysteresis window
        DOES fire the escape valve."""
        # Enter REGEN cleanly.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Threat closes; shields drop and stay at low level for
        # past the hysteresis window.
        _clock[0] += ap.REGEN_NO_PROGRESS_TIMEOUT_S + 0.5
        s["aliens"] = [{"x": 500, "y": 0, "hp": 50}]
        s["player"]["shields"] = 45  # dropped + no recovery
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "after REGEN_NO_PROGRESS_TIMEOUT_S of sustained "
            "no-progress while threatened, escape valve must fire")

    def test_intermittent_progress_keeps_regen_active(
            self, _clock):
        """Shields oscillating up and down but trending up overall
        keeps REGEN active.  Each tick of progress resets the
        no-progress timer, so the hysteresis window never elapses."""
        # Enter REGEN cleanly.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Threat closes.  Simulate 5 alternating ticks: dip-gain-
        # dip-gain-... covering longer than REGEN_NO_PROGRESS_TIMEOUT_S.
        s["aliens"] = [{"x": 500, "y": 0, "hp": 50}]
        sh = 50
        for tick in range(8):
            _clock[0] += 0.3  # each tick < timeout
            # Alternate -1 / +3 (net positive over time).
            sh += -1 if tick % 2 == 0 else 3
            s["player"]["shields"] = sh
            ap._do_auto(s, s["player"])
        # Bot stayed in REGEN because each gain-tick reset the
        # no-progress timer, so the hysteresis window never
        # actually elapsed.
        assert ap._fsm["state"] == ap.S_REGEN, (
            "intermittent progress should reset the no-progress "
            "timer; bot must stay in REGEN")


# ── REGEN escape-valve fast-drop shortcut (2026-05-14 eighteenth pass) ──




# ── REGEN escape-valve fast-drop shortcut (2026-05-14 eighteenth pass) ──


class TestRegenEscapeValveFastDrop:
    """2026-05-14 eighteenth telemetry pass: the 1.5 s hysteresis
    above is correct for single-tick flicker, but leaves a window
    where the bot dies if a boss grinds shields faster than the
    regen rate.  Captured pathology: bot recovered to 60 shields,
    then boss did 59 points of damage in 5 s.  Brief gain ticks
    kept resetting the no-progress timer, so the escape valve
    didn't fire until shields=1.  Bot died in recover_loot 300 ms
    later.

    Fix: if shields drop more than ``REGEN_FAST_DROP_PX`` from the
    high water mark while threatened, fire the escape valve
    immediately (bypass the 1.5 s timer).
    """

    def test_constant_pinned(self):
        """Must be positive (otherwise every tick triggers) and
        well under typical max_shields (otherwise unreachable on
        low-shield ships)."""
        assert 0.0 < ap.REGEN_FAST_DROP_PX < 50.0

    def test_fast_drop_shortcuts_hysteresis_window(self, _clock):
        """Shields crashing fast (boss DPS > regen rate) must fire
        the escape valve immediately, bypassing the 1.5 s timer."""
        # Enter REGEN with no threat.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Shields recover briefly — high water mark advances.
        _clock[0] += 0.2
        s["player"]["shields"] = 70
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Threat closes; shields crash fast.  Well under
        # REGEN_NO_PROGRESS_TIMEOUT_S has elapsed since the last
        # gain tick, but shields dropped > REGEN_FAST_DROP_PX from
        # the high water mark.
        _clock[0] += 0.3  # well under 1.5 s
        s["aliens"] = [{"x": 500, "y": 0, "hp": 50}]
        s["player"]["shields"] = int(70 - ap.REGEN_FAST_DROP_PX - 5)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "shields dropping > REGEN_FAST_DROP_PX from the high "
            "water mark while threatened must fire the escape "
            "valve immediately (bypass the 1.5 s timer)")

    def test_fast_drop_without_threat_keeps_regen(self, _clock):
        """Without a close threat there's no benefit to exiting
        REGEN early — staying parked at the station keeps regen
        ticking even if some non-threat (gas, attrition) drops
        shields.  Fast-drop shortcut must remain gated by
        ``threatened``."""
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        _clock[0] += 0.2
        s["player"]["shields"] = 70  # high water mark
        ap._do_auto(s, s["player"])
        # Shields crash but threat stays out of ENGAGE_ENTER_PX.
        _clock[0] += 0.3
        s["player"]["shields"] = int(70 - ap.REGEN_FAST_DROP_PX - 5)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "fast-drop without close threat must NOT fire the "
            "escape valve")

    def test_small_drop_under_threshold_keeps_hysteresis(
            self, _clock):
        """A drop smaller than REGEN_FAST_DROP_PX must NOT
        shortcut hysteresis — that would re-introduce the
        single-tick flicker the 1.5 s timer was designed to
        prevent."""
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        _clock[0] += 0.2
        s["player"]["shields"] = 70  # high water mark
        ap._do_auto(s, s["player"])
        # Threat closes; shields drop a bit but under the
        # fast-drop threshold.
        _clock[0] += 0.3  # under 1.5 s
        s["aliens"] = [{"x": 500, "y": 0, "hp": 50}]
        s["player"]["shields"] = int(70 - ap.REGEN_FAST_DROP_PX + 5)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "drop under REGEN_FAST_DROP_PX must not shortcut "
            "hysteresis -- 1.5 s timer still rules")




class TestRegenEscapeValveWarpZone:
    """2026-05-17: warp zones (METEOR / LIGHTNING / GAS / ENEMY)
    have ENVIRONMENTAL damage but no alien threat objects, so the
    existing threatened+stalled escape valve doesn't fire.  REGEN's
    default action is _do_idle, so the bot bleeds out from meteor /
    gas / lightning damage with no way to escape.

    Captured pathology: bot died at y=5266 in WARP_METEOR after
    20 s of REGEN-idle with shields oscillating 4-39.  Bot only
    needed to push ~1100 px further north to exit.

    Fix: escape valve also fires when bot is in a warp zone AND
    shields stalled, regardless of threat.  Cascade then re-routes
    to S_WARP_TRAVERSE which drives the bot toward the arrival band.
    """

    @staticmethod
    def _staged_regen_state(zone_id):
        ap._fsm["state"] = ap.S_REGEN
        ap._fsm["entered_at"] = 0.0
        # Stalled regen: shields oscillating but never recovering.
        ap._state.last_regen_shields = 30
        ap._state.last_regen_progress_at = 0.0
        s = _state(
            player={"x": 1600.0, "y": 5266.0, "heading": 0.0,
                    "shields": 5, "max_shields": 120},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = zone_id
        return s

    def test_regen_exits_when_stalled_in_warp_zone(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot stalled in REGEN inside WARP_METEOR with shields
        oscillating + no alien threat.  Escape valve must fire so
        the cascade can re-route to S_WARP_TRAVERSE."""
        monkeypatch.setattr(ap, "_act_warp_traverse", lambda s, p: None)
        # Set the post-boss + traverse latches so the cascade can
        # actually pick S_WARP_TRAVERSE after REGEN exits.
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        _clock[0] = 100.0  # advance past REGEN_NO_PROGRESS_TIMEOUT
        s = self._staged_regen_state("ZoneID.WARP_METEOR")
        ap._do_auto(s, s["player"])
        # Escape valve fired -- bot is now in S_WARP_TRAVERSE,
        # not S_REGEN.
        assert ap._fsm["state"] == ap.S_WARP_TRAVERSE

    def test_regen_stays_in_main_with_no_threat(
            self, _clock, _fresh_bot_state):
        """Bot stalled in REGEN in MAIN with no threat.  Without a
        threat AND not in a warp zone, the bot stays in REGEN --
        the warp-zone relaxation does NOT affect MAIN behavior."""
        _clock[0] = 100.0  # advance past timeout
        s = self._staged_regen_state("ZoneID.MAIN")
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_regen_exits_in_warp_gas_zone(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Mirror of the METEOR case for WARP_GAS.  Same
        environmental-damage mechanic, same fix applies."""
        monkeypatch.setattr(ap, "_act_warp_traverse", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        _clock[0] = 100.0
        s = self._staged_regen_state("ZoneID.WARP_GAS")
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TRAVERSE

    def test_regen_stays_when_not_stalled_in_warp_zone(
            self, _clock, _fresh_bot_state):
        """If shields ARE recovering in a warp zone (e.g. heal
        cooldown is winning), stay in REGEN -- the relaxation only
        kicks in when shields are stalled."""
        ap._fsm["state"] = ap.S_REGEN
        ap._fsm["entered_at"] = 0.0
        ap._state.last_regen_shields = 5
        ap._state.last_regen_progress_at = 100.0
        _clock[0] = 100.1   # only 0.1 s since last progress
        s = _state(
            player={"x": 1600.0, "y": 5266.0, "heading": 0.0,
                    "shields": 30, "max_shields": 120},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_METEOR"
        # Shields gained from 5 -> 30 just now: timer reset.
        # Stalled gate (1.5 s or 20 px drop) hasn't fired.
        ap._do_auto(s, s["player"])
        # Stay in REGEN -- shields are recovering.
        assert ap._fsm["state"] == ap.S_REGEN


# ── REGEN entry-side mirror (2026-05-04 anti-thrash) ─────────────────



# ── REGEN entry-side mirror (2026-05-04 anti-thrash) ─────────────────

class TestRegenEntryWhileThreatenedSuppressed:
    """Entry-side mirror of the escape valve.  When the bot is in
    a non-REGEN state with a close threat, dipping below
    REGEN_ENTER_PCT must NOT transition into REGEN — the escape
    valve would just send it right back next tick, and the resulting
    11/s flip wastes CPU + triggers 14 stuck_detected misfires per
    combat encounter.  Telemetry (2026-05-04 evening) captured
    111 REGEN<->ENGAGE transitions in a single fight, median dwell
    0.09 s (one tick).  Fix: stay in ENGAGE while threatened, even
    at low shields.
    """

    def test_engage_at_low_shields_with_close_threat_does_not_enter_regen(
            self, _clock):
        # Bot already in ENGAGE.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 400, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        # Shields drop into REGEN territory while alien is still close.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s["player"]["shields"] = 50  # 33 % — below REGEN_ENTER_PCT
        ap._do_auto(s, s["player"])
        # Entry-side mirror suppresses REGEN — bot stays in ENGAGE.
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "REGEN entry should be suppressed when a close threat "
            "is engaging — escape valve would just send us back")

    def test_low_shields_no_close_threat_does_enter_regen(self, _clock):
        """Sanity: with no close threat, low shields DOES trigger
        REGEN normally (the suppression is gated on threat presence).
        """
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 5000, "y": 0, "hp": 50}],  # far away
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_low_shields_far_threat_does_enter_regen(self, _clock):
        """Threat exists but is past ENGAGE_ENTER_PX — REGEN should
        fire normally."""
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 50, "max_shields": 150},
            aliens=[{"x": 1500, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        # 1500 px > ENGAGE_ENTER_PX (800 px), so REGEN fires.
        assert ap._fsm["state"] == ap.S_REGEN

    def test_no_regen_engage_thrash_over_many_ticks(self, _clock):
        """End-to-end pin for the headline pathology: 30 ticks of
        sustained low-shields combat must produce AT MOST a couple
        of state transitions, NOT 30 REGEN<->ENGAGE flips.

        Pre-fix, this loop produced ~30 transitions (one per tick
        because both states bypass MIN_DWELL).  Post-fix, the bot
        stays in ENGAGE the entire time."""
        # Start in ENGAGE.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "shields": 100, "max_shields": 150},
            aliens=[{"x": 400, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        transitions: list = []
        # Sustained combat: shields hover around 25-30%, alien
        # stays close.  Drive 30 ticks (3 s of game time).
        for i in range(30):
            prev = ap._fsm["state"]
            _clock[0] += 0.1
            # Shields wobble between 25-35% (actively under fire).
            s["player"]["shields"] = 40 + (i % 5) - 2
            ap._do_auto(s, s["player"])
            if ap._fsm["state"] != prev:
                transitions.append((prev, ap._fsm["state"]))
        # Pre-fix: ~30 transitions.  Post-fix: 0 (stays in ENGAGE).
        assert len(transitions) <= 2, (
            f"REGEN<->ENGAGE thrash regression: {len(transitions)} "
            f"transitions in 30 ticks: {transitions}")
        assert ap._fsm["state"] == ap.S_ENGAGE




class TestRegenBossAliveThresholds:
    """2026-05-13 fourteenth telemetry pass: post-recovery
    install → engage_boss fired at shields=54/120 (45 %), one
    lure trigger later (35 %), then died.  With a boss alive
    the bot must regen further before re-engaging.  Raise the
    thresholds when ``state.boss is not None``: enter at
    ``REGEN_ENTER_PCT_BOSS_ALIVE`` (0.70) instead of 0.40; exit
    at ``REGEN_EXIT_PCT_BOSS_ALIVE`` (0.85) instead of 0.60.
    Escape valve (close-threat exit) still applies.
    """

    def test_constants_pinned(self):
        """Sanity gate on the new constants: enter < exit (so
        REGEN has room to actually run), and both > the no-boss
        baselines (so boss-alive is strictly more conservative)."""
        assert ap.REGEN_ENTER_PCT_BOSS_ALIVE > ap.REGEN_ENTER_PCT
        assert ap.REGEN_EXIT_PCT_BOSS_ALIVE > ap.REGEN_EXIT_PCT
        assert (ap.REGEN_ENTER_PCT_BOSS_ALIVE
                < ap.REGEN_EXIT_PCT_BOSS_ALIVE)

    def test_boss_alive_higher_enter_threshold(self, _clock):
        """Boss alive + shields = 50 % + boss out of immediate
        threat range (> ENGAGE_ENTER_PX) => REGEN fires.  Without
        the boss-alive bump (enter=40 %), 50 % > 40 % so REGEN
        wouldn't fire and the bot would engage the boss.
        """
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 75, "max_shields": 150},  # 50 %
            # No aliens nearby; boss far away (out of escape-valve
            # range so REGEN holds).
        )
        s["boss"] = _boss(x=5000.0, y=5000.0)  # far
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "boss alive + 50 % shields + boss out of threat range "
            "must enter REGEN under boss-alive thresholds")

    def test_no_boss_unchanged_baseline_enter_threshold(
            self, _clock):
        """Sanity: no boss => baseline thresholds, so 50 % shields
        does NOT enter REGEN (above the 40 % baseline enter)."""
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 75, "max_shields": 150},  # 50 %
        )
        # No boss.  50 % > 40 % baseline => no REGEN.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN

    def test_boss_alive_higher_exit_threshold(self, _clock):
        """In REGEN with boss alive + shields = 70 % + boss far =>
        REGEN holds (70 % < 85 % boss-alive exit).  Without the
        bump (exit=60 %), 70 % > 60 % so REGEN would exit early.
        """
        # Force REGEN entry first.
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},  # 20 %
        )
        s["boss"] = _boss(x=5000.0, y=5000.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Shields recover to 70 %.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s["player"]["shields"] = 105  # 70 %
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "boss alive + 70 % shields must hold REGEN under "
            "the 85 % boss-alive exit threshold")

    def test_boss_alive_exit_at_high_shields(self, _clock):
        """Shields reach the boss-alive exit threshold (85 %+) =>
        REGEN exits and the FSM proceeds to ENGAGE_BOSS."""
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        s["boss"] = _boss(x=5000.0, y=5000.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Shields recover to 90 % -- past the 85 % exit threshold.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s["player"]["shields"] = 135  # 90 %
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN

    def test_escape_valve_still_fires_under_boss_alive(
            self, _clock):
        """Boss alive + shields not recovering + boss within
        ENGAGE_ENTER_PX => after the REGEN_NO_PROGRESS_TIMEOUT_S
        hysteresis window, the escape valve fires regardless of
        the higher boss-alive thresholds, so the bot doesn't
        deadlock at the station while the boss attacks."""
        # Force REGEN entry.
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},  # 20 %
        )
        s["boss"] = _boss(x=5000.0, y=5000.0)  # far for entry
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Boss closes to ENGAGE range; shields not recovering for
        # the hysteresis window.
        _clock[0] += ap.REGEN_NO_PROGRESS_TIMEOUT_S + 0.2
        s["boss"] = _boss(x=400.0, y=0.0)  # within ENGAGE_ENTER_PX
        s["player"]["shields"] = 25  # dropped (not recovering)
        ap._do_auto(s, s["player"])
        # Escape valve fires => bot exits REGEN, takes another
        # priority (ENGAGE_BOSS).
        assert ap._fsm["state"] != ap.S_REGEN


# ── GATHER hysteresis ─────────────────────────────────────────────────────




class TestRegenExemptFromStuckDetect:
    """S_REGEN's action is ``_do_idle()`` — the bot intentionally
    parks and waits for shields to recover.  Zero movement is the
    point, so the watchdog fires every cycle if not exempt.  Caught
    from 2026-05-05 telemetry: a single 40 s REGEN run produced 8
    stuck_detected events; each escape burst shoved the bot ~700 px
    until it pinned against an edge."""

    def test_no_escape_in_regen_when_idle(self, _clock):
        """Drop shields below REGEN_ENTER_PCT with no close threat —
        FSM enters REGEN.  Run the full detect window: NO escape
        should fire because REGEN is exempt."""
        # Shields at 30% — below REGEN_ENTER_PCT (0.40) — and no
        # alien within ENGAGE_ENTER_PX so the entry gate opens.
        for _ in range(20):
            s = _state(player={
                "x": 3200.0, "y": 3200.0, "heading": 0.0,
                "shields": 45, "max_shields": 150,
            })
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._fsm["state"] == ap.S_REGEN, (
            "test setup invariant — FSM should enter REGEN when "
            "shields < 40% and no close threat is visible")
        assert ap._stuck_state["escape_until"] == 0.0, (
            "S_REGEN must be exempt from stuck-detect — the bot is "
            "intentionally idling so the watchdog's zero-movement "
            "criterion always fires otherwise")




class TestRegenFleesBossWhenNoHomeStation:
    """2026-05-14 eighteenth telemetry pass.  REGEN's default
    action is ``_do_idle`` -- the bot parks in place while
    shields recover.  When the home station has been destroyed
    AND a boss is alive, idling = death: boss closes on the
    parked bot before shields climb back.  Captured pathology:
    12 deaths in 60 s after HS destruction.

    Fix: in ``_act_regen``, when no HS exists AND a boss is
    alive, actively flee away from the boss toward the world
    edge.  Idle behavior preserved in every other case.
    """

    def test_no_hs_with_boss_flees_away_from_boss(
            self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=120.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_do_idle", lambda: captured.update(idled=True))
        # Bot east of boss, no HS, boss alive.  Expect flee
        # target FURTHER east than the bot's current position
        # (away from boss).
        s = _state(
            player={"x": 3300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        s["boss"] = _boss(x=3000.0, y=3000.0)
        ap._act_regen(s, s["player"])
        assert "idled" not in captured, (
            "no-HS REGEN with boss alive must actively flee, "
            "not idle")
        assert captured.get("tx", 0.0) > 3300.0, (
            "flee target must be east of bot (away from boss "
            "at x=3000)")

    def test_hs_present_drives_to_hs_for_healing(self, monkeypatch):
        """Updated 2026-05-23: with HS present and bot outside the
        REGEN_HS_DRIVE_RADIUS_PX, REGEN drives to the HS so the
        game-side healing umbrella (REPAIR_RANGE = 300 px) kicks
        in.  Previously the action handler idled in place wherever
        shields dropped -- captured pathology: 120 s REGEN dwell
        regenerating slowly at the base rate while the umbrella
        was a quick drive away.

        Boss-fight + HS path uses the same drive logic (the bot
        runs toward HS, and the umbrella also has station turrets
        + station shield protecting it)."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(
                fled=True, tx=tx, ty=ty))
        monkeypatch.setattr(
            ap, "_do_idle",
            lambda: captured.update(idled=True))
        s = _state(
            player={"x": 3300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=3000.0, y=3000.0)
        ap._act_regen(s, s["player"])
        # 1220 px from HS -- well outside REGEN_HS_DRIVE_RADIUS_PX
        # so the bot drives TOWARD the HS, not away from boss.
        assert "fled" in captured and "idled" not in captured, (
            "with HS present, REGEN drives toward HS for the "
            "healing umbrella (no longer idles in place)")
        assert captured["tx"] == 4000.0 and captured["ty"] == 4000.0

    def test_no_boss_idles_normally(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: captured.update(fled=True))
        monkeypatch.setattr(ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 3300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        # No boss key at all -- standard small-alien encounter
        # that drove the bot into REGEN.
        ap._act_regen(s, s["player"])
        assert "idled" in captured and "fled" not in captured




class TestRegenGasCloudEscape:
    """2026-05-15: in the Nebula (ZONE2), the bot would park
    inside a gas cloud while in REGEN and sit there indefinitely
    -- gas does 15 dmg/0.5 s and slows the ship, so shields never
    recover past the damage rate.  Captured pathology: bot at
    (2986, 5750) in the Nebula for 30+ s with shields stuck at
    1-2/120, no aliens in range so the REGEN escape valve
    didn't fire either (gas isn't an alien threat).

    Fix: ``_act_regen`` now checks ``state.gas_areas`` first.  If
    the bot is inside any cloud, drive along the cloud-centre ->
    bot ray to a point past the cloud edge so the bot ends up
    clear of the damage field, not idling inside it.  Priority
    is ABOVE the boss-flee branch (gas damage compounds faster
    than a kiting boss).
    """

    def test_inside_gas_cloud_drives_outward(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(
                tx=tx, ty=ty, called=True))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 1100.0, "y": 1000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        # Cloud to the WEST of the bot; bot is 100 px inside the
        # cloud's 200 px radius.
        s["gas_areas"] = [
            {"x": 1000.0, "y": 1000.0, "radius": 200.0},
        ]
        ap._act_regen(s, s["player"])
        # Drives EAST (away from cloud centre at x=1000) -- target
        # x must exceed the bot's current x.
        assert "called" in captured
        assert "idled" not in captured
        assert captured["tx"] > 1100.0
        # Target should sit past the cloud edge (radius + margin).
        from math import hypot
        d_from_centre = hypot(
            captured["tx"] - 1000.0, captured["ty"] - 1000.0)
        expected = 200.0 + ap.REGEN_GAS_ESCAPE_MARGIN_PX
        assert abs(d_from_centre - expected) < 5.0

    def test_outside_all_clouds_idles_normally(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: captured.update(fled=True))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 5000.0, "y": 5000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        # Cloud exists but bot is far from it.
        s["gas_areas"] = [
            {"x": 100.0, "y": 100.0, "radius": 200.0},
        ]
        ap._act_regen(s, s["player"])
        assert "idled" in captured
        assert "fled" not in captured

    def test_no_gas_areas_idles_normally(self, monkeypatch):
        """Regression: when state has no ``gas_areas`` key (older
        API or non-gas zone), default idle behaviour is preserved."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: captured.update(fled=True))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 3300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        # Don't set gas_areas key at all.
        ap._act_regen(s, s["player"])
        assert "idled" in captured

    def test_gas_escape_takes_priority_over_boss_flee(
            self, monkeypatch):
        """When both conditions hold (in a gas cloud AND boss
        alive without HS), the gas escape wins -- gas damage
        compounds faster than a kiting boss."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(
                tx=tx, ty=ty, called=True))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 1100.0, "y": 1000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        # Cloud west; bot inside.  Boss far east so flee-from-boss
        # would also target eastward direction -- isolate gas
        # escape by having the boss FURTHER east than the bot.
        # If the gas branch fires, target sits at cloud-edge +
        # margin from cloud centre (~400 east of (1000,1000)).
        # If boss-flee fires, target is BOSS_FLEE_TARGET_PX (2000)
        # east of boss at (5000,1000) -> (7000,1000).
        s["gas_areas"] = [
            {"x": 1000.0, "y": 1000.0, "radius": 200.0},
        ]
        s["boss"] = _boss(x=5000.0, y=1000.0)
        ap._act_regen(s, s["player"])
        assert "called" in captured
        # Target distance from cloud centre matches gas-escape,
        # not boss-flee.
        from math import hypot
        d_from_cloud = hypot(
            captured["tx"] - 1000.0, captured["ty"] - 1000.0)
        expected = 200.0 + ap.REGEN_GAS_ESCAPE_MARGIN_PX
        assert abs(d_from_cloud - expected) < 5.0




# ── Warp-zone swarm REGEN suppression (2026-05-23) ────────────────────────


class TestWarpSwarmRegenSuppression:
    """Pin the symmetric REGEN suppression: in a warp zone with too
    many aliens to safely idle, REGEN entry is blocked AND an
    already-in-REGEN bot exits immediately on the next tick.

    Captured pathology (2026-05-23 telemetry): 4 of 6 most recent
    player deaths were in REGEN state in WARP_ENEMY arcs with
    52-60 aliens visible.  REGEN's action is ``_do_idle`` -- safe
    under normal conditions but a death sentence under swarm DPS.
    Suppressing REGEN there lets WARP_TRAVERSE keep the bot
    moving toward the exit; combat assist still auto-aims + fires
    every frame, and consumables still auto-trigger at the
    existing HP/shield thresholds.

    Mirror of ``TestWarpSwarmEngageSuppression`` (PR #155) for the
    REGEN side of the same failure family.
    """

    def _warp_state(self, alien_count=20, in_warp_zone=True,
                    cur_state=None, shields=30, max_shields=120,
                    alien_close=False):
        """Build a state with ``alien_count`` aliens.  If
        ``alien_close`` is False, aliens are placed at x=5000+
        (well outside ENGAGE_ENTER_PX) so the ``threatened`` gate
        in REGEN entry is False -- which is the gate the swarm
        suppression is meant to backstop."""
        zone_id = "ZoneID.WARP_ENEMY" if in_warp_zone else "ZoneID.MAIN"
        if alien_close:
            aliens = [{"x": 100.0 + i * 50.0, "y": 0.0, "hp": 50}
                      for i in range(alien_count)]
        else:
            aliens = [{"x": 5000.0 + i * 50.0, "y": 5000.0, "hp": 50}
                      for i in range(alien_count)]
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": shields, "max_shields": max_shields},
            aliens=aliens,
        )
        s["zone"] = {"world_w": 6400, "world_h": 8000,
                     "zone_id": zone_id, "id": zone_id}
        if cur_state is not None:
            ap._fsm["state"] = cur_state
        return s

    def test_swarm_in_warp_zone_suppresses_regen_entry(
            self, _clock):
        """Bot at low shields with 20 aliens in WARP_ENEMY (none
        close enough to trigger ``threatened``).  Without this
        suppression REGEN would fire on the entry path.  With it,
        REGEN entry is blocked -- bot stays in current state."""
        s = self._warp_state(
            alien_count=20, shields=30,   # ~25 %, below 40 % enter
            alien_close=False,
            cur_state=ap.S_WARP_TRAVERSE,
        )
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN, (
            "REGEN must be suppressed for swarms in warp zones")

    def test_threshold_boundary_just_below_suppresses_nothing(
            self, _clock):
        """One alien below the threshold: normal REGEN entry
        applies."""
        s = self._warp_state(
            alien_count=ap.WARP_SWARM_REGEN_SUPPRESS_ALIENS - 1,
            shields=30, alien_close=False)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_threshold_boundary_at_threshold_suppresses(
            self, _clock):
        """At the exact threshold, REGEN is suppressed."""
        s = self._warp_state(
            alien_count=ap.WARP_SWARM_REGEN_SUPPRESS_ALIENS,
            shields=30, alien_close=False,
            cur_state=ap.S_WARP_TRAVERSE)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN

    def test_main_zone_with_many_aliens_still_enters_regen(
            self, _clock):
        """Outside warp zones REGEN behaves normally: shields below
        threshold + not-threatened-by-close-alien = enter REGEN."""
        s = self._warp_state(
            alien_count=20, shields=30, in_warp_zone=False,
            alien_close=False)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_warp_zone_with_few_aliens_still_enters_regen(
            self, _clock):
        """Sparse warp zone (METEOR, GAS, LIGHTNING) doesn't trip
        the gate; the existing in-warp-zone escape valve continues
        to handle environmental damage cases as before."""
        s = self._warp_state(
            alien_count=3, shields=30, alien_close=False)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_already_in_regen_exits_under_warp_swarm(self, _clock):
        """The hold-side branch: bot already in REGEN, swarm
        appears.  The new swarm-escape-valve fires immediately --
        no waiting for the 1.5 s no-progress timer.  Without this
        the bot would idle for 1.5 s under 50+ alien DPS and die.
        """
        s = self._warp_state(
            alien_count=20, shields=50,   # below regen_exit
            alien_close=False,
            cur_state=ap.S_REGEN)
        # Set the REGEN-entry timers so the stall logic has a
        # baseline.  Make shields appear to be RECOVERING so the
        # stall escape valve does NOT fire -- only the new
        # swarm-suppress should drive the exit.
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.last_regen_shields = 50
        ap._state.last_regen_progress_at = _clock[0]
        ap._fsm["entered_at"] = _clock[0]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN, (
            "swarm suppression must release REGEN immediately, "
            "without the 1.5 s stall-timer wait")

    def test_engage_suppression_and_regen_suppression_compose(
            self, _clock):
        """Both PR #155 (ENGAGE suppress) and this PR (REGEN
        suppress) fire together in WARP_ENEMY.  Bot at low shields
        with aliens in engage range: ENGAGE blocked, REGEN
        blocked, fall through to WARP_TRAVERSE."""
        s = self._warp_state(
            alien_count=20, shields=30,
            alien_close=True,   # in engage range
            cur_state=ap.S_WARP_TRAVERSE)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE, (
            "ENGAGE must stay suppressed (PR #155)")
        assert ap._fsm["state"] != ap.S_REGEN, (
            "REGEN must also be suppressed (PR #161)")
        assert ap._fsm["state"] == ap.S_WARP_TRAVERSE, (
            "fall through to WARP_TRAVERSE so bot keeps moving")




class TestOutsideBaseSwarmRegenSuppression:
    """The 2026-05-23 v2 broadening: REGEN suppression also fires
    in ZONE2 (Nebula), STAR_MAZE, and any non-MAIN zone where
    spawners can produce swarm densities.  Captured pathology:
    29 REGEN deaths in a row at ~(3975, 4250) -- some in
    WARP_ENEMY but at least some in ZONE2 / STAR_MAZE where
    PR #162's WARP-only gate didn't fire.  Broader gate covers
    every zone except MAIN, which is the only zone where the HS
    umbrella + station shield-regen makes REGEN's idle work."""

    def _state_in_zone(self, zone_name, alien_count=20,
                       shields=30, max_shields=100,
                       cur_state=None, iron=0):
        zone_id = f"ZoneID.{zone_name}"
        # Aliens placed far away so the ``threatened`` gate is False
        # -- the swarm-suppress gate is what's under test.
        aliens = [{"x": 5000.0 + i * 50.0, "y": 5000.0, "hp": 50}
                  for i in range(alien_count)]
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": shields, "max_shields": max_shields},
            aliens=aliens,
            iron=iron,
        )
        s["zone"] = {"world_w": 6400, "world_h": 6400,
                     "zone_id": zone_id, "id": zone_id}
        if cur_state is not None:
            ap._fsm["state"] = cur_state
        return s

    def test_zone2_nebula_swarm_suppresses_regen_with_build_alt(
            self, _clock):
        """ZONE2 with 20 aliens + iron + no Nebula HS -- the
        productive alternative S_BUILD_NEBULA is viable, so the
        REGEN-swarm-suppress fires and REGEN entry is blocked.

        Updated 2026-05-24: requires the BUILD_NEBULA productive
        alternative to be set up (iron + not built), matching
        the conditional gate that mirrors PR #169's ENGAGE
        treatment."""
        s = self._state_in_zone("ZONE2", alien_count=20,
                                shields=30,
                                iron=ap.BUILD_IRON_THRESHOLD)
        ap._state.nebula_build_done = False
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN, (
            "REGEN must be suppressed when there's a productive "
            "alternative (BUILD_NEBULA) to fall through to")

    def test_zone2_swarm_without_build_alt_enters_regen(
            self, _clock):
        """The 2026-05-24 fix path: bot in ZONE2 with swarm BUT
        Nebula HS already exists (no build alternative).  Without
        a productive alternative the bot stays in REGEN so PR #167's
        drive-to-HS healing kicks in.

        Matches the user's broader complaint pattern: don't
        block REGEN unnecessarily.  When the bot has no other
        useful thing to do, recovering shields under the HS
        umbrella is the right move."""
        s = self._state_in_zone("ZONE2", alien_count=20,
                                shields=30)
        # Nebula HS already exists -- no build alternative.
        ap._state.nebula_build_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "REGEN must fire when no productive alternative is "
            "available -- bot needs healing, not blocked")

    def test_star_maze_swarm_enters_regen_no_productive_alt(
            self, _clock):
        """STAR_MAZE has no warp-traverse goal AND no build_nebula
        path.  Per the conditional gate, REGEN fires so the bot
        recovers.  Combat assist still defends reflexively.
        Updated from PR #165 (which unconditionally suppressed)."""
        s = self._state_in_zone("STAR_MAZE", alien_count=20,
                                shields=30)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_nebula_warp_zone_swarm_suppresses_regen_with_traverse(
            self, _clock):
        """NEBULA_WARP_ENEMY with the warp-traverse arc active --
        the productive alternative is viable, so REGEN is
        suppressed and the traverse continues."""
        s = self._state_in_zone(
            "NEBULA_WARP_ENEMY", alien_count=20, shields=30)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_REGEN

    def test_main_zone_swarm_still_enters_regen(self, _clock):
        """MAIN with 20 aliens -- HS umbrella exists here, REGEN
        is the right action.  Gate must NOT fire."""
        s = self._state_in_zone("MAIN", alien_count=20, shields=30)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "REGEN must still fire in MAIN (HS umbrella means "
            "idle recovery actually works)")

    def test_main_with_sparse_aliens_still_enters_regen(
            self, _clock):
        """MAIN with few aliens: REGEN fires as expected (default
        behaviour, untouched)."""
        s = self._state_in_zone("MAIN", alien_count=3, shields=30)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_zone2_sparse_aliens_still_enters_regen(self, _clock):
        """ZONE2 with < threshold aliens: no swarm, no suppress.
        The bot can safely idle there because the encounter is
        manageable."""
        s = self._state_in_zone(
            "ZONE2",
            alien_count=ap.WARP_SWARM_REGEN_SUPPRESS_ALIENS - 1,
            shields=30)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_already_in_regen_choose_releases_under_zone2_swarm_with_alt(
            self, _clock):
        """Hold-side branch: bot in REGEN in ZONE2 with a swarm
        AND a productive alternative (BUILD_NEBULA viable).
        ``choose_next_state`` returns something OTHER than REGEN
        -- the swarm-suppress escape fires regardless of stall
        timer.

        Updated 2026-05-24: requires the BUILD_NEBULA productive
        alt to be set up.  When NO alt is available the bot
        stays in REGEN (tested by
        ``test_zone2_swarm_without_build_alt_enters_regen``)."""
        s = self._state_in_zone(
            "ZONE2", alien_count=20, shields=50,
            iron=ap.BUILD_IRON_THRESHOLD)
        ap._state.nebula_build_done = False
        ap._state.last_regen_shields = 50
        ap._state.last_regen_progress_at = _clock[0]
        desired = ap._choose_next_state(s, s["player"],
                                         cur=ap.S_REGEN)
        assert desired != ap.S_REGEN, (
            "choose must NOT return S_REGEN for a swarmed bot "
            "in REGEN with a viable build_nebula alt -- the "
            "escape valve fires regardless of stall timer")


# ── Nebula starter base (2026-05-23) ──────────────────────────────────────




# ── REGEN drive-to-HS for the healing umbrella (2026-05-23) ────────────────


class TestRegenDrivesToHomeStation:
    """The 2026-05-23 follow-up: when REGEN fires with an HS in
    the current zone, the action handler drives the bot toward
    the HS so it lands inside the game's ``REPAIR_RANGE`` (300 px)
    healing umbrella.  Inside that radius shield regen gets the
    ``REPAIR_SHIELD_BOOST`` bonus AND HP regen activates -- both
    only happen near home.

    Captured pathology: bot sat in REGEN for 120 s wherever
    shields dropped (typically 1000+ px from HS), regenerating
    at the slow base rate while the umbrella was a quick drive
    away.  Driving to HS first then idling is strictly faster
    recovery.

    The drive threshold (REGEN_HS_DRIVE_RADIUS_PX = 250) is
    INSIDE the game's REPAIR_RANGE (300) so a single tick of
    repulsion can't bump the bot out of the umbrella mid-heal.
    """

    def test_far_from_hs_drives_toward_it(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(
                tx=tx, ty=ty, stop=stop_radius))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
            buildings=[{"x": 3000.0, "y": 3000.0,
                        "building_type": "Home Station"}],
        )
        ap._act_regen(s, s["player"])
        assert captured.get("tx") == 3000.0
        assert captured.get("ty") == 3000.0
        assert captured.get("stop") == ap.REGEN_HS_DRIVE_STOP_PX
        assert "idled" not in captured

    def test_inside_umbrella_idles(self, monkeypatch):
        """When already within REGEN_HS_DRIVE_RADIUS_PX of HS,
        idle (don't waste regen ticks on thrust input)."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: captured.update(drove=True))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        # 100 px from HS -- well inside the 250 px drive radius.
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
            buildings=[{"x": 3100.0, "y": 3000.0,
                        "building_type": "Home Station"}],
        )
        ap._act_regen(s, s["player"])
        assert captured.get("idled") is True
        assert "drove" not in captured

    def test_boss_alive_still_drives_to_hs(self, monkeypatch):
        """The HS-drive path applies regardless of boss state --
        during a boss fight, driving to HS also brings the bot
        under the station shield + turret coverage.  Replaces
        the prior "boss alive + HS = idle in place" behaviour."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
            buildings=[{"x": 3000.0, "y": 3000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = {"x": 800.0, "y": 1000.0, "hp": 1000,
                     "phase": 1}
        ap._act_regen(s, s["player"])
        assert captured.get("tx") == 3000.0
        assert captured.get("ty") == 3000.0
        assert "idled" not in captured

    def test_no_hs_no_boss_still_idles(self, monkeypatch):
        """Existing behaviour preserved: no HS + no boss = idle
        in place (early-game fallback, pre-starter-base)."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: captured.update(drove=True))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        ap._act_regen(s, s["player"])
        assert captured.get("idled") is True
        assert "drove" not in captured

    def test_no_hs_boss_alive_still_flees(self, monkeypatch):
        """Existing behaviour preserved: no HS + boss alive =
        actively flee away from boss (the no-umbrella case)."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 3300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        s["boss"] = {"x": 3000.0, "y": 3000.0, "hp": 1000,
                     "phase": 1}
        ap._act_regen(s, s["player"])
        # Flee target is east of bot (away from boss at x=3000),
        # not the HS coordinates.
        assert captured.get("tx", 0.0) > 3300.0
        assert "idled" not in captured

    def test_gas_cloud_escape_still_takes_priority(
            self, monkeypatch):
        """Existing gas-escape branch still fires first (top-of-
        function priority) -- HS-drive doesn't override it.
        Captured pathology that motivated the gas-escape branch:
        bot parked inside a gas cloud in REGEN with shields stuck
        at 1-2/120."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        # Bot inside a gas cloud AND far from HS -- gas should win.
        s = _state(
            player={"x": 3300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
        )
        s["gas_areas"] = [
            {"x": 3300.0, "y": 3000.0, "radius": 200.0}
        ]
        ap._act_regen(s, s["player"])
        # Gas escape drives AWAY from cloud centre, not toward HS.
        # Cloud at bot position -- direction depends on the
        # degenerate-axis fallback (+X by default).
        assert captured.get("tx") != 1000.0, (
            "gas escape must take priority over HS drive")


# ── ENGAGE outside-base swarm suppression (2026-05-23 v3) ─────────────────




# ── Swarm-suppress productive-alt helper ──────────────────────────────────


class TestOutsideMainSwarmSuppresses:
    """Direct tests for ``bot_autopilot_choose._outside_main_swarm_suppresses``
    -- the predicate hoisted from the duplicated ENGAGE / REGEN
    inline blocks.  These pin the contract independently of the
    full FSM cascade so future refactors of choose_next_state can
    move call sites without unintended behavioural drift.
    """

    @staticmethod
    def _import():
        import bot_autopilot_choose as choose
        return choose._outside_main_swarm_suppresses

    def _state(self, *, zone_id: str, alien_count: int = 10,
               iron: int = 0, boss_defeated: bool = True) -> dict:
        return {
            "zone": {"id": zone_id},
            "aliens": [{"x": 0.0, "y": 0.0, "hp": 1}
                       for _ in range(alien_count)],
            "boss_defeated": boss_defeated,
            "inventory": {"items": {"iron": iron}},
            "station_inventory": {"items": {}},
        }

    def test_main_zone_never_suppresses(self):
        fn = self._import()
        s = self._state(zone_id="ZoneID.MAIN", alien_count=100)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        assert fn(s, "ZoneID.MAIN", 5) is False

    def test_warp_zone_with_post_boss_traverse_alt_suppresses(self):
        fn = self._import()
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        s = self._state(zone_id="ZoneID.WARP_ENEMY",
                        alien_count=ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS)
        assert fn(s, "ZoneID.WARP_ENEMY",
                  ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS) is True

    def test_warp_zone_pre_boss_does_not_suppress(self):
        """No productive alt -- bot hasn't beaten the boss yet, so
        WARP_TRAVERSE isn't a goal.  ENGAGE / REGEN should fire."""
        fn = self._import()
        ap._state.boss_was_killed = False
        ap._state.warp_after_boss_done = False
        ap._state.warp_traverse_done = False
        s = self._state(zone_id="ZoneID.WARP_ENEMY",
                        alien_count=50, boss_defeated=False)
        assert fn(s, "ZoneID.WARP_ENEMY", 5) is False

    def test_zone2_with_iron_and_no_hs_suppresses(self):
        fn = self._import()
        ap._state.nebula_build_done = False
        s = self._state(zone_id="ZoneID.ZONE2",
                        alien_count=ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS,
                        iron=ap.BUILD_IRON_THRESHOLD)
        assert fn(s, "ZoneID.ZONE2",
                  ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS) is True

    def test_zone2_with_hs_already_built_does_not_suppress(self):
        fn = self._import()
        ap._state.nebula_build_done = True
        s = self._state(zone_id="ZoneID.ZONE2", alien_count=50,
                        iron=ap.BUILD_IRON_THRESHOLD)
        assert fn(s, "ZoneID.ZONE2", 5) is False

    def test_zone2_with_no_iron_does_not_suppress(self):
        fn = self._import()
        ap._state.nebula_build_done = False
        s = self._state(zone_id="ZoneID.ZONE2", alien_count=50, iron=0)
        assert fn(s, "ZoneID.ZONE2", 5) is False

    def test_below_threshold_does_not_suppress(self):
        """All productive-alt gates satisfied but alien count below
        threshold -- helper returns False."""
        fn = self._import()
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        s = self._state(zone_id="ZoneID.WARP_ENEMY", alien_count=2)
        assert fn(s, "ZoneID.WARP_ENEMY", 5) is False

    def test_engage_and_regen_share_predicate(self):
        """Sanity: same productive-alt gate, just different alien
        thresholds.  Verify both ENGAGE and REGEN constants drive
        the helper identically."""
        fn = self._import()
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        threshold_engage = ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS
        threshold_regen = ap.WARP_SWARM_REGEN_SUPPRESS_ALIENS
        n = max(threshold_engage, threshold_regen)
        s = self._state(zone_id="ZoneID.WARP_ENEMY", alien_count=n)
        assert fn(s, "ZoneID.WARP_ENEMY", threshold_engage) is True
        assert fn(s, "ZoneID.WARP_ENEMY", threshold_regen) is True


# ── _act_regen sub-handler dispatch ───────────────────────────────────────




# ── _act_regen sub-handler dispatch ───────────────────────────────────────


class TestActRegenDispatcher:
    """Verifies the ``_act_regen`` dispatcher routes to the correct
    sub-handler based on world state.  The behavioural assertions
    (cloud-edge target math, HS umbrella interior point, ray-from-
    boss flee) live in the long-standing ``TestRegenGasCloudEscape``
    and ``TestRegenFleesBossWhenNoHomeStation`` classes above; these
    tests only pin the dispatcher's priority order so future routing
    changes can't silently swap a branch.

    Priority order: gas-escape > drive-to-HS > flee-boss > idle.
    """

    def _setup_patches(self, monkeypatch):
        captured: dict = {"calls": []}
        import bot_autopilot_actions_combat as combat

        def _stub(name):
            def _fn(*a, **kw):
                captured["calls"].append(name)
            return _fn

        monkeypatch.setattr(combat, "_regen_gas_escape",
                            _stub("gas_escape"))
        monkeypatch.setattr(combat, "_regen_drive_to_hs",
                            _stub("drive_to_hs"))
        monkeypatch.setattr(combat, "_regen_flee_boss",
                            _stub("flee_boss"))
        monkeypatch.setattr(ap, "_do_idle",
                            lambda: captured["calls"].append("idle"))
        return captured

    def test_gas_cloud_present_routes_to_gas_escape(
            self, monkeypatch):
        captured = self._setup_patches(monkeypatch)
        s = _state(player={"x": 1100.0, "y": 1000.0, "heading": 0.0,
                           "shields": 30, "max_shields": 150})
        s["gas_areas"] = [{"x": 1000.0, "y": 1000.0, "radius": 200.0}]
        # Also put HS + boss in scene -- gas must win regardless.
        s["buildings"] = [{"x": 1100.0, "y": 1000.0,
                           "building_type": "Home Station"}]
        s["boss"] = _boss(x=5000.0, y=1000.0)
        ap._act_regen(s, s["player"])
        assert captured["calls"] == ["gas_escape"]

    def test_no_cloud_with_hs_routes_to_drive_to_hs(
            self, monkeypatch):
        captured = self._setup_patches(monkeypatch)
        s = _state(player={"x": 0.0, "y": 0.0, "heading": 0.0,
                           "shields": 30, "max_shields": 150})
        s["buildings"] = [{"x": 1000.0, "y": 1000.0,
                           "building_type": "Home Station"}]
        # Boss alive -- but HS branch takes priority.
        s["boss"] = _boss(x=5000.0, y=1000.0)
        ap._act_regen(s, s["player"])
        assert captured["calls"] == ["drive_to_hs"]

    def test_no_cloud_no_hs_with_boss_routes_to_flee_boss(
            self, monkeypatch):
        captured = self._setup_patches(monkeypatch)
        s = _state(player={"x": 0.0, "y": 0.0, "heading": 0.0,
                           "shields": 30, "max_shields": 150})
        s["boss"] = _boss(x=2000.0, y=0.0)
        ap._act_regen(s, s["player"])
        assert captured["calls"] == ["flee_boss"]

    def test_no_cloud_no_hs_no_boss_idles(self, monkeypatch):
        captured = self._setup_patches(monkeypatch)
        s = _state(player={"x": 0.0, "y": 0.0, "heading": 0.0,
                           "shields": 30, "max_shields": 150})
        ap._act_regen(s, s["player"])
        assert captured["calls"] == ["idle"]

