"""Pure-function geometry helpers for the Star Maze.

All math here is deterministic given the same RNG seed so save/load
round-trips and tests stay stable.  Room layout is a uniform 9×9
grid equally spaced across a ``STAR_MAZE_WIDTH`` × ``STAR_MAZE_HEIGHT``
zone (per user spec: "mazes should be their own units, separate from
each other, and should be equally spaced from each other").  Each
room has four thick walls with two door gaps carved into opposite
sides — minimum guarantee of one way in and one way out, wide enough
for a ship to U-turn inside.
"""
from __future__ import annotations

import random
from typing import NamedTuple

from constants import (
    STAR_MAZE_WIDTH, STAR_MAZE_HEIGHT,
    STAR_MAZE_ROOM_SIZE, STAR_MAZE_ROOM_COLS, STAR_MAZE_ROOM_ROWS,
    STAR_MAZE_WALL_THICK, STAR_MAZE_DOOR_WIDTH,
)


# ``Rect`` is intentionally (x, y, w, h) with lower-left-origin coords
# so it composes directly with ``arcade.LBWH``.
class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float


def room_rects(
    world_w: int = STAR_MAZE_WIDTH,
    world_h: int = STAR_MAZE_HEIGHT,
    cols: int = STAR_MAZE_ROOM_COLS,
    rows: int = STAR_MAZE_ROOM_ROWS,
    size: int = STAR_MAZE_ROOM_SIZE,
) -> list[Rect]:
    """Return 81 room AABBs laid out on a ``cols × rows`` grid.

    Spacing: total row width is ``cols × size + (cols + 1) × gap``
    where ``gap`` is chosen so rooms + gaps fill the world exactly.
    With the default 9×9 grid this gives a gap of ~420 px — plenty
    of room for a ship plus a wandering asteroid between rooms.
    """
    gap_x = (world_w - cols * size) / (cols + 1)
    gap_y = (world_h - rows * size) / (rows + 1)
    out: list[Rect] = []
    for row in range(rows):
        for col in range(cols):
            x = gap_x + col * (size + gap_x)
            y = gap_y + row * (size + gap_y)
            out.append(Rect(x, y, size, size))
    return out


def _split_wall_around_door(
    wall_start: float,
    wall_end: float,
    door_centre: float,
    door_width: float,
) -> list[tuple[float, float]]:
    """Return the ``[start, end)`` segments of the wall remaining after
    a door gap is cut at ``door_centre``.  Clamped to the wall extents
    so a door near a corner leaves only the un-cut segment."""
    door_lo = door_centre - door_width / 2
    door_hi = door_centre + door_width / 2
    segments: list[tuple[float, float]] = []
    if door_lo > wall_start:
        segments.append((wall_start, min(wall_end, door_lo)))
    if door_hi < wall_end:
        segments.append((max(wall_start, door_hi), wall_end))
    # Filter zero-length segments (e.g. door exactly at the corner).
    return [(s, e) for (s, e) in segments if e - s > 0.5]


