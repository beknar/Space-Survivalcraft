"""Tests for distance-based SFX attenuation in update_logic.play_sfx_at.

Sounds emitted from in-world positions further than
``SOUND_HEARING_RADIUS`` from the player are silenced entirely;
inside the radius volume scales linearly to zero at the edge.  UI /
menu sounds bypass the helper and stay at full slider volume.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from constants import SOUND_HEARING_RADIUS


def _gv(player_x=0.0, player_y=0.0):
    return SimpleNamespace(
        player=SimpleNamespace(center_x=player_x, center_y=player_y),
    )


# ── Constant pinning ─────────────────────────────────────────────────────

class TestHearingRadiusConstant:
    def test_default_is_600(self):
        assert SOUND_HEARING_RADIUS == 600.0


# ── Volume falloff ───────────────────────────────────────────────────────

class TestVolumeAttenuation:
    def test_distance_zero_plays_at_full_base_volume(self):
        from update_logic import play_sfx_at
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, object(), 0.0, 0.0, base_volume=0.7)
            assert ps.call_count == 1
            kwargs = ps.call_args.kwargs
            assert kwargs.get("volume", 1.0) == pytest.approx(0.7)

    def test_distance_half_radius_attenuates_to_half(self):
        from update_logic import play_sfx_at
        gv = _gv()
        d = SOUND_HEARING_RADIUS / 2
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, object(), d, 0.0, base_volume=1.0)
            assert ps.call_count == 1
            assert ps.call_args.kwargs["volume"] == pytest.approx(0.5)

    def test_distance_at_radius_silenced(self):
        from update_logic import play_sfx_at
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, object(),
                        SOUND_HEARING_RADIUS, 0.0, base_volume=1.0)
            assert ps.call_count == 0

    def test_distance_beyond_radius_silenced(self):
        from update_logic import play_sfx_at
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, object(),
                        SOUND_HEARING_RADIUS + 100, 0.0, base_volume=1.0)
            assert ps.call_count == 0

    def test_diagonal_distance_uses_euclidean(self):
        from update_logic import play_sfx_at
        # 3-4-5 triangle: distance = 500 from origin.
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, object(), 300.0, 400.0, base_volume=1.0)
            assert ps.call_count == 1
            # falloff = 1 - 500/600 = 1/6
            assert ps.call_args.kwargs["volume"] == pytest.approx(
                1 / 6, abs=1e-3)


# ── Defensive fallbacks ──────────────────────────────────────────────────

class TestDefensiveFallbacks:
    def test_none_sound_is_noop(self):
        from update_logic import play_sfx_at
        gv = _gv()
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, None, 0.0, 0.0, base_volume=0.7)
            assert ps.call_count == 0

    def test_no_player_falls_back_to_full_volume(self):
        # Without a player attribute (e.g. UI / soak stub) the helper
        # plays unattenuated so essential sounds (death-screen
        # explosion, post-load splash) still register.
        from update_logic import play_sfx_at
        gv = SimpleNamespace()  # no player attr
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, object(), 9999.0, 9999.0, base_volume=0.5)
            assert ps.call_count == 1
            assert ps.call_args.kwargs["volume"] == pytest.approx(0.5)

    def test_player_at_far_position_attenuates_distant_sound(self):
        # Player at (10000, 10000); sound at (10100, 10000) → distance 100
        # → falloff = 1 - 100/600.
        from update_logic import play_sfx_at
        gv = _gv(10000.0, 10000.0)
        with patch("arcade.play_sound") as ps:
            play_sfx_at(gv, object(), 10100.0, 10000.0, base_volume=1.0)
            assert ps.call_count == 1
            assert ps.call_args.kwargs["volume"] == pytest.approx(
                1 - 100 / 600)
