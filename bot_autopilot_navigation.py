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
# Longer history window kept by ``record_position`` for the
# net-progress gate in ``detect_stuck``.  Catches the post-
# transition startup case where the 1.5 s spread can briefly dip
# under threshold while the bot is genuinely advancing — e.g. just
# after ``idle_at_base→hunt`` the bot accelerates from zero
# velocity and may move only 20-25 px in any single 1.5 s window
# even though it is 50+ px from the original idle anchor.
STUCK_DETECT_LONG_HISTORY_S = 5.0
# Minimum distance the latest sample must lie from at least one
# sample in the long history for the bot to be declared "making
# progress" (and therefore not stuck).  Tuned just above the short-
# window 25 px spread threshold so a bot oscillating in a 30-40 px
# region around a fixed pin still fires (matching PR #54's wall-
# tangent scenario), while a bot creeping 10 px/s for 5 s (50 px
# net) does not.
STUCK_DETECT_LONG_PROGRESS_PX = 40.0
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
# Per-building repulsion base range.  Bumped from 80 → 150 in the
# 2026-05-04 hardening cycle: at 80 px a chase trajectory entering
# the cluster from 500+ px out had no time to deflect (telemetry
# showed the bot pinning inside the cluster while HUNT navigated
# toward an alien on the far side).  The wider range is safe because
# repulsion is now ALSO target-aware — buildings within
# ``REPULSION_TARGET_SUPPRESS_PX`` of the goto target are excluded
# from the sum so deposit / craft / install navigation isn't blocked
# from docking with their target building.
BUILDING_REPULSION_RANGE_PX: float = 150.0
# Slightly softer than world-edge repulsion: a single building's
# push shouldn't fully overwhelm a chase vector when there's only
# 50 px of clearance.  Adjacent buildings (a corner) stack and
# recover the strong-deflect behaviour automatically.
BUILDING_REPULSION_GAIN: float = 0.7
# Per-building-type range multiplier.  The Home Station is a larger
# physical sprite at the centre of every cluster; giving it a wider
# field steers transit paths around the cluster instead of through
# it.  Other types fall back to the default 1.0× multiplier (i.e.
# the base BUILDING_REPULSION_RANGE_PX).
BUILDING_REPULSION_TYPE_MULTIPLIER: dict = {
    "Home Station": 1.5,
}
# Buildings within this radius of the goto target are excluded from
# the repulsion sum.  Without this gate the wider 150 px field would
# block deposit (200 px range), craft (200 px), and install (250 px)
# from docking with their target building — the field would push
# the bot back out of the action zone before the trigger fires.
REPULSION_TARGET_SUPPRESS_PX: float = 50.0

# Distance the bot walks per tick when seeking a clear spot or
# heading along the escape vector.  Re-exported here because
# ``do_escape_edge`` uses it as the escape target offset.
BUILD_SEEK_TARGET_DIST_PX = 1000.0


# ── Cluster avoidance (2026-05-04 hardening) ────────────────────────────

# A goto path that crosses within (cluster_radius +
# CLUSTER_DETOUR_MARGIN_PX) of the cluster centroid is detoured via
# a tangent waypoint on the cluster boundary.  Margin is wider than
# BUILDING_REPULSION_RANGE_PX so the detour kicks in BEFORE the
# field starts fighting the goto, and is wide enough that the
# waypoint itself sits in clear space.
CLUSTER_DETOUR_MARGIN_PX: float = 250.0
# Detour suppressed when the goto target is inside (cluster_radius +
# this margin) of the centroid — the bot is intentionally heading
# into the cluster (deposit / craft / install) so don't redirect it.
CLUSTER_DETOUR_TARGET_INSIDE_PX: float = 100.0
# Minimum number of buildings required to consider them a "cluster"
# worth detouring around.  A single isolated building doesn't form
# the kind of pin trap that motivates the detour.
CLUSTER_MIN_BUILDINGS: int = 3


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


