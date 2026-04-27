# Space Survivalcraft — Dev Reference

**Call of Orion** is a top-down Newtonian space survival game built on
Python 3.12 + Arcade 3.3.3.  Three main zones (Zone 1 / Nebula /
Star Maze), 12 themed warp zones, two bosses, modular station,
companion drones, multi-ship + AI Pilot, story NPC + dialogue.

See `README.md` for the player-facing feature list, `docs/` for
gameplay systems / rules / stats / controls, `ROADMAP.md` for the
chronology.

## Running

```bash
venv\Scripts\activate.bat        # Windows CMD
source venv/Scripts/activate     # Git Bash
python main.py
python -m pytest "unit tests/" -v
python -m pytest "unit tests/integration/" -v
```

## File structure (cheat sheet)

```
Space Survivalcraft/
├── main.py                  # entry point; patches pyglet clock
├── constants.py             # tuned values + asset paths (sections 1–16)
├── settings.py              # global audio/video/config singleton
├── game_view.py             # thin dispatcher
├── combat_helpers.py        # damage / spawn / XP / boss / drone / fleet
├── building_manager.py      # building placement + trade station
├── ship_manager.py          # ship upgrade / place / switch
├── draw_logic.py            # draw_world / draw_ui / compute_world_stats
├── update_logic.py          # per-frame update phases
├── input_handlers.py        # keyboard + mouse routing
├── game_save.py             # save/load + _restore_sprite_list helper
├── collisions.py            # every collision handler
├── world_setup.py           # asset loading + asteroid/alien population
├── qwi_menu.py              # Quantum Wave Integrator overlay
├── fleet_menu.py            # Fleet Control overlay (Y key)
├── map_overlay.py           # full-screen map (M key)
├── dialogue_overlay.py      # NPC conversation overlay
├── dialogue/                # Debra/Ellie/Tara refugee trees
├── hud.py, hud_minimap.py, hud_equalizer.py
├── base_inventory.py, inventory.py (5×5), station_inventory.py (10×10)
├── escape_menu/             # escape menu package
├── build_menu.py, craft_menu.py, trade_menu.py
├── station_info.py, ship_stats.py, death_screen.py
├── character_data.py        # XP / level / per-character bonuses
├── video_player.py, game_music.py
├── menu_scroll.py           # shared ScrollState for build + craft menus
├── specs.py                 # frozen-dataclass enemy / drone stat bundles
├── sprites/
│   ├── player.py, boss.py, nebula_boss.py
│   ├── alien.py, zone2_aliens.py, alien_ai.py (PatrolPursueMixin)
│   ├── maze_alien.py, maze_spawner.py, stalker.py
│   ├── asteroid.py, copper_asteroid.py, wandering_asteroid.py
│   ├── pickup.py, shield.py, explosion.py, contrail.py
│   ├── projectile.py, missile.py, building.py
│   ├── force_wall.py, wormhole.py, gas_area.py
│   ├── null_field.py, slipspace.py
│   ├── drone.py             # MiningDrone + CombatDrone + WaypointPlanner client
│   ├── parked_ship.py       # multi-ship + AI pilot
│   └── npc_ship.py          # RefugeeNPCShip (story encounter)
└── zones/                   # ZoneID, MainZone, Zone2, StarMazeZone,
                             # warp zones (Zone-1 / Nebula / Maze
                             # variants), maze_geometry (rooms + A*
                             # + WaypointPlanner), nebula_shared
```

## Tests

- **Fast** (`unit tests/`, ~1150 tests, ~25 s) — physics, AI, inventory,
  modules, AI Pilot, refugee/dialogue trees, station shield, Star Maze
  (geometry, A* pathing + WaypointPlanner contract, MazeAlien /
  MazeSpawner stats + save round-trip), companion drones (slot pick,
  mode machine, LOS disengage, spawner priority, stack 100 + save),
  Fleet Control menu, Nebula boss + QWI, null fields, slipspaces,
  force wall, gas area, nebula_shared helpers, ship_manager, dialogue
  overlay lifecycle, save restore, CPU microbenchmarks.
- **Integration** (`unit tests/integration/`, ~378 tests) — real
  GameView flows, full-frame FPS, drone wall containment, GPU render,
  resolution scaling, soak (5 min each, scaffold in
  `unit tests/integration/_soak_base.py`).
- `pytest.ini` excludes `integration/` from default runs.  Real
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
Zone 3 (`StarMazeZone`), and three flavours of four-themed warp
zones (Zone-1 originals, `NEBULA_WARP_*`, `MAZE_WARP_*`).
`instance.zone_id` distinguishes the variant inside `setup`.

