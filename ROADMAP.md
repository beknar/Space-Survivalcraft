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
- [x] Refresh `CLAUDE.md`, `README`, and all `docs/*.md` for recent
      source changes (`7906694`)
- [x] **AI Pilot module** — craft at the Advanced Crafter (800 iron +
      400 copper), drag-install on a parked ship to make it autonomous;
      patrols within 400 px of the Home Station, engages enemies inside
      600 px, fires into `gv.turret_projectile_list` every 0.5 s.
      Zone 1 + Zone 2 perf tests and a 5-min soak test ship with the
      feature. (`4507a01`)
- [x] **Double Star Refugee NPC + dialogue overlay** — building a
      Shield Generator in the Nebula triggers an invulnerable NPC scout
      ship that flies in from the right edge. Clicking within 320 px
      opens a character-specific branching conversation. Debra's tree
      is a full five-scene Ken-Tamashii arc with every branch encoded;
      Ellie/Tara stubs in place. Overlay supports 1-9 choice keys,
      SPACE/ENTER to advance, ESC to close without committing. 12 unit
      + 4 integration + 3 soak tests. (`a5a4078`)
- [x] **AI Pilot patrol polish** — the autonomous ship now orbits the
      Home Station counter-clockwise at 90 % of the patrol radius
      instead of idling, and flips to `return` mode after firing when
      no other enemies are in range (resumes patrol on base arrival).
      5 new unit + 3 integration + 2 soak tests. (`7e7490d`)
- [x] **Station shield + AI yellow shield + refugee parks outside
      station** — first Shield Generator build spawns a faction-tinted
      bubble over the Home Station (100 HP, absorbs alien + boss
      projectiles before they reach buildings, scales with station
      extent). AI-piloted parked ships now carry their own yellow
      shield bubble with half-rate regen. Refugee NPC's parking spot
      moved outside the station's outermost building edge. 10+ new
      unit + 5 integration + 1 soak test. (`47b7f6c`)

### 2026-04-15 — Refactor pass + shield polish

- [x] **Refactor pass 1-7** — shared soak scaffolding, collision
      cooldown helper, shared alien AI module, escape-menu button
      helper, save codec documentation, GameView init ordering
      contract, constants_paths.py re-export surface. 14 unit + 2
      integration + 1 soak test lock in the new helpers. (`b294a4d`)
- [x] **Station shield border-only visual** — `ShieldSprite` now
      accepts an `alpha` constructor parameter; station shield uses
      alpha 15 for a near-invisible fill with a solid 3 px circle-
      outline border drawn on top. `_station_outer_radius` now counts
      building *edges* (centre + `BUILDING_RADIUS`); refugee parking
      pad grew 70 → 120 px. (`ba3f466`)
- [x] **Flaky-test fix (PR #7)** — `_spawn_station` parks the player
      300 px from world centre so Zone 2's wormhole can't auto-
      transition them mid-test. (`ffb2997`)

### 2026-04-16 — Documentation pass

- [x] Refresh README, docs/, CLAUDE, and ROADMAP for every change
      since 2026-04-14: station shield + refugee parking + shielded
      AI fleet + refactor-pass helpers + updated test counts
      (493 fast / 144 integration / 637 total).

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
- [ ] **Allied NPCs / autonomous wingmen** _(AI Pilot module ships
      already autonomously patrol + engage near the home station;
      wider allied-NPC systems still open)_
- [ ] **Characters** — branching storylines, character-specific abilities,
      ship skins _(10-level bonus trees shipped; Debra's refugee
      storyline shipped; Ellie/Tara branches and ship skins still open)_
- [ ] **Warp gates** — travel to new star systems _(intra-system wormholes
      shipped; cross-system gates still open)_
- [ ] **Planetary landing** — land on planets with different surface biomes
- [ ] **Planetary vehicles** — ground-based exploration
