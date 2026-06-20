"""Two regression tests:

* HUD module-slot + quick-use drag previews now render via a
  dedicated ``draw_drag_preview()`` method called AFTER the
  inventory grids paint, so an in-flight drag stays visible above
  the cargo / station overlays instead of disappearing under them.

* Parked ships in the Star Maze now have their AI Pilot ticked
  every frame.  Star Maze.update was previously missing the
  ``_update_parked_ships`` call (Zone 2 has it) so installed
  AI Pilots never patrolled.
"""
from __future__ import annotations

import arcade
import pytest


# ── HUD draw_drag_preview wiring ─────────────────────────────────────────

class TestHUDDragPreviewMethod:
    def test_draw_drag_preview_method_exists(self):
        from hud import HUD
        # Public method that draw_logic now calls AFTER inventories.
        assert callable(getattr(HUD, "draw_drag_preview", None))

    def test_draw_drag_preview_no_drag_is_safe(self):
        # When neither slot is being dragged, the method should be
        # a cheap no-op (still callable without raising).
        from hud import HUD
        h = HUD.__new__(HUD)
        # Only the fields the method touches need to exist.
        h._mod_drag_src = None
        h._mod_drag_type = None
        h._qu_drag_src = None
        h._qu_drag_type = None
        h.draw_drag_preview()  # must not raise

    def test_draw_logic_calls_drag_preview_after_inventories(self):
        # Source-level pin: the call must come AFTER both inventory
        # draws so the dragged icon stays on top.  Inspect the overlay
        # draw source to confirm ordering — keeps the visual contract
        # from regressing under a future refactor.  (The overlay paint
        # order moved from ``draw_ui`` into ``_draw_overlays`` in the
        # 2026-06-07 draw_ui decomposition; the contract is unchanged.)
        import inspect
        from draw_logic import _draw_overlays
        src = inspect.getsource(_draw_overlays)
        inv_idx = src.find("gv.inventory.draw()")
        drag_idx = src.find("gv._hud.draw_drag_preview()")
        assert inv_idx >= 0
        assert drag_idx >= 0
        assert drag_idx > inv_idx, (
            "draw_drag_preview must be called AFTER gv.inventory.draw "
            "so the drag icon overlays the inventory grid."
        )


# ── Star Maze AI Pilot patrol regression ─────────────────────────────────

class TestStarMazeAIPilotPatrol:
    def _setup(self, monkeypatch):
        """Build a GameView, jump to Star Maze, drop a Home Station +
        a parked ship with AI Pilot installed.  Returns (gv, ps)."""
        from game_view import GameView
        from zones import ZoneID
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip
        from sprites.building import create_building
        from PIL import Image
        tex = arcade.Texture(Image.new("RGBA", (32, 32), (0, 200, 0, 255)))
        # Use monkeypatch (not a bare attribute assignment) so the
        # override is restored after the test — a permanent assignment
        # here leaks the stub into later tests that exercise the real
        # texture-extraction cache.
        monkeypatch.setattr(
            PlayerShip, "_extract_ship_texture",
            staticmethod(lambda *a, **k: tex))
        gv = GameView(faction="Earth", ship_type="Cruiser",
                      ship_level=1)
        gv._transition_zone(ZoneID.STAR_MAZE, "bottom")
        # Clear every spawned hostile from the maze so the patrol
        # mechanics test is isolated from engage-mode.  ``_world_seed``
        # is randomised on zone construction (``zones/star_maze.py``),
        # so without this the Z2 alien spawn positions vary between
        # runs — when an alien lands within ``AI_PILOT_DETECT_RANGE``
        # of the parked ship, the AI pilot enters engage mode (lateral
        # chase at AI_PILOT_SPEED) instead of patrol (snap-to-ring at
        # ~260 px on frame 1), and the 1-second movement budget falls
        # short of the 100 px assertion.  The test specifically
        # exercises the patrol code path; engagement mechanics are
        # covered by the dedicated AI-pilot combat suite.
        zone = gv._zone
        for attr in ("_aliens", "_maze_aliens", "_stalkers"):
            lst = getattr(zone, attr, None)
            if lst is not None:
                lst.clear()
        gv.alien_list.clear()
        # Plant a Home Station inside the Star Maze.
        home_tex = gv._building_textures["Home Station"]
        home = create_building("Home Station", home_tex,
                                6000.0, 6000.0, scale=0.5)
        gv.building_list.append(home)
        # Park a ship next to the station with AI Pilot installed.
        ps = ParkedShip(faction="Earth", ship_type="Cruiser",
                         ship_level=1, x=6100.0, y=6000.0)
        ps.module_slots = ["ai_pilot", None, None, None]
        gv._parked_ships.append(ps)
        return gv, ps

    def test_ai_pilot_actually_moves_in_star_maze(self, monkeypatch):
        gv, ps = self._setup(monkeypatch)
        start = (ps.center_x, ps.center_y)
        # 60 ticks at 1/60 s = 1 s of update.  In that window the
        # AI pilot should snap onto the patrol ring AND start
        # rotating around it — well over 100 px of total movement.
        for _ in range(60):
            gv.on_update(1 / 60)
        moved = ((ps.center_x - start[0]) ** 2
                 + (ps.center_y - start[1]) ** 2) ** 0.5
        assert moved > 100.0, (
            f"AI pilot only moved {moved:.1f} px in 1 s — "
            f"patrol is not running"
        )
        # Install latch should have flipped True on the first
        # update_parked tick.
        assert ps._ai_pilot_was_installed is True

    def test_star_maze_update_calls_parked_ship_helpers(self):
        # Source-level pin so a future refactor can't accidentally
        # drop the parked-ship update from the Star Maze loop.
        import inspect
        from zones import star_maze
        src = inspect.getsource(star_maze.StarMazeZone.update)
        assert "_update_parked_ships(gv, dt)" in src
        assert "handle_parked_ship_damage(gv)" in src
        assert "update_buildings(gv, dt)" in src
