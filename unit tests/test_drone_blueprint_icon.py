"""Tests for the drone blueprint icon variant.

Both drone blueprints render with the drone ship sprite as the
background and a red dot stamped in the upper-right corner.  Other
modules' blueprints continue to share the underlying module icon.
"""
from __future__ import annotations

from PIL import Image

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


# ── _make_blueprint_red_dot_variant ──────────────────────────────────────

class TestRedDotVariantHelper:
    def _src_path(self, tmp_path, color=(0, 200, 0, 255), size=(64, 64)):
        p = tmp_path / "src.png"
        Image.new("RGBA", size, color).save(p)
        return str(p)

    def test_returns_a_texture(self, tmp_path):
        from game_view import _make_blueprint_red_dot_variant
        path = self._src_path(tmp_path)
        tex = _make_blueprint_red_dot_variant(path)
        assert isinstance(tex, arcade.Texture)

    def test_preserves_source_size(self, tmp_path):
        from game_view import _make_blueprint_red_dot_variant
        path = self._src_path(tmp_path, size=(128, 128))
        tex = _make_blueprint_red_dot_variant(path)
        assert tex.size == (128, 128)

    def test_red_dot_stamped_in_upper_right(self, tmp_path):
        from game_view import _make_blueprint_red_dot_variant
        # Solid green source so any red pixel found in the upper-
        # right quadrant must be the dot the helper draws.
        path = self._src_path(tmp_path, color=(0, 200, 0, 255),
                               size=(100, 100))
        tex = _make_blueprint_red_dot_variant(path)
        # Inspect the underlying PIL image (arcade keeps it as the
        # texture's source image).
        pil = tex.image
        # Centre of the dot area: width - dot_d/2 - pad, near the top.
        # Just sample the upper-right quadrant for any pixel with
        # red dominance + low green/blue (= the dot).
        found = False
        for x in range(60, 100):
            for y in range(0, 40):
                r, g, b, a = pil.getpixel((x, y))
                if a > 200 and r > 180 and g < 80 and b < 80:
                    found = True
                    break
            if found:
                break
        assert found, "no red dot found in upper-right quadrant"

    def test_lower_left_unchanged_from_source(self, tmp_path):
        from game_view import _make_blueprint_red_dot_variant
        path = self._src_path(tmp_path, color=(0, 200, 0, 255),
                               size=(100, 100))
        tex = _make_blueprint_red_dot_variant(path)
        pil = tex.image
        # Lower-left corner should still be the source green.
        r, g, b, a = pil.getpixel((10, 90))
        assert (r, g, b) == (0, 200, 0)

    def test_caches_per_source_path(self, tmp_path):
        from game_view import (
            _make_blueprint_red_dot_variant, _BP_DOT_VARIANT_CACHE,
        )
        path = self._src_path(tmp_path)
        _BP_DOT_VARIANT_CACHE.clear()
        first = _make_blueprint_red_dot_variant(path)
        second = _make_blueprint_red_dot_variant(path)
        assert first is second


# ── End-to-end wiring through GameView ───────────────────────────────────

class TestGameViewBlueprintIconWiring:
    def _gv(self):
        from game_view import GameView
        return GameView(faction="Earth", ship_type="Cruiser",
                        ship_level=1)

    def test_mining_drone_bp_texture_differs_from_mod(self):
        gv = self._gv()
        bp = gv.inventory.item_icons["bp_mining_drone"]
        mod = gv.inventory.item_icons["mod_mining_drone"]
        assert bp is not mod

    def test_combat_drone_bp_texture_differs_from_mod(self):
        gv = self._gv()
        bp = gv.inventory.item_icons["bp_combat_drone"]
        mod = gv.inventory.item_icons["mod_combat_drone"]
        assert bp is not mod

    def test_drone_world_drop_uses_dotted_variant(self):
        gv = self._gv()
        # The world drop pickup texture comes from
        # ``gv._blueprint_drop_tex[key]`` — must be the dotted
        # version, NOT the plain mod icon.
        assert (gv._blueprint_drop_tex["mining_drone"]
                is gv.inventory.item_icons["bp_mining_drone"])
        assert (gv._blueprint_drop_tex["combat_drone"]
                is gv.inventory.item_icons["bp_combat_drone"])

    def test_non_drone_modules_share_bp_and_mod_icons(self):
        # Sanity check: the dot is drone-only.  Other modules
        # continue to share the same texture between mod_ + bp_.
        gv = self._gv()
        for key in ("armor_plate", "force_wall", "ai_pilot"):
            assert (gv.inventory.item_icons[f"bp_{key}"]
                    is gv.inventory.item_icons[f"mod_{key}"])

    def test_drone_icon_path_points_at_ship_sprite(self):
        from constants import MODULE_TYPES
        # Per spec: blueprint should look like the asset (drone
        # ship), not the legacy powerup-icon stand-in.
        assert MODULE_TYPES["mining_drone"]["icon"].endswith(
            "spaceShips_009.png")
        assert MODULE_TYPES["combat_drone"]["icon"].endswith(
            "spaceShips_004.png")
