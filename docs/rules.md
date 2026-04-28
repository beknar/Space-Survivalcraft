# Call of Orion --- Game Rules & Mechanics

# Collisions & Projectiles

## Collision Rules

All circle-vs-circle collisions in the game share two physics primitives in `collisions.py`:

- **`resolve_overlap(a, b, ra, rb, push_a, push_b)`** computes the contact normal pointing from `b` toward `a`, pushes the bodies apart according to the per-body weights, and returns `(nx, ny)` (or `None` if there's no contact).
- **`reflect_velocity(obj, nx, ny, bounce)`** reflects a single body's velocity along that normal with restitution and returns the closing-speed dot.

The handlers below describe the per-pair `push_a` / `push_b` weights, restitution (`bounce`), and any custom impulse logic layered on top.


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
- Player cooldown: 0.5 s; alien cooldown: 0.40 s

### Player vs Boss
- 80/20 push-apart (player gets pushed more)
- 25 damage to player (5x normal collision)
- Boss barely bounces (0.3 restitution)
- Boss cooldown: 0.5 s

### Player vs Station Building
- Gentle push-out, no damage, no bounce, no sound

### Alien vs Asteroid
- Alien pushed fully away from static asteroid
- Velocity reflected off asteroid normal
- Orange bump flash

### Alien vs Alien
- 50/50 push-apart, equal-mass velocity exchange
- Both get orange bump flash

### Alien vs Station Building
- Alien pushed away, velocity reflected
- Orange bump flash

---

## Projectile Rules

### Player Projectile vs Asteroid (Mining Beam only)
- HitSpark at impact; 10 damage per hit
- Asteroid shake + orange-red tint flash
- On destruction: explosion + iron pickup spawn + XP

### Player Projectile vs Alien (Basic Laser only)
- HitSpark at impact; 25 damage per hit
- Camera shake; red tint flash on alien (0.15 s)
- On destruction: explosion + 5 iron drop + blueprint chance + 25 XP

### Player/Turret Projectile vs Boss
- HitSpark at impact; damage applied to shields first, then HP
- Camera shake on player hits
- On destruction: large explosion + 200 iron + 500 XP

### Alien Laser vs Player
- 10 damage (shields first, then HP)
- Camera shake + bump sound

### Alien Laser vs Station Building
- Building takes 10 damage per hit
- On destruction: explosion + iron drop (equal to build cost)
- Home Station destroyed: all modules disabled

### Boss Projectile vs Player
- Main cannon: 40 damage; Spread: 15 damage per projectile
- Camera shake + bump sound

### Boss Projectile vs Station Building
- Same damage as to player
- Building destruction rules same as alien laser

### Boss Charge Attack vs Player
- 60 damage + heavy knockback (400 px/s impulse)
- Only during dash phase (after 2s windup)

### Turret Projectile vs Alien
- HitSpark at impact; 10 damage per hit
- On destruction: same as player kill (iron + blueprint + XP)

---

# Damage, Death & Respawn

## Damage Flow

1. All damage routes through shields first
2. Shields absorb up to their remaining value; overflow carries into HP
3. Shield visual flashes bright on absorption
4. When hull takes direct damage, fire sparks emit from the ship
5. Damage Absorber module reduces incoming shield damage by 3

### Player Death
When HP reaches 0:
1. Large explosion (2.5x scale, orange-tinted) at ship position
2. 5 additional fire spark bursts
3. Ship and shield become invisible; thruster sound stops
4. **Loadout drop** — every cargo stack, every equipped module (as blueprint pickup), and every quick-use consumable spawns at the death site, scattered on a ring
5. **Bosses retreat** — both the Double Star and Nebula bosses flip `_patrol_home = True` and steer back toward their original spawn coordinates
6. **Aliens forget** — every alien across every zone (active + Zone 1 stash + Zone 2 stash + Star Maze) resets to PATROL with a new patrol target
7. After a 1.5 s death animation the player auto-respawns:
   - **Soft respawn** at the last visited Home Station with **50 % HP / 50 % shields** (inventory, modules, level, XP preserved). The "last visited" position is captured whenever the player clicks a Home Station to open the station inventory
   - **Hard reset** if no Home Station exists in any zone — fresh L1 `PlayerShip` of the player's chosen faction + ship type, placed at Zone 1 world centre with **25 % HP / 0 shields**. `_ship_level`, `_char_xp`, `_char_level`, `_ability_meter*`, and `_module_slots` all reset to first-game defaults; weapons reload off the new ship's gun count
8. Boss `_patrol_home` flag clears the first frame the respawned player re-enters priority range — re-engagement is automatic
9. The legacy death screen (Load Game / Main Menu / Exit Game) is no longer triggered by death; it remains available via the escape menu

---

## Respawn Rules

- Asteroids and aliens respawn every 60 s (one per cycle)
- Will not spawn within 300 px of any player building
- Must be at least 400 px from world centre, 100 px from edges
- Respawn effect: HitSpark flash + bump sound
- Boss does not respawn once defeated

---

# AI Behaviour

## Alien AI Behaviour

### PATROL State
- Circles a random point within 100--150 px of spawn position
- Picks new waypoint when within 8 px of current target
- Takes no hostile action

### PURSUE State
Triggered when player enters 500 px, or player weapon fires within 160 px (4x ship diameter):
- Ranged aliens orbit the player at ~300 px standoff distance instead of charging directly
- Each alien picks a random orbit direction (clockwise or counter-clockwise)
- Approaches if farther than 360 px, backs off if closer than 210 px, strafes laterally at range
- Always faces the player while orbiting
- Fires laser bolts every 1.5 s when player within 500 px
- Immediate first shot on detection
- Returns to PATROL when player exceeds 1,500 px (3x detection range)

### Obstacle Avoidance
- Asteroids and other aliens within avoidance radius (65 px beyond edge) exert repulsion
- Avoidance force weight: 2.5x, decreasing linearly with distance
- Combined steering vector normalised before movement

### Stuck Detection
- Every 2 s, if alien moved less than 10 px, it picks an escape target away from nearest asteroid

---

## Boss AI Behaviour

### Target Priority
- Heads toward the Home Station by default
- Engages the player if within 800 px detection range
- Does not leash --- once spawned, it never gives up

### Phase 1 (100%--50% HP)
- Main cannon (40 dmg, 1s cooldown, 700 px range)
- Spread shot (15 dmg x 3, 30-degree cone, 3s cooldown, 600 px range)
- Shield regeneration at 5/s
- Movement speed: 180 px/s, rotation: 60 deg/s

### Phase 2 (50%--25% HP)
- Adds charge attack: 2s windup telegraph (pulsing white/blue), then 0.8s dash at 600 px/s dealing 60 damage + knockback
- Speed increases to 220 px/s
- Shield regeneration doubles to 10/s
- Charge cooldown: 8 s

### Phase 3 (Below 25% HP)
- Enraged: all weapon cooldowns halved (0.5s cannon, 1.5s spread)
- Shield regeneration stops entirely
- Permanent red tint visual

---

# Stations & Buildings

## Building Placement Rules

- **Home Station** must be built first; all other modules require it
- **Connectable modules** snap to docking ports (N/S/E/W) within 40 px
- **Edge-to-edge snap**: modules sit adjacent, not overlapping
- **Post-placement connectivity**: remaining ports auto-connect to nearby modules
- **Overlap prevention**: cannot place within 60 px of existing buildings
- **Turrets and Missile Arrays** freely placed within 300 px (`TURRET_FREE_PLACE_RADIUS`) of Home Station (no docking)
- **Long-press LMB (>= 0.4 s) on an existing Turret or Missile Array** enters move mode; the building follows the cursor clamped to within 300 px of the Home Station. Release drops it (overlap-checked); a short click does nothing; ESC snaps back to the original position
- Mouse wheel rotates during placement; ESC cancels
- Destroying Home Station disables all modules
- **Advanced Ship** uses placement mode with the next-level ship texture as ghost; places a new ship and leaves the old one as a ParkedShip

### Parked Ship Rules
- Old ships persist in the world with their own HP, shields, cargo, and modules
- Click a parked ship within 300 px to switch control (inventory/modules/weapons swap)
- Parked ships take damage from alien lasers, boss projectiles, and player weapons
- Destroyed ships drop cargo as iron/copper pickups and modules as blueprint pickups
- Parked ships are stashed during zone transitions and serialized in save/load

### Module Capacity
- Base: 4 (from Home Station)
- Solar Array 1: +6 each (max 2)
- Solar Array 2: +10 each (max 2)
- Turret 2 uses 2 slots; all others use 1

---

# World & Zones

## Fog of War

- World starts fully hidden; cells revealed within 400 px of the player
- 128 x 128 grid (50 px per cell) covering the full world
- Objects hidden on minimap until their cell is revealed
- Once revealed, a cell stays revealed permanently (persists across saves)
- Player position always shown regardless of fog

---

## Warp Zone Rules

- Warp zones appear after the originating zone's boss is defeated
- 4 themes (Meteor, Lightning, Gas, Enemy Spawner) × 3 variants:
  - **Zone-1 originals (`WARP_*`)** — top exit → Zone 2
  - **Nebula post-boss (`NEBULA_WARP_*`)** — 2× danger scalar, top exit → Star Maze
  - **Star-Maze (`MAZE_WARP_*`)** — exit returns to the Star Maze
- **Red walls** line warp zone boundaries; contact drains shields continuously
- **Bottom exit** provides a safe return to the originating zone
- Player position and inventory are preserved across zone transitions
- Buildings placed in Zone 2 are preserved when travelling through warp zones and back
- Gas hazards in the Gas Cloud warp zone are always visible on the minimap regardless of fog of war

---

## Background Zone Simulation

- Optional "Simulate All Zones" toggle in Config (disabled by default)
- When enabled, inactive zones are ticked every frame while the player is in a different zone
- Respawn timers advance; asteroids and aliens are replenished
- Aliens revert to PATROL state and wander toward patrol waypoints
- No player interaction, sounds, or visual effects --- purely simulation
- Station Info panel (T key) shows live entity counts from inactive zones

---

## Star Maze (Zone 3) Rules

### Layout & Containment
- 4 maze structures at `STAR_MAZE_CENTERS` (corners + centre) inside a 12000×12000 zone
- Each maze: 5×5 rooms (300 px interior, 32 px walls), carved by recursive-backtracking DFS seeded off the world seed
- Outside the maze rectangles the zone hosts the same Nebula content as Zone 2 (asteroids, gas, wanderers, Z2 aliens, null fields, slipspaces)
- Population uses radius-aware reject filters that keep entities out of every maze AABB
- Non-maze enemies that drift into a maze get pushed back out via `_push_out_of_maze_bounds`
- Misty Step rejects teleports whose path crosses a wall (samples every 16 px)

### Maze Spawner
- Stationary turret in the centre of every room; 100 HP + 100 shields
- Fires a 30-damage laser at the player within 300 px every 1.0 s
- Spawns one MazeAlien every 30 s up to a cap of 20 alive children
- Killed: drops 1000 iron + 100 XP; respawns to full HP/shields after 90 s (alive children carry over)
- Sprite is hidden while killed and reappears on respawn
- Position is **deterministically derived from the world seed**, NOT from save data — restoring a save with stale spawner positions is no longer possible

### Maze Alien
- 50 HP, 30 XP, 10 iron drop on kill
- 120 px/s movement, 20 px collision radius
- Fires a 10-damage laser every 1.5 s within 300 px and 200 px range
- **A* pathfinding**: when the player is in a different room, the alien plans through the room-adjacency graph (`zones/maze_geometry.astar_room_path`) and steers toward the next waypoint instead of bee-lining
- Per-frame moves are checked against a wall spatial-hash and reverted if they would cross a wall; T-intersection corners use a 5-iter push-out loop

---

## Nebula Boss Rules

- Spawned by building the **Quantum Wave Integrator** in Zone 2 (1000 iron + 2000 copper)
- Larger sprite (3× scale, 114 px collision radius); randomised across 8 sprite rows of column 2
- Detection range 1000 px; prioritises the player over buildings
- **Cannon**: 40 damage, 1.0 s cooldown, 800 px range
- **Gas cloud**: 30 damage at 275 px/s; on hit applies a 1.5 s ×0.5 player-speed slow; 60 px collision radius; 4.0 s cooldown
- **Cone attack**: 400 px-long × 200 px-wide; 1.5 s active, 6.0 s cooldown; 20 damage per 0.5 s tick while the player is inside
- **Movement**: routes around force walls instead of grinding on them; rams through asteroids and drops normal alien-style loot along the way
- **Targeted by**: station turrets, missile arrays, and AI-piloted parked ships
- **Reward**: 3000 iron + 1000 copper, no XP
- **Resummon**: clicking the QWI within 300 px after the boss is defeated charges 100 iron and respawns the boss

---

## Null Field Rules

- 30 stealth patches per non-warp zone; sized between 128 px and 256 px diameter
- While the player is inside any active field, AI targeting treats them as **invisible** (`gv._player_cloaked` flag is set)
- All Zone 2 alien classes and the Star Maze MazeAlien/MazeSpawner honour the cloak (Star Maze checks the flag in both `_update_maze_aliens` and `_update_spawners`)
- Firing **any** weapon from inside a field **disables that field** for `NULL_FIELD_DISABLE_S` (10 s) and flashes it red; the field re-enables after the timer elapses
- Disabled fields no longer cloak; surfaced on the Station Info "Other Zones" panel
- Persisted in save/load (per-zone state)

---

## Slipspace Rules

- 15 paired teleport portals per non-warp zone
- Display 160 px / collision 60 px (the player must fly visually into the swirl, not just brush its outer edge)
- On entry: player is teleported to the paired exit and **velocity is conserved** (the player exits with the same momentum they entered with)
- Rotation 90 deg/s; minimap-marked
- Persisted in save/load

---

## Zone 2 Hazard Rules

### Toxic Gas Clouds
- Contact deals continuous damage (shields first, then HP)
- Reduces player movement speed by 50% while inside the cloud
- Gas clouds are stationary environmental hazards

### Wandering Magnetic Asteroids
- Drift through space with random wander, changing direction every 1--3 seconds
- Exert a magnetic pull on nearby ships within 80 px (WANDERING_MAGNET_DIST)
- Pull speed: 200 px/s when attracted (WANDERING_MAGNET_SPEED)
- **Collision with player**: 60/40 push-apart (player pushed more), velocity bounce with 0.55 restitution, 15 damage, wanderer kicked away from player for 1.5 s
- Can be destroyed with the Mining Beam but yield no resources
- Offscreen wanderers only spin (viewport culling optimisation)

---

## Zone 2 Alien Combat & Collision Rules

### Shielded Alien
- Orbits the player at ~300 px standoff distance while firing
- Shields absorb damage before HP (50 shield points)
- Same collision physics as standard aliens

### Fast Alien
- Orbits the player at ~300 px, flips orbit direction unpredictably on a 0.8--2.0 s timer
- Higher speed (160 px/s) makes it harder to track
- Same collision physics as standard aliens

### Gunner Alien
- Orbits the player at ~300 px standoff distance
- Fires from 2 guns simultaneously (double projectile output)
- Same collision physics as standard aliens

### Rammer Alien
- No guns --- charges directly at the player at 1.5x speed when in pursuit
- 100 HP + 50 shields makes it the toughest standard alien
- Collision deals 5 damage (same as standard alien collision)

---

# Player Abilities

## Special Ability Meter Mechanics

- Maximum capacity: 100 ability points
- Regenerates at 5 points per second passively
- Meter is displayed on the HUD alongside HP and shields
- Abilities cannot be used if insufficient ability points remain
- Meter persists across save/load

---

## Misty Step Mechanics

- Activated by double-tapping W, A, S, or D (within 0.3s)
- Teleports the player 100 px in the tapped direction
- Costs 20 ability points per use
- Requires the Misty Step module to be equipped
- Brief invincibility during the teleport (0.1s)
- Cannot teleport through world boundaries

---

## Force Wall Mechanics

- Activated by pressing G (2-second cooldown)
- Deploys a 400 px-wide shimmering barrier behind the ship,
  perpendicular to the ship's heading
- Costs 30 ability points per use
- Requires the Force Wall module to be equipped
- Lifetime: 20 seconds, with shimmering alpha falloff
- Blocks alien projectiles and boss projectiles — each hit is absorbed
  and spawns a hit spark
- Aliens steer around the wall via an extra 2× repulsion term in their
  avoidance; any movement segment that would cross the wall is reverted
  to the alien's pre-move position (hard block)
- Rammer aliens' charge path is clipped the same way
- Multiple walls can be active at once (the oldest drops first when its
  20 s lifetime expires)

---

## Death Blossom Mechanics

- Activated by pressing X
- Fires all currently held homing missiles in a radial burst pattern
- Requires the Death Blossom module to be equipped
- Each missile deals 50 damage with homing AI
- Missiles spread evenly in a 360-degree pattern
- No ability point cost --- consumes missile ammunition instead

---

# Modules & Defences

## AI Pilot Module

- Craftable at the Advanced Crafter for 800 iron + 400 copper
- Installed by dragging `mod_ai_pilot` from station inventory onto a
  parked ship's module slot
- On install the ship immediately enters **patrol** mode — counter-clockwise
  circular orbit at 90 % of `AI_PILOT_PATROL_RADIUS` (360 px) around the
  Home Station
- **Engage**: any live alien/boss within `AI_PILOT_DETECT_RANGE`
  (600 px) that is also inside the patrol leash is targeted; the ship
  faces it, closes to ~60 % of detect range, and fires a turret laser
  every `AI_PILOT_FIRE_COOLDOWN` (0.5 s) for
  `AI_PILOT_LASER_DAMAGE` (10)
- **Return**: if the ship fires at a target and no OTHER live targets
  remain in detect range, `_ai_mode` flips to `return`; the ship heads
  in a straight line back to the Home Station until within
  `AI_PILOT_HOME_ARRIVAL_DIST` (100 px), at which point patrol resumes
- A new target appearing during return instantly re-engages; the leash
  clamp still applies every tick so the ship can never leave patrol
  radius
- Shots are injected into `gv.turret_projectile_list` so the existing
  turret-projectile collision handler delivers the damage

---

## Station Shield

- **Spawn trigger**: the first `Shield Generator` placed while a Home
  Station exists spawns a faction-tinted `ShieldSprite` centred on the
  Home Station with `STATION_SHIELD_HP` (100)
- **Radius**: `station_outer_radius(home) + STATION_SHIELD_PADDING`
  (80 px), recomputed every tick so it grows with the station.
  `station_outer_radius` counts each building's edge (centre distance
  + `BUILDING_RADIUS`, 30 px)
