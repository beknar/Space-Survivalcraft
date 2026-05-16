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
    if now - _ap._state.death_recovery_started_at >= _ap.DEATH_RECOVERY_TIMEOUT_S:
        _ap._telemetry_log(
            "death_recovery_timeout",
            elapsed_s=round(now - _ap._state.death_recovery_started_at, 1),
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
