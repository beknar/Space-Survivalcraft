"""In-process auto-aim + auto-fire defence layer.

Active **only** when ``COO_BOT_API`` is set (gates installation
on game startup).  Hooks ``update_logic.update_weapons`` so that
every frame:

  1. Finds the nearest hostile within ``DETECT_RANGE`` (small
     aliens + bosses).  Bosses count as hostile only when alive.
  2. If the threat is within fire range, snaps
     ``gv.player.heading`` directly to face it (no rotation
     limit -- this is "assist" behaviour, the autopilot still
     drives thrust + sideslip + ability use).
  3. Auto-selects the right weapon: Energy Blade if the threat
     is < ``MELEE_RANGE``, otherwise Basic Laser.
  4. Forces ``fire=True`` for the underlying ``update_weapons``
     call so the projectile / swing fires this frame regardless
     of the player's keyboard input.

The assist intentionally does NOT touch movement, ability
modules, or the inventory -- only heading + active weapon +
fire trigger.  That leaves the strategist (Claude) and the
autopilot in charge of where the ship goes; the assist just
guarantees that anything close enough to be hurting the
player gets shot back.

API:
  * Toggleable at runtime via ``POST /assist {"enabled": false}``
    (see ``bot_api`` patches below).
  * State exposed under ``state.assist`` for read-only inspection.

Limitations:
  * No lead/predict aim -- snaps to the target's instantaneous
    position.  Basic Laser is fast enough that this lands.
  * Can't see projectile threats directly (alien lasers
    in flight); approximated by "nearest alien who has a gun
    pointed at you".
  * No friendly-fire concern (player projectiles can damage
    asteroids the player is mining).  Works as intended for
    now -- the autopilot picks weapon based on intent, the
    assist only triggers when there's a hostile in range,
    overriding any mining-only stance.
"""
from __future__ import annotations

import math
import os
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from game_view import GameView


# ── Tuning ────────────────────────────────────────────────────────────────

DETECT_RANGE: float = 800.0       # px -- look for hostiles inside this
LASER_RANGE: float = 1100.0       # px -- Basic Laser engagement range
MELEE_RANGE: float = 100.0        # px -- swap to Energy Blade
SHIELD_REGEN_GRACE_S: float = 1.0
# Don't keep firing forever after the threat leaves -- give the
# assist a small "cease fire" cooldown so the player's weapon
# choice + intent reasserts after combat.
ASSIST_HOLDOVER_S: float = 0.4

# On the first tick of a fresh engagement (no threat -> threat),
# roll the dice: with this probability the assist commits to the
# Energy Blade for the duration of this engagement and forces the
# weapon every frame regardless of range.  This is the
# game-process side of the autopilot's melee-rush behaviour --
# the autopilot owns movement (closes to swing range), the
# assist owns the weapon lock (so the ranged auto-switch can't
# fight it).  Cleared once the threat has been gone for
# ``MELEE_LOCK_HOLDOVER_S``.
MELEE_COMMIT_CHANCE: float = 0.5
MELEE_LOCK_HOLDOVER_S: float = 0.6

# Indirection so tests can monkey-patch a deterministic RNG.
_get_random = random.random

# Nebula-tier module-usage thresholds (2026-05-24).  When a module
# is installed in the player's loadout, the assist fires it on a
# matching trigger -- gas escape via misty_step, defensive force_wall
# when shields fall under pressure with a threat behind us, and
# death_blossom on close-range alien clusters.  All gated on the
# module's own cooldown + ability/missile budget; the assist only
# DECIDES to fire, the game-side handlers enforce game rules.
MISTY_STEP_GAS_MARGIN_PX: float = 30.0   # treat as "inside" cloud
                                          # past edge + this margin
