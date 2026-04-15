# Call of Orion

A top-down space survival game built with Python and the Arcade framework. Pilot a customisable spaceship through a vast star field, mine asteroids for iron, fight alien scout ships, build a modular space station, and manage your cargo inventory.

## Highlights

- **4 factions** and **5 ship types** with unique stats and contrail colours
- **3 playable characters** (Debra, Ellie, Tara) with 10-level progression trees
- **Newtonian flight model** with thrust, inertia, sideslip, and gamepad support
- **Combat** with Basic Laser, Mining Beam, and ship module weapons (broadside lasers)
- **Boss encounter** --- 3-phase AI boss with 2,000 HP, spread shots, and charge attacks
- **4 warp zones** --- meteor, lightning, gas cloud, and enemy spawner transition zones
- **Zone 2 (Nebula)** --- second biome with copper, gas hazards, magnetic asteroids, and 4 new alien types
- **Cross-zone persistence** --- all zones saved and restored independently; fog of war, asteroids, aliens, and buildings persist across zone transitions and save/load; Zone 2 buildings survive round trips through warp zones
- **Background zone simulation** --- optional "Simulate All Zones" setting ticks inactive zones (respawns, alien patrol, asteroid rotation) while the player is elsewhere
- **Inactive zone info panel** --- Station Info (T key) shows live entity counts from zones the player is not in
- **Homing missiles** --- consumable weapon with homing AI, craftable at Advanced Crafter
- **Advanced modules** --- Misty Step teleport, Force Wall barrier (blocks enemy lasers, boss projectiles, AND enemy movement with route-around AI), Death Blossom missile barrage
- **Special ability meter** --- powers advanced module abilities
- **30 alien scouts** with patrol/pursue/orbit AI and obstacle avoidance
- **75 minable asteroids** that drop iron and copper ore for crafting
- **Modular space station** with 8+ building types, turrets, missile arrays, repair module, and crafters; long-press LMB on turrets/missile arrays to drag-move them within the home-station radius
- **Multi-ship system** --- upgrade ships via build menu placement; old ship persists in the world with its own HP, cargo, and modules; click a parked ship to switch control; hover a parked ship for an HP tooltip; ships take damage from any source and drop cargo on destruction
- **12 ship modules** crafted from blueprint drops (armor, engine, shield, absorber, broadside, and advanced modules)
- **5x5 cargo inventory** and **10x10 station inventory** with drag-and-drop
- **Trading station** for buying and selling items with credits; scrollable sell panel, fixed buy catalog, and hold-to-sell for rapid unloading
- **10 named save slots** preserving full game state including fog of war and boss
- **Fog of war**, minimap, HUD with character video, music video, and equalizer visualizer; music-video title anchored to the top of the video so it stays visible at every resolution
- **Performance-optimized rendering** --- batched minimap draws (`arcade.draw_points` + `arcade.draw_lines` for gas octagon outlines), inlined fog visibility checks, throttled fog texture rebuilds, turret target caching (4x/s rescan), distance-based alien AI culling, inventory render cache with dirty-flag invalidation, PIL-rendered badge texture cache, spatial hashing on static sprite lists only, batched trade-panel `SpriteList` fills with pooled per-row `arcade.Text` objects, cached alien textures shared across GameView rebuilds, and streaming WAV loading for background music loops

## Documentation

Full game documentation is in the [docs/](docs/README.md) directory:

- [Features](docs/features.md) --- all gameplay systems
- [Statistics](docs/statistics.md) --- ship, weapon, enemy, boss, and building stats
- [Controls](docs/controls.md) --- keyboard and gamepad reference
- [Rules & Mechanics](docs/rules.md) --- collision, damage, AI, and placement rules
- [Lore & Characters](docs/lore.md) --- factions, backstories, and character progression
- [Game Rules Reference](docs/game-rules.md) --- comprehensive rules with asset paths and technical details

The [ROADMAP](ROADMAP.md) tracks shipped features in chronological order alongside the open Future Features list.

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
# Fast suite (440 tests, ~1.5s)
python -m pytest "unit tests/" -v

# Integration tests (110 tests — requires an Arcade window)
python -m pytest "unit tests/integration/" -v

