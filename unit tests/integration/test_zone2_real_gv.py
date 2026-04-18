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

    def test_refugee_dialogue_opens_on_click_for_ellie(self, real_game_view):
        """Clicking the refugee as Ellie opens the full Kratos arc
        (intro has choices, not a one-shot end node)."""
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

        gv.player.center_x = WORLD_WIDTH / 2
        gv.player.center_y = WORLD_HEIGHT / 2
        gv._refugee_npc = RefugeeNPCShip(
            gv.player.center_x + 80, gv.player.center_y,
            (gv.player.center_x, gv.player.center_y))
        gv._refugee_spawned = True

        audio.character_name = "Ellie"

        rx = gv._refugee_npc.center_x
        ry = gv._refugee_npc.center_y
        sx = rx - (gv.world_cam.position[0] - gv.window.width / 2)
        sy = ry - (gv.world_cam.position[1] - gv.window.height / 2)

        import arcade
        gv.on_mouse_press(int(sx), int(sy), arcade.MOUSE_BUTTON_LEFT, 0)
        assert gv._dialogue.open is True
        assert gv._met_refugee is True
        intro = gv._dialogue._tree[gv._dialogue._tree["start"]]
        # Ellie now has a full branching tree like Debra — not a stub.
        assert "choices" in intro
        assert len(intro["choices"]) >= 3

    def test_ellie_dialogue_full_walk_sets_kratos_quest(
            self, real_game_view):
        """Walking Ellie's tree to the shared ending must merge the
        Kratos-quest aftermath flags into gv._quest_flags."""
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
        gv.player.center_x = WORLD_WIDTH / 2
        gv.player.center_y = WORLD_HEIGHT / 2
        gv._refugee_npc = RefugeeNPCShip(
            gv.player.center_x + 80, gv.player.center_y,
            (gv.player.center_x, gv.player.center_y))
        gv._refugee_spawned = True
        audio.character_name = "Ellie"

        rx = gv._refugee_npc.center_x
        ry = gv._refugee_npc.center_y
        sx = rx - (gv.world_cam.position[0] - gv.window.width / 2)
        sy = ry - (gv.world_cam.position[1] - gv.window.height / 2)
        import arcade
        gv.on_mouse_press(int(sx), int(sy), arcade.MOUSE_BUTTON_LEFT, 0)

        # Walk the first-choice spine to the shared `ending` node.
        for _ in range(200):
            if not gv._dialogue.open:
                break
            node = gv._dialogue._current_node()
            if node is None:
                gv._dialogue.close()
                break
            if node.get("choices"):
                gv._dialogue._pick(0)
            else:
                gv._dialogue._advance()
        assert gv._dialogue.open is False
        assert gv._quest_flags.get("ellie_quest_dismantle_kratos") is True

    def test_refugee_dialogue_opens_on_click_for_tara(self, real_game_view):
        """Clicking the refugee as Tara opens the full Dead Zone arc
        (intro is linear into a 3-choice branch at s1_4)."""
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

        gv.player.center_x = WORLD_WIDTH / 2
        gv.player.center_y = WORLD_HEIGHT / 2
        gv._refugee_npc = RefugeeNPCShip(
            gv.player.center_x + 80, gv.player.center_y,
            (gv.player.center_x, gv.player.center_y))
        gv._refugee_spawned = True

        audio.character_name = "Tara"

        rx = gv._refugee_npc.center_x
        ry = gv._refugee_npc.center_y
        sx = rx - (gv.world_cam.position[0] - gv.window.width / 2)
        sy = ry - (gv.world_cam.position[1] - gv.window.height / 2)

        import arcade
        gv.on_mouse_press(int(sx), int(sy), arcade.MOUSE_BUTTON_LEFT, 0)
        assert gv._dialogue.open is True
        assert gv._met_refugee is True
        # Tara's tree opens linear (speaker-intro + a few beats), then
        # hits `s1_4` with 3 choices. Advance until we see the branch.
        saw_choices = False
        for _ in range(10):
            if not gv._dialogue.open:
                break
            node = gv._dialogue._current_node()
            if node is None:
                break
            if node.get("choices"):
                saw_choices = len(node["choices"]) >= 3
                break
            gv._dialogue._advance()
        assert saw_choices, (
            "Tara's tree should reach a 3-choice branch within the intro")

    def test_tara_dialogue_full_walk_sets_dead_zone_quest(
            self, real_game_view):
        """Walking Tara's tree to the shared ending must merge the
        Dead Zone aftermath flags into gv._quest_flags."""
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
        gv.player.center_x = WORLD_WIDTH / 2
        gv.player.center_y = WORLD_HEIGHT / 2
        gv._refugee_npc = RefugeeNPCShip(
            gv.player.center_x + 80, gv.player.center_y,
            (gv.player.center_x, gv.player.center_y))
        gv._refugee_spawned = True
        audio.character_name = "Tara"

        rx = gv._refugee_npc.center_x
        ry = gv._refugee_npc.center_y
        sx = rx - (gv.world_cam.position[0] - gv.window.width / 2)
        sy = ry - (gv.world_cam.position[1] - gv.window.height / 2)
        import arcade
        gv.on_mouse_press(int(sx), int(sy), arcade.MOUSE_BUTTON_LEFT, 0)

        for _ in range(300):
            if not gv._dialogue.open:
                break
            node = gv._dialogue._current_node()
            if node is None:
                gv._dialogue.close()
                break
            if node.get("choices"):
                gv._dialogue._pick(0)
            else:
                gv._dialogue._advance()
        assert gv._dialogue.open is False
        assert gv._quest_flags.get("tara_quest_dead_zone") is True

    def test_refugee_is_invulnerable(self, real_game_view):
        from sprites.npc_ship import RefugeeNPCShip
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        ship = RefugeeNPCShip(1000.0, 1000.0, (2000.0, 2000.0))
        ship.take_damage(10_000)  # must not raise and must not change state
        assert ship.arrived is False


