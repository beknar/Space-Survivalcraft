# Planets & Planetary Encounters — Design Document

> **Status:** Design / pre-implementation spec.
> **Scope:** Everything related to planets — reaching them, the aerial
> landing scene, the on-foot surface scene, surface progression,
> planetary items, ability modules, consumables, buildings, and
> resource nodes.
>
> This document merges the original `planets.md` (landing pipeline +
> surface HUD) with the *Planet Encounters Preliminary Design* notes
> (surface gameplay). Asset paths are quoted verbatim from the design
> notes; spelling has been normalized for readability. Suspect/
> inconsistent values are collected in **Appendix A — Design Review
> Flags** rather than silently changed.

---

## 1. Concept Overview

The planet feature adds a two-stage descent and an on-foot survival
loop layered on top of the existing ship game:

```
Ship in space ──(ram planet w/ Landing Adaptation)──▶ Aerial Landing Scene
Aerial Landing Scene ──(exit top edge)──▶ Planet Surface Scene (on-foot)
Planet Surface Scene ──(die / leave)──▶ back to originating space zone
```

- **In space** you fly a ship (existing game).
- **The Landing Scene** is a vertical shmup-style descent through the
  atmosphere with airborne enemies.
- **The Surface Scene** is a top-down, on-foot mode where the
  character walks, fights with personal weapons, mines resources,
  and builds a planetary base.

---

## 2. Progression & Zone Level Caps

Character level is a single global track. The maximum reachable level
is gated by the deepest zone the player has unlocked:

| Zone | Character level cap |
|---|---|
| Double Star (Zone 1) | 10 |
| Nebula (Zone 2) | 20 |
| Star Maze (Zone 3) | 30 |

- **Levels 1–10** are the existing space progression (see
  `character_data.py`).
- **Levels 11–20** unlock in the Nebula and lean toward
  space/gas-survival bonuses.
- **Levels 21–30** unlock in the Star Maze and lean toward
  **planetary** bonuses (surface HP/armor, on-foot tools, planetary
  item/building economy).

Per-character benefit tables for levels 11–30 are in
**Section 7 — Surface Character Progression**.

---

## 3. Technology — Planetary Landing Adaptation (Ship Module)

A new installable ship module sold in the Advanced Crafter menu. It
lets a ship enter the planetary landing scene on contact with a
planet instead of taking collision damage.

| Property | Value |
|---|---|
| Source | Advanced Crafter menu |
| Cost | 500 iron + 500 copper |
| Slot | Standard ship module slot |
| Icon asset | `assets/11 Scifi Icons Pack/128x128/Battery-128x128.png` |
| Without module | On planet contact: 25 % shield damage + 25 % HP damage |
| With module | On planet contact: transitions to the matching planetary landing scene |

---

## 4. Planets (Space World Objects)

Planets are world objects in the Star Maze zone (and future zones).
They have their own collider, so enemies and drones must path around
them or take damage on contact.

### Behavior on contact

| Player state | Result |
|---|---|
| No Planetary Landing Adaptation installed | Ship takes 25 % shield damage + 25 % HP damage (repeated contact eventually destroys the ship) |
| Adaptation installed | Game transitions to the planet's landing scene |

### Planet Types

| Type | Asset | Appears in |
|---|---|---|
| **Earth planet** | `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/Planets/Planets/planet03.png` | Star Maze (first planet found) |
| **Frost planet** | `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/Planets/Planets/planet07.png` | TBD |
| **Barren planet** | `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/Planets/Planets/planet04.png` | TBD |

The surface scene loaded when the player leaves through the top of the
landing scene depends on the planet type.

---

## 5. Planetary Landing Scene (Aerial Descent)

A vertical scene reached by ramming an unlocked planet with the
Planetary Landing Adaptation module installed.

### Layout

| Property | Value |
|---|---|
| Scene size | Same as a warp zone (3,200 × 6,400 px) |
| Player spawn | Bottom edge of the map |
| Bottom edge re-touch | Respawn back into the originating zone (e.g. Star Maze for an Earth planet entered from the Star Maze) |
| Top edge exit | Loads the planet surface scene (type-specific) |
| Left / right edge | Ship takes 25 % shield damage + 25 % HP damage |
| Background asset | `assets/SBS - Seamless Sky Backgrounds - 1024x512/1024x512/Cloudy Sky/Cloudy_Sky-Blue_01-1024x512.png` |

### Enemies

Each landing scene populates with three enemy types at the counts
below.

| Enemy | Count | HP | Shield | Shield Chance | Speed | Weapon | Weapon Damage | Detect | Drops | XP |
|---|---|---|---|---|---|---|---|---|---|---|
| **Sky Worm**     | 20 | 50 | 50 | 35 % | 120 px/s | T-Laser       | 20 | 300 px | None | 35 |
| **Cloud Drone**  | 20 | 60 | 60 | 35 % | 120 px/s | X-Blast       | 30 | 300 px | None | 45 |
| **Thunder Worm** | 20 | 70 | 0  | —    | 150 px/s | Double Laser  | 40 | 200 px | None | 45 |

