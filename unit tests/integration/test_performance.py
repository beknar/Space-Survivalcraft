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


# ═══════════════════════════════════════════════════════════════════════════
#  Test 18: Station Info panel open in Zone 1 with full population
# ═══════════════════════════════════════════════════════════════════════════

def _open_station_info(gv):
    """Open Station Info panel with full stats and inactive zone data."""
    from sprites.building import create_building, compute_modules_used, compute_module_capacity
    from draw_logic import compute_world_stats, compute_inactive_zone_stats

    # Build a station near the player so the panel can open
    if not any(b.building_type == "Home Station" for b in gv.building_list):
        gv.building_list.clear()
        cx, cy = gv.player.center_x, gv.player.center_y
        for i, bt in enumerate([
            "Home Station", "Service Module", "Service Module",
            "Turret 1", "Repair Module",
        ]):
            tex = gv._building_textures[bt]
            laser = gv._turret_laser_tex if "Turret" in bt else None
            b = create_building(bt, tex, cx + 200 + i * 60, cy,
                                laser_tex=laser, scale=0.5)
            gv.building_list.append(b)

    gv._station_info.toggle(
        gv.building_list,
        compute_modules_used(gv.building_list),
        compute_module_capacity(gv.building_list),
        stat_lines=compute_world_stats(gv),
        inactive_zone_stats=compute_inactive_zone_stats(gv),
    )


