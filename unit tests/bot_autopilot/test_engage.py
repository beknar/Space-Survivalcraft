"""ENGAGE + boss-combat FSM transition tests.

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


# ── Non-MAIN recovery-loadout gate (2026-05-26) ───────────────────────────


class TestRecoverLootLoadoutGate:
    """When the bot dies in ZONE2 / a warp zone / star-maze and
    respawns, ``S_RECOVER_LOOT`` should defer until the bot has
    healed + re-equipped consumables.  Captured pathology
    (2026-05-25 20:43 telemetry): bot died at t+2962s in Nebula
    with full kit, drove toward the death pile naked + with cold
    weapons, died again 53 s later in ``fsm=recover_loot``.

    MAIN-zone deaths are exempt -- the HS umbrella + turret ring
    make recovery safe even with a stripped ship.
    """

    @staticmethod
    def _ready_player(*, hp=200, max_hp=200,
                       shields=150, max_shields=150):
        return {"x": 4000.0, "y": 4000.0, "heading": 0.0,
                "hp": hp, "max_hp": max_hp,
                "shields": shields, "max_shields": max_shields,
                "is_dead": False}

    def _zone2_state(self, *, player=None, with_consumables=True):
        s = _state(player=player or self._ready_player())
        s["zone"]["id"] = "ZoneID.ZONE2"
        s["iron_pickups"] = [
            {"x": 4500.0, "y": 4500.0, "amount": 10,
             "item_type": "iron"}]
        slots = []
        if with_consumables:
            slots = [
                {"item_type": "repair_pack", "count": 5},
                {"item_type": "shield_recharge", "count": 5},
            ]
        s["quick_use_slots"] = slots
        return s

    def _arm_recovery(self, _clock):
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (4500.0, 4500.0)
        ap._state.death_recovery_started_at = _clock[0]

    def test_recovery_fires_in_nebula_when_loadout_ready(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_recover_loot",
                            lambda s, p: None)
        self._arm_recovery(_clock)
        s = self._zone2_state()
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_RECOVER_LOOT

    def test_recovery_blocked_in_nebula_without_consumables(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_recover_loot",
                            lambda s, p: None)
        self._arm_recovery(_clock)
        s = self._zone2_state(with_consumables=False)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_RECOVER_LOOT

    def test_recovery_blocked_in_nebula_with_low_hp(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_recover_loot",
                            lambda s, p: None)
        self._arm_recovery(_clock)
        s = self._zone2_state(
            player=self._ready_player(hp=50, max_hp=200))
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_RECOVER_LOOT

    def test_recovery_blocked_in_nebula_with_low_shields(
            self, _clock, _fresh_bot_state, monkeypatch):
        monkeypatch.setattr(ap, "_act_recover_loot",
                            lambda s, p: None)
        self._arm_recovery(_clock)
        s = self._zone2_state(
            player=self._ready_player(shields=20, max_shields=150))
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_RECOVER_LOOT

    def test_recovery_fires_in_main_even_with_naked_loadout(
            self, _clock, _fresh_bot_state, monkeypatch):
        """MAIN exempt -- HS umbrella makes recovery safe."""
        monkeypatch.setattr(ap, "_act_recover_loot",
                            lambda s, p: None)
        self._arm_recovery(_clock)
        s = self._zone2_state(with_consumables=False)
        s["zone"]["id"] = "ZoneID.MAIN"
        # Low HP too -- gate must NOT fire in MAIN.
        s["player"]["hp"] = 50
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_RECOVER_LOOT

    def test_recovery_blocked_in_warp_zone_without_loadout(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Warp zones also count as danger zones."""
        monkeypatch.setattr(ap, "_act_recover_loot",
                            lambda s, p: None)
        self._arm_recovery(_clock)
        s = self._zone2_state(with_consumables=False)
        s["zone"]["id"] = "ZoneID.WARP_ENEMY"
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_RECOVER_LOOT


