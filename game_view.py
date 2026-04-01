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
    REPAIR_PACK_PNG, REPAIR_PACK_CROP, QUICK_USE_SLOTS,
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
from sprites.boss import BossAlienShip
from collisions import (
    handle_projectile_hits,
    handle_ship_asteroid_collision,
    handle_alien_player_collision,
    handle_alien_asteroid_collision,
    handle_alien_alien_collision,
    handle_alien_laser_hits,
    handle_alien_laser_building_hits,
    handle_alien_building_collision,
    handle_turret_projectile_hits,
    handle_ship_building_collision,
    handle_boss_projectile_hits,
    handle_boss_player_collision,
    handle_boss_laser_hits,
    handle_boss_building_hits,
    handle_boss_charge_hit,
)
from station_info import StationInfo
from ship_stats import ShipStats
from station_inventory import StationInventory
from craft_menu import CraftMenu
from trade_menu import TradeMenu
from video_player import VideoPlayer
from game_save import _SAVE_DIR


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
            "armor_plate":     (80, 130, 255),    # blue
            "engine_booster":  (255, 80, 80),     # red
            "shield_booster":  (180, 80, 255),    # purple
            "shield_enhancer": (40, 60, 180),     # navy blue
            "damage_absorber": (255, 140, 200),   # pink
            "broadside":       (200, 100, 255),   # violet
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

        # Module slots
        self._module_slots: list[str | None] = [None] * MODULE_SLOT_COUNT
        self._broadside_cd: float = 0.0
        self._enhancer_angle: float = 0.0  # shield enhancer ring rotation
        # Broadside laser texture (same as basic laser)
        from constants import LASER_DIR
        self._broadside_tex = arcade.load_texture(
            os.path.join(LASER_DIR, "laserBlue03.png"))

        # Alien ships
        self.alien_list, _alien_laser_tex = populate_aliens()
        # Cache respawn textures (avoid reloading from disk every spawn)
        self._asteroid_tex = arcade.load_texture(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "Pixel Art Space", "Asteroid.png"))
        from PIL import Image as PILImage
        from constants import ALIEN_SHIP_PNG, ALIEN_FX_PNG
        _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
        self._alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))
        _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
        _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
        self._alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))
        self.alien_projectile_list: arcade.SpriteList = arcade.SpriteList()
        self.hit_sparks: list[HitSpark] = []
        self.fire_sparks: list[FireSpark] = []

        # Boss encounter state
        self._boss: Optional[BossAlienShip] = None
        self._boss_spawned: bool = False
        self._boss_defeated: bool = False
        self._boss_list: arcade.SpriteList = arcade.SpriteList()
        self._boss_projectile_list: arcade.SpriteList = arcade.SpriteList()
        # Pre-load boss textures (pick random row from first column)
        from PIL import Image as PILImage
        _pil_boss = PILImage.open(BOSS_MONSTER_PNG).convert("RGBA")
        boss_row = random.randint(0, BOSS_SHEET_ROWS - 1)
        _boss_frame = _pil_boss.crop((
            0, boss_row * BOSS_FRAME_SIZE,
            BOSS_FRAME_SIZE, (boss_row + 1) * BOSS_FRAME_SIZE,
        ))
        _boss_frame = _boss_frame.rotate(90, expand=True)
        self._boss_tex = arcade.Texture(_boss_frame)
        self._boss_laser_tex = self._alien_laser_tex  # reuse alien laser

        # Repair pack texture
        from PIL import Image as PILImage
        _pil_items = PILImage.open(REPAIR_PACK_PNG).convert("RGBA")
        x0, y0, x1, y1 = REPAIR_PACK_CROP
        self._repair_pack_tex = arcade.Texture(
            _pil_items.crop((x0, y0, x1, y1))
        )

        # Inventory
        self.inventory = Inventory(
            iron_icon=self._iron_tex,
            repair_pack_icon=self._repair_pack_tex,
        )
        # Set up blueprint + module icons and names for ship inventory
        for key, info in MODULE_TYPES.items():
            mod_icon = arcade.load_texture(info["icon"])
            self.inventory.item_icons[f"mod_{key}"] = mod_icon
            self.inventory.item_icons[f"bp_{key}"] = self._blueprint_tinted.get(key, self._blueprint_tex)
            self.inventory._item_names[f"bp_{key}"] = f"BP {info['label']}"
            self.inventory._item_names[f"mod_{key}"] = info["label"]

        # Building system
        self.building_list = arcade.SpriteList(use_spatial_hash=True)
        self.turret_projectile_list = arcade.SpriteList()
        self._building_textures = load_building_textures()
        self._turret_laser_tex, self._turret_laser_snd = load_turret_laser()
        self._build_menu = BuildMenu()
        self._build_menu.set_textures(self._building_textures)
        # Placement mode state
        self._placing_building: Optional[str] = None
        self._ghost_sprite: Optional[arcade.Sprite] = None
        self._ghost_list: Optional[arcade.SpriteList] = None
        self._ghost_rotation: float = 0.0
        # Destroy mode state
        self._destroy_mode: bool = False
        self._destroy_cursor_x: float = 0.0
        self._destroy_cursor_y: float = 0.0
        # Repair healing accumulators
        self._repair_acc: float = 0.0
        self._building_repair_acc: float = 0.0
        # Building hover tooltip state
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

        # Station inventory (10×10)
        self._station_inv = StationInventory(
            iron_icon=self._iron_tex,
            repair_pack_icon=self._repair_pack_tex,
        )
        # Load blueprint + module icons for station inventory display
        for key, info in MODULE_TYPES.items():
            mod_icon = arcade.load_texture(info["icon"])
            self._station_inv.item_icons[f"mod_{key}"] = mod_icon
            self._station_inv.item_icons[f"bp_{key}"] = self._blueprint_tinted.get(key, self._blueprint_tex)

        # Craft menu
        self._craft_menu = CraftMenu()
        self._craft_menu.repair_pack_icon = self._repair_pack_tex
        for key, info in MODULE_TYPES.items():
            self._craft_menu.item_icons[key] = arcade.load_texture(info["icon"])
        self._active_crafter: Optional[BasicCrafter] = None

        # Trading station
        self._trade_menu = TradeMenu()
        self._trade_station: Optional[arcade.Sprite] = None
        self._trade_station_tex = arcade.load_texture(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "ai generated", "space station.PNG"))

        # Respawn timers (count up toward RESPAWN_INTERVAL)
        self._asteroid_respawn_timer: float = 0.0
        self._alien_respawn_timer: float = 0.0

        # Fog of war grid — False = hidden, True = revealed
        self._fog_grid: list[list[bool]] = [
            [False] * FOG_GRID_W for _ in range(FOG_GRID_H)
        ]
        self._fog_revealed: int = 0

        # Disable automatic GC; run once when ESC menu opens
        gc.disable()
        self._gc_ran: bool = False

        # HUD
        self._hud = HUD(
            has_gamepad=self.joystick is not None,
            faction=faction,
            ship_type=ship_type,
            repair_pack_icon=self._repair_pack_tex,
        )
        if audio.show_fps:
            self._hud._show_fps = True
        # Set module icons on HUD
        for key, info in MODULE_TYPES.items():
            self._hud._mod_icons[key] = arcade.load_texture(info["icon"])

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
        # Video player (music videos)
        self._video_player = VideoPlayer(convert_fps=12.0)
        # Character video player (looping character portrait in HUD)
        # Lower fps + smaller FBO + offset cooldown to minimize GPU cost
        self._char_video_player = VideoPlayer(convert_fps=10.0)
        self._char_video_player._small_w = 160
        self._char_video_player._small_h = 160
        self._char_video_player._convert_cooldown = 0.06  # stagger by ~1 frame
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

        # Background music — shuffled playlist of loop tracks
        self._music_tracks: list[tuple[arcade.Sound, str]] = collect_music_tracks()
        self._music_idx: int = 0
        self._music_player: Optional[arcade.sound.media.Player] = None
        self._current_track_name: str = ""
        if self._music_tracks and not self._skip_music and audio.autoplay_ost:
            self._play_next_track()

    # ── Music (delegated to game_music module) ──────────────────────────────
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

    # ── Helpers ──────────────────────────────────────────────────────────────
    # ── Character progression ──────────────────────────────────────────────
    def _apply_character_weapon_bonuses(self) -> None:
        """Apply Ellie's weapon bonuses to all Basic Laser weapons."""
        from character_data import (laser_damage_bonus, laser_cooldown_bonus,
                                    laser_speed_bonus, laser_range_bonus)
        from settings import audio
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

    def _add_xp(self, amount: int) -> None:
        """Add XP and check for level-up; reapply bonuses if leveled."""
        from character_data import level_for_xp
        if self._char_xp >= 1000:
            return
        old_level = self._char_level
        self._char_xp = min(self._char_xp + amount, 1000)
        self._char_level = level_for_xp(self._char_xp)
        if self._char_level > old_level:
            self._flash_game_msg(f"Level {self._char_level}!", 2.0)
            # Reapply weapon bonuses at new level
            self._weapons = load_weapons(self.player.guns)
            self._apply_character_weapon_bonuses()

    @property
    def _active_weapon(self) -> Weapon:
        """Return the first weapon of the currently active weapon group."""
        gun_count = self.player.guns
        base_idx = (self._weapon_idx // gun_count) * gun_count
        return self._weapons[base_idx]

    def _cycle_weapon(self) -> None:
        gun_count = self.player.guns
        # Jump by gun_count so we cycle weapon *groups*, not individual guns
        self._weapon_idx = (self._weapon_idx + gun_count) % len(self._weapons)

    def _spawn_explosion(self, x: float, y: float) -> None:
        """Spawn a one-shot explosion animation at world position (x, y)."""
        exp = Explosion(self._explosion_frames, x, y, scale=1.0)
        self.explosion_list.append(exp)

    def _spawn_iron_pickup(
        self,
        x: float,
        y: float,
        amount: int = ASTEROID_IRON_YIELD,
        lifetime: Optional[float] = None,
    ) -> None:
        """Spawn an iron token at world position (x, y)."""
        pickup = IronPickup(self._iron_tex, x, y, amount=amount, lifetime=lifetime)
        self.iron_pickup_list.append(pickup)

    def _spawn_blueprint_pickup(self, x: float, y: float) -> None:
        """Spawn a random blueprint pickup at world position (x, y)."""
        mod_type = random.choice(list(MODULE_TYPES.keys()))
        tex = self._blueprint_tinted.get(mod_type, self._blueprint_tex)
        bp = BlueprintPickup(tex, x, y, mod_type,
                             lifetime=WORLD_ITEM_LIFETIME)
        self.blueprint_pickup_list.append(bp)

    def _update_fog(self) -> None:
        """Reveal fog cells around the player's current position."""
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
        """Check if a world position has been revealed by the fog of war."""
        gx = int(wx / FOG_CELL_SIZE)
        gy = int(wy / FOG_CELL_SIZE)
        if 0 <= gx < FOG_GRID_W and 0 <= gy < FOG_GRID_H:
            return self._fog_grid[gy][gx]
        return False

    def _try_respawn_asteroids(self) -> None:
        """Respawn one asteroid if count < ASTEROID_COUNT, avoiding buildings."""
        if len(self.asteroid_list) >= ASTEROID_COUNT:
            return
        from sprites.asteroid import IronAsteroid
        margin = 100
        for _ in range(200):
            ax = random.uniform(margin, WORLD_WIDTH - margin)
            ay = random.uniform(margin, WORLD_HEIGHT - margin)
            cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
            if math.hypot(ax - cx_world, ay - cy_world) < ASTEROID_MIN_DIST:
                continue
            # Check building exclusion zone
            too_close = any(
                math.hypot(ax - b.center_x, ay - b.center_y)
                < RESPAWN_EXCLUSION_RADIUS
                for b in self.building_list
            )
            if too_close:
                continue
            self.asteroid_list.append(IronAsteroid(self._asteroid_tex, ax, ay))
            self.hit_sparks.append(HitSpark(ax, ay))
            arcade.play_sound(self._bump_snd, volume=0.3)
            return

    def _try_respawn_aliens(self) -> None:
        """Respawn one alien if count < ALIEN_COUNT, avoiding buildings."""
        if len(self.alien_list) >= ALIEN_COUNT:
            return
        from sprites.alien import SmallAlienShip
        margin = 100
        for _ in range(200):
            ax = random.uniform(margin, WORLD_WIDTH - margin)
            ay = random.uniform(margin, WORLD_HEIGHT - margin)
            cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
            if math.hypot(ax - cx_world, ay - cy_world) < ALIEN_MIN_DIST:
                continue
            too_close = any(
                math.hypot(ax - b.center_x, ay - b.center_y)
                < RESPAWN_EXCLUSION_RADIUS
                for b in self.building_list
            )
            if too_close:
                continue
            self.alien_list.append(
                SmallAlienShip(self._alien_ship_tex, self._alien_laser_tex, ax, ay)
            )
            self.hit_sparks.append(HitSpark(ax, ay))
            arcade.play_sound(self._bump_snd, volume=0.3)
            return

    def _check_boss_spawn(self) -> None:
        """Check if boss spawn conditions are met and spawn if so."""
        if self._boss_spawned or self._boss_defeated or self._boss is not None:
            return
        # Condition 1: max level (5)
        if self._char_level < 5:
            return
        # Condition 2: all 4 module slots filled
        if any(m is None for m in self._module_slots):
            return
        # Condition 3: at least 5 repair packs (ship + station combined)
        rp_count = self.inventory.count_item("repair_pack")
        rp_count += self._station_inv.count_item("repair_pack")
        if rp_count < 5:
            return
        # Condition 4: must have a Home Station
        home = None
        for b in self.building_list:
            if isinstance(b, HomeStation) and not b.disabled:
                home = b
                break
        if home is None:
            return
        self._spawn_boss(home.center_x, home.center_y)

    def _spawn_boss(self, station_x: float, station_y: float) -> None:
        """Spawn the boss as far as possible from the station."""
        # Pick the world corner farthest from the station
        corners = [
            (100.0, 100.0),
            (WORLD_WIDTH - 100.0, 100.0),
            (100.0, WORLD_HEIGHT - 100.0),
            (WORLD_WIDTH - 100.0, WORLD_HEIGHT - 100.0),
        ]
        best_corner = max(
            corners,
            key=lambda c: math.hypot(c[0] - station_x, c[1] - station_y),
        )
        self._boss = BossAlienShip(
            self._boss_tex, self._boss_laser_tex,
            best_corner[0], best_corner[1],
            station_x, station_y,
        )
        self._boss_list.clear()
        self._boss_list.append(self._boss)
        self._boss_spawned = True
        self._boss_announce_timer = 5.0

    def _trigger_shake(self) -> None:
        """Start a brief camera shake."""
        self._shake_timer = SHAKE_DURATION

    def _apply_damage_to_player(self, amount: int) -> None:
        """Apply damage to the player's shields first, then HP."""
        if self._player_dead:
            return
        # Damage absorber module reduces incoming damage to shields
        if self.player.shield_absorb > 0 and self.player.shields > 0:
            amount = max(1, amount - self.player.shield_absorb)
        if self.player.shields > 0:
            absorbed = min(self.player.shields, amount)
            self.player.shields -= absorbed
            amount -= absorbed
            self.shield_sprite.hit_flash()
        if amount > 0:
            self.player.hp = max(0, self.player.hp - amount)
            # Fire sparks when hull takes damage
            self.fire_sparks.append(
                FireSpark(self.player.center_x, self.player.center_y)
            )
            # Check for death
            if self.player.hp <= 0:
                self._trigger_player_death()
        self._shake_amp = SHAKE_AMPLITUDE

    def _flash_game_msg(self, msg: str, duration: float = 1.5) -> None:
        """Show a temporary message centered on the play area."""
        self._flash_msg = msg
        self._flash_timer = duration

    def _use_repair_pack(self, slot: int) -> None:
        """Try to use a repair pack from the given quick-use slot."""
        if self.player.hp >= self.player.max_hp and self.player.shields >= self.player.max_shields:
            self._flash_game_msg("Already at full HP and shields!")
            return
        if self.inventory.count_item("repair_pack") <= 0:
            return
        heal = int(self.player.max_hp * REPAIR_PACK_HEAL)
        self.player.hp = min(self.player.max_hp, self.player.hp + heal)
        self.inventory.remove_item("repair_pack", 1)
        remaining = self.inventory.count_item("repair_pack")
        if remaining > 0:
            self._hud.set_quick_use(slot, "repair_pack", remaining)
        else:
            self._hud.set_quick_use(slot, None, 0)

    def _trigger_player_death(self) -> None:
        """Handle player ship destruction."""
        self._player_dead = True

        # Spawn a large explosion at the player's position
        exp = Explosion(
            self._explosion_frames,
            self.player.center_x,
            self.player.center_y,
            scale=2.5,  # bigger than asteroid explosions
        )
        exp.color = (255, 180, 100, 255)  # orange-ish tint
        self.explosion_list.append(exp)

        # Spawn extra fire sparks for dramatic effect
        for _ in range(5):
            self.fire_sparks.append(
                FireSpark(self.player.center_x, self.player.center_y)
            )

        # Play explosion sound
        arcade.play_sound(self._explosion_snd, volume=audio.sfx_volume)

        # Hide player and shield
        self.player.visible = False
        self.shield_sprite.visible = False

        # Stop thruster
        if self._thruster_player is not None:
            arcade.stop_sound(self._thruster_player)
            self._thruster_player = None

        # Show death screen after a brief delay (handled via _death_delay)
        self._death_delay: float = 1.5  # seconds before showing death screen

    # ── Building helpers ───────────────────────────────────────────────────
    def _spawn_trade_station(self) -> None:
        """Spawn the trading station at a random position far from the player."""
        if self._trade_station is not None:
            return
        margin = 500
        for _ in range(200):
            tx = random.uniform(margin, WORLD_WIDTH - margin)
            ty = random.uniform(margin, WORLD_HEIGHT - margin)
            # Keep away from player's home area
            if math.hypot(tx - WORLD_WIDTH / 2, ty - WORLD_HEIGHT / 2) < 1500:
                continue
            self._trade_station = arcade.Sprite(
                path_or_texture=self._trade_station_tex, scale=0.15)
            self._trade_station.center_x = tx
            self._trade_station.center_y = ty
            return

    def _building_counts(self) -> dict[str, int]:
        """Return a dict of building_type → count for the current station."""
        counts: dict[str, int] = {}
        for b in self.building_list:
            counts[b.building_type] = counts.get(b.building_type, 0) + 1
        return counts

    def _has_home_station(self) -> bool:
        return any(isinstance(b, HomeStation) for b in self.building_list)

    def _find_nearest_snap_port(
        self, wx: float, wy: float, max_dist: float = 0.0,
    ) -> Optional[tuple[StationModule, DockingPort, float, float]]:
        """Find the nearest unoccupied docking port within max_dist.

        Returns (building, port, snap_x, snap_y) or None.
        """
        if max_dist <= 0:
            max_dist = DOCK_SNAP_DIST
        best = None
        best_dist = max_dist + 1.0
        for b in self.building_list:
            for port in b.get_unoccupied_ports():
                px, py = b.get_port_world_pos(port)
                d = math.hypot(wx - px, wy - py)
                if d < best_dist:
                    best_dist = d
                    best = (b, port, px, py)
        return best

    def _enter_placement_mode(self, building_type: str) -> None:
        """Start building placement — create ghost sprite following cursor."""
        self._placing_building = building_type
        tex = self._building_textures[building_type]
        self._ghost_sprite = arcade.Sprite(path_or_texture=tex, scale=0.5)
        self._ghost_sprite.alpha = 140
        self._ghost_list = arcade.SpriteList()
        self._ghost_list.append(self._ghost_sprite)
        self._ghost_rotation = 0.0
        self._build_menu.open = False

    def _cancel_placement(self) -> None:
        """Cancel building placement mode."""
        self._placing_building = None
        self._ghost_sprite = None
        self._ghost_list = None

    def _enter_destroy_mode(self) -> None:
        """Enter destroy mode — clicks will destroy station modules."""
        self._destroy_mode = True
        self._build_menu.open = False

    def _exit_destroy_mode(self) -> None:
        """Exit destroy mode."""
        self._destroy_mode = False

    def _disconnect_ports(self, building: StationModule) -> None:
        """Free docking ports on connected buildings when one is removed."""
        for port in building.ports:
            if port.occupied and port.connected_to is not None:
                other = port.connected_to
                for op in other.ports:
                    if op.connected_to is building:
                        op.occupied = False
                        op.connected_to = None

    def _destroy_building_at(self, wx: float, wy: float) -> None:
        """Destroy the closest building within click range of world pos."""
        best = None
        best_dist = 40.0  # max click distance
        for b in self.building_list:
            d = math.hypot(wx - b.center_x, wy - b.center_y)
            if d < best_dist:
                best_dist = d
                best = b
        if best is not None:
            self._disconnect_ports(best)
            # Drop iron equal to build cost
            cost = BUILDING_TYPES[best.building_type]["cost"]
            self._spawn_iron_pickup(
                best.center_x, best.center_y, amount=cost,
            )
            if isinstance(best, HomeStation):
                for b in self.building_list:
                    b.disabled = True
                    b.color = (128, 128, 128, 255)
            self._spawn_explosion(best.center_x, best.center_y)
            arcade.play_sound(self._explosion_snd, volume=0.7)
            best.remove_from_sprite_lists()

    def _place_building(self, wx: float, wy: float) -> None:
        """Attempt to place the building at world position (wx, wy)."""
        bt = self._placing_building
        if bt is None:
            return
        stats = BUILDING_TYPES[bt]
        from character_data import build_cost_multiplier, station_hp_multiplier
        cost = int(stats["cost"] * build_cost_multiplier(audio.character_name, self._char_level))

        # Deduct iron from ship inventory first, then station inventory
        total_iron = self.inventory.total_iron + self._station_inv.total_iron
        if total_iron < cost:
            self._cancel_placement()
            return
        remaining = cost
        ship_iron = min(remaining, self.inventory.total_iron)
        if ship_iron > 0:
            self.inventory.remove_item("iron", ship_iron)
            remaining -= ship_iron
        if remaining > 0:
            self._station_inv.remove_item("iron", remaining)

        tex = self._building_textures[bt]
        laser_tex = self._turret_laser_tex if "Turret" in bt else None
        building = create_building(bt, tex, wx, wy, laser_tex=laser_tex, scale=0.5)
        # Tara's station HP bonus
        hp_mult = station_hp_multiplier(audio.character_name, self._char_level)
        if hp_mult != 1.0:
            building.max_hp = int(building.max_hp * hp_mult)
            building.hp = building.max_hp
        building.angle = self._ghost_rotation

        # Snap to port if connectable — edge-to-edge placement
        snap_parent = None
        snap_port = None
        snap_opp_port = None
        if stats["connectable"]:
            # Use larger search radius to find port near the edge-to-edge
            # offset position (ghost center is offset from the port)
            snap = self._find_nearest_snap_port(
                wx, wy, max_dist=DOCK_SNAP_DIST + BUILDING_RADIUS * 2,
            )
            if snap is None and bt != "Home Station":
                # Non-Home connectable modules MUST snap to a port
                self.inventory.add_item("iron", cost)
                self._cancel_placement()
                return
            if snap is not None:
                snap_parent, snap_port, sx, sy = snap
                # Find the opposite port on the new building
                opp_dir = DockingPort.opposite(snap_port.direction)
                for np in building.ports:
                    if np.direction == opp_dir:
                        snap_opp_port = np
                        break
                # Offset by opposite port so edges meet (not centres)
                if snap_opp_port is not None:
                    rad = math.radians(building.angle)
                    cos_a = math.cos(rad)
                    sin_a = math.sin(rad)
                    ox_rot = snap_opp_port.offset_x * cos_a - snap_opp_port.offset_y * sin_a
                    oy_rot = snap_opp_port.offset_x * sin_a + snap_opp_port.offset_y * cos_a
                    building.center_x = sx - ox_rot
                    building.center_y = sy - oy_rot
                else:
                    building.center_x = sx
                    building.center_y = sy

        # Overlap check — no part should be inside any other building
        # Skip the snap parent (connected buildings are intentionally close)
        for existing in self.building_list:
            if existing is snap_parent:
                continue
            if math.hypot(building.center_x - existing.center_x,
                          building.center_y - existing.center_y) < BUILDING_RADIUS * 2:
                self.inventory.add_item("iron", cost)
                self._cancel_placement()
                return

        # Connect ports after overlap check passes
        if snap_port is not None:
            snap_port.occupied = True
            snap_port.connected_to = building
            if snap_opp_port is not None:
                snap_opp_port.occupied = True
                snap_opp_port.connected_to = snap_parent

        self.building_list.append(building)

        # Spawn trading station when first repair module is placed
        if isinstance(building, RepairModule) and self._trade_station is None:
            self._spawn_trade_station()

        # Post-placement: connect any other adjacent ports (both ends connect)
        for new_port in building.get_unoccupied_ports():
            npx, npy = building.get_port_world_pos(new_port)
            for other in self.building_list:
                if other is building:
                    continue
                for other_port in other.get_unoccupied_ports():
                    opx, opy = other.get_port_world_pos(other_port)
                    if math.hypot(npx - opx, npy - opy) < DOCK_SNAP_DIST:
                        new_port.occupied = True
                        new_port.connected_to = other
                        other_port.occupied = True
                        other_port.connected_to = building
                        break
                if new_port.occupied:
                    break

        self._cancel_placement()

    # ── Save / Load / Menu (delegated to game_save / game_music modules) ───
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
        cx = max(hw - STATUS_WIDTH, min(WORLD_WIDTH - hw, self.player.center_x))
        cy = max(hh, min(WORLD_HEIGHT - hh, self.player.center_y))

        shake_x = shake_y = 0.0
        if self._shake_timer > 0.0:
            frac = self._shake_timer / SHAKE_DURATION
            amp = self._shake_amp * frac
            shake_x = random.uniform(-amp, amp)
            shake_y = random.uniform(-amp, amp)

        self.world_cam.position = (cx + shake_x, cy + shake_y)

        with self.world_cam.activate():
            self._draw_background(cx, cy, hw, hh)
            self.asteroid_list.draw()
            self.iron_pickup_list.draw()
            self.blueprint_pickup_list.draw()
            self.explosion_list.draw()
            self.building_list.draw()
            if self._trade_station is not None:
                ts = self._trade_station
                tw = self._trade_station_tex.width * 0.15
                th = self._trade_station_tex.height * 0.15
                arcade.draw_texture_rect(
                    self._trade_station_tex,
                    arcade.LBWH(ts.center_x - tw / 2,
                                ts.center_y - th / 2,
                                tw, th))
            self.turret_projectile_list.draw()
            self.alien_list.draw()
            self.alien_projectile_list.draw()
            # Boss
            if self._boss is not None and self._boss.hp > 0:
                self._boss_list.draw()
                self._boss_projectile_list.draw()
            self.projectile_list.draw()
            # Contrail drawn behind the player ship
            for cp in self._contrail:
                cp.draw()
            self.player_list.draw()
            self.shield_list.draw()
            # Shield enhancer ring (rotating yellow circle outside shield)
            if ("shield_enhancer" in self._module_slots
                    and self.player.shields > 0 and not self._player_dead):
                import math as _m
                ex, ey = self.player.center_x, self.player.center_y
                # Ring radius just outside the shield sprite
                ring_r = self.shield_sprite.width * SHIELD_SCALE / 2 + 20
                # Shade shifts between gold and pale yellow
                t = (_m.sin(self._enhancer_angle * _m.pi / 90) + 1) / 2
                cr = int(200 + 55 * t)
                cg = int(180 + 50 * t)
                cb = int(40 + 80 * (1 - t))
                # Draw dashed ring (8 arcs with gaps for rotation effect)
                segments = 8
                arc_len = 360 / segments * 0.7
                for i in range(segments):
                    start = self._enhancer_angle + i * (360 / segments)
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
            for spark in self.hit_sparks:
                spark.draw()
            for fs in self.fire_sparks:
                fs.draw()
            # Ghost sprite for placement mode
            if self._ghost_list is not None:
                self._ghost_list.draw()
            # Destroy mode crosshair
            if self._destroy_mode:
                cx, cy = self._destroy_cursor_x, self._destroy_cursor_y
                sz = 16
                arcade.draw_line(cx - sz, cy, cx + sz, cy, (255, 60, 60, 200), 2)
                arcade.draw_line(cx, cy - sz, cx, cy + sz, (255, 60, 60, 200), 2)
                arcade.draw_circle_outline(cx, cy, 12, (255, 60, 60, 180), 2)

        with self.ui_cam.activate():
            menu_open = self._escape_menu.open
            self._hud.draw(
                weapon_name=self._active_weapon.name,
                hp=self.player.hp,
                max_hp=self.player.max_hp,
                shields=self.player.shields,
                max_shields=self.player.max_shields,
                asteroid_list=self.asteroid_list,
                iron_pickup_list=self.iron_pickup_list,
                alien_list=self.alien_list,
                player_x=self.player.center_x,
                player_y=self.player.center_y,
                player_heading=self.player.heading,
                track_name=(self._video_player.track_name
                            if self._video_player.active
                            else self._current_track_name),
                building_list=self.building_list,
                fog_grid=self._fog_grid,
                fog_revealed=self._fog_revealed,
                video_active=self._video_player.active,
                character_name=audio.character_name,
                trade_station_pos=(self._trade_station.center_x, self._trade_station.center_y)
                    if self._trade_station is not None else None,
                boss_pos=(self._boss.center_x, self._boss.center_y)
                    if self._boss is not None and self._boss.hp > 0 else None,
            )
            # Skip expensive video frame conversions when menu is open;
            # cached textures still display from last converted frame
            if not menu_open:
                if self._char_video_player.active:
                    cvx, cvy, cvw = self._hud.char_video_rect
                    self._char_video_player.draw_in_hud(cvx, cvy, cvw, aspect=1.0)
                if self._video_player.active:
                    vid_size = STATUS_WIDTH - 20
                    vid_x = 10
                    vid_y = MINIMAP_Y + MINIMAP_H + 20
                    self._video_player.draw_in_hud(vid_x, vid_y, vid_size)

            # Draw station grid, then ship inv, then both drag previews on top
            self._station_inv.draw()
            self.inventory.draw()
            self._station_inv.draw_drag_preview()
            self._build_menu.draw(
                iron=self.inventory.total_iron + self._station_inv.total_iron,
                building_counts=self._building_counts(),
                modules_used=compute_modules_used(self.building_list),
                module_capacity=compute_module_capacity(self.building_list),
                has_home=self._has_home_station(),
            )
            self._station_info.draw()
            self._ship_stats.draw()
            self._craft_menu.draw(self._station_inv.total_iron)
            self._trade_menu.draw()
            # Building hover tooltip
            if (self._hover_building is not None
                    and not menu_open
                    and not self._death_screen.active
                    and not self._build_menu.open
                    and self._placing_building is None
                    and not self._destroy_mode):
                b = self._hover_building
                label = f"{b.building_type}  HP {b.hp}/{b.max_hp}"
                self._t_building_tip.text = label
                tx = self._hover_screen_x
                ty = self._hover_screen_y + 20
                tw = len(label) * 7 + 16
                th = 18
                tx0 = max(2, min(self.window.width - tw - 2, tx - tw // 2))
                if ty + th > self.window.height:
                    ty = self._hover_screen_y - 22
                arcade.draw_rect_filled(
                    arcade.LBWH(tx0, ty, tw, th), (10, 10, 30, 220),
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(tx0, ty, tw, th),
                    arcade.color.STEEL_BLUE, border_width=1,
                )
                self._t_building_tip.x = tx0 + tw // 2
                self._t_building_tip.y = ty + 2
                self._t_building_tip.draw()
            # Boss HP bar (top of play area)
            if self._boss is not None and self._boss.hp > 0:
                bar_w = 400
                bar_h = 16
                bar_x = STATUS_WIDTH + (self.window.width - STATUS_WIDTH - bar_w) // 2
                bar_y = self.window.height - 40
                # Background
                arcade.draw_rect_filled(
                    arcade.LBWH(bar_x, bar_y, bar_w, bar_h), (30, 10, 10, 220))
                # Shield bar (cyan, on top portion)
                if self._boss.shields > 0:
                    sw = int(bar_w * self._boss.shields / self._boss.max_shields)
                    arcade.draw_rect_filled(
                        arcade.LBWH(bar_x, bar_y + bar_h // 2, sw, bar_h // 2),
                        (80, 200, 255, 200))
                # HP bar (red)
                hw = int(bar_w * self._boss.hp / self._boss.max_hp)
                arcade.draw_rect_filled(
                    arcade.LBWH(bar_x, bar_y, hw, bar_h // 2),
                    (220, 50, 50, 220))
                arcade.draw_rect_outline(
                    arcade.LBWH(bar_x, bar_y, bar_w, bar_h),
                    (200, 60, 60), border_width=1)
                # Label
                phase_str = f"Phase {self._boss.phase}"
                if not hasattr(self, '_t_boss_label'):
                    self._t_boss_label = arcade.Text(
                        "", 0, 0, arcade.color.WHITE, 10, bold=True,
                        anchor_x="center", anchor_y="center")
                self._t_boss_label.text = (
                    f"BOSS  HP {self._boss.hp}/{self._boss.max_hp}  "
                    f"Shield {int(self._boss.shields)}/{self._boss.max_shields}  "
                    f"[{phase_str}]"
                )
                self._t_boss_label.x = bar_x + bar_w // 2
                self._t_boss_label.y = bar_y + bar_h + 10
                self._t_boss_label.draw()
            # Flash message (centered on play area)
            if self._flash_msg:
                play_cx = STATUS_WIDTH + (self.window.width - STATUS_WIDTH) // 2
                play_cy = self.window.height // 2
                self._t_flash.text = self._flash_msg
                self._t_flash.x = play_cx
                self._t_flash.y = play_cy
                tw = len(self._flash_msg) * 8 + 20
                arcade.draw_rect_filled(
                    arcade.LBWH(play_cx - tw // 2, play_cy - 12, tw, 24),
                    (30, 10, 10, 200))
                arcade.draw_rect_outline(
                    arcade.LBWH(play_cx - tw // 2, play_cy - 12, tw, 24),
                    (200, 60, 60), border_width=1)
                self._t_flash.draw()
            # Boss spawn announcement (large dramatic text)
            if self._boss_announce_timer > 0.0:
                play_cx = STATUS_WIDTH + (self.window.width - STATUS_WIDTH) // 2
                play_cy = self.window.height // 2 + 40
                # Pulsing alpha based on timer
                pulse = abs(math.sin(self._boss_announce_timer * 3.0))
                alpha = int(180 + 75 * pulse)
                # Dark overlay band
                band_h = 120
                arcade.draw_rect_filled(
                    arcade.LBWH(STATUS_WIDTH, play_cy - band_h // 2,
                                self.window.width - STATUS_WIDTH, band_h),
                    (10, 0, 0, 180))
                # Main title
                self._t_boss_announce.text = "WARNING: BOSS INCOMING"
                self._t_boss_announce.color = (255, 60, 60, alpha)
                self._t_boss_announce.x = play_cx
                self._t_boss_announce.y = play_cy + 10
                self._t_boss_announce.draw()
                # Subtitle
                self._t_boss_subtitle.text = "A massive enemy approaches your station!"
                self._t_boss_subtitle.color = (255, 180, 180, alpha)
                self._t_boss_subtitle.x = play_cx
                self._t_boss_subtitle.y = play_cy - 30
                self._t_boss_subtitle.draw()
            self._escape_menu.draw()
            self._death_screen.draw()


    def _draw_background(
        self, cx: float, cy: float, hw: float, hh: float
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
                    self.bg_texture,
                    arcade.LBWH(tx, ty, ts, ts),
                )
                ty += ts
            tx += ts

    # ── Update ───────────────────────────────────────────────────────────────
    def on_update(self, delta_time: float) -> None:
        # ── Manual GC — run once when ESC menu first opens
        if self._escape_menu.open and not self._gc_ran:
            gc.collect()
            self._gc_ran = True
        elif not self._escape_menu.open:
            self._gc_ran = False
        # ── Smoothed FPS ────────────────────────────────────────────────────
        self._hud.update_fps(delta_time)
        # Sync FPS display from config (may change via Config menu)
        self._hud._show_fps = audio.show_fps

        # ── Character video player update (silent, segment rotation) ────
        if self._char_video_player.active:
            self._char_video_player.update_volume(0.0)

        # ── Video player update ────────────────────────────────────────────
        if self._video_player.active:
            self._video_player.update(audio.music_volume)
        else:
            # ── Background music: sync volume + advance to next track ─────
            if self._music_player is not None:
                self._music_player.volume = audio.music_volume
                if not self._music_player.playing:
                    self._play_next_track()

        # ── Escape menu tick ──────────────────────────────────────────────
        self._escape_menu.update(delta_time)

        # ── Death screen ──────────────────────────────────────────────────
        if self._player_dead:
            # Still update explosions/fire sparks during death delay
            for exp in list(self.explosion_list):
                exp.update_explosion(delta_time)
            for fs in self.fire_sparks:
                fs.update(delta_time)
            self.fire_sparks = [fs for fs in self.fire_sparks if not fs.dead]

            if hasattr(self, '_death_delay') and self._death_delay > 0:
                self._death_delay -= delta_time
                if self._death_delay <= 0:
                    self._death_screen.show()
            return  # No more gameplay updates

        # ── Shake timer tick ────────────────────────────────────────────────
        if self._shake_timer > 0.0:
            self._shake_timer = max(0.0, self._shake_timer - delta_time)
        # ── Flash message timer ────────────────────────────────────────────
        if self._flash_timer > 0.0:
            self._flash_timer = max(0.0, self._flash_timer - delta_time)
            if self._flash_timer <= 0.0:
                self._flash_msg = ""
        if self._boss_announce_timer > 0.0:
            self._boss_announce_timer = max(0.0, self._boss_announce_timer - delta_time)

        # ── Repair Module: check proximity once for shield/HP/building ───
        has_repair = any(
            isinstance(b, RepairModule) and not b.disabled
            for b in self.building_list
        )
        repair_near_home = False
        if has_repair:
            home = None
            for b in self.building_list:
                if isinstance(b, HomeStation) and not b.disabled:
                    home = b
                    break
            if home is not None:
                dist = math.hypot(
                    self.player.center_x - home.center_x,
                    self.player.center_y - home.center_y,
                )
                if dist <= REPAIR_RANGE:
                    repair_near_home = True

        # ── Shield regeneration (boosted by Repair Module near home) ──────
        if self.player.shields < self.player.max_shields:
            regen = self.player._shield_regen
            if repair_near_home:
                regen += REPAIR_SHIELD_BOOST
            self.player._shield_acc += regen * delta_time
            pts = int(self.player._shield_acc)
            if pts > 0:
                self.player._shield_acc -= pts
                self.player.shields = min(self.player.max_shields,
                                          self.player.shields + pts)

        # ── Repair Module: heal player HP when near Home Station ─────────
        if repair_near_home and self.player.hp < self.player.max_hp:
            self._repair_acc += REPAIR_RATE * delta_time
            pts = int(self._repair_acc)
            if pts > 0:
                self._repair_acc -= pts
                self.player.hp = min(
                    self.player.max_hp, self.player.hp + pts
                )

        # ── Repair Module: heal damaged station buildings ─────────────────
        if has_repair:
            any_damaged = any(
                not b.disabled and b.hp < b.max_hp
                for b in self.building_list
            )
            if any_damaged:
                self._building_repair_acc += REPAIR_RATE * delta_time
                pts = int(self._building_repair_acc)
                if pts > 0:
                    self._building_repair_acc -= pts
                    for b in self.building_list:
                        if not b.disabled and b.hp < b.max_hp:
                            b.heal(pts)

        # ── Crafting tick ──────────────────────────────────────────────────
        for b in self.building_list:
            if isinstance(b, BasicCrafter) and b.crafting and not b.disabled:
                b.craft_timer += delta_time
                if b.craft_timer >= b.craft_total:
                    b.crafting = False
                    b.craft_timer = 0.0
                    target = self._craft_menu._craft_target
                    if target and target in MODULE_TYPES:
                        # Produce a module item
                        self._station_inv.add_item(f"mod_{target}", 1)
                    else:
                        # Produce repair packs
                        self._station_inv.add_item("repair_pack", CRAFT_RESULT_COUNT)

        # Update craft menu progress if open
        if self._craft_menu.open and self._active_crafter is not None:
            self._craft_menu.update(
                self._active_crafter.craft_progress,
                self._active_crafter.crafting,
            )

        # ── Fog of war ──────────────────────────────────────────────────────
        self._update_fog()

        # ── Movement input (suppressed while escape menu is open) ──────────
        if self._escape_menu.open:
            rl = rr = tf = tb = sl = sr = fire = False
        else:
            rl = arcade.key.LEFT in self._keys or arcade.key.A in self._keys
            rr = arcade.key.RIGHT in self._keys or arcade.key.D in self._keys
            tf = arcade.key.UP in self._keys or arcade.key.W in self._keys
            tb = arcade.key.DOWN in self._keys or arcade.key.S in self._keys
            sl = arcade.key.Q in self._keys
            sr = arcade.key.E in self._keys
            fire = arcade.key.SPACE in self._keys

        if self.joystick and not self._escape_menu.open:
            lx = self.joystick.leftx
            ly = self.joystick.lefty
            rl |= lx < -DEAD_ZONE
            rr |= lx > DEAD_ZONE
            tf |= ly >  DEAD_ZONE
            tb |= ly < -DEAD_ZONE

            fire |= bool(getattr(self.joystick, "a", False))

            rb = bool(getattr(self.joystick, "rightshoulder", False))
            if rb and not self._prev_rb:
                self._cycle_weapon()
            self._prev_rb = rb

            y_btn = bool(getattr(self.joystick, "y", False))
            if y_btn and not self._prev_y:
                self.inventory.toggle()
            self._prev_y = y_btn

        self.player.apply_input(delta_time, rl, rr, tf, tb, sl, sr)

        # ── Shield sprite position + animation (after movement so it tracks exactly) ─
        self.shield_sprite.update_shield(
            delta_time,
            self.player.center_x, self.player.center_y,
            self.player.shields,
        )
        # Shield enhancer ring rotation (opposite direction to shield)
        from constants import SHIELD_ROT_SPEED
        self._enhancer_angle = (self._enhancer_angle + SHIELD_ROT_SPEED * delta_time) % 360.0

        # ── Thruster sound management ─────────────────────────────────────
        thrusting_now = tf or tb
        if thrusting_now and not self._thrusting_last:
            self._thruster_player = arcade.play_sound(
                self._thruster_snd, volume=0.25, loop=True
            )
        elif not thrusting_now and self._thrusting_last:
            if self._thruster_player is not None:
                arcade.stop_sound(self._thruster_player)
                self._thruster_player = None
        self._thrusting_last = thrusting_now

        # ── Contrail particles ─────────────────────────────────────────────
        intensity = self.player.thrust_intensity
        if intensity > 0.01:
            self._contrail_timer += delta_time
            interval = 1.0 / CONTRAIL_SPAWN_RATE
            while self._contrail_timer >= interval:
                self._contrail_timer -= interval
                if len(self._contrail) < CONTRAIL_MAX_PARTICLES:
                    rad = math.radians(self.player.heading)
                    ex = self.player.center_x - math.sin(rad) * abs(CONTRAIL_OFFSET)
                    ey = self.player.center_y - math.cos(rad) * abs(CONTRAIL_OFFSET)
                    # Add slight random spread
                    ex += random.uniform(-3, 3)
                    ey += random.uniform(-3, 3)
                    start_sz = CONTRAIL_START_SIZE * intensity
                    self._contrail.append(ContrailParticle(
                        ex, ey,
                        self._contrail_start_colour,
                        self._contrail_end_colour,
                        CONTRAIL_LIFETIME,
                        start_sz, CONTRAIL_END_SIZE,
                    ))
        else:
            self._contrail_timer = 0.0

        for cp in self._contrail:
            cp.update(delta_time)
        self._contrail = [p for p in self._contrail if not p.dead]

        # ── Weapons: tick cooldowns ─────────────────────────────────────────
        for w in self._weapons:
            w.update(delta_time)

        # ── Fire active weapon ──────────────────────────────────────────────
        if fire:
            spawn_pts = self.player.gun_spawn_points()
            gun_count = self.player.guns
            base_idx = (self._weapon_idx // gun_count) * gun_count
            for gi in range(gun_count):
                wpn = self._weapons[base_idx + gi]
                pt = spawn_pts[gi] if gi < len(spawn_pts) else spawn_pts[0]
                proj = wpn.fire(pt[0], pt[1], self.player.heading)
                if proj is not None:
                    self.projectile_list.append(proj)

        # ── Broadside module auto-fire ──────────────────────────────────────
        if "broadside" in self._module_slots and not self._player_dead:
            self._broadside_cd -= delta_time
            if self._broadside_cd <= 0.0 and fire:
                self._broadside_cd = BROADSIDE_COOLDOWN
                from sprites.projectile import Projectile
                heading = self.player.heading
                cx, cy = self.player.center_x, self.player.center_y
                for angle_offset in (90.0, -90.0):
                    proj = Projectile(
                        self._broadside_tex, cx, cy,
                        heading + angle_offset,
                        BROADSIDE_SPEED, BROADSIDE_RANGE,
                        scale=1.0, mines_rock=False,
                        damage=BROADSIDE_DAMAGE,
                    )
                    self.projectile_list.append(proj)

        # ── Advance projectiles ─────────────────────────────────────────────
        for proj in list(self.projectile_list):
            proj.update_projectile(delta_time)

        # ── Collision handling (delegated to collisions module) ─────────────
        handle_projectile_hits(self)
        handle_ship_asteroid_collision(self)

        # ── Animate asteroids ───────────────────────────────────────────────
        for asteroid in self.asteroid_list:
            asteroid.update_asteroid(delta_time)

        # ── Iron pickup: fly toward ship + collect ──────────────────────────
        sx, sy = self.player.center_x, self.player.center_y
        for pickup in list(self.iron_pickup_list):
            collected = pickup.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_item("iron", pickup.amount)

        # ── Blueprint pickup: fly toward ship + collect ─────────────────────
        for bp in list(self.blueprint_pickup_list):
            collected = bp.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_item(bp.item_type, 1)

        # ── Alien ship AI + movement ────────────────────────────────────────
        px, py = self.player.center_x, self.player.center_y
        for alien in list(self.alien_list):
            proj = alien.update_alien(
                delta_time, px, py,
                self.asteroid_list, self.alien_list,
            )
            if proj is not None:
                self.alien_projectile_list.append(proj)

        # ── Alien collisions (delegated to collisions module) ───────────────
        handle_alien_player_collision(self)
        handle_alien_asteroid_collision(self)
        handle_alien_alien_collision(self)

        # ── Advance alien projectiles ───────────────────────────────────────
        for proj in list(self.alien_projectile_list):
            proj.update_projectile(delta_time)

        # ── Alien laser hits on player ──────────────────────────────────────
        handle_alien_laser_hits(self)

        # ── Building updates ────────────────────────────────────────────────
        for b in list(self.building_list):
            b.update_building(delta_time)
            if isinstance(b, Turret):
                b.update_turret(delta_time, self.alien_list,
                                self.turret_projectile_list)

        # ── Advance turret projectiles ──────────────────────────────────────
        for proj in list(self.turret_projectile_list):
            proj.update_projectile(delta_time)

        # ── Turret projectile hits on aliens ────────────────────────────────
        handle_turret_projectile_hits(self)

        # ── Alien laser hits on buildings ───────────────────────────────────
        handle_alien_laser_building_hits(self)

        # ── Alien vs building collisions ────────────────────────────────────
        handle_alien_building_collision(self)

        # ── Player vs building collision (gentle push-out, no damage) ──
        handle_ship_building_collision(self)

        # ── Station info live stats update ────────────────────────────
        if self._station_info.open:
            self._station_info.update_stats(
                self.inventory.total_iron,
                len(self.asteroid_list),
                len(self.alien_list),
            )
        # ── Station info auto-close when player moves away ────────────
        if self._station_info.open:
            near = any(
                math.hypot(self.player.center_x - b.center_x,
                           self.player.center_y - b.center_y) < 400.0
                for b in self.building_list
            )
            if not near:
                self._station_info.open = False

        # ── Respawn asteroids and aliens on timer ─────────────────────────
        self._asteroid_respawn_timer += delta_time
        if self._asteroid_respawn_timer >= RESPAWN_INTERVAL:
            self._asteroid_respawn_timer = 0.0
            self._try_respawn_asteroids()

        self._alien_respawn_timer += delta_time
        if self._alien_respawn_timer >= RESPAWN_INTERVAL:
            self._alien_respawn_timer = 0.0
            self._try_respawn_aliens()

        # ── Boss encounter ──────────────────────────────────────────────────
        self._check_boss_spawn()
        if self._boss is not None and self._boss.hp > 0:
            # Find station target
            station_x, station_y = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
            for b in self.building_list:
                if isinstance(b, HomeStation) and not b.disabled:
                    station_x, station_y = b.center_x, b.center_y
                    break
            projs = self._boss.update_boss(
                delta_time,
                self.player.center_x, self.player.center_y,
                station_x, station_y,
                self.asteroid_list,
            )
            for p in projs:
                self._boss_projectile_list.append(p)
            # Advance boss projectiles
            for proj in list(self._boss_projectile_list):
                proj.update_projectile(delta_time)
            # Boss collision handlers
            handle_boss_projectile_hits(self)
            handle_boss_laser_hits(self)
            handle_boss_player_collision(self)
            handle_boss_building_hits(self)
            if self._boss._charging and self._boss._charge_windup <= 0.0:
                handle_boss_charge_hit(self)

        # ── Advance explosion animations ────────────────────────────────────
        for exp in list(self.explosion_list):
            exp.update_explosion(delta_time)

        # ── Advance hit sparks ──────────────────────────────────────────────
        for spark in self.hit_sparks:
            spark.update(delta_time)
        self.hit_sparks = [s for s in self.hit_sparks if not s.dead]

        # ── Advance fire sparks ────────────────────────────────────────────
        for fs in self.fire_sparks:
            fs.update(delta_time)
        self.fire_sparks = [fs for fs in self.fire_sparks if not fs.dead]


    # ── Input ────────────────────────────────────────────────────────────────
    def on_key_press(self, key: int, modifiers: int) -> None:
        if self._death_screen.active:
            self._death_screen.on_key_press(key)
            return
        if key == arcade.key.ESCAPE:
            if self._trade_menu.open:
                self._trade_menu.on_key_press(key)
                return
            if self._craft_menu.open:
                self._craft_menu.open = False
                self._active_crafter = None
                return
            if self._station_inv.open:
                self._station_inv.open = False
                return
            if self._station_info.open:
                self._station_info.open = False
                return
            if self._ship_stats.open:
                self._ship_stats.open = False
                return
            if self._destroy_mode:
                self._exit_destroy_mode()
            elif self._placing_building is not None:
                self._cancel_placement()
            elif self._build_menu.open:
                self._build_menu.toggle()
            elif self._escape_menu.open:
                # Let menu handle ESC (go back from sub-mode, or close)
                self._escape_menu.on_key_press(key, modifiers)
            elif self.inventory.open:
                self.inventory.toggle()
            else:
                self._escape_menu.toggle()
            return
        if self._escape_menu.open:
            self._escape_menu.on_key_press(key, modifiers)
            return
        self._keys.add(key)
        if key == arcade.key.TAB:
            self._cycle_weapon()
        elif key == arcade.key.I:
            self.inventory.toggle()
        elif key == arcade.key.F:
            self._hud.toggle_fps()
            audio.show_fps = self._hud.show_fps
        elif key == arcade.key.B:
            if not self._escape_menu.open and not self._player_dead:
                if self._destroy_mode:
                    self._exit_destroy_mode()
                    return
                if self._placing_building is not None:
                    self._cancel_placement()
                self._build_menu.toggle()
        elif key == arcade.key.T:
            if not self._escape_menu.open and not self._player_dead:
                # Only open if player is near a building
                near = any(
                    math.hypot(self.player.center_x - b.center_x,
                               self.player.center_y - b.center_y) < STATION_INFO_RANGE
                    for b in self.building_list
                )
                if near or self._station_info.open:
                    self._station_info.toggle(
                        self.building_list,
                        compute_modules_used(self.building_list),
                        compute_module_capacity(self.building_list),
                        iron=self.inventory.total_iron,
                        asteroid_count=len(self.asteroid_list),
                        alien_count=len(self.alien_list),
                    )
        elif key == arcade.key.C:
            if not self._escape_menu.open and not self._player_dead:
                self._ship_stats.refresh(
                    self.player, self._faction, self._ship_type,
                    self._module_slots,
                    char_name=audio.character_name,
                    char_xp=self._char_xp,
                    char_level=self._char_level)
                self._ship_stats.toggle()
        # Quick-use keys 1-9 and 0
        elif key in (arcade.key.KEY_1, arcade.key.KEY_2, arcade.key.KEY_3,
                     arcade.key.KEY_4, arcade.key.KEY_5, arcade.key.KEY_6,
                     arcade.key.KEY_7, arcade.key.KEY_8, arcade.key.KEY_9,
                     arcade.key.KEY_0):
            if not self._escape_menu.open and not self._player_dead:
                slot = (key - arcade.key.KEY_1) if key != arcade.key.KEY_0 else 9
                item = self._hud.get_quick_use(slot)
                if item == "repair_pack":
                    self._use_repair_pack(slot)

    def on_key_release(self, key: int, modifiers: int) -> None:
        self._keys.discard(key)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        if button == arcade.MOUSE_BUTTON_LEFT:
            if self._death_screen.active:
                action = self._death_screen.on_mouse_press(x, y)
                if action:
                    self._handle_death_action(action)
                return
            if self._escape_menu.open:
                self._escape_menu.on_mouse_press(x, y)
                return
            # Destroy mode — click to destroy a building
            if self._destroy_mode:
                wx = self.world_cam.position[0] - self.window.width / 2 + x
                wy = self.world_cam.position[1] - self.window.height / 2 + y
                self._destroy_building_at(wx, wy)
                return
            # Placement mode — click to place
            if self._placing_building is not None:
                if self._ghost_sprite is not None:
                    self._place_building(
                        self._ghost_sprite.center_x,
                        self._ghost_sprite.center_y,
                    )
                return
            # Module slot click — start drag if slot has a module
            mod_click = self._hud.module_slot_at(x, y)
            if mod_click is not None and not self._player_dead:
                mod = self._hud.get_module_slot(mod_click)
                if mod is not None:
                    self._hud._mod_drag_src = mod_click
                    self._hud._mod_drag_type = mod
                    self._hud._mod_drag_x = x
                    self._hud._mod_drag_y = y
                    return
            # Quick-use slot click — start drag if slot has an item
            qu_slot = self._hud.slot_at(x, y)
            if qu_slot is not None and not self._player_dead:
                item = self._hud.get_quick_use(qu_slot)
                if item is not None:
                    self._hud._qu_drag_src = qu_slot
                    self._hud._qu_drag_type = item
                    self._hud._qu_drag_count = self._hud._qu_counts[qu_slot]
                    self._hud._qu_drag_x = x
                    self._hud._qu_drag_y = y
                return
            # Build menu click
            if self._build_menu.open:
                selected = self._build_menu.on_mouse_press(
                    x, y,
                    iron=self.inventory.total_iron + self._station_inv.total_iron,
                    building_counts=self._building_counts(),
                    modules_used=compute_modules_used(self.building_list),
                    module_capacity=compute_module_capacity(self.building_list),
                    has_home=self._has_home_station(),
                )
                if selected is not None:
                    if selected == "__destroy__":
                        self._enter_destroy_mode()
                    else:
                        self._enter_placement_mode(selected)
                return
            # Station inventory click
            if self._station_inv.open:
                if self._station_inv.on_mouse_press(x, y):
                    return  # started a drag in station inv
            # Craft menu click
            if self._craft_menu.open:
                action = self._craft_menu.on_mouse_press(
                    x, y, self._station_inv.total_iron
                )
                if action is not None and self._active_crafter is not None:
                    if action == "cancel_craft":
                        # Return iron and stop crafting
                        from character_data import craft_cost_multiplier
                        target = self._craft_menu._craft_target
                        _ccm = craft_cost_multiplier(audio.character_name, self._char_level)
                        if target and target in MODULE_TYPES:
                            refund = int(MODULE_TYPES[target]["craft_cost"] * _ccm)
                        else:
                            refund = int(CRAFT_IRON_COST * _ccm)
                        self._station_inv.add_item("iron", refund)
                        self._active_crafter.crafting = False
                        self._active_crafter.craft_timer = 0.0
                        self._craft_menu._craft_target = ""
                    elif action == "craft":
                        from character_data import craft_cost_multiplier
                        _craft_cost = int(CRAFT_IRON_COST * craft_cost_multiplier(
                            audio.character_name, self._char_level))
                        self._station_inv.remove_item("iron", _craft_cost)
                        self._active_crafter.crafting = True
                        self._active_crafter.craft_timer = 0.0
                        self._active_crafter.craft_total = CRAFT_TIME
                        self._craft_menu._craft_target = ""
                    elif action.startswith("craft_module:"):
                        from character_data import craft_cost_multiplier
                        mod_key = action.split(":", 1)[1]
                        info = MODULE_TYPES[mod_key]
                        _craft_cost = int(info["craft_cost"] * craft_cost_multiplier(
                            audio.character_name, self._char_level))
                        self._station_inv.remove_item("iron", _craft_cost)
                        self._active_crafter.crafting = True
                        self._active_crafter.craft_timer = 0.0
                        self._active_crafter.craft_total = CRAFT_TIME
                        self._craft_menu._craft_target = mod_key
                if not self._craft_menu.open:
                    self._active_crafter = None
                return
            # Trade menu click
            if self._trade_menu.open:
                action = self._trade_menu.on_mouse_press(
                    x, y, inventory=self.inventory, station_inv=self._station_inv)
                if action is not None:
                    if action.startswith("sell:"):
                        _, item_type, amt_str = action.split(":")
                        amt = int(amt_str)
                        # Remove from ship inv first, then station
                        ship_has = self.inventory.count_item(item_type)
                        if ship_has >= amt:
                            self.inventory.remove_item(item_type, amt)
                        else:
                            if ship_has > 0:
                                self.inventory.remove_item(item_type, ship_has)
                            self._station_inv.remove_item(item_type, amt - ship_has)
                        self._trade_menu._refresh_sell_list(self.inventory, self._station_inv)
                    elif action.startswith("buy:"):
                        _, item_type, qty_str = action.split(":")
                        self.inventory.add_item(item_type, int(qty_str))
                if not self._trade_menu.open:
                    pass
                return
            # Click on world buildings (Home Station → inv, Crafter → craft menu)
            if not self._build_menu.open and not self._player_dead:
                wx = self.world_cam.position[0] - self.window.width / 2 + x
                wy = self.world_cam.position[1] - self.window.height / 2 + y
                # Check trading station click
                if self._trade_station is not None:
                    ts = self._trade_station
                    if math.hypot(wx - ts.center_x, wy - ts.center_y) < 80:
                        dist = math.hypot(self.player.center_x - ts.center_x,
                                          self.player.center_y - ts.center_y)
                        if dist < STATION_INFO_RANGE:
                            self._trade_menu.toggle(
                                inventory=self.inventory,
                                station_inv=self._station_inv)
                            return
                for b in self.building_list:
                    if math.hypot(wx - b.center_x, wy - b.center_y) < 40:
                        dist_to_player = math.hypot(
                            self.player.center_x - b.center_x,
                            self.player.center_y - b.center_y,
                        )
                        if dist_to_player < STATION_INFO_RANGE:
                            if isinstance(b, HomeStation) and not b.disabled:
                                self._station_inv.toggle()
                                return
                            if isinstance(b, BasicCrafter) and not b.disabled:
                                self._active_crafter = b
                                self._craft_menu.refresh_recipes(self._station_inv)
                                self._craft_menu.toggle()
                                self._craft_menu.update(
                                    b.craft_progress, b.crafting,
                                )
                                return
            self.inventory.on_mouse_press(x, y)

    def _handle_death_action(self, action: str) -> None:
        """Process an action string from the death screen."""
        if action == "main_menu":
            self._return_to_menu()
        elif action == "exit":
            arcade.exit()
        elif action.startswith("load:"):
            slot = int(action.split(":")[1])
            self._load_game(slot)

    def on_mouse_drag(
        self, x: int, y: int, dx: int, dy: int, buttons: int, modifiers: int
    ) -> None:
        if self._escape_menu.open:
            self._escape_menu.on_mouse_motion(x, y)
            return
        if self._hud._qu_drag_src is not None:
            self._hud._qu_drag_x = x
            self._hud._qu_drag_y = y
        if self._hud._mod_drag_src is not None:
            self._hud._mod_drag_x = x
            self._hud._mod_drag_y = y
        self._station_inv.on_mouse_drag(x, y)
        self.inventory.on_mouse_drag(x, y)

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
        if self._escape_menu.open:
            self._escape_menu.on_mouse_release(x, y)
            return
        if button == arcade.MOUSE_BUTTON_LEFT:
            # Module drag release
            if self._hud._mod_drag_src is not None:
                src = self._hud._mod_drag_src
                mod_type = self._hud._mod_drag_type
                self._hud._mod_drag_src = None
                self._hud._mod_drag_type = None
                target = self._hud.module_slot_at(x, y)
                if target is not None and target != src:
                    # Swap module slots
                    other = self._module_slots[target]
                    self._module_slots[target] = mod_type
                    self._module_slots[src] = other
                elif target == src:
                    # Dropped on same slot — no change
                    pass
                else:
                    # Dropped outside module slots — return to ship inventory
                    self._module_slots[src] = None
                    self.inventory.add_item(f"mod_{mod_type}", 1)
                self.player.apply_modules(self._module_slots)
                self._hud._mod_slots = list(self._module_slots)
                return
            # Quick-use drag release
            if self._hud._qu_drag_src is not None:
                src = self._hud._qu_drag_src
                dt = self._hud._qu_drag_type
                dc = self._hud._qu_drag_count
                self._hud._qu_drag_src = None
                self._hud._qu_drag_type = None
                self._hud._qu_drag_count = 0
                target = self._hud.slot_at(x, y)
                if target is not None and target != src:
                    # Move to different slot — swap contents
                    dst_type = self._hud.get_quick_use(target)
                    dst_count = self._hud._qu_counts[target]
                    self._hud.set_quick_use(target, dt, dc)
                    self._hud.set_quick_use(src, dst_type, dst_count)
                elif target == src:
                    # Released on same slot — use the item
                    if dt == "repair_pack":
                        self._use_repair_pack(src)
                else:
                    # Released outside any slot — unassign from quick-use
                    self._hud.set_quick_use(src, None, 0)
                return
            # Station inventory drop — transfer to ship inv
            station_drop = self._station_inv.on_mouse_release(x, y)
            if station_drop is not None:
                item_type, amount = station_drop
                # Check if dropped on a module slot
                mod_slot = self._hud.module_slot_at(x, y)
                is_module = item_type.startswith("mod_") or item_type.startswith("bp_")
                if mod_slot is not None and is_module:
                    prefix = "mod_" if item_type.startswith("mod_") else "bp_"
                    mod_key = item_type[len(prefix):]
                    if mod_key in self._module_slots:
                        # Already equipped — return to station
                        self._station_inv.add_item(item_type, amount)
                    else:
                        old = self._module_slots[mod_slot]
                        if old is not None:
                            self._station_inv.add_item(f"mod_{old}", 1)
                        self._module_slots[mod_slot] = mod_key
                        if amount > 1:
                            self._station_inv.add_item(item_type, amount - 1)
                        self.player.apply_modules(self._module_slots)
                        self._hud._mod_slots = list(self._module_slots)
                elif mod_slot is not None:
                    self._station_inv.add_item(item_type, amount)
                # Check if dropped on a quick-use slot
                elif (qu_slot := self._hud.slot_at(x, y)) is not None and item_type == "repair_pack":
                    # Assign repair pack to quick-use slot; put item into cargo
                    self.inventory.add_item(item_type, amount)
                    total = self.inventory.count_item("repair_pack")
                    # Clear any other slot that already has repair_pack
                    for s in range(QUICK_USE_SLOTS):
                        if s != qu_slot and self._hud.get_quick_use(s) == "repair_pack":
                            self._hud.set_quick_use(s, None, 0)
                    self._hud.set_quick_use(qu_slot, "repair_pack", total)
                else:
                    # Try exact cell, then nearest empty cell to cursor
                    target_cell = self.inventory._cell_at(x, y)
                    if (target_cell is not None
                            and target_cell not in self.inventory._items):
                        self.inventory._items[target_cell] = (item_type, amount)
                    else:
                        nearest = self.inventory._nearest_empty_cell(x, y)
                        if nearest is not None:
                            self.inventory._items[nearest] = (item_type, amount)
                        else:
                            self.inventory.add_item(item_type, amount)
                    # Update quick-use if repair_pack is assigned
                    if item_type == "repair_pack":
                        for slot in range(QUICK_USE_SLOTS):
                            if self._hud.get_quick_use(slot) == "repair_pack":
                                self._hud.set_quick_use(
                                    slot, "repair_pack",
                                    self.inventory.count_item("repair_pack"),
                                )
            ejected = self.inventory.on_mouse_release(x, y)
            if ejected is not None:
                item_type, amount = ejected
                # Check if dropped on a module slot (mod_ or bp_ items)
                mod_slot = self._hud.module_slot_at(x, y)
                is_module = item_type.startswith("mod_") or item_type.startswith("bp_")
                if mod_slot is not None and is_module:
                    prefix = "mod_" if item_type.startswith("mod_") else "bp_"
                    mod_key = item_type[len(prefix):]
                    # Check uniqueness — only 1 of each type allowed
                    if mod_key in self._module_slots:
                        self.inventory.add_item(item_type, amount)
                    else:
                        # Unequip existing module in this slot (return to inv)
                        old = self._module_slots[mod_slot]
                        if old is not None:
                            self.inventory.add_item(f"mod_{old}", 1)
                        self._module_slots[mod_slot] = mod_key
                        # Consume 1 item, return remainder
                        if amount > 1:
                            self.inventory.add_item(item_type, amount - 1)
                        self.player.apply_modules(self._module_slots)
                        self._hud._mod_slots = list(self._module_slots)
                elif mod_slot is not None:
                    # Non-module item dropped on module slot — put it back
                    self.inventory.add_item(item_type, amount)
                # Check if dropped on a quick-use slot
                elif (qu_slot := self._hud.slot_at(x, y)) is not None and item_type == "repair_pack":
                    # Assign repair pack to quick-use slot; put item back
                    self.inventory.add_item(item_type, amount)
                    total = self.inventory.count_item("repair_pack")
                    # Clear any other slot that already has repair_pack
                    for s in range(QUICK_USE_SLOTS):
                        if s != qu_slot and self._hud.get_quick_use(s) == "repair_pack":
                            self._hud.set_quick_use(s, None, 0)
                    self._hud.set_quick_use(qu_slot, "repair_pack", total)
                elif qu_slot is not None:
                    # Non-assignable item dropped on quick-use — put it back
                    self.inventory.add_item(item_type, amount)
                # Check if dropped onto station inventory panel
                elif self._station_inv.open and self._station_inv._panel_contains(x, y):
                    # Try exact cell, then nearest empty cell to cursor
                    target_cell = self._station_inv._cell_at(x, y)
                    if (target_cell is not None
                            and target_cell not in self._station_inv._items):
                        self._station_inv._items[target_cell] = (item_type, amount)
                    else:
                        nearest = self._station_inv._nearest_empty_cell(x, y)
                        if nearest is not None:
                            self._station_inv._items[nearest] = (item_type, amount)
                        else:
                            self._station_inv.add_item(item_type, amount)
                elif item_type == "iron" and amount > 0:
                    eject_angle = random.uniform(0.0, math.tau)
                    eject_r = SHIP_RADIUS + EJECT_DIST
                    eject_x = max(0.0, min(WORLD_WIDTH,
                                  self.player.center_x + math.cos(eject_angle) * eject_r))
                    eject_y = max(0.0, min(WORLD_HEIGHT,
                                  self.player.center_y + math.sin(eject_angle) * eject_r))
                    self._spawn_iron_pickup(
                        eject_x, eject_y,
                        amount=amount,
                        lifetime=WORLD_ITEM_LIFETIME,
                    )
                elif item_type != "iron" and amount > 0:
                    # Non-iron item ejected to world — just drop it
                    pass  # items other than iron can't become world pickups yet

    def on_mouse_scroll(
        self, x: int, y: int, scroll_x: int, scroll_y: int
    ) -> None:
        """Mouse wheel: rotates ghost during placement, scrolls escape menu lists."""
        if self._escape_menu.open:
            self._escape_menu.on_mouse_scroll(scroll_y)
            return
        if self._ghost_sprite is not None and self._placing_building is not None:
            self._ghost_rotation = (self._ghost_rotation + scroll_y * 15.0) % 360.0
            self._ghost_sprite.angle = self._ghost_rotation

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        if self._death_screen.active:
            self._death_screen.on_mouse_motion(x, y)
            return
        if self._escape_menu.open:
            self._escape_menu.on_mouse_motion(x, y)
            return
        # Track cursor for destroy mode crosshair
        if self._destroy_mode:
            self._destroy_cursor_x = self.world_cam.position[0] - self.window.width / 2 + x
            self._destroy_cursor_y = self.world_cam.position[1] - self.window.height / 2 + y
            return
        if self._build_menu.open:
            self._build_menu.on_mouse_motion(x, y)
        # Ghost sprite follows cursor in world coordinates
        if self._ghost_sprite is not None and self._placing_building is not None:
            # Convert screen pos to world pos
            wx = self.world_cam.position[0] - self.window.width / 2 + x
            wy = self.world_cam.position[1] - self.window.height / 2 + y
            bt = self._placing_building
            stats = BUILDING_TYPES[bt]
            # Snap to port for connectable modules — edge-to-edge preview
            if stats["connectable"]:
                snap = self._find_nearest_snap_port(wx, wy)
                if snap is not None:
                    _, port, sx, sy = snap
                    opp_dir = DockingPort.opposite(port.direction)
                    # Compute ghost's opposite port offset from texture dims
                    ghw = (self._ghost_sprite.width) / 2
                    ghh = (self._ghost_sprite.height) / 2
                    _port_offsets = {"N": (0, ghh), "S": (0, -ghh),
                                     "E": (ghw, 0), "W": (-ghw, 0)}
                    opp_off = _port_offsets.get(opp_dir, (0, 0))
                    rad = math.radians(self._ghost_rotation)
                    cos_a = math.cos(rad)
                    sin_a = math.sin(rad)
                    ox_rot = opp_off[0] * cos_a - opp_off[1] * sin_a
                    oy_rot = opp_off[0] * sin_a + opp_off[1] * cos_a
                    wx = sx - ox_rot
                    wy = sy - oy_rot
            # Turrets must be within radius of Home Station
            if stats["free_place"]:
                home = None
                for b in self.building_list:
                    if isinstance(b, HomeStation):
                        home = b
                        break
                if home is not None:
                    d = math.hypot(wx - home.center_x, wy - home.center_y)
                    if d > TURRET_FREE_PLACE_RADIUS:
                        # Clamp to radius
                        angle = math.atan2(wy - home.center_y, wx - home.center_x)
                        wx = home.center_x + math.cos(angle) * TURRET_FREE_PLACE_RADIUS
                        wy = home.center_y + math.sin(angle) * TURRET_FREE_PLACE_RADIUS
            self._ghost_sprite.center_x = wx
            self._ghost_sprite.center_y = wy
        else:
            self.inventory.on_mouse_move(x, y)
            self._station_inv.on_mouse_motion(x, y)
            # Module slot hover
            mod_slot = self._hud.module_slot_at(x, y)
            self._hud._mod_hover = mod_slot if mod_slot is not None else -1
            # Quick-use slot hover
            qu_hover = self._hud.slot_at(x, y)
            self._hud._qu_hover = qu_hover if qu_hover is not None else -1
            # Module drag tracking
            if self._hud._mod_drag_src is not None:
                self._hud._mod_drag_x = x
                self._hud._mod_drag_y = y
            # Building hover tooltip — detect building under cursor
            wx = self.world_cam.position[0] - self.window.width / 2 + x
            wy = self.world_cam.position[1] - self.window.height / 2 + y
            best = None
            best_dist = 40.0
            for b in self.building_list:
                d = math.hypot(wx - b.center_x, wy - b.center_y)
                if d < best_dist:
                    best_dist = d
                    best = b
            self._hover_building = best
            self._hover_screen_x = x
            self._hover_screen_y = y

    def on_text(self, text: str) -> None:
        if self._escape_menu.open:
            self._escape_menu.on_text(text)
