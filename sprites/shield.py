"""Animated energy-bubble shield sprite."""
from __future__ import annotations

import arcade

from constants import SHIELD_SCALE, SHIELD_ANIM_FPS, SHIELD_ROT_SPEED, SHIELD_HIT_FLASH


class ShieldSprite(arcade.Sprite):
    """Animated energy-bubble shield drawn around the player ship.

    Behaviour
    ---------
    - Visible and animated while shields > 0; invisible when depleted.
    - Rotates slowly and cycles through sprite-sheet frames for a living look.
    - Flashes bright white briefly each time it absorbs damage, then fades back
      to a semi-transparent normal state.
    """

    def __init__(self, frames: list[arcade.Texture],
                 tint: tuple[int, int, int] = (255, 255, 255),
                 scale: float = SHIELD_SCALE,
                 alpha: int = 200) -> None:
        super().__init__(path_or_texture=frames[0], scale=scale)
        self._frames = frames
        self._frame_idx: int = 0
        self._anim_timer: float = 0.0
        self._anim_interval: float = 1.0 / SHIELD_ANIM_FPS
        self._hit_timer: float = 0.0
        self._tint = tint
        self._base_alpha: int = alpha
        self.color = (*tint, alpha)

    def hit_flash(self) -> None:
        """Trigger a short bright flash -- call whenever the shield takes damage."""
        self._hit_timer = SHIELD_HIT_FLASH

    def update_shield(
        self, dt: float, ship_x: float, ship_y: float, shields: int
    ) -> None:
        """Advance animation and position.  Call once per frame."""
        self.center_x = ship_x
        self.center_y = ship_y

        if shields <= 0:
            self.color = (255, 255, 255, 0)   # fully transparent -- invisible
            return

        # ── Frame animation ─────────────────────────────────────────────────
        self._anim_timer += dt
        if self._anim_timer >= self._anim_interval:
            self._anim_timer -= self._anim_interval
            self._frame_idx = (self._frame_idx + 1) % len(self._frames)
            self.texture = self._frames[self._frame_idx]

        # ── Slow rotation ───────────────────────────────────────────────────
        self.angle = (self.angle + SHIELD_ROT_SPEED * dt) % 360.0

        # ── Hit flash ───────────────────────────────────────────────────────
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            t = self._hit_timer / SHIELD_HIT_FLASH
            a = min(255, int(self._base_alpha + 55 * t))
            self.color = (*self._tint, a)
        else:
            self.color = (*self._tint, self._base_alpha)
