"""Tests for the drone blueprint icon variant.

Both drone blueprints render with the drone ship sprite as the
background and a red dot stamped in the upper-right corner.  Other
modules' blueprints continue to share the underlying module icon.
"""
from __future__ import annotations

from PIL import Image

import arcade
import pytest


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


# ── Crafted-consumable visibility regression ─────────────────────────────

class TestCraftedDroneVisibility:
    """Regression: crafting a drone at the Advanced Crafter must
    actually show up in the station inventory.  The crafter calls
    ``gv._station_inv.add_item("mining_drone" / "combat_drone", 5)``;
    without an entry in ``item_icons`` for those keys the cell
    rendered blank, so the player couldn't see (or drag) their
    freshly-crafted drones."""

    def _gv(self):
        from game_view import GameView
        return GameView(faction="Earth", ship_type="Cruiser",
                        ship_level=1)

    def test_ship_inventory_has_mining_drone_icon(self):
        gv = self._gv()
        assert "mining_drone" in gv.inventory.item_icons
        # Must be the plain drone sprite (no red dot — that's BP only).
        assert (gv.inventory.item_icons["mining_drone"]
                is gv.inventory.item_icons["mod_mining_drone"])

    def test_ship_inventory_has_combat_drone_icon(self):
        gv = self._gv()
        assert "combat_drone" in gv.inventory.item_icons
        assert (gv.inventory.item_icons["combat_drone"]
                is gv.inventory.item_icons["mod_combat_drone"])

    def test_station_inventory_has_mining_drone_icon(self):
        gv = self._gv()
        assert "mining_drone" in gv._station_inv.item_icons
        assert (gv._station_inv.item_icons["mining_drone"]
                is gv._station_inv.item_icons["mod_mining_drone"])

    def test_station_inventory_has_combat_drone_icon(self):
        gv = self._gv()
        assert "combat_drone" in gv._station_inv.item_icons
        assert (gv._station_inv.item_icons["combat_drone"]
                is gv._station_inv.item_icons["mod_combat_drone"])

    def test_station_blueprint_uses_dotted_variant(self):
        # The dotted blueprint variant created in _init_inventories
        # for the ship inventory must also be installed in the
        # station inventory so a deposited blueprint reads with the
        # same dot marker on both grids.
        gv = self._gv()
        assert (gv._station_inv.item_icons["bp_mining_drone"]
                is gv.inventory.item_icons["bp_mining_drone"])
        assert (gv._station_inv.item_icons["bp_combat_drone"]
                is gv.inventory.item_icons["bp_combat_drone"])

    def test_friendly_item_name_set_on_ship_inventory(self):
        gv = self._gv()
        assert (gv.inventory._item_names.get("mining_drone")
                == "Mining Drones")
        assert (gv.inventory._item_names.get("combat_drone")
                == "Combat Drones")

    def test_crafted_drone_actually_renders(self):
        # Add the item via the same path the crafter uses, then
        # confirm the cell has both an icon (visible) and a count.
        gv = self._gv()
        gv._station_inv.add_item("mining_drone", 5)
        assert gv._station_inv.count_item("mining_drone") == 5
        # Icon resolves (the resolved Texture is what
        # _build_render_cache stamps into the cell).
        assert gv._station_inv.item_icons.get("mining_drone") is not None
