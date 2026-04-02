# Call of Orion --- Features

## Faction & Ship Selection

- Choose from 4 factions: **Earth**, **Colonial**, **Heavy World**, and **Ascended**
- Select from 5 ship types: Cruiser, Bastion, Aegis, Striker, Thunderbolt
- Ship previews and stat breakdowns shown on the selection screen
- Character selection with 3 unique characters (Debra, Ellie, Tara)
- Mouse and keyboard selection across all three phases

## Newtonian Flight Model

- Realistic thrust-based movement with inertia and space drag
- Per-ship physics: thrust, braking, rotation speed, max speed, and damping
- Coloured engine contrail particles unique to each ship type
- Seamless thruster engine sound loop while accelerating or braking
- **Sideslip**: Q slips left, E slips right (perpendicular to heading)
- Keyboard and Xbox 360 gamepad support

## Combat

- **Basic Laser** --- high-damage weapon for fighting enemies
- **Mining Beam** --- rapid-fire tool for harvesting asteroids
- Dual-gun ships fire from two laterally-offset hardpoints simultaneously
- Weapon cycling with Tab key or gamepad right bumper
- Camera shake and hit sparks on weapon impacts
- Shield system absorbs damage before HP; regenerates over time
- Animated energy shield bubble with hit-flash visual feedback
- Faction-specific shield colour tints

## Enemies --- Small Alien Ships

- 30 alien scout ships patrol the world with autonomous AI
- Two AI states: **Patrol** (lazy loops near spawn) and **Pursue** (chase and fire on detection)
- Obstacle-avoidance steering around asteroids and other aliens
- Physics-based collision bouncing between all entities
- Destroyed aliens drop iron ore and may drop blueprints
- Alien ships respawn every 1 minute until count is restored

## Boss Encounter

- Spawns when player reaches max level, equips all 4 modules, has 5+ repair packs, and a Home Station
- Appears at the farthest world corner from the station and heads toward it
- Large dramatic announcement with pulsing text on spawn
- Boss HP bar at top of screen showing HP, shields, and current phase
- 3-phase AI with escalating difficulty: main cannon + spread, charge attack, enraged mode
- Boss projectiles damage both the player and station buildings
- Drops 200 iron and 500 XP on defeat; does not respawn once defeated
- Full save/load support; appears as a large red marker on the minimap

## Mining & Resources

- 75 iron asteroids scattered across the world
- Mining Beam only --- Basic Laser has no effect on asteroids
- Asteroids spin, shake on hit, and explode with animated effects
- Iron pickups fly toward the player when nearby
- Asteroids respawn on a timer

## Inventory System

- 5x5 cargo hold grid toggled with I key or gamepad Y button
- Drag-and-drop with stacking, swapping, and world ejection
- Iron and repair packs display with dedicated icons and count badges
- **Consolidate** button merges stacks (respects max stack limits)
- Ejected items despawn after 10 minutes

## Ship Module System

- 4 module slots displayed above the quick-use bar
- 6 module types: Armor Plate, Engine Booster, Shield Booster, Shield Enhancer, Damage Absorber, Broadside Module
- Blueprint drops from aliens (50%) and asteroids (25%)
- Craft modules at the Basic Crafter after depositing blueprints
- Drag-to-equip with module slot management
- **Ship Stats panel** (C key) shows stats with module modifications
- **Character Bio panel** alongside Ship Stats with random portrait and backstory

## Space Station Building System

- Build menu (B key) with iron cost from ship + station inventory
- 8 module types with unique stats, costs, and placement rules
- Edge-to-edge docking port snap system
- Deconstruction mode with iron refund
- Turrets auto-target nearest alien within range
- Repair Module heals player HP and boosts shield regen
- Building hover tooltip shows type and HP
- Base capacity of 4, expandable with Solar Arrays

## Station Inventory & Crafting

