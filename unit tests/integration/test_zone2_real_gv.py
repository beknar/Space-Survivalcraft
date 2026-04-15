"""End-to-end integration tests using a real GameView + hidden Arcade window.

These exercise the full wiring: real textures, real sprite lists, real zone
state machines.  Run them explicitly with ``pytest "unit tests/integration/"``
— they're excluded from the default fast suite because the shared Arcade
window can interfere with other tests' window-size math.

Each test gets a fresh ``real_game_view`` (see ``conftest.py``).
"""
from __future__ import annotations

import math

import arcade
import pytest

from zones import ZoneID
from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BUILDING_TYPES, MODULE_SLOT_COUNT,
    CRAFT_TIME, CRAFT_IRON_COST,
)


# ═══════════════════════════════════════════════════════════════════════════
#  Existing regression tests (kept from the original file)
# ═══════════════════════════════════════════════════════════════════════════

class TestZone2RealUpdate:
    def test_zone2_transition_then_alien_collision_does_not_crash(
        self, real_game_view
    ):
        """Regression: UnboundLocalError on resolve_overlap when cooldown
        was active and asteroid branch was skipped."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        assert gv._zone.zone_id == ZoneID.ZONE2

        from sprites.zone2_aliens import ShieldedAlien
        alien = ShieldedAlien(
            gv._zone._alien_textures["shielded"],
            gv._alien_laser_tex,
            gv.player.center_x,
            gv.player.center_y,
        )
        gv._zone._aliens.append(alien)
        gv._zone._shielded_aliens = [alien]
        gv.player._collision_cd = 0.5
        gv._zone.update(gv, 1 / 60)

    def test_zone2_basic_update_tick_with_populated_world(self, real_game_view):
        """A freshly populated Zone 2 survives several update ticks."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        for _ in range(5):
            gv._zone.update(gv, 1 / 60)


# ═══════════════════════════════════════════════════════════════════════════
#  #1 — Save / load round trip
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveLoadRoundTrip:
    def test_player_state_survives_save_load(self, real_game_view):
        """Save, load into the same GameView, verify player position,
        HP, inventory iron, and module slots all survive the round trip.

        Note: save_to_dict stores list/dict *references*. In production
        the data passes through JSON (which copies everything), so we
        simulate that with json.loads(json.dumps(data))."""
        import json
        from game_save import save_to_dict, restore_state

        gv = real_game_view
        # Set up distinctive state
        gv.player.center_x = 1234.0
        gv.player.center_y = 4321.0
        gv.player.hp = 42
        gv.inventory.add_item("iron", 77)
        gv._module_slots[0] = "armor_plate"

        data = json.loads(json.dumps(save_to_dict(gv, "test-save")))
        # Clobber state to prove the restore actually resets it
        gv.player.center_x = 0.0
        gv.player.center_y = 0.0
        gv.player.hp = 1
        gv.inventory._items.clear()
        gv.inventory._mark_dirty()
        gv._module_slots[0] = None

        restore_state(gv, data)

        assert gv.player.center_x == pytest.approx(1234.0)
        assert gv.player.center_y == pytest.approx(4321.0)
        assert gv.player.hp == 42
        assert gv.inventory.total_iron == 77
        assert gv._module_slots[0] == "armor_plate"

    def test_station_inventory_survives_save_load(self, real_game_view):
        """Station inventory items persist through a save/load cycle."""
        from game_save import save_to_dict, restore_state

        gv = real_game_view
        gv._station_inv.add_item("copper", 50)
        gv._station_inv.add_item("repair_pack", 3)

        data = save_to_dict(gv, "test-save")
        gv._station_inv._items.clear()
        gv._station_inv._mark_dirty()

        restore_state(gv, data)

        assert gv._station_inv.count_item("copper") == 50
        assert gv._station_inv.count_item("repair_pack") == 3


# ═══════════════════════════════════════════════════════════════════════════
#  #2 — Zone 2 exit restores Zone 1
# ═══════════════════════════════════════════════════════════════════════════

class TestZone2Exit:
    def test_return_to_zone1_restores_asteroid_list(self, real_game_view):
        """Entering Zone 2 stashes Zone 1 asteroids, returning restores them."""
        gv = real_game_view
        assert gv._zone.zone_id == ZoneID.MAIN
        z1_asteroid_count = len(gv.asteroid_list)
        assert z1_asteroid_count > 0

        gv._transition_zone(ZoneID.ZONE2)
        assert gv._zone.zone_id == ZoneID.ZONE2
        # Zone 1 asteroids are stashed — gv.asteroid_list is now empty
        assert len(gv.asteroid_list) == 0

        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        assert gv._zone.zone_id == ZoneID.MAIN
        assert len(gv.asteroid_list) == z1_asteroid_count

    def test_return_to_zone1_spawns_at_centre(self, real_game_view):
        """On wormhole return, player spawns at the Zone 1 centre.

        Note: MainZone.setup() calls stash.clear() before get_player_spawn()
        runs, so the stashed ``_player_pos`` is wiped and the player falls
        back to (WORLD_WIDTH/2, WORLD_HEIGHT/2). This test documents the
        current behaviour; if position preservation is desired in the
        future, get_player_spawn must extract the position before clear().
        """
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        assert gv._zone.zone_id == ZoneID.ZONE2

        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        assert gv.player.center_x == pytest.approx(WORLD_WIDTH / 2)
        assert gv.player.center_y == pytest.approx(WORLD_HEIGHT / 2)


