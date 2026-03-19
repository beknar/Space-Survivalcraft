# Call of Orion — Game Rules & Reference

## Overview

**Call of Orion** (working title: *Space Survivalcraft*) is a top-down space survival game built with Python and the Arcade framework. Players pilot a customisable spaceship through a vast star field, mine asteroids for resources, fight alien enemies, and manage a cargo inventory. The game features Newtonian physics, multiple ship classes, a weapon system, and a full save/load system.

---

## Game Features

- **Faction & ship selection** — choose from 4 factions and 5 ship types, each with unique stats
- **Newtonian flight model** — thrust, braking, velocity damping, and speed caps
- **Energy shields** — absorb damage before hull HP; regenerate over time
- **Two weapon types** — Basic Laser (combat) and Mining Beam (resource gathering)
- **Asteroid mining** — destroy iron asteroids to collect ore
- **5 x 5 cargo inventory** — drag-and-drop grid with item ejection into the game world
- **Enemy AI** — alien scout ships that patrol, detect, pursue, and fire
- **Collision physics** — elastic bounces with push-out resolution for all object pairs
- **Full HUD** — HP/shield bars, speed, heading, weapon indicator, mini-map, music track, station info overlay
- **Save/load system** — 10 named save slots preserving full game state (includes module count)
- **Background music** — shuffled playlist of loop tracks from two music packs
- **Gamepad support** — Xbox 360 controller with analogue stick and button mapping
- **Visual effects** — explosions, hit sparks, fire sparks, shield flashes, engine contrails
- **Death & respawn** — dramatic destruction sequence with death screen and load options

---

## The Battlefield

| Property | Value |
|---|---|
| World size | 6,400 x 6,400 px (200 x 200 tiles of 32 px) |
| Window resolution | Default 1,280 x 800 px (configurable: 1366x768, 1600x900, 1920x1080, 2560x1440, 3840x2160) |
| Status panel width | 213 px (left side, excluded from gameplay viewport) |
| Gameplay viewport | Window width − 213 px × window height |
| Background | Tiled seamless starfield (1,024 x 1,024 px tiles) |
| Camera | Follows player, clamped at world edges; left edge offset by STATUS_WIDTH so gameplay viewport never shows beyond the world |
| Player start position | World centre (3,200, 3,200) |

---

## Factions

Players choose one of four factions. Each faction provides a unique visual style through its sprite sheet; all factions share the same ship-type stats.

| Faction | Description |
|---|---|
| **Earth** | Terran standard-issue fleet |
| **Colonial** | Frontier colony ships |
| **Heavy World** | High-gravity adapted vessels |
| **Ascended** | Advanced civilisation technology |

Each faction sprite sheet is a 1,024 x 1,024 px grid (8 columns x 8 rows of 128 x 128 px frames). Column 0 is the starting (un-upgraded) ship.

---

## Player Ships

All ships start at world centre (3,200, 3,200). Ships are rendered at 0.75x scale (128 x 0.75 = 96 px in-game). Collision radius is 28 px. Projectiles spawn 44 px ahead of the ship centre (nose offset).

### Ship Type Statistics

| Ship Type | Sheet Row | HP | Shields | Shield Regen | Rotation | Thrust | Brake | Max Speed | Damping | Guns |
|---|---|---|---|---|---|---|---|---|---|---|
| **Cruiser** | 8 | 100 | 100 | 0.5 pt/s | 150 deg/s | 250 px/s^2 | 125 px/s^2 | 450 px/s | 0.98875x | 1 |
| **Bastion** | 7 | 150 | 50 | 0.5 pt/s | 150 deg/s | 200 px/s^2 | 125 px/s^2 | 450 px/s | 0.98875x | 1 |
| **Aegis** | 6 | 50 | 150 | 1.0 pt/s | 100 deg/s | 250 px/s^2 | 125 px/s^2 | 450 px/s | 0.98875x | 1 |
| **Striker** | 5 | 100 | 50 | 0.5 pt/s | 150 deg/s | 300 px/s^2 | 100 px/s^2 | 450 px/s | 0.983125x | 1 |
| **Thunderbolt** | 4 | 100 | 100 | 0.5 pt/s | 150 deg/s | 200 px/s^2 | 125 px/s^2 | 400 px/s | 0.98875x | 2 |

