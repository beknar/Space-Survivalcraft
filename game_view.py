"""GameView -- core gameplay view for Space Survivalcraft."""
from __future__ import annotations

import json
import math
import os
import random
from typing import Optional

import arcade
import arcade.camera
import pyglet.input

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    WORLD_WIDTH, WORLD_HEIGHT, BG_TILE,
    DEAD_ZONE,
    SHIP_RADIUS, ASTEROID_IRON_YIELD,
    SHAKE_DURATION, SHAKE_AMPLITUDE,
    EJECT_DIST, WORLD_ITEM_LIFETIME,
    CONTRAIL_MAX_PARTICLES, CONTRAIL_SPAWN_RATE, CONTRAIL_LIFETIME,
    CONTRAIL_START_SIZE, CONTRAIL_END_SIZE, CONTRAIL_OFFSET, CONTRAIL_COLOURS,
)
from settings import audio
from sprites.projectile import Weapon
from sprites.explosion import Explosion, HitSpark, FireSpark
from sprites.pickup import IronPickup
from sprites.player import PlayerShip
from sprites.contrail import ContrailParticle
from inventory import Inventory
from hud import HUD
from escape_menu import EscapeMenu
from death_screen import DeathScreen
from world_setup import (
    load_bg_texture, load_shield, load_weapons,
    load_explosion_assets, load_bump_sound, load_thruster_sound,
    load_iron_texture, populate_asteroids, populate_aliens,
    collect_music_tracks,
)
from collisions import (
    handle_projectile_hits,
    handle_ship_asteroid_collision,
    handle_alien_player_collision,
    handle_alien_asteroid_collision,
    handle_alien_alien_collision,
    handle_alien_laser_hits,
)

_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")


