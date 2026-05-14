"""Combat-side ``_act_*`` handlers split from ``bot_autopilot``.

Holds the engagement / boss-fight / gather / idle handlers plus the
per-tick ``_maybe_use_consumables`` auto-heal hook.  Constants and
state live on ``bot_autopilot`` and are read via the ``_ap`` alias.
"""
from __future__ import annotations

import math

import bot_autopilot as _ap
import bot_autopilot_navigation as _nav


def _act_engage(state: dict, p: dict) -> None:
    """ENGAGE: close on the nearest threat + hold fire.  Combat
    assist (bot_combat_assist.py) owns aim + fire override; this
    function chooses movement stop radius based on whether the
    assist has committed to a melee rush.

    The assist exposes ``state.assist.melee_engaged`` -- True when
    its per-engagement 50 % dice roll landed on melee.  In that
    case the autopilot drives forward to ``MELEE_STOP_RADIUS_PX``
    so the swing arc reaches the target and lets the assist's
    weapon lock keep the lightsabre selected.  Otherwise it
    stands off at ~380 px and uses the laser/melee sub-band
    hysteresis here.
    """
    aliens = state.get("aliens") or []
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    threat, td = _ap.nearest(aliens, px, py)
    if threat is None:
        # FSM said engage but the alien vanished mid-tick.  Bail
        # to a safe no-op; next tick will re-route us out.
        _ap.KeyState.hold("space", False)
        return

    # Clamp the chase target inside the world rect so a chase
    # toward an alien sitting at / past a world edge doesn't pin
    # the bot against the boundary.  Combat assist (60 FPS aim +
    # fire) still hits the alien through the boundary.  2026-05-04
    # telemetry: 12 HUNT stucks within 200-700 px of the north
    # edge before this clamp.
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _nav.clamp_to_world(
        threat["x"], threat["y"], zone)

    melee_committed = bool(
        (state.get("assist") or {}).get("melee_engaged", False))
    if melee_committed:
        # Committed melee rush: drive in to swing range.  Don't
        # call _ensure_weapon -- the in-process combat assist has
        # locked the Energy Blade and would just fight us at
        # 60 FPS vs our 10 Hz Tab presses.
        _ap._do_goto(state, p, chase_x, chase_y,
                 stop_radius=_ap.MELEE_STOP_RADIUS_PX)
        _ap.KeyState.hold("space", True)
        return

    # Ranged engagement (default): laser/melee sub-band hysteresis.
    cur_weapon = state.get("weapon", {}).get("name", "Basic Laser")
    if cur_weapon == "Melee":
        # In Melee already: only swap back to Laser once we're past
        # the exit band (130 px).
        if td > _ap.MELEE_EXIT_PX:
            _ap._ensure_weapon(state, "Basic Laser")
    else:
        # In a ranged weapon: only swap to Melee once we're firmly
        # inside the enter band (100 px).
        if td < _ap.MELEE_ENTER_PX:
            _ap._ensure_weapon(state, "Melee")
        else:
            _ap._ensure_weapon(state, "Basic Laser")
    _ap._do_goto(state, p, chase_x, chase_y, stop_radius=380.0)
    _ap.KeyState.hold("space", td < _ap.FIRE_RANGE_PX)


