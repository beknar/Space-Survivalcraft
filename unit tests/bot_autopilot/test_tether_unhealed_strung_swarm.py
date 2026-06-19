"""Unhealed ZONE2 tether widens its swarm gate for a strung-out swarm
(2026-06-18 prevention fix).

Regression guard for a 9-death ZONE2 session in ``bot_io``: all deaths
were ``idle_at_base->regen`` at 39-54% shields, ~3400-5200 px from the
Home Station, in a 60-alien swarm with no shield_recharge.  The bot got
that far because the ``_zone2_far_swarm_tether`` dense-swarm gate used
the tight ``RETREAT_SWARM_RANGE_PX`` (1200), which a strung-out swarm
slips through (~4-5 within 1200 px, ~10 within 1800 px).  So a
full-shield unhealed bot roamed deep; only once shields dipped below the
0.7 leash did the tether fire -- too late, dying on the long trip home.

The fix uses the wider ``RETREAT_SWARM_RANGE_EXIT_PX`` (1800) for the
swarm gate WHEN UNHEALED, leashing the bot home early.  Healed bots keep
the tight gate, and a low-alien zone still falls below the count
threshold at 1800 px (the 2026-06-10 starvation case is unaffected).
"""
from __future__ import annotations

import bot_autopilot as ap
import bot_autopilot_choose as choose

from _helpers import _state, _hs_building


def _swarm_state(*, shields, max_shields=100, healed=False,
                 n=6, alien_dist=1500.0, hs_dist=2000.0):
    """ZONE2 state: bot at origin, HS at hs_dist, n aliens ringed at
    alien_dist, optional shield_recharge in a quick-use slot."""
    s = _state(
        player={"x": 0.0, "y": 0.0, "heading": 0.0,
                "shields": shields, "max_shields": max_shields},
        aliens=[{"x": float(alien_dist), "y": 0.0, "hp": 50}
                for _ in range(n)],
        buildings=[_hs_building(x=hs_dist, y=0.0)],
    )
    s["zone"]["id"] = "ZoneID.ZONE2"
    if healed:
        s["quick_use_slots"] = [{"item_type": "shield_recharge", "count": 5}]
    return s


class TestUnhealedWideSwarmGate:
    def test_full_shield_unhealed_strung_swarm_tethers(
            self, _clock, _fresh_bot_state):
        """The captured pathology: full-shield UNHEALED bot beyond the
        1500 px leash with a strung-out swarm (aliens at 1500 px -- past
        the tight 1200 gate, inside the wide 1800 gate) now heads home
        instead of roaming deeper."""
        s = _swarm_state(shields=100, healed=False,
                         n=ap.RETREAT_SWARM_ALIEN_COUNT, alien_dist=1500.0)
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(s, s["player"], hs) is True

    def test_full_shield_unhealed_strung_swarm_idles_full_cascade(
            self, _clock, _fresh_bot_state):
        """End-to-end: the choose cascade returns S_IDLE_AT_BASE so the
        bot drives back to the HS ring before it strands itself."""
        s = _swarm_state(shields=100, healed=False,
                         n=ap.RETREAT_SWARM_ALIEN_COUNT, alien_dist=1500.0)
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) == ap.S_IDLE_AT_BASE

    def test_healed_keeps_tight_gate(self, _clock, _fresh_bot_state):
        """Control: a HEALED bot keeps the tight 1200 px gate -- the same
        strung-out swarm at 1500 px does not tether it (operates out to
        the generous radius as before).  HS placed beyond the healed
        tether distance so the swarm gate is actually reached."""
        s = _swarm_state(shields=100, healed=True,
                         n=ap.RETREAT_SWARM_ALIEN_COUNT,
                         alien_dist=1500.0, hs_dist=3000.0)
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(s, s["player"], hs) is False

    def test_low_alien_zone_unhealed_does_not_tether(
            self, _clock, _fresh_bot_state):
        """Starvation guard (2026-06-10): a sparse zone -- only 2 aliens,
        below the count threshold even at the wide 1800 px range -- must
        NOT tether a full-shield unhealed bot, so it can still roam to
        mine the iron it needs for heals."""
        s = _swarm_state(shields=100, healed=False, n=2, alien_dist=1500.0)
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(s, s["player"], hs) is False

    def test_unhealed_hurt_still_tethers_on_distance_leash(
            self, _clock, _fresh_bot_state):
        """Unchanged: below the 0.7 shield leash the unhealed bot tethers
        on distance alone, regardless of swarm geometry."""
        s = _swarm_state(shields=40, healed=False, n=0, alien_dist=1500.0)
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(s, s["player"], hs) is True

    def test_unhealed_aliens_beyond_wide_gate_does_not_tether(
            self, _clock, _fresh_bot_state):
        """A swarm sitting entirely beyond the wide 1800 px range is not
        adjacent -- a full-shield unhealed bot still roams (the gate
        widened, it did not become unconditional)."""
        s = _swarm_state(shields=100, healed=False,
                         n=ap.RETREAT_SWARM_ALIEN_COUNT, alien_dist=2000.0)
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(s, s["player"], hs) is False


