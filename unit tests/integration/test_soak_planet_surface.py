"""Soak test for the planet surface (on-foot slice).

A 5-minute scenario: the player walks a back-and-forth patrol while
holding the mining beam on a field of resource nodes whose HP is revived
each tick, so the mining-projectile-vs-node loop + ground/node draws +
on-foot movement churn indefinitely.  Leak candidates: ``gv.projectile_list``
churn, the per-frame node-collision + push-out walk, HitSpark/explosion
spawns.

Run explicitly (soak is excluded from the default pytest run):
    pytest "unit tests/integration/test_soak_planet_surface.py" -v -s
"""
from __future__ import annotations

import arcade

from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


class TestSoakPlanetSurface:
    def test_surface_walk_and_mine_5min_soak(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        make_invulnerable(gv)
        z = gv._zone
        # Park mid-field, away from the bottom lift-off edge.
        gv.player.center_x = z.world_width / 2
        gv.player.center_y = z.world_height / 2
        gv._weapon_idx = 1                    # portable mining beam
        gv._keys.add(arcade.key.SPACE)

        # Patrol state: flip walk direction every ~2 s so the player
        # never reaches an edge.
        state = {"dir": 1, "frames": 0}

        def _trim_projectiles() -> None:
            if len(gv.projectile_list) > 60:
                for p in list(gv.projectile_list)[:-30]:
                    p.remove_from_sprite_lists()

        def tick(dt: float) -> None:
            gv.player.hp = gv.player.max_hp
            # Keep nodes alive so the mining loop churns every frame
            # instead of running the field to zero in a few seconds.
            for node in z._nodes:
                node.hp = node.max_hp
            # Force-fire the mining beam every tick.
            for w in gv._weapons:
                w._timer = 0.0
            # Bounce the patrol so we stay mid-field.
            state["frames"] += 1
            if state["frames"] >= 120:
                state["frames"] = 0
                state["dir"] *= -1
            gv._keys.discard(arcade.key.W)
            gv._keys.discard(arcade.key.S)
            gv._keys.add(arcade.key.W if state["dir"] > 0 else arcade.key.S)
            gv.on_update(dt)
            gv.on_draw()
            _trim_projectiles()

        run_soak(gv, "Planet surface walk+mine", tick)
        gv._keys.discard(arcade.key.SPACE)
        gv._keys.discard(arcade.key.W)
        gv._keys.discard(arcade.key.S)