# ═══════════════════════════════════════════════════════════════════════════
#  AI Pilot patrol / return behaviour (real GameView)
# ═══════════════════════════════════════════════════════════════════════════

def _setup_ai_parked(gv, zone):
    """Zone + Home Station + single AI-piloted parked ship near home."""
    from sprites.building import create_building
    from sprites.parked_ship import ParkedShip
    from constants import WORLD_WIDTH, WORLD_HEIGHT
    if zone == ZoneID.MAIN:
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
    else:
        gv._transition_zone(zone)
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", tex, cx, cy, scale=0.5))
    ps = ParkedShip(gv._faction, gv._ship_type, 1, cx + 200, cy)
    ps.module_slots = ["ai_pilot"]
    gv._parked_ships.clear()
    gv._parked_ships.append(ps)
    return ps, (cx, cy)


class TestAIPilotPatrolIntegration:
    def test_idle_ship_circles_the_home_station(self, real_game_view):
        """With no aliens nearby, the AI ship's angle relative to the
        Home Station should change over time — i.e. it orbits instead
        of parking. Radius stays within the patrol leash."""
        import math
        from constants import AI_PILOT_PATROL_RADIUS
        gv = real_game_view
        ps, (hx, hy) = _setup_ai_parked(gv, ZoneID.MAIN)
        # Clear aliens so the AI has nothing to shoot.
        gv.alien_list.clear()
        a0 = math.atan2(ps.center_y - hy, ps.center_x - hx)
        for _ in range(60):  # 1 second of sim
            gv.on_update(1 / 60)
        a1 = math.atan2(ps.center_y - hy, ps.center_x - hx)
        r = math.hypot(ps.center_x - hx, ps.center_y - hy)
        assert a1 != a0, "AI ship should sweep the home-station angle"
        assert r <= AI_PILOT_PATROL_RADIUS + 1.0

    def test_ship_returns_to_base_after_firing_sole_target(
            self, real_game_view):
        """Put a lone alien in range, run the sim, then remove it. The
        AI pilot should flip to ``return`` after firing and the ship's
        distance to home should shrink over subsequent ticks."""
        import math
        from sprites.alien import SmallAlienShip
        gv = real_game_view
        ps, (hx, hy) = _setup_ai_parked(gv, ZoneID.MAIN)
        ps.center_x = hx + 200
        ps.center_y = hy
        gv.alien_list.clear()
        alien = SmallAlienShip(gv._alien_ship_tex, gv._alien_laser_tex,
                               ps.center_x + 180, ps.center_y)
        gv.alien_list.append(alien)

        gv.turret_projectile_list.clear()
        fired_flag = False
        for _ in range(60):
            gv.on_update(1 / 60)
            if len(gv.turret_projectile_list) > 0:
                fired_flag = True
                break
        assert fired_flag, "AI pilot must fire at a lone target"
        # Clear remaining aliens so return-mode can run uninterrupted.
        gv.alien_list.clear()
        assert ps._ai_mode == "return"
        d0 = math.hypot(ps.center_x - hx, ps.center_y - hy)
        for _ in range(30):  # 0.5 s of return-mode flight
            gv.on_update(1 / 60)
        d1 = math.hypot(ps.center_x - hx, ps.center_y - hy)
        assert d1 < d0 - 5.0, "Ship should close on the Home Station"

    def test_ship_resumes_patrol_after_returning_home(self, real_game_view):
        """After the ship makes it back to base, running another second
        of sim should put it back into orbit (the angle should sweep)."""
        import math
        from sprites.alien import SmallAlienShip
        from constants import AI_PILOT_HOME_ARRIVAL_DIST
        gv = real_game_view
        ps, (hx, hy) = _setup_ai_parked(gv, ZoneID.MAIN)
        # Trigger one shot at a lone alien then remove it.
        gv.alien_list.clear()
        ps.center_x = hx + 150
        ps.center_y = hy
        alien = SmallAlienShip(gv._alien_ship_tex, gv._alien_laser_tex,
                               ps.center_x + 200, ps.center_y)
        gv.alien_list.append(alien)
        for _ in range(30):
            gv.on_update(1 / 60)
        gv.alien_list.clear()
        # Let return-mode finish — cap iterations so we don't loop forever.
        for _ in range(600):
            gv.on_update(1 / 60)
            if ps._ai_mode == "patrol":
                break
        assert ps._ai_mode == "patrol"
        a0 = math.atan2(ps.center_y - hy, ps.center_x - hx)
        for _ in range(60):
            gv.on_update(1 / 60)
        a1 = math.atan2(ps.center_y - hy, ps.center_x - hx)
        assert a1 != a0, "Patrol should sweep angle after resuming"


