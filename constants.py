"""Centralised game constants for Space Survivalcraft."""
from __future__ import annotations

import os

# ── Window / World ──────────────────────────────────────────────────────────
SCREEN_WIDTH: int = 1280
SCREEN_HEIGHT: int = 800
SCREEN_TITLE: str = "Call of Orion"

STATUS_WIDTH: int = 213          # Left status panel width (~1/6 of screen)
WORLD_WIDTH: int = 6400          # 200 x 32-px tiles
WORLD_HEIGHT: int = 6400

BG_TILE: int = 1024              # Starfield texture is 1024x1024

# ── Resolution presets ────────────────────────────────────────────────────
RESOLUTION_PRESETS: list[tuple[int, int]] = [
    (1280, 800),
    (1366, 768),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
]

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
ASTEROID_COUNT: int = 75
ASTEROID_HP: int = 100
ASTEROID_IRON_YIELD: int = 10
ASTEROID_MIN_DIST: float = 400.0   # min distance from world centre at spawn
# Explosion sheet: 1260x140 px -> 9 frames of 140x140 each
EXPLOSION_FRAMES: int = 9
EXPLOSION_FRAME_W: int = 140
EXPLOSION_FRAME_H: int = 140
EXPLOSION_FPS: float = 15.0        # frames per second

# ── Small Alien Ship constants ──────────────────────────────────────────────
ALIEN_COUNT: int = 30
ALIEN_HP: int = 50
ALIEN_SCALE: float = 0.10               # display scale  (461 px source -> ~46 px wide)
ALIEN_RADIUS: float = 20.0              # approx collision radius in px
ALIEN_SPEED: float = 120.0              # patrol / pursuit movement speed  px/s
ALIEN_PATROL_RADIUS_MIN: float = 100.0  # minimum patrol-area radius  px
ALIEN_PATROL_RADIUS_MAX: float = 150.0  # maximum patrol-area radius  px
ALIEN_DETECT_DIST: float = 500.0        # player centre-to-centre px -> triggers pursuit
ALIEN_AGGRO_RANGE: float = ALIEN_RADIUS * 8  # 4x ship diameter — projectile nearby triggers pursuit
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
ALIEN_STUCK_TIME: float = 2.0         # seconds before stuck detection triggers
ALIEN_STUCK_DIST: float = 10.0        # px — if alien moved less than this in STUCK_TIME, it's stuck

# ── Respawn constants ──────────────────────────────────────────────────────
RESPAWN_INTERVAL: float = 60.0           # seconds (1 minute) between respawn checks
RESPAWN_EXCLUSION_RADIUS: float = 300.0  # px — no respawn within this range of a building
ALIEN_IRON_DROP: int = 5                 # iron units dropped when an alien ship is destroyed

# ── Iron pickup constants ───────────────────────────────────────────────────
IRON_PICKUP_DIST: float = 40.0   # px -- edge distance (from ship hull) to trigger fly-to-ship
IRON_FLY_SPEED: float = 400.0    # px/s -- speed of iron token once attracted
WORLD_ITEM_LIFETIME: float = 600.0  # seconds before a dropped item despawns (10 min)
EJECT_DIST: float = 60.0            # px from ship EDGE where ejected items land

# ── Fog of war constants ───────────────────────────────────────────────────
FOG_REVEAL_RADIUS: float = 400.0        # px — radius around ship that gets revealed (800 px diameter)
FOG_CELL_SIZE: int = 50                 # px per fog grid cell
FOG_GRID_W: int = WORLD_WIDTH // FOG_CELL_SIZE    # 128 cells
FOG_GRID_H: int = WORLD_HEIGHT // FOG_CELL_SIZE   # 128 cells

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
MENU_H: int = 770
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

# ── Building system constants ────────────────────────────────────────────────
BUILDING_DIR = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Space Shooter Extension", "PNG", "Sprites X2", "Building",
)

BUILDING_TYPES = {
    "Home Station":    {"png": "spaceBuilding_006.png", "hp": 100, "cost": 100,
                        "max": 1,    "module_slots": 0, "connectable": True,
                        "free_place": False, "slots_used": 1},
    "Service Module":  {"png": "spaceBuilding_004.png", "hp":  50, "cost":  25,
                        "max": 4,    "module_slots": 0, "connectable": True,
                        "free_place": False, "slots_used": 1},
    "Power Receiver":  {"png": "spaceBuilding_003.png", "hp":  75, "cost":  50,
                        "max": None, "module_slots": 0, "connectable": True,
                        "free_place": False, "slots_used": 1},
    "Solar Array 1":   {"png": "spaceBuilding_015.png", "hp":  50, "cost":  75,
                        "max": 2,    "module_slots": 6, "connectable": True,
                        "free_place": False, "slots_used": 1},
    "Solar Array 2":   {"png": "spaceBuilding_024.png", "hp":  50, "cost": 100,
                        "max": 2,    "module_slots": 10, "connectable": True,
                        "free_place": False, "slots_used": 1},
    "Turret 1":        {"png": "spaceBuilding_011.png", "hp": 100, "cost":  50,
                        "max": None, "module_slots": 0, "connectable": False,
                        "free_place": True,  "slots_used": 1},
    "Turret 2":        {"png": "spaceBuilding_012.png", "hp": 100, "cost":  75,
                        "max": None, "module_slots": 0, "connectable": False,
                        "free_place": True,  "slots_used": 2},
    "Repair Module":   {"png": "spaceBuilding_009.png", "hp":  75, "cost":  75,
                        "max": 1,    "module_slots": 0, "connectable": True,
                        "free_place": False, "slots_used": 1},
    "Basic Crafter":   {"png": "spaceBuilding_008.png", "hp":  75, "cost": 150,
                        "max": 1,    "module_slots": 0, "connectable": True,
                        "free_place": False, "slots_used": 1},
}

