"""Station-side ``_act_*`` handlers split from ``bot_autopilot``.

Each handler navigates the bot to a station building (Home Station,
Basic Crafter) and POSTs the appropriate one-shot endpoint.  Constants
and helper functions referenced via ``_ap`` live on ``bot_autopilot``.
"""
from __future__ import annotations

import math

import bot_autopilot as _ap


def _act_recover_loot(state: dict, p: dict) -> None:
    """RECOVER_LOOT: navigate back to the recorded death position so
    the dropped iron / module / consumable pickups vacuum into the
    ship via the existing auto-attract loop.

    No POST required -- pickup collection happens passively as the
    bot drives within attract range of each item.  Weapons stay
    cold so a stray asteroid in the area doesn't burn the cycle
    mining instead of recovering.

    Cleared by ``_maybe_clear_death_recovery`` once no pickups
    remain near the death position (either collected by the bot or
    despawned via WORLD_ITEM_LIFETIME) or after
    ``DEATH_RECOVERY_TIMEOUT_S`` elapses.
    """
    target_x, target_y = _ap._state.death_recovery_pos
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    # Clamp to the world rect so a death right at the boundary
    # doesn't push the bot into the edge-repulsion pin.
    tx = max(_ap.STUCK_WORLD_MARGIN_PX,
             min(world_w - _ap.STUCK_WORLD_MARGIN_PX, target_x))
    ty = max(_ap.STUCK_WORLD_MARGIN_PX,
             min(world_h - _ap.STUCK_WORLD_MARGIN_PX, target_y))
    _ap.KeyState.hold("space", False)
    _ap._do_goto(state, p, tx, ty,
                 stop_radius=_ap.DEATH_RECOVERY_STOP_RADIUS_PX)


def _act_build_seek(state: dict, p: dict) -> None:
    """BUILD_SEEK: walk in the direction of least detectable
    density, looking for a clear pocket to build the starter
    base.  Heads BUILD_SEEK_TARGET_DIST_PX in the away-from-
    centroid direction (clamped to the world), then the FSM
    re-evaluates each tick and either flips to S_BUILD when the
    area becomes clear or keeps seeking."""
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    ux, uy = _ap._build_seek_direction(state, px, py)
    tx = px + ux * _ap.BUILD_SEEK_TARGET_DIST_PX
    ty = py + uy * _ap.BUILD_SEEK_TARGET_DIST_PX
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    tx = max(_ap.STUCK_WORLD_MARGIN_PX,
             min(world_w - _ap.STUCK_WORLD_MARGIN_PX, tx))
    ty = max(_ap.STUCK_WORLD_MARGIN_PX,
             min(world_h - _ap.STUCK_WORLD_MARGIN_PX, ty))
    # Don't fire any weapon while seeking — the goal is to find
    # an empty pocket, not to mine on the way.
    _ap.KeyState.hold("space", False)
    _ap._do_goto(state, p, tx, ty, stop_radius=200.0)