FORCE_WALL_SHIELDS_PCT: float = 0.45     # arm threshold
DEATH_BLOSSOM_CLUSTER_MIN: int = 4       # aliens to consider a swarm
DEATH_BLOSSOM_CLUSTER_RANGE_PX: float = 350.0   # close-range only
# Drone dispatch (2026-06-02).  The bot crafts + equips combat / mining
# drones but never deployed them (the in-game "R" key was player-only),
# so they were a crafting dead-end.  Mining drone deploys freely while
# the mining weapon is active; the combat drone only when a cluster of
# aliens is near (don't spend the single drone charge on a lone kiter).
DRONE_DEPLOY_CLUSTER_MIN: int = 3        # aliens to justify a combat drone
DRONE_DEPLOY_RANGE_PX: float = 900.0     # threat range for the cluster test

_state: dict[str, Any] = {
    "enabled": True,
    "fired_this_tick": False,
    "last_threat_dist": -1.0,
    "last_threat_type": "",
    "last_aim_heading": 0.0,
    "engagements": 0,
    "_holdover_until": 0.0,
    # Melee commitment.  ``melee_engaged`` is what callers (the
    # autopilot, /state) read; the underscored fields are internal
    # bookkeeping so the dice only re-roll on a fresh engagement.
    "melee_engaged": False,
    "_had_threat_last_tick": False,
    "_melee_engaged_until": 0.0,
    # Module-usage telemetry (read by /state.assist).
    "misty_step_fires": 0,
    "force_wall_fires": 0,
    "death_blossom_fires": 0,
    "drone_deploys": 0,
}


# ── Geometry ──────────────────────────────────────────────────────────────

def _heading_to(player, target) -> float:
    """Heading degrees (0=N, CW positive) from player to target."""
    dx = float(target.center_x) - float(player.center_x)
    dy = float(target.center_y) - float(player.center_y)
    return math.degrees(math.atan2(dx, dy))


def _dist(player, target) -> float:
    dx = float(target.center_x) - float(player.center_x)
    dy = float(target.center_y) - float(player.center_y)
    return math.hypot(dx, dy)


# ── Threat selection ──────────────────────────────────────────────────────

def _find_nearest_threat(gv) -> tuple[Any | None, float]:
    """Return ``(threat_sprite, distance)`` for the nearest live
    hostile within DETECT_RANGE, or ``(None, inf)`` if none.

    Walks ``gv.alien_list`` (current zone) plus the boss / nebula
    boss when alive.  Skips dead sprites (hp <= 0)."""
    p = gv.player
    best: tuple[Any | None, float] = (None, float("inf"))

    aliens = getattr(gv, "alien_list", None) or ()
    for a in aliens:
        try:
            if getattr(a, "hp", 0) <= 0:
                continue
            d = _dist(p, a)
            if d < best[1]:
                best = (a, d)
        except Exception:
            continue

    for boss_attr in ("_boss", "_nebula_boss"):
        b = getattr(gv, boss_attr, None)
        if b is None:
            continue
        try:
            if getattr(b, "hp", 0) <= 0:
                continue
            d = _dist(p, b)
            if d < best[1]:
                best = (b, d)
        except Exception:
            continue

    if best[0] is not None and best[1] > DETECT_RANGE:
        return (None, float("inf"))
    return best


# ── Weapon switching ──────────────────────────────────────────────────────

_WEAPON_NAME_ORDER = (
    "Basic Laser", "Mining Beam", "Melee", "Energy Pickaxe")


def _ensure_weapon(gv, want: str) -> bool:
    """Set ``gv._weapon_idx`` so the active weapon's name == want.
    Returns True when a switch happened."""
    try:
        cur = gv._active_weapon.name
    except Exception:
        return False
    if cur == want:
        return False
    gun_count = max(1, getattr(gv.player, "guns", 1))
    weapons = gv._weapons
    # Each weapon group is gun_count entries; find the first entry
    # of the wanted group.
    for i in range(0, len(weapons), gun_count):
        if i < len(weapons) and weapons[i].name == want:
            gv._weapon_idx = i
            return True
    return False


