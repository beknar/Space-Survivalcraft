"""Integration smoke test for Planets Phase 5 — base building + power grid
+ surface defenses (docs/planets.md section 10).

Exercises the planetary build system end-to-end against a real GameView:
the build-menu input path, placement + resource deduction, the power grid,
turret fire, the Shield-Generator bubble, Home-Base respawn, and a full
update+draw loop with a built base.  Branch coverage is in the fast stub
suite (``unit tests/test_planet_building.py``).
"""
from __future__ import annotations

import arcade
from PIL import Image as PILImage

from zones import ZoneID
from specs import (
    HOME_BASE, GROUND_TURRET_1, SHIELD_GENERATOR, ARC_TOWER, WIND_FARM,
)


def _stock(gv, n=2000):
    gv.inventory.add_item("iron", n)
    gv.inventory.add_item("copper", n)
    gv.inventory.add_item("silicon", n)


def _enter_surface(gv):
    gv._planet_origin_zone = ZoneID.STAR_MAZE
    gv._transition_zone(ZoneID.PLANETARY_SURFACE, entry_side="bottom")
    gv.player.center_x = gv._zone.world_width / 2
    gv.player.center_y = gv._zone.world_height / 2
    gv._zone._enemies.clear()
    return gv._zone


class TestPlanetBuildingRealGV:
    def test_place_home_base_via_zone(self, real_game_view):
        gv = real_game_view
        z = _enter_surface(gv)
        _stock(gv)
        iron0 = gv.inventory.count_item("iron")
        z._placing = "home_base"
        z._place_building(gv, gv.player.center_x + 80, gv.player.center_y)
        assert len(z._buildings) == 1
        assert z._buildings[0].spec.kind == "home"
        assert gv.inventory.count_item("iron") == iron0 - HOME_BASE.cost_iron

    def test_build_menu_opens_with_b_key(self, real_game_view):
        gv = real_game_view
        _enter_surface(gv)
        assert gv._zone._build_menu.open is False
        gv.on_key_press(arcade.key.B, 0)
        assert gv._zone._build_menu.open is True
        gv.on_key_press(arcade.key.B, 0)
        assert gv._zone._build_menu.open is False

    def test_full_build_input_path(self, real_game_view):
        gv = real_game_view
        z = _enter_surface(gv)
        _stock(gv)
        # Open menu via B, click the Home Base row, then click the world.
        gv.on_key_press(arcade.key.B, 0)
        rx, ry, rw, rh = z._build_menu._row_rect(0)   # row 0 == Home Base
        gv.on_mouse_press(int(rx + 5), int(ry + rh / 2),
                          arcade.MOUSE_BUTTON_LEFT, 0)
        assert z._placing == "home_base"
        # Place by clicking in the world (no camera offset in the test window).
        gv.on_mouse_press(400, 300, arcade.MOUSE_BUTTON_LEFT, 0)
        assert len(z._buildings) == 1

    def test_turret_powers_from_home_and_fires(self, real_game_view):
        from sprites.surface_enemy import SurfaceEnemy
        from specs import ICE_CAT
        gv = real_game_view
        z = _enter_surface(gv)
        _stock(gv)
        px, py = gv.player.center_x, gv.player.center_y
        z._placing = "home_base"
        z._place_building(gv, px + 200, py)
        z._placing = "ground_turret_1"
        z._place_building(gv, px + 320, py)          # within link of home
        turret = z._buildings[-1]
        assert turret.powered is True
        # An enemy beside the turret takes turret fire within a tick.
        e = SurfaceEnemy(ICE_CAT, z._enemy_assets["ice_cat"],
                         px + 350, py, z.world_width, z.world_height)
        z._enemies.append(e)
        hp0 = e.hp
        for _ in range(3):
            gv.on_update(1 / 60)
        assert e.hp < hp0 or e.state != "alive"

    def test_shield_bubble_blocks_enemy(self, real_game_view):
        from sprites.surface_enemy import SurfaceEnemy
        from specs import ICE_CAT
        import math
        gv = real_game_view
        z = _enter_surface(gv)
        _stock(gv)
        px, py = gv.player.center_x, gv.player.center_y
        z._placing = "home_base"
        z._place_building(gv, px, py)
        z._placing = "shield_generator"
        z._place_building(gv, px + 120, py)
        sg = z._buildings[-1]
        assert sg.powered is True
        e = SurfaceEnemy(ICE_CAT, z._enemy_assets["ice_cat"],
                         sg.center_x + 100, sg.center_y,
                         z.world_width, z.world_height)
        z._enemies = arcade.SpriteList()
        z._enemies.append(e)
        gv.on_update(1 / 60)
        d = math.hypot(e.center_x - sg.center_x, e.center_y - sg.center_y)
        assert d >= SHIELD_GENERATOR.bubble_radius - 2.0

    def test_home_base_respawn(self, real_game_view):
        gv = real_game_view
        z = _enter_surface(gv)
        _stock(gv)
        px, py = gv.player.center_x, gv.player.center_y
        z._placing = "home_base"
        z._place_building(gv, px + 60, py + 60)
        home = z._buildings[0]
        gv.player.hp = 0
        gv.on_update(1 / 60)
        assert gv.player.hp == gv.player.max_hp
        # Respawned at the Home Base (within a tile of it).
        import math
        assert math.hypot(gv.player.center_x - home.center_x,
                          gv.player.center_y - home.center_y) < 120.0

    def test_full_loop_with_base_does_not_crash(self, real_game_view):
        gv = real_game_view
        z = _enter_surface(gv)
        _stock(gv, n=5000)
        px, py = gv.player.center_x, gv.player.center_y
        # A small representative base: home, power, defenses.
        plan = [
            ("home_base", px, py),
            ("power_line", px + 110, py),
            ("wind_farm", px + 210, py),
            ("ground_turret_1", px + 150, py + 120),
            ("ground_turret_2", px - 150, py + 120),
            ("arc_tower", px + 150, py - 120),
            ("shield_generator", px - 150, py - 120),
        ]
        for key, bx, by in plan:
            z._placing = key
            z._place_building(gv, bx, by)
        z._placing = None
        # Buildings that fit the budget got placed; at minimum the home +
        # power chain + a couple defenses.
        assert any(b.spec.kind == "home" for b in z._buildings)
        for _ in range(30):
            gv.on_update(1 / 60)
            gv.on_draw()
        assert gv._zone.zone_id == ZoneID.PLANETARY_SURFACE
