# Call of Orion — Roadmap

Inventory of shipped features (in chronological order) and the
future-work items called out in the README. Checked items are live on
`main`; unchecked items are open. Dates come from `git log` against the
feature's merging commit.

## Shipped features (chronological)

### 2026-03-13 — Initial playable prototype
- [x] Repository + project setup + README (`e525f28` → `886f33c`)
- [x] Main play screen with player ship and controls (`6e826a3`)
- [x] Xbox 360 gamepad support via XInput (`303eeae`)
- [x] Thruster exhaust animation keyed to thrust state (`7248fd8`, `1eae655`)
- [x] Thrust tuning — wing turrets decoupled from thrust, ship row 0
      only (`6284924`, `c904d67`, `2f21cc6`, `e7a4e51`)

### 2026-03-15 — Core combat & inventory
- [x] Weapons, projectiles, and cargo inventory (`172af27`)
- [x] 5×5 cargo grid (`453a02c`)
- [x] Iron asteroids with mining, explosion FX, ship-asteroid bounce
      physics (`8ca3b79`, `f313e17`)
- [x] F-key FPS toggle (`9458c79`)
- [x] Iron pickups with fly-to-ship, bump sound, camera shake, world
      ejection (`905d7bf` → `4059d68`)
- [x] Inventory drag-and-drop, tooltips, minimap first draft (`853da4d`,
      `440c0cb`)
- [x] Inventory world-ejection edge cases + pre-built `arcade.Text`
      objects (`138e878`, `3523e31`)
- [x] 20 small alien ships with patrol/pursue AI (`f2d7de6`, `202a5a1`)
- [x] Ship shields with regen, shield-first damage, animated shield
      bubble (`5c30eb7`, `0d800c6`, `36a7d32`)
- [x] Mining beam passes through aliens; alien collision + avoidance
      (`082a24c`, `7c2e009`)
- [x] Monolithic main.py split into focused modules (`816f662`)
- [x] Faction + ship-type selection screen (`e70905c`)
- [x] Dual-gun firing, thruster sound, engine contrails, selection SFX
      (`93fbda5`, `3aafbaa`)
- [x] Escape menu with save/load, main-menu return, exit (`61795e3`)
- [x] 10 named save slots (`4a4bdb3`)
- [x] Inventory hint + perf pass + joystick DeviceOpenException fix
      (`fe63cdd`, `2393d03`)
- [x] Sharper ship preview upscaling (nearest-neighbour) (`bc36f53`)
- [x] Shuffled background music playlist (`5f7857f`)

### 2026-03-16 — Splash, options, and audio polish
- [x] 128×128 ship sprites + HP/shield numeric values (`75d23c3`,
      `600c0ce`)
- [x] Music track name in HUD (`793faa2`)
- [x] Splash screen, options screen, global audio settings (`17b4668`)
- [x] Fire sparks, player death flow, save-slot details (`ed2da90`)
- [x] Exit Game button on splash + options (`a4ef960`)
- [x] First unit-test suite (174 tests) (`04b13ca`)
- [x] Window title "Call of Orion" + 50 death quotes (`9614499`)

### 2026-03-17 — Space station building system
- [x] 7 station module types + ghost placement (`2cdcdcd`, `3d433a9`)
- [x] Escape-menu audio sliders, edge-to-edge building snap,
      player-building collision, station info panel (`39e0de7`)
- [x] Asteroid/alien respawning + alien iron drops (`0de553f`)
- [x] Repair Module, destroy mode, two-way port connectivity (`1525790`)

### 2026-03-18 — Resolution, fog, and repair polish
- [x] Building iron drops, placement overlap check, HUD counters
      (`c8f0d59`)
- [x] Fog of war, 2-min respawn, escape menu no longer pauses (`72ef1a2`)
- [x] 800 px fog reveal + grey fog on minimap (`3ff4a5b`)
- [x] Camera offset, repair enhancements, resolution options (`115fba6`)
- [x] Text objects replace `draw_text` in resolution UI (`749b2c2`)
- [x] Viewport scaling, fullscreen toggle, borderless windowed
      (`307b0d0` → `3804974`)

### 2026-03-19 — Video player + UI centering fixes
- [x] Save naming + save/load panel centering at all resolutions
      (`bade2ac`, `d0dd34c`)
