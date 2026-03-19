# Space Survivalcraft

## Project Overview

**Call of Orion** is a top-down space survival game. Players choose a faction and ship class, then pilot their spaceship through a 6,400×6,400 px star field using Newtonian physics. Core gameplay consists of mining iron asteroids with a Mining Beam, fighting alien scout ships with a Basic Laser, and managing a 5×5 cargo inventory. The game features energy shields, engine contrails, a full save/load system with 10 named slots, background music playlists, gamepad support, and a death/respawn flow.

## Tech Stack

- Python 3.12
- Python Arcade v3.3.3 (game framework, depends on pyglet 2.1.13)
- PIL / Pillow 11.3.0 (sprite sheet cropping, nearest-neighbour upscaling, rotation)
- Virtual Python environment (`venv/` directory, activate with `venv\Scripts\activate.bat` on CMD)
- Dependencies tracked in `requirements.txt`

## Project Setup

- Repository: https://github.com/beknar/Space-Survivalcraft
- `.gitignore` excludes: `.vscode/`, `PROPOSAL.md`, `.markdownlint*`, `venv/`, `__pycache__/`, `*.pyc`, `assets/`, `build/`, `dist/`, `*.spec`, `saves/`, `savegame.json`
- Run with: `python main.py`

## File Structure

```
Space Survivalcraft/
├── CLAUDE.md            # This file — project overview and dev reference
├── game-rules.md        # Comprehensive game rules, features, stats, and asset reference
├── requirements.txt     # pip dependencies (arcade, pillow, pyglet, etc.)
├── .gitignore
│
├── main.py              # Entry point — creates Window, starts SplashView
├── constants.py         # All game constants (window, physics, assets, factions, ship types, respawn)
├── settings.py          # Global runtime settings singleton (volume, resolution, fullscreen) + apply_resolution()
│
│  ── Views (each is an arcade.View subclass) ──
├── splash_view.py       # SplashView — "CALL OF ORION" title, Play/Load/Options/Exit buttons
├── options_view.py      # OptionsView — volume sliders, resolution selector, fullscreen toggle
├── selection_view.py    # SelectionView — two-phase faction then ship-type picker
├── game_view.py         # GameView — core gameplay loop, cameras, input, music, death logic
│
│  ── UI overlays (drawn by GameView, not separate Views) ──
├── hud.py               # HUD — left status panel (HP/shield bars, speed, weapon, asteroid/alien counts, fog-filtered mini-map)
├── escape_menu.py       # EscapeMenu — overlay with save/load/quit, audio sliders (does NOT pause gameplay)
├── death_screen.py      # DeathScreen — "SHIP DESTROYED" overlay with Load/Menu/Exit
├── inventory.py         # Inventory — 5×5 cargo grid with drag-and-drop and world ejection
├── build_menu.py        # BuildMenu — right-side overlay for constructing station modules
├── station_info.py      # StationInfo — right-side overlay showing building HP + module stats (T key)
│
│  ── Game logic ──
├── collisions.py        # All collision handlers (projectile/asteroid/alien/player/building pairs)
├── world_setup.py       # Asset loading helpers + asteroid/alien/building spawning + music collection
│
│  ── Sprite classes ──
├── sprites/
│   ├── __init__.py      # Re-exports all sprite classes
│   ├── player.py        # PlayerShip — Newtonian ship with faction/ship-type config
│   ├── projectile.py    # Projectile + Weapon (fire cooldown, sound throttle)
│   ├── asteroid.py      # IronAsteroid — minable rock with shake/tint on hit
│   ├── alien.py         # SmallAlienShip — PATROL/PURSUE AI with obstacle avoidance
│   ├── pickup.py        # IronPickup — collectible ore token with fly-to-ship behaviour
│   ├── shield.py        # ShieldSprite — animated energy bubble with hit flash
│   ├── explosion.py     # Explosion, HitSpark, FireSpark visual effects
│   ├── contrail.py      # ContrailParticle — engine exhaust particle effect
│   └── building.py      # StationModule, HomeStation, ServiceModule, Turret, RepairModule, DockingPort, etc.
│
│  ── Unit tests ──
├── unit tests/
│   ├── conftest.py        # Shared fixtures (dummy_texture, dummy_texture_list)
│   ├── test_constants.py  # FACTIONS, SHIP_TYPES, physics constants validation
│   ├── test_settings.py   # AudioSettings defaults and mutation
│   ├── test_world_setup.py # _track_name_from_path string parsing
│   ├── test_player.py     # PlayerShip physics (rotation, thrust, damping, clamping)
│   ├── test_projectile.py # Projectile movement + Weapon cooldown
│   ├── test_asteroid.py   # IronAsteroid damage, shake, tint flash
│   ├── test_alien.py      # SmallAlienShip AI states, damage, collision bump
│   ├── test_pickup.py     # IronPickup fly-to-ship, collection, lifetime
│   ├── test_shield.py     # ShieldSprite visibility, hit flash, animation
│   ├── test_explosion.py  # Explosion, HitSpark, FireSpark lifecycle
│   ├── test_contrail.py   # ContrailParticle lifecycle and colour interpolation
│   ├── test_inventory.py  # Grid math, iron management, drag-and-drop, ejection
│   ├── test_damage.py     # Damage routing (shields → HP), death triggering
│   ├── test_building.py   # StationModule, Turret, RepairModule, DockingPort, capacity, snap, collision, port disconnect
│   └── test_respawn.py    # Respawn position logic, timer logic, alien iron drop, fog of war constants/grid
│
├── assets/              # Art, sound, music (gitignored — not in repo)
├── saves/               # Save slot JSON files (gitignored)
├── dist/                # PyInstaller build output (gitignored)
└── venv/                # Python virtual environment (gitignored)
```

