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

_WEAPON_NAME_ORDER = ("Basic Laser", "Mining Beam", "Melee")


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

    threat, d = _find_nearest_threat(gv)
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
    }
