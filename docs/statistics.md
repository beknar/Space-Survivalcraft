# Call of Orion --- Game Statistics

## The Battlefield

| Property | Value |
|---|---|
| World size | 6,400 x 6,400 px |
| Default window resolution | 1,280 x 800 px |
| Resolution presets | 1280x800, 1366x768, 1600x900, 1920x1080, 2560x1440, 3840x2160 |
| Status panel width | 213 px (left side) |
| Background | Tiled seamless starfield (1,024 x 1,024 px tiles) |
| Player start position | World centre (3,200, 3,200) |

---

## Ship Types

All ships start at world centre. Ships rendered at 0.75x scale (96 px in-game). Collision radius: 28 px.

| Ship Type | HP | Shields | Shield Regen | Rotation | Thrust | Brake | Max Speed | Damping | Guns |
|---|---|---|---|---|---|---|---|---|---|
| **Cruiser** | 100 | 100 | 0.5 pt/s | 150 deg/s | 250 px/s^2 | 125 px/s^2 | 450 px/s | 0.98875x | 1 |
| **Bastion** | 150 | 50 | 0.5 pt/s | 150 deg/s | 200 px/s^2 | 125 px/s^2 | 450 px/s | 0.98875x | 1 |
| **Aegis** | 50 | 150 | 1.0 pt/s | 100 deg/s | 250 px/s^2 | 125 px/s^2 | 450 px/s | 0.98875x | 1 |
| **Striker** | 100 | 50 | 0.5 pt/s | 150 deg/s | 300 px/s^2 | 100 px/s^2 | 450 px/s | 0.983125x | 1 |
| **Thunderbolt** | 100 | 100 | 0.5 pt/s | 150 deg/s | 200 px/s^2 | 125 px/s^2 | 400 px/s | 0.98875x | 2 |

### Engine Contrail Colours

| Ship Type | Start Colour | End Colour |
|---|---|---|
| Cruiser | Blue (100, 180, 255) | Dark Blue (20, 40, 120) |
| Bastion | Orange (255, 200, 80) | Dark Orange (120, 60, 10) |
| Aegis | Green (80, 255, 180) | Dark Green (10, 80, 50) |
| Striker | Red (255, 100, 100) | Dark Red (120, 20, 20) |
| Thunderbolt | Purple (200, 120, 255) | Dark Purple (60, 20, 100) |

---

## Weapons

| Weapon | Damage | Cooldown | Speed | Range | Targets |
|---|---|---|---|---|---|
| **Basic Laser** | 25 | 0.30 s | 900 px/s | 1,200 px | Alien ships only |
| **Mining Beam** | 10 | 0.10 s | 500 px/s | 800 px | Asteroids only |

### Broadside Module

| Property | Value |
|---|---|
| Damage | 25 per projectile |
| Cooldown | 0.50 s |
| Speed | 600 px/s |
| Range | 400 px |
| Direction | Perpendicular to ship (both sides) |

---

## Ship Modules

| Module | Effect | Craft Cost |
|---|---|---|
| Armor Plate | +20 max HP | 50 iron |
| Engine Booster | +50 max speed | 75 iron |
| Shield Booster | +20 max shields | 100 iron |
| Shield Enhancer | +3 shield regen/s | 125 iron |
| Damage Absorber | -3 damage to shields | 150 iron |
| Broadside Module | Auto-fires perpendicular lasers | 200 iron |

- 4 module slots on the ship
- Only 1 of each type can be equipped
- Blueprints drop from aliens (50%) and asteroids (25%)

---

## Iron Asteroids

| Property | Value |
|---|---|
| Count | 75 |
| HP | 100 |
| Iron yield | 10 per asteroid |
| Collision radius | 26 px |
| Spin rate | 8--30 deg/s (random) |
| Respawn interval | 60 s |

---

## Small Alien Ships

| Property | Value |
|---|---|
| Count | 30 |
| HP | 50 |
| Collision radius | 20 px |
| Movement speed | 120 px/s |
| Detection range | 500 px |
| Leash range | 1,500 px |
| Iron drop | 5 per kill |
| XP reward | 25 |
| Respawn interval | 60 s |

### Alien Weapon

| Property | Value |
|---|---|
| Damage | 10 per hit |
| Range | 500 px |
| Speed | 650 px/s |
| Cooldown | 1.5 s |

---

## Boss Encounter

| Property | Value |
|---|---|
| HP | 2,000 |
| Shields | 500 |
| Collision radius | 38 px |
| Detection range | 800 px |
| Collision damage | 25 |
| Iron drop | 200 |
| XP reward | 500 |

### Boss Weapons

