# Bot Telemetry Analysis — 2026-06-02 (evening)

Source: `bot_io/autopilot_telemetry.jsonl` (gitignored), 686 events,
single **17.9 min** session. This run is after the ZONE2 swarm-survival
PR (#205) and the module-swap (#206) / drone-dispatch (#207) PRs. No
parse errors. 2 deaths, both `ZoneID.ZONE2`.

## Problem 1 — bot pinned in ENGAGE far from base; tether defeated (highest)

Both deaths end the same way: the bot is **4100–4573 px from its HS in a
57–60 alien swarm**, shields crash full→0, and it dies. The
`_zone2_far_swarm_tether` from PR #205 is supposed to pull it home in
exactly this case — but it sat **below ENGAGE** in the cascade, and a
57-alien swarm always has an alien inside the 800 px engage band, so
**ENGAGE fired every tick and the tether never did.**

**Death 2** (t+653s, `fsm=engage`) — the bot *drove* out from base:

```
+625s mine    px=6098,6003  hs_dist=768
+630s mine    px=4843,5412  hs_dist=2142
+635s engage  px=2860,5209  hs_dist=4101   sh=120 -> 76 -> 39 -> 19 -> 11 -> dead
```

It mined a far target out to hs_dist 4101, an alien entered the engage
band, ENGAGE latched, and it never left until it died. RETREAT didn't
fire (a consumable kept it above the critical floor while shields fell).

### Fix (implemented)
**Promote the ZONE2 far-swarm tether above the ENGAGE tier** (now section
1.9, was 2.6). When the bot is in ZONE2, beyond `ZONE2_TETHER_DIST_PX`
(2800) from its HS, with a dense swarm adjacent, it returns
`S_IDLE_AT_BASE` and drives home **even with an alien in the engage
band** — committing to the return trip while it still has shields,
instead of getting pinned in combat 4000+ px out. RETREAT / REGEN (above
the tether) still own the hurt-bot break-contact / heal cases, and combat
assist still fires reflexively en route. Close-to-base ZONE2 combat
(< 2800 px) is unaffected.

## Problem 2 — intra-zone teleport into the swarm (high; not fixed here)

**Death 1** (t+97s, `fsm=retreat`) — the bot's position **jumped ~4810 px
in 1.4 s** (3400 px/s, far above thrust speed), from beside its HS into
the swarm, same zone (`buildings_count` unchanged at 16):

```
+85.7s mine    px=6572,6715  hs_dist=624   (beside HS, full shields)
+87.1s engage  px=3639,2901  hs_dist=4573  <<< teleport
... sh 100 -> 74(edge-stuck) -> 42 -> 20(retreat) -> 2 -> dead
```

This is a **wormhole / slipspace teleport inside ZONE2**. The targeting
selectors filter pickups/asteroids near *return* wormholes
(`_target_near_return_wormhole`, zone_target=MAIN) but not intra-zone
teleporters, so the bot mined/navigated into one and was flung into the
swarm. The promoted tether (Problem 1) gives the post-teleport bot a
chance to head home, but at 4573 px under a 56-alien swarm the gauntlet
may still be fatal.

**Suggested fix (follow-up):** extend the selector / navigation
repulsion to avoid ALL teleporters in a zone (not just MAIN-return
wormholes), so the bot never drives into a portal that drops it deep in
the swarm. Needs the teleporter's identity in `/state` (the snapshot
fields don't currently carry intra-zone portal positions).

## Problem 3 — Nebula module/drone loop never exercised (info)

No `nebula_advanced_module_queued`, swap, or drone-deploy events fired,
and both deaths still show the **MAIN loadout** (`armor_plate, broadside,
shield_booster, shield_enhancer`) — the module-swap (#206) and
drone-dispatch (#207) code never ran. Cause: the bot never built an
Advanced Crafter this session (it died twice early and spent the run
cycling MAIN↔ZONE2 via death-recovery). This is downstream of survival:
until the bot stops dying in the ZONE2 swarm, it can't reach the
Advanced Crafter that gates the whole Nebula tier. Fixing Problems 1–2
is the prerequisite for the new gear loop to matter.

---

## Implemented this PR
1. Promote the ZONE2 far-swarm tether above ENGAGE, so a bot far from
   base in a dense swarm commits to the return trip instead of being
   pinned in combat until its shields crash. **High.**

## Deferred (ranked)
2. Avoid intra-zone teleporters (Problem 2) — needs portal positions in
   `/state`. **High.**
3. (Downstream) Once survival improves, confirm the Advanced Crafter →
   module-swap → drone loop actually fires in a longer run. **Info.**
