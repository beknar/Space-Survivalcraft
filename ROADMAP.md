# Call of Orion — Roadmap

Inventory of shipped features and the future-work items called out in the
README. Checked items are live on `main`; unchecked items are open.

## Shipped features

### Core flight & combat
- [x] 4 factions × 5 ship types (unique stats and contrail colours)
- [x] Newtonian flight model (thrust, inertia, sideslip)
- [x] Gamepad support
- [x] Basic Laser, Mining Beam, broadside laser modules
- [x] Energy shields with hit flash + shield sprite animation
- [x] Engine contrail particles
- [x] Death/respawn flow

### Enemies & AI
- [x] 30 Zone 1 alien scouts with patrol / pursue / orbit-at-standoff AI
- [x] Ranged alien standoff at `ALIEN_STANDOFF_DIST` (300 px)
- [x] Per-alien obstacle avoidance (asteroids + other aliens)
- [x] Force-wall avoidance + hard-block segment-cross routing for aliens
- [x] 4 Zone 2 alien types — Shielded, Fast, Gunner, Rammer
- [x] 3-phase boss encounter (2000 HP + 500 shields, main cannon, spread,
      charge attack, enraged cooldowns)

### Player progression
- [x] 3 playable characters (Debra, Ellie, Tara) with 10-level XP trees
- [x] Per-character gameplay bonuses (build cost, craft cost, copper, etc.)
- [x] XP hard cap at 1000 (max level 10)
- [x] Character portrait + bio panel in Ship Stats overlay

### World & zones
- [x] 6400×6400 Zone 1 star field
- [x] Zone 2 (Nebula) — copper asteroids, gas hazards, wandering magnetic
      asteroids, double-iron rocks, 4 alien types
- [x] 4 warp zones — Meteor, Lightning, Gas Cloud, Enemy Spawner
- [x] Wormhole transitions between zones
- [x] Cross-zone persistence (fog, asteroids, aliens, buildings, parked
      ships all survive zone transitions)
- [x] Background zone simulation (optional setting)
- [x] Inactive zone info panel on Station Info overlay

### Station building
- [x] Modular station with 8+ building types
- [x] Docking port auto-connection with N/E/S/W orientation
- [x] Turrets (2 tiers) with target caching + range checks
- [x] Repair Module that heals ships and buildings in range
- [x] Basic Crafter and Advanced Crafter
- [x] Missile Array that auto-fires homing missiles
- [x] Fission Generator / Shield Generator / Solar Arrays / Service Modules
- [x] Home Station as station root (destroying it disables all modules)
- [x] Trading station with sell + buy panels
- [x] Scrollable sell panel with scrollbar thumb
- [x] Long-press LMB to move turrets / missile arrays (clamped to
      `TURRET_FREE_PLACE_RADIUS` from the Home Station)

### Inventory & crafting
- [x] 5×5 cargo grid with drag-and-drop
- [x] 10×10 station inventory with item transfer + tooltips
- [x] Iron + copper ore stacking
- [x] Quick-use bar with drag-to-assign, drag-to-reassign, drag-to-unassign
- [x] Module equipment slots with drag install/eject
- [x] Blueprint drops from aliens and rare asteroid smashes
- [x] Crafting recipes — Repair Pack, Shield Recharge, Homing Missile,
      all module blueprints
- [x] Advanced Crafter unlocks advanced modules (incl. Homing Missile
      production)

### Ship modules & abilities
- [x] 12 module types — armor, engine, shield, regen, absorber, broadside,
      misty step, force wall, death blossom, homing missile, etc.
- [x] Ship Module system with stat application via `apply_modules`
- [x] Special ability meter (100 max, 5/s regen)
- [x] Misty Step teleport (WASD double-tap)
- [x] Force Wall barrier (2× length, blocks enemy lasers, boss projectiles,
      and enemy movement)
- [x] Death Blossom missile barrage
- [x] Shield Enhancer rotating ring
- [x] Broadside auto-fires perpendicular lasers
- [x] Homing Missile consumable with turn-rate AI

### Multi-ship system
- [x] Upgrade ships via build-menu placement (Advanced Ship)
- [x] Old ship persists as `ParkedShip` with its own HP, shields, cargo,
      modules
- [x] Click a parked ship within 300 px to switch control
- [x] Parked ships take damage from all sources and drop cargo + module
      blueprints on destruction
