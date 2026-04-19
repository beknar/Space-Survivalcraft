"""Building placement, destruction, and station management extracted from GameView."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Optional

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT,
    BUILDING_TYPES, BUILDING_RADIUS,
    DOCK_SNAP_DIST,
)
from settings import audio
from sprites.building import (
    HomeStation, RepairModule, StationModule, DockingPort,
    create_building,
)

if TYPE_CHECKING:
    from game_view import GameView


def spawn_trade_station(gv: GameView) -> None:
    """Spawn the trading station at a random position clear of all entities."""
    if gv._trade_station is not None:
        return
    zone = gv._zone
    zw = getattr(zone, 'world_width', WORLD_WIDTH)
    zh = getattr(zone, 'world_height', WORLD_HEIGHT)
    margin = 500
    clearance = 120.0  # min distance from any entity

    for _ in range(400):
        tx = random.uniform(margin, zw - margin)
        ty = random.uniform(margin, zh - margin)
        if math.hypot(tx - zw / 2, ty - zh / 2) < 1500:
            continue
        if not _trade_pos_clear(gv, tx, ty, clearance):
            continue
        gv._trade_station = arcade.Sprite(
            path_or_texture=gv._trade_station_tex, scale=0.15)
        gv._trade_station.center_x = tx
        gv._trade_station.center_y = ty
        return


def _trade_pos_clear(gv: GameView, tx: float, ty: float,
                     clearance: float) -> bool:
    """Check that (tx, ty) is clear of asteroids, gas clouds, buildings, etc."""
    # Zone 1 asteroids and aliens
    for slist in (gv.asteroid_list, gv.alien_list, gv.building_list):
        for s in slist:
            if math.hypot(s.center_x - tx, s.center_y - ty) < clearance:
                return False
    # Zone 2 entities (if in Zone 2)
    zone = gv._zone
    for attr in ('_iron_asteroids', '_double_iron', '_copper_asteroids',
                 '_wanderers', '_aliens'):
        slist = getattr(zone, attr, None)
        if slist is not None:
            for s in slist:
                if math.hypot(s.center_x - tx, s.center_y - ty) < clearance:
                    return False
    # Gas areas (check radius, not just centre)
    gas_areas = getattr(zone, '_gas_areas', None)
    if gas_areas is not None:
        for g in gas_areas:
            if math.hypot(g.center_x - tx, g.center_y - ty) < g.radius + clearance:
                return False
    return True


def building_counts(gv: GameView) -> dict[str, int]:
    """Return a dict of building_type -> count for the current station."""
    counts: dict[str, int] = {}
    for b in gv.building_list:
        counts[b.building_type] = counts.get(b.building_type, 0) + 1
    return counts


def has_home_station(gv: GameView) -> bool:
    return any(isinstance(b, HomeStation) for b in gv.building_list)


def find_nearest_snap_port(
    gv: GameView, wx: float, wy: float, max_dist: float = 0.0,
) -> Optional[tuple[StationModule, DockingPort, float, float]]:
    """Find the nearest unoccupied docking port within max_dist."""
    if max_dist <= 0:
        max_dist = DOCK_SNAP_DIST
    best = None
    best_dist = max_dist + 1.0
    for b in gv.building_list:
        for port in b.get_unoccupied_ports():
            px, py = b.get_port_world_pos(port)
            d = math.hypot(wx - px, wy - py)
            if d < best_dist:
                best_dist = d
                best = (b, port, px, py)
    return best


# Ship upgrade/placement/switching lives in ship_manager.py; re-exported below
# so existing imports (`from building_manager import _place_new_ship`, etc.)
# and the GameView delegates keep working.
from ship_manager import (  # noqa: F401,E402
    _upgrade_ship, _place_new_ship, switch_to_ship,
    _place_basic_ship, count_l1_ships,
)


def _flash_fail(gv: GameView, msg: str, duration: float = 2.0) -> None:
    """Show a temporary failure message and bail out of placement."""
    gv._flash_msg = msg
    gv._flash_timer = duration


def _check_resources(gv: GameView, building_type: str) -> bool:
    """Validate iron + copper for ``building_type``.  Sets flash
    message + returns False if either is short.  Returns True when
    the player can afford the build."""
    from character_data import build_cost_multiplier
    bt_stats = BUILDING_TYPES[building_type]
    cost_mult = build_cost_multiplier(audio.character_name, gv._char_level)
    cost = int(bt_stats["cost"] * cost_mult)
    copper_cost = int(bt_stats.get("cost_copper", 0) * cost_mult)
    total_iron = gv.inventory.total_iron + gv._station_inv.total_iron
    if total_iron < cost:
        _flash_fail(gv, "Not enough iron!")
        return False
    if copper_cost > 0:
        total_copper = (gv.inventory.count_item("copper")
                        + gv._station_inv.count_item("copper"))
        if total_copper < copper_cost:
            _flash_fail(gv, "Not enough copper!")
            return False
    return True


def _enter_ship_placement(
    gv: GameView,
    *,
    building_type: str,
    ship_level: int,
    scale: float,
) -> None:
    """Shared body for Basic Ship and Advanced Ship placement.

    The calling branches handle their own specific gates (L1-count
    for Basic, SHIP_MAX_LEVEL for Advanced) BEFORE calling this —
    this helper just does the common work: verify resources, build
    the ghost sprite using the correct ship-level texture, enter
    placement mode."""
    from sprites.player import PlayerShip
    if not _check_resources(gv, building_type):
        return
    tex = PlayerShip._extract_ship_texture(
        gv._faction, gv._ship_type, ship_level)
    gv._ghost_sprite = arcade.Sprite(path_or_texture=tex, scale=scale)
    gv._ghost_sprite.alpha = 140
    gv._ghost_list = arcade.SpriteList()
    gv._ghost_list.append(gv._ghost_sprite)
    gv._ghost_rotation = 0.0
    gv._placing_building = building_type
    gv._build_menu.open = False


def enter_placement_mode(gv: GameView, building_type: str) -> None:
    """Start building placement -- create ghost sprite following cursor.

    Ship-building branches (Basic Ship, Advanced Ship) use the
    player-ship texture as the ghost; other buildings use the
    stock BUILDING_TYPES[...]["png"] texture.  Resource + gate
    checks happen up front so the player never enters placement
    mode for a build they can't afford or a ship they can't
    rebuild.
    """
    if building_type == "Basic Ship":
        # Only one L1 ship allowed at a time.
        if count_l1_ships(gv) > 0:
            _flash_fail(gv, "Already have a level-1 ship!")
            return
        _enter_ship_placement(
            gv, building_type=building_type, ship_level=1, scale=0.6)
        return
    if building_type == "Advanced Ship":
        from constants import SHIP_MAX_LEVEL
        if gv._ship_level >= SHIP_MAX_LEVEL:
            _flash_fail(gv, "Ship already at maximum level!")
            return
        _enter_ship_placement(
            gv, building_type=building_type,
            ship_level=gv._ship_level + 1, scale=0.75)
        return
    # Regular station modules — use the BUILDING_TYPES texture.
    gv._placing_building = building_type
    tex = gv._building_textures[building_type]
    gv._ghost_sprite = arcade.Sprite(path_or_texture=tex, scale=0.5)
    gv._ghost_sprite.alpha = 140
    gv._ghost_list = arcade.SpriteList()
    gv._ghost_list.append(gv._ghost_sprite)
    gv._ghost_rotation = 0.0
    gv._build_menu.open = False


def cancel_placement(gv: GameView) -> None:
    """Cancel building placement mode."""
    gv._placing_building = None
    gv._ghost_sprite = None
    gv._ghost_list = None


def enter_destroy_mode(gv: GameView) -> None:
    """Enter destroy mode -- clicks will destroy station modules."""
    gv._destroy_mode = True
    gv._build_menu.open = False


def exit_destroy_mode(gv: GameView) -> None:
    """Exit destroy mode."""
    gv._destroy_mode = False


def disconnect_ports(gv: GameView, building: StationModule) -> None:
    """Free docking ports on connected buildings when one is removed."""
    for port in building.ports:
        if port.occupied and port.connected_to is not None:
            other = port.connected_to
            for op in other.ports:
                if op.connected_to is building:
                    op.occupied = False
                    op.connected_to = None


def destroy_building_at(gv: GameView, wx: float, wy: float) -> None:
    """Destroy the closest building within click range of world pos."""
    best = None
    best_dist = 40.0
    for b in gv.building_list:
        d = math.hypot(wx - b.center_x, wy - b.center_y)
        if d < best_dist:
            best_dist = d
            best = b
    if best is not None:
        disconnect_ports(gv, best)
        cost = BUILDING_TYPES[best.building_type]["cost"]
        gv._spawn_iron_pickup(
            best.center_x, best.center_y, amount=cost,
        )
        if isinstance(best, HomeStation):
            for b in gv.building_list:
                b.disabled = True
                b.color = (128, 128, 128, 255)
        gv._spawn_explosion(best.center_x, best.center_y)
        arcade.play_sound(gv._explosion_snd, volume=0.7)
        best.remove_from_sprite_lists()


def place_building(gv: GameView, wx: float, wy: float) -> None:
    """Attempt to place the building at world position (wx, wy)."""
    bt = gv._placing_building
    if bt is None:
        return
    # Advanced Ship — place a new ship in the world
    if bt == "Advanced Ship":
        _place_new_ship(gv, wx, wy)
        cancel_placement(gv)
        return
    # Basic Ship — drop a fresh L1 parked ship at the placement spot
    if bt == "Basic Ship":
        _place_basic_ship(gv, wx, wy)
        cancel_placement(gv)
        return
    stats = BUILDING_TYPES[bt]
    from character_data import build_cost_multiplier, station_hp_multiplier
    cost = int(stats["cost"] * build_cost_multiplier(audio.character_name, gv._char_level))

    total_iron = gv.inventory.total_iron + gv._station_inv.total_iron
    if total_iron < cost:
        cancel_placement(gv)
        return
    copper_cost = int(stats.get("cost_copper", 0) * build_cost_multiplier(
        audio.character_name, gv._char_level))
    if copper_cost > 0:
        total_copper = gv.inventory.count_item("copper") + gv._station_inv.count_item("copper")
        if total_copper < copper_cost:
            cancel_placement(gv)
            return
    # Deduct iron + copper via the shared helper (ship inv first,
    # station inv for any shortfall).
    from inventory_ops import deduct_resources
    deduct_resources(gv, cost, copper_cost)

    tex = gv._building_textures[bt]
    laser_tex = gv._turret_laser_tex if "Turret" in bt else None
    building = create_building(bt, tex, wx, wy, laser_tex=laser_tex, scale=0.5)
    hp_mult = station_hp_multiplier(audio.character_name, gv._char_level)
    if hp_mult != 1.0:
        building.max_hp = int(building.max_hp * hp_mult)
        building.hp = building.max_hp
    building.angle = gv._ghost_rotation

    snap_parent = None
    snap_port = None
    snap_opp_port = None
    if stats["connectable"]:
        snap = find_nearest_snap_port(
            gv, wx, wy, max_dist=DOCK_SNAP_DIST + BUILDING_RADIUS * 2,
        )
        if snap is None and bt != "Home Station":
            gv.inventory.add_item("iron", cost)
            cancel_placement(gv)
            return
        if snap is not None:
            snap_parent, snap_port, sx, sy = snap

            # Compute the PHYSICAL direction of the snap port by
            # rotating its label through the parent's angle.
            _DIR_ORDER = ["N", "E", "S", "W"]
            parent_steps = round(snap_parent.angle / 90.0) % 4
            label_idx = _DIR_ORDER.index(snap_port.direction)
            phys_dir = _DIR_ORDER[(label_idx - parent_steps) % 4]
            phys_opp = DockingPort.opposite(phys_dir)

            # Auto-rotate non-square modules so their long axis aligns
            # with the physical snap direction.
            tex = gv._building_textures[bt]
            tw = tex.width * 0.5
            th = tex.height * 0.5
            is_wide = tw > th and abs(tw - th) > 4.0
            is_tall = th > tw and abs(tw - th) > 4.0

            # Wide modules (Solar Arrays) centre on N/S ports instead
            # of edge-to-edge, so skip rotation for them.
            centre_on_port = False
            if is_wide and phys_dir in ("N", "S"):
                centre_on_port = True
            elif is_wide and phys_dir in ("E", "W"):
                building.angle = 90.0
            elif is_tall and phys_dir in ("E", "W"):
                building.angle = 90.0

            if centre_on_port:
                # Place building centre directly on the snap point
                building.center_x = sx
                building.center_y = sy
                snap_opp_port = None
            else:
                # Find the port on the new building that physically
                # faces the opposite of the snap port's physical dir.
                bld_steps = round(building.angle / 90.0) % 4
                opp_idx = _DIR_ORDER.index(phys_opp)
                needed_label = _DIR_ORDER[(opp_idx + bld_steps) % 4]
                for np in building.ports:
                    if np.direction == needed_label:
                        snap_opp_port = np
                        break

                rad = math.radians(building.angle)
                cos_a = math.cos(rad)
                sin_a = math.sin(rad)

                if snap_opp_port is not None:
                    ox_rot = snap_opp_port.offset_x * cos_a - snap_opp_port.offset_y * sin_a
                    oy_rot = snap_opp_port.offset_x * sin_a + snap_opp_port.offset_y * cos_a
                    building.center_x = sx - ox_rot
                    building.center_y = sy - oy_rot
                else:
                    building.center_x = sx
                    building.center_y = sy

    for existing in gv.building_list:
        if existing is snap_parent:
            continue
        if math.hypot(building.center_x - existing.center_x,
                      building.center_y - existing.center_y) < BUILDING_RADIUS * 2:
            gv.inventory.add_item("iron", cost)
            cancel_placement(gv)
            return

    if snap_port is not None:
        snap_port.occupied = True
        snap_port.connected_to = building
        if snap_opp_port is not None:
            snap_opp_port.occupied = True
            snap_opp_port.connected_to = snap_parent

    gv.building_list.append(building)

    if isinstance(building, RepairModule) and gv._trade_station is None:
        spawn_trade_station(gv)

    # Quantum Wave Integrator — auto-spawns the Double Star boss on
    # first build.  Replaces the old ``check_boss_spawn`` conditions
    # (char level + all module slots + 5 repair packs) with a single
    # "player committed to building the QWI" trigger.
    from sprites.building import QuantumWaveIntegrator
    if isinstance(building, QuantumWaveIntegrator):
        from combat_helpers import spawn_boss
        home = next((b for b in gv.building_list
                     if isinstance(b, HomeStation) and not b.disabled), None)
        if (home is not None and not gv._boss_spawned
                and not gv._boss_defeated):
            spawn_boss(gv, home.center_x, home.center_y)

    _DIR_ORDER_AC = ["N", "E", "S", "W"]
    bld_steps_ac = round(building.angle / 90.0) % 4
    for new_port in building.get_unoccupied_ports():
        npx, npy = building.get_port_world_pos(new_port)
        # Physical direction of this port on the new building
        np_idx = _DIR_ORDER_AC.index(new_port.direction)
        np_phys = _DIR_ORDER_AC[(np_idx - bld_steps_ac) % 4]
        np_phys_opp = DockingPort.opposite(np_phys)
        for other in gv.building_list:
            if other is building:
                continue
            other_steps = round(other.angle / 90.0) % 4
            for other_port in other.get_unoccupied_ports():
                opx, opy = other.get_port_world_pos(other_port)
                if math.hypot(npx - opx, npy - opy) >= DOCK_SNAP_DIST:
                    continue
                # Only connect if ports face opposite physical directions
                op_idx = _DIR_ORDER_AC.index(other_port.direction)
                op_phys = _DIR_ORDER_AC[(op_idx - other_steps) % 4]
                if op_phys == np_phys_opp:
                    new_port.occupied = True
                    new_port.connected_to = other
                    other_port.occupied = True
                    other_port.connected_to = building
                    break
            if new_port.occupied:
                break

    cancel_placement(gv)


