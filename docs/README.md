# Call of Orion --- Documentation

Welcome to the full documentation for **Call of Orion**, a top-down space survival game. Use the links below to find detailed information about every aspect of the game.

## Contents

- [Features](features.md) --- Complete list of all gameplay features and systems
- [Statistics](statistics.md) --- All game stats: ship types, weapons, enemies, boss, buildings, items
- [Controls](controls.md) --- Keyboard and gamepad controls reference
- [Rules & Mechanics](rules.md) --- Collision rules, damage flow, AI behaviour, building placement, respawn logic
- [Lore & Characters](lore.md) --- Factions, character backstories, progression, and the Double-Star War
- [Architecture](architecture.md) --- Codebase structure, module extraction pattern, and dependency graph
- [Game Rules Reference](game-rules.md) --- Comprehensive game rules document with asset paths and technical details

# Asset Sources

## Sprites

### 32x32 Sprites

- Spacemonster sprites: https://nulllgames.itch.io/256-spacemonster-sprites
- Spaceship sprites: https://nulllgames.itch.io/256-spaceship-sprites
- Free pixel art: https://jik-a-4.itch.io/freepixel
- Planets/stars/derelicts: https://flavrius.itch.io/free-planetsstarsderelicts-sprites
- Shmup sprites: https://jestan.itch.io/shmupv1
- Pixel planets: https://wyvarth.itch.io/pixel-planets

### Unknown Size Sprites (top-down ships)

- Top-down alien spaceship: https://pzuh.itch.io/top-down-alien-spaceship
- Top-down space shooter 1: https://pzuh.itch.io/top-down-space-shooter-1
- Top-down space shooter 2: https://pzuh.itch.io/top-down-space-shooter-2
- Top-down sci-fi dungeon tileset (maru-98): https://maru-98.itch.io/top-down-sci-fi-dungeon-tileset-2d-pixel-art-game-assets

## Backgrounds & Planets

### Currently Used

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

## General & Weapons

### General Game Assets

- Kenney All-in-1: https://kenney.itch.io/kenney-game-assets

### Weapons / Effects

- Light saber game assets (melee weapon sprites): https://willisthehy.itch.io/light-saber-game-assets

## Music & Sound Effects Licensing

- Bought from Humble Bundle
  - https://www.humblebundle.com/software/game-audio-collection-1800-music-tracks-65000-sound-effects-software
- https://gamedevmarket.net/terms-conditions#pro-licence
- Sci Fi Fantasy Music
  - https://gamedevmarket.net/asset/sci-fi-fantasy-music-bundle
- Sci Fi Sound Effects Bundle
  - https://gamedevmarket.net/asset/sci-fi-sound-effects-bundle-2
- Space and Science Fiction Music Pack Vol 1
  - https://gamedevmarket.net/asset/space-science-fiction-music-pack
- Space and Science Fiction Music Pack Vol 2
  - https://gamedevmarket.net/asset/space-science-fiction-music-pack-vol-2

# Game Systems

## Zone 2 (The Nebula)

Zone 2 is the second biome, accessed through warp zones that appear when the Double Star boss is defeated. It features copper asteroids, toxic gas clouds, wandering magnetic asteroids, and 4 new alien types. Ranged aliens orbit the player at ~300 px standoff distance instead of charging, while the Rammer alien still charges directly. Wandering asteroids bounce off the player on contact with full knockback physics. Gas areas are shown on the minimap as proportionally-sized green octagonal outlines. In warp zones, gas hazards are always visible on the minimap regardless of fog of war. See [Features](features.md) and [Statistics](statistics.md) for full details.

## Zone 3 (The Star Maze)

