"""Centralised game constants for Space Survivalcraft.

Sections:
  1. Window / World / Resolution
  2. Player Physics
  3. Asset Paths (directories, PNGs, SFX)
  4. Shield Sprite Sheet
  5. Weapon / Projectile / Contrail
  6. Inventory / Quick Use
  7. Player Ship Stats / Factions / Ship Types
  8. Ship Module System
  9. Asteroid / Explosion
 10. Alien Ship AI & Physics
 11. Respawn / Pickup / Fog / Camera
 12. UI: Mini-map / Escape Menu / Save-Load
 13. Building System
 14. Zone 2 (Nebula)
 15. Homing Missiles / Special Abilities
 16. Boss Encounter
"""
from __future__ import annotations

import os

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Window / World / Resolution
# ═══════════════════════════════════════════════════════════════════════════════
SCREEN_WIDTH: int = 1280
SCREEN_HEIGHT: int = 800
SCREEN_TITLE: str = "Call of Orion"

STATUS_WIDTH: int = 213          # Left status panel width (~1/6 of screen)
WORLD_WIDTH: int = 6400          # 200 x 32-px tiles
WORLD_HEIGHT: int = 6400

BG_TILE: int = 1024              # Starfield texture is 1024x1024

RESOLUTION_PRESETS: list[tuple[int, int]] = [
    (1280, 800),
    (1366, 768),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
]

# ═══════════════════════════════════════════════════════════════════════════════
# 2. Player Physics
# ═══════════════════════════════════════════════════════════════════════════════
ROT_SPEED: float = 150.0         # deg / s
THRUST: float = 250.0            # px / s^2
BRAKE: float = 125.0             # px / s^2  (reverse thrust)
MAX_SPD: float = 450.0           # px / s cap
DAMPING: float = 0.98875         # per-frame velocity multiplier (space drag)

DEAD_ZONE: float = 0.15          # Gamepad analogue stick dead zone

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Asset Paths
# ═══════════════════════════════════════════════════════════════════════════════
_HERE = os.path.dirname(os.path.abspath(__file__))

# ── Directories ────────────────────────────────────────────────────────────
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

# ── PNG assets ─────────────────────────────────────────────────────────────
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
REPAIR_PACK_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "items.png",
)
REPAIR_PACK_CROP = (198, 0, 396, 198)  # (x0, y0, x1, y1) for PIL crop
SHIELD_RECHARGE_PNG = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Space Shooter Redux", "PNG", "Power-ups", "powerupBlue_bolt.png",
)
BLUEPRINT_PNG = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Simple Space", "PNG", "Retina", "satellite_D.png",
)
MISSILE_PNG = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Space Shooter Extension", "PNG", "Sprites", "Missiles", "spaceMissiles_003.png",
)

# ── SFX assets ─────────────────────────────────────────────────────────────
SFX_MISSILE_LAUNCH = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Weapons", "Misc Weapons",
    "Sci-Fi Missile Flyby 1.wav",
)
SFX_MISSILE_IMPACT = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Weapons", "Explosions",
    "Sci-Fi Missile Impact Explosion 1.wav",
)
SFX_MISTY_STEP = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Energy",
    "Sci-Fi Eerie Crystalline Radiation Loop 1.wav",
)
SFX_FORCE_WALL = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Energy",
    "Sci-Fi Energy Pulse 1.wav",
)

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Shield Sprite Sheet
# ═══════════════════════════════════════════════════════════════════════════════
SHIELD_COLS: int = 3
SHIELD_ROWS: int = 2
SHIELD_FRAME_W: int = 280          # each frame is 280x280 px in the sheet
SHIELD_FRAME_H: int = 280
SHIELD_ANIM_FPS: float = 8.0
SHIELD_SCALE: float = 0.50         # 280x0.5 = 140 px bubble -- wraps 96 px ship
SHIELD_ROT_SPEED: float = 25.0     # slow bubble rotation, degrees/s
SHIELD_HIT_FLASH: float = 0.25     # seconds of bright flash when shield absorbs a hit

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Weapon / Projectile / Contrail
# ═══════════════════════════════════════════════════════════════════════════════
NOSE_OFFSET: float = 44.0        # px ahead of ship centre where projectiles spawn
GUN_LATERAL_OFFSET: float = 10.0 # px left/right of centre axis for dual-gun ships

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

