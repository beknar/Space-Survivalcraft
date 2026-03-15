"""Space Survivalcraft — main entry point."""
from __future__ import annotations

import math
import os
import random
from typing import Optional

import arcade
import arcade.camera
import pyglet.input

# ── Window / World ──────────────────────────────────────────────────────────
SCREEN_WIDTH: int = 1280
SCREEN_HEIGHT: int = 800
SCREEN_TITLE: str = "Space Survivalcraft"

STATUS_WIDTH: int = 213          # Left status panel width (~1/6 of screen)
WORLD_WIDTH: int = 6400          # 200 × 32-px tiles
WORLD_HEIGHT: int = 6400

BG_TILE: int = 1024              # Starfield texture is 1024×1024

# ── Player physics ──────────────────────────────────────────────────────────
ROT_SPEED: float = 150.0         # deg / s
THRUST: float = 250.0            # px / s²
BRAKE: float = 125.0             # px / s²  (reverse thrust)
MAX_SPD: float = 450.0           # px / s cap
DAMPING: float = 0.98875         # per-frame velocity multiplier (space drag)

DEAD_ZONE: float = 0.15          # Gamepad analogue stick dead zone

# ── Asset paths ─────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

STARFIELD_DIR = os.path.join(
    _HERE, "assets",
    "SBS - Seamless Space Backgrounds - Large 1024x1024",
    "Large 1024x1024", "Starfields",
)
SHMUP_DIR = os.path.join(_HERE, "assets", "ShmupAssets_V1")
LASER_DIR = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Space Shooter Redux", "PNG", "Lasers",
)
SFX_WEAPONS_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Weapons", "Energy Weapons",
)
SFX_EXPLOSIONS_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Weapons", "Explosions",
)
ASTEROID_PNG = os.path.join(_HERE, "assets", "Pixel Art Space", "Asteroid.png")
EXPLOSION_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets", "asteroids crusher",
    "Explosions", "PNG", "explosion.png",
)

# ── Weapon / projectile constants ─────────────────────────────────────────────
NOSE_OFFSET: float = 44.0        # px ahead of ship centre where projectiles spawn

# ── Inventory constants ──────────────────────────────────────────────────────
INV_COLS: int = 5
INV_ROWS: int = 5
INV_CELL: int = 48               # cell size in px
INV_PAD: int = 10                # padding around grid
INV_HEADER: int = 32             # space for title text above grid

INV_W: int = INV_COLS * INV_CELL + INV_PAD * 2
INV_H: int = INV_ROWS * INV_CELL + INV_PAD * 2 + INV_HEADER

# ── Player ship stats ────────────────────────────────────────────────────────
PLAYER_MAX_HP: int = 100
SHIP_COLLISION_DAMAGE: int = 5       # HP lost per asteroid collision
SHIP_COLLISION_COOLDOWN: float = 0.5 # seconds of invincibility after a hit
SHIP_BOUNCE: float = 0.55            # velocity restitution on bounce (0=dead stop,1=elastic)
# Approximate circle radii used for overlap push-out (pixels)
SHIP_RADIUS: float = 28.0
ASTEROID_RADIUS: float = 26.0

# ── Asteroid constants ────────────────────────────────────────────────────────
ASTEROID_COUNT: int = 50
ASTEROID_HP: int = 100
ASTEROID_IRON_YIELD: int = 10
ASTEROID_MIN_DIST: float = 400.0   # min distance from world centre at spawn
# Explosion sheet: 1260×140 px → 9 frames of 140×140 each
EXPLOSION_FRAMES: int = 9
EXPLOSION_FRAME_W: int = 140
EXPLOSION_FRAME_H: int = 140
EXPLOSION_FPS: float = 15.0        # frames per second