# ═══════════════════════════════════════════════════════════════════════════
#  Station shield + AI-pilot shield + refugee parking (real GameView)
# ═══════════════════════════════════════════════════════════════════════════

def _spawn_station(gv):
    from sprites.building import create_building
    from constants import WORLD_WIDTH, WORLD_HEIGHT
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    tex = gv._building_textures["Home Station"]
    gv.building_list.append(
        create_building("Home Station", tex, cx, cy, scale=0.5))
    # Park the player at the station so on_update doesn't accidentally
    # trigger a wormhole transition (wormhole spawns near center too).
    gv.player.center_x = cx
    gv.player.center_y = cy + 300
    return cx, cy


class TestStationShieldIntegration:
    def test_station_shield_spawns_on_shield_generator(self, real_game_view):
        from sprites.building import create_building
        from constants import STATION_SHIELD_HP
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        cx, cy = _spawn_station(gv)
        sg_tex = gv._building_textures["Shield Generator"]
        gv.building_list.append(create_building(
            "Shield Generator", sg_tex, cx + 80, cy, scale=0.5))
        # Reset shield state so the assertion is about the spawn.
        gv._station_shield_hp = 0
        gv._station_shield_sprite = None
        gv.on_update(1 / 60)
        assert gv._station_shield_sprite is not None
        assert gv._station_shield_hp == STATION_SHIELD_HP
        assert gv._station_shield_radius > 0.0

    def test_station_shield_absorbs_alien_laser(self, real_game_view):
        from sprites.building import create_building
        from sprites.projectile import Projectile
        from constants import ALIEN_LASER_SPEED, ALIEN_LASER_RANGE
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        cx, cy = _spawn_station(gv)
        sg_tex = gv._building_textures["Shield Generator"]
        gv.building_list.append(create_building(
            "Shield Generator", sg_tex, cx + 80, cy, scale=0.5))
        gv._station_shield_hp = 0
        gv._station_shield_sprite = None
        gv.on_update(1 / 60)  # spawns the shield
        start_hp = gv._station_shield_hp
        # Drop an alien projectile dead-centre on the shield.
        proj = Projectile(gv._alien_laser_tex, cx, cy, 0,
                          ALIEN_LASER_SPEED, ALIEN_LASER_RANGE, damage=10)
        gv.alien_projectile_list.append(proj)
        from collisions import handle_alien_laser_building_hits
        handle_alien_laser_building_hits(gv)
        assert gv._station_shield_hp == start_hp - 10
        assert len(gv.alien_projectile_list) == 0

    def test_station_shield_scales_with_outer_building(self, real_game_view):
        from sprites.building import create_building
        from constants import STATION_SHIELD_PADDING
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        cx, cy = _spawn_station(gv)
        sg_tex = gv._building_textures["Shield Generator"]
        # Place Shield Generator far from home to grow the radius.
        gv.building_list.append(create_building(
            "Shield Generator", sg_tex, cx + 250, cy, scale=0.5))
        gv._station_shield_hp = 0
        gv._station_shield_sprite = None
        gv.on_update(1 / 60)
        r = gv._station_shield_radius
        # Must be at least the Shield Generator's distance + padding.
        assert r >= 250.0 + STATION_SHIELD_PADDING - 1.0


