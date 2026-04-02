"""Equalizer visualizer logic extracted from HUD."""
from __future__ import annotations

import math
import random

import arcade

from constants import STATUS_WIDTH

# Equalizer visualizer constants
EQ_BARS = 16
EQ_BAR_W = 8
EQ_GAP = 3
EQ_MAX_H = 40

# Colour palette for cascading bars (8 colours cycling)
EQ_COLOURS = [
    (0, 200, 255),    # cyan
    (50, 180, 255),   # light blue
    (100, 120, 255),  # blue-purple
    (180, 80, 255),   # purple
    (255, 60, 200),   # magenta
    (255, 80, 100),   # red-pink
    (255, 160, 50),   # orange
    (255, 220, 50),   # yellow
]


class EqualizerState:
    """Holds equalizer animation state and update/draw logic."""

    def __init__(self) -> None:
        self.heights: list[float] = [0.0] * EQ_BARS
        self.timer: float = 0.0
        self.phase: list[float] = [random.uniform(0, math.tau) for _ in range(EQ_BARS)]
        self.speed: list[float] = [random.uniform(2.0, 5.0) for _ in range(EQ_BARS)]
        self.colour_offset: float = 0.0
        self.cascade_dir: int = 1
        self.next_dir_change: float = 0.0

    def update(self, delta_time: float, volume: float) -> None:
        """Advance equalizer animation."""
        self.timer += delta_time
        self.colour_offset += delta_time * 3.0 * self.cascade_dir
        self.next_dir_change -= delta_time
        if self.next_dir_change <= 0:
            self.cascade_dir = random.choice([-1, 1])
            self.next_dir_change = random.uniform(2.0, 5.0)
        for i in range(EQ_BARS):
            target = (0.3 + 0.7 * abs(math.sin(
                self.timer * self.speed[i] + self.phase[i]
            ))) * volume
            if i < 3 or i > EQ_BARS - 3:
                target *= 0.6
            else:
                target *= 0.8 + 0.4 * abs(math.sin(self.timer * 1.5 + i))
            if target > self.heights[i]:
                self.heights[i] += (target - self.heights[i]) * min(1.0, delta_time * 12)
            else:
                self.heights[i] += (target - self.heights[i]) * min(1.0, delta_time * 4)

    def draw(self, eq_y: float) -> None:
        """Draw the equalizer bars at the given y position."""
        eq_total_w = EQ_BARS * EQ_BAR_W + (EQ_BARS - 1) * EQ_GAP
        eq_x = (STATUS_WIDTH - eq_total_w) // 2
        for i in range(EQ_BARS):
            h = int(self.heights[i] * EQ_MAX_H)
            if h < 2:
                h = 2
            bx = eq_x + i * (EQ_BAR_W + EQ_GAP)
            colour_idx = (self.colour_offset + i * 0.5) % len(EQ_COLOURS)
            idx_a = int(colour_idx) % len(EQ_COLOURS)
            idx_b = (idx_a + 1) % len(EQ_COLOURS)
            frac = colour_idx - int(colour_idx)
            ca, cb = EQ_COLOURS[idx_a], EQ_COLOURS[idx_b]
            r = int(ca[0] + (cb[0] - ca[0]) * frac)
            g = int(ca[1] + (cb[1] - ca[1]) * frac)
            b_col = int(ca[2] + (cb[2] - ca[2]) * frac)
            arcade.draw_rect_filled(
                arcade.LBWH(bx, eq_y, EQ_BAR_W, h),
                (r, g, b_col, 230),
            )