class TestStickyCommitNoPingPong:
    """2026-06-19: the wider swarm gate is a hard threshold with no
    hysteresis, so a full-shield unhealed bot far out (hs_dist ~4400,
    60 aliens) flipped idle_at_base<->mine 76 times in 209 s as the local
    swarm count jittered across RETREAT_SWARM_ALIEN_COUNT.  Once the bot
    has turned for home (cur == S_IDLE_AT_BASE) it must STAY committed
    until back inside the leash, not bounce back out to mine."""

    def test_sticky_holds_when_swarm_count_dips(
            self, _clock, _fresh_bot_state):
        """Already heading home, unhealed, far -- a momentary sub-threshold
        swarm count must NOT release the tether (the ping-pong tick)."""
        # Only 3 aliens in range -- below RETREAT_SWARM_ALIEN_COUNT, so the
        # raw swarm gate would read False.
        s = _swarm_state(shields=100, healed=False, n=3,
                         alien_dist=1500.0, hs_dist=4400.0)
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(
            s, s["player"], hs, ap.S_IDLE_AT_BASE) is True

    def test_not_sticky_from_mine_with_weak_swarm(
            self, _clock, _fresh_bot_state):
        """Control: the stickiness is entry-direction aware -- from MINE
        (not yet committed) a sub-threshold swarm does NOT tether, so the
        bot still mines when it isn't genuinely swarmed (no over-tether)."""
        s = _swarm_state(shields=100, healed=False, n=3,
                         alien_dist=1500.0, hs_dist=4400.0)
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(
            s, s["player"], hs, ap.S_MINE) is False

    def test_sticky_releases_once_back_inside_leash(
            self, _clock, _fresh_bot_state):
        """No trap: once the bot is back within the unhealed leash the
        sticky branch is past the hs_dist early-return, so the tether
        releases and the bot can mine near home."""
        s = _swarm_state(shields=100, healed=False, n=8,
                         alien_dist=1000.0, hs_dist=1000.0)  # inside 1500
        hs = ap._find_home_station(s)
        assert choose._zone2_far_swarm_tether(
            s, s["player"], hs, ap.S_IDLE_AT_BASE) is False

    def test_full_cascade_stays_home_not_mine(
            self, _clock, _fresh_bot_state):
        """End-to-end: an unhealed bot already at IDLE_AT_BASE, far out
        with a borderline swarm, keeps returning IDLE_AT_BASE across ticks
        instead of flipping to MINE."""
        s = _swarm_state(shields=100, healed=False, n=3,
                         alien_dist=1500.0, hs_dist=4400.0)
        s["asteroids"] = [{"x": 200.0, "y": 0.0, "hp": 100}]
        for _ in range(4):
            out = ap._choose_next_state(s, s["player"], ap.S_IDLE_AT_BASE)
            assert out == ap.S_IDLE_AT_BASE
