"""Planetary base-building logic (docs/planets.md section 10).

Pure-ish helpers for the surface build system: the build-slot budget,
power-grid connectivity, and placement validation.  They operate on plain
iterables of "building" objects exposing ``.spec`` (a
``specs.PlanetaryBuildingSpec``) plus ``.center_x`` / ``.center_y`` (and,
for the power grid, a settable ``.powered``), so they're testable without a
GameView or GL context.

Power model: a provider (Home Base / Wind / Solar / Fission) is always
powered.  A consumer ("needs") is powered iff it is reachable — through a
graph where any two buildings within ``PB_POWER_LINK_DIST`` are linked —
from some provider.  Power Lines (``conduit``) are ordinary graph nodes, so
chaining them extends a provider's reach to distant defenses.
"""
from __future__ import annotations

import math
from typing import Iterable

from constants import (
    PB_POWER_LINK_DIST, PB_HOME_RADIUS, PB_BUILDING_RADIUS, PB_BASE_BUDGET,
)
from specs import PLANETARY_BUILDINGS


# ── Budget + slots ────────────────────────────────────────────────────────────

def build_budget(buildings: Iterable) -> int:
    """Total build-slot budget = base + every placed building's bonus."""
    return PB_BASE_BUDGET + sum(b.spec.budget_bonus for b in buildings)


def slots_used(buildings: Iterable) -> int:
    """Build slots consumed by the placed buildings."""
    return sum(b.spec.slots_used for b in buildings)


def budget_remaining(buildings: Iterable) -> int:
    bs = list(buildings)
    return build_budget(bs) - slots_used(bs)


def has_home_base(buildings: Iterable) -> bool:
    return any(b.spec.kind == "home" for b in buildings)


def find_home_base(buildings: Iterable):
    for b in buildings:
        if b.spec.kind == "home":
            return b
    return None


def count_of(buildings: Iterable, key: str) -> int:
    return sum(1 for b in buildings if b.spec.key == key)


# ── Power grid ────────────────────────────────────────────────────────────────

def compute_power(buildings: Iterable, link_dist: float = PB_POWER_LINK_DIST):
    """Set ``.powered`` on every building and return the list.

    Providers are always powered.  Consumers/conduits are powered iff
    reachable from a provider through the ``link_dist`` adjacency graph.
    """
    bs = list(buildings)
    n = len(bs)
    # Providers seed the flood; everything starts unpowered.
    for b in bs:
        b.powered = (b.spec.power_role == "provides")
    if n == 0:
        return bs
    link2 = link_dist * link_dist
    # BFS from every powered (provider) node across <= link_dist edges.
    frontier = [i for i, b in enumerate(bs) if b.powered]
    while frontier:
        nxt = []
        for i in frontier:
            bi = bs[i]
            for j in range(n):
                bj = bs[j]
                if bj.powered:
                    continue
                dx = bi.center_x - bj.center_x
                dy = bi.center_y - bj.center_y
                if dx * dx + dy * dy <= link2:
                    bj.powered = True
                    nxt.append(j)
        frontier = nxt
    return bs


# ── Placement validation ──────────────────────────────────────────────────────

def can_afford(spec, iron: int, copper: int, silicon: int) -> bool:
    return (iron >= spec.cost_iron
            and copper >= spec.cost_copper
            and silicon >= spec.cost_silicon)


def menu_availability(spec, buildings: Iterable,
                      iron: int, copper: int, silicon: int) -> tuple[bool, str]:
    """Non-spatial availability for the build menu: home-first, max count,
    budget headroom, and affordability.  Returns ``(ok, reason)``."""
    bs = list(buildings)
    if spec.kind == "home":
        if has_home_base(bs):
            return False, "Built"
    else:
        if not has_home_base(bs):
            return False, "Need Home Base"
    if spec.max_count is not None and count_of(bs, spec.key) >= spec.max_count:
        return False, "Max built"
    if slots_used(bs) + spec.slots_used > build_budget(bs):
        return False, "No power budget"
    if not can_afford(spec, iron, copper, silicon):
        return False, "Need resources"
    return True, ""


def can_place_at(spec, x: float, y: float, buildings: Iterable,
                 world_w: float, world_h: float,
                 iron: int, copper: int, silicon: int) -> tuple[bool, str]:
    """Full placement check (menu availability + spatial rules)."""
    bs = list(buildings)
    ok, reason = menu_availability(spec, bs, iron, copper, silicon)
    if not ok:
        return False, reason
    # World bounds.
    if not (0 <= x <= world_w and 0 <= y <= world_h):
        return False, "Out of bounds"
    # Home-radius rule (everything but the Home Base itself).
    if spec.kind != "home":
        home = find_home_base(bs)
        if home is not None:
            if math.hypot(x - home.center_x, y - home.center_y) > PB_HOME_RADIUS:
                return False, "Too far from Home Base"
    # Collision spacing — Power Lines have no collision footprint.
    if spec.kind != "conduit":
        for b in bs:
            if b.spec.kind == "conduit":
                continue
            min_d = PB_BUILDING_RADIUS * 2.0
            if math.hypot(x - b.center_x, y - b.center_y) < min_d:
                return False, "Too close to a building"
    return True, ""


def arc_blocks(x: float, y: float, buildings: Iterable) -> bool:
    """True if (x, y) lies inside a *powered* Arc Tower's block radius."""
    for b in buildings:
        if (b.spec.kind == "arc" and getattr(b, "powered", False)
                and b.spec.block_radius > 0.0):
            if math.hypot(x - b.center_x,
                          y - b.center_y) <= b.spec.block_radius:
                return True
    return False
