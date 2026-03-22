"""HUD status panel and mini-map drawing for Space Survivalcraft."""
from __future__ import annotations

import math
import random

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT, STATUS_WIDTH,
    WORLD_WIDTH, WORLD_HEIGHT,
    MINIMAP_PAD, MINIMAP_W, MINIMAP_H, MINIMAP_X, MINIMAP_Y,
    FOG_CELL_SIZE, FOG_GRID_W, FOG_GRID_H,
)

# Equalizer visualizer constants
_EQ_BARS = 16          # number of frequency bars
_EQ_BAR_W = 8          # bar width in px
_EQ_GAP = 3            # gap between bars
_EQ_MAX_H = 40         # max bar height in px

# Colour palette for cascading bars (8 colours cycling)
_EQ_COLOURS = [
    (0, 200, 255),    # cyan
    (50, 180, 255),   # light blue
    (100, 120, 255),  # blue-purple
    (180, 80, 255),   # purple
    (255, 60, 200),   # magenta
    (255, 80, 100),   # red-pink
    (255, 160, 50),   # orange
    (255, 220, 50),   # yellow
]


class HUD:
    """Left-side status panel with stats, weapon display, controls, and mini-map."""

    def __init__(
        self,
        has_gamepad: bool = False,
        faction: str | None = None,
        ship_type: str | None = None,
        repair_pack_icon: arcade.Texture | None = None,
    ) -> None:
        # Store the current screen height so draw() uses the right value
        # (SCREEN_HEIGHT gets updated at runtime by apply_resolution, but
        #  the local import binding would be stale)
        self._sh = arcade.get_window().height
        cx = STATUS_WIDTH // 2
        self._t_title = arcade.Text(
            "STATUS", cx, self._sh - 26,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_iron_hud = arcade.Text("", 10, self._sh - 60,
                                       arcade.color.ORANGE, 11)
        self._t_asteroids = arcade.Text("", 10, self._sh - 80,
                                        (150, 150, 150), 11)
        self._t_aliens = arcade.Text("", 10, self._sh - 100,
                                     (220, 80, 80), 11)
        self._t_hp = arcade.Text("HP", 10, self._sh - 136,
                                 arcade.color.LIME_GREEN, 10, bold=True)
        self._t_hp_val = arcade.Text("", 10, self._sh - 164,
                                     arcade.color.WHITE, 9)
        self._t_shield = arcade.Text("SHIELD", 10, self._sh - 180,
                                     arcade.color.CYAN, 10, bold=True)
        self._t_shield_val = arcade.Text("", 10, self._sh - 208,
                                         arcade.color.WHITE, 9)
        self._t_wpn_hdr = arcade.Text("WEAPON", cx, self._sh - 226,
                                      arcade.color.LIGHT_GRAY, 9,
                                      anchor_x="center")
        self._t_wpn_name = arcade.Text("", cx, self._sh - 242,
                                       arcade.color.YELLOW, 10, bold=True,
                                       anchor_x="center")
        self._show_fps: bool = False
        self._fps: float = 60.0
        self._t_fps = arcade.Text("", 10, self._sh - 262,
                                  arcade.color.YELLOW, 10, bold=True)
        self._t_minimap = arcade.Text(
            "MINI-MAP", STATUS_WIDTH // 2,
            MINIMAP_Y + MINIMAP_H + 3,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
        )

        faction_label = faction if faction else "Legacy"
        ship_label = ship_type if ship_type else "Classic"
        self._t_faction = arcade.Text(
            f"FACTION: {faction_label}",
            10, self._sh - 282,
            arcade.color.LIGHT_BLUE, 9, bold=True,
        )
        self._t_ship_type = arcade.Text(
            f"SHIP: {ship_label}",
            10, self._sh - 298,
            arcade.color.LIGHT_GREEN, 9, bold=True,
        )
        self._t_music_hdr = arcade.Text(
            "NOW PLAYING", STATUS_WIDTH // 2, self._sh - 318,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
        )
        self._t_track_name = arcade.Text(
            "", STATUS_WIDTH // 2, self._sh - 334,
            arcade.color.KHAKI, 9, bold=True, anchor_x="center",
        )

        # Equalizer visualizer state
        self._eq_heights: list[float] = [0.0] * _EQ_BARS
        self._eq_timer: float = 0.0
        self._eq_phase: list[float] = [random.uniform(0, math.tau) for _ in range(_EQ_BARS)]
        self._eq_speed: list[float] = [random.uniform(2.0, 5.0) for _ in range(_EQ_BARS)]
        self._eq_colour_offset: float = 0.0       # cascading colour phase
        self._eq_cascade_dir: int = 1              # +1 = left-to-right, -1 = right-to-left
        self._eq_next_dir_change: float = 0.0      # timer for next random direction flip

        # Quick-use bar state (5 slots, each holds item_type or None)
        from constants import QUICK_USE_SLOTS, QUICK_USE_CELL
        self._qu_slots: list[str | None] = [None] * QUICK_USE_SLOTS
        self._qu_counts: list[int] = [0] * QUICK_USE_SLOTS
        self._qu_cell = QUICK_USE_CELL
        self._qu_count = QUICK_USE_SLOTS
        self._repair_pack_icon = repair_pack_icon
        self._t_qu_label = arcade.Text("QUICK USE", STATUS_WIDTH // 2, 0,
                                       arcade.color.LIGHT_GRAY, 8,
                                       anchor_x="center")
        self._t_qu_num = arcade.Text("", 0, 0, arcade.color.WHITE, 8, bold=True,
                                     anchor_x="center", anchor_y="center")

        # Quick-use drag state (for moving items between slots)
        self._qu_drag_src: int | None = None
        self._qu_drag_type: str | None = None
        self._qu_drag_count: int = 0
        self._qu_drag_x: float = 0.0
        self._qu_drag_y: float = 0.0

    def set_quick_use(self, slot: int, item_type: str | None, count: int = 0) -> None:
        """Set a quick-use slot (0-indexed)."""
        if 0 <= slot < self._qu_count:
            self._qu_slots[slot] = item_type
            self._qu_counts[slot] = count

    def get_quick_use(self, slot: int) -> str | None:
        """Get the item type in a quick-use slot (0-indexed)."""
        if 0 <= slot < self._qu_count:
            return self._qu_slots[slot]
        return None

    def slot_at(self, x: float, y: float) -> int | None:
        """Return quick-use slot index (0-based) at screen coords, or None."""
        qu_total_w = self._qu_count * self._qu_cell + (self._qu_count - 1) * 2
        qu_x = (STATUS_WIDTH - qu_total_w) // 2
        qu_y = self._sh - 346 - _EQ_MAX_H - self._qu_cell - 20
        if y < qu_y or y > qu_y + self._qu_cell:
            return None
        for i in range(self._qu_count):
            sx = qu_x + i * (self._qu_cell + 2)
            if sx <= x <= sx + self._qu_cell:
                return i
        return None

    def toggle_fps(self) -> None:
        self._show_fps = not self._show_fps

    @property
    def show_fps(self) -> bool:
        return self._show_fps

    def update_fps(self, delta_time: float) -> None:
        if delta_time > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / delta_time)
        # Update equalizer animation
        self._eq_timer += delta_time
        from settings import audio
        vol = audio.music_volume
        # Advance cascading colour offset
        self._eq_colour_offset += delta_time * 3.0 * self._eq_cascade_dir
        # Randomly flip cascade direction every 2-5 seconds
        self._eq_next_dir_change -= delta_time
        if self._eq_next_dir_change <= 0:
            self._eq_cascade_dir = random.choice([-1, 1])
            self._eq_next_dir_change = random.uniform(2.0, 5.0)
        for i in range(_EQ_BARS):
            # Each bar oscillates at its own frequency with volume scaling
            target = (0.3 + 0.7 * abs(math.sin(
                self._eq_timer * self._eq_speed[i] + self._eq_phase[i]
            ))) * vol
            # Bass and treble bars are typically higher
            if i < 3 or i > _EQ_BARS - 3:
                target *= 0.6
            else:
                target *= 0.8 + 0.4 * abs(math.sin(self._eq_timer * 1.5 + i))
            # Smooth interpolation (fast rise, slow fall)
            if target > self._eq_heights[i]:
                self._eq_heights[i] += (target - self._eq_heights[i]) * min(1.0, delta_time * 12)
            else:
                self._eq_heights[i] += (target - self._eq_heights[i]) * min(1.0, delta_time * 4)

    def draw(
        self,
        iron: int,
        weapon_name: str,
        hp: int,
        max_hp: int,
        shields: int,
        max_shields: int,
        asteroid_list: arcade.SpriteList,
        iron_pickup_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
        player_x: float,
        player_y: float,
        player_heading: float,
        track_name: str = "",
        building_list: arcade.SpriteList | None = None,
        fog_grid: list[list[bool]] | None = None,
        video_active: bool = False,
    ) -> None:
        """Draw the full HUD status panel."""
        # Panel background
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, STATUS_WIDTH, self._sh),
            (15, 15, 40, 235),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(0, 0, STATUS_WIDTH, self._sh),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        self._t_title.draw()
        self._t_hp.draw()
        self._t_shield.draw()
        self._t_wpn_hdr.draw()
        if self._show_fps:
            self._t_fps.text = f"FPS  {self._fps:>6.1f}"
            self._t_fps.draw()

        self._t_iron_hud.text = f"IRON  {iron:>7}"
        self._t_iron_hud.draw()
        self._t_asteroids.text = f"ROIDS {len(asteroid_list):>5}"
        self._t_asteroids.draw()
        self._t_aliens.text = f"ALIEN {len(alien_list):>5}"
        self._t_aliens.draw()
        self._t_wpn_name.text = weapon_name
        self._t_wpn_name.draw()

        # HP bar
        hp_frac = max(0.0, hp / max_hp) if max_hp > 0 else 0.0
        hp_color = (
            (0, 180, 0) if hp_frac > 0.5
            else (220, 140, 0) if hp_frac > 0.25
            else (200, 30, 30)
        )
        arcade.draw_rect_filled(
            arcade.LBWH(10, self._sh - 152, int(190 * hp_frac), 10),
            hp_color,
        )
        # HP numerical value
        self._t_hp_val.text = f"{hp} / {max_hp}"
        self._t_hp_val.draw()

        # Shield bar
        shield_frac = max(0.0, shields / max_shields) if max_shields > 0 else 0.0
        arcade.draw_rect_filled(
            arcade.LBWH(10, self._sh - 196, int(190 * shield_frac), 10),
            (0, 140, 210),
        )
        # Shield numerical value
        self._t_shield_val.text = f"{shields} / {max_shields}"
        self._t_shield_val.draw()

        self._t_faction.draw()
        self._t_ship_type.draw()

        # Now-playing track name
        if track_name:
            self._t_music_hdr.draw()
            self._t_track_name.text = track_name
            self._t_track_name.draw()

        # Equalizer visualizer (only when music is playing, not video)
        if track_name and not video_active:
            eq_total_w = _EQ_BARS * _EQ_BAR_W + (_EQ_BARS - 1) * _EQ_GAP
            eq_x = (STATUS_WIDTH - eq_total_w) // 2
            # Position below the track name text with spacing
            eq_y = self._sh - 346 - _EQ_MAX_H
            for i in range(_EQ_BARS):
                h = int(self._eq_heights[i] * _EQ_MAX_H)
                if h < 2:
                    h = 2
                bx = eq_x + i * (_EQ_BAR_W + _EQ_GAP)
                # Cascading colour: each bar picks from palette based on
                # position + time offset, creating a wave of colour
                colour_idx = (self._eq_colour_offset + i * 0.5) % len(_EQ_COLOURS)
                idx_a = int(colour_idx) % len(_EQ_COLOURS)
                idx_b = (idx_a + 1) % len(_EQ_COLOURS)
                frac = colour_idx - int(colour_idx)
                ca, cb = _EQ_COLOURS[idx_a], _EQ_COLOURS[idx_b]
                r = int(ca[0] + (cb[0] - ca[0]) * frac)
                g = int(ca[1] + (cb[1] - ca[1]) * frac)
                b_col = int(ca[2] + (cb[2] - ca[2]) * frac)
                arcade.draw_rect_filled(
                    arcade.LBWH(bx, eq_y, _EQ_BAR_W, h),
                    (r, g, b_col, 230),
                )

        # Quick-use bar (5 slots labeled 1–5)
        # Position below the equalizer (eq bottom = _sh - 346 - _EQ_MAX_H)
        qu_total_w = self._qu_count * self._qu_cell + (self._qu_count - 1) * 2
        qu_x = (STATUS_WIDTH - qu_total_w) // 2
        qu_y = self._sh - 346 - _EQ_MAX_H - self._qu_cell - 20
        self._t_qu_label.y = qu_y + self._qu_cell + 8
        self._t_qu_label.draw()
        for i in range(self._qu_count):
            sx = qu_x + i * (self._qu_cell + 2)
            is_drag_src = (i == self._qu_drag_src)
            filled = self._qu_slots[i] is not None and not is_drag_src
            if is_drag_src:
                fill = (60, 60, 20, 200)
            elif filled:
                fill = (50, 70, 50, 220)
            else:
                fill = (25, 25, 50, 200)
            arcade.draw_rect_filled(
                arcade.LBWH(sx, qu_y, self._qu_cell, self._qu_cell), fill,
            )
            arcade.draw_rect_outline(
                arcade.LBWH(sx, qu_y, self._qu_cell, self._qu_cell),
                (80, 100, 140), border_width=1,
            )
            # Slot number
            self._t_qu_num.text = str(i + 1)
            self._t_qu_num.x = sx + self._qu_cell // 2
            self._t_qu_num.y = qu_y + self._qu_cell - 6
            self._t_qu_num.color = (160, 160, 160)
            self._t_qu_num.draw()
            # Item icon/label (skip source slot during drag)
            if self._qu_slots[i] is not None and not is_drag_src:
                if self._qu_slots[i] == "repair_pack" and self._repair_pack_icon is not None:
                    icon = self._repair_pack_icon
                    icon_pad = 4
                    icon_size = self._qu_cell - icon_pad * 2
                    arcade.draw_texture_rect(
                        icon,
                        arcade.LBWH(sx + icon_pad, qu_y + icon_pad + 2,
                                    icon_size, icon_size - 4),
                    )
                else:
                    self._t_qu_num.text = self._qu_slots[i][:3].upper()
                    self._t_qu_num.y = qu_y + self._qu_cell // 2 - 2
                    self._t_qu_num.color = arcade.color.YELLOW
                    self._t_qu_num.draw()
                if self._qu_counts[i] > 0:
                    self._t_qu_num.text = str(self._qu_counts[i])
                    self._t_qu_num.x = sx + self._qu_cell // 2
                    self._t_qu_num.y = qu_y + 4
                    self._t_qu_num.color = arcade.color.ORANGE
                    self._t_qu_num.draw()

        # Floating drag preview for quick-use
        if self._qu_drag_src is not None and self._qu_drag_type is not None:
            cs = self._qu_cell
            fx = self._qu_drag_x - cs // 2
            fy = self._qu_drag_y - cs // 2
            arcade.draw_rect_filled(
                arcade.LBWH(fx, fy, cs, cs), (70, 90, 40, 180),
            )
            arcade.draw_rect_outline(
                arcade.LBWH(fx, fy, cs, cs),
                arcade.color.YELLOW, border_width=2,
            )
            if self._qu_drag_type == "repair_pack" and self._repair_pack_icon is not None:
                icon = self._repair_pack_icon
                icon_pad = 4
                icon_size = cs - icon_pad * 2
                arcade.draw_texture_rect(
                    icon,
                    arcade.LBWH(fx + icon_pad, fy + icon_pad + 2,
                                icon_size, icon_size - 4),
                    alpha=200,
                )
            else:
                self._t_qu_num.text = self._qu_drag_type[:3].upper()
                self._t_qu_num.x = fx + cs // 2
                self._t_qu_num.y = fy + cs // 2 - 2
                self._t_qu_num.color = arcade.color.YELLOW
                self._t_qu_num.draw()
            if self._qu_drag_count > 0:
                self._t_qu_num.text = str(self._qu_drag_count)
                self._t_qu_num.x = fx + cs // 2
                self._t_qu_num.y = fy + 4
                self._t_qu_num.color = arcade.color.ORANGE
                self._t_qu_num.draw()

        self._draw_minimap(
            asteroid_list, iron_pickup_list, alien_list,
            player_x, player_y, player_heading,
            building_list=building_list,
            fog_grid=fog_grid,
        )

    @staticmethod
    def _is_revealed(wx: float, wy: float, fog_grid: list[list[bool]] | None) -> bool:
        """Check if a world position has been revealed in the fog grid."""
        if fog_grid is None:
            return True
        gx = int(wx / FOG_CELL_SIZE)
        gy = int(wy / FOG_CELL_SIZE)
        if 0 <= gx < FOG_GRID_W and 0 <= gy < FOG_GRID_H:
            return fog_grid[gy][gx]
        return False

    def _draw_minimap(
        self,
        asteroid_list: arcade.SpriteList,
        iron_pickup_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
        player_x: float,
        player_y: float,
        player_heading: float,
        building_list: arcade.SpriteList | None = None,
        fog_grid: list[list[bool]] | None = None,
    ) -> None:
        """Draw a scaled overview of the world inside the status panel."""
        mx, my = MINIMAP_X, MINIMAP_Y
        mw, mh = MINIMAP_W, MINIMAP_H

        arcade.draw_rect_filled(arcade.LBWH(mx, my, mw, mh), (5, 5, 20, 245))
        arcade.draw_rect_outline(
            arcade.LBWH(mx, my, mw, mh), arcade.color.STEEL_BLUE, border_width=1,
        )
        self._t_minimap.draw()

        def to_map(wx: float, wy: float) -> tuple[float, float]:
            return (
                mx + (wx / WORLD_WIDTH) * mw,
                my + (wy / WORLD_HEIGHT) * mh,
            )

        for asteroid in asteroid_list:
            if not self._is_revealed(asteroid.center_x, asteroid.center_y, fog_grid):
                continue
            ax, ay = to_map(asteroid.center_x, asteroid.center_y)
            arcade.draw_circle_filled(ax, ay, 2.0, (150, 150, 150))

        for pickup in iron_pickup_list:
            if not self._is_revealed(pickup.center_x, pickup.center_y, fog_grid):
                continue
            px, py = to_map(pickup.center_x, pickup.center_y)
            arcade.draw_circle_filled(px, py, 2.0, (255, 165, 0))

        for alien in alien_list:
            if not self._is_revealed(alien.center_x, alien.center_y, fog_grid):
                continue
            amx, amy = to_map(alien.center_x, alien.center_y)
            arcade.draw_circle_filled(amx, amy, 2.0, (220, 50, 50))

        if building_list is not None:
            for building in building_list:
                if not self._is_revealed(building.center_x, building.center_y, fog_grid):
                    continue
                bx, by = to_map(building.center_x, building.center_y)
                arcade.draw_circle_filled(bx, by, 2.5, (100, 220, 255))

        # Draw grey fog overlay on unrevealed cells
        if fog_grid is not None:
            cell_w = mw / FOG_GRID_W
            cell_h = mh / FOG_GRID_H
            fog_colour = (60, 60, 80, 200)
            for gy in range(FOG_GRID_H):
                row = fog_grid[gy]
                run_start = -1
                for gx in range(FOG_GRID_W):
                    if not row[gx]:
                        if run_start < 0:
                            run_start = gx
                    else:
                        if run_start >= 0:
                            rx = mx + run_start * cell_w
                            ry = my + gy * cell_h
                            rw = (gx - run_start) * cell_w
                            arcade.draw_rect_filled(
                                arcade.LBWH(rx, ry, rw, cell_h), fog_colour,
                            )
                            run_start = -1
                # Flush remaining run at end of row
                if run_start >= 0:
                    rx = mx + run_start * cell_w
                    ry = my + gy * cell_h
                    rw = (FOG_GRID_W - run_start) * cell_w
                    arcade.draw_rect_filled(
                        arcade.LBWH(rx, ry, rw, cell_h), fog_colour,
                    )

        sx, sy = to_map(player_x, player_y)
        rad = math.radians(player_heading)
        lx = sx + math.sin(rad) * 5
        ly = sy + math.cos(rad) * 5
        arcade.draw_line(sx, sy, lx, ly, arcade.color.CYAN, 1)
        arcade.draw_circle_filled(sx, sy, 3.0, arcade.color.WHITE)