def _act_deposit(state: dict, p: dict) -> None:
    """DEPOSIT: head to the home station and dump everything in
    the ship inventory into the station's bigger storage.  Once
    within DEPOSIT_RANGE_PX of the Home Station, POSTs the
    deposit and stamps ``last_deposit_at`` so the cooldown kicks
    in.  Otherwise just navigates toward the station — the FSM
    re-evaluates next tick.

    Cooldown guard (2026-05-09): once a deposit POST has fired,
    skip subsequent POSTs while ``last_deposit_at`` is still
    inside ``DEPOSIT_COOLDOWN_S``.  ``_choose_next_state`` already
    refuses to re-enter S_DEPOSIT during cooldown, but the
    ``MIN_DWELL_S = 1 s`` floor keeps the FSM in S_DEPOSIT for
    ~10 more ticks after the first successful POST — without this
    guard the bot fires 9 redundant empty-payload deposit POSTs
    per cycle (each a 5 s-timeout HTTP request), blocking the
    100 ms tick budget.  Caught from the 14-min telemetry session
    where 10 deposit_post events landed within 1.5 s, the first
    with real content and the next 9 each with ``deposited={}``.
    """
    hs = _ap._find_home_station(state)
    if hs is None:
        # Home Station vanished mid-tick (destroyed?) — fall back
        # to idle so the FSM can re-route on the next tick.
        _ap._do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hx = float(hs.get("x", 0.0))
    hy = float(hs.get("y", 0.0))
    dist = math.hypot(hx - px, hy - py)
    if dist <= _ap.DEPOSIT_RANGE_PX:
        # Cooldown guard — see docstring.  Skip the POST if we just
        # deposited; the FSM will transition out of S_DEPOSIT on
        # the next ``_choose_next_state`` evaluation.
        now = _ap._get_now()
        if (now - _ap._state.last_deposit_at) < _ap.DEPOSIT_COOLDOWN_S:
            _ap.KeyState.release_all()
            return
        # In range and cooldown clear — fire the deposit and stamp.
        result = _ap._post_deposit_to_station()
        _ap._state.last_deposit_at = now
        deposited = (result or {}).get("deposited", {}) or {}
        _ap._telemetry_log("deposit_post",
                       success=result is not None,
                       in_range_dist=round(dist, 1),
                       deposited=deposited,
                       **_ap._telemetry_snapshot_fields(state, p))
        if result is not None and deposited:
            print("[autopilot] DEPOSIT: "
                  f"{', '.join(f'{k}={v}' for k, v in deposited.items())}")
        return
    # Not yet in range — navigate to the home station, no fire.
    _ap.KeyState.hold("space", False)
    _ap._do_goto(state, p, hx, hy, stop_radius=_ap.DEPOSIT_RANGE_PX * 0.8)


def _act_craft(state: dict, p: dict) -> None:
    """S_CRAFT: navigate to the nearest idle Basic Crafter.  Once
    in range, fire POST /craft for the queue head and pop the
    queue on success.  The FSM transitions back to MINE / GATHER /
    SEARCH on the next tick — the crafter ticks down its 60 s
    timer on its own, and ``_choose_next_state`` won't re-enter
    S_CRAFT until ``_any_crafter_busy`` reports False again."""
    crafter = _ap._find_basic_crafter(state, idle_only=True)
    if crafter is None:
        # No idle crafter visible — happens for one tick right
        # after we just started a craft (state hasn't refreshed
        # yet).  Fall back to safe coast; the FSM re-routes us
        # next tick.
        _ap._do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    cx = float(crafter.get("x", 0.0))
    cy = float(crafter.get("y", 0.0))
    dist = math.hypot(cx - px, cy - py)
    if dist > _ap.CRAFT_INTERACT_RANGE_PX:
        # Still travelling — navigate, don't fire.
        _ap.KeyState.hold("space", False)
        _ap._do_goto(state, p, cx, cy,
                 stop_radius=_ap.CRAFT_INTERACT_RANGE_PX * 0.8)
        return
    # In range.  Compute what to craft, fire the POST, pop on success.
    target = _ap._next_craft_target(state)
    if target is None:
        # Queue head not ready (insufficient iron, blueprint
        # missing, etc.).  Idle one tick; FSM will re-route.
        _ap._do_idle()
        return
    _ap.KeyState.release_all()
    print(f"[autopilot] CRAFT: starting {target!r} "
          f"(station_iron={_ap._station_iron(state)})")
    result = _ap._post_craft(target)
    q = _ap._state.queue
    if result is None or not result.get("ok", False):
        reason = (result or {}).get("reason", "transport failure")
        print(f"[autopilot] CRAFT: {target!r} rejected ({reason})")
        return
    # Success — pop the queue head + flip the phase-started latch.
    if target in _ap.MODULE_CRAFT_QUEUE and q.modules_to_craft \
            and q.modules_to_craft[0] == target:
        q.modules_to_craft.pop(0)
        q.module_phase_started = True
    elif target == "repair_pack" and q.repair_packs_remaining > 0:
        q.repair_packs_remaining -= 1
        q.consumable_phase_started = True
    elif target == "shield_recharge" and q.shield_recharges_remaining > 0:
        q.shield_recharges_remaining -= 1
        q.consumable_phase_started = True
    print(f"[autopilot] CRAFT: queued {target!r} -- "
          f"modules_left={len(q.modules_to_craft)} "
          f"installs_left={len(q.modules_to_install)} "
          f"rp_left={q.repair_packs_remaining} "
          f"sr_left={q.shield_recharges_remaining}")


