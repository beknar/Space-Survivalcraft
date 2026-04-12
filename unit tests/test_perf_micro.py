"""Microbenchmark performance tests — pure-Python computation, no Arcade window.

These test that individual systems stay within their per-frame time budget.
At 40 FPS the total frame budget is 25 ms. No single subsystem should
consume more than 5 ms or the frame budget is blown before rendering even
starts.

These run in the fast suite (~0.1 s total) and catch algorithmic regressions
like accidental O(N²) loops or per-call overhead creep. They do NOT test
GPU/rendering performance — that's what the integration perf tests are for.

Thresholds are deliberately generous (2–5× headroom over measured baseline)
so they don't flake on slower CI machines. If a test fails, something
got asymptotically worse, not just a bit slower.
"""
from __future__ import annotations

import math
import time
from types import SimpleNamespace

import arcade
import pytest

# ── Budget constants (milliseconds) ───────────────────────────────────────
# Each budget is ~3× the measured baseline on the dev machine.

COLLISION_BUDGET_MS = 2.0    # 60 resolve_overlap + reflect_velocity calls
INVENTORY_BUDGET_MS = 2.0    # 100 add_item + count_item + remove_item cycles
FOG_BUDGET_MS = 1.0          # one fog-reveal pass over a 128×128 grid
ALIEN_AI_BUDGET_MS = 5.0     # 60 alien update_alien calls
SAVE_BUDGET_MS = 10.0        # save_to_dict on a populated GameView-like dict
CONSOLIDATE_BUDGET_MS = 2.0  # consolidate 100 items into stacks


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


# ═══════════════════════════════════════════════════════════════════════════
#  Collision physics primitives
# ═══════════════════════════════════════════════════════════════════════════

