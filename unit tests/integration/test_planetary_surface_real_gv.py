"""Integration smoke test for Planets Phase 2 — on-foot surface slice.

Exercises the surface end-to-end against a real GameView: enter (ship ->
on-foot mode swap), tick the real update+draw loop, mine a node, and lift
off (mode restored).  Branch coverage is in the fast stub suite
(``unit tests/test_planetary_surface.py``).
"""
from __future__ import annotations

from PIL import Image as PILImage
import arcade
import pytest

from constants import DEBRA_SURFACE_VIDEO
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
        assert len(gv._weapons) == 4          # rifle, mining beam, sword, pick
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

    def test_surface_swaps_hud_character_video(self, real_game_view):
        gv = real_game_view
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        cvp = gv._char_video_player
        if not cvp.active:
            pytest.skip("character video inactive (no FFmpeg / decode in env)")
        # Same play_segments scheme, now pointed at the surface clip.
        assert cvp._current_path == DEBRA_SURFACE_VIDEO
        # Lifting off restores a non-surface video (or stops it).
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = 10.0
        gv.on_update(1 / 60)
        assert cvp._current_path != DEBRA_SURFACE_VIDEO

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

    # ── Surface enemies (Phase 3) ───────────────────────────────────

    def _enter_surface(self, gv):
        gv._planet_origin_zone = ZoneID.STAR_MAZE
        gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
        gv.player.center_x = gv._zone.world_width / 2
        gv.player.center_y = gv._zone.world_height / 2
        return gv._zone

    def test_enemies_spawn_per_tier(self, real_game_view):
        gv = real_game_view
        z = self._enter_surface(gv)
        assert len(z._enemies) == 21         # 10 + 7 + 4
        counts = {"A": 0, "B": 0, "C": 0}
        for e in z._enemies:
            counts[e.spec.tier] += 1
        assert counts == {"A": 10, "B": 7, "C": 4}

    def test_player_kills_enemy(self, real_game_view):
        from sprites.surface_enemy import SurfaceEnemy
        from specs import ICE_CAT
        gv = real_game_view
        z = self._enter_surface(gv)
        z._enemies.clear()
        e = SurfaceEnemy(ICE_CAT, z._enemy_assets["ice_cat"],
                         gv.player.center_x + 100, gv.player.center_y,
                         z.world_width, z.world_height)
        z._enemies.append(e)
        # A lethal player shot sitting on the enemy.
        img = arcade.Texture(PILImage.new("RGBA", (4, 4), (0, 0, 255, 255)))
        proj = Projectile(img, e.center_x, e.center_y, 0.0, 900.0, 600.0,
                          scale=1.0, damage=999.0)
        proj.mines_rock = False              # rifle shot
        gv.projectile_list.append(proj)
        gv.on_update(1 / 60)
        assert e.state == "dying"

    def test_enemy_damages_player(self, real_game_view):
        from sprites.surface_enemy import SurfaceEnemy
        from specs import ICE_CAT
        gv = real_game_view
        z = self._enter_surface(gv)
        z._enemies.clear()
        # Ice cat right on top of the player → bump damage within a tick.
        e = SurfaceEnemy(ICE_CAT, z._enemy_assets["ice_cat"],
                         gv.player.center_x + 20, gv.player.center_y,
                         z.world_width, z.world_height)
        e._atk_cd = 0.0
        z._enemies.append(e)
        hp0 = gv.player.hp
        gv.on_update(1 / 60)
        assert gv.player.hp < hp0

    def test_downed_respawns_on_surface(self, real_game_view):
        from sprites.surface_enemy import SurfaceEnemy
        from specs import ICE_CAT
        gv = real_game_view
        z = self._enter_surface(gv)
        z._enemies.clear()
        e = SurfaceEnemy(ICE_CAT, z._enemy_assets["ice_cat"],
                         gv.player.center_x + 20, gv.player.center_y,
                         z.world_width, z.world_height)
        e._atk_cd = 0.0
        z._enemies.append(e)
        gv.player.hp = 5                     # one bump downs the player
        gv.on_update(1 / 60)
        # Surface handles the downed state — NOT the space death flow.
        assert gv._player_dead is False
        assert gv._on_foot is True
        assert gv._zone.zone_id == ZoneID.PLANETARY_SURFACE
        assert gv.player.hp == gv.player.max_hp

    # ── On-foot melee + loot (Phase 4) ──────────────────────────────

    def test_sword_kills_enemy_and_drops_iron(self, real_game_view):
        from sprites.surface_enemy import SurfaceEnemy
        from specs import ICE_CAT
        gv = real_game_view
        z = self._enter_surface(gv)
        z._enemies.clear()
        e = SurfaceEnemy(ICE_CAT, z._enemy_assets["ice_cat"],
                         gv.player.center_x + 40, gv.player.center_y,
                         z.world_width, z.world_height)
        z._enemies.append(e)
        gv._weapon_idx = 2                     # Electron Sword
        gv._keys.add(arcade.key.SPACE)
        iron0 = gv.inventory.count_item("iron")
        for _ in range(80):                   # enough swings to kill (25 HP)
            gv.on_update(1 / 60)
        gv._keys.discard(arcade.key.SPACE)
        assert e.state != "alive"             # killed by the sword
        assert gv.inventory.count_item("iron") > iron0   # loot collected

    def test_pickaxe_mines_node(self, real_game_view):
        gv = real_game_view
        z = self._enter_surface(gv)
        z._enemies.clear()                    # isolate the pick axe
        node = z._nodes[0]
        node.center_x = gv.player.center_x + 30
        node.center_y = gv.player.center_y
        hp0 = node.hp
        gv._weapon_idx = 3                     # Electron Pick Axe
        gv._keys.add(arcade.key.SPACE)
        gv.on_update(1 / 60)
        gv._keys.discard(arcade.key.SPACE)
        assert node.hp < hp0                  # the swing damaged the node

    def test_sword_deflects_incoming_shot(self, real_game_view):
        from unittest.mock import patch
        from sprites.projectile import Projectile
        gv = real_game_view
        z = self._enter_surface(gv)
        z._enemies.clear()
        gv._weapon_idx = 2                     # Electron Sword wielded
        img = arcade.Texture(PILImage.new("RGBA", (4, 4), (255, 0, 0, 255)))
        proj = Projectile(img, gv.player.center_x, gv.player.center_y, 0.0,
                          0.0, 500.0, scale=1.0, damage=30.0)
        z._enemy_projectiles.append(proj)
        hp0 = gv.player.hp
        # Force a deflect (random < 0.5).
        with patch("zones.zone_planetary_surface.random.random",
                   return_value=0.0):
            gv.on_update(1 / 60)
        assert gv.player.hp == hp0            # parried, no damage taken
