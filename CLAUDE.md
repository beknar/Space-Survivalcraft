# Space Survivalcraft — Dev Reference

**Call of Orion** is a top-down Newtonian space survival game built on
Python 3.12 + Arcade 3.3.3. Fly a faction/ship/character combo through
a 6,400×6,400 Zone 1 and a Nebula (Zone 2), mine asteroids, fight
aliens, build a modular station, upgrade ships, talk to story NPCs.

## Running

```bash
venv\Scripts\activate.bat        # Windows CMD
source venv/Scripts/activate     # Git Bash
python main.py
python -m pytest "unit tests/" -v
python -m pytest "unit tests/integration/" -v
```

See `README.md` for the feature list, `docs/` for systems/rules/stats,
`ROADMAP.md` for the chronology, and `debra-conversation-tree1.txt`
for the NPC dialogue spec.

## File Structure (cheat sheet)

```
Space Survivalcraft/
├── main.py                # entry point; patches pyglet clock
├── constants.py           # 16 sections of tuned values
├── settings.py            # global audio/video/config singleton
├── game_view.py           # thin dispatcher (~830 lines, 13 init helpers)
├── combat_helpers.py      # damage, spawn, respawn, XP, boss
├── building_manager.py    # building placement + trade station
├── ship_manager.py        # ship upgrade/place/switch (re-exported via building_manager)
├── constants_paths.py     # re-export surface for just the asset-path constants
├── draw_logic.py          # draw_world / draw_ui / compute_world_stats
├── update_logic.py        # 11 update phases + AI pilot + refugee NPC spawn
├── input_handlers.py      # keyboard + mouse routing
├── game_save.py           # save/load with _restore_sprite_list helper
├── game_music.py          # music/video playback
├── collisions.py          # all collision handlers + resolve_overlap/reflect_velocity
├── world_setup.py         # asset loading + asteroid/alien population + music tracks
├── dialogue_overlay.py    # NPC conversation overlay
├── dialogue/              # Debra/Ellie/Tara refugee trees
├── hud.py                 # HUD + delegates (minimap, equalizer)
├── base_inventory.py      # shared inventory mixin
├── inventory.py           # 5×5 cargo
├── station_inventory.py   # 10×10 station
├── escape_menu/           # escape menu package (10 sub-modes)
├── build_menu.py          # station build overlay
├── craft_menu.py          # crafting UI
├── trade_menu.py          # trading station overlay (scrollable sell)
├── station_info.py        # T-key station info overlay
├── ship_stats.py          # C-key ship/character bio overlay
├── death_screen.py        # death overlay
├── character_data.py      # XP / level / per-character bonuses
├── video_player.py        # FFmpeg video playback (HUD + music video)
├── sprites/
│   ├── player.py boss.py alien.py zone2_aliens.py
│   ├── asteroid.py copper_asteroid.py wandering_asteroid.py
│   ├── pickup.py shield.py explosion.py contrail.py
│   ├── projectile.py missile.py building.py
│   ├── force_wall.py wormhole.py gas_area.py
│   ├── alien_ai.py        # shared patrol + avoidance + wall-cross helpers
│   ├── parked_ship.py     # multi-ship + AI pilot
│   └── npc_ship.py        # RefugeeNPCShip (story encounter)
└── zones/                 # ZoneID, MainZone, Zone2, warp zones
```

## Tests

- **Fast** (`unit tests/`, 493 tests, ~2 s) — physics, AI, inventory,
  modules, AI Pilot, refugee/dialogue trees, station-shield absorb,
  shared alien-AI helpers, collision cooldown helper, save restore
  helpers, CPU microbenchmarks.
- **Integration** (`unit tests/integration/`, 144 tests) — real
  GameView flows, full-frame FPS (trade panel × zones × videos, AI
  pilot fleets, station shield combat, refugee spawn + dialogue
  click, patrol/return), GPU render, resolution scaling (6 presets ×
  2 zones), soak (5 min each — combat, AI pilot, dialogue, station
  shield, shared scaffolding). Shared soak loop in
  `unit tests/integration/_soak_base.py`.
- `pytest.ini` excludes `integration/` from default runs. Real
  music-video tests look in `./yvideos/*.mp4` (gitignored).

## Load-bearing patterns (stuff to know before editing)

### Module extraction + thin dispatcher
All extracted modules live next to `game_view.py` and follow:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from game_view import GameView

