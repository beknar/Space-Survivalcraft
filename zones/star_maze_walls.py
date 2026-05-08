"""Wall geometry / collision helpers extracted from ``zones.star_maze``.

The Star Maze pulls in two dungeon mazes (~150 wall rects each) and
runs per-frame circle / segment / point queries against the union of
their walls.  Plain list scans were the dominant cost on Star Maze
soaks (20 aliens × 120 walls × 5 push-out iterations = 12 k AABB
tests / frame).  This module owns the spatial-hash + push-out
helpers; ``StarMazeZone`` keeps thin one-line wrappers that delegate
to the module-level functions.

Module-level texture / sprite-list helpers (``_load_wall_tile``,
``_build_wall_sprites``) also live here — they're called once per
``setup`` to tile the dungeon-wall sheet across every wall rect, but
they're standalone helpers without per-frame state, so they fit the
same module split.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from constants import (
    STAR_MAZE_WALL_TILE, STAR_MAZE_WALL_SCALE,
    DUNGEON_WALL_SHEET_PNG,
)
from zones.maze_geometry import Rect

if TYPE_CHECKING:
    from zones.star_maze import StarMazeZone


# ── Wall tile cache ─────────────────────────────────────────────────
#
# The 336 × 184 dungeon sheet has many 16×16 tiles.  Most of the top
# row is fully transparent (verified); tile (col 7, row 1) is
# 256/256 opaque, which is what we repeat over every wall rect.  If
# you want per-edge-type tiles later (corners, doorways, etc.) this
# is where to plug them in.

_WALL_TILE_TEX: arcade.Texture | None = None


def _load_wall_tile() -> arcade.Texture:
    global _WALL_TILE_TEX
    if _WALL_TILE_TEX is None:
        from PIL import Image as _PILImage
        sheet = _PILImage.open(DUNGEON_WALL_SHEET_PNG).convert("RGBA")
        tile_col = 7
        tile_row = 1
        left = tile_col * STAR_MAZE_WALL_TILE
        top = tile_row * STAR_MAZE_WALL_TILE
        tile = sheet.crop(
            (left, top, left + STAR_MAZE_WALL_TILE,
             top + STAR_MAZE_WALL_TILE))
        _WALL_TILE_TEX = arcade.Texture(tile)
    return _WALL_TILE_TEX


def _build_wall_sprites(walls: list[Rect]) -> arcade.SpriteList:
    """Tile each wall rect with 32 × 32 instances of the dungeon wall
    tile.  Returned SpriteList draws in one GL call per frame."""
    tex = _load_wall_tile()
    tile_px = int(STAR_MAZE_WALL_TILE * STAR_MAZE_WALL_SCALE)  # 32
    lst = arcade.SpriteList()
    for r in walls:
        cols = max(1, int(math.ceil(r.w / tile_px)))
        rows = max(1, int(math.ceil(r.h / tile_px)))
        for row in range(rows):
            for col in range(cols):
                sx = r.x + col * tile_px + tile_px / 2
                sy = r.y + row * tile_px + tile_px / 2
                s = arcade.Sprite(
                    path_or_texture=tex,
                    scale=STAR_MAZE_WALL_SCALE,
                    center_x=sx,
                    center_y=sy,
                )
                lst.append(s)
    return lst


def build_wall_grid(zone: StarMazeZone) -> None:
    """Build the spatial-hash index over ``zone._walls``.  Every
    wall rect is bucketed into every grid cell it overlaps, so
    a point or circle query only has to look at a handful of
    nearby cells.  Called once per ``_generate``."""
    grid: dict[tuple[int, int], list[Rect]] = {}
    cell = zone._wall_grid_cell
    for w in zone._walls:
        gx0 = int(w.x // cell)
        gy0 = int(w.y // cell)
        gx1 = int((w.x + w.w) // cell)
        gy1 = int((w.y + w.h) // cell)
        for gy in range(gy0, gy1 + 1):
            for gx in range(gx0, gx1 + 1):
                grid.setdefault((gx, gy), []).append(w)
    zone._wall_grid = grid


def walls_near(
    zone: StarMazeZone, cx: float, cy: float, radius: float,
) -> list[Rect]:
    """Return the wall rects whose grid cells overlap the disk at
    ``(cx, cy, radius)``.  Walls may appear multiple times if
    they span more than one cell — callers that care about
    uniqueness should dedupe, but the tight inner loops here are
    already O(1) per check so it's fine."""
    if not zone._wall_grid:
        return zone._walls
    cell = zone._wall_grid_cell
    gx0 = int((cx - radius) // cell)
    gy0 = int((cy - radius) // cell)
    gx1 = int((cx + radius) // cell)
    gy1 = int((cy + radius) // cell)
    out: list[Rect] = []
    seen: set[int] = set()
    for gy in range(gy0, gy1 + 1):
        for gx in range(gx0, gx1 + 1):
            bucket = zone._wall_grid.get((gx, gy))
            if not bucket:
                continue
            for w in bucket:
                wid = id(w)
                if wid not in seen:
                    seen.add(wid)
                    out.append(w)
    return out


def segment_hits_wall_fast(
    zone: StarMazeZone, ax: float, ay: float, bx: float, by: float,
) -> bool:
    """Grid-accelerated version of
    ``segment_hits_any_wall`` — samples 4 points along the
    segment and only checks walls whose cell the sample sits
    in."""
    for t in (0.0, 0.33, 0.66, 1.0):
        x = ax + (bx - ax) * t
        y = ay + (by - ay) * t
        for w in walls_near(zone, x, y, 2.0):
            if (w.x <= x <= w.x + w.w
                    and w.y <= y <= w.y + w.h):
                return True
    return False


def point_in_any_wall_fast(
    zone: StarMazeZone, x: float, y: float,
) -> bool:
    for w in walls_near(zone, x, y, 2.0):
        if (w.x <= x <= w.x + w.w
                and w.y <= y <= w.y + w.h):
            return True
    return False


def push_out_of_maze_bounds(
    zone: StarMazeZone, entities, radius: float,
) -> None:
    """Eject any entity whose centre has drifted inside a maze's
    outer AABB.  Push it out along the shortest of the four edge
    distances and reflect velocity (if any).  Called every frame
    so non-maze aliens / wanderers can never linger inside the
    maze even if they slip through the entrance gap."""
    for e in entities:
        cx, cy = e.center_x, e.center_y
        for m in zone._mazes:
            b = m.bounds
            if not (b.x < cx < b.x + b.w
                    and b.y < cy < b.y + b.h):
                continue
            d_left = cx - b.x
            d_right = b.x + b.w - cx
            d_bot = cy - b.y
            d_top = b.y + b.h - cy
            dmin = min(d_left, d_right, d_bot, d_top)
            if dmin == d_left:
                e.center_x = b.x - radius - 1.0
                nx, ny = -1.0, 0.0
            elif dmin == d_right:
                e.center_x = b.x + b.w + radius + 1.0
                nx, ny = 1.0, 0.0
            elif dmin == d_bot:
                e.center_y = b.y - radius - 1.0
                nx, ny = 0.0, -1.0
            else:
                e.center_y = b.y + b.h + radius + 1.0
                nx, ny = 0.0, 1.0
            vx = getattr(e, "vel_x", None)
            vy = getattr(e, "vel_y", None)
            if vx is not None and vy is not None:
                v_dot_n = vx * nx + vy * ny
                if v_dot_n < 0.0:
                    e.vel_x = vx - 2.0 * v_dot_n * nx
                    e.vel_y = vy - 2.0 * v_dot_n * ny
            break


def push_out_of_walls(
    zone: StarMazeZone, entities, radius: float,
) -> None:
    """Push every entity in ``entities`` (SpriteList-like) out of
    any maze wall it overlaps.  Handles two cases:

      * Circle-vs-AABB overlap where the centre is outside the
        rect — clamp to the nearest point on the rect and push
        out along that normal (standard circle-vs-rect resolve).
      * Centre is INSIDE the rect (can happen when a wanderer
        drifts deep into a wall between ticks) — find the
        nearest edge and teleport the entity to just outside it,
        so "push-out" doesn't collapse to the ambiguous
        dist == 0 case.

    Iterates up to 5 times per entity so corner cases where
    pushing out of one wall lands the entity inside a
    neighbouring wall (T-intersections) eventually resolve.
    """
    for e in entities:
        for _iter in range(5):
            moved = resolve_one_wall_collision(zone, e, radius)
            if not moved:
                break


def resolve_one_wall_collision(
    zone: StarMazeZone, e, radius: float,
) -> bool:
    """Push ``e`` out of the first overlapping wall and return
    True if it moved.  Separated so ``_push_out_of_walls`` can
    iterate until the entity clears every neighbouring wall."""
    cx, cy = e.center_x, e.center_y
    for w in walls_near(zone, cx, cy, radius):
            inside_x = w.x < cx < w.x + w.w
            inside_y = w.y < cy < w.y + w.h
            if inside_x and inside_y:
                # Teleport out the nearest edge.
                d_left = cx - w.x
                d_right = w.x + w.w - cx
                d_bot = cy - w.y
                d_top = w.y + w.h - cy
                dmin = min(d_left, d_right, d_bot, d_top)
                if dmin == d_left:
                    e.center_x = w.x - radius - 0.5
                    nx, ny = -1.0, 0.0
                elif dmin == d_right:
                    e.center_x = w.x + w.w + radius + 0.5
                    nx, ny = 1.0, 0.0
                elif dmin == d_bot:
                    e.center_y = w.y - radius - 0.5
                    nx, ny = 0.0, -1.0
                else:
                    e.center_y = w.y + w.h + radius + 0.5
                    nx, ny = 0.0, 1.0
            else:
                qx = max(w.x, min(cx, w.x + w.w))
                qy = max(w.y, min(cy, w.y + w.h))
                dx = cx - qx
                dy = cy - qy
                dist2 = dx * dx + dy * dy
                if dist2 >= radius * radius:
                    continue
                dist = math.sqrt(dist2) if dist2 > 0 else 0.001
                nx = dx / dist if dist > 0.001 else 1.0
                ny = dy / dist if dist > 0.001 else 0.0
                pen = radius - dist + 0.5
                e.center_x += nx * pen
                e.center_y += ny * pen
            # Bounce velocity if the entity has one.
            vx = getattr(e, "vel_x", None)
            vy = getattr(e, "vel_y", None)
            if vx is not None and vy is not None:
                v_dot_n = vx * nx + vy * ny
                if v_dot_n < 0.0:
                    e.vel_x = vx - 2.0 * v_dot_n * nx
                    e.vel_y = vy - 2.0 * v_dot_n * ny
            return True
    return False
