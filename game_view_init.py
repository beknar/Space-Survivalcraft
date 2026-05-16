"""GameView constructor helpers split from ``game_view``.

Each ``init_*`` function sets up one cohesive group of state on the
``GameView`` instance.  They mirror the previous ``GameView._init_*``
methods one-to-one; the constructor in ``game_view`` calls them in the
documented order-of-operations sequence.

The split keeps ``game_view.py`` as the thin dispatcher described in
CLAUDE.md (combat / draw / update / save / music / building / input
delegates) — the init phase was the last remaining ~540-line block
of in-class state setup.

The same import surface as ``game_view.py``: each helper reaches into
``gv`` for state, and reuses any class-level methods (``gv._save_game``
etc) at call time, so wiring stays unchanged.
"""
from __future__ import annotations

import gc
import os
from typing import TYPE_CHECKING, Optional

import arcade
import arcade.camera
import pyglet.input

from constants import (
    CONTRAIL_COLOURS,
    BLUEPRINT_PNG, MODULE_TYPES, MODULE_SLOT_COUNT,
    BOSS_MONSTER_PNG, BOSS_FRAME_SIZE, BOSS_SHEET_ROWS,
    REPAIR_PACK_PNG, REPAIR_PACK_CROP, SHIELD_RECHARGE_PNG,
    FOG_GRID_W, FOG_GRID_H,
)
from settings import audio
from sprites.projectile import Weapon
from sprites.explosion import HitSpark, FireSpark
from sprites.player import PlayerShip
from sprites.contrail import ContrailParticle
from sprites.building import BasicCrafter, StationModule  # noqa: F401
from sprites.boss import BossAlienShip
from sprites.wormhole import Wormhole
from inventory import Inventory
from hud import HUD
from escape_menu import EscapeMenu
from death_screen import DeathScreen
from build_menu import BuildMenu
from world_setup import (
    load_bg_texture, load_shield, load_weapons,
    load_explosion_assets, load_bump_sound, load_thruster_sound,
    load_iron_texture, populate_asteroids, populate_aliens,
    collect_music_tracks,
    load_building_textures, load_turret_laser,
)
from station_info import StationInfo
from ship_stats import ShipStats
from map_overlay import MapOverlay
from station_inventory import StationInventory
from craft_menu import CraftMenu
from trade_menu import TradeMenu
from video_player import VideoPlayer
from game_save import _SAVE_DIR

if TYPE_CHECKING:
    from game_view import GameView


# Cache the generated red-dot blueprint variants so a save / load
# round-trip doesn't re-decode + re-paste the dot every time the
# GameView is rebuilt.  Keyed by source icon path.
_BP_DOT_VARIANT_CACHE: dict[str, arcade.Texture] = {}


