"""GameView -- core gameplay view for Space Survivalcraft."""
from __future__ import annotations

import math
import os
import random
from typing import Optional

import arcade
import arcade.camera
import pyglet.input
from PIL import Image as PILImage

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT, STATUS_WIDTH,
    WORLD_WIDTH, WORLD_HEIGHT, BG_TILE,
    DEAD_ZONE, NOSE_OFFSET,
    SHIP_RADIUS, ASTEROID_RADIUS, ALIEN_RADIUS,
    SHIP_COLLISION_DAMAGE, SHIP_COLLISION_COOLDOWN, SHIP_BOUNCE,
    SHAKE_DURATION, SHAKE_AMPLITUDE,
    ASTEROID_COUNT, ASTEROID_MIN_DIST, ASTEROID_IRON_YIELD,
    EXPLOSION_FRAMES, EXPLOSION_FRAME_W, EXPLOSION_FRAME_H,
    ALIEN_COUNT, ALIEN_MIN_DIST, ALIEN_BOUNCE, ALIEN_SPEED,
    ALIEN_RADIUS, ALIEN_COL_COOLDOWN,
    IRON_PICKUP_DIST, EJECT_DIST, WORLD_ITEM_LIFETIME,
    MINIMAP_PAD, MINIMAP_W, MINIMAP_H, MINIMAP_X, MINIMAP_Y,
    SHIELD_PNG, SHIELD_COLS, SHIELD_ROWS, SHIELD_FRAME_W, SHIELD_FRAME_H,
    STARFIELD_DIR, LASER_DIR, SFX_WEAPONS_DIR, SFX_EXPLOSIONS_DIR, SFX_BIO_DIR,
    SFX_VEHICLES_DIR,
    ASTEROID_PNG, ALIEN_SHIP_PNG, ALIEN_FX_PNG, EXPLOSION_PNG, IRON_ICON_PNG,
    CONTRAIL_MAX_PARTICLES, CONTRAIL_SPAWN_RATE, CONTRAIL_LIFETIME,
    CONTRAIL_START_SIZE, CONTRAIL_END_SIZE, CONTRAIL_OFFSET, CONTRAIL_COLOURS,
)
from sprites.projectile import Projectile, Weapon
from sprites.explosion import Explosion, HitSpark
from sprites.shield import ShieldSprite
from sprites.pickup import IronPickup
from sprites.asteroid import IronAsteroid
from sprites.alien import SmallAlienShip
from sprites.player import PlayerShip
from inventory import Inventory


