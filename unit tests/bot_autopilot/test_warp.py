"""WARP_TO_WORMHOLE + WARP_TRAVERSE transition tests.

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


# ── Fix (2026-05-17): gas-cloud target filter ─────────────────────────



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




class TestWarpToWormholePinTimeout:
    """The 2026-05-23 follow-up: if the bot has been within
    ``stop_radius`` of its wormhole for ``PIN_TIMEOUT_S`` seconds
    without the game's auto-warp firing, abandon the attempt and
    latch ``warp_after_boss_done``.

    Captured pathology: 19 stuck_detected events over 63 s at
    exactly (3310, 4167) -- the bot reached its wormhole goto
    target, ``_do_goto`` released all keys, the game-side warp
    collision never fired, and the stuck-detect / escape-burst
    mechanism couldn't recover because the next
    ``_act_warp_to_wormhole`` call re-asserted the stop.
    """

    def setup_method(self):
        ap._state.warp_wormhole_arrived_at = 0.0
        ap._state.warp_after_boss_done = False

    def _patch_now(self, monkeypatch, clock):
        monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)

    def test_first_arrival_records_arrived_at(self, monkeypatch):
        """Bot enters stop_radius -- arrived_at stamped, no
        timeout, latch not set."""
        clock = [1000.0]
        self._patch_now(monkeypatch, clock)
        s = _state(
            player={"x": 200.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 210.0, "y": 210.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        # Distance ~14 px, well inside stop_radius (50).
        assert ap._state.warp_wormhole_arrived_at == 1000.0
        assert ap._state.warp_after_boss_done is False

    def test_pinned_past_timeout_latches_done(self, monkeypatch):
        """Bot at wormhole for > PIN_TIMEOUT_S -- latch fires,
        timer resets."""
        clock = [1000.0]
        self._patch_now(monkeypatch, clock)
        s = _state(
            player={"x": 200.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 210.0, "y": 210.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        # Tick 1: arrival edge.
        ap._act_warp_to_wormhole(s, s["player"])
        # Tick 2: T+ PIN_TIMEOUT_S + 0.1 -- past the timeout.
        clock[0] += ap.WARP_TO_WORMHOLE_PIN_TIMEOUT_S + 0.1
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_after_boss_done is True
        assert ap._state.warp_wormhole_arrived_at == 0.0

    def test_pinned_within_timeout_does_not_latch(
            self, monkeypatch):
        """Half the timeout elapsed -- latch not yet set."""
        clock = [1000.0]
        self._patch_now(monkeypatch, clock)
        s = _state(
            player={"x": 200.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 210.0, "y": 210.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        clock[0] += ap.WARP_TO_WORMHOLE_PIN_TIMEOUT_S * 0.5
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_after_boss_done is False

    def test_leaving_stop_radius_resets_timer(self, monkeypatch):
        """Bot arrives, then leaves stop_radius (e.g. bumped by
        an alien) -- timer resets so a future re-arrival gets the
        full PIN_TIMEOUT_S window before the latch fires."""
        clock = [1000.0]
        self._patch_now(monkeypatch, clock)
        s = _state(
            player={"x": 200.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 210.0, "y": 210.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        # Arrival tick.
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_wormhole_arrived_at == 1000.0
        # Bot drifts well outside stop_radius (50 px).
        s["player"]["x"] = 500.0
        s["player"]["y"] = 500.0
        clock[0] += 1.0
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_wormhole_arrived_at == 0.0, (
            "timer must reset when bot leaves stop_radius")
        assert ap._state.warp_after_boss_done is False

    def test_far_from_wormhole_arrival_timer_not_armed(
            self, monkeypatch):
        """Bot well outside stop_radius -- the arrival timer
        stays at 0 and the arrival latch doesn't fire.  Clock
        advance is kept below ``NO_PROGRESS_TIMEOUT_S`` so the
        separate no-progress backstop (tested below) doesn't
        also fire here."""
        clock = [1000.0]
        self._patch_now(monkeypatch, clock)
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_wormhole_arrived_at == 0.0
        # Advance well below NO_PROGRESS_TIMEOUT_S (15 s) so only
        # the arrival branch is under test.
        clock[0] += ap.WARP_TO_WORMHOLE_PIN_TIMEOUT_S * 0.5
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_after_boss_done is False

    def test_timeout_emits_telemetry(self, monkeypatch):
        """The pin-timeout fires a ``warp_to_wormhole_pin_timeout``
        telemetry event so the operator can confirm the latch from
        the log instead of having to infer it from the absence of
        further warp_to_wormhole transitions."""
        clock = [1000.0]
        events: list = []
        monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        s = _state(
            player={"x": 200.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 210.0, "y": 210.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        clock[0] += ap.WARP_TO_WORMHOLE_PIN_TIMEOUT_S + 0.1
        ap._act_warp_to_wormhole(s, s["player"])
        timeout_events = [(e, kw) for (e, kw) in events
                          if e == "warp_to_wormhole_pin_timeout"]
        assert len(timeout_events) == 1
        kw = timeout_events[0][1]
        assert kw["wormhole_x"] == 210.0
        assert kw["wormhole_y"] == 210.0
        assert kw["pin_s"] >= ap.WARP_TO_WORMHOLE_PIN_TIMEOUT_S
        # Reason field distinguishes arrival vs no-progress paths.
        assert kw.get("reason") == "arrival"




class TestWarpToWormholeNoProgressBackstop:
    """The 2026-05-23 follow-up: when the bot can't get within
    ``stop_radius`` of any wormhole (boundary repulsion / building
    geometry / etc.), the arrival pin-timeout never arms.  This
    backstop catches the en-route stuck by tracking the bot's
    closest approach this arc and firing if it doesn't improve
    by ``PROGRESS_THRESHOLD_PX`` over ``NO_PROGRESS_TIMEOUT_S``.

    Captured pathology: 7 stuck_detected events at (582, 1347) over
    18 s in WARP_TO_WORMHOLE, hs_dist=4220 (near west world edge).
    Bot was orbiting at the boundary-repulsion radius, never
    reaching the wormhole at the south edge.  PR #163's arrival
    timer didn't help because ``nearest_d`` never dropped below
    stop_radius (50 px).
    """

    def setup_method(self):
        ap._state.warp_wormhole_arrived_at = 0.0
        ap._state.warp_wormhole_best_d = 0.0
        ap._state.warp_wormhole_progress_at = 0.0
        ap._state.warp_after_boss_done = False

    def _patch(self, monkeypatch, clock):
        monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)

    def test_first_en_route_tick_seeds_trackers(self, monkeypatch):
        """Bot far from wormhole on first tick -- ``best_d`` and
        ``progress_at`` get initialized.  Latch not set yet."""
        clock = [1000.0]
        self._patch(monkeypatch, clock)
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_wormhole_progress_at == 1000.0
        # Distance ~1131 px -- this is what best_d gets seeded to.
        assert ap._state.warp_wormhole_best_d > 0
        assert ap._state.warp_after_boss_done is False

    def test_no_progress_past_timeout_latches_done(
            self, monkeypatch):
        """Bot stays at the same distance for longer than
        ``NO_PROGRESS_TIMEOUT_S`` -- backstop latches done."""
        clock = [1000.0]
        self._patch(monkeypatch, clock)
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        # Tick 1 -- seed trackers.
        ap._act_warp_to_wormhole(s, s["player"])
        # Tick 2 -- past timeout, bot at same position.
        clock[0] += ap.WARP_TO_WORMHOLE_NO_PROGRESS_TIMEOUT_S + 0.1
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_after_boss_done is True
        assert ap._state.warp_wormhole_progress_at == 0.0

    def test_progress_resets_no_progress_timer(self, monkeypatch):
        """If the bot makes meaningful progress (best_d drops by
        >= PROGRESS_THRESHOLD_PX), the timer resets so the bot
        gets the full window again to make MORE progress.  This
        is the protective case: a slow but steady transit shouldn't
        get abandoned mid-flight."""
        clock = [1000.0]
        self._patch(monkeypatch, clock)
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        # Tick 1: distance ~1131.
        ap._act_warp_to_wormhole(s, s["player"])
        seed_progress_at = ap._state.warp_wormhole_progress_at
        # Move 200 px closer (well past PROGRESS_THRESHOLD_PX).
        s["player"]["x"] = 858.0
        s["player"]["y"] = 858.0
        clock[0] += 5.0
        ap._act_warp_to_wormhole(s, s["player"])
        # Timer reset to current clock; best_d dropped.
        assert ap._state.warp_wormhole_progress_at > seed_progress_at
        assert ap._state.warp_wormhole_best_d < 1131.0
        # No latch.
        assert ap._state.warp_after_boss_done is False

    def test_micro_wobble_does_not_count_as_progress(
            self, monkeypatch):
        """Sub-threshold movement (boundary-repulsion oscillation)
        does NOT reset the timer.  Captured pathology: bot
        wobbled between (582, 1349) and (582, 1347) at the west
        edge -- 2 px of movement, far below the 50 px progress
        threshold."""
        clock = [1000.0]
        self._patch(monkeypatch, clock)
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        seed_progress_at = ap._state.warp_wormhole_progress_at
        # Move 2 px -- well below PROGRESS_THRESHOLD_PX (50).
        s["player"]["x"] = 998.0
        clock[0] += 5.0
        ap._act_warp_to_wormhole(s, s["player"])
        # Timer NOT reset -- progress_at still at seed value.
        assert ap._state.warp_wormhole_progress_at == seed_progress_at
        # Latch not yet (still well under NO_PROGRESS_TIMEOUT_S).
        assert ap._state.warp_after_boss_done is False
        # Past the timeout -- latch.
        clock[0] += ap.WARP_TO_WORMHOLE_NO_PROGRESS_TIMEOUT_S
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_after_boss_done is True

    def test_no_progress_timeout_emits_telemetry(self, monkeypatch):
        """The no-progress branch fires the same
        ``warp_to_wormhole_pin_timeout`` event but with
        ``reason="no_progress"`` so the operator can tell the
        arrival path from the en-route path in the log."""
        clock = [1000.0]
        events: list = []
        monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **kw: None)
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._act_warp_to_wormhole(s, s["player"])
        clock[0] += ap.WARP_TO_WORMHOLE_NO_PROGRESS_TIMEOUT_S + 0.1
        ap._act_warp_to_wormhole(s, s["player"])
        timeout_events = [(e, kw) for (e, kw) in events
                          if e == "warp_to_wormhole_pin_timeout"]
        assert len(timeout_events) == 1
        kw = timeout_events[0][1]
        assert kw["reason"] == "no_progress"
        assert "best_d" in kw

    def test_on_enter_resets_trackers(self):
        """``_on_enter(S_WARP_TO_WORMHOLE)`` clears stale trackers
        from a prior arc so a fresh entry starts with full
        timeout budgets."""
        # Pre-populate stale state.
        ap._state.warp_wormhole_arrived_at = 999.9
        ap._state.warp_wormhole_best_d = 1234.5
        ap._state.warp_wormhole_progress_at = 555.0
        ap._on_enter(ap.S_WARP_TO_WORMHOLE)
        assert ap._state.warp_wormhole_arrived_at == 0.0
        assert ap._state.warp_wormhole_best_d == 0.0
        assert ap._state.warp_wormhole_progress_at == 0.0




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




class TestWarpTraverseStrictProgressGate:
    """2026-05-17 follow-up to PR #134: ``py_now > max_y`` reset the
    no-progress timer on ANY pixel advance, so a bot inching forward
    3-50 px per traverse cycle (the captured WARP_GAS pathology)
    kept deferring the detour indefinitely.  Captured log: bot
    oscillated for 5+ minutes, max_y crept from 3547 to 3633 via
    dozens of <50 px advances, detour never fired.

    Fix: only reset progress_at when py has advanced
    WARP_TRAVERSE_MEANINGFUL_PROGRESS_PX (200 px) past the last
    committed y.  Tiny advances are recorded in max_y for the
    detour-clear check but don't postpone the timer.
    """

    @staticmethod
    def _capture_goto(monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=30.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        return captured

    def test_tiny_advances_do_not_reset_progress_timer(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Inch forward 50 px every 5 s for 30 s -- the no-progress
        timer must NOT reset on the tiny advances and the detour
        must fire at the 25-s timeout.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 3500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        commit_y_initial = ap._state.warp_traverse_progress_committed_y
        assert commit_y_initial == 3500.0
        # Inch forward 50 px every 5 s for 6 ticks (30 s total).
        # Total advance: 300 px > 200 (meaningful), so the LAST tick
        # should reset the timer.  But the EARLIER ticks should not.
        for step in range(5):
            _clock[0] += 5.0
            s["player"]["y"] += 50.0
            ap._act_warp_traverse(s, s["player"])
            # max_y advances every tick.
            assert ap._state.warp_traverse_max_y == 3500.0 + (step + 1) * 50.0
            # But committed_y stays at the initial value until py
            # crosses the meaningful threshold.
            advance = (step + 1) * 50.0
            if advance < ap.WARP_TRAVERSE_MEANINGFUL_PROGRESS_PX:
                assert (ap._state.warp_traverse_progress_committed_y
                        == commit_y_initial)
        # After enough advance (250 px > 200), committed_y resets.
        # The detour should NOT fire (timer reset by meaningful
        # advance).
        assert (ap._state.warp_traverse_progress_committed_y
                > commit_y_initial)
        assert ap._state.warp_traverse_detour_side == 0

    def test_meaningful_advance_resets_timer(
            self, _clock, _fresh_bot_state, monkeypatch):
        """A single advance >= MEANINGFUL_PROGRESS_PX resets the
        no-progress timer + committed_y."""
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])
        # Advance by exactly MEANINGFUL_PROGRESS_PX.
        _clock[0] += 1.0
        s["player"]["y"] = 3000.0 + ap.WARP_TRAVERSE_MEANINGFUL_PROGRESS_PX
        ap._act_warp_traverse(s, s["player"])
        # Timer reset to now; committed_y advanced.
        assert ap._state.warp_traverse_progress_at == _clock[0]
        assert (ap._state.warp_traverse_progress_committed_y
                == 3000.0 + ap.WARP_TRAVERSE_MEANINGFUL_PROGRESS_PX)

    def test_detour_fires_despite_tiny_advances(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The exact captured pathology: bot advances max_y by 10 px
        every 5 s for 35 s.  Total advance = 70 px < MEANINGFUL.
        Detour SHOULD fire at the 25-s mark even though max_y has
        technically been increasing -- PR #134's regression was that
        it did NOT.
        """
        captured = self._capture_goto(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 3500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._act_warp_traverse(s, s["player"])  # seed
        # Sub-meaningful advances over 30 s of wall-clock time.
        for step in range(6):
            _clock[0] += 5.0
            s["player"]["y"] += 10.0   # only 10 px per cycle
            ap._act_warp_traverse(s, s["player"])
        # 30 s elapsed, total advance 60 px (< 200 = MEANINGFUL).
        # Detour must have fired during this window.
        assert ap._state.warp_traverse_detour_side != 0
        assert ap._state.warp_traverse_detour_count >= 1




class TestWarpTraverseTelemetry:
    """2026-05-17: telemetry events for warp_traverse so post-hoc
    analysis can measure arc duration per zone (especially
    WARP_GAS where multi-minute stalls have been captured).
    Three new events:
      * ``warp_traverse_arc_started`` on entry to a new arc
      * ``warp_traverse_detour_committed`` when the lateral detour
        fires (after the meaningful-progress timeout)
      * ``warp_traverse_arc_completed`` when the bot reaches the
        arrival band (alongside the existing ``warp_traverse_complete``)
    """

    @staticmethod
    def _capture_telemetry(monkeypatch):
        events: list = []
        original = ap._telemetry_log

        def _intercept(event, **kwargs):
            events.append((event, kwargs))
            return original(event, **kwargs)

        monkeypatch.setattr(ap, "_telemetry_log", _intercept)
        return events

    @staticmethod
    def _capture_goto(monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=30.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        return captured

    def test_arc_started_event_fires_on_new_arc(
            self, _clock, _fresh_bot_state, monkeypatch):
        self._capture_goto(monkeypatch)
        events = self._capture_telemetry(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1600.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._act_warp_traverse(s, s["player"])
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_started" in kinds
        arc_start = next(kw for ev, kw in events
                         if ev == "warp_traverse_arc_started")
        assert arc_start.get("zone_id") == "ZoneID.WARP_GAS"
        assert arc_start.get("arc_start_y") == 200.0

    def test_detour_committed_event_fires_on_timeout(
            self, _clock, _fresh_bot_state, monkeypatch):
        self._capture_goto(monkeypatch)
        events = self._capture_telemetry(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1000.0, "y": 3500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._act_warp_traverse(s, s["player"])
        _clock[0] += ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S + 0.5
        ap._act_warp_traverse(s, s["player"])
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_detour_committed" in kinds
        detour = next(kw for ev, kw in events
                      if ev == "warp_traverse_detour_committed")
        assert detour.get("detour_side") == "left"
        assert detour.get("detour_count") == 1
        assert detour.get("zone_id") == "ZoneID.WARP_GAS"

    def test_arc_completed_event_reports_duration(
            self, _clock, _fresh_bot_state, monkeypatch):
        self._capture_goto(monkeypatch)
        events = self._capture_telemetry(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1600.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        # Enter the arc; arc_started_at = 1000.0.
        ap._act_warp_traverse(s, s["player"])
        # Jump the bot into the arrival band to trigger completion.
        _clock[0] += 120.0
        target_y = 6400.0 - ap.WARP_TRAVERSE_MARGIN_PX
        s["player"]["y"] = target_y - ap.WARP_TRAVERSE_ARRIVAL_PX + 10.0
        ap._act_warp_traverse(s, s["player"])
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_completed" in kinds
        arc = next(kw for ev, kw in events
                   if ev == "warp_traverse_arc_completed")
        assert arc.get("zone_id") == "ZoneID.WARP_GAS"
        assert arc.get("arc_duration_s") == 120.0
        # max_y reflects the final position reached.
        assert arc.get("max_y") >= target_y - ap.WARP_TRAVERSE_ARRIVAL_PX




class TestWarpTraverseFsmExitTelemetry:
    """2026-05-17 follow-up: the action handler's arrival-band
    arc_completed emit doesn't fire when the game's auto-zone-
    transition preempts the next ``_act_warp_traverse`` tick.
    Captured log: bot reached y=6352 (inside arrival band), the
    FSM transitioned ``warp_traverse -> search`` at the next tick
    because zone_id flipped from WARP_GAS to ZONE2, no
    arc_completed event ever fired.

    Fix: lifecycle observer ``_observe_warp_traverse_arc_complete``
    emits the event whenever the FSM exits S_WARP_TRAVERSE with an
    arc still in progress (``arc_started_at != 0.0``).  The action
    handler resets ``arc_started_at`` to 0.0 after its own emit so
    the observer doesn't double-fire.
    """

    @staticmethod
    def _capture_telemetry(monkeypatch):
        events: list = []
        original = ap._telemetry_log

        def _intercept(event, **kwargs):
            events.append((event, kwargs))
            return original(event, **kwargs)

        monkeypatch.setattr(ap, "_telemetry_log", _intercept)
        return events

    def test_observer_emits_arc_completed_on_fsm_exit_crossed(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot exited warp_traverse with max_y past the crossed
        threshold -> outcome=crossed."""
        events = self._capture_telemetry(monkeypatch)
        _clock[0] = 1000.0
        # Simulate an arc in progress at a high max_y.
        ap._state.warp_traverse_arc_started_at = 1000.0
        ap._state.warp_traverse_max_y = 6350.0
        ap._state.warp_traverse_detour_count = 2
        ap._fsm["state"] = ap.S_GATHER  # FSM has already exited
        s = _state(
            player={"x": 4800.0, "y": 4600.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=9600, world_h=9600,
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        _clock[0] = 1100.0
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], _clock[0])
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_completed" in kinds
        arc = next(kw for ev, kw in events
                   if ev == "warp_traverse_arc_completed")
        assert arc.get("outcome") == "crossed"
        assert arc.get("arc_duration_s") == 100.0
        assert arc.get("max_y") == 6350.0
        assert arc.get("detour_count") == 2
        # arc_started_at consumed so the next entry starts fresh.
        assert ap._state.warp_traverse_arc_started_at == 0.0

    def test_observer_emits_arc_completed_outcome_interrupted(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot exited the warp zone (zone_id changed from WARP_*
        to MAIN, e.g. died and respawned) with max_y BELOW the
        crossed threshold -> outcome=interrupted."""
        events = self._capture_telemetry(monkeypatch)
        ap._state.warp_traverse_arc_started_at = 1000.0
        ap._state.warp_traverse_max_y = 3000.0  # well below threshold
        ap._fsm["state"] = ap.S_RECOVER_LOOT  # post-death recovery
        s = _state(
            player={"x": 4017.0, "y": 3879.0, "heading": 0.0,
                    "shields": 0, "max_shields": 150},
        )
        # Bot is back in MAIN after dying in the warp zone.
        s["zone"]["id"] = "ZoneID.MAIN"
        _clock[0] = 1200.0
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], _clock[0])
        arc = next(kw for ev, kw in events
                   if ev == "warp_traverse_arc_completed")
        assert arc.get("outcome") == "interrupted"
        assert ap._state.warp_traverse_arc_started_at == 0.0

    def test_observer_noop_when_still_in_warp_traverse(
            self, _clock, _fresh_bot_state, monkeypatch):
        """While the FSM is still in S_WARP_TRAVERSE the observer
        must not fire -- the action handler owns the arc."""
        events = self._capture_telemetry(monkeypatch)
        ap._state.warp_traverse_arc_started_at = 1000.0
        ap._state.warp_traverse_max_y = 3000.0
        ap._fsm["state"] = ap.S_WARP_TRAVERSE  # still owning the arc
        s = _state(
            player={"x": 1600.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], 1100.0)
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_completed" not in kinds
        # arc_started_at NOT consumed.
        assert ap._state.warp_traverse_arc_started_at == 1000.0

    def test_observer_noop_when_no_arc_in_progress(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Fresh BotState (arc_started_at == 0.0) means no arc to
        complete; observer must be a no-op."""
        events = self._capture_telemetry(monkeypatch)
        assert ap._state.warp_traverse_arc_started_at == 0.0
        ap._fsm["state"] = ap.S_MINE
        s = _state(world_w=6400, world_h=6400)
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], 1000.0)
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_completed" not in kinds

    def test_observer_does_not_double_fire_after_action_handler(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If the action handler already fired arc_completed via
        the arrival-band branch (and reset arc_started_at to 0.0),
        the observer must not also fire."""
        events = self._capture_telemetry(monkeypatch)
        # Action handler fired and reset arc_started_at.
        ap._state.warp_traverse_arc_started_at = 0.0
        ap._fsm["state"] = ap.S_GATHER
        s = _state(world_w=3200, world_h=6400)
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], 1100.0)
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_completed" not in kinds

    def test_observer_noop_during_regen_in_warp_zone(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Captured 2026-05-17 regression: PR #137's observer fired
        arc_completed every time the FSM transitioned warp_traverse
        -> regen within the same warp zone, resetting arc_started_at
        and indirectly resetting every per-arc tracker on the next
        regen -> traverse re-entry.  This disabled PR #134's
        persistent detour side.

        Fix: observer no-ops while ``"WARP" in zone_id``.  Only
        actual zone exits (zone-cross to ZONE2, death-respawn to
        MAIN) count as arc completion.
        """
        events = self._capture_telemetry(monkeypatch)
        ap._state.warp_traverse_arc_started_at = 1000.0
        ap._state.warp_traverse_max_y = 3000.0
        ap._state.warp_traverse_detour_count = 1
        ap._state.warp_traverse_detour_side = 1
        ap._fsm["state"] = ap.S_REGEN  # paused for shield recovery
        s = _state(
            player={"x": 1600.0, "y": 3000.0, "heading": 0.0,
                    "shields": 0, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"  # still in warp zone
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], 1200.0)
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_completed" not in kinds
        # All per-arc trackers preserved across the regen pause.
        assert ap._state.warp_traverse_arc_started_at == 1000.0
        assert ap._state.warp_traverse_max_y == 3000.0
        assert ap._state.warp_traverse_detour_count == 1
        assert ap._state.warp_traverse_detour_side == 1

    def test_observer_fires_on_zone_cross_to_nebula(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot crossed the warp zone (max_y near top) and the game's
        auto-zone-transition moved it to ZONE2.  Observer fires
        with outcome=crossed."""
        events = self._capture_telemetry(monkeypatch)
        ap._state.warp_traverse_arc_started_at = 1000.0
        ap._state.warp_traverse_max_y = 6300.0
        ap._fsm["state"] = ap.S_SEARCH
        s = _state(world_w=9600, world_h=9600)
        s["zone"]["id"] = "ZoneID.ZONE2"  # no longer WARP
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], 1100.0)
        arc = next(kw for ev, kw in events
                   if ev == "warp_traverse_arc_completed")
        assert arc.get("outcome") == "crossed"

    def test_observer_fires_on_death_respawn_to_main(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot died in the warp zone, respawned in MAIN.  Observer
        fires with outcome=interrupted."""
        events = self._capture_telemetry(monkeypatch)
        ap._state.warp_traverse_arc_started_at = 1000.0
        ap._state.warp_traverse_max_y = 2500.0  # didn't cross
        ap._fsm["state"] = ap.S_RECOVER_LOOT
        s = _state(world_w=6400, world_h=6400)
        s["zone"]["id"] = "ZoneID.MAIN"  # respawn target
        ap._observe_warp_traverse_arc_complete(
            s, s["player"], 1050.0)
        arc = next(kw for ev, kw in events
                   if ev == "warp_traverse_arc_completed")
        assert arc.get("outcome") == "interrupted"
        # Trackers consumed so the next arc starts fresh.
        assert ap._state.warp_traverse_arc_started_at == 0.0




class TestWarpTraverseSpuriousArcStartedGuard:
    """2026-05-17 follow-up: the first-ever new-arc detection in
    ``_act_warp_traverse`` fired ``arc_started`` whenever
    ``arc_started_at == 0.0``, regardless of position.  When the
    bot crossed MAIN -> WARP_GAS the state's zone_id flipped to the
    new zone one tick before the position field updated to the new
    zone's spawn coords, so a SPURIOUS arc_started fired with the
    bot's MAIN-zone position (top of MAIN, py=6224.7) followed by
    a LEGIT one with the real spawn (py=200).

    Fix: gate the first-ever case by ``py_now < world_h * 0.5``
    so only positions consistent with a real warp-zone entry
    trigger the new-arc branch.
    """

    @staticmethod
    def _capture_telemetry(monkeypatch):
        events: list = []
        original = ap._telemetry_log

        def _intercept(event, **kwargs):
            events.append((event, kwargs))
            return original(event, **kwargs)

        monkeypatch.setattr(ap, "_telemetry_log", _intercept)
        return events

    @staticmethod
    def _capture_goto(monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=30.0,
            brake_on_arrival=True: captured.update(tx=tx, ty=ty))
        return captured

    def test_stale_main_coords_do_not_trigger_arc_started(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Reproduces the captured race: first call sees zone_id=
        WARP_GAS but the position field is still in MAIN coords
        (top half: py=6224.7).  ``arc_started`` MUST NOT fire."""
        self._capture_goto(monkeypatch)
        events = self._capture_telemetry(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 293.5, "y": 6224.7, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._act_warp_traverse(s, s["player"])
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_started" not in kinds
        # arc_started_at unchanged.
        assert ap._state.warp_traverse_arc_started_at == 0.0

    def test_real_spawn_position_does_trigger_arc_started(
            self, _clock, _fresh_bot_state, monkeypatch):
        """A position consistent with a real warp-zone entry
        (bottom half) does fire arc_started."""
        self._capture_goto(monkeypatch)
        events = self._capture_telemetry(monkeypatch)
        _clock[0] = 1000.0
        s = _state(
            player={"x": 1600.0, "y": 200.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._act_warp_traverse(s, s["player"])
        kinds = [ev for ev, _ in events]
        assert "warp_traverse_arc_started" in kinds
        arc = next(kw for ev, kw in events
                   if ev == "warp_traverse_arc_started")
        assert arc.get("arc_start_y") == 200.0

    def test_only_one_arc_started_when_stale_then_real_state(
            self, _clock, _fresh_bot_state, monkeypatch):
        """End-to-end: simulate the captured race -- stale call
        first, real call second.  Only ONE arc_started must fire,
        for the real spawn coords."""
        self._capture_goto(monkeypatch)
        events = self._capture_telemetry(monkeypatch)
        _clock[0] = 1000.0
        # Stale call with MAIN coords.
        s = _state(
            player={"x": 293.5, "y": 6224.7, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"
        ap._act_warp_traverse(s, s["player"])
        # Real spawn position on the next tick.
        _clock[0] += 0.1
        s["player"]["x"] = 1600.0
        s["player"]["y"] = 200.0
        ap._act_warp_traverse(s, s["player"])
        starts = [kw for ev, kw in events
                  if ev == "warp_traverse_arc_started"]
        assert len(starts) == 1
        assert starts[0].get("arc_start_y") == 200.0




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




class TestWarpRelatchPendingBestEffort:
    """2026-05-17 follow-up to PR #129: the lifecycle relatch
    correctly clears ``warp_after_boss_done`` when the bot is
    observed back in MAIN, but the S_WARP_TO_WORMHOLE cascade
    still required consumables in quick-use slots.  After death,
    the bot's slots get wiped and the one-shot consumable craft
    phase has already been used -- so the cascade falls through
    to GATHER and the bot is stranded farming Zone 1 forever.

    Captured log: bot died at (5566, 4948), relatched at (4016,
    3878), installed 4 recovered modules, then went straight to
    GATHER without ever attempting a warp.

    Fix: ``_observe_warp_back_to_main`` now sets a
    ``warp_relatched_pending`` flag.  While this flag is True, the
    S_WARP_TO_WORMHOLE cascade fires even without consumables in
    slots -- a best-effort warp on the assumption that being
    stranded in MAIN is worse than warping unprepared.  The flag
    clears once the cascade detects the bot has left MAIN.
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
        # NO quick_use_slots -- this is the post-death case where
        # the slots are wiped.
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        return s

    def test_relatch_sets_pending_flag(
            self, _clock, _fresh_bot_state):
        """``_observe_warp_back_to_main`` sets the pending flag
        alongside clearing the other latches."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_traverse_done = True
        ap._state.warp_relatched_pending = False
        s = self._ready_state(zone="ZoneID.MAIN")
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert ap._state.warp_relatched_pending is True

    def test_warp_fires_without_consumables_when_pending(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The captured pathology: post-death state with no
        consumables in slots.  Pending flag set -> cascade still
        fires S_WARP_TO_WORMHOLE."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = True
        ap._state.queue.modules_to_install = []
        s = self._ready_state(zone="ZoneID.MAIN")
        # No quick_use_slots in state -- captured post-death state.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE

    def test_warp_still_blocked_without_pending_no_consumables(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Without the pending flag, the cascade STILL requires
        consumables -- the initial post-boss warp behavior is
        unchanged (the gate exists to ensure the first warp is
        prepared)."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = False  # NOT relatched
        ap._state.queue.modules_to_install = []
        s = self._ready_state(zone="ZoneID.MAIN")
        # No quick_use_slots -- gate fails.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_pending_clears_on_main_exit(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Once the bot leaves MAIN (zone_id no longer contains
        MAIN), the cascade clears the pending flag alongside
        setting warp_after_boss_done."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = True
        s = _state(
            player={"x": 1600.0, "y": 500.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            world_w=3200, world_h=6400,
        )
        s["zone"]["id"] = "ZoneID.WARP_GAS"  # out of MAIN
        ap._do_auto(s, s["player"])
        assert ap._state.warp_after_boss_done is True
        assert ap._state.warp_relatched_pending is False

    def test_consumables_still_preferred_when_present(
            self, _clock, _fresh_bot_state, monkeypatch):
        """With consumables in slots AND pending flag, the cascade
        still fires (the relaxation is additive, not replacing)."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = True
        ap._state.queue.modules_to_install = []
        s = self._ready_state(zone="ZoneID.MAIN")
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5},
            {"item_type": "shield_recharge", "count": 5},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE

    def test_modules_to_install_still_blocks_when_reachable(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If the queued modules are in station inventory
        (reachable), S_INSTALL still preempts S_WARP_TO_WORMHOLE
        -- the bot installs first then warps.  The relatch
        relaxation only kicks in when modules are UNREACHABLE
        (e.g., dropped at a Nebula death position).  Covered by
        ``test_modules_unreachable_lets_relatch_warp`` below.
        """
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = True
        ap._state.queue.modules_to_install = ["broadside"]
        s = self._ready_state(zone="ZoneID.MAIN")
        # Module is in station inventory -- reachable.
        s["station_inventory"]["items"]["mod_broadside"] = 1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_modules_unreachable_lets_relatch_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Captured 2026-05-17: bot's 6th relatch had
        ``modules_to_install_left=4`` but the modules were at a
        Nebula death position (bot returned to MAIN via the
        central wormhole without dying).  S_INSTALL couldn't
        fire (modules not in station inv), S_WARP_TO_WORMHOLE
        couldn't fire (queue non-empty), bot farmed MAIN for
        20+ minutes.

        Fix: when ``warp_relatched_pending`` is True AND
        ``_next_install_target`` returns None despite a non-empty
        queue, the modules check is bypassed and the warp fires.
        """
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = True
        # Queue has modules but station_inventory is empty --
        # _next_install_target returns None.
        ap._state.queue.modules_to_install = [
            "shield_booster", "broadside", "shield_enhancer",
            "armor_plate"]
        s = self._ready_state(zone="ZoneID.MAIN")
        # Empty station inv -- modules unreachable.
        assert s["station_inventory"]["items"] == {}
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE

    def test_modules_unreachable_without_relatch_does_not_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Without ``warp_relatched_pending``, the modules-
        unreachable case does NOT bypass the gate.  Initial
        post-boss behavior is unchanged -- the gate only relaxes
        on a relatch.
        """
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = False
        ap._state.queue.modules_to_install = ["broadside"]
        s = self._ready_state(zone="ZoneID.MAIN")
        # Module not in station -- but no relatch, so gate holds.
        s["quick_use_slots"] = [
            {"item_type": "repair_pack", "count": 5},
            {"item_type": "shield_recharge", "count": 5},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE




class TestWarpRecraftBeforeRewarp:
    """2026-05-17 follow-up to PR #141: PRs #138 / #139 added a
    best-effort warp that bypasses the consumables + modules gates
    when the bot is stranded in MAIN after a return.  That kept
    the bot from being permanently stuck, but the bot then warped
    UNDER-PREPARED -- captured logs showed it dying repeatedly in
    successive warp zones because the one-shot craft queues are
    exhausted by the first arc.

    Fix: the relatch observer now tops up the consumable craft
    queue (when station inv is depleted) and re-queues unreachable
    modules for re-crafting.  The warp cascade defers the best-
    effort warp when any of CRAFT / INSTALL / EQUIP can fire --
    so the bot finishes its prep before re-entering the wormholes.
    """

    @staticmethod
    def _staged_relatch_state(zone="ZoneID.MAIN"):
        s = _state(
            player={"x": 4017.0, "y": 3879.0, "heading": 0.0,
                    "shields": 80, "max_shields": 100},
            buildings=[
                {"x": 4000.0, "y": 4000.0,
                 "building_type": "Home Station"},
                {"x": 4100.0, "y": 4100.0,
                 "building_type": "Basic Crafter"},
            ],
        )
        s["zone"]["id"] = zone
        return s

    def test_relatch_tops_up_consumable_queue_when_depleted(
            self, _clock, _fresh_bot_state):
        """If station has no consumables AND queue counters are 0,
        the relatch observer tops them up to the WARP_RECRAFT
        defaults so the bot crafts more before re-warping.
        """
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        s = self._staged_relatch_state()
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert (ap._state.queue.repair_packs_remaining
                == ap.WARP_RECRAFT_REPAIR_BATCHES)
        assert (ap._state.queue.shield_recharges_remaining
                == ap.WARP_RECRAFT_SHIELD_BATCHES)

    def test_relatch_does_not_top_up_when_station_has_consumables(
            self, _clock, _fresh_bot_state):
        """If station already has consumables, don't top up the
        queue -- the existing stash is enough."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        s = self._staged_relatch_state()
        # Station has consumables -- no re-craft needed.
        s["station_inventory"]["items"]["repair_pack"] = 10
        s["station_inventory"]["items"]["shield_recharge"] = 10
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert ap._state.queue.repair_packs_remaining == 0
        assert ap._state.queue.shield_recharges_remaining == 0

    def test_relatch_requeues_unreachable_modules_to_craft(
            self, _clock, _fresh_bot_state):
        """Modules in the install queue but not in station inv
        get re-queued for crafting so the bot rebuilds them from
        blueprints."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.queue.modules_to_install = [
            "shield_booster", "broadside"]
        ap._state.queue.modules_to_craft.clear()
        s = self._staged_relatch_state()
        # Station inv is empty -- modules unreachable.
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        # Modules re-added to craft queue.
        assert "shield_booster" in ap._state.queue.modules_to_craft
        assert "broadside" in ap._state.queue.modules_to_craft

    def test_relatch_does_not_requeue_when_modules_reachable(
            self, _clock, _fresh_bot_state):
        """If the install target IS reachable (modules in station),
        don't re-queue for crafting -- just install the existing
        copies."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.queue.modules_to_install = ["broadside"]
        ap._state.queue.modules_to_craft.clear()
        s = self._staged_relatch_state()
        # Module IS in station -- reachable for install.
        s["station_inventory"]["items"]["mod_broadside"] = 1
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        # No re-queue -- existing copy will be installed.
        assert ap._state.queue.modules_to_craft == []

    def test_warp_defers_when_consumables_in_station_unequipped(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot has consumables in station but slots are empty.
        Warp cascade defers so the EQUIP cascade can fire."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = True
        ap._state.queue.modules_to_install = []
        s = self._staged_relatch_state()
        # Station has consumables; quick_use slots empty.
        s["station_inventory"]["items"]["repair_pack"] = 10
        s["station_inventory"]["items"]["shield_recharge"] = 10
        ap._do_auto(s, s["player"])
        # Warp deferred -- EQUIP work available.
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_warp_fires_when_no_prep_work_available(
            self, _clock, _fresh_bot_state, monkeypatch):
        """When truly nothing to do at station (no craft, no
        install, no equip), the best-effort warp fires."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.warp_relatched_pending = True
        ap._state.queue.modules_to_install = []
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.queue.consumable_phase_started = True
        s = self._staged_relatch_state()
        # Empty station + empty queue + no install + no consumables
        # in slots -- nothing prep can do.  Warp fires.
        s["wormholes"] = [
            {"x": 200.0, "y": 200.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE


# ── Nebula-death recovery gate (2026-05-24) ───────────────────────────────


class TestNebulaDeathRecoveryGate:
    """Captured 2026-05-24 bot_io: 22 player_death events in a
    35-minute window, 20 of them in ZONE2 or the warp zones
    en-route.  The bot looped warp -> die in Nebula -> respawn ->
    warp back without rebuilding its consumable buffer or healing
    -- the existing relatch recraft only fires when station inv is
    empty, and the best-effort warp gate fires whenever no prep
    work is available, so a bot with empty quick-use slots and no
    consumables anywhere warped under-prepared every time.

    Fix: ``nebula_recovery_pending`` latches True at the alive ->
    dead edge when the death happens in ZONE2.  While latched:
      * ``_observe_warp_back_to_main`` aggressively tops up the
        consumable craft queue with NEBULA_RECOVERY_*_BATCHES even
        when station inv has some consumables (the goal is fresh
        25 + 25 batches, not "just enough to fire");
      * the warp-to-wormhole gate in ``choose_next_state`` becomes
        strict: consumables-in-slots AND HP / shields at the
        configured recovery percentages (default 100 %).  No
        best-effort relaxation.
      * Cleared by the existing ``warp_after_boss_complete``
        observer once the warp-out lands.
    """

    @staticmethod
    def _ready_to_warp_state(*, hp_pct=1.0, shields_pct=1.0,
                             have_repair=True, have_shield=True):
        """Set up a /state where the bot is at the Home Station in
        MAIN, modules installed, station inv has consumables, and
        the various warp gates are satisfied except for the
        Nebula-recovery checks the test wants to exercise."""
        s = _state(
            player={"x": 4000.0, "y": 4000.0, "heading": 0.0,
                    "shields": int(150 * shields_pct),
                    "max_shields": 150,
                    "hp": int(200 * hp_pct), "max_hp": 200},
            buildings=[_hs_building(x=4000.0, y=4000.0)],
        )
        s["zone"]["id"] = "ZoneID.MAIN"
        s["wormholes"] = [
            {"x": 4500.0, "y": 4500.0,
             "zone_target": "ZoneID.WARP_METEOR"},
        ]
        slots = []
        if have_repair:
            slots.append({"item_type": "repair_pack", "count": 5})
        if have_shield:
            slots.append({"item_type": "shield_recharge", "count": 5})
        s["quick_use_slots"] = slots
        return s

    def _arm_state_for_warp(self):
        """Set the warp-cascade latches so the warp gate is the only
        thing standing between cur and S_WARP_TO_WORMHOLE."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.queue.modules_to_install.clear()
        ap._state.queue.modules_to_craft.clear()
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.queue.consumable_phase_started = True
        ap._state.consumables_equipped = True

    # ── Latch arming ──────────────────────────────────────────────────

    def test_death_in_nebula_sets_nebula_recovery_pending(
            self, _clock, _fresh_bot_state):
        """Alive -> dead edge with zone_id containing ZONE2 must
        arm the recovery latch."""
        ap._state.nebula_recovery_pending = False
        ap._state.was_dead = False
        ap._state.last_alive_pos = (4000.0, 4000.0)
        s = _state(player={"x": 4000.0, "y": 4000.0,
                           "heading": 0.0, "shields": 0,
                           "max_shields": 150, "is_dead": True})
        s["zone"]["id"] = "ZoneID.ZONE2"
        ap._observe_death_edges(s, s["player"], 1000.0)
        assert ap._state.nebula_recovery_pending is True
        assert ap._state.was_dead is True

    def test_death_in_main_does_not_arm_latch(
            self, _clock, _fresh_bot_state):
        """Death in MAIN doesn't trigger Nebula recovery -- the
        bot's just at home, not stranded after a Nebula run."""
        ap._state.nebula_recovery_pending = False
        ap._state.was_dead = False
        ap._state.last_alive_pos = (4000.0, 4000.0)
        s = _state(player={"x": 4000.0, "y": 4000.0,
                           "heading": 0.0, "shields": 0,
                           "max_shields": 150, "is_dead": True})
        s["zone"]["id"] = "ZoneID.MAIN"
        ap._observe_death_edges(s, s["player"], 1000.0)
        assert ap._state.nebula_recovery_pending is False

    def test_death_in_warp_zone_does_not_arm_latch(
            self, _clock, _fresh_bot_state):
        """Warp-zone deaths are en-route; the strict ZONE2 check
        means warp-zone deaths leave the existing best-effort
        relaxation in place (existing behaviour unchanged)."""
        ap._state.nebula_recovery_pending = False
        ap._state.was_dead = False
        ap._state.last_alive_pos = (3000.0, 3000.0)
        s = _state(player={"x": 3000.0, "y": 3000.0,
                           "heading": 0.0, "shields": 0,
                           "max_shields": 150, "is_dead": True})
        s["zone"]["id"] = "ZoneID.WARP_ENEMY"
        ap._observe_death_edges(s, s["player"], 1000.0)
        assert ap._state.nebula_recovery_pending is False

    # ── Warp-back observer top-up ────────────────────────────────────

    def test_relatch_observer_force_tops_up_when_recovery_pending(
            self, _clock, _fresh_bot_state):
        """When the recovery latch is set, the warp-back observer
        tops up the consumable queue to NEBULA_RECOVERY_*_BATCHES
        even when station already has some consumables."""
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.nebula_recovery_pending = True
        ap._state.queue.repair_packs_remaining = 0
        ap._state.queue.shield_recharges_remaining = 0
        ap._state.queue.consumable_phase_started = True
        ap._state.consumables_equipped = True
        s = _state(
            player={"x": 4017.0, "y": 3879.0, "heading": 0.0},
            buildings=[_hs_building()])
        s["zone"]["id"] = "ZoneID.MAIN"
        # Station already has SOME consumables -- the basic recraft
        # would skip; the Nebula-recovery path tops up anyway.
        s["station_inventory"]["items"]["repair_pack"] = 4
        s["station_inventory"]["items"]["shield_recharge"] = 4
        ap._observe_warp_back_to_main(s, s["player"], 0.0)
        assert (ap._state.queue.repair_packs_remaining
                == ap.NEBULA_RECOVERY_REPAIR_BATCHES)
        assert (ap._state.queue.shield_recharges_remaining
                == ap.NEBULA_RECOVERY_SHIELD_BATCHES)
        # Re-arms the consumable craft phase so cascade picks it up.
        assert ap._state.queue.consumable_phase_started is False
        assert ap._state.consumables_equipped is False

    # ── Warp gate strict mode ────────────────────────────────────────

    def test_recovery_latch_blocks_best_effort_warp(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Without the Nebula latch, an empty-everything bot
        warps via the best-effort path.  With the latch set, the
        warp must be blocked even when no prep work is available
        -- the bot needs to stay at HS until fully ready."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        self._arm_state_for_warp()
        ap._state.warp_relatched_pending = True
        ap._state.nebula_recovery_pending = True
        s = self._ready_to_warp_state(
            have_repair=False, have_shield=False)
        s["station_inventory"]["items"] = {}
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_recovery_latch_blocks_warp_without_consumables(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Even with full HP/shields, missing consumables in slots
        blocks the warp while the latch is set."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        self._arm_state_for_warp()
        ap._state.nebula_recovery_pending = True
        s = self._ready_to_warp_state(
            have_repair=False, have_shield=False)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_recovery_latch_blocks_warp_below_hp_threshold(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Full consumables + full shields but HP below the
        recovery threshold -- still blocked."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        self._arm_state_for_warp()
        ap._state.nebula_recovery_pending = True
        s = self._ready_to_warp_state(hp_pct=0.5, shields_pct=1.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_recovery_latch_blocks_warp_below_shields_threshold(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Full HP but shields below the recovery threshold --
        still blocked."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        self._arm_state_for_warp()
        ap._state.nebula_recovery_pending = True
        s = self._ready_to_warp_state(hp_pct=1.0, shields_pct=0.5)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_WARP_TO_WORMHOLE

    def test_recovery_latch_releases_when_fully_ready(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Latch + consumables in slots + full HP + full shields:
        the warp fires."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        self._arm_state_for_warp()
        ap._state.nebula_recovery_pending = True
        s = self._ready_to_warp_state(hp_pct=1.0, shields_pct=1.0)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TO_WORMHOLE

    # ── Latch clearing on warp-out ───────────────────────────────────

    def test_warp_out_clears_recovery_latch(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Once the bot's warp arc lands (first non-MAIN tick after
        boss-killed), the warp_after_boss_complete observer in
        choose_next_state clears the latch so the next death
        cycle starts fresh."""
        monkeypatch.setattr(
            ap, "_act_warp_to_wormhole", lambda s, p: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = False
        ap._state.nebula_recovery_pending = True
        s = self._ready_to_warp_state()
        s["zone"]["id"] = "ZoneID.WARP_METEOR"
        ap._do_auto(s, s["player"])
        assert ap._state.warp_after_boss_done is True
        assert ap._state.nebula_recovery_pending is False




class TestWarpPinRetryCooldown:
    """2026-06-08: all four MAIN wormholes are in corners inside the
    boundary-repulsion margin.  When the bot pins ~1800 px short of one,
    the watchdog abandons the warp, but `_observe_warp_back_to_main`
    re-armed within a tick and re-targeted the SAME corner -- a ~15 s
    loop (8 pin-timeouts + 8 relatches over ~110 s).  A pin-timeout now
    sets `warp_pin_retry_after`, and the relatch observer holds off until
    it elapses."""

    def setup_method(self):
        ap._state.warp_wormhole_arrived_at = 0.0
        ap._state.warp_wormhole_progress_at = 0.0
        ap._state.warp_wormhole_best_d = 0.0
        ap._state.warp_after_boss_done = False
        ap._state.warp_pin_retry_after = 0.0

    def _wh_state(self):
        # Bot pinned far from a single corner wormhole.
        s = _state(player={"x": 1500.0, "y": 1500.0, "heading": 0.0,
                           "shields": 150, "max_shields": 150})
        s["wormholes"] = [{"x": 200.0, "y": 200.0,
                           "zone_target": "ZoneID.WARP_METEOR"}]
        return s

    def test_progress_watchdog_sets_cooldown(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **k: None)
        monkeypatch.setattr(ap, "_telemetry_log", lambda *a, **k: None)
        s = self._wh_state()
        ap._act_warp_to_wormhole(s, s["player"])           # arms progress timer
        clock[0] += ap.WARP_TO_WORMHOLE_NO_PROGRESS_TIMEOUT_S + 0.1
        ap._act_warp_to_wormhole(s, s["player"])           # no progress -> timeout
        assert ap._state.warp_after_boss_done is True
        assert ap._state.warp_pin_retry_after == (
            clock[0] + ap.WARP_PIN_RETRY_COOLDOWN_S)

    def test_arrival_watchdog_sets_cooldown(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(ap, "_get_now", lambda: clock[0])
        monkeypatch.setattr(ap, "_do_goto", lambda *a, **k: None)
        monkeypatch.setattr(ap, "_telemetry_log", lambda *a, **k: None)
        # Wormhole within stop_radius so the arrival watchdog arms.
        s = _state(player={"x": 200.0, "y": 200.0, "heading": 0.0,
                           "shields": 150, "max_shields": 150})
        s["wormholes"] = [{"x": 210.0, "y": 210.0,
                           "zone_target": "ZoneID.WARP_METEOR"}]
        ap._act_warp_to_wormhole(s, s["player"])
        clock[0] += ap.WARP_TO_WORMHOLE_PIN_TIMEOUT_S + 0.1
        ap._act_warp_to_wormhole(s, s["player"])
        assert ap._state.warp_after_boss_done is True
        assert ap._state.warp_pin_retry_after == (
            clock[0] + ap.WARP_PIN_RETRY_COOLDOWN_S)

    def _main_state(self):
        s = _state(player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                           "shields": 150, "max_shields": 150},
                   buildings=[_hs_building()])
        s["zone"]["id"] = "ZoneID.MAIN"
        return s

    def test_relatch_suppressed_within_cooldown(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_telemetry_log", lambda *a, **k: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_pin_retry_after = 1000.0
        s = self._main_state()
        ap._observe_warp_back_to_main(s, s["player"], 970.0)   # within cooldown
        assert ap._state.warp_after_boss_done is True          # NOT re-armed

    def test_relatch_fires_after_cooldown(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_telemetry_log", lambda *a, **k: None)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._state.warp_pin_retry_after = 1000.0
        s = self._main_state()
        ap._observe_warp_back_to_main(s, s["player"], 1001.0)  # past cooldown
        assert ap._state.warp_after_boss_done is False         # re-armed