def _act_install(state: dict, p: dict) -> None:
    """S_INSTALL: navigate to the Home Station, then fire POST
    /install_module for the head of ``modules_to_install``.  Pops
    the queue on success."""
    hs = _ap._find_home_station(state)
    if hs is None:
        _ap._do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hx = float(hs.get("x", 0.0))
    hy = float(hs.get("y", 0.0))
    dist = math.hypot(hx - px, hy - py)
    if dist > _ap.INSTALL_INTERACT_RANGE_PX:
        _ap.KeyState.hold("space", False)
        _ap._do_goto(state, p, hx, hy,
                 stop_radius=_ap.INSTALL_INTERACT_RANGE_PX * 0.8)
        return
    target = _ap._next_install_target(state)
    if target is None:
        _ap._do_idle()
        return
    _ap.KeyState.release_all()
    result = _ap._post_install_module(target)
    q = _ap._state.queue
    if result is None or not result.get("ok", False):
        reason = (result or {}).get("reason", "transport failure")
        print(f"[autopilot] INSTALL: {target!r} rejected ({reason})")
        return
    if q.modules_to_install and q.modules_to_install[0] == target:
        q.modules_to_install.pop(0)
    print(f"[autopilot] INSTALL: {target!r} -> slot "
          f"{result.get('slot')} (installs_left="
          f"{len(q.modules_to_install)})")


def _act_build(state: dict, p: dict) -> None:
    """BUILD: fire the one-shot starter-base trigger and flip
    ``_state.build_done`` so the FSM falls through to MINE /
    SEARCH on subsequent ticks.  Releases all movement keys for
    the duration of the call so the ship coasts in place while
    the seven buildings are placed in-process.

    Guarded by an early ``build_done`` check: while the FSM is
    holding S_BUILD through MIN_DWELL_S, the dispatch can call
    this multiple times — but only the FIRST call should actually
    POST the build.  Without the guard, a 0.6 s dwell at 10 Hz
    plus the synchronous HTTP POST round-trip produced 6 build
    attempts in one play-test, each one re-spending iron on
    duplicate buildings."""
    if _ap._state.build_done:
        # Already POSTed once this session.  Coast until the FSM
        # transitions out of S_BUILD on the next tick.
        _ap._do_idle()
        return
    _ap.KeyState.release_all()
    _ap._do_idle()
    print("[autopilot] BUILD: requesting starter base "
          f"(iron={_ap._iron_total(state)})")
    # Mark done BEFORE the POST so a re-entry mid-POST (if it
    # ever happens) early-returns above.  The HTTP request is
    # synchronous so we'll typically only re-enter post-completion.
    _ap._state.build_done = True
    result = _ap._post_build_starter_base()
    if result is None:
        print("[autopilot] BUILD: POST failed; flagging done so the "
              "FSM resumes normal flow")
        return
    placed = result.get("placed", [])
    failed = result.get("failed", [])
    print(f"[autopilot] BUILD: placed {len(placed)} "
          f"({[p['type'] for p in placed]})  "
          f"failed {len(failed)}")
    if failed:
        for f in failed:
            print(f"  - {f}")