#### Weapon assets

| Weapon | Asset |
|---|---|
| T-Laser      | `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserBlue04.png` |
| X-Blast      | `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserRed09.png` |
| Double Laser | `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserBlue09.png` |

#### Special behaviors

- **Thunder Worm — Double Laser**: fires two projectiles at once per
  cooldown.

---

## 6. Planet Surface Scene (On-Foot)

Reached by exiting the landing scene through the top edge. Top-down,
on-foot control of the character.

- **Soft respawn:** if the player has built a **Home Base**, death on
  the surface respawns them there; otherwise they respawn at a random
  surface location.
- The build menu (`B`) on the surface builds **planetary buildings**
  (Section 10), distinct from the space build menu.

### 6.1 Surface HUD

Mirrors the ship HUD layout with planet-specific elements.

| Element | Source |
|---|---|
| Character video panel | Replaces the ship HUD's character animation; uses the planet-surface animation set (below) |
| Character name | Shown directly below the video panel |
| HP bar | Below the character name (same widget as the ship HUD) |
| Ability meter | Below the HP bar (same widget as the ship HUD) |

#### Character Animations

| Property | Value |
|---|---|
| Source directory | `assets/ai generated/planetary/character-animation/` |
| Filename | `<CharacterName>.mp4` — e.g. `Debra.mp4` |
| Lookup | Picked at scene load from the active character (`audio.character_name`) |

#### Playback Algorithm

The planet-surface HUD video uses a hybrid of fixed-start playback and
discrete random-seek windows, layered over the same seamless
standby-player loop used by the ship-HUD character video
(`video_player.VideoPlayer.play_segments` → `_build_standby` →
`_restart_for_loop`).

1. On load, start playing from `0:00`.
2. After 10 seconds of playback, seek to a random offset chosen
   uniformly from `{0:00, 10:00, 20:00, 30:00, 40:00}`.
3. Continue forward playback from the chosen offset.
4. When the source is exhausted, seamlessly swap to the pre-built
   standby player and restart the cycle (steps 1–3 repeat).

The seamless-loop machinery (`_build_standby` background load ~5 s
before end of source, main-thread swap on exhaustion) is inherited
unchanged from the ship-HUD video pipeline. Only the initial seek
behavior at the 10-second mark is added on top.

### 6.2 Armor Mechanic (Surface)

Armor works differently from shields:

- It **prevents a flat amount of damage** equal to its score on every
  hit.
- It **never depletes** — unlike shields, which drain and regenerate.
- Example: Armor score **1** prevents **1 point** of damage per hit.

### 6.3 Surface Character Base Stats

Common to all characters unless noted:

| Stat | Value |
|---|---|
| Base HP | 100 |
| Base Armor | 1 |
| Base speed | 250 px/s |
| Wearable module slots | 4 |
| Electron-sword deflect chance | 50 % |
| Basic laser rifle cooldown | 0.30 s |
| Basic laser rifle range | 600 px |

Per-character combat/mining values:

| Character | Class | Laser rifle dmg | Electron sword melee | Mining beam (dmg / iron) | Electron pick axe (dmg / iron) |
|---|---|---|---|---|---|
| **Debra** | Miner   | 10 | 20 | 5 / 2 | 10 / 3 |
| **Ellie** | Fighter | 15 | 25 | 3 / 2 | 6 / 3 |
| **Tara**  | Builder | 10 | 20 | 5 / 2 | 10 / 3 |

> *Mining beam* damage and pick-axe damage values are **vs. rocks**;
> the iron figure is iron gathered per hit.

### 6.4 On-Foot Arsenal (shared assets)

All three characters share the same weapon/tool assets; only the
numbers in 6.3 differ.

| Item | Type | Visual asset | Effect / projectile asset | Sound asset |
|---|---|---|---|---|
| **Basic Laser Rifle** | Ranged | `assets/scifi-space-station-items-assets/individual/weapons/scifi_weapons_02_007.png` | `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserBlue02.png` | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Energy Weapons/Sci-Fi Laser Weapon Ricochet 2` |
| **Electron Sword** | Melee (50 % deflect) | `assets/scifi-space-station-items-assets/individual/weapons/scifi_weapons_01_003.png` | — | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Electrical Weapons/Sci-Fi Electrical Weapon Shot 1.wav` |
| **Portable Mining Beam** | Tool (vs rocks) | `assets/scifi-space-station-items-assets/individual/tools/scifi_tools_01_008.png` | — | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Machinery/Sci-Fi Dieselpunk Big Clunky Machinery 1 Loop.wav` |
| **Electron Pick Axe** | Melee tool (vs rocks) | `assets/ai generated/planetary/weapons/electron-axe.png` | — | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Electrical Weapons/Sci-Fi Large Electrical Cannon Shot 2.wav` |

