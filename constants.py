"""Centralised game constants for Space Survivalcraft."""
from __future__ import annotations

import os

# ── Window / World ──────────────────────────────────────────────────────────
SCREEN_WIDTH: int = 1280
SCREEN_HEIGHT: int = 800
SCREEN_TITLE: str = "Space Survivalcraft"

STATUS_WIDTH: int = 213          # Left status panel width (~1/6 of screen)
WORLD_WIDTH: int = 6400          # 200 x 32-px tiles
WORLD_HEIGHT: int = 6400

BG_TILE: int = 1024              # Starfield texture is 1024x1024

# ── Player physics ──────────────────────────────────────────────────────────
ROT_SPEED: float = 150.0         # deg / s
THRUST: float = 250.0            # px / s^2
BRAKE: float = 125.0             # px / s^2  (reverse thrust)
MAX_SPD: float = 450.0           # px / s cap
DAMPING: float = 0.98875         # per-frame velocity multiplier (space drag)

DEAD_ZONE: float = 0.15          # Gamepad analogue stick dead zone

# ── Asset paths ─────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

STARFIELD_DIR = os.path.join(
    _HERE, "assets",
    "SBS - Seamless Space Backgrounds - Large 1024x1024",
    "Large 1024x1024", "Starfields",
)
SHMUP_DIR = os.path.join(_HERE, "assets", "ShmupAssets_V1")
FACTION_SHIPS_DIR = os.path.join(_HERE, "assets", "256Spaceships")
LASER_DIR = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Space Shooter Redux", "PNG", "Lasers",
)
SFX_WEAPONS_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Weapons", "Energy Weapons",
)
SFX_EXPLOSIONS_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Weapons", "Explosions",
)
SFX_BIO_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Biomechanical",
)
SFX_VEHICLES_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Vehicles",
)
SFX_INTERFACE_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Interface", "Other Interface",
)
MUSIC_VOL1_DIR = os.path.join(
    _HERE, "assets", "Space and Science Fiction Music Pack Vol 1",
    "Space Science Fiction Music Pack", "audio",
)
MUSIC_VOL2_DIR = os.path.join(
    _HERE, "assets", "Space and Science Fiction Music Pack Vol 2",
    "Space_Science_Fiction_MusicPackVol.2", "Music",
)
MUSIC_VOLUME: float = 0.35          # background music volume (0.0 – 1.0)

ASTEROID_PNG = os.path.join(_HERE, "assets", "Pixel Art Space", "Asteroid.png")
ALIEN_SHIP_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "Ship.png",
)
ALIEN_FX_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "Effects.png",
)
EXPLOSION_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets", "asteroids crusher",
    "Explosions", "PNG", "explosion.png",
)
IRON_ICON_PNG = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Voxel Pack", "PNG", "Items", "ore_ironAlt.png",
)
SHIELD_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets", "asteroids crusher",
    "Weapons", "PNG", "shield_frames.png",
)

# ── Shield sprite-sheet constants ───────────────────────────────────────────
SHIELD_COLS: int = 3
SHIELD_ROWS: int = 2
SHIELD_FRAME_W: int = 280          # each frame is 280x280 px in the sheet
SHIELD_FRAME_H: int = 280
SHIELD_ANIM_FPS: float = 8.0
SHIELD_SCALE: float = 0.50         # 280x0.5 = 140 px bubble -- wraps 96 px ship
SHIELD_ROT_SPEED: float = 25.0     # slow bubble rotation, degrees/s
SHIELD_HIT_FLASH: float = 0.25     # seconds of bright flash when shield absorbs a hit

# ── Weapon / projectile constants ───────────────────────────────────────────
NOSE_OFFSET: float = 44.0        # px ahead of ship centre where projectiles spawn
GUN_LATERAL_OFFSET: float = 10.0 # px left/right of centre axis for dual-gun ships

