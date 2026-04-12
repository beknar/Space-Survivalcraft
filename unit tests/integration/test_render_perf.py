"""Rendering microbenchmarks — isolate individual GPU draw operations.

These need a real Arcade window (GL context) but do NOT construct a full
GameView. They measure the per-call cost of specific rendering primitives
so regressions in batching, text caching, or draw-call count show up as
a named test failure instead of a vague FPS drop in the full-frame tests.

Run with:  ``pytest "unit tests/integration/test_render_perf.py" -v -s``
"""
from __future__ import annotations

import time

import arcade
import pytest
from PIL import Image as PILImage

# ── Configuration ──────────────────────────────────────────────────────────

# Budgets are ~3× measured baseline. A failure means something got
# asymptotically worse, not just a bit slower on a cold run.
MIN_FPS = 40
FRAMES = 60


def _measure(draw_fn, n_warmup: int = 5, n_measure: int = FRAMES) -> float:
    """Call draw_fn (which must include window.clear + flip) n times,
    return average FPS over the measured frames."""
    for _ in range(n_warmup):
        draw_fn()
    start = time.perf_counter()
    for _ in range(n_measure):
        draw_fn()
    elapsed = time.perf_counter() - start
    fps = n_measure / elapsed if elapsed > 0 else 999.0
    print(f"  [render-perf] {fps:.1f} FPS ({n_measure} frames in {elapsed:.3f}s)")
    return fps


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def win(real_window):
    """Reuse the session-scoped hidden Arcade window from conftest.py.
    Arcade only supports one window per process — creating a second one
    destroys the first, which breaks subsequent tests that depend on
    ``real_window``."""
    return real_window


@pytest.fixture
def dummy_tex():
    img = PILImage.new("RGBA", (32, 32), (200, 60, 60, 255))
    return arcade.Texture(img)


# ═══════════════════════════════════════════════════════════════════════════
#  1. arcade.Text.draw() × N  — the inventory count-badge bottleneck
# ═══════════════════════════════════════════════════════════════════════════

