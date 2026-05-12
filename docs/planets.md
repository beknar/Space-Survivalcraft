# Planets and Planetary Encounters

## New Technology

### Planetary Landing Adaptation (Ship Module)

A new installable ship module sold in the Advanced Crafter menu.
Allows a ship to enter the planetary landing scene on contact with a
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

## Planets

Planets are world objects in the Star Maze zone (and future zones).
They have their own collider, so enemies and drones must path
around them or take damage on contact.

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

The landing scene loaded when the player leaves through the top of
the planetary landing scene depends on the planet type.

---

## Planetary Landing Scene

A new scene reached by ramming an unlocked planet with the
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

- **Thunder Worm — Double Laser**: fires two projectiles at once
  per cooldown.

---

## Planet Surface HUD

When the player exits the landing scene through the top edge and
loads the planet surface scene, a HUD is displayed that mirrors the
ship HUD layout but with planet-specific elements.

### Layout

| Element | Source |
|---|---|
| Character video panel | Replaces the ship HUD's character animation; uses the planet-surface animation set (see *Character Animations* below) |
| Character name | Shown directly below the video panel |
| HP bar | Below the character name (same widget as the ship HUD) |
| Ability meter | Below the HP bar (same widget as the ship HUD) |

### Character Animations

| Property | Value |
|---|---|
| Source directory | `assets/ai generated/planetary/character-animation/` |
| Filename | `<CharacterName>.mp4` — e.g. `Debra.mp4` |
| Lookup | Picked at scene load from the active character (`audio.character_name`) |

### Playback Algorithm

The planet-surface HUD video uses a hybrid of fixed-start playback
and discrete random-seek windows, layered over the same seamless
standby-player loop used by the ship-HUD character video
(`video_player.VideoPlayer.play_segments` → `_build_standby` →
`_restart_for_loop`).

1. On load, start playing from `0:00`.
2. After 10 seconds of playback, seek to a random offset chosen
   uniformly from `{0:00, 10:00, 20:00, 30:00, 40:00}`.
3. Continue forward playback from the chosen offset.
4. When the source is exhausted, seamlessly swap to the pre-built
   standby player and restart the cycle (steps 1-3 repeat).

The seamless-loop machinery (`_build_standby` background load
~5 s before end of source, main-thread swap on exhaustion) is
inherited unchanged from the ship-HUD video pipeline. Only the
initial seek behavior at the 10-second mark is added on top.