class TestAIPilotShieldIntegration:
    def test_installed_ai_pilot_attaches_yellow_shield(self, real_game_view):
        from sprites.parked_ship import ParkedShip, _AI_SHIELD_TINT
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _spawn_station(gv)
        ps = ParkedShip(gv._faction, gv._ship_type, 1,
                        gv.player.center_x + 300, gv.player.center_y)
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.clear()
        gv._parked_ships.append(ps)
        # One tick must lazily materialise the yellow shield sprite.
        gv.on_update(1 / 60)
        assert ps._shield_sprite is not None
        assert ps._shield_sprite._tint == _AI_SHIELD_TINT


class TestRefugeeParkingIntegration:
    def test_refugee_parks_outside_all_buildings(self, real_game_view):
        from sprites.building import create_building
        import math
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        cx, cy = _spawn_station(gv)
        # Build an extended station so "outside" is non-trivial.
        sg_tex = gv._building_textures["Shield Generator"]
        gv.building_list.append(create_building(
            "Shield Generator", sg_tex, cx + 250, cy, scale=0.5))
        # Spawn the refugee.
        gv._refugee_npc = None
        gv._refugee_spawned = False
        gv.on_update(1 / 60)
        assert gv._refugee_npc is not None
        # Teleport the refugee close to the parking spot so the
        # integration test doesn't have to simulate the ~20 s cross-map
        # approach from the world edge.
        gv._refugee_npc.center_x = cx + gv._refugee_npc._hold_dist + 400.0
        gv._refugee_npc.center_y = cy
        for _ in range(300):
            gv.on_update(1 / 60)
            if gv._refugee_npc.arrived:
                break
        assert gv._refugee_npc.arrived
        rx, ry = gv._refugee_npc.center_x, gv._refugee_npc.center_y
        # Must not overlap any building (builds + turret-radius headroom).
        for b in gv.building_list:
            d = math.hypot(rx - b.center_x, ry - b.center_y)
            assert d > 60.0, (
                f"Refugee too close to {b.building_type} ({d:.1f} px)")


# ═══════════════════════════════════════════════════════════════════════════
#  Refactor regression — make sure the collision-helper + shared alien AI
#  path still produces damage through a real GameView tick.
# ═══════════════════════════════════════════════════════════════════════════

