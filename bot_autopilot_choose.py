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

    # 0. Unconditional housekeeping — runs every tick, before any
    #    early-return branch.  If the bot just connected to a
    #    world that already has a Home Station (loaded save,
    #    prior session, manual placement), permanently mark
    #    build_done so the BUILD/BUILD_SEEK branch never fires.
    #    Has to live up here, NOT inside the BUILD branch below,
    #    because GATHER/ENGAGE/REGEN early-return long before the
    #    BUILD branch is reached — so if the bot enters GATHER
    #    on its very first tick (likely when a pickup is
    #    visible), build_done would stay False forever and the
    #    BUILD branch would fire as soon as GATHER cleared.
    if (not _ap._state.build_done
            and _ap._find_home_station(state) is not None):
        _ap._state.build_done = True
        _ap._telemetry_log("build_done_short_circuit",
                       reason="home_station_already_exists",
                       **_ap._telemetry_snapshot_fields(state, p))
    # Mirror short-circuit for fortify: if the world already has at
    # least _ap.QWI_STAGE_MIN_TURRETS defenders (loaded save / prior
    # session / manual placement), latch ``fortify_done`` so the
    # FSM doesn't re-enter _ap.S_FORTIFY for a ring that already exists.
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
    # Mirror short-circuit for the consumable craft phase.  The QWI
    # pipeline gate (section 5.6) requires ``_ap._consumable_phase_finished()``,
    # which only returns True after the bot crafts all
    # _ap.REPAIR_PACK_CRAFT_BATCHES + _ap.SHIELD_RECHARGE_CRAFT_BATCHES
    # batches itself — flips the queue's ``consumable_phase_started``
    # flag along the way.  A loaded save (or pre-existing inventory)
    # with the 25 + 25 consumables already present skips the craft
    # phase entirely, leaving ``consumable_phase_started=False``
    # forever, so the QWI build pipeline never fires even though
    # everything else is ready.  User report 2026-05-09: "there is
    # over 2000 iron and there are multiple copies of all the
    # modules and 25 of each consumable, so why has the bot not
    # built a QWI?".  Sum across station / ship / quick-use slots
    # so the latch fires regardless of where the consumables sit.
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

    # Mirror short-circuit for the MODULE craft queue.  Catches the
    # session-restart case (user complaint 2026-05-10: "the bot
    # should only build the modules once, and it has built them
    # multiple times"): a fresh process on an existing save has
    # CraftQueue.modules_to_craft reset to the full MODULE_CRAFT_QUEUE
    # even though some / all modules are already crafted (in
    # station inv as mod_<key>) or installed on the ship.  Pop the
    # already-done heads up front so the bot doesn't try to re-craft
    # them.  _next_craft_target also skip-pops at call time, but
    # latching the started flag here saves the bot from a useless
    # craft-phase round trip when EVERY module is already done.
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
            # If the queue is now empty, also latch
            # module_phase_started so a stale gate check doesn't
            # mis-fire next tick.
            if not _ap._state.queue.modules_to_craft:
                _ap._state.queue.module_phase_started = True
            _ap._telemetry_log(
                "module_craft_phase_short_circuit",
                popped=popped,
                queue_remaining=list(
                    _ap._state.queue.modules_to_craft),
                **_ap._telemetry_snapshot_fields(state, p))

    # 1. REGEN — shields hurt; sit still and recover.  Preempts
    #    ENGAGE/GATHER/MINE so the bot actually idles instead of
    #    burning thrust while shields are low.
    #
    #    REGEN escape valve (added 2026-05-04): the original "always
    #    return REGEN while shields < _ap.REGEN_EXIT_PCT" rule deadlocks
    #    when the bot starts already low on shields with nearby
    #    aliens still firing — the bot sits idle, takes damage, can
    #    never reach the exit threshold, and dies.  Telemetry caught
    #    this clearly: 78 s session, 23 stuck_detected events all in
    #    REGEN with shields=0, 0 iron collected.
    #    Fix: if a threat is within _ap.ENGAGE_ENTER_PX AND shields are
    #    NOT recovering between ticks, fall through and let ENGAGE
    #    (or other priorities) take over — better to fight back at
    #    low HP than die idling.
    sh = int(p.get("shields", 0))
    sh_max = max(1, int(p.get("max_shields", 1)))
    pct = sh / sh_max
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
    # Boss-alive thresholds (2026-05-13 fourteenth telemetry pass):
    # when a boss is alive, regen further before re-engaging.  Death-
    # loop captured in the log was: post-recovery install → engage_boss
    # fired at shields=54/120 (45 %), one lure trigger later (35 %),
    # then died.  Escape valve still applies, so boss-in-range still
    # gets engaged regardless of threshold.
    if boss is not None:
        regen_enter = _ap.REGEN_ENTER_PCT_BOSS_ALIVE
        regen_exit = _ap.REGEN_EXIT_PCT_BOSS_ALIVE
    else:
        regen_enter = _ap.REGEN_ENTER_PCT
        regen_exit = _ap.REGEN_EXIT_PCT
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
            shields_stalled = (no_progress_s
                               >= _ap.REGEN_NO_PROGRESS_TIMEOUT_S)
            threatened = (threat is not None
                          and td < _ap.ENGAGE_ENTER_PX)
            if threatened and shields_stalled:
                # Escape valve — sustained no-progress while
                # threatened means we're truly deadlocked.  Let
                # priority cascade pick ENGAGE (or whatever fits).
                # Don't update trackers so a future REGEN re-entry
                # starts fresh.
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
            else:
                # Entering REGEN — initialize the trend baseline
                # AND the no-progress timer.
                _ap._state.last_regen_shields = sh
                _ap._state.last_regen_progress_at = _ap._get_now()
                return _ap.S_REGEN

    now = _ap._get_now()

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
        return _ap.S_RECOVER_LOOT

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
    boss = state.get("boss")
    if boss is not None:
        return _ap.S_ENGAGE_BOSS

    # 2. ENGAGE — alien within band.  Preempts the rest.
    # ``threat, td`` already loaded above for the REGEN escape
    # valve so we don't re-walk the alien list here.
    if cur == _ap.S_ENGAGE:
        if threat is not None and td < _ap.ENGAGE_EXIT_PX:
            return _ap.S_ENGAGE
    else:
        if threat is not None and td < _ap.ENGAGE_ENTER_PX:
            return _ap.S_ENGAGE

    # 3. GATHER — loot pickup within reach.
    pickup, pd = _ap._nearest_pickup(state, px, py)
    if cur == _ap.S_GATHER:
        if pickup is not None and pd < _ap.GATHER_EXIT_PX:
            return _ap.S_GATHER
    else:
        if pickup is not None and pd < _ap.GATHER_ENTER_PX:
            return _ap.S_GATHER

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
    if hs is not None and _ap._consumable_phase_finished():
        # EQUIP gate (2026-05-11 fifth pass): self-heal by checking
        # the actual quick-use slot state, not just the
        # ``consumables_equipped`` latch.  The latch alone misses
        # the post-death case the user reported: bot picks up the
        # dropped consumables and deposits them, but the latch was
        # set True at session start and never re-armed because the
        # dead->alive edge only resets it when the bot's prior
        # loadout snapshot included consumables (which on deaths
        # 2-4 of a multi-death cycle, it doesn't).  Checking the
        # actual quick-use slot contents makes the gate fire
        # whenever the slot needs a consumable AND station has one
        # to give -- so a fresh session, a post-death pickup, or
        # any other quick-use-empty state all route through EQUIP.
        # The latch is still useful as the one-tick MIN_DWELL-skip
        # helper inside ``_act_at_station``.
        quick_use = state.get("quick_use_slots") or []
        has_consumable_equipped = any(
            s and s.get("item_type") in ("repair_pack", "shield_recharge")
            and int(s.get("count", 0)) > 0
            for s in quick_use)
        # 2026-05-12 eleventh-pass extension: also fire EQUIP when
        # the consumables sit in the SHIP inventory (not station).
        # Death-drop recovery puts them in ship cargo, the deposit
        # code skips them by design (SHIP_ONLY_ITEM_TYPES), so the
        # station-only predicate never saw them and the bot fought
        # the rest of the boss fight without any heal cooldowns.
        has_consumables_available = (
            _ap._consumables_in_station_inv(state)
            or _ap._consumables_in_ship_inv(state))
        if (not has_consumable_equipped
                and has_consumables_available):
            # Reset the latch so ``_act_equip_consumables`` actually
            # POSTs.  The action's skip-condition is the latch
            # itself; a stale-True latch from a previous session
            # would otherwise make the action ``_do_idle`` forever.
            _ap._state.consumables_equipped = False
            return _ap.S_EQUIP_CONSUMABLES
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
        if in_chase_range:
            # Reached (or approached) a chase-range asteroid —
            # clear any prior commitment so future SEARCH /
            # IDLE_AT_BASE episodes get the normal cap-protected
            # behaviour.
            _ap._state.chase_committed = False
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


