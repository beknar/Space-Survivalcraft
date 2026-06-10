"""Performance integration test — planet surface (on-foot slice).

Frame-time / FPS coverage for the on-foot surface scene under load:
the player walking + firing the mining beam across a field of ~28
resource nodes, with the ground backdrop + node draws every frame.

Run with:
    pytest "unit tests/integration/test_performance_planet_surface.py" -v
"""
from __future__ import annotations

import arcade

from zones import ZoneID
from integration.conftest import measure_fps as _measure_fps

MIN_FPS = 40


class TestPlanetSurfacePerf:
    def test_surface_walk_and_mine_above_threshold(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        assert gv._zone.zone_id == ZoneID.PLANETARY_SURFACE

        # Mining beam active, walking up while firing.
        gv._weapon_idx = 1
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2
        gv._keys.add(arcade.key.W)
        gv._keys.add(arcade.key.SPACE)

        # Warm up the scene (reveal, populate projectiles, keep nodes alive).
        dt = 1 / 60
        for _ in range(30):
            for node in gv._zone._nodes:
                node.hp = node.max_hp          # never deplete -> steady churn
            gv.on_update(dt)
            gv.on_draw()

        fps = _measure_fps(gv, n_warmup=10)
        gv._keys.discard(arcade.key.W)
        gv._keys.discard(arcade.key.SPACE)

        node_count = len(gv._zone._nodes)
        assert fps >= MIN_FPS, (
            f"Planet surface ({node_count} nodes): "
            f"{fps:.1f} FPS < {MIN_FPS} FPS threshold")
