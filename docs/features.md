# Call of Orion --- Features

## Faction & Ship Selection

- Choose from 4 factions: **Earth**, **Colonial**, **Heavy World**, and **Ascended**
- Select from 5 ship types: Cruiser, Bastion, Aegis, Striker, Thunderbolt
- Ship previews and stat breakdowns shown on the selection screen
- Character selection with 3 unique characters (Debra, Ellie, Tara), each with 10 levels of progression
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
- Two AI states: **Patrol** (lazy loops near spawn) and **Pursue** (orbit at standoff range and fire)
- Ranged aliens orbit the player at ~300 px instead of charging; each picks a random orbit direction
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

## Warp Zones

- 4 warp zone types: **Meteor**, **Lightning**, **Gas**, and **Enemy Spawner**
- Appear after the boss is defeated, providing access to Zone 2
- Red walls line the warp zone boundaries and drain shields on contact
- Bottom exit provides a safe return to Zone 1
- Top exit transitions the player into Zone 2 (The Nebula)

## Zone 2 --- The Nebula

- New biome with a nebula-themed starfield background
- **Copper asteroids** --- new resource type, mineable with the Mining Beam
- **Double iron asteroids** --- tougher asteroids that yield twice the iron
- **Toxic gas clouds** --- environmental hazards that damage and slow the player on contact
- **Wandering magnetic asteroids** --- asteroids that drift through space and attract nearby ships; bounce off the player on contact with knockback physics
- 4 new alien types with unique abilities:
  - **Shielded Alien** --- comes with 50 shields for extra durability; orbits at range
  - **Fast Alien** --- moves at 160 px/s, harder to hit and outrun; flips orbit direction unpredictably
  - **Gunner Alien** --- equipped with 2 guns for double the firepower; orbits at range
  - **Rammer Alien** --- 100 HP + 50 shields, charges directly toward the player (no guns)

## Advanced Modules

- **Misty Step** --- double-tap WASD to teleport 100 px in that direction; costs 20 ability points
- **Force Wall** --- press G to deploy a 400 px shimmering barrier behind the ship; costs 30 ability points. Blocks enemy lasers and boss projectiles on contact; aliens steer around the wall and cannot cross it (any movement that would cut through the wall is reverted)
- **Death Blossom** --- press X to fire all homing missiles in a radial burst

## Homing Missiles

- Consumable ammunition with homing AI that tracks the nearest enemy
- Deals 50 damage per missile on impact
- Craftable at the Advanced Crafter

## Special Ability Meter

- Maximum capacity of 100 ability points
- Regenerates at 5 points per second
- Powers the advanced modules (Misty Step, Force Wall, Death Blossom)

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
- 12 module types: Armor Plate, Engine Booster, Shield Booster, Shield Enhancer, Damage Absorber, Broadside Module, Misty Step, Force Wall, Death Blossom, Missile Rack, Ability Capacitor, Hull Reinforcement
- Blueprint drops from aliens (50%) and asteroids (25%)
- Craft modules at the Basic Crafter after depositing blueprints
- Drag-to-equip with module slot management
- **Ship Stats panel** (C key, 380x520) shows stats with module modifications and all character benefits up to level 10
- **Character Bio panel** (360x520) alongside Ship Stats with random portrait and backstory

## Multi-Ship System

- **Ship upgrades via build menu** --- "Advanced Ship" enters placement mode with the next-level ship texture as a ghost; place near the station to upgrade
- **Old ship persists** --- the previous ship stays in the world as a `ParkedShip` with its own HP, shields, cargo, and module slots
- **Click to switch** --- fly near a parked ship and left-click to transfer control; inventory, modules, weapons, and ability meter all swap
- **Damage from any source** --- parked ships take damage from alien lasers, boss projectiles, and player weapons (friendly fire)
- **Destruction drops** --- destroyed ships drop cargo as iron/copper pickups and equipped modules as blueprint pickups
- **Minimap markers** --- parked ships shown as teal dots on the minimap
- **Hover tooltip** --- hovering a parked ship surfaces "Level N Ship (HP X/Y) — Click to board"
- **AI Pilot module** --- craft an `AI Pilot` at the Advanced Crafter (800 iron + 400 copper) and drag-install it onto any parked ship. The ship then patrols within 400 px of the Home Station, engages enemies inside 600 px, fires a laser every 0.5 s into the turret-projectile list (so existing turret damage handling applies), and snaps back to the leash if it drifts too far
- **Zone-aware** --- parked ships stashed/restored during zone transitions and fully serialized in save/load

## Space Station Building System

- Build menu (B key) with iron cost from ship + station inventory
- 8 module types with unique stats, costs, and placement rules
- Edge-to-edge docking port snap system
- Deconstruction mode with iron refund
- Turrets auto-target nearest alien within range
- Missile Arrays auto-fire homing missiles at aliens within 600 px
- Repair Module heals player HP and boosts shield regen
- Building hover tooltip shows type and HP
- **Long-press LMB on a Turret or Missile Array** to drag-move it; clamped to within 300 px of the Home Station and overlap-checked against other buildings
- Base capacity of 4, expandable with Solar Arrays

## Station Inventory & Crafting

- 10x10 station grid accessible by clicking the Home Station
- Drag items between station and ship inventories
- Basic Crafter produces Repair Packs and ship modules
- Recipes unlock permanently when blueprints are deposited

## Trading Station

- Spawns when the player builds their first Repair Module
- Sell items for credits; buy consumables with credits
- Sell panel scrolls (with a visible scrollbar thumb) when the
  sellable-item list exceeds the visible rows
- Hold LMB on a sell row to tick off one unit every 0.15 s
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
- Mini-map showing full world: player (white), asteroids (grey), pickups (orange), aliens (red), buildings (cyan), trading station (yellow), boss (large red), gas areas (green octagonal outlines, proportional to world size), wormholes (purple)
- Gas hazards in warp zones always visible on minimap regardless of fog of war
- **Station Info** (T key) --- building HP, module capacity, zone-specific entity counts, plus an "Other Zones" panel showing live stats from inactive zones (Double Star and/or Nebula)

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
- **Config** --- FPS toggle, Simulate All Zones toggle, volume sliders, video directory, autoplay OST toggle, Save Config

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
