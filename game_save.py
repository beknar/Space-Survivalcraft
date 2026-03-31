"""Save/Load/Restore logic extracted from GameView."""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import arcade

from constants import (
    FOG_GRID_W, FOG_GRID_H,
    MODULE_SLOT_COUNT, QUICK_USE_SLOTS,
)

if TYPE_CHECKING:
    from game_view import GameView

_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")


def save_to_dict(gv: GameView, name: str = "") -> dict:
    """Serialize current game state to a dict."""
    from settings import audio
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
        "asteroids": [
            {"x": a.center_x, "y": a.center_y, "hp": a.hp}
            for a in gv.asteroid_list
        ],
        "aliens": [
            {
                "x": al.center_x, "y": al.center_y, "hp": al.hp,
                "vel_x": al.vel_x, "vel_y": al.vel_y,
                "heading": al._heading, "state": al._state,
                "home_x": al._home_x, "home_y": al._home_y,
            }
            for al in gv.alien_list
        ],
        "pickups": [
            {"x": p.center_x, "y": p.center_y, "amount": p.amount}
            for p in gv.iron_pickup_list
        ],
        "buildings": [
            {
                "type": b.building_type, "x": b.center_x, "y": b.center_y,
                "hp": b.hp, "angle": b.angle, "disabled": b.disabled,
            }
            for b in gv.building_list
        ],
        "respawn_timers": {
            "asteroid": gv._asteroid_respawn_timer,
            "alien": gv._alien_respawn_timer,
        },
        "fog_grid": gv._fog_grid,
        "station_inventory": gv._station_inv.to_save_data(),
        "module_slots": gv._module_slots,
        "quick_use": [
            {"type": gv._hud._qu_slots[i], "count": gv._hud._qu_counts[i]}
            for i in range(QUICK_USE_SLOTS)
        ],
        "unlocked_recipes": list(gv._craft_menu._unlocked),
        "credits": gv._trade_menu.credits,
        "trade_station": {
            "x": gv._trade_station.center_x,
            "y": gv._trade_station.center_y,
        } if gv._trade_station is not None else None,
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
    _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
    _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
    alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))
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


def load_game(gv: GameView, slot: int) -> None:
    """Load game state from a numbered save slot and rebuild the view."""
    path = os.path.join(_SAVE_DIR, f"save_slot_{slot + 1:02d}.json")
    if not os.path.exists(path):
        gv._escape_menu._flash_status("No save file found!")
        return
    with open(path, "r") as f:
        data = json.load(f)
    # Stop sounds before rebuilding
    if gv._thruster_player is not None:
        arcade.stop_sound(gv._thruster_player)
        gv._thruster_player = None
    gv._stop_music()
    from game_view import GameView as GV
    view = GV(faction=data.get("faction"), ship_type=data.get("ship_type"))
    restore_state(view, data)
    gv.window.show_view(view)
