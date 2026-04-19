"""Profile a fully-populated Zone 2 (Nebula) frame loop.

Spawns a real GameView, drops the player into Zone 2 with the full
population and a built station, then runs cProfile across
``FRAMES`` frames of ``on_update`` + ``on_draw``.  Prints the top
hot spots by cumulative time so we know where to optimise.

Run:
    python tools/profile_zone2.py            # no music video
    python tools/profile_zone2.py --videos   # also play both videos
"""
from __future__ import annotations

import argparse
import cProfile
import os
import pstats
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(_ROOT)

import arcade  # noqa: E402


def _make_gv(videos: bool):
    from game_view import GameView
    from zones import ZoneID
    from sprites.building import create_building
    from constants import WORLD_WIDTH, WORLD_HEIGHT

    gv = GameView(faction="Earth", ship_type="Cruiser", skip_music=True)
    arcade.get_window().show_view(gv)
    gv._transition_zone(ZoneID.ZONE2)

    # Station so turret-targeting + station-shield code is hot
    gv.building_list.clear()
    cx, cy = gv._zone.world_width / 2, gv._zone.world_height / 2
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))
    for bt, ox in (("Turret 1", 80), ("Turret 2", -80),
                   ("Shield Generator", 0)):
        t = gv._building_textures[bt]
        laser = gv._turret_laser_tex if "Turret" in bt else None
        gv.building_list.append(create_building(
            bt, t, cx + ox, cy + (60 if bt == "Shield Generator" else 0),
            laser_tex=laser, scale=0.5))

    # Park the player near the station so its HUD/inventory paths are hot
    gv.player.center_x = cx + 40
    gv.player.center_y = cy + 40
    gv.player.max_hp = gv.player.hp = 999999
    gv.player.max_shields = gv.player.shields = 999999

    if videos:
        from video_player import scan_characters_dir, character_video_path
        chars = scan_characters_dir()
        paths = [character_video_path(n) for n in chars]
        paths = [p for p in paths if p]
        if paths:
            gv._char_video_player.play_segments(paths[0], volume=0.0)
            if len(paths) > 1:
                gv._video_player.play(paths[1], volume=0.0)
            else:
                gv._video_player.play(paths[0], volume=0.0)
            for _ in range(10):
                gv.on_update(1 / 60); gv.on_draw()

    return gv


def run(videos: bool, frames: int) -> None:
    win = arcade.Window(800, 600, "profile-zone2", visible=False)
    try:
        gv = _make_gv(videos)

        # Warm-up 60 frames (compile shaders, warm caches, populate
        # projectile pools).
        for _ in range(60):
            gv.on_update(1 / 60)
            gv.on_draw()

        prof = cProfile.Profile()
        prof.enable()
        for _ in range(frames):
            gv.on_update(1 / 60)
            gv.on_draw()
        prof.disable()

        stats = pstats.Stats(prof)
        stats.strip_dirs().sort_stats("cumulative")
        print(f"\n=== Top 30 by cumulative time "
              f"(frames={frames}, videos={videos}) ===")
        stats.print_stats(30)

        print("\n=== Top 25 by total (self) time ===")
        stats.sort_stats("tottime").print_stats(25)
    finally:
        try:
            win.close()
        except Exception:
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", action="store_true",
                    help="Also play both video players.")
    ap.add_argument("--frames", type=int, default=180,
                    help="Profiled frames (default 180 = 3 s @60 FPS).")
    args = ap.parse_args()
    run(videos=args.videos, frames=args.frames)
