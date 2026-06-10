"""Section-helper extraction of ``_choose_next_state``.

Lifted from ``bot_autopilot`` in the 2026-05-10 split.  The 551-line
priority cascade was the single largest function in the bot stack
and gets touched on every behavioural fix; pulling it into its own
module makes the section structure (8 priority tiers + section-0
housekeeping) easier to navigate without changing behaviour.

Cross-references to bot_autopilot module-level symbols (state
constants, threshold constants, the ``_state`` / ``_fsm`` globals,
helper functions like ``_find_home_station`` and ``_iron_total``)
are routed through ``_ap.<name>`` so the orchestrator's existing
contract -- including test-time monkey-patches on
``bot_autopilot._state`` etc. -- threads through unchanged.

``bot_autopilot._choose_next_state`` is now a one-line delegate
that calls ``choose_next_state`` here, so all existing call sites
in the orchestrator's FSM tick keep working.
"""
from __future__ import annotations

import math

import bot_autopilot as _ap


def _outside_main_swarm_suppresses(
    state: dict, zone_id: str, alien_threshold: int,
) -> bool:
    """Productive-alternative gate shared by ENGAGE and REGEN.

    Returns True iff (a) the bot is outside MAIN, (b) a productive
    non-combat alternative is viable this tick (WARP_TRAVERSE or
    BUILD_NEBULA), and (c) the on-screen alien count meets
    ``alien_threshold``.

    Originally inlined twice -- PR #169 introduced it for ENGAGE and
    PR #170 mirrored it for REGEN, with separate ENGAGE/REGEN alien
    thresholds.  Hoisted here so future tiers that need the same
    gate can call one place.
    """
    in_main_zone = ("MAIN" in zone_id) and ("WARP" not in zone_id)
    if in_main_zone:
        return False
    boss_killed = (
        _ap._state.boss_was_killed
        or bool(state.get("boss_defeated", False)))
    warp_traverse_alt = (
        "WARP" in zone_id
        and boss_killed
        and _ap._state.warp_after_boss_done
        and not _ap._state.warp_traverse_done)
    build_nebula_alt = (
        "ZONE2" in zone_id
        and not _ap._state.nebula_build_done
        and _ap._iron_total(state) >= _ap.BUILD_IRON_THRESHOLD)
    if not (warp_traverse_alt or build_nebula_alt):
        return False
    return len(state.get("aliens") or []) >= alien_threshold


def _bot_has_ready_shield_consumable(state: dict) -> bool:
    """True iff a shield_recharge sits in a quick-use slot with a
    positive count.  This is the Fix-1 readiness gate: when it's
    False the armed shield-heal latch in ``_maybe_use_consumables``
    can never actually fire, so fighting the swarm is a pure loss.
    """
    for s in (state.get("quick_use_slots") or []):
        if (s and s.get("item_type") == "shield_recharge"
                and int(s.get("count", 0)) > 0):
            return True
    return False


def _retreat_active(state: dict, p: dict, cur: str) -> bool:
    """Section-0.5 predicate: should the bot drop into S_RETREAT?

    True when ALL hold:
      * the bot is in ZONE2 (the Nebula) -- the persistent-swarm
        zone where the captured death spiral happened.  Warp zones
        are deliberately excluded: there the bot is mid-traverse and
        ``S_WARP_TRAVERSE`` + the warp-swarm suppression already keep
        it MOVING toward the exit, which is its own form of retreat;
        layering RETREAT on top would fight that drive.  MAIN is
        excluded too (the fortified HS umbrella makes defending the
        right call there),
      * it has no ready shield_recharge consumable (so the armed
        heal latch can't fire -- the death-spiral signature),
      * a dense swarm (>= RETREAT_SWARM_ALIEN_COUNT aliens within
        RETREAT_SWARM_RANGE_PX) is on top of it,
      * shields are below the enter threshold (or, with hysteresis,
        below the exit threshold while already retreating).

    Gated this tightly so it only triggers the exact under-equipped
    pathology the 2026-05-30 telemetry captured and never interferes
    with a properly-kitted bot's normal REGEN / ENGAGE behaviour.
    """
    zone_id = str((state.get("zone") or {}).get("id", ""))
    if "ZONE2" not in zone_id:
        return False
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    sh = int(p.get("shields", 0))
    sh_max = max(1, int(p.get("max_shields", 1)))
    pct = sh / sh_max
    threshold = (_ap.RETREAT_EXIT_SHIELD_PCT
                 if cur == _ap.S_RETREAT
                 else _ap.RETREAT_ENTER_SHIELD_PCT)
    if pct >= threshold:
        return False
    # Swarm-detect radius (2026-06-02): the base RETREAT_SWARM_RANGE_PX
    # gate released RETREAT the moment the bot drifted just past the
    # swarm, producing the engage<->regen 0-shield thrash that ended in
    # death.  Widen the radius once we're committed to retreating
    # (hysteresis -- stay until genuinely clear) OR when shields are
    # critical (commit to the flee even if the swarm has strung out, it
    # WILL re-converge at near-zero shields).
    swarm_range = (
        _ap.RETREAT_SWARM_RANGE_EXIT_PX
        if (cur == _ap.S_RETREAT or pct < _ap.RETREAT_CRITICAL_SHIELD_PCT)
        else _ap.RETREAT_SWARM_RANGE_PX)
    swarm = sum(
        1 for a in (state.get("aliens") or [])
        if math.hypot(float(a.get("x", 0.0)) - px,
                      float(a.get("y", 0.0)) - py)
        <= swarm_range)
    if swarm < _ap.RETREAT_SWARM_ALIEN_COUNT:
        return False
    # Consumable gate: a ready shield_recharge normally means "fight +
    # heal instead of fleeing", so RETREAT stays suppressed.  BUT the
    # 2026-06-01 telemetry caught the bot thrashing engage<->retreat ~18
    # times in 38 s at 0-5/120 shields under a 46-alien swarm because a
    # flickering consumable kept releasing RETREAT back into a fatal
    # re-engage.  Below RETREAT_CRITICAL_SHIELD_PCT a single heal can't
    # outpace swarm DPS, so retreat regardless of the consumable --
    # breaking contact is the only survivable move at near-zero shields.
    if (pct >= _ap.RETREAT_CRITICAL_SHIELD_PCT
            and _bot_has_ready_shield_consumable(state)):
        return False
    return True


def _zone2_far_swarm_tether(state: dict, p: dict, hs) -> bool:
    """Section-2.6 predicate: should the bot stop seeking resources /
    aliens deeper into a ZONE2 swarm and head home instead?

    True when ALL hold:
      * the bot is in ZONE2 (the persistent-swarm Nebula),
      * a Home Station exists to tether to (``hs`` not None) -- with no
        base there is nothing to retreat toward, so the bot keeps
        roaming to build one,
      * the bot is farther than the tether distance from that HS -- the
        generous ``ZONE2_TETHER_DIST_PX`` normally, but shortened to
        ``ZONE2_TETHER_UNHEALED_DIST_PX`` when no shield_recharge is
        equipped and ``ZONE2_TETHER_RECOVERING_DIST_PX`` while modules are
        pending re-install (the tighter of whichever apply wins),
      * a dense swarm (>= RETREAT_SWARM_ALIEN_COUNT within
        RETREAT_SWARM_RANGE_PX) is adjacent.

    Captured 2026-06-02: 20 edge-stucks while ENGAGE + 2 deaths fighting
    55-60 aliens 2500-4600 px from the HS -- the bot chased
    loot / asteroids / aliens deep into a swarm with no win condition.
    This sits BELOW ENGAGE (so the bot still defends a close threat) and
    below RETREAT / REGEN (so a hurt bot still flees / heals first), but
    ABOVE GATHER / MINE / HUNT -- when it fires the caller returns
    S_IDLE_AT_BASE, whose handler drives the bot back to the HS ring.
    """
    if hs is None:
        return False
    zone_id = str((state.get("zone") or {}).get("id", ""))
    if "ZONE2" not in zone_id:
        return False
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    hs_dist = math.hypot(float(hs.get("x", 0.0)) - px,
                         float(hs.get("y", 0.0)) - py)
    # Heal-aware distance (2026-06-06 evening): with NO shield_recharge
    # equipped the bot can't survive the swarm out in the open, so tether
    # it much closer to the HS umbrella.  Captured: a 4-death spiral far
    # from base (hs_dist 2200-6182) once the bot ran dry of heals.  When a
    # heal IS equipped the normal generous operating radius applies.
    tether_dist = _ap.ZONE2_TETHER_DIST_PX
    if not _bot_has_ready_shield_consumable(state):
        tether_dist = min(tether_dist, _ap.ZONE2_TETHER_UNHEALED_DIST_PX)
    # Recovery-aware distance (2026-06-06 evening): while the bot is
    # rebuilding its loadout after a death -- a combat module that was
    # dropped at death is still queued for re-install -- keep it close to
    # the HS so it gets back to the crafter and re-installs instead of
    # re-engaging the swarm half-equipped.  Independent of the heal check
    # above: the bot can be topped up on heals yet still be missing every
    # module.  Keyed on the intersection of the install queue with the
    # modules lost at the last death (``death_recovery_modules``) so this
    # fires ONLY for a post-death re-install, NOT the initial module
    # install (when ``modules_to_install`` is the never-installed default
    # set and ``death_recovery_modules`` is empty).
    if (set(_ap._state.queue.modules_to_install)
            & set(_ap._state.death_recovery_modules)):
        tether_dist = min(tether_dist, _ap.ZONE2_TETHER_RECOVERING_DIST_PX)
    if hs_dist <= tether_dist:
        return False
    swarm = sum(
        1 for a in (state.get("aliens") or [])
        if math.hypot(float(a.get("x", 0.0)) - px,
                      float(a.get("y", 0.0)) - py)
        <= _ap.RETREAT_SWARM_RANGE_PX)
    return swarm >= _ap.RETREAT_SWARM_ALIEN_COUNT


