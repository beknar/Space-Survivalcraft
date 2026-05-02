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
    TURRET_FREE_PLACE_RADIUS limit defined in constants.py.
    The Y offset is the global STARTER_BASE_OFFSET_Y so the
    turrets line up with the home station along its row."""
    from constants import TURRET_FREE_PLACE_RADIUS
    turret_offsets = [
        (dx, dy) for (bt, dx, dy) in bot_builder.STARTER_BASE_SEQUENCE
        if bt == "Turret 2"
    ]
    base_y = bot_builder._STARTER_BASE_OFFSET_Y
    assert (TURRET_FREE_PLACE_RADIUS, base_y) in turret_offsets
    assert (-TURRET_FREE_PLACE_RADIUS, base_y) in turret_offsets


def test_home_station_offset_clears_player_radius():
    """Home Station must sit far enough from the player that the
    ship doesn't end up trapped inside the structure (player ship
    radius 28 + building radius 30 = 58 px clearance minimum;
    we use a generous 200 px shift so the bot can manoeuvre
    after the build completes)."""
    from constants import SHIP_RADIUS, BUILDING_RADIUS
    hs_offsets = [
        (dx, dy) for (bt, dx, dy) in bot_builder.STARTER_BASE_SEQUENCE
        if bt == "Home Station"
    ]
    assert len(hs_offsets) == 1
    dx, dy = hs_offsets[0]
    import math
    dist = math.hypot(dx, dy)
    min_clearance = SHIP_RADIUS + BUILDING_RADIUS + 50  # 50 px buffer
    assert dist >= min_clearance, (
        f"Home Station offset {dist:.0f} px must be >= "
        f"{min_clearance:.0f} px for the ship to escape after build")


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


# ── Max-count defensive guard ─────────────────────────────────────────────


def test_skips_max_one_buildings_that_already_exist(monkeypatch):
    """Defensive guard: ``place_building`` doesn't enforce
    max-count (that's the build-menu UI's job).  bot_builder must
    skip max=1 types that are already in the building list, or a
    re-trigger would create duplicates."""
    import building_manager as bm
    placed_types: list = []

    def _enter(gv, bt):
        pass

    def _place(gv, wx, wy):
        placed_types.append("placed")
        gv.building_list.append(SimpleNamespace())

    monkeypatch.setattr(bm, "enter_placement_mode", _enter)
    monkeypatch.setattr(bm, "place_building", _place)
    monkeypatch.setattr(bm, "cancel_placement", lambda gv: None)

    # Pre-seed building_list with an existing Home Station + Service Module.
    existing = [
        SimpleNamespace(building_type="Home Station"),
        SimpleNamespace(building_type="Service Module"),
        SimpleNamespace(building_type="Repair Module"),
    ]
    gv = _stub_gv(buildings=list(existing))
    result = bot_builder.build_starter_base(gv)

    # max=1 entries (Home Station, Repair Module) skipped + Service
    # Module skipped.  4 buildings placed (PR, SA2, T2, T2).
    skipped_types = [f["type"] for f in result["failed"]
                     if "max-count" in f.get("reason", "")]
    assert "Home Station" in skipped_types
    assert "Repair Module" in skipped_types
    # Service Module is max=4, only 1 exists, so it should still place.
    assert "Service Module" not in skipped_types


def test_no_max_skip_when_below_limit(monkeypatch):
    """max=4 Service Module with 1 existing → should still place."""
    import building_manager as bm

    def _place(gv, wx, wy):
        gv.building_list.append(SimpleNamespace())

    monkeypatch.setattr(bm, "enter_placement_mode", lambda gv, bt: None)
    monkeypatch.setattr(bm, "place_building", _place)
    monkeypatch.setattr(bm, "cancel_placement", lambda gv: None)

    gv = _stub_gv(buildings=[
        SimpleNamespace(building_type="Service Module")])
    result = bot_builder.build_starter_base(gv)
    skipped_types = [f["type"] for f in result["failed"]
                     if "max-count" in f.get("reason", "")]
    assert "Service Module" not in skipped_types
