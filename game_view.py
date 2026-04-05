"""GameView -- core gameplay view for Space Survivalcraft."""
from __future__ import annotations

import gc
import math
import os
import random
from typing import Optional

import arcade
import arcade.camera
import pyglet.input

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT, STATUS_WIDTH,
    WORLD_WIDTH, WORLD_HEIGHT, BG_TILE,
    DEAD_ZONE,
    SHIP_RADIUS, ASTEROID_IRON_YIELD,
    ASTEROID_COUNT, ASTEROID_MIN_DIST,
    ALIEN_COUNT, ALIEN_MIN_DIST,
    RESPAWN_INTERVAL, RESPAWN_EXCLUSION_RADIUS,
    SHAKE_DURATION, SHAKE_AMPLITUDE,
    EJECT_DIST, WORLD_ITEM_LIFETIME,
    CONTRAIL_MAX_PARTICLES, CONTRAIL_SPAWN_RATE, CONTRAIL_LIFETIME,
    CONTRAIL_START_SIZE, CONTRAIL_END_SIZE, CONTRAIL_OFFSET, CONTRAIL_COLOURS,
    BUILDING_TYPES, DOCK_SNAP_DIST, TURRET_FREE_PLACE_RADIUS,
    BUILDING_RADIUS, STATION_INFO_RANGE,
    REPAIR_RANGE, REPAIR_RATE, REPAIR_SHIELD_BOOST,
    FOG_REVEAL_RADIUS, FOG_CELL_SIZE, FOG_GRID_W, FOG_GRID_H,
    CRAFT_TIME, CRAFT_IRON_COST, CRAFT_RESULT_COUNT, REPAIR_PACK_HEAL,
    REPAIR_PACK_PNG, REPAIR_PACK_CROP, SHIELD_RECHARGE_PNG, QUICK_USE_SLOTS,
    MINIMAP_Y, MINIMAP_H, SHIELD_SCALE,
    BLUEPRINT_PNG, MODULE_TYPES, MODULE_SLOT_COUNT,
    BROADSIDE_COOLDOWN, BROADSIDE_DAMAGE, BROADSIDE_SPEED, BROADSIDE_RANGE,
    BOSS_MONSTER_PNG, BOSS_FRAME_SIZE, BOSS_SHEET_COLS, BOSS_SHEET_ROWS,
    BOSS_RADIUS, BOSS_COLLISION_DAMAGE, BOSS_COLLISION_COOLDOWN,
    BOSS_BOUNCE, BOSS_CHARGE_DAMAGE, BOSS_XP_REWARD, BOSS_IRON_DROP,
)
from settings import audio
from sprites.projectile import Weapon
from sprites.explosion import Explosion, HitSpark, FireSpark
from sprites.pickup import IronPickup, BlueprintPickup
from sprites.player import PlayerShip
from sprites.contrail import ContrailParticle
from sprites.building import (
    StationModule, HomeStation, Turret, RepairModule, BasicCrafter,
    create_building, compute_module_capacity, compute_modules_used,
    DockingPort,
)
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
from station_inventory import StationInventory
from craft_menu import CraftMenu
from trade_menu import TradeMenu
from video_player import VideoPlayer
from game_save import _SAVE_DIR

# Extracted modules
import combat_helpers as _ch
import building_manager as _bm
import draw_logic as _dl
import update_logic as _ul
import input_handlers as _ih


