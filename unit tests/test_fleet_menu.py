"""Fleet Control menu — Y-key drone command overlay.

Pins the four button identifiers, the order/reaction state set on
the active drone, and the no-drone-deployed status string.
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


# ── Menu surface ────────────────────────────────────────────────────────────

class TestFleetMenuButtons:
    def test_button_ids_exposed(self):
        from fleet_menu import FleetMenu
        # Caller code (input_handlers + apply_fleet_order) keys off
        # these constants — pin them so a future rename can't silently
        # break the wire-up.
        assert FleetMenu.BTN_RETURN == "return"
        assert FleetMenu.BTN_ATTACK == "attack"
        assert FleetMenu.BTN_FOLLOW_ONLY == "follow_only"
        assert FleetMenu.BTN_ATTACK_ONLY == "attack_only"

    def test_toggle_open_close(self):
        from fleet_menu import FleetMenu
        m = FleetMenu()
        assert m.open is False
        m.toggle()
        assert m.open is True
        m.toggle()
        assert m.open is False

    def test_y_key_closes_menu(self):
        """Y is the toggle hotkey — pressing Y while open closes."""
        from fleet_menu import FleetMenu
        m = FleetMenu()
        m.toggle()
        m.on_key_press(arcade.key.Y)
        assert m.open is False

    def test_clicks_outside_panel_close_menu(self):
        from fleet_menu import FleetMenu
        m = FleetMenu()
        m.toggle()
        # Click far outside the panel — should close, return None.
        action = m.on_mouse_press(0, 0)
        assert action is None
        assert m.open is False


# ── Order application ──────────────────────────────────────────────────────

class TestApplyFleetOrder:
    def _drone(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        return d

    def test_no_drone_returns_status(self):
        from combat_helpers import apply_fleet_order
        gv = SimpleNamespace(_active_drone=None)
        msg = apply_fleet_order(gv, "return")
        assert msg == "No drone deployed"

    def test_return_sets_direct_order(self):
        from combat_helpers import apply_fleet_order
        d = self._drone()
        gv = SimpleNamespace(_active_drone=d)
        msg = apply_fleet_order(gv, "return")
        assert d._direct_order == "return"
        assert "RETURN" in msg

    def test_attack_sets_direct_order(self):
        from combat_helpers import apply_fleet_order
        d = self._drone()
        gv = SimpleNamespace(_active_drone=d)
        apply_fleet_order(gv, "attack")
        assert d._direct_order == "attack"

    def test_follow_only_sets_reaction_and_clears_direct(self):
        from combat_helpers import apply_fleet_order
        d = self._drone()
        d._direct_order = "attack"  # an old order should clear out
        gv = SimpleNamespace(_active_drone=d)
        apply_fleet_order(gv, "follow_only")
        assert d._reaction == "follow"
        assert d._direct_order is None

    def test_attack_only_resets_reaction(self):
        from combat_helpers import apply_fleet_order
        d = self._drone()
        d._reaction = "follow"
        d._direct_order = "return"
        gv = SimpleNamespace(_active_drone=d)
        apply_fleet_order(gv, "attack_only")
        assert d._reaction == "attack"
        assert d._direct_order is None


# ── Mode machine respects orders + reactions ──────────────────────────────

class TestModeMachineHonoursFleetOrders:
    def _drone_at(self, x, y):
        from sprites.drone import CombatDrone
        return CombatDrone(x, y)

    def test_follow_only_reaction_blocks_attack_mode(self):
        """A combat drone with the FOLLOW_ONLY reaction must NOT
        switch to ATTACK even with a target right next to it."""
        from sprites.drone import _BaseDrone
        d = self._drone_at(0.0, 0.0)
        d._reaction = "follow"
        player = SimpleNamespace(center_x=0.0, center_y=0.0,
                                  heading=0.0)
        target = SimpleNamespace(center_x=100.0, center_y=0.0, hp=100)
        d._update_mode(player, target, walls=None)
        assert d._mode == _BaseDrone._MODE_FOLLOW

    def test_direct_return_overrides_target_in_range(self):
        """RETURN order forces RETURN_HOME regardless of distance to
        player — the drone must NOT engage even when an enemy sits
        right beside it."""
        from sprites.drone import _BaseDrone
        d = self._drone_at(0.0, 0.0)
        d._direct_order = "return"
        # Player ~900 px away so the order is meaningful.
        player = SimpleNamespace(center_x=900.0, center_y=0.0,
                                  heading=0.0)
        target = SimpleNamespace(center_x=50.0, center_y=0.0, hp=100)
        d._update_mode(player, target, walls=None)
        assert d._mode == _BaseDrone._MODE_RETURN_HOME

    def test_direct_return_auto_clears_when_player_close(self):
        """Once the drone is back inside the close-range threshold
        the RETURN order auto-clears so the drone resumes its normal
        reaction."""
        d = self._drone_at(0.0, 0.0)
        d._direct_order = "return"
        # Player sits inside the EXIT distance.
        player = SimpleNamespace(center_x=100.0, center_y=0.0,
                                  heading=0.0)
        d._update_mode(player, target=None, walls=None)
        assert d._direct_order is None

    def test_direct_attack_ignores_break_off_distance(self):
        """ATTACK order keeps the drone engaging even when the
        player has flown past the 800 px break-off line."""
        from sprites.drone import _BaseDrone
        from constants import DRONE_BREAK_OFF_DIST
        d = self._drone_at(0.0, 0.0)
        d._direct_order = "attack"
        player = SimpleNamespace(
            center_x=DRONE_BREAK_OFF_DIST + 200.0, center_y=0.0)
        target = SimpleNamespace(center_x=80.0, center_y=0.0, hp=100)
        d._update_mode(player, target, walls=None)
        assert d._mode == _BaseDrone._MODE_ATTACK


# ── Help menu integration ─────────────────────────────────────────────────

class TestFleetMenuHelpEntry:
    def test_help_menu_lists_y_hotkey(self):
        from escape_menu import _help_mode
        # Y / Fleet Control row must appear in the keyboard help table.
        keys = [k for (k, _) in _help_mode._HELP_LINES]
        assert "Y" in keys
        # Drone how-to lines mention the four button labels so the
        # player can read them without opening the menu first.
        block = " ".join(_help_mode._DRONE_LINES)
        assert "RETURN" in block
        assert "ATTACK" in block
        assert "FOLLOW ONLY" in block
        assert "ATTACK ONLY" in block
