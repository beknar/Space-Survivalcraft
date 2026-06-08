"""Click-priority + drone deploy error-message tests.

Two unrelated UX fixes shipped together — see the call-site
comments for the why.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import arcade
import pytest


# ── Click-priority: open inventory absorbs clicks over its panel ──────────


class TestInventoryPanelAbsorbsClicks:
    """When the cargo inventory is open and the player clicks
    anywhere INSIDE its panel rect, the click must NOT pass
    through to the world-click dispatcher (which would activate
    a station building / parked ship / trade station sitting
    under the cursor in world space).
    """

    def test_world_click_skipped_when_inventory_panel_under_cursor(
            self):
        from input_handlers import handle_mouse_press
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv.inventory.open = True
        # Cursor inside the inventory panel rect.
        sw = arcade.get_window().width
        sh = arcade.get_window().height
        from constants import INV_W, INV_H
        cx = (sw - INV_W) // 2 + INV_W // 2
        cy = (sh - INV_H) // 2 + INV_H // 2
        with patch("input_handlers._handle_world_click") as mock_world:
            handle_mouse_press(
                gv, cx, cy, arcade.MOUSE_BUTTON_LEFT, 0)
        # World click handler must NOT have fired — the inventory
        # absorbed the press.
        mock_world.assert_not_called()

    def test_world_click_fires_when_inventory_closed(self):
        from input_handlers import handle_mouse_press
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv.inventory.open = False
        with patch("input_handlers._handle_world_click",
                    return_value=False) as mock_world:
            handle_mouse_press(
                gv, 400, 300, arcade.MOUSE_BUTTON_LEFT, 0)
        mock_world.assert_called_once()

    def test_world_click_fires_outside_inventory_panel(self):
        """Inventory open but cursor OUTSIDE the panel rect → the
        world dispatcher still runs (e.g. clicks at the edges of
        the screen targeting a world entity)."""
        from input_handlers import handle_mouse_press
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        gv.inventory.open = True
        # Click at (5, 5) — far outside the centred panel.
        with patch("input_handlers._handle_world_click",
                    return_value=False) as mock_world:
            handle_mouse_press(
                gv, 5, 5, arcade.MOUSE_BUTTON_LEFT, 0)
        mock_world.assert_called_once()


# ── Same-variant drone deploy surfaces an error ────────────────────────────


class TestSameDroneDeployErrorMessage:
    def test_same_variant_deploy_flashes_error(self):
        """Pressing R while the matching drone is already deployed
        should flash "<Type> Drone already deployed" instead of
        silently no-op'ing.  The player has no UI feedback
        otherwise."""
        from combat_helpers import deploy_drone
        from sprites.drone import CombatDrone
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        # Pre-deploy a combat drone so the second deploy hits the
        # same-variant branch.
        d = CombatDrone(0.0, 0.0)
        gv._drone_list.append(d)
        gv._active_drone = d
        # Default weapon is the Basic Laser → mines_rock=False →
        # combat drone is the desired variant.
        with patch("combat_helpers.flash_game_msg") as mock_flash:
            deploy_drone(gv)
        # Flash was called with the "already deployed" message.
        flashed = [c.args[1] for c in mock_flash.call_args_list]
        assert any("Combat Drone already deployed" in m
                    for m in flashed), (
            f"flash_game_msg got: {flashed!r} — expected one to "
            f"contain 'Combat Drone already deployed'")

    def test_same_variant_deploy_does_not_consume_inventory(self):
        """Same-variant no-op must NOT charge the player a drone
        from inventory — a re-press shouldn't burn a charge."""
        from combat_helpers import deploy_drone
        from sprites.drone import CombatDrone
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        d = CombatDrone(0.0, 0.0)
        gv._drone_list.append(d)
        gv._active_drone = d
        gv.inventory.add_item("combat_drone", 5)
        before = gv.inventory.count_item("combat_drone")
        deploy_drone(gv)
        assert gv.inventory.count_item("combat_drone") == before

    def test_other_variant_swap_still_works(self):
        """Sanity — pressing R with the OTHER weapon active still
        swaps the deployed drone (regression check on the new
        flash_game_msg call interfering with the swap path)."""
        from combat_helpers import deploy_drone
        from sprites.drone import CombatDrone, MiningDrone
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        # Combat drone deployed.
        d = CombatDrone(0.0, 0.0)
        gv._drone_list.append(d)
        gv._active_drone = d
        # Cycle weapon to the Mining Beam so deploy_drone wants
        # the mining variant.
        for _ in range(len(gv._weapons)):
            if gv._active_weapon.mines_rock:
                break
            gv._weapon_idx += 1
        assert gv._active_weapon.mines_rock is True, (
            "test setup: couldn't switch to mining beam")
        gv.inventory.add_item("mining_drone", 1)
        deploy_drone(gv)
        assert isinstance(gv._active_drone, MiningDrone)