## Running Tests

```bash
# Activate virtual environment first
venv\Scripts\activate.bat          # CMD
# or
source venv/Scripts/activate       # Git Bash / WSL

# Run all tests with verbose output
python -m pytest "unit tests/" -v

# Run a specific test file
python -m pytest "unit tests/test_player.py" -v

# Run a specific test class or method
python -m pytest "unit tests/test_player.py::TestThrust" -v
```

Tests use PIL-generated dummy textures to instantiate `arcade.Sprite` subclasses without requiring an `arcade.Window` or display. No game assets are needed. The only test dependency beyond the game's own requirements is `pytest`.

## Architectural Dependencies

### View Flow

```
main.py
  └─▶ SplashView (splash_view.py)
        ├─▶ SelectionView (selection_view.py) ─▶ GameView (game_view.py)
        ├─▶ OptionsView (options_view.py) ─▶ back to SplashView
        └─▶ Load Game ─▶ GameView (game_view.py)

GameView overlays:
  ├── EscapeMenu (escape_menu.py)  — pauses gameplay
  │     ├── Save/Load sub-menus
  │     └── Main Menu ─▶ SplashView
  ├── DeathScreen (death_screen.py) — shown when HP = 0
  │     └── Load/Menu/Exit
  ├── Inventory (inventory.py) — does NOT pause gameplay
  └── BuildMenu (build_menu.py) — does NOT pause gameplay
```

### Module Dependency Graph

```
constants.py ◀── nearly everything (central config)
settings.py  ◀── splash_view, options_view, game_view, death_screen (audio singleton)

game_view.py
  ├── sprites/* (PlayerShip, Weapon, Explosion, HitSpark, FireSpark, IronPickup, ContrailParticle, Building*)
  ├── collisions.py (all collision handlers called from on_update)
  ├── world_setup.py (asset loading, asteroid/alien/building population, music tracks)
  ├── hud.py, escape_menu.py, death_screen.py, inventory.py, build_menu.py, station_info.py (UI overlays)
  └── settings.py (audio volume)

collisions.py
  ├── constants.py (radii, damage values, bounce factors)
  ├── sprites/explosion.py (HitSpark)
  └── sprites/building.py (HomeStation type check for disable cascade)

world_setup.py
  ├── constants.py (asset paths, counts, frame dimensions)
  ├── sprites/asteroid.py, sprites/alien.py, sprites/shield.py, sprites/projectile.py
  └── PIL (sprite sheet cropping)

selection_view.py
  ├── constants.py (factions, ship types, frame size)
  └── PIL (nearest-neighbour preview upscaling)

sprites/player.py
  ├── constants.py (physics defaults, faction/ship data)
  └── PIL (faction sheet cropping + 90° rotation)

sprites/alien.py
  ├── constants.py (AI parameters, collision constants)
  └── sprites/projectile.py (fires Projectile instances)
```