### Ship Type Profiles

- **Cruiser** — balanced all-rounder with equal HP and shields
- **Bastion** — tanky hull (150 HP) at the cost of weaker shields (50)
- **Aegis** — shield specialist (150 shields, 1.0 pt/s regen) with fragile hull (50 HP) and slower turning (100 deg/s)
- **Striker** — speed-focused (300 thrust, lower damping) with reduced shields (50) and weaker brakes (100)
- **Thunderbolt** — dual-gun ship firing two projectiles simultaneously; lower top speed (400) and thrust (200) as trade-off

### Engine Contrail Colours

Each ship type has a unique engine exhaust colour:

| Ship Type | Start Colour | End Colour |
|---|---|---|
| Cruiser | Blue (100, 180, 255) | Dark Blue (20, 40, 120) |
| Bastion | Orange (255, 200, 80) | Dark Orange (120, 60, 10) |
| Aegis | Green (80, 255, 180) | Dark Green (10, 80, 50) |
| Striker | Red (255, 100, 100) | Dark Red (120, 20, 20) |
| Thunderbolt | Purple (200, 120, 255) | Dark Purple (60, 20, 100) |

Contrail particles spawn at 30/s (max 20 particles), 30 px behind ship centre. Each particle lives 0.5 s, shrinking from 6 px to 1 px radius while fading and transitioning between the two colours.

---

## Shields

| Property | Value |
|---|---|
| Visual | Animated cyan energy bubble (6 frames, 280 x 280 px each, displayed at 0.5x scale = 140 px) |
| Animation | 8 fps frame cycling + 25 deg/s rotation |
| Normal alpha | 200/255 (slightly transparent) |
| Hit flash | Alpha pulses to 255 for 0.25 s on damage absorption |
| Depleted | Fully invisible (alpha 0); reappears when regen brings shields above 0 |
| Regeneration | Fractional accumulation; whole points applied per frame |

All incoming damage is routed through shields first. Overflow damage carries into HP.

---

## Weapons

All ships start with both weapons. The Thunderbolt has 2 guns, so it gets 2x Basic Laser and 2x Mining Beam. Weapons are cycled with Tab (keyboard) or RB (gamepad).

### Weapon Statistics

| Weapon | Damage | Cooldown | Speed | Range | Targets | Auto-fire |
|---|---|---|---|---|---|---|
| **Basic Laser** | 25 | 0.30 s | 900 px/s | 1,200 px | Alien ships only | Yes (hold Space/A) |
| **Mining Beam** | 10 | 0.10 s | 500 px/s | 800 px | Asteroids only | Yes (hold Space/A) |

### Weapon Behaviour

- **Basic Laser** deals damage only to alien ships; passes through asteroids with no effect
- **Mining Beam** deals damage only to asteroids; passes through aliens with no effect
- Projectiles despawn when they exceed their max range or leave the world boundary
- Sound is throttled to a minimum 0.15 s interval to prevent audio stutter from rapid fire
- Dual-gun ships fire from two laterally-offset hardpoints (10 px left/right of nose axis)

---

## Game Objects

### Iron Asteroids

| Property | Value |
|---|---|
| Count | 50 (randomly distributed) |
| HP | 100 |
| Iron yield | 10 per asteroid |
| Sprite size | 64 x 64 px at 1.0x scale |
| Collision radius | 26 px |
| Spin rate | 8-30 deg/s (random direction) |
| Min spawn distance | 400 px from world centre |
| Edge margin | 100 px from world edges |

**Mining mechanics:**
- Only the Mining Beam deals damage (10 per hit)
- Each hit triggers a shake effect (4 px amplitude, 0.20 s) and orange-red tint flash
- On destruction: explosion animation + sound, drops one Iron Pickup at the destruction site

**Respawn:**
- Asteroids respawn every 2 minutes (120 s) until the count returns to 50
- One asteroid respawns per cycle (timer resets after each spawn attempt)
- Asteroids will not respawn within 300 px of any player-built station module
- Same spawn constraints apply: min 400 px from world centre, 100 px from edges

