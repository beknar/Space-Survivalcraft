"""End-to-end Basic Ship build flow.

Real GameView with a hidden Arcade window so we can construct
ParkedShip + drive the full ``enter_placement_mode`` →
``place_building`` path that the build menu kicks off.

Covers:
  - Resource deduction across player + station inventories
  - A fresh L1 ParkedShip appearing in ``gv._parked_ships``
  - The player's own ship is NOT touched (stays at its current level)
  - count_l1_ships transitions from 0 → 1 after placement
  - Build menu re-locks "Basic Ship" after the rebuild
  - Repeat: destroying the parked L1 lets the player rebuild
"""
from __future__ import annotations

import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT, BUILDING_TYPES
from zones import ZoneID


def _strip_player_to_l2(gv) -> None:
    """Move the player to L2 so any L1 ship that exists is parked,
    not the active player.  Mirrors what happens after a normal
    Advanced Ship upgrade."""
    from sprites.player import PlayerShip
    gv._ship_level = 2
    old = gv.player
    new_player = PlayerShip(
        faction=gv._faction, ship_type=gv._ship_type, ship_level=2)
    new_player.center_x = old.center_x
    new_player.center_y = old.center_y
    new_player.heading = old.heading
    gv.player_list.clear()
    gv.player = new_player
    gv.player_list.append(new_player)


def _stock_resources(gv) -> None:
    """Drop enough iron + copper into the station inventory to afford
    a Basic Ship purchase several times over."""
    # Half-cost = 500 iron + 250 copper.  Stock 4× that.
    gv._station_inv._items[(0, 0)] = ("iron", 4 * 500)
    gv._station_inv._items[(0, 1)] = ("copper", 4 * 250)
    gv._station_inv._mark_dirty()


class TestBasicShipPlacementEndToEnd:
    def test_place_basic_ship_appends_l1_parked(self, real_game_view):
        """Direct call to _place_basic_ship — the same code path that
        ``place_building`` hits when the placement-mode click lands."""
        from ship_manager import _place_basic_ship, count_l1_ships

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()
        _stock_resources(gv)

        assert count_l1_ships(gv) == 0
        wx, wy = WORLD_WIDTH / 2 + 200, WORLD_HEIGHT / 2

        _place_basic_ship(gv, wx, wy)

        assert len(gv._parked_ships) == 1
        ps = gv._parked_ships[0]
        assert ps.ship_level == 1
        assert ps.center_x == wx
        assert ps.center_y == wy
        # Ship started fresh — full HP/shields, no cargo, no modules.
        assert ps.hp == ps.max_hp
        assert ps.shields == ps.max_shields
        assert ps.cargo_items == {}
        assert ps.module_slots == []
        # Now there's exactly one L1 ship in the world.
        assert count_l1_ships(gv) == 1

    def test_place_basic_ship_deducts_half_cost(self, real_game_view):
        from ship_manager import _place_basic_ship

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()
        _stock_resources(gv)

        iron_before = gv.inventory.total_iron + gv._station_inv.total_iron
        copper_before = (gv.inventory.count_item("copper")
                         + gv._station_inv.count_item("copper"))

        _place_basic_ship(gv, 100.0, 100.0)

        iron_after = gv.inventory.total_iron + gv._station_inv.total_iron
        copper_after = (gv.inventory.count_item("copper")
                        + gv._station_inv.count_item("copper"))
        assert iron_before - iron_after == BUILDING_TYPES["Basic Ship"]["cost"]
        assert (copper_before - copper_after
                == BUILDING_TYPES["Basic Ship"]["cost_copper"])

    def test_place_basic_ship_does_not_touch_player(self, real_game_view):
        """The player's ship level / position / HP must be untouched —
        Basic Ship only adds a parked ship, it does NOT upgrade or
        teleport the player like Advanced Ship does."""
        from ship_manager import _place_basic_ship

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()
        _stock_resources(gv)

        before_level = gv._ship_level
        before_x = gv.player.center_x
        before_y = gv.player.center_y
        before_hp = gv.player.hp

        _place_basic_ship(gv, 5000.0, 5000.0)

        assert gv._ship_level == before_level
        assert gv.player.center_x == before_x
        assert gv.player.center_y == before_y
        assert gv.player.hp == before_hp

    def test_basic_ship_locks_after_placement(self, real_game_view):
        """After placement, count_l1_ships == 1 → "Basic Ship" should
        re-lock in the build menu."""
        from ship_manager import _place_basic_ship, count_l1_ships
        from build_menu import BuildMenu

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()
        _stock_resources(gv)

        _place_basic_ship(gv, 100.0, 100.0)

        ok, reason = BuildMenu._check_availability(
            "Basic Ship",
            iron=10_000, building_counts={"Home Station": 1},
            modules_used=0, module_capacity=20, has_home=True,
            copper=10_000, unlocked_blueprints=set(),
            ship_level=2, max_ship_exists=False,
            l1_ship_exists=count_l1_ships(gv) > 0,
        )
        assert not ok
        assert "L1" in reason or "level-1" in reason.lower()

    def test_destroy_then_rebuild_basic_ship(self, real_game_view):
        """Realistic gameplay loop — build, simulate alien-killing the
        parked L1, then rebuild.  The rebuild path must succeed."""
        from ship_manager import _place_basic_ship, count_l1_ships

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()
        _stock_resources(gv)

        _place_basic_ship(gv, 100.0, 100.0)
        assert count_l1_ships(gv) == 1

        # Simulate the parked ship being destroyed.
        ps = gv._parked_ships[0]
        ps.remove_from_sprite_lists()
        # Defensive: also drop it from the GameView reference if any
        # lingers (real game removes via collision handler).
        gv._parked_ships.remove(ps) if ps in gv._parked_ships else None

        assert count_l1_ships(gv) == 0

        # Stock should still be enough to rebuild.
        _place_basic_ship(gv, 200.0, 200.0)
        assert count_l1_ships(gv) == 1
        assert len(gv._parked_ships) == 1


class TestBasicShipPlacementModeEntry:
    """The build menu calls ``enter_placement_mode("Basic Ship")``
    before the actual placement click.  That path must enforce the
    same gates (resources + L1 ship count) without producing a ghost."""

    def test_entry_blocked_when_l1_ship_exists(self, real_game_view):
        from building_manager import enter_placement_mode

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        # Player is L1 by default → l1_ship_exists is true.
        gv._parked_ships.clear()
        _stock_resources(gv)
        gv._ghost_sprite = None

        enter_placement_mode(gv, "Basic Ship")
        assert gv._ghost_sprite is None
        assert "level-1" in (gv._flash_msg or "").lower()

    def test_entry_blocked_when_iron_short(self, real_game_view):
        from building_manager import enter_placement_mode

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()
        # Empty inventories — can't afford anything.
        gv.inventory._items.clear()
        gv._station_inv._items.clear()
        gv.inventory._mark_dirty()
        gv._station_inv._mark_dirty()
        gv._ghost_sprite = None

        enter_placement_mode(gv, "Basic Ship")
        assert gv._ghost_sprite is None
        assert "iron" in (gv._flash_msg or "").lower()

    def test_entry_succeeds_when_all_gates_open(self, real_game_view):
        from building_manager import enter_placement_mode

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _strip_player_to_l2(gv)
        gv._parked_ships.clear()
        _stock_resources(gv)
        gv._ghost_sprite = None
        gv._build_menu.open = True

        enter_placement_mode(gv, "Basic Ship")
        assert gv._ghost_sprite is not None
        assert gv._placing_building == "Basic Ship"
        # Build menu was closed by the placement-mode entry.
        assert gv._build_menu.open is False