Zone 3 is a 12000×12000 third biome reached via post-Nebula-boss warp zones. It contains `STAR_MAZE_COUNT` (4) dungeon-wall **maze structures** laid out at the corners + centre via `STAR_MAZE_CENTERS`. Each maze is a **5×5 room grid** (300 px interior, 32 px walls) carved with recursive-backtracking DFS in `zones/maze_geometry.generate_maze`. Every room hosts one **MazeSpawner** (100 HP + 100 shields, 1000 iron + 100 XP on kill, 90 s respawn) which periodically spits out a **MazeAlien** (50 HP, 30 XP, A*-pathfinds through the room graph instead of bee-lining). Outside the maze rectangles the zone hosts the same Nebula content as Zone 2 (asteroids, gas, wanderers, Z2 aliens, null fields, slipspaces) populated via `zones/nebula_shared.populate_nebula_content` with radius-aware reject filters. Misty Step rejects teleports whose path crosses a wall. Star Maze has its own corner wormholes that chain on to deeper `MAZE_WARP_*` warp variants.

## Nebula Boss + Quantum Wave Integrator

The **Quantum Wave Integrator** (QWI) is a Zone-2 building (1000 iron + 2000 copper) that triggers the **Nebula boss** on construction. Clicking the QWI within `QWI_PLACE_RADIUS` (300 px) opens `qwi_menu.QWIMenu`, which charges 100 iron per resummon. The Nebula boss has **gas-cloud** projectiles (30 dmg + 1.5 s slow on hit) and a 400 px **cone attack** (20 dmg per 0.5 s tick while inside). Reward: 3000 iron + 1000 copper, no XP. Station turrets, missile arrays, and AI-piloted parked ships all target + damage the Nebula boss, which routes around force walls.

## Null Fields & Slipspaces

**Null fields** are 30 stealth patches per non-warp zone (`NULL_FIELD_COUNT`) that hide the player from enemies — while inside, AI targeting treats the player as invisible. Firing any weapon from inside a field disables the field for `NULL_FIELD_DISABLE_S` (10 s) and flashes it red. Star Maze + Zone 2 enemies (including maze enemies) all honour the cloak.

**Slipspaces** are 15 paired teleporter portals per non-warp zone that conserve velocity. Display 160 px / collision 60 px. Persisted in save/load and shown on the minimap.

## Multi-Ship System

Upgrading a ship via "Advanced Ship" in the build menu now places the new ship in the world (placement mode with ghost ship texture) rather than swapping textures in-place. The old ship persists as a `ParkedShip` sprite with its own HP, shields, cargo inventory, and module slots. Players click a parked ship within range to switch control --- inventory, modules, weapons, and ability meter all swap. Parked ships take damage from any source (aliens, boss, player weapons) and drop cargo as pickups on destruction. They appear on the minimap as teal dots and are stashed/restored during zone transitions.

# Engineering

## Cross-Zone Save/Load

All three main zones are saved and restored independently. When saving from any zone, Zone 1 (Double Star), Zone 2 (Nebula), and Zone 3 (Star Maze) state is fully serialized --- including asteroids, aliens, fog of war, buildings, wanderers, parked ships, null fields, slipspaces, and maze-spawner state (HP, shields, kill flag, respawn timer, alive-children count). Zone 1 data is pulled from the MainZone stash when the player is in another zone. Zone 2 buildings (and the trade station + parked ships) are stashed in `Zone2._building_stash` so they survive round trips through warp zones. Zone 2 entity population and collision handling live in `zones/zone2_world.py`; both Zone 2 and Star Maze share `zones/nebula_shared.py` for the Nebula content + collisions. Star Maze geometry (rooms, walls, room graph, A* helper) lives in `zones/maze_geometry.py`; Star Maze persists its own world seed so the maze layout regenerates deterministically on load (the spawner positions are re-derived from the seed rather than restored from save data).

## Background Zone Simulation

An optional "Simulate All Zones" toggle (in Config menus) enables background ticking of inactive zones while the player is in a different zone. When enabled:

- Respawn timers advance and replenish asteroids/aliens in zones the player is away from
- Aliens patrol (no player interaction --- they revert to PATROL state and wander toward waypoints)
- Asteroids rotate, wanderers drift
- No sounds, visual effects, or player collision --- purely simulation