### Iron Pickups

| Property | Value |
|---|---|
| Icon scale | 0.5x |
| Amount per pickup | 10 iron |
| Pickup trigger distance | 40 px from ship hull edge (68 px from ship centre) |
| Fly-to-ship speed | 400 px/s |
| Ejected item lifetime | 600 s (10 minutes) before silent despawn |
| Ejection distance | 60 px from ship hull edge (88 px from ship centre) |

Pickups idle at their drop position until the ship's hull edge comes within 40 px, then fly toward the ship. On contact, the pickup is collected and added to inventory.

### Small Alien Ships

| Property | Value |
|---|---|
| Count | 20 (randomly distributed) |
| HP | 50 |
| Collision radius | 20 px |
| Movement speed | 120 px/s (patrol and pursuit) |
| Display scale | 0.10x |
| Min spawn distance | 400 px from world centre |
| Edge margin | 100 px from world edges |

**Respawn:**
- Alien ships respawn every 2 minutes (120 s) until the count returns to 20
- One alien respawns per cycle (timer resets after each spawn attempt)
- Aliens will not respawn within 300 px of any player-built station module
- Same spawn constraints apply: min 400 px from world centre, 100 px from edges

**Iron Drop:**
- When an alien ship is destroyed (by player or turret), it drops 5 iron ore at the destruction site
- The iron pickup behaves identically to asteroid-mined iron (fly-to-ship + collection)

#### Alien Weapon

| Property | Value |
|---|---|
| Laser damage | 10 per hit |
| Laser range | 500 px |
| Laser speed | 650 px/s |
| Fire cooldown | 1.5 s |
| Laser scale | 0.5x |

#### AI Behaviour

**PATROL state:**
- Circles a random point within 100-150 px of its spawn position
- Picks a new waypoint each time it arrives within 8 px
- Takes no hostile action

**PURSUE state (triggered when player enters 500 px):**
- Chases the player at 120 px/s
- Fires laser bolts along its current heading every 1.5 s when player is within 500 px
- Fire cooldown resets to 0 on first detection (immediate first shot)
- Steers around obstacles (asteroids and other aliens) using avoidance blending
- Avoidance radius: 65 px beyond obstacle edge; avoidance force weight: 2.5x

**Leash:** Returns to PATROL if the player moves beyond 1,500 px (3x detection range)

#### Obstacle Avoidance (Both States)

Alien ships use avoidance steering in both PATROL and PURSUE states:
- Asteroids and other alien ships within `ALIEN_AVOIDANCE_RADIUS` (65 px beyond obstacle edge) exert repulsion
- Avoidance force weight: 2.5x, decreasing linearly with distance
- The combined steering vector (base direction + avoidance) is normalised before movement

#### Stuck Detection

| Constant | Value |
|---|---|
| Stuck check interval | 2.0 s |
| Stuck distance threshold | 10 px |

- Every 2 seconds, if the alien has moved less than 10 px since the last check, it is considered stuck
- Stuck aliens pick an escape target in the direction **away** from the nearest asteroid (with slight randomisation)
- This prevents aliens from getting trapped behind asteroids indefinitely

#### Known AI Weaknesses
- No coordinated group behaviour — each ship acts independently
- No flanking or encirclement
- Fires only along its heading; strafing perpendicular to an incoming alien dodges most shots
- No stand-off sniping behaviour

#### Alien Collision Physics

| Property | Value |
|---|---|
| Bounce restitution | 0.65 |
| Velocity damping | 0.97x per frame (at 60 fps, frame-rate independent) |
| Collision cooldown | 0.40 s |
| Bump flash colour | Orange (255, 160, 50) for 0.15 s |
| Weapon hit flash | Red (255, 80, 80) for 0.15 s (takes priority over bump flash) |

---

## Collision Rules

### Player vs Asteroid
- Push-out along collision normal (no interpenetration)
- Velocity bounce with 0.55 restitution (only when moving toward asteroid)
- 5 damage per collision (shields first, then HP)
- 0.5 s invincibility cooldown prevents per-frame damage stacking
- Triggers camera shake (8 px amplitude, 0.25 s) and bump sound