class ContrailParticle:
    """A single fading, shrinking particle in a ship's engine contrail."""

    def __init__(
        self, x: float, y: float,
        start_colour: tuple[int, int, int],
        end_colour: tuple[int, int, int],
        lifetime: float,
        start_size: float,
        end_size: float,
    ) -> None:
        self.x = x
        self.y = y
        self._start_r, self._start_g, self._start_b = start_colour
        self._end_r, self._end_g, self._end_b = end_colour
        self._lifetime = lifetime
        self._start_size = start_size
        self._end_size = end_size
        self._age: float = 0.0
        self.dead: bool = False

    def update(self, dt: float) -> None:
        self._age += dt
        if self._age >= self._lifetime:
            self.dead = True

    def draw(self) -> None:
        if self.dead:
            return
        t = self._age / self._lifetime  # 0 -> 1
        radius = self._start_size + (self._end_size - self._start_size) * t
        alpha = int(255 * (1.0 - t))
        r = int(self._start_r + (self._end_r - self._start_r) * t)
        g = int(self._start_g + (self._end_g - self._start_g) * t)
        b = int(self._start_b + (self._end_b - self._start_b) * t)
        if radius > 0.5:
            arcade.draw_circle_filled(self.x, self.y, radius, (r, g, b, alpha))


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

        # ── Shield sprite ───────────────────────────────────────────────────
        _pil_shield = PILImage.open(SHIELD_PNG).convert("RGBA")
        _shield_frames: list[arcade.Texture] = []
        for row in range(SHIELD_ROWS):
            for col in range(SHIELD_COLS):
                x0 = col * SHIELD_FRAME_W
                y0 = row * SHIELD_FRAME_H
                _shield_frames.append(
                    arcade.Texture(
                        _pil_shield.crop((x0, y0,
                                          x0 + SHIELD_FRAME_W,
                                          y0 + SHIELD_FRAME_H))
                    )
                )
        self.shield_sprite = ShieldSprite(_shield_frames)
        self.shield_sprite.center_x = self.player.center_x
        self.shield_sprite.center_y = self.player.center_y
        self.shield_list = arcade.SpriteList()
        self.shield_list.append(self.shield_sprite)

        # Active projectiles
        self.projectile_list = arcade.SpriteList()

        # Tiled background texture
        self.bg_texture = arcade.load_texture(
            os.path.join(STARFIELD_DIR, "Starfield_01-1024x1024.png")
        )

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
            self.joystick.open()
            print(f"Gamepad connected: {self.joystick.name}")

        # ── Weapons ─────────────────────────────────────────────────────────
        laser_tex = arcade.load_texture(
            os.path.join(LASER_DIR, "laserBlue03.png")
        )
        mining_tex = arcade.load_texture(
            os.path.join(LASER_DIR, "laserGreen13.png")
        )
        laser_snd = arcade.load_sound(
            os.path.join(SFX_WEAPONS_DIR, "Small Laser Weapon Shot 1.wav")
        )
        mining_snd = arcade.load_sound(
            os.path.join(SFX_WEAPONS_DIR, "Sci-Fi Arc Emitter Weapon Shot 2.wav")
        )
        # Build weapon list — Thunderbolt (guns=2) gets doubled weapons
        gun_count = self.player.guns
        self._weapons: list[Weapon] = []
        for _g in range(gun_count):
            self._weapons.append(Weapon(
                "Basic Laser",
                laser_tex, laser_snd,
                cooldown=0.30, damage=25.0,
                projectile_speed=900.0, max_range=1200.0,
                proj_scale=1.0,
                mines_rock=False,
            ))
        for _g in range(gun_count):
            self._weapons.append(Weapon(
                "Mining Beam",
                mining_tex, mining_snd,
                cooldown=0.10, damage=10.0,
                projectile_speed=500.0, max_range=800.0,
                proj_scale=1.0,
                mines_rock=True,
            ))
        self._weapon_idx: int = 0

        # ── Asteroids ──────────────────────────────────────────────────────
        asteroid_tex = arcade.load_texture(ASTEROID_PNG)
        self._iron_tex = arcade.load_texture(IRON_ICON_PNG)

        exp_ss = arcade.load_spritesheet(EXPLOSION_PNG)
        self._explosion_frames: list[arcade.Texture] = [
            exp_ss.get_texture(
                arcade.LBWH(i * EXPLOSION_FRAME_W, 0, EXPLOSION_FRAME_W, EXPLOSION_FRAME_H)
            )
            for i in range(EXPLOSION_FRAMES)
        ]
        self._explosion_snd = arcade.load_sound(
            os.path.join(SFX_EXPLOSIONS_DIR, "Sci-Fi Deep Explosion 1.wav")
        )

        # Collision bump sound
        self._bump_snd = arcade.load_sound(
            os.path.join(SFX_BIO_DIR, "Game Biomechanical Impact Sound 1.wav")
        )

        self.asteroid_list = arcade.SpriteList()
        self.explosion_list = arcade.SpriteList()
        self.iron_pickup_list = arcade.SpriteList()

        cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        margin = 100
        placed = 0
        attempts = 0
        while placed < ASTEROID_COUNT and attempts < ASTEROID_COUNT * 20:
            attempts += 1
            ax = random.uniform(margin, WORLD_WIDTH - margin)
            ay = random.uniform(margin, WORLD_HEIGHT - margin)
            if math.hypot(ax - cx_world, ay - cy_world) < ASTEROID_MIN_DIST:
                continue
            self.asteroid_list.append(IronAsteroid(asteroid_tex, ax, ay))
            placed += 1

        # ── Alien ships ────────────────────────────────────────────────────
        _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
        alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))

        _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
        _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))
        alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))

        self.alien_list: arcade.SpriteList = arcade.SpriteList()
        self.alien_projectile_list: arcade.SpriteList = arcade.SpriteList()
        self.hit_sparks: list[HitSpark] = []

        placed = 0
        attempts = 0
        while placed < ALIEN_COUNT and attempts < ALIEN_COUNT * 20:
            attempts += 1
            ax = random.uniform(100, WORLD_WIDTH - 100)
            ay = random.uniform(100, WORLD_HEIGHT - 100)
            if math.hypot(ax - cx_world, ay - cy_world) < ALIEN_MIN_DIST:
                continue
            self.alien_list.append(SmallAlienShip(alien_ship_tex, alien_laser_tex, ax, ay))
            placed += 1

        # ── Inventory ──────────────────────────────────────────────────────
        self.inventory = Inventory(iron_icon=self._iron_tex)

        # ── HUD text objects ────────────────────────────────────────────────
        cx = STATUS_WIDTH // 2
        self._t_title    = arcade.Text("STATUS", cx, SCREEN_HEIGHT - 26,
                                       arcade.color.LIGHT_BLUE, 14, bold=True,
                                       anchor_x="center", anchor_y="center")
        self._t_spd      = arcade.Text("", 10, SCREEN_HEIGHT - 60,
                                       arcade.color.WHITE, 11)
        self._t_hdg      = arcade.Text("", 10, SCREEN_HEIGHT - 80,
                                       arcade.color.WHITE, 11)
        self._t_iron_hud = arcade.Text("", 10, SCREEN_HEIGHT - 100,
                                       arcade.color.ORANGE, 11)
        self._t_hp       = arcade.Text("HP",     10, SCREEN_HEIGHT - 140,
                                       arcade.color.LIME_GREEN, 10, bold=True)
        self._t_shield   = arcade.Text("SHIELD", 10, SCREEN_HEIGHT - 176,
                                       arcade.color.CYAN, 10, bold=True)
        self._t_wpn_hdr  = arcade.Text("WEAPON", cx, SCREEN_HEIGHT - 210,
                                       arcade.color.LIGHT_GRAY, 9,
                                       anchor_x="center")
        self._t_wpn_name = arcade.Text("", cx, SCREEN_HEIGHT - 226,
                                       arcade.color.YELLOW, 10, bold=True,
                                       anchor_x="center")
        self._t_ctrl_hdr = arcade.Text("CONTROLS", cx, SCREEN_HEIGHT - 248,
                                       arcade.color.LIGHT_GRAY, 9,
                                       anchor_x="center")
        self._t_ctrl_lines = [
            arcade.Text("L/R  A/D    Rotate",   10, SCREEN_HEIGHT - 266,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Up / W      Thrust",   10, SCREEN_HEIGHT - 282,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Dn / S      Brake",    10, SCREEN_HEIGHT - 298,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Space       Fire",     10, SCREEN_HEIGHT - 314,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Tab         Weapon",   10, SCREEN_HEIGHT - 330,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("I           Inventory",10, SCREEN_HEIGHT - 346,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("F           FPS",      10, SCREEN_HEIGHT - 362,
                        arcade.color.LIGHT_GRAY, 9),
        ]
        self._t_gamepad = (
            arcade.Text("Gamepad: connected", 10, SCREEN_HEIGHT - 382,
                        arcade.color.LIME_GREEN, 9)
            if self.joystick else None
        )
        self._show_fps: bool = False
        self._fps: float = 60.0
        self._t_fps = arcade.Text("", 10, SCREEN_HEIGHT - 400,
                                  arcade.color.YELLOW, 10, bold=True)

        self._t_minimap = arcade.Text(
            "MINI-MAP",
            STATUS_WIDTH // 2,
            MINIMAP_Y + MINIMAP_H + 3,
            arcade.color.LIGHT_GRAY, 9,
            anchor_x="center",
        )

        # ── Faction / ship type HUD labels ─────────────────────────────────
        faction_label = faction if faction else "Legacy"
        ship_label = ship_type if ship_type else "Classic"
        self._t_faction = arcade.Text(
            f"FACTION: {faction_label}",
            10, SCREEN_HEIGHT - 420,
            arcade.color.LIGHT_BLUE, 9, bold=True,
        )
        self._t_ship_type = arcade.Text(
            f"SHIP: {ship_label}",
            10, SCREEN_HEIGHT - 436,
            arcade.color.LIGHT_GREEN, 9, bold=True,
        )

        # ── Thruster sound ──────────────────────────────────────────────────
        self._thruster_snd = arcade.load_sound(
            os.path.join(SFX_VEHICLES_DIR, "Sci-Fi Spaceship Thrusters 1.wav")
        )
        self._thruster_player: Optional[arcade.sound.media.Player] = None
        self._thrusting_last: bool = False

        # ── Contrail state ──────────────────────────────────────────────────
        self._contrail: list[ContrailParticle] = []
        self._contrail_timer: float = 0.0
        st = ship_type or "Cruiser"
        colours = CONTRAIL_COLOURS.get(st, CONTRAIL_COLOURS["Cruiser"])
        self._contrail_start_colour: tuple[int, int, int] = colours[0]
        self._contrail_end_colour: tuple[int, int, int] = colours[1]

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
        if self.player.shields > 0:
            absorbed = min(self.player.shields, amount)
            self.player.shields -= absorbed
            amount -= absorbed
            self.shield_sprite.hit_flash()
        if amount > 0:
            self.player.hp = max(0, self.player.hp - amount)
        self._shake_amp = SHAKE_AMPLITUDE

    def _draw_minimap(self) -> None:
        """Draw a scaled overview of the world inside the status panel."""
        mx, my = MINIMAP_X, MINIMAP_Y
        mw, mh = MINIMAP_W, MINIMAP_H

        arcade.draw_rect_filled(arcade.LBWH(mx, my, mw, mh), (5, 5, 20, 245))
        arcade.draw_rect_outline(
            arcade.LBWH(mx, my, mw, mh), arcade.color.STEEL_BLUE, border_width=1
        )
        self._t_minimap.draw()

        def to_map(wx: float, wy: float) -> tuple[float, float]:
            return (
                mx + (wx / WORLD_WIDTH) * mw,
                my + (wy / WORLD_HEIGHT) * mh,
            )

        for asteroid in self.asteroid_list:
            ax, ay = to_map(asteroid.center_x, asteroid.center_y)
            arcade.draw_circle_filled(ax, ay, 2.0, (150, 150, 150))

        for pickup in self.iron_pickup_list:
            px, py = to_map(pickup.center_x, pickup.center_y)
            arcade.draw_circle_filled(px, py, 2.0, (255, 165, 0))

        for alien in self.alien_list:
            amx, amy = to_map(alien.center_x, alien.center_y)
            arcade.draw_circle_filled(amx, amy, 2.0, (220, 50, 50))

        sx, sy = to_map(self.player.center_x, self.player.center_y)
        rad = math.radians(self.player.heading)
        lx = sx + math.sin(rad) * 5
        ly = sy + math.cos(rad) * 5
        arcade.draw_line(sx, sy, lx, ly, arcade.color.CYAN, 1)
        arcade.draw_circle_filled(sx, sy, 3.0, arcade.color.WHITE)

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

        with self.ui_cam.activate():
            self._draw_status_panel()
            self.inventory.draw()

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

    def _draw_status_panel(self) -> None:
        """Draw the left-side HUD status panel."""
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, STATUS_WIDTH, SCREEN_HEIGHT),
            (15, 15, 40, 235),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(0, 0, STATUS_WIDTH, SCREEN_HEIGHT),
            arcade.color.STEEL_BLUE,
            border_width=2,
        )

        self._t_title.draw()
        self._t_hp.draw()
        self._t_shield.draw()
        self._t_wpn_hdr.draw()
        self._t_ctrl_hdr.draw()
        for t in self._t_ctrl_lines:
            t.draw()
        if self._t_gamepad:
            self._t_gamepad.draw()
        if self._show_fps:
            self._t_fps.text = f"FPS  {self._fps:>6.1f}"
            self._t_fps.draw()

        spd = math.hypot(self.player.vel_x, self.player.vel_y)
        self._t_spd.text = f"SPD   {spd:>7.1f}"
        self._t_spd.draw()
        self._t_hdg.text = f"HDG   {self.player.heading:>6.1f}\u00b0"
        self._t_hdg.draw()
        self._t_iron_hud.text = f"IRON  {self.inventory.iron:>7}"
        self._t_iron_hud.draw()
        self._t_wpn_name.text = self._active_weapon.name
        self._t_wpn_name.draw()

        hp_frac = max(0.0, self.player.hp / self.player.max_hp)
        hp_color = (
            (0, 180, 0) if hp_frac > 0.5
            else (220, 140, 0) if hp_frac > 0.25
            else (200, 30, 30)
        )
        arcade.draw_rect_filled(
            arcade.LBWH(10, SCREEN_HEIGHT - 156, int(190 * hp_frac), 10), hp_color
        )
        shield_frac = max(0.0, self.player.shields / self.player.max_shields)
        arcade.draw_rect_filled(
            arcade.LBWH(10, SCREEN_HEIGHT - 192, int(190 * shield_frac), 10),
            (0, 140, 210),
        )

        self._t_faction.draw()
        self._t_ship_type.draw()

        self._draw_minimap()

    # ── Update ───────────────────────────────────────────────────────────────
    def on_update(self, delta_time: float) -> None:
        # ── Smoothed FPS ────────────────────────────────────────────────────
        if delta_time > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / delta_time)

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
                self._thruster_snd, volume=0.25, looping=True
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
            # Active weapon group: for dual-gun ships, fire from matching
            # weapon indices (0 & 1 for lasers, 2 & 3 for mining beams)
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

        # ── Player projectile hits (single pass) ────────────────────────────
        for proj in list(self.projectile_list):
            consumed = False

            if proj.mines_rock:
                hit_asteroids = arcade.check_for_collision_with_list(
                    proj, self.asteroid_list
                )
                if hit_asteroids:
                    asteroid = hit_asteroids[0]
                    self.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    proj.remove_from_sprite_lists()
                    consumed = True
                    asteroid.take_damage(int(proj.damage))
                    if asteroid.hp <= 0:
                        ax, ay = asteroid._base_x, asteroid._base_y
                        self._spawn_explosion(ax, ay)
                        arcade.play_sound(self._explosion_snd, volume=0.7)
                        asteroid.remove_from_sprite_lists()
                        self._spawn_iron_pickup(ax, ay)

            if not consumed and not proj.mines_rock:
                hit_aliens = arcade.check_for_collision_with_list(
                    proj, self.alien_list
                )
                if hit_aliens:
                    alien = hit_aliens[0]
                    self.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                    self._trigger_shake()
                    proj.remove_from_sprite_lists()
                    alien.take_damage(int(proj.damage))
                    if alien.hp <= 0:
                        self._spawn_explosion(alien.center_x, alien.center_y)
                        arcade.play_sound(self._explosion_snd, volume=0.7)
                        alien.remove_from_sprite_lists()

        # ── Animate asteroids ───────────────────────────────────────────────
        for asteroid in self.asteroid_list:
            asteroid.update_asteroid(delta_time)

        # ── Iron pickup: fly toward ship + collect ──────────────────────────
        sx, sy = self.player.center_x, self.player.center_y
        for pickup in list(self.iron_pickup_list):
            collected = pickup.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_iron(pickup.amount)

        # ── Ship <-> Asteroid collision ──────────────────────────────────────
        hit_list = arcade.check_for_collision_with_list(
            self.player, self.asteroid_list
        )
        for asteroid in hit_list:
            dx = self.player.center_x - asteroid.center_x
            dy = self.player.center_y - asteroid.center_y
            dist = math.hypot(dx, dy)
            if dist == 0:
                dx, dy, dist = 0.0, 1.0, 1.0
            nx = dx / dist
            ny = dy / dist
            combined_r = SHIP_RADIUS + ASTEROID_RADIUS
            overlap = combined_r - dist
            if overlap > 0:
                self.player.center_x += nx * overlap
                self.player.center_y += ny * overlap

            dot = self.player.vel_x * nx + self.player.vel_y * ny
            if dot < 0:
                self.player.vel_x -= (1 + SHIP_BOUNCE) * dot * nx
                self.player.vel_y -= (1 + SHIP_BOUNCE) * dot * ny

            if self.player._collision_cd <= 0.0:
                self._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                self.player._collision_cd = SHIP_COLLISION_COOLDOWN
                arcade.play_sound(self._bump_snd, volume=0.5)
                self._trigger_shake()

        # ── Alien ship AI + movement ────────────────────────────────────────
        px, py = self.player.center_x, self.player.center_y
        for alien in list(self.alien_list):
            proj = alien.update_alien(
                delta_time, px, py,
                self.asteroid_list, self.alien_list,
            )
            if proj is not None:
                self.alien_projectile_list.append(proj)

        # ── Alien <-> Player collision ───────────────────────────────────────
        for alien in list(self.alien_list):
            ddx = alien.center_x - self.player.center_x
            ddy = alien.center_y - self.player.center_y
            ddist = math.hypot(ddx, ddy)
            combined_r = ALIEN_RADIUS + SHIP_RADIUS
            if ddist < combined_r and ddist > 0.0:
                nx, ny = ddx / ddist, ddy / ddist
                overlap = combined_r - ddist
                alien.center_x += nx * overlap * 0.5
                alien.center_y += ny * overlap * 0.5
                self.player.center_x -= nx * overlap * 0.5
                self.player.center_y -= ny * overlap * 0.5
                rel_vx = alien.vel_x - self.player.vel_x
                rel_vy = alien.vel_y - self.player.vel_y
                dot = rel_vx * nx + rel_vy * ny
                if dot < 0.0:
                    j = (1.0 + ALIEN_BOUNCE) * dot
                    alien.vel_x -= j * nx
                    alien.vel_y -= j * ny
                    self.player.vel_x += j * nx * 0.4
                    self.player.vel_y += j * ny * 0.4
                if alien._col_cd <= 0.0:
                    alien._col_cd = ALIEN_COL_COOLDOWN
                    alien.collision_bump()
                if self.player._collision_cd <= 0.0:
                    self._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                    self.player._collision_cd = SHIP_COLLISION_COOLDOWN
                    arcade.play_sound(self._bump_snd, volume=0.4)
                    self._trigger_shake()

        # ── Alien <-> Asteroid collision ─────────────────────────────────────
        for alien in list(self.alien_list):
            for asteroid in arcade.check_for_collision_with_list(
                alien, self.asteroid_list
            ):
                adx = alien.center_x - asteroid._base_x
                ady = alien.center_y - asteroid._base_y
                adist = math.hypot(adx, ady)
                if adist == 0.0:
                    adx, ady, adist = 1.0, 0.0, 1.0
                combined_r = ALIEN_RADIUS + ASTEROID_RADIUS
                nx, ny = adx / adist, ady / adist
                overlap = combined_r - adist
                if overlap > 0.0:
                    alien.center_x += nx * overlap
                    alien.center_y += ny * overlap
                dot = alien.vel_x * nx + alien.vel_y * ny
                if dot < 0.0:
                    alien.vel_x -= (1.0 + ALIEN_BOUNCE) * dot * nx
                    alien.vel_y -= (1.0 + ALIEN_BOUNCE) * dot * ny
                else:
                    alien.vel_x += nx * ALIEN_SPEED * 0.4
                    alien.vel_y += ny * ALIEN_SPEED * 0.4
                if alien._col_cd <= 0.0:
                    alien._col_cd = ALIEN_COL_COOLDOWN
                    alien.collision_bump()

        # ── Alien <-> Alien collision ────────────────────────────────────────
        aliens = list(self.alien_list)
        for i in range(len(aliens)):
            for j in range(i + 1, len(aliens)):
                a1, a2 = aliens[i], aliens[j]
                ddx = a1.center_x - a2.center_x
                ddy = a1.center_y - a2.center_y
                ddist = math.hypot(ddx, ddy)
                combined_r = ALIEN_RADIUS * 2.0
                if ddist < combined_r and ddist > 0.0:
                    nx, ny = ddx / ddist, ddy / ddist
                    overlap = combined_r - ddist
                    a1.center_x += nx * overlap * 0.5
                    a1.center_y += ny * overlap * 0.5
                    a2.center_x -= nx * overlap * 0.5
                    a2.center_y -= ny * overlap * 0.5
                    rel_vx = a1.vel_x - a2.vel_x
                    rel_vy = a1.vel_y - a2.vel_y
                    dot = rel_vx * nx + rel_vy * ny
                    if dot < 0.0:
                        j_imp = (1.0 + ALIEN_BOUNCE) * dot
                        a1.vel_x -= j_imp * nx
                        a1.vel_y -= j_imp * ny
                        a2.vel_x += j_imp * nx
                        a2.vel_y += j_imp * ny
                    if a1._col_cd <= 0.0:
                        a1._col_cd = ALIEN_COL_COOLDOWN
                        a1.collision_bump()
                    if a2._col_cd <= 0.0:
                        a2._col_cd = ALIEN_COL_COOLDOWN
                        a2.collision_bump()

        # ── Advance alien projectiles ───────────────────────────────────────
        for proj in list(self.alien_projectile_list):
            proj.update_projectile(delta_time)

        # ── Alien laser hits on player ──────────────────────────────────────
        for proj in list(self.alien_projectile_list):
            if arcade.check_for_collision(proj, self.player):
                proj.remove_from_sprite_lists()
                self._apply_damage_to_player(int(proj.damage))
                self._trigger_shake()
                arcade.play_sound(self._bump_snd, volume=0.3)

        # ── Advance explosion animations ────────────────────────────────────
        for exp in list(self.explosion_list):
            exp.update_explosion(delta_time)

        # ── Advance hit sparks ──────────────────────────────────────────────
        for spark in self.hit_sparks:
            spark.update(delta_time)
        self.hit_sparks = [s for s in self.hit_sparks if not s.dead]

    # ── Input ────────────────────────────────────────────────────────────────
    def on_key_press(self, key: int, modifiers: int) -> None:
        self._keys.add(key)
        if key == arcade.key.ESCAPE:
            arcade.exit()
        elif key == arcade.key.TAB:
            self._cycle_weapon()
        elif key == arcade.key.I:
            self.inventory.toggle()
        elif key == arcade.key.F:
            self._show_fps = not self._show_fps

    def on_key_release(self, key: int, modifiers: int) -> None:
        self._keys.discard(key)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        if button == arcade.MOUSE_BUTTON_LEFT:
            self.inventory.on_mouse_press(x, y)

    def on_mouse_drag(
        self, x: int, y: int, dx: int, dy: int, buttons: int, modifiers: int
    ) -> None:
        self.inventory.on_mouse_drag(x, y)

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
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
        self.inventory.on_mouse_move(x, y)