def _housekeeping_short_circuits(state: dict, p: dict) -> None:
    """Section 0: unconditional latches that fire every tick before
    any priority branch.

    Each gate handles a "loaded save / prior session / manual
    placement" edge case where pre-existing world state should mark
    a one-shot phase as already done -- otherwise the FSM would
    re-run the phase needlessly:

      * ``build_done`` latches on a Home Station in MAIN.
      * ``nebula_build_done`` latches on a Home Station in ZONE2.
      * ``fortify_done`` latches on QWI_STAGE_MIN_TURRETS defenders.
      * ``queue.consumable_phase_started`` latches when 25 + 25
        consumables already exist anywhere.
      * Module-craft queue heads are popped when those modules
        already sit in station inventory / on the ship.

    Each gate is an independent, idempotent check.  Extracted from
    ``choose_next_state`` in the 2026-05-24 PR 7 refactor.
    """
    if (not _ap._state.build_done
            and _ap._find_home_station(state) is not None):
        _ap._state.build_done = True
        _ap._telemetry_log("build_done_short_circuit",
                       reason="home_station_already_exists",
                       **_ap._telemetry_snapshot_fields(state, p))
    if not _ap._state.nebula_build_done:
        zone_id_short = str((state.get("zone") or {}).get("id", ""))
        if ("ZONE2" in zone_id_short
                and _ap._find_home_station(state) is not None):
            _ap._state.nebula_build_done = True
            _ap._telemetry_log(
                "nebula_build_done_short_circuit",
                reason="home_station_already_exists_in_zone2",
                **_ap._telemetry_snapshot_fields(state, p))
    if not _ap._state.fortify_done:
        defenders = sum(
            1 for b in (state.get("buildings") or [])
            if (b.get("building_type") or "") in (
                "Defense Turret", "Turret 2", "Missile Array"))
        if defenders >= _ap.QWI_STAGE_MIN_TURRETS:
            _ap._state.fortify_done = True
            _ap._telemetry_log("fortify_done_short_circuit",
                           reason=f"defenders_{defenders}_meets_min",
                           **_ap._telemetry_snapshot_fields(state, p))
    # Mirror short-circuit for the Nebula fortify ring.  Zone-gated
    # so a loaded save / manual placement in Nebula latches
    # ``nebula_fortify_done`` without affecting the MAIN ``fortify_done``
    # latch (the bot might be in Nebula visiting a pre-existing
    # ring while MAIN itself is unfortified).  Buildings are
    # zone-scoped via the ZoneState stash mechanism so the
    # building_list this tick is whichever zone the bot is in.
    if not _ap._state.nebula_fortify_done:
        _zone_id_fortify = str((state.get("zone") or {}).get("id", ""))
        if "ZONE2" in _zone_id_fortify:
            defenders = sum(
                1 for b in (state.get("buildings") or [])
                if (b.get("building_type") or "") in (
                    "Defense Turret", "Turret 2", "Missile Array"))
            if defenders >= _ap.QWI_STAGE_MIN_TURRETS:
                _ap._state.nebula_fortify_done = True
                _ap._telemetry_log(
                    "nebula_fortify_done_short_circuit",
                    reason=f"defenders_{defenders}_meets_min_in_zone2",
                    **_ap._telemetry_snapshot_fields(state, p))
    # Mirror short-circuit for the Nebula Advanced Crafter.  Zone-
    # gated like the fortify-ring one: if the current zone is ZONE2
    # AND the building_list already contains an Advanced Crafter
    # (loaded save / manual placement / a prior session that placed
    # one before the latch was persisted), latch the flag so
    # ``S_BUILD_ADV_CRAFTER`` never re-fires and the advanced-module
    # auto-queue stays consistent with the world state.
    if not _ap._state.nebula_advanced_crafter_done:
        _zone_id_adv = str((state.get("zone") or {}).get("id", ""))
        if ("ZONE2" in _zone_id_adv
                and _ap._advanced_crafter_already_built(state)):
            _ap._state.nebula_advanced_crafter_done = True
            _ap._telemetry_log(
                "nebula_advanced_crafter_done_short_circuit",
                reason="advanced_crafter_already_in_zone2",
                **_ap._telemetry_snapshot_fields(state, p))
    if not _ap._state.queue.consumable_phase_started:
        sitems = (state.get("station_inventory") or {}).get("items") or {}
        iitems = (state.get("inventory") or {}).get("items") or {}
        quick_use = state.get("quick_use_slots") or []
        quick_repair = sum(
            int(s.get("count", 0)) for s in quick_use
            if s.get("item_type") == "repair_pack")
        quick_shield = sum(
            int(s.get("count", 0)) for s in quick_use
            if s.get("item_type") == "shield_recharge")
        total_repair = (int(sitems.get("repair_pack", 0))
                        + int(iitems.get("repair_pack", 0))
                        + quick_repair)
        total_shield = (int(sitems.get("shield_recharge", 0))
                        + int(iitems.get("shield_recharge", 0))
                        + quick_shield)
        # Each batch yields 5 of the consumable.
        needed_repair = _ap.REPAIR_PACK_CRAFT_BATCHES * 5
        needed_shield = _ap.SHIELD_RECHARGE_CRAFT_BATCHES * 5
        if (total_repair >= needed_repair
                and total_shield >= needed_shield):
            _ap._state.queue.consumable_phase_started = True
            _ap._state.queue.repair_packs_remaining = 0
            _ap._state.queue.shield_recharges_remaining = 0
            _ap._telemetry_log(
                "consumable_phase_done_short_circuit",
                reason=(f"repair_{total_repair}_shield_{total_shield}"
                        f"_meets_{needed_repair}_{needed_shield}"),
                **_ap._telemetry_snapshot_fields(state, p))
    if not _ap._state.queue.module_phase_started \
            and _ap._state.queue.modules_to_craft:
        sitems = (state.get("station_inventory") or {}).get("items") or {}
        installed = set(
            m for m in (state.get("module_slots") or []) if m)
        popped = 0
        while _ap._state.queue.modules_to_craft:
            head = _ap._state.queue.modules_to_craft[0]
            already_in_station = int(sitems.get(f"mod_{head}", 0)) >= 1
            already_installed = head in installed
            if already_in_station or already_installed:
                _ap._state.queue.modules_to_craft.pop(0)
                popped += 1
                continue
            break
        if popped > 0:
            if not _ap._state.queue.modules_to_craft:
                _ap._state.queue.module_phase_started = True
            _ap._telemetry_log(
                "module_craft_phase_short_circuit",
                popped=popped,
                queue_remaining=list(
                    _ap._state.queue.modules_to_craft),
                **_ap._telemetry_snapshot_fields(state, p))
    # Advanced (Nebula-tier) module auto-queue (2026-05-24,
    # extended 2026-05-25).  When the bot is in ZONE2:
    #
    #   * If the module is already crafted (``mod_<key>`` in
    #     station inventory) and not yet on the ship, append to
    #     ``modules_to_install`` -- the existing INSTALL pipeline
    #     picks it up.
    #   * If the module's blueprint (``bp_<key>``) is in station
    #     inventory but the module itself isn't yet crafted, and
    #     an Advanced Crafter exists in the zone (latched flag OR
    #     building list inspection), append to
    #     ``modules_to_craft`` -- the existing CRAFT pipeline
    #     picks it up.
    #
    # Restricted to ZONE2 so the bot doesn't try to use MAIN
    # station inventory for Nebula modules before the Nebula
    # station is established.  Skips entries already in either
    # queue to avoid double-appends.
    _zone_id_adv = str((state.get("zone") or {}).get("id", ""))
    if "ZONE2" in _zone_id_adv:
        sitems_adv = (state.get("station_inventory")
                      or {}).get("items") or {}
        installed_adv = set(
            m for m in (state.get("module_slots") or []) if m)
        queued = set(_ap._state.queue.modules_to_install)
        queued.update(_ap._state.queue.modules_to_craft)
        adv_crafter_present = (
            _ap._state.nebula_advanced_crafter_done
            or _ap._advanced_crafter_already_built(state))
        for key in _ap.NEBULA_ADVANCED_MODULES:
            if key in installed_adv or key in queued:
                continue
            # Path A -- already crafted, just install.
            if int(sitems_adv.get(f"mod_{key}", 0)) >= 1:
                _ap._state.queue.modules_to_install.append(key)
                _ap._telemetry_log(
                    "nebula_advanced_module_queued",
                    module=key, phase="install",
                    **_ap._telemetry_snapshot_fields(state, p))
                continue
            # Path B -- blueprint present + Advanced Crafter exists,
            # queue for crafting.
            if (adv_crafter_present
                    and int(sitems_adv.get(f"bp_{key}", 0)) >= 1):
                _ap._state.queue.modules_to_craft.append(key)
                _ap._telemetry_log(
                    "nebula_advanced_module_queued",
                    module=key, phase="craft",
                    **_ap._telemetry_snapshot_fields(state, p))
        # Prune non-target modules from the install/craft queues
        # (2026-06-07).  Once the Advanced Crafter exists, the Nebula
        # goal is the 4-slot ``NEBULA_TARGET_LOADOUT`` (the three advanced
        # modules + broadside).  A Nebula death re-queues the WHOLE lost
        # loadout for install (``_observe_death_edges`` copies the dead
        # ship's ``module_slots`` into ``modules_to_install``), so the
        # MAIN-loadout modules -- ``shield_booster`` / ``shield_enhancer``
        # / ``armor_plate`` -- get re-queued even though they aren't in
        # the target set.  The bot then burns install cycles re-installing
        # a module the swap planner immediately uninstalls again to make
        # room for an advanced one (a ping-pong).  Drop any non-target
        # module from both queues so the bot stops trying to install the
        # shield booster once the three advanced modules + broadside are
        # the goal.  The craft queue keeps the advanced consumable recipes
        # (homing_missile / mining_drone / combat_drone), which aren't
        # ship modules.
        if adv_crafter_present:
            q = _ap._state.queue
            before = len(q.modules_to_install)
            q.modules_to_install[:] = [
                k for k in q.modules_to_install
                if k in _ap.NEBULA_TARGET_LOADOUT]
            q.modules_to_craft[:] = [
                k for k in q.modules_to_craft
                if k in _ap.NEBULA_TARGET_LOADOUT
                or k in _ap.NEBULA_ADV_CONSUMABLE_TARGETS]
            pruned = before - len(q.modules_to_install)
            if pruned:
                _ap._telemetry_log(
                    "nebula_install_queue_pruned",
                    pruned=pruned,
                    install_queue=list(q.modules_to_install),
                    **_ap._telemetry_snapshot_fields(state, p))
        # Advanced (Nebula-tier) consumable auto-queue (2026-05-26).
        # When the bot is in ZONE2 with an Advanced Crafter built,
        # the matching blueprint deposited, and the produced item
        # stock below its target, queue the recipe for crafting.
        # The auto-pop guard in ``_next_craft_target`` removes the
        # entry once stock meets the target.  Currently covers
        # homing_missile / mining_drone / combat_drone; the bot
        # uses missiles via Death Blossom (PR #186) and drones via
        # the in-game "R" dispatch.
        if adv_crafter_present:
            for craft_key, (item_key, target_count) \
                    in _ap.NEBULA_ADV_CONSUMABLE_TARGETS.items():
                if craft_key in queued:
                    continue
                if int(sitems_adv.get(f"bp_{craft_key}", 0)) < 1:
                    continue
                if int(sitems_adv.get(item_key, 0)) >= target_count:
                    continue
                _ap._state.queue.modules_to_craft.append(craft_key)
                queued.add(craft_key)
                _ap._telemetry_log(
                    "nebula_advanced_consumable_queued",
                    recipe=craft_key, item_key=item_key,
                    target=target_count,
                    have=int(sitems_adv.get(item_key, 0)),
                    **_ap._telemetry_snapshot_fields(state, p))


