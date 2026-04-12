"""Performance integration tests — measure frame time and assert >= 40 FPS.

These tests simulate N frame loops (on_update + on_draw) with a real
GameView on a hidden Arcade window, time the wall-clock cost, and fail
if the measured FPS drops below the threshold.

Run with:  ``pytest "unit tests/integration/test_performance.py" -v``

IMPORTANT: Results depend on the hardware running the tests. These are
calibrated for the development machine. If they fail on CI or a weaker
laptop, raise the ``MIN_FPS`` constant or skip with ``@pytest.mark.skip``.
The value of these tests is catching *algorithmic regressions* (O(n²)
collision loop, per-frame SpriteList rebuilds, etc.), not guaranteeing
absolute FPS on all hardware.
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
#  Test 1: Zone 2 fully populated (the scenario that dropped to 30 FPS)
# ═══════════════════════════════════════════════════════════════════════════

class TestZone2FullPopulation:
    def test_zone2_with_all_entities_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        and fog of war mostly revealed. This matches the user's original
        report of 30 FPS drops in the Nebula zone."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        assert gv._zone.zone_id == ZoneID.ZONE2

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 full population: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 2: Zone 2 with station buildings (turrets targeting 60 aliens)
# ═══════════════════════════════════════════════════════════════════════════

class TestZone2WithStation:
    def test_zone2_with_9_buildings_above_threshold(self, real_game_view):
        """Zone 2 with a 9-module station: Home Station + 4 Service Modules
        + 2 Turrets + Repair Module + Power Receiver. Turrets fire at ~60
        aliens every frame. This is the heaviest realistic scenario."""
        from sprites.building import create_building

        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        gv.building_list.clear()

        # Build a small station near the player
        cx, cy = gv.player.center_x, gv.player.center_y
        station_types = [
            "Home Station",
            "Service Module", "Service Module",
            "Service Module", "Service Module",
            "Turret 1", "Turret 2",
            "Repair Module",
            "Power Receiver",
        ]
        spacing = 60
        for i, bt in enumerate(station_types):
            tex = gv._building_textures[bt]
            laser = gv._turret_laser_tex if "Turret" in bt else None
            bx = cx + 200 + (i % 3) * spacing
            by = cy + (i // 3) * spacing
            b = create_building(bt, tex, bx, by, laser_tex=laser, scale=0.5)
            gv.building_list.append(b)

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 + 9 buildings: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 3: Both inventories open (the 40 FPS drop the user reported)
# ═══════════════════════════════════════════════════════════════════════════

class TestInventoriesOpen:
    def test_both_inventories_open_above_threshold(self, real_game_view):
        """Ship cargo (5x5) and station inventory (10x10) both open with
        items in most slots. This stresses the per-frame inventory
        rendering which previously caused sub-40 FPS drops."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Fill ship inventory (25 cells)
        gv.inventory._items.clear()
        for r in range(5):
            for c in range(5):
                gv.inventory._items[(r, c)] = ("iron", 10 + r * 5 + c)
        gv.inventory._mark_dirty()
        gv.inventory.open = True

        # Fill station inventory (100 cells — worst case)
        gv._station_inv._items.clear()
        for r in range(10):
            for c in range(10):
                gv._station_inv._items[(r, c)] = ("iron", r * 10 + c + 1)
        gv._station_inv._mark_dirty()
        gv._station_inv.open = True

        fps = _measure_fps(gv)

        # Close to avoid polluting later tests
        gv.inventory.open = False
        gv._station_inv.open = False

        assert fps >= MIN_FPS, (
            f"Both inventories open (125 cells): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 4: Zone 1 with full station + boss active
# ═══════════════════════════════════════════════════════════════════════════

class TestZone1WithBoss:
    def test_zone1_boss_fight_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, a boss, and a station.
        The boss fires spread shots and the station has turrets — heavy
        combat scenario."""
        from sprites.building import create_building
        from combat_helpers import spawn_boss

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Place a small station
        gv.building_list.clear()
        tex = gv._building_textures["Home Station"]
        home = create_building("Home Station", tex,
                               WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                               scale=0.5)
        gv.building_list.append(home)
        for bt in ("Turret 1", "Turret 2"):
            tex = gv._building_textures[bt]
            b = create_building(bt, tex,
                                WORLD_WIDTH / 2 + 80,
                                WORLD_HEIGHT / 2,
                                laser_tex=gv._turret_laser_tex, scale=0.5)
            gv.building_list.append(b)

        # Spawn the boss
        gv._boss = None
        gv._boss_spawned = False
        gv._boss_defeated = False
        gv._boss_list.clear()
        gv._boss_projectile_list.clear()
        spawn_boss(gv, WORLD_WIDTH / 2, WORLD_HEIGHT / 2)

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 1 boss fight: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 5: Zone 2 minimap with 200+ entities (draw-heavy)
# ═══════════════════════════════════════════════════════════════════════════

class TestMinimapHeavyDraw:
    def test_zone2_minimap_rendering_above_threshold(self, real_game_view):
        """Zone 2 minimap must render dots for ~150 asteroids + ~60 aliens
        + gas areas + buildings using batched draw_points. This test
        ensures the minimap batching optimization holds under load."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        # The minimap draws inside on_draw via HUD. Just measure FPS of
        # the full frame loop — the minimap is a significant fraction.
        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 minimap heavy: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 6: Heavy combat — projectiles + explosions + sparks everywhere
# ═══════════════════════════════════════════════════════════════════════════

class TestHeavyCombat:
    def test_heavy_combat_above_threshold(self, real_game_view):
        """Simulate a chaotic battle: player broadside active, 2 turrets
        firing, 20 alien projectiles in flight, 10 explosions playing,
        and 30 hit sparks active simultaneously. This is the peak
        per-frame entity count during intense Zone 1 combat."""
        from sprites.building import create_building
        from sprites.explosion import Explosion, HitSpark, FireSpark
        from sprites.projectile import Projectile

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Place 2 turrets
        gv.building_list.clear()
        tex_home = gv._building_textures["Home Station"]
        home = create_building("Home Station", tex_home,
                               WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
                               scale=0.5)
        gv.building_list.append(home)
        for i, bt in enumerate(("Turret 1", "Turret 2")):
            tex = gv._building_textures[bt]
            b = create_building(bt, tex,
                                WORLD_WIDTH / 2 + 80 * (i + 1),
                                WORLD_HEIGHT / 2,
                                laser_tex=gv._turret_laser_tex, scale=0.5)
            gv.building_list.append(b)

        # Spawn 20 alien projectiles near the player
        for i in range(20):
            p = Projectile(
                gv._alien_laser_tex,
                gv.player.center_x + i * 30,
                gv.player.center_y + 100,
                heading=180.0, speed=300.0, max_dist=800.0,
                scale=0.5, damage=10,
            )
            gv.alien_projectile_list.append(p)

        # Spawn 10 explosions
        for i in range(10):
            exp = Explosion(
                gv._explosion_frames,
                gv.player.center_x + i * 50 - 250,
                gv.player.center_y + 150,
            )
            gv.explosion_list.append(exp)

        # Spawn 30 hit sparks + 10 fire sparks
        gv.hit_sparks = [
            HitSpark(gv.player.center_x + i * 20, gv.player.center_y + 80)
            for i in range(30)
        ]
        gv.fire_sparks = [
            FireSpark(gv.player.center_x + i * 30, gv.player.center_y - 50)
            for i in range(10)
        ]

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Heavy combat: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 7: Warp enemy zone — 4 spawners producing 20+ mini-aliens
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
#  Test 8: Escape menu open — GC stall + double-layer rendering
# ═══════════════════════════════════════════════════════════════════════════

class TestEscapeMenuOpen:
    def test_escape_menu_open_above_threshold(self, real_game_view):
        """Escape menu open: the game world is still rendered underneath
        the menu overlay. On first open, gc.collect() runs (potentially
        a stall). Subsequent frames must stay above 40 FPS."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Open the escape menu (this triggers gc.collect on first update)
        gv._escape_menu.open = True
        gv._gc_ran = False

        # First update absorbs the GC stall
        gv.on_update(1 / 60)
        gv.on_draw()

        # Now measure steady-state with menu open
        fps = _measure_fps(gv)

        gv._escape_menu.open = False

        assert fps >= MIN_FPS, (
            f"Escape menu open: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Video helper — start character video if a .mp4 file is available
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


def _start_char_video_or_skip(gv):
    """Start the character video player. Skips if no files or no FFmpeg."""
    paths = _get_video_paths()
    gv._char_video_player.play_segments(paths[0], volume=0.0)
    dt = 1 / 60
    for _ in range(10):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._char_video_player.active:
        pytest.skip("Character video player failed to start (no FFmpeg?)")


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
#  Test 9: Character video + Zone 1 gameplay
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoZone1:
    def test_char_video_with_zone1_above_threshold(self, real_game_view):
        """Zone 1 normal gameplay with the character video portrait
        rendering in the HUD. The video player runs GPU blit downscale +
        frame readback every ~3 frames."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_char_video_or_skip(gv)

        fps = _measure_fps(gv)

        gv._char_video_player.stop()

        assert fps >= MIN_FPS, (
            f"Zone 1 + char video: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 10: Character video + Zone 2 full population
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoZone2:
    def test_char_video_with_zone2_above_threshold(self, real_game_view):
        """Zone 2 (Nebula) full population — the heaviest zone — with the
        character video portrait running. This is the most demanding
        realistic gameplay scenario."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _start_char_video_or_skip(gv)

        fps = _measure_fps(gv)

        gv._char_video_player.stop()

        assert fps >= MIN_FPS, (
            f"Zone 2 + char video: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 11: Character video + both inventories open
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoInventories:
    def test_char_video_with_inventories_above_threshold(self, real_game_view):
        """Both inventories open (125 filled cells) with the character
        video portrait rendering. Stacks the two most expensive UI
        systems together."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_char_video_or_skip(gv)

        # Fill both inventories
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

        fps = _measure_fps(gv)

        gv.inventory.open = False
        gv._station_inv.open = False
        gv._char_video_player.stop()

        assert fps >= MIN_FPS, (
            f"Inventories + char video: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 12: BOTH videos + Zone 1 gameplay
# ═══════════════════════════════════════════════════════════════════════════

class TestDualVideoZone1:
    def test_both_videos_with_zone1_above_threshold(self, real_game_view):
        """Zone 1 gameplay with BOTH the character video portrait AND a
        music video rendering simultaneously. Two independent FFmpeg
        decode pipelines + two GPU blit downscales per frame."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_both_videos_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 1 + both videos: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 13: BOTH videos + Zone 2 full population
# ═══════════════════════════════════════════════════════════════════════════

class TestDualVideoZone2:
    def test_both_videos_with_zone2_above_threshold(self, real_game_view):
        """Zone 2 (Nebula) full population with both video players active.
        This is the absolute worst-case scenario: ~60 aliens, ~150
        asteroids, gas, wanderers, fog, minimap dots, PLUS two FFmpeg
        decode pipelines and GPU blit downscales."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _start_both_videos_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 2 + both videos: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 14: BOTH videos + both inventories open
# ═══════════════════════════════════════════════════════════════════════════

class TestDualVideoInventories:
    def test_both_videos_with_inventories_above_threshold(self, real_game_view):
        """Both inventories open (125 filled cells) with both video
        players active. Stacks the three most expensive rendering
        systems: inventory badges + character video + music video."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_both_videos_or_skip(gv)

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

        fps = _measure_fps(gv)

        gv.inventory.open = False
        gv._station_inv.open = False
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Inventories + both videos: {fps:.1f} FPS "
            f"< {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Real music video helper — uses G:\yvideos\*.mp4
# ═══════════════════════════════════════════════════════════════════════════

_MUSIC_VIDEO_DIR = r"G:\yvideos"


def _start_real_music_and_char_or_skip(gv):
    """Start a real music video from G:\\yvideos AND the character video.
    Skips if the directory doesn't exist, has no .mp4 files, or FFmpeg
    can't decode them."""
    import os
    from video_player import scan_characters_dir, character_video_path

    # Music video
    if not os.path.isdir(_MUSIC_VIDEO_DIR):
        pytest.skip(f"Music video directory not found: {_MUSIC_VIDEO_DIR}")
    mp4s = sorted(f for f in os.listdir(_MUSIC_VIDEO_DIR)
                  if f.lower().endswith(".mp4"))
    if not mp4s:
        pytest.skip(f"No .mp4 files in {_MUSIC_VIDEO_DIR}")
    music_path = os.path.join(_MUSIC_VIDEO_DIR, mp4s[0])

    # Character video
    chars = scan_characters_dir()
    if not chars:
        pytest.skip("No character video files found in characters/")
    char_path = character_video_path(chars[0])
    if char_path is None:
        pytest.skip("Character video path not resolved")

    # Start both
    gv._char_video_player.play_segments(char_path, volume=0.0)
    ok = gv._video_player.play(music_path, volume=0.0)
    if not ok:
        gv._char_video_player.stop()
        pytest.skip(f"Music video failed to start: {gv._video_player.error}")

    # Warmup — let both decoders produce their first frames
    dt = 1 / 60
    for _ in range(15):
        gv.on_update(dt)
        gv.on_draw()
    if not gv._video_player.active:
        gv._char_video_player.stop()
        pytest.skip("Music video player not active after warmup")


# ═══════════════════════════════════════════════════════════════════════════
#  Test 15: Real music video + char video + Zone 1
# ═══════════════════════════════════════════════════════════════════════════

class TestRealMusicVideoZone1:
    def test_real_music_char_video_zone1_above_threshold(self, real_game_view):
        """Zone 1 gameplay with a REAL music video from G:\\yvideos AND
        the character portrait video. Real music videos are typically
        720p–1080p, much heavier than the 1440×1440 character portraits
        — a harder GPU blit test."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_real_music_and_char_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 1 + real music video + char video: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 16: Real music video + char video + Zone 2 full population
# ═══════════════════════════════════════════════════════════════════════════

class TestRealMusicVideoZone2:
    def test_real_music_char_video_zone2_above_threshold(self, real_game_view):
        """Zone 2 (Nebula) full population with a real music video and
        the character video. Absolute worst case: heaviest zone + two
        FFmpeg decodes + 200+ minimap dots + fog overlay."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        _start_real_music_and_char_or_skip(gv)

        fps = _measure_fps(gv)
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Zone 2 + real music video + char video: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 17: Real music video + char video + both inventories
# ═══════════════════════════════════════════════════════════════════════════

class TestRealMusicVideoInventories:
    def test_real_music_char_video_inventories_above_threshold(
        self, real_game_view
    ):
        """Both inventories open (125 filled cells) with a real music
        video and the character video. Stacks every expensive rendering
        system: inventory badges + two video decodes + GPU blits."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_real_music_and_char_or_skip(gv)

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

        fps = _measure_fps(gv)

        gv.inventory.open = False
        gv._station_inv.open = False
        _stop_both_videos(gv)

        assert fps >= MIN_FPS, (
            f"Inventories + real music video + char video: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )
