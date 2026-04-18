"""Null field — a cluster of white dots that cloaks the player ship.

A player who flies into an active null field becomes invisible to
every enemy (aliens + boss). Firing a weapon or using a special
ability while inside disables the field for ``NULL_FIELD_DISABLE_S``
seconds; during the disable the field flashes red.

Drawn immediate-mode as a scatter of white dots (or red dots when
disabled) so the per-frame cost is just 2-3 GPU state changes per
field. Not an ``arcade.Sprite`` — it has no texture and doesn't
participate in SpriteList collision checks.
"""
from __future__ import annotations

import math
import random
from typing import Optional

import arcade

from constants import (
    NULL_FIELD_SIZE_MIN, NULL_FIELD_SIZE_MAX, NULL_FIELD_DISABLE_S,
    NULL_FIELD_DOT_COUNT,
)


class NullField:
    """A stealth-field patch in the world. Cloaks the player when
    active, disables for ``NULL_FIELD_DISABLE_S`` seconds when the
    player fires from inside."""

    __slots__ = (
        "center_x", "center_y", "size", "radius",
        "_disabled_timer", "_flash_phase", "_dots", "_world_dots",
    )

    def __init__(self, x: float, y: float,
                 size: Optional[int] = None,
                 rng: Optional[random.Random] = None) -> None:
        r = rng or random
        if size is None:
            size = r.randint(NULL_FIELD_SIZE_MIN, NULL_FIELD_SIZE_MAX)
        size = max(NULL_FIELD_SIZE_MIN,
                   min(NULL_FIELD_SIZE_MAX, int(size)))
        self.center_x: float = x
        self.center_y: float = y
        self.size: int = size
        self.radius: float = size / 2.0
        self._disabled_timer: float = 0.0
        self._flash_phase: float = 0.0
        # Pre-generate the dot cluster so the pattern is stable between
        # frames. Each entry is (dx, dy, dot_radius).  Dots are drawn at
        # (center_x + dx, center_y + dy) every frame.
        self._dots: list[tuple[float, float, float]] = []
        for _ in range(NULL_FIELD_DOT_COUNT):
            # Gaussian-ish scatter — denser near centre, sparser at edge.
            a = r.uniform(0.0, math.tau)
            rr = abs(r.gauss(0.0, self.radius * 0.45))
            rr = min(rr, self.radius * 0.96)
            dr = r.uniform(1.2, 2.8)
            self._dots.append((math.cos(a) * rr, math.sin(a) * rr, dr))
        # Pre-compute world-space dot positions — null fields don't
        # move so this is cached once and reused every draw call.
        self._world_dots: list[tuple[float, float]] = [
            (x + dx, y + dy) for dx, dy, _ in self._dots]

    @property
    def active(self) -> bool:
        """True when the field is cloaking — disabled timer is 0."""
        return self._disabled_timer <= 0.0

    @property
    def disabled_seconds_remaining(self) -> float:
        return max(0.0, self._disabled_timer)

    def contains_point(self, px: float, py: float) -> bool:
        """Circular bounds check — treats ``size`` as the diameter."""
        dx = px - self.center_x
        dy = py - self.center_y
        return dx * dx + dy * dy <= self.radius * self.radius

    def trigger_disable(self, duration: float = NULL_FIELD_DISABLE_S) -> None:
        """Kick off the red-flash disable. Already-disabled fields
        refresh to the full ``duration`` (firing again while disabled
        extends the penalty rather than stacking it)."""
        self._disabled_timer = max(self._disabled_timer, duration)

    def update_null_field(self, dt: float) -> None:
        if self._disabled_timer > 0.0:
            self._disabled_timer = max(0.0, self._disabled_timer - dt)
            self._flash_phase = (self._flash_phase + dt * 6.0) % math.tau

    def draw(self) -> None:
        cx, cy = self.center_x, self.center_y
        if self.active:
            # Normal: white cluster.
            for dx, dy, r in self._dots:
                arcade.draw_circle_filled(cx + dx, cy + dy, r,
                                          (230, 230, 255, 210))
        else:
            # Disabled: red flash that pulses.
            pulse = 0.6 + 0.4 * math.sin(self._flash_phase)
            red = int(240 * pulse + 15)
            alpha = int(180 * pulse + 30)
            colour = (red, 40, 40, alpha)
            for dx, dy, r in self._dots:
                arcade.draw_circle_filled(cx + dx, cy + dy, r, colour)
