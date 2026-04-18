"""Integration tests for the T-menu fixes and slipspace minimap.

Real GameView in a hidden Arcade window so we can construct the
actual ``StationInfo`` overlay and ``draw_minimap`` and exercise:

1. Opening the T menu in the Nebula doesn't push any stat row's Y
   coordinate below the panel floor.
2. NULL FIELDS appears in the live stat list for MAIN and ZONE2.
3. The slipspace position helper actually returns positions for
   MAIN/ZONE2 and an empty list for warp zones.
"""
from __future__ import annotations

import pytest

from draw_logic import (
    compute_world_stats, compute_inactive_zone_stats, _slipspace_positions,
)
from zones import ZoneID


def _labels(stats):
    return [label for label, _, _ in stats]


def _by_label(stats, label):
    for lbl, count, _ in stats:
        if lbl == label:
            return count
    return None


class TestRealStationInfoLayoutInZone2:
    def test_all_stat_rows_render_inside_panel(self, real_game_view):
        """Pull the real Zone 2 stats list and walk every per-row Y
        coordinate the StationInfo panel would assign — none may sit
        below the panel floor."""
        from station_info import (
            StationInfo, _PANEL_H, _STAT_BASELINE, _MAX_STAT_LINES,
        )
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)

        stats = compute_world_stats(gv)
        info = StationInfo()
        info.toggle(gv.building_list, 0, 0, stat_lines=stats)
        py = info._py
        panel_floor = py
        panel_top = py + _PANEL_H

        for i, _entry in enumerate(stats[:_MAX_STAT_LINES]):
            y = py + _STAT_BASELINE - i * 18
            assert y >= panel_floor, (
                f"Stat row {i} ({_entry[0]}) at y={y} below panel "
                f"floor {panel_floor}")
            assert y < panel_top, (
                f"Stat row {i} ({_entry[0]}) at y={y} above panel "
                f"top {panel_top}")

    def test_null_fields_present_in_zone2_stats(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        stats = compute_world_stats(gv)
        assert "NULL FIELDS" in _labels(stats)
        # Live zone is fully populated by setup() — count must be > 0.
        assert _by_label(stats, "NULL FIELDS") > 0

    def test_null_fields_present_in_main_stats(self, real_game_view):
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        stats = compute_world_stats(gv)
        assert "NULL FIELDS" in _labels(stats)
        assert _by_label(stats, "NULL FIELDS") > 0

    def test_t_menu_open_and_draw_does_not_raise_in_zone2(
            self, real_game_view):
        """Smoke test: open the T menu in Zone 2 and run a draw call.
        Catches any text-object reposition crashes triggered by the
        new layout."""
        from station_info import StationInfo
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        stats = compute_world_stats(gv)
        info = StationInfo()
        info.toggle(gv.building_list, 0, 0, stat_lines=stats,
                    inactive_zone_stats=compute_inactive_zone_stats(gv))
        info.draw()  # must not raise


class TestSlipspaceMinimapInRealZones:
    def test_main_returns_15_slipspace_positions(self, real_game_view):
        gv = real_game_view
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        positions = _slipspace_positions(gv)
        from constants import SLIPSPACE_COUNT
        assert len(positions) == SLIPSPACE_COUNT

    def test_zone2_returns_15_slipspace_positions(self, real_game_view):
        gv = real_game_view
        gv._transition_zone(ZoneID.ZONE2)
        positions = _slipspace_positions(gv)
        from constants import SLIPSPACE_COUNT
        assert len(positions) == SLIPSPACE_COUNT

    @pytest.mark.parametrize("entry_side", ["bottom"])
    def test_warp_zones_return_empty_slipspace_positions(
            self, real_game_view, entry_side):
        """User requirement: slipspaces must NOT show on warp-zone
        minimaps and must NOT spawn there.  We test all four warp
        zone IDs by transitioning into them."""
        gv = real_game_view
        # Transition through MAIN first to avoid coming from arbitrary state.
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        for wid in (ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
                    ZoneID.WARP_GAS, ZoneID.WARP_ENEMY):
            gv._transition_zone(wid, entry_side=entry_side)
            positions = _slipspace_positions(gv)
            assert positions == [], (
                f"warp zone {wid} surfaced {len(positions)} slipspace "
                f"position(s) to the minimap")
            # Also verify the warp zone state object doesn't carry a
            # populated _slipspaces — otherwise a future change to
            # active_slipspaces could leak them through.
            zone_ss = getattr(gv._zone, "_slipspaces", None)
            assert not zone_ss, (
                f"warp zone {wid} has populated _slipspaces "
                f"({zone_ss!r}) — they must not spawn there")
            # Bounce back to MAIN before next iteration.
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
