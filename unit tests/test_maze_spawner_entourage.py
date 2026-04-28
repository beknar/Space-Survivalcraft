"""Tests for maze-spawner entourage + guaranteed-unowned blueprint drop.

* When a MazeSpawner appears (initial setup OR post-kill respawn) it
  brings ``MAZE_SPAWNER_INITIAL_ALIENS`` (10) MazeAliens with it,
  capped by ``MAZE_SPAWNER_MAX_ALIVE - alive_children``.
* Killing a spawner always spawns a blueprint pickup; the picked
  module is one the player has not yet received (no inventory bp_*
  item) AND has not yet unlocked at a crafter.  If every pool key
  is already owned, fall back to a random one.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import arcade
import pytest

from constants import (
    MAZE_SPAWNER_INITIAL_ALIENS, MAZE_SPAWNER_MAX_ALIVE,
    MODULE_TYPES,
)


# ── Constant pinning ─────────────────────────────────────────────────────

class TestEntourageConstant:
    def test_initial_alien_count_is_ten(self):
        assert MAZE_SPAWNER_INITIAL_ALIENS == 10

    def test_initial_count_below_alive_cap(self):
        # The entourage must fit inside the alive-cap so a fresh
        # spawner can field its full set without immediately blocking
        # the per-30 s drip-spawn.
        assert MAZE_SPAWNER_INITIAL_ALIENS <= MAZE_SPAWNER_MAX_ALIVE


# ── MazeSpawner.just_respawned latch ─────────────────────────────────────

class TestSpawnerRespawnLatch:
    def test_constructed_starts_with_latch_set(self, monkeypatch):
        # A freshly-constructed spawner is "just spawned" too — the
        # zone setup pass clears the flag after handling it.
        from sprites.maze_spawner import MazeSpawner
        # Patch the texture loader so __init__ doesn't read disk.
        from sprites import maze_spawner as ms
        monkeypatch.setattr(ms, "_load_sprite",
                            lambda *a, **kw: arcade.Texture(
                                __import__("PIL.Image", fromlist=["Image"]).new(
                                    "RGBA", (32, 32), (0, 0, 0, 0))))
        sp = MazeSpawner(0.0, 0.0)
        assert sp.just_respawned is True

    def test_respawn_sets_latch(self, monkeypatch):
        from sprites.maze_spawner import MazeSpawner
        from sprites import maze_spawner as ms
        monkeypatch.setattr(ms, "_load_sprite",
                            lambda *a, **kw: arcade.Texture(
                                __import__("PIL.Image", fromlist=["Image"]).new(
                                    "RGBA", (32, 32), (0, 0, 0, 0))))
        sp = MazeSpawner(0.0, 0.0)
        # Simulate kill, then run the respawn timer to zero.
        sp.killed = True
        sp.visible = False
        sp.just_respawned = False   # zone has consumed the initial latch
        sp._respawn_cd = 0.001
        # Advance the timer past zero — the in-killed branch must
        # flip just_respawned True again.
        dummy_tex = arcade.Texture(
            __import__("PIL.Image", fromlist=["Image"]).new(
                "RGBA", (4, 4), (0, 0, 0, 0)))
        sp.update_spawner(0.016, 0.0, 0.0, dummy_tex)
        assert sp.killed is False
        assert sp.just_respawned is True

    def test_from_save_clears_latch(self, monkeypatch):
        from sprites.maze_spawner import MazeSpawner
        from sprites import maze_spawner as ms
        monkeypatch.setattr(ms, "_load_sprite",
                            lambda *a, **kw: arcade.Texture(
                                __import__("PIL.Image", fromlist=["Image"]).new(
                                    "RGBA", (32, 32), (0, 0, 0, 0))))
        sp = MazeSpawner(0.0, 0.0)
        sp.from_save_data({"hp": 100, "shields": 100, "killed": False,
                           "alive_children": 0})
        assert sp.just_respawned is False


# ── _player_owns_blueprint ───────────────────────────────────────────────

class _Inv:
    def __init__(self, items):
        self._items = items

    def count_item(self, name):
        return self._items.get(name, 0)


class TestPlayerOwnsBlueprint:
    def test_owned_via_ship_inventory(self):
        from combat_helpers import _player_owns_blueprint
        gv = SimpleNamespace(
            inventory=_Inv({"bp_armor_plate": 1}),
            _station_inv=_Inv({}),
            _craft_menu=SimpleNamespace(_unlocked=set()),
        )
        assert _player_owns_blueprint(gv, "armor_plate") is True

    def test_owned_via_station_inventory(self):
        from combat_helpers import _player_owns_blueprint
        gv = SimpleNamespace(
            inventory=_Inv({}),
            _station_inv=_Inv({"bp_force_wall": 1}),
            _craft_menu=SimpleNamespace(_unlocked=set()),
        )
        assert _player_owns_blueprint(gv, "force_wall") is True

    def test_owned_via_unlocked_recipe(self):
        from combat_helpers import _player_owns_blueprint
        gv = SimpleNamespace(
            inventory=_Inv({}),
            _station_inv=_Inv({}),
            _craft_menu=SimpleNamespace(_unlocked={"misty_step"}),
        )
        assert _player_owns_blueprint(gv, "misty_step") is True

    def test_unowned_returns_false(self):
        from combat_helpers import _player_owns_blueprint
        gv = SimpleNamespace(
            inventory=_Inv({}),
            _station_inv=_Inv({}),
            _craft_menu=SimpleNamespace(_unlocked=set()),
        )
        assert _player_owns_blueprint(gv, "armor_plate") is False


# ── spawn_unowned_blueprint_pickup ───────────────────────────────────────

class TestSpawnUnownedBlueprint:
    def _empty_gv(self):
        from PIL import Image
        tex = arcade.Texture(Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
        bp_drop_tex = {k: tex for k in MODULE_TYPES}
        return SimpleNamespace(
            inventory=_Inv({}),
            _station_inv=_Inv({}),
            _craft_menu=SimpleNamespace(_unlocked=set()),
            _blueprint_drop_tex=bp_drop_tex,
            _blueprint_tex=tex,
            blueprint_pickup_list=arcade.SpriteList(),
        )

    def test_drops_unowned_when_pool_has_unowned(self):
        from combat_helpers import spawn_unowned_blueprint_pickup
        gv = self._empty_gv()
        # Mark every key as owned EXCEPT mining_drone, then assert the
        # drop is mining_drone (only unowned in the pool).
        gv._craft_menu._unlocked = set(MODULE_TYPES.keys()) - {"mining_drone"}
        spawn_unowned_blueprint_pickup(gv, 100.0, 200.0)
        assert len(gv.blueprint_pickup_list) == 1
        assert gv.blueprint_pickup_list[0].module_type == "mining_drone"

    def test_falls_back_to_random_when_all_owned(self):
        # Every key owned → must still drop something (pick from full
        # pool randomly).  Pin RNG so the test is deterministic.
        import random
        from combat_helpers import spawn_unowned_blueprint_pickup
        gv = self._empty_gv()
        gv._craft_menu._unlocked = set(MODULE_TYPES.keys())
        random.seed(42)
        spawn_unowned_blueprint_pickup(gv, 0.0, 0.0)
        assert len(gv.blueprint_pickup_list) == 1
        assert (gv.blueprint_pickup_list[0].module_type
                in MODULE_TYPES.keys())

    def test_drops_at_given_position(self):
        from combat_helpers import spawn_unowned_blueprint_pickup
        gv = self._empty_gv()
        spawn_unowned_blueprint_pickup(gv, 1234.0, 5678.0)
        bp = gv.blueprint_pickup_list[0]
        assert bp.center_x == 1234.0
        assert bp.center_y == 5678.0


# ── End-to-end: initial entourage size ────────────────────────────────────

class TestInitialEntourageSizeInZoneSetup:
    """When the Star Maze sets up, each spawner must spawn with
    exactly MAZE_SPAWNER_INITIAL_ALIENS alive children (capped by
    the alive-cap).  4 spawners × 10 = 40 total at zone start."""

    def test_total_alien_count_after_setup(self):
        from game_view import GameView
        from zones import ZoneID
        from constants import STAR_MAZE_COUNT
        gv = GameView(faction="Earth", ship_type="Cruiser", ship_level=1)
        gv._transition_zone(ZoneID.STAR_MAZE, "bottom")
        zone = gv._zone
        assert len(zone._spawners) == STAR_MAZE_COUNT
        assert len(zone._maze_aliens) == (
            STAR_MAZE_COUNT * MAZE_SPAWNER_INITIAL_ALIENS)
        # alive_children on each spawner reflects its own entourage.
        for sp in zone._spawners:
            assert sp.alive_children == MAZE_SPAWNER_INITIAL_ALIENS
            assert sp.just_respawned is False  # latch consumed