# ── Contrail constants ─────────────────────────────────────────────────────
CONTRAIL_MAX_PARTICLES: int = 20       # max trail particles when thrusting
CONTRAIL_SPAWN_RATE: float = 30.0      # particles per second when thrusting
CONTRAIL_LIFETIME: float = 0.5         # seconds each particle lives
CONTRAIL_START_SIZE: float = 6.0       # initial particle radius
CONTRAIL_END_SIZE: float = 1.0         # final particle radius at end of life
CONTRAIL_OFFSET: float = -30.0        # px behind ship centre (negative = behind)
# Per-ship contrail colour palettes (start colour, end colour)
CONTRAIL_COLOURS = {
    "Cruiser":     ((100, 180, 255), (20, 40, 120)),     # blue
    "Bastion":     ((255, 200, 80),  (120, 60, 10)),     # orange
    "Aegis":       ((80, 255, 180),  (10, 80, 50)),      # green
    "Striker":     ((255, 100, 100), (120, 20, 20)),      # red
    "Thunderbolt": ((200, 120, 255), (60, 20, 100)),      # purple
}

# ── Inventory constants ────────────────────────────────────────────────────
INV_COLS: int = 5
INV_ROWS: int = 5
INV_CELL: int = 48               # cell size in px
INV_PAD: int = 10                # padding around grid
INV_HEADER: int = 32             # space for title text above grid

INV_FOOTER: int = 20             # space for hint text below grid
INV_W: int = INV_COLS * INV_CELL + INV_PAD * 2
INV_H: int = INV_ROWS * INV_CELL + INV_PAD * 2 + INV_HEADER + INV_FOOTER

# ── Player ship stats (defaults; overridden by ship type selection) ─────────
PLAYER_MAX_HP: int = 100
PLAYER_MAX_SHIELD: int = 100         # full shield capacity
SHIELD_REGEN_RATE: float = 0.5       # shield points restored per second (1 per 2 s)
SHIP_COLLISION_DAMAGE: int = 5       # HP/shield lost per asteroid collision
SHIP_COLLISION_COOLDOWN: float = 0.5 # seconds of invincibility after a hit
SHIP_BOUNCE: float = 0.55            # velocity restitution on bounce (0=dead stop,1=elastic)
# Approximate circle radii used for overlap push-out (pixels)
SHIP_RADIUS: float = 28.0
ASTEROID_RADIUS: float = 26.0

# ── Faction definitions ────────────────────────────────────────────────────
FACTIONS = {
    "Earth": "faction_1_ships_128x128.png",
    "Colonial": "faction_2_ships_128x128.png",
    "Heavy World": "faction_5_ships_128x128.png",
    "Ascended": "faction_7_ships_128x128.png",
}

# Ship type → sprite-sheet row (0-indexed) within each faction sheet (8x8, 128x128 frames)
# Row 4 (0-idx 3) = Thunderbolt, Row 5 (0-idx 4) = Striker, Row 6 (0-idx 5) = Aegis,
# Row 7 (0-idx 6) = Bastion, Row 8 (0-idx 7) = Cruiser
SHIP_FRAME_SIZE: int = 128
SHIP_SHEET_COLS: int = 8   # 8 upgrade levels per ship type

SHIP_TYPES = {
    "Cruiser":     {"row": 7, "hp": 100, "shields": 100, "shield_regen": 0.5,
                    "rot_speed": 150.0, "thrust": 250.0, "brake": 125.0,
                    "max_speed": 450.0, "damping": 0.98875, "guns": 1},
    "Bastion":     {"row": 6, "hp": 150, "shields":  50, "shield_regen": 0.5,
                    "rot_speed": 150.0, "thrust": 200.0, "brake": 125.0,
                    "max_speed": 450.0, "damping": 0.98875, "guns": 1},
    "Aegis":       {"row": 5, "hp":  50, "shields": 150, "shield_regen": 1.0,
                    "rot_speed": 100.0, "thrust": 250.0, "brake": 125.0,
                    "max_speed": 450.0, "damping": 0.98875, "guns": 1},
    "Striker":     {"row": 4, "hp": 100, "shields":  50, "shield_regen": 0.5,
                    "rot_speed": 150.0, "thrust": 300.0, "brake": 100.0,
                    "max_speed": 450.0, "damping": 0.983125, "guns": 1},
    "Thunderbolt": {"row": 3, "hp": 100, "shields": 100, "shield_regen": 0.5,
                    "rot_speed": 150.0, "thrust": 200.0, "brake": 125.0,
                    "max_speed": 400.0, "damping": 0.98875, "guns": 2},
}

