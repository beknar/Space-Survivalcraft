"""Minimap drawing extracted from HUD."""
from __future__ import annotations

import math

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    MINIMAP_X, MINIMAP_Y, MINIMAP_W, MINIMAP_H,
    FOG_CELL_SIZE, FOG_GRID_W, FOG_GRID_H,
)


def is_revealed(wx: float, wy: float, fog_grid: list[list[bool]] | None) -> bool:
    """Check if a world position has been revealed in the fog grid."""
    if fog_grid is None:
        return True
    gx = int(wx / FOG_CELL_SIZE)
    gy = int(wy / FOG_CELL_SIZE)
    _fh = len(fog_grid)
    _fw = len(fog_grid[0]) if _fh > 0 else 0
    if 0 <= gx < _fw and 0 <= gy < _fh:
        return fog_grid[gy][gx]
    return False


def draw_minimap(
    t_minimap: arcade.Text,
    asteroid_list: arcade.SpriteList,
    iron_pickup_list: arcade.SpriteList,
    alien_list: arcade.SpriteList,
    player_x: float,
    player_y: float,
    player_heading: float,
    building_list: arcade.SpriteList | None = None,
    fog_grid: list[list[bool]] | None = None,
    fog_revealed: int = 0,
    trade_station_pos: tuple[float, float] | None = None,
    boss_pos: tuple[float, float] | None = None,
    wormhole_positions: list[tuple[float, float]] | None = None,
    zone_width: float = WORLD_WIDTH,
    zone_height: float = WORLD_HEIGHT,
    gas_positions: list[tuple[float, float, float]] | None = None,
) -> None:
    """Draw a scaled overview of the world inside the status panel."""
    mx, my = MINIMAP_X, MINIMAP_Y
    mw, mh = MINIMAP_W, MINIMAP_H

    arcade.draw_rect_filled(arcade.LBWH(mx, my, mw, mh), (5, 5, 20, 245))
    arcade.draw_rect_outline(
        arcade.LBWH(mx, my, mw, mh), arcade.color.STEEL_BLUE, border_width=1,
    )
    t_minimap.draw()

    def to_map(wx: float, wy: float) -> tuple[float, float]:
        return (
            mx + (wx / zone_width) * mw,
            my + (wy / zone_height) * mh,
        )

    # Draw grey fog overlay using 4x4 block sampling
    if fog_grid is not None:
        _BLOCK = 4
        # Derive grid dims from actual fog_grid (may differ per zone)
        _fog_h = len(fog_grid)
        _fog_w = len(fog_grid[0]) if _fog_h > 0 else 0
        bw = max(1, _fog_w // _BLOCK)
        bh = max(1, _fog_h // _BLOCK)
        block_w = mw / bw
        block_h = mh / bh
        fog_colour = (60, 60, 80, 200)
        total = _fog_w * _fog_h
        if fog_revealed < total // 3:
            arcade.draw_rect_filled(
                arcade.LBWH(mx, my, mw, mh), fog_colour)
            clear_colour = (5, 5, 20, 245)
            for by in range(bh):
                run_start = -1
                for bx in range(bw):
                    gy0 = by * _BLOCK
                    gx0 = bx * _BLOCK
                    all_clear = True
                    for dy in range(min(_BLOCK, _fog_h - gy0)):
                        row = fog_grid[gy0 + dy]
                        for dx in range(min(_BLOCK, _fog_w - gx0)):
                            if not row[gx0 + dx]:
                                all_clear = False
                                break
                        if not all_clear:
                            break
                    if all_clear:
                        if run_start < 0:
                            run_start = bx
                    else:
                        if run_start >= 0:
                            arcade.draw_rect_filled(
                                arcade.LBWH(mx + run_start * block_w,
                                            my + by * block_h,
                                            (bx - run_start) * block_w,
                                            block_h), clear_colour)
                            run_start = -1
                if run_start >= 0:
                    arcade.draw_rect_filled(
                        arcade.LBWH(mx + run_start * block_w,
                                    my + by * block_h,
                                    (bw - run_start) * block_w,
                                    block_h), clear_colour)
        else:
            for by in range(bh):
                run_start = -1
                for bx in range(bw):
                    gy0 = by * _BLOCK
                    gx0 = bx * _BLOCK
                    any_fog = False
                    for dy in range(min(_BLOCK, _fog_h - gy0)):
                        row = fog_grid[gy0 + dy]
                        for dx in range(min(_BLOCK, _fog_w - gx0)):
                            if not row[gx0 + dx]:
                                any_fog = True
                                break
                        if any_fog:
                            break
                    if any_fog:
                        if run_start < 0:
                            run_start = bx
                    else:
                        if run_start >= 0:
                            arcade.draw_rect_filled(
                                arcade.LBWH(mx + run_start * block_w,
                                            my + by * block_h,
                                            (bx - run_start) * block_w,
                                            block_h), fog_colour)
                            run_start = -1
                if run_start >= 0:
                    arcade.draw_rect_filled(
                        arcade.LBWH(mx + run_start * block_w,
                                    my + by * block_h,
                                    (bw - run_start) * block_w,
                                    block_h), fog_colour)

    # Objects
    for asteroid in asteroid_list:
        if not is_revealed(asteroid.center_x, asteroid.center_y, fog_grid):
            continue
        ax, ay = to_map(asteroid.center_x, asteroid.center_y)
        arcade.draw_circle_filled(ax, ay, 2.0, (150, 150, 150))

    for pickup in iron_pickup_list:
        if not is_revealed(pickup.center_x, pickup.center_y, fog_grid):
            continue
        ppx, ppy = to_map(pickup.center_x, pickup.center_y)
        arcade.draw_circle_filled(ppx, ppy, 2.0, (255, 165, 0))

    for alien in alien_list:
        if not is_revealed(alien.center_x, alien.center_y, fog_grid):
            continue
        amx, amy = to_map(alien.center_x, alien.center_y)
        arcade.draw_circle_filled(amx, amy, 2.0, (220, 50, 50))

    if building_list is not None:
        for building in building_list:
            if not is_revealed(building.center_x, building.center_y, fog_grid):
                continue
            bbx, bby = to_map(building.center_x, building.center_y)
            arcade.draw_circle_filled(bbx, bby, 2.5, (100, 220, 255))

    # Trading station
    if trade_station_pos is not None:
        tsx, tsy = trade_station_pos
        if is_revealed(tsx, tsy, fog_grid):
            tmx, tmy = to_map(tsx, tsy)
            arcade.draw_rect_filled(
                arcade.LBWH(tmx - 3, tmy - 3, 6, 6),
                (255, 220, 50))
            arcade.draw_rect_outline(
                arcade.LBWH(tmx - 3, tmy - 3, 6, 6),
                (255, 255, 150), border_width=1)

    # Boss marker
    if boss_pos is not None:
        bpx, bpy = boss_pos
        if is_revealed(bpx, bpy, fog_grid):
            bmx, bmy = to_map(bpx, bpy)
            arcade.draw_circle_filled(bmx, bmy, 4.0, (255, 50, 50))
            arcade.draw_circle_outline(bmx, bmy, 5.5, (255, 100, 100), 1)

    # Gas areas (green dots/circles, sized proportionally)
    if gas_positions:
        map_scale = mw / zone_width  # world px to minimap px
        for entry in gas_positions:
            gpx, gpy = entry[0], entry[1]
            grad = entry[2] if len(entry) > 2 else 50.0
            if is_revealed(gpx, gpy, fog_grid):
                gmx, gmy = to_map(gpx, gpy)
                dot_r = max(1.5, grad * map_scale)
                arcade.draw_circle_filled(gmx, gmy, dot_r, (80, 200, 60, 120))

    # Wormholes (purple pulsing circles)
    if wormhole_positions:
        for wpx, wpy in wormhole_positions:
            if is_revealed(wpx, wpy, fog_grid):
                wmx, wmy = to_map(wpx, wpy)
                arcade.draw_circle_filled(wmx, wmy, 4.0, (160, 80, 255))
                arcade.draw_circle_outline(wmx, wmy, 5.5, (200, 140, 255), 1)

    # Player dot
    sx, sy = to_map(player_x, player_y)
    rad = math.radians(player_heading)
    lx = sx + math.sin(rad) * 5
    ly = sy + math.cos(rad) * 5
    arcade.draw_line(sx, sy, lx, ly, arcade.color.CYAN, 1)
    arcade.draw_circle_filled(sx, sy, 3.0, arcade.color.WHITE)