**Rendering note:** the basic laser rifle is drawn **in front of the
character** in whatever direction the character is moving/facing
(left, right, up, or down).

---

## 7. Surface Character Progression (Levels 11–30)

Levels 11–20 unlock in the Nebula; levels 21–30 unlock in the Star
Maze and are planetary-focused. XP values are cumulative thresholds.

### 7.1 Debra — the Miner

| Lvl | XP | Benefit |
|---|---|---|
| 11 | 8,300  | −10 % damage from gas areas; +40 iron from all sources |
| 12 | 9,700  | −20 % damage from gas areas; +30 copper from all sources |
| 13 | 11,200 | −30 % damage from gas areas; +50 iron from all sources |
| 14 | 12,800 | −40 % damage from gas areas; +40 copper from all sources |
| 15 | 14,500 | −10 % slowdown from gas areas; +60 iron from all sources |
| 16 | 16,300 | −20 % slowdown from gas areas; +50 copper from all sources |
| 17 | 18,200 | −30 % slowdown from gas areas; +10 mining-drone damage to asteroids |
| 18 | 20,200 | −40 % slowdown from gas areas; +20 mining-drone damage to asteroids |
| 19 | 22,300 | −40 % damage **and** slowdown from gas areas; +20 mining-drone damage to asteroids |
| 20 | 24,600 | −50 % damage **and** slowdown from gas areas; +20 mining-drone damage to asteroids |
| 21 | 27,100 | +20 px resource pickup range; planetary HP +10 |
| 22 | 29,800 | +30 px resource pickup range; planetary Armor +1 |
| 23 | 32,800 | +40 px resource pickup range; planetary HP +20 |
| 24 | 36,100 | +50 px resource pickup range; planetary Armor +2 |
| 25 | 39,700 | +10 mining-beam dmg vs rocks (planet); +1 wearable module slot |
| 26 | 43,600 | +10 electron-axe melee dmg vs rocks (planet) |
| 27 | 47,800 | +15 mining-beam dmg vs rocks (planet) |
| 28 | 52,300 | +15 electron-axe melee dmg vs rocks (planet) |
| 29 | 57,100 | +20 to **both** mining-beam and electron-axe vs rocks (planet) |
| 30 | 62,300 | planetary HP +15, Armor +3; +2 wearable module slots |

### 7.2 Ellie — the Fighter

| Lvl | XP | Benefit |
|---|---|---|
| 11 | 10,300 | Null field keeps working an extra 5 s after firing, then stops |
| 12 | 11,900 | Null field keeps working an extra 10 s after firing, then stops |
| 13 | 11,200 ⚠️ | Electron-sword deflection now 55 % |
| 14 | 13,500 | Electron-sword deflection now 60 % |
| 15 | 14,500 | Electron-sword deflection now 65 % |
| 16 | 16,900 | Electron-sword deflection now 70 % |
| 17 | 20,800 | Electron-sword deflection now 75 % |
| 18 | 23,000 | +30 total damage with basic laser |
| 19 | 25,300 | +175 px max range with basic laser |
| 20 | 27,900 | +35 total damage with basic laser |
| 21 | 30,700 | +5 laser-rifle damage (planet) |
| 22 | 33,700 | 55 % electron-sword deflect (planet) |
| 23 | 37,000 | +10 laser-rifle damage (planet) |
| 24 | 40,600 | 60 % electron-sword deflect (planet) |
| 25 | 44,500 | +15 laser-rifle damage (planet) |
| 26 | 48,700 | 65 % electron-sword deflect (planet) |
| 27 | 53,200 | +20 laser-rifle damage (planet) |
| 28 | 58,000 | 70 % electron-sword deflect (planet) |
| 29 | 63,100 | +25 laser-rifle damage (planet) |
| 30 | 68,700 | 75 % electron-sword deflect (planet); +1 wearable module slot |

> ⚠️ Lvl 13 XP (11,200) is **lower** than Lvl 12 (11,900) — see
> Appendix A.

### 7.3 Tara — the Builder

| Lvl | XP | Benefit |
|---|---|---|
| 11 | 8,300  | Module special abilities cost 10 % less ability energy |
| 12 | 9,700  | Module special abilities cost 20 % less ability energy |
| 13 | 11,200 | Module special abilities cost 30 % less ability energy |
| 14 | 12,800 | Module special abilities cost 40 % less ability energy |
| 15 | 14,500 | Module special abilities cost 50 % less ability energy |
| 16 | 16,300 | Force Wall ability: 600 px long, 25 s lifetime |
| 17 | 18,200 | Force Wall ability: 700 px long, 30 s lifetime |
| 18 | 20,200 | Misty Step teleports 150 px in tapped direction |
| 19 | 22,300 | Misty Step teleports 200 px in tapped direction |
| 20 | 24,600 | Death Blossom missiles have twice the range of regular missiles |
| 21 | 27,100 | +5 % item drop on planets; +1 wearable module slot |
| 22 | 29,800 | +5 % damage from planetary items that grant bonus damage |
| 23 | 32,800 | +5 % range from planetary items that grant bonus range |
| 24 | 36,100 | −10 % cooldown from planetary items that have a cooldown |
| 25 | 39,700 | +10 % item drop on planets; +2 wearable module slots |
| 26 | 43,600 | +10 % damage from planetary items that grant bonus damage |
| 27 | 47,800 | +10 % range from planetary items that grant bonus range |
| 28 | 52,300 | −20 % cooldown from planetary items that have a cooldown |
| 29 | 57,100 | −10 % material cost for all planetary buildings |
| 30 | 62,300 | −20 % material cost for all planetary buildings; +3 wearable module slots |

