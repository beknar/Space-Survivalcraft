# Space Survivalcraft — Dev Reference

**Call of Orion** is a top-down Newtonian space survival game built on
Python 3.12 + Arcade 3.3.3. Fly a faction/ship/character combo through
Zone 1 (6400×6400) and the Nebula / Zone 2 (9600×9600), mine
asteroids, fight aliens, build a modular station, upgrade ships, talk
to story NPCs.

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
│   ├── asteroid.py, copper_asteroid.py, wandering_asteroid.py
│   ├── pickup.py, shield.py, explosion.py, contrail.py
│   ├── projectile.py, missile.py, building.py
│   ├── force_wall.py, wormhole.py, gas_area.py, null_field.py
│   ├── parked_ship.py       # multi-ship + AI pilot
│   └── npc_ship.py          # RefugeeNPCShip (story encounter)
└── zones/                   # ZoneID, MainZone, Zone2, warp zones
```

## Tests

- **Fast** (`unit tests/`, 701 tests, ~3 s) — physics, AI, inventory,
  modules, AI Pilot, refugee/dialogue trees, station shield, shared
  helpers, save restore, CPU microbenchmarks.
- **Integration** (`unit tests/integration/`, 309 tests) — real
  GameView flows, full-frame FPS (with / without videos, menu scroll,
  station combat, AI pilot fleets, dialogue), GPU render, resolution
  scaling, soak (5 min each). Shared soak scaffold in
  `unit tests/integration/_soak_base.py`.
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

`zones/` owns Zone 1 / Zone 2 / four warp zones. Each `ZoneState` has
`setup / teardown / update / draw / background_update`. `MainZone`
stashes Zone 1 lists during excursions. `Zone2` stashes buildings +
trade station + parked ships in `_building_stash` so warp-zone round
trips don't wipe them. Shared sprite lists (`gv.alien_list`,
`gv.alien_projectile_list`) swap to Zone 2 versions during its update
so reused collision helpers operate on the right entities.

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
  craft, trade, then world clicks.
- `_handle_world_click` order: refugee NPC → parked ship → trade
  station → Home Station → Basic/Advanced Crafter.
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
would cross a wall reverts to the pre-move position.

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
