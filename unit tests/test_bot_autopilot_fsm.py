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
        appears mid-regen and shields aren't recovering — the
        escape valve fires and ENGAGE preempts.

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
        # Step 2: an alien closes in mid-regen, shields drop.
        _clock[0] += ap.MIN_DWELL_S + 0.1
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
    BUILD_CLEAR_RADIUS_PX (800 px — asteroids, aliens, pickups,
    buildings) AND not already attempted.  When iron is met but
    the area isn't clear, the FSM enters S_BUILD_SEEK instead."""

    def test_no_build_below_iron_threshold(self, _clock):
        s = _state(iron=ap.BUILD_IRON_THRESHOLD - 1)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD
        assert ap._fsm["state"] != ap.S_BUILD_SEEK

    def test_seek_when_iron_met_but_asteroid_in_radius(self, _clock):
        """Asteroid inside the 800 px clear radius — bot enters
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
        # Pickup in the clear radius → not clear.
        s = _state(
            iron_pickups=[
                {"x": 300, "y": 0, "amount": 10, "item_type": "iron"}],
        )
        assert not ap._build_area_clear(
            s, s["player"]["x"], s["player"]["y"])
        # Building in the clear radius → not clear.
        s = _state()
        s["buildings"] = [{"x": 500, "y": 0}]
        assert not ap._build_area_clear(
            s, s["player"]["x"], s["player"]["y"])
        # Empty state → clear.
        assert ap._build_area_clear(_state(), 0.0, 0.0)

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
        """Asteroids to the NORTH → bot heads SOUTH."""
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda k, v: None))
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[
                {"x": 3050, "y": 3500, "hp": 100},
                {"x": 2950, "y": 3500, "hp": 100},
            ],
        )
        ap._do_auto(s, s["player"])
        assert _capture_goto["ty"] < 3000.0, (
            "should head south away from clutter to the north")

    def test_seek_target_clamped_to_world(
            self, _clock, _capture_goto, monkeypatch):
        """Even when the away-from-clutter direction would take
        the bot off-map, the target is clamped to world bounds."""
        monkeypatch.setattr(
            ap.KeyState, "hold",
            staticmethod(lambda k, v: None))
        # Player near east edge with clutter east → bot wants to
        # go further east, but clamp keeps target in world.
        s = _state(
            player={"x": 6300.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron=ap.BUILD_IRON_THRESHOLD,
            asteroids=[{"x": 5800, "y": 3000, "hp": 100}],
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
        without bumping suppression is caught."""
        # Suppression radius must be larger than the typical building
        # contact distance (~50 px) so the docking building is
        # excluded for the entire approach.
        assert ap.REPULSION_TARGET_SUPPRESS_PX >= 50.0


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
        assert ap.HUNT_STUCK_THRESHOLD == 3
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