# ── Nebula-tier module use ────────────────────────────────────────────────


def _player_inside_gas_cloud(gv) -> tuple[float, float, float] | None:
    """Return ``(cx, cy, radius)`` for any gas cloud the player is
    currently inside (within ``radius + MISTY_STEP_GAS_MARGIN_PX``),
    or ``None``.  Source is the active zone's ``_clouds`` SpriteList
    -- only set on the gas warp zone + Nebula / Star-Maze variants.
    """
    z = getattr(gv, "_zone", None)
    if z is None:
        return None
    clouds = getattr(z, "_clouds", None)
    if not clouds:
        return None
    p = gv.player
    px = float(p.center_x)
    py = float(p.center_y)
    for c in clouds:
        try:
            cx = float(c.center_x)
            cy = float(c.center_y)
            r = float(getattr(c, "radius", 80.0))
            d = math.hypot(px - cx, py - cy)
            if d < r + MISTY_STEP_GAS_MARGIN_PX:
                return (cx, cy, r)
        except Exception:
            continue
    return None


def _misty_step_escape_key(gv, cloud) -> int | None:
    """Choose which WASD key best aligns with the escape ray
    (cloud-centre -> player, normalised) given the player's current
    heading.  ``misty_step`` interprets W/S as forward/back and A/D
    as strafe-left/right, so we project the escape ray onto each
    axis and pick the one with the largest positive component.
    """
    import arcade
    cx, cy, _r = cloud
    p = gv.player
    dx = float(p.center_x) - cx
    dy = float(p.center_y) - cy
    d = math.hypot(dx, dy)
    if d < 1.0:
        # On top of cloud centre -- pick an arbitrary forward escape.
        return arcade.key.W
    ux, uy = dx / d, dy / d
    # Player forward vector in world coords (matches misty_step body).
    rad = math.radians(p.heading)
    fwd_x, fwd_y = math.sin(rad), math.cos(rad)
    right_x, right_y = math.cos(rad), -math.sin(rad)
    fwd_dot = ux * fwd_x + uy * fwd_y
    right_dot = ux * right_x + uy * right_y
    if abs(fwd_dot) >= abs(right_dot):
        return arcade.key.W if fwd_dot > 0 else arcade.key.S
    return arcade.key.D if right_dot > 0 else arcade.key.A


def _maybe_fire_misty_step_gas(gv) -> bool:
    """Trigger the misty-step teleport when the player is sitting
    inside a damaging gas cloud.  Returns True if fired.

    Captured pathology (PR #185 telemetry): even with the Nebula
    recovery gate + elevated REGEN thresholds + fortify ring,
    deaths persist when the bot fights inside a gas cloud --
    drain rate exceeds shield regen.  misty_step out of the cloud
    cuts the encounter short.
    """
    if "misty_step" not in gv._module_slots:
        return False
    cloud = _player_inside_gas_cloud(gv)
    if cloud is None:
        return False
    key = _misty_step_escape_key(gv, cloud)
    if key is None:
        return False
    from input_handlers_keys import fire_misty_step
    if fire_misty_step(gv, key):
        _state["misty_step_fires"] += 1
        return True
    return False


def _threat_behind_player(gv, threat) -> bool:
    """Return True iff ``threat``'s bearing from the player is in
    the back hemisphere (angle from forward > 90 degrees).  Used
    to choose force_wall (which deploys 60 px BEHIND the ship)."""
    if threat is None:
        return False
    p = gv.player
    dx = float(threat.center_x) - float(p.center_x)
    dy = float(threat.center_y) - float(p.center_y)
    d = math.hypot(dx, dy)
    if d < 1.0:
        return False
    ux, uy = dx / d, dy / d
    rad = math.radians(p.heading)
    fwd_x, fwd_y = math.sin(rad), math.cos(rad)
    return (ux * fwd_x + uy * fwd_y) < 0.0


