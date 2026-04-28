# Call of Orion --- Architecture

## Overview

The codebase follows a modular extraction pattern where the central `GameView` class acts as a thin dispatcher, delegating logic to focused modules. Each extracted module receives a `GameView` reference and uses `TYPE_CHECKING` to avoid circular imports.

## Module Structure

### Core Gameplay (GameView + Extracted Modules)

| Module | Lines | Responsibility |
|---|---|---|
| `game_view.py` | ~830 | Thin dispatcher: `__init__` (split into 13 sectioned init helpers), delegate methods, fog of war, weapon helpers |
| `combat_helpers.py` | ~237 | Damage, death, spawning, respawn, XP, boss spawn |
| `building_manager.py` | ~235 | Building placement, destruction, port snapping, trade station |
| `ship_manager.py` | ~220 | Ship upgrade, new-ship placement, switch-to-ship; `_deduct_ship_cost` + `_resize_module_slots` shared helpers; re-exported via `building_manager` for legacy imports |
| `constants_paths.py` | ~50 | Re-export surface for asset-path constants only (no gameplay tunables). Callers that just need file paths can import from here to keep their dependency surface tight |
| `draw_logic.py` | ~390 | `draw_world()`, `draw_ui()`, `compute_world_stats()` |
| `update_logic.py` | ~570 | 11 update sub-functions for the game loop |
| `input_handlers.py` | ~690 | All keyboard and mouse event handling; eject routing split into 4 helpers |
| `game_save.py` | ~690 | Save/load serialization with `_restore_sprite_list` factory helper |
| `game_music.py` | — | Music playlist, video playback management |
| `collisions.py` | ~490 | All collision handlers + `resolve_overlap` / `reflect_velocity` physics primitives |
| `qwi_menu.py` | — | Quantum Wave Integrator menu — Nebula-boss summon button (100 iron) |
| `map_overlay.py` | — | Full-screen map (`M` key) — zoomed-out view of the active zone with player + entity overlays |
| `zones/` | — | Zone state machine: `MainZone` (Zone 1), `Zone2` (Nebula), `StarMazeZone` (Zone 3), 4 warp-zone classes reused for 3 variants each (`WARP_*`, `NEBULA_WARP_*`, `MAZE_WARP_*`); shared content in `zone2_world.py`, `nebula_shared.py`, `maze_geometry.py` |

### Extraction Pattern

All extracted modules follow the same pattern established by `collisions.py`:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_view import GameView

def some_function(gv: GameView, ...) -> ...:
    # Access state via gv.player, gv.inventory, etc.
    ...
```

GameView keeps thin one-liner delegate methods so external callers continue to work:

```python
def _spawn_explosion(self, x, y):
    _ch.spawn_explosion(self, x, y)