### Key Patterns

- **Pre-built `arcade.Text` objects** everywhere (avoids per-frame `arcade.draw_text()` PerformanceWarning)
- **Module-level caching** for music tracks (`_music_cache` in `world_setup.py`) — loads WAVs once, shuffles copy on each call
- **Spatial hashing** on `asteroid_list` and `alien_list` (`use_spatial_hash=True`) for O(1) collision lookups
- **Sound throttling** on rapid-fire weapons (min 0.15 s between pyglet media player creations)
- **PIL for sprite extraction** — alien ship/laser cropped from composite sheets, faction ships cropped from 1024×1024 grids, shield frames from 3×2 sheet
- **Gamepad resilience** — `joystick.open()` wrapped in `try/except DeviceOpenException` to handle already-open controllers across View transitions

## Game Rules Reference

Full game rules, statistics tables, and asset paths are documented in `game-rules.md`.

## Asset Sources

### 32x32 Sprites

- Spacemonster sprites: https://nulllgames.itch.io/256-spacemonster-sprites
- Spaceship sprites: https://nulllgames.itch.io/256-spaceship-sprites
- Free pixel art: https://jik-a-4.itch.io/freepixel
- Planets/stars/derelicts: https://flavrius.itch.io/free-planetsstarsderelicts-sprites
- Shmup sprites: https://jestan.itch.io/shmupv1
- Pixel planets: https://wyvarth.itch.io/pixel-planets

### Unknown Size Sprites

- Top-down alien spaceship: https://pzuh.itch.io/top-down-alien-spaceship
- Top-down space shooter 1: https://pzuh.itch.io/top-down-space-shooter-1
- Top-down space shooter 2: https://pzuh.itch.io/top-down-space-shooter-2

### Backgrounds & Planets

- Seamless space backgrounds: https://screamingbrainstudios.itch.io/seamless-space-backgrounds
- Planet pack: https://screamingbrainstudios.itch.io/planetpack
- 2D planet pack 2: https://screamingbrainstudios.itch.io/2d-planet-pack-2
- Tiny planet pack: https://screamingbrainstudios.itch.io/tiny-planet-pack
- Seamless sky backgrounds: https://screamingbrainstudios.itch.io/seamless-sky-backgrounds
- Cloudy skyboxes: https://screamingbrainstudios.itch.io/cloudy-skyboxes-pack
- Planet surface skyboxes: https://screamingbrainstudios.itch.io/planet-surface-skyboxes

### Future Development (Planetary Backgrounds)

- Planet texture pack 1: https://screamingbrainstudios.itch.io/planet-texture-pack-1
- Planet surface backgrounds: https://screamingbrainstudios.itch.io/planet-surface-backgrounds
- Planet surface backgrounds 2: https://screamingbrainstudios.itch.io/planet-surface-backgrounds-2

### General Game Assets

- Kenney All-in-1: https://kenney.itch.io/kenney-game-assets

### Music and Sound Effects Licensing

- Bought from Humble Bundle
  - <https://www.humblebundle.com/software/game-audio-collection-1800-music-tracks-65000-sound-effects-software>
- <https://gamedevmarket.net/terms-conditions#pro-licence>
- Sci Fi Fantasy Music
  - <https://gamedevmarket.net/asset/sci-fi-fantasy-music-bundle>
- Sci Fi Sound Effects Bundle
  - <https://gamedevmarket.net/asset/sci-fi-sound-effects-bundle-2>
- Space and Science Fiction Music Pack Vol 1
  - <https://gamedevmarket.net/asset/space-science-fiction-music-pack>
- Space and Science Fiction Music Pack Vol 2
  - <https://gamedevmarket.net/asset/space-science-fiction-music-pack-vol-2>