def _update_combat_latches(state: dict, p: dict, boss: dict,
                           hs: dict | None, phase: int) -> None:
    """Edge-triggered transitions for the two boss-fight latches:

    * ``boss_turret_assist_active`` — set when the boss enters
      ``BOSS_TURRET_ASSIST_ENTER_PX`` of the station, cleared on
      ``BOSS_TURRET_ASSIST_EXIT_PX`` exit (hysteresis prevents
      flap when the boss hovers at the boundary).  Eighth pass.
    * ``boss_lure_active`` — set when shields drop below
      ``BOSS_LURE_SHIELDS_PCT`` and an HS exists.  Sticky for
      the duration of the boss fight (cleared when boss dies).

    Telemetry events fire on edge transitions only, not per tick.
    """
    if hs is None:
        return
    bx = float(boss.get("x", 0.0))
    by = float(boss.get("y", 0.0))
    hpx = float(hs.get("x", 0.0))
    hpy = float(hs.get("y", 0.0))
    boss_to_hs = math.hypot(bx - hpx, by - hpy)
    if (not _ap._state.boss_turret_assist_active
            and boss_to_hs < _ap.BOSS_TURRET_ASSIST_ENTER_PX):
        _ap._state.boss_turret_assist_active = True
        _ap._telemetry_log(
            "boss_turret_assist_enter",
            boss_to_hs=round(boss_to_hs, 1),
            boss_phase=phase)
    elif (_ap._state.boss_turret_assist_active
            and boss_to_hs > _ap.BOSS_TURRET_ASSIST_EXIT_PX):
        _ap._state.boss_turret_assist_active = False
        _ap._telemetry_log(
            "boss_turret_assist_exit",
            boss_to_hs=round(boss_to_hs, 1),
            boss_phase=phase)

    sh_now = int(p.get("shields", 0))
    max_sh = max(1, int(p.get("max_shields", 1)))
    sh_frac = sh_now / max_sh
    if (not _ap._state.boss_lure_active
            and sh_frac < _ap.BOSS_LURE_SHIELDS_PCT):
        _ap._state.boss_lure_active = True
        _ap._telemetry_log("boss_lure_enter",
                           shields=sh_now, max_shields=max_sh,
                           sh_frac=round(sh_frac, 3),
                           boss_phase=phase)


def _compute_kite_target(p: dict, boss: dict, hs: dict | None,
                         desired_range: float
                         ) -> tuple[float, float]:
    """Compute the goto target for the boss-fight kite, before
    charge-dodge perturbation.

    Two anchor modes:

    * **TURRET-ASSIST / LURE** (either latch active, HS exists):
      orbit the FAR side of the station from the boss at
      ``BOSS_TURRET_ASSIST_ORBIT_PX`` so the station sits between
      the bot's heading and the boss.  PR #100/#103.
    * **Default kite**: a tangent orbit point
      ``BOSS_ORBIT_LEAD_RAD`` ahead of the boss->station axis
      (or boss->bot axis when no HS).  PR #106/#107.  The
      legacy station-tether snap (PR #95) still snaps the kite
      to the boss->station ray when it lands outside
      ``BOSS_KITE_STATION_TETHER_PX`` of the station.
    """
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    bx = float(boss.get("x", 0.0))
    by = float(boss.get("y", 0.0))

    use_orbit = ((_ap._state.boss_turret_assist_active
                  or _ap._state.boss_lure_active)
                 and hs is not None)
    if use_orbit:
        hx = float(hs.get("x", 0.0))
        hy = float(hs.get("y", 0.0))
        sdx = hx - bx
        sdy = hy - by
        sdist = math.hypot(sdx, sdy)
        radius = _ap.BOSS_TURRET_ASSIST_ORBIT_PX
        if sdist > 1.0:
            return (hx + (sdx / sdist) * radius,
                    hy + (sdy / sdist) * radius)
        # Boss on top of station — orbit any side of the HS.
        return (hx + radius, hy)

    # Default kite: tangent orbit point on the desired-range ring.
    if hs is not None:
        hx = float(hs.get("x", 0.0))
        hy = float(hs.get("y", 0.0))
        theta_anchor = math.atan2(hy - by, hx - bx)
    else:
        theta_anchor = math.atan2(py - by, px - bx)
    theta_lead = theta_anchor + _ap.BOSS_ORBIT_LEAD_RAD
    kite_x = bx + math.cos(theta_lead) * desired_range
    kite_y = by + math.sin(theta_lead) * desired_range

    # Station-tether snap: if the orbit drifted out of the
    # umbrella, pull the kite to the boss->station ray.
    if hs is not None:
        hx = float(hs.get("x", 0.0))
        hy = float(hs.get("y", 0.0))
        kite_to_hs = math.hypot(kite_x - hx, kite_y - hy)
        if kite_to_hs > _ap.BOSS_KITE_STATION_TETHER_PX:
            shx = hx - bx
            shy = hy - by
            shdist = math.hypot(shx, shy)
            if shdist > 1.0:
                kite_x = bx + (shx / shdist) * desired_range
                kite_y = by + (shy / shdist) * desired_range
    return kite_x, kite_y


