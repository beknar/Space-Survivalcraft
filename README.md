# Call of Orion

A top-down space survival game built with Python and the Arcade framework. Pilot a customisable spaceship through a vast star field, mine asteroids for iron, fight alien scout ships, build a modular space station, and manage your cargo inventory.

## Features

### Faction & Ship Selection
- Choose from 4 factions: **Earth**, **Colonial**, **Heavy World**, and **Ascended**
- Select from 5 ship types, each with unique stats:
  - **Cruiser** --- balanced all-rounder (100 HP, 100 shields)
  - **Bastion** --- heavy armour tank (150 HP, 50 shields)
  - **Aegis** --- shield specialist with fast regen (50 HP, 150 shields, 1.0 pt/s)
  - **Striker** --- agile high-thrust fighter (300 thrust, lower damping)
  - **Thunderbolt** --- dual-gun weapons platform (2 guns, lower top speed)
- Ship previews and stat breakdowns shown on the selection screen

### Newtonian Flight Model
- Realistic thrust-based movement with inertia and space drag
- Per-ship physics: thrust, braking, rotation speed, max speed, and damping
- Coloured engine contrail particles unique to each ship type
- Seamless thruster engine sound loop while accelerating or braking
- Keyboard and Xbox 360 gamepad support

### Combat
- **Basic Laser** --- high-damage weapon for fighting enemies (25 dmg, 0.30 s cooldown)
- **Mining Beam** --- rapid-fire tool for harvesting asteroids (10 dmg, 0.10 s cooldown)
- Dual-gun ships (Thunderbolt) fire from two laterally-offset hardpoints simultaneously
- Weapon cycling with Tab key or gamepad right bumper
- Camera shake and hit sparks on weapon impacts
- Shield system absorbs damage before HP; regenerates over time
- Animated energy shield bubble with hit-flash visual feedback

### Enemies --- Small Alien Ships
- 20 alien scout ships patrol the world with autonomous AI
- Two AI states: **Patrol** (lazy loops near spawn) and **Pursue** (chase and fire on detection)
- Aliens fire laser bolts faster than the player's max speed --- dodging required
- Obstacle-avoidance steering around asteroids and other aliens
- Physics-based collision bouncing between all entities
- Leash range prevents aliens from chasing indefinitely
- Destroyed aliens drop **5 iron ore** that can be collected by the player
- Alien ships respawn every 2 minutes (not within 300 px of player structures) until 20 again

### Mining & Resources
- 50 iron asteroids scattered across the world, each with 100 HP
- Only the Mining Beam can damage asteroids; Basic Laser has no effect
- Asteroids spin, shake on hit, and explode with animated effects when destroyed
- Destroyed asteroids drop iron ore pickups that fly toward the player when nearby
- Asteroids respawn every 2 minutes (not within 300 px of player structures) until 50 again

### Inventory System
- 5x5 cargo hold grid toggled with I key or gamepad Y button
- Drag-and-drop items between inventory slots
- Drop items into the game world by dragging outside the inventory panel
- Iron ore count displayed in both the inventory and HUD
- Ejected items despawn after 10 minutes

### Space Station Building System
- Spend mined iron to construct a modular space station (B key to open build menu)
- **8 module types** with unique stats, costs, and placement rules:
  - **Home Station** --- root module (100 HP, 100 iron); must be built first
  - **Service Module** --- general connector (50 HP, 25 iron; max 4)
  - **Power Receiver** --- links modules to solar arrays (75 HP, 50 iron)
  - **Solar Array 1** --- adds +6 module capacity (50 HP, 75 iron; max 2)
  - **Solar Array 2** --- adds +10 module capacity (50 HP, 100 iron; max 2)
  - **Turret 1** --- single-barrel auto-fire turret (100 HP, 50 iron)
  - **Turret 2** --- dual-barrel auto-fire turret (100 HP, 75 iron; uses 2 slots)
  - **Repair Module** --- passive HP repair when near Home Station (75 HP, 75 iron; max 1)
