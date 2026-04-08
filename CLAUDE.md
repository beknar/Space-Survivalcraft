# Space Survivalcraft

## Project Overview

**Call of Orion** is a top-down space survival game. Players choose a faction and ship class, then pilot their spaceship through a 6,400×6,400 px star field using Newtonian physics. Core gameplay consists of mining iron asteroids with a Mining Beam, fighting alien scout ships with a Basic Laser, and managing a 5×5 cargo inventory. The game features energy shields, engine contrails, a full save/load system with 10 named slots, background music playlists, gamepad support, and a death/respawn flow.

## Tech Stack

- Python 3.12
- Python Arcade v3.3.3 (game framework, depends on pyglet 2.1.13)
- PIL / Pillow 11.3.0 (sprite sheet cropping, nearest-neighbour upscaling, rotation)
- FFmpeg shared DLLs (optional, bundled in project root for video playback; gitignored)
- Virtual Python environment (`venv/` directory, activate with `venv\Scripts\activate.bat` on CMD)
- Dependencies tracked in `requirements.txt`

## Project Setup

- Repository: https://github.com/beknar/Space-Survivalcraft
- `.gitignore` excludes: `.vscode/`, `PROPOSAL.md`, `.markdownlint*`, `venv/`, `__pycache__/`, `*.pyc`, `assets/`, `build/`, `dist/`, `*.spec`, `saves/`, `savegame.json`, `*.dll`
- Run with: `python main.py`

## File Structure

