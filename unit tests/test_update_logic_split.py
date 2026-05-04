"""Seam-pinning tests for the ``update_logic`` -> sibling-module split.

After the 2026-05-03 refactor, distance-attenuated SFX helpers live
in ``update_logic_sfx`` and the null-field / slipspace / force-wall
helpers live in ``update_logic_zone_effects``.  The original
``update_logic`` module re-exports them so the dozens of
``from update_logic import ...`` call sites in draw_logic /
collisions / combat_helpers / input_handlers continue to work.

These tests guard the contract: the public names + signatures must
stay reachable both via the original module AND the new module so
future moves don't silently break callers.
"""
from __future__ import annotations

import inspect

import pytest


# ── SFX module ────────────────────────────────────────────────────────

class TestSfxModuleSeam:
    def test_sfx_module_imports(self):
        import update_logic_sfx  # noqa: F401

    def test_re_exports_match(self):
        import update_logic
        import update_logic_sfx
        for name in (
            "play_sfx_at",
            "_nearest_alien_to_player",
            "_play_throttled_alien_sfx",
            "play_alien_laser_sound",
            "play_missile_launch_sound",
            "emit_alien_shots",
            "_ALIEN_LASER_SND_INTERVAL",
        ):
            assert getattr(update_logic, name) is getattr(
                update_logic_sfx, name), (
                f"update_logic.{name} != update_logic_sfx.{name} — "
                "the re-export shim is stale.")

    def test_play_sfx_at_signature(self):
        import update_logic_sfx
        sig = inspect.signature(update_logic_sfx.play_sfx_at)
        params = list(sig.parameters.keys())
        assert params[:4] == ["gv", "snd", "x", "y"]
        assert "base_volume" in sig.parameters

    def test_emit_alien_shots_signature(self):
        import update_logic_sfx
        sig = inspect.signature(update_logic_sfx.emit_alien_shots)
        assert "use_missile_sound" in sig.parameters
        assert sig.parameters["use_missile_sound"].kind \
            == inspect.Parameter.KEYWORD_ONLY


# ── Zone effects module ───────────────────────────────────────────────

class TestZoneEffectsModuleSeam:
    def test_zone_effects_module_imports(self):
        import update_logic_zone_effects  # noqa: F401

    def test_re_exports_match(self):
        import update_logic
        import update_logic_zone_effects as ze
        for name in (
            "active_null_fields",
            "find_null_field_at",
            "disable_null_field_around_player",
            "player_is_cloaked",
            "active_slipspaces",
            "update_slipspaces",
            "_check_slipspace_teleport",
            "update_null_fields",
            "update_force_walls",
        ):
            assert getattr(update_logic, name) is getattr(ze, name), (
                f"update_logic.{name} != update_logic_zone_effects.{name}.")

    def test_callers_can_still_import_from_update_logic(self):
        """Mirrors the ``from update_logic import play_sfx_at`` style
        that draw_logic / collisions / combat_helpers / input_handlers
        all use.  If this breaks, ~25 call sites break with it."""
        from update_logic import (
            play_sfx_at,
            active_null_fields,
            active_slipspaces,
            disable_null_field_around_player,
            player_is_cloaked,
            update_force_walls,
            emit_alien_shots,
        )
        for fn in (play_sfx_at, active_null_fields, active_slipspaces,
                   disable_null_field_around_player, player_is_cloaked,
                   update_force_walls, emit_alien_shots):
            assert callable(fn)


# ── Slipspace teleport-via-update_logic patch routing ──────────────────

class TestSlipspaceTeleportPatchRouting:
    """Pin that ``_check_slipspace_teleport`` (now in
    update_logic_zone_effects) honours monkey-patches against
    ``update_logic.active_slipspaces``.  Drone-slipspace tests rely
    on this — without the late-lookup shim they all break."""

    def test_patch_via_update_logic_takes_effect(self, monkeypatch):
        from types import SimpleNamespace
        import update_logic
        sentinel: list = []

        def fake_active(gv):
            sentinel.append("called")
            return []

        monkeypatch.setattr(
            update_logic, "active_slipspaces", fake_active)
        gv = SimpleNamespace(
            _player_dead=False,
            player=SimpleNamespace(center_x=0.0, center_y=0.0),
            _inside_slipspace=None,
        )
        update_logic._check_slipspace_teleport(gv)
        assert sentinel == ["called"]