### Player vs Alien Ship
- 50/50 push-apart along collision normal
- Velocity bounce using relative velocity (0.65 restitution)
- 5 damage to player (shields first, then HP)
- Alien gets orange bump flash
- Player collision cooldown: 0.5 s; alien collision cooldown: 0.40 s

### Alien vs Asteroid
- Alien pushed fully away from static asteroid
- Velocity reflected off asteroid normal
- Orange bump flash on alien

### Alien vs Alien
- O(n^2) pair check
- 50/50 push-apart
- Equal-mass velocity exchange
- Both get orange bump flash

### Player Projectile vs Asteroid (Mining Beam only)
- HitSpark effect at impact point
- 10 damage per hit
- Asteroid shake + orange-red tint flash
- On asteroid destruction: explosion + iron pickup spawn

### Player Projectile vs Alien (Basic Laser only)
- HitSpark effect at impact point
- 25 damage per hit
- Camera shake
- Red tint flash on alien (0.15 s)
- On alien destruction: explosion + sound + drops 5 iron ore

### Alien Laser vs Player
- 10 damage per hit (shields first, then HP)
- Camera shake + bump sound
- Bolt removed on contact

### Player vs Station Building
- Push-out along collision normal (no interpenetration)
- Velocity component toward building zeroed (no bounce, restitution = 0)
- **No damage**, no collision cooldown, no sound, no camera shake
- Player can touch the station without harm but cannot pass through

### Alien vs Station Building
- Alien pushed away from building
- Velocity reflected off building normal
- Orange bump flash on alien

### Alien Laser vs Station Building
- HitSpark at impact point
- Building takes laser damage (10 per hit)
- On building destruction: explosion + iron drop (equal to build cost) + port cleanup
- If Home Station destroyed: all modules disabled (greyed out)

### Turret Projectile vs Alien
- HitSpark at impact point
- 10 damage per hit
- On alien destruction: explosion + sound + drops 5 iron ore

---

## Damage & Death

### Damage Flow
1. All damage routes through shields first
2. Shields absorb up to their remaining value; overflow carries into HP
3. Shield visual flashes bright on absorption
4. When hull (HP) takes direct damage, fire sparks emit from the ship

### Fire Sparks
- 12 particles per burst
- Fly outward in random directions at 60-180 px/s
- Transition from bright yellow to dark red over 0.35 s
- Particle size: 2-5 px radius, shrinking over lifetime

### Player Death
When HP reaches 0:
1. Large explosion (2.5x scale, orange-tinted) at ship position
2. 5 additional fire spark bursts
3. Explosion sound plays
4. Ship and shield become invisible
5. Thruster sound stops
6. After 1.5 s delay, death screen appears

### Death Screen
- Title: "SHIP DESTROYED"
- Quote: 'As the Elder Gamer says "git gud"'
- Three buttons: **Load Game**, **Main Menu**, **Exit Game**
- Gameplay is frozen; explosions and fire sparks still animate during the 1.5 s delay

---

## Visual Effects

### Explosions
- 9 frames, 140 x 140 px each, played at 15 fps
- Used for asteroid destruction (1.0x scale) and player death (2.5x scale, orange-tinted)

### Hit Sparks
- Expanding ring + fading bright core
- Duration: 0.18 s, max radius: 28 px
- Ring colour: (255, 200, 80) with fading alpha
- Core colour: (255, 255, 180) shrinking with time

### Camera Shake
- Duration: 0.25 s, amplitude: 8 px
- Fades linearly to zero
- Triggered by: hull collisions, alien hits on player, player hits on aliens

---

## Controls

### Keyboard

| Action | Keys |
|---|---|
| Rotate left | Left Arrow / A |
| Rotate right | Right Arrow / D |
| Thrust forward | Up Arrow / W |
| Brake / reverse | Down Arrow / S |
| Fire active weapon | Space (hold for auto-fire) |
| Cycle weapon | Tab |
| Open/close inventory | I |
| Toggle FPS display | F |
| Open/close build menu | B |
| Station info panel | T (when near station) |
| Escape menu | Escape |

