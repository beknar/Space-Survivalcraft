"""Tests for draw_logic.compute_world_stats — zone-aware Station Info data.

This helper drives the T-key Station Info world-stats panel. It branches on
``gv._zone.zone_id`` and pulls counts from the active zone's sprite lists,
so a regression here would silently revert the Zone 2 stat fix from the
prior session (the panel showed "0 iron / 0 roids" because it was reading
the empty stashed Zone 1 lists).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from draw_logic import compute_world_stats
from zones import ZoneID


def _fake_gv_zone1(asteroid_count: int = 5, alien_count: int = 3,
                   boss_hp: int | None = None) -> SimpleNamespace:
    """Build a minimal GameView stand-in pointing at a Zone 1 zone."""
    zone = SimpleNamespace(zone_id=ZoneID.MAIN)
    boss = None
    if boss_hp is not None:
        boss = SimpleNamespace(hp=boss_hp)
    return SimpleNamespace(
        _zone=zone,
        asteroid_list=[None] * asteroid_count,
        alien_list=[None] * alien_count,
        _boss=boss,
    )


def _fake_gv_zone2(iron: int = 10, double: int = 5, copper: int = 3,
                   wanderers: int = 2, gas: int = 4,
                   aliens: int = 12) -> SimpleNamespace:
    """Build a minimal GameView stand-in pointing at a Zone 2 zone."""
    zone = SimpleNamespace(
        zone_id=ZoneID.ZONE2,
        _iron_asteroids=[None] * iron,
        _double_iron=[None] * double,
        _copper_asteroids=[None] * copper,
        _wanderers=[None] * wanderers,
        _gas_areas=[None] * gas,
        _aliens=[None] * aliens,
    )
    return SimpleNamespace(_zone=zone, _boss=None,
                           asteroid_list=[], alien_list=[])


def _labels(stats):
    return [label for label, _count, _color in stats]


def _by_label(stats, label):
    for lbl, count, _color in stats:
        if lbl == label:
            return count
    raise KeyError(label)


# ── Zone 1 ─────────────────────────────────────────────────────────────────

class TestComputeWorldStatsZone1:
    def test_returns_asteroids_and_aliens(self):
        stats = compute_world_stats(_fake_gv_zone1())
        assert "ASTEROIDS" in _labels(stats)
        assert "ALIENS" in _labels(stats)

    def test_counts_match(self):
        gv = _fake_gv_zone1(asteroid_count=42, alien_count=7)
        stats = compute_world_stats(gv)
        assert _by_label(stats, "ASTEROIDS") == 42
        assert _by_label(stats, "ALIENS") == 7

    def test_boss_line_hidden_when_no_boss(self):
        stats = compute_world_stats(_fake_gv_zone1(boss_hp=None))
        assert "BOSS HP" not in _labels(stats)

    def test_boss_line_hidden_when_boss_dead(self):
        stats = compute_world_stats(_fake_gv_zone1(boss_hp=0))
        assert "BOSS HP" not in _labels(stats)

    def test_boss_line_shown_when_alive(self):
        stats = compute_world_stats(_fake_gv_zone1(boss_hp=1500))
        assert "BOSS HP" in _labels(stats)
        assert _by_label(stats, "BOSS HP") == 1500

    def test_does_not_include_zone2_labels(self):
        labels = _labels(compute_world_stats(_fake_gv_zone1()))
        for z2_label in ("IRON ROCK", "BIG IRON", "COPPER",
                         "WANDERERS", "GAS AREAS"):
            assert z2_label not in labels


# ── Zone 2 ─────────────────────────────────────────────────────────────────

class TestComputeWorldStatsZone2:
    def test_all_six_lines_present(self):
        labels = _labels(compute_world_stats(_fake_gv_zone2()))
        for expected in ("IRON ROCK", "BIG IRON", "COPPER",
                         "WANDERERS", "GAS AREAS", "ALIENS"):
            assert expected in labels

    def test_counts_pull_from_zone_lists_not_stashed_globals(self):
        # The bug we fixed: panel previously read gv.asteroid_list (empty when
        # in Zone 2) instead of gv._zone._iron_asteroids. This locks the fix.
        gv = _fake_gv_zone2(iron=99, double=11, copper=22,
                            wanderers=33, gas=4, aliens=55)
        stats = compute_world_stats(gv)
        assert _by_label(stats, "IRON ROCK") == 99
        assert _by_label(stats, "BIG IRON") == 11
        assert _by_label(stats, "COPPER") == 22
        assert _by_label(stats, "WANDERERS") == 33
        assert _by_label(stats, "GAS AREAS") == 4
        assert _by_label(stats, "ALIENS") == 55

    def test_does_not_include_zone1_asteroids_label(self):
        labels = _labels(compute_world_stats(_fake_gv_zone2()))
        assert "ASTEROIDS" not in labels

    def test_each_entry_has_color_tuple(self):
        for _label, _count, color in compute_world_stats(_fake_gv_zone2()):
            assert isinstance(color, tuple)
            assert len(color) == 4
            assert all(0 <= c <= 255 for c in color)
