# Call of Orion --- Controls

## Keyboard

| Action | Keys |
|---|---|
| Rotate left | Left Arrow / A |
| Rotate right | Right Arrow / D |
| Thrust forward | Up Arrow / W |
| Brake / reverse | Down Arrow / S |
| Sideslip left | Q |
| Sideslip right | E |
| Fire active weapon | Space (hold for auto-fire) |
| Cycle weapon (Basic Laser → Mining Beam → Energy Blade) | Tab |
| Open/close inventory | I |
| Quick Use item | 1--9, 0 (or click the slot) |
| Open/close build menu | B |
| Ship stats / character bio | C |
| Station info panel (+ other zones) | T (when near station) |
| Deploy Force Wall | G |
| Activate Death Blossom | X |
| Misty Step teleport | Double-tap W/A/S/D |
| Toggle FPS display | F |
| Full-screen map | M |
| Deploy drone (mining or combat, picks the matching variant from active weapon) | R |
| Recall drone (refunds 1 charge to inventory) | Shift+R |
| Fleet Control menu (drone orders) | Y |
| Escape menu | Escape |

### Mouse

| Action | Input |
|---|---|
| Inventory cell — pick up / drop | Left-click |
| Inventory cell — split stack in half | Right-click (extras go to the cursor) |
| Trade sell row — sell one unit per 0.15 s | Hold left-click |
| Move turret / missile array | Long-press LMB (≥ 0.4 s) and drag |

## Xbox 360 Gamepad

| Action | Input |
|---|---|
| Rotate | Left stick horizontal |
| Thrust / Brake | Left stick vertical |
| Fire | A button (hold for auto-fire) |
| Cycle weapon | Right bumper (RB) |
| Open/close inventory | Y button |

Gamepad dead zone: 0.15

## Menu Navigation

All overlay menus accept the same keyboard navigation pattern.
Mouse continues to work everywhere it always did:

| Key | Action |
|---|---|
| `Tab` / `↓` / `S` | focus next button (wraps) |
| `Shift+Tab` / `↑` / `W` | focus previous (wraps) |
| `Enter` / `Space` / `Numpad-Enter` | activate focused button |
| `←` / `→` (Video Properties only) | cycle resolution preset |
| `Esc` | back / close (cascades through overlays) |

Bare `Enter` on first open of any menu activates the default button:

* **Splash** -- Play Now (idx 0)
* **Escape menu** -- Resume (idx 0)
* **Music Videos picker** -- the first `.mp4`

Per-screen specifics:

- **Splash menu**: Play Now / Load Game / Options / Exit Game.
  In Load Game, the same Tab/Enter pattern walks the save slots
  + Back button.
- **Selection screen**: Left/Right or A/D to browse factions and ships, Enter/Space to confirm, ESC to go back
- **Escape menu**: ESC opens/closes; ESC in sub-menus returns to parent
- **Build menu**: B to open/close; mouse wheel rotates buildings during placement; ESC cancels placement
- **Station inventory**: Left-click the Home Station within 300 px
- **Craft menu**: Left-click a placed Basic Crafter within 300 px
- **Trade menu**: Left-click the Trading Station within 300 px
- **Destroy mode**: Open build menu (B), click DESTROY, then left-click buildings to remove them
- **Ship switching**: Fly within 300 px of a parked ship and left-click to transfer control. Hovering a parked ship shows its HP and a "Click to board" hint.
- **Move turret / missile array**: Left-click-and-hold (>= 0.4 s) on a placed Turret or Missile Array to pick it up; drag to a new position within 300 px of the Home Station and release to drop it. A short click does nothing; ESC snaps it back to the original position.
- **Trade sell panel**: Mouse-wheel scrolls the sell list (scrollbar thumb visible); hold left-click on a row to sell one unit every 0.15 s.
- **Story NPC (Double Star Refugee)**: Hovering surfaces the "Double Star Refugee" label; left-click the ship while within 320 px to open the dialogue tree. Inside the dialogue, **1-4** pick a choice, **SPACE / ENTER** advance linear beats, and **ESC** closes without committing quest flags.
- **Drones**: Press **R** with the Mining Beam active to deploy a Mining Drone, or with the Basic Laser active to deploy a Combat Drone. **Shift+R** recalls the deployed drone back to inventory (refund 1 charge). Hover the drone in-world to see HP / shields / status; the active drone is plotted as a small blue X on both the minimap and the full-screen map (hover the X on the large map for the same tooltip).
- **Fleet Control (`Y`)**: Modal overlay with four buttons. **RETURN** breaks off and A*-paths back to the player; **ATTACK** engages all detected enemies and ignores the 800 px break-off; **FOLLOW ONLY** is a passive-escort reaction; **ATTACK ONLY** is the default reaction (engage in detect range, otherwise follow). Direct orders override reactions; reactions persist across deployments and saves. ESC or Y closes the menu.
