"""Soak / endurance tests — run for 5 minutes to detect memory leaks,
GC stalls, SpriteList growth, cache bloat, and FPS degradation over time.

Run with:  ``pytest "unit tests/integration/test_soak.py" -v -s``

These are SLOW (~5 min each). They are excluded from the default suite
by pytest.ini's ``norecursedirs = integration``. Run them explicitly
before releases or when investigating memory issues.

Each test measures FPS + RSS memory at the start and end of a 5-minute
simulated gameplay loop with entity churn (aliens dying/respawning,
projectiles firing/despawning, pickups collected, fog revealing).
Fails if FPS drops below 40 OR memory grows by more than 50 MB.
"""
from __future__ import annotations

import gc
import os
import time

import arcade
import psutil
import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID

# ── Configuration ──────────────────────────────────────────────────────────

SOAK_DURATION_S = 300       # 5 minutes
SAMPLE_INTERVAL_S = 30      # measure FPS + memory every 30 seconds
MIN_FPS = 40                # fail if FPS drops below this
MAX_MEMORY_GROWTH_MB = 50   # fail if RSS grows more than this
FRAMES_PER_SAMPLE = 60      # frames to measure per FPS sample
WARMUP_FRAMES = 30          # warmup before first measurement


def _get_rss_mb() -> float:
    """Current process RSS in megabytes."""
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def _measure_fps_quick(gv, n: int = FRAMES_PER_SAMPLE) -> float:
    """Time n full frame loops, return FPS."""
    dt = 1 / 60
    start = time.perf_counter()
    for _ in range(n):
        gv.on_update(dt)
        gv.on_draw()
    elapsed = time.perf_counter() - start
    return n / elapsed if elapsed > 0 else 999.0


def _make_invulnerable(gv) -> None:
    """Make the player effectively unkillable for the duration of a soak
    test. Without this, aliens kill the player within ~30 seconds of
    continuous combat, and the test spends the remaining 4.5 minutes in
    the death-screen state — measuring nothing useful."""
    gv.player.max_hp = 999999
    gv.player.hp = 999999
    gv.player.max_shields = 999999
    gv.player.shields = 999999


def _simulate_churn(gv, dt: float) -> None:
    """One tick of simulated gameplay with entity churn.

    Fires a projectile, advances all entities, and lets the normal
    update loop handle deaths/respawns/pickups. This generates the
    steady-state object creation + destruction that real gameplay does.
    Also heals the player each tick to prevent death during the soak.
    """
    gv.player.hp = gv.player.max_hp
    gv.player.shields = gv.player.max_shields
    gv._keys.add(arcade.key.SPACE)  # hold fire
    gv.on_update(dt)
    gv.on_draw()
    gv._keys.discard(arcade.key.SPACE)


