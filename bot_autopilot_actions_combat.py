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
    # umbrella, pull the kite onto the boss->station ray.  If
    # the ray-snap is STILL out of tether (boss spawned far from
    # HS), park at the umbrella edge facing the boss instead of
    # chasing it into open space.  2026-05-14 eighteenth-pass
    # log: boss spawned ~3000 px from HS, bot followed default
    # kite tangent into point-blank range, took 120 shields of
    # damage in 0.9 s, died with boss at 2000/2000 HP (zero
    # damage dealt).  Parking at the umbrella edge keeps the bot
    # within turret + missile-array DPS share and inside laser
    # range when the boss approaches.
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
            # Recheck after ray-snap.  If still out of tether,
            # boss is too far for any desired-range orbit point
            # to fit -- park at the umbrella edge instead.
            kite_to_hs2 = math.hypot(kite_x - hx, kite_y - hy)
            if kite_to_hs2 > _ap.BOSS_KITE_STATION_TETHER_PX:
                bxh = bx - hx
                byh = by - hy
                bhdist = math.hypot(bxh, byh)
                if bhdist > 1.0:
                    kite_x = (hx + (bxh / bhdist)
                              * _ap.BOSS_KITE_STATION_TETHER_PX)
                    kite_y = (hy + (byh / bhdist)
                              * _ap.BOSS_KITE_STATION_TETHER_PX)
                else:
                    kite_x, kite_y = hx, hy
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


def _regen_gas_escape(state: dict, p: dict, px: float, py: float,
                      cloud) -> None:
    """Drive on a ray from gas cloud centre out past the edge plus
    ``REGEN_GAS_ESCAPE_MARGIN_PX`` so the bot ends up clear of the
    field, not hugging it.  ``gas_repulsion`` in steered_heading
    further deflects around any clouds en route.

    Captured 2026-05-15: bot parked inside a Nebula cloud for 30+ s
    with shields stuck at 1-2/120 -- gas damage exactly matched the
    passive shield regen.
    """
    cx, cy, radius = cloud
    dx, dy = px - cx, py - cy
    d = math.hypot(dx, dy)
    if d < 1.0:
        dx, dy, d = 1.0, 0.0, 1.0
    ux, uy = dx / d, dy / d
    target_dist = radius + _ap.REGEN_GAS_ESCAPE_MARGIN_PX
    tx, ty = cx + ux * target_dist, cy + uy * target_dist
    zone = state.get("zone") or {}
    tx, ty, _ = _nav.clamp_to_world(tx, ty, zone)
    _ap.KeyState.hold("space", False)
    _ap._do_goto(state, p, tx, ty, stop_radius=80.0)


def _regen_drive_to_hs(state: dict, p: dict, px: float, py: float,
                       hs: dict) -> None:
    """Drive to within the game's healing umbrella
    (``REPAIR_RANGE = 300 px``) so ``REPAIR_SHIELD_BOOST`` applies
    + HP regen activates.

    Hysteresis: trigger at ``REGEN_HS_DRIVE_RADIUS_PX`` (250 px,
    inside the 300 px umbrella) -- the bot drives to a comfortable
    interior point and can't be bumped back out by a single tick
    of repulsion.  Once inside, idle to maximize regen rate (any
    thrust wastes regen budget while the bot ducks in and out).
    """
    hx, hy = float(hs.get("x", 0.0)), float(hs.get("y", 0.0))
    d_hs = math.hypot(hx - px, hy - py)
    if d_hs > _ap.REGEN_HS_DRIVE_RADIUS_PX:
        _ap.KeyState.hold("space", False)
        _ap._do_goto(state, p, hx, hy,
                     stop_radius=_ap.REGEN_HS_DRIVE_STOP_PX)
        return
    _ap._do_idle()


def _regen_flee_boss(state: dict, p: dict, px: float, py: float,
                     boss: dict) -> None:
    """No-HS + boss-alive flee.  Drive along the ray from boss
    through the bot out to ``BOSS_FLEE_TARGET_PX`` past the bot's
    current position.

    Captured 2026-05-14: 12 deaths in 60 s after HS destruction
    while idling; active flee kept the bot out of range.
    """
    bx, by = float(boss.get("x", 0.0)), float(boss.get("y", 0.0))
    dx, dy = px - bx, py - by
    d = math.hypot(dx, dy)
    if d < 1.0:
        # Bot on top of boss (degenerate); pick an arbitrary axis.
        dx, dy, d = 1.0, 0.0, 1.0
    ux, uy = dx / d, dy / d
    tx = bx + ux * _ap.BOSS_FLEE_TARGET_PX
    ty = by + uy * _ap.BOSS_FLEE_TARGET_PX
    zone = state.get("zone") or {}
    tx, ty, _ = _nav.clamp_to_world(tx, ty, zone)
    _ap.KeyState.hold("space", False)
    _ap._do_goto(state, p, tx, ty, stop_radius=120.0)


