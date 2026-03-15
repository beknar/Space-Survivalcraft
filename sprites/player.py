"""Player ship sprite with Newtonian physics."""
from __future__ import annotations

import math
import os

import arcade

from constants import (
    SHMUP_DIR, WORLD_WIDTH, WORLD_HEIGHT,
    ROT_SPEED, THRUST, BRAKE, MAX_SPD, DAMPING,
    NOSE_OFFSET, PLAYER_MAX_HP, PLAYER_MAX_SHIELD,
)


class PlayerShip(arcade.Sprite):
    """
    Spaceship with rotation-and-thrust Newtonian physics.

    Controls
    --------
    Keyboard  : Left/Right (or A/D) to rotate, Up (or W) to thrust,
                Down (or S) for reverse brake.
    Gamepad   : Left-stick X to rotate, left-stick Y to thrust/brake.
    """

    _COLS = 4       # animation columns per row
    _ROWS = 3       # rows: 0 = idle/base, 1 = nose weapon, 2 = wing weapons
    _ANIM_FPS = 8   # thruster animation speed (frames/s)

    def __init__(self) -> None:
        sheet = os.path.join(SHMUP_DIR, "shmup_player.png")

        ss = arcade.load_spritesheet(sheet)
        fw = ss.image.width // self._COLS
        fh = ss.image.height // self._ROWS

        # Load all 12 frames: _frames[row][col]
        self._frames: list[list] = [
            [
                ss.get_texture(arcade.LBWH(col * fw, row * fh, fw, fh))
                for col in range(self._COLS)
            ]
            for row in range(self._ROWS)
        ]

        super().__init__(path_or_texture=self._frames[0][0], scale=1.5)

        # Start at world centre
        self.center_x = WORLD_WIDTH / 2
        self.center_y = WORLD_HEIGHT / 2

        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        # Compass heading: 0 = north/up, increases clockwise
        self.heading: float = 0.0

        # Ship stats
        self.hp: int = PLAYER_MAX_HP
        self.max_hp: int = PLAYER_MAX_HP
        self.shields: int = PLAYER_MAX_SHIELD
        self.max_shields: int = PLAYER_MAX_SHIELD
        self._shield_acc: float = 0.0   # fractional shield regen accumulator
        # Invincibility window after a collision
        self._collision_cd: float = 0.0

        # Thruster animation state
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
            self.heading = (self.heading - ROT_SPEED * dt) % 360
        if rotate_right:
            self.heading = (self.heading + ROT_SPEED * dt) % 360

        self.angle = self.heading

        # Thrust along visual nose direction
        rad = math.radians(self.heading)
        if thrust_fwd:
            self.vel_x += math.sin(rad) * THRUST * dt
            self.vel_y += math.cos(rad) * THRUST * dt
        if thrust_bwd:
            self.vel_x -= math.sin(rad) * BRAKE * dt
            self.vel_y -= math.cos(rad) * BRAKE * dt

        # Speed cap
        spd = math.hypot(self.vel_x, self.vel_y)
        if spd > MAX_SPD:
            scale = MAX_SPD / spd
            self.vel_x *= scale
            self.vel_y *= scale

        # Drag
        self.vel_x *= DAMPING
        self.vel_y *= DAMPING

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

        # ── Thruster animation ─────────────────────────────────────────────
        if self._intensity > 0.0:
            self._anim_timer += dt
            if self._anim_timer >= 1.0 / self._ANIM_FPS:
                self._anim_timer -= 1.0 / self._ANIM_FPS
                self._anim_col = (self._anim_col + 1) % self._COLS
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