class TestRefactorRegression:
    def test_alien_laser_still_damages_player_via_shared_helper(
            self, real_game_view):
        """After the collision-cooldown helper refactor, a real alien
        laser hitting the player must still apply damage + shake +
        start the invincibility cooldown."""
        from sprites.projectile import Projectile
        from constants import ALIEN_LASER_SPEED, ALIEN_LASER_RANGE
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv.player.center_x, gv.player.center_y = 1000.0, 1000.0
        gv.player.hp = gv.player.max_hp
        gv.player.shields = 0  # so damage shows in HP directly
        gv.player._collision_cd = 0.0
        proj = Projectile(
            gv._alien_laser_tex, gv.player.center_x, gv.player.center_y,
            0, ALIEN_LASER_SPEED, ALIEN_LASER_RANGE, damage=12)
        gv.alien_projectile_list.clear()
        gv.alien_projectile_list.append(proj)
        from collisions import handle_alien_laser_hits
        hp_before = gv.player.hp
        handle_alien_laser_hits(gv)
        assert gv.player.hp < hp_before

    def test_shared_alien_avoidance_keeps_patrol_working(
            self, real_game_view):
        """Refactored compute_avoidance is the only implementation; one
        Zone 1 tick with aliens + asteroids must still run without
        raising and must advance at least one alien's position."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        if len(gv.alien_list) == 0:
            pytest.skip("No Zone 1 aliens present in this seed")
        pre = [(a.center_x, a.center_y) for a in list(gv.alien_list)[:4]]
        for _ in range(30):
            gv.on_update(1 / 60)
        post = [(a.center_x, a.center_y) for a in list(gv.alien_list)[:4]]
        moved = any(p0 != p1 for p0, p1 in zip(pre, post))
        assert moved, "Aliens did not move after 30 sim frames"


# ═══════════════════════════════════════════════════════════════════════════
#  Null field (stealth patch) — real GameView integration
# ═══════════════════════════════════════════════════════════════════════════

class TestNullFieldIntegration:
    def test_zone1_populates_30_null_fields(self, real_game_view):
        from constants import NULL_FIELD_COUNT
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        assert len(gv._null_fields) == NULL_FIELD_COUNT

    def test_zone2_populates_30_null_fields(self, real_game_view):
        from constants import NULL_FIELD_COUNT
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        assert len(gv._zone._null_fields) == NULL_FIELD_COUNT

    def test_zone2_has_30_gas_areas_not_40(self, real_game_view):
        """Scope reduction from 40 to 30 — verified in a live Zone 2."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        assert len(gv._zone._gas_areas) == 30

    def test_alien_ignores_player_inside_null_field(self, real_game_view):
        """Place an alien next to the player but parked inside a null
        field — the alien must NOT fire or enter PURSUE."""
        from sprites.alien import SmallAlienShip
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        # Overwrite fields with a single known-location field.
        gv._null_fields = [NullField(1000.0, 1000.0, size=300)]
        gv.player.center_x = 1000.0
        gv.player.center_y = 1000.0
        gv.alien_list.clear()
        alien = SmallAlienShip(
            gv._alien_ship_tex, gv._alien_laser_tex, 1080.0, 1000.0)
        gv.alien_list.append(alien)
        gv.alien_projectile_list.clear()
        for _ in range(120):
            gv.on_update(1 / 60)
        # No alien laser should have been fired at the player.
        assert len(gv.alien_projectile_list) == 0
        # Alien stayed in PATROL (state code 0).
        assert alien._state == alien._STATE_PATROL

    def test_alien_targets_player_outside_null_field(self, real_game_view):
        """Control: the same alien, now with the player OUT of the
        field, must fire at least one laser within 5 s."""
        from sprites.alien import SmallAlienShip
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv._null_fields = [NullField(1000.0, 1000.0, size=200)]
        gv.player.center_x = 2000.0  # well outside the field
        gv.player.center_y = 1000.0
        gv.alien_list.clear()
        alien = SmallAlienShip(
            gv._alien_ship_tex, gv._alien_laser_tex, 2050.0, 1000.0)
        gv.alien_list.append(alien)
        gv.alien_projectile_list.clear()
        fired = False
        for _ in range(300):
            gv.on_update(1 / 60)
            if len(gv.alien_projectile_list) > 0:
                fired = True
                break
        assert fired, "Alien with clear sight must eventually fire"

    def test_firing_from_inside_disables_the_field(self, real_game_view):
        """Hold fire while sitting in a null field — the field must
        disable itself on the same frame the first projectile is born."""
        import arcade
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(3000.0, 3000.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 3000.0
        gv.player.center_y = 3000.0
        gv._keys.add(arcade.key.SPACE)
        try:
            # Force weapon off cooldown so the first tick actually fires.
            for w in gv._weapons:
                w._cd = 0.0
            gv.on_update(1 / 60)
        finally:
            gv._keys.discard(arcade.key.SPACE)
        assert nf.active is False, (
            "Firing from inside must trigger the red-flash disable")

    def test_disabled_field_decays_back_to_active(self, real_game_view):
        """Trigger a disable, then advance 31 s of sim time — the
        field should be active again."""
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(0.0, 0.0, size=200)
        nf.trigger_disable()
        gv._null_fields = [nf]
        # 31 virtual seconds (1860 frames at 1/60 dt).
        for _ in range(1860):
            gv.on_update(1 / 60)
        assert nf.active is True

    def test_player_ship_is_transparent_while_cloaked(self, real_game_view):
        """Cloak ghosts the ship: its rendered alpha drops to ~30 for
        the duration of the draw, then restores so other systems that
        read `player.color` aren't stuck with the cloak alpha."""
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1500.0, 1500.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1500.0
        gv.player.center_y = 1500.0
        saved = gv.player.color
        # Spy on player.color mid-draw.
        seen = []
        orig_draw = gv.player_list.draw

        def record_and_draw(*a, **kw):
            seen.append(tuple(gv.player.color))
            return orig_draw(*a, **kw)

        gv.player_list.draw = record_and_draw  # type: ignore[assignment]
        try:
            gv.on_draw()
        finally:
            gv.player_list.draw = orig_draw  # type: ignore[assignment]
        assert seen, "player_list.draw was not called during on_draw"
        assert seen[0][3] < 60, (
            f"Cloaked ship must render at low alpha, got {seen[0]}")
        # Ship's stored color is restored after the draw completes.
        assert tuple(gv.player.color) == tuple(saved)

    def test_cloak_alpha_does_not_leak_to_next_frame(self, real_game_view):
        """The cloak alpha is only applied while the ship is inside an
        active null field. Walking out for one frame restores full
        opacity, not a stuck ghost alpha."""
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1500.0, 1500.0, size=256)
        gv._null_fields = [nf]

        def capture_alpha(gv_):
            seen = []
            orig = gv_.player_list.draw

            def rec(*a, **kw):
                seen.append(tuple(gv_.player.color))
                return orig(*a, **kw)
            gv_.player_list.draw = rec  # type: ignore[assignment]
            try:
                gv_.on_draw()
            finally:
                gv_.player_list.draw = orig  # type: ignore[assignment]
            return seen[0] if seen else None

        gv.player.center_x = 1500.0
        gv.player.center_y = 1500.0
        a_inside = capture_alpha(gv)
        assert a_inside[3] < 60

        gv.player.center_x = 3000.0
        gv.player.center_y = 1500.0
        a_outside = capture_alpha(gv)
        assert a_outside[3] >= 200

        gv.player.center_x = 1500.0
        a_back_in = capture_alpha(gv)
        assert a_back_in[3] < 60

    def test_cloak_restores_prior_tint_like_hit_flash(self, real_game_view):
        """If the ship is already tinted (e.g. a red hit-flash on
        damage), the cloak must restore that tint after drawing, not
        overwrite it with plain white."""
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1500.0, 1500.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1500.0
        gv.player.center_y = 1500.0
        hit_colour = (255, 80, 80, 255)
        gv.player.color = hit_colour
        gv.on_draw()
        assert tuple(gv.player.color) == hit_colour

    def test_cloak_drops_immediately_when_field_disables(
            self, real_game_view):
        """Firing while standing still inside a field: next draw must
        render the ship opaque even though the player hasn't moved."""
        from sprites.null_field import NullField
        from update_logic import disable_null_field_around_player
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1500.0, 1500.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1500.0
        gv.player.center_y = 1500.0

        def capture_alpha(gv_):
            seen = []
            orig = gv_.player_list.draw

            def rec(*a, **kw):
                seen.append(tuple(gv_.player.color))
                return orig(*a, **kw)
            gv_.player_list.draw = rec  # type: ignore[assignment]
            try:
                gv_.on_draw()
            finally:
                gv_.player_list.draw = orig  # type: ignore[assignment]
            return seen[0] if seen else None

        assert capture_alpha(gv)[3] < 60
        disable_null_field_around_player(gv)
        assert capture_alpha(gv)[3] >= 200

    def test_cloak_in_zone2_also_ghosts_the_ship(self, real_game_view):
        """The same visual path works when the player is in the Nebula
        — zone2._null_fields drives cloak, not gv._null_fields."""
        from sprites.null_field import NullField
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        nf = NullField(gv.player.center_x, gv.player.center_y, size=256)
        gv._zone._null_fields.append(nf)
        seen = []
        orig_draw = gv.player_list.draw

        def rec(*a, **kw):
            seen.append(tuple(gv.player.color))
            return orig_draw(*a, **kw)

        gv.player_list.draw = rec  # type: ignore[assignment]
        try:
            gv.on_draw()
        finally:
            gv.player_list.draw = orig_draw  # type: ignore[assignment]
        assert seen and seen[0][3] < 60, (
            f"Zone 2 cloak must ghost the ship; got {seen[0]}")

    def test_player_ship_is_opaque_after_firing_disables_field(
            self, real_game_view):
        """Firing from inside the field drops the cloak — the ship's
        render alpha returns to fully opaque on the next draw."""
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1500.0, 1500.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1500.0
        gv.player.center_y = 1500.0
        from update_logic import disable_null_field_around_player
        disable_null_field_around_player(gv)
        assert nf.active is False
        seen = []
        orig_draw = gv.player_list.draw

        def record_and_draw(*a, **kw):
            seen.append(tuple(gv.player.color))
            return orig_draw(*a, **kw)

        gv.player_list.draw = record_and_draw  # type: ignore[assignment]
        try:
            gv.on_draw()
        finally:
            gv.player_list.draw = orig_draw  # type: ignore[assignment]
        assert seen and seen[0][3] >= 200, (
            f"Uncloaked ship must render opaque, got {seen[0]}")

    def test_repair_pack_from_inside_disables_the_field(
            self, real_game_view):
        """Consuming a repair pack inside a null field trips the
        red-flash disable — stealth breaks the moment you use any
        consumable."""
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1200.0, 1200.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1200.0
        gv.player.center_y = 1200.0
        # Need to be under max HP for the consumable to actually fire.
        gv.player.hp = max(1, gv.player.max_hp // 2)
        gv.inventory.add_item("repair_pack", 1)
        gv._use_repair_pack(0)
        assert nf.active is False

    def test_shield_recharge_from_inside_disables_the_field(
            self, real_game_view):
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1200.0, 1200.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1200.0
        gv.player.center_y = 1200.0
        gv.player.shields = 0
        gv.inventory.add_item("shield_recharge", 1)
        gv._use_shield_recharge(0)
        assert nf.active is False

    def test_homing_missile_from_inside_disables_the_field(
            self, real_game_view):
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1200.0, 1200.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1200.0
        gv.player.center_y = 1200.0
        gv.inventory.add_item("missile", 5)
        gv._missile_fire_cd = 0.0
        gv._fire_missile(0)
        assert nf.active is False

    def test_consumable_with_full_stats_does_not_disable_field(
            self, real_game_view):
        """Repair pack with full HP early-returns and must NOT trip
        the null field — stealth is only broken when the consumable
        actually fires."""
        from sprites.null_field import NullField
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        nf = NullField(1200.0, 1200.0, size=256)
        gv._null_fields = [nf]
        gv.player.center_x = 1200.0
        gv.player.center_y = 1200.0
        gv.player.hp = gv.player.max_hp  # already full → early-return
        gv.inventory.add_item("repair_pack", 1)
        gv._use_repair_pack(0)
        assert nf.active is True


# ═══════════════════════════════════════════════════════════════════════════
#  Asteroid-specific explosion animation (Explo__001..010.png) routing
# ═══════════════════════════════════════════════════════════════════════════

class TestAsteroidExplosionIntegration:
    """Asteroid kills now use the 10-frame Explo__001..010.png cycle;
    ship / alien / building deaths still use the legacy sheet."""

    def test_zone1_asteroid_kill_uses_new_frames(self, real_game_view):
        """Zero-HP asteroid → `_apply_kill_rewards(asteroid=True)` →
        Explosion sprite whose ``_frames`` is the asteroid list."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        if len(gv.asteroid_list) == 0:
            pytest.skip("No Zone 1 asteroids present in this seed")
        before = len(gv.explosion_list)
        ast = list(gv.asteroid_list)[0]
        ast.hp = 1
        from sprites.projectile import Projectile
        proj = Projectile(
            gv._alien_laser_tex,
            ast.center_x, ast.center_y, 0, 500, 800, damage=9999,
            mines_rock=True)
        gv.projectile_list.append(proj)
        from collisions import handle_projectile_hits
        handle_projectile_hits(gv)
        new_explosions = list(gv.explosion_list)[before:]
        assert new_explosions, "Asteroid kill must spawn an explosion"
        assert new_explosions[0]._frames is gv._asteroid_explosion_frames

    def test_zone2_iron_asteroid_kill_uses_new_frames(self, real_game_view):
        from zones.zone2_world import handle_projectile_hits
        from sprites.projectile import Projectile
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        z = gv._zone
        if len(z._iron_asteroids) == 0:
            pytest.skip("Zone 2 seed produced no iron asteroids")
        before = len(gv.explosion_list)
        ast = list(z._iron_asteroids)[0]
        ast.hp = 1
        proj = Projectile(
            gv._alien_laser_tex, ast.center_x, ast.center_y,
            0, 500, 800, damage=9999, mines_rock=True)
        gv.projectile_list.clear()
        gv.projectile_list.append(proj)
        handle_projectile_hits(z, gv)
        new_explosions = list(gv.explosion_list)[before:]
        assert new_explosions
        assert new_explosions[0]._frames is gv._asteroid_explosion_frames

    def test_zone2_copper_asteroid_kill_uses_new_frames(self, real_game_view):
        from zones.zone2_world import handle_projectile_hits
        from sprites.projectile import Projectile
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        z = gv._zone
        if len(z._copper_asteroids) == 0:
            pytest.skip("Zone 2 seed produced no copper asteroids")
        before = len(gv.explosion_list)
        ast = list(z._copper_asteroids)[0]
        ast.hp = 1
        proj = Projectile(
            gv._alien_laser_tex, ast.center_x, ast.center_y,
            0, 500, 800, damage=9999, mines_rock=True)
        gv.projectile_list.clear()
        gv.projectile_list.append(proj)
        handle_projectile_hits(z, gv)
        new_explosions = list(gv.explosion_list)[before:]
        assert new_explosions
        assert new_explosions[0]._frames is gv._asteroid_explosion_frames

    def test_zone2_wanderer_kill_uses_new_frames(self, real_game_view):
        from zones.zone2_world import handle_projectile_hits
        from sprites.projectile import Projectile
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        z = gv._zone
        if len(z._wanderers) == 0:
            pytest.skip("Zone 2 seed produced no wanderers")
        before = len(gv.explosion_list)
        w = list(z._wanderers)[0]
        w.hp = 1
        proj = Projectile(
            gv._alien_laser_tex, w.center_x, w.center_y,
            0, 500, 800, damage=9999, mines_rock=True)
        gv.projectile_list.clear()
        gv.projectile_list.append(proj)
        handle_projectile_hits(z, gv)
        new_explosions = list(gv.explosion_list)[before:]
        assert new_explosions
        assert new_explosions[0]._frames is gv._asteroid_explosion_frames

    def test_alien_kill_still_uses_legacy_frames(self, real_game_view):
        """Regression guard: alien ships continue using the legacy
        single-sheet explosion, NOT the new asteroid cycle."""
        from sprites.alien import SmallAlienShip
        from sprites.projectile import Projectile
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv.alien_list.clear()
        alien = SmallAlienShip(
            gv._alien_ship_tex, gv._alien_laser_tex, 3000.0, 3000.0)
        alien.hp = 1
        gv.alien_list.append(alien)
        before = len(gv.explosion_list)
        proj = Projectile(
            gv._alien_laser_tex, 3000.0, 3000.0, 0, 500, 800,
            damage=9999, mines_rock=False)
        gv.projectile_list.append(proj)
        from collisions import handle_projectile_hits
        handle_projectile_hits(gv)
        new_explosions = list(gv.explosion_list)[before:]
        assert new_explosions
        assert new_explosions[0]._frames is gv._explosion_frames
        assert new_explosions[0]._frames is not gv._asteroid_explosion_frames

    def test_building_kill_still_uses_legacy_frames(self, real_game_view):
        """Regression guard: buildings continue using the legacy
        explosion when destroyed."""
        from sprites.building import create_building
        from sprites.projectile import Projectile
        from constants import ALIEN_LASER_SPEED, ALIEN_LASER_RANGE
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        gv.building_list.clear()
        tex = gv._building_textures["Service Module"]
        b = create_building("Service Module", tex, 4000.0, 4000.0,
                             scale=0.5)
        b.hp = 1
        gv.building_list.append(b)
        before = len(gv.explosion_list)
        proj = Projectile(
            gv._alien_laser_tex, 4000.0, 4000.0, 0,
            ALIEN_LASER_SPEED, ALIEN_LASER_RANGE, damage=9999)
        gv.alien_projectile_list.append(proj)
        from collisions import handle_alien_laser_building_hits
        handle_alien_laser_building_hits(gv)
        new_explosions = list(gv.explosion_list)[before:]
        assert new_explosions
        assert new_explosions[0]._frames is gv._explosion_frames

    def test_asteroid_explosion_has_ten_frames(self, real_game_view):
        """The GameView-cached asteroid frame list contains exactly
        the 10 Explo__001..010 textures."""
        from constants import ASTEROID_EXPLOSION_FRAMES
        gv = real_game_view
        assert len(gv._asteroid_explosion_frames) == ASTEROID_EXPLOSION_FRAMES
        assert ASTEROID_EXPLOSION_FRAMES == 10

    def test_asteroid_explosion_animates_through_all_frames(
            self, real_game_view):
        """Tick the explosion long enough to advance past every frame
        and verify the sprite is removed when the sequence ends."""
        from sprites.explosion import Explosion
        from constants import EXPLOSION_FPS, ASTEROID_EXPLOSION_FRAMES
        gv = real_game_view
        exp = Explosion(gv._asteroid_explosion_frames, 100.0, 200.0)
        gv.explosion_list.append(exp)
        dt_per_frame = 1.0 / EXPLOSION_FPS + 0.0001
        for i in range(ASTEROID_EXPLOSION_FRAMES - 1):
            exp.update_explosion(dt_per_frame)
            assert exp._frame_idx == i + 1, (
                f"Frame {i+1} expected, got {exp._frame_idx}")
        # One more tick removes the sprite.
        exp.update_explosion(dt_per_frame)
        assert exp not in gv.explosion_list