# Soak/endurance tests only (~30 min, 5 min each)
python -m pytest "unit tests/integration/test_soak.py" -v
```

440 fast unit tests covering player physics, weapons, asteroids, aliens, pickups, blueprints, shields, explosions, contrails, inventory (including render-cache dirty flag and badge texture cache), damage routing, buildings, ship modules, respawn, fog of war, video scanning, settings, collision physics primitives (`resolve_overlap` / `reflect_velocity`), save-restore helpers, zone-aware Station Info world stats, Zone 2 update loop branches, and CPU microbenchmarks. 110 integration tests cover full-frame FPS thresholds (incl. the trade sell/buy panel in both zones with both videos running and a buy↔sell churn test), GPU rendering microbenchmarks, resolution scaling across all 6 presets, and 5-minute soak/endurance tests measuring FPS and RSS stability. 550 tests total. Linted with [ruff](https://docs.astral.sh/ruff/) (`ruff.toml` — bug-focused rules).

## Project Structure

```
Space Survivalcraft/
├── main.py              # Entry point
├── constants.py         # All game constants (16 named sections)
├── settings.py          # Audio settings singleton
├── ui_helpers.py        # Shared UI drawing (buttons, save slots)
│
│  ── Core gameplay (GameView + extracted modules) ──
├── game_view.py         # GameView thin dispatcher (~820 lines)
├── game_state.py        # State dataclasses (BossState, FogState, CombatTimers, etc.)
├── combat_helpers.py    # Damage, spawning, respawn, XP, boss spawn
├── building_manager.py  # Building placement, destruction, ports
├── ship_manager.py      # Ship upgrade, placement, switching (extracted)
├── draw_logic.py        # World and UI rendering
├── update_logic.py      # 11 update sub-functions
├── input_handlers.py    # Keyboard and mouse event handling
├── game_save.py         # Save/load with zone-aware serialization helpers
├── game_music.py        # Music and video playback management
├── collisions.py        # Collision handlers + centralised kill rewards
├── world_setup.py       # Asset loading and world population
│
│  ── Views ──
├── splash_view.py       # Title screen
├── selection_view.py    # Faction/ship/character picker
├── options_view.py      # Volume and resolution settings
│
│  ── UI overlays ──
├── hud.py               # HUD status panel
├── hud_minimap.py       # Minimap with fog overlay
├── hud_equalizer.py     # Equalizer visualizer
├── base_inventory.py    # Shared inventory data, drag state, and icon helpers
├── inventory.py         # 5x5 cargo grid
├── station_inventory.py # 10x10 station grid
├── escape_menu/         # Escape menu package (10 sub-modes)
├── ship_stats.py        # Ship stats + character bio overlay
├── build_menu.py        # Station building overlay
├── craft_menu.py        # Crafting UI
├── trade_menu.py        # Trading station overlay
├── station_info.py      # Station info overlay (T key)
├── death_screen.py      # Death screen overlay
├── character_data.py    # Character XP/level/bonuses
├── video_player.py      # FFmpeg video playback
│
│  ── Sprites ──
├── sprites/
│   ├── player.py        # PlayerShip
│   ├── projectile.py    # Projectile + Weapon
│   ├── asteroid.py      # IronAsteroid
│   ├── alien.py         # SmallAlienShip (4 AI sub-methods)
│   ├── boss.py          # BossAlienShip (3 AI sub-methods)
│   ├── pickup.py        # IronPickup + BlueprintPickup
│   ├── shield.py        # ShieldSprite
│   ├── explosion.py     # Explosion, HitSpark, FireSpark
│   ├── contrail.py      # ContrailParticle
│   ├── building.py      # Station modules
│   ├── copper_asteroid.py # CopperAsteroid
│   ├── wandering_asteroid.py # WanderingAsteroid
│   ├── gas_area.py      # GasArea
│   ├── zone2_aliens.py  # ShieldedAlien, FastAlien, GunnerAlien, RammerAlien
│   ├── missile.py       # HomingMissile
│   ├── force_wall.py    # ForceWall
│   ├── wormhole.py      # Wormhole
│   └── parked_ship.py   # ParkedShip (multi-ship system)
├── zones/               # Zone state machine (9 zone files incl. zone2_world.py)
├── unit tests/          # 440 fast tests across 22 files + 110 integration tests (550 total)
├── docs/                # Full game documentation
├── characters/          # Character videos and portraits
├── docs/game-rules.md   # Comprehensive rules reference
└── CLAUDE.md            # Dev reference
```

## Future Features

- **New space biomes** --- visually distinct sectors with unique asteroid types, backgrounds, and resources
- **Hazardous zones** --- radiation clouds, electrical discharge, EMP areas, maze barriers
- **Characters** --- branching storylines, character-specific abilities, ship skins
- **Planetary landing** --- land on planets with different surface biomes
- **Planetary vehicles** --- ground-based exploration
- **Warp gates** --- travel to new star systems
- **Advanced resources** --- new materials for mid/advanced crafting
- **Ship level advancement** --- upgrade ships through experience
- **New space monsters** --- varied creatures with unique behaviours
- **Enemy ships** --- hostile NPCs that manoeuvre like the player

## License

This project is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

Game assets (art, sound, music) are licensed separately from their respective creators — see the Asset Sources section in [CLAUDE.md](CLAUDE.md) for details.