---

## 8. Planetary Items (Blueprint Upgrades)

Planetary items are **blueprints** that drop from enemies and resource
nodes on planets, then are crafted into upgrades. Key rules:

- **Drop rates are independent** — multiple items can drop from the
  same source, each rolled separately.
- The percentage shown is the **chance of that blueprint dropping** on
  planets.
- Higher-tier variants are progressively rarer (25 % → 1 %).

### 8.1 Upgrade Item Assets

| Blueprint family | Icon asset |
|---|---|
| Energy Blade Upgrade | `assets/11 Scifi Icons Pack/128x128/EnergyBlade-128x128.png` |
| Armor Upgrade | `assets/scifi-space-station-items-assets/individual/armor/scifi_armor_01_001.png` |
| Electron Pick Axe Upgrade | `assets/scifi-space-station-items-assets/individual/tools/scifi_tools_01_000.png` |
| Portable Mining Beam Upgrade | `assets/scifi-space-station-items-assets/individual/tools/scifi_tools_01_001.png` |

### 8.2 Energy Blade Upgrade (electron sword)

| Benefit | Drop % |
|---|---|
| +1 armor penetration | 25 |
| +1 damage | 24 |
| +1 armor pen / +1 damage | 23 |
| +2 armor penetration | 22 |
| +2 damage | 21 |
| +2 armor pen / +1 damage | 20 |
| +2 armor pen / +2 damage | 19 |
| +3 armor penetration | 18 |
| +3 damage | 17 |
| +3 armor pen / +1 damage | 16 |
| +3 armor pen / +2 damage | 15 |
| +3 armor pen / +3 damage | 14 |
| +4 armor penetration | 13 |
| +4 damage | 12 |
| +4 armor pen / +1 damage | 11 |
| +4 armor pen / +2 damage | 10 |
| +4 armor pen / +3 damage | 9 |
| +4 armor pen / +4 damage | 8 |
| +5 armor penetration | 7 |
| +5 damage | 6 |
| +5 armor pen / +1 damage | 5 |
| +5 armor pen / +2 damage | 4 |
| +5 armor pen / +3 damage | 3 |
| +5 armor pen / +4 damage | 2 |
| +5 armor pen / +5 damage | 1 |

### 8.3 Armor Upgrade

| Benefit | Drop % |
|---|---|
| +1 armor bonus | 25 |
| +10 % deflect damage | 24 |
| +1 armor / +10 % deflect | 23 |
| +2 armor bonus | 22 |
| +20 % deflect damage | 21 |
| +2 armor / +10 % deflect | 20 |
| +2 armor / +20 % deflect | 19 |
| +3 armor bonus | 18 |
| +30 % deflect damage | 17 |
| +3 armor / +10 % deflect | 16 |
| +3 armor / +20 % deflect | 15 |
| +3 armor / +30 % deflect | 14 |
| +4 armor bonus | 13 |
| +40 % deflect damage | 12 |
| +4 armor / +10 % deflect | 11 |
| +4 armor / +20 % deflect | 10 |
| +4 armor / +30 % deflect | 9 |
| +4 armor / +40 % deflect | 8 |
| +5 armor bonus | 7 |
| +50 % deflect damage | 6 |
| +5 armor / +10 % deflect | 5 |
| +5 armor / +20 % deflect | 4 |
| +5 armor / +30 % deflect | 3 |
| +5 armor / +40 % deflect | 2 |
| +5 armor / +50 % deflect | 1 |

### 8.4 Electron Pick Axe Upgrade

| Benefit | Drop % |
|---|---|
| +1 dmg vs rocks | 25 |
| +1 iron picked up | 24 |
| +1 dmg / +1 iron | 23 |
| +2 dmg vs rocks | 22 |
| +2 iron picked up | 21 |
| +2 dmg / +1 iron | 20 |
| +2 dmg / +2 iron | 19 |
| +3 dmg vs rocks | 18 |
| +3 iron picked up | 17 |
| +3 dmg / +1 iron | 16 |
| +3 dmg / +2 iron | 15 |
| +3 dmg / +3 iron | 14 |
| +4 dmg vs rocks | 13 |
| +4 iron picked up | 12 |
| +4 dmg / +1 iron | 11 |
| +4 dmg / +2 iron | 10 |
| +4 dmg / +3 iron | 9 |
| +4 dmg / +4 iron | 8 |
| +5 dmg vs rocks | 7 |
| +5 iron picked up | 6 |
| +5 dmg / +1 iron | 5 |
| +5 dmg / +2 iron | 4 |
| +5 dmg / +3 iron | 3 |
| +5 dmg / +4 iron | 2 |
| +5 dmg / +5 iron | 1 |

