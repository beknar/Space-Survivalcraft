"""Lifecycle edge observers split from ``bot_autopilot``.

Each helper detects a player-life or boss-engage edge, emits the
matching telemetry event, and flips the relevant ``BotState`` latch.
The orchestrator (``bot_autopilot._do_auto``) calls them once per
tick; they're orthogonal to the FSM dispatch itself.

The same pattern as the other ``bot_autopilot_*`` helpers: import
``bot_autopilot`` as ``_ap`` and read shared state (``_state``,
``_fsm``, constants, telemetry helpers) through that alias so
test-time monkey-patches on the orchestrator module still thread
through.
"""
from __future__ import annotations

import bot_autopilot as _ap


def _observe_death_edges(state: dict, p: dict, now: float) -> None:
    """Track alive->dead and dead->alive transitions to drive the
    post-death loot-recovery action + boss telemetry.

    While alive:
      * Refresh ``last_alive_pos`` / ``last_alive_modules`` /
        ``last_alive_consumable_types`` every tick so the snapshot
        AT THE MOMENT OF DEATH captures the loadout that's about to
        be dropped (``combat_helpers._drop_player_loadout`` wipes
        the module + quick-use slots immediately).

    On alive -> dead edge:
      * Emit ``player_death`` telemetry with the FSM state, dropped
        loadout size, and -- if the death happened during boss
        combat -- a ``boss_context`` snapshot.

    On dead -> alive edge:
      * If the bot had anything worth recovering (modules OR
        consumables), set ``death_recovery_pending=True`` with the
        death position + lost-module list captured at the alive
        edge so the FSM cascade picks S_RECOVER_LOOT until the
        loot is collected.
      * Refill ``queue.modules_to_install`` with the lost modules
        so the existing install pipeline re-installs them after
        the bot deposits the recovered loot.
      * Reset ``consumables_equipped`` so the existing
        S_EQUIP_CONSUMABLES action re-binds quick-use slots once
        the recovered consumables land in station inventory.
    """
    is_dead_now = bool((state.get("player") or {}).get("is_dead",
                                                       False))
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))

    if not is_dead_now:
        # Snapshot live loadout each tick so the alive->dead edge
        # captures the loadout that's about to drop.
        _ap._state.last_alive_pos = (px, py)
        _ap._state.last_alive_modules = [
            m for m in (state.get("module_slots") or [])
            if m is not None]
        _ap._state.last_alive_consumable_types = [
            s.get("item_type") for s in (state.get("quick_use_slots") or [])
            if s and s.get("item_type")
            and s.get("item_type") != "missile"]
        # dead -> alive edge: finalize recovery setup if there was
        # anything to recover (snapshotted at the alive->dead edge
        # in ``death_recovery_modules`` / ``_consumables``).
        if _ap._state.was_dead:
            _ap._state.was_dead = False
            had_modules = bool(_ap._state.death_recovery_modules)
            had_consumables = bool(_ap._state.death_recovery_consumables)
            if had_modules or had_consumables:
                _ap._state.death_recovery_pending = True
                _ap._state.death_recovery_started_at = now
                # Refill the install queue with what was lost so
                # the existing INSTALL pipeline picks them up after
                # the bot deposits the recovered modules.
                for mod in _ap._state.death_recovery_modules:
                    if mod not in _ap._state.queue.modules_to_install:
                        _ap._state.queue.modules_to_install.append(mod)
                # Reset the consumables latch so the existing
                # EQUIP pipeline re-binds quick-use slots once the
                # recovered consumables reach station inventory.
                if had_consumables:
                    _ap._state.consumables_equipped = False
                _ap._telemetry_log(
                    "death_recovery_armed",
                    death_pos=[round(_ap._state.death_recovery_pos[0], 1),
                               round(_ap._state.death_recovery_pos[1], 1)],
                    lost_modules=list(_ap._state.death_recovery_modules),
                    lost_consumables=list(
                        _ap._state.death_recovery_consumables),
                )
        return

    # is_dead_now == True
    if not _ap._state.was_dead:
        # alive -> dead edge.  Freeze the alive-tick snapshots into
        # the death-recovery fields so the dead->alive edge can read
        # them even after this same tick's wipe of module_slots /
        # quick_use_slots clears the live values.
        _ap._state.was_dead = True
        _ap._state.death_recovery_pos = _ap._state.last_alive_pos
        _ap._state.death_recovery_modules = list(
            _ap._state.last_alive_modules)
        _ap._state.death_recovery_consumables = list(
            _ap._state.last_alive_consumable_types)
        # Nebula-death recovery latch (2026-05-24).  Captured
        # pathology: 22 deaths in 35 min, 20 in ZONE2 or the warp
        # zones en-route; the bot looped warp -> die -> warp without
        # rebuilding its consumable buffer.  Latch True when the
        # death happens in the Nebula (ZONE2) so the next warp gate
        # forces consumable rebuild + full HP/shields before allowing
        # re-entry.  Cleared by the existing
        # ``warp_after_boss_complete`` gate once the warp-out lands.
        zone_id_at_death = str((state.get("zone") or {}).get("id", ""))
        if "ZONE2" in zone_id_at_death:
            _ap._state.nebula_recovery_pending = True
        boss = state.get("boss")
        boss_ctx = None
        if boss is not None:
            boss_ctx = {
                "boss_hp": int(boss.get("hp", 0)),
                "boss_max_hp": int(boss.get("max_hp", 0)),
                "boss_phase": int(boss.get("phase", 1)),
            }
        _ap._telemetry_log(
            "player_death",
            fsm_state=_ap._fsm["state"],
            death_pos=[round(_ap._state.death_recovery_pos[0], 1),
                       round(_ap._state.death_recovery_pos[1], 1)],
            lost_modules=list(_ap._state.death_recovery_modules),
            lost_consumables=list(_ap._state.death_recovery_consumables),
            boss_context=boss_ctx,
            zone_id=zone_id_at_death,
            nebula_recovery_armed=bool(
                _ap._state.nebula_recovery_pending),
        )


