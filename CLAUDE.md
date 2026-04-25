# Space Survivalcraft — Dev Reference

**Call of Orion** is a top-down Newtonian space survival game built on
Python 3.12 + Arcade 3.3.3. Fly a faction/ship/character combo through
Zone 1 (6400×6400), the Nebula / Zone 2 (9600×9600), and the Star
Maze / Zone 3 (12000×12000), mine asteroids, fight aliens + two bosses
(Double Star + Nebula), build a modular station, upgrade ships, talk
to story NPCs. Stealth via null fields, fast travel via slipspaces,
hard-block via force walls.

## Running

```bash
venv\Scripts\activate.bat        # Windows CMD
source venv/Scripts/activate     # Git Bash
python main.py
python -m pytest "unit tests/" -v
python -m pytest "unit tests/integration/" -v
```

See `README.md` for the feature list, `docs/` for systems/rules/stats,
`ROADMAP.md` for the chronology.

## File structure (cheat sheet)

```
Space Survivalcraft/
├── main.py                  # entry point; patches pyglet clock
├── constants.py             # tuned values + asset paths (sections 1–16)
├── settings.py              # global audio/video/config singleton
├── game_view.py             # thin dispatcher (~940 lines)
├── combat_helpers.py        # damage / spawn / XP / boss
├── building_manager.py      # building placement + trade station
├── ship_manager.py          # ship upgrade / place / switch
├── constants_paths.py       # re-export surface for asset-path constants
├── draw_logic.py            # draw_world / draw_ui / compute_world_stats
├── update_logic.py          # per-frame update phases
├── input_handlers.py        # keyboard + mouse routing
├── game_save.py             # save/load + _restore_sprite_list helper
├── qwi_menu.py              # Quantum Wave Integrator boss-summon menu
├── map_overlay.py           # full-screen map ('M' key)
├── game_music.py            # music/video playback
├── collisions.py            # every collision handler + resolve_overlap/reflect_velocity
├── world_setup.py           # asset loading + asteroid/alien population
├── dialogue_overlay.py      # NPC conversation overlay
├── dialogue/                # Debra/Ellie/Tara refugee trees
├── hud.py, hud_minimap.py, hud_equalizer.py
├── base_inventory.py, inventory.py (5×5), station_inventory.py (10×10)
├── escape_menu/             # escape menu package
├── build_menu.py, craft_menu.py, trade_menu.py, qwi_menu.py
├── station_info.py, ship_stats.py, death_screen.py
├── map_overlay.py           # full-screen map ('M' key)
├── character_data.py        # XP / level / per-character bonuses
├── video_player.py          # FFmpeg video playback
├── menu_scroll.py           # shared ScrollState for build + craft menus
├── sprites/
│   ├── player.py, boss.py, nebula_boss.py
│   ├── alien.py, zone2_aliens.py, alien_ai.py (shared helpers)
│   ├── maze_alien.py, maze_spawner.py
│   ├── asteroid.py, copper_asteroid.py, wandering_asteroid.py
│   ├── pickup.py, shield.py, explosion.py, contrail.py
│   ├── projectile.py, missile.py, building.py
│   ├── force_wall.py, wormhole.py, gas_area.py
│   ├── null_field.py, slipspace.py
│   ├── parked_ship.py       # multi-ship + AI pilot
│   └── npc_ship.py          # RefugeeNPCShip (story encounter)
└── zones/                   # ZoneID, MainZone, Zone2, StarMazeZone,
                             # warp zones (Zone-1 / Nebula / Maze
                             # variants), maze_geometry, nebula_shared
```

## Tests

- **Fast** (`unit tests/`, 906 tests, ~5.5 s) — physics, AI, inventory,
  modules, AI Pilot, refugee/dialogue trees, station shield, Star Maze
  (geometry, A* pathing, MazeAlien/MazeSpawner stats + save round-trip),
  Nebula boss + QWI, null fields, slipspaces, force wall, gas area,
  nebula_shared helpers, ship_manager, dialogue overlay lifecycle,
  shared helpers, save restore, CPU microbenchmarks.
