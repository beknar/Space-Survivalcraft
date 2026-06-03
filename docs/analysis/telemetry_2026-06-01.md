# Bot Telemetry Analysis — 2026-06-01

Source: `bot_io/autopilot_telemetry.jsonl` (gitignored), 5199 events,
**two** appended sessions. No parse errors.

- **Session 1** — 2208 events, ~66 min. Identical to the 2026-05-30
  capture (same 3 ZONE2 deaths, 254 mine↔gather flips, 0 retreats). This
  is the **pre-fix** run.
- **Session 2** — 2991 events, ~93 min. The **post-fix** run (after the
  S_RETREAT / density-heal / edge-pin / mine-gather-hysteresis PR). This
  is the session worth analysing.

## Did the 2026-05-30 fixes land?

| Fix | Evidence in Session 2 | Verdict |
|---|---|---|
| `S_RETREAT` state | 26 transitions into `retreat`, 9 snapshots | **firing** |
| Density-aware shield heal | 25 `heal_shield_fire` (vs ~late/never before) | **firing** |
| HP heals | 33 `heal_hp_fire` | firing |
| Edge-pin escape | stuck 18 (15 edge / 3 building) | partial |

Heals and retreat both engage now — a real improvement. **But the bot
still died twice in ZONE2**, and the retreat telemetry shows why.

---

## Problem 1 — RETREAT doesn't break contact; engage↔retreat thrash (highest)

Between **t+3140 s and t+3178 s (38 s)** the FSM logged **~18
`engage→retreat` transitions** with shields pinned at **0–5 / 120**, 45–46
aliens within range, and `hs_dist ≈ 4200 px`:

```
+3140s engage->retreat sh=7/120  aliens=47 hs_dist=4055
+3144s engage->retreat sh=3/120  aliens=46 hs_dist=4266
+3149s engage->retreat sh=4/120  aliens=46 hs_dist=4220
... (14 more in the next 30 s, all sh 0-5, hs_dist ~4200) ...
```

Two root causes, both now fixed:

1. **`_act_retreat` marched toward an unreachable HS.** It drove to *any*
   in-zone Home Station regardless of distance. With the HS 4200 px away
   across a 46-alien swarm the bot never reached the umbrella — it bled
   out en route while flip-flopping with ENGAGE.
   **Fix:** only drive to the HS when it is within
   `RETREAT_HS_MAX_DIST_PX` (2200); beyond that, fall through to the
   swarm-centroid flee and actually break contact.

2. **A flickering consumable kept releasing RETREAT.** `_retreat_active`
   returned `False` the instant a `shield_recharge` appeared in a
   quick-use slot (intent: "fight + heal instead of flee"). At 0–5 / 120
   under 46 aliens a single heal can't outpace swarm DPS, so each release
   dumped the bot back into a fatal ENGAGE.
   **Fix:** below `RETREAT_CRITICAL_SHIELD_PCT` (0.25) RETREAT fires
   regardless of consumable; the normal "have-heal → fight" band (≥0.25)
   is unchanged.

This pairing — flee the centroid when the umbrella is unreachable, and
stay retreating at critical shields — is what turns the 18-flip thrash
into a single sustained break-contact.

---

## Problem 2 — gather-while-swarmed death at a map edge (high, not yet fixed)

Death 2 (t+5241 s, `fsm=gather`, pos `[4517, 478]` — near the bottom
edge):

```
+5230s engage->gather sh=80/100 aliens=56
+5232s snapshot       sh=65/100 aliens=56
+5232s stuck_detected sh=47/100 aliens=56  (edge)
+5237s snapshot       sh=2/100  aliens=56
+5240s player_death
```

Shields fell 80→2 in ~8 s while the bot chased loot into a 56-alien
swarm at the map edge and got **edge-stuck** mid-drain. RETREAT's enter
band is 0.60; the drop from 0.80 was so fast the bot was edge-pinned
(`stuck` at 0.47) before RETREAT could act, and the edge-pin escape
didn't peel it off in time.

**Suggested fix (follow-up):** suppress GATHER/MINE when a dense swarm is
adjacent and shields are already falling (mirror the RETREAT swarm gate
on the resource states), so the bot doesn't chase loot into a swarm at
all. Deferred from this PR to keep the retreat change isolated.

---

## Problem 3 — mine↔gather churn persists (low, efficiency)

- mine↔gather flipped **324 times** in Session 2 (vs 254 in Session 1;
  rate 3.5/min vs 3.85/min — only marginally improved by the
  `GATHER_ENTER_WHILE_MINING_PX` hysteresis).
- **611 transitions suppressed by dwell**, dominated by **`gather→mine`
  (264)**. The 2026-05-30 hysteresis guards *mine→gather* (don't abandon
  mining for a far pickup) but not *gather→mine*, which is the dominant
  direction here.

**Suggested fix (follow-up):** add the symmetric hysteresis — while
actively gathering a reachable pickup, only a genuinely-close asteroid
should preempt to MINE.

## Problem 4 — `mine_no_progress_giveup` under swarm (low)

One `mine_no_progress_giveup`: 60 s mining with `iron_baseline=0,
iron_now=0` and **60 aliens** nearby — the bot couldn't reach/clear the
asteroid through the swarm. Related to Problem 2 (resource-seeking into a
swarm). The watchdog correctly blacklisted the asteroid and recovered.

---

## Implemented this PR
1. RETREAT flees the swarm centroid when the HS is beyond
   `RETREAT_HS_MAX_DIST_PX` (unreachable through the swarm). **High.**
2. RETREAT holds below `RETREAT_CRITICAL_SHIELD_PCT` even with a shield
   consumable available, ending the engage↔retreat thrash. **High.**

## Deferred (ranked)
3. Suppress GATHER/MINE under an adjacent dense swarm with falling
   shields (kills the Problem-2 gather-into-swarm death). **High.**
4. Symmetric `gather→mine` hysteresis to cut the 264 churn. **Low.**
