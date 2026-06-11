"""Integration smoke test for Planets Phase 2 — on-foot surface slice.

Exercises the surface end-to-end against a real GameView: enter (ship ->
on-foot mode swap), tick the real update+draw loop, mine a node, and lift
off (mode restored).  Branch coverage is in the fast stub suite
(``unit tests/test_planetary_surface.py``).
"""
from __future__ import annotations

from PIL import Image as PILImage
import arcade

from zones import ZoneID
from sprites.projectile import Projectile


class TestPlanetarySurfaceRealGV:
    def test_enter_swaps_to_on_foot(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")

        assert gv._zone.zone_id == ZoneID.PLANETARY_SURFACE
        assert gv._on_foot is True
        assert gv.player.armor == 1
        assert gv.player.max_shields == 0
        assert gv.player.guns == 1
        assert len(gv._weapons) == 2
        assert len(gv._zone._nodes) > 0
        # Directional walk frames loaded; sprite shows the down-facing frame.
        assert gv.player._on_foot_frames is not None
        assert gv.player.texture is gv.player._on_foot_frames["down"][0]

    def test_walking_animates_and_faces_direction(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2
        gv._keys.add(arcade.key.RIGHT)
        for _ in range(20):
            gv.on_update(1 / 60)
            gv.on_draw()
        gv._keys.discard(arcade.key.RIGHT)
        assert gv.player._facing == "right"
        assert gv.player.texture is gv.player._on_foot_frames["right"][0]

    def test_update_draw_loop_does_not_crash(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2
        for _ in range(20):
            gv.on_update(1 / 60)
            gv.on_draw()
        assert gv._zone.zone_id == ZoneID.PLANETARY_SURFACE

    def test_mining_a_node_yields_resource(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2

        node = gv._zone._nodes[0]
        item = node.yield_item
        before = gv.inventory.count_item(item)
        n_nodes = len(gv._zone._nodes)

        img = arcade.Texture(PILImage.new("RGBA", (4, 4), (0, 255, 0, 255)))
        proj = Projectile(img, node.center_x, node.center_y, 0.0,
                          600.0, 300.0, scale=1.0, damage=999.0)
        proj.mines_rock = True
        gv.projectile_list.append(proj)

        gv.on_update(1 / 60)

        assert gv.inventory.count_item(item) == before + node.yield_amount
        assert len(gv._zone._nodes) == n_nodes - 1

    def test_lift_off_restores_ship(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        # Capture ship state before the round trip.
        ship_guns = gv.player.guns
        ship_weapons = gv._weapons
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        assert gv._on_foot is True

        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = 10.0            # bottom lift-off edge
        gv.on_update(1 / 60)

        assert gv._on_foot is False
        assert gv._zone.zone_id == ZoneID.STAR_MAZE
        assert gv.player.guns == ship_guns
        assert gv._weapons is ship_weapons
        assert gv.player.armor == 0
