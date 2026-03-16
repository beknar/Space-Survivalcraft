"""Player ship sprite with Newtonian physics."""
from __future__ import annotations

import math
import os
from typing import Optional

import arcade
from PIL import Image as PILImage

from constants import (
    SHMUP_DIR, WORLD_WIDTH, WORLD_HEIGHT,
    ROT_SPEED, THRUST, BRAKE, MAX_SPD, DAMPING,
    NOSE_OFFSET, PLAYER_MAX_HP, PLAYER_MAX_SHIELD,
    FACTION_SHIPS_DIR, FACTIONS, SHIP_TYPES,
    SHIP_FRAME_SIZE, SHIP_SHEET_COLS,
)


class PlayerShip(arcade.Sprite):
    """
    Spaceship with rotation-and-thrust Newtonian physics.

    Supports two construction modes:
    1. Legacy (no arguments) — loads the shmup_player.png sheet with 4-column
       thruster animation.  Used if no faction/ship_type is provided.
    2. Faction-based — loads a single 64x64 frame from the chosen faction's
       sprite sheet.  Ship stats come from SHIP_TYPES dict.
    """

    _LEGACY_COLS = 4
    _LEGACY_ROWS = 3
    _ANIM_FPS = 8

    def __init__(
        self,
        faction: Optional[str] = None,
        ship_type: Optional[str] = None,
    ) -> None:
        self._use_legacy: bool = (faction is None or ship_type is None)

        if self._use_legacy:
            # ── Legacy shmup_player sprite ──────────────────────────────────
            sheet = os.path.join(SHMUP_DIR, "shmup_player.png")
            ss = arcade.load_spritesheet(sheet)
            fw = ss.image.width // self._LEGACY_COLS
            fh = ss.image.height // self._LEGACY_ROWS
            self._frames: list[list] = [
                [
                    ss.get_texture(arcade.LBWH(col * fw, row * fh, fw, fh))
                    for col in range(self._LEGACY_COLS)
                ]
                for row in range(self._LEGACY_ROWS)
            ]
            super().__init__(path_or_texture=self._frames[0][0], scale=1.5)

            # Default stats
            self._rot_speed: float = ROT_SPEED
            self._thrust: float = THRUST
            self._brake: float = BRAKE
            self._max_spd: float = MAX_SPD
            self._damping: float = DAMPING
            hp = PLAYER_MAX_HP
            shields = PLAYER_MAX_SHIELD
            self._shield_regen: float = 0.5
            self.guns: int = 1
        else:
            # ── Faction-based ship sprite ───────────────────────────────────
            self._frames = []   # not used for animation in faction mode
            stats = SHIP_TYPES[ship_type]
            filename = FACTIONS[faction]
            path = os.path.join(FACTION_SHIPS_DIR, filename)
            pil_img = PILImage.open(path).convert("RGBA")
            row = stats["row"]
            # Column 0 = starting (un-upgraded) ship
            x0 = 0
            y0 = row * SHIP_FRAME_SIZE
            frame = pil_img.crop((x0, y0, x0 + SHIP_FRAME_SIZE, y0 + SHIP_FRAME_SIZE))
            tex = arcade.Texture(frame)
            super().__init__(path_or_texture=tex, scale=1.5)

            self._rot_speed = stats["rot_speed"]
            self._thrust = stats["thrust"]
            self._brake = stats["brake"]
            self._max_spd = stats["max_speed"]
            self._damping = stats["damping"]
            hp = stats["hp"]
            shields = stats["shields"]
            self._shield_regen = stats["shield_regen"]
            self.guns = stats["guns"]

        # Start at world centre
        self.center_x = WORLD_WIDTH / 2
        self.center_y = WORLD_HEIGHT / 2

        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        self.heading: float = 0.0

        # Ship stats
        self.hp: int = hp
        self.max_hp: int = hp
        self.shields: int = shields
        self.max_shields: int = shields
        self._shield_acc: float = 0.0
        self._collision_cd: float = 0.0

        # Thruster animation state (legacy mode only)
        self._intensity: float = 0.0
        self._anim_timer: float = 0.0
        self._anim_col: int = 0

    def apply_input(
        self,
        dt: float,
        rotate_left: bool,
        rotate_right: bool,
        thrust_fwd: bool,
        thrust_bwd: bool,
    ) -> None:
        # Rotation
        if rotate_left:
            self.heading = (self.heading - self._rot_speed * dt) % 360
        if rotate_right:
            self.heading = (self.heading + self._rot_speed * dt) % 360

        self.angle = self.heading

        # Thrust along visual nose direction
        rad = math.radians(self.heading)
        if thrust_fwd:
            self.vel_x += math.sin(rad) * self._thrust * dt
            self.vel_y += math.cos(rad) * self._thrust * dt
        if thrust_bwd:
            self.vel_x -= math.sin(rad) * self._brake * dt
            self.vel_y -= math.cos(rad) * self._brake * dt

        # Speed cap
        spd = math.hypot(self.vel_x, self.vel_y)
        if spd > self._max_spd:
            scale = self._max_spd / spd
            self.vel_x *= scale
            self.vel_y *= scale

        # Drag
        self.vel_x *= self._damping
        self.vel_y *= self._damping

        # Integrate position, clamped to world bounds
        hw, hh = self.width / 2, self.height / 2
        self.center_x = max(hw, min(WORLD_WIDTH - hw,
                                    self.center_x + self.vel_x * dt))
        self.center_y = max(hh, min(WORLD_HEIGHT - hh,
                                    self.center_y + self.vel_y * dt))

        # ── Collision cooldown tick ────────────────────────────────────────
        if self._collision_cd > 0.0:
            self._collision_cd = max(0.0, self._collision_cd - dt)

        # ── Thruster intensity ─────────────────────────────────────────────
        if thrust_fwd:
            self._intensity = min(1.0, self._intensity + 4.0 * dt)
        else:
            self._intensity = max(0.0, self._intensity - 6.0 * dt)

        # ── Thruster animation (legacy shmup_player only) ──────────────────
        if self._use_legacy and self._frames:
            if self._intensity > 0.0:
                self._anim_timer += dt
                if self._anim_timer >= 1.0 / self._ANIM_FPS:
                    self._anim_timer -= 1.0 / self._ANIM_FPS
                    self._anim_col = (self._anim_col + 1) % self._LEGACY_COLS
            else:
                self._anim_timer = 0.0
                self._anim_col = 0
            self.texture = self._frames[0][self._anim_col]

    @property
    def nose_x(self) -> float:
        """World X of the ship's nose tip (projectile spawn point)."""
        return self.center_x + math.sin(math.radians(self.heading)) * NOSE_OFFSET

    @property
    def nose_y(self) -> float:
        """World Y of the ship's nose tip (projectile spawn point)."""
        return self.center_y + math.cos(math.radians(self.heading)) * NOSE_OFFSET