def _apply_charge_dodge(p: dict, boss: dict, hs: dict | None,
                        kite_x: float, kite_y: float,
                        ux: float, uy: float, bdist: float,
                        phase: int) -> tuple[float, float]:
    """Phase 2+ charge dodge: when the boss is winding up a dash,
    add a perpendicular ``BOSS_DODGE_PERP_PX`` displacement to the
    kite target.  The dodge sign points toward the home station
    so dodge + retreat combine (PR #95).  Telemetry fires once
    per dodging tick.

    No-op outside Phase 2+ or when the boss isn't charging.
    """
    charging = bool(boss.get("charging", False))
    windup = float(boss.get("charge_windup", 0.0))
    if phase < 2 or (not charging and windup <= 0.0):
        return kite_x, kite_y

    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))

    # Panic escape (2026-05-13 thirteenth telemetry pass +
    # sixteenth-pass correction): when the bot is dangerously
    # close to the boss, OVERRIDE the kite target with a point
    # perpendicular to the boss->bot axis at
    # ``BOSS_CHARGE_PANIC_ESCAPE_PX``.  The previous panic version
    # (PR #112) used the radial ``(ux, uy)`` direction (directly
    # away from boss).  That sent the bot in the SAME direction
    # the boss dashes -- boss dashes toward bot's pre-windup
    # position at 600 px/s, bot escapes at ~150 px/s in the same
    # direction => boss catches up, collision damage every tick.
    # Sixteenth-pass log: 28 ``boss_dist=143, panic=true`` events
    # over 1.5 s, bot at collision edge the entire time.
    #
    # Perpendicular escape moves the bot off the dash line so the
    # boss's commit-direction dash misses by ``ESCAPE_PX``.  The
    # sign points toward home so the dodge combines with retreat.
    if bdist < _ap.BOSS_CHARGE_PANIC_DIST_PX:
        perp_x = -uy
        perp_y = ux
        if hs is not None:
            hsx = float(hs.get("x", 0.0))
            hsy = float(hs.get("y", 0.0))
            to_hs_x = hsx - px
            to_hs_y = hsy - py
            sign = 1.0 if (perp_x * to_hs_x
                           + perp_y * to_hs_y) >= 0.0 else -1.0
        else:
            sign = 1.0
        # Override kite to bot's current position + perp * ESCAPE_PX.
        # The dash is on the boss->bot ray; moving perpendicular
        # by ESCAPE_PX clears the dash line by ESCAPE_PX.
        kite_x = px + perp_x * sign * _ap.BOSS_CHARGE_PANIC_ESCAPE_PX
        kite_y = py + perp_y * sign * _ap.BOSS_CHARGE_PANIC_ESCAPE_PX
        _ap._telemetry_log("engage_boss_dodge",
                           phase=phase,
                           charging=bool(charging),
                           windup=round(float(windup), 3),
                           sign=sign,
                           boss_dist=round(bdist, 1),
                           panic=True)
        return kite_x, kite_y

    perp_x = -uy
    perp_y = ux
    if hs is not None:
        hsx = float(hs.get("x", 0.0))
        hsy = float(hs.get("y", 0.0))
        to_hs_x = hsx - px
        to_hs_y = hsy - py
        sign = 1.0 if (perp_x * to_hs_x
                       + perp_y * to_hs_y) >= 0.0 else -1.0
    else:
        sign = 1.0
    kite_x += perp_x * sign * _ap.BOSS_DODGE_PERP_PX
    kite_y += perp_y * sign * _ap.BOSS_DODGE_PERP_PX
    _ap._telemetry_log("engage_boss_dodge",
                       phase=phase,
                       charging=bool(charging),
                       windup=round(float(windup), 3),
                       sign=sign,
                       boss_dist=round(bdist, 1))
    return kite_x, kite_y


