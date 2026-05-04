"""TTL blacklists for unreachable pickups + asteroids.

Both blacklists are dicts keyed by ``(rounded_x, rounded_y)`` ->
expiry monotonic timestamp.  Entries are populated by stuck-detect
events: when the watchdog fires while the FSM is in ``S_GATHER`` /
``S_MINE``, the target the bot was chasing is added so subsequent
passes skip it.  Without this the bot oscillates indefinitely on a
pickup or asteroid sitting inside a station-building's repulsion
zone (the field pushes back, the FSM goto pulls forward; no progress,
escape burst fires, bot returns, repeat).

The 23-event-in-155 s gather-stuck loop and the 5-events-in-12 s
mine-stuck loop captured in ``bot_io/autopilot_telemetry.jsonl`` on
2026-05-02 were the motivating cases.

Functions take the blacklist dict + a ``get_now`` clock callable so
the module is fully decoupled from ``bot_autopilot._state`` and
``bot_autopilot._get_now``.  Wrappers in ``bot_autopilot.py`` bind
those in for the existing call sites + tests.
"""
from __future__ import annotations

import math
from typing import Callable


# ── Pickup blacklist tuning ─────────────────────────────────────────────

# 5 minutes — long enough that the bot moves on to a different
# pocket of the world before a unreachable pickup is reconsidered.
PICKUP_BLACKLIST_TTL_S: float = 300.0
# Skip any pickup within this radius of a blacklisted point.  Set
# wide enough to cover the entire pickup-flock around an obstructed
# building (multiple iron pickups can spawn from one asteroid kill).
PICKUP_BLACKLIST_RADIUS_PX: float = 60.0


# ── Asteroid blacklist tuning ───────────────────────────────────────────

# Shorter TTL than pickups: asteroids may become reachable from a
# different approach angle once the bot drifts elsewhere, and 60 s
# lets the bot retry from a clean state.
ASTEROID_BLACKLIST_TTL_S: float = 60.0
ASTEROID_BLACKLIST_RADIUS_PX: float = 40.0


def _evict_expired(blacklist: dict, now: float) -> None:
    """Drop entries whose expiry has passed.  Called inline from the
    ``is_blacklisted`` scans so the dict stays bounded."""
    expired = [k for k, exp in blacklist.items() if now >= exp]
    for k in expired:
        del blacklist[k]


def pickup_is_blacklisted(pu: dict, blacklist: dict,
                          get_now: Callable[[], float]) -> bool:
    """True if ``pu`` falls within ``PICKUP_BLACKLIST_RADIUS_PX``
    of any live (non-expired) blacklist entry."""
    if not blacklist:
        return False
    pux = float(pu.get("x", 0.0))
    puy = float(pu.get("y", 0.0))
    r_sq = PICKUP_BLACKLIST_RADIUS_PX * PICKUP_BLACKLIST_RADIUS_PX
    now = get_now()
    for (bx, by), expiry in list(blacklist.items()):
        if now >= expiry:
            del blacklist[(bx, by)]
            continue
        dx = bx - pux
        dy = by - puy
        if dx * dx + dy * dy < r_sq:
            return True
    return False


def blacklist_pickup(pu: dict, blacklist: dict,
                     get_now: Callable[[], float]) -> None:
    """Add ``pu`` to the pickup blacklist with a TTL of
    ``PICKUP_BLACKLIST_TTL_S``.  Position is rounded to the nearest
    10 px so floating-point variation between ticks can't slip past
    the lookup."""
    pux = float(pu.get("x", 0.0))
    puy = float(pu.get("y", 0.0))
    key = (round(pux / 10.0) * 10.0, round(puy / 10.0) * 10.0)
    blacklist[key] = get_now() + PICKUP_BLACKLIST_TTL_S


def asteroid_is_blacklisted(ast: dict, blacklist: dict,
                            get_now: Callable[[], float]) -> bool:
    """True if ``ast`` falls within ``ASTEROID_BLACKLIST_RADIUS_PX``
    of any live (non-expired) asteroid blacklist entry."""
    if not blacklist:
        return False
    ax = float(ast.get("x", 0.0))
    ay = float(ast.get("y", 0.0))
    r_sq = ASTEROID_BLACKLIST_RADIUS_PX * ASTEROID_BLACKLIST_RADIUS_PX
    now = get_now()
    for (bx, by), expiry in list(blacklist.items()):
        if now >= expiry:
            del blacklist[(bx, by)]
            continue
        dx = bx - ax
        dy = by - ay
        if dx * dx + dy * dy < r_sq:
            return True
    return False


def blacklist_asteroid(ast: dict, blacklist: dict,
                       get_now: Callable[[], float]) -> None:
    """Add ``ast`` to the asteroid blacklist with a TTL of
    ``ASTEROID_BLACKLIST_TTL_S``.  Position is rounded to a 10 px
    grid (same as the pickup blacklist) to absorb floating-point
    variation between ticks."""
    ax = float(ast.get("x", 0.0))
    ay = float(ast.get("y", 0.0))
    key = (round(ax / 10.0) * 10.0, round(ay / 10.0) * 10.0)
    blacklist[key] = get_now() + ASTEROID_BLACKLIST_TTL_S


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


def nearest_pickup(state: dict, px: float, py: float,
                   blacklist: dict,
                   get_now: Callable[[], float]
                   ) -> tuple[dict | None, float]:
    """Return the nearest iron + blueprint pickup combined, skipping
    any pickup that's been blacklisted.  Blueprints sort first
    (worth more than 10 iron) so they get pulled in on tie."""
    iron = state.get("iron_pickups", []) or []
    bps = state.get("blueprint_pickups", []) or []
    candidates = [c for c in (list(bps) + list(iron))
                  if not pickup_is_blacklisted(c, blacklist, get_now)]
    return nearest(candidates, px, py)


def nearest_asteroid(state: dict, px: float, py: float,
                     blacklist: dict,
                     get_now: Callable[[], float]
                     ) -> tuple[dict | None, float]:
    """Return the nearest non-blacklisted asteroid.  Used by
    ``S_MINE`` so a single unreachable asteroid doesn't lock the
    bot in an infinite stuck → escape → re-target loop — the same
    failure mode the pickup blacklist solved for ``S_GATHER``."""
    asteroids = state.get("asteroids", []) or []
    candidates = [a for a in asteroids
                  if not asteroid_is_blacklisted(a, blacklist, get_now)]
    return nearest(candidates, px, py)