def _maybe_fire_force_wall(gv, threat, threat_dist) -> bool:
    """Deploy the force wall when shields drop under
    ``FORCE_WALL_SHIELDS_PCT`` AND a threat is currently behind
    the ship (the wall plants 60 px behind the bow, so it only
    helps against rear pursuers / projectile streams).  Returns
    True if fired.
    """
    if "force_wall" not in gv._module_slots:
        return False
    if threat is None or threat_dist > DETECT_RANGE:
        return False
    sh = int(getattr(gv.player, "shields", 0))
    sh_max = max(1, int(getattr(gv.player, "max_shields", 1)))
    if (sh / sh_max) >= FORCE_WALL_SHIELDS_PCT:
        return False
    if not _threat_behind_player(gv, threat):
        return False
    # All gates passed.  Delegate to the game-side handler -- it
    # will re-check cooldown + ability budget and may no-op silently.
    from input_handlers_keys import _try_force_wall
    cd_before = getattr(gv, "_force_wall_cd", 0.0)
    _try_force_wall(gv)
    cd_after = getattr(gv, "_force_wall_cd", 0.0)
    if cd_after > cd_before:
        _state["force_wall_fires"] += 1
        return True
    return False


def _maybe_fire_death_blossom(gv) -> bool:
    """Trigger Death Blossom when at least
    ``DEATH_BLOSSOM_CLUSTER_MIN`` live aliens are inside
    ``DEATH_BLOSSOM_CLUSTER_RANGE_PX``.  The handler validates
    missile availability + activation latch internally; this
    function only decides "is the swarm dense enough to justify
    burning all our missiles?"
    """
    if "death_blossom" not in gv._module_slots:
        return False
    if getattr(gv, "_death_blossom_active", False):
        return False
    if gv.inventory.count_item("missile") <= 0:
        return False
    p = gv.player
    px = float(p.center_x)
    py = float(p.center_y)
    r2 = DEATH_BLOSSOM_CLUSTER_RANGE_PX * DEATH_BLOSSOM_CLUSTER_RANGE_PX
    close = 0
    for a in (getattr(gv, "alien_list", None) or ()):
        try:
            if getattr(a, "hp", 0) <= 0:
                continue
            dx = float(a.center_x) - px
            dy = float(a.center_y) - py
            if dx * dx + dy * dy <= r2:
                close += 1
                if close >= DEATH_BLOSSOM_CLUSTER_MIN:
                    break
        except Exception:
            continue
    if close < DEATH_BLOSSOM_CLUSTER_MIN:
        return False
    from input_handlers_keys import _try_death_blossom
    _try_death_blossom(gv)
    if getattr(gv, "_death_blossom_active", False):
        _state["death_blossom_fires"] += 1
        return True
    return False


