"""Local autopilot — translates high-level intents into keys.

Runs as its own process alongside the game.  Polls
``http://127.0.0.1:8765/state`` at ~10 Hz (cheap JSON, ~1 ms),
reads the current ``intent`` from the same response, and
dispatches keyboard commands to the game window via pyautogui.

Architecture:

    Claude (5-10 s cadence)  --POST /intent--> bot_api.py
                                                   |
    bot_autopilot.py (10 Hz) <-- GET /state-------'
                  |
                  +-- pyautogui keyDown/keyUp --> game window

The autopilot owns:
  * Reflex behaviours (brake on low shields, dodge on incoming
    projectile -- not yet implemented; placeholder hooks).
  * Mechanical execution of intents (rotate to heading, thrust
    while in range, fire weapon).
  * Weapon cycling so the right weapon is selected for the
    current intent (mining beam for mining, basic laser for
    aliens, energy blade if very close).

Claude / strategist owns:
  * What intent to set (mine vs fight vs build vs flee).
  * When to escalate (boss fight, retreat, station rebuild).

Hotkeys (pynput, global):
    Ctrl+Shift+P  pause / resume
    Ctrl+Shift+Q  stop the autopilot

Run:
    python bot_autopilot.py

The game must be running with ``COO_BOT_API=1`` set so the
state endpoint is reachable.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen, Request

# UTF-8 stdout for unicode arrows / em-dashes in log messages.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import pyautogui
    from pynput import keyboard
except ImportError as e:
    print(f"ERROR: missing dependency: {e.name}.  Install with:")
    print("    pip install pyautogui pynput")
    sys.exit(1)

try:
    import pygetwindow as gw
except ImportError:
    gw = None


API_BASE = "http://127.0.0.1:8765"
POLL_HZ = 10.0
FIRE_RANGE_PX = 600.0             # within this -> hold fire
MINING_RANGE_PX = 400.0           # within this -> mining beam
MELEE_RANGE_PX = 100.0            # within this -> energy blade


# ── Hotkeys ───────────────────────────────────────────────────────────────

class State:
    paused: bool = False
    stop: bool = False


def _hotkeys():
    def _toggle_pause():
        State.paused = not State.paused
        print(f"[autopilot] {'PAUSED' if State.paused else 'RESUMED'}")
    def _stop():
        State.stop = True
        print("[autopilot] STOP")
    with keyboard.GlobalHotKeys({
        "<ctrl>+<shift>+p": _toggle_pause,
        "<ctrl>+<shift>+q": _stop,
    }) as h:
        h.join()


# ── HTTP client ───────────────────────────────────────────────────────────

def fetch_state(timeout_s: float = 0.5) -> dict | None:
    try:
        with urlopen(f"{API_BASE}/state", timeout=timeout_s) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError):
        return None
    except Exception as e:
        print(f"[autopilot] fetch_state error: {e}")
        return None


# ── Key dispatch ──────────────────────────────────────────────────────────

class KeyState:
    """Track which keys are currently held down so toggling them
    is idempotent + we don't accidentally stack keyDowns."""
    held: set[str] = set()

    @classmethod
    def hold(cls, key: str, down: bool) -> None:
        if down and key not in cls.held:
            pyautogui.keyDown(key)
            cls.held.add(key)
        elif not down and key in cls.held:
            pyautogui.keyUp(key)
            cls.held.discard(key)

    @classmethod
    def release_all(cls) -> None:
        for key in list(cls.held):
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass
        cls.held.clear()


# ── Geometry ──────────────────────────────────────────────────────────────

def angle_to(dx: float, dy: float) -> float:
    """Heading (degrees, 0=N, CW positive) from origin to (dx, dy).
    Matches arcade's player.heading convention used by the game."""
    return math.degrees(math.atan2(dx, dy))


def heading_delta(current: float, target: float) -> float:
    """Shortest signed angle (current -> target) in [-180, 180]."""
    d = (target - current + 540.0) % 360.0 - 180.0
    return d


