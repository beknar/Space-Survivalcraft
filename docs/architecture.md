# Call of Orion --- Architecture

## Overview

The codebase follows a modular extraction pattern where the central `GameView` class acts as a thin dispatcher, delegating logic to focused modules. Each extracted module receives a `GameView` reference and uses `TYPE_CHECKING` to avoid circular imports.

## Module Structure

### Core Gameplay (GameView + Extracted Modules)

| Module | Lines | Responsibility |
|---|---|---|
| `game_view.py` | ~620 | Thin dispatcher: `__init__`, delegate methods, fog of war, weapon helpers |
| `combat_helpers.py` | ~237 | Damage, death, spawning, respawn, XP, boss spawn |
| `building_manager.py` | ~235 | Building placement, destruction, port snapping, trade station |
| `draw_logic.py` | ~271 | `draw_world()` and `draw_ui()` rendering |
| `update_logic.py` | ~431 | 11 update sub-functions for the game loop |
| `input_handlers.py` | ~551 | All keyboard and mouse event handling |
| `game_save.py` | — | Save/load serialization |
| `game_music.py` | — | Music playlist, video playback management |
| `collisions.py` | — | All collision handlers (projectile, asteroid, alien, boss, building) |
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
| `hud.py` | ~518 | HUD status panel, delegates minimap and equalizer |
| `hud_minimap.py` | ~185 | Minimap drawing with fog overlay |
| `hud_equalizer.py` | ~83 | Equalizer visualizer state and rendering |
| `base_inventory.py` | ~84 | Shared `BaseInventoryData` mixin (add/remove/count/consolidate) |
| `inventory.py` | ~420 | 5x5 cargo grid (inherits BaseInventoryData) |
| `station_inventory.py` | ~381 | 10x10 station grid (inherits BaseInventoryData) |
| `escape_menu/` | ~10 files | Escape menu with sub-mode pattern |
| `build_menu.py` | ~337 | Station building overlay |
| `craft_menu.py` | ~283 | Crafting UI |
| `trade_menu.py` | ~276 | Trading station overlay |

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

## Dependency Graph

```
constants.py <-- nearly everything (central config)
settings.py  <-- splash_view, options_view, game_view, death_screen

game_view.py (thin dispatcher)
  +-- combat_helpers.py
  +-- building_manager.py
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
```

## Key Design Patterns

- **Pre-built `arcade.Text` objects** --- avoids per-frame allocation (PerformanceWarning)
- **Spatial hashing** on `asteroid_list` and `alien_list` for O(1) collision lookups
- **GC management** --- automatic GC disabled; manual collect when ESC menu opens
- **Sound throttling** --- min 0.15s between pyglet media player creations
- **BaseInventoryData mixin** --- shared item storage inherited by both inventory classes; subclasses set `_rows`/`_cols`
- **EqualizerState class** --- encapsulates equalizer animation with `update(dt, volume)` and `draw(y)`
- **MenuContext + MenuMode** --- escape menu sub-mode pattern with shared state and per-mode draw/input
- **TYPE_CHECKING imports** --- all extracted modules avoid circular imports at runtime
- **Zone state machine** --- `zones/` package manages transitions between Zone 1, warp zones, and Zone 2; each zone has its own asteroid/alien populations, hazard rules, and background; GameView delegates zone-specific setup and update logic to the active zone state
- **Viewport culling** --- Zone 2 only draws/updates sprites within camera bounds + 250 px margin (gas areas get +200 px extra); offscreen wanderers spin-only; uses `_vis_draw` SpriteList rebuilt each frame for GPU batch drawing
- **Ranged alien standoff AI** --- gun-equipped aliens orbit at `ALIEN_STANDOFF_DIST` (300 px) with random CW/CCW direction; RammerAlien charges directly (`has_guns=False`)

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