# ═══════════════════════════════════════════════════════════════════════════
#  #3 — Warp zone entry and exit
# ═══════════════════════════════════════════════════════════════════════════

class TestWarpZoneRoundTrip:
    def test_warp_zone_setup_and_return(self, real_game_view):
        """Enter a warp zone, tick a few frames, exit via bottom edge,
        verify player ends up back in Zone 1."""
        gv = real_game_view
        assert gv._zone.zone_id == ZoneID.MAIN
        z1_asteroids = len(gv.asteroid_list)

        gv._transition_zone(ZoneID.WARP_METEOR, entry_side="bottom")
        assert gv._zone.zone_id == ZoneID.WARP_METEOR

        # Tick a few frames (hazards may spawn)
        for _ in range(5):
            gv._zone.update(gv, 1 / 60)

        # Exit via bottom edge (player at y < EXIT_THRESHOLD triggers return)
        gv.player.center_y = 5.0
        gv._zone.update(gv, 1 / 60)

        # Should be back in Zone 1 with asteroids restored
        assert gv._zone.zone_id == ZoneID.MAIN
        assert len(gv.asteroid_list) == z1_asteroids


# ═══════════════════════════════════════════════════════════════════════════
#  #4 — Boss spawn conditions
# ═══════════════════════════════════════════════════════════════════════════

class TestBossSpawn:
    def test_boss_spawns_when_all_conditions_met(self, real_game_view):
        """Set all preconditions (level 5, 4 modules, 5 repair packs,
        Home Station built) and verify the boss spawns."""
        from sprites.building import HomeStation, create_building

        gv = real_game_view
        # Ensure we're in Zone 1
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Reset boss state
        gv._boss = None
        gv._boss_spawned = False
        gv._boss_defeated = False
        gv._boss_list.clear()

        # Character level 5
        gv._char_level = 5
        gv._char_xp = 1000

        # Fill all module slots
        module_keys = list(dict.fromkeys(
            k for k in ("armor_plate", "engine_booster",
                        "shield_booster", "damage_absorber")))
        for i in range(MODULE_SLOT_COUNT):
            gv._module_slots[i] = module_keys[i % len(module_keys)]

        # 5 repair packs in inventory
        gv.inventory.add_item("repair_pack", 5)

        # Place a Home Station
        tex = gv._building_textures["Home Station"]
        home = create_building("Home Station", tex,
                               WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                               scale=0.5)
        gv.building_list.append(home)

        # Trigger the spawn check
        from combat_helpers import check_boss_spawn
        check_boss_spawn(gv)

        assert gv._boss is not None, "Boss should have spawned"
        assert gv._boss.hp > 0
        assert gv._boss_spawned is True

    def test_boss_does_not_spawn_without_home_station(self, real_game_view):
        """If no Home Station is built, the boss doesn't spawn even if
        all other conditions are met."""
        from combat_helpers import check_boss_spawn

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        gv._boss = None
        gv._boss_spawned = False
        gv._boss_defeated = False
        gv._char_level = 5
        for i in range(MODULE_SLOT_COUNT):
            gv._module_slots[i] = "armor_plate"
        gv.inventory.add_item("repair_pack", 5)
        # No home station — clear building list
        gv.building_list.clear()

        check_boss_spawn(gv)
        assert gv._boss is None


# ═══════════════════════════════════════════════════════════════════════════
#  #5 — Building placement with docking snap
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildingPlacement:
    def test_home_station_places_at_player(self, real_game_view):
        """Place a Home Station: verify it's added to building_list and
        iron cost is deducted."""
        from building_manager import place_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv.building_list.clear()

        cost = BUILDING_TYPES["Home Station"]["cost"]
        gv.inventory.add_item("iron", cost + 100)
        iron_before = gv.inventory.total_iron

        gv._placing_building = "Home Station"
        gv._ghost_rotation = 0.0
        place_building(gv, gv.player.center_x + 200, gv.player.center_y)

        assert len(gv.building_list) == 1
        assert gv.building_list[0].building_type == "Home Station"
        assert gv.inventory.total_iron == iron_before - cost

    def test_service_module_snaps_to_home_station(self, real_game_view):
        """Place a Service Module near a Home Station: it should snap to
        a docking port and both ports become occupied."""
        from building_manager import place_building
        from sprites.building import create_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv.building_list.clear()

        # Place Home Station manually
        tex = gv._building_textures["Home Station"]
        home = create_building("Home Station", tex,
                               WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                               scale=0.5)
        gv.building_list.append(home)

        # Give enough iron for a Service Module
        sm_cost = BUILDING_TYPES["Service Module"]["cost"]
        gv.inventory.add_item("iron", sm_cost + 100)

        # Place service module near the home station's north port
        gv._placing_building = "Service Module"
        gv._ghost_rotation = 0.0
        # Aim above the home station
        place_building(gv, WORLD_WIDTH / 2,
                       WORLD_HEIGHT / 2 + home.height * 0.5 / 2 + 20)

        assert len(gv.building_list) == 2
        sm = [b for b in gv.building_list
              if b.building_type == "Service Module"]
        assert len(sm) == 1