def wall_rects_for_room(
    room: Rect,
    *,
    seed: int,
    wall_thick: int = STAR_MAZE_WALL_THICK,
    door_width: int = STAR_MAZE_DOOR_WIDTH,
) -> list[Rect]:
    """Return the AABB wall rects around ``room`` with two door gaps.

    Two openings are placed on opposite sides (top/bottom or left/
    right) with ``seed``-determined lateral offsets.  Corner tiles
    stay wall so the door is inset from the corners, keeping the
    dungeon outline recognisable.
    """
    rng = random.Random(seed)
    # Door axis — horizontal (top+bottom) or vertical (left+right).
    axis = rng.choice(("horizontal", "vertical"))
    # Random door centre within the room interior, inset so the gap
    # doesn't land against a corner.
    inset = wall_thick + door_width / 2 + 8
    door_min_x = room.x + inset
    door_max_x = room.x + room.w - inset
    door_min_y = room.y + inset
    door_max_y = room.y + room.h - inset

    door_top_x = rng.uniform(door_min_x, door_max_x)
    door_bot_x = rng.uniform(door_min_x, door_max_x)
    door_lef_y = rng.uniform(door_min_y, door_max_y)
    door_rig_y = rng.uniform(door_min_y, door_max_y)

    # Horizontal walls (top + bottom) run along x; vertical walls
    # (left + right) run along y.
    top_cuts: list[tuple[float, float]]
    bot_cuts: list[tuple[float, float]]
    lef_cuts: list[tuple[float, float]]
    rig_cuts: list[tuple[float, float]]
    if axis == "horizontal":
        top_cuts = _split_wall_around_door(
            room.x, room.x + room.w, door_top_x, door_width)
        bot_cuts = _split_wall_around_door(
            room.x, room.x + room.w, door_bot_x, door_width)
        lef_cuts = [(room.y, room.y + room.h)]
        rig_cuts = [(room.y, room.y + room.h)]
    else:
        top_cuts = [(room.x, room.x + room.w)]
        bot_cuts = [(room.x, room.x + room.w)]
        lef_cuts = _split_wall_around_door(
            room.y, room.y + room.h, door_lef_y, door_width)
        rig_cuts = _split_wall_around_door(
            room.y, room.y + room.h, door_rig_y, door_width)

    walls: list[Rect] = []
    top_y = room.y + room.h - wall_thick
    bot_y = room.y
    lef_x = room.x
    rig_x = room.x + room.w - wall_thick
    for (sx, ex) in top_cuts:
        walls.append(Rect(sx, top_y, ex - sx, wall_thick))
    for (sx, ex) in bot_cuts:
        walls.append(Rect(sx, bot_y, ex - sx, wall_thick))
    for (sy, ey) in lef_cuts:
        walls.append(Rect(lef_x, sy, wall_thick, ey - sy))
    for (sy, ey) in rig_cuts:
        walls.append(Rect(rig_x, sy, wall_thick, ey - sy))
    return walls


def all_wall_rects(rooms: list[Rect], *, zone_seed: int = 0) -> list[Rect]:
    """Every wall in the maze, flat list.  Each room's walls are
    generated with a seed derived from the room index + ``zone_seed``
    so the layout is reproducible across save/load."""
    out: list[Rect] = []
    for i, room in enumerate(rooms):
        out.extend(wall_rects_for_room(room, seed=zone_seed * 131 + i * 17))
    return out


# ── Point/rect tests ────────────────────────────────────────────────

def point_in_rect(x: float, y: float, r: Rect) -> bool:
    return r.x <= x <= r.x + r.w and r.y <= y <= r.y + r.h


def point_in_any(x: float, y: float, rects: list[Rect]) -> bool:
    for r in rects:
        if point_in_rect(x, y, r):
            return True
    return False


def circle_overlaps_rect(
    cx: float, cy: float, radius: float, r: Rect,
) -> bool:
    """Classic circle-vs-AABB overlap: clamp the circle centre to the
    rect and check distance to the clamped point.  Used for the player
    ship + maze-aliens' wall collision."""
    qx = max(r.x, min(cx, r.x + r.w))
    qy = max(r.y, min(cy, r.y + r.h))
    dx = cx - qx
    dy = cy - qy
    return dx * dx + dy * dy <= radius * radius


def circle_hits_any_wall(
    cx: float, cy: float, radius: float, walls: list[Rect],
) -> bool:
    for w in walls:
        if circle_overlaps_rect(cx, cy, radius, w):
            return True
    return False


def segment_hits_any_wall(
    ax: float, ay: float, bx: float, by: float, walls: list[Rect],
) -> bool:
    """Cheap segment-vs-rect test — samples 4 interpolated points and
    checks each with ``point_in_any_rect``.  For projectile vs wall
    where the segment is at most ~10 px per tick, this is plenty.
    """
    for t in (0.0, 0.33, 0.66, 1.0):
        x = ax + (bx - ax) * t
        y = ay + (by - ay) * t
        for w in walls:
            if point_in_rect(x, y, w):
                return True
    return False


# ── Population exclusion ────────────────────────────────────────────

def point_inside_any_room_interior(
    x: float, y: float,
    rooms: list[Rect],
    margin: float = 0.0,
) -> bool:
    """Used when populating the zone's open area with asteroids / gas
    / null fields.  Any candidate position inside a room (plus a
    margin) is rejected so the maze interiors stay empty for spawner
    combat.  ``margin`` can push the exclusion slightly past the room
    walls so asteroids don't spawn flush against a wall from outside.
    """
    for r in rooms:
        if (r.x - margin <= x <= r.x + r.w + margin
                and r.y - margin <= y <= r.y + r.h + margin):
            return True
    return False
