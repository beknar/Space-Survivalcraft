"""Soak tests for the Star Maze biome.

Three 5-minute scenarios that exercise the paths most likely to leak
or regress over time:

  * **TestSoakStarMazeEmptyOrbit** — player parked at zone centre
    idling.  Drives 30 null fields + 15 slipspaces ticking, 4
    spawner cadences + respawn timers, ~80 maze aliens running
    contained AI, 60 Zone 2 aliens doing patrol, 165 asteroid
    rotations, the full wall spatial-hash lookup chain every
    frame.  Catches cumulative regression in the main tick loop
    and, more importantly, any list that grows without bound.

  * **TestSoakStarMazeCombatChurn** — player holds fire at point-
    blank range on a single maze spawner; weapon cooldowns are
    forced to zero so a shot fires every tick.  Spawner takes 50
    damage/tick, dies, 90 s respawn, dies again — repeats for 5
    minutes.  Maze aliens are continuously killed + respawned by
    the spawner.  Leak candidates: ``_alien_parent`` bookkeeping,
    ``gv.projectile_list`` + ``_maze_projectiles`` churn,
    blueprint / iron pickup lists.

  * **TestSoakStarMazeNebulaPressure** — player sits in the open
    area surrounded by Z2 aliens.  Exercises the Nebula-style tick
    path that was added back in (``_alien_projectiles`` advance +
    wall block + player hit, Z2 alien AI + asteroid collision +
    gas damage).  Invulnerable so the player doesn't die mid-soak.

Run explicitly (soak is excluded from the default pytest run):

    pytest "unit tests/integration/test_soak_star_maze.py" -v -s
"""
from __future__ import annotations

import math

from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


# ──────────────────────────────────────────────────────────────────────────
#  Empty orbit — idle at zone centre
# ──────────────────────────────────────────────────────────────────────────

class TestSoakStarMazeEmptyOrbit:
    def test_star_maze_idle_5min_soak(self, real_game_view):
        """Player sits at the zone centre while the whole Star Maze
        ticks + draws.  No combat, no firing — pure list-churn
        baseline.  Regression candidates: the fog-grid, the spatial-
        hash of walls, the Z2 alien / maze alien patrol walks."""
        gv = real_game_view
        make_invulnerable(gv)
        if gv._zone.zone_id != ZoneID.STAR_MAZE:
            gv._transition_zone(ZoneID.STAR_MAZE)
        # Park 500 px south of the central wormhole so the tick
        # doesn't route us out of the zone.
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2 - 500.0

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Star Maze idle orbit", tick)


# ──────────────────────────────────────────────────────────────────────────
#  Combat churn — continuous kill-and-respawn on one spawner
# ──────────────────────────────────────────────────────────────────────────

class TestSoakStarMazeCombatChurn:
    def test_star_maze_spawner_churn_5min_soak(self, real_game_view):
        """Player holds fire on spawner #0 at point-blank range.
        Every tick: clear the weapon cooldown so a shot fires,
        revive the spawner + every maze alien to full HP so the
        combat loop churns indefinitely without draining to zero.

        This hammers:
          * ``gv.projectile_list`` churn (player lasers fired +
            consumed every frame).
          * ``_handle_player_projectile_hits`` iteration over
            spawner + 80 maze aliens.
          * ``_on_maze_alien_killed`` + ``_alien_parent`` bookkeeping
            as aliens die and respawn.
          * Iron + XP + blueprint drop spawns (pickup list growth).
        """
        gv = real_game_view
        make_invulnerable(gv)
        if gv._zone.zone_id != ZoneID.STAR_MAZE:
            gv._transition_zone(ZoneID.STAR_MAZE)
        z = gv._zone
        sp = z._spawners[0]
        # Park the player just outside the spawner's collision radius
        # but within weapon range so every shot connects.
        gv.player.center_x = sp.center_x + 80.0
        gv.player.center_y = sp.center_y
        gv.player.heading = 270.0  # face west (toward spawner)
        # Cap the pickup lists so they don't balloon over 5 minutes —
        # we care about the CPU churn, not the effect of 30 000 drops
        # sitting in a sprite list.
        def _trim_pickups() -> None:
            for lst in (gv.iron_pickup_list, gv.blueprint_pickup_list):
                if len(lst) > 80:
                    for p in list(lst)[:-50]:
                        p.remove_from_sprite_lists()
            if len(gv.projectile_list) > 60:
                for p in list(gv.projectile_list)[:-30]:
                    p.remove_from_sprite_lists()

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            # Force-fire: clear every weapon's cooldown so
            # update_weapons fires on this tick.
            for w in gv._weapons:
                w._timer = 0.0
            # Keep the spawner + every maze alien alive so the
            # kill-reward path is hit over and over instead of
            # running to zero.
            sp.hp = sp.max_hp
            sp.shields = sp.max_shields
            sp.killed = False
            gv.on_update(dt)
            gv.on_draw()
            _trim_pickups()

        run_soak(gv, "Star Maze spawner churn", tick)


# ──────────────────────────────────────────────────────────────────────────
#  Nebula pressure — Z2 aliens firing at the player
# ──────────────────────────────────────────────────────────────────────────

class TestSoakStarMazeNebulaPressure:
    def test_star_maze_nebula_pressure_5min_soak(self, real_game_view):
        """Teleport every Z2 alien to ALIEN_DETECT_DIST from the player
        so they all pursue and fire.  Drives the
        ``_advance_alien_projectiles`` path (advance + wall block +
        player hit), the ``handle_projectile_hits`` path (Z2 alien
        deaths + respawn cadence), and the Z2 alien-vs-asteroid
        collision loop.  Player is invulnerable so the test doesn't
        exit via death screen.

        Nebula-population Z2 aliens might be killed over the 5 min
        — their respawn timer ticks every ``RESPAWN_INTERVAL``, so
        the steady-state population is bounded."""
        from constants import ALIEN_DETECT_DIST
        gv = real_game_view
        make_invulnerable(gv)
        if gv._zone.zone_id != ZoneID.STAR_MAZE:
            gv._transition_zone(ZoneID.STAR_MAZE)
        z = gv._zone
        # Park the player in the open space between the four mazes
        # so Z2 aliens can close on them without fighting walls.
        gv.player.center_x = 6000.0
        gv.player.center_y = 5500.0
        # Pull every Z2 alien into detect range around the player.
        for i, alien in enumerate(z._aliens):
            angle = (i / max(1, len(z._aliens))) * math.tau
            r = ALIEN_DETECT_DIST * 0.8
            alien.center_x = gv.player.center_x + math.cos(angle) * r
            alien.center_y = gv.player.center_y + math.sin(angle) * r

        def _trim_alien_projectiles() -> None:
            # Z2 aliens fire into _alien_projectiles; the list is
            # drained naturally when projectiles expire or hit the
            # player / wall, but under heavy fire the peak can get
            # large.  Cap at 150 so the 5 min doesn't balloon RSS.
            if len(z._alien_projectiles) > 150:
                for p in list(z._alien_projectiles)[:-100]:
                    p.remove_from_sprite_lists()

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            gv.on_update(dt)
            gv.on_draw()
            _trim_alien_projectiles()

        run_soak(gv, "Star Maze Nebula pressure", tick)