def _act_regen(state: dict, p: dict) -> None:
    """REGEN: dispatcher over four mutually-exclusive recovery
    behaviours, in priority order.  Each sub-handler holds its
    own ray math + telemetry context; this function just picks one.

      1. **Gas cloud escape** (``_regen_gas_escape``) -- bot is
         inside a damaging gas field.  Damage from gas compounds
         faster than from a kiting boss, and applies even with no
         boss alive (Nebula clouds outlive the Double Star).
      2. **Drive to HS** (``_regen_drive_to_hs``) -- a home station
         exists in this zone; drive into the healing umbrella so
         shield + HP regen are both active.
      3. **Flee boss** (``_regen_flee_boss``) -- no HS available but
         a boss is alive and will close on a parked bot.  Active
         flee keeps it out of range.
      4. **Idle** -- no special case; sit still and recover at the
         passive regen rate.
    """
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))

    cloud = _gas_cloud_at(state, px, py)
    if cloud is not None:
        _regen_gas_escape(state, p, px, py, cloud)
        return

    hs = _ap._find_home_station(state)
    if hs is not None:
        _regen_drive_to_hs(state, p, px, py, hs)
        return

    boss = state.get("boss")
    if boss is not None:
        _regen_flee_boss(state, p, px, py, boss)
        return

    _ap._do_idle()


def _act_flee_gas(state: dict, p: dict) -> None:
    """FLEE_GAS: drive out of the damaging gas cloud the bot is
    currently inside.  Same ray-out math as ``_act_regen``'s gas
    branch -- target a point past the cloud edge by
    ``REGEN_GAS_ESCAPE_MARGIN_PX`` on the cloud-centre -> bot ray,
    so the bot exits the field rather than hugging it.

    Pre-fix the gas escape only fired when the bot was already in
    S_REGEN.  Captured 2026-05-18 telemetry: bot in S_ENGAGE inside
    a WARP_GAS cloud at (3823, 3089), shields drained 18 -> 0 over
    ~3 s of stuck_detected events while it fought an alien
    standing in the same cloud.  This handler runs whenever
    ``choose_next_state`` routes us to S_FLEE_GAS regardless of
    what the bot would otherwise be doing.
    """
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    # Use the same exit-hysteresis margin as ``choose_next_state``
    # so the handler keeps driving the bot out across the entire
    # hysteresis band, not just while strictly inside the cloud.
    # Without this the bot crosses the strict edge, the strict
    # ``_gas_cloud_at`` returns None, the defensive idle below
    # releases all keys, and the bot drifts in the hysteresis band
    # while FSM still holds S_FLEE_GAS -- making no progress
    # toward the escape target.
    inside_cloud = _gas_cloud_at(state, px, py,
                                 _ap.FLEE_GAS_EXIT_MARGIN_PX)
    if inside_cloud is None:
        # Defensive: choose only routes here when within
        # ``FLEE_GAS_EXIT_MARGIN_PX`` of a cloud edge.  If state
        # shifted between tick and handler dispatch (cloud popped,
        # bot teleported, etc.) just idle for one tick -- next
        # tick's choose will route us out of S_FLEE_GAS.
        _ap._do_idle()
        return
    # Cluster-aware escape (2026-05-19 follow-up).  The previous
    # single-cloud ray only escaped the cloud the bot was currently
    # in -- when adjacent clouds clustered (typical in WARP_GAS), the
    # bot crossed cloud A's edge straight into cloud B, the FSM
    # bounced FLEE_GAS / REGEN / FLEE_GAS, and shields drained ~100 px
    # over ~16 s without making real progress.  Reuse
    # ``gas_repulsion`` which already sums contributions from every
    # cloud within ``GAS_REPULSION_RANGE_PX`` so the drive direction
    # points away from the cluster, not just the nearest cloud
    # centre.  Target distance is large (``FLEE_GAS_CLUSTER_ESCAPE_PX``)
    # so a single goto clears the whole local cluster instead of
    # hugging the first cloud's edge.
    gas_rx, gas_ry = _nav.gas_repulsion(p, state, target=None)
    rep_mag = math.hypot(gas_rx, gas_ry)
    if rep_mag >= 0.01:
        ux, uy = gas_rx / rep_mag, gas_ry / rep_mag
        tx = px + ux * _ap.FLEE_GAS_CLUSTER_ESCAPE_PX
        ty = py + uy * _ap.FLEE_GAS_CLUSTER_ESCAPE_PX
    else:
        # Fallback: ``gas_repulsion`` only returns non-zero for
        # clouds with ``state["gas_areas"]`` populated.  If we got
        # here via the hysteresis band but the field is empty (cloud
        # popped between tick and handler dispatch, or test harness),
        # use the original single-cloud ray as a safety net.
        cx, cy, radius = inside_cloud
        dx = px - cx
        dy = py - cy
        d = math.hypot(dx, dy)
        if d < 1.0:
            dx, dy, d = 1.0, 0.0, 1.0
        ux, uy = dx / d, dy / d
        target_dist = radius + _ap.REGEN_GAS_ESCAPE_MARGIN_PX
        tx = cx + ux * target_dist
        ty = cy + uy * target_dist
    zone = state.get("zone") or {}
    tx, ty, _ = _nav.clamp_to_world(tx, ty, zone)
    _ap.KeyState.hold("space", False)
    _ap._do_goto(state, p, tx, ty, stop_radius=80.0)


