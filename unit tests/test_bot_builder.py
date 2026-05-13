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


def test_turrets_are_at_max_free_place_radius_on_diagonals():
    """Turret 2s sit on the NE and SW corners of the Home Station
    at exactly TURRET_FREE_PLACE_RADIUS away — split evenly
    across the X and Y axes (R/√2 each).  The diagonal layout
    keeps each turret at the maximum allowed distance from the
    station while widening their effective coverage compared to
    the prior straight east/west placement."""
    from constants import TURRET_FREE_PLACE_RADIUS
    import math
    turret_offsets = [
        (dx, dy) for (bt, dx, dy) in bot_builder.STARTER_BASE_SEQUENCE
        if bt == "Turret 2"
    ]
    base_y = bot_builder._STARTER_BASE_OFFSET_Y
    diag = TURRET_FREE_PLACE_RADIUS / math.sqrt(2.0)
    expected_ne = (diag, base_y + diag)
    expected_sw = (-diag, base_y - diag)
    assert expected_ne in turret_offsets, (
        f"NE corner offset {expected_ne} not in {turret_offsets}")
    assert expected_sw in turret_offsets, (
        f"SW corner offset {expected_sw} not in {turret_offsets}")
    # Each turret must sit exactly TURRET_FREE_PLACE_RADIUS from
    # the Home Station (within float tolerance).
    for dx, dy in turret_offsets:
        dist = math.hypot(dx - 0.0, dy - base_y)
        assert abs(dist - TURRET_FREE_PLACE_RADIUS) < 1e-6, (
            f"Turret at ({dx},{dy}) is {dist:.3f} px from station; "
            f"expected {TURRET_FREE_PLACE_RADIUS}")


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
    """Both phases (Phase 1 starter base + Phase 3 extension)
    must be placed.  7 + 4 = 11 buildings expected when all
    placements succeed and no max-count gate trips."""
    calls: list = []

    def _enter(gv, bt):
        calls.append(("enter", bt))

    def _place(gv, wx, wy):
        calls.append(("place", wx, wy))
        # Simulate a successful placement -- grow building_list.
        # Tag with a building_type so max-count guard can dedupe.
        bt = calls[-2][1]   # the matching enter call
        gv.building_list.append(
            SimpleNamespace(building_type=bt))

    def _cancel(gv):
        calls.append(("cancel",))

    import building_manager as bm
    monkeypatch.setattr(bm, "enter_placement_mode", _enter)
    monkeypatch.setattr(bm, "place_building", _place)
    monkeypatch.setattr(bm, "cancel_placement", _cancel)

    gv = _stub_gv()
    # Stub inventory + station_inv so the deposit phase doesn't
    # blow up between Phase 1 and Phase 3.
    gv.inventory = SimpleNamespace(
        total_iron=0,
        count_item=lambda k: 0,
        remove_item=lambda k, n: None,
    )
    gv._station_inv = SimpleNamespace(
        add_item=lambda k, n: None,
    )
    result = bot_builder.build_starter_base(gv)

    # 7 (Phase 1) + 4 (Phase 3) = 11 buildings.
    enter_count = sum(1 for c in calls if c[0] == "enter")
    place_count = sum(1 for c in calls if c[0] == "place")
    assert enter_count == 11
    assert place_count == 11
    assert result["buildings_added"] == 11
    assert len(result["placed"]) == 11
    assert result["failed"] == []


def test_failed_placement_reported_as_rejected(monkeypatch):
    """When ``place_building`` doesn't grow ``building_list`` (the
    canonical "rejected" path — silent cancel inside the helper),
    that step lands in ``failed`` not ``placed``.  All 11 buildings
    across both phases are attempted."""
    import building_manager as bm
    monkeypatch.setattr(bm, "enter_placement_mode", lambda gv, bt: None)
    # Reject every placement.
    monkeypatch.setattr(bm, "place_building", lambda gv, wx, wy: None)
    monkeypatch.setattr(bm, "cancel_placement", lambda gv: None)

    gv = _stub_gv()
    gv.inventory = SimpleNamespace(
        total_iron=0, count_item=lambda k: 0,
        remove_item=lambda k, n: None)
    gv._station_inv = SimpleNamespace(add_item=lambda k, n: None)
    result = bot_builder.build_starter_base(gv)

    assert result["buildings_added"] == 0
    assert result["placed"] == []
    assert len(result["failed"]) == 11
    assert all(f["reason"] == "placement rejected"
               for f in result["failed"])


