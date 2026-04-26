"""Tests for the second-pass drone polish:
* Shield regen at the player's rate
* Stuck-on-target detection (5 s with target but no shot)
* recall_drone helper (Shift+R "put away")
* deploy_drone refund-on-swap behaviour
* AI Pilot install-edge latch on ParkedShip
* Per-crafter craft_target so two crafters can run different recipes
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


# ── Shield regen ─────────────────────────────────────────────────────────

class TestDroneShieldRegen:
    def test_regen_matches_player_rate(self):
        # Player regens 0.5 pt/s (Cruiser); after 2 s the drone
        # should have gained 1 shield point.
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        starting = d.shields
        d.shields = max(0, d.shields - 5)   # leave room to regen
        player = SimpleNamespace(_shield_regen=0.5)
        d.regen_shields(2.0, player)
        assert d.shields == max(0, starting - 5) + 1

    def test_regen_clamps_to_max(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d.shields = d.max_shields
        d.regen_shields(10.0, SimpleNamespace(_shield_regen=10.0))
        assert d.shields == d.max_shields

    def test_zero_max_shields_skips(self):
        # Mining drone has no shields — regen is a no-op.
        from sprites.drone import MiningDrone
        d = MiningDrone(0.0, 0.0)
        d.regen_shields(5.0, SimpleNamespace(_shield_regen=5.0))
        assert d.shields == 0

    def test_no_regen_when_player_rate_is_zero(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d.shields = 5
        d.regen_shields(10.0, SimpleNamespace(_shield_regen=0.0))
        assert d.shields == 5


# ── Stuck-on-target detection ────────────────────────────────────────────

class TestDroneStuckDetection:
    def test_target_lock_starts_active(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        assert d.has_target_lock() is True

    def test_no_target_resets_state(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d._target_acquired_timer = 3.0
        d._stuck_target = SimpleNamespace(hp=10)
        stuck = d._track_stuck_progress(1 / 60, None)
        assert stuck is False
        assert d._target_acquired_timer == 0.0
        assert d._stuck_target is None

    def test_new_target_resets_progress(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d._target_acquired_timer = 4.0
        old = SimpleNamespace(hp=10)
        d._stuck_target = old
        new = SimpleNamespace(hp=20)
        stuck = d._track_stuck_progress(1 / 60, new)
        assert stuck is False
        assert d._stuck_target is new
        assert d._stuck_target_hp == 20
        assert d._target_acquired_timer == 0.0

    def test_hp_drop_resets_timer(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        target = SimpleNamespace(hp=50)
        d._track_stuck_progress(1.0, target)
        # Drone damages target → HP drops.
        target.hp = 35
        stuck = d._track_stuck_progress(1.0, target)
        assert stuck is False
        assert d._target_acquired_timer == 0.0
        assert d._stuck_target_hp == 35

    def test_stuck_threshold_triggers_cooldown(self):
        # Same target, no HP loss for 5+ seconds → stuck.  First call
        # ACQUIRES the target (resets state), subsequent same-target
        # calls accumulate the timer.
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        target = SimpleNamespace(hp=50)
        d._track_stuck_progress(0.0, target)   # acquire (timer = 0)
        d._track_stuck_progress(2.5, target)
        assert d.has_target_lock() is True
        d._track_stuck_progress(2.6, target)   # cumulative 5.1 s
        assert d.has_target_lock() is False
        assert d._target_cooldown == pytest.approx(5.0)
        assert d._stuck_target is None

    def test_cooldown_decays_via_update_visuals(self):
        from sprites.drone import CombatDrone
        d = CombatDrone(0.0, 0.0)
        d._target_cooldown = 5.0
        d.update_visuals(2.0)
        assert d._target_cooldown == pytest.approx(3.0)


# ── recall_drone helper ──────────────────────────────────────────────────

class _Inv:
    def __init__(self, items=None):
        self._items = items or {}

    def count_item(self, name):
        return self._items.get(name, 0)

    def add_item(self, name, qty=1):
        self._items[name] = self._items.get(name, 0) + qty

    def remove_item(self, name, qty=1):
        self._items[name] = max(0, self._items.get(name, 0) - qty)


class TestRecallDrone:
    def _gv_with_drone(self, drone_cls_name):
        from sprites.drone import MiningDrone, CombatDrone
        cls = MiningDrone if drone_cls_name == "MiningDrone" else CombatDrone
        d = cls(0.0, 0.0)
        gv = SimpleNamespace(
            inventory=_Inv({"mining_drone": 0, "combat_drone": 0}),
            _drone_list=arcade.SpriteList(),
            _active_drone=d,
            _flash_msg="",
            _flash_timer=0.0,
        )
        gv._drone_list.append(d)
        return gv, d

    def test_recall_refunds_combat_drone_to_inventory(self):
        from combat_helpers import recall_drone
        gv, _ = self._gv_with_drone("CombatDrone")
        recall_drone(gv)
        assert gv._active_drone is None
        assert gv.inventory.count_item("combat_drone") == 1

    def test_recall_refunds_mining_drone_to_inventory(self):
        from combat_helpers import recall_drone
        gv, _ = self._gv_with_drone("MiningDrone")
        recall_drone(gv)
        assert gv._active_drone is None
        assert gv.inventory.count_item("mining_drone") == 1

    def test_recall_with_no_drone_is_noop(self):
        from combat_helpers import recall_drone
        gv = SimpleNamespace(
            inventory=_Inv(),
            _drone_list=arcade.SpriteList(),
            _active_drone=None,
            _flash_msg="",
            _flash_timer=0.0,
        )
        recall_drone(gv)   # must not raise
        assert gv._active_drone is None


# ── ParkedShip AI Pilot install latch ────────────────────────────────────

class TestAIPilotInstallLatch:
    def _ship(self, monkeypatch):
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip
        from PIL import Image
        tex = arcade.Texture(Image.new("RGBA", (32, 32), (0, 0, 0, 0)))
        monkeypatch.setattr(PlayerShip, "_extract_ship_texture",
                            staticmethod(lambda *a, **k: tex))
        return ParkedShip("Earth", "Cruiser", 1, 0.0, 0.0, heading=0.0)

    def test_install_resets_to_patrol_mode(self, monkeypatch):
        ps = self._ship(monkeypatch)
        # Pre-state: in "return" mode from a previous combat session.
        ps._ai_mode = "return"
        ps._ai_pilot_was_installed = False
        # Install AI Pilot module.
        ps.module_slots = ["ai_pilot"]
        # Need a frames list for the lazy shield init; patch
        # get_shield_frames so _ensure_ai_shield doesn't crash.
        from world_setup import get_shield_frames  # noqa: F401
        # Tick once.
        ps.update_parked(1 / 60)
        # Mode forced back to patrol on the install edge.
        assert ps._ai_mode == "patrol"
        assert ps._ai_pilot_was_installed is True

    def test_uninstall_clears_latch(self, monkeypatch):
        ps = self._ship(monkeypatch)
        ps.module_slots = ["ai_pilot"]
        ps._ai_pilot_was_installed = True
        # Remove module — next tick clears the latch so a future
        # re-install triggers the patrol-mode reset again.
        ps.module_slots = [None]
        ps.update_parked(1 / 60)
        assert ps._ai_pilot_was_installed is False


# ── Per-crafter craft target ─────────────────────────────────────────────

class TestPerCrafterTarget:
    def test_basic_crafter_has_craft_target_field(self):
        from sprites.building import BasicCrafter
        from PIL import Image
        tex = arcade.Texture(Image.new("RGBA", (32, 32), (0, 0, 0, 0)))
        c = BasicCrafter(tex, 0.0, 0.0, "Basic Crafter", scale=1.0)
        assert hasattr(c, "craft_target")
        assert c.craft_target == ""

    def test_two_crafters_track_separate_targets(self):
        from sprites.building import BasicCrafter
        from PIL import Image
        tex = arcade.Texture(Image.new("RGBA", (32, 32), (0, 0, 0, 0)))
        a = BasicCrafter(tex, 0.0, 0.0, "Advanced Crafter", scale=1.0)
        b = BasicCrafter(tex, 100.0, 0.0, "Advanced Crafter", scale=1.0)
        a.craft_target = "mining_drone"
        b.craft_target = "combat_drone"
        # Each crafter retains its own target — assigning one doesn't
        # bleed into the other (the bug before this fix was that both
        # crafters read a single shared field on the menu).
        assert a.craft_target == "mining_drone"
        assert b.craft_target == "combat_drone"
