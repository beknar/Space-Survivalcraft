"""Performance integration tests — asteroid explosion animation.

Frame-time / FPS coverage for the 10-frame Explo__001..010.png
asteroid-explosion sprite (a heavier draw than the old single-frame
explosion):

  * 20 simultaneous asteroid explosions in Zone 1.
  * 20 simultaneous asteroid explosions in Zone 2.
  * 20 simultaneous asteroid explosions in Zone 2 + both videos.
  * Sustained mining: 2 explosions spawned every measurement frame
    so the live list averages ~15 instances.

Run with:  ``pytest "unit tests/integration/test_performance_explosions.py" -v``
"""
from __future__ import annotations

import time

import arcade
import pytest

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BUILDING_TYPES, MODULE_SLOT_COUNT,
)
from zones import ZoneID

# ── Configuration ──────────────────────────────────────────────────────────

MIN_FPS = 40

# Use shared measure_fps from conftest
from integration.conftest import measure_fps as _measure_fps


# ═══════════════════════════════════════════════════════════════════════════
#  Video helpers — start/stop char + music videos
# ═══════════════════════════════════════════════════════════════════════════

def _get_video_paths():
    """Return up to 2 character video paths, or skip."""
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
    return paths


def _start_both_videos_or_skip(gv):
    """Start BOTH the character video and the music video player."""
    paths = _get_video_paths()
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    music_path = paths[1] if len(paths) > 1 else paths[0]
    gv._video_player.play(music_path, volume=0.0)
    dt = 1 / 60
    for _ in range(10):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._char_video_player.active and not gv._video_player.active:
        pytest.skip("Neither video player started (no FFmpeg?)")


def _stop_both_videos(gv):
    """Stop both video players and clean up."""
    gv._char_video_player.stop()
    gv._video_player.stop()


# ═══════════════════════════════════════════════════════════════════════════
#  Asteroid explosion animation — 10-frame Explo__001..010.png draw
# ═══════════════════════════════════════════════════════════════════════════

def _spawn_n_asteroid_explosions(gv, n: int) -> None:
    """Populate the explosion list with N asteroid explosions at
    scattered world positions to simulate a heavy-mining frame."""
    from sprites.explosion import Explosion
    from constants import WORLD_WIDTH, WORLD_HEIGHT
    import random as _r
    for _ in range(n):
        x = _r.uniform(100, WORLD_WIDTH - 100)
        y = _r.uniform(100, WORLD_HEIGHT - 100)
        gv.explosion_list.append(
            Explosion(gv._asteroid_explosion_frames, x, y))


class TestAsteroidExplosionBurstZone1:
    def test_20_asteroid_explosions_zone1_above_threshold(
            self, real_game_view):
        """20 simultaneous asteroid explosions in Zone 1 — simulates a
        mining frenzy frame with the new 10-frame animation."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _spawn_n_asteroid_explosions(gv, 20)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 1 + 20 asteroid explosions: {fps:.1f} FPS < {MIN_FPS}")


class TestAsteroidExplosionBurstZone2:
    def test_20_asteroid_explosions_zone2_above_threshold(
            self, real_game_view):
        """Same burst in the heavier Nebula zone."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _spawn_n_asteroid_explosions(gv, 20)
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 + 20 asteroid explosions: {fps:.1f} FPS < {MIN_FPS}")


class TestAsteroidExplosionBurstZone2WithVideos:
    def test_20_asteroid_explosions_zone2_with_videos_above_threshold(
            self, real_game_view):
        """Worst case: Zone 2 + 20 asteroid explosions + both videos."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _spawn_n_asteroid_explosions(gv, 20)
        _start_both_videos_or_skip(gv)
        try:
            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Zone 2 + 20 asteroid explosions + videos: "
                f"{fps:.1f} FPS < {MIN_FPS}")
        finally:
            _stop_both_videos(gv)


class TestAsteroidExplosionSustainedMining:
    def test_sustained_mining_spawns_asteroid_explosions_above_threshold(
            self, real_game_view):
        """Simulate sustained mining: spawn 2 asteroid explosions every
        measurement frame so the explosion list averages ~15 live
        instances. Catches any per-frame cost tied to iterating the
        list or advancing frame indexes."""
        from sprites.explosion import Explosion
        import random as _r
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        import time as _time
        dt = 1 / 60
        # Warm-up that drips 2 explosions per frame.
        for _ in range(10):
            for _ in range(2):
                gv.explosion_list.append(Explosion(
                    gv._asteroid_explosion_frames,
                    _r.uniform(100, 6000), _r.uniform(100, 6000)))
            gv.on_update(dt)
            gv.on_draw()
        n = 60
        start = _time.perf_counter()
        for _ in range(n):
            for _ in range(2):
                gv.explosion_list.append(Explosion(
                    gv._asteroid_explosion_frames,
                    _r.uniform(100, 6000), _r.uniform(100, 6000)))
            gv.on_update(dt)
            gv.on_draw()
        elapsed = _time.perf_counter() - start
        fps = n / elapsed if elapsed > 0 else 999.0
        print(f"  [perf] sustained-mining: {fps:.1f} FPS "
              f"({n} frames in {elapsed:.3f}s)")
        assert fps >= MIN_FPS, (
            f"Sustained asteroid-explosion mining: {fps:.1f} FPS < {MIN_FPS}")
