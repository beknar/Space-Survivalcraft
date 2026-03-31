"""World population helpers — asteroids, aliens, asset loading."""
from __future__ import annotations

import math
import os
import random

import arcade
from PIL import Image as PILImage

import glob as _glob

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    ASTEROID_COUNT, ASTEROID_MIN_DIST,
    EXPLOSION_FRAMES, EXPLOSION_FRAME_W, EXPLOSION_FRAME_H,
    ALIEN_COUNT, ALIEN_MIN_DIST,
    STARFIELD_DIR, LASER_DIR, SFX_WEAPONS_DIR, SFX_EXPLOSIONS_DIR, SFX_BIO_DIR,
    SFX_VEHICLES_DIR,
    ASTEROID_PNG, ALIEN_SHIP_PNG, ALIEN_FX_PNG, EXPLOSION_PNG, IRON_ICON_PNG,
    SHIELD_PNG, SHIELD_COLS, SHIELD_ROWS, SHIELD_FRAME_W, SHIELD_FRAME_H,
    MUSIC_VOL1_DIR, MUSIC_VOL2_DIR,
    BUILDING_DIR, BUILDING_TYPES,
)
from sprites.asteroid import IronAsteroid
from sprites.alien import SmallAlienShip
from sprites.shield import ShieldSprite
from sprites.projectile import Weapon


def load_bg_texture() -> arcade.Texture:
    """Load the tiled starfield background texture."""
    return arcade.load_texture(
        os.path.join(STARFIELD_DIR, "Starfield_01-1024x1024.png")
    )


_FACTION_SHIELD_TINTS: dict[str, tuple[int, int, int]] = {
    "Earth":       (255, 120, 120),   # red
    "Colonial":    (120, 255, 120),   # green
    "Heavy World": (180, 140, 100),   # brown
    "Ascended":    (200, 120, 255),   # purple
}


def load_shield(player_x: float, player_y: float,
                faction: str | None = None) -> tuple[ShieldSprite, arcade.SpriteList]:
    """Load shield frames and create the ShieldSprite + SpriteList."""
    _pil_shield = PILImage.open(SHIELD_PNG).convert("RGBA")
    frames: list[arcade.Texture] = []
    for row in range(SHIELD_ROWS):
        for col in range(SHIELD_COLS):
            x0 = col * SHIELD_FRAME_W
            y0 = row * SHIELD_FRAME_H
            frames.append(
                arcade.Texture(
                    _pil_shield.crop((x0, y0,
                                      x0 + SHIELD_FRAME_W,
                                      y0 + SHIELD_FRAME_H))
                )
            )
    tint = _FACTION_SHIELD_TINTS.get(faction, (255, 255, 255))
    sprite = ShieldSprite(frames, tint=tint)
    sprite.center_x = player_x
    sprite.center_y = player_y
    slist = arcade.SpriteList()
    slist.append(sprite)
    return sprite, slist


def load_weapons(gun_count: int) -> list[Weapon]:
    """Create the weapon list (doubled for multi-gun ships)."""
    laser_tex = arcade.load_texture(os.path.join(LASER_DIR, "laserBlue03.png"))
    mining_tex = arcade.load_texture(os.path.join(LASER_DIR, "laserGreen13.png"))
    laser_snd = arcade.load_sound(
        os.path.join(SFX_WEAPONS_DIR, "Small Laser Weapon Shot 1.wav")
    )
    mining_snd = arcade.load_sound(
        os.path.join(SFX_WEAPONS_DIR, "Sci-Fi Arc Emitter Weapon Shot 2.wav")
    )
    weapons: list[Weapon] = []
    for _g in range(gun_count):
        weapons.append(Weapon(
            "Basic Laser", laser_tex, laser_snd,
            cooldown=0.30, damage=25.0,
            projectile_speed=900.0, max_range=1200.0,
            proj_scale=1.0, mines_rock=False,
        ))
    for _g in range(gun_count):
        weapons.append(Weapon(
            "Mining Beam", mining_tex, mining_snd,
            cooldown=0.10, damage=10.0,
            projectile_speed=500.0, max_range=800.0,
            proj_scale=1.0, mines_rock=True,
        ))
    return weapons


def load_explosion_assets() -> tuple[list[arcade.Texture], arcade.Sound]:
    """Load explosion animation frames and sound."""
    exp_ss = arcade.load_spritesheet(EXPLOSION_PNG)
    frames = [
        exp_ss.get_texture(
            arcade.LBWH(i * EXPLOSION_FRAME_W, 0, EXPLOSION_FRAME_W, EXPLOSION_FRAME_H)
        )
        for i in range(EXPLOSION_FRAMES)
    ]
    snd = arcade.load_sound(
        os.path.join(SFX_EXPLOSIONS_DIR, "Sci-Fi Deep Explosion 1.wav")
    )
    return frames, snd


