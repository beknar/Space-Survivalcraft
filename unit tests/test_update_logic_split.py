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


# ── Fix (2026-05-05): _tracked_play_sound exception shield ────────────

class TestTrackedPlaySoundExceptionShield:
    """``_tracked_play_sound`` is the monkey-patched
    ``arcade.play_sound`` wrapper that bounds the pyglet Player
    backlog (``_SOUND_HARD_CAP``) so sustained combat doesn't tank
    FPS.  Pyglet's audio backend can also raise mid-call when it's
    out of voices / decoders — caught from the 2026-05-05 full-suite
    cycle when random GameView-creating tests crashed mid-init.
    The wrapper now swallows any exception from
    ``_real_play_sound`` and returns ``None`` (which existing
    callers already handle) so a transient backend failure can't
    take down a whole test run."""

    def _restore_state(self, update_audio, saved_real, saved_list):
        update_audio._real_play_sound = saved_real
        update_audio._sound_players[:] = saved_list

    def test_exception_returns_none(self, monkeypatch):
        import update_audio
        import update_logic
        # update_logic.* must still be reachable as the same objects
        # (re-export shim contract for the audio split).
        assert update_logic._tracked_play_sound is \
            update_audio._tracked_play_sound
        assert update_logic._sound_players is update_audio._sound_players
        saved_real = update_audio._real_play_sound
        saved_list = list(update_audio._sound_players)
        try:
            def boom(*_a, **_k):
                raise RuntimeError("audio backend exhausted")
            monkeypatch.setattr(update_audio, "_real_play_sound", boom)
            update_audio._sound_players.clear()
            result = update_audio._tracked_play_sound(object())
            assert result is None
            assert update_audio._sound_players == [], (
                "Failed play must not leak a tracked Player.")
        finally:
            self._restore_state(update_audio, saved_real, saved_list)

    def test_typeerror_from_arcade_warning_path_swallowed(
            self, monkeypatch):
        """Reproduces the exact symptom: arcade's own warning logger
        has a ``%``-format bug that re-raises the underlying audio
        failure as ``TypeError("not all arguments converted during
        string formatting")``.  The shield must catch this too —
        not just the original RuntimeError — because that's what
        actually surfaces to the caller."""
        import update_audio
        saved_real = update_audio._real_play_sound
        saved_list = list(update_audio._sound_players)
        try:
            def boom(*_a, **_k):
                raise TypeError(
                    "not all arguments converted during string formatting")
            monkeypatch.setattr(update_audio, "_real_play_sound", boom)
            update_audio._sound_players.clear()
            assert update_audio._tracked_play_sound(object()) is None
        finally:
            self._restore_state(update_audio, saved_real, saved_list)

    def test_subsequent_call_after_failure_still_tracks(
            self, monkeypatch):
        """A failed play must not poison the wrapper for later calls
        — the next successful play has to land in ``_sound_players``
        and respect the hard cap."""
        import update_audio
        saved_real = update_audio._real_play_sound
        saved_list = list(update_audio._sound_players)
        try:
            calls = {"n": 0}
            sentinel_player = object()

            def flaky(*_a, **_k):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("first call fails")
                return sentinel_player

            monkeypatch.setattr(update_audio, "_real_play_sound", flaky)
            update_audio._sound_players.clear()
            assert update_audio._tracked_play_sound(object()) is None
            assert update_audio._sound_players == []
            result = update_audio._tracked_play_sound(object())
            assert result is sentinel_player
            assert len(update_audio._sound_players) == 1
            assert update_audio._sound_players[0][1] is sentinel_player
        finally:
            self._restore_state(update_audio, saved_real, saved_list)

    def test_hard_cap_eviction_still_runs_when_play_raises(
            self, monkeypatch):
        """The hard-cap eviction sits BEFORE the play call, so even
        if play_sound raises we must still have evicted the oldest
        entry — otherwise a stuck audio backend could hold the
        backlog at exactly _SOUND_HARD_CAP forever (no new Player
        appended, but also no cleanup of the older ones)."""
        import update_audio
        saved_real = update_audio._real_play_sound
        saved_list = list(update_audio._sound_players)
        try:
            class FakePlayer:
                def __init__(self, tag):
                    self.tag = tag
                    self.deleted = False

                def delete(self):
                    self.deleted = True

            oldest = FakePlayer("oldest")
            update_audio._sound_players[:] = [
                (0.0, oldest)
            ] + [
                (float(i), FakePlayer(f"p{i}"))
                for i in range(1, update_audio._SOUND_HARD_CAP)
            ]

            def boom(*_a, **_k):
                raise RuntimeError("audio backend down")

            monkeypatch.setattr(update_audio, "_real_play_sound", boom)
            assert update_audio._tracked_play_sound(object()) is None
            assert oldest.deleted, (
                "Hard-cap eviction must run even when the play raises.")
            assert len(update_audio._sound_players) == \
                update_audio._SOUND_HARD_CAP - 1, (
                "Failed play after eviction must leave the list one "
                "shorter, not full.")
        finally:
            self._restore_state(update_audio, saved_real, saved_list)