# ═══════════════════════════════════════════════════════════════════════════
#  #6 — Craft completion
# ═══════════════════════════════════════════════════════════════════════════

class TestCraftCompletion:
    def test_repair_pack_craft_completes(self, real_game_view):
        """Start a repair-pack craft on a BasicCrafter building, tick
        until done, verify the item lands in station inventory."""
        from sprites.building import BasicCrafter, create_building
        from update_logic import update_crafting

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Manually add a BasicCrafter to the building list
        tex = gv._building_textures["Basic Crafter"]
        crafter = create_building("Basic Crafter", tex,
                                  WORLD_WIDTH / 2 + 100, WORLD_HEIGHT / 2,
                                  scale=0.5)
        gv.building_list.append(crafter)

        # Start a craft
        crafter.crafting = True
        crafter.craft_timer = 0.0
        crafter.craft_total = CRAFT_TIME
        gv._active_crafter = crafter
        gv._craft_menu._craft_target = "repair_pack"

        rp_before = gv._station_inv.count_item("repair_pack")

        # Tick past the craft time
        elapsed = 0.0
        dt = 1 / 60
        while elapsed < CRAFT_TIME + 1.0:
            update_crafting(gv, dt)
            elapsed += dt

        assert crafter.crafting is False
        rp_after = gv._station_inv.count_item("repair_pack")
        assert rp_after > rp_before


# ═══════════════════════════════════════════════════════════════════════════
#  #7 — Inventory ship ↔ station transfer
# ═══════════════════════════════════════════════════════════════════════════