def _gas_cloud_at(state: dict, px: float, py: float,
                  extra_radius: float = 0.0):
    """Return ``(cx, cy, radius)`` of the first gas cloud whose
    interior contains ``(px, py)``, or ``None`` if the bot is
    in clear space.  Helper for ``_act_regen`` / ``_act_flee_gas``
    plus the FLEE_GAS branch in ``choose_next_state``.

    ``extra_radius`` widens the match radius for hysteresis: when
    ``cur == S_FLEE_GAS`` the choose function passes
    ``FLEE_GAS_EXIT_MARGIN_PX`` so the bot stays in FLEE_GAS
    until clearly past the cloud edge.  Without this, the bot
    exits the boundary on one tick, WARP_TRAVERSE drives it
    straight back into the cloud the next tick, and the FSM
    thrashes ~10 Hz while shields drain.  Captured pathology
    (2026-05-18 telemetry): 17 FLEE_GAS <-> WARP_TRAVERSE
    transitions, one with 93 ms dwell.

    Lists are short (typically <50 entries) so the linear scan
    is cheap; mirrors the per-cloud loop in ``gas_repulsion``
    for consistency.
    """
    for c in (state.get("gas_areas") or []):
        cx = float(c.get("x", 0.0))
        cy = float(c.get("y", 0.0))
        radius = float(c.get("radius", 80.0))
        if math.hypot(px - cx, py - cy) < radius + extra_radius:
            return (cx, cy, radius)
    return None


def _wormhole_arrival_watchdog(state: dict, p: dict, now: float,
                               tx: float, ty: float,
                               nearest_d: float) -> bool:
    """Pin-timeout latch (PR #163).  When the bot has been within
    ``stop_radius`` of a wormhole for ``PIN_TIMEOUT_S`` without the
    game's 100-px auto-warp firing, latch ``warp_after_boss_done``
    so the FSM cascade abandons this attempt and resumes productive
    work.

    The arrival timer is single-armed per visit -- first tick inside
    the radius seeds ``warp_wormhole_arrived_at``; subsequent ticks
    compare against it.  Reset is the caller's job (the en-route
    branch zeroes it when the bot leaves the radius).

    Returns True iff the watchdog fired (caller must early-return).
    """
    if _ap._state.warp_wormhole_arrived_at == 0.0:
        _ap._state.warp_wormhole_arrived_at = now
        return False
    pin_s = now - _ap._state.warp_wormhole_arrived_at
    if pin_s < _ap.WARP_TO_WORMHOLE_PIN_TIMEOUT_S:
        return False
    _ap._telemetry_log(
        "warp_to_wormhole_pin_timeout",
        reason="arrival",
        pin_s=round(pin_s, 2),
        wormhole_x=tx, wormhole_y=ty,
        dist=round(nearest_d, 1),
        **_ap._telemetry_snapshot_fields(state, p))
    _ap._state.warp_after_boss_done = True
    _ap._state.warp_wormhole_arrived_at = 0.0
    return True