def test_exception_in_placement_recorded_and_continues(
        monkeypatch):
    """If ``place_building`` raises, the builder must
    ``cancel_placement`` to clear the ghost and continue with the
    next building.  10 subsequent placements (out of the 11-step
    total) should succeed after a single exception on step 1."""
    import building_manager as bm
    cancels: list = []
    placed_after_first: list = []

    enter_count = [0]
    last_enter_bt: list = []
    def _enter(gv, bt):
        enter_count[0] += 1
        last_enter_bt.append(bt)

    def _place(gv, wx, wy):
        if enter_count[0] == 1:
            raise RuntimeError("boom")
        gv.building_list.append(
            SimpleNamespace(building_type=last_enter_bt[-1]))
        placed_after_first.append(True)

    monkeypatch.setattr(bm, "enter_placement_mode", _enter)
    monkeypatch.setattr(bm, "place_building", _place)
    monkeypatch.setattr(
        bm, "cancel_placement",
        lambda gv: cancels.append(True))

    gv = _stub_gv()
    gv.inventory = SimpleNamespace(
        total_iron=0, count_item=lambda k: 0,
        remove_item=lambda k, n: None)
    gv._station_inv = SimpleNamespace(add_item=lambda k, n: None)
    result = bot_builder.build_starter_base(gv)

    # Failure on Home Station, plus 10 subsequent placements
    # succeed (6 remaining Phase 1 + 4 Phase 3).
    assert len(result["failed"]) == 1
    assert result["failed"][0]["type"] == "Home Station"
    assert "boom" in result["failed"][0]["error"]
    assert len(result["placed"]) == 10
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

    # Pre-seed building_list with an existing Home Station + Repair Module.
    existing = [
        SimpleNamespace(building_type="Home Station"),
        SimpleNamespace(building_type="Repair Module"),
    ]
    gv = _stub_gv(buildings=list(existing))
    gv.inventory = SimpleNamespace(
        total_iron=0, count_item=lambda k: 0,
        remove_item=lambda k, n: None)
    gv._station_inv = SimpleNamespace(add_item=lambda k, n: None)
    result = bot_builder.build_starter_base(gv)

    # max=1 entries (Home Station, Repair Module) skipped.
    skipped_types = [f["type"] for f in result["failed"]
                     if "max-count" in f.get("reason", "")]
    assert "Home Station" in skipped_types
    assert "Repair Module" in skipped_types


def test_no_max_skip_when_below_limit(monkeypatch):
    """max=4 Service Module with 1 existing → should still place."""
    import building_manager as bm

    last_bt: list = []
    def _enter(gv, bt):
        last_bt.append(bt)

    def _place(gv, wx, wy):
        gv.building_list.append(
            SimpleNamespace(building_type=last_bt[-1]))

    monkeypatch.setattr(bm, "enter_placement_mode", _enter)
    monkeypatch.setattr(bm, "place_building", _place)
    monkeypatch.setattr(bm, "cancel_placement", lambda gv: None)

    gv = _stub_gv(buildings=[
        SimpleNamespace(building_type="Service Module")])
    gv.inventory = SimpleNamespace(
        total_iron=0, count_item=lambda k: 0,
        remove_item=lambda k, n: None)
    gv._station_inv = SimpleNamespace(add_item=lambda k, n: None)
    result = bot_builder.build_starter_base(gv)
    skipped_types = [f["type"] for f in result["failed"]
                     if "max-count" in f.get("reason", "")]
    assert "Service Module" not in skipped_types


# ── Phase 2 deposit ───────────────────────────────────────────────────────


def _stub_inv_with_items(items_dict):
    """Build a stub inventory with ``_items`` and tracked
    add/remove/count helpers.  ``items_dict`` is {item_type: count}."""
    transfers: list = []
    # ``_items`` keyed by synthetic cell coords; one cell per type.
    items = {(i, 0): (k, v) for i, (k, v) in enumerate(items_dict.items())}

    def _count(k):
        return sum(c for (it, c) in items.values() if it == k)

    def _remove(k, n):
        transfers.append(("remove", k, n))
        for cell, (it, ct) in list(items.items()):
            if it == k:
                if ct > n:
                    items[cell] = (it, ct - n)
                else:
                    del items[cell]
                return n
        return 0

    def _add(k, n):
        transfers.append(("add", k, n))
        for cell, (it, ct) in list(items.items()):
            if it == k:
                items[cell] = (it, ct + n)
                return
        items[(len(items), 0)] = (k, n)

    inv = SimpleNamespace(
        _items=items,
        total_iron=_count("iron"),
        count_item=_count,
        remove_item=_remove,
        add_item=_add,
    )
    return inv, transfers