- [x] Parked ships stashed across zone transitions
- [x] Parked-ship HP hover tooltip

### UI, HUD, and overlays
- [x] Left status panel with HP / shield / ability bars
- [x] Character video portrait (GPU-blit downscale)
- [x] Music video player
- [x] Now Playing track title anchored above the music video at every
      resolution
- [x] Single-line "WEAPON: <name>" label
- [x] Fog of war (128×128 grid, persisted)
- [x] Minimap with fog overlay + batched `draw_points` for 200+ entities
- [x] Gas-area octagonal outlines on the minimap (including warp zones)
- [x] Parked ship teal dots on the minimap
- [x] Equalizer visualizer
- [x] Escape menu package (10 sub-modes — save/load, audio, songs,
      resolution, video, config, help)
- [x] Build menu, Craft menu, Trade menu, Station Info, Ship Stats
- [x] Station Info "Other Zones" panel for inactive zones
- [x] Death screen with Load / Menu / Exit
- [x] Hover tooltips on buildings and parked ships
- [x] Dynamic UI positioning for all resolutions and fullscreen

### Save / load
- [x] 10 named save slots
- [x] Zone-aware save of Zone 1 + Zone 2 state independently
- [x] Fog of war, boss state, parked ships, trade-station credits all
      persisted
- [x] Splash-screen Load Game panel

### Performance & tooling
- [x] Inventory render cache with dirty-flag invalidation
- [x] PIL-rendered count-badge texture cache
- [x] Minimap batched dot + line draws
- [x] Turret target caching (0.25 s rescan)
- [x] Distance-based alien AI culling in Zone 2
- [x] Spatial hashing on static sprite lists only
- [x] Zone 2 viewport culling (+250 px margin)
- [x] Trade-panel filled-rect batching through a pooled SpriteList
- [x] Pooled per-row `arcade.Text` objects in the trade panel
- [x] Alien-texture caching (no Ship.png / Effects.png re-decode per load)
- [x] Streaming WAV loading for background music loops
- [x] Tracked-player sound cleanup (pyglet Player leak fix)
- [x] Periodic `gc.collect()` during sound cleanup and menu open
- [x] 440 fast unit tests (< 2 s) + 63 integration tests (FPS, GPU, soak)
- [x] Ruff linter with bug-focused ruleset

## Future features (from README)

- [x] **Ship level advancement** — upgrade ships through experience
      (shipped via `Advanced Ship` build + parked-ship swap)
- [x] **Enemy ships** — hostile NPCs that manoeuvre like the player
      (patrol + standoff orbit + obstacle avoidance + Zone 2 variants)
- [ ] **New space biomes** — visually distinct sectors with unique asteroid
      types, backgrounds, and resources _(Zone 2 Nebula + 4 warp zones
      shipped; more biomes still open)_
- [ ] **Hazardous zones** — radiation clouds, electrical discharge, EMP
      areas, maze barriers _(lightning + gas + meteor warp zones shipped;
      radiation / EMP / maze still open)_
- [ ] **Advanced resources** — new materials for mid/advanced crafting
      _(copper added; more tiers still open)_
- [ ] **New space monsters** — varied creatures with unique behaviours
      _(Zone 2 aliens + wandering asteroids shipped; more creatures open)_
- [ ] **Characters** — branching storylines, character-specific abilities,
      ship skins _(10-level trees + bonuses shipped; storylines and skins
      still open)_
- [ ] **Warp gates** — travel to new star systems _(intra-system wormholes
      shipped; cross-system gates still open)_
- [ ] **Planetary landing** — land on planets with different surface biomes
- [ ] **Planetary vehicles** — ground-based exploration

## Near-term / unlisted work on `main`

These aren't called out in the README but have landed recently and are
worth tracking in one place.

- [x] Force wall 2× length + enemy-movement blocking + enemy routing
- [x] Turret / missile array long-press move with 300 px clamp
- [x] Parked-ship hover HP tooltip
- [x] Trade sell panel scrollbar + dynamic height cap
- [x] "NOW PLAYING" + track title anchored above music video at any
      resolution
- [x] `WEAPON: <name>` single-line HUD label
- [x] Cached `arcade.Text` for parked-ship tooltip (PerformanceWarning fix)
- [x] Trade panel perf tests (sell + buy × Zone 1 + Zone 2, with and
      without videos, with buy↔sell toggling)
- [x] Music-video perf tests load `./yvideos` relative to the repo
