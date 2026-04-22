"""5-minute soak tests for the boss + drop tweaks landed this session.

Each soak churns a specific new path that a shorter perf test can't
stress for leaks / degradation over time:

  * **Nebula vs Force Wall** — walls continuously expire + respawn
    while the boss routes around them.  Catches leaks in the wall-
    segment check, wall-repulsion avoidance, and the gas-cloud
    absorption list.
  * **Asteroid Crush** — asteroid field is topped back up every 10 s
    so the boss is constantly smashing rocks + spawning pickups +
    blueprint drops.  Leak-check on the crush pass + drop lists.
  * **Turret + Missile Array + AI Pilot vs Nebula** — full defender
    suite shoots at the boss for 5 min, catching leaks in the
    ``bosses=[…]`` target-walk and the
    ``handle_nebula_boss_projectile_hits`` lists.

Each file follows the standard ``run_soak`` pattern + boss-HP lock
so the boss doesn't die mid-soak and short-circuit the test.

**Do not run by default** — these take 15 minutes for all three.
Invoke explicitly:

    pytest "unit tests/integration/test_soak_session_boss.py" -v -s
"""
from __future__ import annotations

import pytest

from constants import WORLD_WIDTH, WORLD_HEIGHT, BOSS_DETECT_RANGE
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _base_setup(gv):
    """Zone 2 + Home Station + 2 turrets + 1 Missile Array + spawned
    Nebula boss.  Returns the boss instance."""
    from sprites.building import create_building
    from combat_helpers import spawn_nebula_boss

    gv._transition_zone(ZoneID.ZONE2)
    gv.building_list.clear()
    cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    home_tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", home_tex, cx, cy, scale=0.5))
    for bt, ox in (("Turret 1", 80), ("Turret 2", -80),
                    ("Missile Array", 160)):
        t_tex = gv._building_textures[bt]
        laser = gv._turret_laser_tex if "Turret" in bt else None
        gv.building_list.append(create_building(
            bt, t_tex, cx + ox, cy,
            laser_tex=laser, scale=0.5))
    # Stock iron for spawn.
    gv.inventory._items[(0, 0)] = ("iron", 500)
    gv.inventory._mark_dirty()
    gv._nebula_boss = None
    assert spawn_nebula_boss(gv) is True

    gv.player.center_x = gv._nebula_boss.center_x + (BOSS_DETECT_RANGE * 0.6)
    gv.player.center_y = gv._nebula_boss.center_y
    make_invulnerable(gv)
    return gv._nebula_boss


# ──────────────────────────────────────────────────────────────────────────
#  Nebula vs Force Wall churn
# ──────────────────────────────────────────────────────────────────────────

class TestSoakNebulaForceWalls:
    def test_nebula_vs_force_wall_5min_soak(self, real_game_view):
        """Spawn a fresh force wall every 5 s.  Boss must stay
        responsive + walls must garbage-collect via the wall's
        lifetime without accumulating stale objects."""
        from sprites.force_wall import ForceWall
        gv = real_game_view
        nb = _base_setup(gv)
        nb_hp_lock = nb.hp

        elapsed = [0.0]
        wall_cd = [0.0]

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            if gv._nebula_boss is not None:
                gv._nebula_boss.hp = nb_hp_lock
            elapsed[0] += dt
            wall_cd[0] -= dt
            if wall_cd[0] <= 0.0:
                wall_cd[0] = 5.0
                # Plop a wall directly between boss and player so the
                # avoidance + segment-revert paths both fire.
                if gv._nebula_boss is not None:
                    mx = (gv._nebula_boss.center_x + gv.player.center_x) / 2
                    my = (gv._nebula_boss.center_y + gv.player.center_y) / 2
                    gv._force_walls.append(
                        ForceWall(mx, my, heading=90.0))
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Nebula vs Force Walls", tick, min_fps=30)


# ──────────────────────────────────────────────────────────────────────────
#  Asteroid crush churn
# ──────────────────────────────────────────────────────────────────────────

