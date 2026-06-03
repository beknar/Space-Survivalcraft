"""S_RETREAT — under-equipped Nebula-swarm defensive flee.

Added 2026-05-30.  Covers the choose-state gate (``_retreat_active``)
and the ``_act_retreat`` action handler.  See the S_RETREAT block in
``bot_autopilot_tuning.py`` for the captured pathology (three ZONE2
death-spiral deaths) this state addresses.
"""
from __future__ import annotations

import bot_autopilot as ap

from _helpers import _state, _hs_building


def _zone2_swarm_state(*, shields, max_shields=120,
                       alien_count=6, alien_x0=100.0,
                       quick_use=None, buildings=()):
    """ZONE2 state with ``alien_count`` aliens clustered near the
    origin (all within RETREAT_SWARM_RANGE_PX of the bot at 0,0)."""
    aliens = [{"x": alien_x0 + 80.0 * i, "y": 0.0, "hp": 50}
              for i in range(alien_count)]
    s = _state(
        player={"x": 0.0, "y": 0.0, "heading": 0.0,
                "hp": 100, "max_hp": 100,
                "shields": shields, "max_shields": max_shields},
        aliens=aliens,
        buildings=buildings,
    )
    s["zone"]["id"] = "ZoneID.ZONE2"
    if quick_use is not None:
        s["quick_use_slots"] = quick_use
    return s


class TestRetreatGate:
    def test_fires_in_zone2_swarm_without_consumable(
            self, _clock, _fresh_bot_state):
        s = _zone2_swarm_state(shields=50)  # ~42 % < 60 % enter
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) == ap.S_RETREAT

    def test_suppressed_when_shield_consumable_ready(
            self, _clock, _fresh_bot_state):
        """With a shield_recharge available the armed heal latch CAN
        fire, so the bot should defend (ENGAGE) rather than flee."""
        s = _zone2_swarm_state(
            shields=50,
            quick_use=[{"item_type": "shield_recharge", "count": 5}])
        desired = ap._choose_next_state(s, s["player"], ap.S_MINE)
        assert desired != ap.S_RETREAT
        assert desired == ap.S_ENGAGE

    def test_zero_count_consumable_still_retreats(
            self, _clock, _fresh_bot_state):
        """A shield_recharge slot with count 0 is not a usable
        consumable -- the gate must still fire."""
        s = _zone2_swarm_state(
            shields=50,
            quick_use=[{"item_type": "shield_recharge", "count": 0}])
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) == ap.S_RETREAT

    def test_fires_below_critical_even_with_consumable(
            self, _clock, _fresh_bot_state):
        """Below RETREAT_CRITICAL_SHIELD_PCT a ready shield_recharge no
        longer suppresses retreat: at near-zero shields under a swarm a
        single heal can't outpace DPS, so break contact instead of
        thrashing engage<->retreat (2026-06-01)."""
        # 24/120 = 0.20 < 0.25 critical floor.
        s = _zone2_swarm_state(
            shields=24,
            quick_use=[{"item_type": "shield_recharge", "count": 5}])
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) == ap.S_RETREAT

    def test_consumable_still_suppresses_above_critical(
            self, _clock, _fresh_bot_state):
        """Just above the critical floor a ready consumable still means
        fight + heal, not flee -- the critical override must not widen
        the normal suppression band."""
        # 36/120 = 0.30 > 0.25 critical, < 0.60 enter.
        s = _zone2_swarm_state(
            shields=36,
            quick_use=[{"item_type": "shield_recharge", "count": 5}])
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_RETREAT

    def test_suppressed_when_swarm_too_sparse(
            self, _clock, _fresh_bot_state):
        s = _zone2_swarm_state(
            shields=50,
            alien_count=ap.RETREAT_SWARM_ALIEN_COUNT - 1)
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_RETREAT

    def test_suppressed_when_aliens_out_of_range(
            self, _clock, _fresh_bot_state):
        s = _zone2_swarm_state(
            shields=50,
            alien_x0=ap.RETREAT_SWARM_RANGE_PX + 200.0)
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_RETREAT

    def test_suppressed_when_shields_high(
            self, _clock, _fresh_bot_state):
        s = _zone2_swarm_state(shields=110)  # ~92 % > 60 % enter
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_RETREAT

    def test_suppressed_in_main_zone(self, _clock, _fresh_bot_state):
        s = _zone2_swarm_state(shields=50)
        s["zone"]["id"] = "ZoneID.MAIN"
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_RETREAT

    def test_suppressed_in_warp_zone(self, _clock, _fresh_bot_state):
        s = _zone2_swarm_state(shields=50)
        s["zone"]["id"] = "ZoneID.WARP_ENEMY"
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_RETREAT

    def test_hysteresis_holds_between_enter_and_exit(
            self, _clock, _fresh_bot_state):
        """Already retreating, shields recovered to 75 % (above the
        60 % enter but below the 85 % exit): keep retreating so a
        brief regen tick under fire doesn't pop the bot back into
        the swarm."""
        s = _zone2_swarm_state(shields=90)  # 75 %
        assert ap._choose_next_state(
            s, s["player"], ap.S_RETREAT) == ap.S_RETREAT

    def test_hysteresis_releases_above_exit(
            self, _clock, _fresh_bot_state):
        s = _zone2_swarm_state(shields=110)  # ~92 % > 85 % exit
        assert ap._choose_next_state(
            s, s["player"], ap.S_RETREAT) != ap.S_RETREAT


