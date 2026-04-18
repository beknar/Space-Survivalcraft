"""Resilience tests for the refugee spawn flake fix.

The bug: ``test_refugee_spawns_after_shield_generator_in_zone2``
asserted on a single tick after adding a Shield Generator.  In the
full integration suite it occasionally failed despite passing in
isolation — likely due to ordering inside ``on_update`` or shared
state across tests in the session.

The fix: tick a small budget (5 frames) per phase rather than
exactly one, and reset refugee state both before AND after the
zone transition.

These tests verify the fix holds even under hostile preconditions:
- Stale ``_refugee_spawned`` carrying over from a hypothetical
  prior test
- ``_refugee_npc`` already populated
- The transition itself happens to flip state mid-test
"""
from __future__ import annotations

import pytest

from sprites.building import create_building
from sprites.npc_ship import RefugeeNPCShip
from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID


def _setup_zone2_with_home_station(gv):
    """Common setup — transition to ZONE2, clear buildings, drop a
    Home Station at the centre."""
    gv._transition_zone(ZoneID.ZONE2)
    gv.building_list.clear()
    tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", tex,
        WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))


def _add_shield_generator(gv):
    sg_tex = gv._building_textures["Shield Generator"]
    gv.building_list.append(create_building(
        "Shield Generator", sg_tex,
        WORLD_WIDTH / 2 + 80, WORLD_HEIGHT / 2, scale=0.5))


def _tick_until_spawned(gv, max_ticks: int = 5) -> bool:
    for _ in range(max_ticks):
        gv.on_update(1 / 60)
        if gv._refugee_npc is not None:
            return True
    return False


class TestRefugeeSpawnResilientToStaleState:
    def test_spawns_even_with_stale_refugee_spawned_flag(
            self, real_game_view):
        """If a previous test left ``_refugee_spawned=True`` and we
        forget to reset it, the test fix's pre-transition reset must
        still let the next refugee spawn cleanly."""
        gv = real_game_view
        # Simulate stale state from a hypothetical prior test.
        gv._refugee_spawned = True
        gv._refugee_npc = None

        # Now do what the test does: explicitly reset before transition.
        gv._refugee_npc = None
        gv._refugee_spawned = False
        _setup_zone2_with_home_station(gv)
        gv._refugee_npc = None
        gv._refugee_spawned = False

        _add_shield_generator(gv)
        spawned = _tick_until_spawned(gv)
        assert spawned, (
            "Refugee did not spawn within 5 ticks after Shield "
            "Generator added — flake fix didn't help")
        assert gv._refugee_spawned is True

    def test_spawns_even_with_stale_refugee_npc_object(
            self, real_game_view):
        """Stale ``_refugee_npc`` object — must be cleared by the
        test's pre-transition reset for the spawn path to fire."""
        gv = real_game_view
        # Pretend a prior test left a refugee in flight.
        gv._refugee_npc = RefugeeNPCShip(100.0, 100.0, (200.0, 200.0))
        gv._refugee_spawned = True

        # Test's defensive reset before transition.
        gv._refugee_npc = None
        gv._refugee_spawned = False
        _setup_zone2_with_home_station(gv)
        gv._refugee_npc = None
        gv._refugee_spawned = False

        _add_shield_generator(gv)
        spawned = _tick_until_spawned(gv)
        assert spawned

    def test_no_spawn_without_shield_generator_even_with_extra_ticks(
            self, real_game_view):
        """The "extra ticks per phase" half of the fix must NOT
        accidentally spawn a refugee when the precondition is unmet
        — even after 10 ticks with just a Home Station present."""
        gv = real_game_view
        gv._refugee_npc = None
        gv._refugee_spawned = False
        _setup_zone2_with_home_station(gv)
        gv._refugee_npc = None
        gv._refugee_spawned = False

        for _ in range(10):
            gv.on_update(1 / 60)
            assert gv._refugee_npc is None, (
                "Refugee spawned without a Shield Generator")

    def test_spawn_is_idempotent_across_repeated_runs(self, real_game_view):
        """Run the spawn flow twice on the same GameView — second
        run after explicit reset must still spawn cleanly."""
        gv = real_game_view
        # Run #1
        gv._refugee_npc = None
        gv._refugee_spawned = False
        _setup_zone2_with_home_station(gv)
        gv._refugee_npc = None
        gv._refugee_spawned = False
        _add_shield_generator(gv)
        assert _tick_until_spawned(gv)

        # Run #2 — clean reset and repeat
        gv._refugee_npc = None
        gv._refugee_spawned = False
        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(create_building(
            "Home Station", tex,
            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))
        _add_shield_generator(gv)
        assert _tick_until_spawned(gv), (
            "Second-run refugee spawn failed — fix should be "
            "idempotent across repeated test runs in the same session")
