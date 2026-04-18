"""Regression tests for null-field persistence and station-info surfacing.

Two bugs the T-menu exposed:

1. Zone 2 save/load dropped its null fields — ``_restore_zone2_full``
   set ``_populated=True`` but never re-populated ``_null_fields``, so
   a loaded Nebula had an empty list and the whole stealth system
   silently stopped working.

2. The T-key station info panel showed no null-field count for any
   zone, so the player had no way to know whether the Nebula still
   had them.

Both are covered here.  Warp zones must never host null fields — a
separate concern covered by ``test_null_field.py::test_warp_zones...``.
"""
from __future__ import annotations

from types import SimpleNamespace

from constants import NULL_FIELD_COUNT
from draw_logic import compute_inactive_zone_stats
from game_save import _regenerate_null_fields
from zones import ZoneID
from zones.zone2 import Zone2


def _labels(stats):
    return [label for label, _count, _color in stats]


def _by_label(lines, label):
    for lbl, count, _color in lines:
        if lbl == label:
            return count
    return None


class TestRegenerateNullFields:
    def test_populates_full_count(self):
        zone = Zone2()
        zone._null_fields = []
        _regenerate_null_fields(zone)
        assert len(zone._null_fields) == NULL_FIELD_COUNT

    def test_is_deterministic_from_seed(self):
        """Same world seed must produce the same null-field positions
        on reload, otherwise every save/load shifts the stealth map."""
        z1 = Zone2()
        z1._world_seed = 12345
        _regenerate_null_fields(z1)
        z2 = Zone2()
        z2._world_seed = 12345
        _regenerate_null_fields(z2)
        p1 = [(nf.center_x, nf.center_y) for nf in z1._null_fields]
        p2 = [(nf.center_x, nf.center_y) for nf in z2._null_fields]
        assert p1 == p2

    def test_different_seeds_produce_different_layouts(self):
        z1 = Zone2()
        z1._world_seed = 1
        _regenerate_null_fields(z1)
        z2 = Zone2()
        z2._world_seed = 2
        _regenerate_null_fields(z2)
        p1 = [(nf.center_x, nf.center_y) for nf in z1._null_fields]
        p2 = [(nf.center_x, nf.center_y) for nf in z2._null_fields]
        assert p1 != p2

    def test_positions_within_world_bounds(self):
        zone = Zone2()
        _regenerate_null_fields(zone)
        for nf in zone._null_fields:
            assert 0 < nf.center_x < zone.world_width
            assert 0 < nf.center_y < zone.world_height


class TestInactiveZoneNullFieldStats:
    """``compute_inactive_zone_stats`` feeds the "OTHER ZONES" panel in
    StationInfo.  Null-field rows should appear for both Zone 1 and
    Zone 2 when the player is in the opposite zone."""

    def _fake_gv(self, in_zone, z1_null_count=0, z2_null_count=0):
        """Build a minimal stand-in GameView.  Pass ``in_zone`` as the
        zone_id the player is currently in."""
        zone = SimpleNamespace(zone_id=in_zone)
        main_zone = SimpleNamespace(_stash={
            "asteroid_list": [None] * 10,
            "alien_list": [None] * 5,
            "building_list": [],
            "_boss": None,
        })
        zone2 = Zone2()
        zone2._populated = True
        zone2._null_fields = [object()] * z2_null_count
        return SimpleNamespace(
            _zone=zone,
            _main_zone=main_zone,
            _zone2=zone2,
            _null_fields=[object()] * z1_null_count,
        )

    def test_zone1_null_fields_shown_when_in_zone2(self):
        gv = self._fake_gv(in_zone=ZoneID.ZONE2, z1_null_count=30)
        result = compute_inactive_zone_stats(gv)
        z1_entry = next((e for e in result if e[0] == "DOUBLE STAR"), None)
        assert z1_entry is not None
        assert _by_label(z1_entry[1], "NULL FIELDS") == 30

    def test_zone2_null_fields_shown_when_in_zone1(self):
        gv = self._fake_gv(in_zone=ZoneID.MAIN, z2_null_count=30)
        result = compute_inactive_zone_stats(gv)
        z2_entry = next((e for e in result if e[0] == "NEBULA"), None)
        assert z2_entry is not None
        assert _by_label(z2_entry[1], "NULL FIELDS") == 30

    def test_null_field_row_omitted_when_zero(self):
        """If a zone genuinely has zero null fields — e.g. a fresh
        Zone 2 that hasn't populated yet — the row is suppressed
        rather than shown as 'NULL FIELDS 0', which would be noise."""
        gv = self._fake_gv(in_zone=ZoneID.MAIN, z2_null_count=0)
        result = compute_inactive_zone_stats(gv)
        z2_entry = next((e for e in result if e[0] == "NEBULA"), None)
        assert z2_entry is not None
        assert "NULL FIELDS" not in [lbl for lbl, _, _ in z2_entry[1]]