class TestActRetreat:
    def test_drives_to_in_zone_home_station(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: dict = {}

        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        # HS within RETREAT_HS_MAX_DIST_PX (1500 < 2200) -- reachable
        # umbrella, so retreat drives toward the station.
        s = _zone2_swarm_state(
            shields=50, buildings=[_hs_building(x=1500.0, y=0.0)])
        ap._act_retreat(s, s["player"])
        assert captured.get("tx") == 1500.0
        assert captured.get("ty") == 0.0

    def test_flees_centroid_when_hs_too_far(
            self, _clock, _fresh_bot_state, monkeypatch):
        """An in-zone HS beyond RETREAT_HS_MAX_DIST_PX is unreachable
        through the swarm, so retreat ignores it and flees the centroid
        (2026-06-01 fix -- pre-fix it marched toward the distant HS and
        thrashed engage<->retreat at ~0 shields until it died)."""
        captured: dict = {}

        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        # Bot at world centre, swarm to +x, HS 3100 px away (> 2200).
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 50, "max_shields": 120},
            aliens=[{"x": 3700.0, "y": 3200.0, "hp": 50}
                    for _ in range(6)],
            buildings=[_hs_building(x=3200.0, y=100.0)],
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        ap._act_retreat(s, s["player"])
        # Centroid flee (pure -x), NOT toward the far HS.
        assert captured["tx"] == 3200.0 - ap.RETREAT_FLEE_TARGET_PX
        assert captured["ty"] == 3200.0

    def test_flees_swarm_centroid_with_no_station(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: dict = {}

        def _spy(state, p, tx, ty, stop_radius=80.0,
                 brake_on_arrival=True):
            captured["tx"], captured["ty"] = tx, ty
        monkeypatch.setattr(ap, "_do_goto", _spy)
        # Bot at world centre, swarm clustered to the +x side; with
        # no station the retreat drives along the centroid->bot ray
        # (pure -x here) out by RETREAT_FLEE_TARGET_PX.
        s = _state(
            player={"x": 3200.0, "y": 3200.0, "heading": 0.0,
                    "hp": 100, "max_hp": 100,
                    "shields": 50, "max_shields": 120},
            aliens=[{"x": 3700.0, "y": 3200.0, "hp": 50}
                    for _ in range(6)],
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        ap._act_retreat(s, s["player"])
        assert captured["tx"] == 3200.0 - ap.RETREAT_FLEE_TARGET_PX
        assert captured["ty"] == 3200.0


class TestRetreatSwarmRadiusHysteresis:
    """2026-06-02: the swarm-detect radius widens to
    RETREAT_SWARM_RANGE_EXIT_PX when already retreating OR at critical
    shields, so RETREAT doesn't release the moment the swarm drifts just
    past RETREAT_SWARM_RANGE_PX -- the engage<->regen 0-shield thrash
    that ended in death (death 2, 2026-06-02)."""

    def _swarm_at(self, *, shields, dist, max_shields=120, n=None):
        n = ap.RETREAT_SWARM_ALIEN_COUNT if n is None else n
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": shields, "max_shields": max_shields},
            aliens=[{"x": float(dist), "y": 0.0, "hp": 50}
                    for _ in range(n)],
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        return s

    def test_midband_swarm_no_retreat_at_normal_shields(
            self, _clock, _fresh_bot_state):
        # Swarm at 1500 px: > RETREAT_SWARM_RANGE_PX (1200), <
        # RETREAT_SWARM_RANGE_EXIT_PX (1800).  Shields 50/120 (0.42,
        # above critical): base radius applies -> swarm out of range ->
        # no retreat.
        s = self._swarm_at(shields=50, dist=1500.0)
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_RETREAT

    def test_midband_swarm_retreats_at_critical_shields(
            self, _clock, _fresh_bot_state):
        # Same 1500 px swarm, shields 24/120 (0.20 < critical 0.25):
        # widened radius catches the swarm -> RETREAT commits.
        s = self._swarm_at(shields=24, dist=1500.0)
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) == ap.S_RETREAT

    def test_midband_swarm_holds_while_already_retreating(
            self, _clock, _fresh_bot_state):
        # Already retreating, 1500 px swarm, shields 50 (below exit
        # 0.85): widened radius holds RETREAT instead of releasing it
        # into the thrash.
        s = self._swarm_at(shields=50, dist=1500.0)
        assert ap._choose_next_state(
            s, s["player"], ap.S_RETREAT) == ap.S_RETREAT


class TestZone2SwarmTether:
    """2026-06-02: deep in a ZONE2 swarm far from the HS, the bot heads
    home (S_IDLE_AT_BASE) instead of seeking resources/aliens deeper --
    the captured pathology was 20 edge-stucks while ENGAGE + 2 deaths
    fighting 55-60 aliens 2500-4600 px from base."""

    def _far_swarm_state(self, *, shields=120, hs_dist=3000.0,
                         alien_dist=1000.0, n=None, hs=True):
        n = ap.RETREAT_SWARM_ALIEN_COUNT if n is None else n
        buildings = [_hs_building(x=hs_dist, y=0.0)] if hs else []
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": shields, "max_shields": 120},
            aliens=[{"x": float(alien_dist), "y": 0.0, "hp": 50}
                    for _ in range(n)],
            buildings=buildings,
        )
        s["zone"]["id"] = "ZoneID.ZONE2"
        return s

    def test_far_hs_dense_swarm_heads_home(
            self, _clock, _fresh_bot_state):
        # HS 3000 px (> 2800 tether), 6 aliens at 1000 px (within the
        # 1200 swarm range, outside the 800 engage band), full shields.
        s = self._far_swarm_state()
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) == ap.S_IDLE_AT_BASE

    def test_near_hs_does_not_tether(self, _clock, _fresh_bot_state):
        # HS within the tether distance -> normal cascade (mines).
        s = self._far_swarm_state(hs_dist=1500.0)
        s["asteroids"] = [{"x": 300.0, "y": 0.0, "hp": 100}]
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_IDLE_AT_BASE

    def test_far_hs_no_swarm_does_not_tether(
            self, _clock, _fresh_bot_state):
        # Far HS but only one alien in range -> no tether.
        s = self._far_swarm_state(n=1)
        s["asteroids"] = [{"x": 300.0, "y": 0.0, "hp": 100}]
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_IDLE_AT_BASE

    def test_no_home_station_does_not_tether(
            self, _clock, _fresh_bot_state):
        # No HS to tether to (early game) -> keep roaming.
        s = self._far_swarm_state(hs=False)
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) != ap.S_IDLE_AT_BASE

    def test_close_threat_engages_over_tether(
            self, _clock, _fresh_bot_state):
        # Alien inside the 800 px engage band -> ENGAGE (defend) outranks
        # the tether, which sits below ENGAGE.
        s = self._far_swarm_state(alien_dist=500.0)
        assert ap._choose_next_state(
            s, s["player"], ap.S_MINE) == ap.S_ENGAGE