- **Damage absorb**: `collisions._station_shield_absorbs` runs before
  alien-laser-vs-building and boss-projectile-vs-building collision.
  Any enemy projectile within the shield disk has its `damage` bled
  from `_station_shield_hp`, is consumed, and triggers a hit-flash.
  Buildings only take damage once shield HP hits zero
- **Rendering**: the `ShieldSprite` is drawn at alpha 15 (interior
  glow only) and a solid 3 px `arcade.draw_circle_outline` at the
  shield radius is layered on top — alpha 200 idle, spiking to 255
  during the 0.2 s hit-flash. A second 2 px ring 4 px inside the
  border at 1/3 alpha adds a subtle edge glow
- **Persistence**: `station_shield_hp` + `station_shield_max_hp` are
  serialised; restore re-materialises the sprite on the next
  `update_station_shield` tick as long as a Shield Generator is
  still present

# Story

## Story Encounter — Double Star Refugee

- **Spawn trigger**: placing the first `Shield Generator` in Zone 2
  while a Home Station exists spawns `RefugeeNPCShip` once per save
- Spawns at the right edge of the Nebula, flies toward a **parking
  spot** at `(home.x + station_outer_radius + 120, home.y)` at
  `NPC_REFUGEE_APPROACH_SPEED` (140 px/s), and holds when within 24 px
  of that spot. `station_outer_radius` measures from the Home Station
  to the furthest building's *edge* (distance to centre plus
  `BUILDING_RADIUS`, 30 px), so the ship never overlaps any building
  regardless of station size
- Invulnerable (take_damage is a no-op); hovering surfaces the
  "Double Star Refugee" label
- Left-clicking the ship while the player is within
  `NPC_REFUGEE_INTERACT_DIST` (320 px) opens a character-specific
  dialogue tree (see `dialogue/` package). Debra's tree has full
  multi-scene branching; Ellie/Tara currently have placeholder trees
- Dialogue overlay: numeric keys (1-9) or mouse click select choices;
  SPACE or click advances linear beats; ESC closes without committing
  aftermath. Closing via a terminal `end` node merges `aftermath` flags
  into `gv._quest_flags`
- Refugee position, spawn flag, met flag, and quest_flags are all
  persisted in save/load