def _regen_decision(state: dict, p: dict, cur: str,
                    threat, td: float) -> str | None:
    """Section 1 (REGEN): shields hurt -- sit still and recover.
    Returns ``_ap.S_REGEN`` to enter or stay in REGEN, or ``None`` to
    fall through to the rest of the cascade.  ``threat`` / ``td`` are the
    nearest-threat signals computed once in ``choose_next_state`` (with
    the boss injected) and reused by the ENGAGE tier.

    REGEN preempts ENGAGE/GATHER/MINE so the bot actually idles instead
    of burning thrust while shields are low.

    REGEN escape valve (added 2026-05-04): the original "always return
    REGEN while shields < REGEN_EXIT_PCT" rule deadlocks when the bot
    starts already low on shields with nearby aliens still firing -- the
    bot sits idle, takes damage, can never reach the exit threshold, and
    dies.  Telemetry caught this clearly: 78 s session, 23 stuck_detected
    events all in REGEN with shields=0, 0 iron collected.  Fix: if a
    threat is within ENGAGE_ENTER_PX AND shields are NOT recovering
    between ticks, fall through and let ENGAGE (or other priorities) take
    over -- better to fight back at low HP than die idling.
    """
    sh = int(p.get("shields", 0))
    sh_max = max(1, int(p.get("max_shields", 1)))
    pct = sh / sh_max
    boss = state.get("boss")
    # Boss-alive thresholds (2026-05-13 fourteenth telemetry pass):
    # when a boss is alive, regen further before re-engaging.  Death-
    # loop captured in the log was: post-recovery install → engage_boss
    # fired at shields=54/120 (45 %), one lure trigger later (35 %),
    # then died.  Escape valve still applies, so boss-in-range still
    # gets engaged regardless of threshold.
    #
    # Nebula thresholds (2026-05-24, post-PR #184 telemetry): mirror
    # the boss-alive logic for non-MAIN zones.  Captured: second
    # death of the post-merge session was in fsm=regen in ZONE2 --
    # bot tried to recover under fire and lost the damage-vs-regen
    # trade.  Boss-alive takes precedence (it's strictly more
    # dangerous); otherwise non-MAIN gets the elevated threshold.
    _zone_id_for_regen = str((state.get("zone") or {}).get("id", ""))
    _in_main_for_regen = (
        "MAIN" in _zone_id_for_regen
        and "WARP" not in _zone_id_for_regen)
    if boss is not None:
        regen_enter = _ap.REGEN_ENTER_PCT_BOSS_ALIVE
        regen_exit = _ap.REGEN_EXIT_PCT_BOSS_ALIVE
    elif not _in_main_for_regen and _zone_id_for_regen:
        regen_enter = _ap.REGEN_ENTER_PCT_NEBULA
        regen_exit = _ap.REGEN_EXIT_PCT_NEBULA
    else:
        regen_enter = _ap.REGEN_ENTER_PCT
        regen_exit = _ap.REGEN_EXIT_PCT
    # Outside-base swarm gate for REGEN (PR #162 -> #165 -> 2026-05-24).
    #
    # History:
    #   * PR #162 introduced REGEN swarm-suppress in WARP zones only,
    #     so the bot could push through WARP_ENEMY arcs instead of
    #     idling under fire.
    #   * PR #165 broadened to all non-MAIN zones to cover the
    #     ZONE2 / Nebula / STAR_MAZE swarm patterns.
    #   * 2026-05-24 (this change): mirrored PR #169's ENGAGE
    #     fix -- the broadening was too aggressive when the bot
    #     had no productive alternative to fall through to.  With
    #     ENGAGE conditionally allowed (defend) and REGEN
    #     unconditionally suppressed, the bot exited REGEN ->
    #     entered ENGAGE -> ENGAGE preempted REGEN again, leaving
    #     no path to actual healing once an HS exists.  Now both
    #     gates condition on the same productive-alternative
    #     check, so they release together when the bot should
    #     defend AND hold together when there's a productive
    #     traverse / build goal.
    #
    # If no productive alt is viable, REGEN behaves normally --
    # the bot idles (or drives to HS per PR #167) for recovery,
    # combat assist defends reflexively, consumables auto-trigger.
    # That's the correct behavior in MAIN swarms and in ZONE2 /
    # STAR_MAZE with HS available.
    zone_id_regen = str((state.get("zone") or {}).get("id", ""))
    # Productive-alternative gate shared with section 2 (ENGAGE);
    # see ``_outside_main_swarm_suppresses`` for the predicate.
    in_warp_swarm = _outside_main_swarm_suppresses(
        state, zone_id_regen, _ap.WARP_SWARM_REGEN_SUPPRESS_ALIENS)
    # Warp zones inflict ENVIRONMENTAL damage (meteors / gas / bolts)
    # and have no Home Station to heal at, so REGEN's idle just bleeds
    # the bot out -- it must keep MOVING (WARP_TRAVERSE) toward the exit.
    # Used to suppress both REGEN entry AND stay below.
    in_warp_zone = "WARP" in zone_id_regen

    if cur == _ap.S_REGEN:
        if pct < regen_exit:
            # Time-based hysteresis (2026-05-13 fifteenth pass):
            # the escape valve previously fired on a SINGLE tick
            # where shields didn't gain ground.  Captured in the
            # log: shields 50 → 68 over 12 s (clearly recovering),
            # one damage spike flipped ``shields_recovering`` to
            # False on a single tick, the valve fired, and the
            # bot exited REGEN mid-recovery into recover_loot
            # where the boss killed it 3 more times near the
            # station.  Now require
            # ``REGEN_NO_PROGRESS_TIMEOUT_S`` seconds of sustained
            # no-progress before the valve fires.
            now = _ap._get_now()
            if sh > _ap._state.last_regen_shields:
                _ap._state.last_regen_shields = sh
                _ap._state.last_regen_progress_at = now
            elif _ap._state.last_regen_progress_at == 0.0:
                # First tick after REGEN entry -- initialize timer.
                _ap._state.last_regen_progress_at = now
            no_progress_s = (now - _ap._state.last_regen_progress_at)
            # Fast-drop shortcut (2026-05-14 eighteenth pass): if
            # shields have dropped more than REGEN_FAST_DROP_PX
            # from the high water mark, damage rate exceeds regen
            # rate and the 1.5 s timer would let the bot die before
            # firing.  Bypass the timer in that case.
            shields_dropped_px = (_ap._state.last_regen_shields - sh)
            shields_stalled = (
                no_progress_s >= _ap.REGEN_NO_PROGRESS_TIMEOUT_S
                or shields_dropped_px >= _ap.REGEN_FAST_DROP_PX)
            threatened = (threat is not None
                          and td < _ap.ENGAGE_ENTER_PX)
            # Warp-zone escape (2026-05-17): captured pathology --
            # bot died at y=5266 in WARP_METEOR after 20 s of REGEN
            # idle with shields oscillating 4-39.  Warp zones have
            # ENVIRONMENTAL damage (meteors, gas, lightning bolts)
            # but no alien threat objects, so the threatened+stalled
            # gate never fires.  REGEN's default action is _do_idle
            # while environmental damage chews through whatever the
            # heal-shield cooldown can recover -- bot bleeds out.
            # Exit REGEN regardless of threat when shields are
            # stalled in a warp zone so the cascade re-routes to
            # S_WARP_TRAVERSE and the bot keeps driving north
            # toward the arrival band.  (``in_warp_zone`` computed once
            # above, before the entry/stay split.)
            if (threatened or in_warp_zone) and shields_stalled:
                # Escape valve — sustained no-progress under threat
                # OR in a warp zone with environmental damage means
                # we're truly deadlocked.  Let priority cascade pick
                # ENGAGE / WARP_TRAVERSE (or whatever fits).  Don't
                # update trackers so a future REGEN re-entry starts
                # fresh.
                pass
            elif in_warp_swarm:
                # Swarm escape valve (2026-05-23): in a warp zone
                # with many aliens, REGEN's idle is fatal even when
                # shields haven't formally stalled yet.  Exit
                # immediately so WARP_TRAVERSE can keep the bot
                # moving.  No stall-timer wait -- the bot can't
                # afford the 1.5 s under swarm DPS.
                pass
            else:
                return _ap.S_REGEN
        else:
            # Shields fully recovered — leave REGEN cleanly.
            _ap._state.last_regen_shields = 0
            _ap._state.last_regen_progress_at = 0.0
    else:
        if pct < regen_enter:
            # Entry-side mirror of the escape valve: don't enter
            # REGEN if a close threat is already engaging us.  The
            # escape valve in the cur==_ap.S_REGEN branch above would
            # immediately exit on the very next tick anyway, so
            # entering and exiting in a 0.1 s loop just burns FSM
            # cycles + telemetry without doing useful work.
            #
            # Telemetry from the previous session caught the
            # pathology: 111 REGEN <-> ENGAGE transitions in a
            # single combat encounter, median dwell 0.09 s (one
            # tick — both states bypass MIN_DWELL as defensive
            # interrupts).  Plus 14 stuck_detected misfires in the
            # tiny REGEN visits since REGEN action is _do_idle().
            #
            # Better: stay in ENGAGE for the duration of combat,
            # let combat assist + character bonuses keep firing,
            # transition to REGEN only after disengaging.
            threatened = (threat is not None
                          and td < _ap.ENGAGE_ENTER_PX)
            if threatened:
                pass  # stay in current state; ENGAGE/etc preempts
            elif in_warp_swarm:
                # Warp-swarm suppression (2026-05-23): even with no
                # specific alien close enough to trigger ``threatened``,
                # a warp zone full of aliens is no place to idle.
                # Stay in WARP_TRAVERSE (or whatever cur is) so the
                # bot keeps moving toward the exit; combat assist +
                # auto-fired consumables handle defense.  Mirrors the
                # ``suppress_engage_warp_swarm`` gate from PR #155.
                pass
            elif in_warp_zone:
                # Warp-zone entry suppression (2026-06-03): don't ENTER
                # REGEN in a warp zone at all.  The stay-side escape
                # valve above already kicks the bot out once shields
                # stall, but it kept RE-ENTERING on the next tick -- the
                # 2026-06-03 telemetry logged 100 regen<->warp_traverse
                # flips across 4 WARP_METEOR deaths, the bot idling in
                # the meteor field instead of committing to the
                # crossing.  Warp zones have no HS to heal at and
                # inflict environmental damage, so REGEN's idle is
                # always a loss here.  Stay in WARP_TRAVERSE so the bot
                # drives through fast (less time in the field = less
                # cumulative damage); combat assist + auto-heal
                # consumables handle defense en route.
                pass
            else:
                # Entering REGEN — initialize the trend baseline
                # AND the no-progress timer.
                _ap._state.last_regen_shields = sh
                _ap._state.last_regen_progress_at = _ap._get_now()
                return _ap.S_REGEN
    return None


def _engage_decision(state: dict, cur: str, threat, td: float,
                     hs_pri145, zone_id: str) -> str | None:
    """Section 2 (ENGAGE): an alien (or the injected boss) is within the
    engage band -- preempts GATHER/MINE/etc.  Returns ``_ap.S_ENGAGE`` to
    engage or ``None`` to fall through.  ``threat`` / ``td`` are the
    shared signals from ``choose_next_state`` (boss injected, so they
    don't get re-walked here); ``hs_pri145`` is the home-station lookup
    and ``zone_id`` the current zone, both already computed in the
    cascade.

    No-home-station suppression on boss-as-threat (2026-05-14 eighteenth
    pass): when the boss is the chosen threat AND there is no home
    station, charging into ENGAGE range = death.  The seventeenth-pass
    HS-loss fix already blocked ``engage_boss``, but the regular ENGAGE
    path still picked the boss up via the threat injection above (REGEN
    escape valve check) and routed to S_ENGAGE.  Captured as 5
    back-to-back ENGAGE deaths at sh=0-2 in 12 s.  Cascade falls through
    to GATHER / MINE / SEARCH which navigate by resource, not boss aggro.
    """
    boss_is_threat = (
        threat is not None
        and state.get("boss") is not None
        and threat is state.get("boss"))
    suppress_engage_no_hs = (
        boss_is_threat and hs_pri145 is None)
    # Outside-base swarm suppression (PR #155, broadened in #168,
    # then conditioned in 2026-05-23 v4).
    #
    # The original intent (#155) was: in a WARP_ENEMY swarm with
    # an active warp-traverse goal, suppress ENGAGE so the bot
    # keeps driving toward the exit instead of kiting one alien
    # while ~20 others shred it.  PR #168 broadened to all non-MAIN
    # zones to cover the ZONE2-post-boss kite-trap (48 aliens, no
    # Nebula HS yet -- bot needed to BUILD_NEBULA instead of
    # ENGAGE).
    #
    # But PR #168 was too broad: it suppressed ENGAGE in ZONE2
    # even when the bot HAD a Nebula HS and no productive
    # alternative -- the bot ended up mining/gathering defenseless
    # while aliens drained shields to 1/120.  User complaint:
    # "bot is not attacking back when it is attacked.  this should
    # always be a higher priority than gathering resources."
    #
    # Resolution: condition the suppression on a productive
    # alternative actually being viable this tick.  If WARP_TRAVERSE
    # would fire (post-boss arc not yet complete in a warp zone)
    # OR BUILD_NEBULA would fire (in ZONE2, no Nebula HS yet, iron
    # over threshold), suppress ENGAGE so that alternative goal
    # runs.  Otherwise let ENGAGE fire so the bot defends itself
    # instead of falling through to MINE / GATHER while being
    # attacked.
    # Productive-alternative gate shared with section 1 (REGEN);
    # see ``_outside_main_swarm_suppresses`` for the predicate.
    suppress_engage_warp_swarm = _outside_main_swarm_suppresses(
        state, zone_id, _ap.WARP_SWARM_ENGAGE_SUPPRESS_ALIENS)
    if not suppress_engage_no_hs and not suppress_engage_warp_swarm:
        if cur == _ap.S_ENGAGE:
            if threat is not None and td < _ap.ENGAGE_EXIT_PX:
                return _ap.S_ENGAGE
        else:
            if threat is not None and td < _ap.ENGAGE_ENTER_PX:
                return _ap.S_ENGAGE
    return None


