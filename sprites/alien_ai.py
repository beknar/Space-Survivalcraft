"""Shared alien-AI helpers used by both Zone 1 `SmallAlienShip` and the
Zone 2 alien variants.

The two alien hierarchies share the same patrol waypoint + PURSUE
standoff orbit skeleton, plus an obstacle-avoidance steering pass over
asteroids, sibling aliens, and player-deployed force walls.  Rather
than merge the classes (which diverge on stuck-detection, stats, and
guns), the identical bits live here as module-level helpers.

Functions are deliberately stateless and take the body they operate on
as the first argument so they can be called from either class with
exactly one extra line.
"""
from __future__ import annotations

import math
import random
from typing import Iterable

from constants import (
    ALIEN_RADIUS, ALIEN_AVOIDANCE_RADIUS, ALIEN_AVOIDANCE_FORCE,
    ASTEROID_RADIUS,
)


def pick_patrol_target(
    home_x: float, home_y: float, patrol_r: float,
    world_w: float, world_h: float,
) -> tuple[float, float]:
    """Return a random waypoint within ``patrol_r`` of (home_x, home_y),
    clamped to the zone interior."""
    angle = random.uniform(0.0, math.tau)
    r = random.uniform(0.0, patrol_r)
    tx = max(50.0, min(world_w - 50.0, home_x + math.cos(angle) * r))
    ty = max(50.0, min(world_h - 50.0, home_y + math.sin(angle) * r))
    return tx, ty


def compute_avoidance(
    body,
    base_x: float,
    base_y: float,
    asteroid_list: Iterable,
    alien_list: Iterable = (),
    force_walls: list | None = None,
) -> tuple[float, float]:
    """Return ``(steer_x, steer_y)`` — an avoidance-adjusted steering
    vector derived from ``(base_x, base_y)`` plus repulsion from nearby
    asteroids, sibling aliens, and force walls.

    ``body`` is the sprite being steered (needs ``center_x`` / ``center_y``).
    ``alien_list`` defaults to empty — Zone 2 aliens don't repel each
    other, only Zone 1 `SmallAlienShip`s do.  ``force_walls`` is the
    GameView's active `ForceWall` list (may be ``None``).
    """
    steer_x, steer_y = base_x, base_y
    bx, by = body.center_x, body.center_y

    # Asteroid repulsion.
    thresh_ast = ALIEN_RADIUS + ASTEROID_RADIUS + ALIEN_AVOIDANCE_RADIUS
    for asteroid in asteroid_list:
        adx = bx - asteroid.center_x
        ady = by - asteroid.center_y
        adist = math.hypot(adx, ady)
        if 0.0 < adist < thresh_ast:
            w = ALIEN_AVOIDANCE_FORCE * (1.0 - adist / thresh_ast)
            steer_x += adx / adist * w
            steer_y += ady / adist * w

    # Sibling-alien repulsion (Zone 1 only; Zone 2 passes ``()``).
    thresh_al = ALIEN_RADIUS * 2.0 + ALIEN_AVOIDANCE_RADIUS
    for other in alien_list:
        if other is body:
            continue
        odx = bx - other.center_x
        ody = by - other.center_y
        odist = math.hypot(odx, ody)
        if 0.0 < odist < thresh_al:
            w = ALIEN_AVOIDANCE_FORCE * (1.0 - odist / thresh_al)
            steer_x += odx / odist * w
            steer_y += ody / odist * w

    # Force-wall repulsion (2x weight — walls are hard blocks).
    if force_walls:
        wall_thresh = ALIEN_RADIUS + ALIEN_AVOIDANCE_RADIUS + 30.0
        for wall in force_walls:
            cx, cy, wdist = wall.closest_point(bx, by)
            if 0.0 < wdist < wall_thresh:
                w = ALIEN_AVOIDANCE_FORCE * 2.0 * (1.0 - wdist / wall_thresh)
                wdx = bx - cx
                wdy = by - cy
                steer_x += wdx / wdist * w
                steer_y += wdy / wdist * w

    return steer_x, steer_y


def segment_crosses_any_wall(ax: float, ay: float, bx: float, by: float,
                              force_walls: list | None) -> bool:
    """True if the segment (ax, ay) → (bx, by) cuts through any of the
    supplied force walls."""
    if not force_walls:
        return False
    for wall in force_walls:
        if wall.segment_crosses(ax, ay, bx, by):
            return True
    return False