```

### UI Layer

| Module | Lines | Responsibility |
|---|---|---|
| `ui_helpers.py` | ~118 | Shared `draw_button()`, `draw_load_slot()`, `draw_tooltip()`, standard colour constants |
| `hud.py` | ~518 | HUD status panel, delegates minimap and equalizer |
| `hud_minimap.py` | ~185 | Minimap drawing with fog overlay |
| `hud_equalizer.py` | ~83 | Equalizer visualizer state and rendering |
| `base_inventory.py` | ~84 | Shared `BaseInventoryData` mixin (add/remove/count/consolidate, badge texture cache) |
| `inventory.py` | ~420 | 5x5 cargo grid (inherits BaseInventoryData) |
| `station_inventory.py` | ~381 | 10x10 station grid (inherits BaseInventoryData) |
| `escape_menu/` | ~10 files | Escape menu with sub-mode pattern |
| `build_menu.py` | ~337 | Station building overlay |
| `craft_menu.py` | ~283 | Crafting UI |
| `trade_menu.py` | ~360 | Trading station overlay with scrollable sell panel, pooled row Text objects, and batched `SpriteList` fills for the panel chrome |
| `dialogue_overlay.py` | ~180 | NPC conversation overlay — centred panel, pooled Text objects, up to 4 choices (1-9/click), SPACE/ENTER/click advance, ESC close, aftermath sink |
| `dialogue/` | — | Conversation-tree data (`debra_refugee.py`, `ellie_refugee.py`, `tara_refugee.py`) with a `get_refugee_tree(char)` dispatcher |

### Sprite AI

| Module | Lines | Key Methods |
|---|---|---|
| `sprites/alien.py` | ~315 | `update_alien` dispatches to `_update_movement` (standoff orbit AI), `_update_stuck_detection`, `_update_color_tint`, `_try_fire` |
| `sprites/boss.py` | ~354 | `update_boss` dispatches to `_update_charge`, `_try_fire_weapons`, `_update_color_tint` |
| `sprites/shielded_alien.py` | — | ShieldedAlien --- alien with 50-point shield |
| `sprites/fast_alien.py` | — | FastAlien --- 160 px/s high-speed alien |
| `sprites/gunner_alien.py` | — | GunnerAlien --- dual-gun alien |
| `sprites/rammer_alien.py` | — | RammerAlien --- charging alien with 100 HP + 50 shields |
| `sprites/copper_asteroid.py` | — | CopperAsteroid --- minable copper resource |
| `sprites/gas_cloud.py` | — | GasCloud --- toxic environmental hazard |
| `sprites/wandering_asteroid.py` | — | WanderingAsteroid --- drifting magnetic asteroid |
| `sprites/missile.py` | — | HomingMissile --- consumable homing projectile |
| `sprites/force_wall.py` | — | ForceWall --- deployable barrier sprite |
| `sprites/npc_ship.py` | ~55 | `RefugeeNPCShip` --- story NPC with approach AI, hold-at-distance, no-op `take_damage` |
| `sprites/alien_ai.py` | ~100 | Shared alien-AI helpers: `pick_patrol_target`, `compute_avoidance` (asteroid + sibling-alien + force-wall repulsion), `segment_crosses_any_wall`. Used by both `SmallAlienShip` and `Zone2Alien` |
| `sprites/maze_alien.py` | — | MazeAlien --- A*-pathing dungeon enemy spawned by MazeSpawner; takes `rooms` + `room_graph` and replans waypoints via `astar_room_path` whenever the player is in a different room |
| `sprites/maze_spawner.py` | — | MazeSpawner --- stationary turret in every Star Maze room; HP + shields + child cap + respawn cadence |
| `sprites/nebula_boss.py` | — | NebulaBoss --- Zone-2 boss with cannon + gas-cloud + cone attacks; routes around force walls; rams asteroids |
| `sprites/null_field.py` | — | NullField --- stealth patch that toggles `gv._player_cloaked`; firing inside disables it for 10 s |
| `sprites/slipspace.py` | — | Slipspace --- paired teleporter portal that conserves velocity on entry |

## Dependency Graph

```
constants.py   <-- nearly everything (central config, 16 sections)
settings.py    <-- splash_view, options_view, game_view, death_screen
ui_helpers.py  <-- splash_view, death_screen, options_view, escape_menu, hud (shared button/slot/tooltip drawing)

