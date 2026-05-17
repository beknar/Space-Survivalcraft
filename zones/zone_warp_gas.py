"""Gas cloud warp zone — maze of damaging gaseous clouds."""
from __future__ import annotations

import random
from collections import deque
from typing import TYPE_CHECKING

import arcade
from PIL import Image as PILImage, ImageDraw, ImageFilter

from zones import ZoneID
from zones.zone_warp_base import WarpZoneBase, WARP_ZONE_WIDTH, WARP_ZONE_HEIGHT

if TYPE_CHECKING:
    from game_view import GameView

_CLOUD_DAMAGE = 15          # damage per tick (but ticks faster)
_CLOUD_COOLDOWN = 0.5       # seconds between damage ticks
_CLOUD_RADIUS = 80.0        # collision radius
_CLOUD_COUNT = 40           # number of clouds in the maze
_CLOUD_SIZE = 160           # texture size
_EXTRA_LARGE_COUNT = 3      # huge clouds that are hard to avoid

# Path connectivity check (run once at spawn): coarse-grid BFS that
# guarantees at least one safe corridor from the bottom of the zone to
# the top.  ``_PATH_CELL_PX`` is the cell size of the BFS grid;
# ``_PATH_CLEARANCE_PX`` is the buffer beyond ``cloud.radius`` a cell
# centre must clear to count as passable (the ship has 28 px radius
# but ``GasArea.contains_point`` only damages on centre-inside-radius,
# so a 20 px buffer leaves room for the ship body without forcing the
# corridor wider than necessary).
_PATH_CELL_PX = 64
_PATH_CLEARANCE_PX = 20.0


def _generate_cloud_texture() -> arcade.Texture:
    """Procedurally generate a green-purple gas cloud texture."""
    size = _CLOUD_SIZE
    img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    for _ in range(40):
        r = random.gauss(size * 0.2, size * 0.1)
        r = max(4, min(size * 0.35, r))
        ox = random.gauss(0, size * 0.1)
        oy = random.gauss(0, size * 0.1)
        green = random.randint(80, 180)
        red = random.randint(60, 140)
        blue = random.randint(40, 120)
        alpha = random.randint(20, 50)
        draw.ellipse(
            [int(cx + ox - r), int(cy + oy - r),
             int(cx + ox + r), int(cy + oy + r)],
            fill=(red, green, blue, alpha))
    img = img.filter(ImageFilter.GaussianBlur(radius=4))
    return arcade.Texture(img)


from sprites.gas_area import GasArea as GasCloud