### 8.5 Portable Mining Beam Upgrade

| Benefit | Drop % |
|---|---|
| +1 dmg vs rocks | 25 |
| +1 iron picked up | 24 |
| +1 dmg / +1 iron | 23 |
| +2 dmg vs rocks | 22 |
| +2 iron picked up | 21 |
| +2 dmg / +1 iron | 20 |
| +2 dmg / +2 iron | 19 |
| +3 dmg vs rocks | 18 |
| +3 iron picked up | 17 |
| +3 dmg / +1 iron | 16 |
| +3 dmg / +2 iron | 15 |
| +3 dmg / +3 iron | 14 |
| +4 dmg vs rocks | 13 |
| +4 iron picked up | 12 |
| +4 dmg / +1 iron | 11 |
| +4 dmg / +2 iron | 10 |
| +4 dmg / +3 iron | 9 |
| +4 dmg / +4 iron | 8 |
| +5 dmg vs rocks | 7 |
| +5 iron picked up | 6 |
| +5 dmg / +1 iron | 5 |
| +5 dmg / +2 iron | 4 |
| +5 dmg / +3 iron | 3 |
| +5 dmg / +4 iron | 2 |
| +5 dmg / +5 iron | 1 |

---

## 9. Planetary Ability Modules

Non-weapon / non-mining modules. Crafted from blueprints on a planet,
they grant an **active special ability** that draws from the ability
meter. Like the upgrades above, higher tiers are rarer.

### 9.1 Force Wall Emitter — hotkey `G`

Emits a force wall in the **opposite** vector to the player's
movement/facing.

**Base properties:** 32 px long · 10 s duration · 60 ability-meter
cost · 2.0 s cooldown.

Tiers stack length / duration / cost / cooldown modifiers:

| Tier | Modifier | Drop % |
|---|---|---|
| 1 | Base properties only | 29 |
| 2 | +20 % length | 28 |
| 3 | +20 % duration | 27 |
| 4 | −20 % ability cost | 26 |
| 5 | −20 % cooldown | 25 |
| 6 | +20 % length, +20 % duration | 24 |
| 7 | +20 % length, +20 % duration, −20 % cost | 23 |
| 8 | +20 % length, +20 % duration, −20 % cost, −20 % cooldown | 22 |
| 9 | +40 % length | 21 |
| 10 | +40 % duration | 20 |
| 11 | −40 % ability cost | 19 |
| 12 | −40 % cooldown | 18 |
| 13 | +40 % length, +40 % duration | 17 |
| 14 | +40 % length, +40 % duration, −40 % cost | 16 |
| 15 | +40 % length, +40 % duration, −40 % cost, −40 % cooldown | 15 |
| 16 | +60 % length | 14 |
| 17 | +60 % duration | 13 |
| 18 | −60 % ability cost | 12 |
| 19 | −60 % cooldown | 11 |
| 20 | +60 % length, +60 % duration | 10 |
| 21 | +60 % length, +60 % duration, −60 % cost | 9 |
| 22 | +60 % length, +60 % duration, −60 % cost, −60 % cooldown | 8 |
| 23 | +75 % length | 7 |
| 24 | +75 % duration | 6 |
| 25 | −75 % ability cost | 5 |
| 26 | −75 % cooldown | 4 |
| 27 | +75 % length, +75 % duration | 3 |
| 28 | +75 % length, +75 % duration, −75 % cost | 2 |
| 29 | +75 % length, +75 % duration, −75 % cost, −75 % cooldown | 1 |

### 9.2 Dimension Warp — double-tap WASD

Teleports the player in the direction they're moving. Visual asset is
the same as the ship's force wall asset.

**Base properties:** 100 px teleport · 60 ability-meter cost · 5.0 s
cooldown.

| Tier | Modifier | Drop % |
|---|---|---|
| 1 | Base properties only | 29 |
| 2 | +20 % distance | 28 |
| 3 | −20 % ability cost | 27 |
| 4 | −20 % cooldown | 26 |
| 5 | +20 % distance, −20 % cost | 25 |
| 6 | +20 % distance, −20 % cooldown | 24 |
| 7 | −20 % cost, −20 % cooldown | 23 |
| 8 | +20 % distance, −20 % cost, −20 % cooldown | 22 |
| 9 | +40 % distance | 21 |
| 10 | −40 % ability cost | 20 |
| 11 | −40 % cooldown | 19 |
| 12 | +40 % distance, −40 % cost | 18 |
| 13 | +40 % distance, −40 % cooldown | 17 |
| 14 | −40 % cost, −40 % cooldown | 16 |
| 15 | +40 % distance, −40 % cost, −40 % cooldown | 15 |
| 16 | +60 % distance | 14 |
| 17 | −60 % ability cost | 13 |
| 18 | −60 % cooldown | 12 |
| 19 | +60 % distance, −60 % cost | 11 |
| 20 | +60 % distance, −60 % cooldown | 10 |
| 21 | −60 % cost, −60 % cooldown | 9 |
| 22 | +60 % distance, −60 % cost, −60 % cooldown | 8 |
| 23 | +75 % distance | 7 |
| 24 | −75 % ability cost | 6 |
| 25 | −75 % cooldown | 5 |
| 26 | +75 % distance, −75 % cost | 4 |
| 27 | +75 % distance, −75 % cooldown | 3 |
| 28 | −75 % cost, −75 % cooldown | 2 |
| 29 | +75 % distance, −75 % cost, −75 % cooldown | 1 |

