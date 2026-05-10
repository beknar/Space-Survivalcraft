"""Per-frame companion drone tick.

Extracted from ``update_logic`` in the 2026-05-10 split.  Routes any
fired projectile into ``gv.projectile_list`` so the existing player-
projectile collision pipeline handles asteroid + alien damage,
applies alien-projectile damage to the drone, and despawns the
drone once HP hits zero.

Also threads the maze geometry to the drone's ``WaypointPlanner``
so combat / mining drones in Star Maze route around walls.  The
unified rooms / graph / doorway tables are CACHED on the zone
(``_drone_unified_geometry``) since the maze geometry never changes
after generation -- pre-cache, this rebuild allocated ~25 KB / frame
in soak runs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_view import GameView


def update_drone(gv: GameView, dt: float) -> None:
    """Advance the player's active drone (if any).  Routes any fired
    projectile into ``gv.projectile_list`` so the existing player-
    projectile collision code handles asteroid + alien damage,
    applies alien-projectile damage to the drone, and despawns the
    drone once HP hits zero.

    Called every frame by ``GameView.on_update``; cheap when no
    drone is deployed (single early return)."""
    drone = getattr(gv, "_active_drone", None)
    if drone is None:
        return
    zone = getattr(gv, "_zone", None)
    rooms = None
    room_graph = None
    doorways = None
    room_to_exit_room = None
    exit_xy_by_room = None
    exit_outer_xy_by_room = None
    if zone is not None:
        mazes = getattr(zone, "_mazes", None)
        if mazes:
            rooms = []
            room_graph = {}
            doorways = {}
            room_to_exit_room = {}
            exit_xy_by_room = {}
            exit_outer_xy_by_room = {}
            offset = 0
            for m in mazes:
                rooms.extend(m.rooms)
                for k, neighbours in m.room_graph.items():
                    room_graph[k + offset] = [n + offset for n in neighbours]
                for edge_key, midpoint in (
                        getattr(m, "doorways", None) or {}).items():
                    a, b = tuple(edge_key)
                    doorways[frozenset((a + offset, b + offset))] = midpoint
                exit_room = getattr(m, "entrance_room", 0) + offset
                exit_xy = getattr(m, "entrance_xy", (0.0, 0.0))
                exit_outer_xy = getattr(
                    m, "entrance_xy_outer", exit_xy)
                for k in m.room_graph:
                    room_to_exit_room[k + offset] = exit_room
                    exit_xy_by_room[k + offset] = exit_xy
                    exit_outer_xy_by_room[k + offset] = exit_outer_xy
                offset += len(m.rooms)
    drone.attach_maze_planner(
        rooms, room_graph, doorways,
        room_to_exit_room, exit_xy_by_room,
        exit_outer_xy_by_room)
    prev_drone_x = drone.center_x
    prev_drone_y = drone.center_y
    fired = drone.update_drone(dt, gv)
    if fired is not None:
        gv.projectile_list.append(fired)
    zone = getattr(gv, "_zone", None)
    seg_check = getattr(zone, "_segment_hits_wall_fast", None)
    if seg_check is not None and seg_check(
            prev_drone_x, prev_drone_y,
            drone.center_x, drone.center_y):
        drone.center_x = prev_drone_x
        drone.center_y = prev_drone_y
    push = getattr(zone, "_push_out_of_walls", None)
    if push is not None:
        for _ in range(5):
            px, py = drone.center_x, drone.center_y
            push([drone], drone.radius)
            if drone.center_x == px and drone.center_y == py:
                break
    import math as _m
    r = drone.radius
    proj_lists = [getattr(gv, "alien_projectile_list", None),
                  getattr(gv, "_boss_projectile_list", None)]
    for plist in proj_lists:
        if plist is None:
            continue
        for proj in list(plist):
            if _m.hypot(proj.center_x - drone.center_x,
                        proj.center_y - drone.center_y) <= r + 8.0:
                drone.take_damage(int(getattr(proj, "damage", 0)))
                proj.remove_from_sprite_lists()
                if drone.dead:
                    break
        if drone.dead:
            break
    if drone.dead:
        from combat_helpers import spawn_explosion
        spawn_explosion(gv, drone.center_x, drone.center_y)
        drone.remove_from_sprite_lists()
        gv._active_drone = None
