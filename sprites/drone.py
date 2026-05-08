"""Re-export shim for the drone classes.

Original module split in the 2026-05-07 refactor — the actual
implementations live in:

* ``sprites.drone_base``   — ``_BaseDrone`` + module-level helpers
                              (``_load``, ``_load_snd``,
                              ``_segment_crosses_any_wall``,
                              ``_walls_from_zone``,
                              ``_iter_asteroids``,
                              ``drone_status_label``,
                              ``drone_tooltip_text``).
* ``sprites.drone_mining`` — ``MiningDrone``.
* ``sprites.drone_combat`` — ``CombatDrone``.

This shim re-exports every public name so existing
``from sprites.drone import MiningDrone`` / ``CombatDrone`` /
``drone_status_label`` etc. call sites keep working unchanged.
"""
from __future__ import annotations

from sprites.drone_base import (
    _BaseDrone,
    drone_status_label,
    drone_tooltip_text,
    _load,
    _load_snd,
    _segment_crosses_any_wall,
    _walls_from_zone,
    _iter_asteroids,
    _STUCK_PATH_THRESHOLD,
    _TEX_CACHE,
    _SND_CACHE,
)
from sprites.drone_mining import MiningDrone
from sprites.drone_combat import CombatDrone

__all__ = [
    "_BaseDrone",
    "MiningDrone",
    "CombatDrone",
    "drone_status_label",
    "drone_tooltip_text",
]
