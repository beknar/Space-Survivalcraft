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


_shield_frames_cache: list[arcade.Texture] | None = None


def get_shield_frames() -> list[arcade.Texture]:
    """Load + cache the shield-sheet frames. Safe to call many times."""
    global _shield_frames_cache
    if _shield_frames_cache is None:
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
        _pil_shield.close()
        _shield_frames_cache = frames
    return _shield_frames_cache


def faction_shield_tint(faction: str | None) -> tuple[int, int, int]:
    return _FACTION_SHIELD_TINTS.get(faction, (255, 255, 255))


def load_shield(player_x: float, player_y: float,
                faction: str | None = None) -> tuple[ShieldSprite, arcade.SpriteList]:
    """Load shield frames and create the ShieldSprite + SpriteList."""
    frames = get_shield_frames()
    sprite = ShieldSprite(frames, tint=faction_shield_tint(faction))
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


_asteroid_explosion_frames_cache: list[arcade.Texture] | None = None


def load_asteroid_explosion_frames() -> list[arcade.Texture]:
    """Load the 10-frame asteroid explosion sequence.

    Reads ``Explo__001.png`` through ``Explo__010.png`` from
    ``ASTEROID_EXPLOSION_DIR``. Cached at module level so successive
    GameView rebuilds don't re-decode the PNGs."""
    global _asteroid_explosion_frames_cache
    if _asteroid_explosion_frames_cache is None:
        from constants import ASTEROID_EXPLOSION_DIR, ASTEROID_EXPLOSION_FRAMES
        frames: list[arcade.Texture] = []
        for i in range(1, ASTEROID_EXPLOSION_FRAMES + 1):
            path = os.path.join(
                ASTEROID_EXPLOSION_DIR, f"Explo__{i:03d}.png")
            frames.append(arcade.load_texture(path))
        _asteroid_explosion_frames_cache = frames
    return _asteroid_explosion_frames_cache


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
        # Stream music tracks instead of static-loading them — pyglet's
        # default WAV decoder slurps the entire file into memory, which
        # raises MemoryError on long loops.
        _music_cache = [
            (arcade.load_sound(p, streaming=True), _track_name_from_path(p))
            for p in paths
        ]
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


def populate_slipspaces(
    world_w: float, world_h: float,
    texture: arcade.Texture,
    count: int | None = None,
    rng: random.Random | None = None,
) -> arcade.SpriteList:
    """Spawn ``Slipspace`` teleporters randomly across a zone.

    A dedicated ``rng`` lets save/load reproduce the layout
    deterministically from the zone seed.  Returns a ``SpriteList`` so
    the existing ``check_for_collision_with_list`` helpers work without
    extra glue.
    """
    from constants import SLIPSPACE_COUNT, SLIPSPACE_MARGIN
    from sprites.slipspace import Slipspace
    r = rng or random
    n = SLIPSPACE_COUNT if count is None else count
    slist = arcade.SpriteList()
    for _ in range(n):
        x = r.uniform(SLIPSPACE_MARGIN, world_w - SLIPSPACE_MARGIN)
        y = r.uniform(SLIPSPACE_MARGIN, world_h - SLIPSPACE_MARGIN)
        slist.append(Slipspace(texture, x, y))
    return slist


_slipspace_assets_cache: tuple[arcade.Texture, arcade.Sound] | None = None


def load_slipspace_assets() -> tuple[arcade.Texture, arcade.Sound]:
    """Load the slipspace texture + jump sound.

    Cached at module level so GameView rebuilds + Zone 2 setup
    don't re-decode the PNG / re-load the WAV every time."""
    global _slipspace_assets_cache
    if _slipspace_assets_cache is None:
        from constants import SLIPSPACE_PNG, SFX_SLIPSPACE
        tex = arcade.load_texture(SLIPSPACE_PNG)
        snd = arcade.load_sound(SFX_SLIPSPACE)
        _slipspace_assets_cache = (tex, snd)
    return _slipspace_assets_cache


def populate_null_fields(
    world_w: float, world_h: float,
    count: int | None = None,
    rng: random.Random | None = None,
) -> list:
    """Spawn ``NullField`` stealth patches randomly across a zone.

    Used by both Zone 1 (during ``GameView._init_world_entities``) and
    Zone 2 (``zones/zone2_world.populate_null_fields``).  A dedicated
    ``rng`` lets the caller seed placement for save/load determinism.
    """
    from constants import NULL_FIELD_COUNT
    from sprites.null_field import NullField
    r = rng or random
    n = NULL_FIELD_COUNT if count is None else count
    fields: list = []
    margin = 180.0
    for _ in range(n):
        x = r.uniform(margin, world_w - margin)
        y = r.uniform(margin, world_h - margin)
        fields.append(NullField(x, y, rng=r))
    return fields


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


_alien_tex_cache: tuple[arcade.Texture, arcade.Texture] | None = None


def populate_aliens() -> tuple[arcade.SpriteList, arcade.Texture, arcade.Texture]:
    """Spawn alien ships randomly across the world.

    Returns (alien_list, alien_ship_tex, alien_laser_tex). GameView uses
    the ship + laser textures to spawn respawns without re-cropping the
    sprite sheet.
    """
    # Cache the alien textures — loading the ship/FX sheets via PIL and
    # cropping raises MemoryError on fragmented heaps when a second
    # GameView is built (e.g. load-from-save) before the first one's
    # pixel buffers have been freed.
    global _alien_tex_cache
    if _alien_tex_cache is None:
        # Ship.png is 5132x4876 RGBA (~100 MB decompressed). The earlier
        # .convert("RGBA") copied the whole buffer a second time which
        # blew up on fragmented heaps. Both source PNGs are already RGBA,
        # so open-and-crop without a conversion copy.
        _pil_ship = PILImage.open(ALIEN_SHIP_PNG)
        if _pil_ship.mode != "RGBA":
            _pil_ship = _pil_ship.convert("RGBA")
        alien_ship_tex = arcade.Texture(
            _pil_ship.crop((364, 305, 825, 815)).copy())
        _pil_ship.close()

        _pil_fx = PILImage.open(ALIEN_FX_PNG)
        if _pil_fx.mode != "RGBA":
            _pil_fx = _pil_fx.convert("RGBA")
        _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
        alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))
        _pil_fx.close()
        _alien_tex_cache = (alien_ship_tex, alien_laser_tex)
    else:
        alien_ship_tex, alien_laser_tex = _alien_tex_cache

    # Aliens move every frame — spatial hash would be rebuilt each tick
    slist = arcade.SpriteList()
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
    return slist, alien_ship_tex, alien_laser_tex
