"""Layout tests for station_info — every text element must fit
inside the panel rectangle.

Catches the regression where adding NULL FIELDS to compute_world_stats
pushed the bottom row to ``py - 28`` (below the panel floor at
``py``).  These tests work purely against the layout constants and
the per-row Y formulas — no Arcade window required.
"""
from __future__ import annotations

import pytest

import station_info as _si


# Approximate fudge for line height — the actual Text bounding box is
# slightly larger than the font size, but for layout-bound checks
# anchoring to the explicit Y coord and a 6-px slack is sufficient.
_LINE_SLACK = 6


class TestPanelHeightAccommodatesAllStatRows:
    def test_max_stat_lines_fit_inside_panel(self):
        """The bottom-most stat row's Y coord must be >= the panel
        floor.  Failing this means a real player will see clipped
        text in the Nebula's T menu."""
        py = 0  # absolute origin doesn't matter — only offsets do
        last_row_y = py + _si._STAT_BASELINE - (_si._MAX_STAT_LINES - 1) * 18
        panel_floor = py
        assert last_row_y >= panel_floor + _LINE_SLACK, (
            f"_MAX_STAT_LINES={_si._MAX_STAT_LINES} stat rows starting "
            f"at _STAT_BASELINE={_si._STAT_BASELINE} put the last row "
            f"at y={last_row_y - py}, but the panel floor is at y=0. "
            f"Bump _PANEL_H or move _STAT_BASELINE up.")

    def test_footer_inside_panel(self):
        py = 0
        assert _si._FOOTER_Y >= _LINE_SLACK
        assert _si._FOOTER_Y < _si._STAT_BASELINE, (
            "Footer must be BELOW the stats so they don't overlap.")

    def test_stats_do_not_overlap_footer(self):
        """Bottom of the stat list must clear the footer line by at
        least the line spacing."""
        bottom_stat_y = _si._STAT_BASELINE - (_si._MAX_STAT_LINES - 1) * 18
        assert bottom_stat_y >= _si._FOOTER_Y + 18, (
            f"Bottom stat row at y={bottom_stat_y} overlaps footer at "
            f"y={_si._FOOTER_Y}")

    def test_building_lines_clear_stats(self):
        """The deepest building row must be ABOVE the stats top so
        long building lists don't bleed into the stats region."""
        bottom_building_y = _si._PANEL_H - 50 - (_si._MAX_LINES - 1) * _si._LINE_H
        assert bottom_building_y >= _si._STAT_BASELINE + 18, (
            f"Bottom building row at y={bottom_building_y} collides "
            f"with stats top at y={_si._STAT_BASELINE}.  Either reduce "
            f"_MAX_LINES, increase _PANEL_H, or move _STAT_BASELINE.")

    def test_panel_height_was_bumped(self):
        """Belt-and-braces: the original 490 px panel could not hold
        7 stat rows.  If anyone dials it back we want to know."""
        assert _si._PANEL_H >= 580, (
            f"_PANEL_H regressed to {_si._PANEL_H} — must stay >= 580 "
            f"to accommodate the 7-row Zone 2 stats list with NULL FIELDS")


class TestStatLineYHelper:
    """Pure-function checks of the per-row Y formula — locks the
    formula so future refactors can't silently re-introduce the bug."""

    @pytest.mark.parametrize("i", range(8))
    def test_every_row_above_panel_floor(self, i):
        py = 100  # any non-zero baseline
        y = py + _si._STAT_BASELINE - i * 18
        # The row must sit clearly above the panel floor at py.
        assert y > py, (
            f"Stat row {i} at y={y} is below panel floor at y={py}")

    @pytest.mark.parametrize("i", range(8))
    def test_every_row_below_panel_top(self, i):
        py = 100
        y = py + _si._STAT_BASELINE - i * 18
        panel_top = py + _si._PANEL_H
        assert y < panel_top, (
            f"Stat row {i} at y={y} is above panel top at y={panel_top}")
