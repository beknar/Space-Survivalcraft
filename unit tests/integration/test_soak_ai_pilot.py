"""Soak tests for the AI Pilot patrol / engage / return loop.

Spawns AI-piloted parked ships around a Home Station in Zone 2 and
periodically teleports a fresh alien in and out of range so the AI
cycles through all three modes (``patrol`` → engage → fire → ``return``
→ ``patrol``) continuously for 5 minutes.

Shared thresholds + loop live in ``_soak_base.py``.

Run with:
    pytest "unit tests/integration/test_soak_ai_pilot.py" -v -s
"""
from __future__ import annotations

import math

from constants import WORLD_WIDTH, WORLD_HEIGHT
from zones import ZoneID
from integration._soak_base import (
    make_invulnerable, measure_fps_quick, get_rss_mb, run_soak,
    WARMUP_FRAMES, FRAMES_PER_SAMPLE,
)


def _setup_ai_patrol(gv, ai_ship_count: int = 4):
    """Zone 2 + Home Station + ring of AI-piloted parked ships."""
    from sprites.building import create_building
    from sprites.parked_ship import ParkedShip

    make_invulnerable(gv)
    if gv._zone.zone_id != ZoneID.ZONE2:
        gv._transition_zone(ZoneID.ZONE2)

    gv.building_list.clear()
    hx, hy = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
    tex = gv._building_textures["Home Station"]
    gv.building_list.append(create_building(
        "Home Station", tex, hx, hy, scale=0.5))

    gv._parked_ships.clear()
    for i in range(ai_ship_count):
        ang = 2 * math.pi * i / ai_ship_count
        ps = ParkedShip(
            gv._faction, gv._ship_type, 1,
            hx + math.cos(ang) * 250,
            hy + math.sin(ang) * 250,
        )
        ps.module_slots = ["ai_pilot"]
        gv._parked_ships.append(ps)
    gv.player.center_x = hx + 3000
    gv.player.center_y = hy + 3000
    return hx, hy


def _make_patrol_cycle_churn(gv, home_xy):
    """Push an alien next to a different AI ship every 2 seconds and
    sweep it out of range halfway through each cycle so every mode
    transition runs."""
    hx, hy = home_xy
    step = {"n": 0}

    def tick(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.player.shields = gv.player.max_shields
        zone = gv._zone
        aliens = getattr(zone, "_aliens", None)
        if aliens is not None:
            if step["n"] % 120 == 0 and len(gv._parked_ships) > 0:
                target_ship = gv._parked_ships[
                    step["n"] // 120 % len(gv._parked_ships)]
                for a in aliens:
                    a.center_x = -10000
                    a.center_y = -10000
                if aliens:
                    aliens[0].center_x = target_ship.center_x + 160
                    aliens[0].center_y = target_ship.center_y
            elif step["n"] % 120 == 60:
                for a in aliens:
                    a.center_x = hx + 10000
                    a.center_y = hy + 10000
        gv.on_update(dt)
        gv.on_draw()
        step["n"] += 1

    return tick


def _make_idle_orbit_churn(gv):
    """No aliens — just run update + draw."""
    zone = gv._zone
    aliens = getattr(zone, "_aliens", None)
    if aliens is not None:
        for a in aliens:
            a.center_x = -10000
            a.center_y = -10000

    def tick(dt: float) -> None:
        gv.player.hp = gv.player.max_hp
        gv.on_update(dt)
        gv.on_draw()

    return tick


class TestSoakAIPilotPatrolCycle:
    def test_ai_pilot_full_mode_cycle_5min_soak(self, real_game_view):
        """4 AI-piloted parked ships cycle through patrol → engage →
        return → patrol every ~2 seconds for 5 minutes."""
        gv = real_game_view
        home = _setup_ai_patrol(gv, ai_ship_count=4)
        run_soak(gv, "AI Pilot patrol cycle",
                 _make_patrol_cycle_churn(gv, home))


class TestSoakAIPilotIdleOrbit:
    def test_ai_pilot_idle_orbit_5min_soak(self, real_game_view):
        """No aliens at all — validates the orbit loop itself has no
        drift or allocation bloat."""
        gv = real_game_view
        _setup_ai_patrol(gv, ai_ship_count=4)
        run_soak(gv, "AI Pilot idle orbit", _make_idle_orbit_churn(gv))


__all__ = [
    "WARMUP_FRAMES", "FRAMES_PER_SAMPLE", "measure_fps_quick", "get_rss_mb",
]
