"""FLEE_GAS state + gas-lingering observer tests.

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




# ── FLEE_GAS (2026-05-18) ────────────────────────────────────────────────


class TestFleeGasFSM:
    """Pin the new S_FLEE_GAS state: when the bot is inside a
    damaging gas cloud, FSM must preempt productive states
    (ENGAGE, MINE, GATHER, HUNT, ENGAGE_BOSS, WARP_TRAVERSE) and
    drive the bot out of the cloud.

    Captured pathology (2026-05-18 autopilot_telemetry.jsonl):
    bot in S_ENGAGE inside WARP_GAS at (3823, 3089), shields
    drained 18 -> 0 over 3 s of stuck_detected events while it
    fought an alien standing in the same cloud.  Pre-fix the
    only gas-escape lived inside ``_act_regen`` so non-REGEN
    states sat in the damage field.
    """

    def _gas_state(self, **overrides):
        """Build a state dict with a gas cloud at (0, 0) and the
        player inside it.  Overrides let individual tests change
        player position, aliens, shields, etc."""
        s = _state(**{k: v for k, v in overrides.items()
                      if k != "gas_areas"})
        s["gas_areas"] = overrides.get("gas_areas",
                                       [{"x": 0.0, "y": 0.0,
                                         "radius": 200.0}])
        return s

    def test_inside_gas_with_alien_nearby_picks_flee_gas_over_engage(
            self, _clock):
        """The exact captured scenario: alien in engage range,
        bot inside a gas cloud.  Pre-fix the bot picked ENGAGE
        and bled out.  Post-fix S_FLEE_GAS preempts."""
        s = self._gas_state(
            player={"x": 50.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            aliens=[{"x": 100.0, "y": 0.0, "hp": 50}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FLEE_GAS

    def test_inside_gas_with_asteroid_picks_flee_gas_over_mine(
            self, _clock):
        s = self._gas_state(
            player={"x": 50.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 80.0, "y": 0.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FLEE_GAS

    def test_inside_gas_with_pickup_picks_flee_gas_over_gather(
            self, _clock):
        s = self._gas_state(
            player={"x": 50.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            iron_pickups=[{"x": 60.0, "y": 0.0}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FLEE_GAS

    def test_outside_gas_does_not_pick_flee_gas(self, _clock):
        """Bot at (500, 0), gas cloud at origin with 200 px
        radius — bot is well clear, FSM picks the normal
        productive state (MINE on the visible asteroid)."""
        s = self._gas_state(
            player={"x": 500.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 600.0, "y": 0.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FLEE_GAS

    def test_inside_gas_with_low_shields_picks_regen_not_flee(
            self, _clock):
        """REGEN must still preempt FLEE_GAS: shields below 40 %
        is the more urgent defensive interrupt, and
        ``_act_regen`` already has its own gas-escape ramp."""
        s = self._gas_state(
            player={"x": 50.0, "y": 0.0, "heading": 0.0,
                    "shields": 30, "max_shields": 150},   # 20 %
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN

    def test_no_gas_in_state_does_not_pick_flee(self, _clock):
        """If the ``gas_areas`` key is missing from state
        (older API, MAIN zone) the FSM never picks FLEE_GAS
        even at the world origin."""
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 80.0, "y": 0.0, "hp": 100}],
        )
        assert "gas_areas" not in s
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FLEE_GAS

    def test_flee_gas_preempts_engage_boss_when_in_cloud(
            self, _clock):
        """Boss alive + inside a gas cloud: FLEE_GAS preempts
        the boss fight.  Sitting in gas during a boss fight just
        compounds boss DPS with gas DPS; better to step out.
        The boss won't despawn -- next tick post-escape the
        cascade re-enters ENGAGE_BOSS automatically."""
        s = self._gas_state(
            player={"x": 50.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            buildings=[{"building_type": "Home Station",
                        "x": 1000.0, "y": 0.0, "hp": 1000}],
        )
        s["boss"] = {"x": 300.0, "y": 0.0, "hp": 500, "phase": 1}
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FLEE_GAS

    def test_flee_gas_exits_when_bot_leaves_cloud(self, _clock):
        """Enter FLEE_GAS while inside, then simulate the bot
        driving well clear of the cloud (past edge + exit
        margin).  After MIN_DWELL_S the FSM transitions out --
        proves the state isn't sticky once the gas no longer
        surrounds the bot."""
        s = self._gas_state(
            player={"x": 50.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 600.0, "y": 0.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FLEE_GAS
        # Bot drives well clear: 600 px from a 200 px radius
        # cloud centred at origin is 400 px past the edge, well
        # past the 100 px exit margin.  Advance past MIN_DWELL
        # so the FSM is free to transition.
        s["player"]["x"] = 600.0
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FLEE_GAS

    def test_flee_gas_holds_inside_exit_margin(self, _clock):
        """Exit hysteresis: bot is just past the cloud edge but
        still within ``FLEE_GAS_EXIT_MARGIN_PX``.  FSM must hold
        S_FLEE_GAS rather than releasing to a productive state
        that would drive the bot straight back into the cloud.

        Captured pathology (2026-05-18 telemetry, 17 FLEE_GAS
        <-> WARP_TRAVERSE flips, one 93 ms dwell, shields losing
        ~52 px per thrash cycle).
        """
        s = self._gas_state(
            player={"x": 50.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 600.0, "y": 0.0, "hp": 100}],
        )
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FLEE_GAS
        # Move bot just past the cloud edge but inside the exit
        # margin: distance from cloud centre = 250, cloud radius
        # 200, margin 100, so 250 is inside (radius + margin).
        s["player"]["x"] = 250.0
        _clock[0] += ap.MIN_DWELL_S + 0.1
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_FLEE_GAS, (
            "FLEE_GAS must hold while bot is inside the exit "
            "margin -- otherwise the downstream traverse/engage "
            "drive pulls it straight back into the cloud")

    def test_flee_gas_entry_uses_strict_radius_no_margin(
            self, _clock):
        """Entry side of the hysteresis: when NOT already in
        FLEE_GAS, the bot must be genuinely inside the cloud
        (distance < radius, no margin applied) before the state
        fires.  Otherwise FLEE_GAS would pre-emptively trigger
        every time the bot drives within margin of any cloud,
        thrashing the cascade and preventing legitimate work
        like mining a cluster that happens to sit near a gas
        field."""
        s = self._gas_state(
            player={"x": 250.0, "y": 0.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 300.0, "y": 0.0, "hp": 100}],
        )
        # Bot at 250, cloud at 0 radius 200 -- bot is 50 px PAST
        # the cloud edge, but within the 100 px exit margin.
        # Since cur != S_FLEE_GAS, the entry path uses the
        # strict radius and does NOT fire FLEE_GAS.
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_FLEE_GAS




class TestFleeGasActionHandler:
    """The action handler must drive the bot along the cloud-
    centre -> bot ray, targeting a point past the cloud edge by
    REGEN_GAS_ESCAPE_MARGIN_PX so the bot exits the field, not
    hugs it."""

    def test_handler_drives_along_repulsion_vector(
            self, monkeypatch):
        """Single cloud at (3000, 3000) r=200; bot at (3100, 3000).
        Net gas-repulsion vector points +X away from the cloud
        centre.  Action handler drives ``FLEE_GAS_CLUSTER_ESCAPE_PX``
        along that vector from the bot's current position."""
        goto_calls: list = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0:
                goto_calls.append((tx, ty, stop_radius)))

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 3100.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["gas_areas"] = [{"x": 3000.0, "y": 3000.0,
                           "radius": 200.0}]
        ap._act_flee_gas(s, s["player"])
        assert len(goto_calls) == 1
        tx, ty, _ = goto_calls[0]
        # Direction is +X (away from cloud at 3000,3000), magnitude
        # FLEE_GAS_CLUSTER_ESCAPE_PX from the bot's current position.
        assert tx == pytest.approx(3100.0 + ap.FLEE_GAS_CLUSTER_ESCAPE_PX)
        assert ty == pytest.approx(3000.0)

    def test_handler_idles_when_no_longer_in_cloud(
            self, monkeypatch):
        """Defensive: if state shifted between FSM tick and
        handler dispatch (cloud popped, bot moved out), the
        handler must not crash -- just idle and let the next
        tick's choose route us out."""
        idle_calls = [0]
        monkeypatch.setattr(
            ap, "_do_idle", lambda: idle_calls.__setitem__(
                0, idle_calls[0] + 1))
        goto_calls: list = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda *a, **kw: goto_calls.append(a))

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 5000.0, "y": 5000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["gas_areas"] = [{"x": 0.0, "y": 0.0, "radius": 200.0}]
        ap._act_flee_gas(s, s["player"])
        assert idle_calls[0] == 1
        assert goto_calls == []

    def test_handler_drives_through_hysteresis_band(
            self, monkeypatch):
        """When the bot is past the strict cloud edge but still
        within ``FLEE_GAS_EXIT_MARGIN_PX``, the handler must
        keep driving toward the escape target -- not idle.
        Otherwise the bot crosses the boundary, the handler
        releases all keys, and the bot drifts in the hysteresis
        band making no further progress.

        Cloud at (3000, 3000) radius 200; bot at (3250, 3000) is
        50 px past the strict edge but inside the 100 px exit
        margin.  Handler must still call _do_goto, not _do_idle.
        """
        idle_calls = [0]
        monkeypatch.setattr(
            ap, "_do_idle", lambda: idle_calls.__setitem__(
                0, idle_calls[0] + 1))
        goto_calls: list = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0:
                goto_calls.append((tx, ty)))

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 3250.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["gas_areas"] = [{"x": 3000.0, "y": 3000.0,
                           "radius": 200.0}]
        ap._act_flee_gas(s, s["player"])
        assert idle_calls[0] == 0, (
            "handler must not idle while in the hysteresis band")
        assert len(goto_calls) == 1
        # Drive target follows the gas-repulsion vector for
        # FLEE_GAS_CLUSTER_ESCAPE_PX from the current position --
        # not anchored to the cloud edge so the bot keeps moving
        # away even from within the hysteresis band.
        tx, ty = goto_calls[0]
        assert tx == pytest.approx(3250.0 + ap.FLEE_GAS_CLUSTER_ESCAPE_PX)
        assert ty == pytest.approx(3000.0)

    def test_handler_steers_away_from_cluster_not_single_cloud(
            self, monkeypatch):
        """The 2026-05-19 follow-up: with cloud A west of the bot
        AND cloud B north of the bot, the escape vector is the
        SUM of both repulsions -- pointing southeast away from the
        cluster.  Pre-fix the handler escaped along the +X ray
        from cloud A, dropping the bot straight into cloud B.

        Setup: bot at (3000, 3000).  Cloud A at (2800, 3000) r=200
        (bot is INSIDE A -- distance 200).  Cloud B at (3000, 3200)
        r=200 (bot is INSIDE B -- distance 200).  Repulsion from A
        pushes +X, from B pushes -Y, net direction is southeast.
        """
        goto_calls: list = []
        monkeypatch.setattr(
            ap, "_do_goto",
            lambda state, p, tx, ty, stop_radius=80.0:
                goto_calls.append((tx, ty, stop_radius)))

        class _FakeKey:
            @staticmethod
            def hold(name, on): pass

        monkeypatch.setattr(ap, "KeyState", _FakeKey)
        s = _state(
            player={"x": 3000.0, "y": 3000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
        )
        s["gas_areas"] = [
            {"x": 2800.0, "y": 3000.0, "radius": 200.0},
            {"x": 3000.0, "y": 3200.0, "radius": 200.0},
        ]
        ap._act_flee_gas(s, s["player"])
        assert len(goto_calls) == 1
        tx, ty, _ = goto_calls[0]
        # Net direction is southeast: +X (away from A) and -Y
        # (away from B).  Same magnitude from each cloud (bot
        # equidistant from both centres) so the unit vector is
        # (1/sqrt(2), -1/sqrt(2)).
        dx = tx - 3000.0
        dy = ty - 3000.0
        assert dx > 0, f"expected eastward escape, got dx={dx}"
        assert dy < 0, f"expected southward escape, got dy={dy}"
        # Magnitude of escape ray is FLEE_GAS_CLUSTER_ESCAPE_PX
        # (the unit vector was normalised).
        assert math.hypot(dx, dy) == pytest.approx(
            ap.FLEE_GAS_CLUSTER_ESCAPE_PX, rel=0.01)


# ── gas_lingering telemetry (2026-05-19) ─────────────────────────────────




# ── gas_lingering telemetry (2026-05-19) ─────────────────────────────────


class TestObserveGasLingering:
    """Pin the ``gas_lingering`` telemetry event:

      * Fires when bot has been continuously inside a gas cloud
        for ``GAS_LINGER_DETECT_S`` seconds AND lost at least
        ``GAS_LINGER_DAMAGE_PX`` of shields + hp combined.
      * One event per linger episode (no spam during a long stay).
      * Resets cleanly when the bot exits the cloud.
      * Doesn't drive any FSM behaviour -- pure observability.

    Called by ``_do_auto`` once per tick alongside the other
    lifecycle observers.
    """

    def _make_state(self, px=100.0, py=0.0, shields=120,
                    max_shields=120, hp=120, max_hp=120,
                    gas_at=(0.0, 0.0, 200.0)):
        s = _state(player={"x": px, "y": py, "heading": 0.0,
                           "hp": hp, "max_hp": max_hp,
                           "shields": shields,
                           "max_shields": max_shields})
        if gas_at is not None:
            cx, cy, r = gas_at
            s["gas_areas"] = [{"x": cx, "y": cy, "radius": r}]
        return s

    def _capture(self, monkeypatch):
        events: list = []
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        return events

    def test_entry_does_not_fire_event(
            self, _clock, _fresh_bot_state, monkeypatch):
        """First tick inside a cloud just records the entry --
        the dwell threshold hasn't elapsed."""
        events = self._capture(monkeypatch)
        s = self._make_state()
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [e for (e, _) in events if e == "gas_lingering"]
        assert gl == []
        assert ap._state.gas_linger_entered_at == _clock[0]
        assert ap._state.gas_linger_entry_shields == 120

    def test_fires_when_dwell_and_damage_thresholds_met(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot enters cloud at full shields, sits for > 3 s, loses
        > 20 px combined shield/hp -- one event fires."""
        events = self._capture(monkeypatch)
        s = self._make_state(shields=120)
        # Entry tick.
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        # Advance past the dwell threshold; simulate gas damage.
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        s["player"]["shields"] = 60   # -60 from entry
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [(e, kw) for (e, kw) in events if e == "gas_lingering"]
        assert len(gl) == 1
        kw = gl[0][1]
        assert kw["shield_loss"] == 60
        assert kw["hp_loss"] == 0
        assert kw["entry_shields"] == 120
        assert kw["cloud_x"] == 0.0
        assert kw["cloud_y"] == 0.0
        assert kw["cloud_radius"] == 200.0
        assert kw["dwell_s"] >= ap.GAS_LINGER_DETECT_S

    def test_dwell_below_threshold_does_not_fire(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot in cloud < threshold -- no event even with heavy
        damage."""
        events = self._capture(monkeypatch)
        s = self._make_state(shields=120)
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        # Half the threshold -- should not fire even with shield loss.
        _clock[0] += ap.GAS_LINGER_DETECT_S * 0.5
        s["player"]["shields"] = 30
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [e for (e, _) in events if e == "gas_lingering"]
        assert gl == []

    def test_damage_below_threshold_does_not_fire(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot sits in cloud past dwell threshold but takes
        < GAS_LINGER_DAMAGE_PX damage -- gas might be weak or
        bot is being healed.  Not a pathology, no event."""
        events = self._capture(monkeypatch)
        s = self._make_state(shields=120)
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        # Only 5 px loss -- well below the threshold.
        s["player"]["shields"] = 115
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [e for (e, _) in events if e == "gas_lingering"]
        assert gl == []

    def test_no_event_when_outside_any_cloud(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot in clear space -- observer is a no-op."""
        events = self._capture(monkeypatch)
        s = _state(player={"x": 5000.0, "y": 5000.0,
                            "heading": 0.0,
                            "shields": 30, "max_shields": 120,
                            "hp": 30, "max_hp": 120})
        # No gas_areas at all.
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        assert ap._state.gas_linger_entered_at == 0.0
        gl = [e for (e, _) in events if e == "gas_lingering"]
        assert gl == []

    def test_event_fires_only_once_per_linger(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot sits in cloud for 10 s -- one event only, no spam
        on every subsequent tick."""
        events = self._capture(monkeypatch)
        s = self._make_state(shields=120)
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        s["player"]["shields"] = 60
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        # Sit for several more seconds.  Continued shield loss
        # would otherwise re-fire; the per-episode latch must
        # suppress that.
        for _ in range(20):
            _clock[0] += 0.5
            s["player"]["shields"] = max(0, s["player"]["shields"] - 5)
            ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [e for (e, _) in events if e == "gas_lingering"]
        assert len(gl) == 1, "must fire exactly once per linger"

    def test_exit_then_reenter_resets_and_can_fire_again(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Bot exits a cloud + re-enters a different (or same)
        cloud later -- the second episode is independent and can
        fire its own event."""
        events = self._capture(monkeypatch)
        s = self._make_state(shields=120)
        # Episode 1.
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        s["player"]["shields"] = 60
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        # Exit cloud.
        _clock[0] += 1.0
        s["player"]["x"] = 5000.0  # well outside cloud at (0,0) r=200
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        assert ap._state.gas_linger_entered_at == 0.0
        # Episode 2 -- back inside.
        _clock[0] += 1.0
        s["player"]["x"] = 50.0
        s["player"]["shields"] = 120
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        s["player"]["shields"] = 50
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [e for (e, _) in events if e == "gas_lingering"]
        assert len(gl) == 2, (
            "second linger episode must fire its own event after "
            "the bot exited and re-entered the cloud")

    def test_event_carries_fsm_state(
            self, _clock, _fresh_bot_state, monkeypatch):
        """The ``fsm_state`` field is the key diagnostic -- it
        distinguishes "FSM never preempted to FLEE_GAS" from
        "FLEE_GAS active but bot still stuck"."""
        events = self._capture(monkeypatch)
        ap._fsm["state"] = ap.S_ENGAGE
        s = self._make_state(shields=120)
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        s["player"]["shields"] = 50
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [(e, kw) for (e, kw) in events if e == "gas_lingering"]
        assert len(gl) == 1
        assert gl[0][1]["fsm_state"] == ap.S_ENGAGE

    def test_hp_loss_also_counts_toward_damage_threshold(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Most clouds only chip shields, but if HP is taking
        the hit (no shields left) the event should still fire.
        Threshold sums shield_loss + hp_loss."""
        events = self._capture(monkeypatch)
        # Enter with shields at 0 already (gas chews HP directly).
        s = self._make_state(shields=0, hp=120)
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        s["player"]["hp"] = 80   # -40 hp from entry
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [(e, kw) for (e, kw) in events if e == "gas_lingering"]
        assert len(gl) == 1
        assert gl[0][1]["hp_loss"] == 40
        assert gl[0][1]["shield_loss"] == 0

    def test_negative_damage_delta_is_treated_as_zero(
            self, _clock, _fresh_bot_state, monkeypatch):
        """If shields are HIGHER than at entry (consumable healed
        over the gas damage), shield_loss is negative.  Total
        damage clamps at zero so a healing bot doesn't trip the
        event."""
        events = self._capture(monkeypatch)
        s = self._make_state(shields=60)
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        _clock[0] += ap.GAS_LINGER_DETECT_S + 0.1
        # Consumable kicked in -- shields now higher than entry.
        s["player"]["shields"] = 100
        ap._observe_gas_lingering(s, s["player"], _clock[0])
        gl = [e for (e, _) in events if e == "gas_lingering"]
        assert gl == []


# ── Warp-zone swarm engage suppression (2026-05-19) ───────────────────────


