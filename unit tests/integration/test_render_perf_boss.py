"""Render-perf microbenchmarks targeting the Double Star boss.

These need a real Arcade window (GL context) but do NOT construct a
full GameView.  They isolate the per-frame draw cost of:

  - The boss sprite alone (one rotated textured quad)
  - The boss + a heavy spread-shot scene (boss + 30 projectiles +
    10 hit sparks)
  - The boss texture loaded into a SpriteList alongside other Zone 1
    textures (atlas pressure)

If the boss draw path regresses asymptotically (e.g. someone disables
batching for boss projectiles, or moves to per-frame Texture
construction), one of these will fail rather than presenting as a
vague "FPS drop in TestZone1WithBoss".

Run with: ``pytest "unit tests/integration/test_render_perf_boss.py" -v -s``
"""
from __future__ import annotations

import time

import arcade
import pytest
from PIL import Image as PILImage

# ── Configuration ──────────────────────────────────────────────────────────

MIN_FPS = 40
FRAMES = 60


def _measure(draw_fn, n_warmup: int = 5, n_measure: int = FRAMES) -> float:
    for _ in range(n_warmup):
        draw_fn()
    start = time.perf_counter()
    for _ in range(n_measure):
        draw_fn()
    elapsed = time.perf_counter() - start
    fps = n_measure / elapsed if elapsed > 0 else 999.0
    print(f"  [render-perf-boss] {fps:.1f} FPS "
          f"({n_measure} frames in {elapsed:.3f}s)")
    return fps


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def win(real_window):
    """Reuse the session-scoped hidden Arcade window."""
    return real_window


@pytest.fixture
def boss_textures(win):
    """Load the real boss + boss-laser textures that the game uses.

    A first-load + cropped sheet would be too heavy here; we load the
    final flat textures that ``world_setup`` produces."""
    from constants import (
        BOSS_MONSTER_PNG, BOSS_FRAME_SIZE, BOSS_SHEET_COLS,
        BOSS_SHEET_ROWS,
    )
    sheet = arcade.load_spritesheet(BOSS_MONSTER_PNG)
    # Use the first frame from the 8×8 sheet — what spawn_boss does too.
    boss_tex = sheet.get_texture(arcade.LBWH(0, 0,
                                             BOSS_FRAME_SIZE,
                                             BOSS_FRAME_SIZE))
    laser_img = PILImage.new("RGBA", (4, 32), (255, 80, 80, 255))
    laser_tex = arcade.Texture(laser_img)
    return boss_tex, laser_tex


# ═══════════════════════════════════════════════════════════════════════════
#  1. Boss sprite alone — one rotated quad, the absolute baseline
# ═══════════════════════════════════════════════════════════════════════════

class TestBossSpriteSoloDrawPerf:
    def test_single_boss_sprite_above_threshold(self, win, boss_textures):
        from sprites.boss import BossAlienShip
        boss_tex, laser_tex = boss_textures
        boss = BossAlienShip(boss_tex, laser_tex,
                             400.0, 300.0, 200.0, 200.0)
        boss._heading = 45.0
        boss.angle = 45.0
        slist = arcade.SpriteList()
        slist.append(boss)

        def draw():
            win.clear()
            slist.draw()
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"Single boss sprite draw: {fps:.1f} FPS < {MIN_FPS} FPS")


# ═══════════════════════════════════════════════════════════════════════════
#  2. Boss + heavy projectile load — spread shot worst-case
# ═══════════════════════════════════════════════════════════════════════════

class TestBossWithProjectilesDrawPerf:
    def test_boss_plus_30_projectiles(self, win, boss_textures):
        """Boss + 30 projectiles (10 cycles of a 3-shot spread on
        screen at once) + 10 hit sparks.  Catches projectile-batch
        regressions specific to the boss combat scene."""
        from sprites.boss import BossAlienShip
        from sprites.projectile import Projectile
        from sprites.explosion import HitSpark
        from constants import BOSS_CANNON_SPEED, BOSS_CANNON_RANGE

        boss_tex, laser_tex = boss_textures
        boss = BossAlienShip(boss_tex, laser_tex,
                             400.0, 300.0, 200.0, 200.0)
        boss_list = arcade.SpriteList()
        boss_list.append(boss)

        proj_list = arcade.SpriteList()
        for i in range(30):
            proj = Projectile(
                laser_tex,
                400.0 + (i % 6) * 30, 300.0 + (i // 6) * 30,
                30.0 * i, BOSS_CANNON_SPEED, BOSS_CANNON_RANGE,
                scale=0.8, damage=40.0,
            )
            proj_list.append(proj)

        sparks = [HitSpark(50.0 + i * 30, 50.0 + i * 20) for i in range(10)]

        def draw():
            win.clear()
            boss_list.draw()
            proj_list.draw()
            for s in sparks:
                s.draw()
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"Boss + 30 projectiles + 10 sparks: {fps:.1f} FPS < {MIN_FPS}")


# ═══════════════════════════════════════════════════════════════════════════
#  3. Boss texture in a mixed SpriteList — atlas pressure
# ═══════════════════════════════════════════════════════════════════════════

class TestBossTextureMixedAtlasPerf:
    def test_boss_with_50_other_sprites(self, win, boss_textures):
        """Boss sprite drawn alongside 50 other textured sprites.
        Validates the atlas can fit the 128×128 boss frame without
        forcing a re-batch.  If this regresses to 1 draw call per
        sprite (atlas miss), FPS will collapse."""
        from sprites.boss import BossAlienShip
        boss_tex, laser_tex = boss_textures

        # 50 small sprites of a different texture (forces multiple
        # entries in the atlas alongside the boss).
        small_img = PILImage.new("RGBA", (16, 16), (80, 200, 80, 255))
        small_tex = arcade.Texture(small_img)
        slist = arcade.SpriteList()
        for i in range(50):
            s = arcade.Sprite(small_tex)
            s.center_x = (i % 10) * 70
            s.center_y = (i // 10) * 70
            slist.append(s)

        boss = BossAlienShip(boss_tex, laser_tex,
                             400.0, 300.0, 200.0, 200.0)
        boss_list = arcade.SpriteList()
        boss_list.append(boss)

        def draw():
            win.clear()
            slist.draw()
            boss_list.draw()
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"Boss + 50 mixed sprites: {fps:.1f} FPS < {MIN_FPS}")