class GasCloudWarpZone(WarpZoneBase):
    zone_id = ZoneID.WARP_GAS

    def __init__(self) -> None:
        super().__init__()
        self._clouds: arcade.SpriteList = arcade.SpriteList()
        self._cloud_tex: arcade.Texture | None = None
        self._damage_cd: float = 0.0

    def setup(self, gv: GameView) -> None:
        super().setup(gv)
        if self._cloud_tex is None:
            self._cloud_tex = _generate_cloud_texture()
        self._clouds = arcade.SpriteList()
        self._damage_cd = 0.0
        self._in_gas: bool = False  # for screen darkening
        # Generate maze-like cloud layout (grid with gaps).  At higher
        # ``_danger`` we keep more cells filled and spawn extra large
        # clouds so the 2x variants feel markedly denser.
        margin = 150
        cols = 5
        rows = 12
        spacing_x = (WARP_ZONE_WIDTH - margin * 2) / cols
        spacing_y = (WARP_ZONE_HEIGHT - margin * 2) / rows
        skip_chance = 0.4 / max(1.0, self._danger)  # 0.4 ⇒ 0.2 at 2x
        for row in range(rows):
            for col in range(cols):
                if random.random() < skip_chance:
                    continue
                x = margin + col * spacing_x + random.uniform(-30, 30)
                y = margin + row * spacing_y + random.uniform(-30, 30)
                x = max(100, min(WARP_ZONE_WIDTH - 100, x))
                y = max(100, min(WARP_ZONE_HEIGHT - 100, y))
                self._clouds.append(GasCloud(self._cloud_tex, x, y,
                                            world_w=WARP_ZONE_WIDTH, world_h=WARP_ZONE_HEIGHT,
                                            mobile=True))
        # Extra-large clouds that are hard to avoid — count scales
        # with ``_danger``.
        _large_tex = _generate_cloud_texture()
        large_count = int(round(_EXTRA_LARGE_COUNT * max(1.0, self._danger)))
        for _ in range(large_count):
            lx = random.uniform(400, WARP_ZONE_WIDTH - 400)
            ly = random.uniform(1000, WARP_ZONE_HEIGHT - 1000)
            self._clouds.append(GasCloud(_large_tex, lx, ly, size=1500,
                                         world_w=WARP_ZONE_WIDTH, world_h=WARP_ZONE_HEIGHT,
                                         mobile=True))
        # Guarantee at least one corridor exists at spawn.  Clouds drift
        # afterwards, so this only addresses the placement-time wall
        # case (mostly relevant when two extra-large clouds line up).
        self._ensure_path_through()

    def teardown(self, gv: GameView) -> None:
        super().teardown(gv)
        self._clouds.clear()

    def _update_hazards(self, gv: GameView, dt: float) -> None:
        self._damage_cd = max(0.0, self._damage_cd - dt)
        px, py = gv.player.center_x, gv.player.center_y
        self._in_gas = False
        for cloud in self._clouds:
            if cloud.contains_point(px, py):
                self._in_gas = True
                # Slow the player while in gas
                gv.player.vel_x *= 0.97
                gv.player.vel_y *= 0.97
                if self._damage_cd <= 0.0:
                    gv._apply_damage_to_player(int(_CLOUD_DAMAGE))
                    gv._trigger_shake()
                    gv._flash_game_msg("Toxic gas!", 0.5)
                    self._damage_cd = _CLOUD_COOLDOWN
                break

    def get_minimap_objects(self):
        return self._clouds, arcade.SpriteList()

    def _draw_hazards(self, gv: GameView, cx: float, cy: float,
                      hw: float, hh: float) -> None:
        self._clouds.draw()
        # Screen darkening when inside gas
        if self._in_gas:
            arcade.draw_rect_filled(
                arcade.LBWH(cx - hw - 50, cy - hh - 50, hw * 2 + 100, hh * 2 + 100),
                (20, 40, 10, 120))

    # ── Spawn-time connectivity guarantee ───────────────────────────────
    def _has_path_bottom_to_top(self) -> bool:
        """Coarse-grid BFS: returns True iff some bottom-row cell
        reaches some top-row cell without crossing a cloud."""
        cell = _PATH_CELL_PX
        cols = WARP_ZONE_WIDTH // cell
        rows = WARP_ZONE_HEIGHT // cell
        blocked = [[False] * cols for _ in range(rows)]
        for cloud in self._clouds:
            cr = cloud.radius + _PATH_CLEARANCE_PX
            cr2 = cr * cr
            min_col = max(0, int((cloud.center_x - cr) // cell))
            max_col = min(cols - 1, int((cloud.center_x + cr) // cell))
            min_row = max(0, int((cloud.center_y - cr) // cell))
            max_row = min(rows - 1, int((cloud.center_y + cr) // cell))
            for r in range(min_row, max_row + 1):
                cy = r * cell + cell * 0.5
                dy = cy - cloud.center_y
                dy2 = dy * dy
                for c in range(min_col, max_col + 1):
                    if blocked[r][c]:
                        continue
                    cx = c * cell + cell * 0.5
                    dx = cx - cloud.center_x
                    if dx * dx + dy2 < cr2:
                        blocked[r][c] = True
        visited = [[False] * cols for _ in range(rows)]
        q: deque[tuple[int, int]] = deque()
        for c in range(cols):
            if not blocked[0][c]:
                visited[0][c] = True
                q.append((0, c))
        while q:
            r, c = q.popleft()
            if r == rows - 1:
                return True
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if (0 <= nr < rows and 0 <= nc < cols
                        and not visited[nr][nc] and not blocked[nr][nc]):
                    visited[nr][nc] = True
                    q.append((nr, nc))
        return False

    def _ensure_path_through(self) -> None:
        """Remove largest clouds (one at a time) until a corridor opens.
        Termination is guaranteed: in the worst case every cloud is
        removed and the empty zone is trivially passable."""
        if self._has_path_bottom_to_top():
            return
        candidates = sorted(self._clouds, key=lambda c: -c.radius)
        for cloud in candidates:
            cloud.remove_from_sprite_lists()
            if self._has_path_bottom_to_top():
                return
