# Bot Telemetry Analysis — 2026-05-30

Source: `bot_io/autopilot_telemetry.jsonl` (gitignored), 2208 events,
single session of **~66 min** (3959 s). No parse errors.

## Session shape

| Metric | Value |
|---|---|
| Snapshots | 786 |
| State transitions | 731 (all `reason=dwell_or_preempt`) |
| Transitions suppressed by dwell | 501 |
| `stuck_detected` | 20 (19 `edge`, 1 `building`) |
| `player_death` | 3 (all in `ZoneID.ZONE2`) |
| Heal fires | 17 hp + 25 shield (none before t+2578s) |

FSM time spent (state-tagged snapshots): mine 222, gather 163,
engage 136, regen 119, hunt 58, craft 30, deposit 29,
idle_at_base 25, warp_traverse 15, install 14.

---

## Problem 1 — Zone 2 death spiral (highest severity)

All three deaths happened in the Nebula (Zone 2) inside the first
**1457 s**, each losing the same loadout (`broadside`,
`shield_booster`, `shield_enhancer`, `armor_plate`):

| t | state | shield collapse | aliens | notes |
|---|---|---|---|---|
| +200s | gather→regen | 120→83→50→18 in ~13s | 50 | armed shield heal at 18, died |
| +1124s | engage | →2→1 | 53 | **stuck (edge) while engaged**, couldn't flee |
| +1457s | regen | 51→12→1 in ~8s | 60 | armed at 12, died |

**Root cause — the consumable phase never finishes before death.**
`consumable_phase_started` flips back to **False at the exact tick of
each death** (t+201s, t+1125s) because death drops modules +
consumables. The cycle is:

```
enter Zone 2 under-equipped → 50–60 aliens melt shields (~37 sh/s)
→ die → lose modules + consumables → consumable_phase resets
→ re-craft → die again
```

The bot only escapes the loop on the **third** recovery (phase goes
True at t+1752s and stays), and the first heal consumable does not
actually fire until **t+2578s**.

**Why the armed heals never fired.** `_maybe_use_consumables`
(`bot_autopilot_actions_combat.py:1029`) only fires when
`_find_quick_use_slot(slots, "shield_recharge")` returns a slot. During
all three deaths the latch armed (telemetry `heal_shield_arm`) but no
`heal_shield_fire` followed — i.e. there was **no shield-recharge
consumable in a quick-use slot** because the consumable phase had been
reset by the prior death. Arming is purely a latch; with an empty slot
it is a no-op.

**Contributing tuning.** `CONSUMABLE_USE_SHIELD_PCT = 0.20`
(`bot_autopilot_tuning.py:508`) arms shield heals at ≤20 % (24/120).
With shields draining ~37/s in Zone 2 and a 1 s autopilot tick, 20 % is
~0.65 s of buffer — too late to matter even when a consumable exists.

### Suggested fixes
1. **Gate Zone 2 entry on readiness.** Don't fight in the Nebula until
   the consumable phase has completed at least once and shield/repair
   consumables are present in quick-use slots. This breaks the spiral at
   the source.
2. **Retreat instead of `regen`-in-place.** Deaths 1 and 3 occurred
   *while in `regen`* surrounded by 50–60 aliens — `regen` sits and
   heals while still being hit. Add a "shields <X% **and** aliens >N →
   warp/flee to home station" escape that outranks `regen`.
3. **Raise the shield arm threshold** (or make it alien-density aware)
   so the heal fires while there is still shield buffer to spend.

---

## Problem 2 — Edge-stuck, 19× (and one was fatal)

19 of 20 `stuck_detected` events are `cause=edge`. The bot repeatedly
pins itself against map boundaries, clustered on the left/upper Zone 2
edge (x≈2100–2300, y≈6000–7900). For `mine` stucks an asteroid is
blacklisted and it recovers, but `engage`/`gather` edge-stucks have no
asteroid to blacklist:

- t+1120s & t+1123s: **stuck at edge while `engage` with 53 aliens** →
  could not flee → **death 2**.

### Suggested fix
Edge-stuck recovery currently leans on asteroid blacklisting, which does
nothing in `engage`/`gather`. Add an unconditional "push toward map
center" escape impulse on any `edge` stuck regardless of FSM state, and
prioritize it over combat movement so a wall-pin during a fight can't be
lethal.

---

## Problem 3 — State churn (low severity, efficiency)

- `mine`↔`gather` flipped **254 times** (129 + 125), median 4.1 s
  apart, **105 flips under 3 s**. Mining drops iron → gather it → back
  to mine is expected, but the cadence is tight against the 1 s dwell.
- **501 transitions suppressed** by `MIN_DWELL_S` (1.0 s). Dominant
  suppressed desires: `gather→mine` (139), `craft→mine` (91),
  `craft→idle_at_base` (47). The `craft` state spends a lot of ticks
  wanting to leave but being held by dwell — worth checking the craft
  exit condition isn't flapping.

This is not harmful (dwell is doing its job of damping the thrash) but
the volume suggests the `mine`/`gather` and `craft` exit predicates
could be hysteresis-banded to reduce churn.

---

## Quick wins, ranked
1. Block Zone 2 combat until heal consumables exist in quick-use slots
   (kills the death spiral + the wasted re-craft loops). **High impact.**
2. Add a density-aware flee/retreat that outranks `regen`. **High.**
3. Unconditional center-push escape on `edge` stuck. **Medium.**
4. Revisit `CONSUMABLE_USE_SHIELD_PCT` (0.20 arms too late). **Medium.**
5. Hysteresis on `craft`/`mine`/`gather` exits to cut churn. **Low.**
