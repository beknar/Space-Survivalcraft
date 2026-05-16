"""Zone 2 (Nebula) save/restore codec pair.

Split out of ``game_save.py`` to keep the orchestrator focused on the
public entry points (``save_to_dict`` / ``restore_state`` / ``save_game``
/ ``load_game``) and shared serializers.  The shared helpers
(``_serialize_*``, ``_restore_sprite_list``, ``_regenerate_*``,
``_ensure_alien_textures``, ``_building_reject_fn``) stay in
``game_save`` and are reached through the ``_gs`` alias so test-time
monkey-patches on ``game_save`` thread through.

``game_save`` re-exports the three functions defined below at the
bottom of its module body, so existing test imports
(``from game_save import _save_zone2_state``) keep working.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from constants import DOUBLE_IRON_SCALE
import game_save as _gs

if TYPE_CHECKING:
    from game_view import GameView


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
    # Zone 2 buildings: when the player is currently in Zone 2 the
    # buildings live on ``gv.building_list``; when the player is
    # elsewhere (MAIN, a warp zone, the Star Maze) Zone 2 stashes its
    # buildings into ``_building_stash`` on teardown so they survive
    # across visits.  The save needs to read whichever copy is live
    # for this snapshot — otherwise the player's Nebula base
    # disappears on the next reload.
    z2_buildings: list = []
    z2_trade = None
    if gv._zone.zone_id == ZoneID.ZONE2:
        z2_buildings = [_gs._serialize_building(b) for b in gv.building_list]
        z2_trade = _gs._serialize_trade_station(gv._trade_station)
    else:
        stash = getattr(zone2, "_building_stash", None)
        if stash is not None:
            z2_buildings = [
                _gs._serialize_building(b)
                for b in stash.get("building_list", []) or []
            ]
            z2_trade = _gs._serialize_trade_station(stash.get("_trade_station"))
    return {
        "world_seed": zone2._world_seed,
        "fog_grid": zone2._fog_grid,
        "fog_revealed": zone2._fog_revealed,
        "aliens": [_gs._serialize_z2_alien(al) for al in zone2._aliens],
        "iron_asteroids": [_gs._serialize_asteroid(a) for a in zone2._iron_asteroids],
        "double_iron": [_gs._serialize_asteroid(a) for a in zone2._double_iron],
        "copper_asteroids": [_gs._serialize_asteroid(a) for a in zone2._copper_asteroids],
        "wanderers": [
            {"x": w.center_x, "y": w.center_y, "hp": w.hp, "angle": w.angle,
             "wander_angle": w._wander_angle, "wander_timer": w._wander_timer,
             "repel_timer": w._repel_timer}
            for w in zone2._wanderers
        ],
        "buildings": z2_buildings,
        "trade_station": z2_trade,
        # Post-boss progression — governs whether the four corner
        # wormholes to the Star Maze are visible on re-entry.
        "nebula_boss_defeated": zone2._nebula_boss_defeated,
    }


def _restore_zone2_full(view: GameView, z2_state: dict) -> None:
    """Restore full Zone 2 state from saved data, creating the
    persistent instance."""
    from zones.zone2 import Zone2
    from sprites.asteroid import IronAsteroid
    from sprites.copper_asteroid import CopperAsteroid
    from sprites.wandering_asteroid import WanderingAsteroid
    import zones.zone2 as _z2mod

    zone = Zone2()
    zone._world_seed = z2_state.get("world_seed", zone._world_seed)
    zone._populated = True
    zone._nebula_boss_defeated = bool(
        z2_state.get("nebula_boss_defeated", False))

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

    def _make_iron(ad):
        a = IronAsteroid(iron_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        return a

    def _make_double_iron(ad):
        a = IronAsteroid(iron_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        a.scale = DOUBLE_IRON_SCALE
        return a

    def _make_copper(ad):
        a = CopperAsteroid(copper_tex, ad["x"], ad["y"])
        a.hp = ad["hp"]
        return a

    def _make_wanderer(wd):
        w = WanderingAsteroid(iron_tex, wd["x"], wd["y"],
                              zone.world_width, zone.world_height)
        w.hp = wd.get("hp", w.hp)
        w.angle = wd.get("angle", 0.0)
        w._wander_angle = wd.get("wander_angle", w._wander_angle)
        w._wander_timer = wd.get("wander_timer", w._wander_timer)
        w._repel_timer = wd.get("repel_timer", 0.0)
        return w

    _gs._restore_sprite_list(zone._iron_asteroids,
                             z2_state.get("iron_asteroids", []), _make_iron)
    _gs._restore_sprite_list(zone._double_iron,
                             z2_state.get("double_iron", []), _make_double_iron)
    _gs._restore_sprite_list(zone._copper_asteroids,
                             z2_state.get("copper_asteroids", []), _make_copper)
    _gs._restore_sprite_list(zone._wanderers,
                             z2_state.get("wanderers", []), _make_wanderer)

    # Gas areas (deterministic from seed)
    _gs._regenerate_gas_areas(zone, _z2mod)

    # Alien textures
    zone._alien_laser_tex = view._alien_laser_tex
    _gs._ensure_alien_textures(_z2mod, Z2_ALIEN_SHIP_PNG)
    zone._alien_textures = _z2mod._alien_texture_cache

    # Restore aliens
    _gs._restore_z2_aliens_into(zone, z2_state.get("aliens", []))

    # Read building positions BEFORE regenerating null fields and
    # slipspaces so the regen knows where the player's Nebula base
    # is and can keep the re-spawned stealth patches / teleporters
    # outside the station's exclusion zone.  Without this guard the
    # deterministic seed-based regen would frequently land a null
    # field on top of the base, hiding the player's own buildings
    # behind a stealth patch.  (2026-05-09 user request.)
    z2_buildings_data = z2_state.get("buildings", []) or []
    z2_trade_data = z2_state.get("trade_station")
    z2_building_reject = _gs._building_reject_fn(z2_buildings_data)

    # Regenerate null fields deterministically from the world seed —
    # they aren't persisted in the save (no destructible state) but
    # must exist in the live zone or the whole stealth system breaks.
    _gs._regenerate_null_fields(zone, building_reject=z2_building_reject)
    # Same story for slipspaces — no destructible state, regen from
    # seed so the layout is stable across save/load.
    _gs._regenerate_slipspaces(zone, view, building_reject=z2_building_reject)

    # Buildings + trade station — when the save was made while the
    # player was outside Zone 2, the player's Nebula base is on
    # ``z2_state["buildings"]`` / ``["trade_station"]``.  Reconstruct
    # them and pre-fill ``_building_stash`` so ``Zone2.setup`` picks
    # them up on the player's next visit.  Without this the base
    # silently vanished on slot reload.
    if z2_buildings_data or z2_trade_data:
        from sprites.building import create_building
        building_list = arcade.SpriteList()
        for bd in z2_buildings_data:
            bt = bd["type"]
            tex = view._building_textures[bt]
            laser_tex = view._turret_laser_tex if "Turret" in bt else None
            b = create_building(bt, tex, bd["x"], bd["y"],
                                laser_tex=laser_tex, scale=0.5)
            b.hp = bd.get("hp", b.max_hp)
            b.angle = bd.get("angle", 0.0)
            b.disabled = bd.get("disabled", False)
            if b.disabled:
                b.color = (128, 128, 128, 255)
            building_list.append(b)
        trade_station = None
        if z2_trade_data and isinstance(z2_trade_data, dict):
            trade_station = arcade.Sprite(
                path_or_texture=view._trade_station_tex, scale=0.15)
            trade_station.center_x = z2_trade_data["x"]
            trade_station.center_y = z2_trade_data["y"]
        zone._building_stash = {
            "building_list": building_list,
            "turret_projectile_list": arcade.SpriteList(),
            "_trade_station": trade_station,
            "_parked_ships": arcade.SpriteList(),
        }

    view._zone2 = zone


def _restore_z2_buildings(view: GameView, z2_state: dict) -> None:
    """Restore Zone 2 buildings and trade station after zone setup."""
    from sprites.building import create_building
    z2_buildings = z2_state.get("buildings", [])
    for bd in z2_buildings:
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
    z2_ts = z2_state.get("trade_station")
    if z2_ts and isinstance(z2_ts, dict):
        view._trade_station = arcade.Sprite(
            path_or_texture=view._trade_station_tex, scale=0.15)
        view._trade_station.center_x = z2_ts["x"]
        view._trade_station.center_y = z2_ts["y"]