game_view.py (thin dispatcher)
  +-- combat_helpers.py
  +-- building_manager.py --> ship_manager.py (upgrade / place / switch)
  +-- draw_logic.py
  +-- update_logic.py --> collisions.py
  +-- input_handlers.py
  +-- game_save.py
  +-- game_music.py
  +-- hud.py --> hud_minimap.py, hud_equalizer.py
  +-- inventory.py, station_inventory.py --> base_inventory.py
  +-- sprites/*
  +-- world_setup.py
  +-- escape_menu/
  +-- zones/ (zone state machine, warp zones, Zone 2)

collisions.py
  +-- constants.py (radii, damage, bounce)
  +-- sprites/explosion.py (HitSpark)
  +-- sprites/building.py (HomeStation disable cascade)
  +-- character_data.py (kill bonus functions)
  +-- settings.py (character name for bonuses)
```

## Key Design Patterns

- **Shared UI helpers** --- `ui_helpers.py` provides `draw_button()`, `draw_load_slot()` (with `grey_empty` flag), and `draw_tooltip()`; used by splash_view, death_screen, options_view, escape_menu save/load mode, and HUD tooltips
- **Kill reward centralisation** --- `collisions._apply_kill_rewards()` handles explosion + loot + XP for all kill types, eliminating 3x duplicated bonus blocks
- **Constants organisation** --- `constants.py` uses 16 named `═══` sections with a docstring table of contents for discoverability
- **Pre-built `arcade.Text` objects** --- avoids per-frame allocation (PerformanceWarning)
- **Spatial hashing on STATIC sprite lists only** --- `asteroid_list`, `building_list`, and Zone 2's `_iron_asteroids`/`_double_iron`/`_copper_asteroids` use `use_spatial_hash=True` for O(1) lookups. Alien lists (`alien_list`, Zone 2 `_aliens`, warp-zone enemy aliens) deliberately do NOT use spatial hash because aliens move every frame, which forces a per-frame O(N) hash rebuild that costs more than it saves.
- **Inventory render cache (dirty flag)** --- `BaseInventoryData` builds two `SpriteList`s on first draw (cell fills via `SpriteSolidColor`, item icons via textured `Sprite`s) and rebuilds them only when `_render_dirty` is set. Count badges are rendered as PIL text into `arcade.Texture` sprites via `_get_badge_texture(count)` (cached in `_badge_tex_cache`), batched into `_cache_badge_list` SpriteList — one `SpriteList.draw()` replaces 100 per-frame `arcade.Text.draw()` calls. Station inventory went from 26.7 FPS to 50.9 FPS with both inventories open. Both inventories also batch grid lines into a single `arcade.draw_lines()` call.
- **Minimap dot batching** --- `hud_minimap.draw_minimap` collects asteroid/pickup/alien/building positions into per-colour point lists and submits them with a single `arcade.draw_points()` call per colour, instead of per-sprite `draw_circle_filled`. Critical when the Nebula minimap shows 200+ entities.
- **Zone-aware Station Info** --- `draw_logic.compute_world_stats(gv)` returns `(label, count, color)` tuples driven from `gv._zone`. Zone 1 reports ASTEROIDS/ALIENS/BOSS HP; Zone 2 reports IRON ROCK/BIG IRON/COPPER/WANDERERS/GAS AREAS/ALIENS. The `StationInfo._t_stats` pool is generic and renders whatever entries are passed.
- **Collision physics primitives** --- `collisions.resolve_overlap(a, b, ra, rb, push_a, push_b)` does the push-apart math and returns the contact normal `(nx, ny)` (or `None` for no contact). `collisions.reflect_velocity(obj, nx, ny, bounce)` reflects a single body's velocity along that normal with restitution. Used by 9+ collision handlers across `collisions.py` and `zones/zone2.py`, eliminating ~150 lines of duplicated bounce/push math. Asymmetric impulses (e.g. alien-vs-player 0.4-weighted player kickback) and the asteroid `_base_x` quirk (asteroids snap to base position during the resolve so the contact normal isn't jittered by the visual shake) are handled at the call sites.
- **Generic save-restore helper** --- `game_save._restore_sprite_list(target_list, entries, factory)` clears the target sprite list and rebuilds it via a per-entry factory closure. Used by Zone 1 asteroids and all four Zone 2 entity lists (iron, double iron, copper, wanderers). Factory may return `None` to skip an entry.
- **HUD stat bar helper** --- `HUD._draw_stat_bar(y, current, maximum, color, value_text)` renders one HP/shield/ability bar with cached numerical label, replacing three near-identical 12-line bar drawing blocks. Cached `arcade.Text` is updated only when the displayed value actually changes.
- **Inventory eject routing** --- `input_handlers._handle_inventory_eject` dispatches to four small destination helpers: `_eject_to_module_slot` (modules/blueprints onto HUD slots), `_eject_to_quick_use` (consumables to quick-use bar), `_eject_to_station_inv` (drop into station grid), `_eject_iron_to_world` (spawn iron pickup outside ship). Top-level dispatcher is now a 4-line route table.
- **GameView sectioned `__init__`** --- the constructor delegates to 13 named init helpers (`_init_player_and_camera`, `_init_abilities_and_effects`, `_init_text_overlays`, `_init_input_devices`, `_init_weapons_and_audio`, `_init_world_entities`, `_init_boss_and_wormholes`, `_init_consumable_textures`, `_init_inventories`, `_init_buildings_and_overlays`, `_init_world_state`, `_init_hud_audio_video`, `_init_zones`). The body itself is a 13-line scannable list of init phases. Order is significant: textures and sprite lists must exist before the overlays that consume them.
- **Sound player cleanup** --- `update_logic._tracked_play_sound` monkey-patches `arcade.play_sound` to track returned pyglet Players with timestamps. `_cleanup_finished_sounds()` runs every 5 s and `.delete()`s Players older than 3 s. Root cause: pyglet's event system holds strong references to finished Players (`.playing` stays True even after sound ends); with GC disabled, thousands accumulate during combat (8+ sounds/s), degrading FPS from 63 to 7 over 5 minutes. Fix verified: FPS stable at 95--100 for 5+ minutes of continuous combat.
- **GC management** --- automatic GC disabled; periodic `gc.collect()` every 5 s (in sound cleanup) and manual collect when ESC menu opens
- **Inventory SpriteList reuse** --- `_build_render_cache` reuses existing SpriteList objects (clear + repopulate) instead of creating new ones, and caches a single fill texture (`_fill_tex`) shared across all fill sprites. Prevents Arcade texture atlas leak (~0.2 MB/rebuild from atlas entries that never reclaim).
- **Sound throttling** --- min 0.15s between pyglet media player creations
- **BaseInventoryData mixin** --- shared item storage, drag state, icon resolution, badge texture cache (`_get_badge_texture`/`_badge_tex_cache`/`_cache_badge_list`) inherited by both inventory classes; subclasses set `_rows`/`_cols`
- **Ruff linter** --- `ruff.toml` with bug-focused rules; catches unused imports, dead variables, and real import bugs
- **Test infrastructure** --- `pytest.ini` excludes `integration/`; `conftest.py` provides `StubPlayer` and `StubGameView` for windowless zone testing; `psutil` dev dependency for soak tests; 906 fast + ~309 integration ≈ 1215 total tests. Shared soak scaffolding lives in `unit tests/integration/_soak_base.py` (`SOAK_DURATION_S`, `MIN_FPS`, `MAX_MEMORY_GROWTH_MB`, `run_soak`). Integration covers functional (Zone 2 + Star Maze real-GameView flows), FPS (trade panels × {Zone 1, Zone 2} × {no video, both videos}, buy↔sell churn, AI Pilot fleets with/without videos, station shield combat, shielded-fleet + station-shield pairing, refugee NPC spawn + dialogue, patrol/return integration), GPU render, resolution scaling (6 presets × 2 zones), and soak/endurance (5 min each; AI pilot patrol cycle + idle orbit, dialogue spine/exhaustive/character rotation, station shield cycle, **Star Maze idle / combat churn / Nebula pressure**, shared scaffolding). Real music-video tests load `./yvideos/*.mp4` (gitignored)
- **Refactor-pass helpers** --- `collisions._hit_player_on_cooldown` replaces the 6-site `check-cd → apply-damage → reset-cd → sound → shake` pattern; `sprites/alien_ai.py` hosts the shared pick-patrol-target + compute-avoidance + segment-crosses-any-wall helpers both alien hierarchies delegate to; `escape_menu/_ui.draw_button` replaces the repeated rect+outline+text pattern across sub-modes; `constants_paths.py` exposes just the asset-path constants; `game_save._z2_alien_type_name` caches the class→tag lookup and a codec-pair table at the top of `game_save.py` documents each serialize/restore pair so drift is visible at review time
- **EqualizerState class** --- encapsulates equalizer animation with `update(dt, volume)` and `draw(y)`
- **MenuContext + MenuMode** --- escape menu sub-mode pattern with shared state and per-mode draw/input
- **TYPE_CHECKING imports** --- all extracted modules avoid circular imports at runtime
- **Zone state machine** --- `zones/` package manages transitions between Zone 1, Zone 2 (Nebula), Zone 3 (Star Maze), and 12 warp zones (4 themes × 3 variants: `WARP_*`, `NEBULA_WARP_*` with 2× danger, `MAZE_WARP_*`). Each zone has its own asteroid/alien populations, hazard rules, and background; GameView delegates zone-specific setup and update logic to the active zone state. Star Maze + Zone 2 share Nebula content via `zones/nebula_shared.py` (collision/update/fog/gas/wanderer/asteroid handlers) so a fix in one zone applies to both. Star Maze geometry — recursive-backtracking maze gen, room adjacency graph, A* pathing helper, point-in-rect + segment-vs-walls helpers — lives in `zones/maze_geometry.py`. Each warp-zone class is reused for all three variants; `instance.zone_id` distinguishes the variant inside `setup`
- **Viewport culling (update only)** --- Zone 2 only updates asteroid/wanderer/gas sprites within camera bounds + 250 px margin (gas areas get +200 px extra); offscreen wanderers spin-only. Drawing uses direct `SpriteList.draw()` calls on the static lists rather than per-frame visibility rebuild --- the static VBOs upload once and the renderer handles offscreen culling efficiently.
- **Ranged alien standoff AI** --- gun-equipped aliens orbit at `ALIEN_STANDOFF_DIST` (300 px) with random CW/CCW direction; RammerAlien charges directly (`has_guns=False`)
- **Turret target caching** --- `Turret._cached_target` and `_target_rescan_cd` (0.25 s) avoid scanning all aliens every frame; cached target validated cheaply (alive + in range); full rescan 4x/s
- **Star Maze multi-list turret targeting (no SpriteList allocation)** --- `StarMazeZone` exposes hostile sprites across three SpriteLists: `_maze_aliens` (`gv.alien_list` swap target), `_stalkers`, `_aliens` (Z2-style). `StarMazeZone._turret_extra_target_lists` returns `(_stalkers, _aliens)`. Each frame, `update_logic.update_buildings` builds a plain Python list (`list(gv.alien_list) + extras`) for turret AI selection, and `collisions.handle_turret_projectile_hits` iterates the targeting SpriteLists tuple `(gv.alien_list, *extras)` separately, calling `arcade.check_for_collision_with_list` on each. The previous design used a per-frame `SpriteList.clear()+append()` cycle that leaked ~15 KB per call (back-reference accumulation in each sprite's `sprite_lists` tuple) and tanked soak runs to ~568 MB growth in 5 min; pinned at no-leak by `unit tests/test_star_maze_turret_targets.py`
- **Per-faction lightsabre melee** --- `world_setup.load_weapons(gun_count, faction=None)` reads `MELEE_SWORD_PNG_BY_FACTION` (Earth → Sabers-06, Colonial → Sabers-05, Heavy World → Sabers-02, Ascended → Sabers-03) and falls back to `MELEE_SWORD_PNG` when faction is unknown. Threaded through every load_weapons call site (`game_view._init_weapons_and_audio`, `combat_helpers._restore_player`, `combat_helpers.add_xp`, `ship_manager.switch_to_ship`). `MeleeBlade` (in `sprites/melee.py`) is a persistent sprite anchored at `ship.center + MELEE_HIT_RADIUS * forward`, sliding its centre forward by `height/2 * tip_dir` each frame so the handle stays fixed and the tip arcs through the swing animation (-75° → +75°, `MELEE_SWING_ARC = 150.0`). Lightsabre PNG is drawn vertically so `MELEE_TEX_ANGLE_OFFSET = 0.0` (no diagonal compensation needed)
- **Distance-based alien AI culling** --- Zone 2 alien updates check viewport-width + 500 px squared range; aliens outside get cheap position-only updates (velocity decay + drift) instead of full obstacle-avoidance AI
- **Fog texture rebuild throttling** --- `_FOG_REBUILD_THRESHOLD = 8` skips PIL fog overlay rebuilds until 8+ new cells are revealed, avoiding per-frame image creation while the player moves
- **Inlined fog visibility checks** --- minimap entity loops use pre-computed `_inv_cell`, `_fg`, `_fw`, `_fh` locals instead of calling `is_revealed()` 200+ times per frame
- **Gas area minimap batching** --- octagonal outlines drawn via a single `arcade.draw_lines()` call with separate x/y radii for correct proportions in non-square zones
- **Zone 2 building stash** --- `Zone2.teardown()` saves building state into `_building_stash` dict; `Zone2.setup()` restores it; prevents MainZone from overwriting Zone 2 buildings during zone transitions
- **Background zone simulation** --- `ZoneState.background_update(gv, dt)` virtual method; `MainZone` operates on stashed sprite lists, `Zone2` on its own lists; called from `GameView.on_update` when `audio.simulate_all_zones` is True
- **Inactive zone info panel** --- `draw_logic.compute_inactive_zone_stats()` reads Zone 1 stash and Zone 2 sprite list counts; `StationInfo._draw_inactive_zones()` renders a dynamically-sized "Other Zones" panel with pre-pooled `arcade.Text` objects
- **Multi-ship system** --- `ParkedShip(arcade.Sprite)` in `sprites/parked_ship.py` stores faction, type, level, HP, shields, `cargo_items` dict, and `module_slots` list. NOT a StationModule subclass. `ship_manager._place_new_ship()` creates a ParkedShip from the current player and upgrades the active ship. `ship_manager.switch_to_ship()` snapshots the current player into a new ParkedShip, creates a new PlayerShip from the target, and swaps inventory/modules/weapons/ability meter. `collisions.handle_parked_ship_damage()` checks alien, player, and boss projectiles against `gv._parked_ships`. `_destroy_parked_ship()` drops cargo and modules. Parked ships stashed in `_ZONE1_LISTS` and Zone 2's `_building_stash`; serialized via `game_save._serialize_parked_ships()`. A cached `gv._t_parked_ship_tip` renders the HP hover tooltip.
- **Force wall routing** --- `sprites/force_wall.py` exposes `closest_point`, `blocks_point`, and `segment_crosses`. `update_logic.update_force_walls` consumes projectiles from `alien_projectile_list`, `_boss_projectile_list`, and the Zone 2 stashed list. Alien AI classes (`sprites/alien.py`, `sprites/zone2_aliens.py`) take a `force_walls` kwarg through `update_alien` / `_update_movement` / `_move` and add a 2× repulsion term plus a post-move segment-crossing revert so aliens route around the wall instead of passing through.
- **Long-press turret move** --- `input_handlers._try_start_building_move` starts a timer on LMB-down over a Turret/MissileArray; `update_logic.update_timers` (and `handle_mouse_drag`) promote the pending move after `MOVE_LONG_PRESS_TIME` (0.4 s). `_clamp_turret_position` clamps each frame to within `TURRET_FREE_PLACE_RADIUS` (300 px) of the Home Station. Release runs overlap validation; ESC snaps back.
- **Trade panel batching** --- `TradeMenu._rect_sprites` is a pooled `arcade.SpriteList` of `SpriteSolidColor` objects reused every frame via `_rect_reset/_rect_add/_rect_flush`. Per-mode drawers split into a fills phase and a text/outline phase; a second pool of `arcade.Text` objects (`_row_texts`) handles row labels, only re-laying-out on text change. Cut ~15 immediate-mode rect calls per frame down to a single `SpriteList.draw()`.
- **Streaming music loops + alien texture cache** --- `world_setup.collect_music_tracks` loads each WAV with `streaming=True` to avoid a pyglet `MemoryError` on long loops. `world_setup._alien_tex_cache` memoises the cropped Ship.png / Effects.png textures; `populate_aliens` now returns `(slist, ship_tex, laser_tex)` and `GameView._init_aliens` reuses them instead of re-decoding both sheets (~200 MB of redundant PIL allocation per load). `splash_view._do_load` additionally runs `gc.collect()` before constructing the replacement GameView.
- **AI Pilot module** --- installing `ai_pilot` on a `ParkedShip` activates `ParkedShip.update_ai(dt, home_pos, targets, projectile_list, laser_tex)`. An `_ai_mode` field toggles between `"patrol"` (`_orbit_patrol` moves counter-clockwise along the tangent, then snaps radius back to `AI_PILOT_PATROL_RADIUS * AI_PILOT_ORBIT_RADIUS_RATIO`) and `"return"` (straight line back to the Home Station, cleared once within `AI_PILOT_HOME_ARRIVAL_DIST`). Engaging a target flips mode back to `"patrol"`; firing at the last live target flips mode to `"return"`. Shots go to `gv.turret_projectile_list` (so existing turret collision handling delivers damage). Wired via `update_logic._update_parked_ships`, which is called from both Zone 1's `update_entities` and Zone 2's `update` with the alien list swapped in.
- **Story NPC + dialogue tree** --- `update_logic.update_refugee_npc` watches for the first `Shield Generator` while the player is in Zone 2, spawns `RefugeeNPCShip` on the right edge, retargets a parking spot at `(home.x + station_outer_radius + 120, home.y)` every frame (with `hold_dist=24`), and hands off to `update_npc` for the approach. `station_outer_radius` adds `BUILDING_RADIUS` so the measurement covers building *edges*, preventing the parked NPC from overlapping any building. `input_handlers._handle_world_click` opens `DialogueOverlay.start(tree, aftermath_sink=gv._quest_flags)` when the player clicks the ship within `NPC_REFUGEE_INTERACT_DIST`. Trees live in `dialogue/*.py` as dicts keyed by node id with `speaker`, `text`, optional `stage`, and one of `choices` / `next` / `end`. Terminal `end` nodes merge an `aftermath` dict into the sink (e.g. Debra's "find_ken" quest flag). Persisted state: `gv._refugee_spawned`, `gv._met_refugee`, `gv._refugee_npc` pose, `gv._quest_flags`.
- **Station shield** --- `update_logic.update_station_shield` spawns a faction-tinted `ShieldSprite` (alpha 15 fill) centred on the Home Station whenever a Shield Generator exists. Scale = `2 * (station_outer_radius + STATION_SHIELD_PADDING) / SHIELD_FRAME_W`. `collisions._station_shield_absorbs` intercepts alien and boss projectiles inside the disk, bleeds `proj.damage` from `_station_shield_hp`, flashes the sprite, and consumes the projectile before building collision runs. `draw_logic._draw_station_shield` renders the sprite list and then layers a solid 3 px `draw_circle_outline` at the shield radius on top (alpha 200 / 255 on hit-flash) plus a faint inner glow ring, so the border dominates the visual while the interior stays readable. Persisted via `station_shield_hp` and `station_shield_max_hp` — restore re-materialises the sprite on the next update tick as long as the Shield Generator is still present.
- **ShieldSprite alpha parameter** --- `sprites/shield.py`'s constructor takes an optional `alpha` (default 200) that becomes `_base_alpha`. The ship shield and the AI-pilot yellow bubble use 200 (full opacity); the station shield passes `alpha=15`. `hit_flash` spikes to `min(255, base_alpha + 55)` and decays back to the base.

## Drone Pathfinding

Both companion drones (`MiningDrone` + `CombatDrone`) and the
Star Maze enemies (`MazeAlien`) share a single A* pathfinder
over the maze's room-adjacency graph: `WaypointPlanner` in
`zones/maze_geometry.py`.  It is a stateful per-body object —
each drone or alien owns one — and produces one steering
waypoint per frame.  The planner is a no-op outside the Star
Maze (constructed with `rooms=None` / `room_graph=None`).

### MazeLayout — the data the planner consumes

`zones/maze_geometry.MazeLayout` is the per-maze artefact
emitted by `generate_maze()`.  Every field below is read by
`WaypointPlanner`:

| Field | Type | Used for |
|---|---|---|
| `rooms` | `list[Rect]` | `find_room_index`, AABB membership, room-centre fallback waypoint |
| `walls` | `list[Rect]` | Drone slot blocking, maze-alien collision, segment LOS tests |
| `room_graph` | `dict[int, list[int]]` | A* adjacency over carved doorways |
| `doorways` | `dict[frozenset[int], (x, y)]` | Per-edge gap midpoint — the actual steering target between two rooms |
| `entrance_room` | `int` | The single room adjacent to the carved outer-wall gap |
| `entrance_xy` | `(x, y)` | World-space midpoint of the outer-wall gap |
| `entrance_xy_outer` | `(x, y)` | A point `2 * wall_thick` past the gap along the outward normal — the "step out into open space" steering target |

Star Maze hosts `STAR_MAZE_COUNT` (4) mazes.
`update_logic.update_drone` stitches the per-maze tables into a
single unified rooms / room_graph / doorways /
`room_to_exit_room` / `exit_xy_by_room` /
`exit_outer_xy_by_room` set, with each maze's room indices
offset so frozenset / int references stay stable across the
combined graph.

### `WaypointPlanner.plan()` — per-frame resolution order

Called once per frame with the body's current `(sx, sy)` and the
target's `(tx, ty)`.  Returns either a `(wx, wy)` waypoint to
steer toward or `None` (caller falls back to direct chase).

1. **Cooldown bleed** — if the planner is in its post-failure
   cooldown (`_cooldown_t > 0`), tick the timer and return
   `None`.  RETURN_HOME wipes this cooldown each frame so the
   freeze never strands a drone trying to come home.
2. **No-op shortcut** — return `None` immediately when the
   planner has no rooms / graph (caller is outside the Star
   Maze).
3. **Wall-band snap** — `find_room_index(sx, sy)` returns
   `None` when the body sits in the wall thickness band.  If
   the closest room AABB is within `_WALL_BAND_SLACK` (50 px,
   slightly more than the 32 px wall thickness), substitute
   that room as the source.  Without this, drones partially
   clipped into a wall would be misclassified as "outside the
   maze" and routed past the edge.
4. **Target-outside fallback** — if the body has a source room
   but the target's room is `None` (player roamed outside the
   maze), substitute `troom = room_to_exit_room[sroom]` (the
   entrance room of the body's own maze).  The
   geographically-nearest room is often a sealed dead-end; only
   the entrance has an outer opening.  Legacy callers without
   the exit table fall back to the closest room by AABB
   distance.
5. **Body-at-entrance gate** — if the body is in the entrance
   room AND target is outside the maze, emit
   `exit_outer_xy_by_room[sroom]` as the waypoint.  A fixed
   point past the gap means the same waypoint regardless of
   body position, so the body steers continuously through the
   gap into open space.  The earlier "switch to player when
   close to gap" design produced single-frame oscillation.
6. **Body-outside-target-inside entry** — symmetric case: when
   the body is outside every room (and not close enough for the
   wall-band snap to grab it) but the target is inside one, emit
   `exit_xy_by_room[troom]` so the drone heads for the entrance
   gap.  Once it crosses the gap the body's source room snaps
   to the entrance and the rest of the path runs normally.
7. **Same-room early return** — when source and target rooms
   match, return `None` and let the caller chase directly.
   Resets the stuck tracker so the next inter-room plan starts
   with a fresh budget.
8. **A* re-plan** — recompute the path on a `REPLAN_INTERVAL`
   (0.5 s) cadence, on target-room change, or whenever the
   cached path doesn't start in the current source room.
   `astar_room_path` is a plain list-based open set (≤25 rooms
   per maze; `heapq` overhead loses to linear scan at this
   size).
9. **Path trim** — drop already-passed entries until
   `path[0] == sroom`.  Returns `None` when the trimmed path
   has fewer than two entries (body is in the destination
   room).
10. **Stuck-progress tracker** — anchor on first call, then
    measure displacement.  `STUCK_DIST` (30 px) of motion
    within `FAIL_TIMEOUT` (5 s) counts as progress and resets
    the anchor.  No motion for the full window calls
    `_fail()`, which sets the cooldown for `COOLDOWN` (5 s)
    and latches `gave_up()` for one read.
11. **Doorway-arrival path advance** — if the body sits within
    `_DOORWAY_ARRIVAL_RADIUS` (24 px) of the current
    `path[0] ↔ path[1]` doorway midpoint, pop `path[0]` so the
    next call's source is the room we just entered; emit the
    next doorway, or — if only one room remains — its centre
    so the body steps off the wall band into the room
    interior.  Without this, drones parked exactly on a
    doorway midpoint stalled forever (`dist <= 0.001` early-
    return in the drone update loop).
12. **Doorway-aware waypoint** — return the `path[0] ↔ path[1]`
    doorway midpoint.  The doorway sits in the carved gap by
    construction, so straight-line steering from anywhere in
    the current room reaches it without clipping a wall corner.
    Falls back to the next room's centre when no doorway entry
    exists (legacy callers without a doorway table).

### Drone integration — `sprites/drone._BaseDrone`

Per-frame flow inside `update_drone(dt, gv)`:

1. `update_visuals(dt)` + `regen_shields(dt, player)`.
2. `walls = _walls_from_zone(gv)` — current zone's wall list
   (None outside the Star Maze).
3. Pick a target candidate (nearest asteroid for mining drone,
   nearest enemy for combat drone — combat drone gives maze
   spawners priority).
4. `_update_mode(player, target, walls)` resolves the mode in
   this order: **direct RETURN order** (forces RETURN_HOME
   until close + LOS clear) → **direct ATTACK order** (forces
   ATTACK while a target is in range, ignores 800 px break-off)
   → **autonomous RETURN_HOME** at >800 px with hysteresis
   exit at 600 px → **reaction filter** (`"follow"` reaction
   never enters ATTACK) → **distance + LOS check** (ATTACK iff
   target ≤600 px AND no wall on the segment).
5. Branch on the new mode:
   - `RETURN_HOME` → `_run_return_home`: clear the planner's
     cooldown, call `plan()`, steer toward the waypoint (or
     directly at the player if the planner returned `None`),
     ignore enemies entirely, run the un-stick nudge.
   - `FOLLOW` → `follow()`: call `plan()` first to handle
     maze routing; if no waypoint, fall back to the slot
     picker (LEFT default → RIGHT → BACK based on the
     segment-blocked check against `walls`).  Run the un-stick
     nudge after.
   - `ATTACK` → hold station, run `_aim_and_fire(target)` with
     `_track_stuck_progress` to abandon targets the drone
     can't actually reach (5 s of unchanged target HP →
     `_target_cooldown` freeze).

`update_logic.update_drone` calls
`drone.attach_maze_planner(rooms, room_graph, doorways,
room_to_exit_room, exit_xy_by_room, exit_outer_xy_by_room)`
each frame.  An identity check on the room/graph ids skips the
allocation when the geometry hasn't changed (every frame inside
a single zone), so the per-frame cost is one dict lookup +
one comparison.

### Safety nets

The planner is correct in steady state; the safety nets cover
edge cases (pixel-perfect alignment glitches, weird diagonal
geometry, brief simulator perturbations from push-out):

- **Un-stick nudge** (`_BaseDrone._try_unstick_nudge`) — tracks
  per-frame movement; if the drone hasn't moved more than
  10 px in 0.5 s while it should be steering toward a target,
  slides perpendicular to the steering vector for one frame.
  Direction alternates each fire so a corner that blocks the
  right slide gets a left slide on the next attempt.  Hooked
  from both `follow()` and `_run_return_home()`.
- **RETURN_HOME cooldown wipe** — `_run_return_home` resets
  `_follow_planner._cooldown_t = 0` every frame so the
  planner's 5-s give-up freeze never strands a drone trying to
  come back to the player.
- **Direct RETURN clear-on-LOS** — the direct RETURN order
  auto-clears only when the drone is BOTH close to the player
  (within `_DIRECT_RETURN_CLEAR_DIST = 2 * DRONE_FOLLOW_DIST`
  = 160 px) AND has clear line of sight.  Distance alone
  isn't enough — a drone wedged behind a wall at 400 px would
  otherwise lose its order on the first tick.

### Where to look in tests

- `unit tests/test_waypoint_planner.py` — pins every `plan()`
  branch above (no-op cases, doorway-aware waypoint emission,
  wall-band snap, target-outside routing, entrance routing
  both directions, exit-via-outer-point, doorway-arrival path
  advance, no-progress give-up, stuck-timer reset on real
  movement).
- `unit tests/test_drone.py` — slot picker fallback chain,
  mode machine resolution, friendly-fire skip on AI-piloted
  parked ships, LOS disengage, save round-trip including
  reactions + direct orders, hover tooltip text builder,
  stuck-status surfaces in the tooltip.
- `unit tests/test_fleet_menu.py` — Fleet Control button ids,
  `apply_fleet_order` mutations, mode machine respects
  reactions + direct orders.
- `unit tests/integration/test_drone_wall_containment.py` —
  end-to-end against a real Star Maze GameView: drone never
  tunnels through a wall, push-out scoops it free of overlaps.

## View Flow

```
main.py
  --> SplashView
        --> SelectionView --> GameView
        --> OptionsView --> back to SplashView
        --> Load Game --> GameView

GameView overlays:
  +-- EscapeMenu (pauses gameplay)
  +-- DeathScreen (HP = 0)
  +-- Inventory (does NOT pause)
  +-- BuildMenu (does NOT pause)
  +-- StationInventory, CraftMenu, TradeMenu, ShipStats, StationInfo
```
