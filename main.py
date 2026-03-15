"""Space Survivalcraft — main entry point."""
from __future__ import annotations

import math
import os
import random
from typing import Optional

import arcade
import arcade.camera
import pyglet.input
from PIL import Image as PILImage

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
SFX_BIO_DIR = os.path.join(
    _HERE, "assets", "Sci Fi Sound Effects Bundle",
    "Stormwave Audio Sci-Fi Sound Effects Bundle", "Biomechanical",
)
ASTEROID_PNG = os.path.join(_HERE, "assets", "Pixel Art Space", "Asteroid.png")
ALIEN_SHIP_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "Ship.png",
)
ALIEN_FX_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets",
    "alien spaceship creation kit", "png", "Effects.png",
)
EXPLOSION_PNG = os.path.join(
    _HERE, "assets", "gamedevmarket assets", "asteroids crusher",
    "Explosions", "PNG", "explosion.png",
)
IRON_ICON_PNG = os.path.join(
    _HERE, "assets", "kenney space combat assets",
    "Voxel Pack", "PNG", "Items", "ore_ironAlt.png",
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
PLAYER_MAX_SHIELD: int = 100         # full shield capacity
SHIELD_REGEN_RATE: float = 0.5       # shield points restored per second (1 per 2 s)
SHIP_COLLISION_DAMAGE: int = 5       # HP/shield lost per asteroid collision
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

# ── Small Alien Ship constants ────────────────────────────────────────────────
ALIEN_COUNT: int = 20
ALIEN_HP: int = 50
ALIEN_SCALE: float = 0.10               # display scale  (461 px source → ~46 px wide)
ALIEN_RADIUS: float = 20.0              # approx collision radius in px
ALIEN_SPEED: float = 120.0              # patrol / pursuit movement speed  px/s
ALIEN_PATROL_RADIUS_MIN: float = 100.0  # minimum patrol-area radius  px
ALIEN_PATROL_RADIUS_MAX: float = 150.0  # maximum patrol-area radius  px
ALIEN_DETECT_DIST: float = 500.0        # player centre-to-centre px → triggers pursuit
ALIEN_LASER_DAMAGE: float = 10.0        # HP per alien laser hit
ALIEN_LASER_RANGE: float = 500.0        # alien laser max range  px
ALIEN_LASER_SPEED: float = 650.0        # alien laser projectile speed  px/s (faster than player max)
ALIEN_FIRE_COOLDOWN: float = 1.5        # seconds between alien shots
ALIEN_MIN_DIST: float = 400.0           # min spawn distance from world centre  px

# ── Iron pickup constants ─────────────────────────────────────────────────────
IRON_PICKUP_DIST: float = 40.0   # px — edge distance (from ship hull) to trigger fly-to-ship
IRON_FLY_SPEED: float = 400.0    # px/s — speed of iron token once attracted
WORLD_ITEM_LIFETIME: float = 600.0  # seconds before a dropped item despawns (10 min)
EJECT_DIST: float = 60.0            # px from ship EDGE where ejected items land

# ── Camera shake constants ────────────────────────────────────────────────────
SHAKE_DURATION: float = 0.25     # seconds of camera shake after a hull collision
SHAKE_AMPLITUDE: float = 8.0     # max pixel offset during shake

# ── Mini-map constants (drawn inside the status panel) ────────────────────────
MINIMAP_PAD: int = 10
MINIMAP_W: int = STATUS_WIDTH - 2 * MINIMAP_PAD   # 193 px wide
MINIMAP_H: int = MINIMAP_W                         # square
MINIMAP_X: int = MINIMAP_PAD
MINIMAP_Y: int = MINIMAP_PAD + 16                  # 26 px from bottom; label sits below


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
        damage: float = 0.0,
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
        self.damage: float = damage          # HP damage dealt on impact

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
            damage=self.damage,
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


# ── HitSpark ──────────────────────────────────────────────────────────────────
class HitSpark:
    """A brief expanding-ring flash drawn at an impact point.

    No texture required — drawn with arcade primitives.
    Lasts DURATION seconds; ring expands from 0 to MAX_RADIUS and fades out.
    """

    DURATION: float = 0.18
    MAX_RADIUS: float = 28.0

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self._age: float = 0.0
        self.dead: bool = False

    def update(self, dt: float) -> None:
        self._age += dt
        if self._age >= self.DURATION:
            self.dead = True

    def draw(self) -> None:
        if self.dead:
            return
        t = self._age / self.DURATION          # 0 → 1
        radius = self.MAX_RADIUS * t
        alpha = int(255 * (1.0 - t))           # fades out
        # Outer ring
        arcade.draw_circle_outline(
            self.x, self.y, radius,
            (255, 200, 80, alpha), border_width=3,
        )
        # Inner bright core (small filled circle, shrinks as t grows)
        core_r = self.MAX_RADIUS * 0.4 * (1.0 - t)
        if core_r > 1.0:
            arcade.draw_circle_filled(
                self.x, self.y, core_r,
                (255, 255, 180, alpha),
            )


# ── Iron Pickup ───────────────────────────────────────────────────────────────
class IronPickup(arcade.Sprite):
    """Iron ore icon dropped at the site of a destroyed asteroid.

    - Idles at drop position until the ship comes within IRON_PICKUP_DIST px.
    - Then flies toward the ship at IRON_FLY_SPEED px/s.
    - Returns True from update_pickup() when it reaches the ship (collected).
    """

    def __init__(
        self,
        texture: arcade.Texture,
        x: float,
        y: float,
        amount: int = ASTEROID_IRON_YIELD,
        lifetime: Optional[float] = None,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=0.5)
        self.center_x = x
        self.center_y = y
        self.amount: int = amount           # iron units this pickup is worth
        self._lifetime: Optional[float] = lifetime  # None = never expires
        self._age: float = 0.0
        self._flying: bool = False

    def update_pickup(
        self, dt: float, ship_x: float, ship_y: float, ship_radius: float = 0.0
    ) -> bool:
        """Advance state. Returns True on collection (caller reads .amount then removes).

        ship_radius: approximate radius of the ship sprite in px.  The pickup
        trigger fires when the *edge* of the ship (not its centre) comes within
        IRON_PICKUP_DIST px of the token.
        """
        # Age the token; despawn silently when lifetime expires
        if self._lifetime is not None:
            self._age += dt
            if self._age >= self._lifetime:
                self.remove_from_sprite_lists()
                return False

        dx = ship_x - self.center_x
        dy = ship_y - self.center_y
        dist = math.hypot(dx, dy)
        # Edge distance = centre-to-centre minus the ship's radius
        edge_dist = max(0.0, dist - ship_radius)

        if not self._flying and edge_dist <= IRON_PICKUP_DIST:
            self._flying = True

        if self._flying:
            if dist < 6.0:
                self.remove_from_sprite_lists()
                return True
            step = IRON_FLY_SPEED * dt
            ratio = min(1.0, step / dist)
            self.center_x += dx * ratio
            self.center_y += dy * ratio

        return False


# ── Iron Asteroid ─────────────────────────────────────────────────────────────
class IronAsteroid(arcade.Sprite):
    """A minable asteroid containing iron ore.

    - 100 HP; only the Mining Beam deals damage.
    - Yields 10 iron when destroyed.
    - Spins slowly at a randomised rate.
    """

    # Hit-shake constants
    _SHAKE_DURATION: float = 0.20   # seconds the asteroid shakes after a hit
    _SHAKE_AMP: float = 4.0         # max pixel offset during shake

    def __init__(self, texture: arcade.Texture, x: float, y: float) -> None:
        super().__init__(path_or_texture=texture, scale=1.0)
        self.center_x = x
        self.center_y = y
        self._base_x: float = x     # home position; shake offsets from here
        self._base_y: float = y
        self.hp: int = ASTEROID_HP
        # Each asteroid spins at a unique rate for visual variety
        self._rot_speed: float = random.uniform(8.0, 30.0) * random.choice((-1, 1))
        # Hit-shake state
        self._hit_timer: float = 0.0

    def update_asteroid(self, dt: float) -> None:
        self.angle = (self.angle + self._rot_speed * dt) % 360
        # Shake: while hit timer is active, jitter position around base
        if self._hit_timer > 0.0:
            prev = self._hit_timer
            self._hit_timer = max(0.0, self._hit_timer - dt)
            t = self._hit_timer / self._SHAKE_DURATION   # 1→0
            amp = self._SHAKE_AMP * t
            self.center_x = self._base_x + random.uniform(-amp, amp)
            self.center_y = self._base_y + random.uniform(-amp, amp)
            if self._hit_timer == 0.0 and prev > 0.0:
                self.color = (255, 255, 255, 255)   # restore normal tint
        else:
            self.center_x = self._base_x
            self.center_y = self._base_y

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        self._hit_timer = self._SHAKE_DURATION   # start shake
        # Flash orange-red on hit
        self.color = (255, 140, 60, 255)


# ── Small Alien Ship ──────────────────────────────────────────────────────────
class SmallAlienShip(arcade.Sprite):
    """Scout-class enemy.

    Behaviour
    ---------
    PATROL : circles a randomised point within ALIEN_PATROL_RADIUS of its spawn.
    PURSUE : when the player comes within ALIEN_DETECT_DIST px, locks on and
             chases the player, firing ALIEN_LASER_RANGE-px laser bolts.
    Returns to patrol when the player moves more than 3× ALIEN_DETECT_DIST away.
    """

    _STATE_PATROL = 0
    _STATE_PURSUE = 1

    def __init__(
        self,
        texture: arcade.Texture,
        laser_tex: arcade.Texture,
        x: float,
        y: float,
    ) -> None:
        super().__init__(path_or_texture=texture, scale=ALIEN_SCALE)
        self.center_x = x
        self.center_y = y
        self.hp: int = ALIEN_HP

        self._state: int = self._STATE_PATROL
        self._home_x: float = x
        self._home_y: float = y
        self._patrol_r: float = random.uniform(
            ALIEN_PATROL_RADIUS_MIN, ALIEN_PATROL_RADIUS_MAX
        )
        self._tgt_x: float = x
        self._tgt_y: float = y
        self._pick_patrol_target()

        self._heading: float = random.uniform(0.0, 360.0)
        self.angle = self._heading
        # Stagger fire timers so ships don't all shoot simultaneously
        self._fire_cd: float = random.uniform(0.0, ALIEN_FIRE_COOLDOWN)
        self._laser_tex: arcade.Texture = laser_tex
        # Hit-flash state: tint alien red for a short time when struck
        self._hit_timer: float = 0.0

    def _pick_patrol_target(self) -> None:
        """Choose a fresh random point within the patrol radius."""
        angle = random.uniform(0.0, math.tau)
        r = random.uniform(0.0, self._patrol_r)
        self._tgt_x = max(50.0, min(WORLD_WIDTH - 50.0,
                                     self._home_x + math.cos(angle) * r))
        self._tgt_y = max(50.0, min(WORLD_HEIGHT - 50.0,
                                     self._home_y + math.sin(angle) * r))

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        self._hit_timer = 0.15   # flash red for 0.15 s

    def update_alien(
        self, dt: float, player_x: float, player_y: float
    ) -> "Optional[Projectile]":
        """Advance AI + movement.  Returns a fired Projectile, or None."""
        dx = player_x - self.center_x
        dy = player_y - self.center_y
        dist = math.hypot(dx, dy)

        # ── State transitions ─────────────────────────────────────────────────
        if self._state == self._STATE_PATROL:
            if dist <= ALIEN_DETECT_DIST:
                self._state = self._STATE_PURSUE
                self._fire_cd = 0.0   # fire immediately on first detection
        else:
            if dist > ALIEN_DETECT_DIST * 3.0:
                self._state = self._STATE_PATROL
                self._pick_patrol_target()

        # ── Movement ──────────────────────────────────────────────────────────
        if self._state == self._STATE_PATROL:
            tdx = self._tgt_x - self.center_x
            tdy = self._tgt_y - self.center_y
            tdist = math.hypot(tdx, tdy)
            if tdist < 8.0:
                self._pick_patrol_target()
            else:
                step = min(ALIEN_SPEED * dt, tdist)
                self.center_x += tdx / tdist * step
                self.center_y += tdy / tdist * step
                self._heading = math.degrees(math.atan2(tdx, tdy)) % 360.0
                self.angle = self._heading
        else:  # PURSUE — move toward player
            if dist > 1.0:
                step = min(ALIEN_SPEED * dt, dist)
                self.center_x += dx / dist * step
                self.center_y += dy / dist * step
                self._heading = math.degrees(math.atan2(dx, dy)) % 360.0
                self.angle = self._heading

        # ── Hit-flash tint ────────────────────────────────────────────────────
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = (255, 80, 80, 255) if self._hit_timer > 0.0 else (255, 255, 255, 255)

        # ── Fire ──────────────────────────────────────────────────────────────
        self._fire_cd = max(0.0, self._fire_cd - dt)
        if (
            self._state == self._STATE_PURSUE
            and dist <= ALIEN_LASER_RANGE
            and self._fire_cd <= 0.0
        ):
            self._fire_cd = ALIEN_FIRE_COOLDOWN
            return Projectile(
                self._laser_tex,
                self.center_x, self.center_y,
                self._heading,
                ALIEN_LASER_SPEED, ALIEN_LASER_RANGE,
                scale=0.5,
                damage=ALIEN_LASER_DAMAGE,
            )
        return None


# ── Inventory ─────────────────────────────────────────────────────────────────
class Inventory:
    """5×5 cargo hold grid drawn as a modal overlay.

    Tracks stackable resources (iron) separately from slot items.
    Supports mouse drag-and-drop to rearrange items between cells.
    """

    def __init__(self, iron_icon: Optional[arcade.Texture] = None) -> None:
        # items: dict[(row, col)] → item name string; absent key = empty slot
        self._items: dict[tuple[int, int], str] = {}
        self.open: bool = False

        # Stackable resource totals
        self.iron: int = 0
        self._iron_icon: Optional[arcade.Texture] = iron_icon
        # Cell that currently displays the iron stack (draggable)
        self._iron_cell: tuple[int, int] = (0, 0)

        # Drag-and-drop state
        self._drag_type: Optional[str] = None        # item name or "iron"
        self._drag_src: Optional[tuple[int, int]] = None
        self._drag_x: float = 0.0
        self._drag_y: float = 0.0

        # Mouse position (for hover tooltip)
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0

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
            "I \u2014 close   drag to move items",
            cx,
            oy + 6,
            (160, 160, 160),
            9,
            anchor_x="center",
        )
        # Iron count label (reused in cell and while dragging)
        self._t_iron = arcade.Text("", 0, 0, arcade.color.ORANGE, 9, bold=True)
        # Generic item text labels (avoid slow draw_text calls)
        self._t_item_label = arcade.Text("", 0, 0, arcade.color.WHITE, 8)
        self._t_drag_label = arcade.Text("", 0, 0, arcade.color.WHITE, 8)
        self._t_tooltip = arcade.Text(
            "", 0, 0, arcade.color.WHITE, 9,
            anchor_x="center", anchor_y="center",
        )

    # ── Public API ────────────────────────────────────────────────────────────
    def add_iron(self, amount: int) -> None:
        self.iron += amount

    def toggle(self) -> None:
        self.open = not self.open

    # ── Mouse helpers ─────────────────────────────────────────────────────────
    def _grid_origin(self) -> tuple[int, int]:
        """Return (grid_x, grid_y) — pixel coords of the bottom-left of the grid."""
        ox = (SCREEN_WIDTH - INV_W) // 2
        oy = (SCREEN_HEIGHT - INV_H) // 2
        return ox + INV_PAD, oy + INV_PAD

    def _cell_at(self, x: float, y: float) -> Optional[tuple[int, int]]:
        """Return (row, col) for screen-space coords, or None if outside grid."""
        gx, gy = self._grid_origin()
        # Explicit bounds check first — int() truncates toward zero, so a
        # negative offset like int(-5/48) would wrongly return 0 without this.
        grid_w = INV_COLS * INV_CELL
        grid_h = INV_ROWS * INV_CELL
        if x < gx or x >= gx + grid_w or y < gy or y >= gy + grid_h:
            return None
        col = int((x - gx) / INV_CELL)
        row_from_bottom = int((y - gy) / INV_CELL)
        row = INV_ROWS - 1 - row_from_bottom
        if 0 <= row < INV_ROWS and 0 <= col < INV_COLS:
            return (row, col)
        return None

    def _panel_contains(self, x: float, y: float) -> bool:
        """Return True if (x, y) lies within the inventory panel rectangle."""
        ox = (SCREEN_WIDTH - INV_W) // 2
        oy = (SCREEN_HEIGHT - INV_H) // 2
        return ox <= x <= ox + INV_W and oy <= y <= oy + INV_H

    def on_mouse_press(self, x: float, y: float) -> bool:
        """Attempt to pick up the item at (x, y).  Returns True if drag started."""
        if not self.open:
            return False
        cell = self._cell_at(x, y)
        if cell is None:
            return False
        # Iron stack has priority in its display cell
        if self.iron > 0 and cell == self._iron_cell:
            self._drag_type = "iron"
            self._drag_src = cell
            self._drag_x = x
            self._drag_y = y
            return True
        # Named item
        item = self._items.get(cell)
        if item is not None:
            self._drag_type = item
            self._drag_src = cell
            del self._items[cell]
            self._drag_x = x
            self._drag_y = y
            return True
        return False

    def on_mouse_drag(self, x: float, y: float) -> None:
        """Update the floating icon position during a drag."""
        if self._drag_type is not None:
            self._drag_x = x
            self._drag_y = y
        self._mouse_x = x
        self._mouse_y = y

    def on_mouse_move(self, x: float, y: float) -> None:
        """Track cursor position for hover tooltip."""
        self._mouse_x = x
        self._mouse_y = y

    def on_mouse_release(
        self, x: float, y: float
    ) -> Optional[tuple[str, int]]:
        """Drop the carried item.

        Returns (item_type, amount) when an item is ejected into the game world
        (dropped outside the inventory panel), or None otherwise.
        - "iron" → amount is the full iron stack count
        - named item → amount is 1
        """
        if self._drag_type is None:
            return None

        target = self._cell_at(x, y)

        if target is None and not self._panel_contains(x, y):
            # ── Ejected outside the inventory panel → drop into world ─────────
            ejected_type = self._drag_type
            if ejected_type == "iron":
                ejected_amount = self.iron
                self.iron = 0            # iron leaves the inventory
            else:
                ejected_amount = 1       # named item already removed on press
            self._drag_type = None
            self._drag_src = None
            return (ejected_type, ejected_amount)

        if target is None:
            # Dropped on panel header/border — return to source cell
            target = self._drag_src

        assert target is not None
        if self._drag_type == "iron":
            # Swap iron cell with any named item already there
            existing = self._items.get(target)
            if existing is not None:
                self._items[self._drag_src] = existing
                del self._items[target]
            self._iron_cell = target
        else:
            # Swap with whatever is in the target cell
            existing = self._items.get(target)
            if existing is not None:
                self._items[self._drag_src] = existing
            elif self._drag_src in self._items:
                del self._items[self._drag_src]
            self._items[target] = self._drag_type

        self._drag_type = None
        self._drag_src = None
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────
    def _draw_iron_in_cell(
        self, cell_x: float, cell_y: float, alpha: int = 255
    ) -> None:
        """Draw the iron icon + count badge anchored at the bottom-left of a cell."""
        if self._iron_icon is not None:
            icon_scale = (INV_CELL - 12) / max(
                self._iron_icon.width, self._iron_icon.height
            )
            arcade.draw_texture_rect(
                self._iron_icon,
                arcade.LBWH(
                    cell_x + 6, cell_y + 6,
                    self._iron_icon.width * icon_scale,
                    self._iron_icon.height * icon_scale,
                ),
                alpha=alpha,
            )
        self._t_iron.text = str(self.iron)
        self._t_iron.x = cell_x + INV_CELL - 4
        self._t_iron.y = cell_y + 3
        self._t_iron.anchor_x = "right"
        self._t_iron.draw()

    def draw(self) -> None:
        if not self.open:
            return

        ox = (SCREEN_WIDTH - INV_W) // 2
        oy = (SCREEN_HEIGHT - INV_H) // 2
        gx, gy = self._grid_origin()

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

        # Determine which cell the cursor is hovering over (for highlight)
        hover_cell = self._cell_at(self._drag_x, self._drag_y) if self._drag_type else None

        # Grid cells
        for row in range(INV_ROWS):
            for col in range(INV_COLS):
                cx_ = gx + col * INV_CELL
                cy_ = gy + (INV_ROWS - 1 - row) * INV_CELL
                cell = (row, col)
                is_src = (cell == self._drag_src and self._drag_type is not None)
                is_hover = (cell == hover_cell)

                item = self._items.get(cell)
                has_iron = (self.iron > 0 and cell == self._iron_cell)
                occupied = (item is not None) or has_iron

                if is_src:
                    fill = (60, 60, 20, 200)       # yellowish — being dragged from
                elif is_hover:
                    fill = (50, 70, 100, 220)      # blue highlight — drop target
                elif occupied:
                    fill = (50, 80, 50, 200)       # green — has item
                else:
                    fill = (30, 30, 60, 200)       # dark blue — empty

                arcade.draw_rect_filled(
                    arcade.LBWH(cx_ + 1, cy_ + 1, INV_CELL - 2, INV_CELL - 2),
                    fill,
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx_, cy_, INV_CELL, INV_CELL),
                    (60, 80, 120),
                    border_width=1,
                )

                # Draw item content (skip source cell of drag)
                if not is_src:
                    if has_iron:
                        self._draw_iron_in_cell(cx_, cy_)
                    elif item is not None:
                        # Generic item label (placeholder — replace with icon later)
                        self._t_item_label.text = item[:6]
                        self._t_item_label.x = cx_ + 4
                        self._t_item_label.y = cy_ + INV_CELL // 2 - 5
                        self._t_item_label.draw()

        # Floating icon under cursor during drag
        if self._drag_type is not None:
            half = INV_CELL // 2
            fx = self._drag_x - half
            fy = self._drag_y - half
            arcade.draw_rect_filled(
                arcade.LBWH(fx, fy, INV_CELL, INV_CELL),
                (70, 90, 40, 180),
            )
            arcade.draw_rect_outline(
                arcade.LBWH(fx, fy, INV_CELL, INV_CELL),
                arcade.color.YELLOW,
                border_width=1,
            )
            if self._drag_type == "iron":
                self._draw_iron_in_cell(fx, fy, alpha=200)
            else:
                self._t_drag_label.text = self._drag_type[:6]
                self._t_drag_label.x = fx + 4
                self._t_drag_label.y = fy + INV_CELL // 2 - 5
                self._t_drag_label.draw()

        # ── Hover tooltip ────────────────────────────────────────────────────
        tip_cell = self._cell_at(self._mouse_x, self._mouse_y)
        if tip_cell is not None and self._drag_type is None:
            row, col = tip_cell
            is_iron = (self.iron > 0 and tip_cell == self._iron_cell)
            item = self._items.get(tip_cell)
            if is_iron:
                tip_label = f"Iron  \u00d7{self.iron}"
            elif item is not None:
                tip_label = item
            else:
                tip_label = None

            if tip_label:
                gx2, gy2 = self._grid_origin()
                cell_cx = gx2 + col * INV_CELL + INV_CELL // 2
                cell_ty = gy2 + (INV_ROWS - 1 - row) * INV_CELL + INV_CELL + 2
                # Keep tooltip inside screen
                if cell_ty + 16 > SCREEN_HEIGHT:
                    cell_ty = gy2 + (INV_ROWS - 1 - row) * INV_CELL - 18
                tw = len(tip_label) * 6 + 12
                tx0 = max(2, min(SCREEN_WIDTH - tw - 2, cell_cx - tw // 2))
                arcade.draw_rect_filled(
                    arcade.LBWH(tx0, cell_ty, tw, 15), (20, 20, 50, 230)
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(tx0, cell_ty, tw, 15),
                    arcade.color.LIGHT_GRAY, border_width=1,
                )
                self._t_tooltip.text = tip_label
                self._t_tooltip.x = tx0 + tw // 2
                self._t_tooltip.y = cell_ty + 7
                self._t_tooltip.draw()


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
        self.shields: int = PLAYER_MAX_SHIELD
        self.max_shields: int = PLAYER_MAX_SHIELD
        self._shield_acc: float = 0.0   # fractional shield regen accumulator
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

        # Camera shake state
        self._shake_timer: float = 0.0   # seconds remaining
        self._shake_amp: float = 0.0     # current max pixel offset

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
        self._iron_tex = arcade.load_texture(IRON_ICON_PNG)

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

        # Collision bump sound
        self._bump_snd = arcade.load_sound(
            os.path.join(SFX_BIO_DIR, "Game Biomechanical Impact Sound 1.wav")
        )

        self.asteroid_list = arcade.SpriteList()
        self.explosion_list = arcade.SpriteList()
        self.iron_pickup_list = arcade.SpriteList()

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

        # ── Alien ships ──────────────────────────────────────────────────────
        # Ship sprite: first column, first row of Ship.png.
        # Alpha-channel analysis gives the content bounds: x=364..824, y=305..814.
        _pil_ship = PILImage.open(ALIEN_SHIP_PNG).convert("RGBA")
        alien_ship_tex = arcade.Texture(_pil_ship.crop((364, 305, 825, 815)))

        # Laser sprite: last column of first row in Effects.png (x=4299..4358, y=82..309).
        # The bolt faces LEFT in the source file; rotate 90° CCW so it faces NORTH at
        # angle=0, matching the same angle convention used by all other Projectiles.
        _pil_fx = PILImage.open(ALIEN_FX_PNG).convert("RGBA")
        _pil_laser = _pil_fx.crop((4299, 82, 4359, 310))          # 60×228 px, points left
        alien_laser_tex = arcade.Texture(_pil_laser.rotate(90, expand=True))  # now 228×60, points up

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

        # ── Inventory ────────────────────────────────────────────────────────
        self.inventory = Inventory(iron_icon=self._iron_tex)

        # ── HUD text objects (pre-built to avoid per-frame draw_text cost) ───
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
        # Weapon readout
        self._t_wpn_hdr  = arcade.Text("WEAPON", cx, SCREEN_HEIGHT - 210,
                                       arcade.color.LIGHT_GRAY, 9,
                                       anchor_x="center")
        self._t_wpn_name = arcade.Text("", cx, SCREEN_HEIGHT - 226,
                                       arcade.color.YELLOW, 10, bold=True,
                                       anchor_x="center")
        # Controls reference
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
        # FPS overlay (toggled with F key)
        self._show_fps: bool = False
        self._fps: float = 60.0          # smoothed estimate
        self._t_fps = arcade.Text("", 10, SCREEN_HEIGHT - 400,
                                  arcade.color.YELLOW, 10, bold=True)

        # Mini-map label (sits just above the map rectangle)
        self._t_minimap = arcade.Text(
            "MINI-MAP",
            STATUS_WIDTH // 2,
            MINIMAP_Y + MINIMAP_H + 3,
            arcade.color.LIGHT_GRAY, 9,
            anchor_x="center",
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

    def _spawn_iron_pickup(
        self,
        x: float,
        y: float,
        amount: int = ASTEROID_IRON_YIELD,
        lifetime: Optional[float] = None,
    ) -> None:
        """Spawn an iron token at world position (x, y).

        amount   : iron units the token is worth when collected.
        lifetime : seconds until silent despawn (None = permanent until picked up).
        """
        pickup = IronPickup(self._iron_tex, x, y, amount=amount, lifetime=lifetime)
        self.iron_pickup_list.append(pickup)

    def _trigger_shake(self) -> None:
        """Start a brief camera shake."""
        self._shake_timer = SHAKE_DURATION

    def _apply_damage_to_player(self, amount: int) -> None:
        """Apply damage to the player's shields first, then HP.

        Shield absorbs damage down to 0; overflow carries into HP.
        """
        if self.player.shields > 0:
            absorbed = min(self.player.shields, amount)
            self.player.shields -= absorbed
            amount -= absorbed
        if amount > 0:
            self.player.hp = max(0, self.player.hp - amount)
        self._shake_amp = SHAKE_AMPLITUDE

    def _draw_minimap(self) -> None:
        """Draw a scaled overview of the world inside the status panel."""
        mx, my = MINIMAP_X, MINIMAP_Y
        mw, mh = MINIMAP_W, MINIMAP_H

        # Background + border
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

        # Asteroids — small gray circles
        for asteroid in self.asteroid_list:
            ax, ay = to_map(asteroid.center_x, asteroid.center_y)
            arcade.draw_circle_filled(ax, ay, 2.0, (150, 150, 150))

        # Iron pickups — tiny orange dots
        for pickup in self.iron_pickup_list:
            px, py = to_map(pickup.center_x, pickup.center_y)
            arcade.draw_circle_filled(px, py, 2.0, (255, 165, 0))

        # Alien ships — red dots
        for alien in self.alien_list:
            amx, amy = to_map(alien.center_x, alien.center_y)
            arcade.draw_circle_filled(amx, amy, 2.0, (220, 50, 50))

        # Player ship — white dot + cyan heading line
        sx, sy = to_map(self.player.center_x, self.player.center_y)
        rad = math.radians(self.player.heading)
        lx = sx + math.sin(rad) * 5
        ly = sy + math.cos(rad) * 5
        arcade.draw_line(sx, sy, lx, ly, arcade.color.CYAN, 1)
        arcade.draw_circle_filled(sx, sy, 3.0, arcade.color.WHITE)

    # ── Drawing ──────────────────────────────────────────────────────────────
    def on_draw(self) -> None:
        self.clear()

        # Centre camera on player, clamped so edges don't go beyond the world
        hw = SCREEN_WIDTH / 2
        hh = SCREEN_HEIGHT / 2
        cx = max(hw, min(WORLD_WIDTH - hw, self.player.center_x))
        cy = max(hh, min(WORLD_HEIGHT - hh, self.player.center_y))

        # Apply camera shake offset when active
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
            self.player_list.draw()
            for spark in self.hit_sparks:
                spark.draw()

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
        if self._show_fps:
            self._t_fps.text = f"FPS  {self._fps:>6.1f}"
            self._t_fps.draw()

        # Dynamic readouts
        spd = math.hypot(self.player.vel_x, self.player.vel_y)
        self._t_spd.text = f"SPD   {spd:>7.1f}"
        self._t_spd.draw()
        self._t_hdg.text = f"HDG   {self.player.heading:>6.1f}\u00b0"
        self._t_hdg.draw()
        self._t_iron_hud.text = f"IRON  {self.inventory.iron:>7}"
        self._t_iron_hud.draw()
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
            arcade.LBWH(10, SCREEN_HEIGHT - 156, int(190 * hp_frac), 10), hp_color
        )
        # Shield bar — live; fades from bright cyan to dark blue as shields fall
        shield_frac = max(0.0, self.player.shields / self.player.max_shields)
        arcade.draw_rect_filled(
            arcade.LBWH(10, SCREEN_HEIGHT - 192, int(190 * shield_frac), 10),
            (0, 140, 210),
        )

        # Mini-map
        self._draw_minimap()

    # ── Update ───────────────────────────────────────────────────────────────
    def on_update(self, delta_time: float) -> None:
        # ── Smoothed FPS (exponential moving average) ────────────────────────
        if delta_time > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / delta_time)

        # ── Shake timer tick ─────────────────────────────────────────────────
        if self._shake_timer > 0.0:
            self._shake_timer = max(0.0, self._shake_timer - delta_time)

        # ── Shield regeneration (1 pt / 2 s = 0.5 pt/s) ─────────────────────
        if self.player.shields < self.player.max_shields:
            self.player._shield_acc += SHIELD_REGEN_RATE * delta_time
            pts = int(self.player._shield_acc)
            if pts > 0:
                self.player._shield_acc -= pts
                self.player.shields = min(self.player.max_shields,
                                          self.player.shields + pts)

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
                asteroid = hit_asteroids[0]
                # Spawn green hit-spark at impact point
                self.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                proj.remove_from_sprite_lists()
                asteroid.take_damage(int(proj.damage))
                if asteroid.hp <= 0:
                    ax, ay = asteroid._base_x, asteroid._base_y
                    self._spawn_explosion(ax, ay)
                    arcade.play_sound(self._explosion_snd, volume=0.7)
                    asteroid.remove_from_sprite_lists()
                    # Drop one iron icon at the destruction site
                    self._spawn_iron_pickup(ax, ay)

        # ── Animate asteroids (spin) ─────────────────────────────────────────
        for asteroid in self.asteroid_list:
            asteroid.update_asteroid(delta_time)

        # ── Iron pickup: fly toward ship + collect ───────────────────────────
        sx, sy = self.player.center_x, self.player.center_y
        for pickup in list(self.iron_pickup_list):
            collected = pickup.update_pickup(delta_time, sx, sy, SHIP_RADIUS)
            if collected:
                self.inventory.add_iron(pickup.amount)

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

            # --- Damage + bump sound + screen shake (once per cooldown) -------
            if self.player._collision_cd <= 0.0:
                self._apply_damage_to_player(SHIP_COLLISION_DAMAGE)
                self.player._collision_cd = SHIP_COLLISION_COOLDOWN
                arcade.play_sound(self._bump_snd, volume=0.5)
                self._trigger_shake()

        # ── Alien ship AI + movement ─────────────────────────────────────────
        px, py = self.player.center_x, self.player.center_y
        for alien in list(self.alien_list):
            proj = alien.update_alien(delta_time, px, py)
            if proj is not None:
                self.alien_projectile_list.append(proj)

        # ── Advance alien projectiles ─────────────────────────────────────────
        for proj in list(self.alien_projectile_list):
            proj.update_projectile(delta_time)

        # ── Player laser hits on alien ships ─────────────────────────────────
        for proj in list(self.projectile_list):
            hit_aliens = arcade.check_for_collision_with_list(proj, self.alien_list)
            if hit_aliens:
                alien = hit_aliens[0]
                # Spawn hit-spark at impact point before removing projectile
                self.hit_sparks.append(HitSpark(proj.center_x, proj.center_y))
                self._trigger_shake()
                proj.remove_from_sprite_lists()
                alien.take_damage(int(proj.damage))
                if alien.hp <= 0:
                    self._spawn_explosion(alien.center_x, alien.center_y)
                    arcade.play_sound(self._explosion_snd, volume=0.7)
                    alien.remove_from_sprite_lists()

        # ── Alien laser hits on player ────────────────────────────────────────
        for proj in list(self.alien_projectile_list):
            if arcade.check_for_collision(proj, self.player):
                proj.remove_from_sprite_lists()
                self._apply_damage_to_player(int(proj.damage))
                self._trigger_shake()
                arcade.play_sound(self._bump_snd, volume=0.3)

        # ── Advance explosion animations ─────────────────────────────────────
        for exp in list(self.explosion_list):
            exp.update_explosion(delta_time)

        # ── Advance hit sparks ────────────────────────────────────────────────
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
                    # Spawn the pickup EJECT_DIST px from the ship's hull edge so
                    # it sits safely outside the auto-pickup zone.  Random direction
                    # ensures it isn't immediately re-attracted.
                    eject_angle = random.uniform(0.0, math.tau)
                    eject_r = SHIP_RADIUS + EJECT_DIST   # 88 px from centre
                    eject_x = max(0.0, min(WORLD_WIDTH,
                                  self.player.center_x + math.cos(eject_angle) * eject_r))
                    eject_y = max(0.0, min(WORLD_HEIGHT,
                                  self.player.center_y + math.sin(eject_angle) * eject_r))
                    self._spawn_iron_pickup(
                        eject_x, eject_y,
                        amount=amount,
                        lifetime=WORLD_ITEM_LIFETIME,
                    )
                # Named items: add handlers here as new item types are introduced

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        self.inventory.on_mouse_move(x, y)


# ── Entry point ──────────────────────────────────────────────────────────────
def main() -> None:
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
    window.show_view(GameView())
    arcade.run()


if __name__ == "__main__":
    main()