def _act_engage_boss(state: dict, p: dict) -> None:
    """ENGAGE_BOSS: station-anchor kite + phase-aware strafe.

    Strategy (see ``docs/bot.md`` section "Boss fight"):

      * **Anchor on the Home Station, not the boss.**  The boss
        spawns at the far world corner and flies toward the station;
        sitting at the perimeter lets friendly Defense Turrets +
        Missile Array share DPS instead of solo-grinding.  Falls
        back to a basic kite when no Home Station is present (early
        Nebula boss spawn before the bot has set up there).
      * **Hold at ``BOSS_KITE_RANGE_PX`` (750 px) from the boss.**
        Outside the cannon's max range (700) but inside Basic Laser
        range — every shot lands, no return fire.
      * **Stay within ``BOSS_KITE_STATION_TETHER_PX`` (600 px) of
        the station** so the kite circle never leaves the turret /
        missile umbrella.  When holding both constraints is
        impossible (boss is on top of the station), pick the
        station-tether — turret DPS matters more than the 750 px
        kite distance.
      * **Phase-aware charge dodge.**  Phase 2 introduces a 2 s
        charge windup + 0.8 s dash at 600 px/s (480 px line).  When
        ``boss.charging`` or ``boss.charge_windup > 0`` we strafe
        ``BOSS_DODGE_PERP_PX`` perpendicular to the boss-to-bot
        vector — the dash misses by a comfortable margin even with
        a 200 ms reaction.
      * **Phase 3 press.**  Boss has no shield regen and halved
        cooldowns; bot closes to ``BOSS_PHASE3_PRESS_RANGE_PX``
        (still outside spread range 600) to maximize its own DPS.
      * **REGEN escape valve still applies** — entry-side mirror
        + exit valve in ``_choose_next_state`` will yank the bot
        out to S_REGEN if shields collapse, so this handler
        doesn't need its own retreat path.

    Decomposed into three composable helpers:
    ``_update_combat_latches`` (turret-assist + lure latches),
    ``_compute_kite_target`` (geometric target picker),
    ``_apply_charge_dodge`` (perpendicular dash dodge).  This
    function is the orchestrator + boss-vanished early-out + fire
    gate + world clamp + ``_do_goto`` dispatch.
    """
    boss = state.get("boss")
    if boss is None:
        # Boss vanished mid-tick (killed); next tick re-routes.
        _ap.KeyState.hold("space", False)
        # Clear the lure + turret-assist latches so a future boss
        # fight starts fresh.
        _ap._state.boss_lure_active = False
        _ap._state.boss_turret_assist_active = False
        return

    _ap._ensure_weapon(state, "Basic Laser")

    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    bx = float(boss.get("x", 0.0))
    by = float(boss.get("y", 0.0))
    phase = int(boss.get("phase", 1))

    hs = _ap._find_home_station(state)

    _update_combat_latches(state, p, boss, hs, phase)

    # Boss-to-bot unit vector — defines the perpendicular axis for
    # the charge dodge and the fire-gate distance check.
    dx = px - bx
    dy = py - by
    bdist = math.hypot(dx, dy)
    if bdist < 1.0:
        # Bot is sitting on top of the boss (degenerate); pick an
        # arbitrary axis so the unit vector is defined.
        ux, uy = 1.0, 0.0
        bdist = 1.0
    else:
        ux, uy = dx / bdist, dy / bdist

    desired_range = (_ap.BOSS_PHASE3_PRESS_RANGE_PX
                     if phase >= 3 else _ap.BOSS_KITE_RANGE_PX)

    kite_x, kite_y = _compute_kite_target(p, boss, hs, desired_range)
    kite_x, kite_y = _apply_charge_dodge(
        p, boss, hs, kite_x, kite_y, ux, uy, bdist, phase)

    # World-edge clamp — same pattern as _act_engage so a corner
    # boss doesn't pull the bot into the boundary repulsion field.
    zone = state.get("zone") or {}
    target_x, target_y, _ = _nav.clamp_to_world(kite_x, kite_y, zone)

    # Stop radius: a generous 80 px so small course corrections
    # don't burn thrust thrashing the kite ring.
    _ap._do_goto(state, p, target_x, target_y, stop_radius=80.0)

    # Hold fire whenever we're within Basic Laser effective range
    # (the in-process combat assist will refine aim at 60 FPS).
    _ap.KeyState.hold("space", bdist < _ap.BOSS_FIRE_RANGE_PX)