# Broadside weapon stats
BROADSIDE_COOLDOWN: float = 0.50      # seconds between shots
BROADSIDE_DAMAGE: int = 25            # same as basic laser
BROADSIDE_SPEED: float = 600.0        # projectile speed
BROADSIDE_RANGE: float = 400.0        # max travel distance

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Inventory / Quick Use
# ═══════════════════════════════════════════════════════════════════════════════
INV_COLS: int = 5
INV_ROWS: int = 5
INV_CELL: int = 48               # cell size in px
INV_PAD: int = 10                # padding around grid
INV_HEADER: int = 32             # space for title text above grid
INV_FOOTER: int = 20             # space for hint text below grid
INV_W: int = INV_COLS * INV_CELL + INV_PAD * 2
INV_H: int = INV_ROWS * INV_CELL + INV_PAD * 2 + INV_HEADER + INV_FOOTER

STATION_INV_COLS: int = 10
STATION_INV_ROWS: int = 10
STATION_INV_CELL: int = 40            # cell size in px (smaller than ship inv)
STATION_INV_PAD: int = 10

# Item stack limits
MAX_STACK: dict[str, int] = {
    "iron": 999,
    "repair_pack": 99,
    "shield_recharge": 99,
    "copper": 999,
    "missile": 500,
}
MAX_STACK_DEFAULT: int = 10  # for blueprints, modules, etc.

QUICK_USE_SLOTS: int = 10
QUICK_USE_CELL: int = 30              # cell size in px

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Player Ship Stats / Factions / Ship Types
# ═══════════════════════════════════════════════════════════════════════════════
PLAYER_MAX_HP: int = 100
PLAYER_MAX_SHIELD: int = 100         # full shield capacity
SHIELD_REGEN_RATE: float = 0.5       # shield points restored per second (1 per 2 s)
SHIP_COLLISION_DAMAGE: int = 5       # HP/shield lost per asteroid collision
SHIP_COLLISION_COOLDOWN: float = 0.5 # seconds of invincibility after a hit
SHIP_BOUNCE: float = 0.55            # velocity restitution on bounce (0=dead stop,1=elastic)
# Approximate circle radii used for overlap push-out (pixels)
SHIP_RADIUS: float = 28.0
ASTEROID_RADIUS: float = 26.0

FACTIONS = {
    "Earth": "faction_1_ships_128x128.png",
    "Colonial": "faction_2_ships_128x128.png",
    "Heavy World": "faction_5_ships_128x128.png",
    "Ascended": "faction_7_ships_128x128.png",
}

# Ship type -> sprite-sheet row (0-indexed) within each faction sheet (8x8, 128x128 frames)
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

# Ship level upgrade bonuses (per level above 1)
SHIP_LEVEL_HP_BONUS: int = 25          # +25 max HP per upgrade
SHIP_LEVEL_SHIELD_BONUS: int = 25      # +25 max shields per upgrade
SHIP_LEVEL_ABILITY_BONUS: float = 25.0 # +25 ability meter max per upgrade
SHIP_LEVEL_MODULE_BONUS: int = 2       # +2 module slots per upgrade
SHIP_MAX_LEVEL: int = 2                # cap while only Double Star + Nebula exist

