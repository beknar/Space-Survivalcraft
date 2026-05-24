"""FSM mechanics + GATHER / MINE / HUNT / SEARCH / movement.

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



# ── Fix (2026-05-17): gas-cloud target filter ─────────────────────────

class TestGasCloudTargetFilter:
    """``_nearest_pickup`` / ``_nearest_asteroid`` skip targets
    inside any gas cloud's damage zone (visible radius +
    ``PICKUP_GAS_AVOID_MARGIN_PX`` safety buffer).

    Captured 2026-05-17 bot_io: bot dropped to shields=1 while
    blacklisting three pickups in succession at the NE edge of a
    gas cloud cluster.  Each "lesson" cost ~40 shield + heal-shield
    uses; pre-filtering at selection eliminates the lesson
    entirely.

    Unlike the edge / wormhole / pin-zone filters which fall back
    to the original candidate when every alternative fails, the
    gas-cloud filter returns ``None`` per user spec ("give up and
    leave the gas cloud" rather than try to reach a pickup inside
    it).  The bot's GATHER state exits and the cascade routes to
    other behaviors.
    """

    _CLOUD = {"x": 5000.0, "y": 5500.0, "radius": 200.0}

    def test_pickup_inside_gas_cloud_filtered(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Pickup inside a gas cloud is skipped when a safe
        alternative exists."""
        import bot_autopilot_targeting as targeting
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 5050.0, "y": 5500.0, "item_type": "iron"},  # IN cloud
                {"x": 2500.0, "y": 3000.0, "item_type": "iron"},  # SAFE
            ],
            world_w=9600, world_h=9600,
        )
        s["gas_areas"] = [self._CLOUD]
        nearest, _d = ap._nearest_pickup(s, 3000.0, 3000.0)
        assert nearest["x"] == 2500.0  # safe alternative wins

    def test_asteroid_inside_gas_cloud_filtered(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Symmetric pin for ``_nearest_asteroid``."""
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[
                {"x": 5050.0, "y": 5500.0, "hp": 50},  # IN cloud
                {"x": 2500.0, "y": 3000.0, "hp": 50},  # SAFE
            ],
            world_w=9600, world_h=9600,
        )
        s["gas_areas"] = [self._CLOUD]
        nearest, _d = ap._nearest_asteroid(s, 3000.0, 3000.0)
        assert nearest["x"] == 2500.0

    def test_pickup_filter_returns_none_when_all_in_cloud(
            self, _clock, _fresh_bot_state, monkeypatch):
        """User spec: 'give up and leave the gas cloud' rather
        than try to reach a pickup inside it.  When every visible
        pickup is in a gas cloud, return ``None`` instead of
        falling back to the in-cloud candidate."""
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 5050.0, "y": 5500.0, "item_type": "iron"},
                {"x": 4950.0, "y": 5400.0, "item_type": "iron"},
            ],
            world_w=9600, world_h=9600,
        )
        s["gas_areas"] = [self._CLOUD]
        nearest, _d = ap._nearest_pickup(s, 3000.0, 3000.0)
        assert nearest is None

    def test_asteroid_filter_returns_none_when_all_in_cloud(
            self, _clock, _fresh_bot_state, monkeypatch):
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[
                {"x": 5050.0, "y": 5500.0, "hp": 50},
                {"x": 4950.0, "y": 5400.0, "hp": 50},
            ],
            world_w=9600, world_h=9600,
        )
        s["gas_areas"] = [self._CLOUD]
        nearest, _d = ap._nearest_asteroid(s, 3000.0, 3000.0)
        assert nearest is None

    def test_pickup_filter_uses_margin_past_visible_radius(
            self, _clock, _fresh_bot_state, monkeypatch):
        """A pickup just outside the visible radius but within
        the safety margin is also filtered (so the approach
        trajectory doesn't drag the bot through the damage zone).
        """
        import bot_autopilot_targeting as targeting
        s = _state(world_w=9600, world_h=9600)
        s["gas_areas"] = [self._CLOUD]
        # Inside visible radius -> filtered.
        assert targeting._target_in_gas_cloud(
            s, 5050.0, 5500.0) is True
        # Just past visible radius (200) but within margin
        # (200 + 50 = 250) -> filtered.
        assert targeting._target_in_gas_cloud(
            s, 5230.0, 5500.0) is True
        # Past visible radius + margin -> safe.
        assert targeting._target_in_gas_cloud(
            s, 5300.0, 5500.0) is False

    def test_no_gas_clouds_no_op(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Zones without gas (Zone 1, Star Maze, MAIN) populate
        an empty ``gas_areas`` list -> filter is a no-op."""
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[
                {"x": 5050.0, "y": 5500.0, "item_type": "iron"},
            ],
            world_w=9600, world_h=9600,
        )
        # No gas_areas in state.
        nearest, _d = ap._nearest_pickup(s, 3000.0, 3000.0)
        assert nearest["x"] == 5050.0  # not filtered

    def test_gas_cloud_does_not_disturb_default_test_state(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The default ``_state()`` helper doesn't include
        gas_areas, so existing tests in MAIN-zone scenarios are
        unaffected by this PR.  Smoke-test for that invariant."""
        s = _state(
            iron_pickups=[{"x": 100.0, "y": 100.0,
                           "item_type": "iron"}],
        )
        assert "gas_areas" not in s
        nearest, _d = ap._nearest_pickup(s, 0.0, 0.0)
        assert nearest is not None


# ── Fix (2026-05-06): HUNT alien edge filter ─────────────────────────



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


# ── BotState sub-dataclass grouping (PR 5) ────────────────────────────────


class TestBotStateGroupingAliases:
    """The 2026-05-24 PR 5 refactor grouped 24 flat BotState fields
    into ``WarpState`` / ``GasLingerState`` / ``BossCombatState``
    sub-dataclasses, with property aliases preserving the legacy
    flat names so external code keeps working.  These tests pin
    the alias contract: every legacy name maps both ways
    (get / set) to its sub-object counterpart.
    """

    def _aliases(self):
        return [
            # (legacy_name, sub_object, sub_attr, sample_value)
            ("warp_after_boss_done", "warp", "after_boss_done", True),
            ("warp_relatched_pending", "warp", "relatched_pending", True),
            ("warp_traverse_done", "warp", "traverse_done", True),
            ("warp_wormhole_arrived_at", "warp",
             "wormhole_arrived_at", 1234.5),
            ("warp_wormhole_best_d", "warp", "wormhole_best_d", 99.0),
            ("warp_wormhole_progress_at", "warp",
             "wormhole_progress_at", 500.0),
            ("warp_traverse_max_y", "warp", "traverse_max_y", 3000.0),
            ("warp_traverse_progress_at", "warp",
             "traverse_progress_at", 100.0),
            ("warp_traverse_detour_count", "warp",
             "traverse_detour_count", 3),
            ("warp_traverse_detour_side", "warp",
             "traverse_detour_side", -1),
            ("warp_traverse_detour_commit_y", "warp",
             "traverse_detour_commit_y", 2800.0),
            ("warp_traverse_progress_committed_y", "warp",
             "traverse_progress_committed_y", 2750.0),
            ("warp_traverse_arc_started_at", "warp",
             "traverse_arc_started_at", 950.0),
            ("gas_linger_entered_at", "gas_linger", "entered_at", 1.5),
            ("gas_linger_entry_shields", "gas_linger",
             "entry_shields", 99),
            ("gas_linger_entry_hp", "gas_linger", "entry_hp", 80),
            ("gas_linger_event_fired", "gas_linger",
             "event_fired", True),
            ("boss_engage_started_at", "boss_combat",
             "engage_started_at", 700.0),
            ("boss_engage_start_hp", "boss_combat",
             "engage_start_hp", 150),
            ("boss_engage_start_shields", "boss_combat",
             "engage_start_shields", 120),
            ("boss_engage_start_boss_hp", "boss_combat",
             "engage_start_boss_hp", 2000),
            ("boss_lure_active", "boss_combat", "lure_active", True),
            ("boss_turret_assist_active", "boss_combat",
             "turret_assist_active", True),
            ("boss_was_killed", "boss_combat", "was_killed", True),
        ]

    def test_setter_writes_through_to_sub_object(self):
        ap._fsm_reset()
        for legacy, sub, attr, value in self._aliases():
            setattr(ap._state, legacy, value)
            assert getattr(getattr(ap._state, sub), attr) == value, (
                f"setting {legacy}={value!r} did not propagate to "
                f"_state.{sub}.{attr}")

    def test_getter_reads_through_from_sub_object(self):
        ap._fsm_reset()
        for legacy, sub, attr, value in self._aliases():
            setattr(getattr(ap._state, sub), attr, value)
            assert getattr(ap._state, legacy) == value, (
                f"setting _state.{sub}.{attr}={value!r} did not "
                f"surface via legacy {legacy}")

    def test_reset_recreates_sub_objects(self):
        """``BotState.reset()`` replaces the sub-state objects rather
        than poking their fields, so adding a new field to a sub-
        dataclass doesn't leak prior-run state.  Verify by flipping
        every field then calling reset() and confirming defaults
        are restored."""
        for _, sub, attr, value in self._aliases():
            setattr(getattr(ap._state, sub), attr, value)
        ap._state.reset()
        defaults = ap.BotState()
        for _, sub, attr, _value in self._aliases():
            assert (getattr(getattr(ap._state, sub), attr)
                    == getattr(getattr(defaults, sub), attr)), (
                f"reset() did not restore _state.{sub}.{attr}")

