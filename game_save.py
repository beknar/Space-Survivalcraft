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


# ── Serialization helpers ──────────────────────────────────────────────────

def _serialize_asteroid(a) -> dict:
    return {"x": a.center_x, "y": a.center_y, "hp": a.hp}


def _serialize_alien(al) -> dict:
    return {
        "x": al.center_x, "y": al.center_y, "hp": al.hp,
        "vel_x": al.vel_x, "vel_y": al.vel_y,
        "heading": al._heading, "state": al._state,
        "home_x": al._home_x, "home_y": al._home_y,
    }


def _serialize_z2_alien(al) -> dict:
    from sprites.zone2_aliens import (
        ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
    _TYPE_MAP = {ShieldedAlien: "shielded", FastAlien: "fast",
                 GunnerAlien: "gunner", RammerAlien: "rammer"}
    atype = _TYPE_MAP.get(type(al), "shielded")
    d = _serialize_alien(al)
    d.update(type=atype, shields=al.shields)
    return d


def _serialize_building(b) -> dict:
    return {
        "type": b.building_type, "x": b.center_x, "y": b.center_y,
        "hp": b.hp, "angle": b.angle, "disabled": b.disabled,
    }


def _serialize_pickup(p) -> dict:
    return {"x": p.center_x, "y": p.center_y, "amount": p.amount}


def _serialize_boss(boss) -> dict | None:
    if boss is None or boss.hp <= 0:
        return None
    return {
        "x": boss.center_x, "y": boss.center_y,
        "hp": boss.hp, "shields": boss.shields,
        "heading": boss._heading,
        "vel_x": boss.vel_x, "vel_y": boss.vel_y,
        "phase": boss._phase,
        "target_x": boss._target_x, "target_y": boss._target_y,
    }


def _serialize_wormhole(wh) -> dict:
    return {
        "x": wh.center_x, "y": wh.center_y,
        "zone_target": wh.zone_target.name if wh.zone_target else None,
    }


def _serialize_trade_station(ts) -> dict | None:
    if ts is None:
        return None
    return {"x": ts.center_x, "y": ts.center_y}


# ── Deserialization helpers ────────────────────────────────────────────────

def _restore_z1_asteroids(view: GameView, data: list[dict]) -> None:
    """Restore Zone 1 iron asteroids from saved data."""
    from sprites.asteroid import IronAsteroid
    asteroid_tex = arcade.load_texture(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "assets", "Pixel Art Space", "Asteroid.png"))
    view.asteroid_list.clear()
    for ad in data:
        a = IronAsteroid(asteroid_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        view.asteroid_list.append(a)


def _restore_z1_aliens(view: GameView, data: list[dict]) -> None:
    """Restore Zone 1 aliens from saved data."""
    from PIL import Image as PILImage
    from constants import ALIEN_SHIP_PNG, ALIEN_FX_PNG
    from sprites.alien import SmallAlienShip
    _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
    alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))
    _pil_ship.close()
    _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
    _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
    alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))
    _pil_fx.close()
    view.alien_list.clear()
    for ald in data:
        al = SmallAlienShip(alien_ship_tex, alien_laser_tex, ald["x"], ald["y"])
        _apply_alien_fields(al, ald)
        view.alien_list.append(al)


def _apply_alien_fields(al, ald: dict) -> None:
    """Apply shared alien fields from saved data dict."""
    al.hp = ald.get("hp", al.hp)
    al.vel_x = ald.get("vel_x", 0.0)
    al.vel_y = ald.get("vel_y", 0.0)
    al._heading = ald.get("heading", 0.0)
    al.angle = al._heading
    al._state = ald.get("state", 0)
    al._home_x = ald.get("home_x", ald["x"])
    al._home_y = ald.get("home_y", ald["y"])


def _restore_z2_aliens_into(zone, aliens_data: list[dict]) -> None:
    """Restore Zone 2 aliens into a Zone2 instance."""
    from sprites.zone2_aliens import (
        ShieldedAlien, FastAlien, GunnerAlien, RammerAlien)
    classes = {
        "shielded": ShieldedAlien, "fast": FastAlien,
        "gunner": GunnerAlien, "rammer": RammerAlien,
    }
    kw = dict(world_w=zone.world_width, world_h=zone.world_height)
    zone._aliens.clear()
    for ald in aliens_data:
        atype = ald.get("type", "shielded")
        cls = classes.get(atype, ShieldedAlien)
        tex = zone._alien_textures.get(atype)
        if tex is None:
            continue
        al = cls(tex, zone._alien_laser_tex, ald["x"], ald["y"], **kw)
        _apply_alien_fields(al, ald)
        al.shields = ald.get("shields", al.shields)
        zone._aliens.append(al)