def _tier_recover_loot(state, p, now) -> str | None:
    # 1.4  RECOVER_LOOT — after the bot just died, navigate back to
    #      the recorded death position so the dropped iron / module
    #      / consumable pickups vacuum into the ship.  Promoted above
    #      ENGAGE_BOSS (2026-05-11): without this the bot dies during
    #      a boss fight, respawns shieldless + moduleless, and is
    #      pulled straight back into S_ENGAGE_BOSS by section 1.5 —
    #      it never visits S_RECOVER_LOOT, so the lost loadout stays
    #      on the floor and the bot dies again with no modules
    #      installed.  Telemetry caught the death loop: 5 player_death
    #      events with lost_modules=[] after the first death, mod_q=4
    #      stuck in the install queue.  REGEN still preempts (above)
    #      so a half-recovered loadout doesn't get the bot killed
    #      mid-trip.
    _ap._maybe_clear_death_recovery(state, p, now)
    if _ap._state.death_recovery_pending:
        # Suppress recover_loot when re-entering the death pile
        # would walk the bot into the boss's aggro range with no
        # umbrella to retreat to.  2026-05-14 eighteenth-pass log
        # captured the pathology: 7 deaths in 17 s at the same
        # death pile while the boss hovered there.  Two gates:
        #   * boss alive AND boss within
        #     ``RECOVER_LOOT_BOSS_DANGER_PX`` of the death pos
        #     -- bot would respawn-cycle into the boss's range.
        #   * boss alive AND no home station -- nowhere to
        #     install recovered modules at, so recovery is
        #     pointless until HS rebuilds (or boss dies).
        # In both cases pending stays True (recovery resumes
        # when the danger clears) and the hard
        # ``DEATH_RECOVERY_TIMEOUT_S`` still applies, so the
        # FSM doesn't deadlock if the boss never leaves.
        boss = state.get("boss")
        recovery_blocked = False
        if boss is not None:
            drx, dry = _ap._state.death_recovery_pos
            bdx = float(boss.get("x", 0.0)) - drx
            bdy = float(boss.get("y", 0.0)) - dry
            boss_at_death_pos = (
                math.hypot(bdx, bdy)
                < _ap.RECOVER_LOOT_BOSS_DANGER_PX)
            no_hs = _ap._find_home_station(state) is None
            recovery_blocked = boss_at_death_pos or no_hs
        # Non-MAIN loadout gate (2026-05-26).  Captured 2026-05-25
        # pathology: the bot died during ``S_RECOVER_LOOT`` 53 s
        # after a Nebula death because it drove toward the death
        # pile naked + with cold weapons + no consumables in slots.
        # Defer recovery until shields / HP / consumables are
        # rebuilt; the bumped ``DEATH_RECOVERY_TIMEOUT_NEBULA_S``
        # gives the bot 180 s of headroom before it accepts the
        # loss.  MAIN-zone recoveries skip this -- the HS umbrella
        # + turret ring make recovery safe even with a stripped
        # ship.
        if not recovery_blocked \
                and not _ap._recovery_loadout_ready(state):
            recovery_blocked = True
        if not recovery_blocked:
            return _ap.S_RECOVER_LOOT
    return None


def _tier_build(state, p) -> str | None:
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    # 4. BUILD — one-shot starter base when iron + clear area
    #    conditions are met.  Falls below ENGAGE / REGEN so the
    #    bot doesn't try to build during combat or while shields
    #    are low.  Falls above MINE / SEARCH so the bot stops
    #    accumulating iron the moment it has enough and a clear
    #    spot.  ``_ap._state.build_done`` flips True after the first attempt.
    #    BUILD_SEEK actively walks toward less-cluttered space when
    #    iron is met but the area isn't clear.
    #
    #    The has-Home-Station short-circuit (see section 0
    #    above) flips ``build_done`` True the moment the bot
    #    sees an existing HS, so this branch only fires for a
    #    bot starting in a station-less world.
    if (not _ap._state.build_done
            and _ap._iron_total(state) >= _ap.BUILD_IRON_THRESHOLD):
        if _ap._build_area_clear(state, px, py):
            return _ap.S_BUILD
        return _ap.S_BUILD_SEEK

    # 4.5 BUILD_NEBULA — second starter base in ZONE2 (Nebula).
    #     Buildings are zone-scoped via the ZoneState stash
    #     mechanism (see ``zones/__init__.py``), so each zone has its
    #     own ``building_list``.  The ``Home Station`` BUILDING_TYPES
    #     max=1 cap is enforced against the current zone's list, not
    #     save-wide -- so the bot can build a MAIN base AND a Nebula
    #     base without conflict.  Gated by its own ``nebula_build_done``
    #     latch independently of ``build_done``, and restricted to
    #     ZONE2 (the only non-MAIN zone with persistent buildings
    #     where a base makes economic sense; STAR_MAZE is too
    #     space-constrained, WARP_* are transient).
    #
    #     Falls below the MAIN BUILD branch in priority -- if the bot
    #     somehow lands in ZONE2 without ever having built a MAIN
    #     base, the MAIN branch can't fire (wrong zone) so this one
    #     handles things.  But the typical flow is: MAIN built first
    #     (session 0), Nebula built later when the bot accumulates
    #     iron in ZONE2.  Same ``BUILD_SEEK`` shared with MAIN for the
    #     "area not clear, keep walking" sub-state.
    zone_id_build = str((state.get("zone") or {}).get("id", ""))
    in_zone2 = "ZONE2" in zone_id_build
    if (in_zone2
            and not _ap._state.nebula_build_done
            and _ap._iron_total(state) >= _ap.BUILD_IRON_THRESHOLD):
        if _ap._build_area_clear(state, px, py):
            return _ap.S_BUILD_NEBULA
        return _ap.S_BUILD_SEEK

    # 4.6 FORTIFY_NEBULA (2026-05-24) -- after the Nebula HS is up,
    #     add the same defense-turret + missile-array ring the MAIN
    #     HS gets in section 5.6.  Captured pathology (PR #184
    #     telemetry): bot's second Nebula death was in fsm=regen at
    #     the unfortified Nebula HS umbrella; building defenses
    #     gives the bot a safe combat anchor analogous to MAIN's.
    #
    #     Gates: in ZONE2, Nebula HS already up, fortify not yet
    #     done, station iron covers FORTIFY_IRON_COST plus a small
    #     buffer.  ``_act_fortify_nebula`` reuses ``_post_fortify``
    #     -- the builder anchors on the first Home Station in the
    #     current zone's building_list (zone-scoped), so calling
    #     it while the bot is in ZONE2 fortifies the Nebula HS.
    if (in_zone2
            and _ap._state.nebula_build_done
            and not _ap._state.nebula_fortify_done
            and _ap._find_home_station(state) is not None
            and _ap._station_iron(state) >= _ap.FORTIFY_IRON_COST):
        return _ap.S_FORTIFY_NEBULA

    # 4.7 PLACE_AI_PILOT_NEBULA (2026-05-24) -- park a Basic Ship
    #     with the AI Pilot module installed beside the Nebula HS
    #     so the bot has friendly-fire-immune cover fire while it
    #     fights the Nebula swarm.  Gated AFTER fortify (defenses
    #     first; AI pilot ship is the second-tier buff).  Requires
    #     a craftable ``ai_pilot`` module in station inventory,
    #     plus iron + copper to cover the Basic Ship cost.  Falls
    #     through silently if any prerequisite is missing -- the
    #     bot keeps fighting solo until the inputs accumulate.
    if (in_zone2
            and _ap._state.nebula_fortify_done
            and not _ap._state.nebula_ai_pilot_placed
            and _ap._find_home_station(state) is not None):
        _station_items_now = _ap._station_items(state)
        if (int(_station_items_now.get("ai_pilot", 0)) >= 1
                and int(_station_items_now.get("iron", 0))
                    >= _ap.AI_PILOT_SHIP_IRON_COST
                and int(_station_items_now.get("copper", 0))
                    >= _ap.AI_PILOT_SHIP_COPPER_COST):
            return _ap.S_PLACE_AI_PILOT_NEBULA

    # 4.8 BUILD_ADV_CRAFTER (2026-05-25) -- place an Advanced
    #     Crafter beside the Nebula HS so the bot can craft Nebula-
    #     tier modules (misty_step / force_wall / death_blossom)
    #     locally instead of having to warp back to MAIN for every
    #     craft.  Once present, the existing CRAFT pipeline drives
    #     it transparently -- both BasicCrafter and AdvancedCrafter
    #     register as ``BasicCrafter`` instances internally, so
    #     ``_find_idle_basic_crafter`` returns whichever is idle.
    #     Gated AFTER ai-pilot ship (defenses then cover fire then
    #     advanced crafting -- the tier-up chain).  Requires the
    #     ``advanced_crafter`` blueprint deposited + 1000 iron +
    #     500 copper.
    if (in_zone2
            and _ap._state.nebula_fortify_done
            and not _ap._state.nebula_advanced_crafter_done
            and _ap._find_home_station(state) is not None
            and not _ap._advanced_crafter_already_built(state)):
        _station_items_adv = _ap._station_items(state)
        # Blueprint key fix (2026-06-06): a collected blueprint pickup
        # adds ``bp_<module>`` to inventory (game_view:448, pickup:102),
        # so the advanced-crafter blueprint lands in the station as
        # ``bp_advanced_crafter`` -- NOT ``advanced_crafter``.  The gate
        # checked the un-prefixed key, so it never saw the blueprint and
        # the Advanced Crafter was never built (the whole Nebula
        # module/drone tier stayed dormant despite the bot gathering the
        # blueprint).  ``place_advanced_crafter`` is fixed to match.
        if (int(_station_items_adv.get("bp_advanced_crafter", 0)) >= 1
                and int(_station_items_adv.get("iron", 0))
                    >= _ap.ADVANCED_CRAFTER_IRON_COST
                and int(_station_items_adv.get("copper", 0))
                    >= _ap.ADVANCED_CRAFTER_COPPER_COST):
            return _ap.S_BUILD_ADV_CRAFTER
    return None


