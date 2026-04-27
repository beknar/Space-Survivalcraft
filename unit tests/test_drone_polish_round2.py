"""Round-2 drone polish: pickup vacuum on combat drone, wormhole
follow, parked-ship modules drop as ready-to-equip, homing missiles
target stalkers.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


# ── Combat drone vacuums pickups ──────────────────────────────────────────


class TestCombatDronePickupVacuum:
    def test_combat_drone_flags_nearby_iron_pickup_flying(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        # Iron pickup 50 px away (well inside the
        # MINING_DRONE_PICKUP_RADIUS = 200 px vacuum reach).
        pickup = SimpleNamespace(
            center_x=50.0, center_y=0.0, _flying=False)
        gv = SimpleNamespace(
            iron_pickup_list=[pickup],
            blueprint_pickup_list=[])
        d._vacuum_pickups(gv)
        assert pickup._flying is True

    def test_combat_drone_does_not_touch_already_flying(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        pickup = SimpleNamespace(
            center_x=50.0, center_y=0.0, _flying=True)
        gv = SimpleNamespace(
            iron_pickup_list=[pickup],
            blueprint_pickup_list=[])
        d._vacuum_pickups(gv)
        # Still True — wasn't toggled (and shouldn't be touched at
        # all, but the visible side effect is just the flag).
        assert pickup._flying is True

    def test_combat_drone_skips_far_pickups(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        far = SimpleNamespace(
            center_x=2000.0, center_y=0.0, _flying=False)
        gv = SimpleNamespace(
            iron_pickup_list=[far],
            blueprint_pickup_list=[])
        d._vacuum_pickups(gv)
        assert far._flying is False

    def test_mining_drone_still_vacuums(self):
        """Helper extracted to _BaseDrone — both subclasses get it."""
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        pickup = SimpleNamespace(
            center_x=80.0, center_y=0.0, _flying=False)
        gv = SimpleNamespace(
            iron_pickup_list=[pickup],
            blueprint_pickup_list=[])
        d._vacuum_pickups(gv)
        assert pickup._flying is True


# ── Drone follows player through wormhole transition ──────────────────────


class TestDroneFollowsThroughWormhole:
    def test_active_drone_teleports_to_new_spawn(self):
        """``_transition_zone`` repositions the player to the new
        zone's spawn; the active drone must follow to a slot near
        that spawn so it doesn't get stranded in the previous
        zone."""
        from game_view import GameView
        from sprites.drone import CombatDrone
        from zones import ZoneID
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        d = CombatDrone(gv.player.center_x, gv.player.center_y)
        gv._drone_list.append(d)
        gv._active_drone = d
        # Transition into Zone 2 — drone position must update to
        # the new spawn's neighbourhood (we drop it at +30, +30).
        gv._transition_zone(ZoneID.ZONE2)
        new_px, new_py = gv.player.center_x, gv.player.center_y
        assert d.center_x == new_px + 30
        assert d.center_y == new_py + 30

    def test_no_drone_no_op(self):
        from game_view import GameView
        from zones import ZoneID
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        # No drone — transition must not raise.
        gv._transition_zone(ZoneID.ZONE2)
        assert gv._active_drone is None

    def test_drone_planner_is_re_attached(self):
        """Maze geometry is per-zone; clearing
        ``_follow_planner_geom_id`` forces ``attach_maze_planner``
        to rebuild with the new zone's rooms on the next tick."""
        from game_view import GameView
        from sprites.drone import CombatDrone
        from zones import ZoneID
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        d = CombatDrone(gv.player.center_x, gv.player.center_y)
        gv._drone_list.append(d)
        gv._active_drone = d
        # Pre-set the geom id to something non-zero to confirm
        # the transition resets it.
        d._follow_planner_geom_id = 12345
        gv._transition_zone(ZoneID.ZONE2)
        assert d._follow_planner_geom_id == 0


# ── Modules dropped from destroyed parked ship are ready-to-equip ────────


class TestParkedShipModuleDropType:
    def test_dropped_module_pickup_has_mod_item_type(self):
        """``_destroy_parked_ship`` must spawn module drops with
        ``item_type = "mod_<key>"`` so the inventory's add_item
        routes them to the equippable cell, NOT the
        ``bp_<key>`` blueprint cell that requires re-crafting."""
        from collisions import _destroy_parked_ship
        from sprites.parked_ship import ParkedShip
        # Need a real GameView for textures + lists.
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        ps = ParkedShip(
            faction="Earth", ship_type="Cruiser", ship_level=1,
            x=2000.0, y=2000.0)
        # Equip a module the drop logic can serialise.
        ps.module_slots = ["armor_plate", None, None, None]
        gv._parked_ships.append(ps)
        before = len(gv.blueprint_pickup_list)
        _destroy_parked_ship(gv, ps)
        new_drops = list(gv.blueprint_pickup_list)[before:]
        assert len(new_drops) == 1
        mod_drop = new_drops[0]
        assert mod_drop.item_type == "mod_armor_plate", (
            f"got {mod_drop.item_type!r} — modules dropped from a "
            f"destroyed parked ship must be ready-to-equip "
            f"(``mod_<key>``), not blueprints (``bp_<key>``)")


# ── Homing missiles target stalkers ───────────────────────────────────────


class TestMissilesTargetStalkers:
    def test_stalkers_added_to_target_list(self):
        """The target collection in ``update_missiles`` should
        include any live stalker the active zone exposes."""
        # Use a stub zone so the test doesn't need a full GameView.
        from update_logic import update_missiles
        # Drop in a stalker stand-in; only need (x, y) tuples in
        # the targets list — verify by tapping update_missile().
        from sprites.missile import HomingMissile
        from zones import ZoneID
        # Build a minimal stub gv.
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv._transition_zone(ZoneID.STAR_MAZE)
        # Drop a fake stalker on the zone's _stalkers list at a
        # known position; clear other targets so the missile only
        # has this one option.
        zone = gv._zone
        # Empty other target lists for an unambiguous test.
        for attr in ("_aliens", "_maze_aliens"):
            lst = getattr(zone, attr, None)
            if lst is not None:
                lst.clear()
        for sp in getattr(zone, "_spawners", ()):
            sp.killed = True
        # Inject a single fake stalker.  ``update_missiles`` only
        # iterates ``zone._stalkers`` and reads center_x / center_y /
        # hp, so a plain list of namespaces is fine and avoids the
        # arcade.SpriteList unhashable-sprite restriction.
        zone._stalkers = [
            SimpleNamespace(
                center_x=12345.0, center_y=6789.0, hp=10),
        ]
        # Spy on HomingMissile.update_missile to capture the
        # targets it receives.
        captured: dict = {}
        orig = HomingMissile.update_missile
        def _spy(self, dt, targets):
            captured["targets"] = list(targets)
            return orig(self, dt, targets)
        # Build one missile so the collection loop runs.
        m = HomingMissile(gv._missile_tex, 1000.0, 1000.0, 0.0)
        gv._missile_list.append(m)
        try:
            with patch.object(HomingMissile, "update_missile", _spy):
                update_missiles(gv, 1 / 60)
        finally:
            gv._missile_list.clear()
        assert (12345.0, 6789.0) in captured.get("targets", []), (
            f"stalker (12345, 6789) not in missile targets: "
            f"{captured.get('targets')}")