### Xbox 360 Gamepad

| Action | Input |
|---|---|
| Rotate | Left stick horizontal |
| Thrust / Brake | Left stick vertical |
| Fire | A button (hold for auto-fire) |
| Cycle weapon | Right bumper (RB) |
| Open/close inventory | Y button |

Gamepad dead zone: 0.15

---

## Inventory

- 5 x 5 grid (25 slots)
- Toggled with I (keyboard) or Y (gamepad)
- Modal overlay; does **not** pause gameplay
- Iron is tracked as a stackable count in a single cell (default position: 0,0)

### Drag & Drop
- Left-click an occupied cell to pick up; drag to a new cell to move
- Source cell highlighted yellow; drop target highlighted blue
- Dropping inside the panel but outside the grid returns item to source
- Dropping **outside** the panel ejects the item into the game world

### Ejection
- Items spawn 60 px from the ship's hull edge in a random direction
- Placed safely outside the 40 px auto-pickup zone to prevent immediate re-collection
- Ejected items despawn after 600 seconds (10 minutes)

---

## HUD Status Panel

The left-side panel (213 px wide) displays:

| Element | Description |
|---|---|
| HP bar | Green > orange > red as HP falls; numerical value below |
| Shield bar | Cyan bar; numerical value below |
| Speed readout | Current velocity in px/s |
| Heading readout | Current heading in degrees |
| Iron count | Current iron ore in inventory |
| Asteroid count | Number of iron asteroids remaining in the world |
| Alien count | Number of alien ships remaining in the world |
| Active weapon | Name of the selected weapon group |
| Controls reference | Keyboard shortcut reminders |
| Gamepad status | "Gamepad: connected" when detected |
| Faction / Ship type | Current faction and ship labels |
| Now Playing | Current music track name |
| FPS counter | Smoothed exponential moving average (toggle with F) |
| Mini-map | Full world overview (193 x 193 px) |

### Mini-map Legend
- **Grey dots** — asteroids
- **Orange dots** — iron pickups
- **Red dots** — alien ships
- **White dot + cyan heading line** — player ship

---

## Screens & Navigation

### Splash Screen (Title)
- Displays "CALL OF ORION" with subtitle "A Space Survival Saga"
- Background music with track name at bottom
- Decorative starfield (procedural, fixed seed)
- **Buttons:** Play Now, Load Game, Options, Exit Game
- ESC exits the application

### Options Screen
- Music Volume slider (0-100%)
- Sound Effects Volume slider (0-100%)
- **Resolution selector**: left/right arrows cycling through presets (1280x800, 1366x768, 1600x900, 1920x1080, 2560x1440, 3840x2160)
- **Fullscreen toggle**: ON/OFF button
- **Buttons:** Main Menu, Exit Game
- Settings stored in memory for current session (not persisted to disk)

### Selection Screen
- Phase 1: Choose faction (Left/Right or A/D to browse, Enter/Space to confirm)
- Phase 2: Choose ship type (same controls)
- ESC goes back
- UI sounds on navigation and confirmation
- Preview images: 128 px source upscaled 1.5x to 192 px using nearest-neighbour resampling

### Escape Menu (In-Game)
- Toggled with ESC (if inventory is open, first ESC closes inventory)
- Semi-transparent dark overlay with centred panel (320 x 480 px)
- Gameplay **continues** while the escape menu is open (does not pause)
- **Audio sliders:** Music and SFX volume sliders (220 px wide) at the top of the panel, directly draggable with percentage display
- **Buttons:** Resume, Save Game, Load Game, Main Menu, Exit Game
- 10 save slots with naming overlay (max 24 characters, blinking cursor)
- Save slot detail line shows: faction, ship type, HP, shields, and module count (when > 0)
- Status feedback messages displayed for 2 seconds
- **Resolution** button opens a sub-mode with left/right preset selector plus Apply Windowed / Apply Fullscreen buttons
- ESC in sub-menus returns to main menu; ESC in main menu closes overlay

