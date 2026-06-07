"""BUILD / CRAFT / INSTALL / IDLE_AT_BASE / DEPOSIT tests.

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


class TestModuleSwap:
    """2026-06-02: the ship's 4 slots fill with the MAIN loadout, so the
    three Nebula modules (misty_step / force_wall / death_blossom) could
    never be installed -- a crafting dead-end.  ``_module_swap_plan``
    frees a slot by uninstalling a non-target module, and ``_act_install``
    posts the uninstall before the install."""

    _FULL_MAIN = ["broadside", "shield_booster",
                  "shield_enhancer", "armor_plate"]

    def test_swap_plan_drops_non_target_when_slots_full(self, _clock):
        s = _state(module_slots=list(self._FULL_MAIN))
        ap._state.queue.modules_to_install = ["death_blossom"]
        # First installed module not in NEBULA_TARGET_LOADOUT.
        assert ap._module_swap_plan(s) == "shield_booster"

    def test_swap_plan_keeps_target_modules(self, _clock):
        # broadside IS in the target loadout, so it's never the drop.
        s = _state(module_slots=["broadside", "death_blossom",
                                  "force_wall", "armor_plate"])
        ap._state.queue.modules_to_install = ["misty_step"]
        assert ap._module_swap_plan(s) == "armor_plate"

    def test_swap_plan_none_when_free_slot(self, _clock):
        s = _state(module_slots=["broadside", None, None, None])
        ap._state.queue.modules_to_install = ["death_blossom"]
        assert ap._module_swap_plan(s) is None

    def test_swap_plan_none_for_non_target_head(self, _clock):
        # The queued module isn't in the target loadout -> never swap a
        # slot out for it.
        s = _state(module_slots=list(self._FULL_MAIN))
        ap._state.queue.modules_to_install = ["engine_booster"]
        assert ap._module_swap_plan(s) is None

    def test_swap_plan_none_when_head_already_installed(self, _clock):
        s = _state(module_slots=["broadside", "death_blossom",
                                  "shield_enhancer", "armor_plate"])
        ap._state.queue.modules_to_install = ["death_blossom"]
        assert ap._module_swap_plan(s) is None

    def test_act_install_posts_uninstall_to_make_room(
            self, _clock, monkeypatch):
        install_calls: list = []
        uninstall_calls: list = []
        monkeypatch.setattr(
            ap, "_post_install_module",
            lambda mod_key, timeout_s=5.0: (install_calls.append(mod_key)
                                            or {"ok": True, "slot": 0}))
        monkeypatch.setattr(
            ap, "_post_uninstall_module",
            lambda mod_key, timeout_s=5.0: (uninstall_calls.append(mod_key)
                                            or {"ok": True, "slot": 1}))
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[_hs_building(x=3200.0, y=3200.0),
                       _crafter_building()],
            station_inventory_items={"mod_death_blossom": 1},
            module_slots=list(self._FULL_MAIN),
        )
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_install = ["death_blossom"]
        ap._do_auto(s, s["player"])
        # Slot is full, so the swap fires FIRST: uninstall a non-target
        # module; the install is deferred to the next tick.
        assert uninstall_calls == ["shield_booster"]
        assert install_calls == []
        # Install queue untouched -- death_blossom still pending.
        assert ap._state.queue.modules_to_install[0] == "death_blossom"




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

    def test_gate_fires_before_consumable_phase_finished(
            self, _clock, _fresh_bot_state, monkeypatch):
        """2026-06-03: equipping is decoupled from the full 25+25
        consumable phase.  With a shield_recharge in the station and an
        empty quick-use slot, the bot binds it immediately even though
        the phase hasn't finished (batches still remaining) -- so it has
        a working heal while it crafts the rest.  Captured:
        heal_shield_fire = 0 across a 9-death session because the old
        gate refused to equip until the whole phase completed and the
        deaths kept resetting the grind."""
        monkeypatch.setattr(
            ap, "_act_equip_consumables", lambda s, p: None)
        ap._state.consumables_equipped = False
        # Phase NOT finished: started, but batches still remaining.
        ap._state.queue.consumable_phase_started = True
        ap._state.queue.repair_packs_remaining = 3
        ap._state.queue.shield_recharges_remaining = 4
        ap._state.build_done = True
        assert ap._consumable_phase_finished() is False  # precondition
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"}],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items={"shield_recharge": 5},
        )
        s["quick_use_slots"] = [
            {"item_type": None, "count": 0},
            {"item_type": None, "count": 0},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_EQUIP_CONSUMABLES
        assert ap._state.consumables_equipped is False

    def test_gate_fires_for_shield_when_only_repair_equipped(
            self, _clock, _fresh_bot_state, monkeypatch):
        """2026-06-06: a bound repair_pack must NOT mask a MISSING
        shield_recharge.  Captured: the bot kept its repair packs
        equipped (25 hp-heal fires), so the old "any consumable equipped"
        gate skipped, and 5-15 shield_recharge sat in the station
        unequipped for ~540 s -> the shield heal never fired -> death at
        1 shield.  With shield_recharge in the station but absent from
        the slots, EQUIP must fire even though repair_pack is bound."""
        monkeypatch.setattr(
            ap, "_act_equip_consumables", lambda s, p: None)
        ap._state.consumables_equipped = True   # stale
        ap._state.queue.consumable_phase_started = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.build_done = True
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0,
                        "building_type": "Home Station"}],
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items={"shield_recharge": 5},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 10},   # repair bound...
            {"item_type": None, "count": 0},             # ...shield empty
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_EQUIP_CONSUMABLES

    def test_gate_skips_when_missing_type_absent_from_station(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Don't fire EQUIP for a missing type the station can't supply:
        repair_pack bound, shield slot empty, but station has only
        repair packs (no shield_recharge) -> nothing useful to equip."""
        monkeypatch.setattr(
            ap, "_act_equip_consumables", lambda s, p: None)
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
            station_inventory_items={"repair_pack": 5},   # no shield stock
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 10},
            {"item_type": None, "count": 0},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_EQUIP_CONSUMABLES



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
        """Shields at 40 % -- above the 35 % last-resort threshold
        (raised from 20 % in the 2026-05-30 tuning pass).  Bot should
        rely on kite + lure to manage this, not burn a shield-recharge
        charge.  No aliens nearby so the base (non-swarm) threshold
        applies."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 60, "max_shields": 150},  # 40 %
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

    def test_shield_heal_swarm_threshold_fires_earlier(
            self, _clock, _fresh_bot_state, monkeypatch):
        """2026-05-30 density-aware arm threshold.  Shields at 50 %
        is below the swarm threshold (55 %) but above the base
        threshold (35 %).  With a dense swarm on top of the bot the
        heal should fire; with no swarm it should NOT (kite + lure
        manage the smaller dip).  Captured pathology: 50-60 alien
        swarms drained shields ~37 px/s, so 35 % was too late."""
        # Surrounded: CONSUMABLE_SWARM_ALIEN_COUNT aliens inside
        # CONSUMABLE_SWARM_RANGE_PX of the bot.
        aliens = [{"x": 100.0 * i, "y": 0.0, "hp": 50}
                  for i in range(ap.CONSUMABLE_SWARM_ALIEN_COUNT)]
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 60, "max_shields": 120},  # 50 %
            aliens=aliens,
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [1], "swarm threshold should fire at 50 %"

    def test_shield_heal_no_swarm_holds_at_50pct(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Same 50 % shields but only a single alien nearby -- below
        the swarm count, so the base 35 % threshold applies and the
        heal must NOT fire."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 60, "max_shields": 120},  # 50 %
            aliens=[{"x": 100.0, "y": 0.0, "hp": 50}],
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [], "base threshold must not fire at 50 %"

    def test_shield_heal_swarm_threshold_ignores_distant_aliens(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Many aliens but all OUTSIDE CONSUMABLE_SWARM_RANGE_PX --
        the bot isn't actually surrounded, so the base threshold
        applies and the 50 % dip does not fire a heal."""
        far = ap.CONSUMABLE_SWARM_RANGE_PX + 500.0
        aliens = [{"x": far + 50.0 * i, "y": 0.0, "hp": 50}
                  for i in range(ap.CONSUMABLE_SWARM_ALIEN_COUNT + 2)]
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 60, "max_shields": 120},  # 50 %
            aliens=aliens,
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
            {"item_type": "shield_recharge", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [], "distant aliens don't count as a swarm"




class TestHealActiveLatch:
    """Heal-active latches keep firing until the bar reaches the
    DISARM band (~70 %).  Updated 2026-05-19 from the original
    "fire until 100 %" spec: telemetry showed 32 heal_shield_fire
    events from 16 arms in one session (and 44 hp_fire / 22 hp arms)
    -- the next-tick check after a 50 %-heal use saw the bar still
    <100 % and fired a second charge that overhealed.  Disarming at
    70 % caps the single-event spend at one charge while leaving
    sustained-damage scenarios handled via natural re-arming when
    the bar dips back below ``CONSUMABLE_USE_*_PCT``."""

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

    def test_hp_latch_disarms_at_disarm_threshold(
            self, _clock, _fresh_bot_state, monkeypatch):
        """HP reaches CONSUMABLE_DISARM_HP_PCT (~ 70 %) -- the
        latch must disarm and the next-cooldown tick must NOT
        fire again.  Pre-fix this case fired a second charge
        because the latch only disarmed at 100 %."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        ap._state.heal_hp_active = True
        # HP at 75 % -- just past the 70 % disarm threshold.
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 75, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is False
        assert captured == [], (
            "latch must release at 75 % HP -- no third charge to "
            "top off to 100 %")

    def test_hp_latch_stays_armed_below_disarm_threshold(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If HP rose to 60 % (above 30 % arm threshold but below
        70 % disarm threshold), the latch stays armed -- a heal in
        flight may still be applying, and damage may be outpacing
        the heal.  Keep firing under sustained damage; natural
        disarm fires once the bar crosses the 70 % band."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        ap._state.heal_hp_active = True
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 60, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is True
        assert captured == [0]   # still armed, fires

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

    def test_single_use_per_drop_event(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The 2026-05-19 spec: HP drops to 30 %, ONE charge brings
        HP to 80 % (past the 70 % disarm), latch releases, the
        cooldown tick fires no second charge.  Pre-fix the latch
        disarmed only at 100 % so a second charge fired on the
        next cooldown boundary even though the bot was already
        safely past 70 % -- wasting one repair pack per drop event.
        """
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
        # Tick 2 after cooldown: 80 % >= 70 % disarm -- latch
        # releases, no second fire.
        _clock[0] += ap.CONSUMABLE_USE_COOLDOWN_S + 0.1
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0], (
            "must NOT fire a second charge: one consumable already "
            "brought HP from 30 -> 80, past the 70 % disarm band")
        assert ap._state.heal_hp_active is False

    def test_sustained_damage_re_arms_latch_and_fires_again(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If damage outpaces the heal -- e.g., gas cloud or boss
        cannon -- the bot must keep firing.  Sequence: drop to
        30 %, fire (heal to 80 %), then damage pushes HP back
        below 30 % (re-arm), fire again.  Verifies the
        threshold-based design doesn't strand the bot under
        sustained damage."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _state(
            player={"x": 0, "y": 0, "heading": 0,
                    "hp": 30, "max_hp": 100,
                    "shields": 150, "max_shields": 150},
        )
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 25},
        ]
        # First fire at 30 %.
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0]
        # Simulate heal + heavy damage -> bot back below 30 %.
        s["player"]["hp"] = 25
        _clock[0] += ap.CONSUMABLE_USE_COOLDOWN_S + 0.1
        ap._maybe_use_consumables(s, s["player"])
        assert captured == [0, 0]
        assert ap._state.heal_hp_active is True

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




