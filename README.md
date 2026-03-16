# Space Survivalcraft

A space-themed survival crafting game built with Python and the Arcade framework. Pilot a spaceship, mine asteroids for resources, fight alien enemies, manage your cargo, and survive in a vast open world.

## Features

### Faction & Ship Selection
- Choose from 4 factions: **Earth**, **Colonial**, **Heavy World**, and **Ascended**
- Select from 5 ship types, each with unique stats:
  - **Cruiser** — balanced all-rounder
  - **Bastion** — high HP, heavy armour
  - **Aegis** — strong shields with fast regeneration
  - **Striker** — high thrust, agile fighter
  - **Thunderbolt** — dual-gun weapons platform
- Ship previews and stat breakdowns shown on the selection screen

### Newtonian Flight Model
- Realistic thrust-based movement with inertia and space drag
- Per-ship physics: thrust, braking, rotation speed, max speed, and damping
- Coloured engine contrail particles unique to each ship type
- Seamless thruster engine sound loop while accelerating or braking
- Keyboard and Xbox 360 gamepad support

### Combat
- **Basic Laser** — high-damage weapon for fighting enemies (25 dmg, 0.30 s cooldown)
- **Mining Beam** — rapid-fire tool for harvesting asteroids (10 dmg, 0.10 s cooldown)
- Dual-gun ships (Thunderbolt) fire from two laterally-offset hardpoints simultaneously
- Weapon cycling with Tab key or gamepad right bumper
- Camera shake and hit sparks on weapon impacts
- Shield system absorbs damage before HP; regenerates over time
- Animated energy shield bubble with hit-flash visual feedback

### Enemies — Small Alien Ships
- 20 alien scout ships patrol the world with autonomous AI
- Two AI states: **Patrol** (lazy loops near spawn) and **Pursue** (chase and fire on detection)
- Aliens fire laser bolts faster than the player's max speed — dodging required
- Obstacle-avoidance steering around asteroids and other aliens
- Physics-based collision bouncing between all entities
- Leash range prevents aliens from chasing indefinitely

### Mining & Resources
- 50 iron asteroids scattered across the world, each with 100 HP
- Only the Mining Beam can damage asteroids; Basic Laser has no effect
- Asteroids spin, shake on hit, and explode with animated effects when destroyed
- Destroyed asteroids drop iron ore pickups that fly toward the player when nearby

### Inventory System
- 5x5 cargo hold grid toggled with I key or gamepad Y button
- Drag-and-drop items between inventory slots
- Drop items into the game world by dragging outside the inventory panel
- Hover tooltips show item names and quantities
- Iron ore count displayed in both the inventory and HUD

### HUD & Mini-Map
- Left-side status panel showing HP bar, shield bar, speed, heading, iron count, and active weapon
- Faction and ship type indicators
- Controls reference and gamepad connection status
- FPS counter (toggle with F key)
- Mini-map showing the full 6400x6400 world: player (white), asteroids (gray), aliens (red), iron pickups (orange)

### Escape Menu
- Press ESC to open a pause menu that freezes all gameplay
- **Resume** — return to the game
- **Save Game** — save full game state to a JSON file
- **Load Game** — restore a previously saved game
- **Main Menu** — return to faction/ship selection
- **Exit Game** — quit the application
- Single save slot with complete world state preservation

### World
- 6400x6400 pixel open world (200x200 tiles) with tiled starfield background
- Camera follows the player, clamped at world edges
- Ship-to-asteroid and ship-to-alien collision with bounce physics and damage

## Controls

| Action | Keyboard | Xbox 360 Gamepad |
|---|---|---|
| Rotate left/right | Left/Right or A/D | Left stick |
| Thrust forward | Up or W | Left stick up |
| Brake/reverse | Down or S | Left stick down |
| Fire weapon | Space | A button (hold for auto-fire) |
| Cycle weapon | Tab | Right bumper (RB) |
| Open inventory | I | Y button |
| Escape menu | Escape | — |
| Toggle FPS | F | — |

## Requirements

- Python 3.12
- Python Arcade 3.3.3

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

## Project Structure

```
Space Survivalcraft/
├── main.py              # Entry point
├── constants.py         # All game constants
├── selection_view.py    # Faction & ship selection screen
├── game_view.py         # Core gameplay loop
├── hud.py               # HUD and status panel
├── collisions.py        # Collision handling
├── world_setup.py       # Asset loading and world population
├── escape_menu.py       # Pause menu overlay
├── inventory.py         # Cargo hold UI
├── sprites/             # Game object classes
│   ├── player.py        # Player ship
│   ├── asteroid.py      # Iron asteroids
│   ├── alien.py         # Alien scout AI
│   ├── projectile.py    # Projectiles & weapons
│   ├── explosion.py     # Explosion & hit effects
│   ├── shield.py        # Shield bubble
│   ├── pickup.py        # Iron ore pickup
│   └── contrail.py      # Engine exhaust particles
└── assets/              # Art, sound, music (not included in repo)
```

## License

TBD
