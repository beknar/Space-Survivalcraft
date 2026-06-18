"""ENGAGE suppression for the unhealed-zero-shields ZONE2 death spiral
(2026-06-18 fix).

Regression guard for the engage<->idle_at_base oscillation captured in
``bot_io`` telemetry: at sh=0/100 with no shield_recharge (ship + slot
both 0) in a 59-alien ZONE2 swarm ~1500 px from the Home Station, the
bot flip-flopped ENGAGE <-> IDLE_AT_BASE nine times in ~18 s.  Each
ENGAGE preempted the section-2.6 flee tether, so the bot gained no
ground on the flee and never recovered shields.  RETREAT stayed silent
because its density gate misses a strung-out swarm.

The fix suppresses ENGAGE in exactly that pure-loss state (ZONE2 +
sub-critical shields + no ready shield_recharge + a real multi-alien
swarm) so the flee tether / RETREAT carry the bot back under the HS
umbrella instead of kiting one alien at zero shields.
"""
from __future__ import annotations

import bot_autopilot as ap
import bot_autopilot_choose as bac

from _helpers import _state, _hs_building


def _zone2_swarm_state(*, shields, max_shields=100, heal_slot=False,
                       n_band_aliens=3, px=6400.0, py=6400.0):
    """ZONE2 state: player at (px,py) with a Home Station far away, a
    multi-alien swarm inside the engage band, optional shield_recharge."""
    s = _state(
        player={"x": px, "y": py, "heading": 0.0,
                "hp": 100, "max_hp": 100,
                "shields": shields, "max_shields": max_shields},
        aliens=[{"x": px + 850 + 10 * i, "y": py, "hp": 50}
                for i in range(n_band_aliens)],
        buildings=[_hs_building(x=5000.0, y=5000.0)],
        world_w=8000, world_h=8000,
    )
    s["zone"]["id"] = "ZoneID.ZONE2"
    s["zone"]["zone_id"] = "ZoneID.ZONE2"
    s["quick_use_slots"] = (
        [{"item_type": "shield_recharge", "count": 5}] if heal_slot else [])
    return s


class TestSuppressionPredicate:
    def test_fires_at_critical_unhealed_zone2_swarm(self):
        s = _zone2_swarm_state(shields=0)
        assert bac._engage_suppressed_critical_unhealed(
            s, "ZoneID.ZONE2") is True

    def test_silent_when_shields_healthy(self):
        s = _zone2_swarm_state(shields=80)
        assert bac._engage_suppressed_critical_unhealed(
            s, "ZoneID.ZONE2") is False

    def test_silent_when_shield_recharge_ready(self):
        s = _zone2_swarm_state(shields=0, heal_slot=True)
        assert bac._engage_suppressed_critical_unhealed(
            s, "ZoneID.ZONE2") is False

    def test_silent_outside_zone2(self):
        s = _zone2_swarm_state(shields=0)
        # Same dire state but in MAIN — the HS umbrella makes defending
        # the right call, so suppression must not fire.
        assert bac._engage_suppressed_critical_unhealed(
            s, "ZoneID.MAIN") is False

    def test_silent_for_lone_alien(self):
        """A single alien at zero shields is killable — let the bot
        ENGAGE and end the threat rather than flee."""
        s = _zone2_swarm_state(shields=0, n_band_aliens=1)
        assert bac._engage_suppressed_critical_unhealed(
            s, "ZoneID.ZONE2") is False

    def test_silent_when_swarm_outside_engage_band(self):
        """Aliens exist but all sit beyond the engage-exit band — not a
        close swarm, so no suppression (nothing is grinding the bot)."""
        s = _zone2_swarm_state(shields=0)
        for a in s["aliens"]:
            a["x"] = 6400.0 + 1500.0   # > ENGAGE_EXIT_PX (1000)
        assert bac._engage_suppressed_critical_unhealed(
            s, "ZoneID.ZONE2") is False


class TestEngageDecisionGate:
    def test_engage_declined_in_deadlock(self, _clock):
        """With a threat squarely in the engage band, the critical-
        unhealed gate makes _engage_decision return None (decline)."""
        s = _zone2_swarm_state(shields=0)
        threat = s["aliens"][0]
        td = 850.0   # inside the 800-1000 band, would normally engage
        out = bac._engage_decision(
            s, ap.S_ENGAGE, threat, td, _hs_building(5000.0, 5000.0),
            "ZoneID.ZONE2")
        assert out is None

    def test_engage_allowed_when_healed(self, _clock):
        """Control: same swarm + threat but a shield_recharge is ready
        — ENGAGE fires as normal (no regression to defensive play)."""
        s = _zone2_swarm_state(shields=0, heal_slot=True)
        threat = s["aliens"][0]
        td = 850.0
        out = bac._engage_decision(
            s, ap.S_ENGAGE, threat, td, _hs_building(5000.0, 5000.0),
            "ZoneID.ZONE2")
        assert out == ap.S_ENGAGE


class TestEndToEndNoOscillation:
    def test_bot_commits_to_flee_not_engage(self, _clock):
        """The captured pathology: drive _do_auto for several ticks in
        the deadlock state and confirm the bot never oscillates into
        ENGAGE — it commits to the flee (IDLE_AT_BASE / RETREAT)."""
        s = _zone2_swarm_state(shields=0)
        ap._fsm["state"] = ap.S_ENGAGE   # start mid-fight
        seen = []
        for _ in range(6):
            ap._do_auto(s, s["player"])
            seen.append(ap._fsm["state"])
        assert ap.S_ENGAGE not in seen, (
            f"bot must not re-engage at 0 shields unhealed; saw {seen}")
        # And it should be fleeing toward base, not idling in combat.
        assert all(st in (ap.S_IDLE_AT_BASE, ap.S_RETREAT, ap.S_REGEN)
                   for st in seen), seen