# ── Projectile ───────────────────────────────────────────────────────────────
class Projectile(arcade.Sprite):
    """A fired weapon projectile that travels in a straight line."""

    def __init__(
        self,
        texture: arcade.Texture,
        x: float,
        y: float,
        heading: float,
        speed: float,
        max_dist: float,
        scale: float = 1.0,
        mines_rock: bool = False,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=scale)
        self.center_x = x
        self.center_y = y
        self.angle = heading       # CW-positive compass heading — nose points forward
        rad = math.radians(heading)
        self._vx: float = math.sin(rad) * speed
        self._vy: float = math.cos(rad) * speed
        self._max_dist: float = max_dist
        self._dist_travelled: float = 0.0
        self.mines_rock: bool = mines_rock   # True for Mining Beam only

    def update_projectile(self, dt: float) -> None:
        self.center_x += self._vx * dt
        self.center_y += self._vy * dt
        self._dist_travelled += math.hypot(self._vx, self._vy) * dt
        # Despawn when range exhausted or projectile leaves the world
        if (
            self._dist_travelled >= self._max_dist
            or self.center_x < 0 or self.center_x > WORLD_WIDTH
            or self.center_y < 0 or self.center_y > WORLD_HEIGHT
        ):
            self.remove_from_sprite_lists()


# ── Weapon ───────────────────────────────────────────────────────────────────
class Weapon:
    """Defines a weapon's stats and manages its fire cooldown."""

    def __init__(
        self,
        name: str,
        texture: arcade.Texture,
        sound: arcade.Sound,
        cooldown: float,
        damage: float,
        projectile_speed: float,
        max_range: float,
        proj_scale: float = 1.0,
        mines_rock: bool = False,
    ) -> None:
        self.name = name
        self._texture = texture
        self._sound = sound
        self.cooldown = cooldown
        self.damage = damage
        self._proj_speed = projectile_speed
        self._max_range = max_range
        self._proj_scale = proj_scale
        self.mines_rock = mines_rock   # whether projectiles damage asteroids
        self._timer: float = 0.0

    def update(self, dt: float) -> None:
        self._timer = max(0.0, self._timer - dt)

    def fire(
        self,
        spawn_x: float,
        spawn_y: float,
        heading: float,
    ) -> Optional[Projectile]:
        """Attempt to fire; returns a Projectile if off cooldown, else None."""
        if self._timer > 0.0:
            return None
        self._timer = self.cooldown
        arcade.play_sound(self._sound, volume=0.45)
        return Projectile(
            self._texture, spawn_x, spawn_y, heading,
            self._proj_speed, self._max_range, self._proj_scale,
            mines_rock=self.mines_rock,
        )


# ── Explosion ─────────────────────────────────────────────────────────────────
class Explosion(arcade.Sprite):
    """One-shot explosion animation spawned when an asteroid is destroyed."""

    def __init__(
        self,
        frames: list[arcade.Texture],
        x: float,
        y: float,
        scale: float = 1.0,
    ) -> None:
        super().__init__(path_or_texture=frames[0], scale=scale)
        self.center_x = x
        self.center_y = y
        self._frames = frames
        self._frame_idx: int = 0
        self._timer: float = 0.0
        self._interval: float = 1.0 / EXPLOSION_FPS

    def update_explosion(self, dt: float) -> None:
        self._timer += dt
        if self._timer >= self._interval:
            self._timer -= self._interval
            self._frame_idx += 1
            if self._frame_idx >= len(self._frames):
                self.remove_from_sprite_lists()
                return
            self.texture = self._frames[self._frame_idx]


# ── Iron Asteroid ─────────────────────────────────────────────────────────────
class IronAsteroid(arcade.Sprite):
    """A minable asteroid containing iron ore.

    - 100 HP; only the Mining Beam deals damage.
    - Yields 10 iron when destroyed.
    - Spins slowly at a randomised rate.
    """

    def __init__(self, texture: arcade.Texture, x: float, y: float) -> None:
        super().__init__(path_or_texture=texture, scale=1.0)
        self.center_x = x
        self.center_y = y
        self.hp: int = ASTEROID_HP
        # Each asteroid spins at a unique rate for visual variety
        self._rot_speed: float = random.uniform(8.0, 30.0) * random.choice((-1, 1))

    def update_asteroid(self, dt: float) -> None:
        self.angle = (self.angle + self._rot_speed * dt) % 360

    def take_damage(self, amount: int) -> None:
        self.hp -= amount


