"""Unit tests for the 10-frame asteroid-specific explosion path.

Asteroid kills now use their own 10-frame `Explo__001..010.png` cycle
from the space-shooter-kit assets. Ship, alien, boss, and building
destructions keep the legacy single-sheet explosion.
"""
from __future__ import annotations

import os

import pytest

import arcade


class TestLoader:
    def test_all_ten_frame_files_exist_on_disk(self):
        from constants import ASTEROID_EXPLOSION_DIR, ASTEROID_EXPLOSION_FRAMES
        for i in range(1, ASTEROID_EXPLOSION_FRAMES + 1):
            p = os.path.join(
                ASTEROID_EXPLOSION_DIR, f"Explo__{i:03d}.png")
            assert os.path.exists(p), f"missing {p}"

    def test_loader_returns_ten_textures_and_caches(self, monkeypatch):
        """``load_asteroid_explosion_frames`` loads 10 textures the
        first call and reuses them on subsequent calls."""
        import world_setup
        from constants import ASTEROID_EXPLOSION_FRAMES
        # Reset cache so we can verify caching below.
        world_setup._asteroid_explosion_frames_cache = None

        calls = {"n": 0}
        real_loader = arcade.load_texture

        def counting_loader(*a, **kw):
            calls["n"] += 1
            return real_loader(*a, **kw)

        monkeypatch.setattr(arcade, "load_texture", counting_loader)

        frames1 = world_setup.load_asteroid_explosion_frames()
        assert len(frames1) == ASTEROID_EXPLOSION_FRAMES == 10
        assert calls["n"] == ASTEROID_EXPLOSION_FRAMES
        # Second call must hit the cache — no more load_texture calls.
        frames2 = world_setup.load_asteroid_explosion_frames()
        assert frames2 is frames1
        assert calls["n"] == ASTEROID_EXPLOSION_FRAMES


class TestSpawnHelpers:
    def test_spawn_asteroid_explosion_uses_asteroid_frames(self):
        """combat_helpers.spawn_asteroid_explosion must hand the new
        frame list to the Explosion sprite, NOT the legacy list."""
        from combat_helpers import spawn_asteroid_explosion
        from sprites.explosion import Explosion

        ast_frames: list = [object()] * 10
        legacy_frames: list = [object()] * 9
        explosions: list[Explosion] = []

        gv = type("GV", (), {
            "_asteroid_explosion_frames": ast_frames,
            "_explosion_frames": legacy_frames,
            "explosion_list": type("L", (), {
                "append": lambda self, x: explosions.append(x)
            })(),
        })()
        spawn_asteroid_explosion(gv, 100.0, 200.0)
        assert len(explosions) == 1
        assert explosions[0]._frames is ast_frames

    def test_spawn_explosion_still_uses_legacy_frames(self):
        """The generic ``spawn_explosion`` remains on the legacy sheet
        so ship / alien / building deaths are unaffected."""
        from combat_helpers import spawn_explosion
        from sprites.explosion import Explosion

        ast_frames: list = [object()] * 10
        legacy_frames: list = [object()] * 9
        explosions: list[Explosion] = []

        gv = type("GV", (), {
            "_asteroid_explosion_frames": ast_frames,
            "_explosion_frames": legacy_frames,
            "explosion_list": type("L", (), {
                "append": lambda self, x: explosions.append(x)
            })(),
        })()
        spawn_explosion(gv, 100.0, 200.0)
        assert len(explosions) == 1
        assert explosions[0]._frames is legacy_frames


class TestKillRewardsAsteroidFlag:
    def test_asteroid_flag_routes_to_asteroid_spawner(self):
        """_apply_kill_rewards(asteroid=True) must call
        ``_spawn_asteroid_explosion``, not the legacy
        ``_spawn_explosion``."""
        from collisions import _apply_kill_rewards

        ast_calls: list = []
        generic_calls: list = []

        class _StubGV:
            def __init__(self):
                self._explosion_snd = object()
                self._char_level = 1
                self.calls: list = []
                self.bp_calls: list = []

            def _spawn_asteroid_explosion(self, x, y):
                ast_calls.append((x, y))

            def _spawn_explosion(self, x, y):
                generic_calls.append((x, y))

            def _spawn_iron_pickup(self, x, y, amount=0):
                self.calls.append((x, y, amount))

            def _spawn_blueprint_pickup(self, x, y):
                self.bp_calls.append((x, y))

            def _add_xp(self, n):
                pass

        import arcade as _a
        orig_snd = _a.play_sound
        _a.play_sound = lambda *a, **kw: None
        try:
            gv = _StubGV()
            _apply_kill_rewards(
                gv, 1.0, 2.0, 5,
                lambda c, l: 0, 0.0, xp=0, asteroid=True)
        finally:
            _a.play_sound = orig_snd
        assert ast_calls == [(1.0, 2.0)]
        assert generic_calls == []

    def test_default_flag_routes_to_legacy_spawner(self):
        from collisions import _apply_kill_rewards

        ast_calls: list = []
        generic_calls: list = []

        class _StubGV:
            def __init__(self):
                self._explosion_snd = object()
                self._char_level = 1

            def _spawn_asteroid_explosion(self, x, y):
                ast_calls.append((x, y))

            def _spawn_explosion(self, x, y):
                generic_calls.append((x, y))

            def _spawn_iron_pickup(self, x, y, amount=0):
                pass

            def _spawn_blueprint_pickup(self, x, y):
                pass

            def _add_xp(self, n):
                pass

        import arcade as _a
        orig_snd = _a.play_sound
        _a.play_sound = lambda *a, **kw: None
        try:
            gv = _StubGV()
            _apply_kill_rewards(
                gv, 3.0, 4.0, 5, lambda c, l: 0, 0.0, xp=0)
        finally:
            _a.play_sound = orig_snd
        assert generic_calls == [(3.0, 4.0)]
        assert ast_calls == []