- [x] Fog of war restored on load from splash (`ecd83d8`)
- [x] FFmpeg-based video player, WMF fallback explorations, aspect/
      orientation fixes, frame caching, clock patch (`5a5fa9e` through
      `7445fad`)
- [x] Block player input while escape menu is open (`7ad9854`)
- [x] HUD equalizer visualizer with cascading colours (`8c3b49f`,
      `891699a`)

### 2026-03-20 — Songs, Config menu, video performance
- [x] Song controls, weapon aggro range, 4K optimization pass
      (`eca52e4`)
- [x] Scrollbar on video file list, fullscreen video requirement
      (`ab86946`, `45a8baf`)
- [x] Help button with controls list (`8e3ddc5`)
- [x] Persistent `config.json`, Config menu, autoplay OST setting
      (`09bf5b9`)
- [x] Respawn effects, video player memory leak fix, aggro = 4× diameter
      (`f196363`, `eafc00a`, `07d6a6b`)
- [x] Video VRAM leak fix (reuse single texture) + perf diagnostics
      (`18997eb`, `3b930bb`)

### 2026-03-21 — Inventory unification + station inventory
- [x] Video frame de-dup, time-based detection, PIL buffer reuse
      (`2d63ca5`, `5560226`)
- [x] ESC menu reorg: Video Properties / Songs / Help (`230e9b7`)
- [x] Full Config panel (volume sliders, video dir, autoplay) (`a914674`)
- [x] Station inventory, Basic Crafter, Repair Pack, quick-use bar
      (`fb5e51a`)
- [x] Connectable-module placement rules (`7f6aa7c` → `d501a08`)
- [x] Two-way ship↔station inventory transfer with drag-and-drop
      (`1371307` → `96d3eae`)

### 2026-03-22 to 2026-03-29 — Character videos, modules, character trees
- [x] Quick-use bar no longer occludes equalizer (`6cf940e`)
- [x] Character video player in HUD + Video Properties menu + world
      stats moved to T menu (`1d80ac3`)
- [x] Escape menu split into a package (`1936dcc`)
- [x] Character video switched to 1:1 square aspect (`3038db3`)
- [x] Ship module system + sideslip + 44 new tests (`a8acee0`)
- [x] GameView refactor: extract save/load + music/video (`69b0c2d`)
- [x] Future Features section added to README (`08f94f8`)

### 2026-03-31 — Character progression + trading station
- [x] Character progression (Debra/Ellie/Tara), trading station, faction
      shield tints, perf optimizations (`e1ffdd4`)
- [x] XP cap at 1000, character bio panel with portraits/backstories
      (`99c51ae`)

### 2026-04-01 to 2026-04-02 — Boss, docs, zones, wormholes
- [x] Boss encounter: 3-phase AI, dramatic spawn, HP bar (`819b3e7`)
- [x] Documentation moved to `docs/`, README shrunk (`c0ed1b5`)
- [x] Music video + character video documentation (`b13bd9b`)
- [x] GameView refactor: 2175 → 621 lines + HUD/inventory/view/sprite
      decomposition (`c76c234`, `77ee72d`)
- [x] Shield Recharge consumable, wormholes on boss kill (`fa3001d`)
- [x] Apache 2.0 license + asset sources documentation (`44a715b`)
- [x] Multi-zone system with 4 warp zones + Zone 2 stub (`2f41c6c`)
- [x] Zone 2 (Nebula) biome with new resources, enemies, advanced
      modules (`62b98c8`)
- [x] 10-level character progression + ability meter HUD (`04a35d9`)

### 2026-04-04 to 2026-04-06 — Zone 2 polish + persistence
- [x] Zone entry pulsing-text announcements (`cc89b64`)
- [x] Zone shown in save slots, gas visibility, Zone 2 asteroid movement
      fix (`edfe6e4`)
- [x] Gas cloud shape, Zone 2 fog of war, gas on minimap (`8b24022`)
- [x] Zone 2 perf: cache minimap, reduce object counts (`73f7938`)
- [x] Pickup collection unified across all zones (`b9be8e5`)
- [x] Fog of war restored from Zone 2 save (`8fcde3f`)
- [x] Deterministic Zone 2 world seed (`47dea0b`)
- [x] Save/restore Zone 2 aliens + green gas markers on minimap
      (`83bd142`)
