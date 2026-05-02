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
           iron=0, world_w=6400, world_h=6400):
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
        "menu": {},
        "assist": {"melee_engaged": melee_engaged},
        "inventory": {"items": {"iron": int(iron)}},
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

    def test_regen_holds_against_alien_threat(self, _clock):
        """REGEN now sits *above* ENGAGE in the priority order: when
        shields are below 40 %, the bot stays idle even with an
        alien within engagement range.  Combat assist still aims +
        fires every frame so the bot isn't defenseless -- it just
        doesn't burn thrust chasing a fight at low health."""
        s = _state(
            player={
                "x": 0, "y": 0, "heading": 0,
                "shields": 30, "max_shields": 150,
            },
            aliens=[{"x": 400, "y": 0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN
        # Hold for several ticks: even with the alien still present,
        # REGEN must persist until shields cross the 60 % exit band.
        for _ in range(3):
            _clock[0] += 0.1
            ap._do_auto(s, s["player"])
            assert ap._fsm["state"] == ap.S_REGEN

    def test_engage_drops_to_regen_when_shields_collapse(self, _clock):
        """Active engagement; shields drop into REGEN territory --
        the FSM must abandon the chase and idle.  REGEN preempts
        MIN_DWELL just like ENGAGE does, so the switch lands on
        the same tick the shields cross the 40 % enter band."""
        s = _state(
            aliens=[{"x": 400, "y": 0, "hp": 50}],
            player={
                "x": 0, "y": 0, "heading": 0,
                "shields": 150, "max_shields": 150,
            },
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE
        # Shields collapse mid-engagement.
        s["player"]["shields"] = 30
        _clock[0] += 0.05    # well inside MIN_DWELL_S
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "REGEN must preempt ENGAGE without waiting for dwell")


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

    def _drive_ticks_at(self, _clock, x, y, n):
        """Run n ticks with the player frozen at (x, y).  No
        asteroids/aliens/pickups so the FSM lands in SEARCH."""
        for _ in range(n):
            s = _state(player={
                "x": x, "y": y, "heading": 0.0,
                "shields": 150, "max_shields": 150,
            })
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1   # 10 Hz

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

    def test_escape_targets_world_centre(self, _clock, monkeypatch):
        """During the escape override, _do_goto should be called with
        the world centre as the target — not whatever spiral / mine
        target was previously aiming off-map."""
        captured: dict = {}
        def _spy(state, p, tx, ty, stop_radius=80.0):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        # Pin near the bottom edge of a 6400×6400 world.
        for _ in range(20):
            s = _state(player={
                "x": 3200.0, "y": 50.0, "heading": 0.0,
                "shields": 150, "max_shields": 150,
            })
            ap._do_auto(s, s["player"])
            _clock[0] += 0.1
        # Most-recent dispatch was the escape — target should be
        # the world centre (3200, 3200).
        assert captured.get("tx") == 3200.0
        assert captured.get("ty") == 3200.0

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

    def test_escape_clears_when_ship_well_inside_world(
            self, _clock):
        """Once min duration has elapsed AND the ship is clear of
        all edges by the safety margin, the override drops and the
        FSM resumes normal flow."""
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        assert ap._stuck_state["escape_until"] > 0.0
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        # Ship has now moved well clear of every edge.
        s = _state(player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                            "shields": 150, "max_shields": 150})
        ap._do_auto(s, s["player"])
        assert ap._stuck_state["escape_until"] == 0.0

    def test_stuck_re_anchors_spiral_to_world_centre(self, _clock):
        """Re-anchoring the spiral to the world centre on stuck
        means a follow-up SEARCH after escape doesn't re-pin —
        otherwise SEARCH would re-anchor at the bot's edge
        position and immediately spiral back into the wall."""
        self._drive_ticks_at(_clock, 100.0, 100.0, n=20)
        assert ap._spiral_state["anchor"] == (3200.0, 3200.0)

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
        def _spy(state, p, tx, ty, stop_radius=80.0):
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


class TestStuckCentreLockout:
    """After a stuck-escape, the FSM is locked into SEARCH for
    STUCK_CENTRE_LOCKOUT_S seconds so MINE / GATHER / BUILD can't
    immediately retarget whatever edge-adjacent object pulled the
    bot into the wall.  ENGAGE + REGEN still preempt as defensive
    interrupts."""

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

    def test_lockout_set_on_stuck_trigger(self, _clock):
        self._trigger_stuck(_clock)
        assert ap._stuck_state["centre_lockout_until"] > _clock[0]

    def test_mine_suppressed_during_lockout(self, _clock):
        """Even with an asteroid in state, the FSM stays in
        SEARCH for the lockout duration."""
        self._trigger_stuck(_clock)
        # Move past the escape window so we're in lockout but
        # FSM dispatches normally.
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3300.0, "y": 3200.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_SEARCH, (
            "lockout should suppress MINE in favour of SEARCH")

    def test_engage_still_preempts_lockout(self, _clock):
        """Combat priority: even during lockout, an alien within
        ENGAGE range still triggers ENGAGE."""
        self._trigger_stuck(_clock)
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 3500.0, "y": 3200.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_regen_still_preempts_lockout(self, _clock):
        """Defensive priority: low shields → REGEN even during
        lockout."""
        self._trigger_stuck(_clock)
        _clock[0] += ap.STUCK_ESCAPE_MIN_DURATION_S + 0.1
        s = _state(player={
            "x": 3200.0, "y": 3200.0, "heading": 0.0,
            "shields": 30, "max_shields": 150,   # 20 % < 40 %
        })
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_lockout_expires(self, _clock):
        """After STUCK_CENTRE_LOCKOUT_S elapses, normal FSM
        priorities resume and MINE can fire again."""
        self._trigger_stuck(_clock)
        # Jump well past the lockout window.
        _clock[0] += ap.STUCK_CENTRE_LOCKOUT_S + ap.MIN_DWELL_S + 1.0
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 3300.0, "y": 3200.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_MINE