def _act_build_nebula(state: dict, p: dict) -> None:
    """BUILD_NEBULA: fire the starter-base trigger in ZONE2 and
    latch ``_state.nebula_build_done`` so the FSM falls through
    to MINE / SEARCH on subsequent ticks.

    Mirror of ``_act_build`` (different latch only).  The
    game-side ``/build_starter_base`` endpoint places at the
    player's current position into the active zone's
    ``building_list``, which is zone-scoped via the ZoneState
    stash mechanism (see ``zones/__init__.py``).  So the same
    endpoint that built the MAIN base lands a fresh starter
    base in Nebula when called from ZONE2 -- the per-zone
    Home Station ``max=1`` cap is enforced against the
    current zone's building_list, not save-wide.
    """
    if _ap._state.nebula_build_done:
        # Already POSTed once this Nebula visit -- coast until
        # the FSM transitions out on the next tick.
        _ap._do_idle()
        return
    _ap.KeyState.release_all()
    _ap._do_idle()
    print("[autopilot] BUILD_NEBULA: requesting starter base "
          f"(iron={_ap._iron_total(state)})")
    # Mark done BEFORE the POST so a re-entry mid-POST (if it
    # ever happens) early-returns above.  Same guard pattern as
    # ``_act_build``.
    _ap._state.nebula_build_done = True
    result = _ap._post_build_starter_base()
    if result is None:
        print("[autopilot] BUILD_NEBULA: POST failed; flagging "
              "done so the FSM resumes normal flow")
        return
    placed = result.get("placed", [])
    failed = result.get("failed", [])
    print(f"[autopilot] BUILD_NEBULA: placed {len(placed)} "
          f"({[p['type'] for p in placed]})  "
          f"failed {len(failed)}")
    if failed:
        for f in failed:
            print(f"  - {f}")


def _act_at_station(
        state: dict,
        p: dict,
        *,
        label: str,
        post_fn,
        on_success_log,
        latch_setter,
        latch_failure_keywords: tuple[str, ...] = (),
        latch_already_set=None,
        ) -> None:
    """Shared "travel to Home Station, POST a one-shot endpoint,
    latch on success" helper for the boss-prep pipeline action
    handlers.  Both ``_act_equip_consumables`` and ``_act_build_qwi``
    share the same shape — only the POST function, success log, and
    the latch field differ.

    Args:
      label: short string for the log prefix (e.g. ``"EQUIP"``).
      post_fn: zero-arg callable returning the POST response dict.
      on_success_log: callable taking the response dict, returns the
                      log line to print on success.
      latch_setter: zero-arg callable that flips the latch field on
                    ``_state``.  Called both on success AND on a
                    failure response whose reason string contains any
                    of ``latch_failure_keywords`` (default empty).
      latch_failure_keywords: substrings to match against the
                              response's ``reason`` field.  When any
                              matches, the latch is set so the FSM
                              moves on instead of looping forever
                              (e.g. ``"no consumables"`` after
                              consumables already withdrawn).
      latch_already_set: optional zero-arg callable returning True
                              iff the latch field is already set.
                              When True, skip the POST entirely and
                              ``_do_idle`` while the FSM waits out
                              MIN_DWELL_S before transitioning.  The
                              2026-05-10 telemetry caught the bot
                              POSTing /equip_consumables 9 times in
                              the 1-second dwell window after the
                              first success -- every retry returned
                              "no consumables in station inventory"
                              and latched again redundantly.  Same
                              pathology would hit fortify / build_qwi
                              if their FSM exit was dwell-gated, so
                              the latch-skip guard lives on all three
                              station-post sites.

    Telemetry events emitted:
      * ``<label>_post_failure`` — POST returned ``ok=False`` or
        transport failed.  Payload includes ``reason`` and whether
        the failure latched.
      * ``<label>_post_success`` — POST returned ``ok=True``.
    """
    hs = _ap._find_home_station(state)
    if hs is None:
        _ap._do_idle()
        return
    if latch_already_set is not None and latch_already_set():
        # Latch already set this session -- waiting out MIN_DWELL_S
        # before the FSM transitions away.  Skip the POST so we
        # don't burn HTTP round-trips on requests we know will
        # return "no consumables" / "already placed" / etc.
        _ap.KeyState.release_all()
        _ap._do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hx = float(hs.get("x", 0.0))
    hy = float(hs.get("y", 0.0))
    dist = math.hypot(hx - px, hy - py)
    if dist > _ap.INSTALL_INTERACT_RANGE_PX:
        _ap.KeyState.hold("space", False)
        _ap._do_goto(state, p, hx, hy,
                 stop_radius=_ap.INSTALL_INTERACT_RANGE_PX * 0.8)
        return
    _ap.KeyState.release_all()
    result = post_fn()
    if result is None or not result.get("ok", False):
        reason = str((result or {}).get("reason", "transport failure"))
        print(f"[autopilot] {label}: rejected ({reason})")
        latched = False
        if any(kw in reason for kw in latch_failure_keywords):
            latch_setter()
            latched = True
        _ap._telemetry_log(f"{label.lower()}_post_failure",
                       reason=reason, latched=latched)
        return
    latch_setter()
    msg = on_success_log(result)
    print(f"[autopilot] {label}: {msg}")
    _ap._telemetry_log(f"{label.lower()}_post_success",
                   **{k: result.get(k) for k in result if k != "ok"})