| Weapon | Damage | Cooldown | Speed | Range | Notes |
|---|---|---|---|---|---|
| Main Cannon | 40 | 1.0 s | 550 px/s | 700 px | Single projectile |
| Spread Shot | 15 x 3 | 3.0 s | 500 px/s | 600 px | 30-degree cone |
| Charge Attack | 60 | 8.0 s | 600 px/s | --- | 2s windup, 0.8s dash (Phase 2+) |

### Boss Phases

| Phase | HP Range | Speed | Shield Regen | Cooldown Modifier | Special |
|---|---|---|---|---|---|
| Phase 1 | 100%--50% | 180 px/s | 5/s | Normal | Main cannon + spread |
| Phase 2 | 50%--25% | 220 px/s | 10/s | Normal | Adds charge attack |
| Phase 3 | Below 25% | 220 px/s | 0/s | Halved | Enraged, no shield regen |

---

## Station Buildings

| Type | HP | Iron Cost | Max Count | Capacity Slots | Notes |
|---|---|---|---|---|---|
| Home Station | 100 | 100 | 1 | --- | Root module; must be built first |
| Service Module | 50 | 25 | 4 | 1 | General connector |
| Power Receiver | 75 | 50 | unlimited | 1 | Links to solar arrays |
| Solar Array 1 | 50 | 75 | 2 | 1 (+6 capacity) | |
| Solar Array 2 | 50 | 100 | 2 | 1 (+10 capacity) | |
| Turret 1 | 100 | 50 | unlimited | 1 | Single-barrel auto-fire |
| Turret 2 | 100 | 75 | unlimited | 2 | Dual-barrel auto-fire |
| Repair Module | 75 | 75 | 1 | 1 | Passive HP repair |
| Basic Crafter | 75 | 150 | 1 | 1 | Crafts repair packs |

### Turret Stats

| Property | Value |
|---|---|
| Detection range | 400 px |
| Damage | 10 per shot |
| Cooldown | 1.5 s |
| Projectile speed | 700 px/s |
| Projectile range | 500 px |

### Repair Module Stats

| Property | Value |
|---|---|
| Repair range | 300 px from Home Station |
| Repair rate | 1 HP/s (player + buildings) |
| Shield regen boost | +1 pt/s |

### Crafting

| Recipe | Iron Cost | Time | Output |
|---|---|---|---|
| Repair Pack | 200 | 60 s | 5 packs |

---

## Trading Station

| Item | Sell Price | Buy Price |
|---|---|---|
| Iron | 1 credit | --- |
| Repair Pack | 100 credits | 400 credits (x5) |
| Blueprint | Half craft cost | --- |
| Module | Full craft cost | --- |

---

## Fog of War

| Property | Value |
|---|---|
| Reveal radius | 400 px (800 px diameter) |
| Grid cell size | 50 px |
| Grid dimensions | 128 x 128 cells |
| Persistence | Saved/loaded with game state |

---

## Music Video Player

| Property | Value |
|---|---|
| Supported formats | MP4, AVI, WMV, M4V, 3GP, ASF, MKV, WebM, MOV, FLV, OGV |
| Decoder | FFmpeg (bundled DLLs in project root, ~220 MB, gitignored) |
| Display location | HUD status panel, above minimap, 16:9 aspect ratio |
| Availability | Fullscreen or borderless mode only |
| Frame downscale | 200 px wide (GPU blit + PIL conversion) |
| Conversion rate | ~24--30 new frames/s from video source |
| Required DLLs | avcodec-62, avformat-62, avutil-60, swresample-6, swscale-9, avfilter-11, avdevice-62 |

---

## Character Video Player

| Property | Value |
|---|---|
| Display location | HUD status panel, 1:1 square aspect |
| Downscale method | GPU-side `glBlitFramebuffer` (1440 to 200 px) |
| Readback size | ~90 KB per frame (vs ~8 MB unscaled) |
| Conversion rate | 15 fps (throttled) |
| Loop method | Pre-built standby player loaded 5s before end-of-file |
| Source directory | `characters/` (scanned for `Name.mp4` files) |

---

## Persistent Configuration

Settings stored in `config.json` (gitignored):

| Setting | Description | Default |
|---|---|---|
| `music_volume` | Music volume | 0.35 |
| `sfx_volume` | Sound effects volume | 0.60 |
| `video_dir` | Video file directory path | (empty) |
| `show_fps` | FPS counter visibility | false |
| `autoplay_ost` | Auto-play OST on game start | true |

---

## Item Stack Limits

| Item | Max Stack |
|---|---|
| Iron | 999 |
| Repair Pack | 99 |
| Blueprints/Modules | 10 |
