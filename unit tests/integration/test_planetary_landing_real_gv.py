"""Integration smoke test for Planets Phase 1 — "Reach + Descend".

Exercises the Planetary Landing Scene end-to-end against a real
GameView: transition in, confirm the full enemy population spawned,
tick the real update + draw loop for a stretch (no exceptions), and
confirm the bottom edge returns the player to the originating zone.

Branch-level coverage lives in the fast stub suite
(``unit tests/test_planetary_landing.py``); this only catches wiring
bugs the stubs can't see (texture loads, draw path, zone dispatch).
"""
from __future__ import annotations

from zones import ZoneID


class TestPlanetaryLandingRealGV:
    def test_transition_populates_enemies(self, real_game_view):
        gv = real_game_view
        gv._pending_planet_type = "earth"
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_LANDING, entry_side="bottom")

        assert gv._zone.zone_id == ZoneID.PLANETARY_LANDING
        # 20 + 20 + 20 airborne enemies.
        assert len(gv._zone._enemies) == 60
        assert gv._zone.planet_type == "earth"

    def test_update_draw_loop_does_not_crash(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_LANDING, entry_side="bottom")
        # Park the player mid-scene so edge exits don't fire mid-loop.
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2

        dt = 1 / 60
        for _ in range(30):
            gv.on_update(dt)
            gv.on_draw()

        assert gv._zone.zone_id == ZoneID.PLANETARY_LANDING

    def test_bottom_edge_returns_to_star_maze(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_LANDING, entry_side="bottom")
        assert gv._zone.zone_id == ZoneID.PLANETARY_LANDING

        # Drop the player onto the bottom edge -> next tick returns home.
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = 10.0
        gv.on_update(1 / 60)

        assert gv._zone.zone_id == ZoneID.STAR_MAZE

    def test_top_edge_descends_to_surface(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_LANDING, entry_side="bottom")
        zone = gv._zone
        gv.player.center_x = zone.world_width / 2
        gv.player.center_y = zone.world_height - 10.0
        gv.on_update(1 / 60)

        # Phase 2: the top edge now lands on the on-foot surface.
        assert gv._zone.zone_id == ZoneID.PLANETARY_SURFACE
        assert gv._on_foot is True