- **Edge-to-edge snap** --- connectable modules snap to docking ports (N/S/E/W); both ends connect at their edges
- **Deconstruction** --- Destroy button in build menu activates targeting reticle to remove station pieces
- **Repair Module** --- heals player HP (1/s near Home Station), repairs damaged buildings (1/s), and boosts shield regen (+1 pt/s)
- **Turrets** freely placed within 300 px of the Home Station; auto-target nearest alien
- Mouse wheel rotates buildings during placement; ESC cancels placement
- Base module capacity of 4, expandable with Solar Arrays
- Destroying the Home Station disables all modules
- Aliens attack station buildings; turrets defend automatically

### Station Info Panel (T Key)
- Press **T** while near the station to view building stats
- Shows each module's type and HP (colour-coded green/orange/red)
- Displays module count and remaining capacity
- Auto-closes when the player flies away

### Player-Building Collision
- Player ship can touch the station without harm
- Gentle push-out prevents passing through buildings
- No damage, no bounce, no sound --- just a soft stop

### HUD & Mini-Map
- Left-side status panel showing HP bar, shield bar, speed, heading, iron count, and active weapon
- Faction and ship type indicators
- Controls reference and gamepad connection status
- FPS counter (toggle with F key)
- Now-playing music track name
- Mini-map showing the full 6400x6400 world:
  - **White dot** --- player ship (with cyan heading line)
  - **Grey dots** --- asteroids
  - **Orange dots** --- iron pickups
  - **Red dots** --- alien ships
  - **Cyan dots** --- station buildings

### Save/Load System
- 10 named save slots with full game state preservation
- Saves: player position/velocity/HP/shields, weapon index, inventory, all asteroids, all aliens (including AI state), all pickups, and all station buildings
- Save slot display shows: faction, ship type, HP, shields, and module count

### Escape Menu
- Press ESC to open the menu overlay (gameplay continues)
- **Music and SFX volume sliders** --- draggable with percentage display
- **Resolution** selector with windowed, fullscreen, and borderless options (6 presets: 1280x800 to 3840x2160)
- **Video** player --- configure a video folder, pick files, plays in the HUD (fullscreen only, requires FFmpeg)
- **Resume** / **Save Game** / **Load Game** / **Resolution** / **Video** / **Main Menu** / **Exit Game**
- 10 save slots with a naming overlay (max 24 characters, blinking cursor)
- ESC in sub-menus navigates back; ESC in main menu closes overlay

### Death & Respawn
- Dramatic destruction sequence: large explosion, fire sparks, ship disappears
- Death screen with "SHIP DESTROYED" and three options:
  - **Load Game** --- restore from a save slot
  - **Main Menu** --- return to title screen
  - **Exit Game** --- quit
- Gameplay freezes; effects still animate during the 1.5 s death delay

### Audio
- Shuffled background music playlist from two music packs (auto-advances on track end)
- Per-weapon sound effects with rapid-fire throttling
- Engine thruster loop, collision bump sounds, explosion sounds
- Global music and SFX volume controls in both Options screen and in-game escape menu

### Fog of War
- World starts fully hidden; areas revealed as the player explores
- 800 px diameter reveal around the ship (400 px radius)
- Grey fog overlay on the mini-map; cleared areas show objects
- Fog state persists across save/load
- 128×128 cell grid covering the full world

### Visual Effects
- Animated explosion sprite sheets (9 frames)
- Hit sparks (expanding ring + fading core)
- Fire sparks on hull damage (12 particles, yellow-to-red transition)
- Shield hit flash (alpha pulse on damage absorption)
- Engine contrail particles (ship-type coloured, fading and shrinking)

## Controls