- [x] Zone 2 persistence across visits, lightning optimization
      (`9b949a3`)
- [x] Cross-zone save: all zones' state saved, safe wormhole placement
      (`46c1601`)
- [x] `game_state.py` dataclasses refactor (`b3b2ce3`)
- [x] Nebula fog-overlay cache + hot-path allocation removal (`019f828`)
- [x] Zone 2 viewport culling on draw/update (`c84f567`)
- [x] Wandering asteroid movement with viewport-culled updates
      (`e7c08e6`)

### 2026-04-07 — Ranged AI, refactors, Zone 2 buildings
- [x] Ranged alien orbit AI, wanderer bounce, gas minimap markers
      (`88cd69f`)
- [x] Shared UI helpers, centralised kill rewards, constants reorg
      (`64c1484`)
- [x] Buildings supported in Zone 2, trade station visibility, module
      auto-rotation (`e221de8`)
- [x] Solar Array wide-module centring + physical port direction
      snap/auto-connect (`bff6884` → `ba679dd`)
- [x] Craft menu fixes for Advanced Crafter, copper costs, long recipe
      wrapping (`0f0fb03` → `4f2d632`)

### 2026-04-08 to 2026-04-12 — Major perf + multi-ship
- [x] Deduplicate save slots, config sliders, HUD tooltips (`d9d9bb2`)
- [x] Sound-player FPS leak fix + perf optimizations + 436-test suite
      (`ca2a5d3`)
- [x] HUD decomposition + `MenuOverlay` base + test dedup (`5bfc7ff`)
- [x] Zone 2 FPS perf: buildings 35 → 61 FPS, minimap 34 → 55 FPS
      (`9ed4fab`)
- [x] Simulate All Zones option, Zone 2 building loss fix, warp gas on
      minimap (`071d88e`)
- [x] Splash load respects saved ship level (`04f63f8`)
- [x] Inactive zone info panel (`f1191af`)
- [x] Station Info perf/soak tests + stat-update throttling (`eb7176f`)
- [x] Warp zone + full-scenario perf/soak tests + collision optimizations
      (`e929bda`)
- [x] **Multi-ship system — persistent ship placement, switching, combat
      damage, cargo drops** (`b008e60`)
- [x] Aliens take damage from asteroids + route around them (`a501d5c`)

