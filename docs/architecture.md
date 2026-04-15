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
| `draw_logic.py` | ~390 | `draw_world()`, `draw_ui()`, `compute_world_stats()` |
| `update_logic.py` | ~570 | 11 update sub-functions for the game loop |
| `input_handlers.py` | ~690 | All keyboard and mouse event handling; eject routing split into 4 helpers |
| `game_save.py` | ~690 | Save/load serialization with `_restore_sprite_list` factory helper |
| `game_music.py` | — | Music playlist, video playback management |
| `collisions.py` | ~490 | All collision handlers + `resolve_overlap` / `reflect_velocity` physics primitives |
| `zones/` | — | Zone state management, warp zone logic, Zone 2 setup and hazards |

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
- **Test infrastructure** --- `pytest.ini` excludes `integration/`; `conftest.py` provides `StubPlayer` and `StubGameView` for windowless zone testing; `psutil` dev dependency for soak tests; 469 fast + 131 integration = 600 total tests. Integration covers functional, FPS (trade panels × {Zone 1, Zone 2} × {no video, both videos}, buy↔sell churn, AI Pilot fleets with/without videos, refugee NPC spawn + dialogue, patrol/return integration), GPU render, resolution scaling (6 presets × 2 zones), and soak/endurance (5 min each; AI pilot patrol cycle, AI pilot idle orbit, dialogue spine walk, dialogue exhaustive branch rotation, character rotation). Real music-video tests load `./yvideos/*.mp4` (gitignored)
- **EqualizerState class** --- encapsulates equalizer animation with `update(dt, volume)` and `draw(y)`
- **MenuContext + MenuMode** --- escape menu sub-mode pattern with shared state and per-mode draw/input
- **TYPE_CHECKING imports** --- all extracted modules avoid circular imports at runtime
- **Zone state machine** --- `zones/` package manages transitions between Zone 1, warp zones, and Zone 2; each zone has its own asteroid/alien populations, hazard rules, and background; GameView delegates zone-specific setup and update logic to the active zone state
- **Viewport culling (update only)** --- Zone 2 only updates asteroid/wanderer/gas sprites within camera bounds + 250 px margin (gas areas get +200 px extra); offscreen wanderers spin-only. Drawing uses direct `SpriteList.draw()` calls on the static lists rather than per-frame visibility rebuild --- the static VBOs upload once and the renderer handles offscreen culling efficiently.
- **Ranged alien standoff AI** --- gun-equipped aliens orbit at `ALIEN_STANDOFF_DIST` (300 px) with random CW/CCW direction; RammerAlien charges directly (`has_guns=False`)
- **Turret target caching** --- `Turret._cached_target` and `_target_rescan_cd` (0.25 s) avoid scanning all aliens every frame; cached target validated cheaply (alive + in range); full rescan 4x/s
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
- **Story NPC + dialogue tree** --- `update_logic.update_refugee_npc` watches for the first `Shield Generator` while the player is in Zone 2, spawns `RefugeeNPCShip` on the right edge, retargets it at the Home Station each frame, and hands off to `update_npc` for the approach. `input_handlers._handle_world_click` opens `DialogueOverlay.start(tree, aftermath_sink=gv._quest_flags)` when the player clicks the ship within `NPC_REFUGEE_INTERACT_DIST`. Trees live in `dialogue/*.py` as dicts keyed by node id with `speaker`, `text`, optional `stage`, and one of `choices` / `next` / `end`. Terminal `end` nodes merge an `aftermath` dict into the sink (e.g. Debra's "find_ken" quest flag). Persisted state: `gv._refugee_spawned`, `gv._met_refugee`, `gv._refugee_npc` pose, `gv._quest_flags`.

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
