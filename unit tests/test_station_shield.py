"""Unit tests for the station shield and refugee parking logic.

Covers the behaviour that doesn't require a live Arcade window:
- `_station_shield_absorbs` — disk-geometry gate + HP bleed + projectile
  consume — exercised against a stub game view and a fake projectile.
- `RefugeeNPCShip(hold_dist=...)` override — default vs custom hold.
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest
from PIL import Image as PILImage


@pytest.fixture
def dummy_texture(monkeypatch):
    img = PILImage.new("RGBA", (32, 32), (200, 0, 0, 255))
    tex = arcade.Texture(img)
    monkeypatch.setattr(arcade, "load_texture", lambda *a, **kw: tex)
    return tex


# ── Station shield absorb helper ──────────────────────────────────────────


def _make_stub_shield_gv(hp: int = 100, radius: float = 300.0):
    sprite = SimpleNamespace(
        center_x=0.0, center_y=0.0,
        hit_flash_called=0,
        hit_flash=lambda self=None: None,
    )
    # hit_flash must mutate state so we can assert it was called.
    calls = {"n": 0}

    def _flash():
        calls["n"] += 1

    sprite.hit_flash = _flash
    gv = SimpleNamespace(
        _station_shield_hp=hp,
        _station_shield_sprite=sprite,
        _station_shield_radius=radius,
        hit_sparks=[],
    )
    return gv, calls


class _FakeProj:
    def __init__(self, x, y, damage=10):
        self.center_x = x
        self.center_y = y
        self.damage = damage
        self._removed = False

    def remove_from_sprite_lists(self):
        self._removed = True


class TestStationShieldAbsorb:
    def test_absorbs_projectile_inside_disk(self):
        from collisions import _station_shield_absorbs
        gv, flashes = _make_stub_shield_gv(hp=100, radius=300)
        proj = _FakeProj(100.0, 0.0, damage=15)  # 100 px from centre
        assert _station_shield_absorbs(gv, proj) is True
        assert gv._station_shield_hp == 85
        assert proj._removed is True
        assert flashes["n"] == 1
        assert len(gv.hit_sparks) == 1

    def test_does_not_absorb_outside_radius(self):
        from collisions import _station_shield_absorbs
        gv, _ = _make_stub_shield_gv(hp=100, radius=300)
        proj = _FakeProj(400.0, 0.0)  # beyond 300 px radius
        assert _station_shield_absorbs(gv, proj) is False
        assert gv._station_shield_hp == 100
        assert proj._removed is False

    def test_depleted_shield_lets_projectiles_through(self):
        from collisions import _station_shield_absorbs
        gv, _ = _make_stub_shield_gv(hp=0, radius=300)
        proj = _FakeProj(100.0, 0.0)
        assert _station_shield_absorbs(gv, proj) is False

    def test_missing_sprite_is_safe(self):
        from collisions import _station_shield_absorbs
        gv = SimpleNamespace(
            _station_shield_hp=50, _station_shield_sprite=None,
            _station_shield_radius=100, hit_sparks=[])
        proj = _FakeProj(10.0, 10.0)
        assert _station_shield_absorbs(gv, proj) is False

    def test_hp_clamps_at_zero(self):
        from collisions import _station_shield_absorbs
        gv, _ = _make_stub_shield_gv(hp=5, radius=300)
        proj = _FakeProj(0.0, 0.0, damage=999)
        assert _station_shield_absorbs(gv, proj) is True
        assert gv._station_shield_hp == 0


# ── Refugee NPC hold-distance override ────────────────────────────────────


class TestRefugeeHoldOverride:
    def test_default_hold_matches_constant(self, dummy_texture):
        from constants import NPC_REFUGEE_HOLD_DIST
        from sprites.npc_ship import RefugeeNPCShip
        ship = RefugeeNPCShip(2000.0, 1000.0, (1000.0, 1000.0))
        assert ship._hold_dist == NPC_REFUGEE_HOLD_DIST

    def test_custom_hold_stops_closer(self, dummy_texture):
        from sprites.npc_ship import RefugeeNPCShip
        ship = RefugeeNPCShip(1050.0, 1000.0, (1000.0, 1000.0),
                              hold_dist=20)
        # 50 px from target > 20 px hold → still approaching.
        ship.update_npc(0.1)
        assert ship.arrived is False
        # Teleport inside hold radius → arrives immediately.
        ship.center_x = 1010.0
        ship.update_npc(0.1)
        assert ship.arrived is True

    def test_npc_is_invulnerable_after_override(self, dummy_texture):
        from sprites.npc_ship import RefugeeNPCShip
        ship = RefugeeNPCShip(1100.0, 1000.0, (1000.0, 1000.0),
                              hold_dist=30)
        ship.take_damage(9999)  # must not raise
        assert ship.label == "Double Star Refugee"
