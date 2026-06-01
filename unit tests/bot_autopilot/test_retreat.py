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
        s = _zone2_swarm_state(
            shields=50, buildings=[_hs_building(x=3200.0, y=3200.0)])
        # Bot is at the origin, far from the HS umbrella, so retreat
        # drives toward the station.
        ap._act_retreat(s, s["player"])
        assert captured.get("tx") == 3200.0
        assert captured.get("ty") == 3200.0

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