def _maybe_log_boss_engage_edges(state: dict, p: dict, now: float,
                                 prev: str, cur: str) -> None:
    """Emit ``boss_engage_start`` / ``boss_engage_end`` telemetry on
    the matching FSM transitions so post-hoc log analysis can
    measure how long each boss fight took, HP / shield deltas, and
    the outcome (boss killed / player died / disengaged).

    Pulled out into its own helper so the dispatch-loop call sites
    stay one-line.
    """
    if cur == _ap.S_ENGAGE_BOSS and prev != _ap.S_ENGAGE_BOSS:
        player = state.get("player") or {}
        boss = state.get("boss") or {}
        _ap._state.boss_engage_started_at = now
        _ap._state.boss_engage_start_hp = int(player.get("hp", 0))
        _ap._state.boss_engage_start_shields = int(player.get("shields", 0))
        _ap._state.boss_engage_start_boss_hp = int(boss.get("hp", 0))
        _ap._telemetry_log(
            "boss_engage_start",
            from_state=prev,
            player_hp=_ap._state.boss_engage_start_hp,
            player_max_hp=int(player.get("max_hp", 0)),
            player_shields_at_start=_ap._state.boss_engage_start_shields,
            boss_hp=_ap._state.boss_engage_start_boss_hp,
            boss_max_hp=int(boss.get("max_hp", 0)),
            boss_phase=int(boss.get("phase", 1)),
            **_ap._telemetry_snapshot_fields(state, p))
    elif prev == _ap.S_ENGAGE_BOSS and cur != _ap.S_ENGAGE_BOSS:
        player = state.get("player") or {}
        boss = state.get("boss") or {}
        # Outcome inference:
        #   * boss_killed -- ``state.boss`` is now empty / hp <= 0
        #   * player_died -- ``player.is_dead`` flipped True
        #   * disengaged  -- neither; FSM cascade preempted (REGEN /
        #                    something higher priority)
        boss_alive = (state.get("boss") is not None
                      and int(boss.get("hp", 0)) > 0)
        if not boss_alive:
            outcome = "boss_killed"
        elif bool(player.get("is_dead", False)):
            outcome = "player_died"
        else:
            outcome = "disengaged"
        # Latch ``boss_was_killed`` for the post-boss warp-out
        # behaviour: once the main-zone boss has died this session,
        # the FSM will route the bot to the nearest wormhole as
        # soon as recovery + install + consumable equip have all
        # finished.  Sticky for the session -- only cleared by
        # ``warp_after_boss_done`` after the warp transit lands.
        if outcome == "boss_killed":
            _ap._state.boss_was_killed = True
        dwell = now - _ap._state.boss_engage_started_at
        _ap._telemetry_log(
            "boss_engage_end",
            to_state=cur,
            outcome=outcome,
            dwell_s=round(dwell, 2),
            player_hp_delta=int(player.get("hp", 0))
                            - _ap._state.boss_engage_start_hp,
            player_shields_delta=int(player.get("shields", 0))
                                 - _ap._state.boss_engage_start_shields,
            boss_hp_delta=int(boss.get("hp", 0))
                          - _ap._state.boss_engage_start_boss_hp,
            **_ap._telemetry_snapshot_fields(state, p))