class TestStationInfoZone1:
    def test_station_info_zone1_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, station buildings, and
        Station Info panel open showing current zone stats + inactive
        Zone 2 stats. Stresses the Station Info panel rendering and
        live update loop."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Ensure Zone 2 exists so the inactive panel has data
        if gv._zone2 is None:
            gv._transition_zone(ZoneID.ZONE2)
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        _open_station_info(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv)
        gv._station_info.open = False

        assert fps >= MIN_FPS, (
            f"Station Info Zone 1: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 19: Station Info panel open in Zone 2 with full population
# ═══════════════════════════════════════════════════════════════════════════

class TestStationInfoZone2:
    def test_station_info_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        station buildings, and Station Info panel open showing current
        zone stats + inactive Double Star stats. This is the heaviest
        Station Info scenario."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        _open_station_info(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv)
        gv._station_info.open = False

        assert fps >= MIN_FPS, (
            f"Station Info Zone 2: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: start music + set ship level 2
# ═══════════════════════════════════════════════════════════════════════════

def _start_music(gv):
    """Start OST music playback if tracks are available. Returns True if
    music is playing."""
    if gv._music_tracks:
        from settings import audio as _audio
        sound, name = gv._music_tracks[0]
        gv._current_track_name = name
        gv._music_player = arcade.play_sound(sound, volume=_audio.music_volume)
        return gv._music_player is not None
    return False


def _set_ship_level_2(gv):
    """Upgrade the player ship to level 2 by swapping its texture."""
    from sprites.player import PlayerShip
    gv._ship_level = 2
    # Rebuild the player with level 2 texture
    old = gv.player
    new_player = PlayerShip(
        faction=gv._faction, ship_type=gv._ship_type, ship_level=2)
    new_player.center_x = old.center_x
    new_player.center_y = old.center_y
    new_player.vel_x = old.vel_x
    new_player.vel_y = old.vel_y
    new_player.hp = old.hp
    new_player.max_hp = old.max_hp
    new_player.shields = old.shields
    new_player.max_shields = old.max_shields
    gv.player_list.clear()
    gv.player = new_player
    gv.player_list.append(new_player)


def _stop_music(gv):
    """Stop music playback."""
    if gv._music_player is not None:
        try:
            arcade.stop_sound(gv._music_player)
        except Exception:
            pass
        gv._music_player = None


# ═══════════════════════════════════════════════════════════════════════════
#  Test 20: Station Info + music + level 2 ship in Zone 1
# ═══════════════════════════════════════════════════════════════════════════

class TestStationInfoMusicZone1:
    def test_station_info_music_zone1_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, station buildings, Station
        Info panel open, level 2 ship, and background music playing. This
        combines the Station Info overlay, music decode overhead, and the
        higher-res level 2 ship texture."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        # Ensure Zone 2 exists for inactive panel
        if gv._zone2 is None:
            gv._transition_zone(ZoneID.ZONE2)
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info(gv)
        assert gv._station_info.open

        # Extra warmup to absorb music player initialization spike
        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        assert fps >= MIN_FPS, (
            f"Station Info + music + L2 ship Zone 1 "
            f"(music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 21: Station Info + music + level 2 ship in Zone 2
# ═══════════════════════════════════════════════════════════════════════════

class TestStationInfoMusicZone2:
    def test_station_info_music_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        station buildings, Station Info panel open, level 2 ship, and
        background music playing. Heaviest combined Station Info scenario."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info(gv)
        assert gv._station_info.open

        # Extra warmup to absorb music player initialization spike
        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        assert fps >= MIN_FPS, (
            f"Station Info + music + L2 ship Zone 2 "
            f"(music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: build a heavy station with multiple turrets firing at aliens
# ═══════════════════════════════════════════════════════════════════════════

def _build_turret_station(gv):
    """Build a 9-module station with 3 turrets near the player, and ensure
    aliens are within turret range so the turrets actively fire."""
    from sprites.building import create_building

    gv.building_list.clear()
    cx, cy = gv.player.center_x, gv.player.center_y
    station_types = [
        "Home Station",
        "Service Module", "Service Module", "Service Module",
        "Turret 1", "Turret 2", "Turret 1",
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

    # Move a few aliens within turret range so turrets actively fire
    from constants import TURRET_RANGE
    turret_x = cx + 200
    turret_y = cy
    alien_list = gv.alien_list
    from zones import ZoneID
    if gv._zone.zone_id == ZoneID.ZONE2 and hasattr(gv._zone, '_aliens'):
        alien_list = gv._zone._aliens
    moved = 0
    for alien in alien_list:
        if moved >= 8:
            break
        alien.center_x = turret_x + (moved % 3 - 1) * 100
        alien.center_y = turret_y + (moved // 3) * 100 + 150
        moved += 1


def _open_station_info_turrets(gv):
    """Build turret station and open Station Info panel."""
    from sprites.building import compute_modules_used, compute_module_capacity
    from draw_logic import compute_world_stats, compute_inactive_zone_stats

    _build_turret_station(gv)
    gv._station_info.toggle(
        gv.building_list,
        compute_modules_used(gv.building_list),
        compute_module_capacity(gv.building_list),
        stat_lines=compute_world_stats(gv),
        inactive_zone_stats=compute_inactive_zone_stats(gv),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 22: Full scenario — Station Info + turrets + music + L2 ship, Zone 1
# ═══════════════════════════════════════════════════════════════════════════

class TestFullScenarioZone1:
    def test_full_scenario_zone1_above_threshold(self, real_game_view):
        """Zone 1 with 30 aliens, 75 asteroids, 9-module station with 3
        turrets actively firing, Station Info panel open, level 2 ship,
        and background music playing. This is the heaviest realistic
        Zone 1 scenario combining all overlays and combat systems."""
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        if gv._zone2 is None:
            gv._transition_zone(ZoneID.ZONE2)
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info_turrets(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        assert fps >= MIN_FPS, (
            f"Full scenario Zone 1 (music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 23: Full scenario — Station Info + turrets + music + L2 ship, Zone 2
# ═══════════════════════════════════════════════════════════════════════════

class TestFullScenarioZone2:
    def test_full_scenario_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens, ~150 asteroids, gas areas, wanderers,
        9-module station with 3 turrets actively firing, Station Info
        panel open, level 2 ship, and background music playing. Absolute
        heaviest realistic scenario — uses 35 FPS threshold (vs 40 for
        lighter tests) because this combines every expensive system."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        _set_ship_level_2(gv)
        music_on = _start_music(gv)
        _open_station_info_turrets(gv)
        assert gv._station_info.open

        fps = _measure_fps(gv, n_warmup=15)
        gv._station_info.open = False
        _stop_music(gv)

        _FULL_SCENARIO_MIN = 35  # relaxed: absolute worst-case scenario
        assert fps >= _FULL_SCENARIO_MIN, (
            f"Full scenario Zone 2 (music={'on' if music_on else 'off'}): "
            f"{fps:.1f} FPS < {_FULL_SCENARIO_MIN} FPS threshold"
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
#  Test 24–27: All four warp zones with videos + firing + fog
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


# ═══════════════════════════════════════════════════════════════════════════
#  Test 28: Zone 2 with parked ships (multi-ship collision + rendering)
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipsZone2:
    def test_parked_ships_zone2_above_threshold(self, real_game_view):
        """Zone 2 with 3 parked ships (each with cargo and modules), full
        alien population, and turrets firing. Tests rendering overhead of
        parked ships + collision checks against all projectile types."""
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip

        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        # Place 3 parked ships with cargo and modules
        cx, cy = gv.player.center_x, gv.player.center_y
        for i in range(3):
            ps = ParkedShip(
                gv._faction, gv._ship_type, i + 1,
                cx + 200 + i * 100, cy + 100)
            ps.cargo_items[(0, 0)] = ("iron", 50)
            ps.module_slots = ["armor_plate", "engine_booster"]
            gv._parked_ships.append(ps)

        # Also build turrets so projectile lists are active
        _open_station_info_turrets(gv)
        gv._station_info.open = False

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 + 3 parked ships: {fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Test 29: Zone 2 alien-asteroid collisions + obstacle avoidance
# ═══════════════════════════════════════════════════════════════════════════

class TestAlienAsteroidZone2:
    def test_alien_asteroid_collision_zone2_above_threshold(self, real_game_view):
        """Zone 2 with ~60 aliens colliding with ~150 asteroids (damage +
        bounce + obstacle avoidance). Tests that the new alien-asteroid
        collision handler + avoidance steering don't cause FPS drops."""
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        # Move some aliens near asteroids to trigger collisions
        zone = gv._zone
        aliens = list(zone._aliens)[:10]
        asteroids = list(zone._iron_asteroids)[:10]
        for alien, ast in zip(aliens, asteroids):
            alien.center_x = ast.center_x + 20
            alien.center_y = ast.center_y

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Zone 2 alien-asteroid collisions: "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Missile Array perf: 8 arrays + 30 aliens
# ═══════════════════════════════════════════════════════════════════════════

class TestMissileArrayPerf:
    def test_missile_arrays_above_threshold(self, real_game_view):
        """8 Missile Arrays periodically firing at 30 aliens should sustain
        at least the standard FPS threshold."""
        from sprites.building import create_building
        from sprites.alien import SmallAlienShip

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")

        tex = gv._building_textures["Missile Array"]
        for i in range(8):
            ma = create_building("Missile Array", tex,
                                 WORLD_WIDTH / 2 + (i - 4) * 80,
                                 WORLD_HEIGHT / 2 + 200,
                                 scale=0.5)
            gv.building_list.append(ma)

        for i in range(30):
            a = SmallAlienShip(
                gv._alien_ship_tex, gv._alien_laser_tex,
                WORLD_WIDTH / 2 + (i - 15) * 60,
                WORLD_HEIGHT / 2,
            )
            gv.alien_list.append(a)

        fps = _measure_fps(gv)
        assert fps >= MIN_FPS, (
            f"Missile Arrays + 30 aliens: {fps:.1f} FPS < {MIN_FPS}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Missile Array perf with both videos running
# ═══════════════════════════════════════════════════════════════════════════

class TestMissileArrayPerfWithVideos:
    def test_missile_arrays_above_threshold_with_videos(self, real_game_view):
        """Same scenario as TestMissileArrayPerf but with both video
        decoders running. Catches any per-frame interaction between
        MissileArray scanning + the GPU-blit video pipeline."""
        from sprites.building import create_building
        from sprites.alien import SmallAlienShip

        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        _start_both_videos_or_skip(gv)
        try:
            tex = gv._building_textures["Missile Array"]
            for i in range(8):
                ma = create_building("Missile Array", tex,
                                     WORLD_WIDTH / 2 + (i - 4) * 80,
                                     WORLD_HEIGHT / 2 + 200, scale=0.5)
                gv.building_list.append(ma)

            for i in range(30):
                a = SmallAlienShip(
                    gv._alien_ship_tex, gv._alien_laser_tex,
                    WORLD_WIDTH / 2 + (i - 15) * 60,
                    WORLD_HEIGHT / 2,
                )
                gv.alien_list.append(a)

            fps = _measure_fps(gv)
            assert fps >= MIN_FPS, (
                f"Missile Arrays + 30 aliens + both videos: "
                f"{fps:.1f} FPS < {MIN_FPS}"
            )
        finally:
            _stop_both_videos(gv)