def building_repulsion(p: dict, state: dict,
                       target: tuple[float, float] | None = None
                       ) -> tuple[float, float]:
    """Per-building potential-field repulsion summed across every
    building visible in /state.  Same linear ramp as
    ``boundary_repulsion`` but the source is the player's own
    structures instead of the world walls.

    Each building within its per-type range of the ship contributes
    a unit-vector pointing from the building center to the ship,
    scaled by ``1 - dist/range``.  Two adjacent buildings (a station
    corner) sum their contributions automatically, recovering the
    strong-deflect behaviour the boundary field gets at world
    corners.

    Per-type range multiplier (``BUILDING_REPULSION_TYPE_MULTIPLIER``)
    lets the Home Station project a wider field than ordinary
    modules — physically larger sprite, conceptually the centre of
    every cluster.

    ``target``: optional (tx, ty) of the bot's goto target.
    Two-tier suppression:
      * **Tight suppression** (``REPULSION_TARGET_SUPPRESS_PX``,
        ~50 px) excludes the docking building itself for normal
        approaches (deposit, craft, install).
      * **Cluster suppression** kicks in when the target is INSIDE
        the cluster centroid radius — the bot is heading into the
        station for a target that sits between multiple buildings
        (e.g. a pickup that spawned among the cluster).  All
        buildings in the cluster are excluded so the bot can thread
        through.  Caught from 2026-05-04 telemetry: GATHER stuck
        at hs_dist=58 trying to reach a pickup wedged inside the
        cluster while the OTHER buildings around it pushed back.
    """
    buildings = state.get("buildings") or []
    if not buildings:
        return (0.0, 0.0)
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    suppress_sq = (REPULSION_TARGET_SUPPRESS_PX
                   * REPULSION_TARGET_SUPPRESS_PX)
    # Cluster-suppression check: when target is inside the cluster
    # core, suppress every building in the cluster.  Computed once
    # up front to avoid per-building overhead.
    cluster_suppress_active = False
    cx_cluster = cy_cluster = r_cluster = 0.0
    if target is not None and len(buildings) >= CLUSTER_MIN_BUILDINGS:
        ccx, ccy, cr = cluster_centroid_and_radius(state)
        if ccx is not None:
            target_to_centre = math.hypot(target[0] - ccx,
                                          target[1] - ccy)
            if target_to_centre < cr + CLUSTER_DETOUR_TARGET_INSIDE_PX:
                cluster_suppress_active = True
                cx_cluster, cy_cluster, r_cluster = ccx, ccy, cr
    rx = 0.0
    ry = 0.0
    for b in buildings:
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        # Tier 1 — tight target-aware suppression: building is the
        # bot's destination (or right next to it).  Skip its
        # repulsion so the bot can actually dock.
        if target is not None:
            tdx = bx - target[0]
            tdy = by - target[1]
            if tdx * tdx + tdy * tdy < suppress_sq:
                continue
        # Tier 2 — cluster suppression: target is inside the cluster
        # core, so any building in the cluster gets excluded so the
        # bot can thread through to the target without being pushed
        # back out by the surrounding buildings.
        if cluster_suppress_active:
            cdx = bx - cx_cluster
            cdy = by - cy_cluster
            if cdx * cdx + cdy * cdy <= r_cluster * r_cluster:
                continue
        # Per-type range multiplier.
        bt = b.get("building_type", "") or ""
        mult = BUILDING_REPULSION_TYPE_MULTIPLIER.get(bt, 1.0)
        rng = BUILDING_REPULSION_RANGE_PX * mult
        rng_sq = rng * rng
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


# ── Cluster avoidance: aggregate the station as a single obstacle ──────

def clamp_to_world(tx: float, ty: float, zone: dict,
                   margin: float = STUCK_WORLD_MARGIN_PX
                   ) -> tuple[float, float, bool]:
    """Clamp (tx, ty) to inside ``[margin, world_dim - margin]``.
    Returns (clamped_x, clamped_y, was_clamped).  Used by HUNT and
    IDLE_AT_BASE navigation to keep goto targets inside the world
    so the bot doesn't pin against the boundary chasing an
    unreachable point.
    """
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    cx = max(margin, min(world_w - margin, tx))
    cy = max(margin, min(world_h - margin, ty))
    was_clamped = (cx != tx) or (cy != ty)
    return (cx, cy, was_clamped)