def _tier_craft_install_bossprep(state, p, hs) -> str | None:
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    # 5.5  CRAFT / INSTALL — sequential post-build workflow.  Only
    #      reachable after a Home Station + Basic Crafter exist.
    #      Install takes priority over a fresh craft (we want
    #      crafted modules onto the ship before queuing more).
    #      Both gates require the FSM to NOT already have a
    #      crafter mid-cycle — the queue is intentionally serial,
    #      so the bot returns to MINE / GATHER / SEARCH while a
    #      craft ticks down its 60 s timer.
    if hs is not None and _ap._find_basic_crafter(state, idle_only=False) is not None:
        if _ap._next_install_target(state) is not None:
            return _ap.S_INSTALL
        if not _ap._any_crafter_busy(state) and _ap._next_craft_target(state) is not None:
            return _ap.S_CRAFT

    # 5.6  Boss-prep pipeline — fires once the consumable craft
    #      queue is fully drained (25 repair packs + 25 shield
    #      recharges produced, all sitting in station inventory).
    #      Three sequential one-shot stages; each flips a sticky
    #      flag on success so the FSM never re-fires it:
    #
    #        a) _ap.S_EQUIP_CONSUMABLES — withdraw consumables from
    #           station inventory + bind them to ship quick-use
    #           slots.  Falls through immediately if no consumables
    #           remain in station inventory (already withdrawn).
    #        b) _ap.S_PRE_BOSS_MINE     — if station iron is below the
    #           _ap.QWI_BUILD_IRON_TARGET buffer (default 2000), keep
    #           mining.  Same action handler as _ap.S_MINE, but the
    #           FSM-level distinction tracks the explicit mining
    #           goal so telemetry can see it.
    #        c) _ap.S_BUILD_QWI         — iron staged + QWI not yet
    #           placed: navigate to the Home Station and POST
    #           /place_qwi.  The QWI auto-spawns the Double Star
    #           boss; from there _ap.S_ENGAGE_BOSS takes over.
    # EQUIP CONSUMABLES — decoupled from the full consumable phase
    # (2026-06-03).  Bind any available repair_pack / shield_recharge to
    # the quick-use slots whenever a slot lacks one AND the station has
    # one to give -- WITHOUT waiting for the entire 25 + 25 batch phase
    # to finish.  Captured: a 55-min, 9-death session logged
    # heal_shield_fire = 0 (armed 13x, never fired) because no
    # shield_recharge was ever in a quick-use slot.  The bot crafted
    # shield_recharge into the station, but the old gate
    # (``_consumable_phase_finished()``) refused to equip until ALL 50
    # batches completed -- and repeated deaths kept resetting the module/
    # consumable grind, so the phase never finished and the bot fought
    # with no shield heal.  Binding partial stock immediately gives the
    # bot a working heal while it finishes crafting the rest.
    #
    # Self-heal by checking the actual quick-use slot state, not just the
    # ``consumables_equipped`` latch (2026-05-11 fifth pass): the latch
    # alone misses the post-death case where the bot deposits recovered
    # consumables but the latch stayed True from session start.  Checking
    # the live slot contents makes the gate fire whenever a slot needs a
    # consumable AND station has one.  The latch is still the one-tick
    # MIN_DWELL-skip helper inside ``_act_at_station``.
    if hs is not None:
        quick_use = state.get("quick_use_slots") or []
        sitems = _ap._station_items(state)

        # Per-TYPE check (2026-06-06): the old gate used "ANY consumable
        # equipped", so a bound repair_pack masked a MISSING
        # shield_recharge -- the bot never re-equipped the shield heal
        # while it still had repair packs.  Captured: the station held
        # 5-15 shield_recharge for ~540 s but the bot never bound them
        # and died at 1 shield with heals sitting unequipped (25 hp-heal
        # fires in that window confirm repair_pack WAS equipped).  Fire
        # EQUIP if EITHER type is missing from a quick-use slot AND the
        # station has that type to give -- ``equip_consumables_to_quick_use``
        # binds both, so one POST tops up whichever is missing.
        def _equipped(item_type: str) -> bool:
            return any(
                s and s.get("item_type") == item_type
                and int(s.get("count", 0)) > 0
                for s in quick_use)
        needs_repair = (not _equipped("repair_pack")
                        and int(sitems.get("repair_pack", 0)) > 0)
        needs_shield = (not _equipped("shield_recharge")
                        and int(sitems.get("shield_recharge", 0)) > 0)
        if needs_repair or needs_shield:
            # Reset the latch so ``_act_equip_consumables`` actually
            # POSTs.  The action's skip-condition is the latch
            # itself; a stale-True latch from a previous session
            # would otherwise make the action ``_do_idle`` forever.
            _ap._state.consumables_equipped = False
            return _ap.S_EQUIP_CONSUMABLES

    # Boss-prep staging (PRE_BOSS_MINE / FORTIFY / BUILD_QWI) still waits
    # for the FULL consumable phase to finish so the bot faces the Double
    # Star boss fully stocked (25 repair + 25 shield), not on partial
    # supply.  The equip-to-quick-use above is independent of this.
    if hs is not None and _ap._consumable_phase_finished():
        if not _ap._state.qwi_placed \
                and not _ap._qwi_already_built(state):
            station_iron = _ap._station_iron(state)
            # Iron gate covers the fortify ring (_ap.FORTIFY_IRON_COST)
            # AND the QWI cost (1000) — keep mining until the
            # buffer is enough that placing fortify won't drop the
            # station below the QWI cost cushion.  Without this the
            # bot could fortify, drain iron, and then PRE_BOSS_MINE
            # again to refill before BUILD_QWI fires.
            if station_iron < _ap.QWI_BUILD_IRON_TARGET:
                # Still mining toward the iron buffer — fall back
                # to the normal MINE / SEARCH cascade below but
                # tag it as PRE_BOSS_MINE so telemetry knows we're
                # heading toward the QWI build.
                if _ap._nearest_asteroid(state, px, py)[0] is not None:
                    return _ap.S_PRE_BOSS_MINE
            else:
                # Fortify before the QWI build so the cluster has
                # the full defensive ring (matches the bumped
                # _ap.QWI_STAGE_MIN_TURRETS).  The ``_qwi_ready_to_build``
                # gate also enforces the turret count, so even if
                # the bot crashed/restarted between fortify and QWI
                # the latched flag would re-evaluate from current
                # building snapshot before BUILD_QWI fires.
                if not _ap._state.fortify_done:
                    return _ap.S_FORTIFY
                return _ap.S_BUILD_QWI
    return None


def _tier_mine_or_search(state, p, cur, now) -> str | None:
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    # 6. MINE vs SEARCH — discrete event, no hysteresis needed.
    #    Filter out blacklisted asteroids so a single unreachable
    #    one doesn't force MINE to fire on a target the bot
    #    can't actually reach.  Also cap chase distance: an
    #    asteroid farther than _ap.MAX_ASTEROID_CHASE_PX is treated
    #    as out-of-reach so MINE falls through to SEARCH (spiral
    #    around current position) instead of long obstacle-laden
    #    trips across the world.
    #
    #    Escape hatch: if SEARCH **or IDLE_AT_BASE** has been the
    #    active state for _ap.SEARCH_GIVEUP_S, drop the cap and commit
    #    to whatever's _ap.nearest.  A long round trip is better than
    #    parking / spiralling indefinitely in a region with no
    #    in-range asteroids.  IDLE_AT_BASE was added to the gate
    #    in 2026-05-09 — the original gate only covered SEARCH,
    #    so a bot with a Home Station (which routes through
    #    IDLE_AT_BASE in section 8 below when nothing's
    #    actionable) would mine all the near asteroids, then
    #    park forever as far asteroids respawned out of chase
    #    range.  User report: "the bot does not go after asteroids
    #    when all of the enemies have been destroyed and it is
    #    idling at the station."
    #
    #    The commitment is STICKY (``_ap._state.chase_committed``):
    #    once we decide to chase a far target, the cap stays
    #    dropped until the bot reaches chase range — otherwise
    #    the FSM bounces ↔ MINE every MIN_DWELL_S because
    #    ``long_giveup`` only holds while ``cur`` is in the gate.
    nearest_ast, ast_d = _ap._nearest_asteroid(state, px, py)
    if nearest_ast is not None:
        in_chase_range = ast_d < _ap.MAX_ASTEROID_CHASE_PX
        # Gather->mine hysteresis (2026-06-02): the mirror of the
        # mine->gather guard in section 3.  While actively GATHERing,
        # only a genuinely-close asteroid (MINE_ENTER_WHILE_GATHERING_PX)
        # preempts to MINE -- finishing a gather used to dart the bot to
        # a mid-range asteroid (287 dwell-suppressed gather->mine flips),
        # which then dropped iron and pulled it back.  The full chase cap
        # still drives the commit / giveup machinery below, so a far
        # asteroid keeps its SEARCH / IDLE_AT_BASE giveup escape hatch.
        gather_holds_mine = (
            cur == _ap.S_GATHER
            and ast_d >= _ap.MINE_ENTER_WHILE_GATHERING_PX)
        if in_chase_range:
            # Reached (or approached) a chase-range asteroid —
            # clear any prior commitment so future SEARCH /
            # IDLE_AT_BASE episodes get the normal cap-protected
            # behaviour.
            _ap._state.chase_committed = False
            if not gather_holds_mine:
                return _ap.S_MINE
        # Out of chase range.  Either we're already committed
        # to a far chase, or we've been waiting (in SEARCH or
        # IDLE_AT_BASE) long enough to commit now.  IDLE_AT_BASE
        # uses a tighter gate (``_ap.IDLE_AT_BASE_GIVEUP_S``, 10 s)
        # than SEARCH (``_ap.SEARCH_GIVEUP_S``, 60 s) because at base
        # the bot is genuinely idle — the long wait left users
        # observing "the bot does not leave when there are
        # asteroids available to be harvested" (2026-05-09 report).
        search_entered = _ap._fsm.get("entered_at")
        if cur == _ap.S_IDLE_AT_BASE:
            giveup_threshold = _ap.IDLE_AT_BASE_GIVEUP_S
        elif cur == _ap.S_SEARCH:
            giveup_threshold = _ap.SEARCH_GIVEUP_S
        else:
            giveup_threshold = float("inf")
        long_giveup = (
            search_entered is not None
            and (now - search_entered) >= giveup_threshold
        )
        if _ap._state.chase_committed or long_giveup:
            _ap._state.chase_committed = True
            return _ap.S_MINE
    else:
        # No visible asteroid (everything blacklisted, or none
        # in /state) — clear the commitment so the next time an
        # asteroid appears we start fresh.
        _ap._state.chase_committed = False
        # Stale-blacklist flush (2026-05-09): when the bot has been
        # parked in IDLE_AT_BASE for _ap.IDLE_BLACKLIST_FLUSH_S yet the
        # world has visible asteroids that all happen to be
        # blacklisted, the bot is wedged in a silent deadlock —
        # ``_do_mine_nearest`` blacklists unreachable asteroids
        # without emitting a stuck_detected, so the per-entry 60 s
        # TTL can be continuously refreshed by repeated MINE
        # attempts faster than entries evict.  Wipe both blacklists
        # so the next tick re-targets from scratch.  Long enough to
        # not interfere with normal short-cycle blacklisting; short
        # enough to recover within the user's patience window.
        idle_entered = _ap._fsm.get("entered_at")
        visible_asteroids = state.get("asteroids") or []
        if (cur == _ap.S_IDLE_AT_BASE
                and visible_asteroids
                and idle_entered is not None
                and (now - idle_entered) >= _ap.IDLE_BLACKLIST_FLUSH_S
                and (_ap._state.asteroid_blacklist
                     or _ap._state.pickup_blacklist)):
            n_ast = len(_ap._state.asteroid_blacklist)
            n_pu = len(_ap._state.pickup_blacklist)
            _ap._state.asteroid_blacklist.clear()
            _ap._state.pickup_blacklist.clear()
            _ap._telemetry_log(
                "idle_blacklist_flush",
                cleared_asteroid_entries=n_ast,
                cleared_pickup_entries=n_pu,
                visible_asteroids=len(visible_asteroids),
                idle_dwell_s=round(now - idle_entered, 1),
                **_ap._telemetry_snapshot_fields(state, p))
            # Re-query after the flush so this same tick can
            # commit to MINE instead of waiting another tick.
            nearest_ast, ast_d = _ap._nearest_asteroid(state, px, py)
            if nearest_ast is not None:
                _ap._state.chase_committed = True
                return _ap.S_MINE
    return None