class TestDeployDroneVariant:
    """2026-06-07: ``deploy_drone_variant`` lets the autopilot field a
    SPECIFIC drone variant (independent of the active weapon) so it can
    run a combat drone while fighting and a mining drone while mining,
    swapping as needed.  Shares ``_deploy_drone_impl`` with the R key."""

    def _gv(self):
        from game_view import GameView
        return GameView(faction="Earth", ship_type="Cruiser",
                        skip_music=True)

    def test_deploys_requested_combat_variant(self):
        from combat_helpers import deploy_drone_variant
        from sprites.drone import CombatDrone
        gv = self._gv()
        gv.inventory.add_item("combat_drone", 2)
        res = deploy_drone_variant(gv, "combat")
        assert res["ok"] and res["active"] == "combat_drone"
        assert isinstance(gv._active_drone, CombatDrone)
        assert gv.inventory.count_item("combat_drone") == 1

    def test_deploys_requested_mining_variant_regardless_of_weapon(self):
        # Active weapon is the Basic Laser (combat), but an explicit
        # "mining" request must still field the MINING drone.
        from combat_helpers import deploy_drone_variant
        from sprites.drone import MiningDrone
        gv = self._gv()
        assert gv._active_weapon.mines_rock is False
        gv.inventory.add_item("mining_drone", 1)
        res = deploy_drone_variant(gv, "mining")
        assert res["ok"]
        assert isinstance(gv._active_drone, MiningDrone)

    def test_swaps_and_refunds_old_variant(self):
        from combat_helpers import deploy_drone_variant
        from sprites.drone import CombatDrone, MiningDrone
        gv = self._gv()
        d = CombatDrone(0.0, 0.0)
        gv._drone_list.append(d)
        gv._active_drone = d
        gv.inventory.add_item("mining_drone", 1)
        res = deploy_drone_variant(gv, "mining")
        assert res["ok"]
        assert isinstance(gv._active_drone, MiningDrone)
        # Old combat drone refunded to inventory.
        assert gv.inventory.count_item("combat_drone") == 1

    def test_same_variant_is_noop_no_charge(self):
        from combat_helpers import deploy_drone_variant
        from sprites.drone import CombatDrone
        gv = self._gv()
        d = CombatDrone(0.0, 0.0)
        gv._drone_list.append(d)
        gv._active_drone = d
        gv.inventory.add_item("combat_drone", 3)
        res = deploy_drone_variant(gv, "combat")
        assert res["reason"] == "already_deployed"
        assert gv.inventory.count_item("combat_drone") == 3

    def test_no_charges_returns_error(self):
        from combat_helpers import deploy_drone_variant
        gv = self._gv()
        res = deploy_drone_variant(gv, "combat")
        assert res["ok"] is False and res["reason"] == "no_charges"
        assert getattr(gv, "_active_drone", None) is None

    def test_bad_variant_rejected(self):
        from combat_helpers import deploy_drone_variant
        gv = self._gv()
        res = deploy_drone_variant(gv, "nonsense")
        assert res["ok"] is False
        assert res["reason"].startswith("bad_variant")