# ═══════════════════════════════════════════════════════════════════════════════
# 8. Ship Module System
# ═══════════════════════════════════════════════════════════════════════════════
MODULE_SLOT_COUNT: int = 4
MODULE_SLOT_CELL: int = 36            # cell size in px (slightly larger than quick-use)

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
    "rear_turret":     {"label": "Rear Turret",       "effect": "rear_turret",   "value": 1,
                        "craft_cost": 200, "icon": os.path.join(_MODULE_ITEMS_DIR, "Poison.png"),
                        "advanced": True},
    "homing_missile":  {"label": "Homing Missiles",   "effect": "homing",        "value": 1,
                        "craft_cost": 50, "craft_cost_copper": 25,
                        "icon": MISSILE_PNG, "advanced": True,
                        "consumable": True, "craft_time": 30.0, "craft_count": 20,
                        "item_key": "missile"},
    "misty_step":      {"label": "Misty Step",        "effect": "misty_step",    "value": 1,
                        "craft_cost": 400, "craft_cost_copper": 200,
                        "icon": os.path.join(_MODULE_ITEMS_DIR, "Energy.png"),
                        "advanced": True},
    "force_wall":      {"label": "Force Wall",        "effect": "force_wall",    "value": 1,
                        "craft_cost": 400, "craft_cost_copper": 250,
                        "icon": os.path.join(_MODULE_ITEMS_DIR, "Shield.png"),
                        "advanced": True},
    "death_blossom":   {"label": "Death Blossom",     "effect": "death_blossom", "value": 1,
                        "craft_cost": 600, "craft_cost_copper": 400,
                        "icon": os.path.join(_MODULE_ITEMS_DIR, "Nuke.png"),
                        "advanced": True},
    "advanced_crafter": {"label": "Adv. Crafter BP",  "effect": "none",          "value": 0,
                        "craft_cost": 0, "icon": os.path.join(_MODULE_ITEMS_DIR, "Blank.png"),
                        "blueprint_only": True},
}

# ═══════════════════════════════════════════════════════════════════════════════
# 9. Asteroid / Explosion
# ═══════════════════════════════════════════════════════════════════════════════
ASTEROID_COUNT: int = 75
ASTEROID_HP: int = 100
ASTEROID_IRON_YIELD: int = 10
ASTEROID_MIN_DIST: float = 400.0   # min distance from world centre at spawn
# Explosion sheet: 1260x140 px -> 9 frames of 140x140 each
EXPLOSION_FRAMES: int = 9
EXPLOSION_FRAME_W: int = 140
EXPLOSION_FRAME_H: int = 140
EXPLOSION_FPS: float = 15.0        # frames per second

# ═══════════════════════════════════════════════════════════════════════════════
# 10. Alien Ship AI & Physics
# ═══════════════════════════════════════════════════════════════════════════════
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
ALIEN_STANDOFF_DIST: float = 300.0     # preferred orbit distance for ranged aliens  px
ALIEN_MIN_DIST: float = 400.0           # min spawn distance from world centre  px
# Collision / physics
ALIEN_BOUNCE: float = 0.65             # velocity restitution on collision bounce
ALIEN_VEL_DAMPING: float = 0.97        # per-frame physics velocity decay (@ 60 fps)
ALIEN_COL_COOLDOWN: float = 0.40       # seconds before another bounce can re-trigger
ALIEN_ASTEROID_DAMAGE: int = 10        # damage to alien from asteroid collision
ALIEN_AVOIDANCE_RADIUS: float = 65.0   # px beyond obstacle edge where steering begins
ALIEN_AVOIDANCE_FORCE: float = 2.5     # avoidance repulsion weight relative to pursuit
ALIEN_BUMP_FLASH: float = 0.15         # seconds of orange tint on collision bump
ALIEN_STUCK_TIME: float = 2.0         # seconds before stuck detection triggers
ALIEN_STUCK_DIST: float = 10.0        # px — if alien moved less than this in STUCK_TIME, it's stuck

# ═══════════════════════════════════════════════════════════════════════════════
# 11. Respawn / Pickup / Fog / Camera
# ═══════════════════════════════════════════════════════════════════════════════
RESPAWN_INTERVAL: float = 60.0           # seconds (1 minute) between respawn checks
RESPAWN_EXCLUSION_RADIUS: float = 300.0  # px — no respawn within this range of a building
ALIEN_IRON_DROP: int = 5                 # iron units dropped when an alien ship is destroyed