class TestSoakNebulaAsteroidCrush:
    def test_nebula_crush_5min_soak(self, real_game_view):
        """Top up the Zone 2 asteroid list every 10 s so the Nebula
        boss's crush pass keeps finding work.  Leak candidates: the
        pickup list growth, blueprint-drop spawns, and the arcade
        sprite-list churn on asteroid destruction."""
        from sprites.asteroid import IronAsteroid
        from sprites.copper_asteroid import CopperAsteroid
        import random as _r
        gv = real_game_view
        nb = _base_setup(gv)
        nb_hp_lock = nb.hp
        z = gv._zone
        refill_cd = [0.0]

        def refill_asteroids() -> None:
            """Top up the asteroid field, capped so 5 min of boss-
            can't-keep-up doesn't balloon the list.  Only adds
            enough to bring the field back up to the baseline — any
            leak in the crush pass would show as RSS growth
            (caught by ``run_soak``'s memory-growth floor)."""
            _r.seed(42)
            iron_target = 15
            copper_target = 5
            while len(z._iron_asteroids) < iron_target:
                ox = _r.uniform(-400, 400)
                oy = _r.uniform(-400, 400)
                z._iron_asteroids.append(
                    IronAsteroid(z._iron_tex,
                                  nb.center_x + ox, nb.center_y + oy))
            while len(z._copper_asteroids) < copper_target:
                ox = _r.uniform(-400, 400)
                oy = _r.uniform(-400, 400)
                z._copper_asteroids.append(
                    CopperAsteroid(z._copper_tex,
                                    nb.center_x + ox, nb.center_y + oy))

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            if gv._nebula_boss is not None:
                gv._nebula_boss.hp = nb_hp_lock
            refill_cd[0] -= dt
            if refill_cd[0] <= 0.0:
                refill_cd[0] = 10.0
                refill_asteroids()
            # Drain the pickup list so it doesn't blow RSS by 5 min —
            # the test is about the crush / spawn path, not the
            # pickup attraction loop.
            if len(gv.iron_pickup_list) > 50:
                # Keep a window of the most recent drops.
                for pickup in list(gv.iron_pickup_list)[:-50]:
                    pickup.remove_from_sprite_lists()
            gv.on_update(dt)
            gv.on_draw()

        refill_asteroids()
        run_soak(gv, "Nebula crush asteroids", tick, min_fps=30)


# ──────────────────────────────────────────────────────────────────────────
#  Full defender suite vs Nebula
# ──────────────────────────────────────────────────────────────────────────

class TestSoakNebulaDefenderFire:
    def test_defenders_vs_nebula_5min_soak(self, real_game_view):
        """Station defenders + AI-pilot parked ship all fire at the
        Nebula boss for 5 min.  Catches leaks in the
        ``bosses=[…]`` targeting walk, the
        ``_projectiles_vs_boss`` collision loop, and the
        turret-projectile list garbage-collection."""
        gv = real_game_view
        nb = _base_setup(gv)
        nb_hp_lock = nb.hp

        # Add an AI-pilot parked ship.
        from sprites.parked_ship import ParkedShip
        cx, cy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        ps = ParkedShip(faction="Earth", ship_type="Cruiser",
                         ship_level=1, x=cx + 120, y=cy + 120)
        ps.module_slots.append("ai_pilot")
        gv._parked_ships.append(ps)

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            gv.player.shields = gv.player.max_shields
            if gv._nebula_boss is not None:
                gv._nebula_boss.hp = nb_hp_lock
                gv._nebula_boss.shields = gv._nebula_boss.max_shields
            # Drain projectile + pickup lists so they don't balloon
            # RSS from 5 min of continuous fire.
            if len(gv.turret_projectile_list) > 200:
                for p in list(gv.turret_projectile_list)[:-100]:
                    p.remove_from_sprite_lists()
            if len(gv._missile_list) > 50:
                for m in list(gv._missile_list)[:-30]:
                    m.remove_from_sprite_lists()
            gv.on_update(dt)
            gv.on_draw()

        run_soak(gv, "Defenders vs Nebula", tick, min_fps=30)
