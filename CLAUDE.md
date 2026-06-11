# Space Survivalcraft — Dev Reference

**Call of Orion**: top-down Newtonian space survival on
Python 3.12 + Arcade 3.3.3.  Three main zones (Zone 1 / Nebula
/ Star Maze), 12 themed warp zones, two bosses, modular
station, companion drones, multi-ship + AI Pilot, story NPC
+ dialogue, per-faction lightsabre melee.

For everything detailed see `docs/`:

| Doc | What's in it |
|---|---|
| `docs/features.md` | Player-facing feature list |
| `docs/statistics.md` | Tuned numbers (HP, dmg, speeds, costs) |
| `docs/rules.md` | Collision + damage + AI + Star Maze rules |
| `docs/controls.md` | Keyboard / mouse / gamepad / menu nav |
| `docs/architecture.md` | Module map, design patterns, dependency graph |
| `docs/bot.md` | Bot stack (API, autopilot, combat assist) |
| `docs/lore.md` | Factions, characters, story |

`README.md` is the player-facing intro.  `ROADMAP.md` is the
chronology.

## Running

```bash
venv\Scripts\activate.bat        # Windows CMD
source venv/Scripts/activate     # Git Bash
python main.py
python -m pytest "unit tests/"                  # fast suite
python -m pytest "unit tests/integration/"      # slow suite (real arcade window)
```

`pytest.ini` excludes `integration/` from default runs.  Tests
share an `arcade_window` autouse fixture in
`unit tests/conftest.py` (module-scoped).

## File map

```
Space Survivalcraft/
├── main.py                  # entry point
├── constants.py             # tuned values + asset paths
├── settings.py              # global audio/video/config singleton
├── game_view.py             # GameView -- thin dispatcher
├── update_logic.py          # per-frame update phases (orchestrator)
├── update_audio.py          # play-sound monkey-patch + finished-player sweep
├── update_blade.py          # lightsabre / pickaxe blade ensure + AOE
├── update_boss.py           # Zone 1 boss + Nebula boss per-frame update
├── draw_logic.py            # per-frame draw phases
├── input_handlers.py        # keyboard + mouse routing
├── collisions.py            # every collision handler
├── combat_helpers.py        # damage / spawn / XP / boss / drone / fleet
├── building_manager.py      # building placement + trade station
├── ship_manager.py          # ship upgrade / place / switch
├── world_setup.py           # asset loading + asteroid/alien population
├── game_save.py             # save/load + codec-pair docblock
├── game_music.py            # OST + music-video playback
├── video_player.py          # ffmpeg-backed video decoder
├── character_data.py        # XP / level / per-character bonuses
│
├── hud.py + hud_minimap.py + hud_equalizer.py
├── base_inventory.py + inventory.py (5x5) + station_inventory.py (10x10)
├── build_menu.py + craft_menu.py + trade_menu.py + qwi_menu.py
├── fleet_menu.py + map_overlay.py + station_info.py + ship_stats.py
├── escape_menu/             # main / save / load / video / songs / help / config / video_props
├── dialogue_overlay.py + dialogue/   # Debra / Ellie / Tara refugee trees
├── splash_view.py + selection_view.py + options_view.py + death_screen.py
│
├── menu_scroll.py           # shared ScrollState (build + craft)
├── ui_helpers.py            # draw_button / draw_load_slot
├── specs.py                 # frozen-dataclass enemy / drone stats
├── constants_paths.py       # asset-path-only re-exports
│
├── sprites/
│   ├── player.py, boss.py, nebula_boss.py
│   ├── alien.py, zone2_aliens.py, alien_ai.py (PatrolPursueMixin)
│   ├── maze_alien.py, maze_spawner.py, stalker.py
│   ├── asteroid.py, copper_asteroid.py, wandering_asteroid.py
│   ├── pickup.py, shield.py, explosion.py, contrail.py
│   ├── projectile.py, missile.py, building.py
│   ├── force_wall.py, wormhole.py, gas_area.py
│   ├── null_field.py, slipspace.py
│   ├── drone.py             # re-export shim (MiningDrone + CombatDrone + helpers)
│   ├── drone_base.py        # _BaseDrone + WaypointPlanner client + tooltip helpers
│   ├── drone_mining.py      # MiningDrone
│   ├── drone_combat.py      # CombatDrone
│   ├── parked_ship.py       # multi-ship + AI pilot
│   ├── melee.py             # MeleeBlade -- per-faction lightsabre
│   ├── npc_ship.py          # RefugeeNPCShip
│   ├── planet.py            # landable Planet world object (planets P1)
│   ├── landing_enemy.py     # Sky Worm / Cloud Drone / Thunder Worm (planets P1)
│   └── resource_node.py     # surface rock/copper/silicon nodes (planets P2)
│
├── zones/                   # MainZone, Zone2, StarMazeZone, warp variants
│   ├── maze_geometry.py     # rooms + A* + WaypointPlanner
│   ├── nebula_shared.py     # content shared by Zone 2 + Star Maze
│   ├── star_maze_walls.py   # wall sprite build + 7 wall-collision helpers
│   ├── star_maze_spawning.py # maze gen + entourage / stalker / spawner helpers
│   ├── zone_planetary_landing.py # aerial descent scene (planets P1)
│   └── zone_planetary_surface.py # on-foot surface scene (planets P2)
│
├── bot_autopilot.py                  # FSM orchestrator + state
├── bot_autopilot_actions_combat.py   # combat _act_* handlers
├── bot_autopilot_actions_station.py  # station _act_* handlers
├── bot_autopilot_movement.py         # _do_* movement helpers
├── bot_autopilot_targeting.py        # selectors, blacklists, station info
├── bot_autopilot_http.py             # HTTP client + window focus
├── bot_autopilot_navigation.py       # potential field, escape, geometry
├── bot_autopilot_blacklist.py        # pickup/asteroid blacklist core
├── bot_autopilot_telemetry.py        # JSONL writer + snapshot
└── bot_api.py + bot_combat_assist.py + bot_builder.py + bot_kickoff.py
```