# ── Inventory ─────────────────────────────────────────────────────────────────
class Inventory:
    """5×5 cargo hold grid drawn as a modal overlay."""

    def __init__(self) -> None:
        # items: dict[(row, col)] → item name string; absent key = empty slot
        self._items: dict[tuple[int, int], str] = {}
        self.open: bool = False

        # Pre-built Text labels (avoids per-draw allocations)
        cx = SCREEN_WIDTH // 2
        oy = (SCREEN_HEIGHT - INV_H) // 2
        self._t_title = arcade.Text(
            "CARGO HOLD  (5 \u00d7 5)",
            cx,
            oy + INV_H - INV_HEADER // 2 - 2,
            arcade.color.LIGHT_BLUE,
            14,
            bold=True,
            anchor_x="center",
            anchor_y="center",
        )
        self._t_hint = arcade.Text(
            "I  \u2014  close",
            cx,
            oy + 6,
            (160, 160, 160),
            9,
            anchor_x="center",
        )

    def toggle(self) -> None:
        self.open = not self.open

    def draw(self) -> None:
        if not self.open:
            return

        ox = (SCREEN_WIDTH - INV_W) // 2
        oy = (SCREEN_HEIGHT - INV_H) // 2

        # Panel background and border
        arcade.draw_rect_filled(
            arcade.LBWH(ox, oy, INV_W, INV_H), (10, 10, 35, 230)
        )
        arcade.draw_rect_outline(
            arcade.LBWH(ox, oy, INV_W, INV_H),
            arcade.color.STEEL_BLUE,
            border_width=2,
        )

        self._t_title.draw()
        self._t_hint.draw()

        # Grid cells — row 0 is the top row visually
        grid_x = ox + INV_PAD
        grid_y = oy + INV_PAD
        for row in range(INV_ROWS):
            for col in range(INV_COLS):
                cx_ = grid_x + col * INV_CELL
                cy_ = grid_y + (INV_ROWS - 1 - row) * INV_CELL
                item = self._items.get((row, col))
                fill = (30, 30, 60, 200) if item is None else (50, 80, 50, 200)
                arcade.draw_rect_filled(
                    arcade.LBWH(cx_ + 1, cy_ + 1, INV_CELL - 2, INV_CELL - 2),
                    fill,
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx_, cy_, INV_CELL, INV_CELL),
                    (60, 80, 120),
                    border_width=1,
                )