class GameView(arcade.View):

    def __init__(
        self,
        faction: Optional[str] = None,
        ship_type: Optional[str] = None,
    ) -> None:
        super().__init__()

        self._faction = faction
        self._ship_type = ship_type

        # Player
        self.player = PlayerShip(faction=faction, ship_type=ship_type)
        self.player_list = arcade.SpriteList()
        self.player_list.append(self.player)

        # Shield
        self.shield_sprite, self.shield_list = load_shield(
            self.player.center_x, self.player.center_y
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

        # Alien ships
        self.alien_list, _alien_laser_tex = populate_aliens()
        self.alien_projectile_list: arcade.SpriteList = arcade.SpriteList()
        self.hit_sparks: list[HitSpark] = []
        self.fire_sparks: list[FireSpark] = []

        # Inventory
        self.inventory = Inventory(iron_icon=self._iron_tex)

        # HUD
        self._hud = HUD(
            has_gamepad=self.joystick is not None,
            faction=faction,
            ship_type=ship_type,
        )

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
        self._escape_menu = EscapeMenu(
            save_fn=self._save_game,
            load_fn=self._load_game,
            main_menu_fn=self._return_to_menu,
            save_dir=_SAVE_DIR,
        )

        # Death screen
        self._death_screen = DeathScreen()
        self._player_dead: bool = False

        # Background music — shuffled playlist of loop tracks
        self._music_tracks: list[tuple[arcade.Sound, str]] = collect_music_tracks()
        self._music_idx: int = 0
        self._music_player: Optional[arcade.sound.media.Player] = None
        self._current_track_name: str = ""
        if self._music_tracks:
            self._play_next_track()

    # ── Music ──────────────────────────────────────────────────────────────
    def _play_next_track(self) -> None:
        """Start the next track in the shuffled playlist, wrapping around."""
        if not self._music_tracks:
            return
        track, name = self._music_tracks[self._music_idx]
        self._current_track_name = name
        self._music_player = arcade.play_sound(track, volume=audio.music_volume)
        self._music_idx = (self._music_idx + 1) % len(self._music_tracks)

    def _stop_music(self) -> None:
        """Stop the currently playing music track."""
        if self._music_player is not None:
            arcade.stop_sound(self._music_player)
            self._music_player = None

    # ── Helpers ──────────────────────────────────────────────────────────────
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

    def _trigger_shake(self) -> None:
        """Start a brief camera shake."""
        self._shake_timer = SHAKE_DURATION

    def _apply_damage_to_player(self, amount: int) -> None:
        """Apply damage to the player's shields first, then HP."""
        if self._player_dead:
            return
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

    # ── Save / Load / Menu ─────────────────────────────────────────────────
    def _save_game(self, slot: int, name: str) -> None:
        """Serialize current game state to a numbered save slot."""
        os.makedirs(_SAVE_DIR, exist_ok=True)
        path = os.path.join(_SAVE_DIR, f"save_slot_{slot + 1:02d}.json")
        data: dict = {
            "save_name": name,
            "faction": self._faction,
            "ship_type": self._ship_type,
            "player": {
                "x": self.player.center_x,
                "y": self.player.center_y,
                "heading": self.player.heading,
                "vel_x": self.player.vel_x,
                "vel_y": self.player.vel_y,
                "hp": self.player.hp,
                "shields": self.player.shields,
                "shield_acc": self.player._shield_acc,
            },
            "weapon_idx": self._weapon_idx,
            "iron": self.inventory.iron,
            "asteroids": [
                {
                    "x": a.center_x,
                    "y": a.center_y,
                    "hp": a.hp,
                }
                for a in self.asteroid_list
            ],
            "aliens": [
                {
                    "x": al.center_x,
                    "y": al.center_y,
                    "hp": al.hp,
                    "vel_x": al.vel_x,
                    "vel_y": al.vel_y,
                    "heading": al._heading,
                    "state": al._state,
                    "home_x": al._home_x,
                    "home_y": al._home_y,
                }
                for al in self.alien_list
            ],
            "pickups": [
                {
                    "x": p.center_x,
                    "y": p.center_y,
                    "amount": p.amount,
                }
                for p in self.iron_pickup_list
            ],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_game(self, slot: int) -> None:
        """Load game state from a numbered save slot and rebuild the view."""
        path = os.path.join(_SAVE_DIR, f"save_slot_{slot + 1:02d}.json")
        if not os.path.exists(path):
            self._escape_menu._flash_status("No save file found!")
            return
        with open(path, "r") as f:
            data = json.load(f)

        # Stop sounds before rebuilding
        if self._thruster_player is not None:
            arcade.stop_sound(self._thruster_player)
            self._thruster_player = None
        self._stop_music()

        # Build a new GameView from saved faction/ship
        view = GameView(
            faction=data.get("faction"),
            ship_type=data.get("ship_type"),
        )

        # Restore player state
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

        # Restore weapon index
        view._weapon_idx = data.get("weapon_idx", 0)

        # Restore inventory
        view.inventory.iron = data.get("iron", 0)

        # Restore asteroids — clear default spawn, rebuild from save
        view.asteroid_list.clear()
        from sprites.asteroid import IronAsteroid
        asteroid_tex = arcade.load_texture(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "Pixel Art Space", "Asteroid.png")
        )
        for ad in data.get("asteroids", []):
            a = IronAsteroid(asteroid_tex, ad["x"], ad["y"])
            a.hp = ad["hp"]
            view.asteroid_list.append(a)

        # Restore aliens — clear default spawn, rebuild from save
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

        # Restore iron pickups
        view.iron_pickup_list.clear()
        for pd in data.get("pickups", []):
            view._spawn_iron_pickup(pd["x"], pd["y"], amount=pd.get("amount", 10))

        self.window.show_view(view)

    def _return_to_menu(self) -> None:
        """Return to the splash / title screen."""
        # Stop sounds
        if self._thruster_player is not None:
            arcade.stop_sound(self._thruster_player)
            self._thruster_player = None
        self._stop_music()
        from splash_view import SplashView
        self.window.show_view(SplashView())

    # ── Drawing ──────────────────────────────────────────────────────────────
    def on_draw(self) -> None:
        self.clear()

        hw = SCREEN_WIDTH / 2
        hh = SCREEN_HEIGHT / 2
        cx = max(hw, min(WORLD_WIDTH - hw, self.player.center_x))
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
            self.explosion_list.draw()
            self.alien_list.draw()
            self.alien_projectile_list.draw()
            self.projectile_list.draw()
            # Contrail drawn behind the player ship
            for cp in self._contrail:
                cp.draw()
            self.player_list.draw()
            self.shield_list.draw()
            for spark in self.hit_sparks:
                spark.draw()
            for fs in self.fire_sparks:
                fs.draw()

        with self.ui_cam.activate():
            spd = math.hypot(self.player.vel_x, self.player.vel_y)
            self._hud.draw(
                speed=spd,
                heading=self.player.heading,
                iron=self.inventory.iron,
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
                track_name=self._current_track_name,
            )
            self.inventory.draw()
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
        # ── Smoothed FPS ────────────────────────────────────────────────────
        self._hud.update_fps(delta_time)

        # ── Background music: advance to next track when current ends ─────
        if (self._music_player is not None
                and not self._music_player.playing):
            self._play_next_track()

        # ── Escape menu tick ──────────────────────────────────────────────
        self._escape_menu.update(delta_time)
        if self._escape_menu.open:
            return  # Pause all gameplay while menu is open

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

        # ── Shield regeneration ─────────────────────────────────────────────
        if self.player.shields < self.player.max_shields:
            self.player._shield_acc += self.player._shield_regen * delta_time
            pts = int(self.player._shield_acc)
            if pts > 0:
                self.player._shield_acc -= pts
                self.player.shields = min(self.player.max_shields,
                                          self.player.shields + pts)

        # ── Shield sprite position + animation ──────────────────────────────
        self.shield_sprite.update_shield(
            delta_time,
            self.player.center_x, self.player.center_y,
            self.player.shields,
        )

        # ── Movement input ──────────────────────────────────────────────────
        rl = arcade.key.LEFT in self._keys or arcade.key.A in self._keys
        rr = arcade.key.RIGHT in self._keys or arcade.key.D in self._keys
        tf = arcade.key.UP in self._keys or arcade.key.W in self._keys
        tb = arcade.key.DOWN in self._keys or arcade.key.S in self._keys

        fire = arcade.key.SPACE in self._keys

        if self.joystick:
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

        self.player.apply_input(delta_time, rl, rr, tf, tb)

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
                self.inventory.add_iron(pickup.amount)

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
            if self._escape_menu.open:
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
            else:
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
        if not self._escape_menu.open:
            self.inventory.on_mouse_drag(x, y)

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
        if self._escape_menu.open:
            return
        if button == arcade.MOUSE_BUTTON_LEFT:
            ejected = self.inventory.on_mouse_release(x, y)
            if ejected is not None:
                item_type, amount = ejected
                if item_type == "iron" and amount > 0:
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

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        if self._death_screen.active:
            self._death_screen.on_mouse_motion(x, y)
            return
        if self._escape_menu.open:
            self._escape_menu.on_mouse_motion(x, y)
        else:
            self.inventory.on_mouse_move(x, y)

    def on_text(self, text: str) -> None:
        if self._escape_menu.open:
            self._escape_menu.on_text(text)