def _wormhole_progress_watchdog(state: dict, p: dict, now: float,
                                tx: float, ty: float,
                                nearest_d: float) -> bool:
    """No-progress backstop (PR #164, follow-up to #163).  Captured
    pathology: bot pinned at (582, 1347) for 18 s in WARP_TO_WORMHOLE
    -- boundary repulsion at the west world edge prevented getting
    within ``stop_radius`` of a south-edge wormhole, so the arrival
    timer never armed.

    Tracks best (min) nearest_d this arc; if it hasn't dropped by
    ``PROGRESS_THRESHOLD_PX`` over ``NO_PROGRESS_TIMEOUT_S``,
    abandon.  ``_on_enter`` resets the trackers on a fresh
    WARP_TO_WORMHOLE arc.  Also zeroes the arrival timer because
    leaving the stop-radius invalidates any in-flight arrival count.

    Returns True iff the watchdog fired (caller must early-return).
    """
    _ap._state.warp_wormhole_arrived_at = 0.0
    if _ap._state.warp_wormhole_progress_at == 0.0:
        _ap._state.warp_wormhole_best_d = nearest_d
        _ap._state.warp_wormhole_progress_at = now
        return False
    progress_made = nearest_d <= (
        _ap._state.warp_wormhole_best_d
        - _ap.WARP_TO_WORMHOLE_PROGRESS_THRESHOLD_PX)
    if progress_made:
        _ap._state.warp_wormhole_best_d = nearest_d
        _ap._state.warp_wormhole_progress_at = now
        return False
    pin_s = now - _ap._state.warp_wormhole_progress_at
    if pin_s < _ap.WARP_TO_WORMHOLE_NO_PROGRESS_TIMEOUT_S:
        return False
    _ap._telemetry_log(
        "warp_to_wormhole_pin_timeout",
        reason="no_progress",
        pin_s=round(pin_s, 2),
        wormhole_x=tx, wormhole_y=ty,
        dist=round(nearest_d, 1),
        best_d=round(_ap._state.warp_wormhole_best_d, 1),
        **_ap._telemetry_snapshot_fields(state, p))
    _ap._state.warp_after_boss_done = True
    _ap._state.warp_wormhole_best_d = 0.0
    _ap._state.warp_wormhole_progress_at = 0.0
    return True


def _act_warp_to_wormhole(state: dict, p: dict) -> None:
    """WARP_TO_WORMHOLE: navigate to the nearest visible wormhole
    so the game's collision check (player within 100 px of a
    wormhole centre auto-warps) fires.  Per spec, the bot doesn't
    pre-pick a destination -- whichever wormhole is closest wins.

    Weapons cold during transit -- no use spending shots on
    asteroids/aliens en route, this is a one-shot navigation
    task.  Gas-area repulsion (added 2026-05-15) doesn't apply
    in the MAIN zone where wormholes live (no gas there), but
    the steered_heading layer already integrates it for any
    transit done inside the gas warp zone afterward.

    Two watchdogs run in parallel to abandon stuck attempts:
    ``_wormhole_arrival_watchdog`` (in-radius pin) and
    ``_wormhole_progress_watchdog`` (en-route no-progress); either
    one firing latches ``warp_after_boss_done`` and the FSM cascade
    falls through to productive work.  If conditions change later
    (different wormhole, different path) the existing relatch
    observer (``_observe_warp_back_to_main``) re-arms the warp.

    If no wormholes are visible (already in a warp zone, or the
    state list is empty), latch ``warp_after_boss_done`` so the
    FSM falls through to the regular cascade instead of looping.
    """
    whs = state.get("wormholes") or []
    if not whs:
        # Already in a warp zone, or the wormhole list isn't
        # exposed by /state (older API).  Either way the transit
        # task is effectively done; latch so the FSM moves on.
        _ap._state.warp_after_boss_done = True
        _ap._telemetry_log(
            "warp_after_boss_no_wormholes_visible",
            **_ap._telemetry_snapshot_fields(state, p))
        return
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    nearest = None
    nearest_d = float("inf")
    for wh in whs:
        wx = float(wh.get("x", 0.0))
        wy = float(wh.get("y", 0.0))
        d = math.hypot(wx - px, wy - py)
        if d < nearest_d:
            nearest_d = d
            nearest = wh
    if nearest is None:
        _ap._state.warp_after_boss_done = True
        return
    tx = float(nearest.get("x", 0.0))
    ty = float(nearest.get("y", 0.0))
    stop_radius = _ap.WARP_TO_WORMHOLE_STOP_RADIUS_PX
    now = _ap._get_now()
    if nearest_d <= stop_radius:
        if _wormhole_arrival_watchdog(
                state, p, now, tx, ty, nearest_d):
            return
    else:
        if _wormhole_progress_watchdog(
                state, p, now, tx, ty, nearest_d):
            return
    _ap.KeyState.hold("space", False)
    # Stop radius sits well inside the 100 px collision window --
    # once we're within it the game will trigger the transition on
    # the next physics tick (when it does).  The watchdogs above
    # back it out if no transition happens within their timeouts.
    _ap._do_goto(state, p, tx, ty, stop_radius=stop_radius)