IRON_PICKUP_DIST: float = 40.0   # px -- edge distance (from ship hull) to trigger fly-to-ship
IRON_FLY_SPEED: float = 400.0    # px/s -- speed of iron token once attracted
WORLD_ITEM_LIFETIME: float = 600.0  # seconds before a dropped item despawns (10 min)
EJECT_DIST: float = 60.0            # px from ship EDGE where ejected items land

FOG_REVEAL_RADIUS: float = 400.0        # px — radius around ship that gets revealed (800 px diameter)
FOG_CELL_SIZE: int = 50                 # px per fog grid cell
FOG_GRID_W: int = WORLD_WIDTH // FOG_CELL_SIZE    # 128 cells
FOG_GRID_H: int = WORLD_HEIGHT // FOG_CELL_SIZE   # 128 cells

SHAKE_DURATION: float = 0.25     # seconds of camera shake after a hull collision
SHAKE_AMPLITUDE: float = 8.0     # max pixel offset during shake

# ═══════════════════════════════════════════════════════════════════════════════
# 12. UI: Mini-map / Escape Menu / Save-Load
# ═══════════════════════════════════════════════════════════════════════════════
MINIMAP_PAD: int = 10
MINIMAP_W: int = STATUS_WIDTH - 2 * MINIMAP_PAD   # 193 px wide
MINIMAP_H: int = MINIMAP_W                         # square
MINIMAP_X: int = MINIMAP_PAD
MINIMAP_Y: int = MINIMAP_PAD + 16                  # 26 px from bottom; label sits below

MENU_W: int = 320
MENU_H: int = 770
MENU_BTN_W: int = 240
MENU_BTN_H: int = 40
MENU_BTN_GAP: int = 16

SAVE_SLOT_COUNT: int = 10
SAVE_MENU_W: int = 420
SAVE_MENU_H: int = 590
SAVE_SLOT_W: int = 380
SAVE_SLOT_H: int = 42
SAVE_SLOT_GAP: int = 6

# ═══════════════════════════════════════════════════════════════════════════════
# 13. Building System
# ═══════════════════════════════════════════════════════════════════════════════
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
    "Advanced Crafter": {"png": "spaceBuilding_001.png", "hp": 150, "cost": 1000,
                        "cost_copper": 500,
                        "max": None, "module_slots": 0, "connectable": True,
                        "free_place": False, "slots_used": 2,
                        "requires_blueprint": "advanced_crafter"},
    "Fission Generator": {"png": "spaceBuilding_005.png", "hp": 200, "cost": 1000,
                        "cost_copper": 500,
                        "max": 2,    "module_slots": 12, "connectable": True,
                        "free_place": False, "slots_used": 2},
    "Advanced Ship":   {"png": "spaceBuilding_006.png", "hp": 100, "cost": 1000,
                        "cost_copper": 500,
                        "max": None, "module_slots": 0, "connectable": False,
                        "free_place": True, "slots_used": 0,
                        "is_ship": True},
    "Shield Generator": {"png": "spaceBuilding_002.png", "hp": 150, "cost": 800,
                        "cost_copper": 400,
                        "max": 1,    "module_slots": 0, "connectable": True,
                        "free_place": False, "slots_used": 3},
    "Missile Array":   {"png": "spaceBuilding_022.png", "hp": 150, "cost": 600,
                        "cost_copper": 300,
                        "max": None, "module_slots": 0, "connectable": False,
                        "free_place": True,  "slots_used": 2},
}

# Turret combat
TURRET_RANGE: float = 400.0         # px — alien detection range for auto-fire
TURRET_DAMAGE: float = 10.0         # HP per turret shot
TURRET_COOLDOWN: float = 1.5        # seconds between turret shots
TURRET_LASER_SPEED: float = 700.0   # turret projectile speed  px/s
TURRET_LASER_RANGE: float = 500.0   # turret projectile max range  px
TURRET_FREE_PLACE_RADIUS: float = 300.0  # max distance from Home Station for turrets

# Repair module
REPAIR_RANGE: float = 300.0             # px — distance from Home Station for repair to activate
REPAIR_RATE: float = 1.0               # HP restored per second when near Home Station
REPAIR_SHIELD_BOOST: float = 1.0      # extra shield regen pt/s from Repair Module