class TestCollisionPerf:
    def test_resolve_and_reflect_60_pairs(self):
        """60 overlapping body-pairs resolved + reflected in < 2 ms.
        This matches the worst case: 60 Zone 2 aliens all colliding
        with asteroids in a single frame."""
        from collisions import resolve_overlap, reflect_velocity

        bodies_a = [SimpleNamespace(center_x=float(i), center_y=0.0,
                                    vel_x=10.0, vel_y=0.0) for i in range(60)]
        bodies_b = [SimpleNamespace(center_x=float(i) + 5.0, center_y=0.0,
                                    vel_x=-5.0, vel_y=0.0) for i in range(60)]

        start = time.perf_counter()
        for a, b in zip(bodies_a, bodies_b):
            contact = resolve_overlap(a, b, 10.0, 10.0, 0.5, 0.5)
            if contact:
                nx, ny = contact
                reflect_velocity(a, nx, ny, 0.55)
        elapsed = _ms(start)

        assert elapsed < COLLISION_BUDGET_MS, (
            f"60 collision resolves took {elapsed:.2f} ms "
            f"(budget: {COLLISION_BUDGET_MS} ms)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Inventory operations
# ═══════════════════════════════════════════════════════════════════════════

class TestInventoryPerf:
    def test_add_count_remove_100_items(self):
        """100 cycles of add_item + count_item + remove_item in < 2 ms.
        Simulates a full station inventory being restocked each frame."""
        from inventory import Inventory
        inv = Inventory(iron_icon=None)

        start = time.perf_counter()
        for i in range(100):
            inv.add_item("iron", 10)
            inv.count_item("iron")
            inv.remove_item("iron", 5)
        elapsed = _ms(start)

        assert elapsed < INVENTORY_BUDGET_MS, (
            f"100 add/count/remove cycles took {elapsed:.2f} ms "
            f"(budget: {INVENTORY_BUDGET_MS} ms)"
        )

    def test_total_iron_100_cells(self):
        """total_iron property scans all cells — 100 cells in < 0.5 ms."""
        from station_inventory import StationInventory
        inv = StationInventory()
        for r in range(10):
            for c in range(10):
                inv._items[(r, c)] = ("iron", r * 10 + c + 1)

        start = time.perf_counter()
        for _ in range(100):
            _ = inv.total_iron
        elapsed = _ms(start)

        assert elapsed < 1.0, (
            f"100× total_iron on 100 cells took {elapsed:.2f} ms"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Inventory consolidate
# ═══════════════════════════════════════════════════════════════════════════

class TestConsolidatePerf:
    def test_consolidate_100_scattered_items(self):
        """Consolidating 100 cells of mixed items into neat stacks in < 2 ms."""
        from station_inventory import StationInventory
        inv = StationInventory()
        types = ["iron", "copper", "repair_pack", "missile", "shield_recharge"]
        for r in range(10):
            for c in range(10):
                inv._items[(r, c)] = (types[(r + c) % len(types)], 5)

        start = time.perf_counter()
        for _ in range(10):
            inv.consolidate()
            # Re-scatter for next iteration
            for r in range(10):
                for c in range(10):
                    inv._items[(r, c)] = (types[(r + c) % len(types)], 5)
        elapsed = _ms(start)

        assert elapsed < CONSOLIDATE_BUDGET_MS, (
            f"10× consolidate(100 cells) took {elapsed:.2f} ms "
            f"(budget: {CONSOLIDATE_BUDGET_MS} ms)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Fog of war grid operations
# ═══════════════════════════════════════════════════════════════════════════

class TestFogPerf:
    def test_fog_reveal_pass(self):
        """One fog-reveal pass (checking ~50 cells around the player
        on a 128×128 grid) in < 1 ms."""
        from constants import FOG_CELL_SIZE, FOG_REVEAL_RADIUS, FOG_GRID_W, FOG_GRID_H

        fog = [[False] * FOG_GRID_W for _ in range(FOG_GRID_H)]
        px, py = 3200.0, 3200.0  # centre of a 6400 world
        cell_size = FOG_CELL_SIZE
        reveal_r = FOG_REVEAL_RADIUS

        def reveal():
            cx = int(px / cell_size)
            cy = int(py / cell_size)
            r = int(reveal_r / cell_size) + 1
            count = 0
            for gy in range(max(0, cy - r), min(FOG_GRID_H, cy + r + 1)):
                for gx in range(max(0, cx - r), min(FOG_GRID_W, cx + r + 1)):
                    if not fog[gy][gx]:
                        cell_cx = (gx + 0.5) * cell_size
                        cell_cy = (gy + 0.5) * cell_size
                        if math.hypot(px - cell_cx, py - cell_cy) <= reveal_r:
                            fog[gy][gx] = True
                            count += 1
            return count

        start = time.perf_counter()
        for _ in range(100):
            # Reset a patch so there's work to do
            cx = int(px / cell_size)
            cy = int(py / cell_size)
            for gy in range(max(0, cy - 3), min(FOG_GRID_H, cy + 4)):
                for gx in range(max(0, cx - 3), min(FOG_GRID_W, cx + 4)):
                    fog[gy][gx] = False
            reveal()
        elapsed = _ms(start)

        assert elapsed < FOG_BUDGET_MS * 100, (
            f"100 fog reveal passes took {elapsed:.2f} ms "
            f"(budget: {FOG_BUDGET_MS * 100} ms)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Alien AI update (math only, no rendering)
# ═══════════════════════════════════════════════════════════════════════════

class TestAlienAIPerf:
    def test_60_alien_updates(self, dummy_texture):
        """60 Zone 2 alien AI updates (move, fire check, state transition)
        in < 5 ms. This is the per-frame CPU cost of the Nebula zone's
        alien population."""
        from sprites.zone2_aliens import ShieldedAlien, FastAlien, GunnerAlien, RammerAlien

        aliens = []
        empty_list = arcade.SpriteList()
        alien_list = arcade.SpriteList()
        for i in range(15):
            aliens.append(ShieldedAlien(dummy_texture, dummy_texture,
                                        100 + i * 200, 100 + i * 200))
        for i in range(15):
            aliens.append(FastAlien(dummy_texture, dummy_texture,
                                    200 + i * 200, 200 + i * 200))
        for i in range(15):
            aliens.append(GunnerAlien(dummy_texture, dummy_texture,
                                      300 + i * 200, 300 + i * 200))
        for i in range(15):
            aliens.append(RammerAlien(dummy_texture, dummy_texture,
                                      400 + i * 200, 400 + i * 200))
        for a in aliens:
            alien_list.append(a)

        px, py = 3200.0, 3200.0
        dt = 1 / 60

        # Warmup
        for a in aliens:
            a.update_alien(dt, px, py, empty_list, alien_list)

        start = time.perf_counter()
        for _ in range(10):  # 10 frames of 60 aliens = 600 AI updates
            for a in aliens:
                a.update_alien(dt, px, py, empty_list, alien_list)
        elapsed = _ms(start)
        per_frame = elapsed / 10

        assert per_frame < ALIEN_AI_BUDGET_MS, (
            f"60 alien AI updates per frame: {per_frame:.2f} ms "
            f"(budget: {ALIEN_AI_BUDGET_MS} ms)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Minimap point collection (computation, not rendering)
# ═══════════════════════════════════════════════════════════════════════════

class TestMinimapCollectionPerf:
    def test_200_sprites_fog_check_and_mapping(self, dummy_texture):
        """Collecting 200 sprite positions through fog-check + coordinate
        mapping in < 2 ms. This is the CPU cost of building the
        draw_points arrays for the minimap each frame."""
        from constants import FOG_CELL_SIZE, FOG_GRID_W, FOG_GRID_H
        from hud_minimap import is_revealed

        fog = [[True] * FOG_GRID_W for _ in range(FOG_GRID_H)]
        sprites = []
        for i in range(200):
            s = arcade.Sprite(dummy_texture)
            s.center_x = (i % 20) * 300.0 + 100
            s.center_y = (i // 20) * 600.0 + 100
            sprites.append(s)

        zone_w, zone_h = 6400.0, 6400.0
        mx, my, mw, mh = 10, 10, 180, 140

        start = time.perf_counter()
        for _ in range(100):
            pts = []
            sx_w = mw / zone_w
            sy_h = mh / zone_h
            for s in sprites:
                wx, wy = s.center_x, s.center_y
                if is_revealed(wx, wy, fog):
                    pts.append((mx + wx * sx_w, my + wy * sy_h))
        elapsed = _ms(start)
        per_frame = elapsed / 100

        assert per_frame < 2.0, (
            f"200-sprite minimap collection: {per_frame:.2f} ms/frame "
            f"(budget: 2.0 ms)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Save serialization (dict construction, not file I/O)
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveSerializationPerf:
    def test_serialize_75_asteroids_30_aliens(self, dummy_texture):
        """Serializing 75 asteroids + 30 aliens to dicts in < 10 ms.
        This is the CPU cost of save_to_dict's entity loops."""
        from game_save import _serialize_asteroid, _serialize_alien
        from sprites.asteroid import IronAsteroid
        from sprites.alien import SmallAlienShip

        asteroids = [IronAsteroid(dummy_texture, i * 80, i * 80)
                     for i in range(75)]
        aliens = [SmallAlienShip(dummy_texture, dummy_texture, i * 200, i * 200)
                  for i in range(30)]

        start = time.perf_counter()
        for _ in range(100):  # 100 simulated saves
            a_data = [_serialize_asteroid(a) for a in asteroids]
            al_data = [_serialize_alien(al) for al in aliens]
        elapsed = _ms(start)
        per_save = elapsed / 100

        assert per_save < SAVE_BUDGET_MS, (
            f"Serialize 75 asteroids + 30 aliens: {per_save:.2f} ms "
            f"(budget: {SAVE_BUDGET_MS} ms)"
        )