def _maybe_use_consumables(state: dict, p: dict) -> None:
    """Per-tick auto-heal hook: fire repair pack / shield recharge
    based on HP / shield thresholds.  Runs every ``_do_auto`` tick
    before the FSM dispatch so the response is independent of which
    state the bot is in.

    The user spec is "use until 100 %", so each consumable is
    governed by a heal-active latch:

      * Latch ARMS when current value crosses below
        ``CONSUMABLE_USE_*_PCT`` of max.
      * Latch DISARMS when current value reaches max.
      * While the latch is armed, the auto-use loop fires on every
        tick (subject to ``CONSUMABLE_USE_COOLDOWN_S``) until either
        max is reached or the matching consumable runs out.

    Without the latch a single 50 %-heal use only refills the deficit
    that tripped the threshold — if HP dropped to 30 % between ticks,
    one use lands at 80 %, the next tick reads ``80/100 > 0.5`` and
    no further use fires until the bar drops below 50 % again.  The
    latch closes that gap.

    Repair pack takes priority over shield recharge when both
    latches are armed on the same tick (HP can't passively regen;
    shields do)."""
    hp = int(p.get("hp", 0))
    max_hp = max(1, int(p.get("max_hp", 1)))
    sh = int(p.get("shields", 0))
    max_sh = max(1, int(p.get("max_shields", 1)))
    hp_frac = hp / max_hp
    sh_frac = sh / max_sh

    # Edge transitions on the latches — log on arm + disarm so
    # telemetry shows the heal window boundaries.
    if not _ap._state.heal_hp_active and hp_frac <= _ap.CONSUMABLE_USE_HP_PCT:
        _ap._state.heal_hp_active = True
        _ap._telemetry_log("heal_hp_arm",
                       hp=hp, max_hp=max_hp, hp_frac=round(hp_frac, 3))
    if _ap._state.heal_hp_active and hp >= max_hp:
        _ap._state.heal_hp_active = False
        _ap._telemetry_log("heal_hp_disarm",
                       hp=hp, max_hp=max_hp)
    if not _ap._state.heal_shield_active and sh_frac <= _ap.CONSUMABLE_USE_SHIELD_PCT:
        _ap._state.heal_shield_active = True
        _ap._telemetry_log("heal_shield_arm",
                       shields=sh, max_shields=max_sh,
                       sh_frac=round(sh_frac, 3))
    if _ap._state.heal_shield_active and sh >= max_sh:
        _ap._state.heal_shield_active = False
        _ap._telemetry_log("heal_shield_disarm",
                       shields=sh, max_shields=max_sh)

    now = _ap._get_now()
    if (now - _ap._state.last_consumable_use_at) < _ap.CONSUMABLE_USE_COOLDOWN_S:
        return

    slots = state.get("quick_use_slots") or []
    if not slots:
        return

    # HP first — HP loss is harder to recover (no passive regen).
    if _ap._state.heal_hp_active:
        slot = _ap._find_quick_use_slot(slots, "repair_pack")
        if slot is not None:
            _ap._post_use_quick_use(slot)
            _ap._state.last_consumable_use_at = now
            _ap._telemetry_log("heal_hp_fire",
                           slot=slot, hp=hp, max_hp=max_hp)
            return

    if _ap._state.heal_shield_active:
        slot = _ap._find_quick_use_slot(slots, "shield_recharge")
        if slot is not None:
            _ap._post_use_quick_use(slot)
            _ap._state.last_consumable_use_at = now
            _ap._telemetry_log("heal_shield_fire",
                           slot=slot, shields=sh, max_shields=max_sh)
            return