def _act_warp_traverse(state: dict, p: dict) -> None:
    """WARP_TRAVERSE: drive from the bot's entry position (bottom
    of the warp zone after a post-boss warp) to the top edge of
    the map.  The game auto-transitions to the next zone when the
    player crosses ``world_height - EXIT_THRESHOLD (50)``, so the
    bot's target sits ``WARP_TRAVERSE_MARGIN_PX`` (10) from the
    top edge -- inside the exit band -- and the per-tick latch
    fires when the bot is within ``WARP_TRAVERSE_ARRIVAL_PX`` of
    the target so the zone-change happens within braking distance.

    North-edge boundary repulsion is suppressed in warp zones
    (see bot_autopilot_navigation.boundary_repulsion) so the
    field doesn't fight the final approach.  Gas / building /
    wormhole repulsion still apply, so the long-haul navigation
    steers around obstacles automatically.

    Defensive states (REGEN, ENGAGE on close threats) preempt
    via the priority cascade, so this handler only owns the
    long-haul drive.  Cold weapons here -- combat assist still
    fires reflexively when an alien wanders into laser range
    during the transit.
    """
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 3200) or 3200)
    world_h = float(zone.get("world_h", 6400) or 6400)
    py_now = float(p.get("y", 0.0))
    target_y = world_h - _ap.WARP_TRAVERSE_MARGIN_PX

    # Lateral-detour tracker (2026-05-17): every tick of warp_traverse
    # records the bot's best y for the current arc.  If max_y fails
    # to advance for WARP_TRAVERSE_DETOUR_TIMEOUT_S, the action
    # commits a detour SIDE (left or right wall) that persists in
    # state across ticks until the bot's y advances
    # WARP_TRAVERSE_DETOUR_CLEAR_PX past the commit y -- the signal
    # that the obstacle has been bypassed.  Additional timeouts
    # flip sides for wide blockers.
    #
    # Trackers persist across the traverse <-> regen oscillation
    # (intentional -- cumulative no-progress time is exactly what
    # we want to measure) and reset only when the bot's y drops to
    # half of the tracked max, signalling a fresh arc in a new warp
    # zone.
    now = _ap._get_now()
    zone_id = str((state.get("zone") or {}).get("id", ""))
    # New-arc detection: either the first-ever entry (arc_started_at
    # is still 0.0 from a fresh BotState) OR py dropped to less than
    # half of the tracked max (signature of crossing into a new warp
    # zone).  Both reset all per-arc trackers and emit arc-start
    # telemetry so post-hoc analysis can measure time spent per zone
    # (especially WARP_GAS which has accumulated 5+ min stalls in
    # recent captures -- 2026-05-17).
    #
    # First-ever case gated by ``py_now < world_h * 0.5`` to filter
    # out the captured 2026-05-17 stale-state race: when the bot
    # crosses MAIN -> WARP_GAS the state's zone_id flips to the
    # new zone one tick before the position field updates to the
    # new zone's spawn coords.  Without the bottom-half check a
    # bogus arc_started fires with the bot's MAIN-zone position
    # (top of MAIN, py ~6224), then a SECOND legit arc_started
    # fires the next tick at the real spawn (py=200).  The
    # bottom-half check accepts only positions that match a real
    # warp-zone entry.
    is_first_ever_at_spawn = (
        _ap._state.warp_traverse_arc_started_at == 0.0
        and py_now < world_h * 0.5)
    is_zone_drop = py_now < _ap._state.warp_traverse_max_y * 0.5
    is_new_arc = is_first_ever_at_spawn or is_zone_drop
    if is_new_arc:
        _ap._state.warp_traverse_max_y = py_now
        _ap._state.warp_traverse_progress_at = now
        _ap._state.warp_traverse_progress_committed_y = py_now
        _ap._state.warp_traverse_detour_count = 0
        _ap._state.warp_traverse_detour_side = 0
        _ap._state.warp_traverse_detour_commit_y = 0.0
        _ap._state.warp_traverse_arc_started_at = now
        _ap._telemetry_log(
            "warp_traverse_arc_started",
            zone_id=zone_id,
            arc_start_y=round(py_now, 1),
            **_ap._telemetry_snapshot_fields(state, p))
    elif py_now > _ap._state.warp_traverse_max_y:
        _ap._state.warp_traverse_max_y = py_now
        # Meaningful-progress gate (2026-05-17 follow-up to PR #134):
        # only reset the no-progress timer when py has advanced
        # WARP_TRAVERSE_MEANINGFUL_PROGRESS_PX past the last committed
        # y.  Without this gate a bot inching forward 3-50 px per
        # traverse cycle keeps deferring the detour indefinitely.
        if (py_now >= _ap._state.warp_traverse_progress_committed_y
                + _ap.WARP_TRAVERSE_MEANINGFUL_PROGRESS_PX):
            _ap._state.warp_traverse_progress_at = now
            _ap._state.warp_traverse_progress_committed_y = py_now
        # If a detour was active AND we've cleared the obstacle by
        # WARP_TRAVERSE_DETOUR_CLEAR_PX past the commit anchor,
        # expire the side so the bot resumes centre target for the
        # remainder of the arc.
        if (_ap._state.warp_traverse_detour_side != 0
                and py_now >= (_ap._state.warp_traverse_detour_commit_y
                               + _ap.WARP_TRAVERSE_DETOUR_CLEAR_PX)):
            _ap._state.warp_traverse_detour_side = 0
    elif _ap._state.warp_traverse_progress_at == 0.0:
        # First tick after entry; seed the timer + committed-y.
        _ap._state.warp_traverse_progress_at = now
        _ap._state.warp_traverse_progress_committed_y = py_now
    no_progress_s = now - _ap._state.warp_traverse_progress_at
    if no_progress_s >= _ap.WARP_TRAVERSE_DETOUR_TIMEOUT_S:
        # Detour commit: bump the counter, anchor the y position so
        # the clear check has a reference, reset the timer + the
        # progress-committed y so the NEXT timeout fires another
        # (flipped) detour, and flip the side.  If side was already
        # non-zero (a previous detour didn't help), flip to the
        # opposite wall; otherwise start with left.
        _ap._state.warp_traverse_detour_count += 1
        _ap._state.warp_traverse_progress_at = now
        _ap._state.warp_traverse_progress_committed_y = py_now
        _ap._state.warp_traverse_detour_commit_y = py_now
        if _ap._state.warp_traverse_detour_side <= 0:
            _ap._state.warp_traverse_detour_side = 1   # left wall
        else:
            _ap._state.warp_traverse_detour_side = -1  # right wall
        _ap._telemetry_log(
            "warp_traverse_detour_committed",
            zone_id=zone_id,
            detour_count=_ap._state.warp_traverse_detour_count,
            detour_side=("left"
                         if _ap._state.warp_traverse_detour_side > 0
                         else "right"),
            commit_y=round(py_now, 1),
            **_ap._telemetry_snapshot_fields(state, p))
    # Pick the target_x from the persistent side (NOT recomputed
    # from no_progress_s each tick -- that was the PR #133
    # single-tick bug).  Once a side is committed it stays through
    # the regen <-> traverse oscillation until cleared.
    if _ap._state.warp_traverse_detour_side > 0:
        target_x = _ap.WARP_TRAVERSE_MARGIN_PX
    elif _ap._state.warp_traverse_detour_side < 0:
        target_x = world_w - _ap.WARP_TRAVERSE_MARGIN_PX
    else:
        target_x = world_w / 2.0
    if py_now >= target_y - _ap.WARP_TRAVERSE_ARRIVAL_PX:
        if not _ap._state.warp_traverse_done:
            _ap._state.warp_traverse_done = True
            arc_duration_s = (
                now - _ap._state.warp_traverse_arc_started_at
                if _ap._state.warp_traverse_arc_started_at > 0.0
                else None)
            _ap._telemetry_log(
                "warp_traverse_complete",
                arrived_y=round(py_now, 1),
                target_y=round(target_y, 1),
                **_ap._telemetry_snapshot_fields(state, p))
            # Performance metric event (2026-05-17): emit a separate
            # arc-completed event alongside warp_traverse_complete so
            # post-hoc analysis can compute duration + detour count
            # per zone (especially WARP_GAS where multi-minute stalls
            # have been captured).  arc_duration_s is None when the
            # arc was already in progress before this code shipped
            # (no recorded start).
            _ap._telemetry_log(
                "warp_traverse_arc_completed",
                zone_id=zone_id,
                outcome="arrived",
                arc_duration_s=(round(arc_duration_s, 1)
                                if arc_duration_s is not None
                                else None),
                arrived_y=round(py_now, 1),
                max_y=round(_ap._state.warp_traverse_max_y, 1),
                detour_count=_ap._state.warp_traverse_detour_count,
                **_ap._telemetry_snapshot_fields(state, p))
            # Mark the arc consumed so the new lifecycle observer
            # (``_observe_warp_traverse_arc_complete``) doesn't
            # double-fire arc_completed on the inevitable FSM exit
            # from S_WARP_TRAVERSE that follows the zone transition.
            _ap._state.warp_traverse_arc_started_at = 0.0
        # Don't brake -- inertia from the drive carries the bot
        # across the EXIT_THRESHOLD (50 px from edge) and the game
        # auto-transitions zones.  Keep holding the same goto so
        # the bot doesn't drift sideways into the lethal side
        # walls while it waits for the transition.
        _ap.KeyState.hold("space", False)
        _ap._do_goto(state, p, target_x, target_y, stop_radius=30.0)
        return
    _ap.KeyState.hold("space", False)
    _ap._do_goto(state, p, target_x, target_y, stop_radius=30.0)


