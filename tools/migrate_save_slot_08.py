"""One-shot migration: redistribute Zone 2 objects in save slot 8
into the 50%-larger Nebula zone (6400x6400 → 9600x9600).

Preserves groups that belong together:
  - Station (Home Station + every building + trade_station)
  - Refugee NPC (parks next to station — stays at its relative offset)
  - Parked ships (ship-level placements near station)

Redistributes uniformly across the new 9600×9600 field:
  - iron_asteroids, double_iron, copper_asteroids
  - wanderers
  - aliens

Fog grid is expanded from 128×128 to 192×192 with the old revealed
cells preserved at their absolute grid positions — newly-expanded
territory (rows/cols 128–191) starts unexplored so the player has
something new to fly through.

Run:
    python tools/migrate_save_slot_08.py
"""
from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path


NEW_W = 9600
NEW_H = 9600
MARGIN = 200.0
STATION_CLEAR_RADIUS = 500.0   # no redistributed objects inside this of station
FOG_CELL_SIZE = 50             # matches constants.FOG_CELL_SIZE
OLD_GRID = 128                 # 6400 / 50
NEW_GRID = NEW_W // FOG_CELL_SIZE  # 192

_ROOT = Path(__file__).resolve().parent.parent
_SAVE = _ROOT / "saves" / "save_slot_08.json"
_BACKUP = _ROOT / "saves" / "save_slot_08.pre-expand.json"


def _station_centroid(buildings: list[dict]) -> tuple[float, float]:
    if not buildings:
        return (NEW_W / 2, NEW_H / 2)
    # Prefer the Home Station as the anchor if present.
    for b in buildings:
        if b.get("type") == "Home Station":
            return (float(b["x"]), float(b["y"]))
    xs = [float(b["x"]) for b in buildings]
    ys = [float(b["y"]) for b in buildings]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _random_pos_away_from(station_xy, rng, attempts: int = 500) -> tuple[float, float]:
    sx, sy = station_xy
    for _ in range(attempts):
        x = rng.uniform(MARGIN, NEW_W - MARGIN)
        y = rng.uniform(MARGIN, NEW_H - MARGIN)
        if math.hypot(x - sx, y - sy) >= STATION_CLEAR_RADIUS:
            return x, y
    # Fall back — centre of opposite half
    return (NEW_W - sx, NEW_H - sy)


def _redistribute(entries: list[dict], station_xy, rng) -> None:
    """In-place: set each entry's x/y to a fresh random position."""
    for e in entries:
        x, y = _random_pos_away_from(station_xy, rng)
        e["x"] = x
        e["y"] = y


def _rebuild_fog_grid(old_grid: list[list[bool]]) -> list[list[bool]]:
    """Embed the old revealed cells into a new 192×192 grid at the
    same absolute positions (old grid is 128×128).  Rows/cols past
    the old boundary start as False (unexplored new territory)."""
    new_grid = [[False] * NEW_GRID for _ in range(NEW_GRID)]
    for gy, row in enumerate(old_grid):
        if gy >= NEW_GRID:
            break
        for gx, revealed in enumerate(row):
            if gx >= NEW_GRID:
                break
            new_grid[gy][gx] = bool(revealed)
    return new_grid


def _count_revealed(grid: list[list[bool]]) -> int:
    return sum(int(bool(c)) for row in grid for c in row)


def migrate() -> None:
    assert _SAVE.exists(), f"save not found: {_SAVE}"
    # Write a .pre-expand.json backup so the original save is
    # recoverable if something downstream breaks.
    if not _BACKUP.exists():
        _BACKUP.write_bytes(_SAVE.read_bytes())
        print(f"backup -> {_BACKUP.name}")

    with _SAVE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    z2 = data.get("zone2_state")
    assert z2 is not None, "save has no zone2_state to migrate"

    seed = z2.get("world_seed", 0)
    rng = random.Random(seed ^ 0xABCD1234)

    buildings = z2.get("buildings") or []
    station_xy = _station_centroid(buildings)
    print(f"station anchor: ({station_xy[0]:.1f}, {station_xy[1]:.1f})")

    # --- Redistribute ---
    for key in ("iron_asteroids", "double_iron", "copper_asteroids",
                "wanderers", "aliens"):
        entries = z2.get(key)
        if not entries:
            continue
        before = len(entries)
        _redistribute(entries, station_xy, rng)
        print(f"  redistributed {before} {key}")

    # --- Fog grid expansion ---
    old_fog = z2.get("fog_grid")
    if old_fog is not None:
        old_revealed = _count_revealed(old_fog)
        new_fog = _rebuild_fog_grid(old_fog)
        new_revealed = _count_revealed(new_fog)
        z2["fog_grid"] = new_fog
        z2["fog_revealed"] = new_revealed
        print(f"  fog grid {len(old_fog)}x{len(old_fog[0]) if old_fog else 0} "
              f"-> {NEW_GRID}x{NEW_GRID} ({old_revealed} -> {new_revealed} revealed)")

    # --- Groups that stay together ---
    # buildings, trade_station, refugee_npc, parked_ships all keep
    # their absolute positions.  Log so the migration record shows
    # what was preserved.
    print(f"  preserved {len(buildings)} buildings in place")
    ts = z2.get("trade_station")
    if ts:
        print(f"  preserved trade_station at ({ts['x']:.1f}, {ts['y']:.1f})")
    refugee = data.get("refugee_npc")
    if refugee:
        print(f"  preserved refugee_npc at "
              f"({refugee.get('x', '?')!r}, {refugee.get('y', '?')!r})")
    parked = data.get("parked_ships") or []
    if parked:
        print(f"  preserved {len(parked)} parked_ships in place")

    with _SAVE.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"wrote -> {_SAVE.name}")


if __name__ == "__main__":
    migrate()
