"""Soak test for the T-menu + slipspace minimap render path.

Holds the T menu open in Zone 2 for the full soak duration so we
exercise:
  - StationInfo.draw with the new layout (panel height, footer Y,
    stat baseline) — no Text recreation, no clipping
  - Minimap render including the new slipspace markers + null-field
    circles every frame
  - compute_inactive_zone_stats called every frame (it does work
    proportional to number of zones)

See ``_soak_base.py`` for shared thresholds / ``run_soak`` helper.

Run explicitly with:
    pytest "unit tests/integration/test_soak_station_info_minimap.py" -v -s
"""
from __future__ import annotations

from zones import ZoneID
from integration._soak_base import make_invulnerable, run_soak


def _make_t_menu_churn(gv):
    """Hold the T menu open and tick the live update loop the same
    way ``input_handlers`` would once the player presses T near the
    Home Station."""
    from station_info import StationInfo
    from draw_logic import compute_world_stats, compute_inactive_zone_stats

    info = StationInfo()
    info.toggle(
        gv.building_list, 0, 0,
        stat_lines=compute_world_stats(gv),
        inactive_zone_stats=compute_inactive_zone_stats(gv),
    )

    def tick(dt: float) -> None:
        gv.on_update(dt)
        gv.on_draw()
        # Keep stats fresh — same pattern as ``update_logic`` does
        # while the panel is open.
        info.update_stats(
            compute_world_stats(gv),
            inactive_zone_stats=compute_inactive_zone_stats(gv),
        )
        info.draw()

    return tick


class TestSoakStationInfoZone2:
    def test_t_menu_open_in_zone2_5min_soak(self, real_game_view):
        gv = real_game_view
        make_invulnerable(gv)
        gv._transition_zone(ZoneID.ZONE2)
        run_soak(gv, "T menu + Zone 2 minimap",
                 _make_t_menu_churn(gv))


class TestSoakStationInfoZone1:
    def test_t_menu_open_in_zone1_5min_soak(self, real_game_view):
        gv = real_game_view
        make_invulnerable(gv)
        if gv._zone.zone_id != ZoneID.MAIN:
            gv._transition_zone(ZoneID.MAIN, entry_side="wormhole_return")
        run_soak(gv, "T menu + Zone 1 minimap",
                 _make_t_menu_churn(gv))