def _act_equip_consumables(state: dict, p: dict) -> None:
    """S_EQUIP_CONSUMABLES: navigate to the Home Station, then POST
    /equip_consumables.  Flips ``_state.consumables_equipped`` on
    success so the FSM doesn't re-fire.  Also flips the latch on
    the "no consumables" failure (already withdrawn)."""
    def _set_latch():
        _ap._state.consumables_equipped = True

    _act_at_station(
        state, p,
        label="EQUIP",
        post_fn=_ap._post_equip_consumables,
        on_success_log=lambda r: (
            f"rp={r.get('repair_pack')} "
            f"sr={r.get('shield_recharge')} "
            f"slots=({r.get('repair_slot')},{r.get('shield_slot')})"),
        latch_setter=_set_latch,
        latch_failure_keywords=("no consumables",),
        latch_already_set=lambda: _ap._state.consumables_equipped,
    )


def _act_fortify(state: dict, p: dict) -> None:
    """S_FORTIFY: navigate to the Home Station, then POST /fortify
    to drop the 4-turret defensive ring (N / S cardinals + NW / SE
    corners).  Flips ``_state.fortify_done`` on success so the FSM
    falls through to S_BUILD_QWI on the next tick.  Also flips the
    latch on the "ring already complete" / "no home station" failure
    paths so the FSM doesn't loop forever if the user has manually
    populated the cluster or the station was destroyed."""
    def _set_latch():
        _ap._state.fortify_done = True

    _act_at_station(
        state, p,
        label="FORTIFY",
        post_fn=_ap._post_fortify,
        on_success_log=lambda r: (
            f"placed={len(r.get('placed', []))} "
            f"failed={len(r.get('failed', []))} "
            f"defenders_now={r.get('defenders_now', '?')}"),
        latch_setter=_set_latch,
        # The bot_builder helper returns "ring already complete"
        # when the cluster is already at the staging minimum, and
        # "no home station" / "no active home station" when there's
        # nothing to anchor on — both should latch so the FSM
        # advances rather than retrying every tick.
        latch_failure_keywords=("already complete", "no home",
                                "no active home"),
        latch_already_set=lambda: _ap._state.fortify_done,
    )


def _act_build_qwi(state: dict, p: dict) -> None:
    """S_BUILD_QWI: navigate to the Home Station, then POST
    /place_qwi.  Auto-spawns the Double Star boss on success.  Flips
    ``_state.qwi_placed`` so the FSM doesn't re-fire even if the
    next-tick state snapshot hasn't refreshed yet.  Also flips the
    latch on the "already placed" failure path."""
    def _set_latch():
        _ap._state.qwi_placed = True

    _act_at_station(
        state, p,
        label="BUILD_QWI",
        post_fn=_ap._post_place_qwi,
        on_success_log=lambda r: (
            f"placed at {r.get('placed_at')} "
            f"boss_spawned={r.get('boss_spawned', False)}"),
        latch_setter=_set_latch,
        # The bot_builder helper returns "QWI already placed";
        # match case-insensitively via the lowered reason from the
        # test in _act_at_station — easiest is to include both
        # casings as keywords since the comparison is substring.
        latch_failure_keywords=("already placed", "already"),
        latch_already_set=lambda: _ap._state.qwi_placed,
    )