def find_clear_ring_point(hx: float, hy: float, radius: float,
                          zone: dict,
                          preferred_dx: float, preferred_dy: float,
                          margin: float = STUCK_WORLD_MARGIN_PX
                          ) -> tuple[float, float]:
    """Return a point on the circle of given ``radius`` around
    (``hx``, ``hy``) that is INSIDE the world rect (with the safety
    ``margin``).  The preferred direction is (``preferred_dx``,
    ``preferred_dy``) — the function tries that first, then sweeps
    around the ring in 30° increments until it finds an interior
    point.

    Used by ``_act_idle_at_base`` so a Home Station built near a
    world edge doesn't produce an outer-ring target that sits past
    the boundary.  2026-05-04 telemetry caught the regression: HS
    near the upper-right of a 6400×6400 world produced 12 HUNT
    stucks all clustered at y=5500-6200 (within 200-700 px of the
    north edge) because the outer-ring projection along the
    player→HS ray put the target at y≈6600, outside the world.
    """
    world_w = float(zone.get("world_w", 6400) or 6400)
    world_h = float(zone.get("world_h", 6400) or 6400)
    pref_len = math.hypot(preferred_dx, preferred_dy)
    if pref_len < 1e-6:
        # Degenerate: no preferred direction.  Default east.
        ux, uy = 1.0, 0.0
    else:
        ux = preferred_dx / pref_len
        uy = preferred_dy / pref_len
    # Try preferred direction first, then sweep ±30° increments.
    angles_deg = [0.0, 30.0, -30.0, 60.0, -60.0, 90.0, -90.0,
                  120.0, -120.0, 150.0, -150.0, 180.0]
    for a_deg in angles_deg:
        a = math.radians(a_deg)
        cos_a, sin_a = math.cos(a), math.sin(a)
        # Rotate (ux, uy) by a.
        rux = ux * cos_a - uy * sin_a
        ruy = ux * sin_a + uy * cos_a
        tx = hx + rux * radius
        ty = hy + ruy * radius
        if (margin <= tx <= world_w - margin
                and margin <= ty <= world_h - margin):
            return (tx, ty)
    # Every direction is clamped — HS itself is too close to a
    # corner.  Fall back to the clamped preferred direction; the
    # bot will still get close enough to the ring to be "near base".
    tx = hx + ux * radius
    ty = hy + uy * radius
    cx, cy, _ = clamp_to_world(tx, ty, zone, margin=margin)
    return (cx, cy)


def cluster_centroid_and_radius(state: dict
                                ) -> tuple[float | None, float | None,
                                           float | None]:
    """Compute centroid (cx, cy) and bounding radius (r) of the
    placed-building cluster in /state.buildings.  Returns
    (None, None, None) if there are fewer than
    ``CLUSTER_MIN_BUILDINGS`` placed.

    Used to decide whether a goto path crosses the cluster (i.e.
    needs detour routing) instead of relying on the per-building
    field to deflect a trajectory that's already too close to escape.
    """
    buildings = state.get("buildings") or []
    if len(buildings) < CLUSTER_MIN_BUILDINGS:
        return (None, None, None)
    cx = sum(float(b.get("x", 0.0)) for b in buildings) / len(buildings)
    cy = sum(float(b.get("y", 0.0)) for b in buildings) / len(buildings)
    r = 0.0
    for b in buildings:
        dx = float(b.get("x", 0.0)) - cx
        dy = float(b.get("y", 0.0)) - cy
        d = math.hypot(dx, dy)
        if d > r:
            r = d
    return (cx, cy, r)