The Station Info panel (T key) shows an "Other Zones" panel with live entity counts from every inactive main zone (Double Star, Nebula, Star Maze), excluding warp zones.

## Architecture Notes

The codebase follows an extraction pattern where GameView delegates to free-function modules. Recent refactors introduced:

- **`ui_helpers.py`** --- shared `draw_button()` and `draw_load_slot()` with standard colour constants; eliminates duplicated button/slot drawing across splash, death, and options views
- **`collisions._apply_kill_rewards()`** --- centralised explosion + iron drop + character bonus + blueprint chance + XP for all kill types (asteroid, alien-by-player, alien-by-turret)
- **`constants.py`** --- reorganised into 16 clearly labelled sections with `═══` dividers and a docstring table of contents
- **`game_state.py`** --- state dataclasses (`BossState`, `FogState`, `CombatTimers`, `AbilityState`, `EffectState`) for future incremental adoption
- **`game_save.py`** --- reusable serialization/deserialization helpers (`_serialize_asteroid`, `_restore_z1_aliens`, etc.) replacing repeated patterns
- **`zones/zone2_world.py`** --- Zone 2 entity population and collision handling extracted from `zone2.py`
- **`zones/nebula_shared.py`** --- shared Nebula content / collision / fog / gas / wanderer / asteroid handlers used by both `Zone2` and `StarMazeZone`. Extracted to stop drift between the two zones (every Zone 2 fix used to require a manual port to the Star Maze's copy).
- **`zones/maze_geometry.py`** --- Star Maze `MazeLayout` NamedTuple, recursive-backtracking maze generation, room-adjacency graph, A* room pathing, point-in-rect / segment-vs-walls helpers
- **`base_inventory.py`** --- shared drag state, icon resolution, grid helpers, a dirty-flag render cache (`_render_dirty` + `_build_render_cache`) that batches cell fills and item icons into two `SpriteList`s rebuilt only when items change, and a badge texture cache (`_get_badge_texture` renders each unique count via PIL `ImageDraw`, cached in `_badge_tex_cache`) that batches all count badges into `_cache_badge_list` SpriteList. Used by both cargo and station inventories.
- **`collisions.resolve_overlap` / `collisions.reflect_velocity`** --- two pure-math primitives extracted from six near-duplicate collision handlers. `resolve_overlap` returns the contact normal (or `None`) after pushing two bodies apart; `reflect_velocity` reflects one body's velocity along that normal with restitution. Eliminates ~150 lines of bounce/push duplication across `collisions.py` and `zones/zone2.py`.
- **`game_save._restore_sprite_list`** --- generic clear-then-append helper used by Zone 1 asteroid restore and all four Zone 2 entity lists (iron, double iron, copper, wanderers). Factory closures may return `None` to skip a malformed entry.
- **`hud.HUD._draw_stat_bar`** --- shared bar renderer for HP / shield / ability bars; replaces three near-identical 12-line drawing blocks. Numerical label uses the existing cached `arcade.Text` skip-on-unchanged optimization.
- **`input_handlers._eject_to_*` helpers** --- the long `_handle_inventory_eject` routine is now a 4-line dispatch table calling `_eject_to_module_slot`, `_eject_to_quick_use`, `_eject_to_station_inv`, or `_eject_iron_to_world` based on what's under the cursor.
- **`game_view.GameView` sectioned `__init__`** --- the 380-line constructor was split into 13 named init helpers (player/camera, abilities, text overlays, input devices, weapons/audio, world entities, boss, consumable textures, inventories, buildings/overlays, world state, HUD/audio/video, zones). The constructor body itself is now a 13-line list of phase calls; behaviour is identical.

## Performance Notes

Several large optimizations target the Nebula zone, which can populate hundreds of asteroids and dozens of aliens:

- **Spatial hash on static lists only** --- alien sprite lists deliberately do NOT use `use_spatial_hash=True`. With ~50 moving aliens, the per-frame O(N) hash rebuild costs more than it saves. Asteroid and building lists are static and continue to use spatial hashing.
- **Inventory render cache** --- both inventories build cached `SpriteList`s of cell fills and icons; rebuild is gated by a `_render_dirty` flag set on every mutation. Grid lines are batched into a single `arcade.draw_lines()` call. Count badges rendered as PIL text into `arcade.Texture` sprites batched into `_cache_badge_list` SpriteList (one `SpriteList.draw()` replaces 100 per-frame `arcade.Text.draw()` calls). Station inventory went from 26.7 FPS to 50.9 FPS with both inventories open.
- **Minimap dot batching** --- `hud_minimap` collects per-colour point lists and draws each colour group with one `arcade.draw_points()` call instead of per-sprite `draw_circle_filled`. Gas areas drawn as octagonal outlines via batched `arcade.draw_lines()`. Fog visibility checks inlined to avoid per-entity function call overhead. Fog texture rebuilds throttled (every 8 cells).
- **Turret target caching** --- turrets cache their nearest target and rescan only 4x/second, eliminating per-frame O(turrets x aliens) scans.
- **Distance-based alien AI culling** --- Zone 2 aliens far from the viewport get cheap position-only updates instead of full AI with obstacle avoidance.
- **Direct Zone 2 sprite-list draws** --- `Zone2.draw_world` calls `SpriteList.draw()` on each entity list directly; the previous per-frame visibility-list rebuild has been removed (the dead `_draw_visible` helper and `_vis_draw` SpriteList have been deleted). Static VBOs upload once.

# Development & Testing

## Tooling

- **Ruff** --- `ruff.toml` configures bug-focused lint rules (F401, F811, F821, F823, F841, E9, B006/B008/B015/B018/B023). Initial pass cleaned 156 unused imports and 5 dead variables across 12 files, and caught 2 real bugs (missing imports in `station_inventory.py`).
- **pytest.ini** --- excludes `integration/` from default test runs (`norecursedirs`).

## Test Coverage

The fast test suite (`unit tests/`, 906 tests) runs in ~5.5 s and covers:

- **Player physics** (`test_player.py`) — rotation, thrust, damping, clamping
- **Weapons + projectiles** (`test_projectile.py`)
- **Asteroids / aliens / pickups / blueprints / shields** — entity behaviour
- **Inventory** (`test_inventory.py`) — grid math, drag-and-drop, ejection, **render-cache dirty flag invalidation** for every mutator
- **Modules** (`test_modules.py`) — `apply_modules`, sideslip, consolidate, stack limits
- **Damage routing** (`test_damage.py`) — shields → HP → death
- **Buildings** (`test_building.py`) — modules, turret, repair, docking ports
- **Respawn + fog of war** (`test_respawn.py`)
- **Collision physics primitives** (`test_collision_helpers.py`) — `resolve_overlap` (4 detection + 3 push variants) and `reflect_velocity` (5 reflection cases) plus a full ship-vs-asteroid round trip
- **Save restore helper** (`test_save_helpers.py`) — `_restore_sprite_list` clear/append/skip-None contract
- **Zone-aware Station Info** (`test_world_stats.py`) — Zone 1 and Zone 2 stat lines, including a regression lock for the "0 iron / 0 roids" Nebula bug
- **Zone 2 update loop** (`test_zone2_update.py`) — 7 tests covering update branches including the `UnboundLocalError` regression (missing module-level import in `zone2.py`)
- **CPU microbenchmarks** (`test_perf_micro.py`) — 8 tests for collision, inventory, fog, alien AI, minimap, and save serialization (all windowless, ~0.11 s)
- **Parked ships** (`test_parked_ship.py`) — construction by level, HP/shield damage routing, hit flash, cargo/module storage, collision handler (alien/player/boss projectiles), destruction drops, serialization round trip
- **Star Maze** (`test_star_maze.py`) — maze generation determinism, room overlap, recursive-backtracking DFS, A* room pathing (incl. Z-shape), MazeAlien/MazeSpawner stat pinning, geometry collision helpers, save/load round trip (incl. position-NOT-restored contract)
- **Nebula boss + QWI** (`test_qwi_and_nebula_boss.py`, `test_session_boss_tweaks.py`) — boss spawn, gas/cone attacks, drop logic, QWI menu summon flow
- **Null fields + slipspaces** (`test_null_field.py`, `test_null_field_persistence.py`, `test_slipspace.py`, `test_slipspace_minimap.py`) — cloak toggle, weapon-fire disable + 10 s timer, save/restore, minimap markers, paired teleport + velocity conservation
- **Force wall + gas area** (`test_force_wall.py`, `test_gas_area.py`) — endpoint geometry, lifetime, closest_point clamping, segment_crosses; gas drift/bouncing/contains_point
- **Nebula shared helpers** (`test_nebula_shared.py`) — `rebuild_shielded_list`, `update_fog`, `update_gas_damage` cooldown, `update_alien_laser_hits`, `update_player_asteroid_collision`, `update_wanderer_collision`
- **Ship manager** (`test_ship_manager.py`, `test_basic_ship_build.py`) — `_deduct_ship_cost`, `_resize_module_slots`, `_upgrade_ship` guards + success path, `_place_basic_ship` / `_place_new_ship`, `count_l1_ships`
- **Respawn on death** (`test_respawn_on_death.py`) — `_drop_player_loadout` (cargo / modules / quick-use), `_send_bosses_home`, `_reset_alien_aggro` across active + stashed alien lists, `_resolve_respawn_target` (last-visited / any-zone fallback / disabled-station skip), boss `_patrol_home` toggle, full `trigger_player_death` orchestration
- **Dialogue overlay** (`test_dialogue_overlay.py`) — open/close, SPACE/ENTER advance, digit-key picks, ESC closes, aftermath commit on terminal nodes, broken-tree cleanup
- **Settings, video scanning, world setup helpers**

The integration suite (`unit tests/integration/`, ~309 tests) requires an Arcade window and covers:

- **Functional** (`test_zone2_real_gv.py`, `test_star_maze_real_gv.py`) — Zone 2 and Star Maze exercised with a real GameView, including Death Blossom flow with both videos running and Star Maze maze-spawner combat
- **Full-frame FPS** (`test_performance.py`) — 40 FPS-threshold tests across Zone 1 + Zone 2 (full population, buildings, boss, heavy combat, minimap), warp zones, station info with and without music, inventories, parked ships, Missile Array, real music + character video, and the **trade sell / buy panels in both zones with and without both videos playing plus a buy↔sell churn scenario**
- **GPU rendering** (`test_render_perf.py`) — microbenchmarks isolating Text.draw, SpriteList.draw, draw_points, draw_lines, draw_rect_filled vs SpriteList, fog texture rebuild
- **Resolution scaling** (`test_resolution_perf.py`) — 12 tests across all 6 RESOLUTION_PRESETS × 2 zones (Zone 1 + Zone 2); uses `apply_resolution` to resize a hidden window between tests; cannot run in parallel (one Arcade window per process)
- **Soak/endurance** (`test_soak.py`) — 5-minute soak tests measuring FPS + RSS every 30 s: Zone 1 combat, Zone 2 combat, **Star Maze idle / combat churn / Nebula pressure**, video player, inventory churn, fog texture rebuild, combined worst-case. Player made invulnerable to prevent premature death. Requires `psutil` dev dependency.

Grand total: ~1215 tests (906 fast + ~309 integration). Real music-video tests load `.mp4` files from `./yvideos` (gitignored) relative to the project root. Shared soak scaffolding lives in `unit tests/integration/_soak_base.py`; refactor-pass helpers are exercised by `unit tests/test_refactor_helpers.py`.

Tests use PIL-generated dummy textures so no game assets are required. Fast tests need no Arcade window. `pytest` and `psutil` (for soak tests) are needed beyond the game's regular dependencies.

See [Architecture](architecture.md) for the full dependency graph.