### 2026-04-13 — Missile Array, homing missiles, trade panel, Force Wall
- [x] New-game crash + video picker UX fixes (`013f055`, merged PR #1)
- [x] Gas hazards respect fog in warp zones (`45c8fa9`)
- [x] Advanced Ship build flow + spread enemy/asteroid drops (`79f82f3`)
- [x] `PlayerShip.upgrade_ship()` + BuildMenu ship-level kwarg (PR #3)
- [x] Ship level cap at 2, homing missiles gated to Advanced Crafter
      (`99f0aaf`)
- [x] Legacy `mod_homing_missile` → `missile` migration (`614b30a`)
- [x] 3 soak-test failures fixed (inventory sprite pool + thresholds,
      PR #4) (`454a3fe`)
- [x] Crafter panel title, missile desc, misty step range, parked-ship
      modules (`98779dd`)
- [x] Missile Array auto-fires + missile kills drop loot + modules flash
      on cooldown (`87a2d4b`)
- [x] Sell iron at trade station for credits (`cb3df15`)
- [x] Death Blossom polish, copper price, trade iron buy (`3cb58a3`)
- [x] Dynamic trade sell panel, copper sort, iron/copper 20 cr
      (`e0d15d7`)
- [x] Tests + video-enabled variants for recent features (`cd8ef49`,
      `9990a91`)
- [x] Force Wall 2× length + 2 s cooldown, hold-to-sell, ability help
      (`24a332a`)
- [x] Warp memory threshold 1000 → 1200 MB (PR #5) (`67be386`)

### 2026-04-14 — Recent polish & performance
- [x] Refactor: extract `ship_manager`, dedupe trade/craft/world-click
      dispatch (`672b2a6`)
- [x] `test_inventory` window-size pollution fix (PR #6) (`0f277df`)
- [x] **Force wall now blocks enemy lasers + boss projectiles; long-press
      LMB moves turrets; parked-ship HP tooltip; trade scrollbar +
      overlap fix; music video title above video; "WEAPON:" single
      line** (`9ffe748`)
- [x] Force walls hard-block enemy movement + routing; trade panel perf
      fix; more HUD polish (`575001e`)
- [x] Trade panel perf tests with character + music video playing
      (`727490a`)
- [x] Stream music loops to avoid WAV `MemoryError` on startup
      (`a1c9a51`)
- [x] Batch trade panel filled rects into a SpriteList (`d9545ee`)
- [x] Stop re-decoding Ship.png and Effects.png each GameView build
      (`4045960`)
- [x] Resolve music videos from `./yvideos` instead of `G:\yvideos`
      (`1defa57`)
- [x] Add `ROADMAP.md` tracking shipped vs future features (`03722aa`)

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

## Changelog

One line per shipped commit, newest first. Generated from `git log`.

### 2026-04-14
- `03722aa` Add ROADMAP.md tracking shipped vs future features
- `1defa57` Resolve music videos from ./yvideos instead of G:\yvideos
- `4045960` Stop re-decoding Ship.png and Effects.png each GameView build
- `d9545ee` Batch trade panel filled rects into a SpriteList
- `a1c9a51` Stream music loops to avoid WAV MemoryError on startup
- `727490a` Add trade panel perf tests with character + music video playing
- `575001e` Force walls block enemy routing, trade panel perf fix, HUD polish
- `9ffe748` Force wall blocks enemy fire, long-press to move turrets, UI polish
- `3837ff6` Merge PR #6: Fix test_inventory window-size pollution
- `0f277df` Fix test_inventory window-size pollution from integration tests
- `672b2a6` Refactor: extract ship_manager, dedupe trade/craft/world-click dispatch

### 2026-04-13
- `6c8629e` Merge PR #5: Raise warp mem threshold 1000 -> 1200 MB
- `67be386` Raise warp mem threshold 1000 -> 1200 MB
- `24a332a` Force Wall 2x length + 2s cooldown, hold-to-sell, ability help
- `9990a91` Add video-enabled variants for recent feature tests
- `cd8ef49` Add tests for recent feature work
- `e0d15d7` Dynamic trade sell panel, copper sort, iron/copper 20 cr
- `3cb58a3` Death Blossom polish, copper price, trade iron buy
- `cb3df15` Sell iron at trade station for credits
- `87a2d4b` Missile Array auto-fires, missile kills drop loot, modules flash on CD
- `98779dd` Fix crafter panel title, missile desc, misty step range, parked-ship modules
- `0bd6417` Merge PR #4: Fix 3 soak-test failures
- `454a3fe` Fix 3 soak-test failures: pool inventory sprites + adjust thresholds
- `614b30a` Migrate legacy mod_homing_missile items to missile
- `99f0aaf` Cap ship level at 2, gate homing missiles to Advanced Crafter
- `8c572eb` Merge PR #3: Add PlayerShip.upgrade_ship() and BuildMenu ship_level kwarg
- `8523ed2` Add PlayerShip.upgrade_ship() and BuildMenu ship_level kwarg
- `79f82f3` Fix Advanced Ship build flow and spread enemy/asteroid drops
- `f2e02fa` Add character video files
- `f47e691` Merge PR #2: Ignore .venv/ directory
- `1dde5fe` Ignore .venv/ directory
- `ce1bf98` Merge PR #1: Fix new-game crashes and video picker UX
- `45c8fa9` Gas hazards respect fog of war in warp zones
- `013f055` Fix new-game crashes and video picker UX

### 2026-04-12
- `a501d5c` Aliens take damage from asteroids, route around them; update yields
- `b008e60` Add multi-ship system: persistent ship placement, switching, and combat
- `e929bda` Add warp zone + full scenario perf/soak tests, optimize collisions
- `eb7176f` Add Station Info perf/soak tests, throttle stat updates
- `f1191af` Add inactive zone info panel, update all docs with recent changes
- `04f63f8` Fix splash screen load showing level 1 ship instead of saved level
- `071d88e` Add Simulate All Zones option, fix Zone 2 building loss, show warp gas on minimap
- `9ed4fab` Perf: fix Zone 2 FPS drops (35→61 buildings, 34→55 minimap)
- `5bfc7ff` Refactor: HUD decomposition, MenuOverlay base, test dedup, fix fill color
- `ca2a5d3` Fix sound player FPS leak, perf optimizations, refactors, 436-test suite

### 2026-04-08
- `67ce94b` Update docs with draw_tooltip and expanded ui_helpers usage
- `d9d9bb2` Refactor: deduplicate save slots, config sliders, and HUD tooltips

### 2026-04-07
- `4f2d632` Fix FPS drops, add Zone 2 buildings to build menu, support copper costs
- `730f980` Wrap long recipe text to two lines, use variable row heights
- `54a187e` Show advanced crafter build cost, fix recipe list occluded by CRAFT button
- `0f0fb03` Fix craft menu showing 0 iron for advanced crafter, add copper costs
- `ba679dd` Fix ghost sprite snap preview to use physical port direction and auto-rotation
- `848e71d` Fix post-placement auto-connect to require opposing physical directions
- `0e08f95` Use physical port direction for snap placement and auto-rotation
- `bff6884` Centre wide modules (Solar Arrays) on N/S ports instead of edge-to-edge
- `fe17e3b` Fix missing create_building import in _restore_z2_buildings
- `e221de8` Support buildings in Zone 2, fix trade station visibility, auto-rotate modules
- `69227fc` Fix wandering asteroid re-attracting after bounce
- `64c1484` Refactor: extract shared UI helpers, centralise kill rewards, reorganise constants
- `d25b96f` Update docs with orbit AI, wanderer bounce, gas minimap, viewport culling
- `88cd69f` Add ranged alien orbit AI, wanderer bounce, and gas minimap markers

### 2026-04-06
- `e7c08e6` Enable wandering asteroid movement with viewport-culled updates
- `c84f567` Add viewport culling to Zone 2 draw and update
- `019f828` Optimize Nebula zone: cache fog overlay, remove hot-path allocations
- `b3b2ce3` Refactor game_save, zone2, inventory, and add game_state dataclasses

### 2026-04-05
- `46c1601` Save all zones' state cross-zone, optimize Zone 2 collisions, safe wormhole placement

### 2026-04-04
- `9b949a3` Persist Zone 2 across visits, optimize lightning, gas on minimap
- `d51efad` Optimize inventory draw: single background + grid lines instead of 25 cells
- `209fbb3` Cache gas textures, alien textures, and gas minimap positions
- `83bd142` Save/restore Zone 2 aliens, show gas areas as green on minimap
- `47dea0b` Fix Zone 2 map changing on save/load with deterministic world seed
- `8fcde3f` Fix fog of war not restored when loading save from Zone 2
- `b9be8e5` Fix pickup collection in all zones (iron, copper, blueprints)
- `73f7938` Optimize Zone 2: cache minimap, reduce object counts
- `8b24022` Fix gas cloud shape, add Zone 2 fog of war, show gas on minimap
- `edfe6e4` Show zone in save slots, fix gas visibility, stop Zone 2 asteroid movement
- `7da73a1` Fix UnboundLocalError: remove redundant local import arcade in zone2.py
- `cc89b64` Add zone entry announcements with pulsing text overlay
- `5590000` Fix wormhole transitions, warp zone danger, Zone 2 collisions, and scaling

### 2026-04-02
- `d775fd6` Fix wormhole transitions, warp zone danger, Zone 2 collisions, and scaling
- `7d57d56` Update rules, architecture, and lore docs with Zone 2 mechanics
- `3a46a7b` Update all documentation with Zone 2, warp zones, 10-level progression, and new features
- `04a35d9` Expand character progression to 10 levels, add ability meter HUD, update trader
- `62b98c8` Add Zone 2 (Nebula) biome with new resources, enemies, and advanced modules
- `2f41c6c` Add multi-zone system with 4 warp zones, zone transitions, and Zone 2 stub
- `bbaf878` Move game-rules.md to docs/, update asset lists, fix all references
- `44a715b` Optimize wormhole rendering, add Apache 2.0 license, add asset sources to docs
- `fa3001d` Add Shield Recharge consumable, wormholes on boss kill, and bug fixes

### 2026-04-01
- `2fac22b` Update docs with refactored architecture and new module structure
- `77ee72d` Refactor HUD, inventories, options, views, menus, and sprite AI
- `c76c234` Refactor game_view.py: extract 5 modules, reduce from 2175 to 621 lines
- `b13bd9b` Add music video player and character video documentation to docs
- `c0ed1b5` Move game documentation to docs/ directory, shrink root README
- `819b3e7` Add boss encounter with 3-phase AI, dramatic spawn announcement, and HP bar

### 2026-03-31
- `99c51ae` Add XP cap at 1000, character bio panel with portraits and backstories
- `e1ffdd4` Add character progression, trading station, faction shields, and perf optimizations

### 2026-03-30
- `08f94f8` Add Future Features section to README

### 2026-03-29
- `69b0c2d` Refactor game_view.py: extract save/load and music/video management
- `a8acee0` Add ship module system, sideslip, quick-use improvements, and 44 new tests
- `3038db3` Change character video player to 1:1 square aspect ratio

### 2026-03-28
- `1936dcc` Refactor escape_menu.py into package, update CLAUDE.md and README
- `1d80ac3` Add character video player in HUD, move world stats to T menu, add Video Properties menu

### 2026-03-22
- `2ab953d` Show fullscreen-required flash message on top of Songs menu
- `6cf940e` Fix quick-use bar occluding equalizer and remove debug prints

### 2026-03-21
- `c2edb6b` Update README with inventory stacking, quick-use bar, crafting, and building tooltip
- `96d3eae` Unify inventory item storage, add quick-use drag system, building hover tooltip
- `05735b6` Add more debug logging to station inventory on_mouse_release
- `a30ec4f` Add cross-panel detection to ship inventory for station transfers
- `ee3bd83` Fix cross-inventory transfer — detect ship panel in station release
- `ff6946e` Add debug logging for cross-inventory transfer cell targeting
- `d5d981c` Add nearest-empty-cell targeting for cross-inventory transfers
- `3b67d60` Fix cross-inventory drop cell targeting with iron cell check
- `3bcc0fa` Fix station inventory internal drag-and-drop cell targeting
- `1b3f2aa` Fix inventory drag z-order and drop-to-cursor-cell targeting
- `4a897aa` Fix drag preview z-order and drop-to-cell for ship-to-station transfer
- `4aeab4f` Fix station inventory closing when clicking ship inventory
- `1371307` Add two-way inventory transfer — ship to station via drag-and-drop
- `74666d3` Position station inventory to the left of ship inventory
- `d501a08` Fix overlap check blocking snapped module placement
- `6514bd6` Fix connectable placement — use larger search radius for edge-to-edge
- `7f6aa7c` Require connectable modules to snap to a port before placement
- `fb5e51a` Add station inventory, Basic Crafter, Repair Pack, and quick-use bar
- `389c590` Fix OST autoplay — respect autoplay_ost on splash and menu return
- `a914674` Add full config panel to Options with volume, video dir, autoplay OST
- `3c30326` Add visual feedback to Options Config button — shows 'Saved!' for 1.5s
- `ae32794` Fix audio/video interactions and add Config to Options
- `230e9b7` Reorganize ESC menu: Video Properties, Songs, Help structure
- `fbd0315` Remove video player diagnostic logging — performance validated
- `5560226` Fix video frozen frame — use time-based detection instead of id()
- `2d63ca5` Optimise video player — skip unchanged frames, reuse PIL buffers

### 2026-03-20
- `3b930bb` Add detailed performance diagnostics to video player
- `18997eb` Fix video VRAM leak — reuse single texture with in-place image update
- `07d6a6b` Fix resolution change triggering OST, stop video audio, and VRAM leak
- `eafc00a` Fix video player memory leak and set aggro range to 4x ship diameter
- `f196363` Add visual and audio effects when asteroids and aliens respawn
- `09bf5b9` Add persistent config, fix stop-video equalizer, and Config menu
- `4f218de` Stop video without auto-resuming music
- `8e3ddc5` Move controls to Help button; remove speed/heading from HUD
- `4beb2c5` Update game-rules.md with video fullscreen requirement and scrollbar
- `ab86946` Add scrollbar to video file list in escape menu
- `45a8baf` Block video mode in non-fullscreen — show error status message
- `28b1c40` Fix video scroll crash — cast scroll offset to int
- `eca52e4` Add song controls, weapon aggro, video fixes, and 4K optimization
- `0db99be` Document equalizer visualizer and update HUD description

### 2026-03-19
- `891699a` Fix equalizer position and add cascading colour patterns
- `8c3b49f` Add equalizer visualizer to HUD status panel
- `7445fad` Update docs with FFmpeg-only video, clock patch, and frame caching
- `e2abf0d` Cache video frame texture — only rebuild on new video frame
- `8034dbd` Fix pyglet clock crash during video playback
- `62030b6` Fix video orientation and aspect ratio — remove flip, use 16:9
- `84a30b8` Fix video texture access — use player.texture property not get_texture()
- `0a3486d` Call update_texture() before get_texture() to force frame decode
- `db4bb09` Force FFmpeg decoder for video — WMF doesn't provide video textures
- `3c4f791` Add diagnostic logging to video frame rendering
- `7ad9854` Suppress player movement and fire input while escape menu is open
- `e2abf0d` Cache video frame texture
- `865f318` Fix video rendering — use PIL conversion and remove fullscreen restriction
- `85c493b` Fix video frame rendering — convert pyglet texture to arcade.Texture
- `5a38977` Add FFmpeg DLLs to project root and update documentation
- `a1f7b3e` Use Windows Media Foundation for video — no FFmpeg needed
- `abf4fbe` Add FFmpeg detection and error reporting for video player
- `c77ec87` Fix overlapping audio and video directory click handling
- `a1ff05d` Fix AttributeError in video mode — use own Text objects instead of BuildMenu's
- `3532811` Fix UnboundLocalError — remove local import that shadowed STATUS_WIDTH
- `5a5fa9e` Fix resolution UI centering and add video player feature
- `ec37ca0` Update game-rules.md and CLAUDE.md with fog persistence, display modes, and UI patterns
- `ecd83d8` Fix fog of war not restoring on load from splash screen
- `d0dd34c` Fix save/load panel and title centering at all resolutions
- `bade2ac` Fix save naming prompt centering in the input box

### 2026-03-18
- `3804974` Fix inventory, build menu, and station info positioning at all resolutions
- `bc6b27d` Fix fullscreen UI centering — use actual window pixel dimensions
- `b856228` Fix UI centering at all resolutions — use live constants.SCREEN_*
- `1ebcb85` Fix borderless windowed crash — use pyglet display for screen lookup
- `307b0d0` Fix viewport scaling, fullscreen toggle, and add borderless windowed
- `749b2c2` Replace arcade.draw_text with pre-built Text objects in resolution UI
- `115fba6` Add camera offset, repair enhancements, resolution options, and alien AI fix
- `3ff4a5b` Increase fog reveal to 800px diameter and render grey fog on mini-map
- `72ef1a2` Add fog of war, 2-min respawn, and remove escape menu pause
- `c8f0d59` Add building iron drops, placement overlap check, and HUD counters

### 2026-03-17
- `1525790` Add Repair Module, destroy mode, and two-way port connectivity
- `0de553f` Add asteroid/alien respawning and alien iron drops
- `9a8621b` Update README with all game features including building system, audio controls, and station info
- `39e0de7` Add escape menu audio sliders, edge-to-edge building snap, player-building collision, station info panel, and module count in save slots
- `3d433a9` Fix ghost sprite drawing — use SpriteList instead of Sprite.draw()
- `2cdcdcd` Add space station building system with 7 module types

### 2026-03-16
- `43ab711` Fix ESC on faction selection to return to splash screen instead of exiting
- `9614499` Rename window title to Call of Orion and add 50 random death quotes
- `04b13ca` Add unit test suite with 174 tests covering all game modules
- `81aaeec` Rewrite CLAUDE.md to reflect current project architecture
- `c14e4b1` Add comprehensive game rules and reference document
- `a4ef960` Add Exit Game button to splash screen and options screen
- `ed2da90` Add fire sparks, player death, save slot details, and optimize music loading
- `17b4668` Add splash screen, options screen, and global audio settings
- `793faa2` Display current music track name in HUD status panel
- `600c0ce` Add numerical HP and shield values underneath status bars
- `75d23c3` Upgrade ship sprites from 64x64 to 128x128 for higher resolution

### 2026-03-15
- `5f7857f` Add shuffled background music playlist during gameplay
- `bc36f53` Sharpen ship preview images on selection screens with nearest-neighbor scaling
- `2393d03` Optimize performance, fix inventory hint position, increase Striker damping
- `fe63cdd` Fix inventory hint text occlusion and joystick DeviceOpenException on view transitions
- `4a4bdb3` Change selection sounds to ping, add 10 named save slots
- `7820269` Change selection screen sounds to hi-tech beeps, update README with all features
- `61795e3` Add escape menu with save/load, main menu return, and exit
- `4e7cc52` Refactor game_view.py into modules, fix sounds and Striker stats
- `3aafbaa` Fix thruster sound: use loop= parameter (Arcade 3.x API)
- `93fbda5` Add dual-gun firing, thruster sound, engine contrails, selection SFX, and HUD indicators
- `e70905c` Add faction & ship type selection screen before gameplay
- `6be76eb` Add player ship stats table to CLAUDE.md
- `816f662` Refactor: split monolithic main.py into focused modules
- `7c2e009` Alien collision physics, avoidance steering, mining beam pass-through
- `082a24c` Fix mining beam not damaging alien ships
- `36a7d32` Fix ShieldSprite AttributeError: draw via SpriteList
- `0d800c6` Add animated shield bubble around player ship
- `5c30eb7` Add asteroid hit shake, player shields with regen, shield-first damage
- `202a5a1` Add alien hit effects and fix alien combat parameters
- `f2d7de6` Add 20 small alien ships with patrol/pursue AI and alien laser
- `4059d68` Eject dropped items 60px from ship edge to prevent immediate re-collection
- `3523e31` Fix inventory world-ejection: items no longer return to panel when dropped outside
- `138e878` Replace arcade.draw_text() with pre-built arcade.Text objects in Inventory
- `34d233a` Eject inventory items into world when dropped outside the panel
- `440c0cb` Add minimap, inventory tooltips; widen iron pickup to 40px edge distance
- `853da4d` Add inventory drag-and-drop item rearrangement
- `e738108` Fix iron pickup trigger to use ship edge distance, not centre distance
- `905d7bf` Add iron drops, pickup animation, collision bump sound & camera shake
- `9458c79` Add F-key FPS toggle to status panel
- `f313e17` Add ship-asteroid collision: bounce physics and HP damage
- `8ca3b79` Add Iron Asteroids with mining, explosion FX and sound
- `453a02c` Reduce inventory grid from 10×10 to 5×5
- `172af27` Add weapons, projectiles, and cargo inventory

### 2026-03-13
- `e7a4e51` Revert thrust to original values; increase acceleration rate 25%
- `2f21cc6` Increase thrust and brake acceleration by 25%
- `c904d67` Fix: use only sprite row 0 to prevent nose/wing weapon effects during thrust
- `6284924` Fix: wing turrets no longer activate during thrust
- `1eae655` Thruster only glows and animates when thrusting forward
- `7248fd8` Animate thruster exhaust based on thrust state
- `303eeae` Fix Xbox 360 gamepad support via XInput
- `d0cfcf6` Fix controls and HUD performance
- `8695690` Fix Arcade 3.x texture loading API
- `6e826a3` Add main play screen with player ship and controls
- `886f33c` Add repo URL to CLAUDE.md and README.md
- `511d64c` Initial project setup

### 2026-03-10
- `e525f28` Initial commit

## Future features (from README)

Already covered above in the top-level future-features list. Summary:

- [x] Ship level advancement (shipped)
- [x] Enemy ships that manoeuvre like the player (shipped)
- [ ] New space biomes (partial — Zone 2 + 4 warp zones)
- [ ] Hazardous zones (partial — lightning + gas + meteor warp)
- [ ] Advanced resources (partial — copper)
- [ ] New space monsters (partial — Zone 2 aliens + wanderers)
- [ ] Characters — branching storylines, ship skins (partial)
- [ ] Warp gates to new star systems (partial — wormholes in-system)
- [ ] Planetary landing
- [ ] Planetary vehicles