Each `ZoneState` has `setup / teardown / update / draw /
background_update`.  Zone 2 + Star Maze stash buildings + parked
ships in `_building_stash` so warp-zone round trips don't wipe them.
`StarMazeZone` delegates Nebula-style content (asteroids, gas,
wanderers, Z2 aliens, null fields, slipspaces) to
`zones/nebula_shared.py`.  Star Maze geometry (rooms, walls,
room_graph + doorways + entrance, A* helper, WaypointPlanner) lives
in `zones/maze_geometry.py`.  Shared sprite lists swap to the active
zone's versions during update.

### HUD / overlay draw pattern

Every dense overlay (`hud.py`, `build_menu.py`, `craft_menu.py`,
`trade_menu.py`) uses the same triplet: rect fills via a pooled
`arcade.SpriteList`, per-row `arcade.Text` pools attached to a
shared `pyglet.graphics.Batch`, and guarded `.text` / `.x` / `.y`
/ `.color` setters that compare-before-write to dodge pyglet's
layout rebuild.

### Modal-video gate

`draw_logic.draw_ui` computes `menu_open` as the OR of every modal
(escape, craft, trade, build, station-inv, qwi, fleet, station-info,
ship-stats, dialogue, map).  While `menu_open`, the character +
music video `draw_in_hud` calls are skipped — the blit + pixel
readback are the expensive parts.

### GC + sound cleanup cadence

`update_logic.update_preamble`:

- **Every 5 s**: `_cleanup_finished_sounds` (pyglet Player drain) +
  `gc.collect(0)`.  Cleanup scales per-tick deletes with backlog
  (4 / 12 / 32) AND `_tracked_play_sound` hard-caps the tracking
  list at 200 entries with synchronous oldest-eviction — without
  the cap, dead Players accumulated faster than cleanup could
  drain and combat soaks collapsed from 178 → 2 FPS.
- **Every 60 s**: `gc.collect(1)` (gen-1 sweep).  Replaces the old
  120-s gen-2 pass that produced 50 ms spikes.

### Input contracts

- `handle_mouse_press` short-circuits through overlays: death
  screen, dialogue, escape, destroy mode, placement, build, station
  inv, craft, trade, qwi, fleet, then world clicks.
- `_handle_world_click` order: refugee NPC → parked ship → trade
  station → Home Station → Basic / Advanced Crafter → QWI.
- `ESC` cascade: trade → craft → qwi → fleet → station inv →
  station info → ship stats → map → moving / destroy / placement
  / build / inv → escape menu toggle.
- Hotkeys: `M` map, `R` deploy drone (variant from active weapon),
  `Shift+R` recall drone (refunds 1 charge), `Y` Fleet Control.
  Long-press LMB on Turret / Missile Array enters move mode,
  clamped to `TURRET_FREE_PLACE_RADIUS` of the Home Station.

### Drone mode machine + maze pathfinding

`sprites/drone._BaseDrone` carries `_mode` (FOLLOW / ATTACK /
RETURN_HOME), `_reaction` ("attack" / "follow"), and `_direct_order`
(None / "return" / "attack").  `_update_mode` runs orders →
RETURN_HOME hysteresis → reaction → distance / LOS checks each
frame.  Slot picker (LEFT default, RIGHT / BACK fallback) reads
the active zone's wall list via `_walls_from_zone`.

`zones/maze_geometry.WaypointPlanner` is the shared per-body
pathfinder over the room graph: doorway-midpoint waypoints,
wall-band snap (50 px slack), doorway-arrival path advance,
target-outside → route via `entrance_room`, exit branch emits
`entrance_xy_outer` (a fixed point past the gap, kills the
oscillation), entry branch emits `entrance_xy` for body-outside
+ target-inside.  5 s no-progress timer fires `gave_up()`;
RETURN_HOME wipes the planner cooldown each frame so it never
freezes.  An un-stick perpendicular nudge in `_BaseDrone` slides
the body sideways for one frame after 0.5 s of no displacement
as the safety net.

### Fleet Control menu

`fleet_menu.FleetMenu` (Y key) is a four-button modal — RETURN,
ATTACK (direct orders), FOLLOW ONLY, ATTACK ONLY (reactions).
Buttons return string ids consumed by
`combat_helpers.apply_fleet_order`, which mutates the active
drone's `_reaction` / `_direct_order`.  Direct orders override
reactions until cleared (RETURN clears only on close + LOS,
ATTACK persists until replaced).  Reactions + standing orders
round-trip through `_serialize_active_drone` /
`_restore_active_drone` in `game_save.py`.

### Force wall

`sprites/force_wall.py` exposes `closest_point`,
`blocks_point(px, py, radius)`, and `segment_crosses(ax, ay, bx,
by)`.  Aliens delegate avoidance to
`sprites/alien_ai.compute_avoidance`; any move that would cross a
wall reverts to pre-move.  The Nebula boss also routes around
walls via the same primitives.

