"""Tests for ``bot_builder.build_starter_base``.

The function walks the standard build sequence in one call,
delegating placement to ``building_manager`` (resource cost +
snap-port logic).  Tests use a minimal stub of ``gv`` and
monkey-patch ``building_manager.enter_placement_mode`` /
``place_building`` so we can verify the sequence + reporting
without needing a real arcade window or building textures.
"""
from __future__ import annotations

from types import SimpleNamespace

import bot_builder


def _stub_gv(buildings: list | None = None):
    if buildings is None:
        buildings = []
    return SimpleNamespace(
        player=SimpleNamespace(center_x=1000.0, center_y=2000.0),
        building_list=buildings,
    )


# ── Sequence + ordering ───────────────────────────────────────────────────


def test_sequence_is_seven_buildings_in_documented_order():
    types = [bt for (bt, _, _) in bot_builder.STARTER_BASE_SEQUENCE]
    assert types == [
        "Home Station",
        "Service Module",
        "Power Receiver",
        "Solar Array 2",
        "Repair Module",
        "Turret 2",
        "Turret 2",
    ]


def test_turrets_are_at_max_free_place_radius():
    """Turret 2s sit at +/-300 px on the X axis — the
    TURRET_FREE_PLACE_RADIUS limit defined in constants.py."""
    from constants import TURRET_FREE_PLACE_RADIUS
    turret_offsets = [
        (dx, dy) for (bt, dx, dy) in bot_builder.STARTER_BASE_SEQUENCE
        if bt == "Turret 2"
    ]
    assert (TURRET_FREE_PLACE_RADIUS, 0.0) in turret_offsets
    assert (-TURRET_FREE_PLACE_RADIUS, 0.0) in turret_offsets


# ── build_starter_base() behaviour ────────────────────────────────────────


def test_each_step_calls_enter_then_place(monkeypatch):
    calls: list = []

    def _enter(gv, bt):
        calls.append(("enter", bt))

    def _place(gv, wx, wy):
        calls.append(("place", wx, wy))
        # Simulate a successful placement -- grow building_list.
        gv.building_list.append(SimpleNamespace(name="stub"))

    def _cancel(gv):
        calls.append(("cancel",))

    import building_manager as bm
    monkeypatch.setattr(bm, "enter_placement_mode", _enter)
    monkeypatch.setattr(bm, "place_building", _place)
    monkeypatch.setattr(bm, "cancel_placement", _cancel)

    gv = _stub_gv()
    result = bot_builder.build_starter_base(gv)

    # 7 enter + 7 place, in interleaved order.
    enter_count = sum(1 for c in calls if c[0] == "enter")
    place_count = sum(1 for c in calls if c[0] == "place")
    assert enter_count == 7
    assert place_count == 7
    assert result["buildings_added"] == 7
    assert len(result["placed"]) == 7
    assert result["failed"] == []


def test_failed_placement_reported_as_rejected(monkeypatch):
    """When ``place_building`` doesn't grow ``building_list`` (the
    canonical "rejected" path — silent cancel inside the helper),
    that step lands in ``failed`` not ``placed``."""
    import building_manager as bm
    monkeypatch.setattr(bm, "enter_placement_mode", lambda gv, bt: None)
    # Reject every placement.
    monkeypatch.setattr(bm, "place_building", lambda gv, wx, wy: None)
    monkeypatch.setattr(bm, "cancel_placement", lambda gv: None)

    gv = _stub_gv()
    result = bot_builder.build_starter_base(gv)

    assert result["buildings_added"] == 0
    assert result["placed"] == []
    assert len(result["failed"]) == 7
    assert all(f["reason"] == "placement rejected"
               for f in result["failed"])


def test_exception_in_placement_recorded_and_continues(
        monkeypatch):
    """If ``place_building`` raises, the builder must
    ``cancel_placement`` to clear the ghost and continue with the
    next building."""
    import building_manager as bm
    cancels: list = []
    placed_after_first: list = []

    enter_count = [0]
    def _enter(gv, bt):
        enter_count[0] += 1

    def _place(gv, wx, wy):
        if enter_count[0] == 1:
            raise RuntimeError("boom")
        # Subsequent placements succeed.
        gv.building_list.append(SimpleNamespace())
        placed_after_first.append(True)

    monkeypatch.setattr(bm, "enter_placement_mode", _enter)
    monkeypatch.setattr(bm, "place_building", _place)
    monkeypatch.setattr(
        bm, "cancel_placement",
        lambda gv: cancels.append(True))

    gv = _stub_gv()
    result = bot_builder.build_starter_base(gv)

    # Failure on Home Station, but 6 subsequent placements succeed.
    assert len(result["failed"]) == 1
    assert result["failed"][0]["type"] == "Home Station"
    assert "boom" in result["failed"][0]["error"]
    assert len(result["placed"]) == 6
    assert cancels, "must call cancel_placement after exception"
