"""Tests for slipspace teleporters.

Slipspaces are scattered through MAIN and ZONE2 (never warp zones).
Flying into one teleports the player to a random other slipspace in
the same zone with velocity + heading preserved.  An ``_inside_slipspace``
flag prevents re-trigger while the player overlaps the destination.
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import arcade
import pytest
from PIL import Image as PILImage

from constants import (
    SLIPSPACE_COUNT, SLIPSPACE_RADIUS, SLIPSPACE_DISPLAY_SIZE,
)
from sprites.slipspace import Slipspace
from update_logic import (
    active_slipspaces, update_slipspaces, _check_slipspace_teleport,
)
from world_setup import populate_slipspaces
from zones import ZoneID


@pytest.fixture
def dummy_tex() -> arcade.Texture:
    img = PILImage.new("RGBA", (256, 256), (200, 100, 200, 255))
    return arcade.Texture(img)


def _make_player(x: float = 0.0, y: float = 0.0,
                 vx: float = 0.0, vy: float = 0.0,
                 heading: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        center_x=x, center_y=y,
        vel_x=vx, vel_y=vy,
        heading=heading,
    )


def _make_gv(slipspaces, zone_id=ZoneID.MAIN, on_zone_obj=False):
    """Build a minimal stand-in GameView.

    ``on_zone_obj`` switches between the Zone 1 layout (list lives on
    ``gv._slipspaces``) and the Zone 2 layout (list lives on
    ``gv._zone._slipspaces``)."""
    if on_zone_obj:
        zone = SimpleNamespace(zone_id=zone_id, _slipspaces=slipspaces)
        gv_slip = arcade.SpriteList()  # empty Zone 1 list
    else:
        zone = SimpleNamespace(zone_id=zone_id, _slipspaces=arcade.SpriteList())
        gv_slip = slipspaces
    return SimpleNamespace(
        _zone=zone,
        _slipspaces=gv_slip,
        player=_make_player(),
        _player_dead=False,
        _inside_slipspace=None,
        _slipspace_snd=None,
        shield_sprite=None,
    )


# ── Sprite + populate ─────────────────────────────────────────────────────

class TestSlipspaceSprite:
    def test_radius_uses_constant(self, dummy_tex):
        ss = Slipspace(dummy_tex, 0.0, 0.0)
        assert ss.radius == SLIPSPACE_RADIUS

    def test_contains_point_circular(self, dummy_tex):
        ss = Slipspace(dummy_tex, 100.0, 100.0)
        assert ss.contains_point(100.0, 100.0)
        assert ss.contains_point(100.0 + SLIPSPACE_RADIUS - 1, 100.0)
        assert not ss.contains_point(100.0 + SLIPSPACE_RADIUS + 1, 100.0)

    def test_update_rotates(self, dummy_tex):
        ss = Slipspace(dummy_tex, 0.0, 0.0)
        ss.update_slipspace(1.0)
        assert ss.angle > 0.0

    def test_update_wraps_at_360(self, dummy_tex):
        ss = Slipspace(dummy_tex, 0.0, 0.0)
        ss.angle = 359.0
        ss.update_slipspace(10.0)   # > 360 deg of rotation
        assert 0.0 <= ss.angle < 360.0

    def test_display_scale_matches_constant(self, dummy_tex):
        ss = Slipspace(dummy_tex, 0.0, 0.0)
        # arcade stores scale as (sx, sy)
        sx = ss.scale[0] if isinstance(ss.scale, tuple) else ss.scale
        assert ss.width == pytest.approx(SLIPSPACE_DISPLAY_SIZE, abs=1)


class TestPopulate:
    def test_returns_count_slipspaces(self, dummy_tex):
        ss_list = populate_slipspaces(6400.0, 6400.0, dummy_tex)
        assert len(ss_list) == SLIPSPACE_COUNT

    def test_deterministic_with_seeded_rng(self, dummy_tex):
        a = populate_slipspaces(6400.0, 6400.0, dummy_tex,
                                rng=random.Random(42))
        b = populate_slipspaces(6400.0, 6400.0, dummy_tex,
                                rng=random.Random(42))
        pa = [(s.center_x, s.center_y) for s in a]
        pb = [(s.center_x, s.center_y) for s in b]
        assert pa == pb

    def test_within_world_bounds(self, dummy_tex):
        ss_list = populate_slipspaces(6400.0, 6400.0, dummy_tex)
        for s in ss_list:
            assert 0 < s.center_x < 6400.0
            assert 0 < s.center_y < 6400.0


# ── Active list (zone-aware) ──────────────────────────────────────────────

class TestActiveSlipspaces:
    def test_zone1_returns_gv_list(self, dummy_tex):
        ss_list = populate_slipspaces(6400.0, 6400.0, dummy_tex)
        gv = _make_gv(ss_list, zone_id=ZoneID.MAIN)
        assert active_slipspaces(gv) is ss_list

    def test_zone2_prefers_zone_list(self, dummy_tex):
        ss_list = populate_slipspaces(6400.0, 6400.0, dummy_tex)
        gv = _make_gv(ss_list, zone_id=ZoneID.ZONE2, on_zone_obj=True)
        assert active_slipspaces(gv) is ss_list

    def test_warp_zones_return_empty(self, dummy_tex):
        """Warp zones must never expose slipspaces — same rule as null
        fields."""
        ss_list = populate_slipspaces(6400.0, 6400.0, dummy_tex)
        for wid in (ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
                    ZoneID.WARP_GAS, ZoneID.WARP_ENEMY):
            gv = _make_gv(ss_list, zone_id=wid)
            assert active_slipspaces(gv) == [], (
                f"warp {wid} must not expose slipspaces")


# ── Teleport behaviour ────────────────────────────────────────────────────

class TestTeleport:
    def _two_slipspace_gv(self, dummy_tex):
        ss_list = arcade.SpriteList()
        a = Slipspace(dummy_tex, 100.0, 100.0)
        b = Slipspace(dummy_tex, 5000.0, 5000.0)
        ss_list.append(a)
        ss_list.append(b)
        gv = _make_gv(ss_list, zone_id=ZoneID.MAIN)
        return gv, a, b

    def test_collision_teleports_to_other(self, dummy_tex):
        gv, a, b = self._two_slipspace_gv(dummy_tex)
        gv.player.center_x = a.center_x
        gv.player.center_y = a.center_y
        _check_slipspace_teleport(gv)
        assert (gv.player.center_x, gv.player.center_y) == (b.center_x, b.center_y)
        assert gv._inside_slipspace is b

    def test_velocity_and_heading_preserved(self, dummy_tex):
        gv, a, b = self._two_slipspace_gv(dummy_tex)
        gv.player.center_x = a.center_x
        gv.player.center_y = a.center_y
        gv.player.vel_x = 123.0
        gv.player.vel_y = -45.0
        gv.player.heading = 270.0
        _check_slipspace_teleport(gv)
        assert gv.player.vel_x == 123.0
        assert gv.player.vel_y == -45.0
        assert gv.player.heading == 270.0

    def test_no_retrigger_while_inside_destination(self, dummy_tex):
        """The destination slipspace's collision area covers the
        teleported player, so without the ``_inside_slipspace`` flag
        the collision would fire again next frame and bounce them
        back forever."""
        gv, a, b = self._two_slipspace_gv(dummy_tex)
        gv.player.center_x = a.center_x
        gv.player.center_y = a.center_y
        _check_slipspace_teleport(gv)
        assert gv.player.center_x == b.center_x
        # Second tick — player still at b, must NOT teleport again.
        _check_slipspace_teleport(gv)
        assert gv.player.center_x == b.center_x
        assert gv.player.center_y == b.center_y

    def test_leaving_destination_re_arms(self, dummy_tex):
        gv, a, b = self._two_slipspace_gv(dummy_tex)
        gv.player.center_x = a.center_x
        gv.player.center_y = a.center_y
        _check_slipspace_teleport(gv)
        # Drift out of b
        gv.player.center_x = b.center_x + SLIPSPACE_RADIUS + 50
        _check_slipspace_teleport(gv)
        assert gv._inside_slipspace is None
        # Now re-enter a — should teleport back to b.
        gv.player.center_x = a.center_x
        gv.player.center_y = a.center_y
        _check_slipspace_teleport(gv)
        assert gv.player.center_x == b.center_x

    def test_no_teleport_with_only_one_slipspace(self, dummy_tex):
        """Need at least one OTHER slipspace to teleport to."""
        ss_list = arcade.SpriteList()
        only = Slipspace(dummy_tex, 100.0, 100.0)
        ss_list.append(only)
        gv = _make_gv(ss_list, zone_id=ZoneID.MAIN)
        gv.player.center_x = only.center_x
        gv.player.center_y = only.center_y
        _check_slipspace_teleport(gv)
        # Player still at only's position — no jump happened.
        assert (gv.player.center_x, gv.player.center_y) == (
            only.center_x, only.center_y)

    def test_no_teleport_when_dead(self, dummy_tex):
        gv, a, b = self._two_slipspace_gv(dummy_tex)
        gv.player.center_x = a.center_x
        gv.player.center_y = a.center_y
        gv._player_dead = True
        _check_slipspace_teleport(gv)
        assert gv.player.center_x == a.center_x

    def test_no_teleport_in_warp_zone(self, dummy_tex):
        """active_slipspaces returns [] in warp zones, so nothing fires
        even if gv._slipspaces still holds the Zone 1 list."""
        ss_list = arcade.SpriteList()
        a = Slipspace(dummy_tex, 100.0, 100.0)
        ss_list.append(a)
        ss_list.append(Slipspace(dummy_tex, 500.0, 500.0))
        gv = _make_gv(ss_list, zone_id=ZoneID.WARP_GAS)
        gv.player.center_x = a.center_x
        gv.player.center_y = a.center_y
        _check_slipspace_teleport(gv)
        assert gv.player.center_x == a.center_x
        assert gv.player.center_y == a.center_y

    def test_destination_is_one_of_the_others(self, dummy_tex):
        """With many slipspaces, the destination must be a different
        one from the entry point (and a member of the active list)."""
        ss_list = populate_slipspaces(
            6400.0, 6400.0, dummy_tex, rng=random.Random(7))
        gv = _make_gv(ss_list, zone_id=ZoneID.MAIN)
        entry = ss_list[0]
        gv.player.center_x = entry.center_x
        gv.player.center_y = entry.center_y
        _check_slipspace_teleport(gv)
        dest = gv._inside_slipspace
        assert dest is not None
        assert dest is not entry
        assert dest in list(ss_list)


class TestUpdateSlipspacesRotation:
    def test_rotates_active_zone_slipspaces(self, dummy_tex):
        ss_list = populate_slipspaces(6400.0, 6400.0, dummy_tex)
        gv = _make_gv(ss_list, zone_id=ZoneID.MAIN)
        before = [s.angle for s in ss_list]
        update_slipspaces(gv, 0.5)
        after = [s.angle for s in ss_list]
        assert all(a > b for a, b in zip(after, before))