# ── Nebula starter base (2026-05-23) ──────────────────────────────────────


class TestNebulaStarterBaseBuildGate:
    """Pin the second starter-base build flow for ZONE2 (Nebula).

    Buildings are zone-scoped via the ZoneState stash mechanism, so
    the ``Home Station`` BUILDING_TYPES ``max=1`` cap is per-zone.
    The bot can build a MAIN base AND a Nebula base independently;
    they don't conflict because each zone has its own
    ``building_list``.  Gated by a separate ``nebula_build_done``
    latch + ``S_BUILD_NEBULA`` state so the existing MAIN flow
    (``build_done`` + ``S_BUILD``) is untouched.
    """

    def _zone2_state(self, iron=None, **kw):
        """``_state()`` with the zone_id set to ZONE2."""
        if iron is None:
            iron = ap.BUILD_IRON_THRESHOLD
        s = _state(iron=iron, **kw)
        s["zone"] = {"world_w": 6400, "world_h": 6400,
                     "zone_id": "ZoneID.ZONE2",
                     "id": "ZoneID.ZONE2"}
        return s

    def setup_method(self):
        # Fresh latches each test.
        ap._state.build_done = True   # MAIN already built (typical post-progression)
        ap._state.nebula_build_done = False

    def test_zone2_with_iron_and_clear_area_enters_build_nebula(
            self, _clock):
        s = self._zone2_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_NEBULA

    def test_zone2_below_iron_threshold_no_build(self, _clock):
        s = self._zone2_state(iron=ap.BUILD_IRON_THRESHOLD - 1)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_NEBULA

    def test_zone2_with_iron_but_area_blocked_enters_build_seek(
            self, _clock):
        """Asteroid inside the BUILD_CLEAR_RADIUS_PX -- bot enters
        BUILD_SEEK (shared with MAIN flow) to walk away."""
        s = self._zone2_state(
            asteroids=[{"x": 200, "y": 0, "hp": 100}])
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_SEEK

    def test_main_zone_does_not_fire_build_nebula(self, _clock):
        """In MAIN, with iron + clear area + build_done already
        True, the new branch must NOT fire -- the MAIN base has
        priority and the Nebula branch is zone-gated."""
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)   # default zone = MAIN
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_NEBULA

    def test_warp_zone_does_not_fire_build_nebula(self, _clock):
        """Bot in WARP_ENEMY with full iron + clear area.  Warp
        zones are transient; no base building there."""
        s = self._zone2_state()
        s["zone"]["zone_id"] = "ZoneID.WARP_ENEMY"
        s["zone"]["id"] = "ZoneID.WARP_ENEMY"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_NEBULA

    def test_star_maze_does_not_fire_build_nebula(self, _clock):
        """STAR_MAZE has persistent buildings via the same stash
        mechanism but is intentionally excluded -- the maze is
        too space-constrained to host a starter base.  Future work
        could extend this gate; current scope is ZONE2-only."""
        s = self._zone2_state()
        s["zone"]["zone_id"] = "ZoneID.STAR_MAZE"
        s["zone"]["id"] = "ZoneID.STAR_MAZE"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_NEBULA

    def test_nebula_build_done_short_circuits_branch(self, _clock):
        """``nebula_build_done = True`` (e.g. set after a prior
        attempt) blocks the branch even when conditions are met."""
        ap._state.nebula_build_done = True
        s = self._zone2_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_NEBULA

    def test_existing_nebula_home_station_short_circuits(self, _clock):
        """The housekeeping at the top of ``choose_next_state``
        latches ``nebula_build_done`` when the bot enters ZONE2 and
        an HS is already in that zone's building list.  Handles
        loaded-save / manual-placement / prior-session cases."""
        ap._state.nebula_build_done = False
        s = self._zone2_state(
            buildings=[{"x": 3200.0, "y": 3200.0, "hp": 100,
                        "type": "StationModule",
                        "building_type": "Home Station"}])
        ap._do_auto(s, s["player"])
        assert ap._state.nebula_build_done is True
        assert ap._fsm["state"] != ap.S_BUILD_NEBULA

    def test_main_zone_home_station_does_not_latch_nebula(
            self, _clock):
        """If the bot is in MAIN and sees the MAIN HS, only the
        MAIN ``build_done`` latch should fire -- ``nebula_build_done``
        must stay False (Nebula has no HS yet)."""
        ap._state.build_done = False
        ap._state.nebula_build_done = False
        s = _state(
            buildings=[{"x": 3200.0, "y": 3200.0, "hp": 100,
                        "type": "StationModule",
                        "building_type": "Home Station"}])
        ap._do_auto(s, s["player"])
        assert ap._state.build_done is True
        assert ap._state.nebula_build_done is False




