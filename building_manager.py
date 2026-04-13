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


def _upgrade_ship(gv: GameView) -> None:
    """Upgrade the player ship to the next level.

    Deducts iron + copper cost, upgrades the player sprite/stats,
    expands module slots, increases ability meter max, and shows a
    flash message. All existing modules and cargo are preserved.
    """
    from constants import (
        SHIP_MAX_LEVEL, SHIP_LEVEL_MODULE_BONUS, SHIP_LEVEL_ABILITY_BONUS,
        MODULE_SLOT_COUNT,
    )
    from character_data import build_cost_multiplier
    bt = "Advanced Ship"
    stats = BUILDING_TYPES[bt]
    if gv._ship_level >= SHIP_MAX_LEVEL:
        gv._flash_msg = "Ship already at maximum level!"
        gv._flash_timer = 2.0
        return
    # Resource check
    cost_mult = build_cost_multiplier(audio.character_name, gv._char_level)
    cost = int(stats["cost"] * cost_mult)
    copper_cost = int(stats.get("cost_copper", 0) * cost_mult)
    total_iron = gv.inventory.total_iron + gv._station_inv.total_iron
    if total_iron < cost:
        gv._flash_msg = "Not enough iron!"
        gv._flash_timer = 2.0
        return
    if copper_cost > 0:
        total_copper = (gv.inventory.count_item("copper")
                        + gv._station_inv.count_item("copper"))
        if total_copper < copper_cost:
            gv._flash_msg = "Not enough copper!"
            gv._flash_timer = 2.0
            return
    # Deduct iron
    remaining = cost
    ship_iron = min(remaining, gv.inventory.total_iron)
    if ship_iron > 0:
        gv.inventory.remove_item("iron", ship_iron)
        remaining -= ship_iron
    if remaining > 0:
        gv._station_inv.remove_item("iron", remaining)
    # Deduct copper
    if copper_cost > 0:
        remaining_cu = copper_cost
        ship_cu = min(remaining_cu, gv.inventory.count_item("copper"))
        if ship_cu > 0:
            gv.inventory.remove_item("copper", ship_cu)
            remaining_cu -= ship_cu
        if remaining_cu > 0:
            gv._station_inv.remove_item("copper", remaining_cu)
    # Upgrade the ship
    gv._ship_level += 1
    gv.player.upgrade_ship()
    # Expand module slots
    new_slot_count = MODULE_SLOT_COUNT + (gv._ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
    old_slots = gv._module_slots
    gv._module_slots = [None] * new_slot_count
    for i in range(min(len(old_slots), new_slot_count)):
        gv._module_slots[i] = old_slots[i]
    gv.player.apply_modules(gv._module_slots)
    gv._hud.set_module_count(new_slot_count)
    gv._hud._mod_slots = list(gv._module_slots)
    # Increase ability meter max
    gv._ability_meter_max += SHIP_LEVEL_ABILITY_BONUS
    gv._ability_meter = gv._ability_meter_max
    # Flash message
    gv._flash_msg = f"Ship upgraded to level {gv._ship_level}!"
    gv._flash_timer = 3.0


def enter_placement_mode(gv: GameView, building_type: str) -> None:
    """Start building placement -- create ghost sprite following cursor.

    Advanced Ship enters placement mode with the next-level ship texture
    instead of a building texture.  Resource check happens up front.
    """
    if building_type == "Advanced Ship":
        # Resource check before entering placement mode
        from constants import SHIP_MAX_LEVEL
        from character_data import build_cost_multiplier
        bt_stats = BUILDING_TYPES[building_type]
        if gv._ship_level >= SHIP_MAX_LEVEL:
            gv._flash_msg = "Ship already at maximum level!"
            gv._flash_timer = 2.0
            return
        cost_mult = build_cost_multiplier(audio.character_name, gv._char_level)
        cost = int(bt_stats["cost"] * cost_mult)
        copper_cost = int(bt_stats.get("cost_copper", 0) * cost_mult)
        total_iron = gv.inventory.total_iron + gv._station_inv.total_iron
        if total_iron < cost:
            gv._flash_msg = "Not enough iron!"
            gv._flash_timer = 2.0
            return
        if copper_cost > 0:
            total_copper = (gv.inventory.count_item("copper")
                            + gv._station_inv.count_item("copper"))
            if total_copper < copper_cost:
                gv._flash_msg = "Not enough copper!"
                gv._flash_timer = 2.0
                return
        # Use next-level ship texture as the ghost
        from sprites.player import PlayerShip
        next_level = gv._ship_level + 1
        tex = PlayerShip._extract_ship_texture(
            gv._faction, gv._ship_type, next_level)
        gv._ghost_sprite = arcade.Sprite(path_or_texture=tex, scale=0.75)
        gv._ghost_sprite.alpha = 140
        gv._ghost_list = arcade.SpriteList()
        gv._ghost_list.append(gv._ghost_sprite)
        gv._ghost_rotation = 0.0
        gv._placing_building = building_type
        gv._build_menu.open = False
        return
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
    # Deduct iron
    remaining = cost
    ship_iron = min(remaining, gv.inventory.total_iron)
    if ship_iron > 0:
        gv.inventory.remove_item("iron", ship_iron)
        remaining -= ship_iron
    if remaining > 0:
        gv._station_inv.remove_item("iron", remaining)
    # Deduct copper
    if copper_cost > 0:
        remaining_cu = copper_cost
        ship_cu = min(remaining_cu, gv.inventory.count_item("copper"))
        if ship_cu > 0:
            gv.inventory.remove_item("copper", ship_cu)
            remaining_cu -= ship_cu
        if remaining_cu > 0:
            gv._station_inv.remove_item("copper", remaining_cu)

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


# ── Ship placement & switching ────────────────────────────────────────────

def _place_new_ship(gv: GameView, wx: float, wy: float) -> None:
    """Place a new level ship at (wx, wy), leaving the old ship parked."""
    from constants import (
        SHIP_MAX_LEVEL, SHIP_LEVEL_MODULE_BONUS, SHIP_LEVEL_ABILITY_BONUS,
        MODULE_SLOT_COUNT,
    )
    from character_data import build_cost_multiplier
    from sprites.parked_ship import ParkedShip

    bt_stats = BUILDING_TYPES["Advanced Ship"]
    cost_mult = build_cost_multiplier(audio.character_name, gv._char_level)
    cost = int(bt_stats["cost"] * cost_mult)
    copper_cost = int(bt_stats.get("cost_copper", 0) * cost_mult)

    # Deduct iron
    remaining = cost
    ship_iron = min(remaining, gv.inventory.total_iron)
    if ship_iron > 0:
        gv.inventory.remove_item("iron", ship_iron)
        remaining -= ship_iron
    if remaining > 0:
        gv._station_inv.remove_item("iron", remaining)

    # Deduct copper
    if copper_cost > 0:
        remaining_cu = copper_cost
        ship_cu = min(remaining_cu, gv.inventory.count_item("copper"))
        if ship_cu > 0:
            gv.inventory.remove_item("copper", ship_cu)
            remaining_cu -= ship_cu
        if remaining_cu > 0:
            gv._station_inv.remove_item("copper", remaining_cu)

    # Create parked ship from current player (empty cargo — player keeps it)
    old_parked = ParkedShip(
        faction=gv._faction,
        ship_type=gv._ship_type,
        ship_level=gv._ship_level,
        x=gv.player.center_x,
        y=gv.player.center_y,
        heading=gv.player.heading,
    )
    old_parked.hp = gv.player.hp
    old_parked.max_hp = gv.player.max_hp
    old_parked.shields = gv.player.shields
    old_parked.max_shields = gv.player.max_shields
    gv._parked_ships.append(old_parked)

    # Upgrade active ship
    gv._ship_level += 1
    gv.player.upgrade_ship()

    # Expand module slots
    new_slot_count = MODULE_SLOT_COUNT + (gv._ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
    old_slots = gv._module_slots
    gv._module_slots = [None] * new_slot_count
    for i in range(min(len(old_slots), new_slot_count)):
        gv._module_slots[i] = old_slots[i]
    gv.player.apply_modules(gv._module_slots)
    gv._hud.set_module_count(new_slot_count)
    gv._hud._mod_slots = list(gv._module_slots)

    # Increase ability meter
    gv._ability_meter_max += SHIP_LEVEL_ABILITY_BONUS
    gv._ability_meter = gv._ability_meter_max

    # Teleport player to placement position
    gv.player.center_x = wx
    gv.player.center_y = wy
    gv.player.vel_x = 0.0
    gv.player.vel_y = 0.0

    gv._flash_msg = f"Ship upgraded to level {gv._ship_level}!"
    gv._flash_timer = 3.0


def switch_to_ship(gv: GameView, target) -> None:
    """Swap control from the active PlayerShip to a parked ship."""
    from constants import (
        MODULE_SLOT_COUNT, SHIP_LEVEL_MODULE_BONUS,
        ABILITY_METER_MAX, SHIP_LEVEL_ABILITY_BONUS,
    )
    from sprites.player import PlayerShip
    from sprites.parked_ship import ParkedShip

    old_player = gv.player

    # Snapshot current player into a ParkedShip
    old_parked = ParkedShip(
        faction=gv._faction,
        ship_type=gv._ship_type,
        ship_level=gv._ship_level,
        x=old_player.center_x,
        y=old_player.center_y,
        heading=old_player.heading,
    )
    old_parked.hp = old_player.hp
    old_parked.max_hp = old_player.max_hp
    old_parked.shields = old_player.shields
    old_parked.max_shields = old_player.max_shields
    old_parked.cargo_items = dict(gv.inventory._items)
    old_parked.module_slots = list(gv._module_slots)

    # Create new PlayerShip from the target
    new_player = PlayerShip(
        faction=target.faction,
        ship_type=target.ship_type,
        ship_level=target.ship_level,
    )
    new_player.center_x = target.center_x
    new_player.center_y = target.center_y
    new_player.heading = target.heading
    new_player.angle = target.heading
    new_player.hp = target.hp
    new_player.max_hp = target.max_hp
    new_player.shields = target.shields
    new_player.max_shields = target.max_shields
    new_player.vel_x = 0.0
    new_player.vel_y = 0.0
    new_player.world_width = gv._zone.world_width
    new_player.world_height = gv._zone.world_height

    # Swap player reference
    gv.player_list.clear()
    gv.player = new_player
    gv.player_list.append(new_player)

    # Restore inventory from target
    gv.inventory._items = dict(target.cargo_items)
    gv.inventory._mark_dirty()

    # Restore module slots
    gv._ship_level = target.ship_level
    slot_count = MODULE_SLOT_COUNT + (target.ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
    gv._module_slots = list(target.module_slots)
    while len(gv._module_slots) < slot_count:
        gv._module_slots.append(None)
    gv._module_slots = gv._module_slots[:slot_count]
    new_player.apply_modules(gv._module_slots)
    gv._hud.set_module_count(slot_count)
    gv._hud._mod_slots = list(gv._module_slots)

    # Recalculate ability meter
    gv._ability_meter_max = ABILITY_METER_MAX + (gv._ship_level - 1) * SHIP_LEVEL_ABILITY_BONUS
    gv._ability_meter = min(gv._ability_meter, gv._ability_meter_max)

    # Reload weapons for new ship's gun count
    from world_setup import load_weapons
    gv._weapons = load_weapons(new_player.guns)
    gv._weapon_idx = 0

    # Swap parked ships list
    gv._parked_ships.remove(target)
    gv._parked_ships.append(old_parked)

    # Reposition shield
    gv.shield_sprite.center_x = new_player.center_x
    gv.shield_sprite.center_y = new_player.center_y

    gv._flash_msg = f"Switched to level {gv._ship_level} ship!"
    gv._flash_timer = 2.0