def test_deposit_moves_all_item_types_to_station():
    """Deposit transfers EVERY item type from ship inv (iron,
    copper, blueprints, etc.) — not just iron + copper."""
    ship, _ship_xfers = _stub_inv_with_items({
        "iron": 500, "copper": 75,
        "bp_engine_booster": 1, "bp_advanced_crafter": 2,
    })
    station, station_xfers = _stub_inv_with_items({})
    gv = SimpleNamespace(
        building_list=[SimpleNamespace(building_type="Home Station")],
        inventory=ship,
        _station_inv=station,
    )
    result = bot_builder.deposit_ship_resources_to_station(gv)
    deposited = result["deposited"]
    assert deposited.get("iron") == 500
    assert deposited.get("copper") == 75
    assert deposited.get("bp_engine_booster") == 1
    assert deposited.get("bp_advanced_crafter") == 2
    # Ship inv now empty; station has everything.
    assert station.count_item("iron") == 500
    assert station.count_item("copper") == 75
    assert station.count_item("bp_engine_booster") == 1
    assert station.count_item("bp_advanced_crafter") == 2
    assert ship.count_item("iron") == 0
    assert ship.count_item("bp_engine_booster") == 0


def test_deposit_handles_partial_when_station_full():
    """If station's add_item silently rejects (e.g. inventory
    full), the helper only removes the actually-accepted amount
    from the ship.  Items aren't lost."""
    ship, _ = _stub_inv_with_items({"iron": 500})
    # Station that swallows add_item without growing count.
    station = SimpleNamespace(
        count_item=lambda k: 0,
        add_item=lambda k, n: None,   # silently drop
    )
    gv = SimpleNamespace(
        building_list=[SimpleNamespace(building_type="Home Station")],
        inventory=ship,
        _station_inv=station,
    )
    result = bot_builder.deposit_ship_resources_to_station(gv)
    # Nothing accepted → nothing removed from ship.
    assert result["deposited"].get("iron", 0) == 0
    assert ship.count_item("iron") == 500


def test_deposit_keeps_consumables_in_ship_inventory():
    """Repair packs and shield recharges are quick-use-bound and
    must not round-trip back to the station — they stay in the
    ship inventory across deposits."""
    ship, _ = _stub_inv_with_items({
        "iron": 500,
        "repair_pack": 5,
        "shield_recharge": 5,
        "copper": 25,
    })
    station, _ = _stub_inv_with_items({})
    gv = SimpleNamespace(
        building_list=[SimpleNamespace(building_type="Home Station")],
        inventory=ship,
        _station_inv=station,
    )
    result = bot_builder.deposit_ship_resources_to_station(gv)
    deposited = result["deposited"]
    # Iron + copper went to the station as usual.
    assert deposited.get("iron") == 500
    assert deposited.get("copper") == 25
    # Consumables are absent from the deposit report and untouched
    # in both inventories.
    assert "repair_pack" not in deposited
    assert "shield_recharge" not in deposited
    assert ship.count_item("repair_pack") == 5
    assert ship.count_item("shield_recharge") == 5
    assert station.count_item("repair_pack") == 0
    assert station.count_item("shield_recharge") == 0


def test_deposit_skips_when_no_home_station():
    """No Home Station built yet → deposit is a no-op."""
    gv = SimpleNamespace(
        building_list=[],
        inventory=SimpleNamespace(
            total_iron=500,
            count_item=lambda k: 0,
            remove_item=lambda k, n: None,
        ),
        _station_inv=SimpleNamespace(add_item=lambda k, n: None),
    )
    result = bot_builder.deposit_ship_resources_to_station(gv)
    assert result["deposited"] == {}
    assert "no home station" in result.get("skipped", "")


# ── Phase 3 extension layout ──────────────────────────────────────────────


def test_extension_sequence_is_four_buildings_in_order():
    types = [bt for (bt, _, _) in bot_builder.EXTENSION_SEQUENCE]
    assert types == [
        "Service Module",
        "Power Receiver",
        "Solar Array 2",
        "Basic Crafter",
    ]