| Action | Keyboard | Xbox 360 Gamepad |
|---|---|---|
| Rotate left/right | Left/Right or A/D | Left stick |
| Thrust forward | Up or W | Left stick up |
| Brake/reverse | Down or S | Left stick down |
| Fire weapon | Space (hold for auto-fire) | A button |
| Cycle weapon | Tab | Right bumper (RB) |
| Open inventory | I | Y button |
| Build menu | B | --- |
| Station info | T (when near station) | --- |
| Toggle FPS | F | --- |
| Escape menu | Escape | --- |

## Requirements

- Python 3.12
- Python Arcade 3.3.3
- Pillow 11.3.0

## Getting Started

1. Clone the repository:

   ```bash
   git clone https://github.com/beknar/Space-Survivalcraft.git
   cd Space-Survivalcraft
   ```

2. Create and activate a virtual environment:

   ```bash
   python3.12 -m venv venv
   ```

   - **Windows CMD**: `venv\Scripts\activate.bat`
   - **PowerShell**: `venv\Scripts\activate.ps1`
   - **Linux/Mac**: `source venv/bin/activate`

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Run the game:

   ```bash
   python main.py
   ```

## Running Tests

```bash
python -m pytest "unit tests/" -v
```

262 unit tests covering all game modules: player physics, weapons, asteroids, aliens (AI, stuck detection), pickups, shields, explosions, contrails, inventory, damage routing, building system (snap, collision, capacity, repair module, heal, port disconnect), respawn mechanics, fog of war, and settings.

## Project Structure

```
Space Survivalcraft/
├── main.py              # Entry point --- creates Window, starts SplashView
├── constants.py         # All game constants (window, physics, assets, factions, ships, buildings)
├── settings.py          # Global AudioSettings singleton (music_volume, sfx_volume)
│
│  ── Views ──
├── splash_view.py       # Title screen with Play/Load/Options/Exit
├── options_view.py      # Music + SFX volume sliders
├── selection_view.py    # Two-phase faction then ship-type picker
├── game_view.py         # Core gameplay loop, cameras, input, music, death logic
│
│  ── UI Overlays ──
├── hud.py               # Left status panel (HP/shield bars, speed, weapon, mini-map)
├── escape_menu.py       # Pause overlay with save/load/quit and audio sliders
├── death_screen.py      # "SHIP DESTROYED" overlay with Load/Menu/Exit
├── inventory.py         # 5x5 cargo grid with drag-and-drop and world ejection
├── build_menu.py        # Right-side overlay for constructing station modules
├── station_info.py      # Right-side overlay showing building HP and module stats (T key)
│
│  ── Game Logic ──
├── collisions.py        # All collision handlers (projectile/asteroid/alien/player/building)
├── world_setup.py       # Asset loading, asteroid/alien/building spawning, music collection
│
│  ── Sprites ──
├── sprites/
│   ├── player.py        # PlayerShip --- Newtonian ship with faction/ship-type config
│   ├── projectile.py    # Projectile + Weapon (fire cooldown, sound throttle)
│   ├── asteroid.py      # IronAsteroid --- minable rock with shake/tint on hit
│   ├── alien.py         # SmallAlienShip --- PATROL/PURSUE AI with obstacle avoidance
│   ├── pickup.py        # IronPickup --- collectible ore token with fly-to-ship behaviour
│   ├── shield.py        # ShieldSprite --- animated energy bubble with hit flash
│   ├── explosion.py     # Explosion, HitSpark, FireSpark visual effects
│   ├── contrail.py      # ContrailParticle --- engine exhaust particle effect
│   └── building.py      # StationModule, HomeStation, Turret, DockingPort, capacity helpers
│
│  ── Unit Tests ──
├── unit tests/
│   ├── conftest.py      # Shared fixtures (dummy textures)
│   └── test_*.py        # 216 tests across 14 test files
│
├── game-rules.md        # Comprehensive game rules, stats, and asset reference
├── CLAUDE.md            # Project overview and dev reference
├── assets/              # Art, sound, music (gitignored)
├── saves/               # Save slot JSON files (gitignored)
└── venv/                # Python virtual environment (gitignored)
```

## License

TBD