```
Space Survivalcraft/
├── CLAUDE.md            # This file — project overview and dev reference
├── docs/game-rules.md   # Comprehensive game rules, features, stats, and asset reference
├── requirements.txt     # pip dependencies (arcade, pillow, pyglet, etc.)
├── .gitignore
│
├── main.py              # Entry point — creates Window, starts SplashView, patches pyglet clock for video
├── constants.py         # All game constants in 16 named sections (window, physics, assets, factions, aliens, buildings, zone 2, boss, etc.)
├── settings.py          # Global runtime settings singleton (volume, resolution, display mode, video dir) + apply_resolution() + save_config()/load_config()
├── video_player.py      # VideoPlayer — FFmpeg video playback with GPU blit downscale, segment looping, character video support
│
│  ── Character videos ──
├── characters/          # Character video files (Name.mp4), scanned by video_player.scan_characters_dir()
│   └── portraits/       # Character portrait PNGs (Debra1-4.png, Ellie1-4.png, Tara1-4.png) shown in Ship Stats bio panel
│
│  ── Views (each is an arcade.View subclass) ──
├── splash_view.py       # SplashView — "CALL OF ORION" title, Play/Load/Options/Exit buttons
├── options_view.py      # OptionsView — volume sliders, resolution selector, fullscreen toggle, Config save
├── selection_view.py    # SelectionView — two-phase faction then ship-type picker
├── game_view.py         # GameView — thin dispatcher (~820 lines); delegates to extracted modules
├── game_state.py        # GameState dataclasses (BossState, FogState, CombatTimers, AbilityState, EffectState)
├── combat_helpers.py    # Combat, spawning, respawn, XP, boss spawn (extracted from GameView)
├── building_manager.py  # Building placement, destruction, ports, trade station (extracted from GameView)
├── draw_logic.py        # draw_world() and draw_ui() (extracted from GameView.on_draw)
├── update_logic.py      # 11 update sub-functions (extracted from GameView.on_update)
├── input_handlers.py    # All keyboard/mouse event handling (extracted from GameView)
├── game_save.py         # Save/load serialization with reusable serialize/restore helpers
├── game_music.py        # Music/video playback management (extracted from GameView)
│
│  ── UI overlays (drawn by GameView, not separate Views) ──
├── hud.py               # HUD — left status panel (HP/shield bars, character video, weapon); delegates minimap and equalizer
├── hud_minimap.py       # Minimap drawing with fog overlay (extracted from HUD)
├── hud_equalizer.py     # Equalizer visualizer state and drawing (extracted from HUD)
├── base_inventory.py    # BaseInventoryData — shared item storage, drag state, icon resolution, and grid helpers for both inventories
├── escape_menu/         # EscapeMenu package — overlay with save/load/quit, audio sliders, song controls, video/character picker, help
│   ├── __init__.py      # EscapeMenu orchestrator — delegates draw/input to active mode (~157 lines)
│   ├── _context.py      # MenuContext (shared state) + MenuMode base class
│   ├── _ui.py           # Shared drawing helpers (panel, back button, slider, hit tests)
│   ├── _main_mode.py    # Main menu mode — buttons + audio sliders
│   ├── _save_load_mode.py # Save/Load/Naming mode — 10 slots with naming overlay
│   ├── _resolution_mode.py # Resolution selector — windowed/fullscreen/borderless
│   ├── _video_props_mode.py # Video Properties — resolution + character picker
│   ├── _video_mode.py   # Video file picker — directory scanning + playback
│   ├── _config_mode.py  # Config mode — FPS toggle, sliders, video dir
│   ├── _songs_mode.py   # Songs mode — stop/other song, music videos button
│   └── _help_mode.py    # Help mode — keyboard and gamepad controls display
├── death_screen.py      # DeathScreen — "SHIP DESTROYED" overlay with Load/Menu/Exit
├── inventory.py         # Inventory — 5×5 cargo grid with drag-and-drop, consolidate, module/blueprint icons
├── station_inventory.py # StationInventory — 10×10 Home Station inventory with item transfer, consolidate, tooltips
├── craft_menu.py        # CraftMenu — crafting UI for Basic Crafter (Repair Pack + module recipes, cancel support)
├── ship_stats.py        # ShipStats — ship statistics overlay (C key) showing faction, stats, module modifications, character level/benefits + character bio panel with random portrait and backstory
├── trade_menu.py        # TradeMenu — trading station overlay (sell items for credits, buy consumables)
├── build_menu.py        # BuildMenu — right-side overlay for constructing station modules
├── station_info.py      # StationInfo — right-side overlay showing building HP + module stats + world stats (T key)
│
│  ── Character system ──
├── character_data.py    # Character progression: XP/level tables, per-character bonuses (Debra/Ellie/Tara)
│
│  ── Game logic ──
├── collisions.py        # All collision handlers + _apply_kill_rewards helper (explosion, iron, blueprint, XP)
├── ui_helpers.py        # Shared UI drawing: draw_button, draw_load_slot, standard button/slot colours
├── world_setup.py       # Asset loading helpers + asteroid/alien/building spawning + music collection
│
│  ── Sprite classes ──
├── sprites/
│   ├── __init__.py      # Re-exports all sprite classes
│   ├── player.py        # PlayerShip — Newtonian ship with faction/ship-type config, apply_modules, sideslip
│   ├── projectile.py    # Projectile + Weapon (fire cooldown, sound throttle)
│   ├── asteroid.py      # IronAsteroid — minable rock with shake/tint on hit
│   ├── alien.py         # SmallAlienShip — PATROL/PURSUE AI with obstacle avoidance
│   ├── boss.py          # BossAlienShip — 3-phase boss with main cannon, spread shot, charge attack; targets station
│   ├── pickup.py        # IronPickup + BlueprintPickup — collectible tokens with fly-to-ship behaviour
│   ├── shield.py        # ShieldSprite — animated energy bubble with hit flash
│   ├── explosion.py     # Explosion, HitSpark, FireSpark visual effects
│   ├── contrail.py      # ContrailParticle — engine exhaust particle effect
│   ├── building.py      # StationModule, HomeStation, ServiceModule, Turret, RepairModule, BasicCrafter, DockingPort, etc.
│   ├── copper_asteroid.py # CopperAsteroid — minable copper ore
│   ├── wandering_asteroid.py # WanderingAsteroid — magnetic wanderer attracted to player
│   ├── gas_area.py      # GasArea — toxic gaseous hazard with procedural texture
│   ├── zone2_aliens.py  # Zone 2 aliens: ShieldedAlien, FastAlien, GunnerAlien, RammerAlien
│   ├── missile.py       # HomingMissile — homing projectile with turn rate
│   ├── force_wall.py    # ForceWall — temporary shimmering barrier
│   └── wormhole.py      # Wormhole — rotating blue cloud with red spirals
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
│   ├── test_blueprint_pickup.py # BlueprintPickup spinning, module_type, collection
│   ├── test_modules.py    # MODULE_TYPES constants, apply_modules, sideslip, consolidate, stack limits
│   ├── test_video_player.py # scan_characters_dir, character_video_path
│   ├── test_shield.py     # ShieldSprite visibility, hit flash, animation
│   ├── test_explosion.py  # Explosion, HitSpark, FireSpark lifecycle
│   ├── test_contrail.py   # ContrailParticle lifecycle and colour interpolation
│   ├── test_inventory.py  # Grid math, iron management, drag-and-drop, ejection
│   ├── test_damage.py     # Damage routing (shields → HP), death triggering
│   ├── test_building.py   # StationModule, Turret, RepairModule, DockingPort, capacity, snap, collision, port disconnect
│   └── test_respawn.py    # Respawn position logic, timer logic, alien iron drop, fog of war constants/grid
│
│  ── Zones ──
├── zones/
│   ├── __init__.py      # ZoneID enum, ZoneState base class, create_zone() factory
│   ├── zone1_main.py    # MainZone — wraps existing 6400x6400 Double Star gameplay
│   ├── zone_warp_base.py # WarpZoneBase — shared warp zone logic (red walls, exits)
│   ├── zone_warp_meteor.py # MeteorWarpZone — fast meteors from top
│   ├── zone_warp_lightning.py # LightningWarpZone — periodic lightning volleys
│   ├── zone_warp_gas.py # GasCloudWarpZone — maze of damaging gas clouds
│   ├── zone_warp_enemy.py # EnemySpawnerWarpZone — 4 spawner stations
│   ├── zone2.py         # Zone 2 (Nebula) — coordinator (setup/teardown/update/draw)
│   └── zone2_world.py   # Zone 2 entity population, collision handling, respawn (extracted from zone2.py)
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
  ├── EscapeMenu (escape_menu/)  — pauses gameplay
  │     ├── Save/Load sub-menus
  │     ├── Video Properties (resolution + character picker)
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

game_view.py (thin dispatcher)
  ├── combat_helpers.py (damage, death, spawning, respawn, XP, boss)
  ├── building_manager.py (placement, destruction, ports, trade station)
  ├── draw_logic.py (world + UI rendering)
  ├── update_logic.py (11 update phases)
  ├── input_handlers.py (keyboard + mouse events)
  ├── game_save.py (save/load with zone-aware serialization), game_music.py (music/video)
  ├── game_state.py (state dataclasses — BossState, FogState, CombatTimers, AbilityState, EffectState)
  ├── sprites/* (PlayerShip, Weapon, Explosion, HitSpark, FireSpark, IronPickup, ContrailParticle, Building*, BossAlienShip)
  ├── collisions.py (all collision handlers called from update_logic)
  ├── world_setup.py (asset loading, asteroid/alien/building population, music tracks)
  ├── hud.py → hud_minimap.py, hud_equalizer.py (UI overlays)
  ├── inventory.py, station_inventory.py → base_inventory.py (shared item logic)
  └── escape_menu/, death_screen.py, build_menu.py, craft_menu.py, trade_menu.py, station_info.py

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

- **Shared UI helpers** — `ui_helpers.py` provides `draw_button()` and `draw_load_slot()` with standard colour constants; used by splash_view, death_screen, and options_view to eliminate duplicated button/slot drawing code
- **Kill reward centralisation** — `collisions._apply_kill_rewards()` handles explosion + iron drop + character bonus + blueprint chance + XP for all kill types (asteroid, alien-by-player, alien-by-turret)
- **Constants organisation** — `constants.py` grouped into 16 named sections with `═══` dividers and a docstring table of contents for discoverability
- **Pre-built `arcade.Text` objects** everywhere (avoids per-frame `arcade.draw_text()` PerformanceWarning)
- **Module-level caching** for music tracks (`_music_cache` in `world_setup.py`) — loads WAVs once, shuffles copy on each call
- **Spatial hashing** on `asteroid_list` and `alien_list` (`use_spatial_hash=True`) for O(1) collision lookups
- **Sound throttling** on rapid-fire weapons (min 0.15 s between pyglet media player creations)
- **PIL for sprite extraction** — alien ship/laser cropped from composite sheets, faction ships cropped from 1024×1024 grids, shield frames from 3×2 sheet
- **Gamepad resilience** — `joystick.open()` wrapped in `try/except DeviceOpenException` to handle already-open controllers across View transitions
- **Dynamic UI positioning** — all views and overlays use `self.window.width`/`.height` (or `arcade.get_window()`) for layout, never stale imported `SCREEN_WIDTH`/`SCREEN_HEIGHT` constants, to support runtime resolution changes and fullscreen
- **Fog of war** — 128×128 boolean grid saved/loaded with game state; mini-map filters objects by revealed cells and draws grey fog overlay using run-length spans
- **Unified item storage** — both cargo (5×5) and station (10×10) inventories store items as `(type, count)` tuples per cell; iron is a regular stackable item, not a separate pool; `total_iron` property sums across all cells for HUD/build cost checks
- **Quick-use drag system** — HUD tracks drag state (`_qu_drag_src/type/count/x/y`) for visible pick-up animation; items can be assigned by dragging from inventory, moved between slots, or unassigned by dragging out
- **Building hover tooltip** — `on_mouse_motion` detects closest building within 40 px using world-coordinate conversion; tooltip drawn in UI camera space
- **Character video player** — looping 1:1 square character portrait in HUD; uses GPU-side `glBlitFramebuffer` downscale (1440→200px, ~90KB readback vs 8MB); frame conversion throttled to 15fps; seamless loop via pre-built standby player loaded 5s before end-of-file; `draw_in_hud` accepts `aspect` param (1.0 for character, 16/9 for music videos)
- **Ship module system** — 6 module types (armor, engine, shield, regen, absorb, broadside) with blueprint drops, crafting, drag-to-equip, stat application via `apply_modules`; broadside auto-fires perpendicular lasers; shield enhancer draws rotating ring; blueprints color-tinted per type
- **Escape menu package** — refactored from 1918-line monolith into `escape_menu/` package; `MenuContext` + `MenuMode` base class pattern; each sub-mode in its own file; orchestrator delegates all draw/input to active mode
- **Inventory count cache** — both inventories cache `arcade.Text` objects per count value to avoid `.text` churn (0.375ms per call); station inv draws grid as single background + lines instead of 100 individual cells
- **Ranged alien standoff AI** — gun-equipped aliens (Zone 1 scouts, Zone 2 shielded/fast/gunner) orbit at `ALIEN_STANDOFF_DIST` (300 px) instead of charging; each alien picks a random orbit direction (CW/CCW); approach if too far, back off if too close, strafe laterally at range; always face the player; RammerAlien still charges directly (has_guns=False); FastAlien flips orbit direction on dodge timer for unpredictable strafing
- **Wandering asteroid bounce** — collision with player applies push-apart (60% player, 40% wanderer), velocity reflection with `SHIP_BOUNCE` restitution, and kicks the wanderer's wander direction away from the player for 1.5 s before resuming random wander
- **Viewport culling** — Zone 2 only draws/updates sprites within camera bounds + 250 px margin; offscreen wandering asteroids spin-only (cheap); gas areas get wider margin (+200 px) due to large size
- **Gas area minimap markers** — green filled circles with outline rings, sized proportionally to world radius using `map_scale = minimap_width / zone_width`
- **Character progression** — 3 characters (Debra/Ellie/Tara) with 5-level XP trees; bonuses applied via pure functions in `character_data.py`; weapon stats reloaded on level-up
- **Faction shield tints** — shield color varies by faction (red/green/brown/purple) via `tint` param on ShieldSprite
- **Trading station** — spawns on first Repair Module; sell/buy with credits; saved/loaded with game state; shown on minimap as yellow square
- **GC management** — automatic GC disabled; runs once when ESC menu opens to avoid gameplay stalls
- **Two-frame video pipeline** — GPU blit and readback split across frames; per-frame conversion lock prevents double conversion; fog minimap uses 4x4 block sampling
- **Respawn texture caching** — asteroid/alien textures loaded once at init, reused for all respawns
- **XP hard cap** — XP capped at 1,000 (max level); `_add_xp` short-circuits when cap reached
- **Character bio panel** — Ship Stats overlay (C key) shows a second panel with a random portrait from `characters/portraits/` and backstory text; portrait chosen fresh each time the panel opens
- **GameView extraction pattern** — all extracted modules (combat_helpers, building_manager, draw_logic, update_logic, input_handlers) use free functions receiving `gv: GameView` with `TYPE_CHECKING` to avoid circular imports; GameView keeps thin one-liner delegates so external callers (collisions.py, game_save.py) continue to work via `gv._method()`
- **BaseInventoryData mixin** — shared item storage (add/remove/count/consolidate/toggle), drag state (`_init_drag_state`/`_start_drag`/`_finish_drag`/`_clear_drag`), icon resolution (`_resolve_icon`/`_draw_count_badge`), and window helpers inherited by both Inventory and StationInventory; subclasses set `_rows`/`_cols` for grid dimensions
- **Boss encounter** — spawns when player reaches level 5, all 4 modules equipped, 5+ repair packs, and Home Station built; BossAlienShip has 2000 HP + 500 shields, 3-phase AI (main cannon + spread → adds charge attack → enraged with halved cooldowns); spawns at farthest world corner from station and heads toward it; full save/load support; HP bar with phase indicator; large dramatic announcement on spawn; red minimap marker
- **Multi-zone system** — ZoneState base class with zone-specific setup/teardown/update/draw; MainZone stashes zone 1 state during warp zone visits; player world bounds parameterized for different zone sizes
- **Warp zones** — 4 transition zones (meteor, lightning, gas, enemy spawner) with shared WarpZoneBase handling red walls, exits, and safe returns
- **Zone 2 (Nebula)** — second biome with copper asteroids, double iron, gas hazards, wandering magnetic asteroids, and 4 new alien types (shielded, fast, gunner, rammer); population and collision logic extracted into `zones/zone2_world.py`
- **Cross-zone save/load** — Zone 1 state saved from MainZone stash when player is in another zone; Zone 2 state (asteroids, aliens, fog, wanderers) fully serialized; both zones restore correctly on load regardless of which zone was active
- **game_save.py serialization helpers** — reusable `_serialize_asteroid`, `_serialize_alien`, `_serialize_z2_alien`, `_serialize_boss`, `_serialize_wormhole` functions eliminate repeated serialization patterns; matching `_restore_*` functions for deserialization
- **GameState dataclasses** — `game_state.py` defines `BossState`, `FogState`, `CombatTimers`, `AbilityState`, `EffectState` for incremental adoption; GameView attributes unchanged to avoid cascading changes in extracted modules
- **10-level character progression** — XP thresholds 0-7000; Debra gets copper bonuses at L6+, Ellie gets advanced laser upgrades, Tara gets copper cost reductions
- **Special ability meter** — 100 max, 5/s regen; powers Misty Step (teleport), Force Wall (barrier), Death Blossom (missile barrage)
- **Homing missiles** — consumable quick-use item; 50 dmg, 400 px/s, 180 deg/s turn rate, 1500px range

## Game Rules Reference

Full game rules, statistics tables, and asset paths are documented in `docs/game-rules.md`.

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