def _maybe_use_consumables(state: dict, p: dict) -> None:
    """Per-tick auto-heal hook: fire repair pack / shield recharge
    based on HP / shield thresholds.  Runs every ``_do_auto`` tick
    before the FSM dispatch so the response is independent of which
    state the bot is in.

    Each consumable is governed by a heal-active latch:

      * Latch ARMS when current value crosses below
        ``CONSUMABLE_USE_*_PCT`` of max.
      * Latch DISARMS when current value crosses above
        ``CONSUMABLE_DISARM_*_PCT`` of max (~ 70 %).
      * While the latch is armed, the auto-use loop fires on every
        tick (subject to ``CONSUMABLE_USE_COOLDOWN_S``) until either
        the disarm band is reached or the matching consumable runs out.

    Without the latch a single 50 %-heal use only refills the deficit
    that tripped the threshold — if HP dropped to 30 % between ticks,
    one use lands at 80 %, the next tick reads ``80/100 > 0.5`` and
    no further use fires until the bar drops below 50 % again.  The
    latch closes that gap.

    Disarm band (2026-05-19): originally the latch disarmed only at
    100 %, which led the auto-use loop to fire 2-3 consumables per
    arm cycle -- the next-tick check after a 50 %-heal use saw the
    bar still <100 % and fired again on the next cooldown boundary,
    even though the bar was already past 70 %.  Captured pathology:
    32 heal_shield_fire events from 16 arms (and 44 hp_fire / 22 hp
    arms) in a single session, i.e. ~2x charges per drop.  Disarming
    at 70 % keeps the spend at one charge per drop event while
    leaving sustained-damage scenarios (damage outpacing the heal)
    handled correctly via natural re-arming when the bar dips back
    below the arm threshold.

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
    if _ap._state.heal_hp_active and hp_frac >= _ap.CONSUMABLE_DISARM_HP_PCT:
        _ap._state.heal_hp_active = False
        _ap._telemetry_log("heal_hp_disarm",
                       hp=hp, max_hp=max_hp)
    if not _ap._state.heal_shield_active and sh_frac <= _ap.CONSUMABLE_USE_SHIELD_PCT:
        _ap._state.heal_shield_active = True
        _ap._telemetry_log("heal_shield_arm",
                       shields=sh, max_shields=max_sh,
                       sh_frac=round(sh_frac, 3))
    if _ap._state.heal_shield_active and sh_frac >= _ap.CONSUMABLE_DISARM_SHIELD_PCT:
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
