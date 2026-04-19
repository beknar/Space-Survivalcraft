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
import time
from typing import Iterable

from constants import (
    ALIEN_RADIUS, ALIEN_AVOIDANCE_RADIUS, ALIEN_AVOIDANCE_FORCE,
    ASTEROID_RADIUS,
)

# Spatial-hash grid cache for asteroid avoidance.  Each entry is keyed
# by ``id(asteroid_list)`` — one Zone-2 alien loop shares the same
# list across ~60 calls, so building the grid once per frame turns an
# O(M×N) scan into ~O(M) 3×3-cell lookups.  The cache auto-invalidates
# after ``_GRID_TTL`` seconds (~3 frames @60 FPS) so positional drift
# from asteroid spin/velocity stays within the cell boundary.
_GRID_CELL = ALIEN_RADIUS + ASTEROID_RADIUS + ALIEN_AVOIDANCE_RADIUS
_GRID_TTL = 0.05
_grid_cache: dict[int, tuple[float, dict[tuple[int, int], list]]] = {}


def _get_asteroid_grid(asteroid_list) -> dict[tuple[int, int], list]:
    """Return a grid keyed by (cell_x, cell_y) → list[asteroid].

    Rebuilt when the cached entry is older than ``_GRID_TTL`` or the
    list identity changes.  Cell size equals the avoidance threshold
    so each alien only needs to scan the 3×3 block around its cell.
    """
    key = id(asteroid_list)
    now = time.monotonic()
    cached = _grid_cache.get(key)
    if cached is not None and now - cached[0] < _GRID_TTL:
        return cached[1]
    cs = _GRID_CELL
    grid: dict[tuple[int, int], list] = {}
    for a in asteroid_list:
        cx = int(a.center_x // cs)
        cy = int(a.center_y // cs)
        bucket = grid.get((cx, cy))
        if bucket is None:
            grid[(cx, cy)] = [a]
        else:
            bucket.append(a)
    _grid_cache[key] = (now, grid)
    # Drop stale entries (lists garbage-collected or long-unused).
    if len(_grid_cache) > 16:
        for k in [k for k, v in _grid_cache.items() if now - v[0] > 1.0]:
            del _grid_cache[k]
    return grid


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

    # Asteroid repulsion via a per-frame spatial hash.  Cell size is
    # set so every asteroid that could repel the alien lives in one
    # of the 3×3 cells around the alien's own cell — turning a full
    # ~180-asteroid scan into a ~1-asteroid-average lookup.  The
    # squared-distance early-out still guards the inner math.sqrt.
    thresh_ast = _GRID_CELL
    thresh_ast_sq = thresh_ast * thresh_ast
    grid = _get_asteroid_grid(asteroid_list)
    acx = int(bx // thresh_ast)
    acy = int(by // thresh_ast)
    for gx in (acx - 1, acx, acx + 1):
        for gy in (acy - 1, acy, acy + 1):
            bucket = grid.get((gx, gy))
            if not bucket:
                continue
            for asteroid in bucket:
                adx = bx - asteroid.center_x
                ady = by - asteroid.center_y
                adist_sq = adx * adx + ady * ady
                if adist_sq >= thresh_ast_sq or adist_sq == 0.0:
                    continue
                adist = math.sqrt(adist_sq)
                w = ALIEN_AVOIDANCE_FORCE * (1.0 - adist / thresh_ast)
                steer_x += adx / adist * w
                steer_y += ady / adist * w

    # Sibling-alien repulsion (Zone 1 only; Zone 2 passes ``()``).
    # Same squared-distance early-out pattern.
    thresh_al = ALIEN_RADIUS * 2.0 + ALIEN_AVOIDANCE_RADIUS
    thresh_al_sq = thresh_al * thresh_al
    for other in alien_list:
        if other is body:
            continue
        odx = bx - other.center_x
        ody = by - other.center_y
        odist_sq = odx * odx + ody * ody
        if odist_sq >= thresh_al_sq or odist_sq == 0.0:
            continue
        odist = math.sqrt(odist_sq)
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