class TestCrossZoneRecoveryAbandon:
    """2026-05-28: when the bot dies in one zone (e.g. Nebula)
    and respawns in another (e.g. MAIN), the recorded
    ``death_recovery_pos`` is meaningless in the current zone --
    different world.  ``_maybe_clear_death_recovery`` short-
    circuits the latch immediately instead of burning the 60 s
    timeout pretending to look for it.

    Captured 2026-05-28 telemetry: bot died in ZONE2 at +1108s,
    respawned in MAIN, recovery timed out at +1170s after 60 s
    of pointless navigation toward the Nebula coordinates.
    """

    def _make_state(self, *, current_zone="ZoneID.MAIN"):
        s = _state(player={"x": 3500.0, "y": 3500.0,
                           "heading": 0.0,
                           "shields": 150, "max_shields": 150})
        s["zone"]["id"] = current_zone
        s["iron_pickups"] = [
            {"x": 2000.0, "y": 3000.0, "amount": 10}]
        return s

    def _arm(self, _clock, *, death_zone="ZoneID.ZONE2"):
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        ap._state.death_recovery_zone = death_zone

    def test_abandons_when_current_zone_differs(
            self, _clock, _fresh_bot_state, monkeypatch):
        events: list = []
        monkeypatch.setattr(
            ap, "_telemetry_log",
            lambda evt, **kw: events.append((evt, kw)))
        self._arm(_clock, death_zone="ZoneID.ZONE2")
        s = self._make_state(current_zone="ZoneID.MAIN")
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is False
        abandon = [(e, kw) for (e, kw) in events
                   if e == "death_recovery_cross_zone_abandon"]
        assert len(abandon) == 1
        kw = abandon[0][1]
        assert kw["death_zone"] == "ZoneID.ZONE2"
        assert kw["current_zone"] == "ZoneID.MAIN"

    def test_does_not_abandon_when_zones_match(
            self, _clock, _fresh_bot_state):
        """Bot died in ZONE2, respawned in ZONE2 -- recovery runs
        normally (uses the bumped 180 s timeout)."""
        self._arm(_clock, death_zone="ZoneID.ZONE2")
        s = self._make_state(current_zone="ZoneID.ZONE2")
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is True

    def test_does_not_abandon_when_death_zone_unset(
            self, _clock, _fresh_bot_state):
        """Legacy save with empty ``death_recovery_zone`` -- the
        guard skips, and the pre-2026-05-28 timeout-only behaviour
        applies.  Preserves backward compat."""
        self._arm(_clock, death_zone="")
        s = self._make_state(current_zone="ZoneID.MAIN")
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is True

    def test_does_not_abandon_when_current_zone_unset(
            self, _clock, _fresh_bot_state):
        """If the current snapshot lacks zone info, don't fire the
        guard -- safer to fall through to the existing timeout."""
        self._arm(_clock, death_zone="ZoneID.ZONE2")
        s = self._make_state(current_zone="ZoneID.ZONE2")
        s["zone"]["id"] = ""
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is True


class TestDeathObserverCapturesZone:
    """Sanity: the alive -> dead edge writes the current zone_id
    into ``death_recovery_zone`` so the cross-zone abandon guard
    has the data it needs."""

    @staticmethod
    def _alive(**override):
        d = {"x": 1000.0, "y": 1000.0, "heading": 0.0,
             "shields": 150, "max_shields": 150,
             "hp": 200, "max_hp": 200, "is_dead": False}
        d.update(override)
        return d

    def test_captures_zone_id_on_death(
            self, _clock, _fresh_bot_state):
        ap._state.was_dead = False
        ap._state.last_alive_pos = (4000.0, 4000.0)
        s = _state(player=self._alive(is_dead=True))
        s["zone"]["id"] = "ZoneID.ZONE2"
        ap._observe_death_edges(s, s["player"], _clock[0])
        assert ap._state.death_recovery_zone == "ZoneID.ZONE2"