def nearest(lst: list[dict], px: float, py: float,
            max_dist: float = 1e9) -> tuple[dict | None, float]:
    """Return (entry, distance) of the nearest sprite in the list."""
    best: tuple[dict | None, float] = (None, max_dist)
    for sp in lst:
        dx = sp["x"] - px
        dy = sp["y"] - py
        d = math.hypot(dx, dy)
        if d < best[1]:
            best = (sp, d)
    return best


# ── Intent execution ──────────────────────────────────────────────────────

def execute_intent(state: dict) -> None:
    """One tick of action.  Reads intent from state and dispatches
    keys.  Idempotent — leaves keys held only as long as the
    intent says they should be."""
    p = state.get("player", {})
    intent = state.get("intent", {"type": "idle"})
    menu = state.get("menu", {})

    # Don't fight a player who's in a menu.
    if any(menu.values()):
        KeyState.release_all()
        return

    itype = intent.get("type", "idle")
    if itype == "idle":
        _do_idle()
    elif itype == "auto":
        _do_auto(state, p)
    elif itype == "goto":
        _do_goto(state, p, intent.get("x", p.get("x", 0)),
                 intent.get("y", p.get("y", 0)),
                 stop_radius=intent.get("radius", 80.0))
    elif itype == "mine_nearest":
        _do_mine_nearest(state, p)
    elif itype == "attack_nearest":
        _do_attack_nearest(state, p)
    elif itype == "engage_boss":
        _do_engage_boss(state, p)
    elif itype == "retreat_to_station":
        _do_retreat(state, p)
    elif itype == "cycle_weapon":
        _do_cycle_weapon(state, intent.get("to"))
    else:
        # Unknown intent — log + idle until something we know arrives.
        print(f"[autopilot] unknown intent: {itype!r}")
        _do_idle()


def _do_idle() -> None:
    KeyState.release_all()


# ── Auto-mode finite state machine ────────────────────────────────────────
#
#  Five states with asymmetric enter/exit thresholds.  ENGAGE is the
#  defensive interrupt and preempts any other state immediately; the
#  other four respect MIN_DWELL_S to prevent boundary thrash.
#
#       ┌─────────┐  alien<800 (any)            ┌────────┐
#       │ ENGAGE  │ <─────────────────────────── │ ANY *  │
#       │ aim+fire│ ───────────────────────────> │        │
#       └─────────┘  no alien<1000               └────────┘
#                                                    │
#       ┌─────────┐  pickup<1500 + safe              │
#       │ GATHER  │ <────────────────────────────────┤
#       │  fly to │ ────────────────────────────>    │
#       │  pickup │  pickup>1700 / consumed          │
#       └─────────┘                                  │
#                                                    │
#       ┌─────────┐  shields < 40 %                  │
#       │  REGEN  │ <────────────────────────────────┤
#       │  idle   │ ────────────────────────────>    │
#       │ for HP  │  shields ≥ 60 %                  │
#       └─────────┘                                  │
#                                                    │
#       ┌─────────┐  asteroids known                 │
#       │  MINE   │ <────────────────────────────────┤
#       │ nearest │ ────────────────────────────>    │
#       │ rock    │  no asteroids visible            │
#       └─────────┘                                  │
#                                                    │
#       ┌─────────┐  no asteroids known              │
#       │ SEARCH  │ <────────────────────────────────┘
#       │ spiral  │
#       └─────────┘
#
#  The hysteresis bands replace three previous sources of flicker:
#    * mine ↔ engage at the 800 px ring
#    * idle ↔ mine at the 50 % shield threshold
#    * spiral state torn down + re-anchored every time a non-spiral
#      state briefly stole a tick
#
#  Combat assist (bot_combat_assist.py) still owns aim + fire while
#  in ENGAGE.  This module owns thrust + weapon selection.

# ── Hysteresis thresholds ─────────────────────────────────────────────────

