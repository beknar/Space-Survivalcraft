"""Space Survivalcraft — main entry point."""
from __future__ import annotations

import math
import os

import arcade
import arcade.camera

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
DAMPING: float = 0.985           # per-frame velocity multiplier (space drag)

DEAD_ZONE: float = 0.15          # Gamepad analogue stick dead zone

# ── Asset paths ─────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

STARFIELD_DIR = os.path.join(
    _HERE, "assets",
    "SBS - Seamless Space Backgrounds - Large 1024x1024",
    "Large 1024x1024", "Starfields",
)
SHMUP_DIR = os.path.join(_HERE, "assets", "ShmupAssets_V1")


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

    _COLS = 4   # columns in shmup_player.png sprite sheet
    _ROWS = 3   # rows

    def __init__(self) -> None:
        sheet = os.path.join(SHMUP_DIR, "shmup_player.png")

        # In Arcade 3.x, load_spritesheet() returns a SpriteSheet object.
        # Use get_texture(rect) to extract individual frames.
        ss = arcade.load_spritesheet(sheet)
        fw = ss.image.width // self._COLS
        fh = ss.image.height // self._ROWS
        # Frame 0: top-left region of the sheet (row 0, col 0)
        texture = ss.get_texture(arcade.LBWH(0, 0, fw, fh))
        super().__init__(path_or_texture=texture, scale=1.5)

        # Start at world centre
        self.center_x = WORLD_WIDTH / 2
        self.center_y = WORLD_HEIGHT / 2

        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        # heading: 90° = up, matching the sprite's natural orientation
        self.heading: float = 90.0

    def apply_input(
        self,
        dt: float,
        rotate_left: bool,
        rotate_right: bool,
        thrust_fwd: bool,
        thrust_bwd: bool,
    ) -> None:
        # Rotation
        if rotate_left:
            self.heading = (self.heading + ROT_SPEED * dt) % 360
        if rotate_right:
            self.heading = (self.heading - ROT_SPEED * dt) % 360

        # Sprite visual rotation:
        #   sprite faces up at angle=0; heading 90° = up → offset by -90
        self.angle = self.heading - 90.0

        # Thrust along current heading
        rad = math.radians(self.heading)
        if thrust_fwd:
            self.vel_x += math.cos(rad) * THRUST * dt
            self.vel_y += math.sin(rad) * THRUST * dt
        if thrust_bwd:
            self.vel_x -= math.cos(rad) * BRAKE * dt
            self.vel_y -= math.sin(rad) * BRAKE * dt

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


# ── Game view ────────────────────────────────────────────────────────────────
class GameView(arcade.View):

    def __init__(self) -> None:
        super().__init__()

        # Player
        self.player = PlayerShip()
        self.player_list = arcade.SpriteList()
        self.player_list.append(self.player)

        # Tiled background texture
        self.bg_texture = arcade.load_texture(
            os.path.join(STARFIELD_DIR, "Starfield_01-1024x1024.png")
        )

        # World camera (follows player)
        self.world_cam = arcade.camera.Camera2D()
        # UI camera (static — for the status panel overlay)
        self.ui_cam = arcade.camera.Camera2D()

        # Held-key tracking
        self._keys: set[int] = set()

        # Gamepad
        self.joystick = None
        joysticks = arcade.get_joysticks()
        if joysticks:
            self.joystick = joysticks[0]
            self.joystick.open()
            print(f"Gamepad connected: {self.joystick.device.name}")

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
            self.player_list.draw()

        with self.ui_cam.activate():
            self._draw_status_panel()

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

        # Title
        arcade.draw_text(
            "STATUS", STATUS_WIDTH // 2, SCREEN_HEIGHT - 26,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )

        # Speed and heading readouts
        spd = math.hypot(self.player.vel_x, self.player.vel_y)
        y = SCREEN_HEIGHT - 60
        arcade.draw_text(f"SPD   {spd:>7.1f}", 10, y,
                         arcade.color.WHITE, 11)
        arcade.draw_text(f"HDG   {self.player.heading:>6.1f}\u00b0", 10, y - 20,
                         arcade.color.WHITE, 11)

        # HP bar (placeholder — full)
        y -= 60
        arcade.draw_text("HP", 10, y, arcade.color.LIME_GREEN, 10, bold=True)
        arcade.draw_rect_filled(arcade.LBWH(10, y - 16, 190, 10), (0, 180, 0))

        # Shield bar (placeholder — full)
        y -= 36
        arcade.draw_text("SHIELD", 10, y, arcade.color.CYAN, 10, bold=True)
        arcade.draw_rect_filled(arcade.LBWH(10, y - 16, 190, 10), (0, 140, 210))

        # Controls reference
        y -= 50
        arcade.draw_text(
            "CONTROLS", STATUS_WIDTH // 2, y,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
        )
        for line in (
            "Left/Right  Rotate",
            "Up / W      Thrust",
            "Down / S    Brake",
        ):
            y -= 18
            arcade.draw_text(line, 10, y, arcade.color.LIGHT_GRAY, 9)

        if self.joystick:
            y -= 26
            arcade.draw_text(
                "Gamepad: connected", 10, y, arcade.color.LIME_GREEN, 9,
            )

    # ── Update ───────────────────────────────────────────────────────────────
    def on_update(self, delta_time: float) -> None:
        rl = arcade.key.LEFT in self._keys or arcade.key.A in self._keys
        rr = arcade.key.RIGHT in self._keys or arcade.key.D in self._keys
        tf = arcade.key.UP in self._keys or arcade.key.W in self._keys
        tb = arcade.key.DOWN in self._keys or arcade.key.S in self._keys

        if self.joystick:
            lx = self.joystick.x   # left stick X: -1 = left, +1 = right
            ly = self.joystick.y   # left stick Y: -1 = up (forward), +1 = down
            rl |= lx < -DEAD_ZONE
            rr |= lx > DEAD_ZONE
            tf |= ly < -DEAD_ZONE
            tb |= ly > DEAD_ZONE

        self.player.apply_input(delta_time, rl, rr, tf, tb)

    # ── Input ────────────────────────────────────────────────────────────────
    def on_key_press(self, key: int, modifiers: int) -> None:
        self._keys.add(key)
        if key == arcade.key.ESCAPE:
            arcade.exit()

    def on_key_release(self, key: int, modifiers: int) -> None:
        self._keys.discard(key)


# ── Entry point ──────────────────────────────────────────────────────────────
def main() -> None:
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
    window.show_view(GameView())
    arcade.run()


if __name__ == "__main__":
    main()