class TestRecoveryTimeoutBumpedInDangerZone:
    """The bumped DEATH_RECOVERY_TIMEOUT_NEBULA_S applies to
    ``_maybe_clear_death_recovery`` when the bot is in a non-MAIN
    zone -- giving the heal + re-equip cycle realistic headroom."""

    def test_main_zone_uses_60s_timeout(
            self, _clock, _fresh_bot_state):
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(player={"x": 3500.0, "y": 3500.0,
                           "heading": 0.0,
                           "shields": 150, "max_shields": 150})
        s["zone"]["id"] = "ZoneID.MAIN"
        s["iron_pickups"] = [
            {"x": 2000.0, "y": 3000.0, "amount": 10}]
        _clock[0] += ap.DEATH_RECOVERY_TIMEOUT_S + 1.0
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is False

    def test_nebula_zone_uses_extended_timeout(
            self, _clock, _fresh_bot_state):
        """In ZONE2 the timeout extends to NEBULA_S -- the
        60 s mark does NOT clear the latch."""
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(player={"x": 3500.0, "y": 3500.0,
                           "heading": 0.0,
                           "shields": 150, "max_shields": 150})
        s["zone"]["id"] = "ZoneID.ZONE2"
        s["iron_pickups"] = [
            {"x": 2000.0, "y": 3000.0, "amount": 10}]
        _clock[0] += ap.DEATH_RECOVERY_TIMEOUT_S + 1.0
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is True

    def test_nebula_zone_timeout_fires_at_extended_window(
            self, _clock, _fresh_bot_state):
        ap._state.death_recovery_pending = True
        ap._state.death_recovery_pos = (2000.0, 3000.0)
        ap._state.death_recovery_started_at = _clock[0]
        s = _state(player={"x": 3500.0, "y": 3500.0,
                           "heading": 0.0,
                           "shields": 150, "max_shields": 150})
        s["zone"]["id"] = "ZoneID.ZONE2"
        s["iron_pickups"] = [
            {"x": 2000.0, "y": 3000.0, "amount": 10}]
        _clock[0] += ap.DEATH_RECOVERY_TIMEOUT_NEBULA_S + 1.0
        ap._maybe_clear_death_recovery(s, s["player"], _clock[0])
        assert ap._state.death_recovery_pending is False


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


# ── FLEE_GAS (2026-05-18) ────────────────────────────────────────────────




# ── Warp-zone swarm engage suppression (2026-05-19) ───────────────────────


class TestWarpSwarmEngageSuppression:
    """Pin the suppression that keeps the bot in WARP_TRAVERSE when
    it's in a warp zone with too many aliens to safely engage.

    Captured pathology (2026-05-19 telemetry): 4 ENGAGE deaths in
    WARP_ENEMY in a single session.  Pattern was identical each time:
    WARP_TRAVERSE at full shields -> an alien crosses into the 800 px
    engage band -> FSM preempts to ENGAGE -> bot kites that alien
    while ~20 others swarm -> shields 120 -> 0 in 5-7 s -> death.
    With this suppression, ENGAGE stops preempting; WARP_TRAVERSE
    keeps the bot driving toward the far edge while combat assist
    (per-frame auto-aim) handles defense.
    """

    def _warp_state(self, alien_count=20, in_warp_zone=True,
                    cur_state=None, **player_kw):
        zone_id = "ZoneID.WARP_ENEMY" if in_warp_zone else "ZoneID.MAIN"
        aliens = [{"x": 100.0 + i * 50.0, "y": 0.0, "hp": 50}
                  for i in range(alien_count)]
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 120, "max_shields": 120,
                    **player_kw},
            aliens=aliens,
        )
        s["zone"] = {"world_w": 6400, "world_h": 8000,
                     "zone_id": zone_id, "id": zone_id}
        if cur_state is not None:
            ap._fsm["state"] = cur_state
        return s

    def test_swarm_in_warp_zone_suppresses_engage(self, _clock):
        """20 aliens in WARP_ENEMY, bot in WARP_TRAVERSE -- ENGAGE
        must NOT fire even though aliens are inside the 800 px
        band."""
        s = self._warp_state(alien_count=20,
                             cur_state=ap.S_WARP_TRAVERSE)
        # Need the boss-was-killed latch + warp_after_boss_done to
        # let WARP_TRAVERSE be the legitimate fall-through state.
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE, (
            "ENGAGE must be suppressed for swarms in warp zones")

    def test_threshold_boundary_just_below_suppresses_nothing(
            self, _clock):
        """Alien count exactly one below the threshold -- ENGAGE
        fires normally."""
        s = self._warp_state(
            alien_count=ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS - 1)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_threshold_boundary_at_threshold_suppresses(
            self, _clock):
        """At the exact threshold, ENGAGE is suppressed."""
        s = self._warp_state(
            alien_count=ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS,
            cur_state=ap.S_WARP_TRAVERSE)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE

    def test_main_zone_with_many_aliens_still_engages(self, _clock):
        """Outside of warp zones the suppression doesn't fire --
        MAIN zone gets the normal ENGAGE behaviour even with many
        aliens around (the bot's home base is here; abandoning
        ENGAGE would let aliens chew on the station)."""
        s = self._warp_state(alien_count=20, in_warp_zone=False)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_warp_zone_with_few_aliens_still_engages(self, _clock):
        """WARP_METEOR / WARP_GAS / WARP_LIGHTNING don't spawn
        aliens but a stray one could drift in.  With aliens
        count < threshold, ENGAGE still fires -- the bot can
        safely kite a single threat without getting swarmed."""
        s = self._warp_state(alien_count=3)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_suppression_lets_warp_traverse_continue(self, _clock):
        """The whole point: with ENGAGE suppressed in a swarm, the
        FSM should fall through to WARP_TRAVERSE (assuming the
        post-boss warp gates are set) so the bot keeps moving
        toward the far edge instead of standing and dying."""
        s = self._warp_state(
            alien_count=20, cur_state=ap.S_WARP_TRAVERSE)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_WARP_TRAVERSE

    def test_in_regen_with_swarm_no_alt_holds_regen(
            self, _clock):
        """Updated 2026-05-24: with REGEN suppression also
        conditioned on a productive alternative (symmetric mirror
        of PR #169's ENGAGE treatment), an in-REGEN bot with
        close threats but no alt now HOLDS REGEN on tick 1.

        The existing REGEN hold-branch escape valve (PR #141:
        threatened + shields_stalled, or fast-drop shortcut)
        still fires after the stall window, so this isn't a
        regression for the original sustained-damage case --
        it just removes the one-tick forced exit that the
        prior unconditional REGEN-suppress imposed.

        Bot defends via combat assist (per-frame auto-aim +
        fire) while in REGEN; the FSM-level transition to ENGAGE
        happens once the stall timer fires."""
        s = self._warp_state(
            alien_count=20,
            cur_state=ap.S_REGEN,
            shields=50,
        )
        ap._fsm["entered_at"] = _clock[0]
        ap._state.last_regen_shields = 50
        ap._state.last_regen_progress_at = _clock[0]
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_REGEN, (
            "REGEN holds on tick 1 -- no productive alt, no "
            "stall yet.  PR #141's escape valve still fires on "
            "later ticks if the threat is sustained")