def load_bump_sound() -> arcade.Sound:
    """Load the collision bump sound."""
    return arcade.load_sound(
        os.path.join(SFX_BIO_DIR, "Game Biomechanical Impact Sound 1.wav")
    )


def load_thruster_sound() -> arcade.Sound:
    """Load the thruster engine loop sound."""
    return arcade.load_sound(
        os.path.join(SFX_VEHICLES_DIR, "Sci-Fi Spaceship Engine Loop 1.wav")
    )


def load_iron_texture() -> arcade.Texture:
    """Load the iron ore icon texture."""
    return arcade.load_texture(IRON_ICON_PNG)


def _track_name_from_path(path: str) -> str:
    """Extract a human-readable track name from a music file path.

    Vol 1 files: 'Antimatter Fountain [Action Loop].wav' → 'Antimatter Fountain [Action]'
    Vol 2 files: 'Comet Tail_loop.wav' → 'Comet Tail'
    """
    name = os.path.splitext(os.path.basename(path))[0]  # strip .wav
    # Vol 2: strip '_loop' or '_short_loop' suffix
    if name.endswith("_loop"):
        name = name[:-5]
    if name.endswith("_short"):
        name = name[:-6]
    # Vol 1: strip ' Loop]' suffix but keep the category tag
    if name.endswith(" Loop]"):
        name = name[:-6] + "]"  # 'Foo [Action Loop]' → 'Foo [Action]'
    return name.strip()


_music_cache: list[tuple[arcade.Sound, str]] | None = None


def collect_music_tracks() -> list[tuple[arcade.Sound, str]]:
    """Scan both music packs for loop files, shuffle, and return as (Sound, name) pairs.

    Loaded sounds are cached at module level so subsequent calls (e.g. returning
    to the splash screen) are instant — only the shuffle order changes.
    """
    global _music_cache
    if _music_cache is None:
        paths: list[str] = []
        # Vol 1: flat directory — files ending with "Loop].wav"
        for f in _glob.glob(os.path.join(MUSIC_VOL1_DIR, "*Loop].wav")):
            paths.append(f)
        # Vol 2: subdirectories — each contains a "*_loop.wav"
        for f in _glob.glob(os.path.join(MUSIC_VOL2_DIR, "*", "*_loop.wav")):
            paths.append(f)
        _music_cache = [(arcade.load_sound(p), _track_name_from_path(p)) for p in paths]
    # Return a fresh shuffled copy each time
    tracks = list(_music_cache)
    random.shuffle(tracks)
    return tracks


def populate_asteroids() -> arcade.SpriteList:
    """Spawn asteroids randomly across the world."""
    asteroid_tex = arcade.load_texture(ASTEROID_PNG)
    slist = arcade.SpriteList(use_spatial_hash=True)
    cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    margin = 100
    placed = 0
    attempts = 0
    while placed < ASTEROID_COUNT and attempts < ASTEROID_COUNT * 20:
        attempts += 1
        ax = random.uniform(margin, WORLD_WIDTH - margin)
        ay = random.uniform(margin, WORLD_HEIGHT - margin)
        if math.hypot(ax - cx_world, ay - cy_world) < ASTEROID_MIN_DIST:
            continue
        slist.append(IronAsteroid(asteroid_tex, ax, ay))
        placed += 1
    return slist


def load_building_textures() -> dict[str, arcade.Texture]:
    """Load one texture per building type from the BUILDING_DIR asset folder."""
    textures: dict[str, arcade.Texture] = {}
    for name, stats in BUILDING_TYPES.items():
        path = os.path.join(BUILDING_DIR, stats["png"])
        textures[name] = arcade.load_texture(path)
    return textures


def load_turret_laser() -> tuple[arcade.Texture, arcade.Sound]:
    """Load a laser texture and sound for station turrets (reuses blue laser assets)."""
    tex = arcade.load_texture(os.path.join(LASER_DIR, "laserBlue03.png"))
    snd = arcade.load_sound(
        os.path.join(SFX_WEAPONS_DIR, "Small Laser Weapon Shot 1.wav")
    )
    return tex, snd


def populate_aliens() -> tuple[arcade.SpriteList, arcade.Texture]:
    """Spawn alien ships randomly across the world. Returns (alien_list, alien_laser_tex)."""
    _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
    alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))

    _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
    _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
    alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))

    slist = arcade.SpriteList(use_spatial_hash=True)
    cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    placed = 0
    attempts = 0
    while placed < ALIEN_COUNT and attempts < ALIEN_COUNT * 20:
        attempts += 1
        ax = random.uniform(100, WORLD_WIDTH - 100)
        ay = random.uniform(100, WORLD_HEIGHT - 100)
        if math.hypot(ax - cx_world, ay - cy_world) < ALIEN_MIN_DIST:
            continue
        slist.append(SmallAlienShip(alien_ship_tex, alien_laser_tex, ax, ay))
        placed += 1
    return slist, alien_laser_tex
