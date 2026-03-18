"""Space station building sprites — modules, turrets, docking ports."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import arcade

from constants import (
    BUILDING_TYPES,
    TURRET_RANGE, TURRET_DAMAGE, TURRET_COOLDOWN,
    TURRET_LASER_SPEED, TURRET_LASER_RANGE,
    GUN_LATERAL_OFFSET, BASE_MODULE_CAPACITY,
)
from sprites.projectile import Projectile


# ── Docking port ──────────────────────────────────────────────────────────────

@dataclass
class DockingPort:
    """A single attachment point on a building module."""

    direction: str              # "N", "S", "E", "W"
    offset_x: float             # relative to building centre (before rotation)
    offset_y: float
    occupied: bool = False
    connected_to: Optional["StationModule"] = field(default=None, repr=False)

    @staticmethod
    def opposite(direction: str) -> str:
        """Return the opposite port direction."""
        return {"N": "S", "S": "N", "E": "W", "W": "E"}[direction]


# ── Base module class ─────────────────────────────────────────────────────────

class StationModule(arcade.Sprite):
    """Base class for all station building modules.

    Handles HP, docking ports, hit-flash tint, and disabled state.
    """

    _HIT_FLASH: float = 0.20

    def __init__(
        self,
        texture: arcade.Texture,
        x: float,
        y: float,
        building_type: str,
        scale: float = 0.5,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=scale)
        self.center_x = x
        self.center_y = y

        stats = BUILDING_TYPES[building_type]
        self.building_type: str = building_type
        self.hp: int = stats["hp"]
        self.max_hp: int = stats["hp"]
        self.disabled: bool = False

        self._hit_timer: float = 0.0

        # Build 4 docking ports based on sprite dimensions
        hw = (texture.width * scale) / 2
        hh = (texture.height * scale) / 2
        self.ports: list[DockingPort] = [
            DockingPort("N", 0.0,  hh),
            DockingPort("S", 0.0, -hh),
            DockingPort("E",  hw, 0.0),
            DockingPort("W", -hw, 0.0),
        ]

    def get_port_world_pos(self, port: DockingPort) -> tuple[float, float]:
        """Return the world position of a docking port, accounting for rotation."""
        rad = math.radians(self.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        rx = port.offset_x * cos_a - port.offset_y * sin_a
        ry = port.offset_x * sin_a + port.offset_y * cos_a
        return self.center_x + rx, self.center_y + ry

    def get_unoccupied_ports(self) -> list[DockingPort]:
        """Return all ports that are not yet connected."""
        return [p for p in self.ports if not p.occupied]

    def take_damage(self, amount: int) -> None:
        """Reduce HP and trigger a hit-flash."""
        self.hp = max(0, self.hp - amount)
        self._hit_timer = self._HIT_FLASH
        self.color = (255, 100, 100, 255)

    def update_building(self, dt: float) -> None:
        """Tick hit-flash timer and update tint."""
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            if self._hit_timer <= 0.0:
                self.color = (
                    (128, 128, 128, 255) if self.disabled
                    else (255, 255, 255, 255)
                )
        elif self.disabled:
            self.color = (128, 128, 128, 255)


# ── Concrete subclasses ──────────────────────────────────────────────────────

class HomeStation(StationModule):
    """The root station module.  Destroying it disables all other modules."""
    pass


class ServiceModule(StationModule):
    """General connector module that links to any other module."""
    pass


class PowerReceiver(StationModule):
    """Links Service Modules to Solar Arrays in the power chain."""
    pass


class SolarArray(StationModule):
    """Provides additional module capacity."""

    def __init__(
        self,
        texture: arcade.Texture,
        x: float, y: float,
        building_type: str,
        scale: float = 0.5,
    ) -> None:
        super().__init__(texture, x, y, building_type, scale)
        self.capacity_bonus: int = BUILDING_TYPES[building_type]["module_slots"]


class Turret(StationModule):
    """Defensive turret that auto-fires at nearby aliens."""

    def __init__(
        self,
        texture: arcade.Texture,
        x: float, y: float,
        building_type: str,
        laser_tex: arcade.Texture,
        scale: float = 0.5,
    ) -> None:
        super().__init__(texture, x, y, building_type, scale)
        self._laser_tex = laser_tex
        self._fire_cd: float = 0.0
        self._barrel_count: int = 2 if building_type == "Turret 2" else 1
        self.slots_used: int = BUILDING_TYPES[building_type]["slots_used"]

    def update_turret(
        self,
        dt: float,
        alien_list: arcade.SpriteList,
        projectile_list: arcade.SpriteList,
    ) -> None:
        """Find nearest alien in range and fire if off cooldown."""
        if self.disabled:
            return

        self._fire_cd = max(0.0, self._fire_cd - dt)

        # Find nearest alien
        best_dist = TURRET_RANGE + 1.0
        target = None
        for alien in alien_list:
            dx = alien.center_x - self.center_x
            dy = alien.center_y - self.center_y
            d = math.hypot(dx, dy)
            if d < best_dist:
                best_dist = d
                target = alien

        if target is None or best_dist > TURRET_RANGE:
            return

        # Rotate to face target
        dx = target.center_x - self.center_x
        dy = target.center_y - self.center_y
        heading = math.degrees(math.atan2(dx, dy)) % 360.0
        self.angle = heading

        # Fire
        if self._fire_cd > 0.0:
            return
        self._fire_cd = TURRET_COOLDOWN

        if self._barrel_count == 1:
            rad = math.radians(heading)
            nose_x = self.center_x + math.sin(rad) * 20.0
            nose_y = self.center_y + math.cos(rad) * 20.0
            projectile_list.append(Projectile(
                self._laser_tex, nose_x, nose_y, heading,
                TURRET_LASER_SPEED, TURRET_LASER_RANGE,
                scale=0.6, damage=TURRET_DAMAGE,
            ))
        else:
            rad = math.radians(heading)
            fwd_x = math.sin(rad) * 20.0
            fwd_y = math.cos(rad) * 20.0
            perp_x = math.cos(rad)
            perp_y = -math.sin(rad)
            for sign in (-1, 1):
                px = self.center_x + fwd_x + perp_x * GUN_LATERAL_OFFSET * sign
                py = self.center_y + fwd_y + perp_y * GUN_LATERAL_OFFSET * sign
                projectile_list.append(Projectile(
                    self._laser_tex, px, py, heading,
                    TURRET_LASER_SPEED, TURRET_LASER_RANGE,
                    scale=0.6, damage=TURRET_DAMAGE,
                ))


# ── Factory function ──────────────────────────────────────────────────────────

_TYPE_MAP = {
    "Home Station":   HomeStation,
    "Service Module": ServiceModule,
    "Power Receiver": PowerReceiver,
    "Solar Array 1":  SolarArray,
    "Solar Array 2":  SolarArray,
    "Turret 1":       Turret,
    "Turret 2":       Turret,
}


def create_building(
    building_type: str,
    texture: arcade.Texture,
    x: float,
    y: float,
    laser_tex: Optional[arcade.Texture] = None,
    scale: float = 0.5,
) -> StationModule:
    """Instantiate the correct building subclass by type name."""
    cls = _TYPE_MAP[building_type]
    if cls is Turret:
        return cls(texture, x, y, building_type, laser_tex=laser_tex, scale=scale)
    if cls is SolarArray:
        return cls(texture, x, y, building_type, scale=scale)
    return cls(texture, x, y, building_type, scale=scale)


# ── Capacity helpers ──────────────────────────────────────────────────────────

def compute_module_capacity(building_list: arcade.SpriteList) -> int:
    """Return total module capacity: base + solar array bonuses."""
    cap = BASE_MODULE_CAPACITY
    for b in building_list:
        if isinstance(b, SolarArray) and not b.disabled:
            cap += b.capacity_bonus
    return cap


def compute_modules_used(building_list: arcade.SpriteList) -> int:
    """Count modules used (Home Station excluded; Turret 2 counts as 2)."""
    count = 0
    for b in building_list:
        if b.building_type == "Home Station":
            continue
        count += BUILDING_TYPES[b.building_type]["slots_used"]
    return count
