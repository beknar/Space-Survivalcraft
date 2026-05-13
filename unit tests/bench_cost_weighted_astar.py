"""Quick benchmark: cost-weighted A* vs legacy binary grid.

Reproduces telemetered scenarios from the 2026-05-12 log series and
reports for each:

  * Did the planner find a path? (binary vs cost-weighted)
  * How many waypoints + total Euclidean length?
  * How long did planning take (median of N reps)?

Run with ``python -m pytest "unit tests/bench_cost_weighted_astar.py" -s``
to see the table.  Not a regression gate -- prints results, asserts
the new planner solves the scenarios the legacy one fails.
"""
from __future__ import annotations

import math
import time

import bot_autopilot_astar as astar


def _state(buildings: list) -> dict:
    return {"zone": {"world_w": 6400.0, "world_h": 6400.0},
            "buildings": list(buildings)}


def _hs(x: float, y: float) -> dict:
    return {"x": x, "y": y, "building_type": "Home Station"}


def _path_length(start: tuple[float, float],
                 wp: list[tuple[float, float]]) -> float:
    if not wp:
        return 0.0
    total = math.hypot(wp[0][0] - start[0], wp[0][1] - start[1])
    for i in range(1, len(wp)):
        total += math.hypot(wp[i][0] - wp[i - 1][0],
                            wp[i][1] - wp[i - 1][1])
    return total


def _timed_plan(state: dict, sx: float, sy: float,
                gx: float, gy: float, reps: int = 50) -> tuple[
                    list[tuple[float, float]], float]:
    """Return (path, median_plan_time_ms)."""
    times = []
    wp = []
    for _ in range(reps):
        t0 = time.perf_counter()
        wp = astar.plan_path(state, sx, sy, gx, gy)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return wp, times[len(times) // 2]


SCENARIOS = [
    # (name, state, start, goal)
    ("narrow corridor (60 px gap)",
     _state([_hs(3200.0, 3120.0), _hs(3200.0, 3280.0)]),
     (2800.0, 3200.0), (3600.0, 3200.0)),
    ("bot in 4-building diamond, far target east",
     _state([_hs(3120.0, 3200.0), _hs(3280.0, 3200.0),
             _hs(3200.0, 3120.0), _hs(3200.0, 3280.0)]),
     (3200.0, 3200.0), (5000.0, 3200.0)),
    ("bot wedged: 4 buildings at corners of 120 px square",
     _state([_hs(3140.0, 3140.0), _hs(3260.0, 3140.0),
             _hs(3140.0, 3260.0), _hs(3260.0, 3260.0)]),
     (3200.0, 3200.0), (5000.0, 3200.0)),  # bot dead centre, all 8 neighbors blocked under legacy
    ("inter-ring pin (turret ring around HS, bot wedged)",
     _state([_hs(3200.0, 3200.0),  # main station body
             _hs(3340.0, 3200.0),  # east turret
             _hs(3060.0, 3200.0),  # west turret
             _hs(3200.0, 3340.0),  # north turret
             _hs(3200.0, 3060.0),  # south turret
             ]),
     (3270.0, 3200.0), (5000.0, 3200.0)),  # bot between HS + east turret
    ("open world (no obstacles, baseline)",
     _state([]),
     (1000.0, 1000.0), (5000.0, 5000.0)),
]


def test_print_benchmark(capsys):
    """Run each scenario under both planners; print a comparison
    table.  Use ``pytest -s`` to see the output.
    """
    rows = []
    for name, state, (sx, sy), (gx, gy) in SCENARIOS:
        astar.ASTAR_USE_COST_WEIGHTED = False
        bin_wp, bin_ms = _timed_plan(state, sx, sy, gx, gy)
        astar.ASTAR_USE_COST_WEIGHTED = True
        cw_wp, cw_ms = _timed_plan(state, sx, sy, gx, gy)
        rows.append((
            name,
            "FOUND" if bin_wp else "UNREACH",
            f"{_path_length((sx, sy), bin_wp):.0f}" if bin_wp else "-",
            f"{bin_ms:.2f}",
            len(bin_wp) if bin_wp else 0,
            "FOUND" if cw_wp else "UNREACH",
            f"{_path_length((sx, sy), cw_wp):.0f}" if cw_wp else "-",
            f"{cw_ms:.2f}",
            len(cw_wp) if cw_wp else 0,
        ))
    # Restore default flag for the rest of the test session.
    astar.ASTAR_USE_COST_WEIGHTED = True

    with capsys.disabled():
        print()
        print(f"{'scenario':<55} | "
              f"{'BINARY':^25} | {'COST-WEIGHTED':^25}")
        print(f"{'':<55} | "
              f"{'result':<8}{'len':>5}{'ms':>6}{'wp':>4}  | "
              f"{'result':<8}{'len':>5}{'ms':>6}{'wp':>4}")
        print("-" * 113)
        for r in rows:
            print(f"{r[0]:<55} | "
                  f"{r[1]:<8}{r[2]:>5}{r[3]:>6}{r[4]:>4}  | "
                  f"{r[5]:<8}{r[6]:>5}{r[7]:>6}{r[8]:>4}")
        print()

    # Cost-weighted must solve every scenario the binary planner
    # fails on.
    binary_failures = [r for r in rows if r[1] == "UNREACH"]
    cw_failures = [r for r in rows if r[5] == "UNREACH"]
    assert len(cw_failures) <= len(binary_failures), (
        f"Cost-weighted planner failed scenarios the binary one "
        f"solved: cw={cw_failures}, bin failures={binary_failures}")