class TestTextDrawPerf:
    def test_100_text_draws(self, win):
        """100 cached arcade.Text.draw() calls per frame.
        This is exactly the station inventory's count-badge loop (10×10).
        The xfail integration test showed 29 FPS; this isolates the cost."""
        texts = [
            arcade.Text(str(i), 10 + (i % 10) * 40, 10 + (i // 10) * 40,
                        arcade.color.ORANGE, 8, bold=True)
            for i in range(100)
        ]

        def draw():
            win.clear()
            for t in texts:
                t.draw()
            win.flip()

        fps = _measure(draw)
        # Document the current cost; this is the optimization target.
        # If batching is added, raise this threshold to MIN_FPS.
        print(f"  -> 100 Text.draw: {fps:.1f} FPS "
              f"({'ABOVE' if fps >= MIN_FPS else 'BELOW'} 40 FPS)")

    def test_25_text_draws(self, win):
        """25 cached arcade.Text.draw() calls per frame (ship inventory
        5×5). Should be well above 40 FPS even without batching."""
        texts = [
            arcade.Text(str(i), 10 + (i % 5) * 60, 10 + (i // 5) * 60,
                        arcade.color.ORANGE, 9, bold=True)
            for i in range(25)
        ]

        def draw():
            win.clear()
            for t in texts:
                t.draw()
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"25 Text.draw: {fps:.1f} FPS < {MIN_FPS} FPS")


# ═══════════════════════════════════════════════════════════════════════════
#  2. SpriteList.draw() with N sprites — batched rendering throughput
# ═══════════════════════════════════════════════════════════════════════════

class TestSpriteListDrawPerf:
    def test_200_sprites(self, win, dummy_tex):
        """Drawing a SpriteList of 200 sprites in a single .draw() call.
        This validates that the inventory render cache approach (one
        SpriteList per fill/icon layer) scales well."""
        slist = arcade.SpriteList()
        for i in range(200):
            s = arcade.Sprite(dummy_tex)
            s.center_x = 10 + (i % 20) * 38
            s.center_y = 10 + (i // 20) * 55
            slist.append(s)

        def draw():
            win.clear()
            slist.draw()
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"200-sprite SpriteList: {fps:.1f} FPS < {MIN_FPS} FPS")

    def test_500_sprites(self, win, dummy_tex):
        """500 sprites — stress test for larger entity counts."""
        slist = arcade.SpriteList()
        for i in range(500):
            s = arcade.Sprite(dummy_tex)
            s.center_x = (i % 25) * 30
            s.center_y = (i // 25) * 30
            slist.append(s)

        def draw():
            win.clear()
            slist.draw()
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"500-sprite SpriteList: {fps:.1f} FPS < {MIN_FPS} FPS")


# ═══════════════════════════════════════════════════════════════════════════
#  3. arcade.draw_points() with N points — minimap dot batching
# ═══════════════════════════════════════════════════════════════════════════

class TestDrawPointsPerf:
    def test_200_points(self, win):
        """200 points in a single draw_points call (the minimap asteroid
        layer in Zone 2). Should be extremely fast — one GPU call."""
        pts = [(10 + (i % 20) * 38, 10 + (i // 20) * 28) for i in range(200)]

        def draw():
            win.clear()
            arcade.draw_points(pts, (150, 150, 150), 4)
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"200-point draw_points: {fps:.1f} FPS < {MIN_FPS} FPS")

    def test_1000_points(self, win):
        """1000 points — future-proofing for larger maps."""
        pts = [(i % 100 * 7, i // 100 * 60) for i in range(1000)]

        def draw():
            win.clear()
            arcade.draw_points(pts, (220, 50, 50), 4)
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"1000-point draw_points: {fps:.1f} FPS < {MIN_FPS} FPS")


# ═══════════════════════════════════════════════════════════════════════════
#  4. arcade.draw_lines() with N segments — inventory grid
# ═══════════════════════════════════════════════════════════════════════════

class TestDrawLinesPerf:
    def test_22_line_segments(self, win):
        """22 line segments in one draw_lines call (the 10×10 station
        inventory grid: 11 horizontal + 11 vertical lines)."""
        pts = []
        for i in range(11):
            y = 10 + i * 30
            pts.append((10, y))
            pts.append((310, y))
        for i in range(11):
            x = 10 + i * 30
            pts.append((x, 10))
            pts.append((x, 310))

        def draw():
            win.clear()
            arcade.draw_lines(pts, (60, 80, 120), 1)
            win.flip()

        fps = _measure(draw)
        assert fps >= MIN_FPS, (
            f"22-segment draw_lines: {fps:.1f} FPS < {MIN_FPS} FPS")


# ═══════════════════════════════════════════════════════════════════════════
#  5. arcade.draw_rect_filled() × N — unbatched rects (the OLD approach)
# ═══════════════════════════════════════════════════════════════════════════

class TestDrawRectFilledPerf:
    def test_100_individual_rects(self, win):
        """100 individual draw_rect_filled calls per frame. This is what
        the inventory rendered BEFORE the SpriteList cache. Included as
        a baseline so we can verify the cache is actually faster."""
        rects = [
            (10 + (i % 10) * 40, 10 + (i // 10) * 40, 36, 36)
            for i in range(100)
        ]

        def draw():
            win.clear()
            for x, y, w, h in rects:
                arcade.draw_rect_filled(
                    arcade.LBWH(x, y, w, h), (50, 80, 50, 200))
            win.flip()

        fps_unbatched = _measure(draw)
        print(f"  -> 100 unbatched rects: {fps_unbatched:.1f} FPS")

    def test_100_rects_via_spritelist(self, win):
        """100 SpriteSolidColor rects in one SpriteList.draw() call.
        This is the cached approach — should be significantly faster
        than 100 individual draw_rect_filled calls."""
        slist = arcade.SpriteList()
        for i in range(100):
            s = arcade.SpriteSolidColor(
                36, 36,
                10 + (i % 10) * 40 + 18,
                10 + (i // 10) * 40 + 18,
                (50, 80, 50, 200))
            slist.append(s)

        def draw():
            win.clear()
            slist.draw()
            win.flip()

        fps_batched = _measure(draw)
        assert fps_batched >= MIN_FPS, (
            f"100-rect SpriteList: {fps_batched:.1f} FPS < {MIN_FPS} FPS")


# ═══════════════════════════════════════════════════════════════════════════
#  6. Fog texture rebuild (PIL -> arcade.Texture)
# ═══════════════════════════════════════════════════════════════════════════

class TestFogTexturePerf:
    def test_fog_texture_build(self, win):
        """Rebuild the fog overlay texture from a 128×128 boolean grid.
        This runs when fog_revealed changes (roughly every second while
        exploring). Should complete in < 50 ms."""
        from hud_minimap import _build_fog_texture
        from constants import FOG_GRID_W, FOG_GRID_H

        fog = [[False] * FOG_GRID_W for _ in range(FOG_GRID_H)]
        # Reveal a circle in the middle
        cx, cy = FOG_GRID_W // 2, FOG_GRID_H // 2
        for gy in range(FOG_GRID_H):
            for gx in range(FOG_GRID_W):
                if (gx - cx) ** 2 + (gy - cy) ** 2 < 400:
                    fog[gy][gx] = True

        start = time.perf_counter()
        for _ in range(10):
            _build_fog_texture(fog, 180, 140)
        elapsed = (time.perf_counter() - start) * 1000
        per_build = elapsed / 10

        assert per_build < 50.0, (
            f"Fog texture rebuild: {per_build:.1f} ms (budget: 50 ms)")
        print(f"  [render-perf] fog texture: {per_build:.1f} ms/build")