## Tests

Roughly 1335 fast + 470 integration.  See `docs/architecture.md`
for the testing-infrastructure details (soak scaffold,
performance threshold patterns, etc).

## Load-bearing patterns (one-liners — full detail in `docs/architecture.md`)

* **Module extraction + thin dispatcher** -- `GameView` holds
  state + one-line delegates; helpers live next to it and take
  `gv` as first arg with `if TYPE_CHECKING` import.
* **Zone state machine** -- each `ZoneState` exposes
  `setup / teardown / update / draw / background_update`.
  Zone 2 + Star Maze stash buildings + parked ships in
  `_building_stash` so warp-zone round trips don't wipe them.
  `StarMazeZone` delegates Nebula content to
  `zones/nebula_shared.py`.  Geometry in `zones/maze_geometry.py`.
* **HUD / overlay draw triplet** -- pooled rect SpriteList +
  `arcade.Text` pool on shared `pyglet.graphics.Batch` +
  guarded compare-before-write setters.
* **Modal-video gate** -- `draw_logic.draw_ui` skips video
  blits while any modal is open (the blit + readback are the
  expensive part).
* **GC + sound cleanup cadence** -- 5 s `gc.collect(0)` +
  `_cleanup_finished_sounds` (with 200-entry tracking cap),
  60 s gen-1 sweep.  Soak FPS collapsed without the cap.
* **Drone mode machine + maze pathfinding** --
  `_BaseDrone._mode` (FOLLOW / ATTACK / RETURN_HOME) +
  `_reaction` + `_direct_order`.  `WaypointPlanner` in
  `zones/maze_geometry.py` is the per-body A* + safety nets.
* **Star Maze multi-list turret targeting** --
  `StarMazeZone._turret_extra_target_lists` exposes
  `(_stalkers, _aliens)` so turrets see every enemy without
  per-frame SpriteList allocation (the previous cached-list
  design leaked ~15 KB / frame and tanked soaks; pinned by
  `test_star_maze_turret_targets.py`).
