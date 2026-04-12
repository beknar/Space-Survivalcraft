"""Minimap drawing extracted from HUD."""
from __future__ import annotations

import math

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    MINIMAP_X, MINIMAP_Y, MINIMAP_W, MINIMAP_H,
    FOG_CELL_SIZE,
)

# Cached fog overlay texture — rebuilt only when fog_revealed changes
_fog_cache_tex: arcade.Texture | None = None
_fog_cache_revealed: int = -1
_fog_cache_grid_id: int = -1  # id() of the fog_grid list


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


def _build_fog_texture(
    fog_grid: list[list[bool]], mw: int, mh: int
) -> arcade.Texture:
    """Build a small RGBA image for the fog overlay, then wrap as arcade.Texture."""
    from PIL import Image as PILImage

    _fog_h = len(fog_grid)
    _fog_w = len(fog_grid[0]) if _fog_h > 0 else 0
    # Use a small image (block-sampled) to keep it fast
    _BLOCK = 4
    bw = max(1, _fog_w // _BLOCK)
    bh = max(1, _fog_h // _BLOCK)

    # Create RGBA image: fog = semi-transparent grey, clear = fully transparent
    img = PILImage.new("RGBA", (bw, bh), (0, 0, 0, 0))
    pixels = img.load()
    fog_pixel = (60, 60, 80, 200)
    clear_pixel = (0, 0, 0, 0)

    for by in range(bh):
        gy0 = by * _BLOCK
        for bx in range(bw):
            gx0 = bx * _BLOCK
            # Check if any cell in the block is still fogged
            any_fog = False
            for dy in range(min(_BLOCK, _fog_h - gy0)):
                row = fog_grid[gy0 + dy]
                for dx in range(min(_BLOCK, _fog_w - gx0)):
                    if not row[gx0 + dx]:
                        any_fog = True
                        break
                if any_fog:
                    break
            pixels[bx, bh - 1 - by] = fog_pixel if any_fog else clear_pixel

    return arcade.Texture(img)


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
    global _fog_cache_tex, _fog_cache_revealed, _fog_cache_grid_id

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

    # Draw fog overlay as a cached texture (rebuilt only when fog changes)
    if fog_grid is not None:
        grid_id = id(fog_grid)
        if (_fog_cache_tex is None
                or _fog_cache_revealed != fog_revealed
                or _fog_cache_grid_id != grid_id):
            _fog_cache_tex = _build_fog_texture(fog_grid, mw, mh)
            _fog_cache_revealed = fog_revealed
            _fog_cache_grid_id = grid_id
        arcade.draw_texture_rect(
            _fog_cache_tex,
            arcade.LBWH(mx, my, mw, mh),
        )

    # Objects — batch by colour using draw_points (one GPU call per group).
    # This is dramatically faster than per-sprite draw_circle_filled when
    # the minimap shows hundreds of asteroids and aliens.
    sx_w = mw / zone_width
    sy_h = mh / zone_height

    asteroid_pts: list[tuple[float, float]] = []
    for asteroid in asteroid_list:
        ax_w, ay_w = asteroid.center_x, asteroid.center_y
        if fog_grid is not None and not is_revealed(ax_w, ay_w, fog_grid):
            continue
        asteroid_pts.append((mx + ax_w * sx_w, my + ay_w * sy_h))
    if asteroid_pts:
        arcade.draw_points(asteroid_pts, (150, 150, 150), 4)

    pickup_pts: list[tuple[float, float]] = []
    for pickup in iron_pickup_list:
        px_w, py_w = pickup.center_x, pickup.center_y
        if fog_grid is not None and not is_revealed(px_w, py_w, fog_grid):
            continue
        pickup_pts.append((mx + px_w * sx_w, my + py_w * sy_h))
    if pickup_pts:
        arcade.draw_points(pickup_pts, (255, 165, 0), 4)

    alien_pts: list[tuple[float, float]] = []
    for alien in alien_list:
        ax_w, ay_w = alien.center_x, alien.center_y
        if fog_grid is not None and not is_revealed(ax_w, ay_w, fog_grid):
            continue
        alien_pts.append((mx + ax_w * sx_w, my + ay_w * sy_h))
    if alien_pts:
        arcade.draw_points(alien_pts, (220, 50, 50), 4)

    if building_list is not None:
        building_pts: list[tuple[float, float]] = []
        for building in building_list:
            bx_w, by_w = building.center_x, building.center_y
            if fog_grid is not None and not is_revealed(bx_w, by_w, fog_grid):
                continue
            building_pts.append((mx + bx_w * sx_w, my + by_w * sy_h))
        if building_pts:
            arcade.draw_points(building_pts, (100, 220, 255), 5)

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

    # Gas areas (green circles, sized proportionally to world radius)
    if gas_positions:
        map_scale = mw / zone_width  # world px to minimap px
        for entry in gas_positions:
            gpx, gpy = entry[0], entry[1]
            grad = entry[2] if len(entry) > 2 else 50.0
            if is_revealed(gpx, gpy, fog_grid):
                gmx, gmy = to_map(gpx, gpy)
                dot_r = max(2.0, grad * map_scale)
                arcade.draw_circle_filled(gmx, gmy, dot_r, (60, 180, 40, 100))
                arcade.draw_circle_outline(gmx, gmy, dot_r, (100, 220, 60, 180), 1)

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