ENGAGE_ENTER_PX: float = 800.0
ENGAGE_EXIT_PX:  float = 1000.0
GATHER_ENTER_PX: float = 1500.0
GATHER_EXIT_PX:  float = 1700.0
REGEN_ENTER_PCT: float = 0.40
REGEN_EXIT_PCT:  float = 0.60
MELEE_ENTER_PX:  float = 100.0
MELEE_EXIT_PX:   float = 130.0
PICKUP_STOP_RADIUS: float = 60.0
MIN_DWELL_S:     float = 0.6      # how long a non-ENGAGE state must hold

# Stop radius when the in-game combat assist has committed to a
# melee engagement (via its 50 % per-engagement dice roll).  The
# autopilot reads ``state.assist.melee_engaged`` and closes to
# this radius so the swing arc actually reaches the target.
MELEE_STOP_RADIUS_PX: float = 50.0


# ── State constants ───────────────────────────────────────────────────────

S_ENGAGE = "engage"
S_GATHER = "gather"
S_REGEN  = "regen"
S_MINE   = "mine"
S_SEARCH = "search"

ALL_STATES = (S_ENGAGE, S_GATHER, S_REGEN, S_MINE, S_SEARCH)


# ── FSM + spiral state ────────────────────────────────────────────────────

_fsm: dict = {
    "state": S_MINE,        # benign default; first tick re-evaluates
    # Monotonic seconds when current state was entered.  ``None``
    # is a sentinel meaning "never stamped yet" -- the first tick
    # after reset is allowed to transition without dwell, then
    # stamps the timer so subsequent transitions respect MIN_DWELL.
    "entered_at": None,
}

_spiral_state: dict = {
    "anchor": None,   # (x, y) start of the current spiral
    "angle": 0.0,     # radians
    "radius": 100.0,  # px
}

# Indirection so tests can monkey-patch a fake clock.
_get_now = time.monotonic


def _spiral_reset() -> None:
    _spiral_state["anchor"] = None
    _spiral_state["angle"] = 0.0
    _spiral_state["radius"] = 100.0


def _fsm_reset(initial: str = S_MINE) -> None:
    """Reset the FSM to ``initial`` and clear the dwell timer
    sentinel.  The next tick is allowed to transition freely;
    after that, MIN_DWELL gates further transitions.  Tests
    must call this in their setup/fixture so cross-test state
    doesn't leak."""
    _fsm["state"] = initial
    _fsm["entered_at"] = None
    _spiral_reset()


def _nearest_pickup(state: dict, px: float, py: float
                    ) -> tuple[dict | None, float]:
    """Return the nearest iron + blueprint pickup combined.
    Blueprints are slightly preferred (worth more than 10 iron)
    so they get pulled in first when a tie."""
    iron = state.get("iron_pickups", []) or []
    bps = state.get("blueprint_pickups", []) or []
    candidates = list(bps) + list(iron)   # blueprints first
    return nearest(candidates, px, py)


def _choose_next_state(state: dict, p: dict, cur: str) -> str:
    """Pure function: given the world snapshot and the current FSM
    state, return what state the bot *wants* to be in this tick.

    Hysteresis is encoded by branching on ``cur``: the enter
    threshold and exit threshold differ, so a value drifting around
    the boundary doesn't oscillate.
    """
    px, py = p.get("x", 0.0), p.get("y", 0.0)

    # 1. ENGAGE — alien within band.  Preempts everything.
    aliens = state.get("aliens") or []
    threat, td = nearest(aliens, px, py)
    if cur == S_ENGAGE:
        if threat is not None and td < ENGAGE_EXIT_PX:
            return S_ENGAGE
    else:
        if threat is not None and td < ENGAGE_ENTER_PX:
            return S_ENGAGE

    # 2. GATHER — loot pickup within reach.
    pickup, pd = _nearest_pickup(state, px, py)
    if cur == S_GATHER:
        if pickup is not None and pd < GATHER_EXIT_PX:
            return S_GATHER
    else:
        if pickup is not None and pd < GATHER_ENTER_PX:
            return S_GATHER

    # 3. REGEN — shields hurt; sit still and recover.
    sh = int(p.get("shields", 0))
    sh_max = max(1, int(p.get("max_shields", 1)))
    pct = sh / sh_max
    if cur == S_REGEN:
        if pct < REGEN_EXIT_PCT:
            return S_REGEN
    else:
        if pct < REGEN_ENTER_PCT:
            return S_REGEN

    # 4. MINE vs SEARCH — discrete event, no hysteresis needed.
    asteroids = state.get("asteroids") or []
    if asteroids:
        return S_MINE
    return S_SEARCH