---

## Save System

- 10 save slots stored as JSON files in `saves/` directory
- File naming: `save_slot_01.json` through `save_slot_10.json`

### Saved Data
- Save name (player-chosen label)
- Faction and ship type
- Player state: position, heading, velocity, HP, shields, shield accumulator
- Active weapon index
- Inventory iron count
- All surviving asteroids: position, HP
- All surviving aliens: position, HP, velocity, heading, AI state, home position
- All iron pickups: position, amount
- All station buildings: type, position, HP, angle, disabled state
- Respawn timers: asteroid and alien respawn countdown progress

### Save Slot Display
Each slot shows:
- Slot number and save name (or "Empty")
- Detail line: faction, ship type, HP, shields, module count (when > 0)

---

## Music System

Background music plays continuously across all screens.

### Track Sources
- **Vol 1:** Action Loop and Ambient Loop WAV files (~30 tracks)
- **Vol 2:** Loop WAV files in subdirectories (10 tracks)

### Playback
- Tracks are shuffled on each playlist creation
- Auto-advances when a track finishes
- Loaded sounds cached at module level for instant screen transitions
- Volume controlled by global AudioSettings singleton (default: 0.35)

---

## Audio Settings

| Setting | Default | Range |
|---|---|---|
| Music volume | 0.35 (35%) | 0.0 - 1.0 |
| SFX volume | 0.60 (60%) | 0.0 - 1.0 |

Stored in memory via the `AudioSettings` singleton in `settings.py`. Not persisted to disk.

---

## Asset Paths

### Graphical Assets

| Asset | Path |
|---|---|
| Starfield background | `assets/SBS - Seamless Space Backgrounds - Large 1024x1024/Large 1024x1024/Starfields/Starfield_01-1024x1024.png` |
| Faction 1 (Earth) ships | `assets/256Spaceships/faction_1_ships_128x128.png` |
| Faction 2 (Colonial) ships | `assets/256Spaceships/faction_2_ships_128x128.png` |
| Faction 5 (Heavy World) ships | `assets/256Spaceships/faction_5_ships_128x128.png` |
| Faction 7 (Ascended) ships | `assets/256Spaceships/faction_7_ships_128x128.png` |
| Legacy player sprite | `assets/ShmupAssets_V1/shmup_player.png` |
| Basic Laser projectile | `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserBlue03.png` |
| Mining Beam projectile | `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserGreen13.png` |
| Iron Asteroid | `assets/Pixel Art Space/Asteroid.png` (64 x 64 px) |
| Iron ore pickup icon | `assets/kenney space combat assets/Voxel Pack/PNG/Items/ore_ironAlt.png` |
| Explosion sprite sheet | `assets/gamedevmarket assets/asteroids crusher/Explosions/PNG/explosion.png` (9 frames, 140 x 140 px each) |
| Shield sprite sheet | `assets/gamedevmarket assets/asteroids crusher/Weapons/PNG/shield_frames.png` (6 frames, 3 cols x 2 rows, 280 x 280 px each) |
| Small Alien ship | `assets/gamedevmarket assets/alien spaceship creation kit/png/Ship.png` (PIL crop: x=364, y=305, w=461, h=510) |
| Alien laser bolt | `assets/gamedevmarket assets/alien spaceship creation kit/png/Effects.png` (PIL crop: x=4299, y=82, w=60, h=228; rotated 90 deg CCW) |

### Sound Effects

| Sound | Path |
|---|---|
| Basic Laser fire | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Energy Weapons/Small Laser Weapon Shot 1.wav` |
| Mining Beam fire | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Energy Weapons/Sci-Fi Arc Emitter Weapon Shot 2.wav` |
| Explosion | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Explosions/Sci-Fi Deep Explosion 1.wav` |
| Hull collision bump | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Biomechanical/Game Biomechanical Impact Sound 1.wav` |
| Thruster engine loop | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Vehicles/Sci-Fi Spaceship Engine Loop 1.wav` |
| UI click / confirm | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Interface/Other Interface/Sci-Fi Interface Simple Notification 2.wav` |
| UI navigation ping | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Interface/Other Interface/Sci-Fi Interface Simple Notification 1.wav` |
| Escape menu click | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Interface/Other Interface/Sci-Fi Spaceship Interface Mechanical Switch 1.wav` |