class GameView(arcade.View):

    def __init__(
        self,
        faction: Optional[str] = None,
        ship_type: Optional[str] = None,
        skip_music: bool = False,
    ) -> None:
        super().__init__()
        self._skip_music = skip_music

        self._faction = faction
        self._ship_type = ship_type

        # Character progression
        from character_data import level_for_xp
        self._char_xp: int = 0
        self._char_level: int = 1

        # Player
        self.player = PlayerShip(faction=faction, ship_type=ship_type)
        self.player_list = arcade.SpriteList()
        self.player_list.append(self.player)

        # Shield
        self.shield_sprite, self.shield_list = load_shield(
            self.player.center_x, self.player.center_y,
            faction=faction,
        )

        # Active projectiles
        self.projectile_list = arcade.SpriteList()

        # Tiled background texture
        self.bg_texture = load_bg_texture()

        # World camera (follows player)
        self.world_cam = arcade.camera.Camera2D()
        # UI camera (static)
        self.ui_cam = arcade.camera.Camera2D()

        # Camera shake state
        self._shake_timer: float = 0.0
        self._shake_amp: float = 0.0

        # Consumable use glow effect (colour + timer)
        self._use_glow: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._use_glow_timer: float = 0.0

        # Special ability meter
        from constants import ABILITY_METER_MAX
        self._ability_meter: float = ABILITY_METER_MAX
        self._ability_meter_max: float = ABILITY_METER_MAX

        # Misty step cooldown
        self._misty_step_cd: float = 0.0

        # Force walls
        self._force_walls: list = []

        # Death blossom state
        self._death_blossom_active: bool = False
        self._death_blossom_timer: float = 0.0
        self._death_blossom_missiles_left: int = 0

        # Missile list
        self._missile_list: arcade.SpriteList = arcade.SpriteList()
        self._missile_tex: arcade.Texture | None = None

        # Rear turret cooldown
        self._rear_turret_cd: float = 0.0

        # Ship level (increases with Advanced Ship building)
        self._ship_level: int = 1

        # Flash message (centered on play area)
        self._flash_msg: str = ""
        self._flash_timer: float = 0.0
        self._t_flash = arcade.Text("", 0, 0, (255, 100, 100), 12, bold=True,
                                    anchor_x="center", anchor_y="center")

        # Boss announcement (large dramatic text)
        self._boss_announce_timer: float = 0.0
        self._t_boss_announce = arcade.Text(
            "", 0, 0, (255, 60, 60), 36, bold=True,
            anchor_x="center", anchor_y="center")
        self._t_boss_subtitle = arcade.Text(
            "", 0, 0, (255, 180, 180), 16, bold=True,
            anchor_x="center", anchor_y="center")

        # Held-key tracking
        self._keys: set[int] = set()

        # Gamepad
        self.joystick = None
        self._prev_rb: bool = False
        self._prev_y: bool = False
        controllers = pyglet.input.get_controllers()
        if controllers:
            self.joystick = controllers[0]
            try:
                self.joystick.open()
            except pyglet.input.DeviceOpenException:
                pass  # already open from a previous View
            print(f"Gamepad connected: {self.joystick.name}")

        # Weapons
        self._weapons: list[Weapon] = load_weapons(self.player.guns)
        self._weapon_idx: int = 0
        self._apply_character_weapon_bonuses()

        # Explosion assets
        self._explosion_frames, self._explosion_snd = load_explosion_assets()

        # Collision bump sound
        self._bump_snd = load_bump_sound()
        # Victory sound (for boss kill)
        from constants import SFX_INTERFACE_DIR, SFX_MISSILE_LAUNCH, SFX_MISSILE_IMPACT, SFX_MISTY_STEP, SFX_FORCE_WALL
        self._victory_snd = arcade.load_sound(
            os.path.join(SFX_INTERFACE_DIR,
                         "Game Futuristic Item Collection 1.wav"))
        self._missile_launch_snd = arcade.load_sound(SFX_MISSILE_LAUNCH)
        self._missile_impact_snd = arcade.load_sound(SFX_MISSILE_IMPACT)
        self._misty_step_snd = arcade.load_sound(SFX_MISTY_STEP)
        self._force_wall_snd = arcade.load_sound(SFX_FORCE_WALL)

        # Iron texture
        self._iron_tex = load_iron_texture()

        # Asteroids
        self.asteroid_list = populate_asteroids()
        self.explosion_list = arcade.SpriteList()
        self.iron_pickup_list = arcade.SpriteList()
        self.blueprint_pickup_list = arcade.SpriteList()
        self._blueprint_tex = arcade.load_texture(BLUEPRINT_PNG)
        # Tinted blueprint textures per module type
        from PIL import Image as PILImage, ImageEnhance as _IE
        _bp_colors = {
            "armor_plate":     (80, 130, 255),
            "engine_booster":  (255, 80, 80),
            "shield_booster":  (180, 80, 255),
            "shield_enhancer": (40, 60, 180),
            "damage_absorber": (255, 140, 200),
            "broadside":       (200, 100, 255),
        }
        _bp_pil = PILImage.open(BLUEPRINT_PNG).convert("RGBA")
        self._blueprint_tinted: dict[str, arcade.Texture] = {}
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
            self._blueprint_tinted[key] = arcade.Texture(tinted)
        _bp_pil.close()

        # Module slots
        self._module_slots: list[str | None] = [None] * MODULE_SLOT_COUNT
        self._broadside_cd: float = 0.0
        self._enhancer_angle: float = 0.0
        from constants import LASER_DIR
        self._broadside_tex = arcade.load_texture(
            os.path.join(LASER_DIR, "laserBlue03.png"))

        # Alien ships
        self.alien_list, _alien_laser_tex = populate_aliens()
        self._asteroid_tex = arcade.load_texture(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "Pixel Art Space", "Asteroid.png"))
        from PIL import Image as PILImage
        from constants import ALIEN_SHIP_PNG, ALIEN_FX_PNG
        _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
        self._alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))
        _pil_ship.close()
        _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
        _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
        self._alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))
        _pil_fx.close()
        self.alien_projectile_list: arcade.SpriteList = arcade.SpriteList()
        self.hit_sparks: list[HitSpark] = []
        self.fire_sparks: list[FireSpark] = []

        # Boss encounter state
        self._boss: Optional[BossAlienShip] = None
        self._boss_spawned: bool = False
        self._boss_defeated: bool = False
        self._boss_list: arcade.SpriteList = arcade.SpriteList()
        self._boss_projectile_list: arcade.SpriteList = arcade.SpriteList()
        from PIL import Image as PILImage
        _pil_boss = PILImage.open(BOSS_MONSTER_PNG).convert("RGBA")
        boss_row = random.randint(0, BOSS_SHEET_ROWS - 1)
        _boss_frame = _pil_boss.crop((
            0, boss_row * BOSS_FRAME_SIZE,
            BOSS_FRAME_SIZE, (boss_row + 1) * BOSS_FRAME_SIZE,
        ))
        _boss_frame = _boss_frame.rotate(90, expand=True)
        self._boss_tex = arcade.Texture(_boss_frame)
        self._boss_laser_tex = self._alien_laser_tex
        _pil_boss.close()

        # Wormholes (spawned when boss is defeated)
        self._wormholes: list[Wormhole] = []
        self._wormhole_list: arcade.SpriteList = arcade.SpriteList()

        # Repair pack texture
        from PIL import Image as PILImage
        _pil_items = PILImage.open(REPAIR_PACK_PNG).convert("RGBA")
        x0, y0, x1, y1 = REPAIR_PACK_CROP
        self._repair_pack_tex = arcade.Texture(
            _pil_items.crop((x0, y0, x1, y1))
        )
        _pil_items.close()

        # Shield Recharge texture
        self._shield_recharge_tex = arcade.load_texture(SHIELD_RECHARGE_PNG)

        # Copper pickup texture
        from constants import COPPER_PICKUP_PNG, MISSILE_PNG
        self._copper_tex = arcade.load_texture(COPPER_PICKUP_PNG)
        self._missile_tex = arcade.load_texture(MISSILE_PNG)

        # Inventory
        self.inventory = Inventory(
            iron_icon=self._iron_tex,
            repair_pack_icon=self._repair_pack_tex,
            shield_recharge_icon=self._shield_recharge_tex,
        )
        for key, info in MODULE_TYPES.items():
            mod_icon = arcade.load_texture(info["icon"])
            self.inventory.item_icons[f"mod_{key}"] = mod_icon
            self.inventory.item_icons[f"bp_{key}"] = self._blueprint_tinted.get(key, self._blueprint_tex)
            self.inventory._item_names[f"bp_{key}"] = f"BP {info['label']}"
            self.inventory._item_names[f"mod_{key}"] = info["label"]
        self.inventory.item_icons["copper"] = self._copper_tex
        self.inventory.item_icons["missile"] = self._missile_tex

        # Building system
        self.building_list = arcade.SpriteList(use_spatial_hash=True)
        self.turret_projectile_list = arcade.SpriteList()
        self._building_textures = load_building_textures()
        self._turret_laser_tex, self._turret_laser_snd = load_turret_laser()
        self._build_menu = BuildMenu()
        self._build_menu.set_textures(self._building_textures)
        self._placing_building: Optional[str] = None
        self._ghost_sprite: Optional[arcade.Sprite] = None
        self._ghost_list: Optional[arcade.SpriteList] = None
        self._ghost_rotation: float = 0.0
        self._destroy_mode: bool = False
        self._destroy_cursor_x: float = 0.0
        self._destroy_cursor_y: float = 0.0
        self._repair_acc: float = 0.0
        self._building_repair_acc: float = 0.0
        self._hover_building: Optional[StationModule] = None
        self._hover_screen_x: float = 0.0
        self._hover_screen_y: float = 0.0
        self._t_building_tip = arcade.Text(
            "", 0, 0, arcade.color.WHITE, 10, bold=True,
            anchor_x="center", anchor_y="bottom",
        )

        # Station info overlay
        self._station_info = StationInfo()
        self._ship_stats = ShipStats()

        # Station inventory (10x10)
        self._station_inv = StationInventory(
            iron_icon=self._iron_tex,
            repair_pack_icon=self._repair_pack_tex,
            shield_recharge_icon=self._shield_recharge_tex,
        )
        for key, info in MODULE_TYPES.items():
            mod_icon = arcade.load_texture(info["icon"])
            self._station_inv.item_icons[f"mod_{key}"] = mod_icon
            self._station_inv.item_icons[f"bp_{key}"] = self._blueprint_tinted.get(key, self._blueprint_tex)
        self._station_inv.item_icons["copper"] = self._copper_tex
        self._station_inv.item_icons["missile"] = self._missile_tex

        # Craft menu
        self._craft_menu = CraftMenu()
        self._craft_menu.repair_pack_icon = self._repair_pack_tex
        self._craft_menu.shield_recharge_icon = self._shield_recharge_tex
        for key, info in MODULE_TYPES.items():
            self._craft_menu.item_icons[key] = arcade.load_texture(info["icon"])
        self._active_crafter: Optional[BasicCrafter] = None

        # Trading station
        self._trade_menu = TradeMenu()
        self._trade_station: Optional[arcade.Sprite] = None
        self._trade_station_tex = arcade.load_texture(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "ai generated", "space station.PNG"))

        # Respawn timers
        self._asteroid_respawn_timer: float = 0.0
        self._alien_respawn_timer: float = 0.0

        # Fog of war
        self._fog_grid: list[list[bool]] = [
            [False] * FOG_GRID_W for _ in range(FOG_GRID_H)
        ]
        self._fog_revealed: int = 0

        gc.disable()
        self._gc_ran: bool = False

        # HUD
        self._hud = HUD(
            has_gamepad=self.joystick is not None,
            faction=faction,
            ship_type=ship_type,
            repair_pack_icon=self._repair_pack_tex,
            shield_recharge_icon=self._shield_recharge_tex,
        )
        if audio.show_fps:
            self._hud._show_fps = True
        for key, info in MODULE_TYPES.items():
            self._hud._mod_icons[key] = arcade.load_texture(info["icon"])
        self._hud._missile_icon = self._missile_tex

        # Thruster sound
        self._thruster_snd = load_thruster_sound()
        self._thruster_player: Optional[arcade.sound.media.Player] = None
        self._thrusting_last: bool = False

        # Contrail state
        self._contrail: list[ContrailParticle] = []
        self._contrail_timer: float = 0.0
        st = ship_type or "Cruiser"
        colours = CONTRAIL_COLOURS.get(st, CONTRAIL_COLOURS["Cruiser"])
        self._contrail_start_colour: tuple[int, int, int] = colours[0]
        self._contrail_end_colour: tuple[int, int, int] = colours[1]

        # Escape menu
        self._video_player = VideoPlayer(convert_fps=12.0)
        self._char_video_player = VideoPlayer(convert_fps=10.0)
        self._char_video_player._small_w = 160
        self._char_video_player._small_h = 160
        self._char_video_player._convert_cooldown = 0.06
        self._start_character_video()

        self._escape_menu = EscapeMenu(
            save_fn=self._save_game,
            load_fn=self._load_game,
            main_menu_fn=self._return_to_menu,
            save_dir=_SAVE_DIR,
            resolution_fn=self._change_resolution,
            video_play_fn=self._play_video,
            video_stop_fn=self._stop_video,
            stop_song_fn=self._stop_song,
            other_song_fn=self._other_song,
            character_select_fn=self._select_character,
        )

        # Death screen
        self._death_screen = DeathScreen()
        self._player_dead: bool = False

        # Background music
        self._music_tracks: list[tuple[arcade.Sound, str]] = collect_music_tracks()
        self._music_idx: int = 0
        self._music_player: Optional[arcade.sound.media.Player] = None
        self._current_track_name: str = ""
        if self._music_tracks and not self._skip_music and audio.autoplay_ost:
            self._play_next_track()

        # Zone state machine
        from zones.zone1_main import MainZone
        self._main_zone = MainZone()  # kept for reuse on return
        self._zone2: None = None      # created on first visit, reused after
        self._zone = self._main_zone
        self._zone.setup(self)

    # ── Zone transitions ──────────────────────────────────────────────────
    def _transition_zone(self, target_zone_id, entry_side: str = "bottom") -> None:
        """Tear down current zone, set up target zone, reposition player."""
        from zones import ZoneID, create_zone
        # Store player position for return
        if hasattr(self._zone, '_stash'):
            self._zone._stash["_player_pos"] = (
                self.player.center_x, self.player.center_y)
        self._zone.teardown(self)
        # Reuse persistent zone instances (preserves state across visits)
        if target_zone_id == ZoneID.MAIN:
            self._zone = self._main_zone
        elif target_zone_id == ZoneID.ZONE2:
            if self._zone2 is None:
                self._zone2 = create_zone(ZoneID.ZONE2)
            self._zone = self._zone2
        else:
            self._zone = create_zone(target_zone_id)
        self._zone.setup(self)
        # Update player world bounds
        self.player.world_width = self._zone.world_width
        self.player.world_height = self._zone.world_height
        # Reposition player
        px, py = self._zone.get_player_spawn(entry_side)
        self.player.center_x = px
        self.player.center_y = py
        self.player.vel_x = 0.0
        self.player.vel_y = 0.0
        # Zone entry announcement
        _ZONE_NAMES = {
            ZoneID.MAIN: "Entering the Double Star Zone",
            ZoneID.ZONE2: "Entering the Nebula Zone",
            ZoneID.WARP_METEOR: "Meteor Warp Zone",
            ZoneID.WARP_LIGHTNING: "Lightning Warp Zone",
            ZoneID.WARP_GAS: "Gas Cloud Warp Zone",
            ZoneID.WARP_ENEMY: "Enemy Spawner Warp Zone",
        }
        zone_name = _ZONE_NAMES.get(target_zone_id, "")
        if zone_name:
            self._boss_announce_timer = 3.0
            self._t_boss_announce.text = zone_name
            self._t_boss_subtitle.text = ""

    # ── Music delegates (game_music module) ────────────────────────────────
    def _play_next_track(self) -> None:
        from game_music import play_next_track; play_next_track(self)

    def _stop_music(self) -> None:
        from game_music import stop_music; stop_music(self)

    def _play_video(self, filepath: str) -> None:
        from game_music import play_video; play_video(self, filepath)

    def _start_character_video(self) -> None:
        from game_music import start_character_video; start_character_video(self)

    def _select_character(self, name: str) -> None:
        from game_music import select_character; select_character(self, name)

    def _stop_video(self) -> None:
        from game_music import stop_video; stop_video(self)

    def _stop_song(self) -> None:
        from game_music import stop_song; stop_song(self)

    def _other_song(self) -> None:
        from game_music import other_song; other_song(self)

    # ── Character progression ──────────────────────────────────────────────
    def _apply_character_weapon_bonuses(self) -> None:
        from character_data import (laser_damage_bonus, laser_cooldown_bonus,
                                    laser_speed_bonus, laser_range_bonus)
        name = audio.character_name
        lvl = self._char_level
        dmg = laser_damage_bonus(name, lvl)
        cd = laser_cooldown_bonus(name, lvl)
        spd = laser_speed_bonus(name, lvl)
        rng = laser_range_bonus(name, lvl)
        for wpn in self._weapons:
            if wpn.name == "Basic Laser":
                wpn.damage += dmg
                wpn.cooldown = max(0.05, wpn.cooldown - cd)
                wpn._proj_speed += spd
                wpn._max_range += rng

    @property
    def _active_weapon(self) -> Weapon:
        gun_count = self.player.guns
        base_idx = (self._weapon_idx // gun_count) * gun_count
        return self._weapons[base_idx]

    def _cycle_weapon(self) -> None:
        gun_count = self.player.guns
        self._weapon_idx = (self._weapon_idx + gun_count) % len(self._weapons)

    # ── Fog of war ─────────────────────────────────────────────────────────
    def _update_fog(self) -> None:
        px, py = self.player.center_x, self.player.center_y
        cx = int(px / FOG_CELL_SIZE)
        cy = int(py / FOG_CELL_SIZE)
        r = int(FOG_REVEAL_RADIUS / FOG_CELL_SIZE) + 1
        for gy in range(max(0, cy - r), min(FOG_GRID_H, cy + r + 1)):
            for gx in range(max(0, cx - r), min(FOG_GRID_W, cx + r + 1)):
                if not self._fog_grid[gy][gx]:
                    cell_cx = (gx + 0.5) * FOG_CELL_SIZE
                    cell_cy = (gy + 0.5) * FOG_CELL_SIZE
                    if math.hypot(px - cell_cx, py - cell_cy) <= FOG_REVEAL_RADIUS:
                        self._fog_grid[gy][gx] = True
                        self._fog_revealed += 1

    def is_revealed(self, wx: float, wy: float) -> bool:
        gx = int(wx / FOG_CELL_SIZE)
        gy = int(wy / FOG_CELL_SIZE)
        if 0 <= gx < FOG_GRID_W and 0 <= gy < FOG_GRID_H:
            return self._fog_grid[gy][gx]
        return False

    # ── Combat helpers (delegates to combat_helpers module) ─────────────────
    def _trigger_shake(self) -> None:
        _ch.trigger_shake(self)

    def _apply_damage_to_player(self, amount: int) -> None:
        _ch.apply_damage_to_player(self, amount)

    def _flash_game_msg(self, msg: str, duration: float = 1.5) -> None:
        _ch.flash_game_msg(self, msg, duration)

    def _use_repair_pack(self, slot: int) -> None:
        _ch.use_repair_pack(self, slot)

    def _use_shield_recharge(self, slot: int) -> None:
        _ch.use_shield_recharge(self, slot)

    def _fire_missile(self, slot: int) -> None:
        _ch.fire_missile(self, slot)

    def _spawn_explosion(self, x: float, y: float) -> None:
        _ch.spawn_explosion(self, x, y)

    def _spawn_iron_pickup(self, x: float, y: float,
                           amount: int = ASTEROID_IRON_YIELD,
                           lifetime: Optional[float] = None) -> None:
        _ch.spawn_iron_pickup(self, x, y, amount, lifetime)

    def _spawn_blueprint_pickup(self, x: float, y: float) -> None:
        _ch.spawn_blueprint_pickup(self, x, y)

    def _add_xp(self, amount: int) -> None:
        _ch.add_xp(self, amount)

    def _try_respawn_asteroids(self) -> None:
        _ch.try_respawn_asteroids(self)

    def _try_respawn_aliens(self) -> None:
        _ch.try_respawn_aliens(self)

    def _check_boss_spawn(self) -> None:
        _ch.check_boss_spawn(self)

    def _spawn_wormholes(self) -> None:
        """Spawn 4 wormholes in the corners of the map."""
        margin = 200.0
        corners = [
            (margin, margin),
            (WORLD_WIDTH - margin, margin),
            (margin, WORLD_HEIGHT - margin),
            (WORLD_WIDTH - margin, WORLD_HEIGHT - margin),
        ]
        from zones import ZoneID
        targets = [ZoneID.WARP_METEOR, ZoneID.WARP_LIGHTNING,
                   ZoneID.WARP_GAS, ZoneID.WARP_ENEMY]
        for (cx, cy), target in zip(corners, targets):
            wh = Wormhole(cx, cy)
            wh.zone_target = target
            self._wormholes.append(wh)
            self._wormhole_list.append(wh)

    # ── Building helpers (delegates to building_manager module) ─────────────
    def _spawn_trade_station(self) -> None:
        _bm.spawn_trade_station(self)

    def _building_counts(self) -> dict[str, int]:
        return _bm.building_counts(self)

    def _has_home_station(self) -> bool:
        return _bm.has_home_station(self)

    def _find_nearest_snap_port(self, wx: float, wy: float,
                                max_dist: float = 0.0):
        return _bm.find_nearest_snap_port(self, wx, wy, max_dist)

    def _enter_placement_mode(self, building_type: str) -> None:
        _bm.enter_placement_mode(self, building_type)

    def _cancel_placement(self) -> None:
        _bm.cancel_placement(self)

    def _enter_destroy_mode(self) -> None:
        _bm.enter_destroy_mode(self)

    def _exit_destroy_mode(self) -> None:
        _bm.exit_destroy_mode(self)

    def _disconnect_ports(self, building) -> None:
        _bm.disconnect_ports(self, building)

    def _destroy_building_at(self, wx: float, wy: float) -> None:
        _bm.destroy_building_at(self, wx, wy)

    def _place_building(self, wx: float, wy: float) -> None:
        _bm.place_building(self, wx, wy)

    # ── Cleanup ────────────────────────────────────────────────────────────
    def _cleanup(self) -> None:
        """Release resources before this view is replaced (e.g. on load game)."""
        # Stop audio
        if self._thruster_player is not None:
            arcade.stop_sound(self._thruster_player)
            self._thruster_player = None
        self._stop_music()
        self._stop_video()
        # Stop character video
        if self._char_video_player.active:
            self._char_video_player.stop()
        # Clear sprite lists to drop texture references
        self.asteroid_list.clear()
        self.alien_list.clear()
        self.building_list.clear()
        self.explosion_list.clear()
        self.iron_pickup_list.clear()
        self.blueprint_pickup_list.clear()
        self.projectile_list.clear()
        self.alien_projectile_list.clear()
        self.turret_projectile_list.clear()
        self._boss_list.clear()
        self._boss_projectile_list.clear()
        self._boss = None
        self._wormholes.clear()
        self._wormhole_list.clear()
        self._missile_list.clear()
        self._force_walls.clear()
        self._death_blossom_active = False
        # Re-enable GC so old view can be collected
        gc.enable()

    # ── Save / Load / Menu delegates ──────────────────────────────────────
    def _save_to_dict(self, name: str = "") -> dict:
        from game_save import save_to_dict; return save_to_dict(self, name)

    def _save_game(self, slot: int, name: str) -> None:
        from game_save import save_game; save_game(self, slot, name)

    @staticmethod
    def _restore_state(view: "GameView", data: dict) -> None:
        from game_save import restore_state; restore_state(view, data)

    def _load_game(self, slot: int) -> None:
        from game_save import load_game; load_game(self, slot)

    def _change_resolution(self, width: int, height: int, display_mode: str) -> None:
        from game_music import change_resolution; change_resolution(self, width, height, display_mode)

    def _return_to_menu(self) -> None:
        from game_music import return_to_menu; return_to_menu(self)

    # ── Drawing ──────────────────────────────────────────────────────────────
    def on_draw(self) -> None:
        VideoPlayer._frame_id += 1
        self.clear()
        sw = self.window.width
        sh = self.window.height
        hw = sw / 2
        hh = sh / 2
        zw = self._zone.world_width
        zh = self._zone.world_height
        cx = max(hw - STATUS_WIDTH, min(zw - hw, self.player.center_x))
        cy = max(hh, min(zh - hh, self.player.center_y))
        shake_x = shake_y = 0.0
        if self._shake_timer > 0.0:
            frac = self._shake_timer / SHAKE_DURATION
            amp = self._shake_amp * frac
            shake_x = random.uniform(-amp, amp)
            shake_y = random.uniform(-amp, amp)
        self.world_cam.position = (cx + shake_x, cy + shake_y)
        with self.world_cam.activate():
            _dl.draw_world(self, cx, cy, hw, hh)
        with self.ui_cam.activate():
            _dl.draw_ui(self)

    # ── Update ───────────────────────────────────────────────────────────────
    def on_update(self, delta_time: float) -> None:
        _ul.update_preamble(self, delta_time)
        if self._player_dead:
            _ul.update_death_state(self, delta_time)
            return
        _ul.update_timers(self, delta_time)
        _ul.update_repair_and_shields(self, delta_time)
        _ul.update_crafting(self, delta_time)
        fire = _ul.update_movement(self, delta_time)
        _ul.update_contrail(self, delta_time)
        _ul.update_weapons(self, delta_time, fire)
        # Always advance player projectiles (shared across all zones)
        for proj in list(self.projectile_list):
            proj.update_projectile(delta_time)
        # Always collect pickups (shared across all zones)
        from constants import SHIP_RADIUS
        sx, sy = self.player.center_x, self.player.center_y
        for pickup in list(self.iron_pickup_list):
            collected = pickup.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_item(getattr(pickup, 'item_type', 'iron'), pickup.amount)
        for bp in list(self.blueprint_pickup_list):
            collected = bp.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_item(bp.item_type, 1)
        # Zone-specific updates
        from zones import ZoneID
        if self._zone.zone_id == ZoneID.MAIN:
            self._update_fog()
            _ul.update_entities(self, delta_time)
            _ul.update_buildings(self, delta_time)
            _ul.update_respawns(self, delta_time)
            _ul.update_boss(self, delta_time)
            _ul.update_wormholes(self, delta_time)
        else:
            self._zone.update(self, delta_time)
        _ul.update_ability_meter(self, delta_time)
        _ul.update_force_walls(self, delta_time)
        _ul.update_missiles(self, delta_time)
        _ul.update_death_blossom(self, delta_time)
        _ul.update_effects(self, delta_time)

    # ── Input ────────────────────────────────────────────────────────────────
    def on_key_press(self, key: int, modifiers: int) -> None:
        _ih.handle_key_press(self, key, modifiers)

    def on_key_release(self, key: int, modifiers: int) -> None:
        self._keys.discard(key)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        _ih.handle_mouse_press(self, x, y, button, modifiers)

    def on_mouse_drag(
        self, x: int, y: int, dx: int, dy: int, buttons: int, modifiers: int
    ) -> None:
        _ih.handle_mouse_drag(self, x, y, dx, dy, buttons, modifiers)

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
        _ih.handle_mouse_release(self, x, y, button, modifiers)

    def on_mouse_scroll(
        self, x: int, y: int, scroll_x: int, scroll_y: int
    ) -> None:
        _ih.handle_mouse_scroll(self, x, y, scroll_x, scroll_y)

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        _ih.handle_mouse_motion(self, x, y, dx, dy)

    def on_text(self, text: str) -> None:
        if self._escape_menu.open:
            self._escape_menu.on_text(text)