def _restore_boss(view: GameView, boss_data: dict | None) -> None:
    """Restore boss from saved data."""
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


def _restore_wormholes(view: GameView, wh_data: list[dict]) -> None:
    """Restore wormholes from saved data."""
    from sprites.wormhole import Wormhole
    from zones import ZoneID
    view._wormholes.clear()
    view._wormhole_list.clear()
    for whd in wh_data:
        wh = Wormhole(whd["x"], whd["y"])
        zt = whd.get("zone_target")
        if zt and isinstance(zt, str):
            wh.zone_target = ZoneID[zt]
        view._wormholes.append(wh)
        view._wormhole_list.append(wh)


# ── Zone 2 full save/restore ──────────────────────────────────────────────

def _restore_zone2_full(view: GameView, z2_state: dict) -> None:
    """Restore full Zone 2 state from saved data, creating the persistent instance."""
    from zones.zone2 import Zone2
    from sprites.asteroid import IronAsteroid
    from sprites.copper_asteroid import CopperAsteroid
    from sprites.wandering_asteroid import WanderingAsteroid
    import zones.zone2 as _z2mod

    zone = Zone2()
    zone._world_seed = z2_state.get("world_seed", zone._world_seed)
    zone._populated = True

    # Restore fog
    fog = z2_state.get("fog_grid")
    if fog is not None:
        zone._fog_grid = fog
        zone._fog_revealed = z2_state.get("fog_revealed", 0)

    # Textures
    from constants import COPPER_ASTEROID_PNG, COPPER_PICKUP_PNG, Z2_ALIEN_SHIP_PNG
    iron_tex = view._asteroid_tex
    zone._iron_tex = iron_tex
    zone._wanderer_tex = iron_tex
    zone._copper_pickup_tex = arcade.load_texture(COPPER_PICKUP_PNG)
    copper_tex = arcade.load_texture(COPPER_ASTEROID_PNG)
    zone._copper_tex = copper_tex

    # Restore iron asteroids
    zone._iron_asteroids.clear()
    for ad in z2_state.get("iron_asteroids", []):
        a = IronAsteroid(iron_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        zone._iron_asteroids.append(a)

    # Restore double iron
    zone._double_iron.clear()
    for ad in z2_state.get("double_iron", []):
        a = IronAsteroid(iron_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        a.scale = DOUBLE_IRON_SCALE
        zone._double_iron.append(a)

    # Restore copper
    zone._copper_asteroids.clear()
    for ad in z2_state.get("copper_asteroids", []):
        a = CopperAsteroid(copper_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        zone._copper_asteroids.append(a)

    # Restore wanderers
    zone._wanderers.clear()
    for wd in z2_state.get("wanderers", []):
        w = WanderingAsteroid(iron_tex, wd["x"], wd["y"],
                              zone.world_width, zone.world_height)
        w.hp = wd.get("hp", w.hp)
        w.angle = wd.get("angle", 0.0)
        w._wander_angle = wd.get("wander_angle", w._wander_angle)
        w._wander_timer = wd.get("wander_timer", w._wander_timer)
        w._repel_timer = wd.get("repel_timer", 0.0)
        zone._wanderers.append(w)

    # Gas areas (deterministic from seed)
    _regenerate_gas_areas(zone, _z2mod)

    # Alien textures
    zone._alien_laser_tex = view._alien_laser_tex
    _ensure_alien_textures(_z2mod, Z2_ALIEN_SHIP_PNG)
    zone._alien_textures = _z2mod._alien_texture_cache

    # Restore aliens
    _restore_z2_aliens_into(zone, z2_state.get("aliens", []))

    view._zone2 = zone


def _regenerate_gas_areas(zone, _z2mod) -> None:
    """Regenerate gas areas deterministically from zone seed."""
    from sprites.gas_area import GasArea, generate_gas_texture
    import random
    random.seed(zone._world_seed)
    # Skip random calls from population methods that run before gas
    for _ in range(ASTEROID_COUNT + DOUBLE_IRON_COUNT + COPPER_ASTEROID_COUNT):
        random.uniform(0, 1)
        random.uniform(0, 1)
    sizes = [64, 128, 192, 256, 384]
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


def _ensure_alien_textures(_z2mod, ship_png: str) -> None:
    """Load Zone 2 alien textures into module cache if not already loaded."""
    if _z2mod._alien_texture_cache is not None:
        return
    from sprites.zone2_aliens import ALIEN_CROPS
    from PIL import Image as PILImage
    pil_ship = PILImage.open(ship_png).convert("RGBA")
    atc = {}
    for name, crop in ALIEN_CROPS.items():
        atc[name] = arcade.Texture(pil_ship.crop(crop))
    pil_ship.close()
    _z2mod._alien_texture_cache = atc


# ── Zone 1 stash serialization ─────────────────────────────────────────────

def _save_zone1_data(gv: GameView) -> dict:
    """Serialize Zone 1 state — either live on gv or stashed in _main_zone."""
    from zones import ZoneID
    if gv._zone.zone_id == ZoneID.MAIN:
        return _save_zone1_live(gv)
    stash = gv._main_zone._stash
    if not stash:
        return _empty_zone1()
    return _save_zone1_from_stash(stash)


def _save_zone1_live(gv: GameView) -> dict:
    """Serialize Zone 1 from live GameView attributes."""
    return {
        "asteroids": [_serialize_asteroid(a) for a in gv.asteroid_list],
        "aliens": [_serialize_alien(al) for al in gv.alien_list],
        "pickups": [_serialize_pickup(p) for p in gv.iron_pickup_list],
        "buildings": [_serialize_building(b) for b in gv.building_list],
        "fog_grid": gv._fog_grid,
        "respawn_timers": {
            "asteroid": gv._asteroid_respawn_timer,
            "alien": gv._alien_respawn_timer,
        },
        "boss_spawned": gv._boss_spawned,
        "boss_defeated": gv._boss_defeated,
        "boss": _serialize_boss(gv._boss),
        "trade_station": _serialize_trade_station(gv._trade_station),
        "wormholes": [_serialize_wormhole(wh) for wh in gv._wormholes],
    }


def _save_zone1_from_stash(stash: dict) -> dict:
    """Serialize Zone 1 from MainZone's stash dict."""
    boss = stash.get("_boss")
    return {
        "asteroids": [_serialize_asteroid(a) for a in (stash.get("asteroid_list") or [])],
        "aliens": [_serialize_alien(al) for al in (stash.get("alien_list") or [])],
        "pickups": [_serialize_pickup(p) for p in (stash.get("iron_pickup_list") or [])],
        "buildings": [_serialize_building(b) for b in (stash.get("building_list") or [])],
        "fog_grid": stash.get("_fog_grid"),
        "respawn_timers": {
            "asteroid": stash.get("_asteroid_respawn_timer", 0.0),
            "alien": stash.get("_alien_respawn_timer", 0.0),
        },
        "boss_spawned": stash.get("_boss_spawned", False),
        "boss_defeated": stash.get("_boss_defeated", False),
        "boss": _serialize_boss(boss),
        "trade_station": _serialize_trade_station(stash.get("_trade_station")),
        "wormholes": [_serialize_wormhole(wh) for wh in stash.get("_wormholes", [])],
    }


def _empty_zone1() -> dict:
    return {
        "asteroids": [], "aliens": [], "pickups": [], "buildings": [],
        "fog_grid": None,
        "respawn_timers": {"asteroid": 0.0, "alien": 0.0},
        "boss_spawned": False, "boss_defeated": False, "boss": None,
        "trade_station": None, "wormholes": [],
    }


# ── Zone 2 save ────────────────────────────────────────────────────────────

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
    return {
        "world_seed": zone2._world_seed,
        "fog_grid": zone2._fog_grid,
        "fog_revealed": zone2._fog_revealed,
        "aliens": [_serialize_z2_alien(al) for al in zone2._aliens],
        "iron_asteroids": [_serialize_asteroid(a) for a in zone2._iron_asteroids],
        "double_iron": [_serialize_asteroid(a) for a in zone2._double_iron],
        "copper_asteroids": [_serialize_asteroid(a) for a in zone2._copper_asteroids],
        "wanderers": [
            {"x": w.center_x, "y": w.center_y, "hp": w.hp, "angle": w.angle,
             "wander_angle": w._wander_angle, "wander_timer": w._wander_timer,
             "repel_timer": w._repel_timer}
            for w in zone2._wanderers
        ],
    }


# ── Main save/restore ─────────────────────────────────────────────────────

def save_to_dict(gv: GameView, name: str = "") -> dict:
    """Serialize current game state to a dict."""
    from settings import audio

    z1 = _save_zone1_data(gv)

    return {
        "save_name": name,
        "faction": gv._faction,
        "ship_type": gv._ship_type,
        "character_name": audio.character_name,
        "character_xp": gv._char_xp,
        "player": {
            "x": gv.player.center_x, "y": gv.player.center_y,
            "heading": gv.player.heading,
            "vel_x": gv.player.vel_x, "vel_y": gv.player.vel_y,
            "hp": gv.player.hp, "shields": gv.player.shields,
            "shield_acc": gv.player._shield_acc,
        },
        "weapon_idx": gv._weapon_idx,
        "iron": gv.inventory.total_iron,
        "cargo_items": [
            {"r": r, "c": c, "type": it, "count": ct}
            for (r, c), (it, ct) in gv.inventory._items.items()
        ],
        # Zone 1 (Double Star) state
        **z1,
        # Shared state
        "station_inventory": gv._station_inv.to_save_data(),
        "module_slots": gv._module_slots,
        "quick_use": [
            {"type": gv._hud._qu_slots[i], "count": gv._hud._qu_counts[i]}
            for i in range(QUICK_USE_SLOTS)
        ],
        "unlocked_recipes": list(gv._craft_menu._unlocked),
        "credits": gv._trade_menu.credits,
        "zone_id": gv._zone.zone_id.name,
        "zone2_state": _save_zone2_state(gv),
        # Legacy compat
        "zone_seed": getattr(gv._zone, '_world_seed', None),
        "zone2_aliens": [],
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

    # Zone 1 entities
    _restore_z1_asteroids(view, data.get("asteroids", []))
    _restore_z1_aliens(view, data.get("aliens", []))

    view.iron_pickup_list.clear()
    for pd in data.get("pickups", []):
        view._spawn_iron_pickup(pd["x"], pd["y"], amount=pd.get("amount", 10))

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
        view._fog_revealed = sum(cell for row in saved_fog for cell in row)

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

    # Character
    from settings import audio
    saved_char = data.get("character_name", "")
    if saved_char:
        audio.character_name = saved_char
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
        view._trade_station = arcade.Sprite(
            path_or_texture=view._trade_station_tex, scale=0.15)
        view._trade_station.center_x = ts_data["x"]
        view._trade_station.center_y = ts_data["y"]
    elif ts_data is None:
        from sprites.building import RepairModule
        if any(isinstance(b, RepairModule) for b in view.building_list):
            view._spawn_trade_station()

    # Boss
    view._boss_spawned = data.get("boss_spawned", False)
    view._boss_defeated = data.get("boss_defeated", False)
    _restore_boss(view, data.get("boss"))

    # Wormholes
    _restore_wormholes(view, data.get("wormholes", []))

    # Zone 2 state
    z2_state = data.get("zone2_state")
    if z2_state and isinstance(z2_state, dict):
        _restore_zone2_full(view, z2_state)

    # Transition to saved zone if not MAIN
    saved_zone = data.get("zone_id", "MAIN")
    if saved_zone != "MAIN":
        from zones import ZoneID, create_zone
        zid = ZoneID[saved_zone]
        view._zone.teardown(view)
        if zid == ZoneID.ZONE2 and view._zone2 is not None:
            view._zone = view._zone2
        elif zid == ZoneID.ZONE2:
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
        # Restore Zone 2 fog
        if z2_state and hasattr(view._zone, '_fog_grid'):
            z2_fog = z2_state.get("fog_grid")
            if z2_fog is not None:
                view._zone._fog_grid = z2_fog
                view._zone._fog_revealed = sum(
                    cell for row in z2_fog for cell in row)
                view._fog_grid = view._zone._fog_grid
                view._fog_revealed = view._zone._fog_revealed
        elif not z2_state:
            # Legacy save format
            z2_aliens = data.get("zone2_aliens", [])
            if z2_aliens and hasattr(view._zone, '_aliens'):
                _restore_z2_aliens_into(view._zone, z2_aliens)
            if saved_fog is not None and hasattr(view._zone, '_fog_grid'):
                view._fog_grid = saved_fog
                view._fog_revealed = sum(cell for row in saved_fog for cell in row)
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
    import gc
    gv._cleanup()
    gc.collect()
    from game_view import GameView as GV
    view = GV(faction=data.get("faction"), ship_type=data.get("ship_type"))
    restore_state(view, data)
    gv.window.show_view(view)