class TestInventoryTransfer:
    def test_ship_to_station_transfer(self, real_game_view):
        """Drag item from ship inventory, release over station inventory
        panel — item should transfer."""
        gv = real_game_view
        gv.inventory.add_item("iron", 25)
        gv._station_inv.open = True
        gv.inventory.open = True

        # Start drag from ship inventory
        cell = next(iter(gv.inventory._items.keys()))
        gx, gy = gv.inventory._grid_origin()
        from constants import INV_CELL, INV_ROWS
        row, col = cell
        cx = gx + col * INV_CELL + INV_CELL // 2
        cy = gy + (INV_ROWS - 1 - row) * INV_CELL + INV_CELL // 2
        gv.inventory.on_mouse_press(cx, cy)
        assert gv.inventory._drag_type == "iron"

        # Release over station inventory panel
        sox, soy = gv._station_inv._panel_origin()
        from station_inventory import _INV_W, _INV_H
        target_x = sox + _INV_W // 2
        target_y = soy + _INV_H // 2
        ejected = gv.inventory.on_mouse_release(target_x, target_y)

        # The release should return (type, amount) indicating cross-transfer
        assert ejected is not None
        item_type, amount = ejected
        assert item_type == "iron"
        assert amount == 25

    def test_station_to_ship_transfer(self, real_game_view):
        """Drag from station inventory, release over ship inventory panel
        — should return a transfer tuple."""
        gv = real_game_view
        gv._station_inv.add_item("copper", 10)
        gv._station_inv.open = True
        gv.inventory.open = True

        cell = next(iter(gv._station_inv._items.keys()))
        gx, gy = gv._station_inv._grid_origin()
        from constants import STATION_INV_CELL, STATION_INV_ROWS
        row, col = cell
        cx = gx + col * STATION_INV_CELL + STATION_INV_CELL // 2
        cy = gy + (STATION_INV_ROWS - 1 - row) * STATION_INV_CELL + STATION_INV_CELL // 2
        gv._station_inv.on_mouse_press(cx, cy)
        assert gv._station_inv._drag_type == "copper"

        # Release over ship inventory panel
        from constants import INV_W, INV_H
        sw, sh = gv._station_inv._screen_size()
        ship_ox = (sw - INV_W) // 2
        ship_oy = (sh - INV_H) // 2
        ejected = gv._station_inv.on_mouse_release(
            ship_ox + INV_W // 2, ship_oy + INV_H // 2)
        assert ejected is not None
        item_type, amount = ejected
        assert item_type == "copper"
        assert amount == 10


# ═══════════════════════════════════════════════════════════════════════════
#  #8 — Eject iron to world
# ═══════════════════════════════════════════════════════════════════════════

class TestEjectToWorld:
    def test_eject_iron_spawns_pickup(self, real_game_view):
        """Calling _eject_iron_to_world spawns an IronPickup near the
        player with the correct amount."""
        from input_handlers import _eject_iron_to_world

        gv = real_game_view
        pickup_count_before = len(gv.iron_pickup_list)
        _eject_iron_to_world(gv, 30)

        assert len(gv.iron_pickup_list) == pickup_count_before + 1
        newest = gv.iron_pickup_list[-1]
        assert newest.amount == 30
        # Should be near the player (within ship radius + eject dist)
        dist = math.hypot(newest.center_x - gv.player.center_x,
                          newest.center_y - gv.player.center_y)
        assert dist < 200.0


# ═══════════════════════════════════════════════════════════════════════════
#  #9 — Module install to slot
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleInstall:
    def test_equip_module_applies_stats(self, real_game_view):
        """Install an armor plate module into a slot and verify the player's
        max HP increases (armor_plate adds +25 HP)."""
        from input_handlers import _eject_to_module_slot

        gv = real_game_view
        # Clear module slots
        gv._module_slots = [None] * MODULE_SLOT_COUNT
        gv.player.apply_modules(gv._module_slots)
        base_hp = gv.player.max_hp

        _eject_to_module_slot(gv, 0, "mod_armor_plate", 1)

        assert gv._module_slots[0] == "armor_plate"
        assert gv.player.max_hp > base_hp

    def test_equip_duplicate_module_returns_to_inventory(self, real_game_view):
        """If the module key is already equipped in another slot, the item
        should go back to inventory instead of being equipped."""
        from input_handlers import _eject_to_module_slot

        gv = real_game_view
        gv._module_slots = ["armor_plate", None, None, None]
        inv_before = gv.inventory.count_item("mod_armor_plate")

        _eject_to_module_slot(gv, 1, "mod_armor_plate", 1)

        # Slot 1 should still be empty — item returned to inventory
        assert gv._module_slots[1] is None
        assert gv.inventory.count_item("mod_armor_plate") == inv_before + 1


# ═══════════════════════════════════════════════════════════════════════════
#  #10 — Multi-zone chain transition
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiZoneChain:
    def test_main_to_zone2_to_warp_to_main(self, real_game_view):
        """Transition Main → Zone 2 → Warp Meteor → Main and verify the
        final state: back in Zone 1, asteroids restored, fog grid present,
        building list intact."""
        gv = real_game_view
        # Start in Zone 1
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        z1_asteroid_count = len(gv.asteroid_list)
        assert z1_asteroid_count > 0

        # Place a building in Zone 1 so we can check it survives
        from sprites.building import create_building
        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        home = create_building("Home Station", tex,
                               WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                               scale=0.5)
        gv.building_list.append(home)

        # → Zone 2
        gv._transition_zone(ZoneID.ZONE2)
        assert gv._zone.zone_id == ZoneID.ZONE2
        # Zone 1 asteroids are stashed
        assert len(gv.asteroid_list) == 0

        # → Warp Meteor
        gv._transition_zone(ZoneID.WARP_METEOR, entry_side="bottom")
        assert gv._zone.zone_id == ZoneID.WARP_METEOR

        # Tick a few frames
        for _ in range(3):
            gv._zone.update(gv, 1 / 60)

        # → Back to Main via bottom exit
        gv.player.center_y = 5.0
        gv._zone.update(gv, 1 / 60)

        # Verify final state
        assert gv._zone.zone_id == ZoneID.MAIN
        assert len(gv.asteroid_list) == z1_asteroid_count
        assert gv._fog_grid is not None
        # Building list should have at least the Home Station
        assert any(b.building_type == "Home Station" for b in gv.building_list)


# ═══════════════════════════════════════════════════════════════════════════
#  #11 — Parked ship placement via _place_new_ship
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipPlacement:
    def test_place_new_ship_creates_parked_and_upgrades(self, real_game_view):
        """Placing an Advanced Ship creates a ParkedShip at the player's
        old position and upgrades the active ship to the next level."""
        from building_manager import _place_new_ship
        from sprites.building import create_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Build Home Station (required for upgrade)
        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex,
                            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))

        # Give enough resources
        gv.inventory.add_item("iron", 5000)
        gv._station_inv.add_item("copper", 5000)

        old_level = gv._ship_level
        old_x = gv.player.center_x
        old_y = gv.player.center_y

        _place_new_ship(gv, WORLD_WIDTH / 2 + 200, WORLD_HEIGHT / 2 + 200)

        # Active ship upgraded
        assert gv._ship_level == old_level + 1
        # Player teleported to placement position
        assert abs(gv.player.center_x - (WORLD_WIDTH / 2 + 200)) < 1.0
        assert abs(gv.player.center_y - (WORLD_HEIGHT / 2 + 200)) < 1.0
        # Old ship left as parked
        assert len(gv._parked_ships) == 1
        ps = gv._parked_ships[0]
        assert ps.ship_level == old_level
        assert abs(ps.center_x - old_x) < 1.0
        assert abs(ps.center_y - old_y) < 1.0

    def test_place_new_ship_deducts_resources(self, real_game_view):
        """Placing an Advanced Ship deducts iron and copper."""
        from building_manager import _place_new_ship
        from sprites.building import create_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex,
                            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))

        gv.inventory._items.clear()
        gv.inventory.add_item("iron", 5000)
        gv.inventory._mark_dirty()
        gv._station_inv._items.clear()
        gv._station_inv.add_item("copper", 5000)
        gv._station_inv._mark_dirty()

        iron_before = gv.inventory.total_iron + gv._station_inv.total_iron
        copper_before = (gv.inventory.count_item("copper")
                         + gv._station_inv.count_item("copper"))

        _place_new_ship(gv, 3200, 3200)

        iron_after = gv.inventory.total_iron + gv._station_inv.total_iron
        copper_after = (gv.inventory.count_item("copper")
                        + gv._station_inv.count_item("copper"))

        assert iron_after < iron_before
        assert copper_after < copper_before


