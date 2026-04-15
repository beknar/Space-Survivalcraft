"""Parked ship sprite — a player ship sitting in the world, damageable."""
from __future__ import annotations

import math

import arcade

from constants import (
    SHIP_TYPES, SHIP_LEVEL_HP_BONUS, SHIP_LEVEL_SHIELD_BONUS,
    AI_PILOT_PATROL_RADIUS, AI_PILOT_DETECT_RANGE, AI_PILOT_SPEED,
    AI_PILOT_FIRE_COOLDOWN, AI_PILOT_LASER_RANGE, AI_PILOT_LASER_SPEED,
    AI_PILOT_LASER_DAMAGE, AI_PILOT_ORBIT_RADIUS_RATIO,
    AI_PILOT_HOME_ARRIVAL_DIST,
)
from sprites.player import PlayerShip
from sprites.projectile import Projectile
from sprites.shield import ShieldSprite


_AI_SHIELD_TINT: tuple[int, int, int] = (255, 220, 80)  # yellow
_AI_SHIELD_REGEN_MULT: float = 0.5  # half the ship's normal regen rate


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
        # AI pilot state (active only when an "ai_pilot" module is installed)
        self._ai_fire_cd: float = 0.0
        # "patrol" (circle around home) | "return" (fly back to base after
        # the last enemy dies or drops out of range).  Always resets to
        # "patrol" once the ship gets within AI_PILOT_HOME_ARRIVAL_DIST
        # of the Home Station.
        self._ai_mode: str = "patrol"
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        # AI shield bubble (yellow, half regen).  Lazily constructed when
        # an ``ai_pilot`` module is first observed so `update_parked`
        # skips the cost while the ship is unpiloted without one.
        self._shield_sprite: ShieldSprite | None = None
        self._shield_list: arcade.SpriteList | None = None
        self._shield_regen_acc: float = 0.0
        self._shield_regen_rate: float = (
            stats["shield_regen"] * _AI_SHIELD_REGEN_MULT)

    @property
    def has_ai_pilot(self) -> bool:
        """True when an `ai_pilot` module is installed in one of this
        ship's module slots."""
        return "ai_pilot" in self.module_slots

    def take_damage(self, amount: int) -> None:
        """Reduce HP (shields absorb first) and trigger hit flash."""
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
            if self._shield_sprite is not None and absorbed > 0:
                self._shield_sprite.hit_flash()
        self.hp = max(0, self.hp - amount)
        self._hit_timer = self._HIT_FLASH
        self.color = (255, 100, 100, 255)

    def _ensure_ai_shield(self) -> None:
        """Lazily attach a yellow ShieldSprite when an AI pilot is
        installed."""
        if self._shield_sprite is not None:
            return
        from world_setup import get_shield_frames
        frames = get_shield_frames()
        self._shield_sprite = ShieldSprite(frames, tint=_AI_SHIELD_TINT)
        self._shield_sprite.center_x = self.center_x
        self._shield_sprite.center_y = self.center_y
        self._shield_list = arcade.SpriteList()
        self._shield_list.append(self._shield_sprite)

    def update_parked(self, dt: float) -> None:
        """Tick hit-flash timer, advance the AI shield bubble, and
        regenerate AI shields at half the ship's normal rate."""
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            if self._hit_timer <= 0.0:
                self.color = (255, 255, 255, 255)

        if self.has_ai_pilot:
            self._ensure_ai_shield()
            # Half-rate shield regen.
            if self.shields < self.max_shields:
                self._shield_regen_acc += self._shield_regen_rate * dt
                if self._shield_regen_acc >= 1.0:
                    gain = int(self._shield_regen_acc)
                    self.shields = min(self.max_shields,
                                       self.shields + gain)
                    self._shield_regen_acc -= gain
            if self._shield_sprite is not None:
                self._shield_sprite.update_shield(
                    dt, self.center_x, self.center_y, self.shields)

    def update_ai(
        self,
        dt: float,
        home_pos: tuple[float, float] | None,
        targets,
        projectile_list: arcade.SpriteList,
        laser_tex: arcade.Texture,
    ) -> None:
        """Autonomous AI tick — patrol within AI_PILOT_PATROL_RADIUS of
        the Home Station and engage enemies inside AI_PILOT_DETECT_RANGE.

        Shots are fired into ``projectile_list`` (expected to be
        ``gv.turret_projectile_list`` so existing turret-projectile
        collisions handle the damage).  ``targets`` is any iterable of
        sprites with ``center_x/center_y/hp``.  ``home_pos`` is ``None``
        when no Home Station exists, in which case the ship holds position.
        """
        if not self.has_ai_pilot or home_pos is None:
            return

        self._ai_fire_cd = max(0.0, self._ai_fire_cd - dt)

        hx, hy = home_pos
        home_dx = hx - self.center_x
        home_dy = hy - self.center_y
        home_dist = math.hypot(home_dx, home_dy)

        # Pick the nearest live target within detect range — but only if
        # it's also inside the patrol leash around home so the ship
        # doesn't chase enemies across the map.
        best = None
        best_d = AI_PILOT_DETECT_RANGE
        for t in targets:
            tx = getattr(t, "center_x", None)
            ty = getattr(t, "center_y", None)
            if tx is None or getattr(t, "hp", 0) <= 0:
                continue
            d = math.hypot(tx - self.center_x, ty - self.center_y)
            if d < best_d and math.hypot(tx - hx, ty - hy) <= (
                    AI_PILOT_PATROL_RADIUS + AI_PILOT_DETECT_RANGE):
                best_d = d
                best = t

        if best is not None:
            # Engage: cancel any pending return; fight.
            self._ai_mode = "patrol"
            tx, ty = best.center_x, best.center_y
            face_rad = math.atan2(tx - self.center_x, ty - self.center_y)
            self.heading = math.degrees(face_rad) % 360.0
            self.angle = self.heading
            desired = AI_PILOT_DETECT_RANGE * 0.6
            if best_d > desired:
                nx = math.sin(face_rad)
                ny = math.cos(face_rad)
                self.center_x += nx * AI_PILOT_SPEED * dt
                self.center_y += ny * AI_PILOT_SPEED * dt
            # Fire on cooldown.
            if self._ai_fire_cd <= 0.0 and laser_tex is not None:
                self._ai_fire_cd = AI_PILOT_FIRE_COOLDOWN
                projectile_list.append(Projectile(
                    laser_tex,
                    self.center_x, self.center_y, self.heading,
                    AI_PILOT_LASER_SPEED, AI_PILOT_LASER_RANGE,
                    scale=0.6, damage=AI_PILOT_LASER_DAMAGE,
                ))
                # "If the ship shoots at an enemy and there are no other
                # enemies in range, it should return to the base" — count
                # every other live target still inside detect range.
                others = 0
                for t in targets:
                    if t is best:
                        continue
                    if getattr(t, "hp", 0) <= 0:
                        continue
                    tx2 = getattr(t, "center_x", None)
                    ty2 = getattr(t, "center_y", None)
                    if tx2 is None:
                        continue
                    if (math.hypot(tx2 - self.center_x,
                                   ty2 - self.center_y)
                            < AI_PILOT_DETECT_RANGE):
                        others += 1
                        break
                if others == 0:
                    self._ai_mode = "return"
        else:
            # No target — either head back to base or orbit on the
            # patrol ring around home.
            if self._ai_mode == "return":
                if home_dist <= AI_PILOT_HOME_ARRIVAL_DIST:
                    self._ai_mode = "patrol"
                else:
                    nx = home_dx / home_dist if home_dist > 0 else 0.0
                    ny = home_dy / home_dist if home_dist > 0 else 0.0
                    step = min(AI_PILOT_SPEED * dt, home_dist)
                    self.center_x += nx * step
                    self.center_y += ny * step
                    self.heading = math.degrees(math.atan2(nx, ny)) % 360.0
                    self.angle = self.heading
            if self._ai_mode == "patrol":
                self._orbit_patrol(dt, hx, hy, home_dist, home_dx, home_dy)

        # Clamp to the patrol leash so numerical drift or strong enemy
        # chasing can never take the ship too far from home.
        new_dx = self.center_x - hx
        new_dy = self.center_y - hy
        new_dist = math.hypot(new_dx, new_dy)
        if new_dist > AI_PILOT_PATROL_RADIUS:
            scale = AI_PILOT_PATROL_RADIUS / new_dist
            self.center_x = hx + new_dx * scale
            self.center_y = hy + new_dy * scale

    def _orbit_patrol(self, dt: float, hx: float, hy: float,
                      home_dist: float, home_dx: float,
                      home_dy: float) -> None:
        """Circle counter-clockwise around ``(hx, hy)`` at the orbit
        radius. Radial position is corrected at the end of each step so
        the ship settles onto the ring even if it starts in the interior
        or on the edge of the leash."""
        desired_r = AI_PILOT_PATROL_RADIUS * AI_PILOT_ORBIT_RADIUS_RATIO
        step = AI_PILOT_SPEED * dt
        if home_dist < 1.0:
            # Special case — seed a radial so the orbit has a direction.
            self.center_x = hx + desired_r
            self.center_y = hy
            self.heading = 0.0
            self.angle = 0.0
            return
        # Radial vector from home → ship (reuse precomputed components)
        rx = -home_dx / home_dist
        ry = -home_dy / home_dist
        # Counter-clockwise tangent
        tx = -ry
        ty = rx
        # Move along the tangent.
        self.center_x += tx * step
        self.center_y += ty * step
        # Correct radius so the ship tracks the orbit ring.
        nx = self.center_x - hx
        ny = self.center_y - hy
        nd = math.hypot(nx, ny)
        if nd > 0.0:
            scale = desired_r / nd
            self.center_x = hx + nx * scale
            self.center_y = hy + ny * scale
        # Face along the tangent (direction of travel).
        self.heading = math.degrees(math.atan2(tx, ty)) % 360.0
        self.angle = self.heading