def _maybe_clear_death_recovery(state: dict, p: dict, now: float) -> None:
    """Clear the recovery pending flag when the loot at the death
    site is no longer there (collected, or despawned via
    WORLD_ITEM_LIFETIME), OR when ``DEATH_RECOVERY_TIMEOUT_S`` has
    elapsed since the recovery was armed.  Called by the FSM
    cascade so the bot doesn't sit in S_RECOVER_LOOT forever.
    """
    if not _ap._state.death_recovery_pending:
        return
    # Bumped timeout for non-MAIN zones (2026-05-26).  In Nebula
    # / warp zones the bot may need to idle at the HS umbrella
    # for tens of seconds to heal + re-equip consumables before
    # the recovery-loadout gate releases, so the standard 60 s
    # window isn't enough.  Item lifetime is 600 s so 180 s is
    # comfortable headroom.
    zone_id_recovery = str((state.get("zone") or {}).get("id", ""))
    # Only treat the recovery as "in danger zone" when zone_id
    # explicitly identifies one.  Empty / unknown zone_id defaults
    # to MAIN's 60 s timeout so test stubs that don't set the
    # field retain the pre-2026-05-26 behaviour.
    in_danger_zone_recovery = (
        "ZONE2" in zone_id_recovery
        or "WARP" in zone_id_recovery
        or "STAR_MAZE" in zone_id_recovery)
    timeout_s = (
        _ap.DEATH_RECOVERY_TIMEOUT_NEBULA_S
        if in_danger_zone_recovery
        else _ap.DEATH_RECOVERY_TIMEOUT_S)
    if now - _ap._state.death_recovery_started_at >= timeout_s:
        _ap._telemetry_log(
            "death_recovery_timeout",
            elapsed_s=round(now - _ap._state.death_recovery_started_at, 1),
            timeout_s=timeout_s,
            **_ap._telemetry_snapshot_fields(state, p))
        _ap._state.death_recovery_pending = False
        return
    # Check whether any pickup is still within range of the death
    # position.  If none remain (everything collected / despawned),
    # we're done.
    drx, dry = _ap._state.death_recovery_pos
    radius_sq = 600.0 * 600.0   # generous match radius
    for plist_key in ("iron_pickups", "blueprint_pickups"):
        for pu in (state.get(plist_key) or []):
            dx = float(pu.get("x", 0.0)) - drx
            dy = float(pu.get("y", 0.0)) - dry
            if dx * dx + dy * dy <= radius_sq:
                return  # loot still on the floor near the death site
    # No loot remains -- clear the latch and let the FSM fall
    # through to its normal cascade (which will then deposit any
    # recovered items and route through the INSTALL pipeline).
    _ap._telemetry_log(
        "death_recovery_complete",
        elapsed_s=round(now - _ap._state.death_recovery_started_at, 1),
        **_ap._telemetry_snapshot_fields(state, p))
    _ap._state.death_recovery_pending = False