### 9.3 Laser Burst

When the basic laser rifle fires, it **also fires in all 4
directions**. Graphical + sound assets are the same as the basic laser
rifle.

**Base properties:** 10 damage · 0.50 s cooldown · 300 px range.
**Pickup icon:** `assets/scifi-space-station-items-assets/individual/weapons/scifi_weapons_02_008.png`

| Tier | Modifier | Drop % |
|---|---|---|
| 1 | Base properties only | 29 |
| 2 | +100 px range | 28 |
| 3 | +2 damage | 27 |
| 4 | −10 % cooldown | 26 |
| 5 | +100 px range, +2 damage | 25 |
| 6 | +100 px range, −10 % cooldown | 24 |
| 7 | +2 damage, −10 % cooldown | 23 |
| 8 | +100 px range, +2 damage, −10 % cooldown | 22 |
| 9 | +200 px range | 21 |
| 10 | +4 damage | 20 |
| 11 | −20 % cooldown | 19 |
| 12 | +200 px range, +4 damage | 18 |
| 13 | +200 px range, −20 % cooldown | 17 |
| 14 | +4 damage, −20 % cooldown | 16 |
| 15 | +200 px range, +4 damage, −20 % cooldown | 15 |
| 16 | +400 px range | 14 |
| 17 | −40 % cooldown | 13 |
| 18 | +6 damage | 12 |
| 19 | +400 px range, +6 damage | 11 |
| 20 | +400 px range, −40 % cooldown | 10 |
| 21 | +6 damage, −40 % cooldown | 9 |
| 22 | +400 px range, +6 damage, −40 % cooldown | 8 |
| 23 | +600 px range | 7 |
| 24 | −60 % cooldown | 6 |
| 25 | +8 damage | 5 |
| 26 | +600 px range, +8 damage | 4 |
| 27 | +600 px range, −60 % cooldown | 3 |
| 28 | +8 damage, −60 % cooldown | 2 |
| 29 | +600 px range, +8 damage, −60 % cooldown | 1 |

### 9.4 Repulsor Burst — hotkey `C`

A blue circle appears for 1 s and pushes all enemies away.

**Base properties:** 60 ability cost · 1 s duration · pushes enemies
100 px from the player's center · 0.50 s cooldown.

| Tier | Modifier | Drop % |
|---|---|---|
| 1 | Base properties only | 41 |
| 2 | push +50 px | 40 |
| 3 | +10 % duration | 39 |
| 4 | −10 % cooldown | 38 |
| 5 | −10 % ability cost | 37 |
| 6 | push +50 px, +10 % duration | 36 |
| 7 | push +50 px, +20 % duration | 35 |
| 8 | push +50 px, +20 % duration, −10 % cooldown | 34 |
| 9 | push +50 px, +20 % duration, −10 % cooldown, −10 % cost | 33 |
| 10 | push +100 px | 32 |
| 11 | +20 % duration | 31 |
| 12 | −20 % cooldown | 30 |
| 13 | −20 % ability cost | 29 |
| 14 | push +100 px, +20 % duration | 28 |
| 15 | push +100 px, +40 % duration | 27 |
| 16 | push +100 px, +40 % duration, −20 % cooldown | 26 |
| 17 | push +100 px, +40 % duration, −20 % cooldown, −20 % cost | 25 |
| 18 | push +150 px | 24 |
| 19 | +30 % duration | 23 |
| 20 | −30 % cooldown | 22 |
| 21 | −30 % ability cost | 21 |
| 22 | push +150 px, +30 % duration | 20 |
| 23 | push +150 px, +60 % duration | 19 |
| 24 | push +150 px, +60 % duration, −30 % cooldown | 18 |
| 25 | push +150 px, +60 % duration, −30 % cooldown, −30 % cost | 17 |
| 26 | push +200 px | 16 |
| 27 | +40 % duration | 15 |
| 28 | −40 % cooldown | 14 |
| 29 | −40 % ability cost | 13 |
| 30 | push +200 px, +40 % duration | 12 |
| 31 | push +200 px, +80 % duration | 11 |
| 32 | push +200 px, +80 % duration, −40 % cooldown | 10 |
| 33 | push +200 px, +80 % duration, −40 % cooldown, −40 % cost | 9 |
| 34 | push +250 px | 8 |
| 35 | +60 % duration | 7 |
| 36 | −60 % cooldown | 6 |
| 37 | −60 % ability cost | 5 |
| 38 | push +250 px, +60 % duration | 4 |
| 39 | push +250 px, +120 % duration | 3 |
| 40 | push +250 px, +120 % duration, −60 % cooldown | 2 |
| 41 | push +250 px, +120 % duration, −60 % cooldown, −60 % cost | 1 |

