"""Planetary surface buildings (docs/planets.md section 10).

``PlanetaryBuilding`` is a static placeable sprite driven by a
``specs.PlanetaryBuildingSpec``.  Turrets fire at surface enemies when
powered; the Arc Tower and Shield Generator behaviours are handled by the
surface zone (spawn-blocking / bubble) reading ``.powered`` + spec radii.

``load_planet_building_assets()`` returns a cached dict of textures keyed by
building key, plus ``"_turret_laser"`` (the turret projectile texture) and
``"_power_line"`` (a generated red conduit marker).  Cached once and shared
across instances — building textures never change at runtime.
"""
from __future__ import annotations

import math

import arcade
from PIL import Image as _PILImage

from constants import (
    PB_BUILD_SCALE, PB_TURRET_LASER_PNG, PB_TURRET_PROJ_SCALE,
)
from specs import PLANETARY_BUILDINGS as _PB
from sprites.projectile import Projectile

_HIT_FLASH_S = 0.18
_assets_cache: dict | None = None


def load_planet_building_assets() -> dict:
    """Load (once) and return the shared building texture dict."""
    global _assets_cache
    if _assets_cache is not None:
        return _assets_cache
    out: dict = {}
    for key, spec in _PB.items():
        if spec.png:
            out[key] = arcade.load_texture(spec.png)
    out["_turret_laser"] = arcade.load_texture(PB_TURRET_LASER_PNG)
    # Power Line: a generated thick red square marker (no source art).
    img = _PILImage.new("RGBA", (16, 16), (210, 40, 40, 255))
    out["_power_line"] = arcade.Texture(img)
    _assets_cache = out
    return _assets_cache


class PlanetaryBuilding(arcade.Sprite):
    """One placed surface building."""

    def __init__(self, spec, texture: arcade.Texture,
                 x: float, y: float, scale: float = PB_BUILD_SCALE) -> None:
        super().__init__(path_or_texture=texture, scale=scale)
        self.spec = spec
        self.center_x = x
        self.center_y = y
        self.hp: int = spec.hp
        self.max_hp: int = spec.hp
        self.armor: int = spec.armor
        self.radius: float = spec.radius
        self.powered: bool = (spec.power_role == "provides")
        self._hit_timer: float = 0.0
        self._fire_cd: float = 0.0          # turret fire cooldown
        self._dmg_cd: float = 0.0           # enemy-contact damage cooldown
        # Shield Generator absorb pool (drains, then the generator dies).
        self.shield_hp: int = spec.shield_absorb
        self._base_color = (255, 255, 255, 255)

    # ── Damage / lifecycle ──────────────────────────────────────────

    def take_damage(self, amount: int) -> None:
        dealt = max(1, int(amount) - self.armor)
        self.hp -= dealt
        self._hit_timer = _HIT_FLASH_S
        self.color = (255, 110, 110, 255)

    def update_building(self, dt: float) -> None:
        if self._fire_cd > 0.0:
            self._fire_cd -= dt
        if self._dmg_cd > 0.0:
            self._dmg_cd -= dt
        if self._hit_timer > 0.0:
            self._hit_timer -= dt
            if self._hit_timer <= 0.0:
                self.color = self._base_color

    # ── Turret behaviour ────────────────────────────────────────────

    def update_turret(self, dt: float, enemies, out_list,
                      laser_tex: arcade.Texture) -> None:
        """Powered turrets track + fire at the nearest alive enemy in
        detect range, emitting Projectiles into ``out_list``."""
        if self.spec.kind != "turret" or not self.powered:
            return
        target = None
        best = self.spec.detect * self.spec.detect
        for e in enemies:
            if getattr(e, "state", "alive") != "alive":
                continue
            dx = e.center_x - self.center_x
            dy = e.center_y - self.center_y
            d2 = dx * dx + dy * dy
            if d2 <= best:
                best = d2
                target = e
        if target is None:
            return
        dx = target.center_x - self.center_x
        dy = target.center_y - self.center_y
        heading = math.degrees(math.atan2(dx, dy))
        self.angle = heading
        if self._fire_cd > 0.0:
            return
        self._fire_cd = self.spec.fire_cooldown
        # Lateral offset for the twin-barrel turret.
        rad = math.radians(heading)
        perp_x, perp_y = math.cos(rad), -math.sin(rad)
        offsets = (0.0,) if self.spec.barrels <= 1 else (-8.0, 8.0)
        for off in offsets:
            sx = self.center_x + perp_x * off
            sy = self.center_y + perp_y * off
            out_list.append(Projectile(
                laser_tex, sx, sy, heading,
                self.spec.proj_speed, self.spec.fire_range,
                scale=PB_TURRET_PROJ_SCALE, damage=self.spec.damage))


def create_planet_building(spec, assets: dict,
                           x: float, y: float) -> PlanetaryBuilding:
    """Factory: build a ``PlanetaryBuilding`` for ``spec`` at (x, y)."""
    if spec.kind == "conduit":
        tex = assets["_power_line"]
    else:
        tex = assets[spec.key]
    return PlanetaryBuilding(spec, tex, x, y)
