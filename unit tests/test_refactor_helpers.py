"""Unit tests locking in the refactor helpers added as part of the
"refactor 1-7" pass.

Covers:
- `collisions._hit_player_on_cooldown` — the shared damage/cooldown/
  sound/shake pattern pulled out of six collision handlers.
- `sprites.alien_ai.compute_avoidance` + `pick_patrol_target` — the
  shared AI helpers now used by both Zone 1 and Zone 2 aliens.
- `escape_menu._ui.draw_button` — the button helper that replaces the
  repeated rect+text pattern in several escape menu sub-modes.
- `constants_paths` re-export module — a tighter import surface for
  asset paths without pulling in gameplay constants.
- `game_save._z2_alien_type_name` — Zone 2 alien → tag string.
"""
from __future__ import annotations

from types import SimpleNamespace

import arcade
import pytest
from PIL import Image as PILImage


# ── collisions._hit_player_on_cooldown ────────────────────────────────────


def _make_player_gv():
    """Minimal GameView stub for exercising the damage helper."""
    applied: list[int] = []
    shakes: list[int] = []
    sounds: list[float] = []

    class _Player:
        _collision_cd = 0.0

    gv = SimpleNamespace(
        player=_Player(),
        _apply_damage_to_player=lambda dmg: applied.append(dmg),
        _trigger_shake=lambda: shakes.append(1),
        _bump_snd=None,
    )

    # Patch arcade.play_sound so we can watch calls without real audio.
    original = arcade.play_sound
    arcade.play_sound = lambda snd, volume=1.0: sounds.append(volume)
    return gv, applied, shakes, sounds, original


def _restore_play_sound(original):
    arcade.play_sound = original


class TestHitPlayerOnCooldown:
    def test_landing_hit_damages_and_starts_cooldown(self):
        from collisions import _hit_player_on_cooldown
        gv, applied, shakes, sounds, original = _make_player_gv()
        try:
            assert _hit_player_on_cooldown(gv, 10, volume=0.5) is True
            assert applied == [10]
            assert gv.player._collision_cd > 0.0
            assert shakes == [1]
            assert sounds == [0.5]
        finally:
            _restore_play_sound(original)

    def test_subsequent_hit_on_cooldown_is_noop(self):
        from collisions import _hit_player_on_cooldown
        gv, applied, _, sounds, original = _make_player_gv()
        try:
            _hit_player_on_cooldown(gv, 10)
            assert _hit_player_on_cooldown(gv, 10) is False
            assert applied == [10]   # damage applied only once
            assert len(sounds) == 1  # sound played only once
        finally:
            _restore_play_sound(original)

    def test_volume_zero_skips_sound(self):
        from collisions import _hit_player_on_cooldown
        gv, _, _, sounds, original = _make_player_gv()
        try:
            _hit_player_on_cooldown(gv, 5, volume=0.0)
            assert sounds == []
        finally:
            _restore_play_sound(original)

    def test_custom_cooldown_overrides_default(self):
        from collisions import _hit_player_on_cooldown
        gv, _, _, _, original = _make_player_gv()
        try:
            _hit_player_on_cooldown(gv, 5, cooldown=2.5)
            assert gv.player._collision_cd == 2.5
        finally:
            _restore_play_sound(original)


# ── sprites.alien_ai ──────────────────────────────────────────────────────