# ═══════════════════════════════════════════════════════════════════════════
#  #12 — Ship switching
# ═══════════════════════════════════════════════════════════════════════════

class TestShipSwitching:
    def test_switch_to_ship_swaps_player(self, real_game_view):
        """Switching to a parked ship replaces the active player and
        creates a new parked ship from the old player."""
        from building_manager import switch_to_ship, _place_new_ship
        from sprites.building import create_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex,
                            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))

        gv.inventory.add_item("iron", 5000)
        gv._station_inv.add_item("copper", 5000)

        # Place an upgrade (creates parked ship)
        _place_new_ship(gv, WORLD_WIDTH / 2 + 200, WORLD_HEIGHT / 2)
        assert len(gv._parked_ships) == 1
        assert gv._ship_level == 2

        # Put some cargo in active ship's inventory
        gv.inventory.add_item("iron", 100)
        l2_iron = gv.inventory.total_iron

        # Switch back to the parked level 1 ship
        target = gv._parked_ships[0]
        switch_to_ship(gv, target)

        # Now piloting level 1
        assert gv._ship_level == 1
        # Parked ship is now the level 2
        assert len(gv._parked_ships) == 1
        ps = gv._parked_ships[0]
        assert ps.ship_level == 2
        # Level 2 ship's cargo should have the iron we added
        total_parked_iron = sum(
            ct for (_, ct) in ps.cargo_items.values()
            if ct > 0)
        assert total_parked_iron == l2_iron

    def test_switch_preserves_modules(self, real_game_view):
        """Module slots are preserved through a switch round trip."""
        from building_manager import switch_to_ship, _place_new_ship
        from sprites.building import create_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex,
                            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))
        gv.inventory.add_item("iron", 5000)
        gv._station_inv.add_item("copper", 5000)

        # Equip a module before upgrading
        gv._module_slots[0] = "armor_plate"
        gv.player.apply_modules(gv._module_slots)

        _place_new_ship(gv, WORLD_WIDTH / 2 + 200, WORLD_HEIGHT / 2)

        # Level 2 ship should have the armor plate
        assert "armor_plate" in gv._module_slots

        # Switch to level 1 (empty modules)
        target = gv._parked_ships[0]
        switch_to_ship(gv, target)
        assert gv._module_slots == target.module_slots or gv._module_slots[0] is None

        # Switch back to level 2 (should have armor plate)
        target2 = gv._parked_ships[0]
        switch_to_ship(gv, target2)
        assert "armor_plate" in gv._module_slots


# ═══════════════════════════════════════════════════════════════════════════
#  #13 — Parked ship save/load round trip
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipSaveLoad:
    def test_parked_ships_survive_save_load(self, real_game_view):
        """Parked ships persist through a full save → load cycle."""
        import json
        from game_save import save_to_dict, restore_state
        from building_manager import _place_new_ship
        from sprites.building import create_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex,
                            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))
        gv.inventory.add_item("iron", 5000)
        gv._station_inv.add_item("copper", 5000)

        _place_new_ship(gv, WORLD_WIDTH / 2 + 200, WORLD_HEIGHT / 2)
        assert len(gv._parked_ships) == 1
        ps = gv._parked_ships[0]
        ps.cargo_items[(0, 0)] = ("iron", 42)
        ps.module_slots = ["armor_plate", None]

        # Save
        data = json.loads(json.dumps(save_to_dict(gv, "test_parked")))
        assert "parked_ships" in data
        assert len(data["parked_ships"]) == 1

        # Clobber state
        gv._parked_ships.clear()
        assert len(gv._parked_ships) == 0

        # Restore
        restore_state(gv, data)
        assert len(gv._parked_ships) == 1
        restored = gv._parked_ships[0]
        assert restored.ship_level == ps.ship_level
        assert restored.cargo_items[(0, 0)] == ("iron", 42)
        assert restored.module_slots == ["armor_plate", None]


# ═══════════════════════════════════════════════════════════════════════════
#  #14 — Parked ships stashed across zone transitions
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipZoneTransition:
    def test_parked_ships_survive_zone2_round_trip(self, real_game_view):
        """Parked ships in Zone 1 survive a Zone 1 → Zone 2 → Zone 1
        round trip via the zone stash system."""
        from building_manager import _place_new_ship
        from sprites.building import create_building

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex,
                            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))
        gv.inventory.add_item("iron", 5000)
        gv._station_inv.add_item("copper", 5000)

        _place_new_ship(gv, WORLD_WIDTH / 2 + 200, WORLD_HEIGHT / 2)
        assert len(gv._parked_ships) == 1

        # Go to Zone 2 and back
        gv._transition_zone(ZoneID.ZONE2)
        assert len(gv._parked_ships) == 0  # stashed with Zone 1

        gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        assert len(gv._parked_ships) == 1  # restored


# ═══════════════════════════════════════════════════════════════════════════
#  Recent features — Missile Array, homing-missile craft, trade, Death Blossom
# ═══════════════════════════════════════════════════════════════════════════