### Star Maze

`zones/star_maze.py` runs a 12000×12000 zone with `STAR_MAZE_COUNT`
(4) maze structures via `STAR_MAZE_CENTERS`.  Each maze is a 5×5
room grid (300 px interior, 32 px walls), recursive-backtracker
DFS-carved.  `MazeLayout` carries `rooms`, `walls`, `room_graph`,
`doorways` (per-edge midpoints), `entrance_room` + `entrance_xy`
+ `entrance_xy_outer`.  Each room hosts a `MazeSpawner` (kill =
1000 iron + 100 XP, respawn 90 s) that drips `MazeAlien` enemies
(A*-routed via `WaypointPlanner`).  Outside the mazes the zone
hosts Nebula content via `nebula_shared.populate_nebula_content`.

### Nebula Boss + QWI

`sprites/nebula_boss.py` is a separate boss for Zone 2 / Star
Maze with gas-cloud + cone attacks.  `BUILDING_TYPES["Quantum
Wave Integrator"]` triggers it; clicking the QWI within
`QWI_PLACE_RADIUS` opens `qwi_menu.QWIMenu` (100 iron per
resummon).  Reward: 3000 iron + 1000 copper.  Turrets, missile
arrays, and AI-piloted parked ships all damage the Nebula boss.

### Multi-ship + AI Pilot

`ParkedShip` stores faction / type / level, HP / shields,
`cargo_items`, `module_slots`.  `ship_manager._place_new_ship`
builds one from the current player on upgrade;
`ship_manager.switch_to_ship` swaps inventory / modules / weapons /
ability meter.  `collisions.handle_parked_ship_damage` routes
every projectile type — but skips player projectiles when
`has_ai_pilot` is True (friendly-fire immunity).  Parked ships
stash with zones and serialize fully.

Installing `ai_pilot` flips `ParkedShip.has_ai_pilot` on; the
parked ship orbits the station until it sees a target, then
flips to pursuit.  Shots route to `gv.turret_projectile_list`.

### Station shield + AI yellow shield

`update_logic.update_station_shield` spawns a faction-tinted
`ShieldSprite` over the Home Station while a `Shield Generator`
exists.  `collisions._station_shield_absorbs` bleeds
`proj.damage` off `gv._station_shield_hp` for any alien + boss
projectile inside the disk.  AI-piloted parked ships attach
their own yellow `ShieldSprite` lazily (alpha 200) and regen at
0.5× the ship's base rate.

### Respawn on death

`combat_helpers.trigger_player_death` no longer ends the game —
drops every cargo stack + module + quick-use consumable at the
death site, flags both bosses to retreat, resets every alien
across every zone to PATROL.  After the 1.5 s death animation
`combat_helpers.respawn_player` does either soft (last visited
Home Station, 50 % HP / 50 % shields, inventory preserved) or
hard (fresh L1 ship at Zone 1 centre, 25 % HP / 0 shields,
progression rolled back).  Legacy `DeathScreen` no longer
triggers.

### Saves

`game_save.save_to_dict` + `load_game`.  Zone 1 / Zone 2 / Star
Maze state saved independently (even when the player is in
another zone via the stash).  Active drone, parked ships, fog of
war, boss state, trade credits + station position, refugee NPC,
quest flags, station shield HP all persisted.  A codec-pair
documentation block at the top of `game_save.py` lists each
serialize / restore pair so field drift is caught at review time.

### Shared refactor helpers

- `collisions._hit_player_on_cooldown(gv, damage, volume,
  cooldown, shake)` consolidates the cooldown + damage + sound +
  shake pattern.
- `sprites/alien_ai.py` owns `pick_patrol_target`,
  `compute_avoidance`, `segment_crosses_any_wall`, plus
  `PatrolPursueMixin` adopted by every "small ship" enemy.
- `menu_scroll.ScrollState` shared between build + craft menus.
- `escape_menu/_ui.draw_button(...)` centralises button drawing.
- `constants_paths.py` re-exports just the asset-path constants.
- `unit tests/integration/_soak_base.py` hosts `run_soak` plus the
  `SOAK_DURATION_S` / `MIN_FPS` / `MAX_MEMORY_GROWTH_MB`
  thresholds.
- `specs.py` bundles drone / stalker / maze-alien stats as frozen
  dataclasses for one canonical source.

## Asset sources

See `docs/README.md` (Asset Sources) for the full licensed-pack
list.  All asset files live under `assets/` (gitignored), plus
`characters/*.mp4` (gitignored) and `yvideos/*.mp4` (gitignored).
