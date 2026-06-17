"""Per-anchor MINE building-pin giveup (2026-06-16 fix).

Regression guard for the building-pin escape loop captured in
``bot_io`` telemetry: the bot wedged in S_MINE against its
home-station cluster at *exactly* (6810.5, 6071.3), firing 31
``stuck_detected`` (cause=building) + 30 ``escape_release_timeout``
(clear_of_buildings=False) over 342 s of a 588 s session.  The escape
produced zero net movement and the hard 10 s cap just reset the same
pin; blacklisting the mining asteroid was useless because the pin was
the BUILDING, not the asteroid.

The fix mirrors the proven HUNT long-anchor giveup: building-cause
stucks in S_MINE accrue per-grid-anchor hits, and once an anchor
reaches ``MINE_STUCK_ANCHOR_MAX_HITS`` the FSM latches S_MINE off for
``MINE_GIVEUP_S`` so it re-routes (IDLE_AT_BASE / SEARCH) and the new
goto pulls the bot out of the pin.
"""
from __future__ import annotations

import bot_autopilot as ap
import bot_autopilot_choose as bac

from _helpers import _state, _hs_building


def _mine_state_pinned_on_building(px, py):
    """A /state where the player sits on top of a building (so
    ``_ship_clear_of_buildings`` is False) with a reachable asteroid
    nearby for the choose-tier test."""
    player = {"x": px, "y": py, "heading": 0.0,
              "shields": 150, "max_shields": 150}
    return _state(
        player=player,
        buildings=[_hs_building(x=px, y=py)],
        asteroids=[{"x": px + 120.0, "y": py, "hp": 50,
                    "type": "Asteroid"}],
    )


class TestConstants:
    def test_constants_exist(self):
        assert ap.MINE_STUCK_ANCHOR_TTL_S == 300.0
        assert ap.MINE_STUCK_ANCHOR_GRID_PX == 200.0
        assert ap.MINE_STUCK_ANCHOR_MAX_HITS == 3
        assert ap.MINE_GIVEUP_S == 30.0


class TestArmGiveup:
    def test_building_pin_stucks_latch_giveup_after_max_hits(
            self, _clock):
        """Three building-cause stucks at the same grid anchor in
        S_MINE latch ``mine_giveup_until`` — even spread over minutes,
        far past any acute window."""
        ap._state.mine_anchor_hits.clear()
        ap._state.mine_giveup_until = 0.0
        ap._fsm["state"] = ap.S_MINE
        px, py = 6810.5, 6071.3
        s = _mine_state_pinned_on_building(px, py)
        p = s["player"]

        for i in range(ap.MINE_STUCK_ANCHOR_MAX_HITS):
            _clock[0] = 1000.0 + i * 60.0   # 60 s apart
            ap._arm_stuck_escape(s, p, _clock[0])

        assert ap._state.mine_giveup_until >= 1000.0 + 120.0 + ap.MINE_GIVEUP_S
        # Anchor entry consumed on latch so it can't double-fire.
        assert ap._state.mine_anchor_hits == {}

    def test_two_building_pin_stucks_do_not_latch(self, _clock):
        """Below the threshold the latch stays clear (the bot still
        gets the asteroid-blacklist + escape burst, just no giveup)."""
        ap._state.mine_anchor_hits.clear()
        ap._state.mine_giveup_until = 0.0
        ap._fsm["state"] = ap.S_MINE
        px, py = 6810.5, 6071.3
        s = _mine_state_pinned_on_building(px, py)
        p = s["player"]

        for i in range(ap.MINE_STUCK_ANCHOR_MAX_HITS - 1):
            _clock[0] = 1000.0 + i * 60.0
            ap._arm_stuck_escape(s, p, _clock[0])

        assert ap._state.mine_giveup_until == 0.0
        anchor = (round(px / ap.MINE_STUCK_ANCHOR_GRID_PX)
                  * ap.MINE_STUCK_ANCHOR_GRID_PX,
                  round(py / ap.MINE_STUCK_ANCHOR_GRID_PX)
                  * ap.MINE_STUCK_ANCHOR_GRID_PX)
        assert ap._state.mine_anchor_hits[anchor][0] == 2

    def test_edge_cause_stuck_does_not_arm_mine_giveup(self, _clock):
        """A stuck with NO building in range (edge / asteroid ram) is
        handled by the asteroid blacklist alone — it must NOT accrue a
        building-pin anchor hit, or the bot would suppress MINE for
        ordinary edge-asteroid rams."""
        ap._state.mine_anchor_hits.clear()
        ap._state.mine_giveup_until = 0.0
        ap._fsm["state"] = ap.S_MINE
        # Player far from any building → clear_of_buildings True.
        s = _state(
            player={"x": 1000.0, "y": 1000.0, "heading": 0.0,
                    "shields": 150, "max_shields": 150},
            asteroids=[{"x": 1010.0, "y": 1000.0, "hp": 50,
                        "type": "Asteroid"}],
        )
        p = s["player"]

        for i in range(ap.MINE_STUCK_ANCHOR_MAX_HITS + 1):
            _clock[0] = 1000.0 + i * 60.0
            ap._arm_stuck_escape(s, p, _clock[0])

        assert ap._state.mine_anchor_hits == {}
        assert ap._state.mine_giveup_until == 0.0

    def test_giveup_state_resets_with_fsm_reset(self):
        ap._state.mine_anchor_hits[(200.0, 200.0)] = [2, 9999.0]
        ap._state.mine_giveup_until = 9999.0
        ap._fsm_reset()
        assert ap._state.mine_anchor_hits == {}
        assert ap._state.mine_giveup_until == 0.0


class TestChooseSuppression:
    def test_mine_tier_returns_none_while_latched(self, _clock):
        """While the giveup holds, the MINE tier suppresses S_MINE so
        the FSM falls through to a later tier (IDLE_AT_BASE / SEARCH)."""
        ap._state.mine_giveup_until = _clock[0] + 10.0
        ap._state.chase_committed = True
        s = _mine_state_pinned_on_building(6810.5, 6071.3)
        p = s["player"]
        result = bac._tier_mine_or_search(s, p, ap.S_MINE, _clock[0])
        assert result is None
        # Commitment cleared so the post-latch attempt starts fresh.
        assert ap._state.chase_committed is False

    def test_mine_tier_resumes_after_latch_expires(self, _clock):
        """Once the latch expires the MINE tier commits to the
        reachable asteroid again."""
        ap._state.mine_giveup_until = _clock[0] - 1.0   # already expired
        ap._state.chase_committed = False
        s = _mine_state_pinned_on_building(6810.5, 6071.3)
        p = s["player"]
        result = bac._tier_mine_or_search(s, p, ap.S_IDLE_AT_BASE, _clock[0])
        assert result == ap.S_MINE
