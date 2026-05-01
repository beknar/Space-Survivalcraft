"""Pin the deflect-hook integration in the Star Maze projectile-vs-
player handlers.

The Star Maze has two handlers that bypass the generic
``handle_alien_laser_hits`` and apply damage inline:

* ``_handle_maze_projectiles_vs_player`` -- maze alien / spawner bolts
* ``_advance_alien_projectiles``         -- nebula alien bolts inside
                                            the maze

Both must route through ``collisions._try_melee_deflect`` first so the
energy blade can deflect bolts in the Star Maze (the field pilot's
JSONL log showed 0 / 216 swings produced any deflect attempt because
neither path was wired up).  These tests call the bound methods with
stubbed self / gv so we don't need a real arcade window.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import arcade
import pytest
from PIL import Image as PILImage

import collisions
from zones.star_maze import StarMazeZone


@pytest.fixture
def tex():
    img = PILImage.new("RGBA", (16, 16), (200, 200, 200, 255))
    return arcade.Texture(img)


def _make_proj(tex, x, y):
    from sprites.projectile import Projectile
    return Projectile(
        tex, x, y, 0.0, 0.0, 1000.0, scale=1.0, damage=7,
    )


def _stub_gv(blade_swinging: bool | None):
    """Minimal stub of GameView for the deflect handlers.  Pass
    ``blade_swinging=None`` to omit the blade entirely."""
    calls = {"damage": [], "shake": 0}
    gv = SimpleNamespace(
        player=SimpleNamespace(
            center_x=400.0, center_y=400.0,
            position=(400.0, 400.0),
        ),
        projectile_list=arcade.SpriteList(),
        hit_sparks=[],
        _bump_snd=None,
        calls=calls,
    )
    gv._apply_damage_to_player = lambda d: calls["damage"].append(d)
    gv._trigger_shake = lambda: calls.__setitem__(
        "shake", calls["shake"] + 1)
    if blade_swinging is None:
        gv._active_blade = None
    else:
        gv._active_blade = SimpleNamespace(is_swinging=blade_swinging)
    # Real arcade.check_for_collision_with_list needs Sprite-style
    # x/y; the stub player above is enough since we'll use overlap-
    # by-position projectiles.
    return gv


# ── _handle_maze_projectiles_vs_player ─────────────────────────────────────

class TestMazeProjectileDeflect:
    def test_swinging_blade_deflects_maze_bolt(self, tex, monkeypatch):
        monkeypatch.setattr(collisions.random, "random", lambda: 0.0)
        gv = _stub_gv(blade_swinging=True)
        # Replace player with a real Sprite so check_for_collision works.
        gv.player = arcade.Sprite()
        gv.player.texture = tex
        gv.player.center_x = 400.0
        gv.player.center_y = 400.0
        proj = _make_proj(tex, gv.player.center_x, gv.player.center_y)
        stub_self = SimpleNamespace(
            _maze_projectiles=arcade.SpriteList(),
        )
        stub_self._maze_projectiles.append(proj)
        with patch("arcade.play_sound", lambda *a, **kw: None):
            StarMazeZone._handle_maze_projectiles_vs_player(stub_self, gv)
        assert gv.calls["damage"] == []   # no damage applied
        assert proj in gv.projectile_list
        assert proj not in stub_self._maze_projectiles

    def test_idle_blade_takes_damage_normally(
            self, tex, monkeypatch):
        gv = _stub_gv(blade_swinging=False)
        gv.player = arcade.Sprite()
        gv.player.texture = tex
        gv.player.center_x = 400.0
        gv.player.center_y = 400.0
        proj = _make_proj(tex, gv.player.center_x, gv.player.center_y)
        stub_self = SimpleNamespace(
            _maze_projectiles=arcade.SpriteList(),
        )
        stub_self._maze_projectiles.append(proj)
        StarMazeZone._handle_maze_projectiles_vs_player(stub_self, gv)
        assert gv.calls["damage"] == [7]


# ── _advance_alien_projectiles (nebula bolts inside the maze) ──────────────

class TestNebulaBoltDeflectInMaze:
    def test_swinging_blade_deflects_nebula_bolt_inside_maze(
            self, tex, monkeypatch):
        monkeypatch.setattr(collisions.random, "random", lambda: 0.0)
        gv = _stub_gv(blade_swinging=True)
        gv.player = arcade.Sprite()
        gv.player.texture = tex
        gv.player.center_x = 400.0
        gv.player.center_y = 400.0
        proj = _make_proj(tex, gv.player.center_x, gv.player.center_y)
        # update_projectile is a no-op for our stub purposes — the
        # handler advances projectiles before doing the player-collision
        # pass, so we just need the proj to stay overlapping.
        stub_self = SimpleNamespace(
            _alien_projectiles=arcade.SpriteList(),
            _segment_hits_wall_fast=lambda *a, **kw: False,
        )
        stub_self._alien_projectiles.append(proj)
        with patch("arcade.play_sound", lambda *a, **kw: None):
            StarMazeZone._advance_alien_projectiles(
                stub_self, gv, 1.0 / 60.0)
        assert gv.calls["damage"] == []
        assert proj in gv.projectile_list
        assert proj not in stub_self._alien_projectiles

    def test_no_blade_takes_damage_normally(
            self, tex, monkeypatch):
        gv = _stub_gv(blade_swinging=None)
        gv.player = arcade.Sprite()
        gv.player.texture = tex
        gv.player.center_x = 400.0
        gv.player.center_y = 400.0
        proj = _make_proj(tex, gv.player.center_x, gv.player.center_y)
        stub_self = SimpleNamespace(
            _alien_projectiles=arcade.SpriteList(),
            _segment_hits_wall_fast=lambda *a, **kw: False,
        )
        stub_self._alien_projectiles.append(proj)
        StarMazeZone._advance_alien_projectiles(
            stub_self, gv, 1.0 / 60.0)
        assert gv.calls["damage"] == [7]
