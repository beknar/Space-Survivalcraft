# Call of Orion --- Game Rules & Mechanics

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
4. After 1.5 s delay, death screen appears
5. Options: Load Game, Main Menu, Exit Game

---

## Alien AI Behaviour

### PATROL State
- Circles a random point within 100--150 px of spawn position
- Picks new waypoint when within 8 px of current target
- Takes no hostile action

### PURSUE State
Triggered when player enters 500 px, or player weapon fires within 160 px (4x ship diameter):
- Chases player at 120 px/s with obstacle avoidance
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

## Building Placement Rules

- **Home Station** must be built first; all other modules require it
- **Connectable modules** snap to docking ports (N/S/E/W) within 40 px
- **Edge-to-edge snap**: modules sit adjacent, not overlapping
- **Post-placement connectivity**: remaining ports auto-connect to nearby modules
- **Overlap prevention**: cannot place within 60 px of existing buildings
- **Turrets** freely placed within 300 px of Home Station (no docking)
- Mouse wheel rotates during placement; ESC cancels
- Destroying Home Station disables all modules

### Module Capacity
- Base: 4 (from Home Station)
- Solar Array 1: +6 each (max 2)
- Solar Array 2: +10 each (max 2)
- Turret 2 uses 2 slots; all others use 1

---

## Respawn Rules

- Asteroids and aliens respawn every 60 s (one per cycle)
- Will not spawn within 300 px of any player building
- Must be at least 400 px from world centre, 100 px from edges
- Respawn effect: HitSpark flash + bump sound
- Boss does not respawn once defeated

---

## Fog of War

- World starts fully hidden; cells revealed within 400 px of the player
- 128 x 128 grid (50 px per cell) covering the full world
- Objects hidden on minimap until their cell is revealed
- Once revealed, a cell stays revealed permanently (persists across saves)
- Player position always shown regardless of fog

---

## Warp Zone Rules

- Warp zones appear after the boss is defeated
- 4 types: Meteor, Lightning, Gas, Enemy Spawner --- each with unique hazards
- **Red walls** line warp zone boundaries; contact drains shields continuously
- **Bottom exit** provides a safe return to Zone 1 (home sector)
- **Top exit** transitions the player into Zone 2 (The Nebula)
- Player position and inventory are preserved across zone transitions

---

## Zone 2 Hazard Rules

### Toxic Gas Clouds
- Contact deals continuous damage (shields first, then HP)
- Reduces player movement speed by 50% while inside the cloud
- Gas clouds are stationary environmental hazards

### Wandering Magnetic Asteroids
- Drift through space on fixed paths
- Exert a magnetic pull on nearby ships within 200 px
- Pull strength increases as distance decreases
- Can be destroyed with the Mining Beam but yield no resources

---

## Zone 2 Alien Collision Rules

### Shielded Alien
- Same collision rules as standard aliens
- Shields absorb damage before HP (50 shield points)

### Fast Alien
- Same collision rules as standard aliens
- Higher speed (160 px/s) means stronger collision impulse

### Gunner Alien
- Same collision rules as standard aliens
- Fires from 2 guns simultaneously (double projectile output)

### Rammer Alien
- Initiates a charge when player is within 300 px
- Charge collision deals 25 damage (5x normal alien collision)
- 100 HP + 50 shields makes it the toughest standard alien

---

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

- Activated by pressing G
- Deploys a 100 px-wide barrier in front of the ship
- Costs 30 ability points per use
- Requires the Force Wall module to be equipped
- Barrier blocks enemy projectiles and alien movement
- Barrier lasts 5 seconds before dissipating
- Only one Force Wall can be active at a time

---

## Death Blossom Mechanics

- Activated by pressing X
- Fires all currently held homing missiles in a radial burst pattern
- Requires the Death Blossom module to be equipped
- Each missile deals 50 damage with homing AI
- Missiles spread evenly in a 360-degree pattern
- No ability point cost --- consumes missile ammunition instead
