"""Minimap drawing extracted from HUD."""
from __future__ import annotations

import math

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    MINIMAP_X, MINIMAP_Y, MINIMAP_W, MINIMAP_H,
    FOG_CELL_SIZE,
)

# Cached fog overlay texture — rebuilt only when fog_revealed changes enough
_fog_cache_tex: arcade.Texture | None = None
_fog_cache_revealed: int = -1
_fog_cache_grid_id: int = -1  # id() of the fog_grid list
_FOG_REBUILD_THRESHOLD: int = 8  # skip rebuild until N new cells revealed


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
    gas_always_visible: bool = False,
    parked_ship_positions: list[tuple[float, float]] | None = None,
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

    # Draw fog overlay as a cached texture (rebuilt when enough cells change)
    if fog_grid is not None:
        grid_id = id(fog_grid)
        if (_fog_cache_tex is None
                or _fog_cache_grid_id != grid_id
                or (fog_revealed - _fog_cache_revealed) >= _FOG_REBUILD_THRESHOLD):
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

    # Pre-compute fog grid dimensions once to inline visibility checks
    # (avoids per-entity function call overhead on 200+ sprites)
    _has_fog = fog_grid is not None
    if _has_fog:
        _fg = fog_grid
        _inv_cell = 1.0 / FOG_CELL_SIZE
        _fw = len(_fg[0]) if len(_fg) > 0 else 0
        _fh = len(_fg)

    asteroid_pts: list[tuple[float, float]] = []
    for asteroid in asteroid_list:
        ax_w, ay_w = asteroid.center_x, asteroid.center_y
        if _has_fog:
            gx = int(ax_w * _inv_cell)
            gy = int(ay_w * _inv_cell)
            if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                continue
        asteroid_pts.append((mx + ax_w * sx_w, my + ay_w * sy_h))
    if asteroid_pts:
        arcade.draw_points(asteroid_pts, (150, 150, 150), 4)

    pickup_pts: list[tuple[float, float]] = []
    for pickup in iron_pickup_list:
        px_w, py_w = pickup.center_x, pickup.center_y
        if _has_fog:
            gx = int(px_w * _inv_cell)
            gy = int(py_w * _inv_cell)
            if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                continue
        pickup_pts.append((mx + px_w * sx_w, my + py_w * sy_h))
    if pickup_pts:
        arcade.draw_points(pickup_pts, (255, 165, 0), 4)

    alien_pts: list[tuple[float, float]] = []
    for alien in alien_list:
        ax_w, ay_w = alien.center_x, alien.center_y
        if _has_fog:
            gx = int(ax_w * _inv_cell)
            gy = int(ay_w * _inv_cell)
            if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                continue
        alien_pts.append((mx + ax_w * sx_w, my + ay_w * sy_h))
    if alien_pts:
        arcade.draw_points(alien_pts, (220, 50, 50), 4)

    if building_list is not None:
        building_pts: list[tuple[float, float]] = []
        for building in building_list:
            bx_w, by_w = building.center_x, building.center_y
            if _has_fog:
                gx = int(bx_w * _inv_cell)
                gy = int(by_w * _inv_cell)
                if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                    continue
            building_pts.append((mx + bx_w * sx_w, my + by_w * sy_h))
        if building_pts:
            arcade.draw_points(building_pts, (100, 220, 255), 5)

    # Trading station
    if trade_station_pos is not None:
        tsx, tsy = trade_station_pos
        _vis = True
        if _has_fog:
            gx = int(tsx * _inv_cell)
            gy = int(tsy * _inv_cell)
            _vis = 0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]
        if _vis:
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
        _vis = True
        if _has_fog:
            gx = int(bpx * _inv_cell)
            gy = int(bpy * _inv_cell)
            _vis = 0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]
        if _vis:
            bmx, bmy = to_map(bpx, bpy)
            arcade.draw_circle_filled(bmx, bmy, 4.0, (255, 50, 50))
            arcade.draw_circle_outline(bmx, bmy, 5.5, (255, 100, 100), 1)

    # Gas areas (green octagonal outlines scaled to world radius)
    if gas_positions:
        _oct_angles = [math.pi / 8 + i * math.pi / 4 for i in range(8)]
        _oct_cos = [math.cos(a) for a in _oct_angles]
        _oct_sin = [math.sin(a) for a in _oct_angles]
        gas_lines: list[tuple[float, float]] = []
        for entry in gas_positions:
            gpx, gpy = entry[0], entry[1]
            if _has_fog and not gas_always_visible:
                gx = int(gpx * _inv_cell)
                gy = int(gpy * _inv_cell)
                if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                    continue
            gmx = mx + gpx * sx_w
            gmy = my + gpy * sy_h
            grad = entry[2] if len(entry) > 2 else 50.0
            dot_rx = max(2.0, grad * sx_w)
            dot_ry = max(2.0, grad * sy_h)
            for i in range(8):
                j = (i + 1) % 8
                gas_lines.append((gmx + _oct_cos[i] * dot_rx,
                                  gmy + _oct_sin[i] * dot_ry))
                gas_lines.append((gmx + _oct_cos[j] * dot_rx,
                                  gmy + _oct_sin[j] * dot_ry))
        if gas_lines:
            arcade.draw_lines(gas_lines, (100, 220, 60, 200), 1)

    # Wormholes (purple pulsing circles)
    if wormhole_positions:
        for wpx, wpy in wormhole_positions:
            _vis = True
            if _has_fog:
                gx = int(wpx * _inv_cell)
                gy = int(wpy * _inv_cell)
                _vis = 0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]
            if _vis:
                wmx, wmy = to_map(wpx, wpy)
                arcade.draw_circle_filled(wmx, wmy, 4.0, (160, 80, 255))
                arcade.draw_circle_outline(wmx, wmy, 5.5, (200, 140, 255), 1)

    # Parked ships (teal dots)
    if parked_ship_positions:
        ps_pts: list[tuple[float, float]] = []
        for spx, spy in parked_ship_positions:
            if _has_fog:
                gx = int(spx * _inv_cell)
                gy = int(spy * _inv_cell)
                if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                    continue
            ps_pts.append((mx + spx * sx_w, my + spy * sy_h))
        if ps_pts:
            arcade.draw_points(ps_pts, (0, 255, 200), 6)

    # Player dot
    sx, sy = to_map(player_x, player_y)
    rad = math.radians(player_heading)
    lx = sx + math.sin(rad) * 5
    ly = sy + math.cos(rad) * 5
    arcade.draw_line(sx, sy, lx, ly, arcade.color.CYAN, 1)
    arcade.draw_circle_filled(sx, sy, 3.0, arcade.color.WHITE)
