"""Star Maze save/restore codec pair.

Split out of ``game_save.py`` alongside the Zone 2 split (see
``game_save_zone2.py``).  Same alias pattern: reach shared serializers
through ``_gs`` so test-time monkey-patches on ``game_save`` thread
through.

``game_save`` re-exports the two functions defined below at the
bottom of its module body, so existing test imports
(``from game_save import _save_star_maze_state``) keep working.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

import game_save as _gs

if TYPE_CHECKING:
    from game_view import GameView


def _save_star_maze_state(gv: GameView) -> dict | None:
    """Serialize Star Maze state if the player has visited it.

    Persists the world seed (so the room layout + wall doors
    regenerate identically), the populated flag (so re-entering
    after a warp-zone round trip doesn't wipe spawner progress),
    each spawner's full state, AND the player's maze base
    (buildings + trade station).  Maze aliens are not persisted —
    they respawn naturally from the spawners when the player
    returns, and the spawner's spawn-cooldown timer is saved so
    the cadence doesn't reset.

    Buildings live on ``gv.building_list`` while the player is in
    the Star Maze and on ``zone._building_stash`` once they've
    left; the save reads whichever copy is current so the maze
    base doesn't disappear on slot reload.
    """
    from zones import ZoneID
    zone = None
    if gv._zone.zone_id == ZoneID.STAR_MAZE:
        zone = gv._zone
    elif getattr(gv, "_star_maze", None) is not None:
        zone = gv._star_maze
    if zone is None or not zone._populated:
        return None
    sm_buildings: list = []
    sm_trade = None
    if gv._zone.zone_id == ZoneID.STAR_MAZE:
        sm_buildings = [_gs._serialize_building(b) for b in gv.building_list]
        sm_trade = _gs._serialize_trade_station(gv._trade_station)
    else:
        stash = getattr(zone, "_building_stash", None)
        if stash is not None:
            sm_buildings = [
                _gs._serialize_building(b)
                for b in stash.get("building_list", []) or []
            ]
            sm_trade = _gs._serialize_trade_station(stash.get("_trade_station"))
    return {
        "world_seed": zone._world_seed,
        "populated": zone._populated,
        "spawners": [sp.to_save_data() for sp in zone._spawners],
        "fog_grid": zone._fog_grid,
        "fog_revealed": zone._fog_revealed,
        "buildings": sm_buildings,
        "trade_station": sm_trade,
        "nebula_boss_defeated": getattr(
            zone, "_nebula_boss_defeated", False),
    }


def _restore_star_maze_full(view: GameView, state: dict) -> None:
    """Reconstruct the persistent Star Maze instance from save data."""
    from zones import ZoneID, create_zone
    zone = create_zone(ZoneID.STAR_MAZE)
    zone._world_seed = state.get("world_seed", zone._world_seed)
    zone._nebula_boss_defeated = bool(
        state.get("nebula_boss_defeated", False))
    populated = bool(state.get("populated", False))
    if populated:
        # Regenerate rooms + walls + spawners deterministically from
        # the saved seed, then overwrite per-spawner HP / killed /
        # timer from the save.  _generate calls populate_aliens which
        # reads zone._alien_textures, so textures must be loaded first.
        zone._load_textures(view)
        zone._generate(view)
        zone._populated = True
        spawner_data = state.get("spawners", [])
        for sp, sd in zip(zone._spawners, spawner_data):
            sp.from_save_data(sd)
    # Fog state.  Guard against old saves whose grid was sized for a
    # different STAR_MAZE_WIDTH/HEIGHT or FOG_CELL_SIZE — if the
    # dimensions don't match, drop the saved grid and start fresh.
    fog = state.get("fog_grid")
    if (fog is not None and len(fog) == zone._fog_h
            and all(len(row) == zone._fog_w for row in fog)):
        zone._fog_grid = fog
        zone._fog_revealed = state.get("fog_revealed", 0)
    # Buildings + trade station — pre-fill ``_building_stash`` so
    # ``StarMazeZone.setup`` picks them up on the player's next visit.
    # Without this the player's maze base silently vanished on slot
    # reload (mirrors the Zone 2 fix).
    sm_buildings_data = state.get("buildings", []) or []
    sm_trade_data = state.get("trade_station")
    if sm_buildings_data or sm_trade_data:
        from sprites.building import create_building
        building_list = arcade.SpriteList()
        for bd in sm_buildings_data:
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
        if sm_trade_data and isinstance(sm_trade_data, dict):
            trade_station = arcade.Sprite(
                path_or_texture=view._trade_station_tex, scale=0.15)
            trade_station.center_x = sm_trade_data["x"]
            trade_station.center_y = sm_trade_data["y"]
        zone._building_stash = {
            "building_list": building_list,
            "turret_projectile_list": arcade.SpriteList(),
            "_trade_station": trade_station,
            "_parked_ships": arcade.SpriteList(),
        }
    view._star_maze = zone