### Music

| Pack | Directory | Pattern |
|---|---|---|
| Vol 1 | `assets/Space and Science Fiction Music Pack Vol 1/Space Science Fiction Music Pack/audio/` | `*[Action Loop].wav`, `*[Ambient Loop].wav` |
| Vol 2 | `assets/Space and Science Fiction Music Pack Vol 2/Space_Science_Fiction_MusicPackVol.2/Music/` | `*/*_loop.wav` (in subdirectories) |

### Primitive-Drawn Effects (No Asset Files)

| Effect | Description |
|---|---|
| Hit Spark | Expanding ring (gold) + shrinking core (bright yellow); drawn with `arcade.draw_circle_filled` and `arcade.draw_circle_outline` |
| Fire Spark | 12 particles flying outward, yellow-to-red colour transition; drawn with `arcade.draw_circle_filled` |
| Engine Contrail | Fading, shrinking coloured particles behind ship; drawn with `arcade.draw_circle_filled` |
| Mini-map | Coloured dots for objects + heading line; drawn with arcade primitives |
| HUD bars | HP and shield bars; drawn with `arcade.draw_rect_filled` |

---

## 12. Building System — Space Station

Players can spend mined iron to construct a modular space station. Press **B** to open the Build Menu (non-pausing overlay on the right side of the screen). Select a module, then click in the world to place it.

### Building Types

| Type | HP | Iron Cost | Max Count | Module Slots | Notes |
|---|---|---|---|---|---|
| Home Station | 100 | 100 | 1 | — | Root module; destroying it disables all modules |
| Service Module | 50 | 25 | 4 | — | General connector between other modules |
| Power Receiver | 75 | 50 | unlimited | — | Links Service Modules to Solar Arrays |
| Solar Array 1 | 50 | 75 | 2 | +6 capacity | Provides additional module capacity |
| Solar Array 2 | 50 | 100 | 2 | +10 capacity | Provides additional module capacity |
| Turret 1 | 100 | 50 | unlimited | 1 slot | Single-barrel auto-fire turret |
| Turret 2 | 100 | 75 | unlimited | 2 slots | Dual-barrel auto-fire turret |
| Repair Module | 75 | 75 | 1 | 1 slot | Enables passive HP repair near Home Station |

### Placement Rules

- **Home Station** must be built first; all other modules require it.
- **Connectable modules** (Home Station, Service Module, Power Receiver, Solar Arrays, Repair Module) snap to unoccupied docking ports (N/S/E/W) on existing modules within 40 px snap distance.
- **Edge-to-edge snap**: when snapping to a port, the new module is offset so its opposite port aligns with the parent port — modules sit edge-to-edge, not overlapping. Both ends of connected pieces have their ports marked as occupied.
- **Post-placement connectivity**: after placing a new module, any of its remaining ports that are adjacent to other existing modules' ports are also connected automatically.
- **Overlap prevention**: a new building cannot be placed if its centre is within `2 × BUILDING_RADIUS` (60 px) of any existing building. If overlap is detected, the placement is cancelled and iron is refunded.
- **Turrets** are freely placed within 300 px of the Home Station; they do not dock to ports.
- Mouse wheel rotates the ghost building before placement.
- ESC cancels placement mode.

### Deconstruction (Destroy Mode)

- Open the Build Menu (B key) and click the red **DESTROY** button at the bottom.
- The cursor changes to a **targeting reticle** (red crosshair with circle).
- Left-click on any station module to destroy it instantly (explosion + sound).
- **Iron refund**: destroyed buildings drop iron pickups equal to their build cost (e.g. Home Station drops 100 iron).
- Connected ports on adjacent modules are freed when a building is destroyed.
- Destroying the **Home Station** disables all remaining modules (greyed out).
- Press **B** or **ESC** to exit destroy mode.
- Iron is also dropped when alien lasers destroy a building (same cost-based amount).

### Station Info Panel (T Key)

