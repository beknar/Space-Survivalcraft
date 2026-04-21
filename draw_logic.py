"""Drawing routines extracted from GameView.on_draw."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

from constants import (
    STATUS_WIDTH, BG_TILE,
    SHIELD_SCALE,
    MINIMAP_Y, MINIMAP_H,
    SHIP_MAX_LEVEL,
)
from settings import audio

if TYPE_CHECKING:
    from game_view import GameView


def _draw_nebula_boss(gv: GameView) -> None:
    """Draw the Nebula boss sprite, its gas clouds, and (if active)
    its gas cone overlay.  Gas visuals are primitives — the gas
    cloud sprite carries no texture."""
    import math as _math
    nb = getattr(gv, "_nebula_boss", None)
    if nb is None or nb.hp <= 0:
        return
    if not hasattr(gv, "_nebula_boss_list"):
        return
    gv._nebula_boss_list.draw()
    # Gas clouds — pulsing green circles.
    clouds = getattr(gv, "_nebula_gas_clouds", None) or []
    for c in clouds:
        pulse = 0.6 + 0.4 * _math.sin(c._phase)
        alpha = int(140 * pulse + 40)
        arcade.draw_circle_filled(
            c.center_x, c.center_y, c.radius,
            (120, 220, 110, alpha))
        arcade.draw_circle_outline(
            c.center_x, c.center_y, c.radius,
            (80, 200, 80, 200), 2)
    # Gas cone — draw a translucent triangle toward the player.
    if getattr(nb, "_cone_active", False):
        from constants import NEBULA_BOSS_CONE_RANGE, NEBULA_BOSS_CONE_WIDTH
        dx, dy = nb._cone_dir_x, nb._cone_dir_y
        # Perpendicular.
        px_, py_ = -dy, dx
        tip_x = nb.center_x + dx * NEBULA_BOSS_CONE_RANGE
        tip_y = nb.center_y + dy * NEBULA_BOSS_CONE_RANGE
        half_w = NEBULA_BOSS_CONE_WIDTH / 2.0
        x1 = tip_x + px_ * half_w
        y1 = tip_y + py_ * half_w
        x2 = tip_x - px_ * half_w
        y2 = tip_y - py_ * half_w
        # Simple filled triangle.
        try:
            arcade.draw_triangle_filled(
                nb.center_x, nb.center_y, x1, y1, x2, y2,
                (80, 200, 80, 120))
        except Exception:
            pass


def _draw_slipspaces(gv: GameView) -> None:
    """Draw every slipspace teleporter in the active zone.  The PNG
    has its own background so we don't paint anything behind it; the
    game's space starfield naturally shows through any transparent
    pixels.  Routed through ``SpriteList.draw()`` so the renderer
    batches the textured quads in one GPU call."""
    from update_logic import active_slipspaces
    ss_list = active_slipspaces(gv)
    if not ss_list:
        return
    if hasattr(ss_list, "draw"):
        ss_list.draw()
    else:
        for ss in ss_list:
            arcade.draw_sprite(ss)


def _draw_null_fields(gv: GameView) -> None:
    """Draw every null field in the active zone as two batched
    ``draw_points`` calls — one for the active (white) fields and one
    for the disabled (red) fields. 30 fields × 28 dots each is ~840
    points per frame; batching collapses this into 2 GPU draws."""
    from update_logic import active_null_fields
    import math
    active_pts: list[tuple[float, float]] = []
    disabled_pts: list[tuple[float, float]] = []
    disabled_pulse = 0.0
    for nf in active_null_fields(gv):
        if nf.active:
            active_pts.extend(nf._world_dots)
        else:
            disabled_pts.extend(nf._world_dots)
            # Pulse sync'd to any one field's flash phase is fine —
            # every field runs the same 6 rad/s oscillator.
            disabled_pulse = nf._flash_phase
    if active_pts:
        arcade.draw_points(active_pts, (230, 230, 255, 210), 4.0)
    if disabled_pts:
        pulse = 0.6 + 0.4 * math.sin(disabled_pulse)
        red = min(255, int(240 * pulse + 15))
        alpha = min(255, int(180 * pulse + 30))
        arcade.draw_points(disabled_pts, (red, 40, 40, alpha), 4.0)


def _draw_trade_station(gv: GameView) -> None:
    """Draw the trade station sprite if it exists."""
    if gv._trade_station is not None:
        ts = gv._trade_station
        tw = gv._trade_station_tex.width * 0.15
        th = gv._trade_station_tex.height * 0.15
        arcade.draw_texture_rect(
            gv._trade_station_tex,
            arcade.LBWH(ts.center_x - tw / 2, ts.center_y - th / 2, tw, th))


def _draw_parked_ship_shields(gv: GameView) -> None:
    """Draw the yellow shield bubble around every AI-piloted parked ship."""
    for ps in gv._parked_ships:
        if ps.has_ai_pilot and ps._shield_list is not None and ps.shields > 0:
            ps._shield_list.draw()


def _draw_station_shield(gv: GameView) -> None:
    """Draw the station shield as a near-invisible fill (for the
    hit-flash) plus a solid-looking circle outline border.

    The sprite renders at alpha ~15 so the interior is barely
    perceptible; the real visual is the outline ring drawn on top at
    full tint colour with moderate alpha so the border looks solid
    while the interior stays clean."""
    if (getattr(gv, "_station_shield_list", None) is not None
            and getattr(gv, "_station_shield_hp", 0) > 0):
        gv._station_shield_list.draw()
        # Solid-looking border ring.
        s = gv._station_shield_sprite
        r = gv._station_shield_radius
        if s is not None and r > 0:
            tr, tg, tb = s._tint
            # Base border is solid; flash makes it brighter.
            border_alpha = 200 if s._hit_timer <= 0 else 255
            arcade.draw_circle_outline(
                s.center_x, s.center_y, r,
                (tr, tg, tb, border_alpha), border_width=3)
            # A faint second ring just inside for a subtle glow edge.
            arcade.draw_circle_outline(
                s.center_x, s.center_y, r - 4,
                (tr, tg, tb, border_alpha // 3), border_width=2)


def draw_background(
    gv: GameView, cx: float, cy: float, hw: float, hh: float
) -> None:
    """Tile the starfield texture to fill the visible area."""
    ts = BG_TILE
    x0 = int((cx - hw) / ts) * ts
    y0 = int((cy - hh) / ts) * ts
    tx = x0
    while tx < cx + hw + ts:
        ty = y0
        while ty < cy + hh + ts:
            arcade.draw_texture_rect(
                gv.bg_texture,
                arcade.LBWH(tx, ty, ts, ts),
            )
            ty += ts
        tx += ts


def draw_world(gv: GameView, cx: float, cy: float, hw: float, hh: float) -> None:
    """Draw all world-space entities (called inside world_cam.activate)."""
    draw_background(gv, cx, cy, hw, hh)

    # Zone-specific world entities
    from zones import ZoneID
    if gv._zone.zone_id == ZoneID.MAIN:
        gv.asteroid_list.draw()
        gv.iron_pickup_list.draw()
        gv.blueprint_pickup_list.draw()
        gv.explosion_list.draw()
        gv.building_list.draw()
        gv._parked_ships.draw()
        _draw_parked_ship_shields(gv)
        if gv._wormholes:
            gv._wormhole_list.draw()
        gv.turret_projectile_list.draw()
        gv.alien_list.draw()
        gv.alien_projectile_list.draw()
        if gv._boss is not None and gv._boss.hp > 0:
            gv._boss_list.draw()
            gv._boss_projectile_list.draw()
    else:
        gv.explosion_list.draw()
        gv._zone.draw_world(gv, cx, cy, hw, hh)
        gv._parked_ships.draw()
        _draw_parked_ship_shields(gv)
        # Nebula boss lives in Zone 2 — draw it here so its gas
        # clouds + cone overlay the zone's own entities.
        _draw_nebula_boss(gv)

    # Trade station (shared across all zones — drawn after zone entities)
    _draw_trade_station(gv)

    # Slipspace teleporters — drawn before null fields so a slipspace
    # that overlaps a stealth patch doesn't block the cluster dots.
    _draw_slipspaces(gv)

    # Null fields — semi-transparent dot clusters drawn above world
    # entities but below the player ship + projectiles so they don't
    # occlude combat readouts.
    _draw_null_fields(gv)

    # Station shield — drawn before the player/particles so it sits
    # behind the ship and projectiles but on top of buildings.
    _draw_station_shield(gv)

    # Double Star Refugee NPC — Zone 2 only, once unlocked
    if gv._refugee_npc is not None and gv._zone.zone_id == ZoneID.ZONE2:
        arcade.draw_sprite(gv._refugee_npc)
        if gv._hover_refugee:
            from constants import NPC_REFUGEE_LABEL
            t = gv._t_refugee_tip
            if t.text != NPC_REFUGEE_LABEL:
                t.text = NPC_REFUGEE_LABEL
            t.x = gv._refugee_npc.center_x
            t.y = gv._refugee_npc.center_y + 40
            t.draw()

    # Shared world entities (always drawn)
    gv.projectile_list.draw()
    gv._missile_list.draw()
    # Force walls
    for wall in gv._force_walls:
        wall.draw()
    # Contrail drawn behind the player ship
    for cp in gv._contrail:
        cp.draw()
    # Null-field cloak: ghost the ship to alpha ~30 + neutral tint so
    # it visually reads as invisible. The cloak state matches what the
    # alien AI sees via `player_is_cloaked`; firing or using an ability
    # flips the null field into its `NULL_FIELD_DISABLE_S` disable, dropping the
    # cloak and restores the ship's appearance on the next frame.
    from update_logic import player_is_cloaked
    _cloaked_now = player_is_cloaked(gv)
    if _cloaked_now:
        _saved_color = gv.player.color
        gv.player.color = (255, 255, 255, 30)
    gv.player_list.draw()
    if _cloaked_now:
        gv.player.color = _saved_color
    gv.shield_list.draw()
    # Shield enhancer ring
    if ("shield_enhancer" in gv._module_slots
            and gv.player.shields > 0 and not gv._player_dead):
        import math as _m
        ex, ey = gv.player.center_x, gv.player.center_y
        ring_r = gv.shield_sprite.width * SHIELD_SCALE / 2 + 20
        t = (_m.sin(gv._enhancer_angle * _m.pi / 90) + 1) / 2
        cr = int(200 + 55 * t)
        cg = int(180 + 50 * t)
        cb = int(40 + 80 * (1 - t))
        segments = 8
        arc_len = 360 / segments * 0.7
        for i in range(segments):
            start = gv._enhancer_angle + i * (360 / segments)
            a1 = _m.radians(start)
            a2 = _m.radians(start + arc_len)
            steps = 6
            for s in range(steps):
                f1 = a1 + (a2 - a1) * s / steps
                f2 = a1 + (a2 - a1) * (s + 1) / steps
                x1 = ex + _m.cos(f1) * ring_r
                y1 = ey + _m.sin(f1) * ring_r
                x2 = ex + _m.cos(f2) * ring_r
                y2 = ey + _m.sin(f2) * ring_r
                arcade.draw_line(x1, y1, x2, y2, (cr, cg, cb, 180), 2)
    # Consumable use glow effect (brief coloured circle around ship)
    if gv._use_glow_timer > 0.0 and not gv._player_dead:
        frac = gv._use_glow_timer / 0.4
        r, g, b, a = gv._use_glow
        alpha = int(a * frac)
        radius = 60 + 20 * (1.0 - frac)
        arcade.draw_circle_filled(
            gv.player.center_x, gv.player.center_y,
            radius, (r, g, b, alpha))
    # Parked ship HP bars (world space)
    for ps in gv._parked_ships:
        if ps.hp < ps.max_hp:
            bw, bh = 40, 4
            bx = ps.center_x - bw / 2
            by = ps.center_y + 30
            arcade.draw_rect_filled(arcade.LBWH(bx, by, bw, bh), (40, 40, 40, 200))
            fill = max(1, int(bw * ps.hp / ps.max_hp))
            arcade.draw_rect_filled(arcade.LBWH(bx, by, fill, bh), (0, 200, 0, 220))
    # Hover tooltip for parked ships (cached Text to avoid draw_text warning)
    if gv._hover_parked_ship is not None:
        ps = gv._hover_parked_ship
        label = f"Level {ps.ship_level} Ship (HP {ps.hp}/{ps.max_hp}) — Click to board"
        t = gv._t_parked_ship_tip
        if t.text != label:
            t.text = label
        t.x = ps.center_x
        t.y = ps.center_y + 45
        t.draw()
    for spark in gv.hit_sparks:
        spark.draw()
    for fs in gv.fire_sparks:
        fs.draw()
    # Ghost sprite for placement mode
    if gv._ghost_list is not None:
        gv._ghost_list.draw()
    # Destroy mode crosshair
    if gv._destroy_mode:
        dcx, dcy = gv._destroy_cursor_x, gv._destroy_cursor_y
        sz = 16
        arcade.draw_line(dcx - sz, dcy, dcx + sz, dcy, (255, 60, 60, 200), 2)
        arcade.draw_line(dcx, dcy - sz, dcx, dcy + sz, (255, 60, 60, 200), 2)
        arcade.draw_circle_outline(dcx, dcy, 12, (255, 60, 60, 180), 2)


def _minimap_obstacles(gv: GameView) -> arcade.SpriteList:
    """Return obstacle sprite list for minimap (zone-aware)."""
    from zones import ZoneID
    from zones.zone_warp_base import WarpZoneBase
    if gv._zone.zone_id == ZoneID.MAIN:
        return gv.asteroid_list
    if isinstance(gv._zone, WarpZoneBase):
        obstacles, _ = gv._zone.get_minimap_objects()
        return obstacles
    if hasattr(gv._zone, '_minimap_cache'):
        # Zone 2: use cached combined list (rebuilt only when stale)
        cache = gv._zone._minimap_cache
        if cache is not None:
            return cache
        combined = arcade.SpriteList()
        for a in gv._zone._iron_asteroids:
            combined.append(a)
        for a in gv._zone._copper_asteroids:
            combined.append(a)
        gv._zone._minimap_cache = combined
        return combined
    return gv.asteroid_list


def _minimap_enemies(gv: GameView) -> arcade.SpriteList:
    """Return enemy sprite list for minimap (zone-aware)."""
    from zones import ZoneID
    from zones.zone_warp_base import WarpZoneBase
    if gv._zone.zone_id == ZoneID.MAIN:
        return gv.alien_list
    if isinstance(gv._zone, WarpZoneBase):
        _, enemies = gv._zone.get_minimap_objects()
        return enemies
    if hasattr(gv._zone, '_aliens'):
        return gv._zone._aliens
    return gv.alien_list


def compute_world_stats(gv: GameView) -> list[tuple[str, int, tuple]]:
    """Return a list of (label, count, color) entries for the station info panel.
    Zone-aware: shows different stats depending on the active zone."""
    from zones import ZoneID
    from update_logic import active_null_fields
    stats: list[tuple[str, int, tuple]] = []
    grey = (180, 180, 180, 255)
    orange = (220, 160, 60, 255)
    red = (220, 80, 80, 255)
    green = (120, 200, 90, 255)
    purple = (180, 140, 220, 255)
    if gv._zone.zone_id == ZoneID.ZONE2 and hasattr(gv._zone, '_iron_asteroids'):
        z = gv._zone
        stats.append(("IRON ROCK", len(z._iron_asteroids), grey))
        stats.append(("BIG IRON",  len(z._double_iron),    orange))
        stats.append(("COPPER",    len(z._copper_asteroids), (200, 130, 60, 255)))
        stats.append(("WANDERERS", len(z._wanderers),       (200, 200, 130, 255)))
        stats.append(("GAS AREAS", len(z._gas_areas),       green))
        stats.append(("ALIENS",    len(z._aliens),          red))
        stats.append(("NULL FIELDS", len(active_null_fields(gv)), purple))
    elif gv._zone.zone_id == ZoneID.MAIN:
        stats.append(("ASTEROIDS", len(gv.asteroid_list), grey))
        stats.append(("ALIENS",    len(gv.alien_list),    red))
        stats.append(("NULL FIELDS", len(active_null_fields(gv)), purple))
        if gv._boss is not None and gv._boss.hp > 0:
            stats.append(("BOSS HP", int(gv._boss.hp), red))
    else:
        # Warp zones — no null fields by design, no boss.
        stats.append(("ASTEROIDS", len(gv.asteroid_list), grey))
        stats.append(("ALIENS",    len(gv.alien_list),    red))
    return stats


def compute_inactive_zone_stats(gv: GameView) -> list[tuple[str, list[tuple[str, int, tuple]]]]:
    """Return stats for zones the player is NOT in (Zone 1 and Zone 2 only).

    Returns a list of (zone_name, stat_lines) tuples.
    """
    from zones import ZoneID
    grey = (180, 180, 180, 255)
    orange = (220, 160, 60, 255)
    red = (220, 80, 80, 255)
    green = (120, 200, 90, 255)
    purple = (180, 140, 220, 255)
    result: list[tuple[str, list[tuple[str, int, tuple]]]] = []

    # Zone 1 (Double Star) stats from stash
    if gv._zone.zone_id != ZoneID.MAIN and gv._main_zone._stash:
        stash = gv._main_zone._stash
        lines: list[tuple[str, int, tuple]] = []
        ast = stash.get("asteroid_list")
        ali = stash.get("alien_list")
        bld = stash.get("building_list")
        if ast is not None:
            lines.append(("ASTEROIDS", len(ast), grey))
        if ali is not None:
            lines.append(("ALIENS", len(ali), red))
        if bld is not None and len(bld) > 0:
            lines.append(("BUILDINGS", len(bld), orange))
        # Zone 1 null fields live on gv._null_fields regardless of
        # active zone — they aren't stashed — so report them directly.
        z1_nulls = getattr(gv, "_null_fields", None) or []
        if z1_nulls:
            lines.append(("NULL FIELDS", len(z1_nulls), purple))
        boss = stash.get("_boss")
        if boss is not None and getattr(boss, 'hp', 0) > 0:
            lines.append(("BOSS HP", int(boss.hp), red))
        result.append(("DOUBLE STAR", lines))

    # Zone 2 (Nebula) stats from live zone instance
    if gv._zone.zone_id != ZoneID.ZONE2 and gv._zone2 is not None:
        z2 = gv._zone2
        if z2._populated:
            lines = []
            lines.append(("IRON ROCK", len(z2._iron_asteroids), grey))
            lines.append(("BIG IRON", len(z2._double_iron), orange))
            lines.append(("COPPER", len(z2._copper_asteroids), (200, 130, 60, 255)))
            lines.append(("WANDERERS", len(z2._wanderers), (200, 200, 130, 255)))
            lines.append(("GAS AREAS", len(z2._gas_areas), green))
            lines.append(("ALIENS", len(z2._aliens), red))
            z2_nulls = getattr(z2, "_null_fields", None) or []
            if z2_nulls:
                lines.append(("NULL FIELDS", len(z2_nulls), purple))
            if z2._building_stash is not None:
                bld = z2._building_stash.get("building_list")
                if bld is not None and len(bld) > 0:
                    lines.append(("BUILDINGS", len(bld), orange))
            result.append(("NEBULA", lines))

    return result


def _gas_always_visible(gv: GameView) -> bool:
    """Gas hazards respect fog of war in all zones, including warp zones."""
    return False


def _null_field_positions(
    gv: GameView,
) -> list[tuple[float, float, float, bool]]:
    """Return (x, y, radius, active) for every null field in the
    active zone — used by the minimap.  Always-visible (no fog check)
    so the player can plan stealth routes ahead of exploration."""
    from update_logic import active_null_fields
    return [(nf.center_x, nf.center_y, nf.radius, nf.active)
            for nf in active_null_fields(gv)]


def _slipspace_positions(gv: GameView) -> list[tuple[float, float]]:
    """Return (x, y) for every slipspace in the active zone — used
    by the minimap.  ``active_slipspaces`` already enforces the
    "non-warp zones only" rule so warp zones get an empty list."""
    from update_logic import active_slipspaces
    ss_list = active_slipspaces(gv)
    return [(ss.center_x, ss.center_y) for ss in ss_list]


def _gas_positions(gv: GameView) -> list[tuple[float, float, float]]:
    """Return gas area (x, y, radius) for minimap (Zone 2 and gas warp zone)."""
    # Zone 2: use cached positions
    if hasattr(gv._zone, '_gas_pos_cache'):
        if gv._zone._gas_pos_cache is not None:
            return gv._zone._gas_pos_cache
        if hasattr(gv._zone, '_gas_areas'):
            gv._zone._gas_pos_cache = [
                (g.center_x, g.center_y, g.radius) for g in gv._zone._gas_areas]
            return gv._zone._gas_pos_cache
    # Gas warp zone: return cloud positions
    if hasattr(gv._zone, '_clouds'):
        return [(c.center_x, c.center_y, c.radius) for c in gv._zone._clouds]
    return []


def draw_ui(gv: GameView) -> None:
    """Draw all UI-space elements (called inside ui_cam.activate)."""
    from sprites.building import compute_modules_used, compute_module_capacity

    # Treat every modal overlay as "menu open" so the expensive video
    # blit + pixel-readback is skipped while the user is in a panel.
    # fps_drops.log showed ~1250 drops with CRAFT open (worst 81 ms)
    # — the HUD videos were still decoding behind the panel the user
    # can't even see through.
    menu_open = (
        gv._escape_menu.open
        or gv._craft_menu.open
        or gv._trade_menu.open
        or gv._build_menu.open
        or gv._station_inv.open
        or gv._qwi_menu.open
        or gv._station_info.open
        or gv._ship_stats.open
        or gv._dialogue.open
        or gv._map_overlay.open
    )
    gv._hud.draw(
        weapon_name=gv._active_weapon.name,
        hp=gv.player.hp,
        max_hp=gv.player.max_hp,
        shields=gv.player.shields,
        max_shields=gv.player.max_shields,
        asteroid_list=_minimap_obstacles(gv),
        iron_pickup_list=gv.iron_pickup_list,
        alien_list=_minimap_enemies(gv),
        player_x=gv.player.center_x,
        player_y=gv.player.center_y,
        player_heading=gv.player.heading,
        track_name=(gv._video_player.track_name
                    if gv._video_player.active
                    else gv._current_track_name),
        building_list=gv.building_list,
        fog_grid=gv._fog_grid,
        fog_revealed=gv._fog_revealed,
        video_active=gv._video_player.active,
        character_name=audio.character_name,
        trade_station_pos=(gv._trade_station.center_x, gv._trade_station.center_y)
            if gv._trade_station is not None else None,
        boss_pos=(gv._boss.center_x, gv._boss.center_y)
            if gv._boss is not None and gv._boss.hp > 0 else None,
        extra_boss_positions=(
            [(gv._nebula_boss.center_x, gv._nebula_boss.center_y)]
            if getattr(gv, "_nebula_boss", None) is not None
               and gv._nebula_boss.hp > 0 else None
        ),
        wormhole_positions=[(wh.center_x, wh.center_y) for wh in gv._wormholes],
        zone_width=gv._zone.world_width,
        zone_height=gv._zone.world_height,
        ability_meter=gv._ability_meter,
        ability_meter_max=gv._ability_meter_max,
        gas_positions=_gas_positions(gv),
        gas_always_visible=_gas_always_visible(gv),
        parked_ship_positions=[(ps.center_x, ps.center_y) for ps in gv._parked_ships],
        null_field_positions=_null_field_positions(gv),
        slipspace_positions=_slipspace_positions(gv),
    )
    # Video frame draws (skip when menu open)
    if not menu_open:
        if gv._char_video_player.active:
            cvx, cvy, cvw = gv._hud.char_video_rect
            gv._char_video_player.draw_in_hud(cvx, cvy, cvw, aspect=1.0)
        if gv._video_player.active:
            vid_size = STATUS_WIDTH - 20
            vid_x = 10
            vid_y = MINIMAP_Y + MINIMAP_H + 6
            gv._video_player.draw_in_hud(vid_x, vid_y, vid_size)

    # Overlays
    gv._station_inv.draw()
    gv.inventory.draw()
    gv._station_inv.draw_drag_preview()
    from ship_manager import count_l1_ships
    gv._build_menu.draw(
        iron=gv.inventory.total_iron + gv._station_inv.total_iron,
        building_counts=gv._building_counts(),
        modules_used=compute_modules_used(gv.building_list),
        module_capacity=compute_module_capacity(gv.building_list),
        has_home=gv._has_home_station(),
        copper=gv.inventory.count_item("copper") + gv._station_inv.count_item("copper"),
        unlocked_blueprints=gv._craft_menu._unlocked,
        ship_level=gv._ship_level,
        max_ship_exists=any(
            p.ship_level >= SHIP_MAX_LEVEL for p in gv._parked_ships
        ) or gv._ship_level >= SHIP_MAX_LEVEL,
        l1_ship_exists=count_l1_ships(gv) > 0,
    )
    gv._station_info.draw()
    gv._ship_stats.draw()
    gv._craft_menu.draw(gv._station_inv.total_iron)
    gv._trade_menu.draw()
    gv._qwi_menu.draw()
    gv._dialogue.draw()
    # Full-screen map last so it sits on top of every other overlay.
    gv._map_overlay.draw(gv)

    # Building hover tooltip
    if (gv._hover_building is not None
            and not menu_open
            and not gv._death_screen.active
            and not gv._build_menu.open
            and gv._placing_building is None
            and not gv._destroy_mode):
        b = gv._hover_building
        label = f"{b.building_type}  HP {b.hp}/{b.max_hp}"
        gv._t_building_tip.text = label
        tx = gv._hover_screen_x
        ty = gv._hover_screen_y + 20
        tw = len(label) * 7 + 16
        th = 18
        tx0 = max(2, min(gv.window.width - tw - 2, tx - tw // 2))
        if ty + th > gv.window.height:
            ty = gv._hover_screen_y - 22
        arcade.draw_rect_filled(
            arcade.LBWH(tx0, ty, tw, th), (10, 10, 30, 220),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(tx0, ty, tw, th),
            arcade.color.STEEL_BLUE, border_width=1,
        )
        gv._t_building_tip.x = tx0 + tw // 2
        gv._t_building_tip.y = ty + 2
        gv._t_building_tip.draw()

    # Boss HP bar
    if gv._boss is not None and gv._boss.hp > 0:
        bar_w = 400
        bar_h = 16
        bar_x = STATUS_WIDTH + (gv.window.width - STATUS_WIDTH - bar_w) // 2
        bar_y = gv.window.height - 40
        arcade.draw_rect_filled(
            arcade.LBWH(bar_x, bar_y, bar_w, bar_h), (30, 10, 10, 220))
        if gv._boss.shields > 0:
            sw = int(bar_w * gv._boss.shields / gv._boss.max_shields)
            arcade.draw_rect_filled(
                arcade.LBWH(bar_x, bar_y + bar_h // 2, sw, bar_h // 2),
                (80, 200, 255, 200))
        hw = int(bar_w * gv._boss.hp / gv._boss.max_hp)
        arcade.draw_rect_filled(
            arcade.LBWH(bar_x, bar_y, hw, bar_h // 2),
            (220, 50, 50, 220))
        arcade.draw_rect_outline(
            arcade.LBWH(bar_x, bar_y, bar_w, bar_h),
            (200, 60, 60), border_width=1)
        phase_str = f"Phase {gv._boss.phase}"
        if not hasattr(gv, '_t_boss_label'):
            gv._t_boss_label = arcade.Text(
                "", 0, 0, arcade.color.WHITE, 10, bold=True,
                anchor_x="center", anchor_y="center")
        gv._t_boss_label.text = (
            f"BOSS  HP {gv._boss.hp}/{gv._boss.max_hp}  "
            f"Shield {int(gv._boss.shields)}/{gv._boss.max_shields}  "
            f"[{phase_str}]"
        )
        gv._t_boss_label.x = bar_x + bar_w // 2
        gv._t_boss_label.y = bar_y + bar_h + 10
        gv._t_boss_label.draw()

    # Flash message
    if gv._flash_msg:
        play_cx = STATUS_WIDTH + (gv.window.width - STATUS_WIDTH) // 2
        play_cy = gv.window.height // 2
        gv._t_flash.text = gv._flash_msg
        gv._t_flash.x = play_cx
        gv._t_flash.y = play_cy
        tw = len(gv._flash_msg) * 8 + 20
        arcade.draw_rect_filled(
            arcade.LBWH(play_cx - tw // 2, play_cy - 12, tw, 24),
            (30, 10, 10, 200))
        arcade.draw_rect_outline(
            arcade.LBWH(play_cx - tw // 2, play_cy - 12, tw, 24),
            (200, 60, 60), border_width=1)
        gv._t_flash.draw()

    # Boss spawn announcement
    if gv._boss_announce_timer > 0.0:
        play_cx = STATUS_WIDTH + (gv.window.width - STATUS_WIDTH) // 2
        play_cy = gv.window.height // 2 + 40
        pulse = abs(math.sin(gv._boss_announce_timer * 3.0))
        alpha = int(180 + 75 * pulse)
        band_h = 120
        arcade.draw_rect_filled(
            arcade.LBWH(STATUS_WIDTH, play_cy - band_h // 2,
                        gv.window.width - STATUS_WIDTH, band_h),
            (10, 0, 0, 180))
        gv._t_boss_announce.color = (255, 60, 60, alpha)
        gv._t_boss_announce.x = play_cx
        gv._t_boss_announce.y = play_cy + 10
        gv._t_boss_announce.draw()
        gv._t_boss_subtitle.color = (255, 180, 180, alpha)
        gv._t_boss_subtitle.x = play_cx
        gv._t_boss_subtitle.y = play_cy - 30
        gv._t_boss_subtitle.draw()

    gv._escape_menu.draw()
    gv._death_screen.draw()
