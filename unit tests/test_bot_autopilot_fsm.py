"""FSM transition tests for ``bot_autopilot._do_auto``.

Pins the three guarantees that the formal state machine adds
over the prior cascade:

  1. **Hysteresis** -- a value drifting around an enter threshold
     does not flip the bot's state on every tick.  Each state has
     an asymmetric exit threshold (e.g. enter ENGAGE at 800 px,
     exit at 1000 px).
  2. **MIN_DWELL** -- once a non-ENGAGE state is entered, the
     FSM holds it for at least ``MIN_DWELL_S`` seconds before
     accepting a transition (with the sole exception below).
  3. **ENGAGE preemption** -- ENGAGE is a defensive interrupt and
     bypasses MIN_DWELL from any other state.

These tests inject a fake ``_get_now`` clock so dwell timing is
deterministic.
"""
from __future__ import annotations

import math

import pytest

import bot_autopilot as ap


# ── Fixtures ──────────────────────────────────────────────────────────────


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


def _state(player=None, aliens=(), asteroids=(),
           iron_pickups=(), blueprint_pickups=(),
           weapon_name="Basic Laser", melee_engaged=False,
           iron=0, world_w=6400, world_h=6400,
           buildings=(), inventory_items=None,
           station_inventory_items=None, module_slots=None):
    inv = {"iron": int(iron)} if inventory_items is None else dict(inventory_items)
    sinv = (dict(station_inventory_items)
            if station_inventory_items is not None else {})
    slots = list(module_slots) if module_slots is not None else []
    return {
        "player": player or {
            "x": 0.0, "y": 0.0, "heading": 0.0,
            "shields": 150, "max_shields": 150,
        },
        "weapon": {"name": weapon_name, "idx": 0},
        "aliens": list(aliens),
        "asteroids": list(asteroids),
        "iron_pickups": list(iron_pickups),
        "blueprint_pickups": list(blueprint_pickups),
        "buildings": list(buildings),
        "menu": {},
        "assist": {"melee_engaged": melee_engaged},
        "inventory": {"items": inv},
        "station_inventory": {"items": sinv},
        "module_slots": slots,
        "zone": {"world_w": world_w, "world_h": world_h,
                 "zone_id": "ZoneID.MAIN"},
    }


# ── ENGAGE hysteresis ─────────────────────────────────────────────────────


class TestEngageHysteresis:
    def test_alien_just_inside_band_enters_engage(self, _clock):
        s = _state(aliens=[{"x": 799, "y": 0, "hp": 50}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_alien_just_outside_enter_band_does_not_engage(self, _clock):
        s = _state(aliens=[{"x": 801, "y": 0, "hp": 50}],
                   asteroids=[{"x": 100, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE

    def test_engage_holds_through_exit_band(self, _clock):
        """In ENGAGE at 799 px -- if the alien drifts out to 950 px
        (past enter-band but inside exit-band), ENGAGE must hold."""
        s = _state(aliens=[{"x": 799, "y": 0, "hp": 50}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        # Simulate alien drifting just past enter band.
        s["aliens"][0]["x"] = 950
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "ENGAGE must hold inside the 800-1000 hysteresis band")

    def test_engage_releases_past_exit_band(self, _clock):
        """In ENGAGE -- alien at > 1000 px must release ENGAGE."""
        s = _state(aliens=[{"x": 799, "y": 0, "hp": 50}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        # Push past the exit band + advance time past dwell so the
        # follow-up state can settle.
        s["aliens"][0]["x"] = 1100
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE


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


class TestGatherHysteresis:
    def test_pickup_in_enter_band_triggers_gather(self, _clock):
        s = _state(iron_pickups=[
            {"x": 1400, "y": 0, "amount": 10, "item_type": "iron"}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_GATHER

    def test_pickup_outside_exit_band_releases_gather(self, _clock):
        s = _state(iron_pickups=[
            {"x": 1400, "y": 0, "amount": 10, "item_type": "iron"}],
            asteroids=[{"x": 100, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_GATHER
        # Pickup somehow drifted past the exit band.
        s["iron_pickups"][0]["x"] = 1800
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_GATHER


# ── MIN_DWELL gating ──────────────────────────────────────────────────────


class TestMinDwell:
    def test_mine_holds_within_dwell_for_non_defensive_change(self, _clock):
        """MIN_DWELL still holds for transitions that aren't
        defensive interrupts.  Drop the asteroids mid-dwell -- the
        FSM would normally fall through to SEARCH, but it has to
        wait for the dwell timer first."""
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        s["asteroids"] = []
        _clock[0] += ap.MIN_DWELL_S / 2.0
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE, (
            "MIN_DWELL must hold MINE for at least MIN_DWELL_S")

    def test_mine_flips_after_dwell(self, _clock):
        """Same setup as above, but advance past MIN_DWELL_S --
        now the transition is allowed."""
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        s["asteroids"] = []
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH

    def test_mine_drops_to_regen_within_dwell(self, _clock):
        """REGEN is a defensive interrupt: shields collapsing while
        MINE is still inside its dwell window must still trigger
        the swap on the next tick (just like ENGAGE)."""
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        s["player"]["shields"] = 30
        _clock[0] += ap.MIN_DWELL_S / 2.0
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_idle_at_base_bypasses_dwell_for_hunt(
            self, _clock, _fresh_bot_state):
        """2026-05-10 telemetry-anchored regression.

        IDLE_AT_BASE is the bot's "doing nothing while parked"
        state.  When the cascade picks a productive desired state
        (HUNT, MINE, GATHER, anything), the bot must transition
        IMMEDIATELY -- there's nothing to preserve about the idle
        state.  Pre-fix MIN_DWELL_S held the FSM for 1 s per
        transition, producing 87 suppressed idle_at_base->hunt
        events in a single 10-minute session.
        """
        # Park the bot in IDLE_AT_BASE with no live alien.
        s = _state(
            buildings=[_hs_building()],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._fsm["state"] = ap.S_IDLE_AT_BASE
        ap._fsm["entered_at"] = _clock[0]
        # An alien spawns within IDLE_HUNT_RANGE_PX -- cascade wants HUNT.
        s["aliens"] = [{"x": 5000.0, "y": 3200.0, "hp": 50}]
        # Re-eval well inside the dwell window.
        _clock[0] += ap.MIN_DWELL_S / 4.0
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT, (
            "IDLE_AT_BASE must bypass MIN_DWELL_S; pre-fix this "
            "took 1 s to fire, producing 87 suppressed events per "
            "10-minute session in the captured telemetry.")

    def test_idle_at_base_bypasses_dwell_for_mine(
            self, _clock, _fresh_bot_state):
        """Same fast-reaction guarantee for MINE: an asteroid
        appearing in chase range while the bot is idle must
        transition immediately.
        """
        s = _state(
            buildings=[_hs_building()],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._fsm["state"] = ap.S_IDLE_AT_BASE
        ap._fsm["entered_at"] = _clock[0]
        # Asteroid in chase range.
        s["asteroids"] = [{"x": 3500.0, "y": 3200.0, "hp": 100}]
        _clock[0] += ap.MIN_DWELL_S / 4.0
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE

    def test_idle_at_base_bypass_does_not_break_other_transitions(
            self, _clock, _fresh_bot_state):
        """Asymmetry guard: only IDLE_AT_BASE bypasses dwell.  A
        MINE state inside its dwell window with the cascade
        wanting GATHER must STILL be held (no broader bypass)."""
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        # Pickup appears -- cascade wants GATHER.
        s["iron_pickups"] = [
            {"x": 100, "y": 0, "amount": 10, "item_type": "iron"}]
        # Mid-dwell.
        _clock[0] += ap.MIN_DWELL_S / 4.0
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE, (
            "MIN_DWELL_S must STILL hold non-IDLE_AT_BASE states "
            "so the bypass doesn't bleed into the general case.")


# ── ENGAGE preemption ─────────────────────────────────────────────────────


class TestEngagePreemption:
    def test_engage_preempts_mine_within_dwell(self, _clock):
        """MIN_DWELL doesn't apply to ENGAGE -- defensive priority."""
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        # Alien jumps in mid-dwell.
        s["aliens"] = [{"x": 400, "y": 0, "hp": 50}]
        _clock[0] += ap.MIN_DWELL_S / 4.0   # well inside dwell
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "ENGAGE must preempt MIN_DWELL")

    def test_regen_holds_against_alien_threat_when_shields_recovering(
            self, _clock):
        """REGEN holds against a threat that appears mid-regen when
        shields are recovering (alien isn't actually hitting us —
        maybe out of fire range, maybe firing past us).  Combat
        assist still aims + fires every frame so the bot isn't
        defenseless — it just doesn't burn thrust chasing a fight
        at low health.

        Note: the entry-side mirror suppresses REGEN entry while
        a close threat is engaging us, so this test enters REGEN
        cleanly first (no threat) before introducing the alien.

        Counter-test (REGEN escape valve): see
        ``TestRegenEscapeValve.test_close_threat_and_falling_shields_breaks_regen``
        — when shields are NOT recovering with a mid-regen threat,
        the in-REGEN valve fires and ENGAGE preempts REGEN.
        """
        # Step 1: enter REGEN cleanly with no threat.
        s = _state(
            player={
                "x": 0, "y": 0, "heading": 0,
                "shields": 30, "max_shields": 150,
            },
            aliens=[{"x": 5000, "y": 0, "hp": 50}],  # far
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Step 2: alien now closes in, but shields tick up (alien
        # missing) — REGEN must hold for several ticks.
        s["aliens"] = [{"x": 400, "y": 0, "hp": 50}]
        for i in range(3):
            _clock[0] += 0.1
            s["player"]["shields"] = 30 + (i + 1)  # 31, 32, 33
            ap._do_auto(s, s["player"])
            assert ap._fsm["state"] == ap.S_REGEN

    def test_engage_drops_to_regen_when_shields_collapse_and_alien_leaves(
            self, _clock):
        """Active engagement; shields drop into REGEN territory.
        With the entry-side mirror, REGEN entry is suppressed
        while the threat is still close — the bot stays in ENGAGE
        and fights through.  Once the alien drifts out of
        ENGAGE_ENTER_PX, REGEN can fire normally.

        (Pre-2026-05-04: this test asserted REGEN fires immediately
        when shields collapse.  That created the REGEN<->ENGAGE
        thrash pathology; see ``TestRegenEntryWhileThreatenedSuppressed``.)
        """
        s = _state(
            aliens=[{"x": 400, "y": 0, "hp": 50}],
            player={
                "x": 0, "y": 0, "heading": 0,
                "shields": 150, "max_shields": 150,
            },
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        # Shields collapse, alien still close — REGEN entry
        # suppressed by the mirror, bot stays in ENGAGE.
        s["player"]["shields"] = 30
        _clock[0] += 0.05
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        # Alien now drifts out of engagement range — bot can
        # safely transition to REGEN.
        s["aliens"][0]["x"] = 5000
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "REGEN must fire once threat is past ENGAGE_ENTER_PX")


# ── Post-engage gather ────────────────────────────────────────────────────


class TestPostEngageGather:
    def test_alien_dies_pickup_appears_gather_starts(self, _clock):
        """ENGAGE -> alien removed, iron drop spawns where it died.
        Once dwell elapses the FSM rolls into GATHER."""
        s = _state(aliens=[{"x": 400, "y": 0, "hp": 50}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        # Alien dies, drops iron at the engagement point.
        s["aliens"] = []
        s["iron_pickups"] = [
            {"x": 400, "y": 0, "amount": 10, "item_type": "iron"}]
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_GATHER


# ── SEARCH spiral re-anchor ───────────────────────────────────────────────


class TestSearchEntryReseedsSpiral:
    def test_entering_search_resets_spiral_anchor(self, _clock):
        """Each fresh entry into SEARCH must clear the spiral
        anchor so the new sweep starts from the bot's current
        position, not stale prior coordinates."""
        s = _state(player={"x": 5000, "y": 5000, "heading": 0,
                            "shields": 150, "max_shields": 150})
        # Pre-poison the spiral with stale coords.
        ap._spiral_state["anchor"] = (-9999.0, -9999.0)
        ap._spiral_state["radius"] = 1234.0
        # No asteroids -> SEARCH on first tick.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH
        # Spiral anchor was cleared on entry, then set to current
        # position by _do_spiral_search.
        assert ap._spiral_state["anchor"] == (5000.0, 5000.0)


# ── Menu suppression preserves FSM state ──────────────────────────────────


class TestMenuSuppression:
    def test_menu_open_releases_keys_but_keeps_state(self, _clock):
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        # Open a menu -- execute_intent should release keys but
        # the FSM state must persist so we resume coherently
        # when the menu closes.
        s["menu"] = {"build": True}
        s["intent"] = {"type": "auto"}
        ap.execute_intent(s)
        assert ap._fsm["state"] == ap.S_MINE


# ── ENGAGE: melee-commit movement (driven by combat assist) ───────────────
#
# The dice roll lives in ``bot_combat_assist.tick`` -- it has to,
# because combat assist runs every game frame and would otherwise
# fight the autopilot's slower 10 Hz Tab presses.  The autopilot
# reads ``state.assist.melee_engaged`` and switches its movement
# stop radius to close in for the swing arc.


class TestMeleeCommitMovement:
    """When the assist signals it's committed to melee, the
    autopilot must drive forward to ``MELEE_STOP_RADIUS_PX``
    instead of holding the 380 px ranged stand-off."""

    def test_committed_melee_uses_short_stop_radius(
            self, _clock, monkeypatch):
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0):
            captured["stop_radius"] = stop_radius
        monkeypatch.setattr(ap, "_do_goto", _spy)
        s = _state(aliens=[{"x": 400, "y": 0, "hp": 50}],
                   melee_engaged=True)
        ap._do_auto(s, s["player"])
        assert captured.get("stop_radius") == ap.MELEE_STOP_RADIUS_PX

    def test_uncommitted_uses_ranged_stop_radius(
            self, _clock, monkeypatch):
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0):
            captured["stop_radius"] = stop_radius
        monkeypatch.setattr(ap, "_do_goto", _spy)
        s = _state(aliens=[{"x": 400, "y": 0, "hp": 50}],
                   melee_engaged=False)
        ap._do_auto(s, s["player"])
        assert captured.get("stop_radius") == 380.0

    def test_committed_melee_does_not_call_ensure_weapon(
            self, _clock, monkeypatch):
        """When committed, the autopilot must leave weapon choice
        to the in-process combat assist -- not press Tab from
        out-of-process at 10 Hz."""
        switches: list[str] = []
        monkeypatch.setattr(
            ap, "_ensure_weapon",
            lambda state, want: switches.append(want))
        s = _state(aliens=[{"x": 600, "y": 0, "hp": 50}],
                   melee_engaged=True)
        ap._do_auto(s, s["player"])
        assert switches == [], (
            "autopilot must not fight combat assist for weapon "
            "choice while melee-engaged")


# ── Mining-weapon dice roll on MINE entry ─────────────────────────────────


class TestMiningWeaponDiceRoll:
    """When the FSM enters the MINE state the bot rolls a 50/50
    dice to pick between Mining Beam (default ranged mining) and
    Energy Pickaxe (melee mining).  The choice is sticky for the
    whole mining session so the bot doesn't tab-flap mid-asteroid."""

    def test_pickaxe_chosen_when_roll_low(
            self, _clock, monkeypatch):
        """Force the dice low — bot picks Energy Pickaxe."""
        switches: list[str] = []
        monkeypatch.setattr(
            ap, "_ensure_weapon",
            lambda state, want: switches.append(want))
        monkeypatch.setattr(ap.random, "random", lambda: 0.0)
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert "Energy Pickaxe" in switches
        assert "Mining Beam" not in switches
        assert ap._state.mining_weapon_pick == "Energy Pickaxe"

    def test_mining_beam_chosen_when_roll_high(
            self, _clock, monkeypatch):
        """Force the dice above the threshold — bot keeps Mining Beam."""
        switches: list[str] = []
        monkeypatch.setattr(
            ap, "_ensure_weapon",
            lambda state, want: switches.append(want))
        monkeypatch.setattr(ap.random, "random", lambda: 0.99)
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert "Mining Beam" in switches
        assert "Energy Pickaxe" not in switches
        assert ap._state.mining_weapon_pick == "Mining Beam"

    def test_choice_sticky_across_mining_ticks(
            self, _clock, monkeypatch):
        """Once the dice has rolled, repeated MINE ticks must keep
        the same weapon — the dice is per-ENTRY, not per-tick."""
        rolls = iter([0.0, 0.99, 0.99, 0.99, 0.99])
        monkeypatch.setattr(ap.random, "random", lambda: next(rolls))
        switches: list[str] = []
        monkeypatch.setattr(
            ap, "_ensure_weapon",
            lambda state, want: switches.append(want))
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        for _ in range(5):
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        # All 5 ticks should still reference the pickaxe (the entry
        # roll was 0.0; subsequent rolls don't matter while we stay
        # in MINE).
        assert all(w == "Energy Pickaxe" for w in switches), switches
        assert ap._state.mining_weapon_pick == "Energy Pickaxe"

    def test_dice_rerolled_on_fresh_mine_entry(
            self, _clock, monkeypatch):
        """Leaving + re-entering MINE re-rolls the dice — the
        sticky choice resets per session."""
        # Roll #1: pickaxe.  Roll #2: mining beam.
        rolls = iter([0.0, 0.99])
        monkeypatch.setattr(ap.random, "random", lambda: next(rolls))
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        assert ap._state.mining_weapon_pick == "Energy Pickaxe"
        # Drop the asteroid → MINE → SEARCH → re-add asteroid → MINE.
        s["asteroids"] = []
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH
        s["asteroids"] = [{"x": 200, "y": 0, "hp": 100}]
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        # Second entry rolled 0.99 → Mining Beam.
        assert ap._state.mining_weapon_pick == "Mining Beam"

    def test_pickaxe_uses_hold_distance_not_goto(
            self, _clock, monkeypatch):
        """When the dice picks pickaxe, the bot must hold optimal
        swing distance via _do_hold_distance — _do_goto would close
        until contact and ram the asteroid."""
        captured: dict = {}
        def _spy_hold(state, p, tx, ty, hold_radius, dead_band=20.0):
            captured["hold_radius"] = hold_radius
        def _spy_goto(*a, **kw):
            captured["goto_called"] = True
        monkeypatch.setattr(ap, "_do_hold_distance", _spy_hold)
        monkeypatch.setattr(ap, "_do_goto", _spy_goto)
        monkeypatch.setattr(ap.random, "random", lambda: 0.0)
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert (
            captured.get("hold_radius")
            == ap.PICKAXE_HOLD_DISTANCE_PX)
        assert "goto_called" not in captured, (
            "pickaxe path must not use _do_goto -- that closes to "
            "stop_radius and rams the asteroid")

    def test_mining_beam_uses_ranged_stop_radius(
            self, _clock, monkeypatch):
        """Mining Beam keeps the existing 200 px stand-off via
        _do_goto (not _do_hold_distance — beam is ranged)."""
        captured: dict = {}
        def _spy_goto(state, p, tx, ty, stop_radius=80.0):
            captured["stop_radius"] = stop_radius
        def _spy_hold(*a, **kw):
            captured["hold_called"] = True
        monkeypatch.setattr(ap, "_do_goto", _spy_goto)
        monkeypatch.setattr(ap, "_do_hold_distance", _spy_hold)
        monkeypatch.setattr(ap.random, "random", lambda: 0.99)
        s = _state(asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert captured.get("stop_radius") == 200.0
        assert "hold_called" not in captured


class TestHoldDistanceBehaviour:
    """Pin the thrust-forward / coast / reverse-thrust branches in
    _do_hold_distance so the pickaxe path doesn't ram asteroids."""

    @pytest.fixture
    def _key_log(self, monkeypatch):
        log: dict = {}
        def _hold(key, down):
            log[key] = bool(down)
        monkeypatch.setattr(
            ap.KeyState, "hold", staticmethod(_hold))
        return log

    def _player_at(self, x, y, heading=0.0):
        return {
            "x": x, "y": y, "heading": heading,
            "shields": 150, "max_shields": 150,
        }

    def test_far_thrusts_forward(self, _key_log):
        # Asteroid at (0, 500), bot at (0, 0).  Distance 500 >>
        # hold + dead_band → forward thrust (and aligned).
        p = self._player_at(0, 0, heading=0.0)
        ap._do_hold_distance(_state(), p, 0.0, 500.0,
                             hold_radius=100.0)
        assert _key_log.get("w") is True
        assert _key_log.get("s") is False

    def test_too_close_reverses(self, _key_log):
        # Asteroid at (0, 50), bot at (0, 0).  Distance 50 <
        # hold (100) - dead_band (20) = 80 → reverse thrust.
        p = self._player_at(0, 0, heading=0.0)
        ap._do_hold_distance(_state(), p, 0.0, 50.0,
                             hold_radius=100.0)
        assert _key_log.get("s") is True
        assert _key_log.get("w") is False

    def test_inside_dead_band_coasts(self, _key_log):
        # Asteroid at (0, 100), bot at (0, 0).  Distance 100 sits
        # exactly on hold → no thrust either direction.
        p = self._player_at(0, 0, heading=0.0)
        ap._do_hold_distance(_state(), p, 0.0, 100.0,
                             hold_radius=100.0)
        assert _key_log.get("w") is False
        assert _key_log.get("s") is False

    def test_always_rotates_to_face_target(self, _key_log):
        # Asteroid to the right (90°) of a north-facing ship → must
        # rotate clockwise (heading_delta sign convention).
        p = self._player_at(0, 0, heading=0.0)
        ap._do_hold_distance(_state(), p, 500.0, 0.0,
                             hold_radius=100.0)
        # One of A/D must be held to rotate toward the target.
        assert _key_log.get("a") is True or _key_log.get("d") is True


# ── Starter-base BUILD trigger ────────────────────────────────────────────


class TestStarterBaseBuildGate:
    """Pin the conditions for entering the one-shot S_BUILD state:
    ≥ BUILD_IRON_THRESHOLD iron AND no detectable within
    BUILD_CLEAR_RADIUS_PX (400 px after the 2026-05-10 reduction;
    asteroids, aliens, pickups, buildings) AND not already
    attempted.  When iron is met but the area isn't clear, the FSM
    enters S_BUILD_SEEK instead."""

    def test_no_build_below_iron_threshold(self, _clock):
        s = _state(iron=ap.BUILD_IRON_THRESHOLD - 1)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD
        assert ap._fsm["state"] != ap.S_BUILD_SEEK

    def test_seek_when_iron_met_but_asteroid_in_radius(self, _clock):
        """Asteroid inside the 400 px clear radius — bot enters
        S_BUILD_SEEK to walk away from it, not S_BUILD."""
        s = _state(
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[{"x": 200, "y": 0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_SEEK

    def test_clear_check_counts_pickups_and_buildings(self, _clock):
        """``_build_area_clear`` rejects pickups and buildings just
        like asteroids + aliens.  (GATHER preempts BUILD_SEEK in the
        FSM when a pickup is in reach, so this is checked at the
        helper level rather than via _do_auto dispatch.)"""
        # Pickup at 300 px (inside the 400 px clear radius) → not clear.
        s = _state(
            iron_pickups=[
                {"x": 300, "y": 0, "amount": 10, "item_type": "iron"}],
        )
        assert not ap._build_area_clear(
            s, s["player"]["x"], s["player"]["y"])
        # Building at 350 px (inside the 400 px clear radius) → not clear.
        s = _state()
        s["buildings"] = [{"x": 350, "y": 0}]
        assert not ap._build_area_clear(
            s, s["player"]["x"], s["player"]["y"])
        # Empty state → clear.
        assert ap._build_area_clear(_state(), 0.0, 0.0)

    def test_clear_radius_lowered_from_800_to_400(self, _clock):
        """Pin the 2026-05-10 telemetry-anchored reduction.

        A pickup at x=500 used to fail the clearance check (inside
        the old 800 px radius); post-fix it's outside the 400 px
        radius and the build area reads as clear.  Captures the
        intent: the bot can now find buildable spots in a typical
        asteroid field instead of wandering BUILD_SEEK forever.
        """
        assert ap.BUILD_CLEAR_RADIUS_PX == 400.0
        # Detectable at exactly the old boundary -- outside new radius.
        s = _state()
        s["asteroids"] = [{"x": 500, "y": 0, "hp": 100}]
        assert ap._build_area_clear(
            s, s["player"]["x"], s["player"]["y"]), (
            "asteroid at 500 px must be outside the new 400 px "
            "clear radius (it was inside the pre-fix 800 px radius)")
        # Detectable inside new radius still blocks.
        s["asteroids"] = [{"x": 350, "y": 0, "hp": 100}]
        assert not ap._build_area_clear(
            s, s["player"]["x"], s["player"]["y"])

    def test_no_build_when_alien_too_close(self, _clock):
        s = _state(
            iron=ap.BUILD_IRON_THRESHOLD,
            aliens=[{"x": 500, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        # Engage takes priority anyway; just verify not BUILD.
        assert ap._fsm["state"] != ap.S_BUILD

    def test_build_triggers_when_conditions_met(
            self, _clock, monkeypatch):
        # Stub out the HTTP POST so the test doesn't need a server.
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda timeout_s=5.0: (
                post_calls.append(True) or {"placed": [], "failed": []}))
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD
        assert len(post_calls) == 1, "POST must fire on BUILD entry"
        assert ap._state.build_done is True

    def test_build_is_one_shot(self, _clock, monkeypatch):
        """After ``_build_done`` flips, the FSM must not re-enter
        S_BUILD even if conditions are still met."""
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda timeout_s=5.0: (
                post_calls.append(True) or {"placed": [], "failed": []}))
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._do_auto(s, s["player"])
        assert ap._state.build_done is True
        # Walk past dwell + tick again with the same conditions.
        for _ in range(5):
            _clock[0] += ap.MIN_DWELL_S + 0.1
            ap._do_auto(s, s["player"])
        assert len(post_calls) == 1, (
            "BUILD must fire exactly once; subsequent ticks must "
            "fall through to MINE / SEARCH")
        assert ap._fsm["state"] != ap.S_BUILD

    def test_existing_home_station_short_circuits_build_branch(
            self, _clock):
        """User-reported regression: autopilot starting alongside a
        pre-existing Home Station with >= 1000 iron oscillated
        between BUILD_SEEK (walk away from station) and DEPOSIT
        (walk back).  The fix flips ``build_done = True`` on
        first sight of an existing HS, so the BUILD/BUILD_SEEK
        branch never fires when a station already exists."""
        ap._state.build_done = False  # autopilot just started
        s = _state(
            iron=ap.BUILD_IRON_THRESHOLD,
            buildings=[{"x": 3200.0, "y": 3200.0, "hp": 100,
                        "type": "StationModule",
                        "building_type": "Home Station"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._state.build_done is True, (
            "build_done should flip True on first sight of an "
            "existing Home Station")
        assert ap._fsm["state"] not in (ap.S_BUILD, ap.S_BUILD_SEEK), (
            "BUILD/BUILD_SEEK must not fire when a Home Station "
            "already exists")

    def test_no_home_station_still_triggers_build_normally(
            self, _clock):
        """Sanity check: the short-circuit only fires when an HS
        exists.  Without one, the normal iron-gated build path
        still works."""
        ap._state.build_done = False
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._do_auto(s, s["player"])
        assert ap._state.build_done is True or \
               ap._fsm["state"] in (ap.S_BUILD, ap.S_BUILD_SEEK)

    def test_act_build_does_not_repost_during_dwell(
            self, _clock, monkeypatch):
        """While the FSM is holding S_BUILD through MIN_DWELL_S,
        the dispatch may call _act_build multiple times — but only
        the FIRST call should POST.  Without the guard, the
        synchronous HTTP round-trip plus the 0.6 s dwell at 10 Hz
        produced 6 build attempts in a play-test, each one re-
        spending iron on duplicate buildings."""
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda timeout_s=5.0: (
                post_calls.append(True) or {"placed": [], "failed": []}))
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        # Manually call _act_build five times in a row (simulating
        # repeated dispatch within the dwell window).
        for _ in range(5):
            ap._act_build(s, s["player"])
        assert len(post_calls) == 1, (
            "_act_build must guard against repeat POSTs via "
            "_state.build_done check")

    def test_build_releases_movement_keys(
            self, _clock, monkeypatch):
        """The act_build branch must coast in place — movement keys
        released — so the ship doesn't drift while seven buildings
        are placed in the HTTP-handler thread."""
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda timeout_s=5.0: {"placed": [], "failed": []})
        released: list = []
        monkeypatch.setattr(
            ap.KeyState, "release_all",
            staticmethod(lambda: released.append(True)))
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._do_auto(s, s["player"])
        assert released, "release_all must be called in BUILD state"

    def test_engage_preempts_build(self, _clock, monkeypatch):
        """An alien that appears alongside the build conditions must
        steal the FSM — combat priority over construction."""
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda timeout_s=5.0: {"placed": [], "failed": []})
        s = _state(
            iron=ap.BUILD_IRON_THRESHOLD,
            aliens=[{"x": 400, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE


# ── Edge-stuck watchdog ───────────────────────────────────────────────────


class TestStuckEscape:
    """The bot must escape when pinned at a world edge.  A short
    rolling window of position samples is checked; if displacement
    over the window is below STUCK_DETECT_DIST_PX, an escape burst
    toward the world centre is triggered for STUCK_ESCAPE_DURATION_S."""

    def _drive_ticks_at(self, _clock, x, y, n,
                         force_state=None):
        """Run n ticks with the player frozen at (x, y).  When
        ``force_state`` is provided, force that FSM state so
        stuck-detect runs (S_SEARCH is exempt from stuck-detect
        because its brake-coast spiral motion looks identical to
        being pinned).  Default seeds an asteroid so the FSM lands
        in S_MINE — a state that DOES participate in stuck-detect."""
        for _ in range(n):
            # Seed an asteroid so the FSM picks S_MINE instead of
            # S_SEARCH (which is exempt from stuck-detect).
            s = _state(
                player={
                    "x": x, "y": y, "heading": 0.0,
                    "shields": 150, "max_shields": 150,
                },
                asteroids=[{"x": x + 200.0, "y": y, "hp": 50}],
            )
            if force_state is not None:
                ap._fsm["state"] = force_state
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1   # 10 Hz

    def test_no_escape_when_ship_is_rotating_in_place(self, _clock):
        """Rotation alone counts as activity — the bot rotating to
        face a new spiral target during SEARCH must NOT trigger
        the watchdog.  Without this gate the SEARCH spiral fired
        stuck-detect every 1.5 s during normal operation: bot
        reached spiral target, braked, rotated to next target,
        position barely moved during rotation, position-only
        detection couldn't tell rotation from being pinned."""
        # Pin position but rotate the heading 10° per tick =
        # 100°/s — well above STUCK_DETECT_ROTATION_DEG / window.
        for i in range(20):
            s = _state(player={
                "x": 100.0, "y": 100.0,
                "heading": (i * 10.0) % 360.0,
                "shields": 150, "max_shields": 150,
            })
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._stuck_state["escape_until"] == 0.0, (
            "rotation alone should not trigger stuck-detect")

    def test_no_escape_when_ship_is_moving(self, _clock):
        # Drive 20 ticks, advancing 50 px each tick — ship clearly
        # making progress; stuck detection must NOT fire.
        for i in range(20):
            s = _state(player={
                "x": 100.0 + i * 50.0, "y": 100.0, "heading": 0.0,
                "shields": 150, "max_shields": 150,
            })
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._stuck_state["escape_until"] == 0.0

    def test_escape_fires_after_window_with_no_movement(
            self, _clock):
        """Pin the ship at (100, 100) for the full detect window —
        next tick must flag stuck and start the escape override."""
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        # Inside the escape window now.
        assert ap._stuck_state["escape_until"] > 0.0

    def test_escape_targets_along_repulsion_vector(
            self, _clock, monkeypatch):
        """The escape now heads along the local repulsion vector
        instead of toward world centre.  Pinned at the south
        edge: repulsion points pure-north (+y), so the escape
        target sits ``BUILD_SEEK_TARGET_DIST_PX`` north of the
        ship — clamped to inside the world."""
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        # Pin near the bottom edge of a 6400×6400 world.  Force
        # FSM into S_MINE (S_SEARCH is exempt from stuck-detect)
        # by seeding an in-range asteroid the bot is "chasing".
        for _ in range(20):
            s = _state(
                player={"x": 3200.0, "y": 50.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                asteroids=[{"x": 3200.0, "y": 0.0, "hp": 50}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        # Repulsion at y=50 is pure +y; target is 50 + 1000 = 1050
        # (BUILD_SEEK_TARGET_DIST_PX north of the ship), clamped
        # to inside [200, 6200].  X is unchanged because the ship
        # is mid-axis with no X repulsion.
        assert captured.get("tx") == 3200.0
        expected_ty = 50.0 + ap.BUILD_SEEK_TARGET_DIST_PX
        assert captured.get("ty") == expected_ty

    def test_escape_targets_away_from_building_pin(
            self, _clock, monkeypatch):
        """The user's reported failure mode: bot pinned outside
        the player station gets driven INTO the cluster by the
        old "head to world centre" escape.  New escape uses the
        building repulsion vector so it heads AWAY from the
        building, not through it."""
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        # Pin the ship 40 px south of a building near world centre.
        # World-edge repulsion is zero (mid-axis); building
        # repulsion at distance 40 / range 80 = 0.5 in direction
        # (0, -1).  Escape target should be SOUTH of the ship,
        # not toward world centre (which is north of the ship).
        # Seed an asteroid so the FSM lands in S_MINE — S_SEARCH
        # is exempt from stuck-detect.
        for _ in range(20):
            s = _state(
                player={"x": 3200.0, "y": 3160.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                buildings=[{"x": 3200.0, "y": 3200.0,
                            "hp": 100, "type": "StationModule",
                            "building_type": "Home Station"}],
                asteroids=[{"x": 3200.0, "y": 3100.0, "hp": 50}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        # Escape target must be SOUTH (lower y) of the ship's
        # current position, NOT north (which is where world
        # centre sits and where the building is).
        assert captured.get("ty") < 3160.0, (
            f"escape ty {captured.get('ty')} should be south of "
            f"ship at 3160 (away from building at 3200), not north")

    def test_escape_holds_until_ship_clears_edge_margin(
            self, _clock):
        """Even after STUCK_ESCAPE_MIN_DURATION_S elapses, the
        escape override must persist while the ship is still
        within STUCK_ESCAPE_CLEAR_MARGIN_PX of any edge — long
        rotations from a corner can take longer than the minimum."""
        # Pin near the top edge of a 6400×6400 world.
        self._drive_ticks_at(_clock, 3200.0, 6300.0, n=20)
        assert ap._stuck_state["escape_until"] > 0.0
        # Jump past the minimum escape duration but stay near edge.
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.5
        s = _state(player={"x": 3200.0, "y": 6300.0, "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_auto(s, s["player"])
        # Override must NOT clear yet — ship still pinned at top.
        assert ap._stuck_state["escape_until"] > 0.0

    def test_escape_holds_until_ship_clears_buildings(
            self, _clock):
        """Even with min duration elapsed AND world edges cleared,
        the escape must persist while the ship is still inside
        any building's repulsion zone — otherwise the escape from
        a station-corner pin would expire while still inside the
        field that re-pins."""
        # Trigger stuck somewhere harmless so escape arms.
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        assert ap._stuck_state["escape_until"] > 0.0
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.5
        # Ship is mid-world (clear of edges) but right next to a
        # building (inside its 80 px repulsion zone).
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 3240.0, "y": 3200.0, "hp": 100,
                        "type": "StationModule",
                        "building_type": "Service Module"}],
        )
        ap._do_auto(s, s["player"])
        # Escape must NOT clear yet — building still in range.
        assert ap._stuck_state["escape_until"] > 0.0

    def test_escape_clears_when_ship_well_inside_world(
            self, _clock):
        """Once min duration has elapsed AND the ship is clear of
        all edges by the safety margin AND clear of all buildings,
        the override drops and the FSM resumes normal flow."""
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        assert ap._stuck_state["escape_until"] > 0.0
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        # Ship has now moved well clear of every edge.
        s = _state(player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_auto(s, s["player"])
        assert ap._stuck_state["escape_until"] == 0.0

    def test_escape_exit_anchors_spiral_at_clear_space_position(
            self, _clock):
        """The spiral re-anchor used to fire on stuck-detect with
        world centre as the anchor — but the home station is
        typically built near world centre, so the next SEARCH
        cycle would target right back through the building
        cluster (observed: 13 consecutive stuck events in 72 s,
        all in S_SEARCH, oscillating between two positions
        60-130 px from the HS).  Now the re-anchor fires when
        the escape EXITS, using the bot's clear-space landing
        position so the new spiral starts away from whatever
        caused the stuck."""
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        assert ap._stuck_state["escape_until"] > 0.0
        # During the escape, anchor is whatever it was before
        # (or what _do_spiral_search set on its first call).
        # Now jump past the escape window, with the ship clear
        # of edges + buildings.
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        s = _state(player={"x": 3500.0, "y": 3500.0, "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_auto(s, s["player"])
        # Escape exit branch should have re-anchored the spiral
        # at the ship's CURRENT (3500, 3500) position.  Radius
        # and angle then get advanced one tick when the FSM
        # falls through to _do_spiral_search post-escape, so
        # they end up just past the seeded 100 / 0.0.
        assert ap._spiral_state["anchor"] == (3500.0, 3500.0)
        assert 100.0 < ap._spiral_state["radius"] < 110.0
        assert ap._spiral_state["angle"] == ap.SPIRAL_ANGLE_ADVANCE_RAD

    def test_stuck_log_is_throttled(self, _clock, capsys):
        """A long stuck recovery used to spam the console with
        one line per detect cycle.  STUCK_LOG_THROTTLE_S now caps
        log rate."""
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        # First trigger logs.
        out1 = capsys.readouterr().out
        assert "STUCK at edge" in out1
        # Stay pinned, force another stuck cycle quickly.
        _clock[0] += 0.5
        ap._stuck_state["escape_until"] = 0.0   # simulate expiry
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        out2 = capsys.readouterr().out
        # Within throttle window: must NOT log again.
        assert "STUCK at edge" not in out2


class TestSpiralWorldClamp:
    """Spiral search targets must stay inside the world rect (with
    a margin) so the bot doesn't keep aiming off-map and pinning
    itself against the edge."""

    def test_spiral_target_clamped_within_world(
            self, _clock, monkeypatch):
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        # Force the spiral anchor near the SW corner, with a huge
        # radius and an angle that points off-map (toward -x, -y).
        ap._spiral_state["anchor"] = (50.0, 50.0)
        ap._spiral_state["radius"] = 5000.0
        import math as _m
        ap._spiral_state["angle"] = _m.radians(225.0)   # SW
        s = _state(
            player={"x": 50.0, "y": 50.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=6400, world_h=6400,
        )
        ap._do_spiral_search(s, s["player"])
        # Clamp = 200 px margin.
        assert ap.STUCK_WORLD_MARGIN_PX <= captured["tx"]
        assert ap.STUCK_WORLD_MARGIN_PX <= captured["ty"]
        assert captured["tx"] <= 6400 - ap.STUCK_WORLD_MARGIN_PX
        assert captured["ty"] <= 6400 - ap.STUCK_WORLD_MARGIN_PX


# ── BUILD_SEEK + spiral-no-fire ───────────────────────────────────────────


class TestBuildSeek:
    """Active hunt for a clear pocket: when the bot has the iron
    threshold but the area isn't clear, it should walk AWAY from
    the centroid of nearby clutter (instead of waiting passively
    for SEARCH to land somewhere quiet)."""

    @pytest.fixture
    def _capture_goto(self, monkeypatch):
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0):
            captured["tx"], captured["ty"] = tx, ty
            captured["stop_radius"] = stop_radius
        monkeypatch.setattr(ap, "_do_goto", _spy)
        return captured

    def test_seek_walks_away_from_single_asteroid(
            self, _clock, _capture_goto, monkeypatch):
        """One asteroid 300 px to the EAST → bot heads WEST."""
        # Stub KeyState so the fire-suppress assertion isn't noisy.
        keys: dict = {}
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda k, v: keys.__setitem__(k, bool(v))))
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[{"x": 3300.0, "y": 3000.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        # Target should be west of player (tx < 3000, |dy| small).
        assert _capture_goto.get("tx") is not None
        assert _capture_goto["tx"] < 3000.0, (
            f"expected target west of player, got tx={_capture_goto['tx']}")

    def test_seek_walks_toward_open_space_with_clutter_north(
            self, _clock, _capture_goto, monkeypatch):
        """Asteroids to the NORTH → bot heads SOUTH.  Asteroids must
        be inside BUILD_CLEAR_RADIUS_PX (400 px after 2026-05-10
        reduction) to force the SEEK branch instead of the BUILD
        branch."""
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda k, v: None))
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[
                {"x": 3050, "y": 3300, "hp": 100},
                {"x": 2950, "y": 3300, "hp": 100},
            ],
        )
        ap._do_auto(s, s["player"])
        assert _capture_goto["ty"] < 3000.0, (
            "should head south away from clutter to the north")

    def test_seek_target_clamped_to_world(
            self, _clock, _capture_goto, monkeypatch):
        """Even when the away-from-clutter direction would take
        the bot off-map, the target is clamped to world bounds.

        Asteroid placed inside BUILD_CLEAR_RADIUS_PX (400 px) of the
        bot so the FSM enters SEEK; the away-from-asteroid heading
        then pushes east toward the world edge, exercising the clamp.
        """
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda k, v: None))
        # Player near east edge with asteroid 200 px west.  Direction
        # away from the asteroid points east, into the edge.
        s = _state(
            player={"x": 6300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[{"x": 6100, "y": 3000, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        # Target stays inside the world rect with margin.
        assert (
            _capture_goto["tx"]
            <= 6400 - ap.STUCK_WORLD_MARGIN_PX)
        assert _capture_goto["tx"] >= ap.STUCK_WORLD_MARGIN_PX

    def test_seek_does_not_fire_weapon(
            self, _clock, _capture_goto, monkeypatch):
        """Seeking is positioning-only — must not press space."""
        keys: dict = {}
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda k, v: keys.__setitem__(k, bool(v))))
        s = _state(
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[{"x": 200, "y": 0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        # space key must be False (released) during seek.
        assert keys.get("space") is False

    def test_seek_transitions_to_build_when_pocket_clear(
            self, _clock, monkeypatch):
        """Once the bot reaches a position with no detectables in
        the 800 px radius, the FSM flips from S_BUILD_SEEK to
        S_BUILD on the next tick."""
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda timeout_s=5.0: {"placed": [], "failed": []})
        # First tick: clutter nearby → SEEK.
        s_dirty = _state(
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[{"x": 200, "y": 0, "hp": 100}],
        )
        ap._do_auto(s_dirty, s_dirty["player"])
        assert ap._fsm["state"] == ap.S_BUILD_SEEK
        # Second tick (after dwell): clutter gone → BUILD.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s_clean = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._do_auto(s_clean, s_clean["player"])
        assert ap._fsm["state"] == ap.S_BUILD


class TestSpiralFireGate:
    """The spiral search used to fire the active mining weapon
    every tick as a "drift past extraction lag" safety net.  After
    a stuck-escape that put the bot at the world centre with no
    real targets, that meant the bot stood there mining empty
    space.  Fire is now gated on actually having an asteroid in
    range of the picked weapon."""

    @pytest.fixture
    def _key_log(self, monkeypatch):
        log: dict = {}
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda k, v: log.__setitem__(k, bool(v))))
        return log

    def test_no_fire_with_no_asteroids(self, _key_log):
        s = _state()   # no asteroids
        ap._do_spiral_search(s, s["player"])
        assert _key_log.get("space") is False

    def test_no_fire_with_distant_asteroid(self, _key_log):
        # Asteroid well outside MINING_RANGE_PX (400 px).
        s = _state(asteroids=[{"x": 2000, "y": 0, "hp": 100}])
        ap._do_spiral_search(s, s["player"])
        assert _key_log.get("space") is False

    def test_fires_when_asteroid_within_mining_beam_range(
            self, _key_log):
        # Within MINING_RANGE_PX (400) for the default Mining Beam.
        ap._state.mining_weapon_pick = "Mining Beam"
        s = _state(asteroids=[{"x": 300, "y": 0, "hp": 100}])
        ap._do_spiral_search(s, s["player"])
        assert _key_log.get("space") is True


class TestStuckEscapeNoLockout:
    """The 30 s centre-lockout was removed once the boundary +
    building potential field landed: the field deflects future
    attempts at the same edge-adjacent target, so suppressing the
    FSM for half a minute after every escape was overkill.  These
    tests pin the simpler post-escape behaviour: once the ship
    clears the edge, the normal FSM priorities resume immediately."""

    def _trigger_stuck(self, _clock):
        """Force a stuck cycle by pinning the player at one
        position for the full detect window."""
        for _ in range(20):
            s = _state(player={
                "x": 100.0, "y": 100.0, "heading": 0.0,
                "shields": 150, "max_shields": 150,
            })
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1

    def test_no_centre_lockout_field_in_stuck_state(self):
        """The lockout field was removed entirely — the stuck
        dict only carries history + escape timing now."""
        assert "centre_lockout_until" not in ap._stuck_state
        assert "centre_lockout_until" not in ap.BotState().stuck

    def test_mine_resumes_immediately_after_escape_clears(
            self, _clock):
        """After the stuck-escape exits (ship clear of all edges),
        an asteroid in MINE range triggers MINE without waiting
        for any lockout window — the field handles the
        re-pinning case proactively."""
        self._trigger_stuck(_clock)
        # Skip past the escape duration AND move the ship clear
        # of all edges so _ship_clear_of_edges returns True and
        # the override exits.
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3300.0, "y": 3200.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE, (
            "with no lockout, MINE should fire as soon as the "
            "escape window closes and an asteroid is reachable")

    def test_engage_still_preempts_after_stuck(self, _clock):
        """Combat priority unchanged — an alien within ENGAGE
        range steals the FSM whether or not we just escaped a
        stuck condition."""
        self._trigger_stuck(_clock)
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3500.0, "y": 3200.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_regen_still_preempts_after_stuck(self, _clock):
        """Defensive priority unchanged — low shields trigger
        REGEN even right after a stuck escape."""
        self._trigger_stuck(_clock)
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        s = _state(player={
            "x": 3200.0, "y": 3200.0, "heading": 0.0,
            "shields": 30, "max_shields": 150,   # 20 % < 40 %
        })
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN


# ── DEPOSIT (ongoing return-to-base) ──────────────────────────────────────


def _hs_building(x=3200.0, y=3200.0):
    """Build a Home Station entry for /state.buildings."""
    return {"x": x, "y": y, "hp": 100, "type": "StationModule",
            "building_type": "Home Station"}


class TestDepositTrigger:
    """S_DEPOSIT fires when the bot has a Home Station built AND
    the ship inventory has substantial items (≥ DEPOSIT_IRON_THRESHOLD
    iron OR any blueprint).  Cooldown prevents re-trigger."""

    def test_no_deposit_without_home_station(self, _clock):
        s = _state(iron=ap.DEPOSIT_IRON_THRESHOLD)
        # No buildings → no Home Station.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_DEPOSIT

    def test_no_deposit_below_iron_threshold(self, _clock):
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD - 1,
            buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_DEPOSIT

    def test_deposit_triggers_at_iron_threshold(self, _clock):
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT

    def test_blueprint_alone_does_not_trigger_deposit(self, _clock):
        """A blueprint without enough iron must NOT trigger a return
        trip — wasteful navigation cost.  Blueprints accumulate
        with iron until the iron threshold is met, then everything
        ships in one round trip.  (Updated from the prior
        OR-blueprint behaviour after operator feedback that the
        bot was making short, low-yield deposit trips.)"""
        s = _state(
            iron=10,
            inventory_items={"iron": 10, "bp_engine_booster": 1},
            buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_DEPOSIT

    def test_deposit_triggers_when_iron_meets_threshold_with_blueprints(
            self, _clock):
        """Once iron crosses the threshold, the deposit run fires
        regardless of what else is in the ship — and the deposit
        ships every item type, so blueprints ride along on the
        same trip."""
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            inventory_items={
                "iron": ap.DEPOSIT_IRON_THRESHOLD,
                "bp_engine_booster": 1,
            },
            buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT

    def test_deposit_cooldown_prevents_immediate_retrigger(self, _clock):
        """After a deposit, the bot must not re-enter DEPOSIT for
        DEPOSIT_COOLDOWN_S (otherwise it would loop between mine
        and deposit on every iron pickup)."""
        ap._state.last_deposit_at = _clock[0]
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_DEPOSIT

    def test_engage_preempts_deposit(self, _clock):
        """Combat priority: alien within engage range steals the
        FSM from DEPOSIT just like every other non-defensive state."""
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building()],
            aliens=[{"x": 400, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_nearby_asteroid_suppresses_deposit_below_full_threshold(
            self, _clock):
        """Mine-before-deposit override (2026-05-09 user report):
        when an asteroid is within MAX_ASTEROID_CHASE_PX AND ship
        iron is below DEPOSIT_IRON_FULL_THRESHOLD, the bot mines
        the visible cluster instead of zigzagging back to the
        station after every loot drop.  Pins the user-reported
        scenario where the ship returned to the station after
        destroying an enemy even with asteroids on screen."""
        ap._state.asteroid_blacklist.clear()
        # Iron just at the deposit threshold — would normally fire
        # DEPOSIT.  But there's an asteroid in chase range, so MINE
        # should preempt.
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building()],
            asteroids=[{"x": 800.0, "y": 0.0, "hp": 100,
                        "type": "Asteroid"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE, (
            "An asteroid in chase range with ship iron below the "
            "FULL threshold must preempt DEPOSIT — the bot should "
            "finish mining the visible cluster before round-tripping.")

    def test_full_cargo_overrides_mine_priority(self, _clock):
        """The mine-before-deposit override has an upper bound: at
        DEPOSIT_IRON_FULL_THRESHOLD or above the bot ALWAYS deposits,
        even with an asteroid in chase range.  Otherwise a long
        mining run would let the cargo grow indefinitely."""
        ap._state.asteroid_blacklist.clear()
        s = _state(
            iron=ap.DEPOSIT_IRON_FULL_THRESHOLD,
            buildings=[_hs_building()],
            asteroids=[{"x": 800.0, "y": 0.0, "hp": 100,
                        "type": "Asteroid"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT, (
            "Ship iron at the FULL threshold must trigger DEPOSIT "
            "even when an asteroid is in chase range — the cargo-"
            "near-full safety valve.")

    def test_far_from_home_below_full_does_not_deposit(self, _clock):
        """Distance gate (2026-05-09 follow-up): when ship_iron is
        between THRESHOLD and FULL and the bot is more than
        DEPOSIT_HS_MAX_DIST_PX from home, DEPOSIT must NOT fire —
        the long round trip would almost certainly be interrupted
        by combat (ENGAGE preempt) before reaching the station,
        leaving the bot stranded mid-trip with unchanged cargo
        state.  Caught from telemetry: bot at hs_dist=6340 px
        triggered DEPOSIT with iron=320, traveled 600 px, hit an
        alien, aborted; spent the next 2 minutes mining its way
        back instead of one efficient close-range deposit."""
        ap._state.asteroid_blacklist.clear()
        # Player at the world edge, HS at the opposite edge —
        # comfortably past DEPOSIT_HS_MAX_DIST_PX.
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD + 50,
            buildings=[_hs_building(x=6200.0, y=6200.0)],
            player={"x": 100.0, "y": 100.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_DEPOSIT, (
            "Far-from-home deposit must be suppressed when cargo "
            "isn't full so the bot keeps making local progress "
            "instead of committing to an interrupt-prone round trip.")

    def test_far_from_home_full_cargo_still_deposits(self, _clock):
        """The distance gate is bypassed when cargo is genuinely
        full (iron ≥ DEPOSIT_IRON_FULL_THRESHOLD) — at that point
        the bot can't keep mining productively anyway, so the long
        trip is worth the risk of interruption."""
        ap._state.asteroid_blacklist.clear()
        s = _state(
            iron=ap.DEPOSIT_IRON_FULL_THRESHOLD,
            buildings=[_hs_building(x=6200.0, y=6200.0)],
            player={"x": 100.0, "y": 100.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT, (
            "Cargo-full deposits must bypass the distance gate — "
            "at DEPOSIT_IRON_FULL_THRESHOLD or above the bot can't "
            "productively keep mining, so the trip is worth taking.")

    def test_within_distance_gate_below_full_still_deposits(self, _clock):
        """Sanity: when within DEPOSIT_HS_MAX_DIST_PX, deposit
        fires normally for non-full cargo (per the existing iron-
        threshold logic).  Pins that the new gate doesn't also
        accidentally suppress short-trip deposits."""
        ap._state.asteroid_blacklist.clear()
        # Player at (3000, 3200), HS at (3200, 3200) — 200 px apart,
        # well within the 5000 px gate.
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            player={"x": 3000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT

    def test_deposit_fires_when_asteroid_out_of_chase_range(
            self, _clock):
        """The mine-before-deposit override only suppresses DEPOSIT
        when the asteroid is actually reachable.  An asteroid past
        MAX_ASTEROID_CHASE_PX shouldn't keep the bot from
        depositing — there's nothing nearby to mine."""
        ap._state.asteroid_blacklist.clear()
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building()],
            asteroids=[{"x": ap.MAX_ASTEROID_CHASE_PX + 500.0,
                        "y": 0.0, "hp": 100, "type": "Asteroid"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT

    def test_blacklisted_asteroid_does_not_suppress_deposit(self, _clock):
        """Blacklisted asteroids are filtered out by ``_nearest_asteroid``,
        so the suppression check sees no in-range target and lets
        DEPOSIT fire.  Without this, a stuck-blacklist would also
        block deposits."""
        ap._state.asteroid_blacklist.clear()
        # Blacklist the only nearby asteroid.
        ap._blacklist_asteroid({"x": 500.0, "y": 0.0})
        s = _state(
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building()],
            asteroids=[{"x": 500.0, "y": 0.0, "hp": 100,
                        "type": "Asteroid"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT

    def test_act_deposit_navigates_to_home_station_when_far(
            self, _clock, monkeypatch):
        """When the ship is far from the home station, _act_deposit
        calls _do_goto with the station's (x, y) — does NOT POST
        the deposit yet."""
        captured: dict = {}
        def _spy_goto(state, p, tx, ty, stop_radius=80.0):
            captured["tx"], captured["ty"] = tx, ty
        post_calls: list = []
        monkeypatch.setattr(ap, "_do_goto", _spy_goto)
        monkeypatch.setattr(
            ap, "_post_deposit_to_station",
            lambda timeout_s=5.0: post_calls.append(True))
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building(x=3200.0, y=3200.0)])
        ap._do_auto(s, s["player"])
        assert captured.get("tx") == 3200.0
        assert captured.get("ty") == 3200.0
        assert post_calls == []   # too far to deposit yet

    def test_act_deposit_posts_when_in_range(
            self, _clock, monkeypatch):
        """When within DEPOSIT_RANGE_PX of the home station,
        _act_deposit POSTs the deposit + stamps last_deposit_at."""
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_deposit_to_station",
            lambda timeout_s=5.0: (post_calls.append(True)
                                   or {"deposited": {"iron": 200}}))
        s = _state(
            player={"x": 3100.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building(x=3200.0, y=3200.0)])
        ap._do_auto(s, s["player"])
        assert len(post_calls) == 1
        assert ap._state.last_deposit_at == _clock[0]

    def test_act_deposit_posts_at_400px_post_2026_05_10(
            self, _clock, monkeypatch):
        """2026-05-10 telemetry-anchored regression.

        Pre-fix DEPOSIT_RANGE_PX = 200 left the bot wedged in
        S_DEPOSIT for 38.7 seconds at hs_dist 361-393 px -- the
        force-balance equilibrium of the 7 non-suppressed cluster
        buildings' stacked repulsion fields.  The bot couldn't
        close the final ~190 px, so ship_iron stayed at 110 and
        the deposit never landed.

        Post-fix DEPOSIT_RANGE_PX = 500 lets the bot fire the POST
        from its actual wedged position, unblocking the deposit
        cycle.  Server-side
        ``deposit_ship_resources_to_station`` doesn't enforce a
        distance check, so depositing from 400 px is safe.
        """
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_deposit_to_station",
            lambda timeout_s=5.0: (post_calls.append(True)
                                   or {"deposited": {"iron": 110}}))
        # Bot 400 px from HS -- right in the cluster-pin band the
        # telemetry caught (361-393 px).  Pre-fix this would have
        # navigated forever; post-fix it fires the POST.
        s = _state(
            player={"x": 3600.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building(x=3200.0, y=3200.0)])
        ap._do_auto(s, s["player"])
        assert ap.DEPOSIT_RANGE_PX >= 500.0
        assert len(post_calls) == 1, (
            "Bot at 400 px from HS must fire the deposit POST "
            "under the widened DEPOSIT_RANGE_PX; pre-fix this "
            "wedged for 38.7 s in the captured telemetry.")

    def test_act_deposit_does_not_repost_within_cooldown(
            self, _clock, monkeypatch):
        """Once a deposit POST has fired, ``_act_deposit`` must
        skip subsequent POSTs while ``last_deposit_at`` is still
        inside ``DEPOSIT_COOLDOWN_S``.  ``_choose_next_state``
        already gates S_DEPOSIT entry on the cooldown, but
        ``MIN_DWELL_S = 1 s`` keeps the FSM in S_DEPOSIT for ~10
        more ticks after the first POST — without this guard the
        bot fires 9 redundant empty-payload POSTs (each a 5 s
        timeout HTTP request) per deposit cycle.  Caught from
        2026-05-09 telemetry: 10 deposit_post events landed
        within 1.5 s, the first with real content and the next 9
        each with ``deposited={}``."""
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_deposit_to_station",
            lambda timeout_s=5.0: (post_calls.append(True)
                                   or {"deposited": {"iron": 200}}))

        class _FakeKey:
            released: int = 0
            @classmethod
            def hold(cls, name, on):
                pass
            @classmethod
            def release_all(cls):
                cls.released += 1

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 3100.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building(x=3200.0, y=3200.0)])

        # Simulate the post-deposit cooldown by stamping the
        # timestamp directly (mirrors the state right after the
        # first POST fires).
        ap._state.last_deposit_at = _clock[0]
        # Now invoke _act_deposit DIRECTLY (skipping FSM dispatch)
        # so we exercise the in-range path.  ``cooldown_remaining``
        # is the entire ``DEPOSIT_COOLDOWN_S`` window.
        from bot_autopilot_actions_station import _act_deposit
        _act_deposit(s, s["player"])
        assert len(post_calls) == 0, (
            "Deposit POST must NOT fire within DEPOSIT_COOLDOWN_S "
            "of the previous POST — the FSM's MIN_DWELL_S keeps "
            "the bot in S_DEPOSIT for ~10 ticks after the first "
            "successful POST and we must not spam empty deposits.")
        # KeyState.release_all was called to halt thrust.
        assert _FakeKey.released >= 1, (
            "The cooldown short-circuit must release the keys "
            "so the bot doesn't keep thrusting against the "
            "station while waiting for the FSM to transition.")

    def test_act_deposit_reposts_after_cooldown_expires(
            self, _clock, monkeypatch):
        """The cooldown guard must NOT block legitimate re-entries
        after the full cooldown window expires.  Pins that the
        guard doesn't accidentally turn into a permanent block."""
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_deposit_to_station",
            lambda timeout_s=5.0: (post_calls.append(True)
                                   or {"deposited": {"iron": 50}}))

        class _FakeKey:
            @classmethod
            def hold(cls, name, on): pass
            @classmethod
            def release_all(cls): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 3100.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.DEPOSIT_IRON_THRESHOLD,
            buildings=[_hs_building(x=3200.0, y=3200.0)])
        # Stamp last_deposit_at far enough in the past that the
        # cooldown is fully expired.
        ap._state.last_deposit_at = _clock[0] - ap.DEPOSIT_COOLDOWN_S - 1.0
        from bot_autopilot_actions_station import _act_deposit
        _act_deposit(s, s["player"])
        assert len(post_calls) == 1, (
            "Cooldown expired → POST must fire normally.")


# ── Craft / install queue ────────────────────────────────────────────────


def _crafter_building(x=3260.0, y=3260.0, *,
                      crafting=False, craft_target=""):
    """Build a Basic Crafter entry for /state.buildings."""
    return {"x": x, "y": y, "hp": 75, "type": "BasicCrafter",
            "building_type": "Basic Crafter",
            "crafting": crafting, "craft_target": craft_target,
            "disabled": False}


def _all_blueprints_in_station(extra=None):
    """Station-inventory dict pre-populated with one of every
    module blueprint the bot waits on before crafting."""
    items = {f"bp_{k}": 1 for k in ap.MODULE_CRAFT_QUEUE}
    if extra:
        items.update(extra)
    return items


class TestCraftQueueGate:
    """The module-craft phase requires:
      * Home Station + Basic Crafter built
      * Every blueprint in MODULE_CRAFT_QUEUE deposited
      * 2000 iron in station inventory (gate fires once, then sticky)
    Otherwise the FSM falls through to MINE / SEARCH.
    """

    def test_no_craft_without_basic_crafter(self, _clock):
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_CRAFT

    def test_no_craft_below_iron_threshold_on_first_entry(self, _clock):
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD - 1}),
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_CRAFT

    def test_no_craft_when_a_blueprint_is_missing(self, _clock):
        items = _all_blueprints_in_station(
            {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD})
        del items["bp_armor_plate"]
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=items,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_CRAFT

    def test_craft_triggers_with_all_conditions_met(self, _clock):
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_CRAFT

    def test_engage_preempts_craft(self, _clock):
        """Combat priority: alien within engage range steals the
        FSM from S_CRAFT just like every other non-defensive state."""
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
            aliens=[{"x": 400, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_busy_crafter_blocks_new_craft(self, _clock):
        """If any Basic Crafter is mid-cycle, the bot doesn't queue
        a second craft — it falls through to mining/searching while
        the active one finishes."""
        s = _state(
            buildings=[_hs_building(),
                       _crafter_building(crafting=True,
                                         craft_target="armor_plate")],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
            asteroids=[{"x": 100, "y": 0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_CRAFT


class TestCraftQueueOrder:
    """``_next_craft_target`` returns the right thing based on the
    current queue contents — module heads first, then repair packs,
    then shield recharges."""

    def test_first_target_is_armor_plate(self, _clock):
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        assert ap._next_craft_target(s) == "armor_plate"

    def test_module_phase_started_relaxes_2k_gate(self, _clock):
        """Once the first module craft has fired, the 2000-iron
        gate sticks open — the next module craft only needs enough
        iron for that module's per-craft cost."""
        ap._state.queue.module_phase_started = True
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": 800}),  # well below 2000 but above engine_booster cost (75)
        )
        # Pop armor_plate so engine_booster is the head.
        ap._state.queue.modules_to_craft.pop(0)
        assert ap._next_craft_target(s) == "engine_booster"

    def test_consumable_phase_starts_after_modules_drained(self, _clock):
        """With both queues drained except for repair packs, the
        next craft target is repair_pack — but only when the 2000
        iron gate is met (or the consumable phase already started)."""
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install.clear()
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={
                "iron": ap.CRAFT_PHASE_IRON_THRESHOLD},
        )
        assert ap._next_craft_target(s) == "repair_pack"

    def test_shield_recharge_after_repair_packs(self, _clock):
        """After repair packs run out, the next consumable in the
        queue is shield recharge."""
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.consumable_phase_started = True
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"iron": 200},
        )
        assert ap._next_craft_target(s) == "shield_recharge"

    def test_empty_queue_returns_none(self, _clock):
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"iron": 5000},
        )
        assert ap._next_craft_target(s) is None


class TestCraftQueueSkipsAlreadyDoneModules:
    """2026-05-10 user-reported bug: "the bot should only build the
    modules once, and it has built them multiple times".

    Root cause: ``CraftQueue.modules_to_craft`` resets to the full
    ``MODULE_CRAFT_QUEUE`` on every process start (BotState default),
    so a session resuming with already-crafted modules (sitting in
    station inv as ``mod_<key>`` OR installed on the ship) would
    re-craft them all.

    Fix: ``_next_craft_target`` skip-pops heads that are already
    crafted or installed, mirroring the equivalent guard in
    ``_next_install_target``.
    """

    def test_skips_module_already_in_station_inv(self, _clock):
        """Head of queue is ``armor_plate`` but station inv already
        has ``mod_armor_plate`` -- must skip to ``engine_booster``."""
        ap._state.queue.modules_to_craft = list(ap.MODULE_CRAFT_QUEUE)
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station({
                "iron": ap.CRAFT_PHASE_IRON_THRESHOLD,
                "mod_armor_plate": 1,
            }),
        )
        target = ap._next_craft_target(s)
        assert target == "engine_booster", (
            f"expected next target to skip already-crafted "
            f"armor_plate, got {target!r}")
        # Queue head was popped.
        assert ap._state.queue.modules_to_craft[0] == "engine_booster"

    def test_skips_module_already_installed(self, _clock):
        """Head of queue is ``armor_plate`` but ``armor_plate`` is
        already in ``state.module_slots`` -- must skip."""
        ap._state.queue.modules_to_craft = list(ap.MODULE_CRAFT_QUEUE)
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        s["module_slots"] = ["armor_plate", None, None]
        target = ap._next_craft_target(s)
        assert target == "engine_booster"
        assert ap._state.queue.modules_to_craft[0] == "engine_booster"

    def test_skips_multiple_already_done_heads(self, _clock):
        """Three modules already done -- must pop all three and
        return the fourth."""
        ap._state.queue.modules_to_craft = list(ap.MODULE_CRAFT_QUEUE)
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station({
                "iron": ap.CRAFT_PHASE_IRON_THRESHOLD,
                "mod_armor_plate": 1,
                "mod_engine_booster": 1,
            }),
        )
        # Third module already installed.
        s["module_slots"] = ["shield_booster", None]
        # MODULE_CRAFT_QUEUE order is [armor_plate, engine_booster,
        # shield_booster, shield_enhancer, damage_absorber,
        # broadside].  After popping the first three the head is
        # shield_enhancer.
        target = ap._next_craft_target(s)
        assert target == "shield_enhancer"
        assert ap._state.queue.modules_to_craft[0] == "shield_enhancer"

    def test_drains_queue_when_all_modules_done(self, _clock):
        """Every module already done -- queue empties and the
        function falls through to consumable / shield phases."""
        ap._state.queue.modules_to_craft = list(ap.MODULE_CRAFT_QUEUE)
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        # Every module installed.
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"iron": 5000},
        )
        s["module_slots"] = list(ap.MODULE_CRAFT_QUEUE)
        target = ap._next_craft_target(s)
        assert target is None
        assert ap._state.queue.modules_to_craft == []

    def test_does_not_skip_module_that_is_not_done(self, _clock):
        """Asymmetry guard: a module that is NOT in station inv and
        NOT installed must NOT be skipped."""
        ap._state.queue.modules_to_craft = list(ap.MODULE_CRAFT_QUEUE)
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        target = ap._next_craft_target(s)
        assert target == "armor_plate"
        # Queue head unchanged.
        assert ap._state.queue.modules_to_craft[0] == "armor_plate"


class TestModuleCraftPhaseShortCircuit:
    """One-time short-circuit at FSM start.  When ALL modules in
    the default queue are already crafted/installed, drain the
    queue and latch ``module_phase_started`` so the FSM doesn't
    even attempt a craft-phase round trip.  Mirrors
    ``build_done_short_circuit`` and
    ``consumable_phase_done_short_circuit`` patterns."""

    def test_short_circuit_drains_queue_when_everything_done(
            self, _clock, _fresh_bot_state):
        """All 6 modules already installed -- short-circuit fires."""
        s = _state(
            buildings=[_hs_building()],
            player={"x": 3250.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["module_slots"] = list(ap.MODULE_CRAFT_QUEUE)
        ap._do_auto(s, s["player"])
        assert ap._state.queue.modules_to_craft == []
        assert ap._state.queue.module_phase_started is True

    def test_short_circuit_partial_pop(self, _clock, _fresh_bot_state):
        """First 2 modules already done -- pops 2 heads but doesn't
        latch module_phase_started (queue isn't empty yet)."""
        s = _state(
            buildings=[_hs_building()],
            player={"x": 3250.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items={
                "iron": 100,
                "mod_armor_plate": 1,
                "mod_engine_booster": 1,
            },
        )
        # The starter base SETUP doesn't have anything installed on
        # the ship; the short-circuit detects via station inventory.
        ap._do_auto(s, s["player"])
        assert ap._state.queue.modules_to_craft[0] == "shield_booster", (
            f"expected first two heads to be popped; got "
            f"{ap._state.queue.modules_to_craft}")
        # module_phase_started stays False because the queue isn't empty.
        assert ap._state.queue.module_phase_started is False

    def test_short_circuit_does_not_fire_when_nothing_done(
            self, _clock, _fresh_bot_state):
        """Asymmetry guard: empty inventory + no modules installed
        means the queue is untouched."""
        s = _state(
            buildings=[_hs_building()],
            player={"x": 3250.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        before = list(ap._state.queue.modules_to_craft)
        ap._do_auto(s, s["player"])
        assert list(ap._state.queue.modules_to_craft) == before


class TestInstallQueue:
    """Install priority + queue-pop behaviour for the four modules
    the bot installs after the craft phase."""

    def test_install_takes_priority_over_craft(self, _clock):
        """When ``mod_broadside`` is in the station inventory, the
        FSM enters S_INSTALL even if the craft queue still has
        unfinished modules."""
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items=_all_blueprints_in_station({
                "iron": ap.CRAFT_PHASE_IRON_THRESHOLD,
                "mod_broadside": 1,
            }),
        )
        # Drop broadside off the craft queue (it was crafted) so the
        # remaining craft queue head is engine_booster.
        ap._state.queue.modules_to_craft = ["engine_booster"]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_INSTALL

    def test_install_skips_already_installed_modules(self, _clock):
        """If broadside is already on the ship (for whatever
        reason), the install queue pops it and re-evaluates."""
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"mod_broadside": 1},
            module_slots=["broadside", None, None, None],
        )
        ap._state.queue.modules_to_craft.clear()
        target = ap._next_install_target(s)
        # Pop happened — now head is shield_booster, which isn't in
        # station inv, so no install target.
        assert target is None
        assert ap._state.queue.modules_to_install[0] == "shield_booster"

    def test_install_returns_none_when_module_not_in_station(self, _clock):
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={},  # no mod_broadside
        )
        assert ap._next_install_target(s) is None


class TestCraftAction:
    """``_act_craft`` navigates to a Basic Crafter and fires
    POST /craft when in range, popping the queue on success."""

    def test_navigates_when_far_does_not_post(self, _clock, monkeypatch):
        captured: dict = {}
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0: captured.update(
                tx=tx, ty=ty))
        monkeypatch.setattr(
            ap, "_post_craft",
            lambda target, timeout_s=5.0: post_calls.append(target)
            or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(),
                       _crafter_building(x=4000.0, y=4000.0)],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        ap._do_auto(s, s["player"])
        assert captured.get("tx") == 4000.0
        assert captured.get("ty") == 4000.0
        assert post_calls == []

    def test_posts_craft_when_in_range(self, _clock, monkeypatch):
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_craft",
            lambda target, timeout_s=5.0: (post_calls.append(target)
                                            or {"ok": True}))
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(),
                       _crafter_building(x=4050.0, y=4050.0)],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        ap._do_auto(s, s["player"])
        assert post_calls == ["armor_plate"]
        assert ap._state.queue.modules_to_craft[0] == "engine_booster"
        assert ap._state.queue.module_phase_started is True

    def test_failed_post_does_not_pop_queue(self, _clock, monkeypatch):
        monkeypatch.setattr(
            ap, "_post_craft",
            lambda target, timeout_s=5.0: {"ok": False,
                                            "reason": "no idle crafter"})
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(),
                       _crafter_building(x=4050.0, y=4050.0)],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        before = list(ap._state.queue.modules_to_craft)
        ap._do_auto(s, s["player"])
        assert ap._state.queue.modules_to_craft == before

    def test_posts_craft_from_400px_post_2026_05_10(
            self, _clock, monkeypatch):
        """2026-05-10 telemetry-anchored regression.

        Pre-fix CRAFT_INTERACT_RANGE_PX = 200 left the bot wedged
        in S_CRAFT 9 times during a 39-minute session, all at
        hs_dist 280-470 px (cluster-pin band: the 7 non-suppressed
        cluster buildings stacked their repulsion fields and pushed
        the bot to a force-balance equilibrium outside the pre-fix
        200 px gate).

        Post-fix CRAFT_INTERACT_RANGE_PX = 500 lets the bot fire
        the craft POST from its actual wedged position outside the
        cluster.  Server-side ``start_craft`` doesn't enforce a
        distance check, so depositing from 400 px is safe.
        """
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_craft",
            lambda target, timeout_s=5.0: (post_calls.append(target)
                                            or {"ok": True}))
        # Bot 400 px from crafter -- right in the cluster-pin band
        # the telemetry caught.  Pre-fix this would have navigated
        # forever; post-fix it fires the POST.
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(),
                       _crafter_building(x=4400.0, y=4000.0)],
            station_inventory_items=_all_blueprints_in_station(
                {"iron": ap.CRAFT_PHASE_IRON_THRESHOLD}),
        )
        ap._do_auto(s, s["player"])
        assert ap.CRAFT_INTERACT_RANGE_PX >= 500.0
        assert post_calls == ["armor_plate"], (
            "Bot at 400 px from crafter must fire the craft POST "
            "under the widened CRAFT_INTERACT_RANGE_PX; pre-fix "
            "this wedged at hs_dist 280-470 px in the captured "
            "telemetry, producing 9 stuck_detected events in 39 min.")


class TestInstallAction:
    """``_act_install`` navigates to the Home Station and fires
    POST /install_module when in range, popping the install queue
    on success."""

    def test_posts_install_when_in_range(self, _clock, monkeypatch):
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_install_module",
            lambda mod_key, timeout_s=5.0: (post_calls.append(mod_key)
                                             or {"ok": True, "slot": 0}))
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0),
                       _crafter_building()],
            station_inventory_items={"mod_broadside": 1},
        )
        ap._state.queue.modules_to_craft.clear()
        ap._do_auto(s, s["player"])
        assert post_calls == ["broadside"]
        # First entry of install queue is broadside; should pop.
        assert ap._state.queue.modules_to_install[0] == "shield_booster"

    def test_posts_install_from_400px_post_2026_05_10(
            self, _clock, monkeypatch):
        """Mirror of the CRAFT regression: same cluster geometry,
        same risk profile, same widened range
        (INSTALL_INTERACT_RANGE_PX = 500).
        """
        post_calls: list = []
        monkeypatch.setattr(
            ap, "_post_install_module",
            lambda mod_key, timeout_s=5.0: (post_calls.append(mod_key)
                                             or {"ok": True, "slot": 0}))
        # Bot 400 px from HS, in the cluster-pin band.
        s = _state(
            player={"x": 3600.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0),
                       _crafter_building()],
            station_inventory_items={"mod_broadside": 1},
        )
        ap._state.queue.modules_to_craft.clear()
        ap._do_auto(s, s["player"])
        assert ap.INSTALL_INTERACT_RANGE_PX >= 500.0
        assert post_calls == ["broadside"], (
            "Bot at 400 px from HS must fire the install POST "
            "under the widened INSTALL_INTERACT_RANGE_PX.")


class TestCraftQueueDefaults:
    """Pin the user-facing queue ordering so changes here are
    deliberate, not accidental."""

    def test_module_craft_order(self):
        assert list(ap.MODULE_CRAFT_QUEUE) == [
            "armor_plate", "engine_booster", "shield_booster",
            "shield_enhancer", "damage_absorber", "broadside",
        ]

    def test_module_install_order(self):
        assert list(ap.MODULE_INSTALL_QUEUE) == [
            "broadside", "shield_booster",
            "shield_enhancer", "armor_plate",
        ]

    def test_consumable_batch_counts(self):
        assert ap.REPAIR_PACK_CRAFT_BATCHES == 5
        assert ap.SHIELD_RECHARGE_CRAFT_BATCHES == 5


# ── Boundary repulsion (potential field) ─────────────────────────────────


class TestBoundaryRepulsion:
    """``_boundary_repulsion`` returns a per-axis push vector that
    ramps from 0 (at ``BOUNDARY_REPULSION_RANGE_PX`` from an edge)
    to 1 (right at the edge).  Far from any edge it's exactly zero
    so the safe case pays no cost."""

    def _zone(self, w=6400, h=6400):
        return {"world_w": w, "world_h": h, "zone_id": "ZoneID.MAIN"}

    def test_far_from_edges_returns_zero(self):
        rx, ry = ap._boundary_repulsion(
            {"x": 3200.0, "y": 3200.0}, self._zone())
        assert rx == 0.0 and ry == 0.0

    def test_at_west_edge_pushes_east(self):
        rx, ry = ap._boundary_repulsion(
            {"x": 0.0, "y": 3200.0}, self._zone())
        assert rx == 1.0
        assert ry == 0.0

    def test_at_east_edge_pushes_west(self):
        rx, ry = ap._boundary_repulsion(
            {"x": 6400.0, "y": 3200.0}, self._zone())
        assert rx == -1.0
        assert ry == 0.0

    def test_at_south_edge_pushes_north(self):
        rx, ry = ap._boundary_repulsion(
            {"x": 3200.0, "y": 0.0}, self._zone())
        assert rx == 0.0
        assert ry == 1.0

    def test_at_north_edge_pushes_south(self):
        rx, ry = ap._boundary_repulsion(
            {"x": 3200.0, "y": 6400.0}, self._zone())
        assert rx == 0.0
        assert ry == -1.0

    def test_at_sw_corner_pushes_diagonally_ne(self):
        """Corners stack both axes — the result is a 45° push away
        from the corner without any extra special-case logic."""
        rx, ry = ap._boundary_repulsion(
            {"x": 0.0, "y": 0.0}, self._zone())
        assert rx == 1.0
        assert ry == 1.0

    def test_ramps_linearly_across_range(self):
        """Halfway through the range -> half magnitude."""
        half = ap.BOUNDARY_REPULSION_RANGE_PX * 0.5
        rx, _ = ap._boundary_repulsion(
            {"x": half, "y": 3200.0}, self._zone())
        assert abs(rx - 0.5) < 1e-9

    def test_missing_zone_dims_returns_zero(self):
        """Defensive: a /state without world dimensions yields zero
        repulsion (caller falls back to plain angle_to)."""
        rx, ry = ap._boundary_repulsion(
            {"x": 100.0, "y": 100.0}, {})
        assert rx == 0.0 and ry == 0.0


class TestSteeredHeadingDeflectsNearEdge:
    """``_steered_heading`` blends repulsion into the goto vector.
    These tests confirm the deflection happens (i.e. the heading
    moves away from the wall) without being so strong that the bot
    completely abandons distant targets."""

    def test_far_from_edges_heading_is_unchanged(self):
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150})
        # Goto vector pointing east (dx=+1000, dy=0).
        h = ap._steered_heading(s, s["player"], 1000.0, 0.0, 1000.0)
        # angle_to(+x, 0) returns 90° (east) under arcade's
        # heading-0-=-north convention.
        assert abs(h - 90.0) < 0.01

    def test_pinned_at_west_edge_pure_west_goto_falls_back_to_repulsion(self):
        """Bot pinned at the west edge with a goto pointing further
        west (degenerate cancellation case): ``_steered_heading``
        falls back to **pure repulsion** so the bot peels off the
        wall instead of arbitrarily collapsing to angle_to(0, 0).
        Heading should be 90° (pure east) — directly away from
        the west wall."""
        s = _state(
            player={"x": 0.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150})
        h = ap._steered_heading(s, s["player"], -100.0, 0.0, 100.0)
        assert abs(h - 90.0) < 0.01, (
            f"expected fallback to pure-east repulsion (90°), got {h}°")

    def test_pinned_at_north_edge_pure_north_goto_falls_back_to_repulsion(self):
        """Same fallback at the north edge: degenerate cancellation
        steers the bot to pure south (180°) — away from the
        north wall."""
        s = _state(
            player={"x": 3200.0, "y": 6400.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150})
        h = ap._steered_heading(s, s["player"], 0.0, 100.0, 100.0)
        assert abs(h - 180.0) < 0.01, (
            f"expected fallback to pure-south repulsion (180°), got {h}°")

    def test_half_range_deflection_is_significant(self):
        """At half the repulsion range, the deflection should be
        roughly 27° (atan2(0.5, 1.0)) for a goto pointing into the
        wall.  Pin it within a small tolerance."""
        import math as _math
        rng_half = ap.BOUNDARY_REPULSION_RANGE_PX * 0.5
        s = _state(
            player={"x": rng_half, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150})
        # Goto pointing north (dx=0, dy=+1000).  Field at this x
        # contributes (+0.5, 0) — pushing east as we travel north.
        h = ap._steered_heading(s, s["player"], 0.0, 1000.0, 1000.0)
        # angle_to(+0.5, 1.0) = degrees(atan2(0.5, 1.0)) ≈ 26.57°
        expected = _math.degrees(_math.atan2(0.5, 1.0))
        assert abs(h - expected) < 0.5


class TestBuildingRepulsion:
    """``_building_repulsion`` keeps the bot from pinning itself
    on the corners of its own station.  Each building within
    BUILDING_REPULSION_RANGE_PX contributes a unit-vector pointing
    from the building toward the ship; corners stack two
    contributions automatically."""

    def _building(self, x, y):
        return {"x": x, "y": y, "hp": 100, "type": "StationModule",
                "building_type": "Service Module"}

    def test_no_buildings_returns_zero(self):
        rx, ry = ap._building_repulsion({"x": 100.0, "y": 100.0},
                                         {"buildings": []})
        assert rx == 0.0 and ry == 0.0

    def test_outside_range_returns_zero(self):
        s = {"buildings": [self._building(0.0, 0.0)]}
        # Ship is 300 px from a single building, well past the
        # 150 px base range (no Home Station multiplier here) —
        # no contribution.
        rx, ry = ap._building_repulsion({"x": 300.0, "y": 0.0}, s)
        assert rx == 0.0 and ry == 0.0

    def test_pushes_away_from_single_building(self):
        """Ship 75 px east of a building — repulsion points east
        with magnitude (1 - 75/150) = 0.5."""
        s = {"buildings": [self._building(0.0, 0.0)]}
        rx, ry = ap._building_repulsion({"x": 75.0, "y": 0.0}, s)
        assert abs(rx - 0.5) < 1e-9
        assert abs(ry) < 1e-9

    def test_corner_stacks_two_buildings(self):
        """The corner-stuck case: two buildings meeting at a right
        angle.  The bot sitting at the outer corner gets a
        diagonal push that's the sum of both contributions —
        without any special-case logic for corners."""
        s = {"buildings": [
            self._building(0.0, 0.0),     # west neighbour
            self._building(75.0, 75.0),   # north neighbour
        ]}
        # Ship just past the corner, 75 px from each building.
        rx, ry = ap._building_repulsion(
            {"x": 75.0, "y": 0.0}, s)
        # West neighbour at (0,0) — push east (+x): strength 0.5,
        #   direction (+1, 0)  -> (+0.5, 0)
        # North neighbour at (75,75) — push south (-y): strength 0.5,
        #   direction (0, -1)  -> (0, -0.5)
        # Sum: (+0.5, -0.5) — diagonal away from the corner.
        assert abs(rx - 0.5) < 1e-9
        assert abs(ry + 0.5) < 1e-9

    def test_steered_heading_routes_around_station_corner(self):
        """End-to-end fix for the user's reported case: bot
        navigating past the corner of the player-built station
        (two perpendicular buildings) gets deflected diagonally
        away from the corner instead of pinning between the
        two walls.

        Setup mirrors a real station corner — two Service Modules
        sitting at right angles.  The ship is just past the
        corner with a goto pointing east; the deflected heading
        must turn south-east (away from both buildings) rather
        than continuing pure east into the corner trap."""
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[
                # North neighbour — pushes south (-y).
                {"x": 3200.0, "y": 3275.0, "hp": 100,
                 "type": "StationModule",
                 "building_type": "Service Module"},
                # East neighbour — pushes west (-x).
                {"x": 3275.0, "y": 3200.0, "hp": 100,
                 "type": "StationModule",
                 "building_type": "Repair Module"},
            ])
        # Goto pointing east, straight into the corner.
        h = ap._steered_heading(s, s["player"], 1000.0, 0.0, 1000.0)
        # The unsteered heading would be 90° (east).  With both
        # neighbours pushing back, the deflected heading swings
        # south-east — past 90° but well under 180°.  Check the
        # qualitative sign: heading must be > 90° (turned south)
        # but the bot must still make eastward progress (heading
        # < 180°).
        assert 90.0 < h < 180.0, (
            f"expected south-east deflection (90°-180°), got {h}°")

    def test_axial_pin_against_one_building_does_not_deflect(self):
        """Documented limitation of a pure potential field: a
        goto pointing **straight** at a single building has no
        tangential component to deflect along, so the field only
        opposes (slows) the goto.  Real-world this is rare —
        buildings are usually off-axis from the bot's heading,
        and corners (two buildings) deflect correctly per the
        test above.  The reactive ``_detect_stuck`` watchdog is
        the backstop for this case."""
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[
                {"x": 3200.0, "y": 3275.0, "hp": 100,
                 "type": "StationModule",
                 "building_type": "Service Module"}])
        h = ap._steered_heading(s, s["player"], 0.0, 1000.0, 1000.0)
        # Heading still 0° (north): repulsion reduced the
        # magnitude but didn't change the direction.  Pin the
        # behaviour so future changes are deliberate.
        assert abs(h - 0.0) < 0.01


class TestBuildingRepulsionDoesNotBlockDeposit:
    """Deposit / install / craft actions navigate close to their
    target building.  After the 2026-05-04 hardening cycle widened
    the per-building repulsion range from 80 → 150 px (with Home
    Station at 1.5× = 225 px), some action stop-radii now sit
    *inside* the raw repulsion field — but ``building_repulsion``
    is now ALSO target-aware: buildings within
    REPULSION_TARGET_SUPPRESS_PX of the goto target are excluded
    from the sum.  This test pins the suppression mechanism rather
    than the raw constant relationship."""

    def test_target_suppression_clears_field_at_destination(self):
        """When goto target == building position, that building's
        repulsion is suppressed so the bot can dock."""
        s = {"buildings": [{"x": 3200.0, "y": 3200.0, "hp": 100,
                            "type": "StationModule",
                            "building_type": "Home Station"}]}
        # Bot 100 px from HS — well inside the 225 px Home Station
        # field WITHOUT suppression.  WITH suppression (target = HS
        # position), repulsion is zero.
        rx, ry = ap._building_repulsion(
            {"x": 3300.0, "y": 3200.0}, s, target=(3200.0, 3200.0))
        assert rx == 0.0 and ry == 0.0

    def test_suppression_only_applies_to_buildings_near_target(self):
        """Repulsion still fires from buildings AWAY from the goto
        target — only the docking building is suppressed."""
        s = {"buildings": [
            {"x": 3200.0, "y": 3200.0, "hp": 100,
             "type": "StationModule", "building_type": "Home Station"},
            {"x": 3200.0, "y": 3400.0, "hp": 100,
             "type": "StationModule", "building_type": "Service Module"},
        ]}
        # Bot near both, goto target = HS only.  HS is suppressed,
        # Service Module still pushes.
        rx, ry = ap._building_repulsion(
            {"x": 3200.0, "y": 3320.0}, s, target=(3200.0, 3200.0))
        # Service Module (at 3200,3400) is 80 px north — pushes south.
        assert ry < 0.0  # negative-y push (away from north building)

    def test_install_action_target_passed_through(self):
        """Sanity: after the hardening cycle, INSTALL still works.
        Pin the constants so a regression that bumps repulsion
        without bumping suppression is caught.

        Suppression radius widened from 50 to 100 in 2026-05-10:
        the starter base places adjacent buildings at 60 px from
        their neighbours (Repair Module 60 px from Basic Crafter),
        so a 50 px gate left the RM repelling the bot away from
        its CRAFT target.
        """
        # Suppression radius must cover the tightest adjacent-
        # building distance in the starter base layout (60 px
        # between Repair Module and Basic Crafter).
        assert ap.REPULSION_TARGET_SUPPRESS_PX >= 100.0


# ── Pickup blacklist (stuck-in-GATHER recovery) ──────────────────────────


class TestPickupBlacklist:
    """When stuck-detect fires while the FSM is in S_GATHER, the
    pickup the bot was chasing is blacklisted — typically because
    it's sitting inside a station-building's repulsion zone, where
    the goto vector pulls toward it but the field pushes back, so
    the bot oscillates forever without making progress.  Tests
    pin the blacklist mechanic + its TTL eviction."""

    def test_blacklisted_pickup_skipped_by_nearest_pickup(self, _clock):
        ap._state.pickup_blacklist.clear()
        # Two iron pickups: one will be blacklisted, one fresh.
        s = _state(iron_pickups=[
            {"x": 100.0, "y": 0.0, "amount": 5, "item_type": "iron"},
            {"x": 500.0, "y": 0.0, "amount": 5, "item_type": "iron"},
        ])
        ap._blacklist_pickup({"x": 100.0, "y": 0.0})
        # Nearest free pickup should be the 500 px one, not the
        # blacklisted 100 px one.
        pu, d = ap._nearest_pickup(s, 0.0, 0.0)
        assert pu is not None
        assert pu["x"] == 500.0

    def test_blacklist_radius_covers_close_pickups(self, _clock):
        """Pickups within PICKUP_BLACKLIST_RADIUS_PX of a
        blacklisted point are also skipped — covers the case
        where a pickup spawns at a slightly different position
        each tick (e.g. iron pickup splits)."""
        ap._state.pickup_blacklist.clear()
        ap._blacklist_pickup({"x": 100.0, "y": 0.0})
        near = {"x": 130.0, "y": 0.0}  # 30 px away, well inside 60 px radius
        far = {"x": 200.0, "y": 0.0}   # 100 px away, outside radius
        assert ap._pickup_is_blacklisted(near) is True
        assert ap._pickup_is_blacklisted(far) is False

    def test_blacklist_entries_expire(self, _clock):
        """After ``PICKUP_BLACKLIST_TTL_S``, entries expire so
        the bot can retry a temporarily-trapped pickup."""
        ap._state.pickup_blacklist.clear()
        ap._blacklist_pickup({"x": 100.0, "y": 0.0})
        assert ap._pickup_is_blacklisted({"x": 100.0, "y": 0.0}) is True
        # Jump past the TTL.
        _clock[0] += ap.PICKUP_BLACKLIST_TTL_S + 1.0
        assert ap._pickup_is_blacklisted({"x": 100.0, "y": 0.0}) is False
        # Expired entry was lazily evicted from the dict.
        assert len(ap._state.pickup_blacklist) == 0

    def test_stuck_in_gather_blacklists_the_target_pickup(
            self, _clock):
        """End-to-end fix: when the bot gets stuck while
        gathering, the pickup it was chasing lands in the
        blacklist and the next GATHER pass picks a different
        target."""
        ap._state.pickup_blacklist.clear()
        # Drive a stuck cycle WHILE the bot is in GATHER (pickup
        # visible, no movement).  Pin position at (100, 100) with
        # an iron pickup right next to it.
        for _ in range(20):
            s = _state(
                player={"x": 100.0, "y": 100.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                iron_pickups=[
                    {"x": 110.0, "y": 100.0,
                     "amount": 5, "item_type": "iron"}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        # FSM was in GATHER (only state with a pickup nearby);
        # stuck-detect should have fired and added the pickup to
        # the blacklist.
        assert len(ap._state.pickup_blacklist) >= 1, (
            "stuck while gathering must blacklist the pickup")
        # Next GATHER pass with the same pickup should see it
        # filtered out.
        s2 = _state(iron_pickups=[
            {"x": 110.0, "y": 100.0, "amount": 5, "item_type": "iron"}])
        pu, _d = ap._nearest_pickup(s2, 100.0, 100.0)
        assert pu is None, (
            "the previously-stuck pickup must not be re-targeted")


class TestAsteroidBlacklist:
    """Same mechanic as TestPickupBlacklist but for asteroids
    targeted while in S_MINE.  Diagnosed via the
    bot_io/autopilot_telemetry.jsonl session that showed 5
    consecutive stuck-detects within 12 s at the same world
    position, all in S_MINE — the bot was pressing against an
    asteroid (asteroids aren't in the building/boundary
    repulsion field, so the field couldn't deflect around it)."""

    def test_blacklisted_asteroid_skipped_by_nearest_asteroid(
            self, _clock):
        ap._state.asteroid_blacklist.clear()
        s = _state(asteroids=[
            {"x": 100.0, "y": 0.0, "hp": 100, "type": "Asteroid"},
            {"x": 500.0, "y": 0.0, "hp": 100, "type": "Asteroid"},
        ])
        ap._blacklist_asteroid({"x": 100.0, "y": 0.0})
        ast, _d = ap._nearest_asteroid(s, 0.0, 0.0)
        assert ast is not None
        assert ast["x"] == 500.0

    def test_blacklist_radius_covers_close_asteroids(self, _clock):
        ap._state.asteroid_blacklist.clear()
        ap._blacklist_asteroid({"x": 100.0, "y": 0.0})
        near = {"x": 120.0, "y": 0.0}  # 20 px away, inside 40 px radius
        far = {"x": 200.0, "y": 0.0}   # 100 px away, outside
        assert ap._asteroid_is_blacklisted(near) is True
        assert ap._asteroid_is_blacklisted(far) is False

    def test_blacklist_entries_expire(self, _clock):
        ap._state.asteroid_blacklist.clear()
        ap._blacklist_asteroid({"x": 100.0, "y": 0.0})
        assert ap._asteroid_is_blacklisted(
            {"x": 100.0, "y": 0.0}) is True
        _clock[0] += ap.ASTEROID_BLACKLIST_TTL_S + 1.0
        assert ap._asteroid_is_blacklisted(
            {"x": 100.0, "y": 0.0}) is False
        # Lazy eviction during the lookup.
        assert len(ap._state.asteroid_blacklist) == 0

    def test_stuck_in_mine_blacklists_the_target_asteroid(
            self, _clock):
        """End-to-end fix: when the bot gets stuck while mining,
        the asteroid it was pressing against lands in the
        blacklist and the next MINE evaluation either picks a
        different asteroid or falls through to SEARCH."""
        ap._state.asteroid_blacklist.clear()
        ap._state.pickup_blacklist.clear()
        # Pin position with one asteroid right next to the bot.
        for _ in range(20):
            s = _state(
                player={"x": 100.0, "y": 100.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                asteroids=[
                    {"x": 110.0, "y": 100.0,
                     "hp": 100, "type": "Asteroid"}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert len(ap._state.asteroid_blacklist) >= 1, (
            "stuck while mining must blacklist the asteroid")
        # Re-querying with the same asteroid: it should be filtered.
        s2 = _state(asteroids=[
            {"x": 110.0, "y": 100.0, "hp": 100, "type": "Asteroid"}])
        ast, _d = ap._nearest_asteroid(s2, 100.0, 100.0)
        assert ast is None, (
            "the previously-stuck asteroid must not be re-targeted")

    def test_choose_next_state_falls_through_to_search_when_all_blacklisted(
            self, _clock):
        """If every visible asteroid is blacklisted,
        _choose_next_state must NOT return S_MINE — it should
        fall through to S_SEARCH so the bot relocates instead of
        idling on an empty asteroid pointer."""
        ap._state.asteroid_blacklist.clear()
        ap._blacklist_asteroid({"x": 100.0, "y": 0.0})
        s = _state(asteroids=[
            {"x": 100.0, "y": 0.0, "hp": 100, "type": "Asteroid"}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_MINE, (
            "MINE must not fire when the only asteroid is "
            "blacklisted")


class TestAsteroidChaseDistanceCap:
    """An asteroid farther than ``MAX_ASTEROID_CHASE_PX`` is
    treated as out-of-reach by the MINE-vs-SEARCH gate, so the
    FSM falls through to SEARCH (spiral around current position)
    instead of committing the bot to a long obstacle-laden trip
    across the world.  Diagnosed via the bot_io session that
    showed 61% of time spent more than 1500 px from base."""

    def test_mine_does_not_fire_for_asteroid_beyond_chase_cap(
            self, _clock):
        ap._state.asteroid_blacklist.clear()
        # Asteroid placed exactly past the cap.
        s = _state(asteroids=[
            {"x": ap.MAX_ASTEROID_CHASE_PX + 100.0, "y": 0.0,
             "hp": 100, "type": "Asteroid"}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH, (
            "MINE must fall through to SEARCH for asteroids "
            "beyond MAX_ASTEROID_CHASE_PX")

    def test_mine_fires_for_asteroid_inside_chase_cap(self, _clock):
        ap._state.asteroid_blacklist.clear()
        # Asteroid well inside the cap.
        s = _state(asteroids=[
            {"x": 800.0, "y": 0.0, "hp": 100, "type": "Asteroid"}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE

    def test_chase_cap_applies_after_blacklist_filter(self, _clock):
        """Both filters compose: a near asteroid that's
        blacklisted + a far asteroid beyond the cap means MINE
        can't fire, falls through to SEARCH."""
        ap._state.asteroid_blacklist.clear()
        # Blacklist the near one.
        ap._blacklist_asteroid({"x": 100.0, "y": 0.0})
        s = _state(asteroids=[
            {"x": 100.0, "y": 0.0,
             "hp": 100, "type": "Asteroid"},
            {"x": ap.MAX_ASTEROID_CHASE_PX + 500.0, "y": 0.0,
             "hp": 100, "type": "Asteroid"},
        ])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH

    def test_search_giveup_drops_chase_cap(self, _clock):
        """After the FSM has been in S_SEARCH for SEARCH_GIVEUP_S
        seconds, the chase cap is dropped so the bot commits to
        the nearest visible asteroid regardless of distance.
        Without this escape hatch the bot can spiral indefinitely
        in a region whose only asteroids sit just past the cap
        (observed: 187 s of continuous SEARCH at one anchor with
        3-6 asteroids visible the whole time, all out of chase
        range)."""
        ap._state.asteroid_blacklist.clear()
        # Far asteroid beyond the chase cap.
        far_x = ap.MAX_ASTEROID_CHASE_PX + 500.0
        s = _state(asteroids=[
            {"x": far_x, "y": 0.0, "hp": 100, "type": "Asteroid"}])
        # Enter SEARCH.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH
        # Stay in SEARCH for the full giveup window.
        _clock[0] += ap.SEARCH_GIVEUP_S + ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        # Now the cap drops and MINE fires.
        assert ap._fsm["state"] == ap.S_MINE

    def test_giveup_commitment_is_sticky_across_ticks(self, _clock):
        """Regression for the bouncing pattern: SEARCH → MINE
        (giveup fires) → SEARCH (giveup no longer applies because
        cur != S_SEARCH) → MINE (giveup fires again) → SEARCH...
        Observed in the diagnosed session at t=122 and t=183.
        The commitment must stick across ticks so MINE persists
        until the bot actually reaches a chase-range asteroid
        OR all asteroids vanish."""
        ap._state.asteroid_blacklist.clear()
        ap._state.chase_committed = False
        far_x = ap.MAX_ASTEROID_CHASE_PX + 500.0
        s = _state(asteroids=[
            {"x": far_x, "y": 0.0, "hp": 100, "type": "Asteroid"}])
        # Enter SEARCH and stay long enough for giveup.
        ap._do_auto(s, s["player"])
        _clock[0] += ap.SEARCH_GIVEUP_S + ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        assert ap._state.chase_committed is True
        # Walk forward several MIN_DWELL windows with the same
        # state (asteroid still beyond cap).  The FSM must STAY
        # in MINE — without the sticky flag it would bounce back
        # to SEARCH because ``long_search`` is False once cur is
        # MINE, and the cap re-applies.
        for _ in range(5):
            _clock[0] += ap.MIN_DWELL_S + 0.1
            ap._do_auto(s, s["player"])
            assert ap._fsm["state"] == ap.S_MINE, (
                "MINE must stay sticky once chase_committed is set")

    def test_chase_commitment_clears_when_target_reached(self, _clock):
        """When the bot moves into chase range of an asteroid
        (either by progress along the long chase, or because a
        new closer asteroid appeared), the commitment clears so
        future SEARCH episodes get the normal cap-protected
        behaviour."""
        ap._state.asteroid_blacklist.clear()
        ap._state.chase_committed = True   # pretend we were chasing far
        # Now an asteroid is in chase range.
        s = _state(asteroids=[
            {"x": 500.0, "y": 0.0, "hp": 100, "type": "Asteroid"}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        assert ap._state.chase_committed is False, (
            "chase_committed should clear once an in-range "
            "asteroid is targeted")

    def test_chase_commitment_clears_when_no_asteroid_visible(
            self, _clock):
        ap._state.asteroid_blacklist.clear()
        ap._state.chase_committed = True
        s = _state()  # no asteroids
        ap._do_auto(s, s["player"])
        assert ap._state.chase_committed is False

    def test_idle_at_base_giveup_drops_chase_cap(self, _clock):
        """When a Home Station exists and the bot has been parked
        in S_IDLE_AT_BASE for ``IDLE_AT_BASE_GIVEUP_S`` with only
        out-of-range asteroids visible, the chase cap must drop so
        the bot commits to a long round trip rather than parking
        indefinitely.  Caught from 2026-05-09 user report: the bot
        stopped going after asteroids when all enemies were
        destroyed and only far asteroids (>MAX_ASTEROID_CHASE_PX)
        remained — section 6's giveup gate was originally only
        checking ``cur == S_SEARCH`` so a station-equipped bot
        routed to S_IDLE_AT_BASE in section 8 and never escaped.
        The IDLE-side gate later (2026-05-09 follow-up) was
        tightened to ``IDLE_AT_BASE_GIVEUP_S`` (10 s) so the
        observed latency is responsive."""
        ap._state.asteroid_blacklist.clear()
        ap._state.chase_committed = False
        # Far asteroid beyond the chase cap, plus a Home Station
        # so section 8 routes the bot to S_IDLE_AT_BASE rather
        # than S_SEARCH when the asteroid is out of range.
        far_x = ap.MAX_ASTEROID_CHASE_PX + 500.0
        s = _state(
            asteroids=[{"x": far_x, "y": 0.0, "hp": 100,
                        "type": "Asteroid"}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # build_done must be latched True so the BUILD branch
        # doesn't preempt — mirrors the housekeeping short-
        # circuit at the top of _choose_next_state.
        ap._state.build_done = True
        # Enter IDLE_AT_BASE on the first tick.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        # Stay in IDLE for the IDLE-side giveup window.
        _clock[0] += ap.IDLE_AT_BASE_GIVEUP_S + ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        # Now the cap drops and MINE fires.
        assert ap._fsm["state"] == ap.S_MINE, (
            "S_IDLE_AT_BASE giveup must drop the chase cap so the "
            "bot leaves base for a far asteroid instead of "
            "parking indefinitely.")
        assert ap._state.chase_committed is True

    def test_idle_at_base_giveup_does_not_fire_too_early(self, _clock):
        """The bot must NOT leave IDLE_AT_BASE the very first tick
        after entering — there's still a brief grace window so a
        transient scan glitch (e.g. asteroid temporarily out of
        chase range mid-tick) doesn't ricochet into a long round
        trip.  The grace window is short
        (``IDLE_AT_BASE_GIVEUP_S`` = 10 s) but non-zero.  Pins
        that the threshold isn't accidentally set to 0."""
        ap._state.asteroid_blacklist.clear()
        ap._state.chase_committed = False
        far_x = ap.MAX_ASTEROID_CHASE_PX + 500.0
        s = _state(
            asteroids=[{"x": far_x, "y": 0.0, "hp": 100,
                        "type": "Asteroid"}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._state.build_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        # Advance only HALF the IDLE giveup window — bot must stay.
        _clock[0] += ap.IDLE_AT_BASE_GIVEUP_S * 0.5
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE, (
            "Bot must wait the full IDLE_AT_BASE_GIVEUP_S before "
            "committing to a far chase — a 0-second threshold "
            "would ricochet into round trips at every minor "
            "transient.")

    def test_search_giveup_still_uses_search_threshold(self, _clock):
        """Splitting the IDLE giveup into its own (tighter)
        constant must not affect the SEARCH-side path — fresh-game
        bots without a Home Station route through S_SEARCH and
        keep the original 60-second giveup.  Pins that
        ``cur == S_SEARCH`` still uses ``SEARCH_GIVEUP_S``."""
        ap._state.asteroid_blacklist.clear()
        ap._state.chase_committed = False
        far_x = ap.MAX_ASTEROID_CHASE_PX + 500.0
        # No Home Station — section 8 routes to S_SEARCH.
        s = _state(asteroids=[
            {"x": far_x, "y": 0.0, "hp": 100, "type": "Asteroid"}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH
        # Advance exactly IDLE_AT_BASE_GIVEUP_S — SEARCH must NOT
        # commit yet (its threshold is the longer SEARCH_GIVEUP_S).
        _clock[0] += ap.IDLE_AT_BASE_GIVEUP_S + ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH, (
            "S_SEARCH must keep the original 60 s giveup — the "
            "10 s IDLE-side threshold is tighter on purpose.")
        # Advance through the full SEARCH_GIVEUP_S window now.
        _clock[0] += ap.SEARCH_GIVEUP_S + ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE


class TestIdleBlacklistFlush:
    """Section 6 stale-blacklist flush valve.  Without this, silent
    ``_do_mine_nearest`` reachability blacklisting could accumulate
    past the per-entry 60 s TTL via repeated MINE attempts and wedge
    the bot in S_IDLE_AT_BASE indefinitely (caught from 2026-05-09
    telemetry: 14-minute idle stretch with ast=14 / aliens=13 visible
    yet zero state transitions, indicating the targeting helpers were
    returning None every tick).  The flush kicks in only after a
    long dwell so it can't interfere with normal short-cycle
    blacklisting that's intended to last a full 60 s TTL."""

    def test_flush_clears_blacklist_and_fires_mine(self, _clock):
        """After IDLE_BLACKLIST_FLUSH_S in IDLE_AT_BASE with visible
        asteroids that all match a saturated blacklist, the FSM
        must wipe the blacklist + immediately commit to MINE on the
        same tick instead of waiting another full evaluation cycle."""
        ap._state.asteroid_blacklist.clear()
        ap._state.pickup_blacklist.clear()
        ap._state.chase_committed = False
        ap._state.build_done = True
        # Asteroid is INSIDE chase range so once the blacklist is
        # flushed, MINE fires via the in-range branch (not the
        # giveup branch) — keeps the test focused on the flush.
        s = _state(
            asteroids=[{"x": 3700.0, "y": 3200.0, "hp": 100,
                        "type": "Asteroid"}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # Pre-blacklist the asteroid so ``_nearest_asteroid``
        # returns None on the first cascade through section 6.
        ap._blacklist_asteroid(s["asteroids"][0])
        # Enter IDLE_AT_BASE.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        assert len(ap._state.asteroid_blacklist) == 1, (
            "Pre-condition: the asteroid must be blacklisted so "
            "the cascade reaches section 6's else branch.")
        # Advance past the flush gate.
        _clock[0] += ap.IDLE_BLACKLIST_FLUSH_S + ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        # Flush must have wiped the blacklist + transitioned to MINE.
        assert ap._fsm["state"] == ap.S_MINE, (
            "Stale-blacklist flush must immediately commit to MINE "
            "after wiping the blacklist on the same evaluation tick.")
        assert len(ap._state.asteroid_blacklist) == 0, (
            "Blacklist must be empty after the flush so the bot "
            "can re-attempt the previously rejected targets.")

    def test_flush_skipped_when_no_visible_asteroids(self, _clock):
        """The flush valve must not fire when the world has zero
        visible asteroids — there's nothing to mine, so wiping the
        blacklist is pointless and would just churn entries.  Pins
        that the gate's ``visible_asteroids`` check holds."""
        ap._state.asteroid_blacklist.clear()
        ap._state.pickup_blacklist.clear()
        ap._state.chase_committed = False
        ap._state.build_done = True
        # Stale blacklist entry from a prior session — but the
        # world list is empty right now.
        ap._blacklist_asteroid({"x": 4000.0, "y": 4000.0})
        s = _state(
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        _clock[0] += ap.IDLE_BLACKLIST_FLUSH_S + ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        # Still IDLE; blacklist preserved (nothing to flush against).
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        assert len(ap._state.asteroid_blacklist) == 1

    def test_flush_skipped_before_threshold(self, _clock):
        """Flushing too early would defeat the per-entry 60 s TTL
        that normal short-cycle blacklisting depends on.  The flush
        must wait the full IDLE_BLACKLIST_FLUSH_S window before
        firing so legitimate "asteroid behind a wall" blacklisting
        keeps its protective effect."""
        ap._state.asteroid_blacklist.clear()
        ap._state.pickup_blacklist.clear()
        ap._state.chase_committed = False
        ap._state.build_done = True
        s = _state(
            asteroids=[{"x": 3700.0, "y": 3200.0, "hp": 100,
                        "type": "Asteroid"}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._blacklist_asteroid(s["asteroids"][0])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        # Advance only halfway — flush must NOT fire.
        _clock[0] += ap.IDLE_BLACKLIST_FLUSH_S * 0.5
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE, (
            "Flush must wait the full IDLE_BLACKLIST_FLUSH_S — "
            "early firing would defeat normal short-cycle "
            "blacklisting.")
        assert len(ap._state.asteroid_blacklist) == 1


class TestSpiralAngleAdvanceTuning:
    """The spiral's angle-advance rate must stay slow enough that
    the tangential target speed at typical orbit radii is something
    the ship can actually rotate to follow — otherwise the bot
    perpetually re-orients without thrusting (looked like
    "rotating endlessly in place" in the diagnosed session)."""

    def test_spiral_angle_advance_is_modest(self):
        """At a typical search radius of 200 px, the tangential
        speed at 10 Hz must stay under the ship's rotation rate.
        4°/tick = 40°/s — comfortably below typical player ship
        turn rates of 60-90°/s — so the bot always catches up."""
        import math as _math
        # The tuned constant.  ~4° per tick at 10 Hz = ~40°/s.
        deg_per_tick = _math.degrees(ap.SPIRAL_ANGLE_ADVANCE_RAD)
        assert 2.0 < deg_per_tick < 6.0, (
            f"spiral angle advance {deg_per_tick:.1f}°/tick — "
            "outside the 2-6° band the bot can follow")

    def test_spiral_advances_by_tuned_constant(self, _clock,
                                                 monkeypatch):
        """``_do_spiral_search`` must advance the spiral by exactly
        ``SPIRAL_ANGLE_ADVANCE_RAD`` per call so the tuning
        actually takes effect."""
        # No-op _do_goto so we just measure the spiral state.
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
                   brake_on_arrival=True: None)
        ap._spiral_state["anchor"] = (3200.0, 3200.0)
        ap._spiral_state["angle"] = 0.0
        ap._spiral_state["radius"] = 200.0
        s = _state(player={"x": 3200.0, "y": 3200.0,
                            "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_spiral_search(s, s["player"])
        assert abs(ap._spiral_state["angle"]
                   - ap.SPIRAL_ANGLE_ADVANCE_RAD) < 1e-9


class TestBuildDoneShortCircuitIsUnconditional:
    """Regression for the bug where the build_done flip lived
    inside the BUILD branch of _choose_next_state — when GATHER
    or another high-priority state preempted, the BUILD branch
    never ran, and build_done stayed False forever (observed
    in 2026-05-02 telemetry: 155 s session in GATHER, 11
    buildings present, build_done still False at end)."""

    def test_short_circuit_fires_even_when_gather_preempts(
            self, _clock):
        """A pickup is in GATHER range AND a Home Station exists
        in the buildings list.  The FSM picks GATHER, but the
        unconditional short-circuit at the top of
        _choose_next_state must still flip build_done True."""
        ap._state.build_done = False
        s = _state(
            iron_pickups=[
                {"x": 100.0, "y": 0.0,
                 "amount": 5, "item_type": "iron"}],
            buildings=[{"x": 3200.0, "y": 3200.0, "hp": 100,
                        "type": "StationModule",
                        "building_type": "Home Station"}],
        )
        ap._do_auto(s, s["player"])
        # GATHER won the dispatch...
        assert ap._fsm["state"] == ap.S_GATHER
        # ...but the short-circuit still ran.
        assert ap._state.build_done is True

    def test_short_circuit_fires_even_when_engage_preempts(
            self, _clock):
        """Same regression but with ENGAGE preempting."""
        ap._state.build_done = False
        s = _state(
            aliens=[{"x": 400.0, "y": 0.0, "hp": 50}],
            buildings=[{"x": 3200.0, "y": 3200.0, "hp": 100,
                        "type": "StationModule",
                        "building_type": "Home Station"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        assert ap._state.build_done is True

    def test_short_circuit_fires_even_when_regen_preempts(
            self, _clock):
        """Same regression but with REGEN preempting."""
        ap._state.build_done = False
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
            buildings=[{"x": 3200.0, "y": 3200.0, "hp": 100,
                        "type": "StationModule",
                        "building_type": "Home Station"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        assert ap._state.build_done is True


class TestConsumablePhaseDoneShortCircuit:
    """Regression for the bug where a loaded save with consumables
    already crafted (or pre-existing in inventory) leaves the
    queue's ``consumable_phase_started`` flag at False forever, so
    ``_consumable_phase_finished()`` never returns True and the QWI
    build pipeline never fires.  User report 2026-05-09: 'over
    2000 iron, multiple copies of all the modules, 25 of each
    consumable, why has the bot not built a QWI?'"""

    def _fresh_queue(self):
        from bot_autopilot import CraftQueue
        ap._state.queue = CraftQueue()

    def test_short_circuit_latches_phase_done_for_station_inventory(
            self, _clock):
        """When the station inventory has the full 25 + 25 already,
        the short-circuit must flip ``consumable_phase_started`` True
        and zero the remaining-batches counters so the QWI gate can
        proceed."""
        self._fresh_queue()
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items={
                "iron": 2000,
                "repair_pack": 25,
                "shield_recharge": 25,
            },
        )
        ap._do_auto(s, s["player"])
        assert ap._state.queue.consumable_phase_started is True
        assert ap._state.queue.repair_packs_remaining == 0
        assert ap._state.queue.shield_recharges_remaining == 0

    def test_short_circuit_counts_quick_use_slots(self, _clock):
        """Consumables already equipped to the bot's quick-use slots
        also satisfy the threshold — equipped consumables have left
        station inventory but are still on hand."""
        self._fresh_queue()
        s = _state(
            buildings=[_hs_building()],
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._do_auto(s, s["player"])
        assert ap._state.queue.consumable_phase_started is True

    def test_short_circuit_sums_across_locations(self, _clock):
        """Counts station + ship + quick-use slots together so a
        partially-equipped player still hits the threshold."""
        self._fresh_queue()
        s = _state(
            buildings=[_hs_building()],
            inventory_items={"iron": 0, "repair_pack": 10},
            station_inventory_items={"repair_pack": 15,
                                      "shield_recharge": 25},
        )
        ap._do_auto(s, s["player"])
        # 10 (ship) + 15 (station) = 25 repair packs >= 25 needed.
        # 25 (station) shield recharges >= 25 needed.
        assert ap._state.queue.consumable_phase_started is True

    def test_short_circuit_skipped_when_below_threshold(self, _clock):
        """When the user has fewer than the full 25 + 25, the
        short-circuit must NOT fire — the bot still needs to craft
        the rest, so the queue stays armed."""
        self._fresh_queue()
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items={
                "iron": 2000,
                "repair_pack": 24,        # one short
                "shield_recharge": 25,
            },
        )
        ap._do_auto(s, s["player"])
        assert ap._state.queue.consumable_phase_started is False
        assert ap._state.queue.repair_packs_remaining > 0

    def test_short_circuit_does_not_re_run_when_already_started(
            self, _clock):
        """Idempotency: once the phase flag is True, a subsequent
        tick must NOT re-fire the short-circuit (or reset the
        remaining counters mid-craft if the phase is genuinely
        running)."""
        self._fresh_queue()
        # Simulate the phase having already started + 2 batches
        # left for repair packs.
        ap._state.queue.consumable_phase_started = True
        ap._state.queue.repair_packs_remaining = 2
        ap._state.queue.shield_recharges_remaining = 0
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items={
                "iron": 2000,
                "repair_pack": 25,
                "shield_recharge": 25,
            },
        )
        ap._do_auto(s, s["player"])
        # repair_packs_remaining must NOT have been reset to 0.
        assert ap._state.queue.repair_packs_remaining == 2


class TestEquipConsumablesGateSelfHeals:
    """User report (2026-05-11 fifth pass): after the boss is killed
    and the bot picks up dropped consumables, the bot deposits them
    but never re-equips.  Root cause: the EQUIP gate used the
    ``consumables_equipped`` latch, which was set True at session
    start and never re-armed because the dead->alive edge only
    resets it when the prior loadout snapshot includes consumables
    (which on deaths 2-4 of a multi-death cycle, it doesn't).  The
    gate now checks the actual quick-use slot state and self-heals
    whenever a slot is empty AND station inventory has a matching
    consumable."""

    def test_gate_fires_when_quick_use_empty_despite_stale_latch(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The exact pathology from telemetry: latch True (stale),
        quick-use slots empty (post-death), station has consumables.
        Gate must fire S_EQUIP_CONSUMABLES anyway."""
        monkeypatch.setattr(
            ap, "_act_equip_consumables", lambda s, p: None)
        ap._state.consumables_equipped = True  # stale from session start
        ap._state.queue.consumable_phase_started = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.build_done = True  # past starter-base build
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"}],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items={"repair_pack": 5,
                                     "shield_recharge": 5},
        )
        s["quick_use_slots"] = [
            {"item_type": None, "count": 0},  # empty after death
            {"item_type": None, "count": 0},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_EQUIP_CONSUMABLES
        # Latch reset so the action will actually POST, not idle.
        assert ap._state.consumables_equipped is False

    def test_gate_does_not_fire_when_quick_use_already_loaded(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Sanity: when the quick-use slots already have consumables,
        the gate must NOT fire even if station inv has more."""
        ap._state.consumables_equipped = False
        ap._state.queue.consumable_phase_started = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.build_done = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"}],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items={"repair_pack": 5,
                                     "shield_recharge": 5},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5},
            {"item_type": "shield_recharge", "count": 5},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_EQUIP_CONSUMABLES

    def test_gate_fires_when_consumables_only_in_ship_inv(
            self, _clock, _fresh_bot_state, monkeypatch):
        """2026-05-12 eleventh-pass pin: death-drop recovery puts
        the consumables back in SHIP inventory (deposit skips them
        by design).  Station inventory has none.  Quick-use slots
        are empty post-death.  The gate must STILL fire so the bot
        binds the ship-side stock to its quick-use slots.
        """
        monkeypatch.setattr(
            ap, "_act_equip_consumables", lambda s, p: None)
        ap._state.consumables_equipped = True  # stale from session
        ap._state.queue.consumable_phase_started = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.build_done = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"}],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # Station empty (deposit skipped consumables) but ship
            # has them in cargo from death-drop recovery.
            inventory_items={"repair_pack": 1, "shield_recharge": 1},
            station_inventory_items={},
        )
        s["quick_use_slots"] = [
            {"item_type": None, "count": 0},
            {"item_type": None, "count": 0},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_EQUIP_CONSUMABLES
        assert ap._state.consumables_equipped is False

    def test_consumables_in_ship_inv_predicate(self):
        """Direct test of the helper predicate added for the
        eleventh-pass fix."""
        # Empty ship inv.
        s = _state(player={"x": 0.0, "y": 0.0, "heading": 0.0,
                           "shields": 150, "max_shields": 150})
        assert ap._consumables_in_ship_inv(s) is False
        # Repair pack in ship inv.
        s["inventory"]["items"] = {"repair_pack": 1}
        assert ap._consumables_in_ship_inv(s) is True
        # Shield recharge in ship inv.
        s["inventory"]["items"] = {"shield_recharge": 3}
        assert ap._consumables_in_ship_inv(s) is True
        # Zero counts don't count.
        s["inventory"]["items"] = {"repair_pack": 0,
                                   "shield_recharge": 0}
        assert ap._consumables_in_ship_inv(s) is False


class TestSearchExemptFromStuckDetect:
    """The spiral search's brake-coast motion at small radii looks
    indistinguishable from being pinned to the position+rotation
    watchdog (consecutive spiral targets at r=100 are only ~7 px
    apart, well inside the 25 px detect threshold).  Telemetry on
    2026-05-03 showed ~30 false-fire stuck-detect events per session
    in normal SEARCH operation, each firing a 1.5 s escape burst
    that marched the bot eastward instead of sweeping the spiral.

    Fix: ``_do_auto`` skips the stuck-detect block while the FSM
    state is S_SEARCH.  Other states (S_GATHER, S_MINE, S_DEPOSIT,
    S_INSTALL, S_CRAFT) still get the watchdog because their
    targets are real chase points where a real pin is meaningful.
    """

    def test_no_escape_in_search_even_when_pinned(self, _clock):
        """Pin the bot at a position with no asteroids/aliens — FSM
        defaults to S_SEARCH.  Run the full detect window: NO
        escape should fire because S_SEARCH is exempt."""
        for _ in range(20):
            s = _state(player={
                "x": 3200.0, "y": 3200.0, "heading": 0.0,
                "shields": 150, "max_shields": 150,
            })
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._fsm["state"] == ap.S_SEARCH, (
            "test setup invariant — FSM should be in SEARCH "
            "when no asteroids / aliens / pickups are visible")
        assert ap._stuck_state["escape_until"] == 0.0, (
            "S_SEARCH must be exempt from stuck-detect — the "
            "brake-coast spiral motion looks identical to being "
            "pinned to the watchdog")

    def test_escape_still_fires_in_mine(self, _clock):
        """S_MINE is NOT exempt — pin the bot near an asteroid for
        the full window and the watchdog must fire."""
        for _ in range(20):
            s = _state(
                player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                asteroids=[{"x": 3300.0, "y": 3200.0, "hp": 50}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._fsm["state"] == ap.S_MINE
        assert ap._stuck_state["escape_until"] > 0.0, (
            "S_MINE must still trigger stuck-detect")

    def test_escape_still_fires_in_gather(self, _clock):
        """S_GATHER is NOT exempt either — same pinning pattern,
        watchdog must fire."""
        for _ in range(20):
            s = _state(
                player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                iron_pickups=[{"x": 3300.0, "y": 3200.0,
                                "amount": 5, "item_type": "iron"}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._fsm["state"] == ap.S_GATHER
        assert ap._stuck_state["escape_until"] > 0.0


class TestDoGotoBrakeFlag:
    """``_do_goto`` accepts ``brake_on_arrival`` to control whether
    the ``s`` reverse-thrust key engages on arrival.  Spiral search
    passes False so the bot coasts through close-spaced targets
    instead of braking-then-recovering."""

    def _record_keys(self, monkeypatch):
        """Replace the stub ``KeyState.hold`` with a recording dict
        so the test can observe what was set."""
        keys: dict[str, bool] = {}
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda key, down: keys.__setitem__(key, down)))
        return keys

    def test_default_brakes_on_arrival(self, monkeypatch):
        keys = self._record_keys(monkeypatch)
        s = _state(player={"x": 100.0, "y": 100.0, "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_goto(s, s["player"], 100.0, 100.0, stop_radius=200.0)
        assert keys.get("s") is True
        assert keys.get("w") is False

    def test_brake_disabled_no_s_key(self, monkeypatch):
        keys = self._record_keys(monkeypatch)
        s = _state(player={"x": 100.0, "y": 100.0, "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_goto(s, s["player"], 100.0, 100.0, stop_radius=200.0,
                    brake_on_arrival=False)
        # 's' is explicitly NOT engaged — bot coasts.
        assert keys.get("s") is False
        assert keys.get("w") is False

class TestSpiralStopRadiusReduced:
    """The spiral search's stop_radius dropped from 120 to 40 px so
    consecutive close-spaced targets at small radii aren't already
    'arrived' the moment the spiral advances."""

    def test_spiral_uses_small_stop_radius(self, _clock, monkeypatch):
        """Capture the stop_radius `_do_spiral_search` passes to
        `_do_goto` and assert it's ≤ 40 px."""
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["stop_radius"] = stop_radius
            captured["brake_on_arrival"] = brake_on_arrival
        monkeypatch.setattr(ap, "_do_goto", _spy)
        ap._spiral_state["anchor"] = (3200.0, 3200.0)
        ap._spiral_state["radius"] = 200.0
        s = _state(player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_spiral_search(s, s["player"])
        assert captured["stop_radius"] <= 40.0, (
            f"spiral stop_radius is {captured['stop_radius']}; "
            "must stay ≤ 40 px so consecutive spiral targets at "
            "small radii aren't already inside it")
        assert captured["brake_on_arrival"] is False, (
            "spiral search must coast through targets, not brake")


# ── Consumable-phase deadlock fixes (2026-05-03 telemetry) ────────────

class TestConsumablePhaseThreshold:
    """The consumable phase uses CONSUMABLE_PHASE_IRON_THRESHOLD
    (500) as its entry gate, not the module phase's 2000.  Without
    this distinction the bot deadlocked at "install queue empty +
    station iron in [100, 2000)" forever — observed in 2026-05-03
    telemetry, post-install station iron stuck at 1335 with
    consumable_phase_started never flipping True."""

    def test_consumable_threshold_is_500(self):
        assert ap.CONSUMABLE_PHASE_IRON_THRESHOLD == 500

    def test_consumable_threshold_is_below_module_threshold(self):
        """The consumable gate must be much lower than the module
        gate — by the time modules drain, station iron has dropped
        from the buffer and the bot needs the lower gate to keep
        moving."""
        assert (ap.CONSUMABLE_PHASE_IRON_THRESHOLD
                < ap.CRAFT_PHASE_IRON_THRESHOLD)

    def test_consumable_phase_starts_at_lower_threshold(self, _clock):
        """500 station iron is enough to enter the consumable phase
        even though the module-phase 2000 gate would have blocked."""
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install.clear()
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"iron": 500},
        )
        # 500 < CRAFT_PHASE_IRON_THRESHOLD (2000) — old code would
        # have returned None.  New code returns repair_pack.
        assert ap._next_craft_target(s) == "repair_pack"

    def test_consumable_phase_blocked_below_500(self, _clock):
        """Just below the consumable threshold — the bot still
        waits."""
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install.clear()
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"iron": 499},
        )
        assert ap._next_craft_target(s) is None

    def test_consumable_phase_started_latch_persists(self, _clock):
        """Once started, an iron dip below 500 doesn't re-gate —
        per-craft cost (100) is the only check.  This is the
        sticky-latch behaviour."""
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.consumable_phase_started = True
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"iron": 200},  # < 500 threshold
        )
        # Latch is True so the threshold gate is bypassed.
        assert ap._next_craft_target(s) == "repair_pack"

    def test_auto_flip_when_install_empty_and_iron_above_threshold(
            self, _clock):
        """The auto-flip mechanism: when install queue is empty AND
        iron is past the consumable threshold, latch flips to True
        on the next call to _next_craft_target so subsequent dips
        don't re-gate."""
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install.clear()
        assert ap._state.queue.consumable_phase_started is False
        s = _state(
            buildings=[_hs_building(), _crafter_building()],
            station_inventory_items={"iron": 600},
        )
        ap._next_craft_target(s)
        assert ap._state.queue.consumable_phase_started is True


class TestDepositThresholdLowered:
    """DEPOSIT_IRON_THRESHOLD dropped from 200 → 100 on 2026-05-03
    after telemetry showed the bot capping out at 195 ship iron
    between station visits and never reaching the old threshold —
    only ONE deposit fired in a 10-minute session."""

    def test_deposit_threshold_is_100(self):
        assert ap.DEPOSIT_IRON_THRESHOLD == 100

    def test_deposit_fires_at_100_iron(self, _clock):
        """Bot has exactly 100 ship iron — should trigger DEPOSIT."""
        ap._state.last_deposit_at = 0.0  # cooldown ok
        _clock[0] = ap.DEPOSIT_COOLDOWN_S + 1.0
        s = _state(
            iron=100,
            buildings=[_hs_building()],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_DEPOSIT

    def test_no_deposit_at_99_iron(self, _clock):
        """Just below — no deposit yet."""
        ap._state.last_deposit_at = 0.0
        _clock[0] = ap.DEPOSIT_COOLDOWN_S + 1.0
        s = _state(
            iron=99,
            buildings=[_hs_building()],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_DEPOSIT


# ── HUNT mode (no-asteroid alien hunting, 2026-05-03 telemetry) ──────

class TestHuntMode:
    """When no asteroid is visible AND an alien is within
    HUNT_RANGE_PX (3000 px), the bot enters S_HUNT to pursue
    aliens for resources instead of circling in empty space.
    Telemetry from 2026-05-03 showed the bot spending 53% of a
    217-second session in SEARCH with 5 aliens permanently visible
    but ignored because all sat outside the 800 px ENGAGE band."""

    def test_hunt_constant_is_3000(self):
        assert ap.HUNT_RANGE_PX == 3000.0

    def test_hunt_in_all_states(self):
        assert ap.S_HUNT in ap.ALL_STATES

    def test_hunt_fires_when_no_asteroid_alien_in_range(self, _clock):
        """No asteroids, alien at 1500 px (outside ENGAGE 800 px,
        inside HUNT 3000 px) — bot should HUNT."""
        s = _state(
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT

    def test_engage_still_preempts_close_alien(self, _clock):
        """Alien within ENGAGE_ENTER_PX (800 px) — ENGAGE wins
        even when no asteroids."""
        s = _state(
            aliens=[{"x": 500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_mine_preempts_hunt_when_asteroid_available(self, _clock):
        """Asteroid in chase range — MINE wins over HUNT even if
        an alien is also visible."""
        s = _state(
            asteroids=[{"x": 200.0, "y": 0.0, "hp": 100}],
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE

    def test_hunt_does_not_fire_when_alien_too_far(self, _clock):
        """Alien at 3500 px — beyond HUNT_RANGE_PX (3000), so
        SEARCH is the fallback."""
        s = _state(
            aliens=[{"x": 3500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH

    def test_hunt_does_not_fire_when_no_aliens(self, _clock):
        """No asteroids and no aliens — bot falls through to
        SEARCH."""
        s = _state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH

    def test_regen_preempts_hunt(self, _clock):
        """Low shields — REGEN preempts HUNT just like it preempts
        every other state."""
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 20, "max_shields": 150},
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_hunt_uses_act_engage(self, _clock, monkeypatch):
        """S_HUNT dispatches through _act_engage so the bot closes
        + fires the same way it would for a defensive engagement."""
        called: list = []
        real_act_engage = ap._act_engage
        def _spy(state, p):
            called.append("act_engage")
            real_act_engage(state, p)
        monkeypatch.setattr(ap, "_act_engage", _spy)
        s = _state(
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT
        assert called == ["act_engage"]

    def test_hunt_yields_to_engage_when_alien_closes(self, _clock):
        """If the alien drifts closer than ENGAGE_ENTER_PX during a
        HUNT chase, the FSM transitions to ENGAGE on the next tick
        (after MIN_DWELL_S elapses)."""
        # Start with an alien at 1500 — HUNT fires.
        s = _state(aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT
        _clock[0] += ap.MIN_DWELL_S + 0.1
        # Alien now within ENGAGE band — ENGAGE preempts.
        s = _state(aliens=[{"x": 500.0, "y": 0.0, "hp": 50}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE


# ── IDLE_AT_BASE (return-to-base when nothing visible, 2026-05-03) ────

class TestIdleAtBaseDispatch:
    """When no asteroid is visible AND no alien is within
    HUNT_RANGE_PX AND a Home Station exists, the bot routes to
    IDLE_AT_BASE instead of falling through to SEARCH.  Without
    this the bot circled empty space forever — observed in
    2026-05-03 telemetry, 47 seconds in SEARCH oscillating between
    two positions ~2000 px from base."""

    def test_idle_radius_is_600(self):
        """Wide idle radius (600 px) keeps the bot OUTSIDE typical
        station-building clusters (HS + 10 placed buildings spread
        300-500 px around the centre).  At the original 300 px the
        bot oscillated inside the cluster, fired stuck-detect 12
        times in 5 minutes, and burned thrust without progress."""
        assert ap.IDLE_AT_BASE_RADIUS_PX == 600.0

    def test_idle_in_all_states(self):
        assert ap.S_IDLE_AT_BASE in ap.ALL_STATES

    def test_idle_fires_when_nothing_visible_and_hs_exists(self, _clock):
        """No asteroids, no aliens, HS exists — IDLE_AT_BASE fires."""
        s = _state(buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE

    def test_search_fallback_when_no_hs(self, _clock):
        """Early-game (no HS yet): no asteroids + no aliens still
        falls back to SEARCH so the bot roams to find resources
        for the starter base."""
        s = _state()  # no buildings
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH

    def test_mine_preempts_idle(self, _clock):
        """Asteroid in chase range — MINE wins."""
        s = _state(
            buildings=[_hs_building()],
            asteroids=[{"x": 200.0, "y": 0.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE

    def test_hunt_preempts_idle(self, _clock):
        """Alien in HUNT_RANGE_PX — HUNT wins (no asteroid to mine)."""
        s = _state(
            buildings=[_hs_building()],
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT

    def test_engage_preempts_idle(self, _clock):
        """Alien close enough for ENGAGE — ENGAGE wins."""
        s = _state(
            buildings=[_hs_building()],
            aliens=[{"x": 500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_regen_preempts_idle(self, _clock):
        """Low shields — REGEN preempts everything including IDLE."""
        s = _state(
            buildings=[_hs_building()],
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 20, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_idle_yields_to_mine_when_asteroid_appears(self, _clock):
        """Bot is idling at base; an asteroid spawns within chase
        range — FSM transitions to MINE on the next tick."""
        s = _state(buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        _clock[0] += ap.MIN_DWELL_S + 0.1
        # Asteroid appears.
        s = _state(
            buildings=[_hs_building()],
            asteroids=[{"x": 200.0, "y": 0.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE

    def test_idle_yields_to_hunt_when_alien_appears(self, _clock):
        """Bot is idling at base; an alien spawns within
        HUNT_RANGE_PX — FSM transitions to HUNT."""
        s = _state(buildings=[_hs_building()])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        _clock[0] += ap.MIN_DWELL_S + 0.1
        s = _state(
            buildings=[_hs_building()],
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT


class TestIdleAtBaseAction:
    """``_act_idle_at_base`` navigates the bot to within
    ``IDLE_AT_BASE_RADIUS_PX`` of the Home Station, then idles
    (releases all keys)."""

    def _record_keys(self, monkeypatch):
        keys: dict[str, bool] = {}
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda key, down: keys.__setitem__(key, down)))
        return keys

    def test_navigates_to_outer_ring_when_far(self, monkeypatch):
        """Target is the nearest point on the IDLE_AT_BASE_RADIUS_PX
        ring around HS, not HS centre.  Parking on the outer ring
        keeps the bot OUTSIDE the station building cluster — see
        the 2026-05-04 telemetry incident where parking at
        hs_dist=58 trapped the bot inside the cluster during a
        subsequent HUNT."""
        import math as _m
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
            captured["stop_radius"] = stop_radius
        monkeypatch.setattr(ap, "_do_goto", _spy)
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0)],
        )
        ap._act_idle_at_base(s, s["player"])
        # Target is on the line from HS toward player at distance
        # IDLE_AT_BASE_RADIUS_PX from HS — i.e. on the outer ring
        # facing the player.
        d_target_to_hs = _m.hypot(captured["tx"] - 3200.0,
                                  captured["ty"] - 3200.0)
        assert abs(d_target_to_hs - ap.IDLE_AT_BASE_RADIUS_PX) < 0.5
        # And on the player → HS ray, so dx/dy match the unit
        # vector from HS toward player.
        ux = (0.0 - 3200.0) / _m.hypot(3200.0, 3200.0)
        uy = (0.0 - 3200.0) / _m.hypot(3200.0, 3200.0)
        assert abs(captured["tx"] - (3200.0 + ux * ap.IDLE_AT_BASE_RADIUS_PX)) < 0.5
        assert abs(captured["ty"] - (3200.0 + uy * ap.IDLE_AT_BASE_RADIUS_PX)) < 0.5

    def test_idles_when_close_to_base(self, monkeypatch):
        keys = self._record_keys(monkeypatch)
        # Block _do_goto to make sure it isn't called.
        called = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: called.append("_do_goto"))
        s = _state(
            player={"x": 3300.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0)],
        )
        # Player is 100 px from HS — well inside the 300 px idle radius.
        ap._act_idle_at_base(s, s["player"])
        # No navigation call.
        assert called == []
        # Fire is explicitly off; KeyState releases happen via _do_idle.
        assert keys.get("space") is False

    def test_does_not_fire_weapon_while_navigating(self, monkeypatch):
        keys = self._record_keys(monkeypatch)
        # _do_goto stub so the test is hermetic.
        monkeypatch.setattr(ap, "_do_goto",
                            lambda *a, **kw: None)
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0)],
        )
        ap._act_idle_at_base(s, s["player"])
        assert keys.get("space") is False

    def test_no_hs_falls_back_to_idle(self, monkeypatch):
        """Defensive: HS vanished mid-tick — bot just idles, no
        navigation call (FSM re-evaluates next tick)."""
        called = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: called.append("_do_goto"))
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )  # no buildings
        ap._act_idle_at_base(s, s["player"])
        assert called == []


class TestIdleAtBaseExemptFromStuckDetect:
    """S_IDLE_AT_BASE joins S_SEARCH on the stuck-detect exempt list.
    The bot is intentionally parked + drifting near the station; a
    micro-collision or a brief brush against a building's potential
    field shouldn't fire a 1.5 s escape burst that overrides the
    intent.  Real pins still fire in chase states (GATHER, MINE,
    HUNT, DEPOSIT, etc)."""

    def test_no_escape_in_idle_at_base_when_pinned(self, _clock):
        """Pin the bot near the station for the full detect window
        — NO escape should fire because IDLE_AT_BASE is exempt."""
        for _ in range(20):
            s = _state(
                player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                buildings=[_hs_building(x=3200.0, y=3200.0)],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        assert ap._stuck_state["escape_until"] == 0.0, (
            "S_IDLE_AT_BASE must be exempt from stuck-detect — the "
            "bot is intentionally drifting near the station")

    def test_escape_still_fires_in_mine(self, _clock):
        """Sanity: MINE still triggers stuck-detect (the exemption
        is narrow, only covers IDLE_AT_BASE + SEARCH + REGEN)."""
        for _ in range(20):
            s = _state(
                player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                asteroids=[{"x": 3300.0, "y": 3200.0, "hp": 50}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._fsm["state"] == ap.S_MINE
        assert ap._stuck_state["escape_until"] > 0.0


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


class TestIdleAtBaseStopsOutsideBuildingCluster:
    """The idle-target stop_radius must be wide enough that the
    bot stops OUTSIDE the typical station-building cluster.  At
    600 px idle radius * 0.8 = 480 px stop radius, the bot lands
    far enough out that no building's 80 px potential field reaches
    it."""

    def test_stop_radius_clears_building_field(self):
        # The stop radius the action handler passes to _do_goto.
        stop_radius = ap.IDLE_AT_BASE_RADIUS_PX * 0.8
        # Must be greater than typical placed-building distance
        # from HS centre (300-500 px) PLUS the building potential
        # field range (80 px).  If a typical outer building sits
        # 400 px from HS, the bot at 480 px from HS is 80+ px from
        # that building — exactly on the field's outer edge.
        assert stop_radius > 400.0

    def test_idle_zone_excludes_building_field(self):
        """If the bot is exactly at IDLE_AT_BASE_RADIUS_PX from HS,
        and a building sits halfway between HS and the bot, the
        bot is still outside that building's repulsion range."""
        # Building halfway between HS (0,0) and bot at 600 px:
        # building at 300 px, bot at 600 px → 300 px gap, well
        # past the 80 px field range.
        gap = ap.IDLE_AT_BASE_RADIUS_PX - 300.0
        assert gap > ap.BUILDING_REPULSION_RANGE_PX


# ── Fix #1: outer-ring idle target (2026-05-04 cluster-trap fix) ──────

class TestIdleAtBaseOuterRingTarget:
    """``_act_idle_at_base`` must aim for the OUTER RING of the
    idle zone (one radius from HS, on the player→HS ray) — never
    HS centre — so the bot parks in clear space outside the
    station building cluster.  Caught from 2026-05-04 telemetry:
    the bot drifted to hs_dist=58, deep inside an 11-building
    cluster, and 14 stuck_detected events fired during the next
    HUNT cycle without ever reaching an enemy."""

    def test_target_is_one_radius_from_station(self, monkeypatch):
        import math as _m
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0)],
        )
        ap._act_idle_at_base(s, s["player"])
        d = _m.hypot(captured["tx"] - 3200.0, captured["ty"] - 3200.0)
        assert abs(d - ap.IDLE_AT_BASE_RADIUS_PX) < 0.5

    def test_target_is_on_player_to_station_ray(self, monkeypatch):
        """Target should sit on the line from player toward HS,
        not on some arbitrary axis."""
        import math as _m
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        # Player off to the upper-right of HS.
        s = _state(
            player={"x": 5000.0, "y": 5000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0)],
        )
        ap._act_idle_at_base(s, s["player"])
        # Target must be between player and HS, with positive
        # offset from HS in both x and y (player is upper-right).
        assert captured["tx"] > 3200.0
        assert captured["ty"] > 3200.0
        # And on the diagonal: dx == dy because player→HS ray is 45°.
        assert abs((captured["tx"] - 3200.0)
                   - (captured["ty"] - 3200.0)) < 0.5

    def test_no_navigation_when_inside_idle_radius(self, monkeypatch):
        """Already inside the radius → idle, no goto call."""
        called: list = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: called.append("called"))
        # Player 400 px from HS — inside the 600 px radius.
        s = _state(
            player={"x": 3600.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0)],
        )
        ap._act_idle_at_base(s, s["player"])
        assert called == []

    def test_target_never_inside_cluster(self, monkeypatch):
        """Even from 5000 px away, the target distance from HS
        equals exactly IDLE_AT_BASE_RADIUS_PX — never penetrates
        the cluster (which sits within ~500 px of HS centre)."""
        import math as _m
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        s = _state(
            player={"x": -1000.0, "y": -1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0)],
        )
        ap._act_idle_at_base(s, s["player"])
        d = _m.hypot(captured["tx"] - 3200.0, captured["ty"] - 3200.0)
        # Must be at the ring, not closer.  500 px is the typical
        # outer-building distance — target must be beyond.
        assert d >= 500.0


# ── Fix #2: stuck-history clears on FSM transition ────────────────────

class TestStuckHistoryClearedOnTransition:
    """Every state transition must clear ``_stuck_state['history']``
    so the new state's first detect-stuck pass starts with a fresh
    motion window.  Without this, leaving an exempt state
    (S_SEARCH / S_IDLE_AT_BASE) carries forward a window of
    near-zero motion and stuck_detected false-fires immediately
    on the next state's first tick.  2026-05-04 telemetry caught
    this on a 42 s IDLE_AT_BASE → HUNT transition."""

    def test_history_cleared_when_transition_fires(self, _clock):
        # Manually fill history to look like a long pin window.
        ap._stuck_state["history"] = [
            (_clock[0] - 1.5 + i * 0.1, 100.0, 100.0, 0.0)
            for i in range(20)
        ]
        # Force a state change: park the bot, then introduce an
        # in-range alien so the FSM wants HUNT.
        s = _state(
            player={"x": 100.0, "y": 100.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 1500.0, "y": 100.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        # On state transition the history should be wiped.
        assert ap._stuck_state["history"] == []

    def test_history_preserved_when_no_transition(self, _clock):
        """If no transition fires, history grows normally."""
        # Seed an asteroid so the FSM stays in MINE.
        for _ in range(5):
            s = _state(
                player={"x": 0.0, "y": 0.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                asteroids=[{"x": 200.0, "y": 0.0, "hp": 50}],
            )
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        assert ap._fsm["state"] == ap.S_MINE
        # History should have accumulated samples.
        assert len(ap._stuck_state["history"]) > 1


# ── Fix #3: wider hunt range when in IDLE_AT_BASE ─────────────────────

class TestIdleHuntRange:
    """While parked at base (S_IDLE_AT_BASE), the FSM uses
    ``IDLE_HUNT_RANGE_PX`` (wider) to decide HUNT eligibility.
    From the parked-at-base state the bot is healed, supplied,
    and adjacent to the crafter — no reason to be picky about
    distance.  2026-05-04 telemetry: bot sat parked for 95 s
    while aliens roamed at >3000 px because the standard HUNT
    gate never fired."""

    def test_idle_hunt_range_constant_is_wider(self):
        assert ap.IDLE_HUNT_RANGE_PX > ap.HUNT_RANGE_PX

    def test_distant_alien_triggers_hunt_from_idle(self, _clock):
        """Bot in S_IDLE_AT_BASE, alien at 5000 px (well beyond
        normal 3000 HUNT_RANGE_PX but inside 9000 IDLE_HUNT_RANGE_PX)
        — HUNT should fire."""
        ap._fsm["state"] = ap.S_IDLE_AT_BASE
        ap._fsm["entered_at"] = _clock[0] - 10.0  # past dwell
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 5000.0, "y": 0.0, "hp": 50}],
            buildings=[_hs_building(x=0.0, y=0.0)],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT

    def test_distant_alien_does_not_trigger_hunt_from_other_states(self, _clock):
        """Bot in S_SEARCH (not idle), same 5000 px alien — HUNT
        must NOT fire because the wider gate only applies from
        S_IDLE_AT_BASE."""
        ap._fsm["state"] = ap.S_SEARCH
        ap._fsm["entered_at"] = _clock[0] - 10.0
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 5000.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT

    def test_in_range_alien_still_triggers_hunt_from_idle(self, _clock):
        """Sanity: a normal-range alien still triggers HUNT from
        IDLE (the wider gate is a superset)."""
        ap._fsm["state"] = ap.S_IDLE_AT_BASE
        ap._fsm["entered_at"] = _clock[0] - 10.0
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
            buildings=[_hs_building(x=0.0, y=0.0)],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT


# ── Fix #5: symmetric HUNT gate (no IDLE↔HUNT thrash) ─────────────────

class TestHuntGateSymmetric:
    """Once in S_HUNT, the HUNT exit threshold must equal the
    IDLE_HUNT_RANGE_PX entry threshold — otherwise an alien sitting
    in the (HUNT_RANGE_PX, IDLE_HUNT_RANGE_PX) band creates a thrash
    zone where IDLE re-enters HUNT and HUNT falls back to IDLE
    every MIN_DWELL_S.

    2026-05-04-evening telemetry caught this regression: 52
    IDLE↔HUNT transitions in 5.9 minutes (22/23 HUNT→IDLE dwells
    landed in 0.6-0.8s — right at the MIN_DWELL_S floor).
    """

    def test_hunt_persists_when_alien_inside_idle_range(self, _clock):
        """Bot in S_HUNT, alien at 5000 px (between HUNT_RANGE_PX
        3000 and IDLE_HUNT_RANGE_PX 9000) — must STAY in HUNT,
        not fall back to IDLE_AT_BASE.

        Uses an interior world (16k×16k centred on the player) so
        the 2026-05-06 wall-pin escape doesn't suppress the
        symmetric-gate behaviour this test exists to pin — bot and
        alien are both well clear of any edge.
        """
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 10.0
        s = _state(
            player={"x": 8000.0, "y": 8000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 13000.0, "y": 8000.0, "hp": 50}],
            # HS far from bot (>BUILDING_REPULSION_RANGE_PX) so the
            # building-cluster pin escape stays out of the way of
            # the symmetric-gate behaviour this test pins.
            buildings=[_hs_building(x=1000.0, y=1000.0)],
            world_w=16000, world_h=16000,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT

    def test_hunt_exits_when_alien_past_idle_range(self, _clock):
        """Bot in S_HUNT, alien at 9500 px (just past
        IDLE_HUNT_RANGE_PX 9000) — HUNT must exit to IDLE_AT_BASE
        because the alien is now genuinely out of range."""
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 10.0
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 9500.0, "y": 0.0, "hp": 50}],
            buildings=[_hs_building(x=0.0, y=0.0)],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE

    def test_no_idle_hunt_thrash_over_many_ticks(self, _clock):
        """Drive 30 ticks with a stationary alien at 5000 px
        (inside IDLE_HUNT_RANGE_PX, outside HUNT_RANGE_PX) — the
        FSM must NOT bounce.  Before the symmetric-gate fix, this
        loop produced 30 transitions; after the fix it produces 1
        (the initial IDLE → HUNT) and stays in HUNT forever.

        Uses an interior 16k×16k world (see
        ``test_hunt_persists_when_alien_inside_idle_range``) so
        the 2026-05-06 wall-pin escape stays out of the symmetric-
        gate test's way.
        """
        ap._fsm["state"] = ap.S_IDLE_AT_BASE
        ap._fsm["entered_at"] = _clock[0] - 10.0
        transitions: list = []
        for _ in range(30):
            prev = ap._fsm["state"]
            s = _state(
                player={"x": 8000.0, "y": 8000.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                aliens=[{"x": 13000.0, "y": 8000.0, "hp": 50}],
                # HS placed far from bot to keep building-cluster
                # escape out of the symmetric-gate test's way.
                buildings=[_hs_building(x=1000.0, y=1000.0)],
                world_w=16000, world_h=16000,
            )
            ap._do_auto(s, s["player"])
            if ap._fsm["state"] != prev:
                transitions.append((prev, ap._fsm["state"]))
            _clock[0] += 0.1 + ap.MIN_DWELL_S  # past dwell every tick
        assert len(transitions) <= 1, (
            f"FSM bounced {len(transitions)} times — symmetric "
            f"HUNT gate broken: {transitions}")
        assert ap._fsm["state"] == ap.S_HUNT


# ── Fix #4: hunt-stuck giveup ─────────────────────────────────────────

class TestHuntStuckGiveup:
    """If S_HUNT logs HUNT_STUCK_THRESHOLD or more stuck_detected
    events inside HUNT_STUCK_WINDOW_S, ``hunt_giveup_until`` latches
    the FSM out of HUNT for HUNT_GIVEUP_S seconds.  Triggered by
    2026-05-04 telemetry: 14 stuck_detected events in 85 s while
    HUNT kept routing the bot from inside the station cluster."""

    def test_constants_exist(self):
        # Threshold lowered from 3 to 2 in 2026-05-10 after telemetry
        # showed a 52 s HUNT cycle wasting time before the 3rd stuck
        # event cleared the threshold.  Two stuck events inside the
        # 30 s window are already sustained-pin evidence.
        assert ap.HUNT_STUCK_THRESHOLD == 2
        assert ap.HUNT_STUCK_WINDOW_S == 30.0
        assert ap.HUNT_GIVEUP_S == 30.0

    def test_giveup_latches_after_threshold_events(self, _clock):
        """Three stuck events in 10 s → giveup latch fires."""
        ap._fsm["state"] = ap.S_HUNT
        # Each call records one stuck event in the rolling window.
        for i in range(ap.HUNT_STUCK_THRESHOLD):
            now = _clock[0] + i * 0.1
            times = ap._state.hunt_stuck_times
            cutoff = now - ap.HUNT_STUCK_WINDOW_S
            ap._state.hunt_stuck_times = [t for t in times if t >= cutoff]
            ap._state.hunt_stuck_times.append(now)
        # Simulate the threshold trip from inside the handler.
        if len(ap._state.hunt_stuck_times) >= ap.HUNT_STUCK_THRESHOLD:
            ap._state.hunt_giveup_until = _clock[0] + ap.HUNT_GIVEUP_S
        assert ap._state.hunt_giveup_until > _clock[0]

    def test_giveup_suppresses_hunt_transition(self, _clock):
        """While ``hunt_giveup_until > now``, _choose_next_state
        must NOT return S_HUNT even if an alien is in range."""
        ap._state.hunt_giveup_until = _clock[0] + 10.0
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
            buildings=[_hs_building(x=0.0, y=0.0)],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT

    def test_giveup_expires_after_window(self, _clock):
        """After HUNT_GIVEUP_S elapses, HUNT can fire again."""
        ap._state.hunt_giveup_until = _clock[0] + 10.0
        # Advance past the giveup window.
        _clock[0] += 11.0
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 1500.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT

    def test_old_stuck_events_evicted_from_window(self, _clock):
        """Events older than HUNT_STUCK_WINDOW_S must be dropped
        so two old events + one new event don't trip the latch."""
        # Two events from far in the past.
        ap._state.hunt_stuck_times = [_clock[0] - 100.0, _clock[0] - 50.0]
        # Simulate one new event right now: prune + append.
        now = _clock[0]
        cutoff = now - ap.HUNT_STUCK_WINDOW_S
        ap._state.hunt_stuck_times = [
            t for t in ap._state.hunt_stuck_times if t >= cutoff]
        ap._state.hunt_stuck_times.append(now)
        # Old entries should have been evicted.
        assert ap._state.hunt_stuck_times == [now]

    def test_giveup_state_resets_with_fsm_reset(self):
        """``_fsm_reset`` must clear hunt-stuck tracking so a new
        process starts with no carry-over."""
        ap._state.hunt_giveup_until = 9999.0
        ap._state.hunt_stuck_times = [1.0, 2.0, 3.0]
        ap._fsm_reset()
        assert ap._state.hunt_giveup_until == 0.0
        assert ap._state.hunt_stuck_times == []

    def test_single_stuck_event_does_not_trip_giveup(self, _clock):
        """Asymmetry guard: a SINGLE stuck event in S_HUNT must
        not trip the giveup (one-off stucks happen during normal
        kill chains).  Pins HUNT_STUCK_THRESHOLD >= 2."""
        ap._fsm["state"] = ap.S_HUNT
        now = _clock[0]
        ap._state.hunt_stuck_times = [now]
        # Mirror the handler's trip check from bot_autopilot.py:
        if len(ap._state.hunt_stuck_times) >= ap.HUNT_STUCK_THRESHOLD:
            ap._state.hunt_giveup_until = now + ap.HUNT_GIVEUP_S
        # One event must NOT have tripped the latch.
        assert ap._state.hunt_giveup_until == 0.0

    def test_two_stuck_events_trip_giveup_post_2026_05_10(
            self, _clock):
        """Pin the 2026-05-10 threshold lowering: two stuck events
        within HUNT_STUCK_WINDOW_S now trip the giveup (pre-fix
        needed three, which let a 52 s HUNT pin run unchecked)."""
        ap._fsm["state"] = ap.S_HUNT
        now = _clock[0]
        # Two stuck events spaced 9 s apart (matches the telemetry
        # pattern from the 2026-05-10 session: first stuck at +30s,
        # second at +39s).
        ap._state.hunt_stuck_times = [now - 9.0, now]
        # Mirror the handler trip check.
        if len(ap._state.hunt_stuck_times) >= ap.HUNT_STUCK_THRESHOLD:
            ap._state.hunt_giveup_until = now + ap.HUNT_GIVEUP_S
        assert ap._state.hunt_giveup_until == now + ap.HUNT_GIVEUP_S


# ── 2026-05-04 hardening: target-aware repulsion ──────────────────────

class TestTargetAwareRepulsion:
    """``building_repulsion`` now takes an optional ``target`` arg.
    Buildings within ``REPULSION_TARGET_SUPPRESS_PX`` of the target
    are excluded from the sum so the wider 150 px field doesn't
    block deposit / craft / install from docking with their target."""

    def test_no_target_full_repulsion(self):
        s = {"buildings": [{"x": 0.0, "y": 0.0, "hp": 100,
                            "type": "StationModule",
                            "building_type": "Service Module"}]}
        rx, ry = ap._building_repulsion({"x": 75.0, "y": 0.0}, s)
        assert rx > 0.0  # full push east

    def test_target_at_building_suppresses_its_repulsion(self):
        s = {"buildings": [{"x": 0.0, "y": 0.0, "hp": 100,
                            "type": "StationModule",
                            "building_type": "Service Module"}]}
        rx, ry = ap._building_repulsion(
            {"x": 75.0, "y": 0.0}, s, target=(0.0, 0.0))
        assert rx == 0.0 and ry == 0.0

    def test_target_far_from_building_does_not_suppress(self):
        s = {"buildings": [{"x": 0.0, "y": 0.0, "hp": 100,
                            "type": "StationModule",
                            "building_type": "Service Module"}]}
        # Target 1000 px away — building far outside the suppression
        # radius, so its repulsion still applies.
        rx, ry = ap._building_repulsion(
            {"x": 75.0, "y": 0.0}, s, target=(1000.0, 1000.0))
        assert rx > 0.0

    def test_adjacent_neighbor_60px_from_target_is_suppressed(self):
        """2026-05-10 telemetry-anchored regression.

        The starter base places the Repair Module at (60, 60) and
        the Basic Crafter at (120, 60) -- exactly 60 px apart.  When
        the bot navigates to the crafter, the RM (60 px from target)
        is inside the 100 px suppression radius and is excluded from
        repulsion.  Pre-fix (50 px suppress) the RM was just outside
        the gate and its 150 px field pushed the bot back out of the
        200 px craft interact range, producing 3 stuck_detected
        events spaced 60 s apart at (683, 1600) before the bot gave
        up.
        """
        # Simulate the RM at (60, 60) and the bot navigating to the
        # crafter target at (120, 60).  Bot positioned BETWEEN them
        # at (90, 60) -- 30 px from RM, 30 px from crafter.
        crafter_target = (120.0, 60.0)
        repair_module = {"x": 60.0, "y": 60.0, "hp": 100,
                         "type": "StationModule",
                         "building_type": "Repair Module"}
        s = {"buildings": [repair_module]}
        rx, ry = ap._building_repulsion(
            {"x": 90.0, "y": 60.0}, s, target=crafter_target)
        # RM is 60 px from the crafter target (60 < 100 suppress
        # radius), so it must be excluded from the repulsion sum.
        assert rx == 0.0 and ry == 0.0, (
            f"Repair Module at 60 px from the Basic Crafter target "
            f"must be suppressed (got repulsion ({rx}, {ry}))")

    def test_distant_cluster_member_120px_from_target_still_pushes(
            self):
        """The widened 100 px suppression must NOT extend to more
        distant cluster members.  Service Module at 120 px from
        target (the actual SM->Crafter distance in the starter base
        layout) still applies its protective field so transit
        paths around the cluster aren't broken."""
        crafter_target = (120.0, 60.0)
        # Service Module at (0, 60) -- 120 px from crafter, west.
        service_module = {"x": 0.0, "y": 60.0, "hp": 100,
                          "type": "StationModule",
                          "building_type": "Service Module"}
        s = {"buildings": [service_module]}
        # Bot 80 px east of the SM at (80, 60), inside its 150 px field.
        rx, ry = ap._building_repulsion(
            {"x": 80.0, "y": 60.0}, s, target=crafter_target)
        # SM is 120 px from target (> 100 suppress), still pushes east.
        assert rx > 0.0, (
            f"Service Module at 120 px from target must NOT be "
            f"suppressed (got rx={rx})")


# ── 2026-05-04 hardening: per-building-type range multiplier ──────────

class TestPerTypeRepulsionMultiplier:
    """Home Station gets BUILDING_REPULSION_TYPE_MULTIPLIER['Home Station']
    (= 1.5) wider field than ordinary modules.  Reflects the
    larger physical sprite + role as cluster centre."""

    def test_home_station_pushes_at_extended_range(self):
        """A Service Module at 200 px doesn't push (outside 150),
        but a Home Station at the same distance still pushes
        because 200 < 150 * 1.5 = 225."""
        sm = {"x": 0.0, "y": 0.0, "hp": 100,
              "type": "StationModule",
              "building_type": "Service Module"}
        hs = {"x": 0.0, "y": 0.0, "hp": 100,
              "type": "StationModule",
              "building_type": "Home Station"}
        # Service Module: 200 px is outside its 150 range.
        rx, ry = ap._building_repulsion(
            {"x": 200.0, "y": 0.0}, {"buildings": [sm]})
        assert rx == 0.0 and ry == 0.0
        # Home Station: 200 px is inside its 225 px range.
        rx, ry = ap._building_repulsion(
            {"x": 200.0, "y": 0.0}, {"buildings": [hs]})
        assert rx > 0.0

    def test_unknown_type_falls_back_to_default(self):
        """An unrecognised building_type uses the 1.0× default."""
        unk = {"x": 0.0, "y": 0.0, "hp": 100,
               "type": "StationModule",
               "building_type": "Mystery Module"}
        rx, ry = ap._building_repulsion(
            {"x": 200.0, "y": 0.0}, {"buildings": [unk]})
        # 200 > 150 base range — no contribution.
        assert rx == 0.0 and ry == 0.0


# ── 2026-05-04 hardening: cluster aggregate avoidance ─────────────────

class TestClusterCentroidAndRadius:
    def test_no_buildings_returns_none(self):
        assert ap._cluster_centroid_and_radius({"buildings": []}) == (None, None, None)

    def test_below_minimum_count_returns_none(self):
        # 2 buildings — below CLUSTER_MIN_BUILDINGS = 3.
        s = {"buildings": [{"x": 0.0, "y": 0.0},
                           {"x": 100.0, "y": 0.0}]}
        cx, cy, r = ap._cluster_centroid_and_radius(s)
        assert cx is None and cy is None and r is None

    def test_centroid_and_radius_correct(self):
        s = {"buildings": [{"x": 0.0, "y": 0.0},
                           {"x": 100.0, "y": 0.0},
                           {"x": 50.0, "y": 80.0}]}
        cx, cy, r = ap._cluster_centroid_and_radius(s)
        assert abs(cx - 50.0) < 1e-9
        # Centroid y = (0 + 0 + 80) / 3 = 26.667
        assert abs(cy - 80.0/3) < 1e-9
        # Radius = distance to farthest point.  All three points are
        # equidistant from the centroid in this triangle.
        import math as _m
        expected = _m.hypot(50.0, 80.0/3)  # corner-to-centroid
        assert abs(r - expected) < 1e-6


class TestClusterDetourWaypoint:
    """Goto paths that cross the cluster get redirected to a tangent
    waypoint on the cluster boundary."""

    def _cluster_state(self, cx=0.0, cy=0.0, r=200.0):
        """Build a 4-building symmetric cluster around (cx, cy):
        centroid lands exactly at (cx, cy), bounding radius is
        exactly ``r``."""
        return {"buildings": [
            {"x": cx + r, "y": cy, "building_type": "Service Module"},
            {"x": cx - r, "y": cy, "building_type": "Service Module"},
            {"x": cx, "y": cy + r, "building_type": "Home Station"},
            {"x": cx, "y": cy - r, "building_type": "Service Module"},
        ]}

    def test_path_that_misses_cluster_gets_no_waypoint(self):
        s = self._cluster_state(cx=0.0, cy=0.0, r=200.0)
        # Path from (-1000, -1000) to (-1000, 1000) — way off to the
        # west, never approaches the cluster.
        wp = ap._cluster_detour_waypoint(s, -1000.0, -1000.0,
                                         -1000.0, 1000.0)
        assert wp is None

    def test_path_through_cluster_returns_waypoint(self):
        s = self._cluster_state(cx=0.0, cy=0.0, r=200.0)
        # Straight east-west path through the cluster centre.
        wp = ap._cluster_detour_waypoint(s, -2000.0, 0.0, 2000.0, 0.0)
        assert wp is not None
        wx, wy = wp
        # Waypoint must be off the path (perpendicular offset) and
        # on the cluster boundary at distance R = r + margin.
        import math as _m
        d_to_centre = _m.hypot(wx - 0.0, wy - 0.0)
        assert abs(d_to_centre - (200.0 + ap.CLUSTER_DETOUR_MARGIN_PX)) < 0.5

    def test_target_inside_cluster_no_detour(self):
        """When the bot is INTENTIONALLY heading into the cluster
        (deposit / craft / install), no detour is applied."""
        s = self._cluster_state(cx=0.0, cy=0.0, r=200.0)
        # Target inside the cluster (at the centre — clearly the HS).
        wp = ap._cluster_detour_waypoint(s, -2000.0, 0.0, 0.0, 0.0)
        assert wp is None

    def test_short_segment_returns_none(self):
        """Degenerate near-zero-length segment shouldn't crash."""
        s = self._cluster_state(cx=0.0, cy=0.0, r=200.0)
        wp = ap._cluster_detour_waypoint(s, 1000.0, 1000.0,
                                         1000.0, 1000.05)
        assert wp is None

    def test_centroid_behind_player_no_detour(self):
        """Path heading AWAY from the cluster — segment doesn't
        cross it even if extended would."""
        s = self._cluster_state(cx=0.0, cy=0.0, r=200.0)
        # Player on east side of cluster, target further east.
        wp = ap._cluster_detour_waypoint(s, 1000.0, 0.0, 5000.0, 0.0)
        assert wp is None

# ── 2026-05-04 hardening: long-term per-anchor hunt-stuck giveup ──────

class TestHuntAnchorLongTermGiveup:
    """Three stuck events at the same cluster anchor (rounded to
    HUNT_ANCHOR_GRID_PX) inside HUNT_ANCHOR_TTL_S latch the
    long-giveup window even if they're spread across minutes —
    far longer than the acute 10 s window can see."""

    def test_constants_exist(self):
        assert ap.HUNT_ANCHOR_TTL_S == 300.0
        assert ap.HUNT_ANCHOR_GRID_PX == 200.0
        assert ap.HUNT_ANCHOR_MAX_HITS == 3
        assert ap.HUNT_LONG_GIVEUP_S == 120.0

    def test_anchor_hits_track_per_grid_cell(self):
        """Two stucks at the same rounded anchor accumulate into
        one entry."""
        ap._state.hunt_anchor_hits.clear()
        # Simulate the per-anchor recording inline.
        sx, sy = 3101.0, 3816.0
        anchor = (round(sx / ap.HUNT_ANCHOR_GRID_PX) * ap.HUNT_ANCHOR_GRID_PX,
                  round(sy / ap.HUNT_ANCHOR_GRID_PX) * ap.HUNT_ANCHOR_GRID_PX)
        now = 1000.0
        ap._state.hunt_anchor_hits[anchor] = [1, now + ap.HUNT_ANCHOR_TTL_S]
        # Second stuck at slightly different position but same grid cell.
        sx2, sy2 = 3110.0, 3820.0
        anchor2 = (round(sx2 / ap.HUNT_ANCHOR_GRID_PX) * ap.HUNT_ANCHOR_GRID_PX,
                   round(sy2 / ap.HUNT_ANCHOR_GRID_PX) * ap.HUNT_ANCHOR_GRID_PX)
        assert anchor == anchor2  # same grid cell

    def test_max_hits_latches_long_giveup(self, _clock):
        """The full handler logic: 3 hits at the same anchor over
        any time within TTL fires the long giveup."""
        ap._state.hunt_anchor_hits.clear()
        ap._state.hunt_giveup_until = 0.0
        sx, sy = 3101.0, 3816.0
        # Manually drive 3 hits at the same anchor across 200s
        # (longer than the acute 10s window — would NOT trip the
        # short giveup, but should trip the long one).
        for i in range(ap.HUNT_ANCHOR_MAX_HITS):
            now = _clock[0] + i * 60.0  # 60s apart
            anchor = (round(sx / ap.HUNT_ANCHOR_GRID_PX) * ap.HUNT_ANCHOR_GRID_PX,
                      round(sy / ap.HUNT_ANCHOR_GRID_PX) * ap.HUNT_ANCHOR_GRID_PX)
            entry = ap._state.hunt_anchor_hits.get(anchor)
            if entry is None:
                ap._state.hunt_anchor_hits[anchor] = [1, now + ap.HUNT_ANCHOR_TTL_S]
            else:
                entry[0] += 1
                entry[1] = now + ap.HUNT_ANCHOR_TTL_S
                if entry[0] >= ap.HUNT_ANCHOR_MAX_HITS:
                    ap._state.hunt_giveup_until = now + ap.HUNT_LONG_GIVEUP_S
                    del ap._state.hunt_anchor_hits[anchor]
        # Long giveup should be active.
        assert ap._state.hunt_giveup_until > _clock[0] + 60.0

    def test_anchor_hits_cleared_on_fsm_reset(self):
        ap._state.hunt_anchor_hits[(100.0, 100.0)] = [2, 9999.0]
        ap._fsm_reset()
        assert ap._state.hunt_anchor_hits == {}


# ── 2026-05-04 hardening: world-edge-aware navigation ─────────────────

class TestClampToWorld:
    def test_inside_world_unchanged(self):
        zone = {"world_w": 6400, "world_h": 6400}
        cx, cy, clamped = ap._clamp_to_world(3000.0, 3000.0, zone)
        assert cx == 3000.0 and cy == 3000.0 and clamped is False

    def test_past_north_edge_clamped(self):
        zone = {"world_w": 6400, "world_h": 6400}
        cx, cy, clamped = ap._clamp_to_world(3000.0, 6500.0, zone)
        assert cx == 3000.0
        assert cy == 6400.0 - ap.STUCK_WORLD_MARGIN_PX
        assert clamped is True

    def test_past_corner_clamped_both_axes(self):
        zone = {"world_w": 6400, "world_h": 6400}
        cx, cy, clamped = ap._clamp_to_world(7000.0, 7000.0, zone)
        margin = ap.STUCK_WORLD_MARGIN_PX
        assert cx == 6400.0 - margin
        assert cy == 6400.0 - margin
        assert clamped is True


class TestFindClearRingPoint:
    """``find_clear_ring_point`` returns a point on the ring around
    HS that's INSIDE the world rect, preferring the supplied
    direction.  Critical for IDLE_AT_BASE when HS is near a world
    edge — the naive player→HS projection can land outside the
    world."""

    def test_preferred_direction_used_when_inside(self):
        zone = {"world_w": 6400, "world_h": 6400}
        # HS at world centre, plenty of room.  Preferred direction
        # is east (+x); ring point should land directly east of HS.
        tx, ty = ap._find_clear_ring_point(
            3200.0, 3200.0, 600.0, zone, 1.0, 0.0)
        assert abs(tx - 3800.0) < 0.5
        assert abs(ty - 3200.0) < 0.5

    def test_preferred_direction_outside_world_swept(self):
        """HS near upper-right corner; preferred direction is NE
        (+x, +y).  The projected target lands outside the world,
        so the function sweeps to find an interior alternative
        (south or west)."""
        zone = {"world_w": 6400, "world_h": 6400}
        # HS at (6100, 6100), 600 px ring extends to (6700, 6700) —
        # outside the world.  Find an interior point.
        tx, ty = ap._find_clear_ring_point(
            6100.0, 6100.0, 600.0, zone, 1.0, 1.0)
        margin = ap.STUCK_WORLD_MARGIN_PX
        assert margin <= tx <= 6400.0 - margin
        assert margin <= ty <= 6400.0 - margin
        # Distance from HS should still be approximately 600 px
        # (one of the swept rotations landed inside).
        import math as _m
        d = _m.hypot(tx - 6100.0, ty - 6100.0)
        assert abs(d - 600.0) < 0.5

    def test_hs_in_corner_falls_back_to_clamped(self):
        """HS so close to a corner that NO direction on the ring
        lands inside.  Function falls back to the clamped
        preferred direction so the bot still gets close to the
        ring."""
        zone = {"world_w": 600, "world_h": 600}
        tx, ty = ap._find_clear_ring_point(
            500.0, 500.0, 600.0, zone, 1.0, 0.0)
        margin = ap.STUCK_WORLD_MARGIN_PX
        assert margin <= tx <= 600.0 - margin
        assert margin <= ty <= 600.0 - margin


class TestIdleAtBaseEdgeAware:
    """``_act_idle_at_base`` now uses ``find_clear_ring_point`` so
    HS near a world edge produces an interior outer-ring target,
    not one past the boundary.  Regression caught from 2026-05-04
    telemetry: HS in upper-right of 6400×6400 world produced 12
    HUNT stucks at y=5500-6200 (within 200-700 px of the north
    edge)."""

    def test_outer_ring_target_inside_world(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        # HS in upper-right corner; player south of HS so the
        # naive ring projection (player→HS direction = north)
        # would land at y > 6400.
        s = _state(
            player={"x": 6000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=6000.0, y=6000.0)],
            world_w=6400, world_h=6400,
        )
        ap._act_idle_at_base(s, s["player"])
        # Target must be inside the world.
        margin = ap.STUCK_WORLD_MARGIN_PX
        assert margin <= captured["tx"] <= 6400.0 - margin
        assert margin <= captured["ty"] <= 6400.0 - margin


class TestEngageChaseClampedToWorld:
    """ENGAGE / HUNT chase target clamps to inside the world rect
    so a chase toward an alien sitting at the edge doesn't pin
    the bot.  Combat assist still hits through the boundary —
    the bot just stops short."""

    def test_chase_target_clamped_when_alien_outside_margin(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        # Alien at y=6450 — past the world boundary (6400).
        s = _state(
            player={"x": 3200.0, "y": 5000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3200.0, "y": 6450.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        ap._act_engage(s, s["player"])
        margin = ap.STUCK_WORLD_MARGIN_PX
        assert captured["ty"] <= 6400.0 - margin

    def test_chase_target_unchanged_when_alien_inside(self, monkeypatch):
        """Sanity: alien inside world → no clamp."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3700.0, "y": 3200.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        ap._act_engage(s, s["player"])
        assert captured["tx"] == 3700.0
        assert captured["ty"] == 3200.0


class TestNearestAsteroidEdgeFilter:
    """``_nearest_asteroid`` now skips asteroids within
    ``ASTEROID_EDGE_SKIP_PX`` of a world boundary at selection
    time so the bot doesn't ram the wall trying to circle them.
    Falls back to the edge-adjacent candidate when no interior
    asteroid is available."""

    def test_edge_adjacent_skipped_when_interior_available(self):
        # Asteroid just inside north margin (250 px) and one near
        # the world centre.  Interior one should win even though
        # the edge one is closer to the player.
        s = _state(
            player={"x": 3200.0, "y": 6300.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[
                {"x": 3200.0, "y": 6350.0, "hp": 50},  # 50px from north edge
                {"x": 3200.0, "y": 4000.0, "hp": 50},  # interior
            ],
            world_w=6400, world_h=6400,
        )
        nearest, _d = ap._nearest_asteroid(s, 3200.0, 6300.0)
        assert nearest["y"] == 4000.0  # interior wins

    def test_edge_adjacent_used_when_only_option(self):
        """If every asteroid is edge-adjacent, fall back to the
        closest one — bot will probably stuck-detect, blacklist
        it, and try the next."""
        s = _state(
            player={"x": 3200.0, "y": 6300.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[
                {"x": 3200.0, "y": 6350.0, "hp": 50},  # edge
                {"x": 3300.0, "y": 6360.0, "hp": 50},  # edge
            ],
            world_w=6400, world_h=6400,
        )
        nearest, _d = ap._nearest_asteroid(s, 3200.0, 6300.0)
        assert nearest is not None
        # Should be the closer of the two.
        assert nearest["y"] == 6350.0

    def test_no_asteroids_returns_none(self):
        s = _state(asteroids=[], world_w=6400, world_h=6400)
        nearest, _d = ap._nearest_asteroid(s, 3200.0, 3200.0)
        assert nearest is None

    def test_edge_skip_constant_wider_than_world_margin(self):
        """ASTEROID_EDGE_SKIP_PX must exceed STUCK_WORLD_MARGIN_PX
        so the bot has room to circle the asteroid before the
        boundary repulsion field starts pushing back."""
        assert ap.ASTEROID_EDGE_SKIP_PX > ap.STUCK_WORLD_MARGIN_PX


# ── Fix A (2026-05-04): pickup edge filter ────────────────────────────

class TestNearestPickupEdgeFilter:
    """``_nearest_pickup`` skips pickups within ``PICKUP_EDGE_SKIP_PX``
    (200 px) of any world boundary.  Pickups spawn wherever an alien
    dies — including against the wall — and chasing one pins the bot
    against the boundary the same way edge-adjacent asteroids do.
    Mirrors the asteroid filter from PR #25.  Pinned by a real
    GATHER stuck event in the 2026-05-04 telemetry."""

    def test_edge_adjacent_pickup_skipped_when_interior_available(self):
        s = _state(
            player={"x": 3200.0, "y": 6300.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3200.0, "y": 6350.0,         # 50 px from north edge
                 "item_type": "iron"},
                {"x": 3200.0, "y": 4000.0,         # interior
                 "item_type": "iron"},
            ],
            world_w=6400, world_h=6400,
        )
        nearest, _d = ap._nearest_pickup(s, 3200.0, 6300.0)
        assert nearest["y"] == 4000.0  # interior wins

    def test_edge_pickup_used_when_only_option(self):
        """If every pickup is edge-adjacent, fall back to the closest
        — bot will probably stuck-detect, blacklist it, try another."""
        s = _state(
            player={"x": 3200.0, "y": 6300.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3200.0, "y": 6350.0, "item_type": "iron"},
                {"x": 3300.0, "y": 6360.0, "item_type": "iron"},
            ],
            world_w=6400, world_h=6400,
        )
        nearest, _d = ap._nearest_pickup(s, 3200.0, 6300.0)
        assert nearest is not None  # falls back

    def test_blueprints_still_prioritised_over_iron(self):
        """The base ``_bl.nearest_pickup`` sorts blueprints first
        on tie; the edge-filter wrapper must preserve that."""
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[{"x": 3300.0, "y": 3200.0,
                           "item_type": "iron"}],
            blueprint_pickups=[{"x": 3300.0, "y": 3200.0,
                                "item_type": "blueprint"}],
            world_w=6400, world_h=6400,
        )
        nearest, _d = ap._nearest_pickup(s, 3200.0, 3200.0)
        # _bl.nearest_pickup puts blueprints before iron in the
        # candidate list; on tie it picks the first → blueprint.
        assert nearest.get("item_type") == "blueprint"

    def test_no_pickups_returns_none(self):
        s = _state(world_w=6400, world_h=6400)
        nearest, _d = ap._nearest_pickup(s, 3200.0, 3200.0)
        assert nearest is None

    def test_pickup_edge_skip_constant_set(self):
        assert ap.PICKUP_EDGE_SKIP_PX == 200.0
        # Must be at least the world margin so the pickup edge skip
        # zone covers the boundary repulsion danger zone.  Equal is
        # fine; pickups have a despawn timer and are easier to wait
        # out than asteroids (which is why the asteroid skip is
        # wider at 250 px).
        assert ap.PICKUP_EDGE_SKIP_PX >= ap.STUCK_WORLD_MARGIN_PX


# ── Fix (2026-05-17): return-wormhole proximity target filter ─────────

class TestReturnWormholeTargetFilter:
    """``_nearest_pickup`` and ``_nearest_asteroid`` skip targets
    sitting inside the danger zone of a return wormhole (one whose
    ``zone_target`` contains ``MAIN``), but ONLY when the bot is
    currently in a non-MAIN zone.

    Pinned by 2026-05-16 bot_io capture: bot in Nebula collided
    with the central return wormhole at (3200, 3200) and got
    teleported back to MAIN.  The ``wormhole_repulsion`` field
    deflected the path but a strong target attraction past the
    wormhole overcame it.  Filtering at selection guarantees the
    bot never picks a target whose approach crosses the danger
    zone.  PR #129 fixed the consequence (re-arm warp cascade on
    accidental return); this PR fixes the root cause.

    Threshold = ``WORMHOLE_REPULSION_RADIUS_PX +
    WORMHOLE_REPULSION_RANGE_PX`` = 350 px.
    """

    _WH = {"x": 3200.0, "y": 3200.0, "zone_target": "ZoneID.MAIN"}

    def test_pickup_inside_danger_zone_skipped_when_alternative(self):
        """Pickup near return wormhole in Nebula: filter selects
        the safe alternative even if it's farther from the bot."""
        s = _state(
            player={"x": 4000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3300.0, "y": 3200.0, "item_type": "iron"},  # 100 px from wh -- DANGER
                {"x": 5000.0, "y": 3200.0, "item_type": "iron"},  # 1800 px from wh -- SAFE
            ],
            world_w=6400, world_h=6400,
        )
        s["wormholes"] = [self._WH]
        s["zone"]["id"] = "ZoneID.ZONE2"
        nearest, _d = ap._nearest_pickup(s, 4000.0, 3200.0)
        assert nearest["x"] == 5000.0  # safe alternative wins

    def test_asteroid_inside_danger_zone_skipped_when_alternative(self):
        """Symmetric pin for ``_nearest_asteroid``."""
        s = _state(
            player={"x": 4000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[
                {"x": 3300.0, "y": 3200.0, "hp": 50},  # DANGER
                {"x": 5000.0, "y": 3200.0, "hp": 50},  # SAFE
            ],
            world_w=6400, world_h=6400,
        )
        s["wormholes"] = [self._WH]
        s["zone"]["id"] = "ZoneID.ZONE2"
        nearest, _d = ap._nearest_asteroid(s, 4000.0, 3200.0)
        assert nearest["x"] == 5000.0

    def test_pickup_outside_danger_zone_returned_normally(self):
        """Pickup outside the 350 px danger zone: filter is a no-op."""
        s = _state(
            player={"x": 5000.0, "y": 5000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 4500.0, "y": 4500.0, "item_type": "iron"},  # ~1800 px from wh
            ],
            world_w=6400, world_h=6400,
        )
        s["wormholes"] = [self._WH]
        s["zone"]["id"] = "ZoneID.ZONE2"
        nearest, _d = ap._nearest_pickup(s, 5000.0, 5000.0)
        assert nearest["x"] == 4500.0

    def test_filter_disabled_in_main_zone(self):
        """In MAIN the wormholes are OUTBOUND (target=WARP_*) and
        even ones with ``MAIN`` text shouldn't filter -- the bot is
        already where the filter would route it to.  More robustly:
        the helper short-circuits in MAIN regardless of wormhole
        targets, so the existing GATHER/MINE behavior in Zone 1 is
        unaffected by this PR.
        """
        s = _state(
            player={"x": 4000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3300.0, "y": 3200.0, "item_type": "iron"},
            ],
            world_w=6400, world_h=6400,
        )
        s["wormholes"] = [self._WH]
        s["zone"]["id"] = "ZoneID.MAIN"
        nearest, _d = ap._nearest_pickup(s, 4000.0, 3200.0)
        assert nearest is not None
        assert nearest["x"] == 3300.0  # not filtered

    def test_outbound_wormholes_not_filtered(self):
        """Only wormholes whose target contains ``MAIN`` are filtered.
        Nebula's post-boss corner wormholes (target=NEBULA_WARP_*)
        must not trigger the filter so the bot can still mine
        asteroids near them en route to Star Maze.
        """
        s = _state(
            player={"x": 4000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3300.0, "y": 3200.0, "item_type": "iron"},
            ],
            world_w=6400, world_h=6400,
        )
        s["wormholes"] = [
            {"x": 3200.0, "y": 3200.0,
             "zone_target": "ZoneID.NEBULA_WARP_GAS"},
        ]
        s["zone"]["id"] = "ZoneID.ZONE2"
        nearest, _d = ap._nearest_pickup(s, 4000.0, 3200.0)
        assert nearest is not None
        assert nearest["x"] == 3300.0  # NEBULA_WARP_* is outbound

    def test_fallback_when_every_target_inside_danger_zone(self):
        """If every reachable target is inside the danger zone,
        fall back to the closest -- let the blacklist + stuck-
        watchdog handle the consequences rather than starving the
        bot of targets entirely.  Same fallback shape as the
        edge filter.
        """
        s = _state(
            player={"x": 4000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3300.0, "y": 3200.0, "item_type": "iron"},
                {"x": 3400.0, "y": 3200.0, "item_type": "iron"},
            ],
            world_w=6400, world_h=6400,
        )
        s["wormholes"] = [self._WH]
        s["zone"]["id"] = "ZoneID.ZONE2"
        nearest, _d = ap._nearest_pickup(s, 4000.0, 3200.0)
        # Both are in the danger zone; fall back to closest.
        assert nearest is not None

    def test_no_wormholes_no_op(self):
        """Empty wormhole list: filter does not engage even in a
        non-MAIN zone.  Defensive for zones that have no return
        wormholes at all (e.g. warp zones where the bot is in
        traverse).
        """
        s = _state(
            player={"x": 4000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3300.0, "y": 3200.0, "item_type": "iron"},
            ],
            world_w=6400, world_h=6400,
        )
        s["wormholes"] = []
        s["zone"]["id"] = "ZoneID.ZONE2"
        nearest, _d = ap._nearest_pickup(s, 4000.0, 3200.0)
        assert nearest["x"] == 3300.0

    def test_helper_threshold_matches_repulsion_field(self):
        """The proximity threshold defaults to the same combined
        radius the ``wormhole_repulsion`` field uses, so a target
        survives the filter exactly when its approach won't be
        deflected by the field.  Pinned to catch a future drift
        where one constant moves without the other.
        """
        import bot_autopilot_navigation as nav
        import bot_autopilot_targeting as targeting
        s = _state(world_w=6400, world_h=6400)
        s["wormholes"] = [self._WH]
        s["zone"]["id"] = "ZoneID.ZONE2"
        outer = (nav.WORMHOLE_REPULSION_RADIUS_PX
                 + nav.WORMHOLE_REPULSION_RANGE_PX)
        # Just inside outer radius -> filtered.
        assert targeting._target_near_return_wormhole(
            s, 3200.0 + outer - 1.0, 3200.0) is True
        # Just outside -> not filtered.
        assert targeting._target_near_return_wormhole(
            s, 3200.0 + outer + 1.0, 3200.0) is False


# ── Fix (2026-05-17): pin-zone target filter ─────────────────────────

class TestPinZoneTargetFilter:
    """Every ``stuck_detected`` event records the bot's position as
    a pin-zone anchor; target selectors then filter pickups +
    asteroids within ``PIN_ZONE_RADIUS_PX`` of any non-expired
    anchor for ``PIN_ZONE_TTL_S`` seconds.

    Pinned by 2026-05-17 bot_io capture: 8 stuck events in 130 s at
    (8592, 1453) in Nebula, bot frozen for 30+ s at shields=0,
    burned 28 repair packs during the pin.  Generalizes the
    HUNT-anchor giveup pattern to all FSM states by hooking the
    filter at target selection rather than per-state.
    """

    def test_record_pin_zone_anchor_appends_with_ttl(
            self, _clock, _fresh_bot_state):
        _clock[0] = 1000.0
        ap._record_pin_zone_anchor(123.0, 456.0, _clock[0])
        assert len(ap._state.pin_zones) == 1
        cx, cy, exp = ap._state.pin_zones[0]
        assert (cx, cy) == (123.0, 456.0)
        assert exp == 1000.0 + ap.PIN_ZONE_TTL_S

    def test_record_pin_zone_anchor_evicts_expired(
            self, _clock, _fresh_bot_state):
        # Seed with an expired entry, then add a fresh one.
        ap._state.pin_zones[:] = [(1.0, 1.0, 500.0)]  # exp at t=500
        _clock[0] = 1000.0
        ap._record_pin_zone_anchor(2.0, 2.0, _clock[0])
        # Old expired entry evicted; new fresh entry retained.
        assert len(ap._state.pin_zones) == 1
        assert ap._state.pin_zones[0][:2] == (2.0, 2.0)

    def test_record_pin_zone_anchor_caps_at_pin_zone_max(
            self, _clock, _fresh_bot_state):
        _clock[0] = 1000.0
        # Add MAX + 1 unique anchors; list should not exceed cap.
        for i in range(ap.PIN_ZONE_MAX + 5):
            ap._record_pin_zone_anchor(float(i * 1000),
                                       float(i * 1000), _clock[0])
        assert len(ap._state.pin_zones) == ap.PIN_ZONE_MAX

    def test_target_in_pin_zone_inside_radius_returns_true(
            self, _clock, _fresh_bot_state):
        _clock[0] = 1000.0
        ap._state.pin_zones[:] = [
            (5000.0, 5000.0, 1000.0 + ap.PIN_ZONE_TTL_S),
        ]
        # Inside radius (10 px from anchor).
        assert ap._target_in_pin_zone(5010.0, 5000.0) is True
        # On the edge of the radius (slightly inside).
        assert ap._target_in_pin_zone(
            5000.0 + ap.PIN_ZONE_RADIUS_PX - 1.0, 5000.0) is True

    def test_target_in_pin_zone_outside_radius_returns_false(
            self, _clock, _fresh_bot_state):
        _clock[0] = 1000.0
        ap._state.pin_zones[:] = [
            (5000.0, 5000.0, 1000.0 + ap.PIN_ZONE_TTL_S),
        ]
        # Just past the radius -- not filtered.
        assert ap._target_in_pin_zone(
            5000.0 + ap.PIN_ZONE_RADIUS_PX + 1.0, 5000.0) is False

    def test_target_in_pin_zone_ignores_expired_anchors(
            self, _clock, _fresh_bot_state):
        _clock[0] = 5000.0
        # Anchor expired at t=1000, current time t=5000.
        ap._state.pin_zones[:] = [(5000.0, 5000.0, 1000.0)]
        assert ap._target_in_pin_zone(5010.0, 5000.0) is False

    def test_empty_pin_zones_is_no_op(self, _clock, _fresh_bot_state):
        assert ap._state.pin_zones == []
        assert ap._target_in_pin_zone(0.0, 0.0) is False
        assert ap._target_in_pin_zone(9999.0, 9999.0) is False

    def test_nearest_pickup_skips_in_pin_zone(
            self, _clock, _fresh_bot_state):
        """Pickup inside an active pin zone is filtered when an
        alternative exists outside."""
        _clock[0] = 1000.0
        ap._state.pin_zones[:] = [
            (8600.0, 1450.0, 1000.0 + ap.PIN_ZONE_TTL_S),
        ]
        s = _state(
            player={"x": 7000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 8600.0, "y": 1450.0,           # inside pin zone
                 "item_type": "iron"},
                {"x": 5000.0, "y": 3000.0,           # outside
                 "item_type": "iron"},
            ],
            world_w=9600, world_h=9600,
        )
        nearest, _d = ap._nearest_pickup(s, 7000.0, 3000.0)
        assert nearest["x"] == 5000.0  # alternative wins

    def test_nearest_asteroid_skips_in_pin_zone(
            self, _clock, _fresh_bot_state):
        """Symmetric pin for ``_nearest_asteroid``."""
        _clock[0] = 1000.0
        ap._state.pin_zones[:] = [
            (8600.0, 1450.0, 1000.0 + ap.PIN_ZONE_TTL_S),
        ]
        s = _state(
            player={"x": 7000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[
                {"x": 8600.0, "y": 1450.0, "hp": 50},  # pin zone
                {"x": 5000.0, "y": 3000.0, "hp": 50},  # safe
            ],
            world_w=9600, world_h=9600,
        )
        nearest, _d = ap._nearest_asteroid(s, 7000.0, 3000.0)
        assert nearest["x"] == 5000.0

    def test_nearest_pickup_falls_back_when_all_in_pin_zones(
            self, _clock, _fresh_bot_state):
        """If every pickup is inside a pin zone, return the closest
        anyway -- let the blacklist + stuck-watchdog handle the rest
        rather than starving the bot of targets entirely."""
        _clock[0] = 1000.0
        ap._state.pin_zones[:] = [
            (3200.0, 3200.0, 1000.0 + ap.PIN_ZONE_TTL_S),
        ]
        s = _state(
            player={"x": 3500.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3200.0, "y": 3200.0, "item_type": "iron"},
                {"x": 3100.0, "y": 3200.0, "item_type": "iron"},
            ],
            world_w=9600, world_h=9600,
        )
        nearest, _d = ap._nearest_pickup(s, 3500.0, 3200.0)
        assert nearest is not None  # falls back

    def test_no_pin_zones_does_not_disturb_existing_behavior(
            self, _clock, _fresh_bot_state):
        """With ``pin_zones`` empty (a fresh session), the existing
        edge / wormhole filters and selection order are unchanged."""
        assert ap._state.pin_zones == []
        s = _state(
            player={"x": 3500.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 3200.0, "y": 3200.0, "item_type": "iron"},
            ],
            world_w=6400, world_h=6400,
        )
        nearest, _d = ap._nearest_pickup(s, 3500.0, 3200.0)
        assert nearest["x"] == 3200.0


# ── Fix (2026-05-06): HUNT alien edge filter ─────────────────────────

class TestNearestHuntableAlienEdgeFilter:
    """``_nearest_huntable_alien`` skips aliens within
    ``ALIEN_EDGE_SKIP_PX`` (250 px) of any world boundary so HUNT
    doesn't commit to a wall-pinned chase.  Pinned by 2026-05-06
    telemetry: bot stuck at px=48 for 190+ s tracking an alien at
    the left edge while no stuck_detected fired (oscillation
    defeated both the displacement and rotation gates of the
    position-history detector).

    ENGAGE / REGEN deliberately keep using unfiltered ``nearest``
    over ``state['aliens']`` — defensive responses must react to
    any attacker regardless of position."""

    def test_edge_adjacent_alien_skipped_when_interior_available(self):
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[
                {"x": 100.0, "y": 3200.0, "hp": 50},   # 100 px from west edge
                {"x": 4500.0, "y": 3200.0, "hp": 50},  # interior, farther
            ],
            world_w=6400, world_h=6400,
        )
        nearest_alien, _d = ap._nearest_huntable_alien(s, 3200.0, 3200.0)
        assert nearest_alien["x"] == 4500.0  # interior wins despite distance

    def test_edge_alien_used_when_only_option(self):
        """When every visible alien is edge-adjacent the helper falls
        back to the unfiltered nearest so HUNT can still fire — the
        hunt-stuck giveup latch is the backstop in that case."""
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[
                {"x": 100.0, "y": 3200.0, "hp": 50},
                {"x": 200.0, "y": 6350.0, "hp": 50},
            ],
            world_w=6400, world_h=6400,
        )
        nearest_alien, _d = ap._nearest_huntable_alien(s, 3200.0, 3200.0)
        assert nearest_alien is not None
        assert nearest_alien["x"] == 100.0  # closer of the two

    def test_no_aliens_returns_none(self):
        s = _state(aliens=[], world_w=6400, world_h=6400)
        nearest_alien, _d = ap._nearest_huntable_alien(s, 3200.0, 3200.0)
        assert nearest_alien is None

    def test_alien_edge_skip_constant_wider_than_world_margin(self):
        """ALIEN_EDGE_SKIP_PX must exceed STUCK_WORLD_MARGIN_PX so the
        bot has room to circle the alien before boundary repulsion
        engages (mirrors the asteroid + pickup edge skip invariants)."""
        assert ap.ALIEN_EDGE_SKIP_PX > ap.STUCK_WORLD_MARGIN_PX

    def test_engage_still_responds_to_edge_alien(self, _clock):
        """The edge filter is HUNT-only; an alien close enough to
        trigger ENGAGE must still be picked up even if it's right
        against the wall, because ENGAGE/REGEN read ``state['aliens']``
        directly via ``nearest``."""
        s = _state(
            player={"x": 300.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 50.0, "y": 3200.0, "hp": 50}],   # edge-adjacent
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_no_fallback_when_bot_at_edge_and_currently_hunting(self):
        """2026-05-06 follow-up: with the bot itself inside the same
        edge margin as every visible alien AND already in HUNT, the
        helper must return None instead of falling back to nearest.
        Otherwise HUNT re-fires every tick and the bot wall-pins
        (95 s pin observed at px=48 because combat had herded every
        alien against the left wall).  Returning None on the
        re-entry lets the FSM fall through to IDLE_AT_BASE so the
        bot navigates AWAY from the wall and breaks the loop."""
        s = _state(
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[
                {"x": 60.0,  "y": 3200.0, "hp": 50},
                {"x": 80.0,  "y": 3500.0, "hp": 50},
                {"x": 100.0, "y": 3700.0, "hp": 50},
            ],
            world_w=6400, world_h=6400,
        )
        nearest_alien, _d = ap._nearest_huntable_alien(
            s, 48.0, 3200.0, currently_hunting=True)
        assert nearest_alien is None, (
            "Already in HUNT + bot at edge + only edge aliens must "
            "NOT fall back — that's the wall-pin re-commit.")

    def test_fallback_fires_on_initial_hunt_from_edge(self):
        """The wall-pin escape only kicks in on HUNT re-entries
        (``currently_hunting=True``).  An initial HUNT entry —
        even from an edge position — keeps the legacy fallback so
        the bot can react to a one-shot proactive chase before
        adapting via IDLE_AT_BASE on the next tick if needed."""
        s = _state(
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 100.0, "y": 3200.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        nearest_alien, _d = ap._nearest_huntable_alien(
            s, 48.0, 3200.0, currently_hunting=False)
        assert nearest_alien is not None, (
            "Initial HUNT entry (currently_hunting=False) must keep "
            "the fallback so test fixtures with edge-position "
            "players still exercise HUNT.")

    def test_fallback_fires_when_bot_is_interior(self):
        """Bot in open space + only edge aliens visible: fallback
        must fire regardless of currently_hunting because there's
        no wall-pin risk from an interior position."""
        for hunting in (False, True):
            s = _state(
                player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                        "shields": 150, "max_shields": 150},
                aliens=[{"x": 100.0, "y": 3200.0, "hp": 50}],
                world_w=6400, world_h=6400,
            )
            nearest_alien, _d = ap._nearest_huntable_alien(
                s, 3200.0, 3200.0, currently_hunting=hunting)
            assert nearest_alien is not None, (
                f"Interior bot fallback must fire "
                f"(currently_hunting={hunting})")
            assert nearest_alien["x"] == 100.0

    def test_hunt_releases_when_bot_is_pinned_at_edge(self, _clock):
        """End-to-end: bot at wall, currently in HUNT, only edge
        aliens visible — FSM must transition out of HUNT.  Pre-fix
        this scenario committed to HUNT every tick and pinned for
        95 s.  HS exists so the cascade falls to IDLE_AT_BASE; the
        bot then navigates back to clear space and HUNT can re-fire
        legitimately on the next iteration."""
        # Step 1: enter HUNT cleanly from open space so cur becomes
        # S_HUNT.  Use an interior alien so the initial pick is
        # interior (no fallback dependency).
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4000.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building()],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT
        _clock[0] += ap.MIN_DWELL_S + 0.1
        # Step 2: now the bot has chased to the wall and only edge
        # aliens are left.  The fallback must be suppressed and
        # the FSM must transition out of HUNT.
        s = _state(
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[
                {"x": 100.0, "y": 5000.0, "hp": 50},
                {"x": 150.0, "y": 1000.0, "hp": 50},
            ],
            buildings=[_hs_building()],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT, (
            "HUNT must release when bot is wall-pinned and every "
            "visible alien is edge-adjacent.")
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE, (
            "FSM should fall through to IDLE_AT_BASE so the bot "
            "navigates away from the wall.")


# ── Fix (2026-05-06 #4): HUNT pin-escape lockout ──────────────────────

class TestHuntPinEscapeLockout:
    """When the wall-pin escape (PR #36) or cluster-pin guard (PR #37)
    suppresses HUNT, the FSM also pushes ``_state.hunt_giveup_until``
    forward by ``HUNT_PIN_GIVEUP_S`` so the next tick from
    IDLE_AT_BASE can't immediately re-fire HUNT.  Without this, the
    suppression only stops the CURRENT HUNT — IDLE→HUNT runs the
    helper with ``currently_hunting=False``, takes the unfiltered
    fallback path, picks up the same edge alien, and fires HUNT
    again on the very next tick.

    2026-05-06 follow-up #4 telemetry caught the result: 107
    IDLE↔HUNT toggles in 3 minutes, both states pinned to the
    MIN_DWELL_S floor, bot wall-pinned at px=48 for 146 s while
    visibly oscillating.  The lockout converts a 1-per-second
    thrash into 1-per-10-seconds probing — 90 % less visible
    oscillation."""

    def test_wall_pin_escape_sets_lockout(self, _clock):
        """Wall-pin escape fires (cur == S_HUNT, bot at edge, every
        alien edge-adjacent) → ``_state.hunt_giveup_until`` must be
        pushed at least HUNT_PIN_GIVEUP_S into the future."""
        ap._fsm_reset()
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 5.0
        ap._state.hunt_giveup_until = 0.0
        s = _state(
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[
                {"x": 100.0, "y": 5000.0, "hp": 50},
                {"x": 150.0, "y": 1000.0, "hp": 50},
            ],
            buildings=[_hs_building()],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._state.hunt_giveup_until >= (
            _clock[0] + ap.HUNT_PIN_GIVEUP_S - 0.01), (
            "Wall-pin suppression must arm the HUNT_PIN_GIVEUP_S "
            "lockout so IDLE_AT_BASE can't re-fire HUNT immediately.")

    def test_cluster_pin_guard_sets_lockout(self, _clock):
        """Cluster guard fires (cur == S_HUNT, hunt_time past delay,
        bot inside cluster) → lockout must be armed."""
        ap._fsm_reset()
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 10.0  # past delay
        ap._state.hunt_giveup_until = 0.0
        s = _state(
            player={"x": 3220.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._state.hunt_giveup_until >= (
            _clock[0] + ap.HUNT_PIN_GIVEUP_S - 0.01)

    def test_lockout_prevents_idle_to_hunt_re_entry(self, _clock):
        """End-to-end pin for the user-reported oscillation.  After
        the wall-pin escape fires (HUNT → IDLE_AT_BASE), the next
        tick from IDLE_AT_BASE — even with the same edge alien
        visible — must NOT re-fire HUNT until the lockout expires."""
        ap._fsm_reset()
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 5.0
        ap._state.hunt_giveup_until = 0.0
        s = _state(
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[
                {"x": 100.0, "y": 5000.0, "hp": 50},
                {"x": 150.0, "y": 1000.0, "hp": 50},
            ],
            buildings=[_hs_building()],
            world_w=6400, world_h=6400,
        )
        # Tick 1: wall-pin escape fires, FSM → IDLE_AT_BASE.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE
        # Tick 2: same state, past MIN_DWELL_S — pre-fix this would
        # bounce back to HUNT because helper's fallback returns the
        # edge alien.  With lockout, HUNT must stay suppressed.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT, (
            "IDLE_AT_BASE re-fired HUNT immediately — lockout is "
            "not engaging.  This is the user-reported oscillation.")
        # Tick 3: also blocked.
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT

    def test_lockout_expires_after_giveup_window(self, _clock):
        """Once HUNT_PIN_GIVEUP_S elapses the lockout releases and
        HUNT can fire again.  Without expiry the bot would never
        re-attempt the chase even after the alien moved or the bot
        drifted clear of the wall."""
        ap._fsm_reset()
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 5.0
        ap._state.hunt_giveup_until = 0.0
        s_pinned = _state(
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[
                {"x": 100.0, "y": 5000.0, "hp": 50},
                {"x": 150.0, "y": 1000.0, "hp": 50},
            ],
            buildings=[_hs_building()],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s_pinned, s_pinned["player"])
        # Jump past the lockout window with the bot now in clear
        # space and an interior alien visible.
        _clock[0] += ap.HUNT_PIN_GIVEUP_S + 0.5
        s_clear = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building()],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s_clear, s_clear["player"])
        assert ap._fsm["state"] == ap.S_HUNT, (
            "Lockout must expire after HUNT_PIN_GIVEUP_S so the bot "
            "can resume hunting once the pin condition clears.")

    def test_lockout_not_set_when_no_aliens_visible(self, _clock):
        """The lockout's gate (``aliens visible AND hunt_target is
        None``) must not fire when there are simply no aliens — that
        case is benign (no thrash to prevent), and arming an
        unnecessary lockout would suppress legitimate HUNT entries
        once aliens DO appear."""
        ap._fsm_reset()
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 5.0
        ap._state.hunt_giveup_until = 0.0
        s = _state(
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[],
            buildings=[_hs_building()],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._state.hunt_giveup_until == 0.0, (
            "No-aliens case must not arm the lockout — the gate "
            "is conditional on aliens being visible.")


# ── Fix (2026-05-06 #7): wall+cluster trap force-escape ──────────────

class TestWallPinTrapForceEscape:
    """Geometry-aware backstop for the navigation-layer
    position-history stuck detector.  When the bot is in the
    wall+cluster trap geometry (wall-pinned + cluster centroid on
    the inland side) AND has not moved more than
    WALL_PIN_TRAP_PROGRESS_PX over WALL_PIN_TRAP_WINDOW_S, the
    autopilot force-arms ``_stuck_state['escape_until']`` so
    ``compute_escape_target``'s wall-tangent path (PR #42) runs.

    Why this is needed: ``detect_stuck`` has a rotation gate that
    short-circuits "stuck" when the bot rotates >30° over a 1.5 s
    window.  Bots tracking wall-glued aliens defeat that gate even
    while making only ~1 px/s of net translation.  Telemetry from
    2026-05-06 follow-up #7 caught the bot pinned at px=48,
    hsd≈250 for the entire 65 s session (py oscillating 3942–3983)
    with zero stuck_detected events and zero escape activations.
    """

    @staticmethod
    def _trap_state():
        """Standard wall+cluster trap fixture used by these tests:
        bot at west wall, HS inland, alien at low px so the action
        handler tries to drive into the cluster."""
        return _state(
            player={"x": 48.0, "y": 3984.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 30.0, "y": 4500.0, "hp": 50}],
            buildings=[
                {"x": 290.0, "y": 3984.0, "building_type": "Home Station"},
                {"x": 200.0, "y": 3950.0, "building_type": "Service Module"},
                {"x": 380.0, "y": 4020.0, "building_type": "Service Module"},
            ],
            world_w=6400, world_h=6400,
        )

    def test_force_escape_arms_after_window_with_no_movement(
            self, _clock):
        """Trap geometry + bot stationary for >= WALL_PIN_TRAP_WINDOW_S
        must arm escape mode."""
        ap._fsm_reset()
        ap._stuck_state["escape_until"] = 0.0
        s = self._trap_state()
        # Tick 1: trap conditions hold, anchor planted.
        ap._do_auto(s, s["player"])
        assert ap._stuck_state["escape_until"] == 0.0, (
            "Escape must NOT arm on the very first tick — the "
            "anchor needs WALL_PIN_TRAP_WINDOW_S to elapse first.")
        anchor_at = ap._state.wall_pin_anchor_at
        assert anchor_at > 0.0, "Anchor must be set on first trap tick."
        # Advance past the trap window with no bot movement.
        _clock[0] += ap.WALL_PIN_TRAP_WINDOW_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._stuck_state["escape_until"] > 0.0, (
            "Escape must arm once the bot has been in the trap "
            "longer than WALL_PIN_TRAP_WINDOW_S without making "
            "WALL_PIN_TRAP_PROGRESS_PX of progress.")

    def test_force_escape_does_not_arm_within_window(self, _clock):
        """Inside the detection window the detector waits — it
        doesn't fire prematurely on the first tick."""
        ap._fsm_reset()
        ap._stuck_state["escape_until"] = 0.0
        s = self._trap_state()
        ap._do_auto(s, s["player"])
        # Advance only halfway through the window.
        _clock[0] += ap.WALL_PIN_TRAP_WINDOW_S * 0.5
        ap._do_auto(s, s["player"])
        assert ap._stuck_state["escape_until"] == 0.0

    def test_force_escape_does_not_arm_when_bot_makes_progress(
            self, _clock):
        """If the bot moves more than WALL_PIN_TRAP_PROGRESS_PX
        across the window, the detector re-anchors instead of
        arming escape — the bot isn't actually stuck, it's just
        in the trap geometry temporarily while moving through it."""
        ap._fsm_reset()
        ap._stuck_state["escape_until"] = 0.0
        s_before = self._trap_state()
        ap._do_auto(s_before, s_before["player"])
        anchor_at_before = ap._state.wall_pin_anchor_at
        # Advance time + move bot well past the progress threshold
        # (still in trap geometry — same wall + same cluster, just
        # different py).
        _clock[0] += ap.WALL_PIN_TRAP_WINDOW_S + 0.1
        s_after = self._trap_state()
        s_after["player"]["y"] = (
            3984.0 + ap.WALL_PIN_TRAP_PROGRESS_PX + 50.0)
        ap._do_auto(s_after, s_after["player"])
        assert ap._stuck_state["escape_until"] == 0.0, (
            "Bot made > PROGRESS_PX of motion — trap should be "
            "treated as transient, escape NOT armed.")
        # Anchor was reset to the new position (timestamp updated).
        assert ap._state.wall_pin_anchor_at >= anchor_at_before

    def test_force_escape_does_not_arm_outside_trap_geometry(
            self, _clock):
        """Bot interior or wall-pinned without cluster on the
        inland side — detector must not fire."""
        ap._fsm_reset()
        ap._stuck_state["escape_until"] = 0.0
        # Bot in open space, far from any wall — no trap.
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        for _ in range(5):
            _clock[0] += ap.WALL_PIN_TRAP_WINDOW_S + 0.1
            ap._do_auto(s, s["player"])
        assert ap._stuck_state["escape_until"] == 0.0
        assert ap._state.wall_pin_anchor_at == 0.0

    def test_force_escape_resets_anchor_when_trap_clears(
            self, _clock):
        """Bot enters trap, then moves out before the window
        elapses — anchor must reset so a future trap entry restarts
        the timer cleanly."""
        ap._fsm_reset()
        ap._stuck_state["escape_until"] = 0.0
        s_trap = self._trap_state()
        ap._do_auto(s_trap, s_trap["player"])
        assert ap._state.wall_pin_anchor_at > 0.0
        # Bot escapes the trap (now interior).
        _clock[0] += ap.WALL_PIN_TRAP_WINDOW_S * 0.5
        s_clear = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s_clear, s_clear["player"])
        assert ap._state.wall_pin_anchor_at == 0.0


# ── Fix (2026-05-06 #2): HUNT building-cluster pin escape ─────────────

class TestHuntBuildingClusterEscape:
    """Symmetric to the wall-pin escape: when the bot is already in
    S_HUNT and has wandered INSIDE the home-station building
    repulsion field, the FSM must release HUNT instead of re-firing
    every tick.  Caught from 2026-05-06 follow-up #2 telemetry: a
    55 s pin at px≈220 / hsd≈230 inside the cluster while chasing
    an interior alien.  The wall-pin escape doesn't engage there
    because the alien target is interior (not edge-adjacent), so a
    parallel building-cluster guard is needed.

    The check uses ``_ship_clear_of_buildings`` (already used by the
    escape exit condition) to keep the cluster boundary definition
    consistent across the navigation + FSM layers."""

    def _close_building(self, x=3200.0, y=3200.0):
        """A non-Home-Station building inside the cluster radius
        used to stuff the bot inside the building-repulsion field
        without the bot literally overlapping the HS."""
        return {"x": x, "y": y, "hp": 100, "type": "StationModule",
                "building_type": "Service Module"}

    def test_hunt_releases_when_bot_inside_building_cluster(
            self, _clock):
        """Bot already in HUNT, inside the home-station cluster
        (within BUILDING_REPULSION_RANGE_PX of a building) — FSM
        must transition out of HUNT to IDLE_AT_BASE.  Pre-fix this
        scenario looped indefinitely chasing aliens through the
        cluster's repulsion field."""
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 10.0
        # Bot at (3220, 3200) — 20 px from the HS at (3200, 3200),
        # well inside the 150 px building-repulsion range.  Alien
        # at (4500, 3200) — interior, in HUNT_RANGE_PX, so the
        # wall-pin escape would NOT fire here.
        s = _state(
            player={"x": 3220.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT, (
            "HUNT must release when bot is inside the building "
            "cluster — the wall-pin escape doesn't catch this "
            "because the alien is interior.")
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE, (
            "FSM should fall to IDLE_AT_BASE; its 600 px outer-"
            "ring navigation pulls the bot OUT of the cluster.")

    def test_hunt_persists_when_bot_outside_cluster(self, _clock):
        """Inverse: bot already in HUNT, but parked OUTSIDE the
        building cluster — HUNT must continue firing.  Pin escape
        is conditional on cluster-interior position, not just
        currently-hunting state."""
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 10.0
        # Bot at (4000, 3200) — 800 px from the HS, far clear of
        # the 150 px building-repulsion range.
        s = _state(
            player={"x": 4000.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 5500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT, (
            "HUNT must persist when bot is clear of the cluster "
            "even when currently_hunting=True.")

    def test_cluster_guard_does_not_fire_within_delay(self, _clock):
        """2026-05-06 follow-up #3: the cluster guard must wait
        HUNT_CLUSTER_PIN_DELAY_S before activating.  Without the
        delay it tripped on the very first re-eval tick (dwell ~ 1 s)
        and triggered an IDLE↔HUNT thrash whenever IDLE_AT_BASE
        parked the bot inside the cluster perimeter (39 fast
        IDLE↔HUNT pairs in the follow-up telemetry).

        Setup: bot already in HUNT for only 1 s (well under the
        3 s delay), inside the cluster, with an interior alien in
        range.  HUNT must continue firing — the bot needs time to
        thread its way out before the guard is allowed to suppress.
        """
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 1.0  # 1 s in HUNT
        s = _state(
            player={"x": 3220.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT, (
            "Cluster guard fired before HUNT_CLUSTER_PIN_DELAY_S — "
            "this would re-introduce the IDLE↔HUNT thrash from "
            "the 2026-05-06 follow-up #3 telemetry.")

    def test_cluster_guard_fires_after_delay(self, _clock):
        """Same scenario as the previous test but with HUNT held
        for past the delay — guard must now fire.  Together with
        ``test_cluster_guard_does_not_fire_within_delay`` this
        pins both sides of the HUNT_CLUSTER_PIN_DELAY_S boundary."""
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = (_clock[0]
                                 - ap.HUNT_CLUSTER_PIN_DELAY_S
                                 - 0.5)
        s = _state(
            player={"x": 3220.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE

    def test_no_thrash_when_idle_parked_inside_cluster(self, _clock):
        """End-to-end pin for the actual symptom: bot parked at
        IDLE_AT_BASE inside the cluster perimeter, alien appears,
        HUNT fires.  The next several ticks (each past MIN_DWELL_S
        but well under HUNT_CLUSTER_PIN_DELAY_S) must KEEP the FSM
        in HUNT — pre-fix the cluster guard suppressed HUNT on
        every re-eval, producing the IDLE→HUNT→IDLE→HUNT bounce.
        """
        ap._fsm_reset()
        ap._fsm["state"] = ap.S_IDLE_AT_BASE
        ap._fsm["entered_at"] = _clock[0] - 30.0  # parked a while
        s = _state(
            # Bot parked at hsd≈275 px from HS — inside the cluster
            # repulsion range of perimeter buildings.  Mirrors the
            # actual telemetry (bot at hsd=152–275 across the
            # session).
            player={"x": 3475.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT, (
            "Initial HUNT entry from cluster-interior idle parking "
            "must fire.")
        # Next 2 ticks — still under HUNT_CLUSTER_PIN_DELAY_S
        # (3.0 s); HUNT must persist.
        for _ in range(2):
            _clock[0] += ap.MIN_DWELL_S + 0.1
            ap._do_auto(s, s["player"])
            assert ap._fsm["state"] == ap.S_HUNT, (
                "HUNT bounced back to IDLE within the cluster pin "
                "delay window — guard fired too aggressively.")

    def test_initial_hunt_entry_from_inside_cluster_still_fires(
            self, _clock):
        """The cluster guard, like the wall-pin escape, only
        suppresses HUNT *re-entries* (cur == S_HUNT).  An initial
        HUNT trigger from IDLE_AT_BASE — even with the bot inside
        the cluster — must still fire.  Otherwise IDLE_AT_BASE
        would never be able to launch a chase from its own parking
        spot near the station, defeating the IDLE→HUNT cascade
        altogether."""
        ap._fsm["state"] = ap.S_IDLE_AT_BASE
        ap._fsm["entered_at"] = _clock[0] - 10.0
        s = _state(
            player={"x": 3220.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT, (
            "Initial HUNT entry from IDLE_AT_BASE must still fire "
            "even from inside the cluster — cluster guard is a "
            "re-entry-only suppression, mirroring the wall-pin "
            "escape's cur==S_HUNT gate.")

    def test_cluster_guard_does_not_fire_when_bot_at_wall(
            self, _clock):
        """2026-05-06 follow-up #5: with the bot wall-pinned
        (within ALIEN_EDGE_SKIP_PX of any world edge) AND inside
        the cluster repulsion field AND chasing an interior alien,
        the cluster guard must NOT fire.  This scenario is
        geometric reality (cluster is the only path to the alien
        from the wall), not a stuck — the user reported the bot
        sitting idle for 90+ s with 2 enemies on the minimap
        because the guard kept suppressing every 13 s.  The
        wall-pin escape (PR #36) already owns the wall+edge-aliens
        case; the cluster guard now exclusively covers interior
        cluster pins (bot stuck deep in the station, far from any
        wall).
        """
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 10.0  # well past delay
        s = _state(
            # Bot at px=48 — inside ALIEN_EDGE_SKIP_PX (250) of west
            # edge.  HS at (200, 3200), so the bot at hsd≈250 is
            # also within BUILDING_REPULSION_RANGE_PX (150) of HS
            # — both pin conditions hold simultaneously.
            player={"x": 48.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3000.0, "y": 3200.0, "hp": 50}],  # interior
            buildings=[_hs_building(x=200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_HUNT, (
            "Cluster guard must not suppress HUNT when the bot is "
            "wall-pinned — the cluster is on the inboard side and "
            "is the only path to the interior alien.  Suppressing "
            "here was the symptom: 'bot sits idle in base while "
            "enemies are visible on the minimap'.")

    def test_interior_cluster_guard_still_fires_away_from_walls(
            self, _clock):
        """Regression pin for PR #37: the cluster guard's *original*
        symptom — bot stuck DEEP inside the cluster, far from any
        world edge — must still trigger.  The wall exemption only
        opens up the wall-adjacent case; interior cluster pins
        keep the suppression+lockout behaviour from #37/#38/#39.
        """
        ap._fsm["state"] = ap.S_HUNT
        ap._fsm["entered_at"] = _clock[0] - 10.0
        # Bot far from any world edge (interior of 6400×6400),
        # next to the HS so still inside the building repulsion
        # range.  Mirrors the original 55 s pin geometry.
        s = _state(
            player={"x": 3220.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 4500.0, "y": 3200.0, "hp": 50}],
            buildings=[_hs_building(x=3200.0, y=3200.0)],
            world_w=6400, world_h=6400,
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_HUNT, (
            "Interior cluster pin must still suppress HUNT — only "
            "the wall+cluster case is exempted by the wall-exemption."
        )
        assert ap._fsm["state"] == ap.S_IDLE_AT_BASE


# ── Fix B (2026-05-04): cluster-aware repulsion suppression ──────────

class TestClusterAwareRepulsionSuppression:
    """When the goto target is INSIDE the cluster centroid radius,
    ALL buildings in the cluster get excluded from repulsion (not
    just the docking building's tight 50 px radius).  Catches the
    case where a pickup spawns wedged among multiple cluster
    buildings — the bot needs to thread through, but the surrounding
    buildings push back through the narrow tight-suppression gap."""

    def _cluster_state(self, cx=3200.0, cy=3200.0, r=200.0):
        """Symmetric 4-building cluster: centroid at (cx, cy),
        bounding radius r."""
        return {"buildings": [
            {"x": cx + r, "y": cy, "building_type": "Service Module"},
            {"x": cx - r, "y": cy, "building_type": "Service Module"},
            {"x": cx, "y": cy + r, "building_type": "Home Station"},
            {"x": cx, "y": cy - r, "building_type": "Service Module"},
        ]}

    def test_target_inside_cluster_suppresses_all_cluster_buildings(self):
        """Target at the cluster centre.  Bot near one of the cluster
        buildings.  WITHOUT cluster suppression the bot would feel
        the surrounding buildings' push.  WITH it, the field is
        zero — bot can thread through."""
        s = self._cluster_state(cx=3200.0, cy=3200.0, r=200.0)
        # Bot near the east cluster building, target at centre.
        rx, ry = ap._building_repulsion(
            {"x": 3380.0, "y": 3200.0}, s, target=(3200.0, 3200.0))
        assert abs(rx) < 1e-9 and abs(ry) < 1e-9

    def test_target_outside_cluster_no_cluster_suppression(self):
        """Sanity: target far from cluster → cluster suppression
        does NOT activate, normal per-building repulsion fires.

        Note: ``building_repulsion`` returns a vector pointing FROM
        the building TO the ship (i.e. the direction the ship is
        being pushed).  Bot east of building → push east (rx > 0).
        """
        s = self._cluster_state(cx=3200.0, cy=3200.0, r=200.0)
        # Bot 20 px east of east cluster building.
        rx, ry = ap._building_repulsion(
            {"x": 3420.0, "y": 3200.0}, s, target=(5000.0, 5000.0))
        # East building at (3400, 3200), bot 20 px east → push east.
        assert rx > 0.0

    def test_below_cluster_min_buildings_no_suppression(self):
        """If there aren't enough buildings to count as a cluster
        (CLUSTER_MIN_BUILDINGS = 3), the cluster-suppression logic
        skips and only tight target suppression applies."""
        s = {"buildings": [
            {"x": 3400.0, "y": 3200.0,
             "building_type": "Service Module"},
            {"x": 3000.0, "y": 3200.0,
             "building_type": "Service Module"},
        ]}  # only 2 — below threshold
        # Bot near east building; target at (3200, 3200) — between
        # the two buildings.  WITHOUT cluster suppression, only the
        # tight 50 px target-suppression kicks in (excludes neither
        # building since both are >50 px from target).
        rx, ry = ap._building_repulsion(
            {"x": 3380.0, "y": 3200.0}, s, target=(3200.0, 3200.0))
        # West building at (3000, 3200) is 380 px away — outside its
        # 150 px range, no contribution.
        # East building at (3400, 3200) is 20 px away — strong push west.
        assert rx < 0.0  # west push from east building

    def test_target_far_outside_cluster_radius_no_suppression(self):
        """Target outside cluster AND outside the 100 px
        CLUSTER_DETOUR_TARGET_INSIDE_PX margin → no cluster
        suppression."""
        s = self._cluster_state(cx=3200.0, cy=3200.0, r=200.0)
        # Target 500 px from cluster centre — well outside r + 100 = 300.
        # Bot near east cluster building.
        rx, ry = ap._building_repulsion(
            {"x": 3420.0, "y": 3200.0}, s, target=(3700.0, 3200.0))
        # East building NOT suppressed → push from it.
        assert rx > 0.0

# ── 2026-05-04 hardening: MINE/GATHER chase clamped to world ──────────

class TestMineChaseClampedToWorld:
    """``_do_mine_nearest`` clamps the asteroid chase target to
    inside the world rect.  An edge-adjacent asteroid would
    otherwise pull the bot into the boundary repulsion local-minimum
    trap (goto vs repulsion cancellation along the wall-perpendicular
    axis → bot drifts along the wall instead of reaching the
    asteroid → 30+ s of oscillation per asteroid).  Mining Beam range
    is 400 px vs world margin 200 px, so clamping leaves plenty of
    reach to mine the asteroid from inside the safety zone."""

    def test_mining_beam_chase_clamped_when_asteroid_past_margin(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.mining_weapon_pick = "Mining Beam"
        # Asteroid at y=50 — well past the 200 px south margin in
        # a 6400×6400 world.
        s = _state(
            player={"x": 3200.0, "y": 800.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3200.0, "y": 50.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        ap._do_mine_nearest(s, s["player"])
        # Y must be clamped to >= STUCK_WORLD_MARGIN_PX.
        assert captured["ty"] >= ap.STUCK_WORLD_MARGIN_PX

    def test_mining_beam_chase_unchanged_when_asteroid_inside(self, monkeypatch):
        """Sanity: interior asteroid passes through unchanged."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.mining_weapon_pick = "Mining Beam"
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3500.0, "y": 3200.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        ap._do_mine_nearest(s, s["player"])
        assert captured["tx"] == 3500.0
        assert captured["ty"] == 3200.0

    def test_pickaxe_chase_also_clamped(self, monkeypatch):
        """Energy Pickaxe path uses ``_do_hold_distance`` instead
        of ``_do_goto`` — it should also receive the clamped
        target."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_hold_distance",
            lambda state, p, tx, ty, hold_radius, dead_band=10.0:
                captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.mining_weapon_pick = "Energy Pickaxe"
        s = _state(
            player={"x": 3200.0, "y": 800.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3200.0, "y": 50.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        ap._do_mine_nearest(s, s["player"])
        assert captured["ty"] >= ap.STUCK_WORLD_MARGIN_PX

    def test_fire_gate_uses_unclamped_distance(self, monkeypatch):
        """The fire trigger uses the REAL (unclamped) distance to
        the asteroid so weapon range gating remains accurate.
        Pin via the captured ``space`` key."""
        keys: dict = {}
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda key, down: keys.__setitem__(key, down)))
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.mining_weapon_pick = "Mining Beam"
        # Asteroid at y=50, bot at y=300 — 250 px real distance.
        # Inside MINING_RANGE_PX (400) → fire.
        s = _state(
            player={"x": 3200.0, "y": 300.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3200.0, "y": 50.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        ap._do_mine_nearest(s, s["player"])
        assert keys.get("space") is True


class TestMineNoProgressGiveup:
    """``_do_mine_nearest`` watchdog that blacklists the current
    target if ship_iron hasn't increased over MINE_NO_PROGRESS_S.
    Caught from 2026-05-09 telemetry: 12-minute S_MINE wedge with
    ship_iron static at 85, asteroid_blacklist empty throughout —
    every nominal target passed A* but the bot never closed to
    mining range.  This watchdog forces target rotation so the FSM
    can recover instead of orbiting the same unreachable cluster."""

    def _seed_mine_state(self):
        ap._state.asteroid_blacklist.clear()
        ap._state.pickup_blacklist.clear()
        ap._state.chase_committed = False
        ap._state.mine_iron_baseline = 0
        ap._state.mine_progress_check_at = 0.0
        ap._state.mining_weapon_pick = "Mining Beam"

    def test_first_call_seeds_baseline(self, _clock, monkeypatch):
        """The first ``_do_mine_nearest`` call after MINE entry must
        capture the current ship_iron + arm the deadline.  No
        blacklisting yet — the watchdog needs a full window before
        firing."""
        self._seed_mine_state()
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            asteroids=[{"x": 3500.0, "y": 3200.0, "hp": 100}],
            inventory_items={"iron": 50},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=6400, world_h=6400,
        )
        ap._do_mine_nearest(s, s["player"])
        assert ap._state.mine_iron_baseline == 50, (
            "Baseline must equal ship_iron at first action call.")
        assert ap._state.mine_progress_check_at == _clock[0] + ap.MINE_NO_PROGRESS_S
        # No blacklist yet — fresh window.
        assert len(ap._state.asteroid_blacklist) == 0

    def test_no_progress_blacklists_target(self, _clock, monkeypatch):
        """After MINE_NO_PROGRESS_S without ship_iron rising, the
        watchdog must blacklist the current target so the FSM
        re-targets next tick."""
        self._seed_mine_state()
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            asteroids=[{"x": 3500.0, "y": 3200.0, "hp": 100}],
            inventory_items={"iron": 50},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=6400, world_h=6400,
        )
        # Seed.
        ap._do_mine_nearest(s, s["player"])
        assert len(ap._state.asteroid_blacklist) == 0
        # Advance past the deadline; iron unchanged.
        _clock[0] += ap.MINE_NO_PROGRESS_S + 0.1
        ap._do_mine_nearest(s, s["player"])
        assert len(ap._state.asteroid_blacklist) == 1, (
            "Watchdog must blacklist the stalled target so the FSM "
            "rotates to a different asteroid.")
        # Deadline must be re-armed for the next window.
        assert ap._state.mine_progress_check_at >= _clock[0]

    def test_progress_extends_window_no_blacklist(self, _clock,
                                                   monkeypatch):
        """If ship_iron has gone up by the deadline, the bot is
        making progress — update baseline + bump deadline, do NOT
        blacklist."""
        self._seed_mine_state()
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            asteroids=[{"x": 3500.0, "y": 3200.0, "hp": 100}],
            inventory_items={"iron": 50},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=6400, world_h=6400,
        )
        ap._do_mine_nearest(s, s["player"])
        # Iron tick up — bot mined something.
        s["inventory"]["items"]["iron"] = 75
        # Advance past the deadline.
        _clock[0] += ap.MINE_NO_PROGRESS_S + 0.1
        ap._do_mine_nearest(s, s["player"])
        # No blacklist — progress was real.
        assert len(ap._state.asteroid_blacklist) == 0
        # Baseline updated to the new iron value.
        assert ap._state.mine_iron_baseline == 75

    def test_on_enter_clears_deadline(self):
        """``_on_enter(S_MINE)`` must reset the deadline sentinel so
        a fresh MINE entry re-seeds the baseline against current
        ship_iron rather than carrying a stale value across a
        MINE→OTHER→MINE round trip."""
        ap._state.mine_iron_baseline = 999
        ap._state.mine_progress_check_at = 12345.6
        ap._on_enter(ap.S_MINE)
        assert ap._state.mine_progress_check_at == 0.0

    def test_on_enter_pre_boss_mine_also_clears_deadline(self):
        """2026-05-10 telemetry-anchored regression.

        ``_on_enter(S_PRE_BOSS_MINE)`` must reset the watchdog the
        same way ``_on_enter(S_MINE)`` does, because both states
        share the same ``_do_mine_nearest`` action handler and the
        same baseline / deadline pair.  Pre-fix this hook only
        matched S_MINE, so the cycle PRE_BOSS_MINE → DEPOSIT →
        PRE_BOSS_MINE carried a stale baseline from the first
        PRE_BOSS_MINE session into the second one -- by the time
        the 60 s deadline tripped, ship_iron had been deposited to
        0 and the watchdog blacklisted whatever asteroid was
        currently nearest as a false positive.  The captured
        session fired 10 of these in 20 minutes (one every
        ~120 s).
        """
        ap._state.mine_iron_baseline = 999
        ap._state.mine_progress_check_at = 12345.6
        ap._on_enter(ap.S_PRE_BOSS_MINE)
        assert ap._state.mine_progress_check_at == 0.0, (
            "PRE_BOSS_MINE entry must reset the watchdog so the "
            "first action-handler call after the entry re-seeds "
            "baseline against post-deposit ship_iron")

    def test_on_enter_pre_boss_mine_also_rolls_mining_weapon(
            self, monkeypatch):
        """PRE_BOSS_MINE entry must ALSO re-roll the mining-weapon
        dice -- otherwise a stale ``mining_weapon_pick`` from an
        earlier entry decides whether the bot mines with Mining
        Beam or Energy Pickaxe through the entire boss-prep grind.
        The pick is the visible side-effect that S_MINE entry sets;
        pinning it here ensures both states behave identically.
        """
        # Force the dice to deterministically pick the pickaxe.
        monkeypatch.setattr(ap.random, "random",
                            lambda: ap.MINING_PICKAXE_CHANCE - 0.01)
        ap._state.mining_weapon_pick = "Mining Beam"  # stale carry
        ap._on_enter(ap.S_PRE_BOSS_MINE)
        assert ap._state.mining_weapon_pick == "Energy Pickaxe"


class TestGatherChaseClampedToWorld:
    """``_act_gather`` clamps the pickup chase target to the world
    rect.  Same rationale as the asteroid case: an edge-adjacent
    pickup that the bot can't actually reach (because boundary
    repulsion blocks the approach) shouldn't trap the bot in
    oscillation.  Pickup either drifts into reach or expires."""

    def test_pickup_chase_clamped_when_past_margin(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        s = _state(
            player={"x": 3200.0, "y": 800.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[{"x": 3200.0, "y": 50.0,
                           "item_type": "iron"}],
            world_w=6400, world_h=6400,
        )
        # Disable the edge filter for this test by adding a closer
        # interior pickup so _nearest_pickup returns the edge one
        # via fallback.  Actually simpler: mock _nearest_pickup
        # directly to force the edge candidate.
        monkeypatch.setattr(
            ap, "_nearest_pickup",
            lambda *a, **kw: ({"x": 3200.0, "y": 50.0,
                              "item_type": "iron"}, 750.0))
        ap._act_gather(s, s["player"])
        assert captured["ty"] >= ap.STUCK_WORLD_MARGIN_PX

    def test_pickup_chase_unchanged_when_inside(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(
            ap, "_nearest_pickup",
            lambda *a, **kw: ({"x": 3500.0, "y": 3200.0,
                              "item_type": "iron"}, 300.0))
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=6400, world_h=6400,
        )
        ap._act_gather(s, s["player"])
        assert captured["tx"] == 3500.0
        assert captured["ty"] == 3200.0


class TestAttackNearestChaseClampedToWorld:
    """``_do_attack_nearest`` (intent-driven, separate from
    ``_act_engage``) also clamps its chase target to the world rect.
    Mirrors the ENGAGE clamp from PR #25 so direct-attack intents
    posted via the bot API don't pin the bot against an edge alien."""

    def test_attack_chase_clamped_when_alien_past_margin(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 3200.0, "y": 800.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3200.0, "y": 50.0, "hp": 50}],
            world_w=6400, world_h=6400,
        )
        ap._do_attack_nearest(s, s["player"])
        assert captured["ty"] >= ap.STUCK_WORLD_MARGIN_PX


# ── Double Star boss engagement (Choices 2-4) ─────────────────────────────


def _boss(x=5800.0, y=5800.0, hp=2000, max_hp=2000, phase=1,
          charging=False, windup=0.0):
    """Build a /state ``boss`` dict for the FSM tests."""
    return {
        "x": x, "y": y, "hp": hp, "max_hp": max_hp, "phase": phase,
        "charging": charging, "charge_windup": windup,
        "charge_timer": 0.0,
    }


class TestDeathRecovery:
    """2026-05-10 feature: when the player dies, the bot snapshots
    the loadout (modules + consumables) that was on the ship the
    tick before death and the death position.  After respawn, the
    FSM cascade picks S_RECOVER_LOOT until the dropped pickups at
    the death site have been collected (or DEATH_RECOVERY_TIMEOUT_S
    elapses).  Then the existing INSTALL / EQUIP pipelines re-equip
    the recovered loadout."""

    @staticmethod
    def _alive_player(**override):
        d = {"x": 1000.0, "y": 1000.0, "heading": 0.0,
             "shields": 150, "max_shields": 150,
             "hp": 200, "max_hp": 200, "is_dead": False}
        d.update(override)
        return d

    @staticmethod
    def _dead_player(**override):
        d = {"x": 1500.0, "y": 1500.0, "heading": 0.0,
             "shields": 0, "max_shields": 150,
             "hp": 0, "max_hp": 200, "is_dead": True}
        d.update(override)
        return d

    def test_alive_tick_refreshes_loadout_snapshot(
            self, _clock, _fresh_bot_state):
        s = _state(player=self._alive_player(x=1234.0, y=5678.0))
        s["module_slots"] = ["shield_enhancer", "broadside", None]
        s["quick_use_slots"] = [{"item_type": "repair_pack", "count": 5},
                                {"item_type": "shield_recharge", "count": 5}]
        ap._observe_death_edges(s, s["player"], _clock[0])
        assert ap._state.last_alive_pos == (1234.0, 5678.0)
        assert ap._state.last_alive_modules == ["shield_enhancer",
                                                "broadside"]
        assert ap._state.last_alive_consumable_types == [
            "repair_pack", "shield_recharge"]
        assert ap._state.was_dead is False

    def test_alive_to_dead_edge_captures_death_pos_and_loadout(
            self, _clock, _fresh_bot_state):
        # First tick: alive, captures loadout.
        alive = _state(player=self._alive_player(x=2000.0, y=3000.0))
        alive["module_slots"] = ["broadside", "engine_booster"]
        alive["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5}]
        ap._observe_death_edges(alive, alive["player"], _clock[0])
        # Second tick: dead.
        _clock[0] += 0.1
        dead = _state(player=self._dead_player(x=5000.0, y=5000.0))
        # Death-state snapshot wipes module_slots + quick_use_slots
        # to empty; observer must use the snapshot captured at the
        # alive edge.
        dead["module_slots"] = [None, None]
        dead["quick_use_slots"] = []
        ap._observe_death_edges(dead, dead["player"], _clock[0])
        assert ap._state.was_dead is True
        assert ap._state.death_recovery_pos == (2000.0, 3000.0)
        assert ap._state.death_recovery_modules == [
            "broadside", "engine_booster"]
        # Consumables snapshot frozen at the alive->dead edge.
        assert ap._state.death_recovery_consumables == [
            "repair_pack"]
        # Recovery is NOT yet pending -- bot is still dead.
        assert ap._state.death_recovery_pending is False

    def test_dead_to_alive_edge_arms_recovery_and_refills_queue(
            self, _clock, _fresh_bot_state):
        # Stage: prior alive tick captured loadout, dead tick set was_dead.
        ap._state.last_alive_pos = (2000.0, 3000.0)
        ap._state.last_alive_modules = ["broadside", "engine_booster"]
        ap._state.last_alive_consumable_types = [
            "repair_pack", "shield_recharge"]
        ap._state.was_dead = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_modules = ["broadside",
                                            "engine_booster"]
        ap._state.death_recovery_consumables = [
            "repair_pack", "shield_recharge"]
        # Drain the install queue first to mimic an end-of-pipeline
        # bot that died after all modules were already installed.
        ap._state.queue.modules_to_install = []
        ap._state.consumables_equipped = True

        # Bot respawns alive.
        alive = _state(player=self._alive_player(x=3200.0, y=3200.0))
        ap._observe_death_edges(alive, alive["player"], _clock[0])

        assert ap._state.was_dead is False
        assert ap._state.death_recovery_pending is True
        # Lost modules re-queued for the install pipeline.
        assert ap._state.queue.modules_to_install == [
            "broadside", "engine_booster"]
        # Equip latch reset so S_EQUIP_CONSUMABLES re-fires once
        # the recovered consumables reach station inventory.
        assert ap._state.consumables_equipped is False

    def test_fsm_cascade_picks_recover_loot_when_pending(
            self, _clock, _fresh_bot_state, monkeypatch):
        """When death_recovery_pending is True AND pickups remain
        near the death site, the FSM cascade returns S_RECOVER_LOOT.
        """
        monkeypatch.setattr(ap, "_act_recover_loot", lambda s, p: None)
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(player=self._alive_player(x=2050.0, y=3050.0))
        # Pickup at the death site -- recovery must still be pending.
        s["iron_pickups"] = [
            {"x": 2000.0, "y": 3000.0, "amount": 10,
             "item_type": "iron"}]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_RECOVER_LOOT

    def test_recovery_clears_when_no_pickups_remain(
            self, _clock, _fresh_bot_state):
        """``_maybe_clear_death_recovery`` flips the pending latch
        False once every pickup near the death site is gone."""
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(player=self._alive_player(x=3500.0, y=3500.0))
        # No pickups visible anywhere.
        s["iron_pickups"] = []
        s["blueprint_pickups"] = []
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is False

    def test_recovery_clears_after_timeout(
            self, _clock, _fresh_bot_state):
        """Hard timeout: if the bot can't reach the death site (e.g.
        died inside an inaccessible cluster), pending clears after
        ``DEATH_RECOVERY_TIMEOUT_S`` so the FSM doesn't lock."""
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(player=self._alive_player(x=3500.0, y=3500.0))
        # Pickup STILL there -- the only thing that ends recovery
        # in this test is the timeout.
        s["iron_pickups"] = [
            {"x": 2000.0, "y": 3000.0, "amount": 10,
             "item_type": "iron"}]
        # Advance past the timeout.
        _clock[0] += ap.DEATH_RECOVERY_TIMEOUT_S + 1.0
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is False

    def test_no_recovery_when_loadout_was_empty(
            self, _clock, _fresh_bot_state):
        """Sanity: a death with empty modules + empty quick-use
        slots doesn't arm recovery (nothing to collect)."""
        ap._state.was_dead = True
        ap._state.death_recovery_modules = []  # no modules to recover
        ap._state.death_recovery_consumables = []
        alive = _state(player=self._alive_player())
        ap._observe_death_edges(alive, alive["player"], _clock[0])
        assert ap._state.death_recovery_pending is False

    def test_recovery_preempts_engage_boss(
            self, _clock, _fresh_bot_state, monkeypatch):
        """User spec (2026-05-11): "during the boss fight, bot does
        not pick up dropped modules and consumables when it is killed.
        it should pick those up when it respawns before it goes back
        to fight the boss."  death_recovery_pending must outrank a
        live boss in ``_choose_next_state`` so the bot visits the
        death site before re-engaging.
        """
        monkeypatch.setattr(ap, "_act_recover_loot", lambda s, p: None)
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(
            player={"x": 2050.0, "y": 3050.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # HS present + boss far from death_pos -- the
            # 2026-05-14 recover_loot gate only suppresses when
            # (boss near death_pos) OR (no HS).  Neither here, so
            # the original "recover preempts engage_boss" intent
            # still holds.
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Both a boss AND a pending loot recovery on the floor.
        s["boss"] = _boss()
        s["iron_pickups"] = [
            {"x": 2000.0, "y": 3000.0, "amount": 10,
             "item_type": "iron"}]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_RECOVER_LOOT

    def test_post_recovery_deposit_preempts_engage_boss(
            self, _clock, _fresh_bot_state, monkeypatch):
        """User-spec follow-up (2026-05-11): after S_RECOVER_LOOT
        vacuums up dropped modules, the bot has them in SHIP cargo
        but the install queue is still non-empty.  Without this
        priority bump, ENGAGE_BOSS at 1.5 wins and the bot fights
        without modules forever.  Telemetry caught 4 modules
        (ship_mods=4) sitting in cargo for 50 s of S_ENGAGE_BOSS
        after a recovery timeout."""
        monkeypatch.setattr(ap, "_act_deposit", lambda s, p: None)
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        # Boss alive, modules in cargo from a recent loot pickup.
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
            inventory_items={"mod_broadside": 1, "mod_armor_plate": 1},
        )
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        # Priority 1.45 must win over 1.5 ENGAGE_BOSS.
        assert ap._fsm["state"] == ap.S_DEPOSIT

    def test_post_recovery_install_preempts_engage_boss(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Step 2 of the post-recovery pipeline: after deposit,
        modules are in station inventory and the install queue
        head matches.  S_INSTALL must beat ENGAGE_BOSS."""
        monkeypatch.setattr(ap, "_act_install", lambda s, p: None)
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        monkeypatch.setattr(
            ap, "_find_basic_crafter",
            lambda state, idle_only=False: {"x": 4000.0, "y": 4000.0})
        ap._state.queue.modules_to_install = ["broadside"]
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
            station_inventory_items={"mod_broadside": 1},
            # No mod_<key> in ship cargo -- past the deposit stage.
        )
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_INSTALL


class TestBossEngageTelemetry:
    """2026-05-10 feature: emit boss_engage_start / boss_engage_end
    telemetry events at the FSM transition into/out of S_ENGAGE_BOSS
    so post-hoc analysis can measure boss-fight dwell + HP/shield
    deltas + outcome (boss_killed / player_died / disengaged)."""

    def test_helper_records_engage_start_state(
            self, _clock, _fresh_bot_state):
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 120, "max_shields": 150,
                    "hp": 180, "max_hp": 200, "is_dead": False})
        s["boss"] = _boss(hp=2500, max_hp=3000, phase=2)
        ap._maybe_log_boss_engage_edges(
            s, s["player"], _clock[0],
            prev=ap.S_MINE, cur=ap.S_ENGAGE_BOSS)
        assert ap._state.boss_engage_started_at == _clock[0]
        assert ap._state.boss_engage_start_hp == 180
        assert ap._state.boss_engage_start_shields == 120
        assert ap._state.boss_engage_start_boss_hp == 2500

    def test_helper_records_engage_end_boss_killed_outcome(
            self, _clock, _fresh_bot_state):
        ap._state.boss_engage_started_at = _clock[0] - 12.5
        ap._state.boss_engage_start_hp = 200
        ap._state.boss_engage_start_shields = 150
        ap._state.boss_engage_start_boss_hp = 3000
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 90, "max_shields": 150,
                    "hp": 150, "max_hp": 200, "is_dead": False})
        # Boss dead -> outcome = boss_killed.
        s["boss"] = None
        # No exception, function runs cleanly.
        ap._maybe_log_boss_engage_edges(
            s, s["player"], _clock[0],
            prev=ap.S_ENGAGE_BOSS, cur=ap.S_IDLE_AT_BASE)

    def test_helper_no_op_when_neither_edge(
            self, _clock, _fresh_bot_state):
        """No transition involving S_ENGAGE_BOSS -- helper must
        leave boss_engage_started_at unchanged (no false event)."""
        ap._state.boss_engage_started_at = 9999.0
        s = _state(player={"x": 1.0, "y": 1.0, "heading": 0.0,
                           "shields": 150, "max_shields": 150,
                           "hp": 200, "max_hp": 200,
                           "is_dead": False})
        ap._maybe_log_boss_engage_edges(
            s, s["player"], _clock[0],
            prev=ap.S_MINE, cur=ap.S_GATHER)
        assert ap._state.boss_engage_started_at == 9999.0


class TestBossEngagementStateRouting:
    """Boss alive => FSM enters S_ENGAGE_BOSS regardless of small
    aliens or other priorities (REGEN still preempts)."""

    def test_boss_routes_to_engage_boss_state(self, _clock, monkeypatch):
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # Home Station present -- engage_boss only fires when HS
            # exists (seventeenth-pass no-HS suppression).
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE_BOSS

    def test_boss_preempts_small_alien_engage(self, _clock, monkeypatch):
        """A close small alien (within 800 px) would normally trigger
        S_ENGAGE.  Boss routing must override it."""
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3300.0, "y": 3200.0, "hp": 50}],
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE_BOSS

    def test_regen_still_preempts_boss(self, _clock, monkeypatch):
        """Shield collapse routes to S_REGEN even with boss alive,
        unless the threat-near + not-recovering escape valve fires."""
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},  # 20 % < 40 %
        )
        # Boss far enough away that the entry-side mirror doesn't
        # fire (boss > ENGAGE_ENTER_PX).
        s["boss"] = _boss(x=5800.0, y=5800.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_boss_state_bypasses_min_dwell(self, _clock, monkeypatch):
        """Boss appearing mid-MINE must route to S_ENGAGE_BOSS even
        before MIN_DWELL_S elapses — defensive interrupt, like
        ENGAGE / REGEN."""
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3300.0, "y": 3200.0, "hp": 100}],
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
        # Boss appears next tick — barely 0.05 s later, well below
        # MIN_DWELL_S.
        _clock[0] += 0.05
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE_BOSS


class TestBossEngageSuppressedWhenNoHomeStation:
    """2026-05-13 seventeenth telemetry pass: after the boss
    destroyed the home station mid-fight, the bot kept routing
    to ``S_ENGAGE_BOSS`` and respawning at world center (3200,
    3200) -- the no-HS default respawn -- where the boss sat
    on the spawn point and killed it 6 times in 7 seconds.

    Fix: when ``has_home_station == False`` AND a boss is alive,
    suppress the engage_boss priority and let the cascade
    continue to ENGAGE / GATHER / MINE.  Bot stays productive
    while turrets + missile array finish the boss (the 15 other
    buildings in the cluster typically survive HS destruction).
    """

    def test_boss_alive_without_hs_does_not_route_to_engage_boss(
            self, _clock, monkeypatch):
        """Direct pin of the suppression: boss alive, no HS in
        buildings list => engage_boss is NOT the chosen state."""
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # No Home Station in the buildings list.
        )
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE_BOSS, (
            "engage_boss must be suppressed when no home station "
            "exists -- bot has no umbrella, can't survive a "
            "direct boss engagement")

    def test_boss_alive_with_hs_still_routes_to_engage_boss(
            self, _clock, monkeypatch):
        """Sanity: the suppression only triggers when HS is
        ABSENT.  With HS present, engage_boss fires as before."""
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE_BOSS

    def test_no_hs_no_boss_cascade_unchanged(
            self, _clock, monkeypatch):
        """No HS, no boss -- regular cascade runs (e.g., to
        MINE if asteroid in range).  The suppression is gated
        on ``boss is not None``, not just ``hs is None``."""
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3300.0, "y": 3200.0, "hp": 100}],
        )
        # No boss, no HS.
        ap._do_auto(s, s["player"])
        # Either MINE (asteroid in range) or some other normal
        # state -- as long as it's not engage_boss (boss doesn't
        # exist) or a non-action state.
        assert ap._fsm["state"] in (ap.S_MINE,)


class TestEngageSuppressedOnBossWhenNoHomeStation:
    """2026-05-14 eighteenth telemetry pass: PR #117 suppressed
    ``S_ENGAGE_BOSS`` when no HS exists, but the regular
    ``S_ENGAGE`` priority still picked the boss up via the threat
    injection (the REGEN escape-valve injects the boss into the
    threat slot when within ENGAGE_ENTER_PX so REGEN can bail).
    Result: 5 back-to-back ENGAGE deaths at sh=0-2 in 12 s.

    Fix: when threat-is-boss AND no HS, suppress S_ENGAGE too --
    the cascade falls through to GATHER / MINE / SEARCH which
    navigate by resource, not boss aggro.
    """

    def test_boss_as_threat_with_no_hs_does_not_route_to_engage(
            self, _clock, monkeypatch):
        """No HS + boss in ENGAGE_ENTER_PX => not S_ENGAGE."""
        # Place the bot at 500 px from the boss -- well inside
        # ENGAGE_ENTER_PX (800).  No HS in the buildings list.
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3700.0, y=3200.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE, (
            "bot must not engage the boss directly when no "
            "home station exists -- no umbrella, certain death")
        assert ap._fsm["state"] != ap.S_ENGAGE_BOSS, (
            "the seventeenth-pass no-HS engage_boss suppression "
            "still applies")

    def test_boss_as_threat_with_hs_still_routes_to_engage_boss(
            self, _clock, monkeypatch):
        """Sanity: with HS present, threat-is-boss in band
        => S_ENGAGE_BOSS (higher priority than S_ENGAGE)."""
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=3700.0, y=3200.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE_BOSS

    def test_small_alien_threat_with_no_hs_still_engages(
            self, _clock, monkeypatch):
        """The no-HS suppression is gated on threat-is-BOSS.
        A regular alien threat without HS still routes to
        ENGAGE -- otherwise the bot would never fight small
        aliens until it had a base."""
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3500.0, "y": 3200.0, "hp": 50}],
        )
        # Boss exists but is far away -- not the chosen threat.
        s["boss"] = _boss(x=10000.0, y=10000.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE


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

    def test_hs_present_idles_normally(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: captured.update(fled=True))
        monkeypatch.setattr(ap, "_do_idle", lambda: captured.update(idled=True))
        s = _state(
            player={"x": 3300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=3000.0, y=3000.0)
        ap._act_regen(s, s["player"])
        assert "idled" in captured and "fled" not in captured, (
            "with HS present, REGEN still idles (the FSM-level "
            "routing parks the bot at HS)")

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


class TestRecoverLootBossProximityGate:
    """2026-05-14 eighteenth telemetry pass.  S_RECOVER_LOOT
    routed the bot back to the death pile while the boss
    hovered there.  Captured pathology: 7 deaths in 17 s at
    (3170-3225, 3180-3210) -- bot died, dropped loot, FSM re-
    entered recover_loot toward the new pile, died again.

    Fix: suppress S_RECOVER_LOOT when entering would walk the
    bot into the boss's aggro range.  Two gates:
      * boss within RECOVER_LOOT_BOSS_DANGER_PX of death_pos
      * no HS AND boss alive (nowhere to install recovered
        modules at, so recovery is pointless until HS rebuilds)
    The pending latch stays True so recovery resumes when
    the danger clears; the hard DEATH_RECOVERY_TIMEOUT_S
    backstop still applies.
    """

    def test_boss_at_death_pos_suppresses_recover_loot(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_recover_loot", lambda s, p: None)
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (3200.0, 3200.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(
            player={"x": 3500.0, "y": 3500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # HS far away so the no-HS gate doesn't also fire.
            buildings=[{"x": 100.0, "y": 100.0,
                        "building_type": "Home Station"}],
        )
        # Boss right at the death pos -- well inside
        # RECOVER_LOOT_BOSS_DANGER_PX.
        s["boss"] = _boss(x=3200.0, y=3200.0)
        s["iron_pickups"] = [
            {"x": 3200.0, "y": 3200.0, "amount": 10,
             "item_type": "iron"}]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_RECOVER_LOOT, (
            "must not route into recover_loot while boss is "
            "camping the death pile")
        # The pending latch stays True so recovery resumes when
        # the boss leaves.
        assert ap._state.death_recovery_pending is True

    def test_no_hs_with_boss_alive_suppresses_recover_loot(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_recover_loot", lambda s, p: None)
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (3200.0, 3200.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(
            player={"x": 3500.0, "y": 3500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # No HS in buildings list.
        )
        # Boss far from death_pos -- only the no-HS gate fires.
        s["boss"] = _boss(x=10000.0, y=10000.0)
        s["iron_pickups"] = [
            {"x": 3200.0, "y": 3200.0, "amount": 10,
             "item_type": "iron"}]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_RECOVER_LOOT
        assert ap._state.death_recovery_pending is True

    def test_boss_far_with_hs_does_not_suppress(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Sanity: when neither gate fires (HS exists AND boss
        far from death_pos), recover_loot routes normally."""
        monkeypatch.setattr(ap, "_act_recover_loot", lambda s, p: None)
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (3200.0, 3200.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(
            player={"x": 3500.0, "y": 3500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=10000.0, y=10000.0)
        s["iron_pickups"] = [
            {"x": 3200.0, "y": 3200.0, "amount": 10,
             "item_type": "iron"}]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_RECOVER_LOOT

    def test_no_boss_does_not_suppress(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Without a boss, both gates are inactive -- recovery
        routes normally even without an HS (gate is gated on
        boss-alive)."""
        monkeypatch.setattr(ap, "_act_recover_loot", lambda s, p: None)
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (3200.0, 3200.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(
            player={"x": 3500.0, "y": 3500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["iron_pickups"] = [
            {"x": 3200.0, "y": 3200.0, "amount": 10,
             "item_type": "iron"}]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_RECOVER_LOOT


class TestPostBossWarpToWormholeTrigger:
    """2026-05-15: after the main-zone boss dies and the bot has
    recovered every dropped module + has consumables equipped,
    the FSM should route the bot to the nearest wormhole for a
    one-shot warp into one of the four warp zones.  Trigger
    gates:
      * ``boss_was_killed`` latch True
      * ``warp_after_boss_done`` latch False (one-shot)
      * Current zone is MAIN (wormholes only spawn there)
      * No death recovery pending
      * Module install queue is empty
      * Quick-use slots contain >=1 repair_pack + >=1 shield_recharge
    """

    @staticmethod
    def _ready_state(have_wormhole=True, **player_overrides):
        """Build a state that satisfies every warp trigger gate
        except the boss-was-killed latch (callers set that)."""
        player = {"x": 3200.0, "y": 3200.0, "heading": 0.0,
                  "shields": 150, "max_shields": 150}
        player.update(player_overrides)
        s = _state(
            player=player,
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # The default _state helper uses key "zone_id" but the
        # real API exposes the enum as "id" -- set both so the
        # choose-state check (which reads "id") fires.
        s["zone"]["id"] = "ZoneID.MAIN"
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5},
            {"item_type": "shield_recharge", "count": 5},
        ]
        if have_wormhole:
            s["wormholes"] = [
                {"x": 200.0, "y": 200.0,
                 "zone_target": "ZoneID.WARP_METEOR"},
                {"x": 6200.0, "y": 200.0,
                 "zone_target": "ZoneID.WARP_LIGHTNING"},
            ]
        return s

    def test_all_gates_satisfied_routes_to_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE

    def test_no_boss_kill_no_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Without the boss_was_killed latch the warp branch must
        not fire, even when every other gate is satisfied."""
        ap._state.boss_was_killed = False
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_warp_done_latch_blocks_reentry_outside_main(
            self, _clock, _fresh_bot_state, monkeypatch):
        """While the bot is *outside* MAIN (e.g. mid-traverse in
        Nebula) the latch keeps the warp-to-wormhole cascade quiet
        so the bot doesn't keep trying to re-route to a wormhole
        that doesn't exist in this zone.

        Note: the previous "one-shot blocks even in MAIN" behavior
        was intentionally inverted on 2026-05-16 -- if the bot
        ends up back in MAIN (e.g. Nebula's central return
        wormhole), ``_observe_warp_back_to_main`` clears the
        latch and the cascade re-fires.  Pinned by
        ``TestWarpBackToMainReArms``.
        """
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        s["zone"]["id"] = "ZoneID.ZONE2"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_modules_left_to_install_blocks_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = ["broadside"]
        s = self._ready_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_no_consumables_equipped_blocks_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        s["quick_use_slots"] = []  # nothing equipped
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_only_repair_pack_blocks_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Both repair_pack AND shield_recharge required -- one
        alone isn't enough."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_death_recovery_pending_blocks_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If the bot has loot pickup pending, finish that first
        (recover_loot wins via section 1.4)."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (3200.0, 3200.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = self._ready_state()
        s["iron_pickups"] = [
            {"x": 3200.0, "y": 3200.0, "amount": 10,
             "item_type": "iron"}]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_warp_zone_latches_done_flag(
            self, _clock, _fresh_bot_state, monkeypatch):
        """When the bot's zone_id flips out of MAIN with the
        boss-was-killed latch still set, ``warp_after_boss_done``
        must latch so subsequent ticks don't keep trying."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        s["zone"]["id"] = "ZoneID.WARP_GAS"  # bot just warped in
        ap._do_auto(s, s["player"])
        assert ap._state.warp_after_boss_done is True
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE


class TestWarpToWormholeAction:
    """``_act_warp_to_wormhole`` picks the closest wormhole and
    routes there.  If none are visible (already in a warp zone, or
    the API doesn't expose them), latch ``warp_after_boss_done`` so
    the FSM falls through to the regular cascade."""

    def test_picks_nearest_wormhole(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=50.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,           # near (~1131 px)
             "zone_target": "ZoneID.WARP_METEOR"},
            {"x": 6200.0, "y": 200.0,          # far  (~5273 px)
             "zone_target": "ZoneID.WARP_LIGHTNING"},
            {"x": 6200.0, "y": 6200.0,         # far
             "zone_target": "ZoneID.WARP_ENEMY"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        assert captured["tx"] == 200.0
        assert captured["ty"] == 200.0

    def test_no_wormholes_latches_done(self, monkeypatch):
        """Empty wormhole list latches the done flag so the FSM
        falls through next tick."""
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: None)
        ap._state.warp_after_boss_done = False
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = []
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_after_boss_done is True


class TestWarpTriggerOnBossDefeatedFromSave:
    """2026-05-15: warp-to-wormhole trigger must also fire on
    save-loaded games where the in-session ``boss_was_killed``
    latch never set (because ``boss_engage_end`` never fired
    this session).  ``state.boss_defeated`` is the game's
    persisted "main boss killed in this save" flag exposed via
    bot_api -- the choose-state cascade ORs the two signals so
    either path triggers the warp.

    Captured pathology: 488 s session loaded from a save with the
    boss already dead; bot finished craft + install + equip but
    never routed to a wormhole because boss_was_killed=False.
    """

    @staticmethod
    def _ready_state(**player_overrides):
        player = {"x": 3200.0, "y": 3200.0, "heading": 0.0,
                  "shields": 150, "max_shields": 150}
        player.update(player_overrides)
        s = _state(
            player=player,
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["zone"]["id"] = "ZoneID.MAIN"
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5},
            {"item_type": "shield_recharge", "count": 5},
        ]
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        return s

    def test_boss_defeated_from_save_triggers_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The bot loaded a save where the boss was killed last
        session.  ``state.boss_defeated`` is True from the game's
        persisted flag; ``_state.boss_was_killed`` is the default
        False (no kill this session).  Warp must still fire."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = False
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        s["boss_defeated"] = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE

    def test_neither_latch_nor_flag_does_not_trigger(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Sanity: neither signal set => no warp.  Mirrors the
        existing TestPostBossWarpToWormholeTrigger test but pins
        the ``boss_defeated`` default to False."""
        ap._state.boss_was_killed = False
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        s = self._ready_state()
        s["boss_defeated"] = False  # explicit False
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_missing_boss_defeated_key_does_not_break(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Backward compat: an older API that doesn't expose
        ``boss_defeated`` must not crash the cascade.  Trigger
        falls back to the local latch only."""
        ap._state.boss_was_killed = True  # local latch set
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install = []
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        s = self._ready_state()
        # Don't set "boss_defeated" at all -- state.get returns None.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE


class TestWarpTraverseTrigger:
    """2026-05-15: once the bot has warped into a warp zone
    after the post-boss arc, route to S_WARP_TRAVERSE so the
    bot drives to the far side of the map (entry_side is
    "bottom" so the goal is the top y edge).
    """

    def test_in_warp_zone_after_warp_routes_to_traverse(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(
            ap, "_act_warp_traverse", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        s = _state(
            player={"x": 1600.0, "y": 500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TRAVERSE

    def test_traverse_done_latch_blocks_reentry(
            self, _clock, _fresh_bot_state, monkeypatch):
        """One-shot: after ``warp_traverse_done`` latches, the
        bot doesn't re-route to traverse on subsequent warp-zone
        visits."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = True
        s = _state(
            player={"x": 1600.0, "y": 500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TRAVERSE

    def test_traverse_not_in_main_zone(
            self, _clock, _fresh_bot_state, monkeypatch):
        """In the MAIN zone the traverse branch must NOT fire
        (zone_id doesn't contain WARP)."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        s = _state(
            player={"x": 1600.0, "y": 500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TRAVERSE

    def test_close_threat_preempts_traverse(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Priority: ENGAGE > WARP_TRAVERSE.  A close threat
        must pull the bot off the traversal so it doesn't drive
        past hostiles taking free hits."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        s = _state(
            player={"x": 1600.0, "y": 500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 1800.0, "y": 500.0, "hp": 50}],
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE


class TestWarpTraverseAction:
    """``_act_warp_traverse`` drives toward (world_w/2, world_h -
    margin) and latches ``warp_traverse_done`` once the bot has
    reached the far-side margin."""

    def test_action_drives_toward_far_side(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=120.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        s = _state(
            player={"x": 800.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        # Target is centre-x, top-edge-minus-margin.
        assert captured["tx"] == 1600.0
        assert captured["ty"] == 6400.0 - ap.WARP_TRAVERSE_MARGIN_PX

    def test_action_latches_done_at_far_side(
            self, _fresh_bot_state, monkeypatch):
        """At/past the arrival band the latch fires AND the bot
        keeps driving toward the same target -- inertia carries
        it across the game's EXIT_THRESHOLD (50 px from edge) so
        the zone auto-transition fires.  Braking here would
        leave the bot 10-50 px short of the exit, stuck."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=30.0,
            brake_on_arrival=True: captured.update(
                tx=tx, ty=ty, called=True))
        monkeypatch.setattr(
            ap, "_do_idle", lambda: captured.update(idled=True))
        ap._state.warp_traverse_done = False
        # Place bot inside the arrival band.
        target_y = 6400.0 - ap.WARP_TRAVERSE_MARGIN_PX
        s = _state(
            player={"x": 1600.0,
                    "y": target_y - ap.WARP_TRAVERSE_ARRIVAL_PX
                         + 10.0,
                    "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_done is True
        # Keep driving so inertia carries the bot across the
        # exit threshold instead of braking 10-50 px short.
        assert "called" in captured
        assert "idled" not in captured


class TestWarpTraverseLateralDetour:
    """``_act_warp_traverse`` now tracks the bot's max y per arc
    and switches target_x from the world centre to an alternating
    wall margin after WARP_TRAVERSE_DETOUR_TIMEOUT_S seconds of
    no y progress.

    Pinned by 2026-05-17 bot_io capture: 590-s session, bot stuck
    in WARP_GAS oscillating traverse → regen → traverse → regen
    around y=2400-2670 because a gas cloud sat dead-centre on the
    drive path.  ``gas_repulsion`` alone wasn't strong enough to
    deflect a target attraction aimed at the top edge.
    """

    @staticmethod
    def _capture_goto(monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=30.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        return captured

    def test_centre_target_when_y_progressing(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Normal traverse with y advancing: target stays at
        centre (world_w/2)."""
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1600.0, "y": 2000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        # First tick: max_y updates to 2000, timer reset, no detour.
        assert captured["tx"] == 1600.0
        # Advance the bot further north a few ticks below the
        # arrival band; target_x must stay centred.
        for y in (2500.0, 3000.0, 3500.0):
            _clock[0] += 1.0
            s["player"]["y"] = y
            ap._act_warp_traverse(s, s["player"])
            assert captured["tx"] == 1600.0
        assert ap._state.warp_traverse_detour_count == 0

    def test_detour_fires_after_timeout_no_progress(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Stall for WARP_TRAVERSE_DETOUR_TIMEOUT_S without y
        advancing: target_x flips to a wall margin."""
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 2400.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])  # seed max_y + timer
        assert captured["tx"] == 1600.0
        # Advance the clock just past the timeout without y progress.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        # Detour active: target_x = left wall (count=1, odd).
        assert captured["tx"] == ap.WARP_TRAVERSE_MARGIN_PX
        assert ap._state.warp_traverse_detour_count == 1

    def test_detour_alternates_sides(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Consecutive timeouts alternate left / right wall so a
        wide central obstacle gets bypassed on whichever side is
        clear."""
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        world_w = 3200.0
        s = _state(
            player={"x": 1000.0, "y": 2400.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=int(world_w), world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])  # seed
        # First detour: left wall.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert captured["tx"] == ap.WARP_TRAVERSE_MARGIN_PX
        # Second detour (still no progress): right wall.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert captured["tx"] == (world_w - ap.WARP_TRAVERSE_MARGIN_PX)
        # Third detour: left wall again.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert captured["tx"] == ap.WARP_TRAVERSE_MARGIN_PX
        assert ap._state.warp_traverse_detour_count == 3

    def test_detour_does_not_fire_when_progressing(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Even if many seconds elapse, the detour does NOT fire as
        long as the bot's max y keeps advancing -- normal traverse
        completes cleanly."""
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1600.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        # Drive north over a long interval; each tick advances max_y
        # which resets the no-progress timer.
        for y in (1000.0, 2000.0, 3000.0, 4000.0, 5000.0):
            _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S - 1.0
            s["player"]["y"] = y
            ap._act_warp_traverse(s, s["player"])
            assert captured["tx"] == 1600.0
        assert ap._state.warp_traverse_detour_count == 0

    def test_trackers_reset_on_new_arc(
            self, _clock, _fresh_bot_state, monkeypatch):
        """When the bot's y drops to less than half of the tracked
        max (i.e., a new warp arc spawned in another warp zone),
        the trackers reset cleanly so the timeout doesn't carry
        over from the previous arc.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        # Arc 1: bot reaches y=5000.
        s = _state(
            player={"x": 1600.0, "y": 5000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_max_y == 5000.0
        # Arc 2: bot spawns at y=200 in a fresh warp zone.
        _clock[0] += 100.0  # any reasonable interval
        s["player"]["y"] = 200.0
        ap._act_warp_traverse(s, s["player"])
        # max_y reset to the new arc's starting y, timer fresh,
        # detour count zeroed.
        assert ap._state.warp_traverse_max_y == 200.0
        assert ap._state.warp_traverse_detour_count == 0
        # No detour fires on the very next call -- timer just reset.
        assert captured["tx"] == 1600.0


class TestWarpTraverseDetourPersistence:
    """2026-05-17 follow-up to PR #133: the detour was single-tick
    (lasted only the one call where ``no_progress_s >= TIMEOUT``).
    On every subsequent tick ``no_progress_s`` was ~1 s and the
    ``else`` branch reverted ``target_x`` to centre.  Net result:
    bot heads toward the wall for one tick, then back toward the
    central gas cloud for 25 s, repeat.  Captured log: x stayed
    in 1592-1731 across 30 traverse <-> regen oscillations.

    Fix: detour SIDE persists in BotState across ticks until the
    bot's y advances WARP_TRAVERSE_DETOUR_CLEAR_PX past the commit
    anchor (signal that the obstacle has been bypassed).  Each
    timeout flips to the opposite wall, so a wide blocker that
    covers one side gets bypassed on the other.
    """

    @staticmethod
    def _capture_goto(monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=30.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        return captured

    def test_detour_side_persists_across_ticks(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Once the detour fires, ``target_x`` stays at the wall on
        every subsequent tick until the obstacle is cleared.  This
        is the exact bug PR #133 missed -- it only set target_x on
        the timeout tick, then reverted to centre.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 2400.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])  # seed
        assert captured["tx"] == 1600.0
        # Trip the detour.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert captured["tx"] == ap.WARP_TRAVERSE_MARGIN_PX
        assert ap._state.warp_traverse_detour_side == 1
        # Advance the clock by a small amount (less than timeout)
        # and call again.  target_x must STAY at the wall -- this
        # is the PR #133 regression we're fixing.
        for _ in range(5):
            _clock[0] += 1.0  # well below TIMEOUT
            ap._act_warp_traverse(s, s["player"])
            assert captured["tx"] == ap.WARP_TRAVERSE_MARGIN_PX
            assert ap._state.warp_traverse_detour_side == 1

    def test_detour_persists_through_regen_oscillation(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The persistent side survives a traverse -> (regen) ->
        traverse cycle without resetting.  Simulates the captured
        pathology: bot enters regen briefly, then comes back to
        warp_traverse, and the detour must still be active.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 2400.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == 1
        # Simulate a regen interlude: clock advances, no traverse
        # ticks fire.  Then a new traverse tick.
        _clock[0] += 10.0
        ap._act_warp_traverse(s, s["player"])
        # Side still latched at left wall.
        assert ap._state.warp_traverse_detour_side == 1
        assert captured["tx"] == ap.WARP_TRAVERSE_MARGIN_PX

    def test_detour_clears_when_obstacle_bypassed(
            self, _clock, _fresh_bot_state, monkeypatch):
        """When py advances WARP_TRAVERSE_DETOUR_CLEAR_PX past the
        commit anchor, the side resets to 0 and target_x returns to
        centre.  Models the bot successfully routing around the
        obstacle via the lateral path.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        commit_y = 2400.0
        s = _state(
            player={"x": 1000.0, "y": commit_y, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == 1
        commit_anchor = ap._state.warp_traverse_detour_commit_y
        # Advance py past the clear threshold.
        s["player"]["y"] = commit_anchor + ap.WARP_TRAVERSE_DETOUR_CLEAR_PX + 10.0
        _clock[0] += 1.0
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == 0
        assert captured["tx"] == 1600.0

    def test_additional_timeout_flips_side(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If the bot is still stuck after the first detour fires
        AND another TIMEOUT elapses without progress, flip to the
        opposite wall.  Handles wide blockers that cover one side.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        world_w = 3200.0
        s = _state(
            player={"x": 1000.0, "y": 2400.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=int(world_w), world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        # First timeout: left wall.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == 1
        assert captured["tx"] == ap.WARP_TRAVERSE_MARGIN_PX
        # Second timeout (still no y progress): flip to right wall.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == -1
        assert captured["tx"] == (world_w - ap.WARP_TRAVERSE_MARGIN_PX)
        # Third timeout: back to left wall.
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == 1

    def test_new_arc_resets_persistent_side(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Crossing into a new warp zone (py < max_y * 0.5) clears
        the persistent side so the new arc starts fresh at centre.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 2400.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == 1
        # New arc: bot spawns at y=200 in a fresh warp zone.
        _clock[0] += 100.0
        s["player"]["y"] = 200.0
        ap._act_warp_traverse(s, s["player"])
        assert ap._state.warp_traverse_detour_side == 0
        assert ap._state.warp_traverse_detour_commit_y == 0.0
        assert captured["tx"] == 1600.0


class TestWarpBackToMainReArms:
    """2026-05-16: after the post-boss warp out to a warp zone
    succeeded (``warp_after_boss_done`` latched True), the bot can
    still end up back in MAIN -- e.g. by walking into Nebula's
    central return wormhole.  The session-sticky latch then blocked
    the FSM from ever re-routing to a wormhole, so the bot farmed
    Zone 1 forever.

    Fix: ``_observe_warp_back_to_main`` runs each tick and clears
    both ``warp_after_boss_done`` and ``warp_traverse_done`` whenever
    the bot is observed in MAIN with the post-boss latch still True
    (a logical contradiction -- the latch was set on leaving MAIN).
    The existing ``S_WARP_TO_WORMHOLE`` cascade then re-fires.
    """

    @staticmethod
    def _ready_state(zone="ZoneID.MAIN", **player_overrides):
        player = {"x": 3200.0, "y": 3200.0, "heading": 0.0,
                  "shields": 150, "max_shields": 150}
        player.update(player_overrides)
        s = _state(
            player=player,
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["zone"]["id"] = zone
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5},
            {"item_type": "shield_recharge", "count": 5},
        ]
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
            {"x": 6200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_LIGHTNING"},
        ]
        return s

    def test_clears_latches_when_back_in_main_after_warp(
            self, _clock, _fresh_bot_state):
        """Both ``warp_after_boss_done`` and ``warp_traverse_done``
        clear when the bot is in MAIN with the post-boss latch set."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = True
        s = self._ready_state(zone="ZoneID.MAIN")
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert ap._state.warp_after_boss_done is False
        assert ap._state.warp_traverse_done is False

    def test_no_op_when_latch_not_set(
            self, _clock, _fresh_bot_state):
        """Without the latch, the observer is a no-op so it doesn't
        churn the telemetry log every tick of a normal MAIN-zone
        session."""
        ap._state.warp_after_boss_done = False
        ap._state.warp_traverse_done = False
        s = self._ready_state(zone="ZoneID.MAIN")
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert ap._state.warp_after_boss_done is False
        assert ap._state.warp_traverse_done is False

    def test_no_op_in_warp_zone(self, _clock, _fresh_bot_state):
        """While the bot is actually in a warp zone the latch
        should stay set -- the FSM's traverse cascade depends on it."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        s = self._ready_state(zone="ZoneID.WARP_GAS")
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert ap._state.warp_after_boss_done is True
        assert ap._state.warp_traverse_done is False

    def test_no_op_in_nebula(self, _clock, _fresh_bot_state):
        """Nebula (ZONE2) isn't MAIN -- observer should not fire.
        The bot's expected dwell in Nebula keeps the latch set so
        the cascade doesn't kick in until the bot actually returns."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = True
        s = self._ready_state(zone="ZoneID.ZONE2")
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert ap._state.warp_after_boss_done is True
        assert ap._state.warp_traverse_done is True

    def test_main_word_in_warp_zone_id_does_not_trigger(
            self, _clock, _fresh_bot_state):
        """Defensive: a hypothetical zone id containing both
        ``MAIN`` and ``WARP`` (e.g. a future ``MAIN_WARP_*``) must
        not fool the observer.  The match keys off ``MAIN`` AND
        NOT ``WARP``."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = False
        s = self._ready_state(zone="ZoneID.MAIN_WARP_HYPOTHETICAL")
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert ap._state.warp_after_boss_done is True

    def test_end_to_end_do_auto_reroutes_warp_after_relatch(
            self, _clock, _fresh_bot_state, monkeypatch):
        """End-to-end: bot wakes in MAIN with post-boss latch set,
        ``_do_auto`` runs the observer (clears latch), then the
        choose-state cascade re-fires ``S_WARP_TO_WORMHOLE``."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = True
        ap._state.queue.modules_to_install = []
        s = self._ready_state(zone="ZoneID.MAIN")
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE
        assert ap._state.warp_after_boss_done is False


class TestBossKilledLatchInEngageEndEdge:
    """``boss_was_killed`` flips True on ``boss_engage_end`` with
    outcome=boss_killed, sticky for the session."""

    def test_outcome_boss_killed_latches(
            self, _clock, _fresh_bot_state):
        ap._state.boss_was_killed = False
        # Stage S_ENGAGE_BOSS as the previous tick's state.
        ap._fsm["state"] = ap.S_ENGAGE_BOSS
        ap._fsm["entered_at"] = _clock[0]
        ap._state.boss_engage_started_at = _clock[0]
        # Bot has just transitioned out of engage_boss with the
        # boss gone -- _maybe_log_boss_engage_edges will infer
        # outcome=boss_killed.
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = None  # boss dead -> "boss is None"
        _clock[0] += 1.0
        ap._maybe_log_boss_engage_edges(
            s, s["player"], _clock[0],
            ap.S_ENGAGE_BOSS, ap.S_GATHER)
        assert ap._state.boss_was_killed is True

    def test_outcome_disengaged_does_not_latch(
            self, _clock, _fresh_bot_state):
        ap._state.boss_was_killed = False
        ap._fsm["state"] = ap.S_ENGAGE_BOSS
        ap._fsm["entered_at"] = _clock[0]
        ap._state.boss_engage_started_at = _clock[0]
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # Boss still alive -- outcome=disengaged (REGEN preempted).
        s["boss"] = _boss(hp=1500)
        _clock[0] += 1.0
        ap._maybe_log_boss_engage_edges(
            s, s["player"], _clock[0],
            ap.S_ENGAGE_BOSS, ap.S_REGEN)
        assert ap._state.boss_was_killed is False


class TestGasRepulsion:
    """Gas-cloud repulsion (added 2026-05-15) deflects the bot
    away from toxic clouds in the gas warp zone.  Pure-function
    test on ``gas_repulsion`` -- the same linear-ramp pattern as
    boundary / building repulsion."""

    def test_no_gas_returns_zero(self):
        from bot_autopilot_navigation import gas_repulsion
        s = _state()
        s["gas_areas"] = []
        rx, ry = gas_repulsion(s["player"], s)
        assert rx == 0.0 and ry == 0.0

    def test_cloud_in_range_repulses_along_outward_axis(self):
        from bot_autopilot_navigation import gas_repulsion
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0})
        # Cloud to the east -- repulsion should push west (-x).
        s["gas_areas"] = [{"x": 1100.0, "y": 1000.0, "radius": 80.0}]
        rx, ry = gas_repulsion(s["player"], s)
        assert rx < 0.0, "should push away from cloud (west)"
        assert abs(ry) < 0.01, "no y component needed"

    def test_outside_range_returns_zero(self):
        from bot_autopilot_navigation import gas_repulsion, GAS_REPULSION_RANGE_PX
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0})
        # Cloud far enough that bot is OUTSIDE (radius + range).
        far_x = 80.0 + GAS_REPULSION_RANGE_PX + 100.0
        s["gas_areas"] = [{"x": far_x, "y": 0.0, "radius": 80.0}]
        rx, ry = gas_repulsion(s["player"], s)
        assert rx == 0.0 and ry == 0.0

    def test_target_inside_cloud_is_suppressed(self):
        """If the goto target sits inside a cloud (e.g. drifting
        pickup), suppress that cloud's repulsion so the bot can
        actually reach the target."""
        from bot_autopilot_navigation import gas_repulsion
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0})
        s["gas_areas"] = [{"x": 1100.0, "y": 1000.0, "radius": 80.0}]
        # Target right at the cloud centre.
        rx, ry = gas_repulsion(
            s["player"], s, target=(1100.0, 1000.0))
        assert rx == 0.0 and ry == 0.0

    def test_multiple_clouds_stack(self):
        """Two clouds either side of the bot should produce a
        net cancellation (left+right cancel) but ANY two clouds
        in the same hemisphere should sum, not interfere."""
        from bot_autopilot_navigation import gas_repulsion
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0})
        # Two clouds north-east, both within range.
        s["gas_areas"] = [
            {"x": 1100.0, "y": 1000.0, "radius": 80.0},
            {"x": 1000.0, "y": 1100.0, "radius": 80.0},
        ]
        rx, ry = gas_repulsion(s["player"], s)
        # Net: push southwest (away from NE cluster).
        assert rx < 0.0 and ry < 0.0


class TestBoundaryRepulsionWarpZoneNorthSuppress:
    """2026-05-15: in warp zones (WARP_*, NEBULA_WARP_*, etc.)
    the TOP edge is the EXIT to the next zone.  The game's
    auto-transition fires when ``py > world_h - EXIT_THRESHOLD``
    (50 px from top).  Boundary repulsion at 400 px range would
    fight the bot's S_WARP_TRAVERSE for the entire last 400 px,
    leaving the bot pinned ~350 px short of the exit.

    Fix: suppress the north-edge contribution entirely when the
    zone id contains ``WARP``.  Bottom + side walls KEEP their
    repulsion (bottom returns to source; sides drain shields).
    """

    def test_warp_zone_north_edge_no_repulsion(self):
        from bot_autopilot_navigation import boundary_repulsion
        # Bot 100 px below the top edge of a 3200x6400 warp zone.
        p = {"x": 1600.0, "y": 6300.0, "heading": 0.0}
        zone = {"world_w": 3200, "world_h": 6400,
                "id": "ZoneID.WARP_GAS"}
        rx, ry = boundary_repulsion(p, zone)
        # North-edge repulsion suppressed -> ry must be 0.
        assert ry == 0.0
        # Side walls aren't in range here -- rx is also 0.
        assert rx == 0.0

    def test_warp_zone_side_edges_still_repulse(self):
        from bot_autopilot_navigation import boundary_repulsion
        # Bot 100 px from the WEST edge of the warp zone.
        p = {"x": 100.0, "y": 3200.0, "heading": 0.0}
        zone = {"world_w": 3200, "world_h": 6400,
                "id": "ZoneID.WARP_GAS"}
        rx, ry = boundary_repulsion(p, zone)
        # West-edge push east -> rx > 0.
        assert rx > 0.0

    def test_warp_zone_bottom_edge_still_repulses(self):
        """Crossing the bottom edge returns the bot to source --
        we must KEEP the south repulsion so the bot doesn't drift
        into that trap on entry."""
        from bot_autopilot_navigation import boundary_repulsion
        p = {"x": 1600.0, "y": 100.0, "heading": 0.0}
        zone = {"world_w": 3200, "world_h": 6400,
                "id": "ZoneID.WARP_GAS"}
        rx, ry = boundary_repulsion(p, zone)
        # South-edge push north -> ry > 0.
        assert ry > 0.0

    def test_main_zone_north_edge_still_repulses(self):
        """Regression: MAIN zone north edge still repulses
        normally -- the suppression is warp-zone-only."""
        from bot_autopilot_navigation import boundary_repulsion
        p = {"x": 3200.0, "y": 6300.0, "heading": 0.0}
        zone = {"world_w": 6400, "world_h": 6400,
                "id": "ZoneID.MAIN"}
        rx, ry = boundary_repulsion(p, zone)
        # North-edge push south -> ry < 0.
        assert ry < 0.0

    def test_zone2_north_edge_still_repulses(self):
        """ZONE2 (Nebula) is not a warp zone -- north edge
        repulses normally there too."""
        from bot_autopilot_navigation import boundary_repulsion
        p = {"x": 3200.0, "y": 6300.0, "heading": 0.0}
        zone = {"world_w": 6400, "world_h": 6400,
                "id": "ZoneID.ZONE2"}
        rx, ry = boundary_repulsion(p, zone)
        assert ry < 0.0

    def test_nebula_warp_zone_north_also_suppressed(self):
        """The suppression matches any zone id containing
        ``WARP`` -- covers NEBULA_WARP_* and MAZE_WARP_*
        variants which inherit from WarpZoneBase."""
        from bot_autopilot_navigation import boundary_repulsion
        p = {"x": 1600.0, "y": 6300.0, "heading": 0.0}
        zone = {"world_w": 3200, "world_h": 6400,
                "id": "ZoneID.NEBULA_WARP_LIGHTNING"}
        rx, ry = boundary_repulsion(p, zone)
        assert ry == 0.0


class TestWormholeRepulsion:
    """2026-05-15: wormholes in non-MAIN zones that target MAIN
    are RETURN wormholes -- using one undoes the post-boss
    progression.  ``wormhole_repulsion`` deflects the bot away
    from them so any in-zone navigation steers clear.

    User report: "make sure bot avoids the return wormhole while
    in the nebula zone."  Central wormhole in ZONE2 has
    zone_target=MAIN -- exactly this case.
    """

    def test_main_zone_no_repulsion(self):
        """In MAIN, the wormholes are OUTBOUND (target=WARP_*)
        and the bot may want to use one.  Early-return (0, 0)
        regardless of wormhole content."""
        from bot_autopilot_navigation import wormhole_repulsion
        s = _state(
            player={"x": 200.0, "y": 200.0, "heading": 0.0})
        s["zone"]["id"] = "ZoneID.MAIN"
        s["wormholes"] = [
            {"x": 250.0, "y": 250.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        rx, ry = wormhole_repulsion(s["player"], s)
        assert rx == 0.0 and ry == 0.0

    def test_nebula_main_target_repulses(self):
        """In ZONE2 with the central return wormhole pointing to
        MAIN, the bot is pushed away from it."""
        from bot_autopilot_navigation import wormhole_repulsion
        s = _state(
            player={"x": 1700.0, "y": 1000.0, "heading": 0.0})
        s["zone"]["id"] = "ZoneID.ZONE2"
        s["wormholes"] = [
            {"x": 1600.0, "y": 1000.0,
             "zone_target": "ZoneID.MAIN"},  # return wormhole
        ]
        rx, ry = wormhole_repulsion(s["player"], s)
        # Wormhole is WEST of bot -> repulsion pushes EAST.
        assert rx > 0.0
        assert abs(ry) < 0.01

    def test_nebula_forward_target_not_repulsed(self):
        """ZONE2 corner wormholes (post-Nebula-boss) target
        NEBULA_WARP_* -- those are FORWARD progression, not
        return.  No repulsion."""
        from bot_autopilot_navigation import wormhole_repulsion
        s = _state(
            player={"x": 200.0, "y": 200.0, "heading": 0.0})
        s["zone"]["id"] = "ZoneID.ZONE2"
        s["wormholes"] = [
            {"x": 220.0, "y": 220.0,
             "zone_target": "ZoneID.NEBULA_WARP_METEOR"},
        ]
        rx, ry = wormhole_repulsion(s["player"], s)
        assert rx == 0.0 and ry == 0.0

    def test_out_of_range_no_repulsion(self):
        """Bot far from the wormhole -> no force."""
        from bot_autopilot_navigation import wormhole_repulsion
        s = _state(
            player={"x": 5000.0, "y": 5000.0, "heading": 0.0})
        s["zone"]["id"] = "ZoneID.ZONE2"
        s["wormholes"] = [
            {"x": 100.0, "y": 100.0,
             "zone_target": "ZoneID.MAIN"},
        ]
        rx, ry = wormhole_repulsion(s["player"], s)
        assert rx == 0.0 and ry == 0.0

    def test_warp_zone_with_no_wormholes(self):
        """Warp zones don't carry wormholes (exit via edge);
        state.wormholes is empty -> no force."""
        from bot_autopilot_navigation import wormhole_repulsion
        s = _state(
            player={"x": 1600.0, "y": 3000.0, "heading": 0.0})
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        s["wormholes"] = []
        rx, ry = wormhole_repulsion(s["player"], s)
        assert rx == 0.0 and ry == 0.0


class TestBossKiteAtRange:
    """``_act_engage_boss`` holds the bot at ``BOSS_KITE_RANGE_PX``
    from the boss (just outside cannon range 700)."""

    def test_kite_target_lies_outside_cannon_range(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # Boss 100 px east of bot; no Home Station — pure kite.
        s["boss"] = _boss(x=3300.0, y=3200.0)
        ap._act_engage_boss(s, s["player"])
        # Kite target must be on the boss→bot ray, BOSS_KITE_RANGE_PX
        # from the boss.  Bot was west of boss (x=3200 < x=3300), so
        # kite target is also west of the boss.
        import math
        d = math.hypot(captured["tx"] - 3300.0,
                       captured["ty"] - 3200.0)
        assert abs(d - ap.BOSS_KITE_RANGE_PX) < 1.0
        assert captured["tx"] < 3300.0  # west side preserved

    def test_kite_holds_fire_within_basic_laser_range(self, monkeypatch):
        """KeyState.hold('space', True) only when bot is within
        ``BOSS_FIRE_RANGE_PX`` of the boss."""
        recorded: dict = {}

        class _FakeKey:
            @staticmethod
            def hold(name, on):
                recorded[name] = on

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # Boss within fire range — fire ON.
        s["boss"] = _boss(x=3500.0, y=3200.0)
        ap._act_engage_boss(s, s["player"])
        assert recorded["space"] is True
        # Boss past fire range — fire OFF.
        recorded.clear()
        s["boss"] = _boss(x=3200.0 + ap.BOSS_FIRE_RANGE_PX + 50.0,
                          y=3200.0)
        ap._act_engage_boss(s, s["player"])
        assert recorded["space"] is False


class TestBossOrbitKite:
    """2026-05-12 ninth-pass change: when the bot is in the
    legacy kite phase (NOT turret-assist, NOT lure), the kite
    target is a TANGENT point ahead on the orbit circle.  This
    produces continuous tangential motion so the bot isn't
    "stuck on the boss" and the broadside module's perpendicular
    shots align with the boss.
    """

    def _record_goto(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        return captured

    def test_orbit_target_off_boss_to_bot_ray(self, monkeypatch):
        """The orbit lead places the target OFF the boss→bot ray
        (which would have angle equal to the bot's angle around the
        boss).  Verify the dot product of (target - boss) and
        (bot - boss) is strictly less than ``range^2`` -- i.e., the
        target is not radial from the boss."""
        import math
        captured = self._record_goto(monkeypatch)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3500.0, y=3200.0)
        ap._act_engage_boss(s, s["player"])
        bot_vec = (3200.0 - 3500.0, 3200.0 - 3200.0)
        tgt_vec = (captured["tx"] - 3500.0, captured["ty"] - 3500.0)
        # Old (static-ray) code: |dot| == |bot_vec| * |tgt_vec|.
        # Orbit code: |dot| < |bot_vec| * |tgt_vec| -- the target
        # is at an angle to the ray.
        dot = bot_vec[0] * tgt_vec[0] + bot_vec[1] * tgt_vec[1]
        bot_mag = math.hypot(*bot_vec)
        tgt_mag = math.hypot(*tgt_vec)
        # cosine of angle between rays = dot / (|a| * |b|)
        cos_angle = dot / (bot_mag * tgt_mag) if bot_mag * tgt_mag else 0
        # Lead = 0.30 rad => cos(0.30) ~ 0.955.  Strictly less than 1.
        assert cos_angle < 0.99

    def test_orbit_target_at_desired_range(self, monkeypatch):
        """Orbit target distance from boss equals BOSS_KITE_RANGE_PX
        in phases 1-2 (BOSS_PHASE3_PRESS_RANGE_PX in phase 3)."""
        import math
        captured = self._record_goto(monkeypatch)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # Phase 1: default kite range.
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=1)
        ap._act_engage_boss(s, s["player"])
        d_p1 = math.hypot(captured["tx"] - 3400.0,
                          captured["ty"] - 3200.0)
        assert abs(d_p1 - ap.BOSS_KITE_RANGE_PX) < 1.0
        # Phase 3: PRESS range (closer for DPS).
        captured.clear()
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=3)
        ap._act_engage_boss(s, s["player"])
        d_p3 = math.hypot(captured["tx"] - 3400.0,
                          captured["ty"] - 3200.0)
        assert abs(d_p3 - ap.BOSS_PHASE3_PRESS_RANGE_PX) < 1.0

    def test_orbit_advances_consistently_around_boss(
            self, monkeypatch):
        """Two consecutive ticks with the bot at progressively
        more advanced angles around the boss produce orbit targets
        whose angles advance by the same lead.  Tests the orbit's
        angular consistency (CCW or CW, but never alternating)."""
        import math
        captured = self._record_goto(monkeypatch)
        # Bot due west of boss.
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3400.0, y=3200.0)
        ap._act_engage_boss(s, s["player"])
        theta_1 = math.atan2(captured["ty"] - 3200.0,
                             captured["tx"] - 3400.0)
        # Move bot 0.1 rad along the orbit (CCW in math coords).
        captured.clear()
        new_theta = math.pi + 0.1
        s["player"]["x"] = 3400.0 + 200.0 * math.cos(new_theta)
        s["player"]["y"] = 3200.0 + 200.0 * math.sin(new_theta)
        ap._act_engage_boss(s, s["player"])
        theta_2 = math.atan2(captured["ty"] - 3200.0,
                             captured["tx"] - 3400.0)
        # theta_2 should be ahead of theta_1 (CCW), i.e., advance
        # by ~0.1 rad (the bot moved 0.1, lead is constant).
        # Both targets are at their respective bot-angle + lead.
        # difference = (new_theta + LEAD) - (PI + LEAD) = 0.1.
        diff = theta_2 - theta_1
        # Wrap-safe difference in [-π, π].
        diff = (diff + math.pi) % (2 * math.pi) - math.pi
        assert abs(diff - 0.1) < 0.01

    def test_orbit_snaps_to_station_when_too_far(self, monkeypatch):
        """Existing station-tether logic still kicks in: when the
        orbit point lands > BOSS_KITE_STATION_TETHER_PX from the
        station, snap to the station-side ray.  Preserves the
        umbrella discipline when the boss is on the wrong side."""
        captured = self._record_goto(monkeypatch)
        # Bot east of boss; station WEST of boss far away.  Boss
        # outside turret-assist enter range so this exercises the
        # legacy kite path with snap.
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 2000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Boss 2500 px east of station -- outside turret-assist
        # enter range (1500).
        s["boss"] = _boss(x=4500.0, y=4000.0)
        # Bot exactly on boss => degenerate; use slightly offset.
        s["player"]["x"] = 4600.0
        ap._act_engage_boss(s, s["player"])
        # Snap pulls the kite to the station side of the boss
        # (west) at desired_range.
        assert captured["tx"] < 4500.0

    def test_orbit_anchored_on_boss_to_station_axis(
            self, monkeypatch):
        """2026-05-12 tenth-pass pin: when an HS exists, the orbit
        angle anchors on the BOSS->HOME-STATION axis (theta_hs),
        not on the bot's current angle.  Otherwise the bot trails
        the boss into the corner -- tenth-pass log captured the
        bot drifting from hs_dist=429 to 2921 in 20 s because the
        bot-anchored orbit kept it on the SW side of the boss as
        the boss moved NE toward the station.
        """
        import math
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        # Station NE of boss; bot SW of boss (drifted into corner
        # by the old bot-anchored orbit).  Boss outside turret-
        # assist enter range so we exercise the legacy kite path.
        s = _state(
            player={"x": 1500.0, "y": 1500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Boss between bot and station -- mid-way.
        s["boss"] = _boss(x=2500.0, y=2500.0)
        ap._act_engage_boss(s, s["player"])
        # Expected: orbit target is on the boss->HS ray side
        # (NE of boss), NOT on the bot side (SW of boss).
        # Compute the dot product of (target-boss) with (HS-boss);
        # positive means the target is on the station side.
        hs_vec = (4000.0 - 2500.0, 4000.0 - 2500.0)  # NE
        tgt_vec = (captured["tx"] - 2500.0,
                   captured["ty"] - 2500.0)
        dot = hs_vec[0] * tgt_vec[0] + hs_vec[1] * tgt_vec[1]
        assert dot > 0, (
            "Orbit target must sit on the station-side semicircle "
            "of the boss, not trail the bot's drift.")

    def test_orbit_target_stable_as_bot_drifts(
            self, monkeypatch):
        """The new station-anchored orbit must produce a stable
        kite point regardless of the bot's current position --
        moving the bot to different drifted positions yields the
        SAME orbit target (boss + station positions unchanged).
        Catches accidental dependency on theta_bot.
        """
        import math
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Boss outside turret-assist enter range.
        s["boss"] = _boss(x=2000.0, y=2000.0)
        ap._act_engage_boss(s, s["player"])
        tx1, ty1 = captured["tx"], captured["ty"]
        # Move the bot to a drastically different position.
        captured.clear()
        s["player"]["x"] = 1000.0
        s["player"]["y"] = 1000.0
        ap._act_engage_boss(s, s["player"])
        tx2, ty2 = captured["tx"], captured["ty"]
        # Same orbit point (within rounding) because boss + HS
        # positions are unchanged.
        assert abs(tx1 - tx2) < 0.5
        assert abs(ty1 - ty2) < 0.5

    def test_orbit_no_station_uses_bot_angle(self, monkeypatch):
        """No-station fallback (early Nebula spawn, Star Maze):
        orbit uses the bot's current angle (PR #106 behavior).
        Without this fallback the bot's orbit would be undefined.
        """
        import math
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # no buildings
        )
        s["boss"] = _boss(x=3500.0, y=3200.0)
        ap._act_engage_boss(s, s["player"])
        # PR #106 invariant: target on circle of radius
        # BOSS_KITE_RANGE_PX, off the boss->bot ray by ~LEAD.
        d = math.hypot(captured["tx"] - 3500.0,
                       captured["ty"] - 3200.0)
        assert abs(d - ap.BOSS_KITE_RANGE_PX) < 1.0


class TestBossLureMode:
    """User spec (2026-05-11 fifth pass): the bot should ATTACK the
    boss first (kite at BOSS_KITE_RANGE_PX) and only retreat to
    lure when shields drop below BOSS_LURE_SHIELDS_PCT (50 %).
    Once activated, the latch holds until the boss dies so the
    bot doesn't yo-yo between kite + lure when shields oscillate
    around the threshold."""

    def test_lure_does_not_arm_at_full_shields(self, monkeypatch):
        """User spec: bot should attack first, NOT lure pre-emptively."""
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},  # full
            buildings=[{"x": 2000.0, "y": 3200.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss()
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_lure_active is False

    def test_lure_activates_when_shields_drop_below_threshold(
            self, monkeypatch):
        """User spec: retreat when shields fall under 50 %."""
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 40, "max_shields": 150},  # 27 %
            buildings=[{"x": 2000.0, "y": 3200.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss()
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_lure_active is True

    def test_lure_does_not_arm_without_station(self, monkeypatch):
        """No Home Station -> no lure; the bot falls back to the
        standard kite ring."""
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 40, "max_shields": 150},
            # no buildings -> no station
        )
        s["boss"] = _boss()
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_lure_active is False

    def test_lure_holds_even_when_shields_recover(self, monkeypatch):
        """Sticky latch: shields back to 100 % must KEEP the lure
        active so the bot doesn't yo-yo back into kite range."""
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = True
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},  # 100 %
            buildings=[{"x": 2000.0, "y": 3200.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss()
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_lure_active is True

    def test_lure_target_is_station_perimeter(self, monkeypatch):
        """When lure is active and a Home Station exists, the goto
        target must land within ``BOSS_LURE_TURRET_RADIUS_PX`` of
        the station -- not on the kite ring."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = False  # will arm in handler
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},  # 20 %
            buildings=[{"x": 2000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=4800.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        import math
        d = math.hypot(captured["tx"] - 2000.0,
                       captured["ty"] - 4000.0)
        assert abs(d - ap.BOSS_LURE_TURRET_RADIUS_PX) < 1.0

    def test_lure_target_is_on_far_side_of_station_from_boss(
            self, monkeypatch):
        """Pinning the 2026-05-12 sixth-pass fix: lure target sits
        on the FAR side of the station from the boss.  The bot
        then turns ~180 degrees and forward-thrusts past the
        station, dragging the boss into the umbrella -- it never
        has to drive toward the boss to reach the umbrella, and
        never reverse-thrusts.
        """
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = False  # will arm in handler
        # Station west, boss east -- the far-side anchor should sit
        # WEST of the station (smaller x than HS.x).  Pre-fix this
        # landed EAST of the station (between station and boss).
        s = _state(
            player={"x": 3500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},  # 20 %
            buildings=[{"x": 2000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=4800.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        # Far-side: target.x < station.x because boss is east.
        assert captured["tx"] < 2000.0
        # And on the far-side ray, the station lies between target
        # and boss -- vector station->target opposes station->boss.
        import math
        sx_to_tx = captured["tx"] - 2000.0
        sx_to_bx = 4800.0 - 2000.0
        sy_to_ty = captured["ty"] - 4000.0
        sy_to_by = 4000.0 - 4000.0
        # Dot product must be negative (opposing rays).
        assert sx_to_tx * sx_to_bx + sy_to_ty * sy_to_by < 0.0

    def test_lure_clears_when_boss_dies_mid_tick(self, monkeypatch):
        """Boss vanishing during ENGAGE_BOSS clears the latch so a
        future encounter starts from kite mode."""
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)

        class _FakeKey:
            @staticmethod
            def hold(name, on):
                pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        ap._state.boss_lure_active = True
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},
        )
        s["boss"] = None
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_lure_active is False


class TestBossTurretAssistOrbit:
    """User spec (2026-05-12 eighth telemetry pass): when the boss
    is within ``BOSS_TURRET_ASSIST_ENTER_PX`` of the Home Station,
    the bot orbits the station's far perimeter and lets the turret +
    missile umbrella solo it instead of kiting directly.  When the
    boss is far from the station, the legacy kite-at-range behavior
    runs so a boss that spawned outside turret range gets drawn in.
    Hysteresis on (ENTER_PX, EXIT_PX) keeps the latch stable.
    """

    def _record_goto(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        return captured

    def test_turret_assist_arms_when_boss_near_station(
            self, monkeypatch):
        """Boss within ENTER_PX of HS -> latch becomes True."""
        self._record_goto(monkeypatch)
        ap._state.boss_turret_assist_active = False
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},  # full
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Boss 1000 px east of HS -- well within ENTER_PX (1500).
        s["boss"] = _boss(x=5000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_turret_assist_active is True

    def test_turret_assist_does_not_arm_when_boss_far(
            self, monkeypatch):
        """Boss > ENTER_PX from HS -> latch stays False (legacy
        kite engages to draw the boss in)."""
        self._record_goto(monkeypatch)
        ap._state.boss_turret_assist_active = False
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 2000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Boss 4000 px east of HS -- well outside ENTER_PX (1500).
        s["boss"] = _boss(x=6000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_turret_assist_active is False

    def test_turret_assist_hysteresis_holds_between_thresholds(
            self, monkeypatch):
        """Once armed, the latch survives until boss leaves EXIT_PX.
        At intermediate distance (ENTER < d < EXIT) the latch holds.
        """
        self._record_goto(monkeypatch)
        ap._state.boss_turret_assist_active = True  # already armed
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Boss at d=1650 (between ENTER=1500 and EXIT=1800).
        s["boss"] = _boss(x=5650.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_turret_assist_active is True

    def test_turret_assist_clears_when_boss_exits_far(
            self, monkeypatch):
        """Boss leaves EXIT_PX -> latch drops, kite resumes for a
        future boss-far engagement."""
        self._record_goto(monkeypatch)
        ap._state.boss_turret_assist_active = True
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        # Boss at d=2000 (> EXIT=1800).
        s["boss"] = _boss(x=6000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_turret_assist_active is False

    def test_turret_assist_clears_when_boss_dies(self, monkeypatch):
        """Boss=None -> latch cleared so a future fight starts
        fresh (same lifecycle as the lure latch)."""
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)

        class _FakeKey:
            @staticmethod
            def hold(name, on):
                pass
        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        ap._state.boss_turret_assist_active = True
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = None
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_turret_assist_active is False

    def test_orbit_target_is_far_side_of_station(self, monkeypatch):
        """When turret-assist is active, the goto target is the
        station's far-side perimeter at BOSS_TURRET_ASSIST_ORBIT_PX.
        Station between bot heading and boss => bot rotates ~180,
        forward-thrusts past the station.
        """
        captured = self._record_goto(monkeypatch)
        ap._state.boss_turret_assist_active = False
        ap._state.boss_lure_active = False
        # Station at (4000, 4000), boss east at (5000, 4000) --
        # within ENTER_PX so latch arms this tick.  Far-side
        # orbit point should be WEST of the station.
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=5000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        # Target sits at ORBIT_PX from station, on the FAR side.
        import math
        d = math.hypot(captured["tx"] - 4000.0,
                       captured["ty"] - 4000.0)
        assert abs(d - ap.BOSS_TURRET_ASSIST_ORBIT_PX) < 1.0
        # And on the FAR side: dot(station->target, station->boss) < 0
        sx_to_tx = captured["tx"] - 4000.0
        sx_to_bx = 5000.0 - 4000.0
        sy_to_ty = captured["ty"] - 4000.0
        sy_to_by = 4000.0 - 4000.0
        assert sx_to_tx * sx_to_bx + sy_to_ty * sy_to_by < 0.0

    def test_no_station_falls_back_to_kite(self, monkeypatch):
        """No Home Station -> turret-assist can't arm, the bot
        kites at standard range (eg. early Nebula boss spawn)."""
        captured = self._record_goto(monkeypatch)
        ap._state.boss_turret_assist_active = False
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            # no buildings -> no station
        )
        s["boss"] = _boss(x=5000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        assert ap._state.boss_turret_assist_active is False
        # Target is a kite-range point, not a far-side orbit.
        # With boss at (5000, 4000) and bot at (4500, 4000), the
        # kite point sits along the boss->bot ray at BOSS_KITE_RANGE
        # from the boss => west of the boss.
        import math
        boss_to_target = math.hypot(captured["tx"] - 5000.0,
                                    captured["ty"] - 4000.0)
        assert abs(boss_to_target - ap.BOSS_KITE_RANGE_PX) < 50.0

    def test_turret_assist_overrides_full_shields_kite(
            self, monkeypatch):
        """Even with full shields (lure normally wouldn't arm),
        if the boss is near the station the bot orbits.  This is
        the core spec: the bot should NOT engage near-station
        bosses directly even when healthy."""
        captured = self._record_goto(monkeypatch)
        ap._state.boss_turret_assist_active = False
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},  # full shields
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=5000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        # Turret-assist armed; orbit target landed on far-side
        # perimeter (not a kite point).
        assert ap._state.boss_turret_assist_active is True
        import math
        d = math.hypot(captured["tx"] - 4000.0,
                       captured["ty"] - 4000.0)
        assert abs(d - ap.BOSS_TURRET_ASSIST_ORBIT_PX) < 1.0


class TestBossKiteStationAnchor:
    """When a Home Station exists, the kite target prefers the side
    of the boss closest to the station so friendly turrets share DPS."""

    def test_kite_target_pulls_toward_station_when_default_too_far(
            self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        # Bot east of boss; station WEST of boss.  Default kite
        # target (boss→bot ray) sits east — far from station.  The
        # station-tether logic should pull the kite point west to
        # the station-side of the boss instead.
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 2000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=4000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        # Pulled west — kite x must be less than the boss x, not
        # east on the bot side.
        assert captured["tx"] < 4000.0


class TestBossKiteStationAnchorBossFar:
    """2026-05-14 eighteenth telemetry pass.  The previous
    station-tether snap only pulled the kite onto the
    boss->station ray; when the boss spawned far enough from
    HS that NO point at ``BOSS_KITE_RANGE_PX`` from the boss
    fell within tether, the snap still left the bot chasing
    the boss into open space.  Captured pathology: boss
    spawned ~3000 px from HS, bot followed kite tangent into
    point-blank range, took 120 shields in 0.9 s, died with
    boss still at 2000/2000 HP (zero damage dealt).

    Fix: when ray-snap is still outside tether, park at the
    umbrella edge (HS + tether * unit(HS->boss)) instead.
    Bot stays inside turret + missile DPS range and inside
    laser range once the boss approaches.
    """

    def test_far_boss_parks_at_umbrella_edge(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        # HS at (2000, 2000); boss at (5000, 2000) -- 3000 px
        # east of HS.  Tether = 600 px, kite range = 750 px.
        # Even snapping to the boss->HS ray gives a kite
        # 3000 - 750 = 2250 px from HS, well outside tether.
        # New behavior: park at HS + 600 * unit(HS->boss) =
        # (2600, 2000).
        s = _state(
            player={"x": 2200.0, "y": 2000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 2000.0, "y": 2000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=5000.0, y=2000.0)
        ap._act_engage_boss(s, s["player"])
        # Target must be at the umbrella edge facing the boss,
        # not 2250 px out chasing the boss.
        d_from_hs = math.hypot(
            captured["tx"] - 2000.0, captured["ty"] - 2000.0)
        assert abs(d_from_hs - ap.BOSS_KITE_STATION_TETHER_PX) < 5.0, (
            f"bot should park at umbrella edge (tether="
            f"{ap.BOSS_KITE_STATION_TETHER_PX}) when boss is "
            f"too far for any kite point to be in tether; "
            f"got d={d_from_hs:.1f}")
        # Direction sanity: target should be east of HS
        # (toward the boss), not the opposite side.
        assert captured["tx"] > 2000.0

    def test_existing_pull_toward_station_test_still_passes(
            self, monkeypatch):
        """Sanity: the original
        ``TestBossKiteStationAnchor.test_kite_target_pulls_toward
        _station_when_default_too_far`` asserts ``tx < 4000``
        for a boss at (4000, 4000) with HS at (2000, 4000).
        Under the new umbrella-edge rule, the kite target is
        at HS + tether * unit(HS->boss) = (2600, 4000) -- still
        west of boss, so the original assertion holds."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 4500.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 2000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=4000.0, y=4000.0)
        ap._act_engage_boss(s, s["player"])
        # Pulled WEST -- new behavior parks at umbrella edge
        # (HS + 600 east), which is x = 2600, well west of boss.
        assert captured["tx"] < 4000.0
        # Concretely: target sits ~600 px from HS.
        d_from_hs = math.hypot(
            captured["tx"] - 2000.0, captured["ty"] - 4000.0)
        assert abs(d_from_hs - ap.BOSS_KITE_STATION_TETHER_PX) < 5.0


class TestBossPhase2ChargeDodge:
    """Phase 2 charge windup => bot strafes perpendicular."""

    def test_charge_windup_displaces_kite_target_perpendicular(
            self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # Phase 2 boss directly east, charging.  Bot is west of boss
        # along +x axis, so default kite is at (3200 - extra, 3200)
        # — the perpendicular dodge must change y by BOSS_DODGE_PERP.
        # Boss positioned outside BOSS_CHARGE_PANIC_DIST_PX so the
        # standard perpendicular dodge fires (not the panic escape).
        s["boss"] = _boss(x=3700.0, y=3200.0, phase=2,
                          charging=True, windup=2.0)
        ap._act_engage_boss(s, s["player"])
        # Default kite y would be 3200; dodge displaces it by
        # ±BOSS_DODGE_PERP_PX.
        assert abs(captured["ty"] - 3200.0) >= ap.BOSS_DODGE_PERP_PX - 1.0

    def test_phase1_charge_fields_ignored_no_dodge(self, monkeypatch):
        """charging=True at phase=1 (impossible in-game, defensive
        check) must NOT trigger the dodge -- the kite target equals
        the bare ORBIT point with no perpendicular dodge offset.
        Post-2026-05-12 the orbit lead puts the target naturally
        off-axis from the boss→bot ray; this test confirms NO
        ADDITIONAL displacement on top of the orbit lead."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=1,
                          charging=True, windup=2.0)
        ap._act_engage_boss(s, s["player"])
        # Expected bare orbit point: bot due west of boss => theta=π.
        # Lead by BOSS_ORBIT_LEAD_RAD, project to BOSS_KITE_RANGE_PX
        # around the boss.  No dodge displacement applied in phase 1.
        import math
        expected_theta = math.pi + ap.BOSS_ORBIT_LEAD_RAD
        expected_x = (3400.0
                      + math.cos(expected_theta) * ap.BOSS_KITE_RANGE_PX)
        expected_y = (3200.0
                      + math.sin(expected_theta) * ap.BOSS_KITE_RANGE_PX)
        assert abs(captured["tx"] - expected_x) < 1.0
        assert abs(captured["ty"] - expected_y) < 1.0


class TestBossDodgeSignDeterministic:
    """The dodge sign was previously alternated with windup time at
    ~0.1 s flips, which locked the bot in a tight zigzag (21 dodge
    events at frozen bdist=143 in the 2026-05-11 telemetry).  Now
    the sign is deterministic for the entire windup, picked to
    point the dodge toward the Home Station so dodge + retreat
    combine."""

    def test_dodge_picks_station_side(self, monkeypatch):
        """Station NORTH of bot, boss EAST.  Perpendicular options
        are ±y.  The dodge must pick +y (north) to move toward
        station, not -y (south, away from station)."""
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 3200.0, "y": 5000.0,  # station NORTH
                        "building_type": "Home Station"}],
        )
        # Boss outside BOSS_CHARGE_PANIC_DIST_PX so the standard
        # perpendicular dodge (which picks the station-side sign)
        # fires, not the panic escape.
        s["boss"] = _boss(x=3700.0, y=3200.0, phase=2,
                          charging=True, windup=2.0)
        ap._act_engage_boss(s, s["player"])
        # The lure target sits between bot and station — assert the
        # commanded y is NORTH of the bot's current y (station side).
        assert captured["ty"] > 3200.0

    def test_dodge_sign_stable_across_windup_decay(self, monkeypatch):
        """The previous alternating-sign code flipped every 0.1 s as
        windup decayed.  Now repeated calls with decreasing windup
        must keep the same sign (station-side picks aren't
        influenced by windup magnitude)."""
        sign_values: list = []

        def _capture_dodge(event, **kw):
            if event == "engage_boss_dodge":
                sign_values.append(kw.get("sign"))

        monkeypatch.setattr(ap, "_telemetry_log", _capture_dodge)
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        ap._state.boss_lure_active = True  # skip lure-arm telemetry
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 3200.0, "y": 5000.0,
                        "building_type": "Home Station"}],
        )
        # Boss outside BOSS_CHARGE_PANIC_DIST_PX so the standard
        # perpendicular dodge fires and its sign is observable
        # (under panic the helper logs sign=0.0 for every call).
        for w in (2.0, 1.9, 1.8, 1.7, 1.0, 0.5, 0.1):
            s["boss"] = _boss(x=3700.0, y=3200.0, phase=2,
                              charging=True, windup=w)
            ap._act_engage_boss(s, s["player"])
        assert len(set(sign_values)) == 1, (
            f"dodge sign flipped during a single windup: {sign_values}")


class TestBossChargePanicEscape:
    """2026-05-13 thirteenth-pass pin: when the bot is too close to
    the boss during a charge windup, the standard perpendicular
    dodge displacement is dominated by the long-range kite/lure
    target vector -- bot drifts ALONGSIDE the boss instead of
    opening distance.  Captured 28 dodge events at frozen
    ``boss_dist=143 px`` across 1.9 s of a Phase 2 charge windup
    (boss collision radius is 114 + ship 25 = 139 px, so 143
    means one frame from a heavy collision bump).

    Fix: when ``boss_dist < BOSS_CHARGE_PANIC_DIST_PX`` and the
    boss is charging, override the kite target with a point
    directly away from the boss at ``BOSS_CHARGE_PANIC_ESCAPE_PX``.
    """

    def _record_goto(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        return captured

    def test_panic_fires_when_close_to_boss_during_charge(
            self, monkeypatch):
        """Bot 200 px from boss + charging => kite overridden to a
        point ``BOSS_CHARGE_PANIC_ESCAPE_PX`` PERPENDICULAR to the
        boss->bot axis from the bot's current position.  The
        previous panic direction was radial (directly away), but
        that put the bot in the same direction the boss dashes --
        boss caught up at 600 vs 150 px/s.  Perpendicular escape
        moves the bot off the dash line."""
        import math
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = True  # so lure target would
        # otherwise dominate; panic must override
        ap._state.boss_turret_assist_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 5000.0, "y": 5000.0,  # far NE
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=2,
                          charging=True, windup=1.5)
        ap._act_engage_boss(s, s["player"])
        # Bot at (3200, 3200), boss at (3400, 3200) => ux = -1, uy = 0,
        # perp = (-uy, ux) = (0, -1).  HS NE => station-side sign = -1
        # (so perp * sign = (0, +1) heads NORTH toward station).
        # Panic kite = bot + perp*sign*ESCAPE_PX = (3200, 3800).
        # The distance from BOT to kite must equal ESCAPE_PX exactly.
        bot_to_kite = math.hypot(captured["tx"] - 3200.0,
                                 captured["ty"] - 3200.0)
        assert abs(bot_to_kite
                   - ap.BOSS_CHARGE_PANIC_ESCAPE_PX) < 1.0
        # And the kite displacement is PERPENDICULAR to the boss->bot
        # axis (which is purely along x here): so the kite must have
        # changed y from the bot's y, not x.
        assert abs(captured["tx"] - 3200.0) < 1.0
        assert abs(captured["ty"] - 3200.0) > 100.0

    def test_panic_does_not_fire_outside_panic_range(
            self, monkeypatch):
        """Bot 500 px from boss + charging => standard
        perpendicular dodge (NOT panic)."""
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # 500 px east of bot -- outside BOSS_CHARGE_PANIC_DIST_PX=300.
        s["boss"] = _boss(x=3700.0, y=3200.0, phase=2,
                          charging=True, windup=1.5)
        ap._act_engage_boss(s, s["player"])
        # Standard perp dodge displaces kite y by ±250 px from the
        # boss->station-axis baseline (no HS here, so it's
        # boss->bot axis).  Panic would set kite at 600 from boss
        # along boss->bot ray with ty == 3200 (no displacement).
        # Confirm we are NOT in panic by checking |ty - 3200| > 100.
        assert abs(captured["ty"] - 3200.0) > 100.0, (
            "Boss at 500 px should fall outside panic range "
            "-- standard perpendicular dodge should fire instead")

    def test_panic_does_not_fire_when_not_charging(
            self, monkeypatch):
        """Bot 100 px from boss but boss NOT charging => no panic
        (panic only triggers on charge windup, not just proximity).
        """
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # 100 px east of bot -- well inside panic radius -- but boss
        # is not charging.
        s["boss"] = _boss(x=3300.0, y=3200.0, phase=2,
                          charging=False, windup=0.0)
        ap._act_engage_boss(s, s["player"])
        # No HS, no charge => standard orbit kite at desired_range
        # from boss.  Target distance from boss == BOSS_KITE_RANGE_PX.
        import math
        d = math.hypot(captured["tx"] - 3300.0,
                       captured["ty"] - 3200.0)
        # Panic would put target at ESCAPE_PX (600).  Standard kite
        # puts it at BOSS_KITE_RANGE_PX (750).  Differ enough to
        # tell them apart.
        assert abs(d - ap.BOSS_KITE_RANGE_PX) < 1.0

    def test_panic_logs_telemetry_with_panic_marker(
            self, monkeypatch):
        """Panic-escape branch emits an engage_boss_dodge event with
        a ``panic=True`` flag so post-hoc analysis can distinguish
        panic firings from standard dodges."""
        self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        events: list = []

        def _capture(event, **kw):
            if event == "engage_boss_dodge":
                events.append(kw)
        monkeypatch.setattr(ap, "_telemetry_log", _capture)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=2,
                          charging=True, windup=1.5)
        ap._act_engage_boss(s, s["player"])
        assert len(events) == 1
        assert events[0].get("panic") is True

    def test_panic_constants_sane(self):
        """Sanity gates on the panic constants -- the escape
        distance must be strictly greater than the panic-entry
        distance, otherwise the panic target would be inside the
        panic region itself and the bot would never exit."""
        assert (ap.BOSS_CHARGE_PANIC_ESCAPE_PX
                > ap.BOSS_CHARGE_PANIC_DIST_PX)

    def test_panic_escape_is_perpendicular_not_radial(
            self, monkeypatch):
        """2026-05-13 sixteenth-pass pin: the panic-escape kite
        target must sit PERPENDICULAR to the boss->bot axis, NOT
        along the radial (boss->bot) direction.  PR #112's
        original radial-escape sent the bot in the same direction
        the boss dashes -- boss caught up at 600 px/s, bot stuck
        at collision edge for 28 dodge ticks.
        """
        import math
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        # Boss directly east; bot west of boss => boss->bot axis
        # is purely along -x.  Perpendicular axis is y.  Panic
        # kite should sit on the y axis from the bot, NOT
        # further west along x.
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=2,
                          charging=True, windup=1.5)
        ap._act_engage_boss(s, s["player"])
        # Dot product of (kite - bot) and (bot - boss) must be ~0
        # (they're perpendicular).
        kx_minus_px = captured["tx"] - 3200.0
        ky_minus_py = captured["ty"] - 3200.0
        px_minus_bx = 3200.0 - 3400.0  # -200
        py_minus_by = 3200.0 - 3200.0  # 0
        dot = (kx_minus_px * px_minus_bx
               + ky_minus_py * py_minus_by)
        # Magnitudes: |kite-bot| should be ESCAPE_PX, |bot-boss|=200.
        # Perpendicular => |dot| << product of magnitudes.
        magnitude_product = (
            math.hypot(kx_minus_px, ky_minus_py)
            * math.hypot(px_minus_bx, py_minus_by))
        cos_angle = (dot / magnitude_product
                     if magnitude_product else 0.0)
        assert abs(cos_angle) < 0.01, (
            f"panic kite must be perpendicular to boss->bot axis; "
            f"cos(angle)={cos_angle:.3f} indicates non-perpendicular "
            f"displacement")

    def test_panic_escape_picks_station_side_perpendicular(
            self, monkeypatch):
        """The perpendicular axis has two directions.  Pick the
        sign that moves the bot toward the home station, so the
        panic-escape + retreat combine."""
        captured = self._record_goto(monkeypatch)
        ap._state.boss_lure_active = False
        ap._state.boss_turret_assist_active = False
        # Bot at origin, boss to the east, HS to the NORTH.
        # Perpendicular options are +y or -y.  Sign must pick +y
        # (toward station).
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 0.0, "y": 5000.0,  # HS due north
                        "building_type": "Home Station"}],
        )
        s["boss"] = _boss(x=200.0, y=0.0, phase=2,
                          charging=True, windup=1.5)
        ap._act_engage_boss(s, s["player"])
        # ty must be positive (toward station).
        assert captured["ty"] > 0.0, (
            "panic escape must pick the perpendicular sign that "
            "moves toward the home station")


class TestBossPhase3Press:
    """Phase 3 (no shield regen) => bot closes to ``BOSS_PHASE3_PRESS_RANGE_PX``."""

    def test_phase3_uses_press_range(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=3)
        ap._act_engage_boss(s, s["player"])
        import math
        d = math.hypot(captured["tx"] - 3400.0,
                       captured["ty"] - 3200.0)
        # Phase 3 uses BOSS_PHASE3_PRESS_RANGE_PX (600), not the
        # 750 px default kite.
        assert abs(d - ap.BOSS_PHASE3_PRESS_RANGE_PX) < 1.0


class TestQwiStagingGate:
    """``_qwi_ready_to_build`` predicate — Choice 1 staging gate."""

    def test_no_home_station_blocks(self):
        s = _state()
        ready, reason = ap._qwi_ready_to_build(s)
        assert ready is False
        assert reason == "no_home_station"

    def test_too_few_defenders_blocks(self):
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"}],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150,
                    "ship_level": 2},
        )
        ready, reason = ap._qwi_ready_to_build(s)
        assert ready is False
        assert reason.startswith("defenders_")

    def test_low_ship_level_blocks(self):
        # Defender count meets the staging minimum (6 = 2 starter +
        # 4 fortify) so the gate falls through to the ship-level
        # check.
        s = _state(
            buildings=[
                {"x": 3200.0, "y": 3200.0, "building_type": "Home Station"},
                {"x": 3300.0, "y": 3300.0, "building_type": "Turret 2"},
                {"x": 3100.0, "y": 3100.0, "building_type": "Turret 2"},
                {"x": 3300.0, "y": 3100.0, "building_type": "Turret 2"},
                {"x": 3100.0, "y": 3300.0, "building_type": "Turret 2"},
                {"x": 3200.0, "y": 3400.0, "building_type": "Turret 2"},
                {"x": 3200.0, "y": 3000.0, "building_type": "Turret 2"},
            ],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150,
                    "ship_level": 1},
        )
        ready, reason = ap._qwi_ready_to_build(s)
        assert ready is False
        assert reason.startswith("ship_level_")

    def test_all_conditions_met_returns_ready(self):
        s = _state(
            buildings=[
                {"x": 3200.0, "y": 3200.0, "building_type": "Home Station"},
                {"x": 3300.0, "y": 3300.0, "building_type": "Turret 2"},
                {"x": 3100.0, "y": 3100.0, "building_type": "Missile Array"},
                {"x": 3300.0, "y": 3100.0, "building_type": "Turret 2"},
                {"x": 3100.0, "y": 3300.0, "building_type": "Turret 2"},
                {"x": 3200.0, "y": 3400.0, "building_type": "Turret 2"},
                {"x": 3200.0, "y": 3000.0, "building_type": "Turret 2"},
            ],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150,
                    "ship_level": 2},
        )
        ready, reason = ap._qwi_ready_to_build(s)
        assert ready is True
        assert reason == "ok"


class TestBossEngageWeaponAndIntent:
    """Intent-driven ``engage_boss`` (sent via /intent) still routes
    through the new station-anchor handler — keeps the public API
    surface stable."""

    def test_engage_boss_intent_uses_basic_laser(self, monkeypatch):
        ensured: list = []
        monkeypatch.setattr(
            ap, "_ensure_weapon",
            lambda state, name: ensured.append(name))
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)

        class _FakeKey:
            @staticmethod
            def hold(name, on):
                pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state()
        s["boss"] = _boss(x=3400.0, y=3200.0)
        ap._do_engage_boss(s, s["player"])
        assert ensured == ["Basic Laser"]


# ── Post-consumable boss-prep pipeline ─────────────────────────────────────


def _drained_consumable_queue():
    """Reset the bot's craft queue to mimic 25 + 25 batches done."""
    q = ap._state.queue
    q.modules_to_craft.clear()
    q.modules_to_install.clear()
    q.repair_packs_remaining = 0
    q.shield_recharges_remaining = 0
    q.module_phase_started = True
    q.consumable_phase_started = True


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


class TestConsumablePhaseFinished:
    def test_fresh_queue_returns_false(self, _fresh_bot_state):
        assert ap._consumable_phase_finished() is False

    def test_drained_returns_true(self, _fresh_bot_state):
        _drained_consumable_queue()
        assert ap._consumable_phase_finished() is True

    def test_drained_but_phase_never_started_returns_false(
            self, _fresh_bot_state):
        q = ap._state.queue
        q.repair_packs_remaining = 0
        q.shield_recharges_remaining = 0
        q.consumable_phase_started = False
        assert ap._consumable_phase_finished() is False


class TestEquipConsumablesRouting:
    def test_routes_to_equip_when_phase_done_and_station_has_items(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_equip_consumables", lambda s, p: None)
        _drained_consumable_queue()
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"},
                       {"x": 3260.0, "y": 3200.0,
                        "building_type": "Basic Crafter"}],
            station_inventory_items={"repair_pack": 25,
                                     "shield_recharge": 25,
                                     "iron": 100},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_EQUIP_CONSUMABLES

    def test_skips_equip_when_consumables_already_equipped(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_build_qwi", lambda s, p: None)
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        # Pre-latch fortify so the FSM falls through past S_FORTIFY
        # into the BUILD_QWI branch — this test pins the equip-skip
        # behaviour, not the fortify gate (covered by
        # ``TestFortifyRouting`` below).
        ap._state.fortify_done = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"},
                       {"x": 3260.0, "y": 3200.0,
                        "building_type": "Basic Crafter"}],
            station_inventory_items={"iron": 2500},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_QWI


class TestPreBossMineRouting:
    def test_routes_to_pre_boss_mine_when_iron_below_target(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_do_mine_nearest", lambda s, p: None)
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"},
                       {"x": 3260.0, "y": 3200.0,
                        "building_type": "Basic Crafter"}],
            station_inventory_items={"iron": 500},
            asteroids=[{"x": 3400.0, "y": 3200.0, "hp": 100}],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_PRE_BOSS_MINE


class TestBuildQwiRouting:
    def test_routes_to_build_qwi_when_iron_target_met(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_build_qwi", lambda s, p: None)
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        # Pre-latch fortify so this test stays scoped to the
        # iron-target → BUILD_QWI behaviour.  Fortify routing is
        # covered separately by ``TestFortifyRouting``.
        ap._state.fortify_done = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"},
                       {"x": 3260.0, "y": 3200.0,
                        "building_type": "Basic Crafter"}],
            station_inventory_items={"iron": 2500},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_QWI

    def test_skips_when_qwi_already_placed(
            self, _clock, _fresh_bot_state, monkeypatch):
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        ap._state.qwi_placed = True
        s = _state(
            buildings=[
                {"x": 3200.0, "y": 3200.0, "building_type": "Home Station"},
                {"x": 3260.0, "y": 3200.0, "building_type": "Basic Crafter"},
                {"x": 3200.0, "y": 3000.0,
                 "building_type": "Quantum Wave Integrator"},
            ],
            station_inventory_items={"iron": 2500},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] not in (ap.S_BUILD_QWI,
                                        ap.S_EQUIP_CONSUMABLES,
                                        ap.S_PRE_BOSS_MINE)

    def test_boss_alive_takes_priority_over_pipeline(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_engage_boss", lambda s, p: None)
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"}],
            station_inventory_items={"iron": 2500},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE_BOSS


class TestFortifyRouting:
    """Pins the S_FORTIFY phase: fortify must fire after consumables
    are equipped and the iron buffer is staged, before BUILD_QWI."""

    def test_routes_to_fortify_after_equip_when_iron_target_met(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_fortify", lambda s, p: None)
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        # Only the 2 starter turrets — fortify gate is open.
        s = _state(
            buildings=[
                {"x": 3200.0, "y": 3200.0, "building_type": "Home Station"},
                {"x": 3260.0, "y": 3200.0, "building_type": "Basic Crafter"},
                {"x": 3300.0, "y": 3300.0, "building_type": "Turret 2"},
                {"x": 3100.0, "y": 3100.0, "building_type": "Turret 2"},
            ],
            station_inventory_items={"iron": 2500},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FORTIFY

    def test_short_circuits_fortify_done_when_ring_already_placed(
            self, _clock, _fresh_bot_state, monkeypatch):
        """When the world snapshot already has 6+ defenders (e.g.
        loaded save / manual placement), the housekeeping short-
        circuit at the top of ``_choose_next_state`` latches
        ``fortify_done`` so the FSM never enters S_FORTIFY."""
        monkeypatch.setattr(ap, "_act_build_qwi", lambda s, p: None)
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        # 6 defenders already on the field.
        s = _state(
            buildings=[
                {"x": 3200.0, "y": 3200.0, "building_type": "Home Station"},
                {"x": 3260.0, "y": 3200.0, "building_type": "Basic Crafter"},
                {"x": 3300.0, "y": 3300.0, "building_type": "Turret 2"},
                {"x": 3100.0, "y": 3100.0, "building_type": "Turret 2"},
                {"x": 3300.0, "y": 3100.0, "building_type": "Turret 2"},
                {"x": 3100.0, "y": 3300.0, "building_type": "Turret 2"},
                {"x": 3200.0, "y": 3400.0, "building_type": "Turret 2"},
                {"x": 3200.0, "y": 3000.0, "building_type": "Turret 2"},
            ],
            station_inventory_items={"iron": 2500},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._state.fortify_done is True
        assert ap._fsm["state"] == ap.S_BUILD_QWI

    def test_skips_fortify_when_already_done(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Once ``fortify_done`` is latched (success or short-
        circuit), the FSM falls through to the BUILD_QWI branch."""
        monkeypatch.setattr(ap, "_act_build_qwi", lambda s, p: None)
        _drained_consumable_queue()
        ap._state.consumables_equipped = True
        ap._state.fortify_done = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"},
                       {"x": 3260.0, "y": 3200.0,
                        "building_type": "Basic Crafter"}],
            station_inventory_items={"iron": 2500},
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_QWI


class TestActEquipConsumables:
    def test_travels_to_home_station_when_far(
            self, _fresh_bot_state, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        monkeypatch.setattr(ap, "_post_equip_consumables", lambda: None)

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 3500.0, "y": 3500.0,
                        "building_type": "Home Station"}],
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_equip_consumables(s, s["player"])
        assert captured["tx"] == 3500.0
        assert captured["ty"] == 3500.0
        assert ap._state.consumables_equipped is False

    def test_posts_when_in_range_and_latches_on_success(
            self, _fresh_bot_state, monkeypatch):
        called: list = []

        def fake_post():
            called.append(True)
            return {"ok": True, "repair_pack": 25,
                    "shield_recharge": 25,
                    "repair_slot": 0, "shield_slot": 1}
        monkeypatch.setattr(ap, "_post_equip_consumables", fake_post)

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_equip_consumables(s, s["player"])
        assert called == [True]
        assert ap._state.consumables_equipped is True

    def test_latches_when_station_already_empty(
            self, _fresh_bot_state, monkeypatch):
        def fake_post():
            return {"ok": False,
                    "reason": "no consumables in station inventory"}
        monkeypatch.setattr(ap, "_post_equip_consumables", fake_post)

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_equip_consumables(s, s["player"])
        assert ap._state.consumables_equipped is True


class TestActBuildQwi:
    def test_posts_when_in_range_and_latches(
            self, _fresh_bot_state, monkeypatch):
        def fake_post():
            return {"ok": True, "placed_at": [3200.0, 3000.0],
                    "boss_spawned": True}
        monkeypatch.setattr(ap, "_post_place_qwi", fake_post)

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_build_qwi(s, s["player"])
        assert ap._state.qwi_placed is True

    def test_already_placed_response_latches(
            self, _fresh_bot_state, monkeypatch):
        def fake_post():
            return {"ok": False, "reason": "QWI already placed"}
        monkeypatch.setattr(ap, "_post_place_qwi", fake_post)

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_build_qwi(s, s["player"])
        assert ap._state.qwi_placed is True


class TestStationPostSkipAfterLatch:
    """The FSM keeps the bot in a station-post state (EQUIP_CONSUMABLES /
    FORTIFY / BUILD_QWI) for the full MIN_DWELL_S window even after the
    POST succeeds and the latch fires, because the next ``desired``
    state has to outwait MIN_DWELL_S before the transition fires.  The
    action handler is called every tick during that wait -- pre-fix the
    second-through-Nth call would re-POST the endpoint, the server
    would respond "no consumables in station inventory" / "already
    placed", and the bot would burn 8-10 HTTP round-trips per latch.

    2026-05-10 telemetry: equip_post_success at t=0.1s followed by 9
    equip_post_failure events at t=0.2-1.0s, all latched=True with
    reason "no consumables in station inventory".  This test class
    pins the fix: a second call to any of the three handlers after
    the latch is already set short-circuits to _do_idle without
    POSTing.
    """

    @staticmethod
    def _fake_key():
        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass
        return _FakeKey

    def _at_station(self):
        return _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )

    def test_equip_skips_post_when_already_latched(
            self, _fresh_bot_state, monkeypatch):
        called: list = []

        def fake_post():
            called.append(True)
            return {"ok": False,
                    "reason": "no consumables in station inventory"}
        monkeypatch.setattr(ap, "_post_equip_consumables", fake_post)
        monkeypatch.setattr(ap, "KeyState", self._fake_key())
        ap._state.consumables_equipped = True

        ap._act_equip_consumables(self._at_station(),
                                  self._at_station()["player"])

        assert called == [], (
            "expected zero POSTs once the consumables_equipped latch "
            f"is set; got {len(called)}")

    def test_fortify_skips_post_when_already_latched(
            self, _fresh_bot_state, monkeypatch):
        called: list = []

        def fake_post():
            called.append(True)
            return {"ok": False, "reason": "ring already complete"}
        monkeypatch.setattr(ap, "_post_fortify", fake_post)
        monkeypatch.setattr(ap, "KeyState", self._fake_key())
        ap._state.fortify_done = True

        ap._act_fortify(self._at_station(),
                        self._at_station()["player"])

        assert called == []

    def test_build_qwi_skips_post_when_already_latched(
            self, _fresh_bot_state, monkeypatch):
        called: list = []

        def fake_post():
            called.append(True)
            return {"ok": False, "reason": "QWI already placed"}
        monkeypatch.setattr(ap, "_post_place_qwi", fake_post)
        monkeypatch.setattr(ap, "KeyState", self._fake_key())
        ap._state.qwi_placed = True

        ap._act_build_qwi(self._at_station(),
                          self._at_station()["player"])

        assert called == []

    def test_equip_still_posts_when_latch_not_set(
            self, _fresh_bot_state, monkeypatch):
        """Regression: the new skip guard must NOT fire when the
        latch hasn't flipped yet -- the very first call this session
        must still POST.  Pins the asymmetry: pre-latch POST, post-
        latch skip."""
        called: list = []

        def fake_post():
            called.append(True)
            return {"ok": True, "repair_pack": 25,
                    "shield_recharge": 25,
                    "repair_slot": 0, "shield_slot": 1}
        monkeypatch.setattr(ap, "_post_equip_consumables", fake_post)
        monkeypatch.setattr(ap, "KeyState", self._fake_key())
        assert ap._state.consumables_equipped is False

        ap._act_equip_consumables(self._at_station(),
                                  self._at_station()["player"])

        assert called == [True]
        assert ap._state.consumables_equipped is True

    def test_post_burst_replicates_pre_fix_pathology(
            self, _fresh_bot_state, monkeypatch):
        """Drive the handler 10 ticks in a row at-station; the first
        tick POSTs and latches, the remaining 9 must skip.  Matches
        the pre-fix telemetry pattern (1 success + 9 failures within
        the 1-second MIN_DWELL_S window) and is the strongest
        regression signal."""
        call_results = [
            {"ok": True, "repair_pack": 25, "shield_recharge": 25,
             "repair_slot": 0, "shield_slot": 1},
        ] + [
            {"ok": False, "reason": "no consumables in station inventory"}
        ] * 9
        idx = [0]

        def fake_post():
            r = call_results[idx[0]] if idx[0] < len(call_results) else (
                {"ok": False, "reason": "exhausted"})
            idx[0] += 1
            return r
        monkeypatch.setattr(ap, "_post_equip_consumables", fake_post)
        monkeypatch.setattr(ap, "KeyState", self._fake_key())

        for _ in range(10):
            ap._act_equip_consumables(self._at_station(),
                                      self._at_station()["player"])

        # Exactly one POST -- the rest short-circuited via the
        # latch_already_set guard.
        assert idx[0] == 1, (
            f"expected exactly 1 POST across 10 ticks once the "
            f"latch is set; got {idx[0]}.  Pre-fix this was 10 "
            f"(1 success + 9 'no consumables' retries).")
        assert ap._state.consumables_equipped is True


class TestMaybeUseConsumables:
    def test_low_hp_with_repair_pack_fires_slot(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 30, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0]

    def test_low_shields_with_recharge_fires_slot(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        # Shields at 20 % (CONSUMABLE_USE_SHIELD_PCT) -- last-resort
        # threshold so kite + lure get the first try at managing damage.
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 25, "max_shields": 150},  # ~17 %
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [1]

    def test_shields_above_last_resort_threshold_does_not_fire(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Shields at 33 % -- above the 20 % last-resort threshold.
        Bot should rely on kite + lure to manage this, not burn a
        shield-recharge charge."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 50, "max_shields": 150},  # 33 %
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == []

    def test_full_hp_and_shields_does_nothing(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == []

    def test_empty_quick_use_slots_does_nothing(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 30, "max_hp": 100,
                    "shields": 30, "max_shields": 150},
        )
        ap._maybe_use_consumables(s, s["player"])
        assert captured == []

    def test_zero_count_slot_skipped(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 30, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 0},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == []

    def test_cooldown_suppresses_back_to_back_fires(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 30, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        _clock[0] += ap.CONSUMABLE_USE_COOLDOWN_S * 0.5
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0]
        _clock[0] += ap.CONSUMABLE_USE_COOLDOWN_S * 1.5
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0, 0]


class TestHealActiveLatch:
    """Heal-active latches keep firing until the bar reaches max,
    matching the user spec ("use until 100%").  Without the latch
    one 50%-heal use would leave the bot at e.g. 80% HP — above the
    50% re-trigger threshold, so no second fire."""

    def test_hp_latch_arms_when_threshold_crosses(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_post_use_quick_use",
                            lambda slot: {"ok": True})
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 30, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is True

    def test_hp_latch_disarms_when_full(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_post_use_quick_use",
                            lambda slot: {"ok": True})
        # Pre-arm the latch then feed full HP — must disarm.
        ap._state.heal_hp_active = True
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 100, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is False

    def test_hp_latch_stays_armed_at_intermediate_hp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If HP rose to 80 % (above 50 % threshold but below max),
        the latch must STAY armed so the next tick still fires.
        This is the spec-correctness test — under the old
        threshold-only logic the latch never existed and the bot
        would stop firing here."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        ap._state.heal_hp_active = True
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 80, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is True
        assert captured == [0]   # fires even at 80 % because latch armed

    def test_shield_latch_independent_from_hp_latch(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Arming one latch must not affect the other."""
        monkeypatch.setattr(ap, "_post_use_quick_use",
                            lambda slot: {"ok": True})
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 100, "max_hp": 100,    # full HP
                    "shields": 30, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is False
        assert ap._state.heal_shield_active is True

    def test_latch_keeps_firing_across_ticks_until_full(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Simulates the user's exact spec: HP drops to 30 %, the
        bot must fire repeatedly (not just once) until HP reaches
        100 %.  Each fire bumps HP by 50 % of max in the test
        harness, mirroring the in-game heal."""
        captured: list = []

        def fake_post(slot):
            captured.append(slot)
            # Simulate the heal landing — bump HP by 50 %.
            s["player"]["hp"] = min(
                s["player"]["max_hp"],
                s["player"]["hp"] + int(s["player"]["max_hp"] * 0.5))
            return {"ok": True}

        monkeypatch.setattr(ap, "_post_use_quick_use", fake_post)
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 30, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        # Tick 1: arm + fire (hp 30 -> 80).
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0]
        assert s["player"]["hp"] == 80
        # Tick 2 after cooldown: latch still armed, fire again
        # (hp 80 -> 100).
        _clock[0] += ap.CONSUMABLE_USE_COOLDOWN_S + 0.1
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0, 0]
        assert s["player"]["hp"] == 100
        # Tick 3 after cooldown: latch disarms, no fire.
        _clock[0] += ap.CONSUMABLE_USE_COOLDOWN_S + 0.1
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0, 0]
        assert ap._state.heal_hp_active is False

    def test_latch_stops_firing_when_consumable_runs_out(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If the consumable count drops to 0 mid-heal, the auto-use
        loop must NOT spam the endpoint — _find_quick_use_slot
        returns None for count=0 slots."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        ap._state.heal_hp_active = True
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 30, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 0},
        ]
        ap._maybe_use_consumables(s, s["player"])
        # Latch stays armed (HP < max), but no fire.
        assert captured == []
        assert ap._state.heal_hp_active is True


class TestActAtStationHelper:
    """The shared travel-and-post helper produces telemetry events
    for both success and failure paths, and the failure-keyword
    matcher latches the right field on known failure modes."""

    def test_emits_post_success_telemetry(
            self, _fresh_bot_state, monkeypatch):
        events: list = []
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        monkeypatch.setattr(ap, "_post_equip_consumables",
                            lambda: {"ok": True, "repair_pack": 25,
                                     "shield_recharge": 25})

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_equip_consumables(s, s["player"])
        success_events = [e for (e, _) in events
                          if e == "equip_post_success"]
        assert len(success_events) == 1

    def test_emits_post_failure_telemetry_with_latched_flag(
            self, _fresh_bot_state, monkeypatch):
        events: list = []
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        monkeypatch.setattr(
            ap, "_post_equip_consumables",
            lambda: {"ok": False,
                     "reason": "no consumables in station inventory"})

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_equip_consumables(s, s["player"])
        # Locate the equip_post_failure event and confirm it
        # captures latched=True.
        fails = [kw for (e, kw) in events
                 if e == "equip_post_failure"]
        assert len(fails) == 1
        assert fails[0]["latched"] is True

    def test_unknown_failure_does_not_latch(
            self, _fresh_bot_state, monkeypatch):
        events: list = []
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        # A "transport failure" reason isn't in the equip latch
        # keyword list, so the latch must NOT flip.
        monkeypatch.setattr(
            ap, "_post_equip_consumables",
            lambda: None)   # transport failure

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass
            @staticmethod
            def release_all(): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            buildings=[{"x": 1000.0, "y": 1000.0,
                        "building_type": "Home Station"}],
            player={"x": 1050.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        ap._act_equip_consumables(s, s["player"])
        assert ap._state.consumables_equipped is False
        fails = [kw for (e, kw) in events
                 if e == "equip_post_failure"]
        assert len(fails) == 1
        assert fails[0]["latched"] is False


class TestEngageBossDodgeTelemetry:
    """The Phase-2 charge dodge in _act_engage_boss now emits a
    telemetry event so live runs can be analyzed."""

    def test_dodge_emits_event_when_charging(self, monkeypatch):
        events: list = []
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=2,
                          charging=True, windup=2.0)
        ap._act_engage_boss(s, s["player"])
        dodge_events = [kw for (e, kw) in events
                        if e == "engage_boss_dodge"]
        assert len(dodge_events) == 1
        assert dodge_events[0]["phase"] == 2

    def test_no_dodge_event_when_not_charging(self, monkeypatch):
        events: list = []
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_ensure_weapon", lambda *a, **kw: None)

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["boss"] = _boss(x=3400.0, y=3200.0, phase=1)
        ap._act_engage_boss(s, s["player"])
        dodge_events = [e for (e, _) in events
                        if e == "engage_boss_dodge"]
        assert dodge_events == []