# ── Player ship ──────────────────────────────────────────────────────────────
class PlayerShip(arcade.Sprite):
    """
    Spaceship with rotation-and-thrust Newtonian physics.

    Controls
    --------
    Keyboard  : Left/Right (or A/D) to rotate, Up (or W) to thrust,
                Down (or S) for reverse brake.
    Gamepad   : Left-stick X to rotate, left-stick Y to thrust/brake.
    """

    _COLS = 4       # animation columns per row
    _ROWS = 3       # rows: 0 = idle/base, 1 = nose weapon, 2 = wing weapons
    _ANIM_FPS = 8   # thruster animation speed (frames/s)

    def __init__(self) -> None:
        sheet = os.path.join(SHMUP_DIR, "shmup_player.png")

        ss = arcade.load_spritesheet(sheet)
        fw = ss.image.width // self._COLS
        fh = ss.image.height // self._ROWS

        # Load all 12 frames: _frames[row][col]
        self._frames: list[list] = [
            [
                ss.get_texture(arcade.LBWH(col * fw, row * fh, fw, fh))
                for col in range(self._COLS)
            ]
            for row in range(self._ROWS)
        ]

        super().__init__(path_or_texture=self._frames[0][0], scale=1.5)

        # Start at world centre
        self.center_x = WORLD_WIDTH / 2
        self.center_y = WORLD_HEIGHT / 2

        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        # Compass heading: 0 = north/up, increases clockwise (matches Arcade's
        # CW-positive sprite angle convention).  Direct-mapped to self.angle.
        self.heading: float = 0.0

        # Ship stats
        self.hp: int = PLAYER_MAX_HP
        self.max_hp: int = PLAYER_MAX_HP
        # Invincibility window after an asteroid collision (prevents per-frame damage)
        self._collision_cd: float = 0.0

        # Thruster animation state
        self._intensity: float = 0.0
        self._anim_timer: float = 0.0
        self._anim_col: int = 0

    def apply_input(
        self,
        dt: float,
        rotate_left: bool,
        rotate_right: bool,
        thrust_fwd: bool,
        thrust_bwd: bool,
    ) -> None:
        # Rotation — A/Left = CCW (heading decreases), D/Right = CW (increases)
        if rotate_left:
            self.heading = (self.heading - ROT_SPEED * dt) % 360
        if rotate_right:
            self.heading = (self.heading + ROT_SPEED * dt) % 360

        # Sprite visual angle maps 1:1 to compass heading (Arcade is CW-positive)
        self.angle = self.heading

        # Thrust along visual nose direction.
        # Compass heading → Cartesian: vel_x = sin(h), vel_y = cos(h)
        rad = math.radians(self.heading)
        if thrust_fwd:
            self.vel_x += math.sin(rad) * THRUST * dt
            self.vel_y += math.cos(rad) * THRUST * dt
        if thrust_bwd:
            self.vel_x -= math.sin(rad) * BRAKE * dt
            self.vel_y -= math.cos(rad) * BRAKE * dt

        # Speed cap
        spd = math.hypot(self.vel_x, self.vel_y)
        if spd > MAX_SPD:
            scale = MAX_SPD / spd
            self.vel_x *= scale
            self.vel_y *= scale

        # Drag
        self.vel_x *= DAMPING
        self.vel_y *= DAMPING

        # Integrate position, clamped to world bounds
        hw, hh = self.width / 2, self.height / 2
        self.center_x = max(hw, min(WORLD_WIDTH - hw,
                                    self.center_x + self.vel_x * dt))
        self.center_y = max(hh, min(WORLD_HEIGHT - hh,
                                    self.center_y + self.vel_y * dt))

        # ── Collision cooldown tick ──────────────────────────────────────────
        if self._collision_cd > 0.0:
            self._collision_cd = max(0.0, self._collision_cd - dt)

        # ── Thruster intensity ───────────────────────────────────────────────
        if thrust_fwd:
            self._intensity = min(1.0, self._intensity + 4.0 * dt)
        else:
            self._intensity = max(0.0, self._intensity - 6.0 * dt)

        # ── Thruster animation ───────────────────────────────────────────────
        # Row 0 only — rows 1 and 2 show nose/wing weapon effects.
        if self._intensity > 0.0:
            self._anim_timer += dt
            if self._anim_timer >= 1.0 / self._ANIM_FPS:
                self._anim_timer -= 1.0 / self._ANIM_FPS
                self._anim_col = (self._anim_col + 1) % self._COLS
        else:
            self._anim_timer = 0.0
            self._anim_col = 0

        self.texture = self._frames[0][self._anim_col]

    @property
    def nose_x(self) -> float:
        """World X of the ship's nose tip (projectile spawn point)."""
        return self.center_x + math.sin(math.radians(self.heading)) * NOSE_OFFSET

    @property
    def nose_y(self) -> float:
        """World Y of the ship's nose tip (projectile spawn point)."""
        return self.center_y + math.cos(math.radians(self.heading)) * NOSE_OFFSET


