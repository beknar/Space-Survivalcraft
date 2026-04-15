"""NPC ship sprites — non-hostile characters the player can interact with."""
from __future__ import annotations

import math

import arcade

from constants import (
    NPC_REFUGEE_SHIP_PNG, NPC_REFUGEE_APPROACH_SPEED, NPC_REFUGEE_HOLD_DIST,
    NPC_REFUGEE_LABEL,
)


class RefugeeNPCShip(arcade.Sprite):
    """A Double Star refugee that flies in from the right edge of the
    Nebula zone, approaches the player's Home Station, and holds
    position there until the player talks to them.

    Invulnerable — `take_damage` is intentionally a no-op. Hovering the
    mouse over the ship surfaces the label ``Double Star Refugee``.
    """

    label: str = NPC_REFUGEE_LABEL

    def __init__(self, x: float, y: float, target: tuple[float, float]) -> None:
        tex = arcade.load_texture(NPC_REFUGEE_SHIP_PNG)
        super().__init__(path_or_texture=tex, scale=0.6)
        self.center_x = x
        self.center_y = y
        self._target = target
        self._arrived: bool = False
        # Face the station on spawn so it looks like it's flying in.
        self._face_target()

    @property
    def arrived(self) -> bool:
        return self._arrived

    def _face_target(self) -> None:
        tx, ty = self._target
        rad = math.atan2(tx - self.center_x, ty - self.center_y)
        self.angle = math.degrees(rad) % 360.0

    def update_npc(self, dt: float) -> None:
        """Advance the approach. Once within ``NPC_REFUGEE_HOLD_DIST`` of
        the target, the ship stops and holds indefinitely."""
        if self._arrived:
            return
        tx, ty = self._target
        dx = tx - self.center_x
        dy = ty - self.center_y
        dist = math.hypot(dx, dy)
        if dist <= NPC_REFUGEE_HOLD_DIST:
            self._arrived = True
            return
        step = min(NPC_REFUGEE_APPROACH_SPEED * dt, dist - NPC_REFUGEE_HOLD_DIST)
        if step <= 0.0:
            self._arrived = True
            return
        self.center_x += dx / dist * step
        self.center_y += dy / dist * step
        self._face_target()

    # Invulnerable — absorbs damage calls for uniformity with other ship
    # sprites but never reduces HP.
    def take_damage(self, amount: int) -> None:  # noqa: D401 - matches sibling API
        return None