def _tier_hunt(state, p, cur, now) -> str | None:
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    # 7. HUNT — no asteroid available but an alien is in _ap.HUNT_RANGE_PX.
    #    The bot needs resources (iron drops on alien kills) and
    #    sitting in SEARCH circling empty space wastes time.
    #    Triggered only when ENGAGE didn't fire (alien out of the
    #    800 px engage band) AND no asteroid is reachable.  Action
    #    handler reuses _act_engage so the close-and-fight behaviour
    #    is identical — only the dispatch differs (HUNT proactively,
    #    ENGAGE defensively).
    #
    #    Use the wider _ap.IDLE_HUNT_RANGE_PX gate when CURRENTLY in
    #    either _ap.S_IDLE_AT_BASE (bot parked at base, healed, adjacent
    #    to crafter — no reason to be picky) OR _ap.S_HUNT (already
    #    committed to a chase — finish it instead of bouncing back
    #    to idle).  The _ap.S_HUNT case is the symmetric-exit half of
    #    the hysteresis: without it, an alien sitting between
    #    _ap.HUNT_RANGE_PX (3000) and _ap.IDLE_HUNT_RANGE_PX (9000) creates
    #    a thrash band where IDLE keeps re-entering HUNT and HUNT
    #    keeps falling out — the 2026-05-04-evening telemetry
    #    captured 52 IDLE↔HUNT bounces in 5.9 minutes (one every
    #    7 s, 22/23 dwells right at the MIN_DWELL_S floor) before
    #    this fix.  Other states (MINE / SEARCH / GATHER) still
    #    use the tight 3000 px gate so they only divert to a chase
    #    when the alien is genuinely close.
    hunt_gate = (_ap.IDLE_HUNT_RANGE_PX
                 if cur in (_ap.S_IDLE_AT_BASE, _ap.S_HUNT)
                 else _ap.HUNT_RANGE_PX)
    # Use the edge-filtered selector for HUNT so we don't commit
    # to chasing an alien parked against the world boundary; that
    # was the dominant failure mode in the 2026-05-06 telemetry
    # (190 s wall-pin at px=48 with no stuck_detected firing).
    # ENGAGE / REGEN above keep using the unfiltered ``threat``
    # because defensive responses must react to any attacker
    # regardless of position.
    hunt_target, hunt_td = _ap._nearest_huntable_alien(
        state, px, py, currently_hunting=(cur == _ap.S_HUNT))
    # Building-cluster pin escape (2026-05-06 follow-up #2): if we're
    # already in _ap.S_HUNT and the bot has wandered INSIDE the home-
    # station building repulsion field, refuse to re-fire HUNT.
    # Symmetric to the wall-pin escape but against buildings instead
    # of world edges: bot drove into the cluster chasing an alien,
    # buildings are blocking forward motion, but the FSM keeps
    # picking HUNT every tick because the alien target is interior
    # (not edge-adjacent) so the wall-pin escape doesn't engage.
    # Telemetry caught a 55 s pin at px≈220, hsd≈230 inside the
    # cluster — the alien was chased through the field, the bot
    # oscillated 10–20 px per 5 s tick, and rotation defeated the
    # position-history stuck detector after the initial hit.
    # Falling through to IDLE_AT_BASE pulls the bot to the 600 px
    # outer ring (clear of all buildings) on the next tick; HUNT can
    # then re-fire from open space and engage cleanly.
    #
    # Delay (2026-05-06 follow-up #3): require HUNT to have been
    # active for >= _ap.HUNT_CLUSTER_PIN_DELAY_S before the guard fires.
    # Without this, the guard tripped on the very first re-eval tick
    # (dwell ~ MIN_DWELL_S = 1 s) which broke fresh HUNT entries
    # from cluster-interior idle parking positions: 39 fast IDLE↔HUNT
    # pairs in the follow-up telemetry.  The delay gives the bot
    # 3 s of HUNT travel to thread its way out of the perimeter
    # before the guard activates; the 55 s pin from #37 is still
    # caught well within the original symptom window.
    hunt_entered = _ap._fsm.get("entered_at")
    hunt_time = (now - hunt_entered
                 if cur == _ap.S_HUNT and hunt_entered is not None
                 else 0.0)
    # Wall exemption (2026-05-06 follow-up #5): when the bot is
    # inside the world-edge margin, the cluster guard is the WRONG
    # tool — the bot isn't stuck in the cluster centre, it's wall-
    # pinned with the cluster on the inboard side, and the cluster
    # is the *only path* to interior aliens.  Pre-fix telemetry
    # showed the guard firing every 13 s in this scenario (3 s HUNT
    # + 10 s lockout), with the user complaint "bot stays idle even
    # though enemies are present on the minimap; only moves when an
    # asteroid respawns".  Letting HUNT continue here returns the
    # geometry-driven slow-but-steady chase the user expects.
    #
    # PR #36's wall-pin escape still owns the wall+edge-aliens case
    # (it returns None when every alien is edge-adjacent, which
    # arms PR #39's lockout).  The cluster guard now owns only the
    # interior cluster pin it was originally designed for: bot
    # genuinely stuck deep in the station, far from any wall.
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    bot_at_wall = (px < _ap.ALIEN_EDGE_SKIP_PX
                   or px > world_w - _ap.ALIEN_EDGE_SKIP_PX
                   or py < _ap.ALIEN_EDGE_SKIP_PX
                   or py > world_h - _ap.ALIEN_EDGE_SKIP_PX)
    if (cur == _ap.S_HUNT and hunt_target is not None
            and hunt_time >= _ap.HUNT_CLUSTER_PIN_DELAY_S
            and not _ap._ship_clear_of_buildings(p, state)
            and not bot_at_wall):
        hunt_target = None
    # Pin-escape lockout (2026-05-06 follow-up #4): if either pin-
    # escape path zeroed hunt_target while aliens were still visible,
    # block HUNT re-entry from IDLE_AT_BASE for _ap.HUNT_PIN_GIVEUP_S so
    # the next tick doesn't immediately re-fire (currently_hunting
    # would be False from IDLE, taking the helper's fallback path).
    # Without this lockout the bot oscillated IDLE↔HUNT 107 times in
    # 3 minutes during a wall-pin (median dwell 1.01 s in both
    # states).  hunt_target is None here only when aliens are
    # visible AND we were in HUNT (no-aliens case has empty list,
    # legitimate alien-out-of-range case has non-None target with
    # hunt_td >= hunt_gate); both gates fail-closed for safety.
    if (cur == _ap.S_HUNT and hunt_target is None
            and (state.get("aliens") or [])):
        _ap._state.hunt_giveup_until = max(
            _ap._state.hunt_giveup_until, now + _ap.HUNT_PIN_GIVEUP_S)
    if (hunt_target is not None and hunt_td < hunt_gate
            and now >= _ap._state.hunt_giveup_until):
        return _ap.S_HUNT
    return None