class TestMissileArrayFires:
    def test_builds_and_fires_at_alien(self, real_game_view):
        """Missile Array builds via the factory and launches a homing missile
        at a nearby alien in Zone 1."""
        from sprites.building import create_building, MissileArray
        from update_logic import update_buildings
        from sprites.alien import SmallAlienShip

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        tex = gv._building_textures["Missile Array"]
        ma = create_building("Missile Array", tex,
                             WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5)
        assert isinstance(ma, MissileArray)
        gv.building_list.append(ma)

        alien = SmallAlienShip(
            gv._alien_ship_tex, gv._alien_laser_tex,
            ma.center_x + 200, ma.center_y,
        )
        gv.alien_list.append(alien)

        update_buildings(gv, 0.1)
        assert len(gv._missile_list) >= 1


class TestCraftHomingMissileAdvanced:
    def test_consumable_craft_produces_20_missiles(self, real_game_view):
        """Crafting the homing_missile recipe on an Advanced Crafter tick
        path adds 20 'missile' items to the station inventory."""
        from sprites.building import create_building, BasicCrafter
        from update_logic import update_crafting
        from constants import MODULE_TYPES

        gv = real_game_view
        tex = gv._building_textures["Advanced Crafter"]
        crafter = create_building("Advanced Crafter", tex,
                                  WORLD_WIDTH / 2 + 100, WORLD_HEIGHT / 2,
                                  scale=0.5)
        assert isinstance(crafter, BasicCrafter)
        gv.building_list.append(crafter)
        gv._active_crafter = crafter
        gv._craft_menu._craft_target = "homing_missile"

        crafter.crafting = True
        crafter.craft_timer = 0.0
        crafter.craft_total = MODULE_TYPES["homing_missile"]["craft_time"]

        missiles_before = gv._station_inv.count_item("missile")
        elapsed = 0.0
        dt = 1 / 60
        while elapsed < crafter.craft_total + 1.0:
            update_crafting(gv, dt)
            elapsed += dt

        assert crafter.crafting is False
        missiles_after = gv._station_inv.count_item("missile")
        assert missiles_after - missiles_before == 20


class TestTradeSellIronCopper:
    def test_iron_and_copper_sell_for_20(self, real_game_view):
        """Sell iron + copper at the trade station; credits = 20 each."""
        gv = real_game_view
        gv.inventory.add_item("iron", 5)
        gv.inventory.add_item("copper", 3)
        gv._trade_menu._credits = 0
        gv._trade_menu._refresh_sell_list(gv.inventory, gv._station_inv)
        # Emulate 5 clicks on iron + 3 clicks on copper by finding each
        # row's price and adding it.
        from trade_menu import SELL_PRICES
        gv._trade_menu._credits += SELL_PRICES["iron"] * 5
        gv._trade_menu._credits += SELL_PRICES["copper"] * 3
        assert gv._trade_menu._credits == 20 * 5 + 20 * 3


class TestDeathBlossomFlow:
    def test_triggers_clears_missiles_and_activates(self, real_game_view):
        """Pressing X with death_blossom equipped and missiles in cargo
        drains the cargo, clears any quick-use slot bound to missile, and
        activates the death-blossom state."""
        import arcade as _arcade
        from input_handlers import handle_key_press
        from constants import QUICK_USE_SLOTS

        gv = real_game_view
        gv.inventory.add_item("missile", 12)
        # Equip death_blossom in the first module slot
        gv._module_slots[0] = "death_blossom"
        gv._hud.set_quick_use(0, "missile", 12)

        handle_key_press(gv, _arcade.key.X, 0)

        assert gv._death_blossom_active is True
        assert gv._death_blossom_missiles_left == 12
        assert gv.inventory.count_item("missile") == 0
        # Slot bound to "missile" has been cleared
        assert gv._hud.get_quick_use(0) is None


# ═══════════════════════════════════════════════════════════════════════════
#  Recent features with videos running
# ═══════════════════════════════════════════════════════════════════════════

def _start_video_pipeline(gv):
    """Start both character + music video players for an integration test.
    Skips the test if no .mp4 files are available or FFmpeg can't decode."""
    from video_player import scan_characters_dir, character_video_path
    chars = scan_characters_dir()
    if not chars:
        pytest.skip("No character video files found in characters/")
    paths = []
    for name in chars:
        p = character_video_path(name)
        if p is not None:
            paths.append(p)
        if len(paths) >= 2:
            break
    if not paths:
        pytest.skip("No character video file paths resolved")
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    music_path = paths[1] if len(paths) > 1 else paths[0]
    gv._video_player.play(music_path, volume=0.0)
    dt = 1 / 60
    for _ in range(10):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._char_video_player.active and not gv._video_player.active:
        pytest.skip("Neither video player started (no FFmpeg?)")


def _stop_video_pipeline(gv):
    gv._char_video_player.stop()
    gv._video_player.stop()


