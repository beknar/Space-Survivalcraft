"""Asset-path constants re-exported from ``constants.py``.

``constants.py`` remains the single source of truth — this module just
exposes the subset of names that are file-system paths so callers that
only need asset locations (e.g. asset-loading utilities, build tooling)
can import from a tighter surface.

Usage::

    from constants_paths import ASTEROID_PNG, LASER_DIR

Any ``_DIR``, ``_PNG``, or ``SFX_*`` value that lives in ``constants.py``
should be listed in ``__all__`` below when it's added.
"""
from __future__ import annotations

from constants import (
    # Directories
    STARFIELD_DIR, SHMUP_DIR, FACTION_SHIPS_DIR, LASER_DIR,
    SFX_WEAPONS_DIR, SFX_EXPLOSIONS_DIR, SFX_BIO_DIR,
    SFX_VEHICLES_DIR, SFX_INTERFACE_DIR,
    MUSIC_VOL1_DIR, MUSIC_VOL2_DIR,
    # Image paths
    ASTEROID_PNG, ALIEN_SHIP_PNG, ALIEN_FX_PNG, EXPLOSION_PNG,
    IRON_ICON_PNG, SHIELD_PNG, REPAIR_PACK_PNG, SHIELD_RECHARGE_PNG,
    BLUEPRINT_PNG, MISSILE_PNG,
    NPC_REFUGEE_SHIP_PNG,
    # Sound paths
    SFX_MISSILE_LAUNCH, SFX_MISSILE_IMPACT,
    SFX_MISTY_STEP, SFX_FORCE_WALL,
)


__all__ = [
    "STARFIELD_DIR", "SHMUP_DIR", "FACTION_SHIPS_DIR", "LASER_DIR",
    "SFX_WEAPONS_DIR", "SFX_EXPLOSIONS_DIR", "SFX_BIO_DIR",
    "SFX_VEHICLES_DIR", "SFX_INTERFACE_DIR",
    "MUSIC_VOL1_DIR", "MUSIC_VOL2_DIR",
    "ASTEROID_PNG", "ALIEN_SHIP_PNG", "ALIEN_FX_PNG", "EXPLOSION_PNG",
    "IRON_ICON_PNG", "SHIELD_PNG", "REPAIR_PACK_PNG",
    "SHIELD_RECHARGE_PNG", "BLUEPRINT_PNG", "MISSILE_PNG",
    "NPC_REFUGEE_SHIP_PNG",
    "SFX_MISSILE_LAUNCH", "SFX_MISSILE_IMPACT",
    "SFX_MISTY_STEP", "SFX_FORCE_WALL",
]