def test_extension_west_chain_extends_leftward():
    """The Service / Power Receiver / Solar Array chain runs WEST
    from the home station — each module further left than the
    previous so each can snap to its parent's W port."""
    west = [(dx, dy) for (bt, dx, dy) in bot_builder.EXTENSION_SEQUENCE
            if bt in ("Service Module",
                      "Power Receiver",
                      "Solar Array 2")]
    xs = [dx for (dx, _) in west]
    # Strictly decreasing x — each step further west than the last.
    for i in range(1, len(xs)):
        assert xs[i] < xs[i - 1], (
            f"Phase 3 west chain must extend leftward; got x={xs}")


def test_full_build_includes_basic_crafter():
    """The Basic Crafter is part of the combined sequence so the
    bot has a crafting station after one POST."""
    all_types = (
        [bt for (bt, _, _) in bot_builder.STARTER_BASE_SEQUENCE]
        + [bt for (bt, _, _) in bot_builder.EXTENSION_SEQUENCE])
    assert "Basic Crafter" in all_types


# ── Equip consumables to ship quick-use slots ────────────────────────────


class _StubHud:
    """Stub HUD that records set_quick_use calls so tests can
    assert which slots got bound to which item types."""

    def __init__(self):
        self.calls: list = []

    def set_quick_use(self, slot, item_type, count=0):
        self.calls.append((int(slot), item_type, int(count)))


def test_equip_consumables_transfers_from_station_to_ship():
    """Withdraws repair_pack + shield_recharge from station into ship
    inventory and binds them to the requested quick-use slots."""
    ship, _ = _stub_inv_with_items({})
    station, _ = _stub_inv_with_items({"repair_pack": 25,
                                       "shield_recharge": 25,
                                       "iron": 1000})
    hud = _StubHud()
    gv = SimpleNamespace(
        inventory=ship, _station_inv=station, _hud=hud,
        building_list=[],
    )
    result = bot_builder.equip_consumables_to_quick_use(gv)
    assert result["ok"] is True
    assert result["repair_pack"] == 25
    assert result["shield_recharge"] == 25
    # Ship has the consumables now; station no longer.
    assert ship.count_item("repair_pack") == 25
    assert ship.count_item("shield_recharge") == 25
    assert station.count_item("repair_pack") == 0
    assert station.count_item("shield_recharge") == 0
    # Iron untouched.
    assert station.count_item("iron") == 1000
    # HUD slots bound (slot 0 = repair, slot 1 = shield by default).
    assert (0, "repair_pack", 25) in hud.calls
    assert (1, "shield_recharge", 25) in hud.calls


def test_equip_consumables_caps_at_max_each():
    """``max_each`` caps the per-item withdraw amount so a station
    overflowing with 100 repair packs only ships 25 to the bot."""
    ship, _ = _stub_inv_with_items({})
    station, _ = _stub_inv_with_items({"repair_pack": 100,
                                       "shield_recharge": 100})
    hud = _StubHud()
    gv = SimpleNamespace(
        inventory=ship, _station_inv=station, _hud=hud,
        building_list=[],
    )
    result = bot_builder.equip_consumables_to_quick_use(
        gv, max_each=25)
    assert result["repair_pack"] == 25
    assert result["shield_recharge"] == 25
    assert ship.count_item("repair_pack") == 25
    assert station.count_item("repair_pack") == 75


def test_equip_consumables_returns_failure_when_station_empty():
    ship, _ = _stub_inv_with_items({})
    station, _ = _stub_inv_with_items({"iron": 500})
    hud = _StubHud()
    gv = SimpleNamespace(
        inventory=ship, _station_inv=station, _hud=hud,
        building_list=[],
    )
    result = bot_builder.equip_consumables_to_quick_use(gv)
    assert result["ok"] is False
    assert "no consumables" in result["reason"]
    assert hud.calls == []