- **Integration** (`unit tests/integration/`, ~309 tests) — real
  GameView flows incl. Star Maze + Nebula boss, full-frame FPS (with /
  without videos, menu scroll, station combat, AI pilot fleets,
  dialogue), GPU render, resolution scaling, soak (5 min each, incl.
  Star Maze idle / combat churn / Nebula pressure). Shared soak
  scaffold in `unit tests/integration/_soak_base.py`.
- `pytest.ini` excludes `integration/` from default runs. Real
  music-video tests look in `./yvideos/*.mp4` (gitignored).

## Load-bearing patterns

### Module extraction + thin dispatcher

Extracted modules live next to `game_view.py` and follow:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from game_view import GameView

def work(gv: GameView, ...): ...
```

`GameView` holds shared state + one-line delegates so external callers
(`collisions.py`, `game_save.py`, tests) stay stable when code moves.

### Zone state machine

`zones/` owns Zone 1 (`MainZone`), Zone 2 (`Zone2`, the Nebula),
Zone 3 (`StarMazeZone`), and three flavours of four-themed warp zones
(meteor / lightning / gas / enemy spawner): the Zone-1 originals,
`NEBULA_WARP_*` variants reached after the Nebula boss with a 2× danger
scalar, and `MAZE_WARP_*` variants reached from the Star Maze with the
same theme rotation. The single `MeteorWarpZone` / `LightningWarpZone`
/ `GasCloudWarpZone` / `EnemySpawnerWarpZone` classes are reused for
all three; `instance.zone_id` distinguishes the variant inside `setup`.

Each `ZoneState` has `setup / teardown / update / draw /
background_update`. `MainZone` stashes Zone 1 lists during excursions.
`Zone2` stashes buildings + trade station + parked ships in
`_building_stash` so warp-zone round trips don't wipe them. `StarMazeZone`
delegates its Nebula-style content (asteroids, gas, wanderers, Z2
aliens, null fields, slipspaces) to `zones/nebula_shared.py`, which
both Zone 2 and Star Maze call into; the shared module keeps drift
between the two zones from re-introducing collision regressions. Star
Maze geometry (room layout, carved corridors, room-adjacency graph,
A* helper, point-in-rect / segment-vs-walls helpers) lives in
`zones/maze_geometry.py`. Shared sprite lists (`gv.alien_list`,
`gv.alien_projectile_list`) swap to the active zone's versions during
its update so reused collision helpers operate on the right entities.

### HUD / overlay draw pattern (shared rect + Text pools)

Every scrollable or dense overlay (`hud.py`, `build_menu.py`,
`craft_menu.py`, `trade_menu.py`) uses the same triplet:

1. **Rect fills via `arcade.SpriteList`** — each overlay owns a
   `_rect_sprites` pool with `_rect_reset` / `_rect_add` / `_rect_flush`
   helpers so N per-frame `draw_rect_filled` calls collapse into one
   `SpriteList.draw`.
2. **Per-row `arcade.Text` pools attached to a shared
   `pyglet.graphics.Batch`** — one `batch.draw()` replaces N
   `Text.draw()` calls; off-viewport rows toggle
   `_label.visible = False` for clipping during scroll.
3. **Guarded `.text` / `.x` / `.y` / `.color` setters** — every
   mutation checks if the value actually changed before firing the
   pyglet setter (which rebuilds the label layout). Colour guards
   normalise to 4-tuples so `arcade.color.Color` / `(r,g,b)` /
   `(r,g,b,a)` comparisons match.

### Modal-video gate

`draw_logic.draw_ui` computes `menu_open` as the OR of every modal
(escape, craft, trade, build, station-inv, qwi, station-info, ship-
stats, dialogue, map). While `menu_open`, the character + music video
`draw_in_hud` calls are skipped — audio/video decode keeps running
but the blit + pixel-readback are the expensive parts and they pause.

### Asteroid / alien AI performance

- `sprites/alien_ai.compute_avoidance` caches a per-frame spatial
  hash of each `asteroid_list` (cell size = avoidance threshold, 0.05
  s TTL via `time.monotonic`). Alien AI only scans the 3×3 block
  around its cell instead of all 180 asteroids.
- `sprites/asteroid.py` + `copper_asteroid.py` skip the
  `center_x = _base_x` self-write while idle — previously triggered
  75 spatial-hash bucket rebuilds per frame on arcade's side.
- Alien position + asteroid position reads cached before the tight
  inner loops.

### GC + sound cleanup cadence

`update_logic.update_preamble`:

- **Every 5 s**: `_cleanup_finished_sounds` (rate-limited to
  `_MAX_DELETES_PER_TICK = 4` so a Player-delete burst can't stall
  150-200 ms) + `gc.collect(0)` (gen-0 only, ~0.1 ms).
- **Every 120 s**: `gc.collect()` full pass. Flight-recorder RSS was
  stable at ~270 MB after 36 s, so the full pass frees ~3 MB per
  run and costing a 60-100 ms spike is priced in.
- There is **no** forced GC when the escape menu opens. The old "it's
  invisible because the frame is paused" heuristic produced a 600 ms
  stall on the fps-drops log.

### Input contracts

- `handle_mouse_press` short-circuits through overlays: death screen,
  dialogue, escape, destroy mode, placement, build, station inv,
  craft, trade, qwi, then world clicks.
- `_handle_world_click` order: refugee NPC → parked ship → trade
  station → Home Station → Basic/Advanced Crafter → QWI.
- `ESC` cascade: trade → craft → qwi → station inv → station info →
  ship stats → **map** → moving/destroy/placement/build/inv → escape
  menu toggle.
- `M` toggles the full-screen map (not while dead or in escape menu).
- Long-press LMB (`MOVE_LONG_PRESS_TIME = 0.4 s`) on Turret / Missile
  Array enters move mode, clamped to `TURRET_FREE_PLACE_RADIUS` of
  the active Home Station.
- Dialogue overlay consumes all keys + mouse while open; digits 1-9
  pick choices, SPACE/ENTER advance, ESC closes without committing
  aftermath flags.

### Projectile despawn

`sprites/projectile.py` gates despawn **only** on `_max_dist` (the
weapon's range). The world-bounds gate was removed — it used Zone 1
coords (`WORLD_WIDTH` / `WORLD_HEIGHT`) and killed every projectile
fired past 6400 in the expanded Nebula. Every projectile type is
already range-capped (basic laser 1200, mining beam 800, broadside
400, alien laser 500, boss cannon 700).

### Force wall

`sprites/force_wall.py` exposes `closest_point`,
`blocks_point(px, py, radius)`, and `segment_crosses(ax, ay, bx, by)`.
`update_logic.update_force_walls` consumes alien + boss projectiles
colliding with any active wall. Every alien class takes a
`force_walls` kwarg and delegates avoidance to
`sprites/alien_ai.compute_avoidance`, which adds a 2× repulsion term
within `ALIEN_RADIUS + ALIEN_AVOIDANCE_RADIUS + 30 px`; any move that
would cross a wall reverts to the pre-move position. The Nebula boss
also routes around walls via the same primitives.

### Star Maze (Zone 3)

`zones/star_maze.py` runs a 12000×12000 zone with `STAR_MAZE_COUNT`
(4) maze structures laid out at the corners + centre via
`STAR_MAZE_CENTERS`. Each maze is a 5×5 room grid (300 px interior,
32 px walls) carved with recursive-backtracking DFS in
`zones/maze_geometry.generate_maze`; the resulting `MazeLayout` carries
`rooms`, `walls`, `room_graph` (adjacency from the carved edges),
`rows`, `cols`, plus the helpers `find_room_index`,
`astar_room_path`, `point_in_rect`, `segment_crosses_walls`. Each room
spawns one `MazeSpawner` (kill = 1000 iron + 100 XP, respawn 90 s)
which periodically (`MAZE_SPAWNER_SPAWN_INTERVAL = 30 s`, cap 20 alive)
emits a `MazeAlien`. Maze aliens take `rooms` + `room_graph` and
A*-plan through the room graph instead of bee-lining; each frame's
move is checked against the wall spatial-hash and reverted if it would
cross. Outside the maze rectangles the zone hosts the same Nebula
content as Zone 2, populated via `nebula_shared.populate_nebula_content`
with radius-aware reject filters that keep entities out of maze AABBs.
Non-maze aliens that drift into a maze get pushed back via
`_push_out_of_maze_bounds`. Misty Step rejects teleports whose path
crosses a wall.

### Nebula Boss + QWI

`sprites/nebula_boss.py` is a separate boss for Zone 2/Star Maze with
gas-cloud + cone attacks. The Quantum Wave Integrator
(`BUILDING_TYPES["Quantum Wave Integrator"]`) is the trigger: building
one in Zone 2 spawns the boss; clicking the QWI within `QWI_PLACE_RADIUS`
opens `qwi_menu.QWIMenu`, which charges `QWI_SPAWN_NEBULA_BOSS_IRON_COST`
(100 iron) per resummon. Boss reward: 3000 iron + 1000 copper. Station
turrets, missile arrays, and AI-piloted parked ships all target +
damage the Nebula boss.

### Null fields + slipspaces

`sprites/null_field.py` are `NULL_FIELD_COUNT` (30/zone) stealth
patches that hide the player from enemies — while inside, AI targeting
treats the player as invisible and `update_logic` toggles
`gv._player_cloaked`. Firing a weapon from inside a field disables the
field for `NULL_FIELD_DISABLE_S` (10 s) and flashes it red. Star Maze
+ Zone 2 maze enemies both honour the cloak (checked in
`_update_maze_aliens` and `_update_spawners`).

`sprites/slipspace.py` portals (15 per non-warp zone) teleport the
player to a paired slipspace and conserve velocity. They render at
160 px display / 60 px collision radius. Persisted in save/load.

### Multi-ship + AI Pilot

`ParkedShip` stores faction/type/level, HP/shields, `cargo_items`,
`module_slots`. `ship_manager._place_new_ship` builds one from the
current player on upgrade; `ship_manager.switch_to_ship` swaps
inventory / modules / weapons / ability meter.
`collisions.handle_parked_ship_damage` routes every projectile type.
Parked ships stash with zones and serialize fully.

Installing `ai_pilot` flips `ParkedShip.has_ai_pilot` on; the parked
ship orbits the station (`"patrol"` mode) until it sees a target,
then flips to pursuit. Shots go to `gv.turret_projectile_list` so the
existing turret-projectile collision handler delivers damage.

### Station shield + AI yellow shield

`update_logic.update_station_shield` spawns a faction-tinted
`ShieldSprite` over the Home Station while a `Shield Generator`
exists. `collisions._station_shield_absorbs` bleeds `proj.damage`
off `gv._station_shield_hp` for any alien + boss projectile inside
the disk before building collision runs. AI-piloted parked ships
attach their own yellow `ShieldSprite` lazily and regen at 0.5× the
ship's base `shield_regen`. `ShieldSprite(alpha=...)` lets each
shield pick its opacity — ship + AI pilot use 200, station uses 15.

### Blueprints + module icons

Every `MODULE_TYPES[key]["icon"]` texture serves three purposes:

1. The recipe icon in the Basic / Advanced Crafter menus.
2. The inventory `mod_{key}` cell icon.
3. The spinning **world-drop** sprite — populated into
   `game_view._blueprint_drop_tex[key]` during
   `_init_inventory_and_tip` and consumed by
   `combat_helpers.spawn_blueprint_pickup` +
   `collisions._destroy_parked_ship`. `BlueprintPickup.__init__`
   auto-scales each drop to a 40 px target so icons of wildly
   different native sizes all render at the same on-screen size.

The legacy tinted `BLUEPRINT_PNG` still backs the inventory `bp_{key}`
cell icon for now.

### Respawn on death

`combat_helpers.trigger_player_death` no longer ends the game.  It
drops every cargo stack + equipped module + quick-use consumable at
the death site (`_drop_player_loadout` reuses `_drop_scatter` from
`collisions.py` so they ring around the wreckage), flags both bosses
to retreat (`boss._patrol_home = True` — overrides `_target_x/_y`
to `boss._spawn_x/_spawn_y` until the player is back inside
`_PLAYER_PRIORITY_RANGE`), and resets every alien across every zone
(active list + `_main_zone._stash` + `_zone2._building_stash` +
`_star_maze`) to `_STATE_PATROL` with a fresh patrol target.

After the existing 1.5 s death animation, `update_logic.update_death_state`
calls `combat_helpers.respawn_player`:

1. **Soft respawn** — `gv._last_station_pos` (set on Home Station
   click in `input_handlers._handle_world_click`) points at a still-
   standing Home Station: teleport there with 50 % HP / 50 % shields,
   transitioning zones via `_transition_zone` if needed.  Inventory,
   modules, level, XP all preserved.
2. **Hard reset** — no Home Station survives in any zone: build a
   fresh L1 `PlayerShip` of `gv._faction` / `gv._ship_type` at Zone 1
   centre with 25 % HP / 0 shields, roll back `_ship_level`,
   `_char_xp`, `_char_level`, `_ability_meter*`, `_module_slots`,
   reload weapons.  `_last_station_pos / _zone` clear.

The legacy `DeathScreen` is no longer triggered — respawn is
automatic.  The screen still exists for future Game Over use but is
unreachable through normal play.

### Story NPC + dialogue

Building a `Shield Generator` in Zone 2 triggers
`update_logic.update_refugee_npc`, which spawns `RefugeeNPCShip` on
the right edge and parks it outside the station's outer radius.
Clicking within `NPC_REFUGEE_INTERACT_DIST` calls
`DialogueOverlay.start(tree, aftermath_sink=gv._quest_flags)` with
`dialogue.get_refugee_tree(audio.character_name)`. Tree nodes hold
`speaker / text / stage` plus one of `choices / next / end` (with
optional `aftermath` dict of quest flags). Save/load persists
`gv._refugee_spawned`, `gv._met_refugee`, `gv._refugee_npc` pose,
and `gv._quest_flags`.

### Save-restore helpers

`game_save._restore_sprite_list(target_list, entries, factory)` wipes
the target list and rebuilds it via a per-entry factory closure;
factory returns `None` to skip. A codec-pair documentation block at
the top of `game_save.py` lists each serialize/restore pair so field
drift between them is caught at review time.

### Shared refactor helpers

- `collisions._hit_player_on_cooldown(gv, damage, volume, cooldown,
  shake)` consolidates the cooldown + damage + sound + shake pattern.
- `sprites/alien_ai.py` owns `pick_patrol_target`,
  `compute_avoidance`, `segment_crosses_any_wall`.
- `menu_scroll.ScrollState` is shared between `build_menu` and
  `craft_menu`.
- `escape_menu/_ui.draw_button(rect, text_obj, label, fill, outline)`
  replaces the repeated button-rendering pattern.
- `constants_paths.py` re-exports just the asset-path constants for
  callers that don't need gameplay tunables.
- `unit tests/integration/_soak_base.py` hosts `run_soak` plus the
  `SOAK_DURATION_S` / `MIN_FPS` / `MAX_MEMORY_GROWTH_MB` thresholds.

### Character progression

`character_data.py` holds XP thresholds (10 levels, cap 1000 XP),
per-character `level_for_xp`, and bonus helpers. Debra gets bonus
iron/copper on kills; Ellie gets laser upgrades; Tara gets crafting
discounts. Weapons reload on level-up. Ship Stats overlay (`C` key)
reads all bonuses live.

### Saves

`game_save.save_to_dict` + `load_game`. Zone 1 + Zone 2 state saved
independently (even when the player is in a different zone via the
stash). Fog of war, boss state, parked ships, trade credits, trade
station position, refugee NPC, quest flags, station shield HP all
persisted.

## Asset sources

See `docs/README.md` (Asset Sources) for the full licensed-pack list.
All asset files live under `assets/` (gitignored), plus
`characters/*.mp4` (character videos, gitignored) and
`yvideos/*.mp4` (test music videos, gitignored).