def work(gv: GameView, ...): ...
```
`GameView` holds shared state + thin one-liner delegates so external
callers (`collisions.py`, `game_save.py`, tests) keep working when
we move code around.

### Zone state machine
`zones/` owns Zone 1 / Zone 2 / four warp zones. Each `ZoneState` has
`setup/teardown/update/draw/background_update`. `MainZone` stashes
Zone 1 lists during excursions. `Zone2` stashes its buildings + trade
station + parked ships in `_building_stash` so round trips through
warp zones don't wipe them. Shared sprite lists (`gv.alien_list`,
`gv.alien_projectile_list`) get swapped to Zone 2 versions during its
update so reused collision helpers operate on the right entities.

### Performance hotspots with existing optimisations
- Inventory render cache with dirty flag; single fill texture reused
  across all cell sprites (prevents atlas leak).
- Inventory count badges rendered via PIL into cached `arcade.Texture`s,
  drawn through a pooled `SpriteList` once per frame.
- Minimap dots batched via `arcade.draw_points` per colour group; gas
  octagons batched via `arcade.draw_lines`; fog visibility inlined.
- Turret target caching (0.25 s rescan) + distance-based alien AI
  culling in Zone 2.
- Trade panel pools `SpriteSolidColor` for every fill (panel bg, row
  fills, scrollbar, back button) and per-row `arcade.Text` objects —
  one `SpriteList.draw()` replaces 15+ `arcade.draw_rect_filled` calls.
- `world_setup._alien_tex_cache` memoises cropped Ship.png +
  Effects.png so GameView rebuilds skip ~200 MB of PIL re-decode.
- Music WAVs use `streaming=True` to avoid pyglet's buffer-it-all
  MemoryError; SFX stay static for zero-latency playback.
- Sound-player cleanup every 5 s `.delete()`s pyglet Players that
  pyglet's event system would otherwise pin forever; `gc.collect()`
  runs alongside.

### Input contracts
- `handle_mouse_press` short-circuits through overlays: death screen,
  dialogue overlay, escape menu, destroy mode, placement mode, build
  menu, station inv, craft menu, trade menu, then world clicks.
- `_handle_world_click` order: refugee NPC → parked ship →
  trade station → Home Station → Basic/Advanced Crafter.
- Long-press LMB (`MOVE_LONG_PRESS_TIME` = 0.4 s) on Turret / Missile
  Array enters move mode; the building follows the cursor clamped to
  within `TURRET_FREE_PLACE_RADIUS` (300 px) of the active Home
  Station.
- Dialogue overlay consumes all keys + mouse while open; number keys
  1-9 pick choices, SPACE/ENTER advance linear beats, ESC closes
  without committing aftermath flags.

### Force wall
`sprites/force_wall.py` exposes `closest_point`,
`blocks_point(px, py, radius)`, and `segment_crosses(ax, ay, bx, by)`.
`update_logic.update_force_walls` consumes alien + boss projectiles
colliding with any active wall. Alien AI (both `sprites/alien.py` and
`sprites/zone2_aliens.py`, including Shielded/Fast/Gunner/Rammer
overrides) takes a `force_walls` kwarg; both classes delegate their
avoidance to `sprites/alien_ai.compute_avoidance`, which adds a 2×
repulsion term within `ALIEN_RADIUS + ALIEN_AVOIDANCE_RADIUS + 30 px`,
and any movement segment that would cross a wall reverts to the
pre-move position. `FORCE_WALL_LENGTH` = 400 px,
`FORCE_WALL_DURATION` = 20 s.

### Multi-ship + AI Pilot
`ParkedShip` stores faction/type/level, HP/shields, `cargo_items`,
`module_slots`. `ship_manager._place_new_ship` builds one from the
current player on upgrade; `ship_manager.switch_to_ship` swaps
inventory/modules/weapons/ability meter.
`collisions.handle_parked_ship_damage` routes every projectile type.
Parked ships stash with zones and serialize fully in save/load.

Installing `ai_pilot` flips `ParkedShip.has_ai_pilot` on.
`update_logic._update_parked_ships` runs every tick in both zones
with the correct alien list swapped in. `ParkedShip._ai_mode` toggles
between `"patrol"` (counter-clockwise orbit at
`AI_PILOT_PATROL_RADIUS * AI_PILOT_ORBIT_RADIUS_RATIO` via
`_orbit_patrol` — tangent step + radial correction each tick) and
`"return"` (straight-line flight back to the Home Station, cleared
once within `AI_PILOT_HOME_ARRIVAL_DIST`). Seeing a target cancels
return; firing when no other target remains in `AI_PILOT_DETECT_RANGE`
flips to return. Shots go to `gv.turret_projectile_list` so the
existing turret-projectile collision handler delivers damage.

### Station shield + AI yellow shield
`update_logic.update_station_shield` spawns a faction-tinted
`ShieldSprite` (alpha 15 fill) over the Home Station as soon as a
`Shield Generator` exists; scale tracks `station_outer_radius + 80 px`
every tick. `collisions._station_shield_absorbs` bleeds `proj.damage`
off `gv._station_shield_hp` for any alien + boss projectile inside
the disk before building collision runs. `draw_logic._draw_station_shield`
layers a solid 3 px `draw_circle_outline` border (+ faint inner
ring) on top so the perimeter dominates the visual. HP persists in
save/load; the sprite re-materialises on next tick while the Shield
Generator is present. `ShieldSprite(alpha=...)` lets each shield pick
its own opacity — ship + AI pilot use 200, station uses 15.

AI-piloted parked ships attach their own yellow `ShieldSprite` lazily
(`_AI_SHIELD_TINT = (255, 220, 80)`) and regenerate at 0.5× the ship
type's base `shield_regen`.

### Story NPC + dialogue
Building a `Shield Generator` in Zone 2 triggers
`update_logic.update_refugee_npc`, which spawns `RefugeeNPCShip`
(invulnerable) on the right edge and retargets a parking spot at
`(home.x + station_outer_radius + 120, home.y)` with `hold_dist=24`
every frame. `_station_outer_radius` counts each building's EDGE
(centre distance + `BUILDING_RADIUS`, 30 px) so the parked ship never
overlaps the station. Clicking within `NPC_REFUGEE_INTERACT_DIST`
(320 px) calls
`DialogueOverlay.start(tree, aftermath_sink=gv._quest_flags)` using
`dialogue.get_refugee_tree(audio.character_name)`. Tree nodes hold
`speaker/text/stage` plus one of `choices` / `next` / `end`
(with optional `aftermath` dict of quest flags). Save/load persists
`gv._refugee_spawned`, `gv._met_refugee`, `gv._refugee_npc` pose, and
`gv._quest_flags`.

### Save-restore helpers
`game_save._restore_sprite_list(target_list, entries, factory)` wipes
the target list and rebuilds it via a per-entry factory closure;
factory may return `None` to skip an entry. Used by Zone 1 asteroids
and every Zone 2 entity list. A codec-pair documentation block at
the top of `game_save.py` lists each serialize/restore pair so
field drift between them is caught at review time.

### Shared refactor helpers
- `collisions._hit_player_on_cooldown(gv, damage, volume, cooldown,
  shake)` consolidates the 6-site cooldown + damage + sound + shake
  pattern. Returns True if the hit landed (False if still on
  cooldown).
- `sprites/alien_ai.py` owns `pick_patrol_target`, `compute_avoidance`,
  `segment_crosses_any_wall`. `SmallAlienShip` and `Zone2Alien` both
  delegate. Zone 2 passes `()` for `alien_list` (Zone 2 aliens don't
  repel each other).
- `escape_menu/_ui.draw_button(rect, text_obj, label, fill, outline)`
  replaces the repeated rect-fill + outline + centred-label pattern
  across escape-menu sub-modes.
- `constants_paths.py` re-exports just the asset-path constants from
  `constants.py` for callers that don't need gameplay tunables.
- `unit tests/integration/_soak_base.py` hosts `run_soak(gv, label,
  churn_tick)` plus `SOAK_DURATION_S`/`MIN_FPS`/`MAX_MEMORY_GROWTH_MB`
  thresholds; every `test_soak*.py` file calls `run_soak`.

### Character progression
`character_data.py` holds XP thresholds (10 levels, cap at 1000 XP),
per-character `level_for_xp`, and bonus helpers. Debra gets bonus
iron/copper on kills; Ellie gets laser upgrades; Tara gets crafting
discounts. Weapons reload on level-up. Ship Stats overlay (C key)
reads all bonuses live.

### Saves
`game_save.save_to_dict` + `load_game`. Zone 1 + Zone 2 state saved
independently (even when the player is in a different zone via the
stash). Fog of war, boss state, parked ships, trade credits, trade
station position, refugee NPC, and quest flags all persisted.

## Asset sources

See `docs/README.md` (Asset Sources) for the full list of licensed
packs. Music is bought from Humble Bundle and Gamedev.market; art
comes from Kenney, ScreamingBrainStudios, Itch.io packs. All asset
files live under `assets/` (gitignored), plus `characters/*.mp4`
(character videos, gitignored) and `yvideos/*.mp4` (test music
videos, gitignored).