# ── Warp-zone swarm REGEN suppression (2026-05-23) ────────────────────────




# ── ENGAGE outside-base swarm suppression (2026-05-23 v3) ─────────────────


class TestOutsideBaseSwarmEngageSuppression:
    """The 2026-05-23 v3 broadening: ENGAGE suppression now also
    fires in ZONE2 (Nebula), STAR_MAZE, and any non-MAIN zone with
    8+ aliens visible.  Captured pathology: bot warped post-boss
    to ZONE2 with 48 aliens, no Nebula HS yet, got pinned in a
    870x800 px kite box for 500+ s with one state transition
    (MINE -> ENGAGE on first tick).  Burned 23 repair packs to
    stay alive at ~35 HP.

    Mirror of ``TestOutsideBaseSwarmRegenSuppression`` (PR #165)
    for ENGAGE: same "MAIN is the only safe-to-engage zone"
    semantic.  Falling through to BUILD_NEBULA / MINE / etc. lets
    the bot make progress instead of dying in place.
    """

    def _state_in_zone(self, zone_name, alien_count=20,
                       cur_state=None, iron=0,
                       **player_overrides):
        zone_id = f"ZoneID.{zone_name}"
        # Aliens placed within ENGAGE_ENTER_PX (800) of player so
        # the ENGAGE branch would otherwise fire.
        aliens = [{"x": 200.0 + i * 30.0, "y": 0.0, "hp": 50}
                  for i in range(alien_count)]
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 120, "max_shields": 120,
                    **player_overrides},
            aliens=aliens,
            iron=iron,
        )
        s["zone"] = {"world_w": 6400, "world_h": 8000,
                     "zone_id": zone_id, "id": zone_id}
        if cur_state is not None:
            ap._fsm["state"] = cur_state
        return s

    def test_zone2_nebula_swarm_suppresses_engage_with_build_alt(
            self, _clock):
        """ZONE2 with 20 aliens + iron + no Nebula HS -- the
        productive alternative S_BUILD_NEBULA is viable, so the
        ENGAGE-swarm-suppress fires and ENGAGE is blocked.
        Captured pathology: bot warped post-boss to Nebula with
        48 aliens, no Nebula HS yet -- needed to BUILD, not kite.

        Updated 2026-05-23 v4: requires the BUILD_NEBULA
        productive alternative to be set up (iron + not built)."""
        s = self._state_in_zone("ZONE2", alien_count=20,
                                 iron=ap.BUILD_IRON_THRESHOLD)
        ap._state.nebula_build_done = False
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE

    def test_zone2_swarm_without_build_alt_engages(self, _clock):
        """The 2026-05-23 v4 fix path: bot in ZONE2 with swarm BUT
        Nebula HS already exists (no build alternative).  Without
        a productive alternative the bot must DEFEND, not gather
        defenseless.  Captured pathology: 0 ENGAGE events in 500 s
        while shields dropped to 1/120 -- bot mining while being
        rammed because PR #168's unconditional suppress blocked
        ENGAGE entirely."""
        s = self._state_in_zone("ZONE2", alien_count=20)
        # Nebula HS already exists -- no build alternative.
        ap._state.nebula_build_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "ENGAGE must fire when no productive alternative is "
            "available -- otherwise bot defends itself with combat "
            "assist only while moving toward an asteroid")

    def test_star_maze_swarm_engages_no_productive_alt(
            self, _clock):
        """STAR_MAZE has no warp-traverse goal AND no build_nebula
        path.  Per the conditional gate, ENGAGE fires so the bot
        defends.  Updated from PR #168 (which unconditionally
        suppressed)."""
        s = self._state_in_zone("STAR_MAZE", alien_count=20)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_nebula_warp_zone_swarm_suppresses_engage_with_traverse(
            self, _clock):
        """NEBULA_WARP_ENEMY with the warp-traverse arc active --
        the productive alternative is viable, so ENGAGE is
        suppressed and the traverse continues."""
        s = self._state_in_zone("NEBULA_WARP_ENEMY",
                                alien_count=20)
        ap._state.boss_was_killed = True
        ap._state.warp_after_boss_done = True
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] != ap.S_ENGAGE

    def test_main_zone_swarm_still_engages(self, _clock):
        """MAIN with 20 aliens -- HS umbrella + station shield +
        fortify turrets make ENGAGE safe here.  Gate must NOT
        fire."""
        s = self._state_in_zone("MAIN", alien_count=20)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE, (
            "ENGAGE must still fire in MAIN (the layered defense "
            "of HS umbrella / station shield / turrets makes the "
            "kite safe)")

    def test_zone2_sparse_aliens_still_engages(self, _clock):
        """Sparse Nebula encounter -- < threshold aliens -- ENGAGE
        fires normally.  The bot can safely kite a small group."""
        s = self._state_in_zone(
            "ZONE2",
            alien_count=ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS - 1)
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_ENGAGE

    def test_zone2_swarm_with_iron_falls_to_build_nebula(
            self, _clock):
        """The captured-pathology fix: bot in Nebula with iron +
        clear area + 20 aliens.  ENGAGE suppressed, cascade falls
        to S_BUILD_NEBULA -- bot builds the Nebula base instead
        of dying in the kite trap."""
        # Aliens far enough (5000+) to not block ``_build_area_clear``
        # but close enough (under 800 px) that ENGAGE would
        # otherwise trigger.  Use the close set for ENGAGE-trigger.
        s = self._state_in_zone(
            "ZONE2", alien_count=20)
        # Override to give the bot iron for build.
        s["inventory"] = {"items": {"iron": ap.BUILD_IRON_THRESHOLD}}
        # Move aliens out of the BUILD_CLEAR_RADIUS (400 px) but
        # still within engage range.  Spread across the +X axis
        # starting at 500 px so the closest is in ENGAGE_ENTER_PX
        # but outside BUILD_CLEAR_RADIUS.
        s["aliens"] = [{"x": 500.0 + i * 50.0, "y": 0.0,
                        "hp": 50} for i in range(20)]
        ap._state.nebula_build_done = False
        ap._state.build_done = True   # MAIN already built
        ap._do_auto(s, s["player"])
        assert ap._fsm["state"] == ap.S_BUILD_NEBULA, (
            f"expected S_BUILD_NEBULA, got {ap._fsm['state']}")


# ── Swarm-suppress productive-alt helper ──────────────────────────────────