class TestActBuildNebula:
    """The action handler mirrors ``_act_build`` (one-shot, guarded
    by its own latch) and reuses the existing
    ``/build_starter_base`` endpoint, which places at the player's
    current position into the zone's ``building_list`` (zone-scoped
    via the ZoneState stash mechanism)."""

    def setup_method(self):
        ap._state.nebula_build_done = False

    def test_fires_post_build_starter_base_when_not_done(
            self, monkeypatch):
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda: posts.append("call") or {"placed": [{"type": "Home Station"}],
                                              "failed": []})
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._act_build_nebula(s, s["player"])
        assert posts == ["call"]
        assert ap._state.nebula_build_done is True

    def test_idles_if_already_done(self, monkeypatch):
        """Guard against duplicate POSTs during MIN_DWELL hold:
        ``nebula_build_done = True`` short-circuits to idle, no
        new POST fires."""
        ap._state.nebula_build_done = True
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_build_starter_base",
            lambda: posts.append("call"))
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._act_build_nebula(s, s["player"])
        assert posts == []

    def test_latches_done_before_post_so_re_entry_idles(
            self, monkeypatch):
        """The latch flips BEFORE the POST so a re-entry during the
        synchronous HTTP round-trip early-returns -- preserves the
        single-POST guarantee even under MIN_DWELL re-dispatch."""
        seen_done: list = []

        def fake_post():
            seen_done.append(ap._state.nebula_build_done)
            return {"placed": [], "failed": []}

        monkeypatch.setattr(ap, "_post_build_starter_base", fake_post)
        s = _state(iron=ap.BUILD_IRON_THRESHOLD)
        ap._act_build_nebula(s, s["player"])
        assert seen_done == [True], (
            "nebula_build_done must already be True at the moment "
            "the POST is dispatched, so a concurrent re-entry "
            "would short-circuit")


# ── REGEN drive-to-HS for the healing umbrella (2026-05-23) ────────────────


# ── Nebula fortify ring (2026-05-24) ──────────────────────────────────────