def cluster_detour_waypoint(state: dict, px: float, py: float,
                            tx: float, ty: float
                            ) -> tuple[float, float] | None:
    """If the line from (px, py) to (tx, ty) passes within
    (cluster_radius + ``CLUSTER_DETOUR_MARGIN_PX``) of the cluster
    centroid, return a tangent waypoint on the cluster boundary
    that detours around it.  Otherwise return None.

    Suppressed when the target is inside the cluster's expanded
    radius — the bot is intentionally heading into the cluster
    (deposit / craft / install) so don't redirect it.
    """
    cx, cy, r = cluster_centroid_and_radius(state)
    if cx is None:
        return None
    R_path = r + CLUSTER_DETOUR_MARGIN_PX
    R_target = r + CLUSTER_DETOUR_TARGET_INSIDE_PX
    # Target is inside the cluster — it's our destination, no detour.
    target_to_centre = math.hypot(tx - cx, ty - cy)
    if target_to_centre < R_target:
        return None
    dx = tx - px
    dy = ty - py
    seg_len = math.hypot(dx, dy)
    if seg_len < 1.0:
        return None
    # Project centroid onto the segment from start→target.
    sx = cx - px
    sy = cy - py
    t_proj = (sx * dx + sy * dy) / (seg_len * seg_len)
    # Centroid not between start and end — straight path doesn't
    # really cross the cluster, no detour needed.
    if t_proj <= 0.0 or t_proj >= 1.0:
        return None
    nearest_x = px + t_proj * dx
    nearest_y = py + t_proj * dy
    perp_dx = nearest_x - cx
    perp_dy = nearest_y - cy
    perp_len = math.hypot(perp_dx, perp_dy)
    # Path clears the cluster — straight line is fine.
    if perp_len >= R_path:
        return None
    # Path penetrates the cluster.  Pick a perpendicular waypoint at
    # distance R_path from the centroid, on the side the path is
    # currently closer to (so the detour is the smaller arc).
    if perp_len < 0.5:
        # Segment passes essentially through centroid — pick a
        # perpendicular axis arbitrarily (rotate +90° from segment).
        ux = -dy / seg_len
        uy = dx / seg_len
    else:
        ux = perp_dx / perp_len
        uy = perp_dy / perp_len
    return (cx + ux * R_path, cy + uy * R_path)


