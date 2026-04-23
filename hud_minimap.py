"""Minimap drawing extracted from HUD."""
from __future__ import annotations

import math
import time

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
    extra_boss_positions: list[tuple[float, float]] | None = None,
    wormhole_positions: list[tuple[float, float]] | None = None,
    zone_width: float = WORLD_WIDTH,
    zone_height: float = WORLD_HEIGHT,
    gas_positions: list[tuple[float, float, float]] | None = None,
    gas_always_visible: bool = False,
    parked_ship_positions: list[tuple[float, float]] | None = None,
    null_field_positions: list[tuple[float, float, float, bool]] | None = None,
    slipspace_positions: list[tuple[float, float]] | None = None,
    maze_rooms: list[tuple[float, float, float, float]] | None = None,
    maze_spawner_positions: list[tuple[float, float, bool]] | None = None,
    rect: tuple[int, int, int, int] | None = None,
) -> None:
    """Draw a scaled overview of the world inside the status panel.

    ``rect`` lets a caller render the same content at arbitrary
    screen coords — the full-screen map overlay reuses this function
    with a window-sized rect so it doesn't have to duplicate the
    fog + asteroid + alien + building + trade + boss + gas +
    wormhole + slipspace + null-field + parked-ship markers.
    Defaults to the HUD status-panel minimap.
    """
    global _fog_cache_tex, _fog_cache_revealed, _fog_cache_grid_id

    if rect is None:
        mx, my, mw, mh = MINIMAP_X, MINIMAP_Y, MINIMAP_W, MINIMAP_H
    else:
        mx, my, mw, mh = rect

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

    # Star Maze rooms — draw as filled dark rects before any entity
    # markers so spawner + alien dots render on top.  Pure filled
    # rects (no outline) keeps the minimap readable when 81 rooms
    # all tile the field.
    if maze_rooms:
        for (rx, ry, rw, rh) in maze_rooms:
            arcade.draw_rect_filled(
                arcade.LBWH(
                    mx + rx * sx_w, my + ry * sy_h,
                    rw * sx_w, rh * sy_h,
                ),
                (60, 40, 60, 180),
            )

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

    # Maze spawners — live orange, killed ones grey.  Always visible
    # (no fog check) so the player sees the objective even in
    # unrevealed areas; matches the always-visible rendering of the
    # maze rooms above.
    if maze_spawner_positions:
        live_pts: list[tuple[float, float]] = []
        dead_pts: list[tuple[float, float]] = []
        for (sx, sy, killed) in maze_spawner_positions:
            screen = (mx + sx * sx_w, my + sy * sy_h)
            (dead_pts if killed else live_pts).append(screen)
        if live_pts:
            arcade.draw_points(live_pts, (255, 80, 40), 6)
        if dead_pts:
            arcade.draw_points(dead_pts, (90, 90, 90), 5)

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

    # Boss markers — every live boss (Double Star + Nebula) pulses
    # yellow so it stands out from the red alien dots and so the
    # player can't miss which direction the big threat is in.  Uses
    # a 2 Hz ``math.sin`` pulse on the alpha channel of the outline;
    # fill stays fully opaque so the blip never vanishes mid-pulse.
    _boss_markers: list[tuple[float, float]] = []
    if boss_pos is not None:
        _boss_markers.append(boss_pos)
    if extra_boss_positions:
        _boss_markers.extend(extra_boss_positions)
    if _boss_markers:
        # Sine in [0..1] at 2 Hz -> halo alpha 80..255.
        _pulse = 0.5 + 0.5 * math.sin(time.monotonic() * math.pi * 2.0)
        _halo_alpha = int(80 + 175 * _pulse)
        for bpx, bpy in _boss_markers:
            _vis = True
            if _has_fog:
                gx = int(bpx * _inv_cell)
                gy = int(bpy * _inv_cell)
                _vis = 0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]
            if not _vis:
                continue
            bmx, bmy = to_map(bpx, bpy)
            arcade.draw_circle_filled(bmx, bmy, 4.0, (255, 220, 40))
            arcade.draw_circle_outline(
                bmx, bmy, 7.0, (255, 255, 120, _halo_alpha), 2)

    # Gas areas (green octagonal outlines scaled to world radius)
    if gas_positions:
        _oct_angles = [math.pi / 8 + i * math.pi / 4 for i in range(8)]
        _oct_cos = [math.cos(a) for a in _oct_angles]
        _oct_sin = [math.sin(a) for a in _oct_angles]
        # Sample offsets for the "cloud revealed?" check: the centre
        # plus 8 points at half-radius, N/E/S/W + the four diagonals.
        # Using only the centre missed huge warp-zone clouds whose
        # centre sat in an unrevealed fog cell while their edges were
        # already explored.
        _fog_sample_offsets = [(0.0, 0.0)] + [
            (0.5 * math.cos(a), 0.5 * math.sin(a))
            for a in (i * math.pi / 4 for i in range(8))
        ]
        gas_lines: list[tuple[float, float]] = []
        for entry in gas_positions:
            gpx, gpy = entry[0], entry[1]
            grad = entry[2] if len(entry) > 2 else 50.0
            if _has_fog and not gas_always_visible:
                any_revealed = False
                for (ox, oy) in _fog_sample_offsets:
                    sx = gpx + ox * grad
                    sy = gpy + oy * grad
                    gx = int(sx * _inv_cell)
                    gy = int(sy * _inv_cell)
                    if (0 <= gx < _fw and 0 <= gy < _fh
                            and _fg[gy][gx]):
                        any_revealed = True
                        break
                if not any_revealed:
                    continue
            gmx = mx + gpx * sx_w
            gmy = my + gpy * sy_h
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

    # Null fields (white-dot clusters, pulse red when disabled).
    # Each entry is (x, y, radius, active).  Hidden behind fog so
    # the player has to actually explore the area before the
    # stealth-route marker appears.
    if null_field_positions:
        nf_active: list[tuple[float, float]] = []
        nf_disabled: list[tuple[float, float]] = []
        for nx, ny, nrad, nactive in null_field_positions:
            if _has_fog:
                gx = int(nx * _inv_cell)
                gy = int(ny * _inv_cell)
                if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                    continue
            nmx = mx + nx * sx_w
            nmy = my + ny * sy_h
            (nf_active if nactive else nf_disabled).append((nmx, nmy))
        # Halo ring + core dot, batched per color group.  Previously
        # each null field made its own ``draw_circle_outline`` call
        # (30 individual GL calls per frame); replaced with two
        # ``draw_points`` calls per color (halo + core) for a
        # visually-equivalent marker at ~1/15 the GL cost.  Null
        # fields on the new 9600×9600 Nebula all clamp to the
        # 2.5-px floor radius anyway, so the uniform batch draw
        # reproduces the previous look exactly.
        if nf_active:
            arcade.draw_points(nf_active, (230, 230, 255, 160), 6)
            arcade.draw_points(nf_active, (230, 230, 255, 240), 3)
        if nf_disabled:
            arcade.draw_points(nf_disabled, (240, 60, 60, 180), 6)
            arcade.draw_points(nf_disabled, (240, 60, 60, 240), 3)

    # Slipspace teleporters (cyan diamond markers).  Hidden behind
    # fog — same convention as every other marker type.  Note: in
    # warp zones ``active_slipspaces`` returns [] so this is
    # naturally empty.
    if slipspace_positions:
        ss_pts: list[tuple[float, float]] = []
        for spx, spy in slipspace_positions:
            if _has_fog:
                gx = int(spx * _inv_cell)
                gy = int(spy * _inv_cell)
                if not (0 <= gx < _fw and 0 <= gy < _fh and _fg[gy][gx]):
                    continue
            ss_pts.append((mx + spx * sx_w, my + spy * sy_h))
        if ss_pts:
            # Bright cyan core + soft halo so they stand out from
            # parked-ship teal and null-field white.  The halo was
            # previously 15 individual ``draw_circle_outline`` calls
            # per frame; replaced with one larger batched ``draw_points``
            # behind the core for a visually-equivalent ring effect
            # at ~1/15 the GL-call cost.
            arcade.draw_points(ss_pts, (180, 240, 255, 160), 9)
            arcade.draw_points(ss_pts, (120, 220, 255, 240), 5)

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
