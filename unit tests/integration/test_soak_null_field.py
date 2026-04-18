"""Soak tests for the null field stealth patches.

Two scenarios, 5 minutes each:

- ``TestSoakNullFieldIdle`` — Zone 2 runs continuously while the
  player sits INSIDE a null field.  Exercises the cloak gate in the
  alien AI, the null-field draw path (30 fields × 28 dots batched),
  and the timer tick.
- ``TestSoakNullFieldChurn`` — Zone 2 runs while the player
  periodically fires from inside a null field (triggering the 10 s
  red-flash disable), lets it recover, then fires again. Catches any
  leak in the trigger/cooldown/restore cycle.

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
    again. Cycle length: ~60 seconds (10 s red-flash disable then
    ~50 s of cloaked rest before the next shot)."""
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


class TestSoakCloakVisualToggle:
    def test_cloak_visual_toggle_zone2_5min_soak(self, real_game_view):
        """5-minute Nebula soak where the player teleports in and out
        of the null field every second so `draw_logic._draw_world`
        alternates between the ghost-alpha path and the opaque path.
        Catches any leak in the save/restore of `player.color` around
        `player_list.draw()` (e.g. stuck alpha across frames or
        color-tuple allocation churn)."""
        from sprites.null_field import NullField
        gv = real_game_view
        nf = _setup_zone2_with_fields(gv)
        # Spawn + save the planted field's centre as a teleport anchor.
        hx, hy = nf.center_x, nf.center_y
        step = {"n": 0}

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            # Every 30 simulated frames (~0.5 s) flip position so the
            # cloak flickers fast — exercises the alpha-save/restore
            # and the active-fields loop under contention.
            if step["n"] % 30 == 0:
                gv.player.center_x = hx
                gv.player.center_y = hy
            elif step["n"] % 30 == 15:
                gv.player.center_x = hx + 5000.0
                gv.player.center_y = hy
            gv.on_update(dt)
            gv.on_draw()
            step["n"] += 1

        run_soak(gv, "Null field cloak visual", tick)


class TestSoakCloakVisualDisableCycle:
    def test_cloak_visual_disable_cycle_zone2_5min_soak(self, real_game_view):
        """5-minute soak where the player sits inside a null field and
        fires every 20 seconds, so the ship oscillates between the
        cloaked (ghost alpha) and uncloaked (opaque, field disabled)
        visual states continuously. The 10 s red-flash disable plus
        10 s of cloaked rest between shots gives an even split. Pairs
        with the integration tests that assert the alpha never sticks
        across frames."""
        from update_logic import disable_null_field_around_player
        gv = real_game_view
        _setup_zone2_with_fields(gv)
        step = {"n": 0}

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            # Fire every 1200 frames (~20 s at 1/60).  The 10 s disable
            # completes by the midpoint, so the visual spends half the
            # cycle cloaked and half the cycle uncloaked.
            if step["n"] % 1200 == 0 and step["n"] > 0:
                disable_null_field_around_player(gv)
            gv.on_update(dt)
            gv.on_draw()
            step["n"] += 1

        run_soak(gv, "Null field cloak disable cycle", tick)