class TestNebulaFortifyGate:
    """The S_FORTIFY_NEBULA trigger fires once the Nebula starter
    base is up, station iron covers FORTIFY_IRON_COST, and the
    ring hasn't yet been built.  Latches into
    ``nebula_fortify_done`` to avoid re-firing.  Mirrors the
    MAIN-zone fortify trigger (which lives inside the QWI prep
    pipeline); this one is standalone since the Nebula doesn't
    have a QWI pipeline yet.
    """

    def _zone2_state(self, *, station_iron=2000, defenders=0,
                     have_hs=True):
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items={"iron": station_iron},
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        builds = []
        if have_hs:
            builds.append({"x": 4000.0, "y": 4000.0,
                           "building_type": "Home Station"})
        for i in range(defenders):
            builds.append({"x": 4100.0 + i * 50.0, "y": 4100.0,
                           "building_type": "Defense Turret"})
        s["buildings"] = builds
        return s

    def test_fires_when_zone2_has_hs_and_iron_and_not_done(
            self, _clock):
        ap._state.nebula_build_done = True
        ap._state.nebula_fortify_done = False
        ap._state.build_done = True
        s = self._zone2_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FORTIFY_NEBULA

    def test_does_not_fire_in_main_zone(self, _clock):
        ap._state.nebula_build_done = True
        ap._state.nebula_fortify_done = False
        ap._state.build_done = True
        s = self._zone2_state()
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FORTIFY_NEBULA

    def test_does_not_fire_without_nebula_hs(self, _clock):
        ap._state.nebula_build_done = True
        ap._state.nebula_fortify_done = False
        ap._state.build_done = True
        s = self._zone2_state(have_hs=False)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FORTIFY_NEBULA

    def test_does_not_fire_without_iron(self, _clock):
        ap._state.nebula_build_done = True
        ap._state.nebula_fortify_done = False
        ap._state.build_done = True
        s = self._zone2_state(station_iron=ap.FORTIFY_IRON_COST - 1)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FORTIFY_NEBULA

    def test_does_not_fire_when_already_done(self, _clock):
        ap._state.nebula_build_done = True
        ap._state.nebula_fortify_done = True
        ap._state.build_done = True
        s = self._zone2_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FORTIFY_NEBULA

    def test_short_circuit_latches_when_ring_already_present(
            self, _clock):
        """If the bot enters ZONE2 with the ring already built
        (loaded save / manual placement), the housekeeping
        short-circuit latches the flag without re-firing the
        action."""
        ap._state.nebula_fortify_done = False
        ap._state.build_done = True
        ap._state.nebula_build_done = True
        s = self._zone2_state(defenders=ap.QWI_STAGE_MIN_TURRETS)
        ap._do_auto(s, s["player"])
        assert ap._state.nebula_fortify_done is True

    def test_short_circuit_does_not_fire_outside_zone2(
            self, _clock):
        """Defenders visible in MAIN should latch MAIN's
        ``fortify_done``, not the Nebula one."""
        ap._state.nebula_fortify_done = False
        ap._state.fortify_done = False
        ap._state.build_done = True
        s = self._zone2_state(defenders=ap.QWI_STAGE_MIN_TURRETS)
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._do_auto(s, s["player"])
        assert ap._state.nebula_fortify_done is False


class TestActFortifyNebula:
    """Mirrors TestActFortify but exercises the Nebula latch."""

    def setup_method(self):
        ap._state.nebula_fortify_done = False

    def test_fires_post_fortify_and_latches_nebula_done(
            self, monkeypatch):
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_fortify",
            lambda timeout_s=10.0: posts.append("call") or {
                "ok": True, "placed": [{"x": 4100, "y": 4100}],
                "failed": [], "defenders_now": 4})
        # Patch driving so the test focuses on the POST gate.
        monkeypatch.setattr(ap, "_do_goto",
                            lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_do_idle", lambda: None)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        ap._act_fortify_nebula(s, s["player"])
        assert posts == ["call"]
        assert ap._state.nebula_fortify_done is True
        # MAIN latch unaffected.
        assert ap._state.fortify_done is False

    def test_already_done_short_circuits(self, monkeypatch):
        ap._state.nebula_fortify_done = True
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_fortify",
            lambda timeout_s=10.0: posts.append("call"))
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_do_idle", lambda: None)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        ap._act_fortify_nebula(s, s["player"])
        assert posts == []


# ── Nebula AI Pilot ship placement (2026-05-24) ──────────────────────────