def _maybe_deploy_drone(gv) -> bool:
    """Deploy a companion drone when one would help and none is out.

    The drone variant follows the active weapon -- exactly how
    ``combat_helpers.deploy_drone`` decides: a mining weapon
    (``mines_rock``) deploys a MiningDrone, anything else a CombatDrone.
    Since the bot runs the mining weapon while in S_MINE and a laser in
    combat, that coupling lands the right drone for the situation for
    free.

    The engine caps active drones at one (``gv._active_drone``), so we
    only deploy when there is no drone out -- otherwise ``deploy_drone``
    would no-op (and flash a message) on a same-variant press, or swap
    (refund + reconsume) on a different-variant press mid-combat.

      * Mining drone -- deploy whenever the mining weapon is active and
        one is in ship inventory (it speeds up mining; no threat gate).
      * Combat drone -- deploy only when at least
        ``DRONE_DEPLOY_CLUSTER_MIN`` live aliens are within
        ``DRONE_DEPLOY_RANGE_PX`` (don't spend the single charge on a
        lone kiter).

    Drone items reach ship inventory via
    ``bot_builder.equip_consumables_to_quick_use`` (slots 3/4), which
    ``deploy_drone`` consumes from.
    """
    if getattr(gv, "_active_drone", None) is not None:
        return False
    weapon = getattr(gv, "_active_weapon", None)
    is_mining = bool(getattr(weapon, "mines_rock", False))
    item_key = "mining_drone" if is_mining else "combat_drone"
    try:
        if gv.inventory.count_item(item_key) <= 0:
            return False
    except Exception:
        return False
    if not is_mining:
        p = gv.player
        px = float(p.center_x)
        py = float(p.center_y)
        r2 = DRONE_DEPLOY_RANGE_PX * DRONE_DEPLOY_RANGE_PX
        close = 0
        for a in (getattr(gv, "alien_list", None) or ()):
            try:
                if getattr(a, "hp", 0) <= 0:
                    continue
                dx = float(a.center_x) - px
                dy = float(a.center_y) - py
                if dx * dx + dy * dy <= r2:
                    close += 1
                    if close >= DRONE_DEPLOY_CLUSTER_MIN:
                        break
            except Exception:
                continue
        if close < DRONE_DEPLOY_CLUSTER_MIN:
            return False
    from combat_helpers import deploy_drone
    deploy_drone(gv)
    if getattr(gv, "_active_drone", None) is not None:
        _state["drone_deploys"] += 1
        return True
    return False


# ── Per-frame tick ────────────────────────────────────────────────────────

def tick(gv, dt: float, original_fire: bool) -> bool:
    """Run the assist for one frame.  Returns the (possibly
    overridden) fire flag for ``update_weapons``.  Heading +
    active weapon are adjusted as a side effect on ``gv``.
    """
    _state["fired_this_tick"] = False
    if not _state["enabled"]:
        return original_fire

    # Don't interfere while a menu is open -- can't rotate / fire
    # in a menu anyway, and we don't want to rip control away
    # from the player while they're configuring.
    if any((
        getattr(gv, "_build_menu_open", False),
        getattr(getattr(gv, "inventory", None), "_open", False),
        getattr(gv, "_escape_menu_open", False),
        getattr(gv, "_player_dead", False),
        getattr(gv, "_dialogue_open", False),
    )):
        return original_fire

    # Nebula-tier module use (2026-05-24).  Order matters: gas
    # escape first because gas damage compounds before combat
    # decisions can land; force_wall + death_blossom both layer
    # onto the existing aim/fire logic below and don't preempt it.
    try:
        _maybe_fire_misty_step_gas(gv)
    except Exception as e:
        print(f"[combat_assist] misty_step error: {e}")

    threat, d = _find_nearest_threat(gv)
    try:
        _maybe_fire_force_wall(gv, threat, d)
    except Exception as e:
        print(f"[combat_assist] force_wall error: {e}")
    try:
        _maybe_fire_death_blossom(gv)
    except Exception as e:
        print(f"[combat_assist] death_blossom error: {e}")
    try:
        _maybe_deploy_drone(gv)
    except Exception as e:
        print(f"[combat_assist] drone deploy error: {e}")

    now = _now(gv)
    if threat is None:
        # No threat this tick.  Drop the melee commitment once the
        # grace timer has elapsed (so a brief target-loss + reacquire
        # doesn't reroll the dice mid-fight).
        _state["_had_threat_last_tick"] = False
        if (_state["melee_engaged"]
                and now >= _state["_melee_engaged_until"]):
            _state["melee_engaged"] = False
        # Retain assist briefly after target loss so we don't strobe
        # between assist and player control on frame-by-frame loss.
        if now < _state["_holdover_until"]:
            return True
        return original_fire

    # Fresh-engagement detection: roll the melee-commit dice on the
    # tick that transitions no-threat -> threat.  Once committed, the
    # flag persists for the entire engagement (and re-arms the grace
    # timer below so a momentary line-of-sight loss doesn't drop it).
    fresh = not _state["_had_threat_last_tick"]
    _state["_had_threat_last_tick"] = True
    if fresh and not _state["melee_engaged"]:
        if _get_random() < MELEE_COMMIT_CHANCE:
            _state["melee_engaged"] = True
    if _state["melee_engaged"]:
        _state["_melee_engaged_until"] = now + MELEE_LOCK_HOLDOVER_S

    # Aim: snap heading directly.  Player rotation rate would slow
    # the ship's natural turn, but for assist we want immediate
    # response since the threat is firing on us NOW.
    heading = _heading_to(gv.player, threat)
    gv.player.heading = heading
    _state["last_aim_heading"] = heading

    # Weapon choice:
    #   * Melee-committed: force Energy Blade every frame, swing
    #     even out of arc (the autopilot is closing the distance;
    #     the swing animation just whiffs until we're in range).
    #   * Otherwise: range-based -- Energy Blade at point-blank,
    #     Basic Laser inside laser range, hands off past it.
    if _state["melee_engaged"]:
        _ensure_weapon(gv, "Melee")
        _state["fired_this_tick"] = True
        _state["last_threat_dist"] = d
        _state["last_threat_type"] = type(threat).__name__
        _state["engagements"] += 1
        _state["_holdover_until"] = now + ASSIST_HOLDOVER_S
        return True
    want = "Melee" if d < MELEE_RANGE else "Basic Laser"
    if d < LASER_RANGE or d < MELEE_RANGE:
        _ensure_weapon(gv, want)
        _state["fired_this_tick"] = True
        _state["last_threat_dist"] = d
        _state["last_threat_type"] = type(threat).__name__
        _state["engagements"] += 1
        _state["_holdover_until"] = now + ASSIST_HOLDOVER_S
        return True
    # In DETECT but out of LASER -- still aim, but don't waste shots.
    return original_fire