def steered_heading(state: dict, p: dict, dx: float, dy: float,
                    dist: float,
                    target: tuple[float, float] | None = None) -> float:
    """Return the heading (degrees) the bot should rotate toward,
    after blending in the boundary + building repulsion fields.

    When the ship is far from every world edge AND every building
    the function returns ``angle_to(dx, dy)`` — both fields are zero
    so the blended heading is identical to the unmodified one.
    Closer to an edge / building the field pushes the heading along
    that wall instead of through it.

    ``target``: optional (tx, ty) of the bot's intended destination.
    When provided, ``building_repulsion`` excludes buildings within
    ``REPULSION_TARGET_SUPPRESS_PX`` of the target so the bot can
    actually dock with it (deposit / craft / install).
    """
    zone = state.get("zone") or {}
    rx, ry = boundary_repulsion(p, zone)
    bx, by = building_repulsion(p, state, target=target)
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
    (stuck) — both look identical to position-only detection.

    History retention uses ``STUCK_DETECT_LONG_HISTORY_S`` (5 s) so
    ``detect_stuck`` can run a long-window net-progress gate after
    the short-window spread/rotation checks.  The short-window
    checks themselves filter samples down to the last
    ``STUCK_DETECT_WINDOW_S`` (1.5 s) at evaluation time.
    """
    now = get_now()
    px = float(p.get("x", 0.0))
    py = float(p.get("y", 0.0))
    heading = float(p.get("heading", 0.0))
    h = stuck_state["history"]
    h.append((now, px, py, heading))
    cutoff = now - STUCK_DETECT_LONG_HISTORY_S
    while h and h[0][0] < cutoff:
        h.pop(0)


def detect_stuck(stuck_state: dict) -> bool:
    """True when the ship has barely moved over the last
    ``STUCK_DETECT_WINDOW_S`` **and** isn't actively rotating
    **and** has not made meaningful progress over the last
    ``STUCK_DETECT_LONG_HISTORY_S``.  Conservative: requires the
    history to have spanned at least 80% of the short window so we
    don't false-fire in the first second after process start.

    Three gates, evaluated in order:

    1. **Short-window spread** (last 1.5 s subset).  Motion is
       measured as the bounding-box spread of all samples in the
       window, not endpoint-to-endpoint distance.  Endpoint distance
       falsely flagged the bot as stuck during legitimate chase
       motion when it drifted forward and rotated back near its
       start position within the window (PR #56).  Spread stays
       small only when the bot is truly pinned in place.

    2. **Short-window rotation**.  Rotating to face a new target
       legitimately produces low spread; the rotation gate
       distinguishes "actively turning" from "pinned".

    3. **Long-window net progress** (full 5 s history).  Catches the
       post-transition startup case where the 1.5 s spread briefly
       dips under threshold while the bot is genuinely advancing —
       e.g. 4-5 s after ``idle_at_base→hunt`` the bot has moved
       50+ px from the original idle anchor even though any
       individual 1.5 s window only shows 20 px of motion (10 px/s
       acceleration ramp + station-cluster repulsion cross-currents).
       If any sample in the long history is more than
       ``STUCK_DETECT_LONG_PROGRESS_PX`` from the latest position,
       the bot is making net progress and is not stuck.  Caught
       from 2026-05-07 telemetry: 60 s ``hunt`` chase from
       (317, 3875) to (603, 3525) — 7.5 px/s average — that fired
       three stuck events near the start, each derailing the chase
       with a world-centre escape burst.
    """
    h = stuck_state["history"]
    if len(h) < 5:
        return False

    # Short-window subset: last STUCK_DETECT_WINDOW_S of samples.
    short_cutoff = h[-1][0] - STUCK_DETECT_WINDOW_S
    short = [s for s in h if s[0] >= short_cutoff]
    if len(short) < 5:
        return False
    span = short[-1][0] - short[0][0]
    if span < STUCK_DETECT_WINDOW_S * 0.8:
        return False
    xs = [s[1] for s in short]
    ys = [s[2] for s in short]
    spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    if spread >= STUCK_DETECT_DIST_PX:
        return False
    rotation_total = 0.0
    for i in range(1, len(short)):
        rotation_total += abs(heading_delta(short[i - 1][3], short[i][3]))
    if rotation_total >= STUCK_DETECT_ROTATION_DEG:
        return False

    # Long-window net-progress gate.  If any sample in the full
    # history is > LONG_PROGRESS_PX from the current position, the
    # bot has been making net progress despite the recent slow
    # window.  Uses whatever history is available — at startup
    # (fewer than 5 s of samples) the gate naturally falls back to
    # a tighter check, so a bot that genuinely never moved still
    # fires in the first second after the short-window gate fills.
    cur_x = h[-1][1]
    cur_y = h[-1][2]
    long_sq = STUCK_DETECT_LONG_PROGRESS_PX * STUCK_DETECT_LONG_PROGRESS_PX
    for s in h:
        d_sq = (s[1] - cur_x) ** 2 + (s[2] - cur_y) ** 2
        if d_sq > long_sq:
            return False
    return True


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
    boundary / building pin.

    Three cases, evaluated in order:

    1. **Wall-pinned with cluster blocking the inland path**: bot
       is inside ``STUCK_ESCAPE_CLEAR_MARGIN_PX`` of a world edge
       AND the building cluster's centroid sits between the bot
       and the world interior on that axis.  The legacy gradient
       points "outward from the wall" but the cluster physically
       blocks that direction (it's on the inland side), so thrust
       is wasted against the cluster's repulsion field even though
       the gradient direction is correct.  Caught from 2026-05-06
       follow-up #6 telemetry: bot frozen at *exactly* (48, 3983.8)
       in S_HUNT for 117+ s — stuck_detected fired once, escape
       mode kicked in, but the gradient target at (1048, 3984)
       was geometrically unreachable through the station cluster.
       Slide ALONG the wall tangent instead, in the direction
       AWAY from the cluster centroid — the bot exits the
       cluster's lateral coverage and can then drift inland on
       the next escape cycle.

    2. **Combined repulsion field active** (``|rx|>0.05`` or
       ``|ry|>0.05``): head along the gradient (legacy path).

    3. **No active field**: legacy world-centre fallback.

    Result is clamped inside the world rect with
    ``STUCK_WORLD_MARGIN_PX`` margin so the escape target itself
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

    # Case 1: wall + cluster trap.  Detect first so it can override
    # an otherwise-correct-looking gradient that the cluster makes
    # physically unreachable.
    near_west = px < STUCK_ESCAPE_CLEAR_MARGIN_PX
    near_east = px > world_w - STUCK_ESCAPE_CLEAR_MARGIN_PX
    near_south = py < STUCK_ESCAPE_CLEAR_MARGIN_PX
    near_north = py > world_h - STUCK_ESCAPE_CLEAR_MARGIN_PX
    wall_count = ((1 if near_west else 0) + (1 if near_east else 0)
                  + (1 if near_south else 0) + (1 if near_north else 0))
    wall_pinned_single = wall_count == 1
    # Corner pin (>=2 walls in margin): skip the wall-tangent path.
    # The tangent along wall A points ±perpendicular-to-A — which is
    # toward wall B at a corner — so the legacy gradient + world-
    # centre fallback's diagonal direction is the only escape that
    # exits both walls simultaneously.  Caught from 2026-05-06
    # follow-up #8 telemetry: bot wedged in the SE corner at
    # (px≈6003, py≈480) for 145+ s — east-wall pin AND south-wall
    # pin both held, wall-tangent picked ±y, "away from cluster"
    # sign chose -y (south), and the resulting target was due
    # south into the south wall.  The world-centre fallback at the
    # same position produces a NW target that exits both walls
    # cleanly via boundary repulsion.
    if wall_pinned_single and (state.get("buildings") or []):
        cx, cy, r_cluster = _cluster_centroid_and_extent(state, (px, py))
        # Bot must additionally be within the cluster's perpendicular
        # extent (with one repulsion-range buffer) for the cluster to
        # actually block the inland path.  Without this check the
        # wall-tangent fires whenever the cluster centroid is inland of
        # the bot, even if the bot is far above/below the cluster — at
        # which point inland motion clears the cluster laterally and
        # the tangent escape just keeps the bot pinned to the wall.
        # Caught from 2026-05-07 telemetry: bot oscillating at
        # (370, 4542) for 50+ s with cluster centred at (390, 4030);
        # cluster_blocks_inland gated wall-tangent because cx>px, but
        # py was 500+ px above the cluster — going east at that y had
        # no obstruction and the bot should have fallen through to
        # the legacy gradient (which targets due east here).
        extent = r_cluster + BUILDING_REPULSION_RANGE_PX
        if near_west or near_east:
            bot_in_cluster_lat = abs(py - cy) <= extent
            cluster_blocks_inland = bot_in_cluster_lat and (
                (near_west and cx > px)
                or (near_east and cx < px))
            if cluster_blocks_inland:
                # West/east wall: tangent direction is ±y.  Pick
                # the side that moves AWAY from the cluster's y
                # centroid so the bot exits the cluster's
                # lateral coverage.  Tie (bot at same y as
                # centroid) defaults to +y deterministically.
                #
                # NOTE: only clamp the tangent axis (y).  The wall-
                # axis (x) is intentionally at the wall — clamping
                # it inland would defeat the tangent (escape target
                # would end up with a +x component pushing the bot
                # back into the cluster).
                sign = 1.0 if py >= cy else -1.0
                tx = px
                ty = max(STUCK_WORLD_MARGIN_PX,
                         min(world_h - STUCK_WORLD_MARGIN_PX,
                             py + sign * BUILD_SEEK_TARGET_DIST_PX))
                return (tx, ty)
        else:
            bot_in_cluster_lat = abs(px - cx) <= extent
            cluster_blocks_inland = bot_in_cluster_lat and (
                (near_south and cy > py)
                or (near_north and cy < py))
            if cluster_blocks_inland:
                # North/south wall: tangent direction is ±x.
                sign = 1.0 if px >= cx else -1.0
                tx = max(STUCK_WORLD_MARGIN_PX,
                         min(world_w - STUCK_WORLD_MARGIN_PX,
                             px + sign * BUILD_SEEK_TARGET_DIST_PX))
                ty = py
                return (tx, ty)

    # Case 2 + 3: legacy paths (gradient or world-centre fallback).
    if abs(rx) > 0.05 or abs(ry) > 0.05:
        norm = math.hypot(rx, ry)
        ux = rx / norm
        uy = ry / norm
        tx = px + ux * BUILD_SEEK_TARGET_DIST_PX
        ty = py + uy * BUILD_SEEK_TARGET_DIST_PX
    else:
        tx = world_w * 0.5
        ty = world_h * 0.5
    return _clamp_target(tx, ty, world_w, world_h)


def _clamp_target(tx: float, ty: float, world_w: float, world_h: float
                  ) -> tuple[float, float]:
    """Clamp an escape target inside the world rect with
    ``STUCK_WORLD_MARGIN_PX`` margin so the target itself doesn't
    sit on an edge."""
    return (
        max(STUCK_WORLD_MARGIN_PX,
            min(world_w - STUCK_WORLD_MARGIN_PX, tx)),
        max(STUCK_WORLD_MARGIN_PX,
            min(world_h - STUCK_WORLD_MARGIN_PX, ty)),
    )


def _building_cluster_centroid(state: dict,
                               fallback: tuple[float, float]
                               ) -> tuple[float, float]:
    """Return (cx, cy) — the centroid of all buildings in /state.
    Used by ``compute_escape_target``'s wall-tangent path to
    decide which side of the cluster to slide toward.  When no
    buildings exist, return ``fallback`` (typically the bot's
    own position) so the sign comparisons in the caller default
    to a deterministic side without firing a "head into nothing"
    target."""
    buildings = state.get("buildings") or []
    if not buildings:
        return fallback
    sx = 0.0
    sy = 0.0
    n = 0
    for b in buildings:
        sx += float(b.get("x", 0.0))
        sy += float(b.get("y", 0.0))
        n += 1
    if n == 0:
        return fallback
    return (sx / n, sy / n)


def _cluster_centroid_and_extent(state: dict,
                                 fallback: tuple[float, float]
                                 ) -> tuple[float, float, float]:
    """Return (cx, cy, r) — centroid plus max-spoke radius — using
    every building in /state regardless of count.  Distinct from
    ``cluster_centroid_and_radius`` (line ~338), which gates on
    ``CLUSTER_MIN_BUILDINGS=3`` for the detour heuristic; the
    wall-tangent escape needs cluster geometry even with 1–2
    buildings on the field.  ``fallback`` is returned for centroid
    (with r=0.0) when no buildings exist."""
    buildings = state.get("buildings") or []
    if not buildings:
        return (fallback[0], fallback[1], 0.0)
    sx = 0.0
    sy = 0.0
    n = 0
    for b in buildings:
        sx += float(b.get("x", 0.0))
        sy += float(b.get("y", 0.0))
        n += 1
    if n == 0:
        return (fallback[0], fallback[1], 0.0)
    cx = sx / n
    cy = sy / n
    r = 0.0
    for b in buildings:
        bx = float(b.get("x", 0.0))
        by = float(b.get("y", 0.0))
        d = math.hypot(bx - cx, by - cy)
        if d > r:
            r = d
    return (cx, cy, r)
