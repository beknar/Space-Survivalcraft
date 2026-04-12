"""Branch tests for Zone2.update() and friends.

These tests directly call Zone2 update entry points with a StubGameView,
exercising the alien-collision / wanderer / wormhole / building branches
without requiring an Arcade window. They specifically lock the regression
that crashed the game when an alien hit the player while the
player-asteroid collision branch was skipped (cooldown active), causing an
``UnboundLocalError`` on ``resolve_overlap``.
"""
from __future__ import annotations

import math
from unittest.mock import patch

import arcade
import pytest

from zones.zone2 import Zone2


# ── Test helpers ───────────────────────────────────────────────────────────

@pytest.fixture
def empty_zone2(dummy_texture) -> Zone2:
    """A Zone 2 with empty sprite lists and dummy textures wired up.

    We bypass ``setup()`` (which loads real textures and populates the
    world) and just install the bits the update loop reads.
    """
    zone = Zone2()
    zone._iron_tex = dummy_texture
    zone._copper_tex = dummy_texture
    zone._copper_pickup_tex = dummy_texture
    zone._wanderer_tex = dummy_texture
    zone._alien_laser_tex = dummy_texture
    zone._alien_textures = {
        "shielded": dummy_texture, "fast": dummy_texture,
        "gunner": dummy_texture, "rammer": dummy_texture,
    }
    zone._populated = True
    zone._shielded_aliens = []
    return zone


def _silence_arcade_audio():
    """Patch arcade.play_sound so collision handlers don't try to play audio."""
    return patch("arcade.play_sound", lambda *a, **kw: None)


# ── Regression: the UnboundLocalError bug ──────────────────────────────────

class TestUnboundLocalRegression:
    """The bug that prompted this whole test suite.

    `zones/zone2.py:update()` previously imported ``resolve_overlap`` and
    ``reflect_velocity`` *inside* the ``if gv.player._collision_cd <= 0.0``
    block. When an alien collided with the player while the cooldown was
    active (≤ 1 s after a recent hit), the asteroid branch was skipped, the
    in-function imports never ran, and the alien-player collision below
    crashed with ``UnboundLocalError``.

    These tests prove the imports are now resolved at module level.
    """

    def test_alien_collision_with_active_cooldown_does_not_crash(
        self, empty_zone2, stub_gv, dummy_texture
    ):
        from sprites.zone2_aliens import ShieldedAlien
        # Alien overlapping the player
        alien = ShieldedAlien(dummy_texture, dummy_texture,
                              stub_gv.player.center_x,
                              stub_gv.player.center_y)
        empty_zone2._aliens.append(alien)
        empty_zone2._shielded_aliens = [alien]

        # Cooldown ACTIVE — asteroid branch will be skipped
        stub_gv.player._collision_cd = 0.5
        with _silence_arcade_audio():
            empty_zone2.update(stub_gv, 1 / 60)
        # The crash was the failure mode; reaching here means the regression
        # is fixed. (Alien-player melee damage is gated by cooldown so it
        # won't fire, but the alien may still shoot a point-blank laser that
        # deals projectile damage — that's actual game behaviour.)

    def test_player_asteroid_collision_with_zero_cooldown_works(
        self, empty_zone2, stub_gv, dummy_texture
    ):
        from sprites.asteroid import IronAsteroid
        rock = IronAsteroid(dummy_texture, stub_gv.player.center_x,
                            stub_gv.player.center_y)
        empty_zone2._iron_asteroids.append(rock)

        stub_gv.player._collision_cd = 0.0  # cooldown OFF — branch runs
        with _silence_arcade_audio():
            empty_zone2.update(stub_gv, 1 / 60)
        # Asteroid collision should have applied damage and triggered shake
        assert len(stub_gv.calls["damage"]) == 1
        assert stub_gv.calls["shake"] >= 1
        assert stub_gv.player._collision_cd > 0.0


# ── Branch coverage ────────────────────────────────────────────────────────

class TestZone2AlienPlayerCollision:
    def test_pushes_player_and_alien_apart(
        self, empty_zone2, stub_gv, dummy_texture
    ):
        from sprites.zone2_aliens import ShieldedAlien
        # Stack them exactly so resolve_overlap will push them apart
        alien = ShieldedAlien(dummy_texture, dummy_texture,
                              stub_gv.player.center_x + 5,
                              stub_gv.player.center_y)
        empty_zone2._aliens.append(alien)

        with _silence_arcade_audio():
            empty_zone2.update(stub_gv, 1 / 60)

        # Alien should have been pushed (its center moved from the start)
        # and gained velocity from the +150 nudge
        assert alien.vel_x != 0.0 or alien.vel_y != 0.0


class TestZone2WandererCollision:
    def test_bounce_sets_repel_timer(
        self, empty_zone2, stub_gv, dummy_texture
    ):
        from sprites.wandering_asteroid import WanderingAsteroid
        w = WanderingAsteroid(dummy_texture,
                              stub_gv.player.center_x,
                              stub_gv.player.center_y,
                              6400.0, 6400.0)
        empty_zone2._wanderers.append(w)

        with _silence_arcade_audio():
            empty_zone2.update(stub_gv, 1 / 60)

        # Wanderer collision applies damage AND sets the magnet-suppression
        # timer. This locks the "wanderer kept attaching to player" fix.
        assert len(stub_gv.calls["damage"]) >= 1
        assert w._repel_timer > 0.0
        assert w._wander_timer > 0.0

    def test_wanderer_with_active_cooldown_skipped(
        self, empty_zone2, stub_gv, dummy_texture
    ):
        from sprites.wandering_asteroid import WanderingAsteroid
        w = WanderingAsteroid(dummy_texture,
                              stub_gv.player.center_x,
                              stub_gv.player.center_y,
                              6400.0, 6400.0)
        empty_zone2._wanderers.append(w)
        stub_gv.player._collision_cd = 0.5  # cooldown active

        with _silence_arcade_audio():
            empty_zone2._update_wanderer_collision(stub_gv, 1 / 60)

        # Cooldown gates the entire handler
        assert stub_gv.calls["damage"] == []
        assert w._repel_timer == 0.0


class TestZone2WormholeTransition:
    def test_wormhole_within_range_triggers_transition(
        self, empty_zone2, stub_gv
    ):
        from sprites.wormhole import Wormhole
        from zones import ZoneID
        wh = Wormhole(stub_gv.player.center_x + 50,
                      stub_gv.player.center_y)
        wh.zone_target = ZoneID.MAIN
        stub_gv._wormholes = [wh]

        with _silence_arcade_audio():
            empty_zone2.update(stub_gv, 1 / 60)

        # Should have called _transition_zone with the wormhole's target
        assert len(stub_gv.calls["transition"]) == 1
        args, kw = stub_gv.calls["transition"][0]
        assert args[0] == ZoneID.MAIN
        assert kw.get("entry_side") == "wormhole_return"


class TestZone2FogReveal:
    def test_player_position_reveals_fog_cells(
        self, empty_zone2, stub_gv
    ):
        # Force-clear stale fog from a previous test sharing the cache
        empty_zone2._fog_revealed = 0
        for row in empty_zone2._fog_grid:
            for i in range(len(row)):
                row[i] = False

        before = empty_zone2._fog_revealed
        with _silence_arcade_audio():
            empty_zone2._update_fog(stub_gv)
        after = empty_zone2._fog_revealed
        assert after > before, "fog should reveal at least one cell at the player position"
