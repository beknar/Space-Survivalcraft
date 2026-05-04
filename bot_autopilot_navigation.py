"""Boundary + building potential field, stuck detection, escape burst.

Pure helpers extracted from ``bot_autopilot.py``.  Every function here
operates on ``state`` / ``p`` snapshots from the /state HTTP endpoint
plus a small handful of mutable state objects (the stuck-detect
history dict, the spiral anchor dict).  No module-level singletons
are imported — callers pass them in, which keeps the module trivially
testable.

The split addresses two pain points in the original 2400-line
``bot_autopilot.py``:

* The potential-field code mixed pure geometry with FSM-driven
  side effects — the geometry is now standalone and stress-tested
  in isolation.

* The stuck-detect / escape pair was the most-iterated section of
  the autopilot (eight bug-fix cycles in 2026-04-29..2026-05-03).
  Pulling it out makes the seam between "decide stuck" and "act on
  stuck" explicit.

Constants live at the top of this module.  ``bot_autopilot.py``
re-exports them so existing tests using ``ap.BOUNDARY_REPULSION_GAIN``
keep working.
"""
from __future__ import annotations

import math
from typing import Callable


# ── Edge / building / escape tuning ─────────────────────────────────────

# Sample window over which displacement is measured for stuck-detect.
STUCK_DETECT_WINDOW_S = 1.5
# < this much movement in window -> stuck (combined with rotation gate).
STUCK_DETECT_DIST_PX = 25.0
# Cumulative heading rotation across the detect window above which
# the bot is considered "actively turning" rather than stuck.
# Without this gate the SEARCH spiral fires stuck-detect every
# 1.5 s during normal operation.
STUCK_DETECT_ROTATION_DEG = 30.0
# Minimum time the escape override lasts.
STUCK_ESCAPE_MIN_DURATION_S = 1.5
# Escape stays active until the ship is at least this far from any
# world edge — keeps the override running through long rotations
# (e.g. 180° turn from the top edge to face south).
STUCK_ESCAPE_CLEAR_MARGIN_PX = 500.0
# Spiral / escape targets stay this far inside the world rect.
STUCK_WORLD_MARGIN_PX = 200.0
# Throttle the "STUCK at edge" log so a long escape doesn't spam.
STUCK_LOG_THROTTLE_S = 30.0

# Within this distance of any world edge a per-axis repulsion
# vector is blended into the goto heading.  Tuned to start nudging
# well before the bot is at risk of pinning (~one screen height of
# warning) so the deflection is gradual, not a last-second swerve.
BOUNDARY_REPULSION_RANGE_PX: float = 400.0
# Strength of the repulsion vs the (unit-normalized) goto vector.
# Gain 1.0 means: at the edge itself (distance 0), repulsion has
# magnitude 1.0 along that axis — equal to the goto's magnitude —
# so a chase target through the edge ends up deflected ~45° along
# the wall instead of pinning.
BOUNDARY_REPULSION_GAIN: float = 1.0
# Per-building repulsion range.  Intentionally small (well past
# the building's collision radius of ~30 px but still inside the
# deposit / install / craft stop radii of 200-250 px) so navigation
# TO a building still completes.
BUILDING_REPULSION_RANGE_PX: float = 80.0
# Slightly softer than world-edge repulsion: a single building's
# push shouldn't fully overwhelm a chase vector when there's only
# 50 px of clearance.  Adjacent buildings (a corner) stack and
# recover the strong-deflect behaviour automatically.
BUILDING_REPULSION_GAIN: float = 0.7

# Distance the bot walks per tick when seeking a clear spot or
# heading along the escape vector.  Re-exported here because
# ``do_escape_edge`` uses it as the escape target offset.
BUILD_SEEK_TARGET_DIST_PX = 1000.0


# ── Geometry ────────────────────────────────────────────────────────────

def angle_to(dx: float, dy: float) -> float:
    """Heading (degrees, 0=N, CW positive) from origin to (dx, dy).
    Matches arcade's player.heading convention used by the game."""
    return math.degrees(math.atan2(dx, dy))


def heading_delta(current: float, target: float) -> float:
    """Shortest signed angle (current -> target) in [-180, 180]."""
    d = (target - current + 540.0) % 360.0 - 180.0
    return d