- Press **T** while within **300 px** of any station building to open the station info overlay.
- Non-pausing right-side panel (280 x 420 px).
- Shows each building's type and HP (colour-coded: green > 50%, orange > 25%, red ≤ 25%).
- Disabled modules shown in grey with "DISABLED" label.
- Footer: "Modules: X / Y used" (used vs. capacity).
- Auto-closes when the player moves beyond **400 px** from all buildings.
- Press **T** again to close manually.

### Module Capacity

- Base capacity: **4** (from Home Station).
- Each Solar Array 1 adds **+6** capacity (max 2).
- Each Solar Array 2 adds **+10** capacity (max 2).
- Turret 2 counts as **2** module slots; all other non-Home modules count as **1**.

### Turret Behaviour

| Constant | Value |
|---|---|
| Detection range | 400 px |
| Damage per shot | 10 HP |
| Fire cooldown | 1.5 s |
| Projectile speed | 700 px/s |
| Projectile max range | 500 px |

- Turrets auto-target the nearest alien within range.
- Turret 2 fires two parallel projectiles with lateral barrel offset.
- Disabled turrets (Home Station destroyed) do not fire.

### Repair Module Behaviour

| Constant | Value |
|---|---|
| Repair range | 300 px (distance from Home Station) |
| Repair rate | 1 HP per second (player + buildings) |
| Shield regen boost | +1 pt/s (added to ship's base shield regen rate) |

- **Player HP repair**: when a non-disabled Repair Module exists and the player is within **300 px** of a non-disabled Home Station, the player's HP regenerates at **1 HP/s**.
- **Station repair**: when a non-disabled Repair Module exists, all damaged non-disabled station buildings are healed at **1 HP/s** (regardless of player position).
- **Shield boost**: when the player is within repair range of the Home Station, shield regeneration is boosted by **+1 pt/s** (e.g. Cruiser goes from 0.5 → 1.5 pt/s; Aegis from 1.0 → 2.0 pt/s).
- Uses fractional accumulation — whole HP points are applied per frame.
- Does not heal beyond `max_hp`.
- Disabled Repair Modules (Home Station destroyed) do not provide healing or shield boost.

### Building Assets

All building PNGs are located in `assets/kenney space combat assets/Space Shooter Extension/PNG/Sprites X2/Building/`:

| Type | File |
|---|---|
| Home Station | `spaceBuilding_006.png` |
| Service Module | `spaceBuilding_004.png` |
| Power Receiver | `spaceBuilding_003.png` |
| Solar Array 1 | `spaceBuilding_015.png` |
| Solar Array 2 | `spaceBuilding_024.png` |
| Turret 1 | `spaceBuilding_011.png` |
| Turret 2 | `spaceBuilding_012.png` |
| Repair Module | `spaceBuilding_009.png` |

### Mini-map

Buildings appear as **cyan dots** (2.5 px radius) on the mini-map.

---

## 13. Fog of War

The world starts fully hidden. As the player travels, areas are revealed in a circle around the ship.

| Property | Value |
|---|---|
| Reveal diameter | 800 px (400 px radius) |
| Grid cell size | 50 px |
| Grid dimensions | 128 x 128 cells (covers the full 6,400 x 6,400 world) |
| Persistence | Fog state is saved/loaded with game state |

### Behaviour

- All objects (asteroids, aliens, pickups, buildings) are **hidden on the mini-map** until the player's ship has travelled within 400 px of the cell containing them.
- Unrevealed areas are rendered as a **grey fog overlay** (60, 60, 80, alpha 200) on the mini-map; revealed areas show the dark starfield background with visible objects.
- Fog is drawn using horizontal run-length spans for efficiency (consecutive unrevealed cells in a row are batched into a single rectangle).
- Once a cell is revealed, it remains revealed permanently for that session (and across saves).
- The player's own position and heading are always shown on the mini-map regardless of fog.
- Each frame, cells within `FOG_REVEAL_RADIUS` (400 px) of the player's position are marked as revealed.
- Fog is stored as a 128 x 128 boolean grid; each cell covers a 50 x 50 px area of the world.