# Crafting
CRAFT_TIME: float = 60.0              # seconds to craft one Repair Pack batch
CRAFT_IRON_COST: int = 200            # iron needed from station inventory
CRAFT_RESULT_COUNT: int = 5           # number of Repair Packs produced per craft
REPAIR_PACK_HEAL: float = 0.50       # fraction of max_hp healed per Repair Pack use
SHIELD_RECHARGE_HEAL: float = 0.50   # fraction of max_shields recharged per Shield Recharge use

# Docking / placement / capacity
DOCK_SNAP_DIST: float = 40.0        # px — max distance to snap to a port
BASE_MODULE_CAPACITY: int = 4
BUILDING_RADIUS: float = 30.0
STATION_INFO_RANGE: float = 300.0

# Build menu UI
BUILD_MENU_W: int = 280
BUILD_MENU_H: int = 420
BUILD_MENU_ITEM_H: int = 48
BUILD_MENU_PAD: int = 10

# ═══════════════════════════════════════════════════════════════════════════════
# 14. Zone 2 (Nebula)
# ═══════════════════════════════════════════════════════════════════════════════
ZONE2_WIDTH: int = 6400
ZONE2_HEIGHT: int = 6400

# Double iron asteroids
DOUBLE_IRON_COUNT: int = 15
DOUBLE_IRON_HP: int = ASTEROID_HP * 2        # 200
DOUBLE_IRON_YIELD: int = ASTEROID_IRON_YIELD * 2  # 20
DOUBLE_IRON_SCALE: float = 2.0
DOUBLE_IRON_XP: int = 10

# Copper asteroids
COPPER_ASTEROID_COUNT: int = 75
COPPER_ASTEROID_HP: int = 100
COPPER_YIELD: int = 10
COPPER_IRON_YIELD: int = 5
COPPER_XP: int = 10
COPPER_ASTEROID_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "asteroids crusher", "Asteroids", "PNG", "asteroid_02.png",
)
COPPER_PICKUP_PNG = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Space Shooter Redux", "PNG", "Power-ups", "things_bronze.png",
)

# Gaseous areas
GAS_AREA_COUNT: int = 40
GAS_AREA_DAMAGE: float = 20.0       # damage per second + on first contact
GAS_AREA_SLOW: float = 0.5          # speed multiplier while inside gas
GAS_AREA_MIN_SIZE: int = 64
GAS_AREA_MAX_SIZE: int = 384

# Wandering magnetic asteroids
WANDERING_COUNT: int = 15
WANDERING_HP: int = 150
WANDERING_IRON_YIELD: int = 15
WANDERING_SPEED: float = 80.0       # wander speed px/s
WANDERING_MAGNET_DIST: float = 80.0 # px attraction range
WANDERING_MAGNET_SPEED: float = 200.0
WANDERING_DAMAGE: int = 15
WANDERING_RADIUS: float = 26.0

# Zone 2 alien types
Z2_ALIEN_SHIP_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "Ship.png",
)
Z2_SHIELDED_COUNT: int = 15
Z2_SHIELDED_SHIELD: int = 50
Z2_SHIELDED_XP: int = 50
Z2_FAST_COUNT: int = 15
Z2_FAST_SPEED: float = 160.0
Z2_FAST_XP: int = 60
Z2_GUNNER_COUNT: int = 15
Z2_GUNNER_XP: int = 70
Z2_RAMMER_COUNT: int = 15
Z2_RAMMER_HP: int = ALIEN_HP * 2   # 100
Z2_RAMMER_SHIELD: int = 50
Z2_RAMMER_XP: int = 80

# ═══════════════════════════════════════════════════════════════════════════════
# 15. Homing Missiles / Special Abilities
# ═══════════════════════════════════════════════════════════════════════════════
MISSILE_COST_IRON: int = 50
MISSILE_COST_COPPER: int = 25
MISSILE_CRAFT_TIME: float = 30.0
MISSILE_FIRE_RATE: float = 0.3
MISSILE_DAMAGE: float = 50.0
MISSILE_SPEED: float = 400.0
MISSILE_RANGE: float = 1500.0
MISSILE_TURN_RATE: float = 180.0    # deg/s homing turn rate
MISSILE_ARRAY_RANGE: float = 600.0  # scan range for Missile Array
MISSILE_ARRAY_COOLDOWN: float = 3.0 # seconds between launches