def test_equip_consumables_binds_ship_side_stock_when_station_empty():
    """2026-05-12 eleventh-pass extension: when consumables are
    already in the SHIP inventory (death-drop recovery puts them
    there; deposit skips them by design) and the station has none,
    the endpoint must still bind them to quick-use slots instead
    of returning ``ok=False``.  This is the WHOLE POINT of EQUIP
    in the post-recovery scenario."""
    ship, _ = _stub_inv_with_items({"repair_pack": 3,
                                    "shield_recharge": 2})
    station, _ = _stub_inv_with_items({"iron": 500})
    hud = _StubHud()
    gv = SimpleNamespace(
        inventory=ship, _station_inv=station, _hud=hud,
        building_list=[],
    )
    result = bot_builder.equip_consumables_to_quick_use(gv)
    assert result["ok"] is True
    # Nothing was withdrawn from station (it had none).
    assert result["repair_pack"] == 0
    assert result["shield_recharge"] == 0
    # Ship totals reflect the existing cargo, slot-bound to HUD.
    assert result["ship_repair_total"] == 3
    assert result["ship_shield_total"] == 2
    assert (0, "repair_pack", 3) in hud.calls
    assert (1, "shield_recharge", 2) in hud.calls
    # Station iron untouched.
    assert station.count_item("iron") == 500


# ── Quantum Wave Integrator placement ─────────────────────────────────────


def test_place_qwi_returns_failure_without_home_station():
    gv = SimpleNamespace(building_list=[])
    result = bot_builder.place_quantum_wave_integrator(gv)
    assert result["ok"] is False
    assert "no active home station" in result["reason"]


def test_place_qwi_skips_when_already_placed():
    """Defensive — if a QWI already exists, don't place a second one
    (the BUILDING_TYPES max=1 cap would reject it; we short-circuit
    earlier so the bot doesn't hammer the placement chain)."""
    home = SimpleNamespace(
        building_type="Home Station", disabled=False,
        center_x=3200.0, center_y=3200.0)
    qwi = SimpleNamespace(building_type="Quantum Wave Integrator")
    gv = SimpleNamespace(building_list=[home, qwi])
    result = bot_builder.place_quantum_wave_integrator(gv)
    assert result["ok"] is False
    assert "already" in result["reason"].lower()


def test_place_qwi_calls_placement_chain_for_south_offset(monkeypatch):
    """First candidate is 200 px south of the Home Station."""
    home = SimpleNamespace(
        building_type="Home Station", disabled=False,
        center_x=3200.0, center_y=3200.0)
    gv = SimpleNamespace(
        building_list=[home],
        player=SimpleNamespace(center_x=3200.0, center_y=3200.0))

    placements: list = []

    def fake_enter(g, bt):
        placements.append(("enter", bt))

    def fake_place(g, wx, wy):
        placements.append(("place", wx, wy))
        # Simulate success — append a fake QWI sprite to mirror the
        # real placement's effect on building_list.
        g.building_list.append(
            SimpleNamespace(building_type="Quantum Wave Integrator"))

    import building_manager
    monkeypatch.setattr(building_manager, "enter_placement_mode",
                        fake_enter)
    monkeypatch.setattr(building_manager, "place_building", fake_place)
    result = bot_builder.place_quantum_wave_integrator(gv)
    assert result["ok"] is True
    # First (and only successful) candidate is at x=3200, y=3000
    # (200 px south of HS at y=3200).
    assert ("place", 3200.0, 3000.0) in placements
    assert ("enter", "Quantum Wave Integrator") in placements


# ── Fortify defense ring ──────────────────────────────────────────────────


def test_fortify_sequence_is_four_turret_2_entries():
    """The fortify ring is exactly 4 ``Turret 2`` entries — combined
    with the 2 starter turrets at NE/SW corners that brings the
    cluster to ``QWI_STAGE_MIN_TURRETS=6``."""
    types = [bt for (bt, _, _) in bot_builder.FORTIFY_SEQUENCE]
    assert types == ["Turret 2", "Turret 2", "Turret 2", "Turret 2"]
    assert len(bot_builder.FORTIFY_SEQUENCE) == 4


def test_fortify_offsets_are_inside_free_place_radius():
    """Every fortify offset must be within the
    ``TURRET_FREE_PLACE_RADIUS`` (300 px) limit enforced by
    ``input_handlers``; otherwise placement would be rejected."""
    import math
    from constants import TURRET_FREE_PLACE_RADIUS
    for bt, dx, dy in bot_builder.FORTIFY_SEQUENCE:
        d = math.hypot(dx, dy)
        assert d <= TURRET_FREE_PLACE_RADIUS + 0.01, (
            f"fortify {bt} at ({dx:.0f}, {dy:.0f}) is "
            f"{d:.1f} px from HS — outside the {TURRET_FREE_PLACE_RADIUS} "
            f"px free-place limit.")


def test_fortify_returns_failure_without_home_station():
    gv = SimpleNamespace(building_list=[])
    result = bot_builder.fortify_base_defenses(gv)
    assert result["ok"] is False
    assert "no home station" in result["reason"]