# Turret combat constants
TURRET_RANGE: float = 400.0         # px — alien detection range for auto-fire
TURRET_DAMAGE: float = 10.0         # HP per turret shot
TURRET_COOLDOWN: float = 1.5        # seconds between turret shots
TURRET_LASER_SPEED: float = 700.0   # turret projectile speed  px/s
TURRET_LASER_RANGE: float = 500.0   # turret projectile max range  px
TURRET_FREE_PLACE_RADIUS: float = 300.0  # max distance from Home Station for turrets

# Repair module constants
REPAIR_RANGE: float = 300.0             # px — distance from Home Station for repair to activate
REPAIR_RATE: float = 1.0               # HP restored per second when near Home Station
REPAIR_SHIELD_BOOST: float = 1.0      # extra shield regen pt/s from Repair Module

# Crafting constants
CRAFT_TIME: float = 60.0              # seconds to craft one Repair Pack batch
CRAFT_IRON_COST: int = 200            # iron needed from station inventory
CRAFT_RESULT_COUNT: int = 5           # number of Repair Packs produced per craft
REPAIR_PACK_HEAL: float = 0.50       # fraction of max_hp healed per Repair Pack use

# Station inventory constants
STATION_INV_COLS: int = 10
STATION_INV_ROWS: int = 10
STATION_INV_CELL: int = 40            # cell size in px (smaller than ship inv)
STATION_INV_PAD: int = 10

# Item stack limits
MAX_STACK: dict[str, int] = {
    "iron": 999,
    "repair_pack": 99,
}
MAX_STACK_DEFAULT: int = 10  # for blueprints, modules, etc.

# Quick use bar constants
QUICK_USE_SLOTS: int = 10
QUICK_USE_CELL: int = 30              # cell size in px

# Repair Pack asset (items.png — second 198×198 item in first row)
REPAIR_PACK_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "items.png",
)
REPAIR_PACK_CROP = (198, 0, 396, 198)  # (x0, y0, x1, y1) for PIL crop

# ── Ship Module System ────────────────────────────────────────────────────────
MODULE_SLOT_COUNT: int = 4
MODULE_SLOT_CELL: int = 36            # cell size in px (slightly larger than quick-use)

BLUEPRINT_PNG = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Simple Space", "PNG", "Retina", "satellite_D.png",
)
BLUEPRINT_SPIN_SPEED: float = 180.0   # degrees per second
BLUEPRINT_DROP_CHANCE_ALIEN: float = 0.50
BLUEPRINT_DROP_CHANCE_ASTEROID: float = 0.25

_MODULE_ITEMS_DIR = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "Separate", "Items",
)

MODULE_TYPES: dict[str, dict] = {
    "armor_plate":     {"label": "Armor Plate",      "effect": "max_hp",        "value": 20,
                        "craft_cost": 50,  "icon": os.path.join(_MODULE_ITEMS_DIR, "Blank.png")},
    "engine_booster":  {"label": "Engine Booster",    "effect": "max_speed",     "value": 50,
                        "craft_cost": 75,  "icon": os.path.join(_MODULE_ITEMS_DIR, "Energy.png")},
    "shield_booster":  {"label": "Shield Booster",    "effect": "max_shields",   "value": 20,
                        "craft_cost": 100, "icon": os.path.join(_MODULE_ITEMS_DIR, "Shield.png")},
    "shield_enhancer": {"label": "Shield Enhancer",   "effect": "shield_regen",  "value": 3.0,
                        "craft_cost": 125, "icon": os.path.join(_MODULE_ITEMS_DIR, "Freeze.png")},
    "damage_absorber": {"label": "Damage Absorber",   "effect": "shield_absorb", "value": 3,
                        "craft_cost": 150, "icon": os.path.join(_MODULE_ITEMS_DIR, "Nuke.png")},
    "broadside":       {"label": "Broadside Module",  "effect": "broadside",     "value": 1,
                        "craft_cost": 200, "icon": os.path.join(_MODULE_ITEMS_DIR, "Poison.png")},
}

# Broadside weapon stats
BROADSIDE_COOLDOWN: float = 0.50      # seconds between shots
BROADSIDE_DAMAGE: int = 25            # same as basic laser
BROADSIDE_SPEED: float = 600.0        # projectile speed
BROADSIDE_RANGE: float = 400.0        # max travel distance

# Docking port snap distance
DOCK_SNAP_DIST: float = 40.0        # px — max distance to snap to a port

# Base module capacity (before Solar Arrays)
BASE_MODULE_CAPACITY: int = 4

# Building collision radius (approximate)
BUILDING_RADIUS: float = 30.0

# Station info panel — max distance to open
STATION_INFO_RANGE: float = 300.0

# Build menu UI constants
BUILD_MENU_W: int = 280
BUILD_MENU_H: int = 420
BUILD_MENU_ITEM_H: int = 48
BUILD_MENU_PAD: int = 10