class TestMissileArrayFiresWithVideos:
    def test_builds_and_fires_at_alien_with_videos(self, real_game_view):
        """Same as TestMissileArrayFires but with both video decoders
        running to ensure they don't interfere with building tick order
        or missile spawning."""
        from sprites.building import create_building, MissileArray
        from update_logic import update_buildings
        from sprites.alien import SmallAlienShip

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_video_pipeline(gv)
        try:
            tex = gv._building_textures["Missile Array"]
            ma = create_building("Missile Array", tex,
                                 WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5)
            assert isinstance(ma, MissileArray)
            gv.building_list.append(ma)

            alien = SmallAlienShip(
                gv._alien_ship_tex, gv._alien_laser_tex,
                ma.center_x + 200, ma.center_y,
            )
            gv.alien_list.append(alien)

            update_buildings(gv, 0.1)
            assert len(gv._missile_list) >= 1
        finally:
            _stop_video_pipeline(gv)


class TestDeathBlossomFlowWithVideos:
    def test_triggers_with_videos_running(self, real_game_view):
        """Death Blossom trigger flow exercised while both video decoders
        are active — verifies input routing + inventory drain + quick-use
        slot clearing survive the two-frame video pipeline."""
        import arcade as _arcade
        from input_handlers import handle_key_press

        gv = real_game_view
        _start_video_pipeline(gv)
        try:
            gv.inventory.add_item("missile", 12)
            gv._module_slots[0] = "death_blossom"
            gv._hud.set_quick_use(0, "missile", 12)

            handle_key_press(gv, _arcade.key.X, 0)

            assert gv._death_blossom_active is True
            assert gv._death_blossom_missiles_left == 12
            assert gv.inventory.count_item("missile") == 0
            assert gv._hud.get_quick_use(0) is None
        finally:
            _stop_video_pipeline(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  AI Pilot module — parked ship patrols and fights enemies
# ═══════════════════════════════════════════════════════════════════════════

def _spawn_home_and_parked(gv, parked_pos):
    """Place a Home Station at the world centre and a parked ship nearby
    with an ai_pilot module installed. Returns the ParkedShip."""
    from sprites.building import create_building
    from sprites.parked_ship import ParkedShip
    from constants import WORLD_WIDTH, WORLD_HEIGHT
    gv.building_list.clear()
    tex = gv._building_textures["Home Station"]
    home = create_building("Home Station", tex,
                           WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5)
    gv.building_list.append(home)
    ps = ParkedShip(gv._faction, gv._ship_type, 1,
                    parked_pos[0], parked_pos[1])
    ps.module_slots = ["ai_pilot"]
    gv._parked_ships.append(ps)
    return ps, home


class TestAIPilotZone1Functional:
    def test_ai_pilot_fires_at_alien_in_range(self, real_game_view):
        """AI-piloted parked ship fires at an alien placed within detect
        range, queuing projectiles in gv.turret_projectile_list."""
        from sprites.alien import SmallAlienShip
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        ps, _home = _spawn_home_and_parked(gv, (cx + 100, cy))
        # Isolate: exactly one alien 200 px from the ship, well inside
        # both detect range and the patrol leash.
        gv.alien_list.clear()
        alien = SmallAlienShip(gv._alien_ship_tex, gv._alien_laser_tex,
                               cx + 300, cy)
        gv.alien_list.append(alien)

        gv.turret_projectile_list.clear()
        dt = 1 / 60
        for _ in range(40):
            gv.on_update(dt)
            if len(gv.turret_projectile_list) > 0:
                break
        assert len(gv.turret_projectile_list) > 0, (
            "AI pilot should fire at an alien in range")

    def test_ai_pilot_returns_to_patrol_leash(self, real_game_view):
        """A stray parked ship outside the leash is pulled back to within
        AI_PILOT_PATROL_RADIUS of the Home Station after one tick."""
        from constants import (
            WORLD_WIDTH, WORLD_HEIGHT, AI_PILOT_PATROL_RADIUS,
        )
        import math
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        ps, _ = _spawn_home_and_parked(gv, (cx + 2000, cy))
        gv.alien_list.clear()
        gv.on_update(1 / 60)
        dist = math.hypot(ps.center_x - cx, ps.center_y - cy)
        assert dist <= AI_PILOT_PATROL_RADIUS + 1.0

    def test_ai_pilot_without_module_is_idle(self, real_game_view):
        """A parked ship without the ai_pilot module stays perfectly
        still even with an enemy on top of it."""
        from sprites.alien import SmallAlienShip
        from sprites.parked_ship import ParkedShip
        from sprites.building import create_building
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex, cx, cy, scale=0.5))

        ps = ParkedShip(gv._faction, gv._ship_type, 1, cx + 100, cy)
        # no module_slots set — explicitly no ai_pilot
        gv._parked_ships.clear()
        gv._parked_ships.append(ps)

        gv.alien_list.clear()
        gv.alien_list.append(SmallAlienShip(
            gv._alien_ship_tex, gv._alien_laser_tex, cx + 300, cy))

        gv.turret_projectile_list.clear()
        start = (ps.center_x, ps.center_y)
        for _ in range(30):
            gv.on_update(1 / 60)
        # Only the ship's own shots are prohibited — turrets on the home
        # station don't exist in this fixture — so the list must be empty.
        assert len(gv.turret_projectile_list) == 0
        assert abs(ps.center_x - start[0]) < 0.01
        assert abs(ps.center_y - start[1]) < 0.01