# ── Potential field ─────────────────────────────────────────────────────

def boundary_repulsion(p: dict, zone: dict) -> tuple[float, float]:
    """Potential-field repulsion vector pointing **away from world
    edges**.  Each axis contributes independently and linearly:
    magnitude is 0 at distance ``BOUNDARY_REPULSION_RANGE_PX`` from
    an edge, ramps to 1.0 right at the edge.

    Corners get the sum of both axis components automatically, which
    yields a diagonal push (correct: away from the corner).  Far
    from any edge the result is exactly ``(0.0, 0.0)`` so callers
    pay no cost for the safe case.
    """
    if not zone:
        return (0.0, 0.0)
    world_w = float(zone.get("world_w", 0) or 0)
    world_h = float(zone.get("world_h", 0) or 0)
    if world_w <= 0 or world_h <= 0:
        return (0.0, 0.0)
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    rng = BOUNDARY_REPULSION_RANGE_PX
    rx = 0.0
    ry = 0.0
    if px < rng:
        rx += 1.0 - max(0.0, px) / rng
    east_dist = world_w - px
    if east_dist < rng:
        rx -= 1.0 - max(0.0, east_dist) / rng
    if py < rng:
        ry += 1.0 - max(0.0, py) / rng
    north_dist = world_h - py
    if north_dist < rng:
        ry -= 1.0 - max(0.0, north_dist) / rng
    return (rx, ry)


def building_repulsion(p: dict, state: dict) -> tuple[float, float]:
    """Per-building potential-field repulsion summed across every
    building visible in /state.  Same linear ramp as
    ``boundary_repulsion`` but the source is the player's own
    structures instead of the world walls.

    Each building within ``BUILDING_REPULSION_RANGE_PX`` of the
    ship contributes a unit-vector pointing from the building
    center to the ship, scaled by ``1 - dist/range``.  Two adjacent
    buildings (a station corner) sum their contributions
    automatically, recovering the strong-deflect behaviour the
    boundary field gets at world corners.
    """
    buildings = state.get("buildings") or []
    if not buildings:
        return (0.0, 0.0)
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    rng = BUILDING_REPULSION_RANGE_PX
    rng_sq = rng * rng
    rx = 0.0
    ry = 0.0
    for b in buildings:
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        dx_b = px - bx
        dy_b = py - by
        d_sq = dx_b * dx_b + dy_b * dy_b
        if d_sq >= rng_sq:
            continue
        d = math.sqrt(d_sq)
        if d < 0.5:
            ry += 1.0
            continue
        strength = 1.0 - d / rng
        rx += (dx_b / d) * strength
        ry += (dy_b / d) * strength
    return (rx, ry)


def steered_heading(state: dict, p: dict, dx: float, dy: float,
                    dist: float) -> float:
    """Return the heading (degrees) the bot should rotate toward,
    after blending in the boundary + building repulsion fields.

    When the ship is far from every world edge AND every building
    the function returns ``angle_to(dx, dy)`` — both fields are zero
    so the blended heading is identical to the unmodified one.
    Closer to an edge / building the field pushes the heading along
    that wall instead of through it.
    """
    zone = state.get("zone") or {}
    rx, ry = boundary_repulsion(p, zone)
    bx, by = building_repulsion(p, state)
    rx += bx * BUILDING_REPULSION_GAIN
    ry += by * BUILDING_REPULSION_GAIN
    if rx == 0.0 and ry == 0.0:
        return angle_to(dx, dy)
    norm = max(1.0, dist)
    gx = dx / norm
    gy = dy / norm
    sx = gx + rx * BOUNDARY_REPULSION_GAIN
    sy = gy + ry * BOUNDARY_REPULSION_GAIN
    # Degenerate cancellation: a goto pointing straight into a wall
    # opposes the repulsion exactly along one axis, so the sum's
    # magnitude collapses to ~0.  Fall back to **pure repulsion**
    # so the bot peels off the wall instead of picking a random
    # heading.
    if abs(sx) < 0.05 and abs(sy) < 0.05:
        return angle_to(rx, ry)
    return angle_to(sx, sy)


# ── Stuck detection ─────────────────────────────────────────────────────

