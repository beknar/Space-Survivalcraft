"""Performance integration tests — warp zones.

Frame-time / FPS coverage for the four themed warp-zone variants
under their hardest conditions:

  * Enemy warp zone — 4 spawners producing 20+ mini-aliens.
  * Meteor warp zone — meteors raining + both videos + firing + fog.
  * Lightning warp zone — 10–20 jagged bolts per volley + videos.
  * Gas warp zone — ~36 drifting gas clouds + videos.
  * Enemy warp zone with extra forced spawn waves + videos.

Run with:  ``pytest "unit tests/integration/test_performance_warp_zones.py" -v``
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
#  Video helpers — start/stop character + music videos
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
    """Start BOTH the character video and the music video player.
    Uses two different character .mp4 files as stand-ins (same FFmpeg
    decode + GPU blit pipeline). Skips if fewer than 2 video files exist
    or FFmpeg is unavailable."""
    paths = _get_video_paths()
    # Character video (small 160×160 portrait)
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    # Music video (larger 16:9 panel) — use a second file if available,
    # otherwise reuse the same file (still exercises both decode pipelines)
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
#  Warp enemy zone — 4 spawners producing 20+ mini-aliens
# ═══════════════════════════════════════════════════════════════════════════

class TestWarpEnemyZone:
    def test_warp_enemy_zone_above_threshold(self, real_game_view):
        """Enemy Spawner warp zone with 4 spawner stations each producing
        waves of mini-aliens. After a few spawn cycles there are 20+
        aliens in a small arena, all pursuing and firing at the player."""
        gv = real_game_view
        gv._transition_zone(ZoneID.WARP_ENEMY, entry_side="bottom")
        assert gv._zone.zone_id == ZoneID.WARP_ENEMY

        # Force several spawn waves so alien count builds up.
        # _spawn_timer starts at 5.0 and _SPAWN_INTERVAL is the reset.
        # Setting it to 0 triggers an immediate wave per update tick.
        zone = gv._zone
        for _ in range(4):
            zone._spawn_timer = 0.0
            zone.update(gv, 1 / 60)

        alien_count = len(zone._aliens)

        # Now measure with all those aliens active
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Warp enemy zone ({alien_count} aliens): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: warp zone setup with videos + player firing + fog reveal
# ═══════════════════════════════════════════════════════════════════════════

def _setup_warp_zone_test(gv, zone_id):
    """Transition to a warp zone, start both videos, hold fire,
    and advance a few frames to populate hazards and reveal fog."""
    import math
    gv._transition_zone(zone_id, entry_side="bottom")
    assert gv._zone.zone_id == zone_id

    # Start both video players
    _start_both_videos_or_skip(gv)

    # Move player upward and hold fire to reveal fog + generate projectiles
    gv.player.center_x = gv._zone.world_width / 2
    gv.player.center_y = 400
    gv._keys.add(arcade.key.SPACE)  # fire weapon
    gv._keys.add(arcade.key.W)      # thrust forward

    dt = 1 / 60
    # Advance frames to populate hazards and reveal fog
    for i in range(30):
        # Slowly move player up to reveal fog cells
        gv.player.center_y = min(gv.player.center_y + 20,
                                  gv._zone.world_height - 200)
        gv.on_update(dt)
        gv.on_draw()

    gv._keys.discard(arcade.key.W)
    # Keep firing during measurement
    # gv._keys still has SPACE


def _teardown_warp_zone_test(gv):
    """Stop videos and release keys."""
    gv._keys.discard(arcade.key.SPACE)
    _stop_both_videos(gv)


# ═══════════════════════════════════════════════════════════════════════════
#  All four warp zones with videos + firing + fog
# ═══════════════════════════════════════════════════════════════════════════

class TestWarpMeteorFull:
    def test_warp_meteor_full_above_threshold(self, real_game_view):
        """Meteor warp zone with meteors raining from all edges, both
        videos playing, player firing mining beam, and fog revealing.
        Meteors spawn every 0.15s — after 30 warmup frames there are
        ~30 meteors in flight."""
        gv = real_game_view
        _setup_warp_zone_test(gv, ZoneID.WARP_METEOR)

        fps = _measure_fps(gv, n_warmup=10)
        _teardown_warp_zone_test(gv)

        assert fps >= MIN_FPS, (
            f"Warp Meteor full: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


class TestWarpLightningFull:
    def test_warp_lightning_full_above_threshold(self, real_game_view):
        """Lightning warp zone with 10-20 bolts per volley firing every
        0.3-1.5s, both videos playing, player firing basic laser, and
        fog revealing. Each bolt is drawn as a 4-segment jagged line."""
        gv = real_game_view
        _setup_warp_zone_test(gv, ZoneID.WARP_LIGHTNING)

        fps = _measure_fps(gv, n_warmup=10)
        _teardown_warp_zone_test(gv)

        assert fps >= MIN_FPS, (
            f"Warp Lightning full: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


class TestWarpGasFull:
    def test_warp_gas_full_above_threshold(self, real_game_view):
        """Gas cloud warp zone with ~36 gas clouds (incl. 3 extra-large
        at 1500px), both videos playing, player firing, and fog revealing.
        Gas clouds drift with Brownian motion and damage on contact."""
        gv = real_game_view
        _setup_warp_zone_test(gv, ZoneID.WARP_GAS)

        fps = _measure_fps(gv, n_warmup=10)
        _teardown_warp_zone_test(gv)

        assert fps >= MIN_FPS, (
            f"Warp Gas full: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


class TestWarpEnemyFull:
    def test_warp_enemy_full_above_threshold(self, real_game_view):
        """Enemy spawner warp zone with 4 spawners, ~24 mini-aliens after
        force-spawning waves, both videos playing, player firing basic
        laser, and fog revealing. Spawners and aliens both fire at player."""
        gv = real_game_view
        _setup_warp_zone_test(gv, ZoneID.WARP_ENEMY)

        # Force extra spawn waves for maximum alien count
        zone = gv._zone
        for _ in range(3):
            zone._spawn_timer = 0.0
            zone.update(gv, 1 / 60)

        fps = _measure_fps(gv, n_warmup=10)
        _teardown_warp_zone_test(gv)

        assert fps >= MIN_FPS, (
            f"Warp Enemy full ({len(zone._aliens)} aliens): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
