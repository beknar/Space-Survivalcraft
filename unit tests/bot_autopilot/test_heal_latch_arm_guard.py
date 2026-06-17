"""Heal-latch arm guard (2026-06-16 fix).

Regression guard for the no-supply heal-arm churn captured in
``bot_io`` telemetry: over a 2.4 h ZONE2 session the shield-heal latch
armed 46 times with *zero* ``shield_recharge`` in ship / station /
quick-use slot, each arm riding 37-79 s to the natural-regen disarm
band (shields 70 %) without ever firing -- 54 % of all shield arms,
pure wasted latch + telemetry churn.

The fix gates the arm on the same ``_find_quick_use_slot`` lookup the
fire path uses (count > 0), so a latch only arms when the matching
consumable is actually available to fire.
"""
from __future__ import annotations

import bot_autopilot as ap

from _helpers import _state


def _low_state(*, hp=150, max_hp=150, shields=30, max_shields=150,
               slots=None):
    s = _state(
        player={"x": 0.0, "y": 0.0, "heading": 0.0,
                "hp": hp, "max_hp": max_hp,
                "shields": shields, "max_shields": max_shields},
    )
    s["quick_use_slots"] = list(slots) if slots is not None else []
    return s


class TestShieldArmGuard:
    def test_no_arm_without_shield_recharge(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Shields below threshold but no shield_recharge anywhere —
        the latch must NOT arm (the captured ZONE2 no-supply case)."""
        monkeypatch.setattr(ap, "_post_use_quick_use",
                            lambda slot: {"ok": True})
        s = _low_state(shields=30, slots=[])   # empty quick-use bar
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_shield_active is False

    def test_no_arm_when_slot_count_zero(
            self, _clock, _fresh_bot_state, monkeypatch):
        """A shield_recharge slot drained to count 0 is not 'available'
        — the latch must stay disarmed."""
        monkeypatch.setattr(ap, "_post_use_quick_use",
                            lambda slot: {"ok": True})
        s = _low_state(
            shields=30,
            slots=[{"item_type": "shield_recharge", "count": 0}])
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_shield_active is False

    def test_arms_and_fires_when_shield_recharge_present(
            self, _clock, _fresh_bot_state, monkeypatch):
        """Control: with a stocked shield_recharge the latch arms and
        fires exactly as before the guard."""
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _low_state(
            shields=30,
            slots=[{"item_type": "shield_recharge", "count": 25}])
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_shield_active is True
        assert captured == [0]


class TestHpArmGuard:
    def test_no_arm_without_repair_pack(
            self, _clock, _fresh_bot_state, monkeypatch):
        """HP below threshold but no repair_pack — no arm.  Matters
        more for HP: with no passive regen a supply-less HP arm would
        never reach its disarm band and stay armed indefinitely."""
        monkeypatch.setattr(ap, "_post_use_quick_use",
                            lambda slot: {"ok": True})
        s = _low_state(hp=30, max_hp=100, shields=150, slots=[])
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is False

    def test_arms_and_fires_when_repair_pack_present(
            self, _clock, _fresh_bot_state, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            ap, "_post_use_quick_use",
            lambda slot: captured.append(slot) or {"ok": True})
        s = _low_state(
            hp=30, max_hp=100, shields=150,
            slots=[{"item_type": "repair_pack", "count": 25}])
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_hp_active is True
        assert captured == [0]


class TestDisarmStillWorksWithoutSupply:
    def test_armed_shield_latch_disarms_at_band_even_if_supply_gone(
            self, _clock, _fresh_bot_state, monkeypatch):
        """A latch armed while supply existed must still disarm at the
        70 % band after the supply ran out — the guard only blocks the
        ARM edge, never the disarm edge (so a depleted latch can't get
        stuck armed forever)."""
        monkeypatch.setattr(ap, "_post_use_quick_use",
                            lambda slot: {"ok": True})
        ap._state.heal_shield_active = True   # pre-armed
        # Shields recovered to 75 % via natural regen; no recharge left.
        s = _low_state(shields=113, max_shields=150, slots=[])
        ap._maybe_use_consumables(s, s["player"])
        assert ap._state.heal_shield_active is False