# ── Game view ────────────────────────────────────────────────────────────────
class GameView(arcade.View):

    def __init__(self) -> None:
        super().__init__()

        # Player
        self.player = PlayerShip()
        self.player_list = arcade.SpriteList()
        self.player_list.append(self.player)

        # Active projectiles
        self.projectile_list = arcade.SpriteList()

        # Tiled background texture
        self.bg_texture = arcade.load_texture(
            os.path.join(STARFIELD_DIR, "Starfield_01-1024x1024.png")
        )

        # World camera (follows player)
        self.world_cam = arcade.camera.Camera2D()
        # UI camera (static — for the status panel and modal overlays)
        self.ui_cam = arcade.camera.Camera2D()

        # Held-key tracking
        self._keys: set[int] = set()

        # Gamepad — Xbox controllers use XInput (pyglet Controller API).
        # arcade.get_joysticks() uses DirectInput and misses Xbox pads.
        self.joystick = None
        self._prev_rb: bool = False   # right bumper previous frame (weapon cycle)
        self._prev_y: bool = False    # Y button previous frame (inventory toggle)
        controllers = pyglet.input.get_controllers()
        if controllers:
            self.joystick = controllers[0]
            self.joystick.open()
            print(f"Gamepad connected: {self.joystick.name}")

        # ── Weapons ──────────────────────────────────────────────────────────
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
        self._weapons: list[Weapon] = [
            Weapon(
                "Basic Laser",
                laser_tex, laser_snd,
                cooldown=0.30, damage=25.0,
                projectile_speed=900.0, max_range=1200.0,
                proj_scale=1.0,
                mines_rock=False,   # basic laser cannot mine asteroids
            ),
            Weapon(
                "Mining Beam",
                mining_tex, mining_snd,
                cooldown=0.10, damage=10.0,
                projectile_speed=500.0, max_range=800.0,
                proj_scale=1.0,
                mines_rock=True,    # mining beam damages asteroids
            ),
        ]
        self._weapon_idx: int = 0

        # ── Asteroids ────────────────────────────────────────────────────────
        asteroid_tex = arcade.load_texture(ASTEROID_PNG)

        # Load explosion sprite sheet: 9 frames, each 140×140
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

        self.asteroid_list = arcade.SpriteList()
        self.explosion_list = arcade.SpriteList()

        cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        margin = 100          # keep asteroids away from world edges
        placed = 0
        attempts = 0
        while placed < ASTEROID_COUNT and attempts < ASTEROID_COUNT * 20:
            attempts += 1
            ax = random.uniform(margin, WORLD_WIDTH - margin)
            ay = random.uniform(margin, WORLD_HEIGHT - margin)
            # Keep clear of player start position
            if math.hypot(ax - cx_world, ay - cy_world) < ASTEROID_MIN_DIST:
                continue
            self.asteroid_list.append(IronAsteroid(asteroid_tex, ax, ay))
            placed += 1

        # ── Inventory ────────────────────────────────────────────────────────
        self.inventory = Inventory()

        # ── HUD text objects (pre-built to avoid per-frame draw_text cost) ───
        cx = STATUS_WIDTH // 2
        self._t_title    = arcade.Text("STATUS", cx, SCREEN_HEIGHT - 26,
                                       arcade.color.LIGHT_BLUE, 14, bold=True,
                                       anchor_x="center", anchor_y="center")
        self._t_spd      = arcade.Text("", 10, SCREEN_HEIGHT - 60,
                                       arcade.color.WHITE, 11)
        self._t_hdg      = arcade.Text("", 10, SCREEN_HEIGHT - 80,
                                       arcade.color.WHITE, 11)
        self._t_hp       = arcade.Text("HP",     10, SCREEN_HEIGHT - 120,
                                       arcade.color.LIME_GREEN, 10, bold=True)
        self._t_shield   = arcade.Text("SHIELD", 10, SCREEN_HEIGHT - 156,
                                       arcade.color.CYAN, 10, bold=True)
        # Weapon readout
        self._t_wpn_hdr  = arcade.Text("WEAPON", cx, SCREEN_HEIGHT - 190,
                                       arcade.color.LIGHT_GRAY, 9,
                                       anchor_x="center")
        self._t_wpn_name = arcade.Text("", cx, SCREEN_HEIGHT - 206,
                                       arcade.color.YELLOW, 10, bold=True,
                                       anchor_x="center")
        # Controls reference
        self._t_ctrl_hdr = arcade.Text("CONTROLS", cx, SCREEN_HEIGHT - 228,
                                       arcade.color.LIGHT_GRAY, 9,
                                       anchor_x="center")
        self._t_ctrl_lines = [
            arcade.Text("L/R  A/D    Rotate",   10, SCREEN_HEIGHT - 246,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Up / W      Thrust",   10, SCREEN_HEIGHT - 262,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Dn / S      Brake",    10, SCREEN_HEIGHT - 278,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Space       Fire",     10, SCREEN_HEIGHT - 294,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Tab         Weapon",   10, SCREEN_HEIGHT - 310,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("I           Inventory",10, SCREEN_HEIGHT - 326,
                        arcade.color.LIGHT_GRAY, 9),
        ]
        self._t_gamepad = (
            arcade.Text("Gamepad: connected", 10, SCREEN_HEIGHT - 350,
                        arcade.color.LIME_GREEN, 9)
            if self.joystick else None
        )

    # ── Helpers ──────────────────────────────────────────────────────────────
    @property
    def _active_weapon(self) -> Weapon:
        return self._weapons[self._weapon_idx]

    def _cycle_weapon(self) -> None:
        self._weapon_idx = (self._weapon_idx + 1) % len(self._weapons)

    def _spawn_explosion(self, x: float, y: float) -> None:
        """Spawn a one-shot explosion animation at world position (x, y)."""
        exp = Explosion(self._explosion_frames, x, y, scale=1.0)
        self.explosion_list.append(exp)

    # ── Drawing ──────────────────────────────────────────────────────────────
    def on_draw(self) -> None:
        self.clear()

        # Centre camera on player, clamped so edges don't go beyond the world
        hw = SCREEN_WIDTH / 2
        hh = SCREEN_HEIGHT / 2
        cx = max(hw, min(WORLD_WIDTH - hw, self.player.center_x))
        cy = max(hh, min(WORLD_HEIGHT - hh, self.player.center_y))
        self.world_cam.position = (cx, cy)

        with self.world_cam.activate():
            self._draw_background(cx, cy, hw, hh)
            self.asteroid_list.draw()
            self.explosion_list.draw()
            self.projectile_list.draw()
            self.player_list.draw()

        with self.ui_cam.activate():
            self._draw_status_panel()
            self.inventory.draw()        # drawn last → always on top

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
        # Background fill
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, STATUS_WIDTH, SCREEN_HEIGHT),
            (15, 15, 40, 235),
        )
        # Right border
        arcade.draw_rect_outline(
            arcade.LBWH(0, 0, STATUS_WIDTH, SCREEN_HEIGHT),
            arcade.color.STEEL_BLUE,
            border_width=2,
        )

        # Static labels
        self._t_title.draw()
        self._t_hp.draw()
        self._t_shield.draw()
        self._t_wpn_hdr.draw()
        self._t_ctrl_hdr.draw()
        for t in self._t_ctrl_lines:
            t.draw()
        if self._t_gamepad:
            self._t_gamepad.draw()

        # Dynamic readouts
        spd = math.hypot(self.player.vel_x, self.player.vel_y)
        self._t_spd.text = f"SPD   {spd:>7.1f}"
        self._t_spd.draw()
        self._t_hdg.text = f"HDG   {self.player.heading:>6.1f}\u00b0"
        self._t_hdg.draw()
        self._t_wpn_name.text = self._active_weapon.name
        self._t_wpn_name.draw()

        # HP bar (live — shrinks as ship takes damage)
        hp_frac = max(0.0, self.player.hp / self.player.max_hp)
        hp_color = (
            (0, 180, 0) if hp_frac > 0.5
            else (220, 140, 0) if hp_frac > 0.25
            else (200, 30, 30)
        )
        arcade.draw_rect_filled(
            arcade.LBWH(10, SCREEN_HEIGHT - 136, int(190 * hp_frac), 10), hp_color
        )
        # Shield bar (placeholder — full)
        arcade.draw_rect_filled(
            arcade.LBWH(10, SCREEN_HEIGHT - 172, 190, 10), (0, 140, 210)
        )

    # ── Update ───────────────────────────────────────────────────────────────
    def on_update(self, delta_time: float) -> None:
        # ── Movement input ───────────────────────────────────────────────────
        rl = arcade.key.LEFT in self._keys or arcade.key.A in self._keys
        rr = arcade.key.RIGHT in self._keys or arcade.key.D in self._keys
        tf = arcade.key.UP in self._keys or arcade.key.W in self._keys
        tb = arcade.key.DOWN in self._keys or arcade.key.S in self._keys

        # ── Fire input (hold to auto-fire at weapon's rate) ──────────────────
        fire = arcade.key.SPACE in self._keys

        if self.joystick:
            lx = self.joystick.leftx   # -1=left, +1=right
            ly = self.joystick.lefty   # +1=up/fwd, -1=down/brake (XInput Y-up)
            rl |= lx < -DEAD_ZONE
            rr |= lx > DEAD_ZONE
            tf |= ly >  DEAD_ZONE
            tb |= ly < -DEAD_ZONE

            # A button = fire
            fire |= bool(getattr(self.joystick, "a", False))

            # RB = cycle weapon (edge detect — one cycle per press)
            rb = bool(getattr(self.joystick, "rightshoulder", False))
            if rb and not self._prev_rb:
                self._cycle_weapon()
            self._prev_rb = rb

            # Y button = toggle inventory (edge detect)
            y_btn = bool(getattr(self.joystick, "y", False))
            if y_btn and not self._prev_y:
                self.inventory.toggle()
            self._prev_y = y_btn

        self.player.apply_input(delta_time, rl, rr, tf, tb)

        # ── Weapons: tick cooldowns ──────────────────────────────────────────
        for w in self._weapons:
            w.update(delta_time)

        # ── Fire active weapon ───────────────────────────────────────────────
        if fire:
            proj = self._active_weapon.fire(
                self.player.nose_x, self.player.nose_y, self.player.heading
            )
            if proj is not None:
                self.projectile_list.append(proj)

        # ── Advance projectiles ──────────────────────────────────────────────
        for proj in list(self.projectile_list):
            proj.update_projectile(delta_time)

        # ── Mining beam hits on asteroids ────────────────────────────────────
        for proj in list(self.projectile_list):
            if not proj.mines_rock:
                continue
            hit_asteroids = arcade.check_for_collision_with_list(
                proj, self.asteroid_list
            )
            if hit_asteroids:
                proj.remove_from_sprite_lists()
                asteroid = hit_asteroids[0]
                asteroid.take_damage(10)
                if asteroid.hp <= 0:
                    self._spawn_explosion(asteroid.center_x, asteroid.center_y)
                    arcade.play_sound(self._explosion_snd, volume=0.7)
                    asteroid.remove_from_sprite_lists()

        # ── Animate asteroids (spin) ─────────────────────────────────────────
        for asteroid in self.asteroid_list:
            asteroid.update_asteroid(delta_time)

        # ── Ship ↔ Asteroid collision ────────────────────────────────────────
        hit_list = arcade.check_for_collision_with_list(
            self.player, self.asteroid_list
        )
        for asteroid in hit_list:
            # --- Push-out: separate ship from asteroid along collision normal ---
            dx = self.player.center_x - asteroid.center_x
            dy = self.player.center_y - asteroid.center_y
            dist = math.hypot(dx, dy)
            if dist == 0:                  # degenerate: push straight up
                dx, dy, dist = 0.0, 1.0, 1.0
            nx = dx / dist                 # unit collision normal (asteroid → ship)
            ny = dy / dist
            combined_r = SHIP_RADIUS + ASTEROID_RADIUS
            overlap = combined_r - dist
            if overlap > 0:
                self.player.center_x += nx * overlap
                self.player.center_y += ny * overlap

            # --- Bounce: reflect velocity component along normal ---------------
            dot = self.player.vel_x * nx + self.player.vel_y * ny
            if dot < 0:                    # only bounce when moving toward asteroid
                self.player.vel_x -= (1 + SHIP_BOUNCE) * dot * nx
                self.player.vel_y -= (1 + SHIP_BOUNCE) * dot * ny

            # --- Damage (once per cooldown window) ----------------------------
            if self.player._collision_cd <= 0.0:
                self.player.hp = max(0, self.player.hp - SHIP_COLLISION_DAMAGE)
                self.player._collision_cd = SHIP_COLLISION_COOLDOWN

        # ── Advance explosion animations ─────────────────────────────────────
        for exp in list(self.explosion_list):
            exp.update_explosion(delta_time)

    # ── Input ────────────────────────────────────────────────────────────────
    def on_key_press(self, key: int, modifiers: int) -> None:
        self._keys.add(key)
        if key == arcade.key.ESCAPE:
            arcade.exit()
        elif key == arcade.key.TAB:
            self._cycle_weapon()
        elif key == arcade.key.I:
            self.inventory.toggle()

    def on_key_release(self, key: int, modifiers: int) -> None:
        self._keys.discard(key)


# ── Entry point ──────────────────────────────────────────────────────────────
def main() -> None:
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
    window.show_view(GameView())
    arcade.run()


if __name__ == "__main__":
    main()