def record_position(p: dict, stuck_state: dict, get_now: Callable[[], float]
                    ) -> None:
    """Append the player's current position + heading to the rolling
    stuck-detect history and evict samples older than the window.
    Heading is captured so ``detect_stuck`` can distinguish "rotating
    to face new target" (not stuck) from "pinned against an obstacle"
    (stuck) — both look identical to position-only detection."""
    now = get_now()
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    heading = float(p.get("heading", 0.0))
    h = stuck_state["history"]
    h.append((now, px, py, heading))
    cutoff = now - STUCK_DETECT_WINDOW_S
    while h and h[0][0] < cutoff:
        h.pop(0)


def detect_stuck(stuck_state: dict) -> bool:
    """True when the ship has barely moved over the last
    ``STUCK_DETECT_WINDOW_S`` **and** isn't actively rotating.
    Conservative: requires the history to have spanned at least 80%
    of the window so we don't false-fire in the first second after
    process start.
    """
    h = stuck_state["history"]
    if len(h) < 5:
        return False
    span = h[-1][0] - h[0][0]
    if span < STUCK_DETECT_WINDOW_S * 0.8:
        return False
    moved = math.hypot(h[-1][1] - h[0][1], h[-1][2] - h[0][2])
    if moved >= STUCK_DETECT_DIST_PX:
        return False
    rotation_total = 0.0
    for i in range(1, len(h)):
        rotation_total += abs(heading_delta(h[i - 1][3], h[i][3]))
    return rotation_total < STUCK_DETECT_ROTATION_DEG


def ship_clear_of_edges(p: dict, zone: dict) -> bool:
    """True when the ship is at least ``STUCK_ESCAPE_CLEAR_MARGIN_PX``
    from every world edge.  Used as one half of the exit condition
    for the escape override so the bot doesn't drop back into the
    FSM while still pinned at a boundary."""
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    world_w = float(zone.get("world_w", 0) or 0)
    world_h = float(zone.get("world_h", 0) or 0)
    if world_w <= 0 or world_h <= 0:
        return True
    return (
        px > STUCK_ESCAPE_CLEAR_MARGIN_PX
        and py > STUCK_ESCAPE_CLEAR_MARGIN_PX
        and px < world_w - STUCK_ESCAPE_CLEAR_MARGIN_PX
        and py < world_h - STUCK_ESCAPE_CLEAR_MARGIN_PX
    )


def ship_clear_of_buildings(p: dict, state: dict) -> bool:
    """True when the ship is outside ``BUILDING_REPULSION_RANGE_PX``
    of every building.  Used alongside ``ship_clear_of_edges`` as
    the second half of the escape exit condition."""
    buildings = state.get("buildings") or []
    if not buildings:
        return True
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    margin_sq = (
        BUILDING_REPULSION_RANGE_PX * BUILDING_REPULSION_RANGE_PX)
    for b in buildings:
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        dx = bx - px
        dy = by - py
        if dx * dx + dy * dy < margin_sq:
            return False
    return True


def compute_escape_target(state: dict, p: dict
                          ) -> tuple[float, float]:
    """Return (tx, ty) the bot should head toward to escape a
    boundary / building pin.  The direction is the combined
    boundary + building repulsion vector; falls back to world
    centre only when neither field is active.

    Result is clamped inside the world rect (with
    ``STUCK_WORLD_MARGIN_PX`` margin) so the escape target itself
    doesn't sit at an edge.
    """
    zone = state.get("zone") or {}
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    rx, ry = boundary_repulsion(p, zone)
    bx, by = building_repulsion(p, state)
    rx += bx * BUILDING_REPULSION_GAIN
    ry += by * BUILDING_REPULSION_GAIN
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    if abs(rx) > 0.05 or abs(ry) > 0.05:
        norm = math.hypot(rx, ry)
        ux = rx / norm
        uy = ry / norm
        tx = px + ux * BUILD_SEEK_TARGET_DIST_PX
        ty = py + uy * BUILD_SEEK_TARGET_DIST_PX
    else:
        tx = world_w * 0.5
        ty = world_h * 0.5
    tx = max(STUCK_WORLD_MARGIN_PX,
             min(world_w - STUCK_WORLD_MARGIN_PX, tx))
    ty = max(STUCK_WORLD_MARGIN_PX,
             min(world_h - STUCK_WORLD_MARGIN_PX, ty))
    return (tx, ty)
