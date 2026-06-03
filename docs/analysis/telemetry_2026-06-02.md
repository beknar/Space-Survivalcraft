# Bot Telemetry Analysis — 2026-06-02

Source: `bot_io/autopilot_telemetry.jsonl` (gitignored), 3456 events,
single session of **~124 min**. No parse errors. This is the run *after*
the 2026-06-01 RETREAT break-contact PR (#202).

## Session shape

| Metric | Value |
|---|---|
| Snapshots | 1480 |
| State transitions | 944 |
| Suppressed by dwell | 602 |
| `stuck_detected` | 31 (**27 edge**, 4 building) |
| `player_death` | 2 (both `ZoneID.ZONE2`) |
| `heal_shield_fire` / `heal_hp_fire` | 45 / 55 |
| Transitions into `retreat` | 3 |

FSM snapshot time: regen 320, hunt 290, mine 282, engage 234, gather
223, idle 59, deposit 35, craft 18, warp_traverse 14.

---

## Problem 1 — REGEN marches to an unreachable HS and dies (highest)

**Death 1** (t+5309 s, `fsm=regen`, pos `[3554, 5002]`):

```
+5292s snapshot sh=1/120 aliens=49 hs_dist=3631 fsm=regen
+5297s snapshot sh=1/120 aliens=49 hs_dist=3587 fsm=regen
+5302s snapshot sh=0/120 aliens=49 hs_dist=3542 fsm=regen
+5307s snapshot sh=0/120 aliens=49 hs_dist=3500 fsm=regen
+5308s player_death
```

The bot spent **~16 s in REGEN at 0–1 / 120 shields** with 49 aliens,
slowly closing on a home station **3500 px away** (`hs_dist` ticking down
3631→3500), and died en route.

**Root cause.** `_act_regen` drives to *any* in-zone HS regardless of
distance (`bot_autopilot_actions_combat.py`, the `_regen_drive_to_hs`
branch) — the **same far-HS bug PR #202 fixed for `_act_retreat` but
never fixed for REGEN.** Marching 3500 px toward an umbrella at 0 shields
under a swarm is the maximum-exposure option; the bot bleeds out before
arriving.

Why REGEN and not RETREAT here: RETREAT's gate needs ≥6 aliens within
`RETREAT_SWARM_RANGE_PX` (1200). While the bot is strung out between the
swarm and the far HS, fewer than 6 are within 1200 px, so RETREAT
releases and REGEN takes over — then drives back toward the distant HS.

### Fix (implemented)
Mirror PR #202's far-HS handling in `_act_regen`: when the HS is beyond
`RETREAT_HS_MAX_DIST_PX` (2200) **and** a dense swarm is adjacent, flee
the swarm centroid (break contact) instead of marching to the umbrella.
Within range, the umbrella is still the recovery target. The shared
centroid-flee logic is extracted into `_flee_swarm_centroid` and reused
by both RETREAT and REGEN.

---

## Problem 2 — engage↔regen thrash at 0 shields, far from HS (high, partial)

**Death 2** (t+5977 s, `fsm=engage`, `hs_dist ≈ 2500`):

```
+5958s regen->engage sh=36/100 aliens=57
+5963s snapshot      sh=0/100  aliens=57 fsm=engage
+5968s engage->regen sh=0/100  aliens=57
+5972s regen->engage sh=1/100  aliens=57
+5973s stuck_detected (edge) sh=1/100
+5977s player_death
```

The bot oscillated regen↔engage at 0 shields, `hs_dist ≈ 2500` (just over
the 2200 retreat-HS threshold), then edge-pinned and died. RETREAT didn't
commit (same <6-within-1200 gating as Problem 1 once strung out). The
Problem-1 fix helps the REGEN half of this thrash; the ENGAGE half is a
choose-level issue (RETREAT not firing when the swarm is just outside
1200 px) and is **not** fully resolved here — see deferred items.

---

## Problem 3 — edge-stuck while ENGAGE, 20× (high)

27 of 31 `stuck_detected` were `cause=edge`; **20 were in `engage`**, in
tight clusters:

- t+890–928 s: **11 edge-stucks in 38 s** at x≈3400–4140, y≈5160–5230,
  58 aliens, `hs_dist` 2870–3560.
- t+4505–4517 s: 4 edge-stucks at (3650–3715, 2910–2956), shields
  crashing 74→0.

The common thread: the bot fights ~55–60 aliens **deep in ZONE2
(2500–4600 px from HS)**, pins against a map edge, and shields collapse.
The edge-pin escape (PR #197) fires but the bot keeps returning to the
same edge to fight the swarm. The deeper issue is **the bot roaming far
into a persistent swarm to fight/gather/mine with no win condition** —
the standing "don't fight far from base in ZONE2" recommendation from the
2026-05-30 analysis, still unimplemented.

---

## Problem 4 — gather→mine churn persists (low)

mine↔gather flipped 234 times; **`gather→mine` was the top
dwell-suppressed desire (287)**. The 2026-05-30 hysteresis guards
*mine→gather* but not *gather→mine* (the dominant direction). Symmetric
hysteresis would cut it. Unchanged from the 2026-06-01 finding.

---

## Implemented this PR
1. REGEN flees the swarm centroid when the HS is beyond
   `RETREAT_HS_MAX_DIST_PX` and a dense swarm is adjacent, instead of
   marching to the unreachable umbrella (fixes Death 1). **High.**

## Deferred (ranked)
2. Make RETREAT commit when the swarm is just outside 1200 px (fixes the
   Problem-2 engage↔regen thrash) — widen the swarm-detect radius or add
   hysteresis to the RETREAT gate. **High.**
3. Don't seek resources / engage deep in a ZONE2 swarm far from HS
   (Problem 3 root cause). **High, larger behavioural change.**
4. Symmetric `gather→mine` hysteresis (Problem 4). **Low.**
