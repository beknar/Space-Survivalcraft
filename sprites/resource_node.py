"""Resource nodes for the planet surface (docs/planets.md section 12).

A node is a static, mineable sprite: rocks yield iron, copper veins
yield copper, silicon veins yield silicon.  The owning surface zone
applies mining-beam damage and, on destruction, credits the yield and
spawns the shared asteroid-explosion animation.
"""
from __future__ import annotations

import arcade

from constants import (
    ROCK_NODE_PNG, ROCK_NODE_HP, ROCK_NODE_YIELD,
    COPPER_VEIN_PNG, COPPER_VEIN_HP, COPPER_VEIN_YIELD,
    SILICON_VEIN_PNG, SILICON_VEIN_HP, SILICON_VEIN_YIELD,
    RESOURCE_NODE_SCALE, RESOURCE_NODE_RADIUS,
)

# node_type -> (png, hp, yield_item, yield_amount)
_NODE_DEFS: dict[str, tuple] = {
    "rock":    (ROCK_NODE_PNG, ROCK_NODE_HP, "iron", ROCK_NODE_YIELD),
    "copper":  (COPPER_VEIN_PNG, COPPER_VEIN_HP, "copper", COPPER_VEIN_YIELD),
    "silicon": (SILICON_VEIN_PNG, SILICON_VEIN_HP, "silicon", SILICON_VEIN_YIELD),
}


class ResourceNode(arcade.Sprite):
    """A mineable surface node.  ``node_type`` is rock / copper / silicon."""

    def __init__(self, node_type: str, x: float, y: float) -> None:
        png, hp, yield_item, yield_amt = _NODE_DEFS[node_type]
        super().__init__(path_or_texture=png, scale=RESOURCE_NODE_SCALE)
        self.center_x = x
        self.center_y = y
        self.node_type: str = node_type
        self.hp: int = hp
        self.max_hp: int = hp
        self.yield_item: str = yield_item
        self.yield_amount: int = yield_amt
        self.radius: float = RESOURCE_NODE_RADIUS
        self._hit_timer: float = 0.0

    def take_damage(self, amount: int) -> None:
        self.hp -= int(amount)
        self._hit_timer = 0.12
        self.color = (255, 160, 160, 255)

    def update_node(self, dt: float) -> None:
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            if self._hit_timer == 0.0:
                self.color = (255, 255, 255, 255)