def _on_enter(new_state: str) -> None:
    """Per-state entry hook.  Currently only SEARCH cares -- its
    spiral anchor must be cleared so each fresh search starts
    from the bot's current position, not a stale prior anchor.

    The melee-commit dice roll on ENGAGE entry happens in the
    in-process combat assist (see ``bot_combat_assist.tick``),
    not here, because combat assist is the authoritative owner
    of weapon selection -- the autopilot's 10 Hz tick + 0.25 s
    Tab rate-limit can't beat the per-frame ranged-vs-melee
    auto-switch unless the assist itself stays out of its way.
    The autopilot reads the result via ``state.assist.melee_engaged``
    in ``_act_engage`` to choose the right movement stop radius.
    """
    if new_state == S_SEARCH:
        _spiral_reset()


def _do_auto(state: dict, p: dict) -> None:
    """Step the FSM one tick, then dispatch the action for the
    current state.  ENGAGE preempts dwell; everything else waits
    out ``MIN_DWELL_S`` before transitioning.

    The first tick after ``_fsm_reset()`` (entered_at sentinel
    None) always stamps the timer and is allowed to transition
    freely -- otherwise a fresh process couldn't react to its
    initial observation."""
    now = _get_now()
    cur = _fsm["state"]
    desired = _choose_next_state(state, p, cur)

    if _fsm["entered_at"] is None:
        # First tick: stamp the timer, allow immediate transition.
        _fsm["entered_at"] = now
        if desired != cur:
            _fsm["state"] = desired
            cur = desired
            _on_enter(cur)
    elif desired != cur:
        dwell = now - _fsm["entered_at"]
        if desired == S_ENGAGE or dwell >= MIN_DWELL_S:
            _fsm["state"] = desired
            _fsm["entered_at"] = now
            cur = desired
            _on_enter(cur)

    if cur == S_ENGAGE:
        _act_engage(state, p)
    elif cur == S_GATHER:
        _act_gather(state, p)
    elif cur == S_REGEN:
        _do_idle()
    elif cur == S_MINE:
        _do_mine_nearest(state, p)
    else:  # S_SEARCH
        _do_spiral_search(state, p)


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
    threat, td = nearest(aliens, px, py)
    if threat is None:
        # FSM said engage but the alien vanished mid-tick.  Bail
        # to a safe no-op; next tick will re-route us out.
        KeyState.hold("space", False)
        return

    melee_committed = bool(
        (state.get("assist") or {}).get("melee_engaged", False))
    if melee_committed:
        # Committed melee rush: drive in to swing range.  Don't
        # call _ensure_weapon -- the in-process combat assist has
        # locked the Energy Blade and would just fight us at
        # 60 FPS vs our 10 Hz Tab presses.
        _do_goto(state, p, threat["x"], threat["y"],
                 stop_radius=MELEE_STOP_RADIUS_PX)
        KeyState.hold("space", True)
        return

    # Ranged engagement (default): laser/melee sub-band hysteresis.
    cur_weapon = state.get("weapon", {}).get("name", "Basic Laser")
    if cur_weapon == "Melee":
        # In Melee already: only swap back to Laser once we're past
        # the exit band (130 px).
        if td > MELEE_EXIT_PX:
            _ensure_weapon(state, "Basic Laser")
    else:
        # In a ranged weapon: only swap to Melee once we're firmly
        # inside the enter band (100 px).
        if td < MELEE_ENTER_PX:
            _ensure_weapon(state, "Melee")
        else:
            _ensure_weapon(state, "Basic Laser")
    _do_goto(state, p, threat["x"], threat["y"], stop_radius=380.0)
    KeyState.hold("space", td < FIRE_RANGE_PX)


