# Call of Orion --- Lore & Characters

## The Double-Star War

The Double-Star War is a galaxy-defining conflict that has shaped the lives of every character in the game. Its shadow lingers over the star systems, influencing the motivations and decisions of those who survived it.

---

## Factions

Players choose one of four factions. Each faction provides a unique visual style; all factions share the same ship-type stats.

| Faction | Description |
|---|---|
| **Earth** | Terran standard-issue fleet |
| **Colonial** | Frontier colony ships |
| **Heavy World** | High-gravity adapted vessels |
| **Ascended** | Advanced civilisation technology |

### Faction Shield Tints

Each faction has a distinct shield color:

| Faction | Shield Colour |
|---|---|
| Earth | Red |
| Colonial | Green |
| Heavy World | Brown |
| Ascended | Purple |

---

## Characters

Three playable characters, each shaped by the Double-Star War in different ways.

### Debra --- The Miner

**Class:** Miner

Debra's smile hides a sadness that she barely overcomes. She laughs, smiles, tells jokes, whatever she has to do to keep going. The shadow of the Double-Star War looms over her, tainting everything she does. She believes that her light can overcome her past, and she wants you to join her on her journey. Will you help her escape? Or will you help Debra overcome her personal darkness?

**Level Benefits:**
| Level | Bonus |
|---|---|
| 1 | +10 iron from asteroids |
| 2 | +10 iron from enemies |
| 3 | +15 iron from asteroids |
| 4 | +15 iron from enemies |
| 5 | +20 iron from all sources |
| 6 | +5 copper from copper asteroids |
| 7 | +10 copper from copper asteroids |
| 8 | +25 iron from all sources |
| 9 | +15 copper from copper asteroids |
| 10 | +30 iron and +20 copper from all sources |

---

### Ellie --- The Fighter

**Class:** Fighter

Ellie isn't fleeing. She's chasing vengeance. Every corner, every doorway could reveal a clue to the whereabouts of the villains of the Double-Star War that betrayed her and others. What could these people have done that would cause a young woman to give up her life to hunt criminals?

**Level Benefits:**
| Level | Bonus |
|---|---|
| 1 | +10 laser damage |
| 2 | -0.10s laser cooldown |
| 3 | +50 px/s laser speed |
| 4 | +100 px laser range |
| 5 | +15 laser damage |
| 6 | -0.05s laser cooldown |
| 7 | +75 px/s laser speed |
| 8 | +20 laser damage |
| 9 | +150 px laser range |
| 10 | +25 laser damage and -0.10s cooldown |

---

### Tara --- The Builder

**Class:** Builder

Tara is a treasure hunter looking for the technology of the ancients. After having her work destroyed during the Double-Star War, she now searches for vestiges of a past glory that she suspects is greater than the current status quo. A few clues from distant dig sites have led her here. Is she really looking for answers from the past or does she have a hidden motive?

**Level Benefits:**
| Level | Bonus |
|---|---|
| 1 | +25% blueprint drop chance |
| 2 | -10% build iron cost |
| 3 | -10% craft iron cost |
| 4 | -20% build iron cost |
| 5 | +10% station HP |
| 6 | -10% copper build cost |
| 7 | -15% craft iron cost |
| 8 | -25% build iron cost |
| 9 | +20% station HP |
| 10 | -30% all build costs and +25% station HP |

---

## Character Progression

- All characters share the same XP thresholds: 0, 100, 300, 600, 1000, 2500, 3600, 4700, 5800, 7000
- 10 levels of progression per character
- XP is hard-capped at 7,000 --- no further XP earned after max level
- XP earned: 10 per asteroid destroyed, 25 per alien kill, 500 for defeating the boss
- Character portraits are displayed in the Ship Stats panel (C key), chosen randomly from `characters/portraits/`

---

## The Nebula

Beyond the warp zones lies the Nebula, a volatile region of space where the remnants of an ancient conflict still churn. Toxic gas clouds drift through corridors of shattered asteroids, and the alien presence here is far more aggressive and varied than anything in the home sector.

The Nebula is rich in copper, a resource unknown in the core systems. Legends suggest that the copper deposits are the scattered remains of a vast alien infrastructure, destroyed during a war that predates even the Double-Star War. Scavengers who brave the Nebula's hazards --- magnetic asteroid fields that drag ships off course, and four distinct alien species adapted to the harsh environment --- return with materials capable of forging technology far beyond standard issue.

For Debra, the Nebula's copper veins promise wealth enough to leave the past behind. For Ellie, the alien strongholds may hold clues to the betrayers she hunts. For Tara, the ancient technology buried here could be the discovery of a lifetime.

---

## The Double Star Refugee

Powering up a Shield Generator inside the Nebula triggers the arrival
of **Scout Kael Vox**, a military scout dispatched from Double Star
Command. His orange scout ship flies in from the right edge of the
Nebula and holds position near the player's Home Station, unable to be
harmed.

Clicking the ship (within 320 px) opens a conversation that branches on
the active character:

- **Debra Wildstar** — Kael's mission to the outer sector is a cover
  for the news he carries: Ken Tamashii's body has gone missing from
  secure storage in the Inner Core System. Debra walks Kael through
  the blackouts, the investigation, and ultimately the aliens nobody
  at Command has admitted to. The scene closes with Debra declaring
  she is going beyond the Nebula to find whoever — whatever — took Ken,
  activating the "Find Ken" quest hook.
- **Ellie Solver / Tara Ozora** — short placeholder exchanges while
  their bespoke trees are still being written.

The meeting flag and any aftermath flags (quest activation, objective
text, the "aliens are real" revelation) are persisted with the save.