def _observe_warp_back_to_main(state: dict, p: dict, now: float) -> None:
    """Re-arm the post-boss warp cascade when the bot ends up back in
    MAIN after having already warped out.

    Captured pathology (2026-05-16 bot_io log): after a successful
    post-boss warp to WARP_GAS -> traverse -> Nebula, the bot
    wandered around Nebula and walked into the central return
    wormhole (``zones/zone2.py`` plants one at the zone centre that
    routes back to MAIN).  The session-sticky
    ``warp_after_boss_done`` latch (set on the first non-MAIN tick
    in ``choose_next_state``) meant the FSM never re-fired the
    warp-to-wormhole cascade -- the bot just farmed Zone 1
    indefinitely.

    Fix: whenever the bot is observed in MAIN with the latch still
    True, that's a logical contradiction (the latch was set *because*
    the bot left MAIN) -- clear it, and the symmetrical
    ``warp_traverse_done`` latch too, so the next tick's choose
    cascade routes back through a corner wormhole and on into Nebula.

    Gates remain unchanged (modules_to_install empty, consumables
    equipped, no death recovery), so a bot still mid-install or
    without health packs won't immediately bounce out.
    """
    if not _ap._state.warp_after_boss_done:
        return
    zone_id = str((state.get("zone") or {}).get("id", ""))
    in_main = ("MAIN" in zone_id) and ("WARP" not in zone_id)
    if not in_main:
        return
    _ap._state.warp_after_boss_done = False
    _ap._state.warp_traverse_done = False
    # Mark the pending-relatch flag so the S_WARP_TO_WORMHOLE
    # cascade fires even when consumables aren't in slots (the
    # post-death case captured 2026-05-17: bot has installed
    # recovered modules but quick-use slots are wiped and the
    # one-shot consumable craft phase has already been used).
    # The flag clears when the cascade detects the bot has left
    # MAIN again.
    _ap._state.warp_relatched_pending = True

    # Re-craft / re-install prep before the next warp (2026-05-17
    # follow-up to PRs #138 / #139 / #141).  PRs #138/#139 added
    # a best-effort warp that bypasses the consumables + modules
    # gates when the bot is stranded in MAIN after a return.
    # That kept the bot from being permanently stuck, but the
    # bot then warped UNDER-PREPARED -- captured logs showed it
    # dying repeatedly in successive warp zones because the one-
    # shot craft queues are exhausted by the first arc.
    #
    # Top up the consumable craft queue when station inventory
    # is depleted, and re-queue any unreachable modules
    # (dropped at a Nebula death position the bot can't reach)
    # for re-crafting from blueprints.  The refined warp gate in
    # ``bot_autopilot_choose.py`` defers the relaxed warp when
    # any of CRAFT / INSTALL / EQUIP can fire -- so the bot
    # finishes its prep before re-entering the wormholes.
    queue = _ap._state.queue
    has_consumables_in_station = _ap._consumables_in_station_inv(state)
    if (not has_consumables_in_station
            and queue.repair_packs_remaining == 0
            and queue.shield_recharges_remaining == 0):
        queue.repair_packs_remaining = _ap.WARP_RECRAFT_REPAIR_BATCHES
        queue.shield_recharges_remaining = (
            _ap.WARP_RECRAFT_SHIELD_BATCHES)
    # Nebula-death recovery (2026-05-24).  When the bot died in
    # Nebula on the prior arc, force a full fresh batch of repair
    # packs + shield recharges even if station inventory still has
    # some -- the death loop captured in the 2026-05-24 telemetry
    # (22 deaths / 35 min) shows the existing "station empty only"
    # trigger is too conservative.  Setting the queue counts only
    # tops up if the craft phase is unscheduled; if the queue
    # already holds remaining batches we don't duplicate them.
    if _ap._state.nebula_recovery_pending:
        if queue.repair_packs_remaining < _ap.NEBULA_RECOVERY_REPAIR_BATCHES:
            queue.repair_packs_remaining = (
                _ap.NEBULA_RECOVERY_REPAIR_BATCHES)
        if queue.shield_recharges_remaining < _ap.NEBULA_RECOVERY_SHIELD_BATCHES:
            queue.shield_recharges_remaining = (
                _ap.NEBULA_RECOVERY_SHIELD_BATCHES)
        # Re-arm the consumable craft phase so the FSM cascade
        # picks S_CRAFT again -- ``consumable_phase_started`` is
        # sticky from the initial craft, but the recovery flow
        # needs the gate to re-evaluate against the fresh queue.
        queue.consumable_phase_started = False
        # Force a re-equip after the recovery crafts land.
        _ap._state.consumables_equipped = False
    # Re-queue unreachable modules for re-craft.  When the bot
    # died in Nebula and walked back to MAIN via the central
    # wormhole, its lost modules are at the Nebula death
    # position and unreachable from MAIN's station inv.
    # ``_next_install_target`` returns None despite a non-empty
    # install queue.  Add those modules back to ``modules_to_craft``
    # so the craft cascade re-makes them from blueprints (assuming
    # blueprints + iron are in station).
    if (queue.modules_to_install
            and _ap._next_install_target(state) is None):
        for key in queue.modules_to_install:
            if key not in queue.modules_to_craft:
                queue.modules_to_craft.append(key)
        # Reset the module-phase latch so the craft cascade's
        # entry gate (2000-iron threshold) re-evaluates instead
        # of trusting the stale started-flag.
        queue.module_phase_started = False

    _ap._telemetry_log(
        "warp_after_boss_relatch_for_return",
        zone_id=zone_id,
        **_ap._telemetry_snapshot_fields(state, p))