def _now(gv) -> float:
    """Monotonic-ish time using gv.uptime if exposed, else
    ``time.monotonic()``."""
    import time
    return time.monotonic()


# ── Hook installation ─────────────────────────────────────────────────────

_installed: bool = False


def install(gv) -> None:
    """Monkey-patch ``update_logic.update_weapons`` so the assist
    runs every frame.  Idempotent.  Gated on ``COO_BOT_API`` --
    callers should still wrap the call in an env check, but the
    function refuses to install twice."""
    global _installed
    if _installed:
        return
    if os.environ.get("COO_BOT_API", "").strip() in ("", "0", "false"):
        return
    import update_logic
    _orig_update_weapons = update_logic.update_weapons

    def _patched_update_weapons(_gv, _dt, _fire):
        try:
            _fire = tick(_gv, _dt, _fire)
        except Exception as e:
            print(f"[combat_assist] tick error: {e}")
        return _orig_update_weapons(_gv, _dt, _fire)

    update_logic.update_weapons = _patched_update_weapons
    _installed = True
    print("[combat_assist] installed (DETECT=%dpx, LASER=%dpx, MELEE=%dpx)" % (
        DETECT_RANGE, LASER_RANGE, MELEE_RANGE))


def set_enabled(enabled: bool) -> dict:
    _state["enabled"] = bool(enabled)
    return get_state()


def get_state() -> dict:
    return {
        "enabled": _state["enabled"],
        "installed": _installed,
        "fired_this_tick": _state["fired_this_tick"],
        "last_threat_dist": _state["last_threat_dist"],
        "last_threat_type": _state["last_threat_type"],
        "last_aim_heading": _state["last_aim_heading"],
        "engagements": _state["engagements"],
        "melee_engaged": _state["melee_engaged"],
        "detect_range": DETECT_RANGE,
        "laser_range": LASER_RANGE,
        "melee_range": MELEE_RANGE,
        "misty_step_fires": _state["misty_step_fires"],
        "force_wall_fires": _state["force_wall_fires"],
        "death_blossom_fires": _state["death_blossom_fires"],
        "drone_deploys": _state["drone_deploys"],
    }