class TestPlaceAiPilotNebulaGate:
    """``S_PLACE_AI_PILOT_NEBULA`` fires once the Nebula HS is up,
    the fortify ring is in place, and station inventory has the
    ai_pilot module + iron / copper to cover the Basic Ship cost.
    Latches into ``nebula_ai_pilot_placed`` after a successful
    POST so the FSM doesn't re-fire.
    """

    def _staged_state(self, *, station_items=None):
        items = {"iron": ap.AI_PILOT_SHIP_IRON_COST,
                 "copper": ap.AI_PILOT_SHIP_COPPER_COST,
                 "ai_pilot": 1}
        if station_items is not None:
            items.update(station_items)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items=items,
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}],
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        return s

    def _arm_prerequisites(self):
        ap._state.build_done = True
        ap._state.nebula_build_done = True
        ap._state.nebula_fortify_done = True
        ap._state.nebula_ai_pilot_placed = False

    def test_fires_when_all_prerequisites_met(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_PLACE_AI_PILOT_NEBULA

    def test_defers_until_fortify_done(self, _clock):
        self._arm_prerequisites()
        ap._state.nebula_fortify_done = False
        s = self._staged_state()
        ap._do_auto(s, s["player"])
        # Should fire FORTIFY_NEBULA first.
        assert ap._fsm["state"] == ap.S_FORTIFY_NEBULA

    def test_does_not_fire_without_ai_pilot_module(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state(station_items={"ai_pilot": 0})
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_PLACE_AI_PILOT_NEBULA

    def test_does_not_fire_without_iron(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state(
            station_items={"iron": ap.AI_PILOT_SHIP_IRON_COST - 1})
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_PLACE_AI_PILOT_NEBULA

    def test_does_not_fire_without_copper(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state(
            station_items={"copper": ap.AI_PILOT_SHIP_COPPER_COST - 1})
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_PLACE_AI_PILOT_NEBULA

    def test_does_not_fire_when_already_placed(self, _clock):
        self._arm_prerequisites()
        ap._state.nebula_ai_pilot_placed = True
        s = self._staged_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_PLACE_AI_PILOT_NEBULA

    def test_does_not_fire_in_main_zone(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state()
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_PLACE_AI_PILOT_NEBULA


class TestActPlaceAiPilotNebula:
    """Action-handler tests for the POST + latch behaviour."""

    def setup_method(self):
        ap._state.nebula_ai_pilot_placed = False

    def test_fires_post_and_latches(self, monkeypatch):
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_place_ai_pilot_ship",
            lambda timeout_s=10.0: posts.append("call") or {
                "ok": True, "placed_at": [4000.0, 3850.0]})
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_do_idle", lambda: None)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        ap._act_place_ai_pilot_nebula(s, s["player"])
        assert posts == ["call"]
        assert ap._state.nebula_ai_pilot_placed is True

    def test_already_nearby_latches_without_posting_twice(
            self, monkeypatch):
        """A duplicate-call response (skipped: already nearby)
        flips the latch via the failure-keyword path so the FSM
        moves on instead of looping."""
        posts: list = []

        def fake_post(timeout_s=10.0):
            posts.append("call")
            return {
                "ok": True, "skipped": "ai pilot ship already nearby",
                "placed_at": [4000.0, 3850.0]}

        monkeypatch.setattr(
            ap, "_post_place_ai_pilot_ship", fake_post)
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_do_idle", lambda: None)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        ap._act_place_ai_pilot_nebula(s, s["player"])
        # The latch flips immediately (ok=True), even on skip.
        assert ap._state.nebula_ai_pilot_placed is True

    def test_already_placed_short_circuits_post(self, monkeypatch):
        ap._state.nebula_ai_pilot_placed = True
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_place_ai_pilot_ship",
            lambda timeout_s=10.0: posts.append("call"))
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_do_idle", lambda: None)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        ap._act_place_ai_pilot_nebula(s, s["player"])
        assert posts == []


# ── Nebula advanced-module auto-queue (2026-05-24) ────────────────────────


class TestNebulaAdvancedModuleAutoQueue:
    """When the bot is in ZONE2 and an advanced module
    (misty_step / force_wall / death_blossom) is sitting in the
    station inventory but not yet on the ship, the housekeeping
    short-circuit appends it to the install queue so the existing
    CRAFT / INSTALL pipeline picks it up.
    """

    def _zone2_with_inv(self, *, station_items=None,
                        module_slots=None):
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items=station_items or {},
            module_slots=module_slots or [],
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        s["zone"]["id"] = "ZoneID.ZONE2"
        return s

    def test_queues_misty_step_when_present(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        s = self._zone2_with_inv(station_items={"mod_misty_step": 1})
        ap._do_auto(s, s["player"])
        assert "misty_step" in ap._state.queue.modules_to_install

    def test_queues_all_three_when_all_present(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        s = self._zone2_with_inv(station_items={
            "mod_misty_step": 1,
            "mod_force_wall": 1,
            "mod_death_blossom": 1,
        })
        ap._do_auto(s, s["player"])
        assert "misty_step" in ap._state.queue.modules_to_install
        assert "force_wall" in ap._state.queue.modules_to_install
        assert "death_blossom" in ap._state.queue.modules_to_install

    def test_skips_modules_already_installed(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        s = self._zone2_with_inv(
            station_items={"mod_misty_step": 1,
                           "mod_force_wall": 1},
            module_slots=["misty_step"])
        ap._do_auto(s, s["player"])
        assert "misty_step" not in ap._state.queue.modules_to_install
        assert "force_wall" in ap._state.queue.modules_to_install

    def test_skips_modules_already_queued(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        # Pre-seed the queue with misty_step.
        ap._state.queue.modules_to_install.append("misty_step")
        before_len = len(ap._state.queue.modules_to_install)
        s = self._zone2_with_inv(
            station_items={"mod_misty_step": 1})
        ap._do_auto(s, s["player"])
        # Should NOT double-append.
        assert ap._state.queue.modules_to_install.count(
            "misty_step") == 1
        assert len(ap._state.queue.modules_to_install) == before_len

    def test_does_not_queue_outside_zone2(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        s = self._zone2_with_inv(
            station_items={"mod_misty_step": 1})
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._do_auto(s, s["player"])
        assert "misty_step" not in ap._state.queue.modules_to_install

    def test_does_not_queue_when_station_lacks_module(
            self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        s = self._zone2_with_inv(station_items={})
        ap._do_auto(s, s["player"])
        # Empty station -> nothing to queue.
        for k in ("misty_step", "force_wall", "death_blossom"):
            assert k not in ap._state.queue.modules_to_install


# ── Nebula Advanced Crafter (2026-05-25) ──────────────────────────────────


class TestNebulaAdvancedCrafterGate:
    """``S_BUILD_ADV_CRAFTER`` fires once the Nebula HS + fortify
    ring are in place, the ``advanced_crafter`` blueprint is in
    station inventory, and the station has 1000 iron + 500 copper
    to cover the build.  Latches into
    ``nebula_advanced_crafter_done`` after a successful POST so
    the FSM doesn't re-fire.
    """

    def _staged_state(self, *, station_items=None,
                      advanced_crafter_present=False):
        items = {
            "iron": ap.ADVANCED_CRAFTER_IRON_COST,
            "copper": ap.ADVANCED_CRAFTER_COPPER_COST,
            "advanced_crafter": 1,
        }
        if station_items is not None:
            items.update(station_items)
        builds = [{"x": 4000.0, "y": 4000.0,
                   "building_type": "Home Station"}]
        if advanced_crafter_present:
            builds.append({"x": 4120.0, "y": 3940.0,
                           "building_type": "Advanced Crafter"})
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items=items,
            buildings=builds,
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        return s

    def _arm_prerequisites(self):
        ap._state.build_done = True
        ap._state.nebula_build_done = True
        ap._state.nebula_fortify_done = True
        ap._state.nebula_ai_pilot_placed = True
        ap._state.nebula_advanced_crafter_done = False

    def test_fires_when_all_prerequisites_met(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_ADV_CRAFTER

    def test_does_not_fire_without_fortify(self, _clock):
        self._arm_prerequisites()
        ap._state.nebula_fortify_done = False
        s = self._staged_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_ADV_CRAFTER

    def test_does_not_fire_without_blueprint(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state(station_items={"advanced_crafter": 0})
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_ADV_CRAFTER

    def test_does_not_fire_without_iron(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state(
            station_items={"iron": ap.ADVANCED_CRAFTER_IRON_COST - 1})
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_ADV_CRAFTER

    def test_does_not_fire_without_copper(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state(
            station_items={"copper": ap.ADVANCED_CRAFTER_COPPER_COST - 1})
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_ADV_CRAFTER

    def test_does_not_fire_when_already_done_latch(self, _clock):
        self._arm_prerequisites()
        ap._state.nebula_advanced_crafter_done = True
        s = self._staged_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_ADV_CRAFTER

    def test_does_not_fire_when_already_built_in_world(
            self, _clock):
        """Even with the latch False (loaded save / manual placement),
        seeing an Advanced Crafter in the zone short-circuits the
        trigger."""
        self._arm_prerequisites()
        s = self._staged_state(advanced_crafter_present=True)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_ADV_CRAFTER

    def test_does_not_fire_in_main_zone(self, _clock):
        self._arm_prerequisites()
        s = self._staged_state()
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_BUILD_ADV_CRAFTER

    def test_startup_short_circuit_latches_when_already_present(
            self, _clock):
        """If the bot enters ZONE2 with an Advanced Crafter already
        in the building list (loaded save / manual placement),
        the housekeeping short-circuit latches
        ``nebula_advanced_crafter_done`` so the trigger never fires
        and the latch stays consistent with the world."""
        ap._state.nebula_advanced_crafter_done = False
        self._arm_prerequisites()
        ap._state.nebula_advanced_crafter_done = False
        s = self._staged_state(advanced_crafter_present=True)
        ap._do_auto(s, s["player"])
        assert ap._state.nebula_advanced_crafter_done is True

    def test_startup_short_circuit_does_not_fire_outside_zone2(
            self, _clock):
        """An Advanced Crafter visible in MAIN's building_list
        (unusual, but possible via a stash bug) should NOT latch
        the Nebula-specific flag."""
        ap._state.nebula_advanced_crafter_done = False
        self._arm_prerequisites()
        ap._state.nebula_advanced_crafter_done = False
        s = self._staged_state(advanced_crafter_present=True)
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._do_auto(s, s["player"])
        assert ap._state.nebula_advanced_crafter_done is False

    def test_startup_short_circuit_no_op_when_absent(self, _clock):
        """Bot in ZONE2 without an Advanced Crafter visible -- the
        latch stays False so the FSM can still build one."""
        ap._state.nebula_advanced_crafter_done = False
        self._arm_prerequisites()
        ap._state.nebula_advanced_crafter_done = False
        s = self._staged_state(advanced_crafter_present=False)
        ap._do_auto(s, s["player"])
        assert ap._state.nebula_advanced_crafter_done is False


class TestActBuildAdvancedCrafter:
    def setup_method(self):
        ap._state.nebula_advanced_crafter_done = False

    def test_fires_post_and_latches(self, monkeypatch):
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_place_advanced_crafter",
            lambda timeout_s=10.0: posts.append("call") or {
                "ok": True, "placed_at": [4120.0, 3940.0]})
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_do_idle", lambda: None)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        ap._act_build_advanced_crafter(s, s["player"])
        assert posts == ["call"]
        assert ap._state.nebula_advanced_crafter_done is True

    def test_already_done_short_circuits(self, monkeypatch):
        ap._state.nebula_advanced_crafter_done = True
        posts: list = []
        monkeypatch.setattr(
            ap, "_post_place_advanced_crafter",
            lambda timeout_s=10.0: posts.append("call"))
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(ap, "_do_idle", lambda: None)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"x": 4000.0, "y": 4000.0,
                        "building_type": "Home Station"}])
        ap._act_build_advanced_crafter(s, s["player"])
        assert posts == []


class TestNebulaAdvancedModuleCraftQueue:
    """When the bot is in ZONE2 with an Advanced Crafter built AND
    the blueprint (``bp_<key>``) is deposited, the housekeeping
    observer appends the module key to ``modules_to_craft`` so the
    existing CRAFT pipeline picks it up.
    """

    def _zone2_state(self, *, station_items=None,
                     buildings_extra=()):
        items = dict(station_items or {})
        builds = [{"x": 4000.0, "y": 4000.0,
                   "building_type": "Home Station"}]
        builds.extend(buildings_extra)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items=items,
            buildings=builds,
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        return s

    def test_queues_for_craft_when_blueprint_present_and_crafter_exists(
            self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(
            station_items={"bp_misty_step": 1})
        ap._do_auto(s, s["player"])
        assert "misty_step" in ap._state.queue.modules_to_craft
        # Should NOT also be in install queue.
        assert "misty_step" not in ap._state.queue.modules_to_install

    def test_does_not_queue_for_craft_without_crafter(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = False
        s = self._zone2_state(
            station_items={"bp_misty_step": 1})
        ap._do_auto(s, s["player"])
        assert "misty_step" not in ap._state.queue.modules_to_craft

    def test_install_path_takes_priority_when_already_crafted(
            self, _clock):
        """If the module is already crafted (mod_<key> in station),
        the install path fires INSTEAD of re-queuing for craft."""
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(
            station_items={
                "mod_misty_step": 1,
                "bp_misty_step": 1,
            })
        ap._do_auto(s, s["player"])
        assert "misty_step" in ap._state.queue.modules_to_install
        assert "misty_step" not in ap._state.queue.modules_to_craft

    def test_world_inspection_satisfies_crafter_gate(self, _clock):
        """Latch is False but an Advanced Crafter is in the world
        (loaded save / manual placement) -- the auto-queue should
        still fire."""
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = False
        s = self._zone2_state(
            station_items={"bp_misty_step": 1},
            buildings_extra=[{
                "x": 4120.0, "y": 3940.0,
                "building_type": "Advanced Crafter"}])
        ap._do_auto(s, s["player"])
        assert "misty_step" in ap._state.queue.modules_to_craft

    def test_queues_all_three_when_all_blueprints_present(
            self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(station_items={
            "bp_misty_step": 1,
            "bp_force_wall": 1,
            "bp_death_blossom": 1,
        })
        ap._do_auto(s, s["player"])
        for k in ("misty_step", "force_wall", "death_blossom"):
            assert k in ap._state.queue.modules_to_craft


# ── Nebula advanced-consumable auto-queue (2026-05-26) ────────────────────


class TestNebulaAdvancedConsumableCraftQueue:
    """Advanced consumables (homing_missile / mining_drone /
    combat_drone) get queued for crafting when:
      * bot is in ZONE2,
      * an Advanced Crafter exists (latch OR world inspection),
      * the matching blueprint is deposited,
      * station-inv count of the produced item is below the
        target stockpile.

    The auto-pop guard in ``_next_craft_target`` removes the head
    once the stockpile target is met, so the bot crafts ONE batch
    per recipe per fill cycle.
    """

    def _zone2_state(self, *, station_items=None,
                     buildings_extra=()):
        items = dict(station_items or {})
        builds = [{"x": 4000.0, "y": 4000.0,
                   "building_type": "Home Station"}]
        builds.extend(buildings_extra)
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            station_inventory_items=items,
            buildings=builds,
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        return s

    def test_queues_homing_missile_when_blueprint_present(
            self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(station_items={"bp_homing_missile": 1})
        ap._do_auto(s, s["player"])
        assert "homing_missile" in ap._state.queue.modules_to_craft

    def test_queues_all_three_consumables(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(station_items={
            "bp_homing_missile": 1,
            "bp_mining_drone": 1,
            "bp_combat_drone": 1,
        })
        ap._do_auto(s, s["player"])
        for k in ("homing_missile", "mining_drone", "combat_drone"):
            assert k in ap._state.queue.modules_to_craft

    def test_does_not_queue_without_advanced_crafter(self, _clock):
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = False
        s = self._zone2_state(station_items={"bp_homing_missile": 1})
        ap._do_auto(s, s["player"])
        assert "homing_missile" not in ap._state.queue.modules_to_craft

    def test_skips_when_stockpile_at_target(self, _clock):
        """20 missiles already in station -- don't queue another
        homing_missile craft."""
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(station_items={
            "bp_homing_missile": 1,
            "missile": ap.NEBULA_ADV_CONSUMABLE_TARGETS[
                "homing_missile"][1],
        })
        ap._do_auto(s, s["player"])
        assert "homing_missile" not in ap._state.queue.modules_to_craft

    def test_queues_below_target(self, _clock):
        """10 missiles, target 20 -- still queue."""
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(station_items={
            "bp_homing_missile": 1,
            "missile": 10,
        })
        ap._do_auto(s, s["player"])
        assert "homing_missile" in ap._state.queue.modules_to_craft

    def test_does_not_double_queue(self, _clock):
        """If already queued, don't re-append."""
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_craft.append("homing_missile")
        ap._state.nebula_advanced_crafter_done = True
        s = self._zone2_state(station_items={"bp_homing_missile": 1})
        ap._do_auto(s, s["player"])
        assert ap._state.queue.modules_to_craft.count(
            "homing_missile") == 1


class TestNextCraftTargetConsumableAutoPop:
    """``_next_craft_target``'s auto-pop guard handles consumable
    heads via the produced-item-key stockpile check.  Without this
    the bot would re-craft homing_missile forever (the existing
    ``mod_<key>`` guard never triggers because the craft produces
    "missile" items, not "mod_homing_missile")."""

    def test_pops_homing_missile_when_stock_at_target(self):
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_craft.append("homing_missile")
        s = _state(station_inventory_items={
            "bp_homing_missile": 1,
            "missile": 20,
        })
        target = ap._next_craft_target(s)
        assert "homing_missile" not in ap._state.queue.modules_to_craft
        assert target != "homing_missile"

    def test_does_not_pop_when_stock_below_target(self):
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_craft.append("homing_missile")
        s = _state(station_inventory_items={
            "bp_homing_missile": 1,
            "missile": 10,
            "iron": 200,
        })
        # Auto-pop check should NOT remove the head.
        ap._next_craft_target(s)
        assert "homing_missile" in ap._state.queue.modules_to_craft

    def test_pops_mining_drone_when_stock_at_target(self):
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_craft.append("mining_drone")
        s = _state(station_inventory_items={
            "bp_mining_drone": 1,
            "mining_drone": 5,
        })
        ap._next_craft_target(s)
        assert "mining_drone" not in ap._state.queue.modules_to_craft

    def test_pops_combat_drone_when_stock_at_target(self):
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.modules_to_craft.append("combat_drone")
        s = _state(station_inventory_items={
            "bp_combat_drone": 1,
            "combat_drone": 5,
        })
        ap._next_craft_target(s)
        assert "combat_drone" not in ap._state.queue.modules_to_craft


# ── Copper-priority mining for the Nebula tier (2026-06-06) ────────────


class TestCopperPriority:
    """The MINE selector ignored asteroid type, so the bot never
    accumulated the 500 copper the Advanced Crafter gate needs and the
    whole Nebula module/drone tier stayed dormant.  ``_copper_priority_active``
    + ``_nearest_copper_asteroid`` let the MINE action seek copper when
    the Nebula build needs it."""

    def _zone2(self, *, copper=0, fortified=True, asteroids=()):
        s = _state(
            buildings=[_hs_building()],
            asteroids=list(asteroids),
            station_inventory_items={"copper": copper},
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        ap._state.nebula_fortify_done = fortified
        return s

    def test_priority_active_in_zone2_low_copper(
            self, _clock, _fresh_bot_state):
        assert ap._copper_priority_active(self._zone2(copper=100)) is True

    def test_priority_inactive_when_copper_sufficient(
            self, _clock, _fresh_bot_state):
        s = self._zone2(copper=ap.ADVANCED_CRAFTER_COPPER_COST)
        assert ap._copper_priority_active(s) is False

    def test_priority_inactive_outside_zone2(
            self, _clock, _fresh_bot_state):
        s = self._zone2(copper=0)
        s["zone"]["id"] = "ZoneID.MAIN"
        assert ap._copper_priority_active(s) is False

    def test_priority_inactive_before_fortify(
            self, _clock, _fresh_bot_state):
        s = self._zone2(copper=0, fortified=False)
        assert ap._copper_priority_active(s) is False

    def test_priority_inactive_when_already_built(
            self, _clock, _fresh_bot_state):
        s = self._zone2(copper=0)
        s["buildings"].append({"x": 3300.0, "y": 3300.0,
                               "building_type": "Advanced Crafter"})
        assert ap._copper_priority_active(s) is False

    def test_nearest_copper_picks_copper_over_nearer_iron(
            self, _clock, _fresh_bot_state):
        # Iron is closer, but the selector must return the copper one.
        s = self._zone2(copper=0, asteroids=[
            {"x": 3000.0, "y": 3000.0, "hp": 100, "type": "IronAsteroid"},
            {"x": 3600.0, "y": 3000.0, "hp": 100,
             "type": "CopperAsteroid"},
        ])
        target, d = ap._nearest_copper_asteroid(s, 3000.0, 3000.0)
        assert target is not None
        assert target["type"] == "CopperAsteroid"
        assert d == 600.0

    def test_nearest_copper_none_when_no_copper_asteroids(
            self, _clock, _fresh_bot_state):
        s = self._zone2(copper=0, asteroids=[
            {"x": 3000.0, "y": 3000.0, "hp": 100,
             "type": "IronAsteroid"}])
        target, _d = ap._nearest_copper_asteroid(s, 3000.0, 3000.0)
        assert target is None


# ── Consumable depleted-restock (2026-06-05 telemetry) ────────────────


class TestConsumableRestock:
    """``_observe_consumable_restock`` re-arms the consumable craft
    queue when the bot runs its stock dry WHILE OPERATING -- not just on
    the warp-back-to-MAIN edge.  Captured 2026-06-05: the bot fought the
    final ~13 min of a session with shield supply = 0 because the only
    restock trigger fired on the warp edge."""

    def test_rearms_when_shield_depleted(self, _clock, _fresh_bot_state):
        ap._state.boss_was_killed = True   # restock is post-boss only
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.queue.consumable_phase_started = True
        ap._state.consumables_equipped = True
        s = _state(
            buildings=[_hs_building()],
            # shield depleted (2 <= floor 5); repair plentiful.
            station_inventory_items={"shield_recharge": 2,
                                     "repair_pack": 20},
        )
        ap._observe_consumable_restock(s, s["player"], 0.0)
        assert (ap._state.queue.shield_recharges_remaining
                == ap.WARP_RECRAFT_SHIELD_BATCHES)
        assert (ap._state.queue.repair_packs_remaining
                == ap.WARP_RECRAFT_REPAIR_BATCHES)
        # Latches reset so CRAFT re-evaluates + the bot re-equips.
        assert ap._state.queue.consumable_phase_started is False
        assert ap._state.consumables_equipped is False

    def test_rearms_on_loaded_save_via_boss_defeated(
            self, _clock, _fresh_bot_state):
        """2026-06-06 fix: ``boss_was_killed`` is set only on the
        in-session boss-kill edge, so on a save loaded post-boss it stays
        False.  The captured session ran that way and the restock never
        fired -- the bot spent ~100 min with shield supply = 0.  The
        persisted ``boss_defeated`` flag from /state must trigger the
        restock on loaded games too."""
        ap._state.boss_was_killed = False          # no in-session kill
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items={"shield_recharge": 0},
        )
        s["boss_defeated"] = True                  # loaded post-boss save
        ap._observe_consumable_restock(s, s["player"], 0.0)
        assert (ap._state.queue.shield_recharges_remaining
                == ap.WARP_RECRAFT_SHIELD_BATCHES)

    def test_no_rearm_before_boss_even_when_depleted(
            self, _clock, _fresh_bot_state):
        """Pre-boss (neither signal set), the restock stays off so it
        can't un-finish the consumable phase and block QWI / FORTIFY
        staging."""
        ap._state.boss_was_killed = False
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items={"shield_recharge": 0},
        )
        # boss_defeated absent / False -> pre-boss.
        ap._observe_consumable_restock(s, s["player"], 0.0)
        assert ap._state.queue.shield_recharges_remaining == 0

    def test_no_rearm_when_supply_above_floor(
            self, _clock, _fresh_bot_state):
        ap._state.boss_was_killed = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items={"shield_recharge": 20,
                                     "repair_pack": 20},
        )
        ap._observe_consumable_restock(s, s["player"], 0.0)
        assert ap._state.queue.shield_recharges_remaining == 0
        assert ap._state.queue.repair_packs_remaining == 0

    def test_no_rearm_when_queue_already_armed(
            self, _clock, _fresh_bot_state):
        ap._state.boss_was_killed = True
        # A batch is mid-craft -- don't duplicate / reset it.
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 2
        s = _state(
            buildings=[_hs_building()],
            station_inventory_items={"shield_recharge": 0},
        )
        ap._observe_consumable_restock(s, s["player"], 0.0)
        assert ap._state.queue.shield_recharges_remaining == 2

    def test_counts_supply_across_station_ship_quickuse(
            self, _clock, _fresh_bot_state):
        ap._state.boss_was_killed = True
        # Supply spread thin across all three locations still totals
        # above the floor -> no premature re-arm.
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        s = _state(
            buildings=[_hs_building()],
            inventory_items={"iron": 0, "shield_recharge": 3,
                             "repair_pack": 10},
            station_inventory_items={"shield_recharge": 3,
                                     "repair_pack": 10},
        )
        s["quick_use_slots"] = [
            {"item_type": "shield_recharge", "count": 4},
            {"item_type": "repair_pack", "count": 4},
        ]
        # shield total = 3 + 3 + 4 = 10 > 5; repair = 10 + 10 + 4 = 24.
        ap._observe_consumable_restock(s, s["player"], 0.0)
        assert ap._state.queue.shield_recharges_remaining == 0