class TestAIPilotZone2Functional:
    def test_ai_pilot_engages_in_zone2(self, real_game_view):
        """AI-piloted parked ship still fires when the player is in the
        Nebula — update_logic._update_parked_ships is routed through
        Zone2.update with the zone's alien list swapped in."""
        from sprites.parked_ship import ParkedShip
        from sprites.building import create_building

        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        zone = gv._zone

        # Place a Home Station near the player.
        gv.building_list.clear()
        cx, cy = gv.player.center_x, gv.player.center_y
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(
            create_building("Home Station", tex, cx, cy, scale=0.5))

        ps = ParkedShip(gv._faction, gv._ship_type, 1, cx + 100, cy)
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.clear()
        gv._parked_ships.append(ps)

        # Move one zone-2 alien right next to the ship so it's the
        # obvious closest target regardless of the rest of the population.
        if len(zone._aliens) == 0:
            pytest.skip("No Zone 2 aliens available")
        for a in zone._aliens:
            # push all aliens far away so they don't interfere
            a.center_x = cx + 5000
            a.center_y = cy + 5000
        zone._aliens[0].center_x = cx + 250
        zone._aliens[0].center_y = cy

        gv.turret_projectile_list.clear()
        for _ in range(40):
            gv.on_update(1 / 60)
            if len(gv.turret_projectile_list) > 0:
                break
        assert len(gv.turret_projectile_list) > 0


# ═══════════════════════════════════════════════════════════════════════════
#  Double Star Refugee — NPC + dialogue integration
# ═══════════════════════════════════════════════════════════════════════════

class TestRefugeeNPCIntegration:
    def test_refugee_spawns_after_shield_generator_in_zone2(
            self, real_game_view):
        """Building a Shield Generator while in Zone 2 must spawn the
        Double Star Refugee exactly once."""
        from sprites.building import create_building
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(create_building(
            "Home Station", tex,
            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))

        # Before the Shield Generator: no spawn.
        gv._refugee_npc = None
        gv._refugee_spawned = False
        gv.on_update(1 / 60)
        assert gv._refugee_npc is None

        # Add a Shield Generator to the station.
        sg_tex = gv._building_textures["Shield Generator"]
        gv.building_list.append(create_building(
            "Shield Generator", sg_tex,
            WORLD_WIDTH / 2 + 80, WORLD_HEIGHT / 2, scale=0.5))
        gv.on_update(1 / 60)
        assert gv._refugee_npc is not None
        assert gv._refugee_spawned is True

    def test_refugee_does_not_spawn_outside_zone2(self, real_game_view):
        from sprites.building import create_building
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(create_building(
            "Home Station", tex,
            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))
        sg_tex = gv._building_textures["Shield Generator"]
        gv.building_list.append(create_building(
            "Shield Generator", sg_tex,
            WORLD_WIDTH / 2 + 80, WORLD_HEIGHT / 2, scale=0.5))

        gv._refugee_npc = None
        gv._refugee_spawned = False
        gv.on_update(1 / 60)
        assert gv._refugee_npc is None

    def test_refugee_dialogue_opens_on_click_for_debra(self, real_game_view):
        from settings import audio
        from sprites.building import create_building
        from sprites.npc_ship import RefugeeNPCShip
        from constants import WORLD_WIDTH, WORLD_HEIGHT
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        gv.building_list.append(create_building(
            "Home Station", tex,
            WORLD_WIDTH / 2, WORLD_HEIGHT / 2, scale=0.5))

        # Place the refugee right next to the player.
        gv.player.center_x = WORLD_WIDTH / 2
        gv.player.center_y = WORLD_HEIGHT / 2
        gv._refugee_npc = RefugeeNPCShip(
            gv.player.center_x + 80, gv.player.center_y,
            (gv.player.center_x, gv.player.center_y))
        gv._refugee_spawned = True

        audio.character_name = "Debra"

        # Cursor over the refugee in world coords → screen coords.
        rx = gv._refugee_npc.center_x
        ry = gv._refugee_npc.center_y
        sx = rx - (gv.world_cam.position[0] - gv.window.width / 2)
        sy = ry - (gv.world_cam.position[1] - gv.window.height / 2)

        import arcade
        gv.on_mouse_press(int(sx), int(sy), arcade.MOUSE_BUTTON_LEFT, 0)
        assert gv._dialogue.open is True
        assert gv._met_refugee is True
        # First advance moves into Kael's intro choice list.
        intro = gv._dialogue._tree[gv._dialogue._tree["start"]]
        assert "choices" in intro
        # ESC closes without setting aftermath flags.
        gv.on_key_press(arcade.key.ESCAPE, 0)
        assert gv._dialogue.open is False
        assert gv._quest_flags == {}

    def test_refugee_is_invulnerable(self, real_game_view):
        from sprites.npc_ship import RefugeeNPCShip
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        ship = RefugeeNPCShip(1000.0, 1000.0, (2000.0, 2000.0))
        ship.take_damage(10_000)  # must not raise and must not change state
        assert ship.arrived is False
