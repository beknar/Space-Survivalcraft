"""Parked ship sprite — a player ship sitting in the world, damageable."""
from __future__ import annotations

import arcade

from constants import (
    SHIP_TYPES, SHIP_LEVEL_HP_BONUS, SHIP_LEVEL_SHIELD_BONUS,
)
from sprites.player import PlayerShip


class ParkedShip(arcade.Sprite):
    """A ship the player is not currently piloting.

    Persists in the world, can take damage from any source, and can be
    clicked to switch control.  Stores its own cargo and module state
    so the player's inventory swaps on switch.
    """

    _HIT_FLASH: float = 0.20

    def __init__(
        self,
        faction: str,
        ship_type: str,
        ship_level: int,
        x: float,
        y: float,
        heading: float = 0.0,
    ) -> None:
        tex = PlayerShip._extract_ship_texture(faction, ship_type, ship_level)
        super().__init__(path_or_texture=tex, scale=0.75)
        self.center_x = x
        self.center_y = y
        self.angle = heading

        self.faction: str = faction
        self.ship_type: str = ship_type
        self.ship_level: int = ship_level
        self.heading: float = heading

        stats = SHIP_TYPES[ship_type]
        level_bonus = ship_level - 1
        self.hp: int = stats["hp"] + level_bonus * SHIP_LEVEL_HP_BONUS
        self.max_hp: int = self.hp
        self.shields: int = stats["shields"] + level_bonus * SHIP_LEVEL_SHIELD_BONUS
        self.max_shields: int = self.shields

        # Per-ship cargo (same format as Inventory._items)
        self.cargo_items: dict[tuple[int, int], tuple[str, int]] = {}
        # Per-ship module slots
        self.module_slots: list[str | None] = []

        self._hit_timer: float = 0.0

    def take_damage(self, amount: int) -> None:
        """Reduce HP (shields absorb first) and trigger hit flash."""
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
        self.hp = max(0, self.hp - amount)
        self._hit_timer = self._HIT_FLASH
        self.color = (255, 100, 100, 255)

    def update_parked(self, dt: float) -> None:
        """Tick hit-flash timer."""
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            if self._hit_timer <= 0.0:
                self.color = (255, 255, 255, 255)