# ── Asteroid constants ──────────────────────────────────────────────────────
ASTEROID_COUNT: int = 50
ASTEROID_HP: int = 100
ASTEROID_IRON_YIELD: int = 10
ASTEROID_MIN_DIST: float = 400.0   # min distance from world centre at spawn
# Explosion sheet: 1260x140 px -> 9 frames of 140x140 each
EXPLOSION_FRAMES: int = 9
EXPLOSION_FRAME_W: int = 140
EXPLOSION_FRAME_H: int = 140
EXPLOSION_FPS: float = 15.0        # frames per second

# ── Small Alien Ship constants ──────────────────────────────────────────────
ALIEN_COUNT: int = 20
ALIEN_HP: int = 50
ALIEN_SCALE: float = 0.10               # display scale  (461 px source -> ~46 px wide)
ALIEN_RADIUS: float = 20.0              # approx collision radius in px
ALIEN_SPEED: float = 120.0              # patrol / pursuit movement speed  px/s
ALIEN_PATROL_RADIUS_MIN: float = 100.0  # minimum patrol-area radius  px
ALIEN_PATROL_RADIUS_MAX: float = 150.0  # maximum patrol-area radius  px
ALIEN_DETECT_DIST: float = 500.0        # player centre-to-centre px -> triggers pursuit
ALIEN_LASER_DAMAGE: float = 10.0        # HP per alien laser hit
ALIEN_LASER_RANGE: float = 500.0        # alien laser max range  px
ALIEN_LASER_SPEED: float = 650.0        # alien laser projectile speed  px/s
ALIEN_FIRE_COOLDOWN: float = 1.5        # seconds between alien shots
ALIEN_MIN_DIST: float = 400.0           # min spawn distance from world centre  px
# ── Alien physics / collision constants ─────────────────────────────────────
ALIEN_BOUNCE: float = 0.65             # velocity restitution on collision bounce
ALIEN_VEL_DAMPING: float = 0.97        # per-frame physics velocity decay (@ 60 fps)
ALIEN_COL_COOLDOWN: float = 0.40       # seconds before another bounce can re-trigger
ALIEN_AVOIDANCE_RADIUS: float = 65.0   # px beyond obstacle edge where steering begins
ALIEN_AVOIDANCE_FORCE: float = 2.5     # avoidance repulsion weight relative to pursuit
ALIEN_BUMP_FLASH: float = 0.15         # seconds of orange tint on collision bump

# ── Iron pickup constants ───────────────────────────────────────────────────
IRON_PICKUP_DIST: float = 40.0   # px -- edge distance (from ship hull) to trigger fly-to-ship
IRON_FLY_SPEED: float = 400.0    # px/s -- speed of iron token once attracted
WORLD_ITEM_LIFETIME: float = 600.0  # seconds before a dropped item despawns (10 min)
EJECT_DIST: float = 60.0            # px from ship EDGE where ejected items land

# ── Camera shake constants ──────────────────────────────────────────────────
SHAKE_DURATION: float = 0.25     # seconds of camera shake after a hull collision
SHAKE_AMPLITUDE: float = 8.0     # max pixel offset during shake

# ── Mini-map constants (drawn inside the status panel) ──────────────────────
MINIMAP_PAD: int = 10
MINIMAP_W: int = STATUS_WIDTH - 2 * MINIMAP_PAD   # 193 px wide
MINIMAP_H: int = MINIMAP_W                         # square
MINIMAP_X: int = MINIMAP_PAD
MINIMAP_Y: int = MINIMAP_PAD + 16                  # 26 px from bottom; label sits below

# ── Escape menu constants ─────────────────────────────────────────────────
MENU_W: int = 320
MENU_H: int = 340
MENU_BTN_W: int = 240
MENU_BTN_H: int = 40
MENU_BTN_GAP: int = 16

# ── Save/Load slot sub-menu constants ─────────────────────────────────────
SAVE_SLOT_COUNT: int = 10
SAVE_MENU_W: int = 420
SAVE_MENU_H: int = 590
SAVE_SLOT_W: int = 380
SAVE_SLOT_H: int = 42
SAVE_SLOT_GAP: int = 6
