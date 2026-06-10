"""Planet — a static world object the ship can ram to descend.

Phase 1 ("Reach + Descend") of the planet game mode (docs/planets.md
section 4).  A Planet is an indestructible collider placed in the Star
Maze.  Ramming it with the Planetary Landing Adapter module installed
transitions the player into the aerial Planetary Landing Scene; without
the module the ship takes collision damage instead.  The contact logic
itself lives in the owning zone (zones/star_maze.py); this sprite just
carries the texture, type, and collision radius.
"""
from __future__ import annotations

import arcade

from constants import PLANET_PNG_BY_TYPE, PLANET_SCALE, PLANET_RADIUS


class Planet(arcade.Sprite):
    """A landable planet.  ``planet_type`` is one of ``earth`` /
    ``frost`` / ``barren`` and selects both the sprite and (in a later
    phase) which surface scene loads."""

    def __init__(
        self,
        x: float,
        y: float,
        planet_type: str = "earth",
        *,
        scale: float = PLANET_SCALE,
        radius: float = PLANET_RADIUS,
    ) -> None:
        png = PLANET_PNG_BY_TYPE.get(planet_type, PLANET_PNG_BY_TYPE["earth"])
        super().__init__(path_or_texture=png, scale=scale)
        self.center_x = x
        self.center_y = y
        self.planet_type: str = planet_type
        # Collision radius used by the zone's ram check.  Independent of
        # the sprite's pixel size so tuning the art scale doesn't silently
        # change gameplay reach.
        self.radius: float = radius