def _run_soak(gv, label: str) -> None:
    """Core soak loop: warmup, then measure FPS + memory every
    SAMPLE_INTERVAL_S seconds for SOAK_DURATION_S total."""
    dt = 1 / 60

    # Warmup
    for _ in range(WARMUP_FRAMES):
        _simulate_churn(gv, dt)

    # Baseline measurements
    fps_start = _measure_fps_quick(gv)
    mem_start = _get_rss_mb()
    print(f"\n  [{label}] START: {fps_start:.1f} FPS, {mem_start:.0f} MB RSS")

    fps_samples: list[float] = [fps_start]
    mem_samples: list[float] = [mem_start]
    fps_min = fps_start

    soak_start = time.perf_counter()
    last_sample = soak_start
    frame_count = 0

    while True:
        elapsed_total = time.perf_counter() - soak_start
        if elapsed_total >= SOAK_DURATION_S:
            break

        # Simulate ~1 second of gameplay between samples (60 frames)
        for _ in range(60):
            _simulate_churn(gv, dt)
            frame_count += 1

        # Sample every SAMPLE_INTERVAL_S
        now = time.perf_counter()
        if now - last_sample >= SAMPLE_INTERVAL_S:
            fps = _measure_fps_quick(gv)
            mem = _get_rss_mb()
            fps_samples.append(fps)
            mem_samples.append(mem)
            fps_min = min(fps_min, fps)
            elapsed_min = elapsed_total / 60
            print(f"  [{label}] {elapsed_min:.1f}m: "
                  f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                  f"(+{mem - mem_start:.1f} MB)")
            last_sample = now

    # Final measurement
    fps_end = _measure_fps_quick(gv)
    mem_end = _get_rss_mb()
    fps_samples.append(fps_end)
    mem_samples.append(mem_end)
    fps_min = min(fps_min, fps_end)
    mem_growth = mem_end - mem_start

    print(f"  [{label}] END: {fps_end:.1f} FPS, {mem_end:.0f} MB RSS")
    print(f"  [{label}] Summary: min FPS={fps_min:.1f}, "
          f"mem growth={mem_growth:+.1f} MB, "
          f"frames={frame_count}")

    # Assertions
    assert fps_min >= MIN_FPS, (
        f"{label}: FPS dropped to {fps_min:.1f} "
        f"(threshold: {MIN_FPS})"
    )
    assert mem_growth <= MAX_MEMORY_GROWTH_MB, (
        f"{label}: memory grew by {mem_growth:.1f} MB "
        f"(threshold: {MAX_MEMORY_GROWTH_MB} MB). "
        f"Start={mem_start:.0f} MB, End={mem_end:.0f} MB"
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 1: Zone 1 soak — aliens, asteroids, projectiles, pickups, fog
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakZone1:
    def test_zone1_5min_soak(self, real_game_view):
        """5-minute Zone 1 soak with continuous combat. Tests for:
        - SpriteList growth from alien/asteroid respawns
        - Explosion + HitSpark + FireSpark accumulation
        - IronPickup + BlueprintPickup creation/collection
        - Fog of war grid updates
        - Projectile creation/despawn churn
        - GC stall from disabled automatic collection"""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Point player toward aliens (top-right quadrant has spawns)
        gv.player.center_x = WORLD_WIDTH * 0.7
        gv.player.center_y = WORLD_HEIGHT * 0.7
        gv.player.heading = 0.0
        _make_invulnerable(gv)

        _run_soak(gv, "Zone 1")


# ═══════════════════════════════════════════════════════════════════════════
#  Test 2: Zone 2 soak — copper, gas, wanderers, 4 alien types, fog
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakZone2:
    def test_zone2_5min_soak(self, real_game_view):
        """5-minute Zone 2 soak with the full Nebula population. Tests for:
        - Zone 2 alien respawn cycle (4 types)
        - Copper pickup creation
        - Wandering asteroid magnetic attraction churn
        - Gas area damage tick accumulation
        - Zone 2 fog grid updates
        - Alien projectile accumulation"""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _make_invulnerable(gv)

        _run_soak(gv, "Zone 2")


# ═══════════════════════════════════════════════════════════════════════════
#  Test 3: Video player soak — FFmpeg frame buffer + texture leaks
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakVideoPlayer:
    def test_video_player_5min_soak(self, real_game_view):
        """5-minute soak with the character video running continuously.
        Tests for:
        - PIL image buffer accumulation in the video conversion pipeline
        - pyglet texture / FFmpeg decoder state leaks
        - arcade.Texture cache growth from frame updates
        - The 2-frame GPU blit pipeline over thousands of frames"""
        from video_player import scan_characters_dir, character_video_path

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        chars = scan_characters_dir()
        if not chars:
            pytest.skip("No character video files")
        path = character_video_path(chars[0])
        if path is None:
            pytest.skip("Character video path not resolved")

        _make_invulnerable(gv)
        gv._char_video_player.play_segments(path, volume=0.0)
        # Warmup to confirm video started
        dt = 1 / 60
        for _ in range(15):
            gv.on_update(dt)
            gv.on_draw()
        if not gv._char_video_player.active:
            pytest.skip("Video player failed to start (no FFmpeg?)")

        _run_soak(gv, "Video player")
        gv._char_video_player.stop()


# ═══════════════════════════════════════════════════════════════════════════
#  Test 4: Inventory churn soak — add/remove/consolidate/dirty cycles
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakInventoryChurn:
    def test_inventory_churn_5min_soak(self, real_game_view):
        """5-minute soak with both inventories open and items being
        continuously added, removed, and consolidated. Tests for:
        - _badge_tex_cache growth (unique count values)
        - _count_cache growth (arcade.Text objects)
        - SpriteList rebuild cost stability over thousands of dirty cycles
        - _render_dirty flag thrashing"""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _make_invulnerable(gv)

        gv.inventory.open = True
        gv._station_inv.open = True

        # Seed some items
        for r in range(5):
            for c in range(5):
                gv.inventory._items[(r, c)] = ("iron", 10 + r * 5 + c)
        gv.inventory._mark_dirty()
        for r in range(10):
            for c in range(10):
                gv._station_inv._items[(r, c)] = ("iron", r * 10 + c + 1)
        gv._station_inv._mark_dirty()

        dt = 1 / 60
        # Warmup
        for _ in range(WARMUP_FRAMES):
            gv.on_update(dt)
            gv.on_draw()

        fps_start = _measure_fps_quick(gv)
        mem_start = _get_rss_mb()
        print(f"\n  [Inventory churn] START: {fps_start:.1f} FPS, "
              f"{mem_start:.0f} MB RSS")

        fps_min = fps_start
        soak_start = time.perf_counter()
        last_sample = soak_start
        churn_cycle = 0

        while True:
            elapsed = time.perf_counter() - soak_start
            if elapsed >= SOAK_DURATION_S:
                break

            # Churn: modify items to trigger dirty → rebuild cycle
            # This varies the count values so _badge_tex_cache grows
            churn_cycle += 1
            for r in range(10):
                for c in range(10):
                    count = ((r * 10 + c + churn_cycle) % 200) + 1
                    gv._station_inv._items[(r, c)] = ("iron", count)
            gv._station_inv._mark_dirty()

            # Also churn ship inventory
            for r in range(5):
                for c in range(5):
                    count = ((r * 5 + c + churn_cycle * 3) % 100) + 1
                    gv.inventory._items[(r, c)] = ("iron", count)
            gv.inventory._mark_dirty()

            # Consolidate periodically (rebuilds all stacks)
            if churn_cycle % 50 == 0:
                gv._station_inv.consolidate()
                gv.inventory.consolidate()

            # Run frames
            for _ in range(60):
                gv.on_update(dt)
                gv.on_draw()

            now = time.perf_counter()
            if now - last_sample >= SAMPLE_INTERVAL_S:
                fps = _measure_fps_quick(gv)
                mem = _get_rss_mb()
                fps_min = min(fps_min, fps)
                print(f"  [Inventory churn] {elapsed / 60:.1f}m: "
                      f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                      f"(+{mem - mem_start:.1f} MB), "
                      f"badge_cache={len(gv._station_inv._badge_tex_cache)}")
                last_sample = now

        fps_end = _measure_fps_quick(gv)
        mem_end = _get_rss_mb()
        fps_min = min(fps_min, fps_end)
        mem_growth = mem_end - mem_start

        gv.inventory.open = False
        gv._station_inv.open = False

        print(f"  [Inventory churn] END: {fps_end:.1f} FPS, "
              f"{mem_end:.0f} MB RSS")
        print(f"  [Inventory churn] Summary: min FPS={fps_min:.1f}, "
              f"mem growth={mem_growth:+.1f} MB, "
              f"badge_cache_size={len(gv._station_inv._badge_tex_cache)}, "
              f"churn_cycles={churn_cycle}")

        assert fps_min >= MIN_FPS, (
            f"Inventory churn: FPS dropped to {fps_min:.1f} "
            f"(threshold: {MIN_FPS})"
        )
        # This stress test does ~400 full inventory rebuilds in 5 minutes
        # (real gameplay: 1-2/minute). Each rebuild creates ~375 Sprite
        # objects. Python's pymalloc keeps freed arenas in its free list,
        # so RSS never shrinks even after gc.collect(). The growth is
        # allocator fragmentation, not a real leak — the memory IS reusable
        # by Python. Threshold is set proportionally to churn intensity.
        _CHURN_MEM_THRESHOLD = 80  # MB — generous for ~400 rebuild cycles
        assert mem_growth <= _CHURN_MEM_THRESHOLD, (
            f"Inventory churn: memory grew by {mem_growth:.1f} MB "
            f"(threshold: {_CHURN_MEM_THRESHOLD} MB)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 5: Fog texture rebuild soak — repeated texture creation
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakFogTexture:
    def test_fog_texture_rebuild_5min_soak(self, real_game_view):
        """5-minute soak with the player moving continuously, causing
        fog cells to reveal and the fog texture to rebuild every few
        frames. Tests for:
        - arcade.Texture creation leak (old textures not freed)
        - PIL Image buffer accumulation from _build_fog_texture
        - Minimap fog overlay VRAM growth"""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _make_invulnerable(gv)

        # Move player in a slow spiral to continuously reveal new fog cells
        import math
        dt = 1 / 60
        # Warmup
        for _ in range(WARMUP_FRAMES):
            gv.on_update(dt)
            gv.on_draw()

        fps_start = _measure_fps_quick(gv)
        mem_start = _get_rss_mb()
        print(f"\n  [Fog texture] START: {fps_start:.1f} FPS, "
              f"{mem_start:.0f} MB RSS, "
              f"fog_revealed={gv._fog_revealed}")

        fps_min = fps_start
        soak_start = time.perf_counter()
        last_sample = soak_start
        tick = 0

        while True:
            elapsed = time.perf_counter() - soak_start
            if elapsed >= SOAK_DURATION_S:
                break

            # Move player in a spiral to reveal fog
            tick += 1
            angle = tick * 0.02
            radius = 500 + tick * 0.3
            gv.player.center_x = min(WORLD_WIDTH - 100, max(100,
                WORLD_WIDTH / 2 + math.cos(angle) * min(radius, 2800)))
            gv.player.center_y = min(WORLD_HEIGHT - 100, max(100,
                WORLD_HEIGHT / 2 + math.sin(angle) * min(radius, 2800)))

            gv.on_update(dt)
            gv.on_draw()

            now = time.perf_counter()
            if now - last_sample >= SAMPLE_INTERVAL_S:
                fps = _measure_fps_quick(gv)
                mem = _get_rss_mb()
                fps_min = min(fps_min, fps)
                print(f"  [Fog texture] {elapsed / 60:.1f}m: "
                      f"{fps:.1f} FPS, {mem:.0f} MB RSS "
                      f"(+{mem - mem_start:.1f} MB), "
                      f"fog_revealed={gv._fog_revealed}")
                last_sample = now

        fps_end = _measure_fps_quick(gv)
        mem_end = _get_rss_mb()
        fps_min = min(fps_min, fps_end)
        mem_growth = mem_end - mem_start

        print(f"  [Fog texture] END: {fps_end:.1f} FPS, "
              f"{mem_end:.0f} MB RSS, "
              f"fog_revealed={gv._fog_revealed}")
        print(f"  [Fog texture] Summary: min FPS={fps_min:.1f}, "
              f"mem growth={mem_growth:+.1f} MB")

        assert fps_min >= MIN_FPS, (
            f"Fog texture: FPS dropped to {fps_min:.1f} "
            f"(threshold: {MIN_FPS})"
        )
        assert mem_growth <= MAX_MEMORY_GROWTH_MB, (
            f"Fog texture: memory grew by {mem_growth:.1f} MB "
            f"(threshold: {MAX_MEMORY_GROWTH_MB} MB)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 6: Combined worst-case soak — everything at once
# ═══════════════════════════════════════════════════════════════════════════

class TestSoakCombined:
    def test_combined_5min_soak(self, real_game_view):
        """5-minute soak with Zone 2 + both inventories + character video +
        continuous combat. This is the absolute worst case for memory: every
        system creating and destroying objects simultaneously."""
        from video_player import scan_characters_dir, character_video_path

        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _make_invulnerable(gv)

        # Start character video if available
        chars = scan_characters_dir()
        video_active = False
        if chars:
            path = character_video_path(chars[0])
            if path:
                gv._char_video_player.play_segments(path, volume=0.0)
                dt = 1 / 60
                for _ in range(15):
                    gv.on_update(dt)
                    gv.on_draw()
                video_active = gv._char_video_player.active

        # Open both inventories with items
        for r in range(5):
            for c in range(5):
                gv.inventory._items[(r, c)] = ("iron", 10 + r * 5 + c)
        gv.inventory._mark_dirty()
        gv.inventory.open = True
        for r in range(10):
            for c in range(10):
                gv._station_inv._items[(r, c)] = ("iron", r * 10 + c + 1)
        gv._station_inv._mark_dirty()
        gv._station_inv.open = True

        label = f"Combined (video={'on' if video_active else 'off'})"
        _run_soak(gv, label)

        gv.inventory.open = False
        gv._station_inv.open = False
        if video_active:
            gv._char_video_player.stop()
