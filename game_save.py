"""Save/Load/Restore logic extracted from GameView."""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import arcade

from constants import (
    FOG_GRID_W, FOG_GRID_H,
    MODULE_SLOT_COUNT, QUICK_USE_SLOTS,
    WORLD_WIDTH, WORLD_HEIGHT,
    DOUBLE_IRON_SCALE,
    ASTEROID_COUNT, DOUBLE_IRON_COUNT, COPPER_ASTEROID_COUNT,
    GAS_AREA_COUNT, WANDERING_COUNT,
)

if TYPE_CHECKING:
    from game_view import GameView

_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")


def _restore_zone2_full(view: GameView, z2_state: dict) -> None:
    """Restore full Zone 2 state from saved data, creating the persistent instance."""
    from zones import ZoneID, create_zone
    from zones.zone2 import Zone2
    from sprites.zone2_aliens import (
        ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
    from sprites.asteroid import IronAsteroid
    from sprites.copper_asteroid import CopperAsteroid
    from sprites.wandering_asteroid import WanderingAsteroid

    # Create zone instance with the saved seed
    zone = Zone2()
    zone._world_seed = z2_state.get("world_seed", zone._world_seed)
    zone._populated = True  # Mark as populated so setup() won't regenerate

    # Restore fog
    fog = z2_state.get("fog_grid")
    if fog is not None:
        zone._fog_grid = fog
        zone._fog_revealed = z2_state.get("fog_revealed", 0)

    # We need textures — use module-level caches from zone2
    import zones.zone2 as _z2mod
    import arcade as _arc
    from constants import COPPER_ASTEROID_PNG, Z2_ALIEN_SHIP_PNG

    # Textures from GameView
    iron_tex = view._asteroid_tex
    zone._iron_tex = iron_tex
    zone._wanderer_tex = iron_tex
    from constants import COPPER_PICKUP_PNG
    zone._copper_pickup_tex = _arc.load_texture(COPPER_PICKUP_PNG)

    # Restore iron asteroids
    zone._iron_asteroids.clear()
    for ad in z2_state.get("iron_asteroids", []):
        a = IronAsteroid(iron_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        zone._iron_asteroids.append(a)

    # Restore double iron asteroids
    zone._double_iron.clear()
    for ad in z2_state.get("double_iron", []):
        a = IronAsteroid(iron_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        a.scale = DOUBLE_IRON_SCALE
        zone._double_iron.append(a)

    # Restore copper asteroids
    copper_tex = _arc.load_texture(COPPER_ASTEROID_PNG)
    zone._copper_tex = copper_tex
    zone._copper_asteroids.clear()
    for ad in z2_state.get("copper_asteroids", []):
        a = CopperAsteroid(copper_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        zone._copper_asteroids.append(a)

    # Restore wandering asteroids
    zone._wanderers.clear()
    for wd in z2_state.get("wanderers", []):
        w = WanderingAsteroid(iron_tex, wd["x"], wd["y"],
                              zone.world_width, zone.world_height)
        w.hp = wd.get("hp", w.hp)
        w.angle = wd.get("angle", 0.0)
        zone._wanderers.append(w)

    # Restore gas areas (regenerated deterministically from seed)
    from sprites.gas_area import GasArea, generate_gas_texture
    import random
    random.seed(zone._world_seed)
    # Skip the population methods we don't need (iron, double, copper, ...)
    # Regenerate gas in the same order as _populate_gas_areas
    sizes = [64, 128, 192, 256, 384]
    # Skip random calls that would have been made by _populate_iron_asteroids,
    # _populate_double_iron, _populate_copper_asteroids
    for _ in range(ASTEROID_COUNT):
        random.uniform(100, zone.world_width - 100)
        random.uniform(100, zone.world_height - 100)
    for _ in range(DOUBLE_IRON_COUNT):
        random.uniform(100, zone.world_width - 100)
        random.uniform(100, zone.world_height - 100)
    for _ in range(COPPER_ASTEROID_COUNT):
        random.uniform(100, zone.world_width - 100)
        random.uniform(100, zone.world_height - 100)
    # Now gas areas
    gas_cache = _z2mod._gas_texture_cache
    zone._gas_areas.clear()
    for _ in range(GAS_AREA_COUNT):
        size = random.choice(sizes)
        if size not in gas_cache:
            gas_cache[size] = generate_gas_texture(size)
        x = random.uniform(200, zone.world_width - 200)
        y = random.uniform(200, zone.world_height - 200)
        zone._gas_areas.append(GasArea(gas_cache[size], x, y, size,
                                       world_w=zone.world_width,
                                       world_h=zone.world_height))
    zone._gas_pos_cache = [(g.center_x, g.center_y, g.radius)
                           for g in zone._gas_areas]
    random.seed()

    # Restore aliens
    zone._alien_laser_tex = view._alien_laser_tex
    # Ensure alien textures are loaded
    if _z2mod._alien_texture_cache is None:
        from sprites.zone2_aliens import ALIEN_CROPS
        from PIL import Image as PILImage
        pil_ship = PILImage.open(Z2_ALIEN_SHIP_PNG).convert("RGBA")
        atc = {}
        for name, crop in ALIEN_CROPS.items():
            frame = pil_ship.crop(crop)
            atc[name] = _arc.Texture(frame)
        pil_ship.close()
        _z2mod._alien_texture_cache = atc
        zone._alien_textures = atc
    else:
        zone._alien_textures = _z2mod._alien_texture_cache

    zone._aliens.clear()
    classes = {
        "shielded": ShieldedAlien, "fast": FastAlien,
        "gunner": GunnerAlien, "rammer": RammerAlien,
    }
    kw = dict(world_w=zone.world_width, world_h=zone.world_height)
    for ald in z2_state.get("aliens", []):
        atype = ald.get("type", "shielded")
        cls = classes.get(atype, ShieldedAlien)
        tex = zone._alien_textures.get(atype)
        if tex is None:
            continue
        al = cls(tex, zone._alien_laser_tex, ald["x"], ald["y"], **kw)
        al.hp = ald.get("hp", al.hp)
        al.shields = ald.get("shields", al.shields)
        al.vel_x = ald.get("vel_x", 0.0)
        al.vel_y = ald.get("vel_y", 0.0)
        al._heading = ald.get("heading", 0.0)
        al.angle = al._heading
        al._state = ald.get("state", 0)
        al._home_x = ald.get("home_x", ald["x"])
        al._home_y = ald.get("home_y", ald["y"])
        zone._aliens.append(al)

    # Store on GameView for reuse
    view._zone2 = zone


def _restore_zone2_aliens(view: GameView, aliens_data: list[dict]) -> None:
    """Restore Zone 2 aliens from saved data."""
    from sprites.zone2_aliens import (
        ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
    zone = view._zone
    zone._aliens.clear()
    classes = {
        "shielded": ShieldedAlien,
        "fast": FastAlien,
        "gunner": GunnerAlien,
        "rammer": RammerAlien,
    }
    kw = dict(world_w=zone.world_width, world_h=zone.world_height)
    for ald in aliens_data:
        atype = ald.get("type", "shielded")
        cls = classes.get(atype, ShieldedAlien)
        tex = zone._alien_textures.get(atype)
        if tex is None:
            continue
        al = cls(tex, zone._alien_laser_tex, ald["x"], ald["y"], **kw)
        al.hp = ald.get("hp", al.hp)
        al.shields = ald.get("shields", al.shields)
        al.vel_x = ald.get("vel_x", 0.0)
        al.vel_y = ald.get("vel_y", 0.0)
        al._heading = ald.get("heading", 0.0)
        al.angle = al._heading
        al._state = ald.get("state", 0)
        al._home_x = ald.get("home_x", ald["x"])
        al._home_y = ald.get("home_y", ald["y"])
        zone._aliens.append(al)


def _save_zone2_aliens(gv: GameView) -> list[dict]:
    """Serialize Zone 2 aliens if currently in Zone 2."""
    from zones import ZoneID
    if gv._zone.zone_id != ZoneID.ZONE2 or not hasattr(gv._zone, '_aliens'):
        return []
    from sprites.zone2_aliens import (
        ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
    result = []
    for al in gv._zone._aliens:
        if isinstance(al, ShieldedAlien):
            atype = "shielded"
        elif isinstance(al, FastAlien):
            atype = "fast"
        elif isinstance(al, GunnerAlien):
            atype = "gunner"
        elif isinstance(al, RammerAlien):
            atype = "rammer"
        else:
            atype = "shielded"
        result.append({
            "type": atype,
            "x": al.center_x, "y": al.center_y,
            "hp": al.hp, "shields": al.shields,
            "vel_x": al.vel_x, "vel_y": al.vel_y,
            "heading": al._heading, "state": al._state,
            "home_x": al._home_x, "home_y": al._home_y,
        })
    return result


def _save_zone1_stashed(gv: GameView) -> dict | None:
    """If Zone 1 data is stashed (player is in another zone), save it."""
    from zones import ZoneID
    if gv._zone.zone_id == ZoneID.MAIN:
        return None  # Zone 1 is active — saved via normal fields
    stash = gv._main_zone._stash
    if not stash:
        return None
    # Serialize the stashed Zone 1 sprite lists
    ast_list = stash.get("asteroid_list")
    alien_list = stash.get("alien_list")
    building_list = stash.get("building_list")
    pickup_list = stash.get("iron_pickup_list")
    fog = stash.get("_fog_grid")
    fog_rev = stash.get("_fog_revealed", 0)
    boss = stash.get("_boss")
    boss_spawned = stash.get("_boss_spawned", False)
    boss_defeated = stash.get("_boss_defeated", False)
    trade_station = stash.get("_trade_station")
    wormholes = stash.get("_wormholes", [])
    resp_ast = stash.get("_asteroid_respawn_timer", 0.0)
    resp_alien = stash.get("_alien_respawn_timer", 0.0)

    result: dict = {
        "asteroids": [
            {"x": a.center_x, "y": a.center_y, "hp": a.hp}
            for a in (ast_list or [])
        ],
        "aliens": [
            {
                "x": al.center_x, "y": al.center_y, "hp": al.hp,
                "vel_x": al.vel_x, "vel_y": al.vel_y,
                "heading": al._heading, "state": al._state,
                "home_x": al._home_x, "home_y": al._home_y,
            }
            for al in (alien_list or [])
        ],
        "pickups": [
            {"x": p.center_x, "y": p.center_y, "amount": p.amount}
            for p in (pickup_list or [])
        ],
        "buildings": [
            {
                "type": b.building_type, "x": b.center_x, "y": b.center_y,
                "hp": b.hp, "angle": b.angle, "disabled": b.disabled,
            }
            for b in (building_list or [])
        ],
        "fog_grid": fog,
        "fog_revealed": fog_rev,
        "respawn_timers": {"asteroid": resp_ast, "alien": resp_alien},
        "boss_spawned": boss_spawned,
        "boss_defeated": boss_defeated,
        "trade_station": {
            "x": trade_station.center_x,
            "y": trade_station.center_y,
        } if trade_station is not None else None,
        "wormholes": [
            {"x": wh.center_x, "y": wh.center_y,
             "zone_target": wh.zone_target.name if wh.zone_target else None}
            for wh in wormholes
        ],
    }
    if boss is not None and boss.hp > 0:
        result["boss"] = {
            "x": boss.center_x, "y": boss.center_y,
            "hp": boss.hp, "shields": boss.shields,
            "heading": boss._heading,
            "vel_x": boss.vel_x, "vel_y": boss.vel_y,
            "phase": boss._phase,
            "target_x": boss._target_x, "target_y": boss._target_y,
        }
    return result


def _save_zone2_state(gv: GameView) -> dict | None:
    """Save Zone 2 state (from active zone or stashed instance)."""
    from zones import ZoneID
    zone2 = None
    if gv._zone.zone_id == ZoneID.ZONE2:
        zone2 = gv._zone
    elif gv._zone2 is not None and gv._zone2._populated:
        zone2 = gv._zone2
    if zone2 is None:
        return None
    # Serialize Zone 2 sprites
    from sprites.zone2_aliens import (
        ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
    aliens = []
    for al in zone2._aliens:
        if isinstance(al, ShieldedAlien):
            atype = "shielded"
        elif isinstance(al, FastAlien):
            atype = "fast"
        elif isinstance(al, GunnerAlien):
            atype = "gunner"
        elif isinstance(al, RammerAlien):
            atype = "rammer"
        else:
            atype = "shielded"
        aliens.append({
            "type": atype,
            "x": al.center_x, "y": al.center_y,
            "hp": al.hp, "shields": al.shields,
            "vel_x": al.vel_x, "vel_y": al.vel_y,
            "heading": al._heading, "state": al._state,
            "home_x": al._home_x, "home_y": al._home_y,
        })
    return {
        "world_seed": zone2._world_seed,
        "fog_grid": zone2._fog_grid,
        "fog_revealed": zone2._fog_revealed,
        "aliens": aliens,
        "iron_asteroids": [
            {"x": a.center_x, "y": a.center_y, "hp": a.hp}
            for a in zone2._iron_asteroids
        ],
        "double_iron": [
            {"x": a.center_x, "y": a.center_y, "hp": a.hp}
            for a in zone2._double_iron
        ],
        "copper_asteroids": [
            {"x": a.center_x, "y": a.center_y, "hp": a.hp}
            for a in zone2._copper_asteroids
        ],
        "wanderers": [
            {"x": w.center_x, "y": w.center_y, "hp": w.hp, "angle": w.angle}
            for w in zone2._wanderers
        ],
    }


def save_to_dict(gv: GameView, name: str = "") -> dict:
    """Serialize current game state to a dict."""
    from settings import audio
    from zones import ZoneID

    # Determine which zone's data is live on gv vs stashed
    in_main = gv._zone.zone_id == ZoneID.MAIN

    # Zone 1 data: either live on gv or stashed in _main_zone._stash
    if in_main:
        z1_asteroids = [
            {"x": a.center_x, "y": a.center_y, "hp": a.hp}
            for a in gv.asteroid_list
        ]
        z1_aliens = [
            {
                "x": al.center_x, "y": al.center_y, "hp": al.hp,
                "vel_x": al.vel_x, "vel_y": al.vel_y,
                "heading": al._heading, "state": al._state,
                "home_x": al._home_x, "home_y": al._home_y,
            }
            for al in gv.alien_list
        ]
        z1_pickups = [
            {"x": p.center_x, "y": p.center_y, "amount": p.amount}
            for p in gv.iron_pickup_list
        ]
        z1_buildings = [
            {
                "type": b.building_type, "x": b.center_x, "y": b.center_y,
                "hp": b.hp, "angle": b.angle, "disabled": b.disabled,
            }
            for b in gv.building_list
        ]
        z1_fog = gv._fog_grid
        z1_respawn = {
            "asteroid": gv._asteroid_respawn_timer,
            "alien": gv._alien_respawn_timer,
        }
        z1_boss_spawned = gv._boss_spawned
        z1_boss_defeated = gv._boss_defeated
        z1_boss = None
        if gv._boss is not None:
            z1_boss = {
                "x": gv._boss.center_x, "y": gv._boss.center_y,
                "hp": gv._boss.hp, "shields": gv._boss.shields,
                "heading": gv._boss._heading,
                "vel_x": gv._boss.vel_x, "vel_y": gv._boss.vel_y,
                "phase": gv._boss._phase,
                "target_x": gv._boss._target_x,
                "target_y": gv._boss._target_y,
            }
        z1_trade = {
            "x": gv._trade_station.center_x, "y": gv._trade_station.center_y,
        } if gv._trade_station is not None else None
        z1_wormholes = [
            {"x": wh.center_x, "y": wh.center_y,
             "zone_target": wh.zone_target.name if wh.zone_target else None}
            for wh in gv._wormholes
        ]
    else:
        # Zone 1 is stashed — pull from stash
        z1_data = _save_zone1_stashed(gv)
        if z1_data:
            z1_asteroids = z1_data["asteroids"]
            z1_aliens = z1_data["aliens"]
            z1_pickups = z1_data["pickups"]
            z1_buildings = z1_data["buildings"]
            z1_fog = z1_data["fog_grid"]
            z1_respawn = z1_data["respawn_timers"]
            z1_boss_spawned = z1_data["boss_spawned"]
            z1_boss_defeated = z1_data["boss_defeated"]
            z1_boss = z1_data.get("boss")
            z1_trade = z1_data["trade_station"]
            z1_wormholes = z1_data["wormholes"]
        else:
            # No stash (shouldn't happen) — save empty
            z1_asteroids = []
            z1_aliens = []
            z1_pickups = []
            z1_buildings = []
            z1_fog = None
            z1_respawn = {"asteroid": 0.0, "alien": 0.0}
            z1_boss_spawned = False
            z1_boss_defeated = False
            z1_boss = None
            z1_trade = None
            z1_wormholes = []

    return {
        "save_name": name,
        "faction": gv._faction,
        "ship_type": gv._ship_type,
        "character_name": audio.character_name,
        "character_xp": gv._char_xp,
        "player": {
            "x": gv.player.center_x,
            "y": gv.player.center_y,
            "heading": gv.player.heading,
            "vel_x": gv.player.vel_x,
            "vel_y": gv.player.vel_y,
            "hp": gv.player.hp,
            "shields": gv.player.shields,
            "shield_acc": gv.player._shield_acc,
        },
        "weapon_idx": gv._weapon_idx,
        "iron": gv.inventory.total_iron,
        "cargo_items": [
            {"r": r, "c": c, "type": it, "count": ct}
            for (r, c), (it, ct) in gv.inventory._items.items()
        ],
        # Zone 1 (Double Star) state — always saved
        "asteroids": z1_asteroids,
        "aliens": z1_aliens,
        "pickups": z1_pickups,
        "buildings": z1_buildings,
        "respawn_timers": z1_respawn,
        "fog_grid": z1_fog,
        "boss_spawned": z1_boss_spawned,
        "boss_defeated": z1_boss_defeated,
        "boss": z1_boss,
        "trade_station": z1_trade,
        "wormholes": z1_wormholes,
        # Shared state
        "station_inventory": gv._station_inv.to_save_data(),
        "module_slots": gv._module_slots,
        "quick_use": [
            {"type": gv._hud._qu_slots[i], "count": gv._hud._qu_counts[i]}
            for i in range(QUICK_USE_SLOTS)
        ],
        "unlocked_recipes": list(gv._craft_menu._unlocked),
        "credits": gv._trade_menu.credits,
        # Current zone
        "zone_id": gv._zone.zone_id.name,
        # Zone 2 (Nebula) state — saved if it exists
        "zone2_state": _save_zone2_state(gv),
        # Legacy fields kept for backwards compat
        "zone_seed": getattr(gv._zone, '_world_seed', None),
        "zone2_aliens": _save_zone2_aliens(gv),
    }


def save_game(gv: GameView, slot: int, name: str) -> None:
    """Serialize current game state to a numbered save slot."""
    os.makedirs(_SAVE_DIR, exist_ok=True)
    path = os.path.join(_SAVE_DIR, f"save_slot_{slot + 1:02d}.json")
    data = save_to_dict(gv, name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def restore_state(view: GameView, data: dict) -> None:
    """Restore game state from a dict into a freshly constructed GameView."""
    from sprites.building import create_building

    # Player
    p = data["player"]
    view.player.center_x = p["x"]
    view.player.center_y = p["y"]
    view.player.heading = p["heading"]
    view.player.angle = p["heading"]
    view.player.vel_x = p["vel_x"]
    view.player.vel_y = p["vel_y"]
    view.player.hp = p["hp"]
    view.player.shields = p["shields"]
    view.player._shield_acc = p.get("shield_acc", 0.0)
    view._weapon_idx = data.get("weapon_idx", 0)

    # Cargo inventory
    view.inventory._items.clear()
    cargo_items = data.get("cargo_items")
    if cargo_items:
        for entry in cargo_items:
            view.inventory._items[(entry["r"], entry["c"])] = (entry["type"], entry["count"])
    else:
        old_iron = data.get("iron", 0)
        if old_iron > 0:
            view.inventory.add_item("iron", old_iron)

    # Asteroids
    view.asteroid_list.clear()
    from sprites.asteroid import IronAsteroid
    asteroid_tex = arcade.load_texture(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "assets", "Pixel Art Space", "Asteroid.png"))
    for ad in data.get("asteroids", []):
        a = IronAsteroid(asteroid_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        view.asteroid_list.append(a)

    # Aliens
    view.alien_list.clear()
    from PIL import Image as PILImage
    from constants import ALIEN_SHIP_PNG, ALIEN_FX_PNG
    _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
    alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))
    _pil_ship.close()
    _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
    _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
    alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))
    _pil_fx.close()
    from sprites.alien import SmallAlienShip
    for ald in data.get("aliens", []):
        al = SmallAlienShip(alien_ship_tex, alien_laser_tex, ald["x"], ald["y"])
        al.hp = ald["hp"]
        al.vel_x = ald.get("vel_x", 0.0)
        al.vel_y = ald.get("vel_y", 0.0)
        al._heading = ald.get("heading", 0.0)
        al.angle = al._heading
        al._state = ald.get("state", 0)
        al._home_x = ald.get("home_x", ald["x"])
        al._home_y = ald.get("home_y", ald["y"])
        view.alien_list.append(al)

    # Iron pickups
    view.iron_pickup_list.clear()
    for pd in data.get("pickups", []):
        view._spawn_iron_pickup(pd["x"], pd["y"], amount=pd.get("amount", 10))

    # Buildings
    view.building_list.clear()
    for bd in data.get("buildings", []):
        bt = bd["type"]
        tex = view._building_textures[bt]
        laser_tex = view._turret_laser_tex if "Turret" in bt else None
        b = create_building(bt, tex, bd["x"], bd["y"], laser_tex=laser_tex, scale=0.5)
        b.hp = bd.get("hp", b.max_hp)
        b.angle = bd.get("angle", 0.0)
        b.disabled = bd.get("disabled", False)
        if b.disabled:
            b.color = (128, 128, 128, 255)
        view.building_list.append(b)

    # Respawn timers
    rt = data.get("respawn_timers", {})
    view._asteroid_respawn_timer = rt.get("asteroid", 0.0)
    view._alien_respawn_timer = rt.get("alien", 0.0)

    # Fog of war
    saved_fog = data.get("fog_grid")
    if (saved_fog is not None and isinstance(saved_fog, list)
            and len(saved_fog) == FOG_GRID_H
            and all(isinstance(r, list) and len(r) == FOG_GRID_W for r in saved_fog)):
        view._fog_grid = saved_fog
        # Recount revealed cells
        view._fog_revealed = sum(
            cell for row in saved_fog for cell in row)

    # Station inventory
    si_data = data.get("station_inventory")
    if si_data:
        view._station_inv.from_save_data(si_data)

    # Module slots
    saved_mods = data.get("module_slots")
    if saved_mods and isinstance(saved_mods, list):
        for i in range(min(len(saved_mods), MODULE_SLOT_COUNT)):
            view._module_slots[i] = saved_mods[i]
        view.player.apply_modules(view._module_slots)
        view._hud._mod_slots = list(view._module_slots)

    # Unlocked recipes
    saved_unlocked = data.get("unlocked_recipes")
    if saved_unlocked and isinstance(saved_unlocked, list):
        view._craft_menu._unlocked = set(saved_unlocked)

    # Restore character name
    from settings import audio
    saved_char = data.get("character_name", "")
    if saved_char:
        audio.character_name = saved_char
    # Restore character XP
    from character_data import level_for_xp
    view._char_xp = data.get("character_xp", 0)
    view._char_level = level_for_xp(view._char_xp)
    view._apply_character_weapon_bonuses()

    # Quick-use slots
    saved_qu = data.get("quick_use")
    if saved_qu and isinstance(saved_qu, list):
        for i, slot_data in enumerate(saved_qu):
            if i < QUICK_USE_SLOTS and isinstance(slot_data, dict):
                view._hud.set_quick_use(
                    i, slot_data.get("type"), slot_data.get("count", 0))

    # Trading station
    view._trade_menu.credits = data.get("credits", 0)
    ts_data = data.get("trade_station")
    if ts_data and isinstance(ts_data, dict):
        import arcade as _arc
        view._trade_station = _arc.Sprite(
            path_or_texture=view._trade_station_tex, scale=0.15)
        view._trade_station.center_x = ts_data["x"]
        view._trade_station.center_y = ts_data["y"]
    elif ts_data is None:
        # Old save without trade station data — spawn if repair module exists
        from sprites.building import RepairModule
        if any(isinstance(b, RepairModule) for b in view.building_list):
            view._spawn_trade_station()

    # Boss encounter
    view._boss_spawned = data.get("boss_spawned", False)
    view._boss_defeated = data.get("boss_defeated", False)
    boss_data = data.get("boss")
    if boss_data and isinstance(boss_data, dict):
        from sprites.boss import BossAlienShip
        view._boss = BossAlienShip(
            view._boss_tex, view._boss_laser_tex,
            boss_data["x"], boss_data["y"],
            boss_data.get("target_x", WORLD_WIDTH / 2),
            boss_data.get("target_y", WORLD_HEIGHT / 2),
        )
        view._boss.hp = boss_data["hp"]
        view._boss.shields = boss_data.get("shields", 0)
        view._boss._heading = boss_data.get("heading", 0.0)
        view._boss.angle = view._boss._heading
        view._boss.vel_x = boss_data.get("vel_x", 0.0)
        view._boss.vel_y = boss_data.get("vel_y", 0.0)
        view._boss._phase = boss_data.get("phase", 1)
        view._boss_list.clear()
        view._boss_list.append(view._boss)
    else:
        view._boss = None
        view._boss_list.clear()

    # Wormholes
    view._wormholes.clear()
    view._wormhole_list.clear()
    for whd in data.get("wormholes", []):
        from sprites.wormhole import Wormhole
        from zones import ZoneID
        wh = Wormhole(whd["x"], whd["y"])
        zt = whd.get("zone_target")
        if zt and isinstance(zt, str):
            wh.zone_target = ZoneID[zt]
        view._wormholes.append(wh)
        view._wormhole_list.append(wh)

    # Restore Zone 2 state (if saved) — create the persistent Zone 2 instance
    z2_state = data.get("zone2_state")
    if z2_state and isinstance(z2_state, dict):
        _restore_zone2_full(view, z2_state)

    # Restore zone — transition to saved zone if not MAIN
    saved_zone = data.get("zone_id", "MAIN")
    if saved_zone != "MAIN":
        from zones import ZoneID, create_zone
        zid = ZoneID[saved_zone]
        # Transition away from Zone 1 (stashes Zone 1 data we just restored)
        if zid == ZoneID.ZONE2 and view._zone2 is not None:
            view._zone.teardown(view)
            view._zone = view._zone2
        else:
            view._zone.teardown(view)
            if zid == ZoneID.ZONE2:
                view._zone2 = create_zone(ZoneID.ZONE2)
                saved_seed = data.get("zone_seed")
                if saved_seed is not None:
                    view._zone2._world_seed = saved_seed
                view._zone = view._zone2
            else:
                view._zone = create_zone(zid)
        view._zone.setup(view)
        view.player.world_width = view._zone.world_width
        view.player.world_height = view._zone.world_height
        # Restore Zone 2 fog into the zone (setup may have created a blank one)
        if z2_state and hasattr(view._zone, '_fog_grid'):
            z2_fog = z2_state.get("fog_grid")
            if z2_fog is not None:
                view._zone._fog_grid = z2_fog
                view._zone._fog_revealed = sum(
                    cell for row in z2_fog for cell in row)
                view._fog_grid = view._zone._fog_grid
                view._fog_revealed = view._zone._fog_revealed
        # Legacy: restore Zone 2 aliens from old save format
        elif not z2_state:
            z2_aliens = data.get("zone2_aliens", [])
            if z2_aliens and hasattr(view._zone, '_aliens'):
                _restore_zone2_aliens(view, z2_aliens)
            saved_fog = data.get("fog_grid")
            if saved_fog is not None:
                view._fog_grid = saved_fog
                view._fog_revealed = sum(
                    cell for row in saved_fog for cell in row)
                if hasattr(view._zone, '_fog_grid'):
                    view._zone._fog_grid = saved_fog
                    view._zone._fog_revealed = view._fog_revealed


def load_game(gv: GameView, slot: int) -> None:
    """Load game state from a numbered save slot and rebuild the view."""
    path = os.path.join(_SAVE_DIR, f"save_slot_{slot + 1:02d}.json")
    if not os.path.exists(path):
        gv._escape_menu._flash_status("No save file found!")
        return
    with open(path, "r") as f:
        data = json.load(f)
    # Clean up old view resources before rebuilding
    import gc
    gv._cleanup()
    gc.collect()
    from game_view import GameView as GV
    view = GV(faction=data.get("faction"), ship_type=data.get("ship_type"))
    restore_state(view, data)
    gv.window.show_view(view)