class TestAlienAI:
    def test_compute_avoidance_repels_from_asteroid(self):
        from sprites.alien_ai import compute_avoidance
        body = SimpleNamespace(center_x=0.0, center_y=0.0)
        ast = SimpleNamespace(center_x=10.0, center_y=0.0)  # close -> repel
        sx, sy = compute_avoidance(body, 1.0, 0.0, [ast])
        assert sx < 1.0  # pushed back along -X

    def test_compute_avoidance_ignores_far_obstacles(self):
        from sprites.alien_ai import compute_avoidance
        body = SimpleNamespace(center_x=0.0, center_y=0.0)
        ast = SimpleNamespace(center_x=5000.0, center_y=0.0)
        sx, sy = compute_avoidance(body, 1.0, 0.0, [ast])
        assert sx == 1.0

    def test_pick_patrol_target_is_within_radius(self):
        from sprites.alien_ai import pick_patrol_target
        for _ in range(50):
            tx, ty = pick_patrol_target(1000.0, 1000.0, 120.0,
                                         6400.0, 6400.0)
            assert (tx - 1000.0) ** 2 + (ty - 1000.0) ** 2 <= 120.0 ** 2 + 1e-6

    def test_segment_crosses_any_wall_empty_is_safe(self):
        from sprites.alien_ai import segment_crosses_any_wall
        assert segment_crosses_any_wall(0, 0, 10, 10, None) is False
        assert segment_crosses_any_wall(0, 0, 10, 10, []) is False


# ── escape_menu._ui.draw_button ───────────────────────────────────────────


class TestEscapeMenuButton:
    @pytest.fixture
    def dummy_window(self):
        win = arcade.Window(200, 200, "escape-ui-test", visible=False)
        yield win
        try:
            win.close()
        except Exception:
            pass

    def test_draw_button_without_label_does_not_crash(self, dummy_window):
        from escape_menu._ui import draw_button
        draw_button((10, 10, 80, 30))

    def test_draw_button_updates_pooled_text_in_place(self, dummy_window):
        from escape_menu._ui import draw_button
        t = arcade.Text("", 0, 0, arcade.color.WHITE, 10,
                        anchor_x="center", anchor_y="center")
        draw_button((10, 10, 80, 30), t, label="Save")
        assert t.text == "Save"
        # Text mutation is lazy — re-drawing the same label should NOT
        # rewrite the Text.text attribute (we already skip that write).
        t.text = "Save"
        draw_button((10, 10, 80, 30), t, label="Save")
        assert t.text == "Save"


# ── constants_paths re-export ─────────────────────────────────────────────


class TestConstantsPaths:
    def test_reexports_match_constants(self):
        import constants
        import constants_paths
        for name in constants_paths.__all__:
            assert getattr(constants_paths, name) is getattr(constants, name)

    def test_contains_expected_directories(self):
        import constants_paths
        for expected in (
                "LASER_DIR", "SFX_WEAPONS_DIR",
                "MUSIC_VOL1_DIR", "MUSIC_VOL2_DIR"):
            assert hasattr(constants_paths, expected)


# ── game_save._z2_alien_type_name ─────────────────────────────────────────


class TestZ2AlienTypeLookup:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        import game_save
        game_save._Z2_ALIEN_TYPE_LOOKUP = None
        yield
        game_save._Z2_ALIEN_TYPE_LOOKUP = None

    def test_type_name_for_each_variant(self, monkeypatch):
        import game_save
        from sprites.zone2_aliens import (
            ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)

        img = PILImage.new("RGBA", (32, 32), (0, 0, 0, 255))
        tex = arcade.Texture(img)

        for cls, tag in (
                (ShieldedAlien, "shielded"),
                (FastAlien, "fast"),
                (GunnerAlien, "gunner"),
                (RammerAlien, "rammer")):
            # zone2 aliens accept (texture, laser_tex, x, y) plus kwargs
            al = cls(tex, tex, 0.0, 0.0)
            assert game_save._z2_alien_type_name(al) == tag

    def test_lookup_is_cached_after_first_call(self):
        import game_save
        assert game_save._Z2_ALIEN_TYPE_LOOKUP is None

        img = PILImage.new("RGBA", (32, 32), (0, 0, 0, 255))
        tex = arcade.Texture(img)
        from sprites.zone2_aliens import ShieldedAlien
        al = ShieldedAlien(tex, tex, 0.0, 0.0)
        game_save._z2_alien_type_name(al)
        assert game_save._Z2_ALIEN_TYPE_LOOKUP is not None
