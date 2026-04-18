"""Soak test for the 10-frame asteroid-specific explosion animation.

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run explicitly with:
    pytest "unit tests/integration/test_soak_asteroid_explosion.py" -v -s

Continuously churns asteroid explosions (Explo__001..010) in both Zone 1
and Zone 2 for 5 minutes each so we catch any per-frame leak tied to
the new frame list, Explosion sprite lifecycle, or texture cache.
"""
from __future__ import annotations

import random

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _spawn_asteroid_explosion(gv) -> None:
    from sprites.explosion import Explosion
    x = random.uniform(100, WORLD_WIDTH - 100)
    y = random.uniform(100, WORLD_HEIGHT - 100)
    gv.explosion_list.append(
        Explosion(gv._asteroid_explosion_frames, x, y))


def _make_explosion_churn(gv, per_frame: int = 1):
    """Spawn ``per_frame`` asteroid explosions each tick so the list
    cycles through create + 10-frame animate + teardown continuously."""
    def tick(dt: float) -> None:
        for _ in range(per_frame):
            _spawn_asteroid_explosion(gv)
        gv.on_update(dt)
        gv.on_draw()

    return tick


class TestSoakAsteroidExplosionZone1:
    def test_asteroid_explosion_zone1_5min_soak(self, real_game_view):
        """5-min soak: sustained asteroid deaths in Zone 1, 1 per frame."""
        gv = real_game_view
        make_invulnerable(gv)
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        run_soak(gv, "Asteroid explosion Zone 1",
                 _make_explosion_churn(gv, per_frame=1))


class TestSoakAsteroidExplosionZone2:
    def test_asteroid_explosion_zone2_5min_soak(self, real_game_view):
        """5-min soak: sustained asteroid deaths in the Nebula."""
        gv = real_game_view
        make_invulnerable(gv)
        gv._transition_zone(ZoneID.ZONE2)
        run_soak(gv, "Asteroid explosion Zone 2",
                 _make_explosion_churn(gv, per_frame=1))


class TestSoakAsteroidExplosionBurst:
    def test_asteroid_explosion_heavy_burst_5min_soak(self, real_game_view):
        """5-min soak with 3 asteroid explosions per frame — heavier
        churn to surface any list-iteration or frame-index overhead
        that a lighter cadence would miss."""
        gv = real_game_view
        make_invulnerable(gv)
        gv._transition_zone(ZoneID.ZONE2)
        run_soak(gv, "Asteroid explosion burst Zone 2",
                 _make_explosion_churn(gv, per_frame=3))