# Special ability meter
ABILITY_METER_MAX: float = 100.0
ABILITY_REGEN_RATE: float = 5.0     # points per second

# Misty step module
MISTY_STEP_DISTANCE: float = 300.0
MISTY_STEP_COST: float = 20.0
MISTY_STEP_COOLDOWN: float = 2.0

# Force wall module
FORCE_WALL_LENGTH: float = 100.0
FORCE_WALL_DURATION: float = 20.0
FORCE_WALL_COST: float = 30.0

# Death blossom module
DEATH_BLOSSOM_FIRE_RATE: float = 0.3   # seconds between volleys
DEATH_BLOSSOM_MISSILES_PER_VOLLEY: int = 8
DEATH_BLOSSOM_HP_AFTER: int = 10

# ═══════════════════════════════════════════════════════════════════════════════
# 16. Boss Encounter
# ═══════════════════════════════════════════════════════════════════════════════
BOSS_MONSTER_PNG = os.path.join(
    _HERE, "assets", "256Spacemonsters", "faction_6_monsters_128x128.png",
)
BOSS_FRAME_SIZE: int = 128
BOSS_SHEET_COLS: int = 8
BOSS_SHEET_ROWS: int = 8

BOSS_HP: int = 2000
BOSS_SHIELDS: int = 500
BOSS_SHIELD_REGEN: float = 5.0          # shields/s (Phase 1)
BOSS_SHIELD_REGEN_P2: float = 10.0      # shields/s (Phase 2)
BOSS_SPEED: float = 180.0               # px/s
BOSS_SPEED_P2: float = 220.0            # px/s (Phase 2+)
BOSS_ROT_SPEED: float = 60.0            # deg/s
BOSS_SCALE: float = 0.60                # 128*0.6 ≈ 77 px displayed
BOSS_RADIUS: float = 38.0               # collision radius in px
BOSS_DETECT_RANGE: float = 800.0        # px — aggro range

# Boss main cannon
BOSS_CANNON_DAMAGE: float = 40.0
BOSS_CANNON_COOLDOWN: float = 1.0       # seconds (halved in Phase 3)
BOSS_CANNON_SPEED: float = 550.0        # px/s
BOSS_CANNON_RANGE: float = 700.0        # px

# Boss spread shot (3 projectiles in a 30° cone)
BOSS_SPREAD_DAMAGE: float = 15.0
BOSS_SPREAD_COOLDOWN: float = 3.0       # seconds (halved in Phase 3)
BOSS_SPREAD_SPEED: float = 500.0
BOSS_SPREAD_RANGE: float = 600.0
BOSS_SPREAD_COUNT: int = 3
BOSS_SPREAD_ARC: float = 30.0           # degrees total arc

# Boss charge attack (Phase 2+)
BOSS_CHARGE_DAMAGE: float = 60.0
BOSS_CHARGE_SPEED: float = 600.0        # px/s during dash
BOSS_CHARGE_WINDUP: float = 2.0         # seconds telegraph
BOSS_CHARGE_DURATION: float = 0.8       # seconds of dash
BOSS_CHARGE_COOLDOWN: float = 8.0       # seconds between charges

# Boss collision
BOSS_COLLISION_DAMAGE: int = 25
BOSS_COLLISION_COOLDOWN: float = 0.5
BOSS_BOUNCE: float = 0.3                # heavy boss barely bounces

# Boss phase thresholds (fraction of max HP)
BOSS_PHASE2_HP: float = 0.50            # 50% HP → Phase 2
BOSS_PHASE3_HP: float = 0.25            # 25% HP → Phase 3

# Boss rewards
BOSS_XP_REWARD: int = 500
BOSS_IRON_DROP: int = 200
