# Bot Telemetry Analysis — 2026-06-03

Source: `bot_io/autopilot_telemetry.jsonl` (gitignored), 2318 events,
single **55.5 min** session. Post the tether-above-engage PR (#208). No
parse errors. **9 deaths** — 5 `ZoneID.ZONE2`, **4 `ZoneID.WARP_METEOR`**.

The WARP_METEOR deaths are a new dominant pattern (the prior captures
died only in ZONE2).

## Problem 1 — regen ↔ warp_traverse thrash in WARP_METEOR (highest)

**100 `regen ↔ warp_traverse` transitions** this session. In WARP_METEOR
the bot oscillates between the two states every ~0.1–2 s while shields
are pinned at 0–6/120, driving north through the meteor field, and dies
before reaching the exit. Four deaths follow this exact shape:

```
+1497s warp_traverse->regen  sh=51/100 py=4704
+1498s regen->warp_traverse  sh=26     py=5017
+1498s warp_traverse->regen  sh=26     py=5046
... 25+ more flips, sh 0-6, py climbing 5000->5900 ...
+1517s player_death          sh=0      py=5926
```

**Root cause.** REGEN's `_regen_decision` suppressed entry on a close
threat (`threatened`) or a warp **swarm** (`in_warp_swarm`), but **not**
on a warp zone with environmental damage and no swarm. WARP_METEOR has
meteors, not aliens, so `threatened` / `in_warp_swarm` were both False
and the bot **entered REGEN every tick**. The existing stay-side escape
valve kicked it back out once shields stalled — but it re-entered the
next tick. REGEN's only action in a warp zone is to idle (there is no HS
to heal at), so the bot was idling in the meteor field instead of
crossing it.

### Fix (implemented)
Add `in_warp_zone` to the REGEN **entry** suppression (mirroring the
existing exit valve). In any warp zone the bot now stays in
WARP_TRAVERSE and commits to the crossing — less time in the field =
less cumulative damage — with combat assist + auto-heal consumables
handling defense en route. Warp-only; MAIN / ZONE2 REGEN is unchanged.

## Problem 2 — shield heals never fired all session (high; not fixed here)

`heal_shield_fire` = **0** across the whole 55-min, 9-death session,
despite `heal_shield_arm` firing 13×. The shield-heal latch armed but
never fired — i.e. **there was no `shield_recharge` in a quick-use slot
to consume** (the death-spiral signature from the original 2026-05-30
analysis). With no working shield heal, every encounter is a pure
attrition loss. The repeated deaths drop + reset the consumable loadout
faster than the EQUIP pipeline restores it.

**Suggested fix (follow-up):** harden the consumable-equip path so a
`shield_recharge` is reliably bound to a quick-use slot before the bot
leaves the home-station umbrella (and re-verify after every death-
recovery), so `_maybe_use_consumables` can actually fire. This is likely
the single biggest survival lever and deserves its own focused pass.

## Problem 3 — Nebula module/drone loop still never exercised (info)

No `nebula_advanced_module_queued`, swap, install, or drone-deploy
events; both ZONE2 deaths still show the MAIN loadout. The bot never
built an Advanced Crafter this session — it spent the run dying (9×) and
cycling MAIN ↔ ZONE2 ↔ WARP via death-recovery. Same conclusion as the
prior capture: the module-swap (#206) / drone-dispatch (#207) loop can't
matter until the bot survives long enough to reach the Advanced Crafter.
Problems 1–2 are the prerequisites.

---

## Implemented this PR
1. Suppress REGEN **entry** in warp zones so the bot commits to
   WARP_TRAVERSE instead of thrashing regen↔warp_traverse in the meteor
   field. **High.**

## Deferred (ranked)
2. Guarantee a `shield_recharge` is bound to a quick-use slot before /
   after leaving base (Problem 2 — heals never fire). **High.**
3. Avoid intra-zone teleporters (carried from 2026-06-02b). **High.**
4. (Downstream) Confirm the Advanced Crafter → module-swap → drone loop
   fires once survival improves. **Info.**