def _act_gather(state: dict, p: dict) -> None:
    """GATHER: head toward the nearest pickup, no fire."""
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    pickup, _pd = _nearest_pickup(state, px, py)
    if pickup is None:
        # Pickup vanished (probably collected); next tick re-routes.
        KeyState.hold("space", False)
        return
    KeyState.hold("space", False)
    _do_goto(state, p, pickup["x"], pickup["y"],
             stop_radius=PICKUP_STOP_RADIUS)


def _do_spiral_search(state: dict, p: dict) -> None:
    """Drive the ship in an outward spiral around the position
    where the spiral started, sweeping the field for any asteroid
    that became reachable.  Re-anchors if the spiral has run for
    too long without finding anything."""
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    if _spiral_state["anchor"] is None:
        _spiral_state["anchor"] = (px, py)
        _spiral_state["angle"] = 0.0
        _spiral_state["radius"] = 100.0
    ax, ay = _spiral_state["anchor"]
    r = _spiral_state["radius"]
    a = _spiral_state["angle"]
    tx = ax + math.cos(a) * r
    ty = ay + math.sin(a) * r
    _ensure_weapon(state, "Mining Beam")
    _do_goto(state, p, tx, ty, stop_radius=120.0)
    # Mining beam fires while moving, in case we drift past an
    # asteroid we couldn't see in state (e.g. extraction lag).
    KeyState.hold("space", True)
    # Advance the spiral incrementally each tick.
    _spiral_state["angle"] = (a + math.radians(8.0)) % (2 * math.pi)
    _spiral_state["radius"] = min(r + 1.5, 3000.0)
    if _spiral_state["radius"] >= 3000.0:
        _spiral_reset()


def _do_goto(state: dict, p: dict, tx: float, ty: float,
             stop_radius: float = 80.0) -> None:
    """Rotate toward (tx, ty) and thrust until within ``stop_radius``."""
    dx = tx - p.get("x", 0)
    dy = ty - p.get("y", 0)
    dist = math.hypot(dx, dy)
    if dist < stop_radius:
        # Arrived — release thrust + rotation, drift in place.
        KeyState.hold("w", False)
        KeyState.hold("a", False)
        KeyState.hold("d", False)
        KeyState.hold("s", True)         # gentle brake
        return
    KeyState.hold("s", False)
    target = angle_to(dx, dy)
    delta = heading_delta(p.get("heading", 0.0), target)
    if delta < -5.0:
        KeyState.hold("a", True);  KeyState.hold("d", False)
    elif delta > 5.0:
        KeyState.hold("a", False); KeyState.hold("d", True)
    else:
        KeyState.hold("a", False); KeyState.hold("d", False)
    # Only thrust forward when roughly aligned (within 45° of target).
    KeyState.hold("w", abs(delta) < 45.0)


def _do_mine_nearest(state: dict, p: dict) -> None:
    asteroids = state.get("asteroids", [])
    target, dist = nearest(asteroids, p.get("x", 0), p.get("y", 0))
    if target is None:
        _do_idle()
        return
    _ensure_weapon(state, "Mining Beam")
    _do_goto(state, p, target["x"], target["y"], stop_radius=200.0)
    KeyState.hold("space", dist < MINING_RANGE_PX)


def _do_attack_nearest(state: dict, p: dict) -> None:
    aliens = state.get("aliens", [])
    target, dist = nearest(aliens, p.get("x", 0), p.get("y", 0))
    if target is None:
        _do_idle()
        return
    if dist < MELEE_RANGE_PX:
        _ensure_weapon(state, "Melee")
    else:
        _ensure_weapon(state, "Basic Laser")
    _do_goto(state, p, target["x"], target["y"], stop_radius=300.0)
    KeyState.hold("space", dist < FIRE_RANGE_PX)


def _do_engage_boss(state: dict, p: dict) -> None:
    boss = state.get("boss")
    if boss is None:
        _do_attack_nearest(state, p)
        return
    _ensure_weapon(state, "Basic Laser")
    _do_goto(state, p, boss["x"], boss["y"], stop_radius=400.0)
    KeyState.hold("space", True)