def _make_blueprint_red_dot_variant(icon_path: str) -> arcade.Texture:
    """Return an ``arcade.Texture`` of the icon at ``icon_path`` with
    a small red dot stamped in the upper-right corner — used to mark
    the BLUEPRINT version of an item visually distinct from the
    already-owned consumable / module icon.
    """
    cached = _BP_DOT_VARIANT_CACHE.get(icon_path)
    if cached is not None:
        return cached
    from PIL import Image as _PILImage, ImageDraw as _PILDraw
    src = _PILImage.open(icon_path).convert("RGBA").copy()
    w, h = src.size
    dot_d = max(8, min(48, int(min(w, h) * 0.22)))
    pad = max(2, dot_d // 4)
    x0 = w - dot_d - pad
    y0 = pad
    draw = _PILDraw.Draw(src)
    draw.ellipse((x0, y0, x0 + dot_d, y0 + dot_d),
                 fill=(230, 40, 40, 255),
                 outline=(120, 0, 0, 255),
                 width=max(1, dot_d // 12))
    tex = arcade.Texture(src)
    _BP_DOT_VARIANT_CACHE[icon_path] = tex
    return tex


def init_player_and_camera(gv: GameView, faction: Optional[str]) -> None:
    """Player ship, shield, projectiles, background, cameras, shake."""
    from character_data import level_for_xp  # noqa: F401
    gv._char_xp = 0
    gv._char_level = 1

    gv.player = PlayerShip(faction=faction, ship_type=gv._ship_type,
                           ship_level=gv._ship_level)
    gv.player_list = arcade.SpriteList()
    gv.player_list.append(gv.player)

    gv.shield_sprite, gv.shield_list = load_shield(
        gv.player.center_x, gv.player.center_y,
        faction=faction,
    )

    gv.projectile_list = arcade.SpriteList()
    gv.bg_texture = load_bg_texture()
    gv.world_cam = arcade.camera.Camera2D()
    gv.ui_cam = arcade.camera.Camera2D()

    gv._shake_timer = 0.0
    gv._shake_amp = 0.0


def init_abilities_and_effects(gv: GameView) -> None:
    """Special ability meter, missile state, force walls, death blossom,
    consumable use-glow, ship level, rear turret cooldown."""
    gv._use_glow = (0, 0, 0, 0)
    gv._use_glow_timer = 0.0

    from constants import ABILITY_METER_MAX, SHIP_LEVEL_ABILITY_BONUS
    base_ability = ABILITY_METER_MAX + (gv._ship_level - 1) * SHIP_LEVEL_ABILITY_BONUS
    gv._ability_meter = base_ability
    gv._ability_meter_max = base_ability
    gv._misty_step_cd = 0.0
    gv._force_wall_cd = 0.0
    gv._force_walls = []

    gv._death_blossom_active = False
    gv._death_blossom_timer = 0.0
    gv._death_blossom_missiles_left = 0

    gv._missile_list = arcade.SpriteList()
    gv._missile_tex = None
    gv._rear_turret_cd = 0.0
    # Persistent energy-blade sprite — visible whenever the melee
    # weapon is the active weapon, hidden / despawned when the player
    # tabs back to a laser.
    gv._melee_swings = arcade.SpriteList()
    gv._active_blade = None
    # Energy Pickaxe — separate slot from the lightsabre so the
    # bolt-deflect path (which keys off ``_active_blade``) does not
    # fire when the pickaxe is the active weapon.
    gv._active_pickaxe = None

    # Companion drone — at most one active at a time.
    gv._drone_list = arcade.SpriteList()
    gv._active_drone = None
    gv._hover_drone = None
    gv._t_drone_tip = arcade.Text(
        "", 0, 0, arcade.color.WHITE, 9, bold=True,
        anchor_x="center", anchor_y="bottom",
    )


def init_text_overlays(gv: GameView) -> None:
    """Cached arcade.Text objects for flash messages and boss announce."""
    gv._flash_msg = ""
    gv._flash_timer = 0.0
    gv._t_flash = arcade.Text("", 0, 0, (255, 100, 100), 12, bold=True,
                              anchor_x="center", anchor_y="center")

    gv._boss_announce_timer = 0.0
    gv._t_boss_announce = arcade.Text(
        "", 0, 0, (255, 60, 60), 36, bold=True,
        anchor_x="center", anchor_y="center")
    gv._t_boss_subtitle = arcade.Text(
        "", 0, 0, (255, 180, 180), 16, bold=True,
        anchor_x="center", anchor_y="center")


def init_input_devices(gv: GameView) -> None:
    """Held-key set + first available gamepad (resilient to reuse)."""
    gv._keys = set()
    gv.joystick = None
    gv._prev_rb = False
    gv._prev_y = False
    controllers = pyglet.input.get_controllers()
    if controllers:
        gv.joystick = controllers[0]
        try:
            gv.joystick.open()
        except pyglet.input.DeviceOpenException:
            pass  # already open from a previous View
        print(f"Gamepad connected: {gv.joystick.name}")


def init_weapons_and_audio(gv: GameView) -> None:
    """Player weapons + all sound effects."""
    gv._weapons = load_weapons(gv.player.guns, faction=gv._faction)
    gv._weapon_idx = 0
    gv._apply_character_weapon_bonuses()

    gv._explosion_frames, gv._explosion_snd = load_explosion_assets()
    # Asteroid-specific explosion uses a separate 10-frame sequence.
    from world_setup import load_asteroid_explosion_frames
    gv._asteroid_explosion_frames = load_asteroid_explosion_frames()
    gv._bump_snd = load_bump_sound()

    from constants import (
        SFX_INTERFACE_DIR, SFX_MISSILE_LAUNCH, SFX_MISSILE_IMPACT,
        SFX_MISTY_STEP, SFX_FORCE_WALL,
    )
    gv._victory_snd = arcade.load_sound(
        os.path.join(SFX_INTERFACE_DIR,
                     "Game Futuristic Item Collection 1.wav"))
    gv._missile_launch_snd = arcade.load_sound(SFX_MISSILE_LAUNCH)
    gv._missile_impact_snd = arcade.load_sound(SFX_MISSILE_IMPACT)
    gv._misty_step_snd = arcade.load_sound(SFX_MISTY_STEP)
    gv._force_wall_snd = arcade.load_sound(SFX_FORCE_WALL)
    from constants import SFX_ALIEN_LASER
    gv._alien_laser_snd = arcade.load_sound(SFX_ALIEN_LASER)
    gv._alien_laser_snd_cd = 0.0

    gv._iron_tex = load_iron_texture()

    from world_setup import load_slipspace_assets
    gv._slipspace_tex, gv._slipspace_snd = load_slipspace_assets()


def init_world_entities(gv: GameView) -> None:
    """Asteroids, pickup lists, and explosion list."""
    from constants import WORLD_WIDTH, WORLD_HEIGHT
    gv.asteroid_list = populate_asteroids()
    gv.explosion_list = arcade.SpriteList()
    gv.iron_pickup_list = arcade.SpriteList()
    gv.blueprint_pickup_list = arcade.SpriteList()
    from world_setup import populate_null_fields, populate_slipspaces
    gv._null_fields = populate_null_fields(WORLD_WIDTH, WORLD_HEIGHT)
    gv._slipspaces = populate_slipspaces(
        WORLD_WIDTH, WORLD_HEIGHT, gv._slipspace_tex)
    gv._inside_slipspace = None
    init_blueprint_textures(gv)
    init_module_slots(gv)
    init_aliens(gv)


def init_blueprint_textures(gv: GameView) -> None:
    """Load and tint the blueprint textures (one per module type).

    Also exposes ``_blueprint_drop_tex[key]`` — the module-icon texture
    used for the spinning world drop sprite.
    """
    from PIL import Image as PILImage
    gv._blueprint_tex = arcade.load_texture(BLUEPRINT_PNG)
    gv._blueprint_drop_tex = {}
    _bp_colors = {
        "armor_plate":     (80, 130, 255),
        "engine_booster":  (255, 80, 80),
        "shield_booster":  (180, 80, 255),
        "shield_enhancer": (40, 60, 180),
        "damage_absorber": (255, 140, 200),
        "broadside":       (200, 100, 255),
    }
    _bp_pil = PILImage.open(BLUEPRINT_PNG).convert("RGBA")
    gv._blueprint_tinted = {}
    for key, (tr, tg, tb) in _bp_colors.items():
        tinted = _bp_pil.copy()
        pixels = tinted.load()
        for py_ in range(tinted.height):
            for px_ in range(tinted.width):
                r, g, b, a = pixels[px_, py_]
                if a > 0:
                    gray = (r + g + b) // 3
                    pixels[px_, py_] = (
                        min(255, gray * tr // 255),
                        min(255, gray * tg // 255),
                        min(255, gray * tb // 255),
                        a,
                    )
        gv._blueprint_tinted[key] = arcade.Texture(tinted)
    _bp_pil.close()


def init_module_slots(gv: GameView) -> None:
    """Module equipment slots and broadside laser texture."""
    from constants import SHIP_LEVEL_MODULE_BONUS, LASER_DIR
    slot_count = MODULE_SLOT_COUNT + (gv._ship_level - 1) * SHIP_LEVEL_MODULE_BONUS
    gv._module_slots = [None] * slot_count
    gv._broadside_cd = 0.0
    gv._enhancer_angle = 0.0
    gv._broadside_tex = arcade.load_texture(
        os.path.join(LASER_DIR, "laserBlue03.png"))


def init_aliens(gv: GameView) -> None:
    """Alien ships, laser textures, and projectile/spark lists."""
    gv.alien_list, gv._alien_ship_tex, gv._alien_laser_tex = populate_aliens()
    gv._asteroid_tex = arcade.load_texture(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "assets", "Pixel Art Space", "Asteroid.png"))
    gv.alien_projectile_list = arcade.SpriteList()
    gv.hit_sparks = []
    gv.fire_sparks = []


def init_boss_and_wormholes(gv: GameView) -> None:
    """Boss sprite/state placeholders and wormhole sprite list."""
    import random
    gv._boss = None
    gv._boss_spawned = False
    gv._boss_defeated = False
    gv._boss_list = arcade.SpriteList()
    gv._boss_projectile_list = arcade.SpriteList()

    from PIL import Image as PILImage
    _pil_boss = PILImage.open(BOSS_MONSTER_PNG).convert("RGBA")
    boss_row = random.randint(0, BOSS_SHEET_ROWS - 1)
    _boss_frame = _pil_boss.crop((
        0, boss_row * BOSS_FRAME_SIZE,
        BOSS_FRAME_SIZE, (boss_row + 1) * BOSS_FRAME_SIZE,
    ))
    _boss_frame = _boss_frame.rotate(90, expand=True)
    gv._boss_tex = arcade.Texture(_boss_frame)
    gv._boss_laser_tex = gv._alien_laser_tex
    _pil_boss.close()

    gv._wormholes = []
    gv._wormhole_list = arcade.SpriteList()


def init_consumable_textures(gv: GameView) -> None:
    """Repair pack, shield recharge, copper pickup, missile textures."""
    from PIL import Image as PILImage
    _pil_items = PILImage.open(REPAIR_PACK_PNG).convert("RGBA")
    x0, y0, x1, y1 = REPAIR_PACK_CROP
    gv._repair_pack_tex = arcade.Texture(_pil_items.crop((x0, y0, x1, y1)))
    _pil_items.close()

    gv._shield_recharge_tex = arcade.load_texture(SHIELD_RECHARGE_PNG)

    from constants import COPPER_PICKUP_PNG, MISSILE_PNG
    gv._copper_tex = arcade.load_texture(COPPER_PICKUP_PNG)
    gv._missile_tex = arcade.load_texture(MISSILE_PNG)


def init_inventories(gv: GameView) -> None:
    """Cargo inventory + module/blueprint icon registration."""
    gv.inventory = Inventory(
        iron_icon=gv._iron_tex,
        repair_pack_icon=gv._repair_pack_tex,
        shield_recharge_icon=gv._shield_recharge_tex,
    )
    # Drone blueprints get a red dot in the upper-right corner so the
    # BP version is visually distinguishable from the placed consumable.
    _DOT_KEYS = {"mining_drone", "combat_drone"}
    for key, info in MODULE_TYPES.items():
        mod_icon = arcade.load_texture(info["icon"])
        gv.inventory.item_icons[f"mod_{key}"] = mod_icon
        if key in _DOT_KEYS:
            bp_icon = _make_blueprint_red_dot_variant(info["icon"])
        else:
            bp_icon = mod_icon
        gv.inventory.item_icons[f"bp_{key}"] = bp_icon
        gv.inventory._item_names[f"bp_{key}"] = f"BP {info['label']}"
        gv.inventory._item_names[f"mod_{key}"] = info["label"]
        gv._blueprint_drop_tex[key] = bp_icon
    gv.inventory.item_icons["copper"] = gv._copper_tex
    gv.inventory.item_icons["missile"] = gv._missile_tex
    # Drone consumables — same drone-ship icon as the ``mod_<key>`` cell.
    for _drone_key in ("mining_drone", "combat_drone"):
        _drone_icon = gv.inventory.item_icons[f"mod_{_drone_key}"]
        gv.inventory.item_icons[_drone_key] = _drone_icon
        gv.inventory._item_names[_drone_key] = (
            MODULE_TYPES[_drone_key]["label"])


def init_buildings_and_overlays(gv: GameView) -> None:
    """Building list, build menu, ghost preview state, station info /
    ship stats / station inv / craft / trade overlays, hover state."""
    gv.building_list = arcade.SpriteList(use_spatial_hash=True)
    gv.turret_projectile_list = arcade.SpriteList()
    gv._building_textures = load_building_textures()
    gv._turret_laser_tex, gv._turret_laser_snd = load_turret_laser()
    gv._build_menu = BuildMenu()
    gv._build_menu.set_textures(gv._building_textures)
    gv._placing_building = None
    gv._ghost_sprite = None
    gv._ghost_list = None
    gv._ghost_rotation = 0.0
    gv._destroy_mode = False
    gv._destroy_cursor_x = 0.0
    gv._destroy_cursor_y = 0.0
    gv._move_candidate = None
    gv._move_press_time = 0.0
    gv._moving_building = None
    gv._move_origin_x = 0.0
    gv._move_origin_y = 0.0
    gv._repair_acc = 0.0
    gv._building_repair_acc = 0.0
    gv._hover_building = None
    gv._hover_screen_x = 0.0
    gv._hover_screen_y = 0.0
    gv._parked_ships = arcade.SpriteList()
    gv._hover_parked_ship = None
    gv._t_parked_ship_tip = arcade.Text(
        "", 0, 0, arcade.color.WHITE, 9, bold=True,
        anchor_x="center", anchor_y="bottom",
    )
    gv._t_building_tip = arcade.Text(
        "", 0, 0, arcade.color.WHITE, 10, bold=True,
        anchor_x="center", anchor_y="bottom",
    )

    gv._station_info = StationInfo()
    gv._ship_stats = ShipStats()
    gv._map_overlay = MapOverlay()

    gv._station_inv = StationInventory(
        iron_icon=gv._iron_tex,
        repair_pack_icon=gv._repair_pack_tex,
        shield_recharge_icon=gv._shield_recharge_tex,
    )
    for key, info in MODULE_TYPES.items():
        mod_icon = arcade.load_texture(info["icon"])
        gv._station_inv.item_icons[f"mod_{key}"] = mod_icon
        gv._station_inv.item_icons[f"bp_{key}"] = mod_icon
    gv._station_inv.item_icons["copper"] = gv._copper_tex
    gv._station_inv.item_icons["missile"] = gv._missile_tex
    for _drone_key in ("mining_drone", "combat_drone"):
        _drone_icon = gv._station_inv.item_icons[f"mod_{_drone_key}"]
        gv._station_inv.item_icons[_drone_key] = _drone_icon
        _bp_dotted = gv.inventory.item_icons.get(f"bp_{_drone_key}")
        if _bp_dotted is not None:
            gv._station_inv.item_icons[f"bp_{_drone_key}"] = _bp_dotted

    gv._craft_menu = CraftMenu()
    gv._craft_menu.repair_pack_icon = gv._repair_pack_tex
    gv._craft_menu.shield_recharge_icon = gv._shield_recharge_tex
    for key, info in MODULE_TYPES.items():
        gv._craft_menu.item_icons[key] = arcade.load_texture(info["icon"])
    gv._active_crafter = None

    gv._trade_menu = TradeMenu()
    gv._trade_station = None
    gv._trade_station_tex = arcade.load_texture(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "assets", "ai generated", "space station.PNG"))

    # Fleet Control overlay
    from fleet_menu import FleetMenu
    gv._fleet_menu = FleetMenu()

    # Quantum Wave Integrator click-menu overlay + Nebula boss state.
    from qwi_menu import QWIMenu
    gv._qwi_menu = QWIMenu()
    gv._active_qwi = None
    gv._nebula_boss = None
    gv._nebula_boss_list = arcade.SpriteList()
    gv._nebula_gas_clouds = []

    # Station shield — spawned by the first Shield Generator built.
    from constants import STATION_SHIELD_HP
    gv._station_shield_sprite = None
    gv._station_shield_list = None
    gv._station_shield_hp = 0
    gv._station_shield_max_hp = STATION_SHIELD_HP
    gv._station_shield_radius = 0.0

    # Double Star Refugee NPC (unlocked by Shield Generator in Zone 2)
    from dialogue_overlay import DialogueOverlay
    gv._refugee_npc = None
    gv._refugee_spawned = False
    gv._hover_refugee = False
    gv._met_refugee = False
    gv._quest_flags = {}
    gv._dialogue = DialogueOverlay()
    gv._t_refugee_tip = arcade.Text(
        "", 0, 0, arcade.color.WHITE, 10, bold=True,
        anchor_x="center", anchor_y="bottom",
    )


def init_world_state(gv: GameView) -> None:
    """Respawn timers, fog of war grid, GC management."""
    gv._asteroid_respawn_timer = 0.0
    gv._alien_respawn_timer = 0.0

    gv._fog_grid = [[False] * FOG_GRID_W for _ in range(FOG_GRID_H)]
    gv._fog_revealed = 0

    from zones import ZoneID  # noqa: F401
    gv._last_station_pos = None
    gv._last_station_zone = None

    gc.disable()
    gv._gc_ran = False


def init_hud(gv: GameView) -> None:
    """HUD panel with module icons and thruster/contrail state."""
    gv._hud = HUD(
        has_gamepad=gv.joystick is not None,
        faction=gv._faction,
        ship_type=gv._ship_type,
        repair_pack_icon=gv._repair_pack_tex,
        shield_recharge_icon=gv._shield_recharge_tex,
    )
    if audio.show_fps:
        gv._hud._show_fps = True
    for key, info in MODULE_TYPES.items():
        gv._hud._mod_icons[key] = arcade.load_texture(info["icon"])
    gv._hud._missile_icon = gv._missile_tex

    gv._thruster_snd = load_thruster_sound()
    gv._thruster_player = None
    gv._thrusting_last = False

    gv._contrail = []
    gv._contrail_timer = 0.0
    st = gv._ship_type or "Cruiser"
    colours = CONTRAIL_COLOURS.get(st, CONTRAIL_COLOURS["Cruiser"])
    gv._contrail_start_colour = colours[0]
    gv._contrail_end_colour = colours[1]


def init_video_and_menus(gv: GameView) -> None:
    """Video players, escape menu, death screen, and background music."""
    gv._video_player = VideoPlayer(convert_fps=12.0)
    # Character video — slow ambient loop, fine at 4 FPS.
    gv._char_video_player = VideoPlayer(convert_fps=8.0)
    gv._char_video_player._small_w = 160
    gv._char_video_player._small_h = 160
    gv._char_video_player._convert_cooldown = 0.06
    gv._start_character_video()

    gv._escape_menu = EscapeMenu(
        save_fn=gv._save_game,
        load_fn=gv._load_game,
        main_menu_fn=gv._return_to_menu,
        save_dir=_SAVE_DIR,
        resolution_fn=gv._change_resolution,
        video_play_fn=gv._play_video,
        video_stop_fn=gv._stop_video,
        stop_song_fn=gv._stop_song,
        other_song_fn=gv._other_song,
        character_select_fn=gv._select_character,
    )

    gv._death_screen = DeathScreen()
    gv._player_dead = False

    gv._music_tracks = collect_music_tracks()
    gv._music_idx = 0
    gv._music_player = None
    gv._current_track_name = ""
    if gv._music_tracks and not gv._skip_music and audio.autoplay_ost:
        gv._play_next_track()


def init_zones(gv: GameView) -> None:
    """Zone state machine — main zone created up front, Zone 2 and
    Star Maze lazily on first visit so their state survives
    round-trips through warp zones."""
    from zones.zone1_main import MainZone
    gv._main_zone = MainZone()
    gv._zone2 = None
    gv._star_maze = None
    gv._zone = gv._main_zone
    gv._zone.setup(gv)