def _observe_warp_traverse_arc_complete(state: dict, p: dict,
                                        now: float) -> None:
    """Emit ``warp_traverse_arc_completed`` when the FSM exits the
    warp_traverse state without the action handler having already
    fired the arrival-band completion.

    Captured pathology (2026-05-17 bot_io): bot successfully
    crossed WARP_GAS to y=6352 (inside the arrival band), but the
    game's auto-zone-transition fired BEFORE ``_act_warp_traverse``
    got another tick to detect the arrival.  The FSM transitioned
    ``warp_traverse -> search`` because zone_id flipped from
    WARP_GAS to ZONE2, and neither ``warp_traverse_complete`` nor
    ``warp_traverse_arc_completed`` ever fired.  Post-hoc analysis
    of arc duration in the gas zone was impossible.

    Hook: each tick, if an arc is in progress
    (``arc_started_at != 0.0``) and the FSM is no longer in
    S_WARP_TRAVERSE, emit ``arc_completed`` with an outcome
    derived from how close ``max_y`` reached the top edge.
    The action handler resets ``arc_started_at`` to ``0.0`` after
    its own arrival-band emit, so this observer doesn't
    double-fire that path.

    Outcome heuristic:
      * ``crossed`` -- max_y reached >=85% of typical warp-zone
        height (5440 px of 6400).  Means the bot exited via the
        top edge.
      * ``interrupted`` -- otherwise; FSM was preempted (ENGAGE,
        REGEN, death, etc.) before the bot reached the top.
    """
    if _ap._state.warp_traverse_arc_started_at == 0.0:
        return
    if _ap._fsm["state"] == _ap.S_WARP_TRAVERSE:
        return
    zone_id = str((state.get("zone") or {}).get("id", ""))
    # The FSM leaving warp_traverse for regen / engage / death-
    # recovery while the bot is STILL in a warp zone is a pause,
    # not a completed arc.  Captured 2026-05-17 (post-PR-#137):
    # the observer was firing arc_completed on every traverse ->
    # regen oscillation, resetting ``arc_started_at`` to 0.0, and
    # the next regen -> traverse re-entry tripped the action
    # handler's first-ever-arc detection (``arc_started_at == 0.0
    # AND py < world_h/2``), which then ALSO reset every
    # per-arc tracker (max_y, progress_at, detour_count,
    # detour_side, detour_commit_y).  PR #134's persistent detour
    # side was effectively disabled: a single 25-s no-progress
    # detour fire was wiped out by the next regen interlude,
    # leaving the bot oscillating forever.
    #
    # Gating on ``"WARP" not in zone_id`` keeps the observer firing
    # only on actual zone transitions (auto-zone-transition past
    # the arrival band, death-respawn to MAIN, accidental walk
    # back through the Nebula central wormhole).  Regen interludes
    # within the same warp zone leave the trackers intact so the
    # detour can accumulate enough no-progress time to fire.
    if "WARP" in zone_id:
        return
    arc_duration_s = now - _ap._state.warp_traverse_arc_started_at
    crossed = (_ap._state.warp_traverse_max_y
               >= _ap.WARP_TRAVERSE_CROSSED_MAX_Y_PX)
    _ap._telemetry_log(
        "warp_traverse_arc_completed",
        zone_id=zone_id,
        outcome="crossed" if crossed else "interrupted",
        arc_duration_s=round(arc_duration_s, 1),
        max_y=round(_ap._state.warp_traverse_max_y, 1),
        detour_count=_ap._state.warp_traverse_detour_count,
        fsm_state=_ap._fsm["state"],
        **_ap._telemetry_snapshot_fields(state, p))
    # Consume the arc so the next entry to warp_traverse starts a
    # fresh arc with a new arc_started event.
    _ap._state.warp_traverse_arc_started_at = 0.0