def choose_next_state(state: dict, p: dict, cur: str) -> str:
    """Pure function: given the world snapshot and the current FSM
    state, return what state the bot *wants* to be in this tick.

    Hysteresis is encoded by branching on ``cur``: the enter
    threshold and exit threshold differ, so a value drifting around
    the boundary doesn't oscillate.

    REGEN is the **top priority** -- when shields drop below 40 %
    the bot disengages, sits still, and waits for shields to climb
    back to 60 % before doing anything else.  Combat assist still
    aims + fires automatically every frame, so the bot isn't
    defenseless while regenerating; it just doesn't burn thrust
    chasing targets while the shield bar is low.
    """
    px, py = p.get("x", 0.0), p.get("y", 0.0)

    # 0. Unconditional housekeeping -- runs every tick, before any
    #    early-return branch.  See ``_housekeeping_short_circuits``
    #    for the gate list (build_done / nebula_build_done /
    #    fortify_done / consumable-phase / module-craft-queue
    #    pops).  Extracted in PR 7 so the priority cascade below
    #    stays focused on state selection, not session-restart
    #    bookkeeping.
    _housekeeping_short_circuits(state, p)

    # 0.5 RETREAT — under-equipped defensive flee (2026-05-30).  Top
    #     of the cascade so it outranks REGEN and ENGAGE: when the
    #     bot is in ZONE2 (Nebula), shields are low, a dense swarm
    #     is on top of it, AND it has no shield_recharge in its
    #     quick-use slots, sitting in REGEN or trading blows in
    #     ENGAGE is a loss -- the captured death spiral.  Peel off to
    #     the Home Station umbrella (or away from the swarm) instead.
    #
    #     Tightly gated so it never interferes with normal combat:
    #       * ZONE2 only (MAIN swarms have the fortified HS umbrella +
    #         turret ring so the bot should defend there; warp zones
    #         already drive the bot out via S_WARP_TRAVERSE),
    #       * no ready shield consumable -- the moment one is
    #         available the bot reverts to REGEN/ENGAGE + auto-heal,
    #       * dense swarm within range (a lone kiter isn't a retreat
    #         trigger),
    #       * shield hysteresis (enter low, hold until recovered).
    #     The escape valve below mirrors REGEN's: if the bot is being
    #     actively run down with nowhere safe, RETREAT still drives
    #     toward the HS / open space rather than freezing.
    if _retreat_active(state, p, cur):
        return _ap.S_RETREAT

    # 1. REGEN — shields hurt; sit still and recover.  Compute the
    #    shared (threat, td) combat signals here -- with the boss
    #    injected -- because the ENGAGE tier (section 2) reuses them,
    #    then defer the full enter/exit + escape-valve decision to
    #    ``_regen_decision`` (returns S_REGEN to park, None to fall
    #    through).
    aliens = state.get("aliens") or []
    threat, td = _ap.nearest(aliens, px, py)
    # Treat the boss as a threat for REGEN escape-valve purposes
    # (2026-05-11 telemetry): without this the bot sat in REGEN at
    # point-blank cannon range -- ``nearest(aliens, ...)`` returned
    # None, the escape-valve threat check evaluated False, and the
    # bot idled while the boss drained 86 shields over 28 s, then
    # died.  Boss is at most one entity, so a single distance check
    # is cheaper than rebuilding the alien list with the boss
    # appended.  ENGAGE_ENTER_PX (800) matches BOSS_DETECT_RANGE so
    # the threat band lines up with the boss's own aggro distance.
    boss = state.get("boss")
    if boss is not None:
        bd = math.hypot(float(boss.get("x", 0.0)) - px,
                        float(boss.get("y", 0.0)) - py)
        if bd < _ap.ENGAGE_ENTER_PX and (threat is None or bd < td):
            threat, td = boss, bd
    regen_state = _regen_decision(state, p, cur, threat, td)
    if regen_state is not None:
        return regen_state

    # 1.1 FLEE_GAS (2026-05-18) — bot is sitting inside a damaging
    #     gas cloud.  Captured pathology: in S_ENGAGE at (3823, 3089)
    #     inside WARP_GAS, shields drained 18 -> 0 over 3 s while the
    #     bot fought an alien standing in the same cloud.  Pre-fix
    #     the only gas-escape lived inside ``_act_regen``, so any
    #     non-REGEN state (ENGAGE, MINE, GATHER, HUNT, ENGAGE_BOSS,
    #     WARP_TRAVERSE, ...) let the bot bleed out.
    #
    #     Priority below REGEN (which has its own gas-escape ramp
    #     and is the more urgent defensive interrupt when shields
    #     are collapsing) but above every productive state.  The
    #     action handler drives along the cloud-centre -> bot ray
    #     past the cloud edge by ``REGEN_GAS_ESCAPE_MARGIN_PX`` --
    #     same math ``_act_regen`` already uses.
    #
    #     No threat check: gas damage applies even when no aliens
    #     are around (WARP_GAS, parts of the Nebula), and a kiting
    #     alien in the same cloud is exactly the scenario that
    #     triggered the user report.
    #
    #     Exit hysteresis (2026-05-18 follow-up): when ``cur`` is
    #     already S_FLEE_GAS, widen the match radius by
    #     ``FLEE_GAS_EXIT_MARGIN_PX`` so the state holds until the
    #     bot is clearly past the cloud edge.  Captured pathology:
    #     17 FLEE_GAS <-> WARP_TRAVERSE flips in one session, one
    #     with 93 ms dwell.  Bot exited the cloud boundary, the
    #     downstream traverse/engage drive pulled it straight back
    #     into the same or an adjacent cloud, and shields drained
    #     ~52 px per thrash cycle.  Entry stays strict (no margin)
    #     so the bot doesn't pre-emptively detour around clouds it
    #     never reaches.
    exit_margin = (_ap.FLEE_GAS_EXIT_MARGIN_PX
                   if cur == _ap.S_FLEE_GAS else 0.0)
    if _ap._gas_cloud_at(state, px, py, exit_margin) is not None:
        return _ap.S_FLEE_GAS

    now = _ap._get_now()

    # 1.4 RECOVER_LOOT — drive back to the death pile to vacuum
    #     dropped loot.  Extracted to ``_tier_recover_loot``.
    result = _tier_recover_loot(state, p, now)
    if result is not None:
        return result

    # 1.45 POST-RECOVERY DEPOSIT/INSTALL — after S_RECOVER_LOOT vacuums
    #      up dropped modules, they sit in SHIP cargo as ``mod_<key>``
    #      items and the install queue still has the keys.  Without
    #      this priority bump, ENGAGE_BOSS at 1.5 wins and the bot
    #      fights the rest of the fight with no loadout -- telemetry
    #      from the 2026-05-11 fourth pass showed 4 modules in cargo
    #      (ship_mods=4) + mod_q=4 stuck for 50 s of S_ENGAGE_BOSS
    #      after a recovery timeout.  ``mod_<key>`` items appear in
    #      ship cargo ONLY after a death-drop pickup (normal craft
    #      flow deposits the crafted module straight into station
    #      inventory), so this signal cleanly identifies the
    #      "post-recovery, need to install" window without false
    #      positives.  Deposits the modules into station inv first,
    #      then the next tick routes to S_INSTALL.
    hs_pri145 = _ap._find_home_station(state)
    if hs_pri145 is not None:
        inv_items = (state.get("inventory") or {}).get("items") or {}
        has_mod_in_cargo = any(
            k.startswith("mod_") and v > 0
            for k, v in inv_items.items())
        if has_mod_in_cargo:
            return _ap.S_DEPOSIT
        if _ap._next_install_target(state) is not None:
            # Only fires when station inv has the queued mod_<key>
            # AND the key isn't already installed -- the
            # ``_next_install_target`` helper enforces both.
            return _ap.S_INSTALL

    # 1.5  ENGAGE_BOSS — boss alive, station-anchor kite owns the fight.
    #      Above ENGAGE so a roaming small alien at 200 px doesn't
    #      pull the bot off the station perimeter into the boss's
    #      cannon range — boss DPS dwarfs anything a small alien
    #      brings, and combat assist still aims/fires at small
    #      aliens that walk into laser range during the kite.
    #
    #      No-home-station suppression (2026-05-13 seventeenth pass):
    #      when the home station has been destroyed (boss took it
    #      out mid-fight) AND the boss is still alive, suppress
    #      engage_boss entirely.  The bot has no umbrella to
    #      retreat to, no shield-regen at base, no consumable
    #      resupply -- engaging is just stepping into the boss's
    #      cannon range to die.  The seventeenth-pass log captured
    #      this exact death loop: HS destroyed after death 2, then
    #      6 deaths in 7 seconds at world center (3200, 3200) --
    #      the no-HS respawn point -- while the bot kept engaging
    #      a boss it had no realistic chance of damaging.  With
    #      ENGAGE_BOSS suppressed the cascade falls through to
    #      ENGAGE/GATHER/MINE -- bot stays productive (or evasive)
    #      while turrets + missile array finish the boss.
    boss = state.get("boss")
    if boss is not None and hs_pri145 is not None:
        return _ap.S_ENGAGE_BOSS

    # 1.6 WARP_TO_WORMHOLE (2026-05-15).  After the bot kills the
    #     main-zone boss and finishes recovering / installing /
    #     equipping, route to the nearest wormhole and warp into
    #     one of the warp zones.  One-shot per session; latches
    #     into ``warp_after_boss_done`` once the zone transition
    #     to a WARP_* zone is observed.
    #
    #     Gates (in order):
    #       * ``boss_was_killed`` latch is True (set on
    #         ``boss_engage_end outcome=boss_killed``)
    #       * ``warp_after_boss_done`` latch is False (one-shot)
    #       * Current zone contains ``MAIN`` -- wormholes only
    #         spawn in the MAIN zone.  Bonus: this also lets us
    #         detect the post-warp zone change (zone_id no longer
    #         contains ``MAIN``) and latch ``warp_after_boss_done``.
    #       * No death recovery pending -- bot must finish loot
    #         pickup before warping out.
    #       * Module install queue empty -- every recovered or
    #         pre-crafted module is on the ship.
    #       * Quick-use slots have at least one repair_pack AND
    #         one shield_recharge -- consumables are equipped.
    zone_id = str((state.get("zone") or {}).get("id", ""))
    in_main_zone = ("MAIN" in zone_id) and ("WARP" not in zone_id)
    # Boss-killed signal: OR the in-session ``boss_was_killed``
    # latch with the game's persisted ``boss_defeated`` flag.
    # The persisted flag (exposed 2026-05-15) lets the warp behavior
    # fire on save-loaded games too -- without it the bot would
    # only warp after a fresh kill THIS session, which broke for
    # any session that started from a save where the boss had
    # already died.  Captured in the 2026-05-15 log: bot finished
    # craft + install + equip pipeline (modules_to_install=0,
    # consumable_phase_started=True) but never routed to a
    # wormhole because boss_engage_end never fired this session.
    boss_killed_signal = (
        _ap._state.boss_was_killed
        or bool(state.get("boss_defeated", False)))
    # Latch warp_done when we've transitioned out of MAIN after
    # boss kill (post-warp landing).  Also clear the pending-relatch
    # flag (set by ``_observe_warp_back_to_main`` on the prior return
    # to MAIN) -- the bot has successfully re-warped, so the
    # consumables-relaxation guard for the cascade is no longer
    # needed until the next return.
    if (boss_killed_signal
            and not _ap._state.warp_after_boss_done
            and not in_main_zone
            and zone_id):
        _ap._state.warp_after_boss_done = True
        _ap._state.warp_relatched_pending = False
        # The warp-out landed -- the bot's preparation gauntlet
        # (recraft + re-equip + heal to full) is done, so clear the
        # Nebula-death recovery latch.  Next non-MAIN death will
        # re-arm it.
        _ap._state.nebula_recovery_pending = False
        _ap._telemetry_log(
            "warp_after_boss_complete",
            zone_id=zone_id,
            **_ap._telemetry_snapshot_fields(state, p))
    # Modules-to-install gate (2026-05-17 follow-up): the queue
    # blocks the warp by default, but if the queue is non-empty AND
    # ``_next_install_target`` returns None, the modules have been
    # queued from a prior death but aren't reachable from this
    # zone's station inventory (e.g. modules dropped at a Nebula
    # death position, bot returned to MAIN via the central return
    # wormhole without dying).  In that case S_INSTALL can't drain
    # the queue either, so blocking on it strands the bot in MAIN
    # forever.  Relax the gate alongside the consumables relaxation
    # when ``warp_relatched_pending`` is True.
    modules_unreachable = (
        bool(_ap._state.queue.modules_to_install)
        and _ap._next_install_target(state) is None)
    modules_gate_ok = (
        not _ap._state.queue.modules_to_install
        or (_ap._state.warp_relatched_pending and modules_unreachable))
    if (boss_killed_signal
            and not _ap._state.warp_after_boss_done
            and in_main_zone
            and not _ap._state.death_recovery_pending
            and modules_gate_ok):
        slots = state.get("quick_use_slots") or []
        have_repair = any(
            (s.get("item_type") == "repair_pack"
             and int(s.get("count", 0)) > 0)
            for s in slots)
        have_shield = any(
            (s.get("item_type") == "shield_recharge"
             and int(s.get("count", 0)) > 0)
            for s in slots)
        # Prep-work check (2026-05-17 follow-up to PR #141): the
        # bot should re-craft / re-install / re-equip whatever is
        # missing before re-entering wormholes, instead of warping
        # under-prepared and dying.  Defer the relaxed warp gate
        # when any prep action is available; the cascade will
        # naturally pick CRAFT / INSTALL / EQUIP from sections
        # 5.5 / 5.6 instead.  Only the initial post-boss warp
        # (warp_relatched_pending == False) uses the strict
        # have_repair AND have_shield gate.
        can_craft = _ap._next_craft_target(state) is not None
        can_install = _ap._next_install_target(state) is not None
        has_consumables_unequipped = (
            not (have_repair and have_shield)
            and _ap._consumables_in_station_inv(state))
        prep_work_available = (
            can_craft or can_install or has_consumables_unequipped)
        # Initial post-boss warp requires consumables in slots.
        # Re-warp after a return-to-MAIN relatch fires only when
        # there's no more prep work the bot could be doing at the
        # station (captured 2026-05-17: bot's quick-use slots get
        # wiped on death and the one-shot consumable craft phase
        # is already exhausted; without the relaxation the strict
        # gate strands the bot in MAIN forever).
        warp_best_effort = (
            _ap._state.warp_relatched_pending
            and not prep_work_available)
        # Nebula-death recovery gate (2026-05-24): when the bot
        # died in Nebula on the prior arc, demand strict prep --
        # consumables in slots AND HP / shields at the configured
        # recovery percentages.  No best-effort relaxation: the
        # captured pathology (22 deaths in 35 min) shows the bot
        # warping back under-prepared and dying repeatedly.  By
        # blocking the warp here, the FSM cascade falls through to
        # CRAFT / EQUIP / IDLE_AT_BASE -- the bot rebuilds at the
        # home-station umbrella where shield + HP regen are both
        # active and stays put until it's fully ready.
        if _ap._state.nebula_recovery_pending:
            player = state.get("player") or {}
            hp = int(player.get("hp", 0))
            hp_max = max(1, int(player.get("max_hp", 1)))
            sh_now = int(player.get("shields", 0))
            sh_max = max(1, int(player.get("max_shields", 1)))
            hp_ready = (hp / hp_max) >= _ap.NEBULA_RECOVERY_HP_PCT
            sh_ready = (sh_now / sh_max) >= _ap.NEBULA_RECOVERY_SHIELDS_PCT
            if (have_repair and have_shield
                    and hp_ready and sh_ready):
                return _ap.S_WARP_TO_WORMHOLE
        elif (have_repair and have_shield) or warp_best_effort:
            return _ap.S_WARP_TO_WORMHOLE

    # 1.9 ZONE2 swarm tether (2026-06-02; promoted above ENGAGE
    #     2026-06-02 follow-up).  When the bot is deep in a ZONE2 swarm
    #     far from its Home Station, head home instead of fighting --
    #     the captured pathology was 2 deaths at hs_dist 4100-4573 in a
    #     57-60 alien swarm with shields crashing full->0.
    #
    #     Priority: this sits ABOVE ENGAGE.  The first cut (2026-06-02)
    #     placed the tether BELOW ENGAGE, but in a 57-alien swarm there
    #     is always an alien inside the 800 px engage band, so ENGAGE
    #     fired every tick and the tether never did -- the bot stayed
    #     pinned in combat 4000+ px from base until it died.  Promoting
    #     it above ENGAGE makes the bot commit to the return trip while
    #     it still has shields to survive the gauntlet; combat assist
    #     still fires reflexively en route, and RETREAT / REGEN (above
    #     this) still own the hurt-bot break-contact / heal cases.  Only
    #     fires far from base (> ZONE2_TETHER_DIST_PX) under a dense
    #     swarm, so close-to-base ZONE2 combat is unaffected.
    #     S_IDLE_AT_BASE's handler drives the bot back to the HS ring.
    if _zone2_far_swarm_tether(state, p, hs_pri145):
        return _ap.S_IDLE_AT_BASE

    # 1.95 EMERGENCY RESTOCK CRAFT (2026-06-09).  When the bot's heal
    #      supply is FULLY DRY (zero shield_recharge or repair_pack
    #      across station + ship + quick-use) and a crafter is ready,
    #      route to S_CRAFT *above* ENGAGE.  Captured pathology: with
    #      ~60 aliens around the Nebula HS there is always a threat in
    #      the 800 px engage band, so the normal CRAFT tier (5.5, below
    #      ENGAGE) never got a window -- the bot brawled + regen-cycled
    #      at 0 heals for ~24 min instead of spending 60 s crafting a
    #      batch.  The station umbrella defends the trip (turrets +
    #      combat assist still fire reflexively); RETREAT / REGEN /
    #      FLEE_GAS above this still own the defensive interrupts.
    #      Self-limiting: one batch landing makes supply non-zero and
    #      the tier stops firing.  ``_next_craft_target`` must agree a
    #      consumable is actually craftable (crafter idle, iron covers
    #      the per-craft cost, entry gate bypassed when dry -- see the
    #      paired emergency-bypass fix), so this can't promote module
    #      crafts or fire at an unaffordable/busy crafter.
    if (hs_pri145 is not None
            and (_ap._consumable_supply_total(state, "shield_recharge") == 0
                 or _ap._consumable_supply_total(state, "repair_pack") == 0)
            and _ap._find_basic_crafter(state, idle_only=False) is not None
            and not _ap._any_crafter_busy(state)
            and _ap._next_craft_target(state) in (
                "repair_pack", "shield_recharge")):
        return _ap.S_CRAFT

    # 2. ENGAGE — alien within band.  Preempts the rest.  ``threat, td``
    #    were loaded above for the REGEN escape valve and are reused
    #    here (no re-walk of the alien list); the no-HS-boss + outside-
    #    base-swarm suppression and the enter/exit band live in
    #    ``_engage_decision``.
    engage_state = _engage_decision(state, cur, threat, td,
                                    hs_pri145, zone_id)
    if engage_state is not None:
        return engage_state

    # 2.5 WARP_TRAVERSE (2026-05-15).  Once the bot has landed in
    #     a warp zone after the post-boss warp, drive to the far
    #     side of the map (the game enters at ``entry_side="bottom"``
    #     so the goal is the top y edge).  ``warp_traverse_done``
    #     latches True once the bot reaches the far-side margin so
    #     this branch is a one-shot per post-boss arc.
    #
    #     Priority is BELOW ENGAGE (close threats preempt -- bot
    #     fights its way past aliens rather than driving through
    #     them taking free hits) but ABOVE GATHER / MINE / HUNT
    #     (traversal beats opportunistic resource collection -- the
    #     spec is "get past the obstacles", not "stop and farm").
    #     Gas / building / boundary repulsion in steered_heading
    #     handles obstacle avoidance during the drive.
    if (boss_killed_signal
            and _ap._state.warp_after_boss_done
            and not _ap._state.warp_traverse_done
            and ("WARP" in zone_id)):
        return _ap.S_WARP_TRAVERSE

    # 3. GATHER — loot pickup within reach.
    #    Hysteresis (2026-05-30): when the bot is actively mining a
    #    reachable asteroid, only a genuinely-close pickup
    #    (GATHER_ENTER_WHILE_MINING_PX) preempts it -- the wide
    #    1500 px enter gate caused 254 mine<->gather flips in the
    #    captured session.  The tighter gate applies ONLY when there
    #    is actually an asteroid in chase range to mine; a stale
    #    S_MINE with nothing to mine still uses the wide gate so the
    #    bot doesn't ignore reachable loot.  GATHER's own exit gate is
    #    unchanged so an in-progress gather still runs to completion.
    pickup, pd = _ap._nearest_pickup(state, px, py)
    if cur == _ap.S_GATHER:
        if pickup is not None and pd < _ap.GATHER_EXIT_PX:
            return _ap.S_GATHER
    else:
        mining_real_asteroid = False
        if cur == _ap.S_MINE:
            _gather_ast, _gather_ast_d = _ap._nearest_asteroid(
                state, px, py)
            mining_real_asteroid = (
                _gather_ast is not None
                and _gather_ast_d < _ap.MAX_ASTEROID_CHASE_PX)
        gather_enter = (
            _ap.GATHER_ENTER_WHILE_MINING_PX
            if mining_real_asteroid
            else _ap.GATHER_ENTER_PX)
        if pickup is not None and pd < gather_enter:
            return _ap.S_GATHER

    # 4. BUILD family (4 / 4.5 / 4.6 / 4.7 / 4.8) — starter base,
    #     Nebula base, fortify, AI-pilot ship, advanced crafter.
    #     Extracted to ``_tier_build``.
    result = _tier_build(state, p)
    if result is not None:
        return result

    # 5. DEPOSIT — once a Home Station exists, the bot periodically
    #    returns to dump everything in the ship inventory (iron,
    #    blueprints, etc.) into the station's bigger inventory.
    #    Triggers when ship iron ≥ _ap.DEPOSIT_IRON_THRESHOLD.  The
    #    iron gate is required (no blueprint shortcut) so the bot
    #    doesn't make wasteful return trips with a single
    #    blueprint and 5 iron — blueprints accumulate alongside
    #    iron until the threshold is met, then everything ships
    #    in one round trip.  Cooldown prevents the bot from
    #    re-triggering immediately after a deposit run.
    #
    #    Mine-before-deposit override (2026-05-09): if there's an
    #    asteroid within _ap.MAX_ASTEROID_CHASE_PX AND ship iron is
    #    below _ap.DEPOSIT_IRON_FULL_THRESHOLD, suppress the deposit
    #    so the bot mines the visible cluster first.  Without this
    #    override, the loot pickup from a single alien kill drove
    #    iron above 100 and the bot zigzagged back to base while
    #    asteroids were still visible on the user's screen.  The
    #    upper FULL threshold ensures the bot eventually returns
    #    when the cargo bay is genuinely getting heavy.
    hs = _ap._find_home_station(state)
    if hs is not None:
        cooldown_ok = (
            now - _ap._state.last_deposit_at) >= _ap.DEPOSIT_COOLDOWN_S
        ship_iron = _ap._iron_total(state)
        if cooldown_ok and ship_iron >= _ap.DEPOSIT_IRON_THRESHOLD:
            # Check whether a non-blacklisted asteroid is in chase
            # range — if yes and iron isn't yet "full", prefer
            # mining over the deposit run.
            ast_for_mine, ast_for_mine_d = _ap._nearest_asteroid(
                state, px, py)
            asteroid_in_chase_range = (
                ast_for_mine is not None
                and ast_for_mine_d < _ap.MAX_ASTEROID_CHASE_PX)
            cargo_near_full = ship_iron >= _ap.DEPOSIT_IRON_FULL_THRESHOLD
            # Distance gate (2026-05-09 follow-up): non-cargo-full
            # deposit runs from far away tend to get interrupted by
            # combat before reaching the station, leaving the bot
            # stranded mid-trip.  Stay productive in the local area
            # until either home is closer (mining drifts the bot
            # back) or cargo genuinely fills.
            hs_dist = math.hypot(
                float(hs.get("x", 0.0)) - px,
                float(hs.get("y", 0.0)) - py)
            too_far_for_deposit = (
                hs_dist > _ap.DEPOSIT_HS_MAX_DIST_PX
                and not cargo_near_full)
            if ((not asteroid_in_chase_range or cargo_near_full)
                    and not too_far_for_deposit):
                return _ap.S_DEPOSIT

    # 5.5 / 5.6 CRAFT / INSTALL + boss-prep pipeline (equip /
    #     pre-boss mine / fortify / QWI).  Extracted to
    #     ``_tier_craft_install_bossprep`` (takes the section-5 ``hs``).
    result = _tier_craft_install_bossprep(state, p, hs)
    if result is not None:
        return result

    # 6. MINE vs SEARCH — discrete chase / commit / give-up +
    #     stale-blacklist flush.  Extracted to ``_tier_mine_or_search``.
    result = _tier_mine_or_search(state, p, cur, now)
    if result is not None:
        return result

    # 7. HUNT — proactive alien chase with cluster/wall pin guards.
    #     Extracted to ``_tier_hunt``.
    result = _tier_hunt(state, p, cur, now)
    if result is not None:
        return result

    # 8. IDLE_AT_BASE — nothing actionable is visible.  When a Home
    #    Station exists, head there and wait for respawns rather
    #    than spiralling forever in empty space (observed:
    #    2026-05-03 session, 47 s of SEARCH with 0 aliens visible
    #    + 1 distant blacklisted asteroid, bot oscillated between
    #    two positions).  When no Home Station exists yet
    #    (early-game), fall back to the original SEARCH spiral —
    #    the bot still needs to roam to find resources for the
    #    starter base.
    if hs is not None:
        return _ap.S_IDLE_AT_BASE
    return _ap.S_SEARCH