def _do_retreat(state: dict, p: dict) -> None:
    # Find a Home Station building, head toward it.
    buildings = state.get("buildings", [])
    home = None
    for b in buildings:
        if "Station" in (b.get("type") or "") or \
           "Station" in (b.get("name") or ""):
            home = b
            break
    if home is None:
        # No station — head to world centre as fallback.
        zone = state.get("zone", {})
        cx = zone.get("world_w", 6400) / 2
        cy = zone.get("world_h", 6400) / 2
        _do_goto(state, p, cx, cy, stop_radius=200.0)
        return
    _do_goto(state, p, home["x"], home["y"], stop_radius=150.0)
    KeyState.hold("space", False)


# ── Weapon cycling ────────────────────────────────────────────────────────

_WEAPON_ORDER = ("Basic Laser", "Mining Beam", "Melee")
_last_cycle_t: float = 0.0


def _do_cycle_weapon(state: dict, target_name: str | None) -> None:
    if target_name is None:
        return
    _ensure_weapon(state, target_name)


def _ensure_weapon(state: dict, want: str) -> None:
    """Press Tab as many times as needed to land on ``want``.  Has
    a per-call rate limit so we don't spam Tab faster than the
    game can register weapon cycles."""
    global _last_cycle_t
    cur = state.get("weapon", {}).get("name", "Basic Laser")
    if cur == want:
        return
    if (time.time() - _last_cycle_t) < 0.25:
        return
    try:
        cur_idx = _WEAPON_ORDER.index(cur)
        want_idx = _WEAPON_ORDER.index(want)
    except ValueError:
        return
    n = (want_idx - cur_idx) % len(_WEAPON_ORDER)
    pyautogui.press("tab")
    _last_cycle_t = time.time()


# ── Main loop ─────────────────────────────────────────────────────────────

def _ensure_game_focused() -> None:
    """Activate the game window so pyautogui keystrokes reach
    it.  No-op on non-Windows or if pygetwindow isn't installed.
    Called periodically from main()."""
    if gw is None:
        return
    try:
        for w in gw.getAllWindows():
            if "Call of Orion" in (w.title or ""):
                # Skip if already active to avoid focus thrash.
                try:
                    if hasattr(w, "isActive") and w.isActive:
                        return
                except Exception:
                    pass
                try:
                    w.activate()
                except Exception:
                    pass
                return
    except Exception:
        pass


def main() -> None:
    print("=" * 60)
    print("Call of Orion -- autopilot")
    print(f"API: {API_BASE}/state  |  Poll: {POLL_HZ:.0f} Hz")
    print("Hotkeys: Ctrl+Shift+P pause | Ctrl+Shift+Q quit")
    print("=" * 60)
    threading.Thread(target=_hotkeys, daemon=True).start()
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0
    period = 1.0 / POLL_HZ
    last_warn = 0.0
    last_focus = 0.0
    # Activate the game once at startup so the very first
    # keystroke lands in the game window.
    _ensure_game_focused()
    while not State.stop:
        if State.paused:
            KeyState.release_all()
            time.sleep(0.1)
            continue
        t0 = time.time()
        # Re-activate the game window every ~2 s so keystrokes
        # keep reaching it even if the user clicks elsewhere.
        if t0 - last_focus > 2.0:
            _ensure_game_focused()
            last_focus = t0
        state = fetch_state()
        if state is None:
            if time.time() - last_warn > 5.0:
                print("[autopilot] no /state response -- is the "
                      "game running with COO_BOT_API=1?")
                last_warn = time.time()
            KeyState.release_all()
            time.sleep(1.0)
            continue
        try:
            execute_intent(state)
        except Exception as e:
            print(f"[autopilot] execute_intent error: {e}")
            KeyState.release_all()
        # Sleep the remainder of the frame.
        elapsed = time.time() - t0
        if elapsed < period:
            time.sleep(period - elapsed)
    KeyState.release_all()
    print("[autopilot] done")


if __name__ == "__main__":
    main()