def _act_gather(state: dict, p: dict) -> None:
    """GATHER: head toward the nearest pickup, no fire.

    Chase target is clamped to the world rect via ``_clamp_to_world``
    so a pickup sitting past the safety margin doesn't pull the bot
    into the boundary repulsion field's local-minimum trap (the
    classical edge-resource oscillation: goto pulls toward the wall,
    boundary repulsion pushes back, leftover force is wall-parallel,
    bot drifts along the edge instead of toward the resource).  When
    the pickup is inside the margin the clamp is a no-op.  When it's
    past the margin the bot navigates to the boundary edge — if the
    pickup hasn't drifted into reach, stuck-detect + the pickup
    blacklist let the bot move on to the next pickup instead of
    grinding for tens of seconds.

    Reachability check (2026-05-07 follow-up): before committing to
    a chase, ``_astar.target_reachable`` confirms a path exists
    through the building grid.  Pickups that drift inside the
    station-cluster repulsion zone (no path) get blacklisted
    immediately and the bot re-targets the next-nearest non-
    blacklisted pickup on the same tick — eliminating the deadlock
    where the bot pinned at (160, 4083) for 100+ s (PR #60
    telemetry).
    """
    import bot_autopilot_astar as _astar
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    pickup, _pd = _ap._nearest_pickup(state, px, py)
    if pickup is None:
        # Pickup vanished (probably collected); next tick re-routes.
        _ap.KeyState.hold("space", False)
        return
    # Up-front reachability check: blacklist + re-route if A* can't
    # find a path.  Capped at one re-attempt so a degenerate
    # all-pickups-blocked frame can't loop more than twice.
    for _attempt in range(2):
        if _astar.target_reachable(
                state, px, py, float(pickup["x"]), float(pickup["y"])):
            break
        _ap._blacklist_pickup(pickup)
        print(f"[autopilot] PICKUP-BLACKLIST (unreachable): "
              f"{pickup.get('item_type', '?')} at "
              f"({pickup['x']:.0f}, {pickup['y']:.0f})")
        _ap._astar_invalidate_path()
        pickup, _pd = _ap._nearest_pickup(state, px, py)
        if pickup is None:
            _ap.KeyState.hold("space", False)
            return
    else:
        # Both nearest pickups were unreachable; bail to a clean
        # idle so the next FSM tick re-evaluates the state cascade.
        _ap.KeyState.hold("space", False)
        return
    _ap.KeyState.hold("space", False)
    zone = state.get("zone") or {}
    chase_x, chase_y, _ = _nav.clamp_to_world(
        pickup["x"], pickup["y"], zone)
    _ap._do_goto(state, p, chase_x, chase_y,
             stop_radius=_ap.PICKUP_STOP_RADIUS)


def _act_idle_at_base(state: dict, p: dict) -> None:
    """IDLE_AT_BASE: navigate to the *outer ring* of the idle zone
    (one ``IDLE_AT_BASE_RADIUS_PX`` from the Home Station, on the
    line from the player toward the station) and idle there.

    Why the outer ring instead of the station centre: 2026-05-04
    telemetry showed the bot drifting all the way to hs_dist 58 —
    deep inside the 11-building station cluster.  When an alien
    later spawned and HUNT fired, the bot couldn't escape the
    cluster (14 ``stuck_detected`` events, all anchored at the
    same cluster-interior position, zero combat).  Parking at the
    outer ring instead means HUNT can launch from clear space.
    """
    hs = _ap._find_home_station(state)
    if hs is None:
        # Defensive: caller (_choose_next_state) only routes here
        # when an HS exists, but if it disappeared mid-tick fall
        # back to a clean idle so the FSM re-evaluates next tick.
        _ap._do_idle()
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    hx = float(hs.get("x", 0.0))
    hy = float(hs.get("y", 0.0))
    _ap.KeyState.hold("space", False)  # never fire while idle
    # Vector from station to player — the outer-ring target is on
    # this ray at distance IDLE_AT_BASE_RADIUS_PX from the station.
    dx = px - hx
    dy = py - hy
    dist = math.hypot(dx, dy)
    if dist <= _ap.IDLE_AT_BASE_RADIUS_PX:
        # Already inside the idle zone — release everything and
        # drift.  Stuck-detect is exempt for IDLE_AT_BASE so a
        # nudge from a building's potential field won't trigger
        # an escape burst.
        _ap._do_idle()
        return
    # Outside the idle ring — head to a point on the ring around HS
    # that's INSIDE the world rect.  Preferred direction is the
    # player→HS ray (so the bot parks on the side it's coming from);
    # if that point is past the world boundary (HS near a corner),
    # ``find_clear_ring_point`` sweeps the ring for an interior
    # alternative.  Caught from 2026-05-04 telemetry: HS in the
    # upper-right of the world produced 12 HUNT stucks at y≈5500-6200
    # because the projected outer-ring target sat at y≈6600.
    zone = state.get("zone") or {}
    target_x, target_y = _nav.find_clear_ring_point(
        hx, hy, _ap.IDLE_AT_BASE_RADIUS_PX, zone, dx, dy)
    _ap._do_goto(state, p, target_x, target_y, stop_radius=80.0)