> The source notes wrote several Repulsor tiers as "+X % duration,
> +X % duration" (duration listed twice). These have been
> interpreted as a **doubled** duration bonus (e.g. two +10 % →
> +20 %). See Appendix A if a single bonus was intended.

---

## 10. Planetary Building System

The build menu (`B`) on a planet builds different structures than the
space build menu.

### 10.1 Global build rules

- **Home Base must be built first** — nothing else can be placed
  without it.
- Buildings may only be placed within a **500 px radius** of the Home
  Base.
- Buildings need not connect to each other, but some require **power**,
  delivered via **Power Lines** from a power-providing building.
- Each building consumes a number of **module/build slots**; power
  sources and the Home Base **increase** the slot budget.

### 10.2 Building summary

| Building | HP | Armor | Cost (iron / copper / silicon) | Max | Slots used | Power | Function |
|---|---|---|---|---|---|---|---|
| **Home Base** | 10 ⚠️ | +1 | 100 / 100 / 100 | 1 | 0 | provides | Root module; soft respawn point; 10×10 inventory; +5 to building budget |
| **Landing Beacon** | 20 | +1 | 200 / 200 / 100 | 1 | 3 | — | Lets you skip the aerial Landing Scene on future landings |
| **Power Line** | 10 | 0 | 10 / 10 / 10 | 200 | 0 | conduit | Connects power sources to buildings; no collision layer |
| **Wind Farm** | 20 | +1 | 300 / 300 / 200 | 2 | 1 | provides | +5 to building budget |
| **Solar Farm** | 20 | +1 | 300 / 300 / 200 | 2 | 1 | provides | +10 to building budget |
| **Fission Reactor** | 50 | +2 | 500 / 500 / 300 | 2 | 2 | provides | +15 to building budget |
| **Ground Turret 1** | 50 | +1 | 100 / 100 / 50 | n/a | 1 | needs | Single-barrel turret |
| **Ground Turret 2** | 75 | +2 | 150 / 150 / 100 | n/a | 2 | needs | Double-barrel turret |
| **Arc Tower** | 60 | +1 | 60 / 60 / 20 | 2 | 1 | needs | Blocks enemy spawns within 300 px |
| **Shield Generator** | 60 | +1 | 100 / 100 / 50 | 1 | 2 | needs | Bubble blocks enemy entry/fire within 500 px |
| **Planet Forge** | 100 | +2 | 150 / 150 / 75 | 5 | 1 | — | Crafts basic consumables |
| **Advanced Forge** | — | — | — | — | — | — | Crafts modules from found blueprints |
| **Bio Lab** | — | — | — | — | — | — | Enables growing a pet follower |

> ⚠️ Home Base HP of 10 is lower than every defensive building — see
> Appendix A.

### 10.3 Building details & assets

| Building | Visual asset | Notes |
|---|---|---|
| **Home Base** | `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/RTS Sci-fi/PNG/Retina/Structure/scifiStructure_10.png` | Built with `B`. Soft respawn on death; otherwise random surface spawn. |
| **Landing Beacon** | — | Built with `B`. |
| **Power Line** | Generated SVG asset: a thick **red** line, one building-tile long | No collision layer — never collides with the player or moving objects. |
| **Wind Farm** | `assets/ai generated/planetary/buildings/wind_generator.png` | — |
| **Solar Farm** | `assets/ai generated/planetary/buildings/solar_farm.png` | — |
| **Fission Reactor** | `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/RTS Sci-fi/PNG/Retina/Structure/scifiStructure_07.png` | — |
| **Ground Turret 1** | Building: `assets/kenney space combat assets/Space Shooter Extension/PNG/Sprites X2/Building/spaceBuilding_011.png` (tint **blue**) · Projectile: `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserRed02.png` | Detect 200 px · 10 dmg/shot · 1.5 s cooldown · 700 px/s projectile · 250 px range. Rotates/animates in place to face enemy. |
| **Ground Turret 2** | Building: `assets/kenney space combat assets/Space Shooter Extension/PNG/Sprites X2/Building/spaceBuilding_012.png` (tint **blue**) · Projectile: `assets/kenney space combat assets/Space Shooter Redux/PNG/Lasers/laserRed02.png` | Detect 200 px · 15 dmg/shot · 1.5 s cooldown · 700 px/s projectile · 250 px range. Rotates/animates in place to face enemy. |
| **Arc Tower** | `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/RTS Sci-fi/PNG/Retina/Structure/scifiStructure_13.png` | Stops enemies spawning within 300 px. |
| **Shield Generator** | Building: `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/RTS Sci-fi/PNG/Retina/Structure/scifiStructure_03.png` · Shield: animated 280×280 frame sheet `assets/gamedevmarket assets/asteroids crusher/Weapons/PNG/shield_frames.png` | Shield absorbs **100 points** before failing; on failure the generator is destroyed and must be rebuilt. |
| **Planet Forge** | `assets/Kenney Game Assets All-in-1 3.4.0/2D assets/RTS Sci-fi/PNG/Retina/Structure/scifiStructure_12.png` | Crafts First Aid Pack, Grenades, Homing Rocket. |

