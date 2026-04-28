"""Tests for the drone-follows-player-through-slipspace behaviour.

When the player crosses through a slipspace into its paired exit,
the active drone should be teleported with them — preserving the
drone's offset from the player so it pops out of the destination
in the same relative position.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import arcade
import pytest


def _stub_slipspace(x, y, *, contains=False):
    ss = SimpleNamespace(
        center_x=float(x), center_y=float(y),
        _contains=contains)
    ss.contains_point = lambda px, py: ss._contains
    return ss


class TestDroneFollowsThroughSlipspace:
    def _make_gv_with_drone(self, player_xy, drone_offset):
        from sprites.drone import CombatDrone
        px, py = player_xy
        d = CombatDrone(px + drone_offset[0], py + drone_offset[1])
        gv = SimpleNamespace(
            _player_dead=False,
            player=SimpleNamespace(center_x=px, center_y=py),
            _inside_slipspace=None,
            _active_drone=d,
            _slipspace_snd=None,
            shield_sprite=None)
        return gv, d

    def test_drone_teleports_with_player(self, monkeypatch):
        """Player enters slipspace A, paired exit B exists →
        player teleports to B, drone teleports to B + (offset)."""
        from update_logic import _check_slipspace_teleport
        # Player at (1000, 1000), drone 80 px to the east.
        gv, d = self._make_gv_with_drone(
            player_xy=(1000.0, 1000.0), drone_offset=(80.0, 0.0))
        # Slipspace A at the player's position, B at (3000, 4000).
        a = _stub_slipspace(1000.0, 1000.0, contains=True)
        b = _stub_slipspace(3000.0, 4000.0, contains=False)
        # Stub active_slipspaces and the random.choice so the
        # teleport is deterministic.
        import update_logic
        monkeypatch.setattr(
            update_logic, "active_slipspaces",
            lambda gv: [a, b])
        monkeypatch.setattr(
            "random.choice", lambda seq: b)
        _check_slipspace_teleport(gv)
        # Player teleported to B.
        assert (gv.player.center_x, gv.player.center_y) == (3000.0, 4000.0)
        # Drone teleported with the same offset.
        assert d.center_x == 3000.0 + 80.0
        assert d.center_y == 4000.0

    def test_no_drone_no_op(self, monkeypatch):
        """Player teleports normally when no drone is deployed."""
        from update_logic import _check_slipspace_teleport
        gv, _ = self._make_gv_with_drone(
            player_xy=(1000.0, 1000.0), drone_offset=(0.0, 0.0))
        gv._active_drone = None
        a = _stub_slipspace(1000.0, 1000.0, contains=True)
        b = _stub_slipspace(2000.0, 2000.0, contains=False)
        import update_logic
        monkeypatch.setattr(
            update_logic, "active_slipspaces",
            lambda gv: [a, b])
        monkeypatch.setattr(
            "random.choice", lambda seq: b)
        # Should not raise even though _active_drone is None.
        _check_slipspace_teleport(gv)
        assert (gv.player.center_x, gv.player.center_y) == (2000.0, 2000.0)

    def test_drone_nudge_anchor_resets(self, monkeypatch):
        """The drone's un-stick nudge tracker resets after the
        teleport so it doesn't fire on the next frame just because
        the drone "moved" without steering."""
        from update_logic import _check_slipspace_teleport
        gv, d = self._make_gv_with_drone(
            player_xy=(1000.0, 1000.0), drone_offset=(50.0, 0.0))
        # Pretend the nudge timer was building before the jump.
        d._nudge_anchor_x = 1050.0
        d._nudge_anchor_y = 1000.0
        d._nudge_timer = 0.4
        a = _stub_slipspace(1000.0, 1000.0, contains=True)
        b = _stub_slipspace(5000.0, 5000.0, contains=False)
        import update_logic
        monkeypatch.setattr(
            update_logic, "active_slipspaces",
            lambda gv: [a, b])
        monkeypatch.setattr("random.choice", lambda seq: b)
        _check_slipspace_teleport(gv)
        assert d._nudge_timer == 0.0
        # Anchor is now at the destination so a 50 px move on the
        # next frame doesn't read as "no progress since some old
        # anchor."
        assert d._nudge_anchor_x == d.center_x
        assert d._nudge_anchor_y == d.center_y
