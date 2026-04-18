"""Soak tests for the null field stealth patches.

Two scenarios, 5 minutes each:

- ``TestSoakNullFieldIdle`` — Zone 2 runs continuously while the
  player sits INSIDE a null field.  Exercises the cloak gate in the
  alien AI, the null-field draw path (30 fields × 28 dots batched),
  and the timer tick.
- ``TestSoakNullFieldChurn`` — Zone 2 runs while the player
  periodically fires from inside a null field (triggering the 30 s
  disable), lets it recover, then fires again.  Catches any leak in
  the trigger/cooldown/restore cycle.

Shared thresholds + loop in ``_soak_base.py``. Not executed by the
default pytest run (``pytest.ini``'s ``norecursedirs``).

Run with:
    pytest "unit tests/integration/test_soak_null_field.py" -v -s
"""
from __future__ import annotations

import math

from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _setup_zone2_with_fields(gv):
    """Transition to Zone 2, invulnerable player, and stash a known
    NullField on top of the player so cloak is guaranteed.

    Returns the planted NullField so the caller can toggle it."""
    from sprites.null_field import NullField

    make_invulnerable(gv)
    if gv._zone.zone_id != ZoneID.ZONE2:
        gv._transition_zone(ZoneID.ZONE2)
    # Plant a big field on the player so cloak check is hot every tick.
    nf = NullField(gv.player.center_x, gv.player.center_y, size=256)
    gv._zone._null_fields.append(nf)
    return nf


def _make_idle_churn(gv):
    """No firing — just run the update/draw loop while cloaked."""
    def tick(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.player.shields = gv.player.max_shields
        gv.on_update(dt)
        gv.on_draw()
    return tick


def _make_fire_churn(gv, nf):
    """Periodically fire from inside the field, let it recover, fire
    again. Cycle length: ~60 seconds (disable lasts 30 s, then 30 s
    of cloaked rest before the next shot)."""
    from update_logic import disable_null_field_around_player
    step = {"n": 0}

    def tick(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.player.shields = gv.player.max_shields
        # Every 60 simulated seconds (3600 ticks at 1/60) fire one shot.
        if step["n"] % 3600 == 0:
            disable_null_field_around_player(gv)
        gv.on_update(dt)
        gv.on_draw()
        step["n"] += 1
    return tick


class TestSoakNullFieldIdle:
    def test_null_field_idle_zone2_5min_soak(self, real_game_view):
        """5-minute Nebula soak with the player cloaked inside a null
        field.  Every frame batches 840+ dot points via draw_points."""
        gv = real_game_view
        _setup_zone2_with_fields(gv)
        run_soak(gv, "Null field idle", _make_idle_churn(gv))


class TestSoakNullFieldChurn:
    def test_null_field_fire_cycle_zone2_5min_soak(self, real_game_view):
        """5-minute Nebula soak where the player fires from inside the
        field every 60 s so the disable→active cycle runs ~5 times."""
        gv = real_game_view
        nf = _setup_zone2_with_fields(gv)
        run_soak(gv, "Null field churn", _make_fire_churn(gv, nf))