* **Per-faction lightsabre melee** --
  `MELEE_SWORD_PNG_BY_FACTION` chooses the sprite;
  `world_setup.load_weapons(gun_count, faction=...)` threads
  the choice; `MeleeBlade` in `sprites/melee.py` swings -75°
  -> +75° around a fixed handle pivot.
* **Multi-ship + AI Pilot** -- `ParkedShip` stores faction /
  type / level / HP / shields / cargo / modules.
  `ship_manager.switch_to_ship` swaps everything.  AI Pilot
  module flips `has_ai_pilot` so the parked ship orbits and
  fires through `gv.turret_projectile_list` (friendly-fire
  immune).
* **Bot stack** -- `bot_api.py` exposes `/state` + `/intent`;
  `bot_combat_assist.py` monkey-patches `update_weapons` for
  reflex aim + fire; `bot_autopilot.py` polls /state at 10 Hz
  and dispatches keystrokes.  `bot_kickoff.py` wires it all
  up.  Full guide: `docs/bot.md`.
* **Bot autopilot helper-module split** -- the orchestrator
  (`bot_autopilot.py`) holds constants + `BotState` + FSM
  (`_choose_next_state` / `_on_enter` / `_do_auto`) + `main`.
  Topical helpers (`bot_autopilot_http`, `_targeting`,
  `_movement`, `_actions_station`, `_actions_combat`) each
  `import bot_autopilot as _ap` and qualify cross-references
  as `_ap.X` so test-time monkey-patching of `_ap` symbols
  still threads through.  The orchestrator re-exports every
  moved symbol at the bottom so `bot_autopilot.X` imports
  stay valid.
* **Class-method delegate pattern (StarMazeZone)** -- large
  class methods extracted to module-level functions in
  `zones/star_maze_walls.py` (wall build + 7 collision
  helpers) and `zones/star_maze_spawning.py` (maze gen +
  entourage / stalker / spawner helpers).  The class methods
  stay defined as one-line delegates calling the helper with
  `self` as first arg, so external callers still see methods
  on the class.
* **`sprites/drone.py` re-export shim** -- 44-line shim that
  re-exports `_BaseDrone` (`drone_base.py`), `MiningDrone`
  (`drone_mining.py`), `CombatDrone` (`drone_combat.py`), and
  the tooltip helpers, so existing
  `from sprites.drone import MiningDrone` imports keep
  working after the split.
* **Planets: reach -> descend -> surface** -- two implemented
  slices of `docs/planets.md`.  Phase 1 (reach + descend):
  `Planet` colliders in the Star Maze, the `planetary_landing`
  ship module gate (`StarMazeZone._update_planet_contact`),
  and `PlanetaryLandingZone(WarpZoneBase)` -- a warp-zone-sized
  aerial scene with 60 airborne `LandingEnemy`s.  Phase 2
  (on-foot surface): `PlanetarySurfaceZone` reached from the
  landing top edge.  The on-foot character **reuses
  `gv.player`** via a mode switch -- `setup` stashes ship
  state and flips `gv._on_foot` (surface texture, `armor`,
  no shields, rifle + mining beam, `guns=1`); `teardown`
  restores it.  `update_logic.update_movement` branches to
  `PlayerShip.apply_input_on_foot` (direct WASD 250 px/s) and
  `combat_helpers.apply_damage_to_player` subtracts the flat
  `armor` first.  Resource nodes mined by `mines_rock`
  projectiles yield iron/copper/silicon.  Deferred to later
  phases: surface enemies, melee arsenal, base-building,
  blueprints, L11-30 progression, Ellie/Tara surface art.

## Asset sources

See `docs/README.md` (Asset Sources) for the licensed-pack list.
All `assets/`, `characters/*.mp4`, `yvideos/*.mp4`, and
`bot_io/` are gitignored.