---

## 11. Consumables (crafted at the Planet Forge)

| Consumable | Function | Icon asset | Thrown / projectile asset | Explosion asset | Sound asset |
|---|---|---|---|---|---|
| **First Aid Pack** | Heals **25 HP** ⚠️ | `assets/scifi-space-station-items-assets/individual/consumables/scifi_consumables_01_000.png` | — | — | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Devices/Sci-Fi Device 2.wav` |
| **Grenade** | Thrown in an arc; AoE damage in 200 px radius, 400 px throw range | `assets/scifi-space-station-items-assets/individual/weapons/scifi_weapons_01_005.png` | same as icon | `assets/gamedevmarket assets/asteroids crusher/Explosions/PNG/explosion_big.png` | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Explosions/Sci-Fi Energy Grenade Blast 1.wav` |
| **Homing Rocket** | Targets the closest enemy; 50 damage at up to 800 px | `assets/FINAL-Neon Void Vanguard/128/Projectiles/Ammo_Missile_Homing.png` | same as icon | same as icon | `assets/Sci Fi Sound Effects Bundle/Stormwave Audio Sci-Fi Sound Effects Bundle/Weapons/Explosions/Sci-Fi Explosion 2.wav` |

> ⚠️ The design notes describe First Aid Pack as both "heals half of
> the player's HP" and "heals 25 HP". The detailed entry (25 HP) is
> used above — see Appendix A.

---

## 12. Resource Gathering Nodes

Resources gathered on the surface:

| Resource | Source node |
|---|---|
| Bio-matter | trees, plants |
| Iron | rocks |
| Copper | copper veins |
| Silicon | crystals (silicon veins) |

### Node stats & assets

| Node | HP | Armor | Yield | Node asset | Ore asset |
|---|---|---|---|---|---|
| **Rock** | 50 | +1 | 10 iron ore | `assets/scifi-space-station-items-assets/individual/materials/scifi_materials_01_000.png` | `assets/kenney space combat assets/Voxel Pack/PNG/Items/ore_ironAlt.png` |
| **Copper Vein** | 50 | +1 | 10 copper ore | `assets/scifi-space-station-items-assets/individual/materials/scifi_materials_02_004.png` | `assets/kenney space combat assets/Space Shooter Redux/PNG/Power-ups/things_bronze.png` |
| **Silicon Vein** | 75 | +2 | 10 silicon ore | `assets/scifi-space-station-items-assets/individual/materials/scifi_materials_01_001.png` | `assets/scifi-space-station-items-assets/individual/materials/scifi_materials_01_003.png` |

**Node destruction VFX:** all three node types use the same 10-frame
asteroid-explosion sequence:
`assets/gamedevmarket assets/space shooter kit - side scrolling/png/Separate/Effects/Explosion/Explo__001.png … Explo__010.png`

> The "Bio-matter from trees/plants" node has no stat/asset block in
> the source notes yet — see Appendix A.

---

## Appendix A — Design Review Flags

Values carried over verbatim from the design notes that look like
typos or open questions. Listed here so they can be resolved before
implementation rather than silently "fixed."

1. **Ellie Lvl 13 XP (11,200)** is lower than Lvl 12 (11,900),
   breaking the otherwise-monotonic XP curve. Likely intended to be
   ~13,000+.
2. **First Aid Pack heal amount** is contradictory in the source —
   "heals half of the player's HP" vs. "heals 25 HP." Section 11 uses
   25 HP; confirm which is canonical.
3. **Home Base HP = 10** is lower than every defensive building
   (turrets 50–75, Shield Gen 60). For a root/respawn structure this
   may be a missing zero (1,000?) — confirm.
4. **Repulsor Burst tiers** list "+X % duration, +X % duration"
   (duration twice) on several rows. Interpreted as a doubled
   duration bonus; confirm whether a single bonus was intended.
5. **Bio-matter node** is named as a resource but has no HP / yield /
   asset definition yet.
6. **Advanced Forge** and **Bio Lab** buildings have function
   descriptions but no HP / cost / slot / asset stats yet.
7. **Misty Step** (Tara Lvl 18–19) — confirm whether this is the same
   ability as the ship "Misty Step" module or a surface-specific one.