def test_fortify_short_circuits_when_ring_already_complete():
    """If the cluster already has 6+ defenders (manual placement,
    loaded save), fortify returns ``ok=True`` with a ``skipped``
    field so the FSM latches ``fortify_done`` without re-placing."""
    home = SimpleNamespace(
        building_type="Home Station", disabled=False,
        center_x=3200.0, center_y=3200.0)
    turrets = [SimpleNamespace(building_type="Turret 2",
                               center_x=3200.0 + i * 10.0,
                               center_y=3200.0)
               for i in range(6)]
    gv = SimpleNamespace(building_list=[home, *turrets])
    result = bot_builder.fortify_base_defenses(gv)
    assert result["ok"] is True
    assert result["placed"] == []
    assert "already complete" in result.get("skipped", "")
    assert result["defenders_now"] == 6


def test_fortify_anchors_on_home_station_not_player(monkeypatch):
    """Placement offsets translate through the Home Station's
    centre, NOT the player position — fortify fires long after the
    starter base, when the player ship has typically moved
    elsewhere."""
    home = SimpleNamespace(
        building_type="Home Station", disabled=False,
        center_x=3200.0, center_y=3200.0)
    # Player far from station to make the anchor mistake obvious if
    # it regresses.
    gv = SimpleNamespace(
        building_list=[home],
        player=SimpleNamespace(center_x=1000.0, center_y=1000.0))

    placements: list = []

    def fake_enter(g, bt):
        placements.append(("enter", bt))

    def fake_place(g, wx, wy):
        placements.append(("place", round(wx, 1), round(wy, 1)))
        g.building_list.append(
            SimpleNamespace(building_type="Turret 2",
                            center_x=wx, center_y=wy))

    import building_manager
    monkeypatch.setattr(building_manager, "enter_placement_mode",
                        fake_enter)
    monkeypatch.setattr(building_manager, "place_building", fake_place)
    result = bot_builder.fortify_base_defenses(gv)
    assert result["ok"] is True
    assert len(result["placed"]) == 4
    # Verify each placement is anchored on HS (3200, 3200), not the
    # player at (1000, 1000).
    for entry in placements:
        if entry[0] == "place":
            _, wx, wy = entry
            import math
            d = math.hypot(wx - 3200.0, wy - 3200.0)
            assert d < 320.0, (
                f"placement at ({wx}, {wy}) is {d:.1f} px from HS "
                f"— should be at most ~300 (free-place limit).")
            d_from_player = math.hypot(wx - 1000.0, wy - 1000.0)
            assert d_from_player > 1500.0, (
                f"placement at ({wx}, {wy}) is suspiciously close "
                f"to the player at (1000, 1000) — anchor regressed?")


# ── Quick-use slot trigger ────────────────────────────────────────────────


def test_use_quick_use_slot_dispatches_to_repair_pack():
    used: list = []
    hud = SimpleNamespace(get_quick_use=lambda i: "repair_pack")
    gv = SimpleNamespace(
        _hud=hud,
        _use_repair_pack=lambda slot: used.append(("rp", slot)),
        _use_shield_recharge=lambda slot: used.append(("sr", slot)),
        _fire_missile=lambda slot: used.append(("ms", slot)),
    )
    result = bot_builder.use_quick_use_slot(gv, 0)
    assert result["ok"] is True
    assert result["used"] == "repair_pack"
    assert used == [("rp", 0)]


def test_use_quick_use_slot_dispatches_to_shield_recharge():
    used: list = []
    hud = SimpleNamespace(get_quick_use=lambda i: "shield_recharge")
    gv = SimpleNamespace(
        _hud=hud,
        _use_repair_pack=lambda slot: used.append(("rp", slot)),
        _use_shield_recharge=lambda slot: used.append(("sr", slot)),
        _fire_missile=lambda slot: used.append(("ms", slot)),
    )
    result = bot_builder.use_quick_use_slot(gv, 1)
    assert result["ok"] is True
    assert result["used"] == "shield_recharge"
    assert used == [("sr", 1)]


def test_use_quick_use_slot_empty_returns_failure():
    hud = SimpleNamespace(get_quick_use=lambda i: None)
    gv = SimpleNamespace(_hud=hud)
    result = bot_builder.use_quick_use_slot(gv, 5)
    assert result["ok"] is False
    assert "empty" in result["reason"]