def _observe_gas_lingering(state: dict, p: dict, now: float) -> None:
    """Detect when the bot has been stuck inside a gas cloud
    taking damage for too long, and emit one ``gas_lingering``
    event per linger episode.

    Pure observability hook -- doesn't drive any behaviour.  Lets
    the operator see "bot bled out in a gas cloud" directly in
    the telemetry log instead of cross-referencing
    state_transition timestamps and shield deltas by hand.

    Fires when:
      * Bot has been continuously inside a gas cloud for
        >= ``GAS_LINGER_DETECT_S`` seconds (3.0 s)
      * AND has lost >= ``GAS_LINGER_DAMAGE_PX`` shields + hp
        combined since the entry edge (20 px)

    Throttled: one event per linger episode (``gas_linger_event_fired``
    latch).  On exit from the cloud, the entry trackers reset so
    the next entry starts fresh.

    The ``fsm_state`` field on the event is the key diagnostic:

      * ``flee_gas`` -- FLEE_GAS is running but the bot is still
        bleeding out (e.g. exit hysteresis stall, geometry pinned
        against world edge)
      * anything else -- FSM didn't preempt to FLEE_GAS, which is
        the original pathology PR #147 addressed

    Either case is actionable.
    """
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    cloud = _ap._gas_cloud_at(state, px, py)

    if cloud is None:
        # Outside any cloud -- reset trackers so the next entry
        # starts a fresh episode.
        if _ap._state.gas_linger_entered_at != 0.0:
            _ap._state.gas_linger_entered_at = 0.0
            _ap._state.gas_linger_entry_shields = 0
            _ap._state.gas_linger_entry_hp = 0
            _ap._state.gas_linger_event_fired = False
        return

    sh = int(p.get("shields", 0))
    hp = int(p.get("hp", 0))

    if _ap._state.gas_linger_entered_at == 0.0:
        # Cloud-entry edge -- snapshot the moment of entry so the
        # damage delta is anchored at the right baseline.  Pop a
        # fresh latch so the per-episode throttle works.
        _ap._state.gas_linger_entered_at = now
        _ap._state.gas_linger_entry_shields = sh
        _ap._state.gas_linger_entry_hp = hp
        _ap._state.gas_linger_event_fired = False
        # Edge-entry telemetry (2026-05-27): one event per cloud
        # crossing so the operator can see *if* the bot enters a
        # cloud at all -- the existing gas_lingering signal only
        # fires after GAS_LINGER_DETECT_S of dwell.  Useful to
        # validate the gas-cloud routing tuning across cycles.
        cx, cy, radius = cloud
        _ap._telemetry_log(
            "gas_cloud_entered",
            cloud_x=round(cx, 1),
            cloud_y=round(cy, 1),
            cloud_radius=round(radius, 1),
            fsm_state=_ap._fsm["state"],
            entry_shields=sh,
            entry_hp=hp,
            **_ap._telemetry_snapshot_fields(state, p))
        return

    if _ap._state.gas_linger_event_fired:
        # Already fired for this episode -- one event per cloud
        # stay.  Bot has to exit + re-enter to fire again.
        return

    dwell_s = now - _ap._state.gas_linger_entered_at
    if dwell_s < _ap.GAS_LINGER_DETECT_S:
        return

    shield_loss = _ap._state.gas_linger_entry_shields - sh
    hp_loss = _ap._state.gas_linger_entry_hp - hp
    total_loss = max(0, shield_loss) + max(0, hp_loss)
    if total_loss < _ap.GAS_LINGER_DAMAGE_PX:
        # Inside cloud long enough to count, but no damage taken
        # (gas areas in some zones are slow, or the bot is being
        # actively healed by consumables / station umbrella).
        # Don't fire -- not a pathology.
        return

    cx, cy, radius = cloud
    _ap._state.gas_linger_event_fired = True
    _ap._telemetry_log(
        "gas_lingering",
        dwell_s=round(dwell_s, 2),
        shield_loss=int(shield_loss),
        hp_loss=int(hp_loss),
        entry_shields=int(_ap._state.gas_linger_entry_shields),
        entry_hp=int(_ap._state.gas_linger_entry_hp),
        cloud_x=round(cx, 1),
        cloud_y=round(cy, 1),
        cloud_radius=round(radius, 1),
        fsm_state=_ap._fsm["state"],
        **_ap._telemetry_snapshot_fields(state, p))
