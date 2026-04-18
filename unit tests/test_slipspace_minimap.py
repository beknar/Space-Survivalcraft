"""Tests for slipspace minimap surfacing.

Slipspaces should appear on the minimap in MAIN and ZONE2 (every
zone where they actually exist) and be ABSENT in warp zones (where
they deliberately don't spawn).  The plumbing goes:

    draw_logic._slipspace_positions(gv)
        -> hud.draw_status_panel(slipspace_positions=...)
        -> hud_minimap.draw_minimap(slipspace_positions=...)

These tests cover the first link — the "what positions do we send
to the minimap" decision.  The actual GPU draw is exercised by an
integration test elsewhere because it needs a real Arcade window.
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade

from draw_logic import _slipspace_positions
from sprites.slipspace import Slipspace
from world_setup import populate_slipspaces
from zones import ZoneID


class _DummyTex:
    """Minimal stand-in for an arcade.Texture — only ``width`` is
    read by ``Slipspace.__init__`` to compute scale."""
    width = 256


def _make_gv(slipspaces, zone_id=ZoneID.MAIN, on_zone_obj=False):
    if on_zone_obj:
        zone = SimpleNamespace(zone_id=zone_id, _slipspaces=slipspaces)
        gv_slip = arcade.SpriteList()
    else:
        zone = SimpleNamespace(zone_id=zone_id, _slipspaces=arcade.SpriteList())
        gv_slip = slipspaces
    return SimpleNamespace(_zone=zone, _slipspaces=gv_slip)


class TestSlipspacePositionsForMinimap:
    def test_returns_list_of_xy_tuples(self):
        sl = arcade.SpriteList()
        sl.append(Slipspace(_make_dummy_tex(), 100.0, 200.0))
        sl.append(Slipspace(_make_dummy_tex(), 300.0, 400.0))
        gv = _make_gv(sl, ZoneID.MAIN)
        result = _slipspace_positions(gv)
        assert result == [(100.0, 200.0), (300.0, 400.0)]

    def test_zone1_returns_gv_slipspaces(self):
        sl = arcade.SpriteList()
        sl.append(Slipspace(_make_dummy_tex(), 50.0, 60.0))
        gv = _make_gv(sl, ZoneID.MAIN)
        positions = _slipspace_positions(gv)
        assert len(positions) == 1
        assert positions[0] == (50.0, 60.0)

    def test_zone2_returns_zone_slipspaces(self):
        sl = arcade.SpriteList()
        sl.append(Slipspace(_make_dummy_tex(), 1234.0, 5678.0))
        gv = _make_gv(sl, ZoneID.ZONE2, on_zone_obj=True)
        positions = _slipspace_positions(gv)
        assert positions == [(1234.0, 5678.0)]

    def test_warp_zones_return_empty_for_minimap(self):
        """The user requirement: slipspaces must NOT show on warp
        zone minimaps even though gv._slipspaces still holds the
        Zone 1 list."""
        sl = arcade.SpriteList()
        sl.append(Slipspace(_make_dummy_tex(), 100.0, 200.0))
        for wid in (ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
                    ZoneID.WARP_GAS, ZoneID.WARP_ENEMY):
            gv = _make_gv(sl, wid)
            assert _slipspace_positions(gv) == [], (
                f"warp zone {wid} surfaced slipspaces to the minimap")


class TestSlipspacesNeverSpawnInWarpZones:
    """Spawn-side guard.  Warp zone classes don't define _slipspaces
    at all — and the population helpers are only called by Zone 1
    (GameView init) and Zone 2 (Zone2.setup).  This test makes both
    facts explicit so a future zone refactor can't silently start
    populating slipspaces in a warp zone."""

    def test_no_warp_zone_class_calls_populate_slipspaces(self):
        import inspect
        import zones.zone_warp_meteor as m
        import zones.zone_warp_lightning as l
        import zones.zone_warp_gas as g
        import zones.zone_warp_enemy as e
        for mod in (m, l, g, e):
            src = inspect.getsource(mod)
            assert "populate_slipspaces" not in src, (
                f"{mod.__name__} references populate_slipspaces — "
                f"warp zones must NOT spawn slipspaces")
            assert "_slipspaces" not in src, (
                f"{mod.__name__} references _slipspaces — warp zones "
                f"must not own a slipspace list")


def _make_dummy_tex() -> _DummyTex:
    return _DummyTex()
