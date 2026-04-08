# Call of Orion --- Documentation

Welcome to the full documentation for **Call of Orion**, a top-down space survival game. Use the links below to find detailed information about every aspect of the game.

## Contents

- [Features](features.md) --- Complete list of all gameplay features and systems
- [Statistics](statistics.md) --- All game stats: ship types, weapons, enemies, boss, buildings, items
- [Controls](controls.md) --- Keyboard and gamepad controls reference
- [Rules & Mechanics](rules.md) --- Collision rules, damage flow, AI behaviour, building placement, respawn logic
- [Lore & Characters](lore.md) --- Factions, character backstories, progression, and the Double-Star War
- [Architecture](architecture.md) --- Codebase structure, module extraction pattern, and dependency graph
- [Game Rules Reference](game-rules.md) --- Comprehensive game rules document with asset paths and technical details

## Asset Sources

### 32x32 Sprites

- Spacemonster sprites: https://nulllgames.itch.io/256-spacemonster-sprites
- Spaceship sprites: https://nulllgames.itch.io/256-spaceship-sprites
- Free pixel art: https://jik-a-4.itch.io/freepixel
- Planets/stars/derelicts: https://flavrius.itch.io/free-planetsstarsderelicts-sprites
- Shmup sprites: https://jestan.itch.io/shmupv1
- Pixel planets: https://wyvarth.itch.io/pixel-planets

### Unknown Size Sprites

- Top-down alien spaceship: https://pzuh.itch.io/top-down-alien-spaceship
- Top-down space shooter 1: https://pzuh.itch.io/top-down-space-shooter-1
- Top-down space shooter 2: https://pzuh.itch.io/top-down-space-shooter-2

### Backgrounds & Planets

- Seamless space backgrounds: https://screamingbrainstudios.itch.io/seamless-space-backgrounds
- Planet pack: https://screamingbrainstudios.itch.io/planetpack
- 2D planet pack 2: https://screamingbrainstudios.itch.io/2d-planet-pack-2
- Tiny planet pack: https://screamingbrainstudios.itch.io/tiny-planet-pack
- Seamless sky backgrounds: https://screamingbrainstudios.itch.io/seamless-sky-backgrounds
- Cloudy skyboxes: https://screamingbrainstudios.itch.io/cloudy-skyboxes-pack
- Planet surface skyboxes: https://screamingbrainstudios.itch.io/planet-surface-skyboxes

### Future Development (Planetary Backgrounds)

- Planet texture pack 1: https://screamingbrainstudios.itch.io/planet-texture-pack-1
- Planet surface backgrounds: https://screamingbrainstudios.itch.io/planet-surface-backgrounds
- Planet surface backgrounds 2: https://screamingbrainstudios.itch.io/planet-surface-backgrounds-2

### General Game Assets

- Kenney All-in-1: https://kenney.itch.io/kenney-game-assets

## Zone 2 (The Nebula)

Zone 2 is the second biome, accessed through warp zones that appear when the boss is defeated. It features copper asteroids, toxic gas clouds, wandering magnetic asteroids, and 4 new alien types. Ranged aliens orbit the player at ~300 px standoff distance instead of charging, while the Rammer alien still charges directly. Wandering asteroids bounce off the player on contact with full knockback physics. Gas areas are shown on the minimap as proportionally-sized green circles with outline rings. See [Features](features.md) and [Statistics](statistics.md) for full details.

## Cross-Zone Save/Load

All zones are saved and restored independently. When saving from any zone, both Zone 1 (Double Star) and Zone 2 (Nebula) state is fully serialized --- including asteroids, aliens, fog of war, buildings, and wanderers. Zone 1 data is pulled from the MainZone stash when the player is in another zone. Zone 2 entity population and collision handling are in `zones/zone2_world.py`.

## Architecture Notes

The codebase follows an extraction pattern where GameView delegates to free-function modules. Recent refactors introduced:

- **`game_state.py`** --- state dataclasses (`BossState`, `FogState`, `CombatTimers`, `AbilityState`, `EffectState`) for future incremental adoption
- **`game_save.py`** --- reusable serialization/deserialization helpers (`_serialize_asteroid`, `_restore_z1_aliens`, etc.) replacing repeated patterns
- **`zones/zone2_world.py`** --- Zone 2 entity population and collision handling extracted from `zone2.py`
- **`base_inventory.py`** --- shared drag state, icon resolution, and grid helpers used by both cargo and station inventories

See [Architecture](architecture.md) for the full dependency graph.

### Music and Sound Effects Licensing

- Bought from Humble Bundle
  - https://www.humblebundle.com/software/game-audio-collection-1800-music-tracks-65000-sound-effects-software
- https://gamedevmarket.net/terms-conditions#pro-licence
- Sci Fi Fantasy Music
  - https://gamedevmarket.net/asset/sci-fi-fantasy-music-bundle
- Sci Fi Sound Effects Bundle
  - https://gamedevmarket.net/asset/sci-fi-sound-effects-bundle-2
- Space and Science Fiction Music Pack Vol 1
  - https://gamedevmarket.net/asset/space-science-fiction-music-pack
- Space and Science Fiction Music Pack Vol 2
  - https://gamedevmarket.net/asset/space-science-fiction-music-pack-vol-2
