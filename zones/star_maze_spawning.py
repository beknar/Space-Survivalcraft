"""Spawn / entourage helpers extracted from ``zones.star_maze``.

The Star Maze populates each maze with a centre spawner + entourage
of ``MAZE_SPAWNER_INITIAL_ALIENS`` MazeAliens, plus stalkers placed
at random points outside every maze AABB.  This module owns those
generation helpers; ``StarMazeZone`` keeps thin one-line wrappers
that delegate to the module-level functions.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

import arcade

from constants import MAZE_ALIEN_RADIUS
from zones.maze_geometry import (
    MazeLayout, generate_all_mazes,
    circle_hits_any_wall,
)
from sprites.maze_alien import MazeAlien
from sprites.maze_spawner import MazeSpawner

from zones import star_maze_walls

if TYPE_CHECKING:
    from game_view import GameView
    from zones.star_maze import StarMazeZone


def generate(zone: StarMazeZone, gv: GameView) -> None:
    zone._mazes = generate_all_mazes(zone_seed=zone._world_seed)
    zone._rooms = []
    zone._walls = []
    for m in zone._mazes:
        zone._rooms.extend(m.rooms)
        zone._walls.extend(m.walls)
    star_maze_walls.build_wall_grid(zone)
    # One spawner per maze, anchored at the maze centre.
    zone._spawners = arcade.SpriteList()
    for i, m in enumerate(zone._mazes):
        sp = MazeSpawner(m.spawner[0], m.spawner[1])
        sp.uid = i + 1   # uid 0 reserved for "unlinked"
        zone._spawners.append(sp)

    # Pre-populate each spawner with the standard "spawner came
    # online" entourage (10 maze aliens — see
    # ``MAZE_SPAWNER_INITIAL_ALIENS``).  ``_spawn_entourage`` does
    # the actual room-pick + sprite construction and is reused
    # per-frame whenever a respawned spawner sets the
    # ``just_respawned`` latch.
    from constants import MAZE_SPAWNER_INITIAL_ALIENS
    prep_rng = random.Random(zone._world_seed + 977)
    for sp, maze in zip(zone._spawners, zone._mazes):
        spawn_entourage(zone, sp, maze,
                        MAZE_SPAWNER_INITIAL_ALIENS,
                        gv, rng=prep_rng)
        sp.just_respawned = False  # initial spawn already covered

    # Nebula-style population (asteroids, gas, wanderers, null
    # fields, slipspaces, four Z2 alien types) — same counts as
    # Zone 2, reject_fn keeps every candidate out of the four
    # maze AABBs (plus 40 px margin).
    from zones.nebula_shared import populate_nebula_content
    from constants import ASTEROID_RADIUS
    # Radii picked to keep each entity's full body outside the
    # maze AABB.  Gas sizes top out at 384 px (radius 192).
    populate_nebula_content(
        zone, gv,
        reject_iron=zone._maze_reject_fn(radius=ASTEROID_RADIUS),
        reject_big_iron=zone._maze_reject_fn(
            radius=ASTEROID_RADIUS * 2.0),
        reject_copper=zone._maze_reject_fn(radius=ASTEROID_RADIUS),
        reject_gas=zone._maze_reject_fn(radius=192.0),
        reject_wanderers=zone._maze_reject_fn(radius=30.0),
        reject_aliens=zone._maze_reject_fn(radius=24.0),
        reject_null=zone._maze_reject_fn(radius=100.0),
        reject_slip=zone._maze_reject_fn(radius=60.0),
    )
    populate_stalkers(zone, gv)


def spawn_entourage(
    zone: StarMazeZone,
    sp: MazeSpawner, maze: MazeLayout,
    count: int, gv: GameView,
    rng: random.Random | None = None,
) -> int:
    """Spawn up to ``count`` MazeAliens around ``sp``, capped by
    ``MAZE_SPAWNER_MAX_ALIVE - sp.alive_children``.  Returns the
    number actually spawned.  Aliens are placed in random rooms
    of the spawner's home maze (with no repeats while rooms are
    available) so an entourage of 10 spreads across the maze
    instead of stacking on top of the spawner."""
    from constants import MAZE_SPAWNER_MAX_ALIVE
    free_slots = MAZE_SPAWNER_MAX_ALIVE - sp.alive_children
    n = min(count, max(0, free_slots))
    if n <= 0:
        return 0
    if rng is None:
        rng = random
    bounds = (maze.bounds.x, maze.bounds.y,
              maze.bounds.w, maze.bounds.h)
    room_sample = list(maze.rooms)
    rng.shuffle(room_sample)
    rooms_pick = room_sample[:n]
    while len(rooms_pick) < n:
        rooms_pick.append(rng.choice(maze.rooms))
    for room in rooms_pick:
        ax = room.x + room.w / 2 + rng.uniform(
            -room.w / 4, room.w / 4)
        ay = room.y + room.h / 2 + rng.uniform(
            -room.h / 4, room.h / 4)
        alien = MazeAlien(
            gv._alien_laser_tex, ax, ay,
            world_w=zone.world_width,
            world_h=zone.world_height,
            patrol_home=(ax, ay),
            patrol_radius=max(80.0, room.w / 2.0 - 40.0),
            maze_bounds=bounds,
            rooms=maze.rooms,
            room_graph=maze.room_graph,
            doorways=getattr(maze, "doorways", None),
        )
        zone._maze_aliens.append(alien)
        zone._alien_parent[alien] = sp.uid
        sp.alive_children += 1
    return n


def populate_stalkers(zone: StarMazeZone, gv: GameView) -> None:
    """Drop ``STALKER_COUNT`` stalkers at random outside-the-maze
    positions.  Uses the same rejection contract as Z2 aliens
    (radius 30 px keeps the stalker body out of any maze AABB)
    and seeds off the world seed so the layout is deterministic
    across save / load.

    ``gv._missile_tex`` is loaded by GameView's consumable-tex
    init pass, so it's safe to read here from ``setup``.
    """
    from constants import STALKER_COUNT, STALKER_RADIUS
    from sprites.stalker import Stalker
    rng = random.Random(zone._world_seed + 401)
    reject = zone._maze_reject_fn(radius=STALKER_RADIUS)
    margin = 200.0
    attempts_per = 40
    for _ in range(STALKER_COUNT):
        for _try in range(attempts_per):
            sx = rng.uniform(margin, zone.world_width - margin)
            sy = rng.uniform(margin, zone.world_height - margin)
            if not reject(sx, sy):
                zone._stalkers.append(
                    Stalker(gv._missile_tex, sx, sy,
                            world_w=zone.world_width,
                            world_h=zone.world_height))
                break


def update_spawners(zone: StarMazeZone, gv: GameView, dt: float,
                    px: float, py: float) -> None:
    # Note: update_spawner still needs to run on killed spawners
    # so its respawn cooldown ticks down — the spawner
    # self-resurrects inside update_spawner when the timer hits
    # zero.  When the player is cloaked by a null field, pass the
    # synthetic far-away position so spawners stop detecting +
    # firing; their spawn cadence still ticks so the maze stays
    # populated when the player uncloaks.
    from update_logic import player_is_cloaked
    if player_is_cloaked(gv):
        ai_px, ai_py = px + 1e9, py + 1e9
    else:
        ai_px, ai_py = px, py
    from update_logic import emit_alien_shots
    for sp in zone._spawners:
        fired, should_spawn = sp.update_spawner(
            dt, ai_px, ai_py, gv._alien_laser_tex)
        emit_alien_shots(gv, zone._maze_projectiles, fired)
        if should_spawn:
            spawn_child(zone, sp, gv._alien_laser_tex)
        # Respawn entourage — when a killed spawner's timer
        # ticks to zero it sets ``just_respawned``; drop a fresh
        # entourage of MAZE_SPAWNER_INITIAL_ALIENS around it
        # (capped by the alive-cap) and clear the latch.
        if sp.just_respawned:
            from constants import MAZE_SPAWNER_INITIAL_ALIENS
            maze = maze_for_spawner(zone, sp)
            if maze is not None:
                spawn_entourage(
                    zone, sp, maze, MAZE_SPAWNER_INITIAL_ALIENS, gv)
            sp.just_respawned = False


def spawn_child(zone: StarMazeZone, sp: MazeSpawner,
                laser_tex: arcade.Texture) -> None:
    """Emit one MazeAlien near the spawner's centre room.  Patrol
    radius is scoped to one room (not the whole maze) so
    waypoints stay reachable without walking through walls.
    The maze AABB is passed through so the alien is hard-bounded
    from leaving its home maze."""
    from constants import STAR_MAZE_ROOM_SIZE
    maze = maze_for_spawner(zone, sp)
    if maze is not None:
        ax, ay = find_maze_interior_point(zone, sp)
        home_xy = (ax, ay)
        bounds = (maze.bounds.x, maze.bounds.y,
                  maze.bounds.w, maze.bounds.h)
    else:
        home_xy = (sp.center_x, sp.center_y)
        ax = sp.center_x
        ay = sp.center_y + MAZE_ALIEN_RADIUS * 2 + 4
        bounds = None
    patrol_r = max(80.0, STAR_MAZE_ROOM_SIZE / 2.0 - 40.0)
    alien = MazeAlien(
        laser_tex, ax, ay,
        world_w=zone.world_width,
        world_h=zone.world_height,
        patrol_home=home_xy,
        patrol_radius=patrol_r,
        maze_bounds=bounds,
        rooms=maze.rooms if maze is not None else None,
        room_graph=maze.room_graph if maze is not None else None,
        doorways=(getattr(maze, "doorways", None)
                  if maze is not None else None),
    )
    zone._maze_aliens.append(alien)
    zone._alien_parent[alien] = sp.uid
    sp.alive_children += 1


def maze_for_spawner(zone: StarMazeZone,
                     sp: MazeSpawner) -> MazeLayout | None:
    """Return the MazeLayout whose centre matches ``sp``'s
    position.  Uses the spawner's uid (1-indexed) to index into
    ``zone._mazes`` — O(1) instead of a position search."""
    idx = sp.uid - 1
    if 0 <= idx < len(zone._mazes):
        return zone._mazes[idx]
    return None


def find_maze_interior_point(
    zone: StarMazeZone, sp: MazeSpawner,
) -> tuple[float, float]:
    """Pick a free point within a short radius of the spawner."""
    for _ in range(40):
        ax = sp.center_x + random.uniform(-120.0, 120.0)
        ay = sp.center_y + random.uniform(-120.0, 120.0)
        if not circle_hits_any_wall(
                ax, ay, MAZE_ALIEN_RADIUS + 4, zone._walls):
            return ax, ay
    return sp.center_x, sp.center_y