- 10x10 station grid accessible by clicking the Home Station
- Drag items between station and ship inventories
- Basic Crafter produces Repair Packs and ship modules
- Recipes unlock permanently when blueprints are deposited

## Trading Station

- Spawns when the player builds their first Repair Module
- Sell items for credits; buy consumables with credits
- Shown on minimap as a bright yellow square

## Quick Use Bar

- 10 slots (1--9, 0) for fast item access
- Assign by dragging from inventory; use by pressing number keys
- Rearrange by dragging between slots; unassign by dragging out

## Save/Load System

- 10 named save slots with full game state preservation
- Save slots display faction, ship type, character, HP, shields, module count
- Overwrite warning and delete support (DEL key)
- Quick-use, module slots, boss state, and fog of war all persist

## HUD & Mini-Map

- Left-side status panel with HP/shield bars, character video, active weapon, faction/ship info
- FPS counter (toggle with F), music track name with equalizer visualizer
- Mini-map showing full world: player (white), asteroids (grey), pickups (orange), aliens (red), buildings (cyan), trading station (yellow), boss (large red)

## Fog of War

- World starts fully hidden; revealed as the player explores
- 800 px diameter reveal around the ship
- Grey fog overlay on mini-map; persists across save/load

## Character Video Player

- Looping 1:1 square character video portrait in the HUD
- GPU-side downscale via `glBlitFramebuffer` for high performance (~90 KB readback vs ~8 MB)
- Frame conversion throttled to 15 fps to maintain 50+ game FPS
- Choose character via **Video Properties** in the ESC menu
- Characters are video files (`Name.mp4`) in the `characters/` directory
- Video starts at a random position and loops seamlessly with a pre-built standby player

## Music Video Player

- Play video files in place of the background music soundtrack
- Video frame displayed as a small 16:9 panel in the HUD status panel, above the minimap
- **Supported formats**: MP4, AVI, WMV, M4V, 3GP, ASF, MKV, WebM, MOV, FLV, OGV
- **Requires FFmpeg** --- bundled DLLs in the project root (gitignored, ~220 MB)
- **Fullscreen or borderless mode required** --- Video button shows error in windowed mode
- **How to use**: ESC menu > Songs > Music Videos > configure a video directory, browse and select files
- Alternatively: ESC menu > Video to access the dedicated video file browser with scrollable list
- Click a video file to start playback (replaces background music); click **Stop Video** to stop
- Video loops automatically when it reaches the end
- Volume controlled by the Music volume slider
- Starting a video stops OST music and the equalizer visualizer
- Changing resolution preserves video playback state (video restarts automatically)
- Performance optimised: video frame cached and downscaled to 200 px wide; old GL textures removed from atlas to prevent VRAM accumulation
- `main.py` patches pyglet's clock to handle FFmpeg scheduling conflicts with Arcade

## Escape Menu

- Resume, Save/Load, Video Properties, Help, Songs, Main Menu
- Music/SFX volume sliders, resolution selector
- 10 save slots with naming overlay
- **Video Properties** --- resolution selector + character picker for the HUD video portrait
- **Songs** --- Stop Song, Other Song (random OST track), Music Videos (opens video browser)
- **Help** --- keyboard and gamepad controls display
- **Config** --- FPS toggle, volume sliders, video directory, autoplay OST toggle, Save Config

## Death & Respawn

- Dramatic destruction sequence with explosion and fire sparks
- Death screen with Load Game, Main Menu, and Exit Game options

## Audio

- Shuffled background music playlist (auto-advances on track end)
- Per-weapon sound effects with rapid-fire throttling
- Engine thruster loop, collision bumps, explosions
- Global volume controls in Options and ESC menu

## Visual Effects

- Animated explosion sprite sheets (9 frames)
- Hit sparks, fire sparks, shield hit flash
- Engine contrail particles (ship-type coloured)
- Shield enhancer rotating yellow ring
- Boss charge attack telegraph (pulsing white/blue, red dash)
