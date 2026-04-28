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
ENGAGE_RANGE_PX = 800.0           # target acquisition radius
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


# ── Auto-mode state machine ───────────────────────────────────────────────
#
#  Priority cascade per tick (re-evaluated every frame, no hysteresis
#  beyond what the goto/mine helpers already provide):
#
#    1. Under attack (alien within ENGAGE_RANGE)
#         -> close to fire range, combat assist auto-aims + auto-fires
#    2. Pickups within GATHER_RANGE_PX
#         -> collect them (loot drops from kills + asteroid mines).
#         Runs whenever a kill / mine has dropped iron or blueprints
#         within reach, so loot from a finished alien fight gets
#         scooped before the bot moves on.
#    3. Shields not full + safe
#         -> idle (let regen finish)
#    4. Shields full + safe + asteroids known
#         -> mine the nearest asteroid
#    5. No asteroids visible (rare)
#         -> spiral search outward from current position
#
#  Step 1 cooperates with the in-process combat-assist hook
#  (bot_combat_assist.py): the assist owns aim + fire, the
#  autopilot owns thrust to keep the threat in fire range.

GATHER_RANGE_PX: float = 1500.0   # how far the bot will detour for loot
PICKUP_STOP_RADIUS: float = 60.0  # close enough for the magnet to engage

_spiral_state: dict = {
    "anchor": None,   # (x, y) start of the current spiral
    "angle": 0.0,     # radians
    "radius": 100.0,  # px
}


def _do_auto(state: dict, p: dict) -> None:
    aliens = state.get("aliens", []) or []
    px, py = p.get("x", 0.0), p.get("y", 0.0)
    threat, threat_dist = nearest(aliens, px, py)

    # Priority 1: under attack -> engage.
    if threat is not None and threat_dist < ENGAGE_RANGE_PX:
        _spiral_reset()                  # break spiral so mine resumes from here
        if threat_dist < MELEE_RANGE_PX:
            _ensure_weapon(state, "Melee")
        else:
            _ensure_weapon(state, "Basic Laser")
        # Stay just outside alien stand-off (~300 px) to keep the
        # threat in laser range without colliding.  Combat assist
        # snaps heading + fires; autopilot just maintains distance.
        _do_goto(state, p, threat["x"], threat["y"],
                 stop_radius=380.0)
        # Hold space too, in case the assist is disabled.
        KeyState.hold("space", threat_dist < FIRE_RANGE_PX)
        return

    # Priority 2: pickups in range -> gather.  Runs once the
    # threat has been cleared, so the iron + blueprints dropped
    # by a destroyed attacker get collected before the bot
    # idles or returns to mining.  Also catches the iron drops
    # from asteroid mines that didn't auto-magnet because the
    # bot had already drifted too far.
    pickup, pdist = _nearest_pickup(state, px, py)
    if pickup is not None and pdist < GATHER_RANGE_PX:
        # Mining Beam doesn't help here, but it doesn't hurt --
        # holding fire while flying may catch any new asteroid
        # the bot drifts past.  Still, switch off space so we
        # don't waste shots if Basic Laser is the active weapon.
        KeyState.hold("space", False)
        _do_goto(state, p, pickup["x"], pickup["y"],
                 stop_radius=PICKUP_STOP_RADIUS)
        return

    # Priority 3: shields below 50 % + safe -> idle for regen.
    # We don't wait for full shields any more -- 50 % is enough
    # buffer to take the next mining trip and pop a stray alien.
    sh = int(p.get("shields", 0))
    sh_max = int(p.get("max_shields", 1))
    SHIELD_RECOVER_THRESHOLD: float = 0.5
    if sh < sh_max * SHIELD_RECOVER_THRESHOLD:
        _spiral_reset()
        _do_idle()
        return

    # Priority 4 & 5: full shields, safe -> mine.
    asteroids = state.get("asteroids", []) or []
    if asteroids:
        _spiral_reset()
        _do_mine_nearest(state, p)
        return

    # Priority 5 fallback: spiral search.  Should only fire when
    # the entire zone has been mined out, which is rare in normal
    # play but documented in the spec.
    _do_spiral_search(state, p)


def _nearest_pickup(state: dict, px: float, py: float
                    ) -> tuple[dict | None, float]:
    """Return the nearest iron + blueprint pickup combined.
    Blueprints are slightly preferred (worth more than 10 iron)
    so they get pulled in first when a tie."""
    iron = state.get("iron_pickups", []) or []
    bps = state.get("blueprint_pickups", []) or []
    candidates = list(bps) + list(iron)   # blueprints first
    return nearest(candidates, px, py)


def _spiral_reset() -> None:
    _spiral_state["anchor"] = None
    _spiral_state["angle"] = 0.0
    _spiral_state["radius"] = 100.0


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
