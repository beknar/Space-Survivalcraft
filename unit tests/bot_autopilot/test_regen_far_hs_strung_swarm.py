"""REGEN far-HS break-contact for a strung-out swarm (2026-06-18 fix).

Regression guard for a 3-death ZONE2 session in ``bot_io``: the bot
entered REGEN at 39-49% shields ~3700-4900 px from the Home Station --
well beyond the ``RETREAT_HS_MAX_DIST_PX`` (2200) umbrella reach -- in a
60-alien swarm with no shield_recharge, then drove toward the unreachable
HS at ~88 px/s and bled out (three times).

REGEN's far-HS break-contact (``_flee_swarm_centroid``) was meant to
catch exactly this, but its ``_dense_swarm_adjacent`` gate required
``RETREAT_SWARM_ALIEN_COUNT`` (6) aliens within the tight
``RETREAT_SWARM_RANGE_PX`` (1200).  A strung-out swarm slips through
(~4-5 within 1200 px, ~10 within 1800 px), so the gate stayed False and
the bot took the fatal drive.  The fix widens the gate to
``RETREAT_SWARM_RANGE_EXIT_PX`` (1800) for the far-HS case.
"""
from __future__ import annotations

import bot_autopilot as ap
import bot_autopilot_actions_combat as ac

from _helpers import _state, _hs_building


def _strung_out_swarm(px, py, n=7, lo=1300.0, hi=1750.0):
    """n aliens ringed between lo and hi px from (px,py): none inside
    the tight 1200 px gate, all inside the wide 1800 px gate."""
    step = (hi - lo) / max(1, n - 1)
    return [{"x": px + lo + step * i, "y": py, "hp": 50} for i in range(n)]


class TestDenseSwarmAdjacentRange:
    def test_strung_out_swarm_misses_tight_gate(self):
        s = {"aliens": _strung_out_swarm(0.0, 0.0)}
        assert ac._dense_swarm_adjacent(s, 0.0, 0.0) is False

    def test_strung_out_swarm_caught_by_wide_gate(self):
        s = {"aliens": _strung_out_swarm(0.0, 0.0)}
        assert ac._dense_swarm_adjacent(
            s, 0.0, 0.0,
            swarm_range=ap.RETREAT_SWARM_RANGE_EXIT_PX) is True


class TestRegenFarHsBreakContact:
    def _spy(self, monkeypatch):
        calls: dict = {}
        monkeypatch.setattr(
            ac, "_flee_swarm_centroid",
            lambda state, p, px, py: calls.update(fled=True))
        monkeypatch.setattr(
            ac, "_regen_drive_to_hs",
            lambda state, p, px, py, hs: calls.update(drove=True))
        return calls

    def test_far_hs_strung_swarm_breaks_contact(self, monkeypatch):
        """HS beyond 2200 px + a strung-out swarm (none within 1200 px,
        plenty within 1800 px): the bot must peel away, not drive to the
        unreachable umbrella."""
        calls = self._spy(monkeypatch)
        # Bot at origin; HS ~3500 px away (> RETREAT_HS_MAX_DIST_PX).
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 0, "max_shields": 100},
            buildings=[_hs_building(x=3500.0, y=0.0)],
        )
        s["aliens"] = _strung_out_swarm(0.0, 0.0)
        ac._act_regen(s, s["player"])
        assert calls.get("fled") is True
        assert "drove" not in calls

    def test_far_hs_no_swarm_still_drives_to_hs(self, monkeypatch):
        """Control: far HS but no swarm at all — driving home is fine,
        no regression to the break-contact."""
        calls = self._spy(monkeypatch)
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 0, "max_shields": 100},
            buildings=[_hs_building(x=3500.0, y=0.0)],
        )
        s["aliens"] = []
        ac._act_regen(s, s["player"])
        assert calls.get("drove") is True
        assert "fled" not in calls

    def test_near_hs_swarm_drives_to_umbrella(self, monkeypatch):
        """Control: HS within reach (< RETREAT_HS_MAX_DIST_PX) — the
        umbrella is worth the drive even under a swarm, unchanged."""
        calls = self._spy(monkeypatch)
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 0, "max_shields": 100},
            buildings=[_hs_building(x=1500.0, y=0.0)],   # < 2200
        )
        s["aliens"] = _strung_out_swarm(0.0, 0.0)
        ac._act_regen(s, s["player"])
        assert calls.get("drove") is True
        assert "fled" not in calls

    def test_far_hs_few_distant_stragglers_still_drives(self, monkeypatch):
        """A couple of distant stragglers (below the count threshold even
        at the wide range) are not a swarm — the bot still heads home."""
        calls = self._spy(monkeypatch)
        s = _state(
            player={"x": 0.0, "y": 0.0, "heading": 0.0,
                    "shields": 0, "max_shields": 100},
            buildings=[_hs_building(x=3500.0, y=0.0)],
        )
        # Only 2 aliens within the wide range — under RETREAT_SWARM_ALIEN_COUNT.
        s["aliens"] = [{"x": 1400.0, "y": 0.0, "hp": 50},
                       {"x": 1500.0, "y": 0.0, "hp": 50}]
        ac._act_regen(s, s["player"])
        assert calls.get("drove") is True
        assert "fled" not in calls
