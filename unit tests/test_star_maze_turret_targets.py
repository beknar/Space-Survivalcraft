"""Star Maze: station turrets target the full enemy population.

Pre-fix: ``StarMazeZone.update`` swapped ``gv.alien_list =
self._maze_aliens`` for the ``update_buildings`` call, so turrets
only saw maze aliens.  Stalkers + Z2-style aliens populating the
zone outside the maze structures were ignored.
"""
from __future__ import annotations

import arcade
import pytest


@pytest.fixture(scope="module", autouse=True)
def _arcade_window():
    w = arcade.Window(800, 600, visible=False)
    yield w
    w.close()


def _enter_star_maze(gv):
    from zones import ZoneID
    if gv._zone.zone_id != ZoneID.STAR_MAZE:
        gv._transition_zone(ZoneID.STAR_MAZE)


# ── Combined target list contents ─────────────────────────────────────────


class TestTurretTargetsIncludeAllStarMazeEnemies:
    def test_alien_list_during_update_buildings_combines_lists(
            self, monkeypatch):
        """When ``StarMazeZone.update`` calls ``update_buildings``,
        ``gv.alien_list`` must contain every mobile hostile sprite
        the zone exposes — not just the maze aliens.  Spy on
        update_buildings to capture the swapped list."""
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone

        # Capture the alien_list contents at the moment
        # update_buildings is invoked.
        captured: dict = {}
        import update_logic as _ul
        original = _ul.update_buildings

        def spy(gv_, dt):
            # Capture references to all current lists for cross-check.
            captured["len"] = len(gv_.alien_list)
            captured["sprite_ids"] = {
                id(s) for s in list(gv_.alien_list)
            }
            captured["maze_alien_ids"] = {
                id(a) for a in zone._maze_aliens
            }
            captured["stalker_ids"] = {
                id(s) for s in zone._stalkers
            }
            captured["z2_alien_ids"] = {
                id(a) for a in zone._aliens
            }
            return original(gv_, dt)

        monkeypatch.setattr(_ul, "update_buildings", spy)
        # Also patch through the import inside zones.star_maze.
        import zones.star_maze as _sm
        # No re-import needed — star_maze does
        # ``from update_logic import update_buildings, ...``
        # inside its update method, so a setattr on update_logic
        # is enough.
        zone.update(gv, 1 / 60)

        # The captured alien_list must include EVERY sprite from
        # _maze_aliens, _stalkers, and _aliens.
        for label, ids in (
                ("maze aliens", captured["maze_alien_ids"]),
                ("stalkers", captured["stalker_ids"]),
                ("z2 aliens", captured["z2_alien_ids"])):
            missing = ids - captured["sprite_ids"]
            assert not missing, (
                f"turret targeting list missing {label}: "
                f"{len(missing)} sprite(s) not present")


# ── Turret damage actually lands on a stalker ─────────────────────────────


class TestTurretTargetListIsCached:
    """Regression: an earlier version of this fix built a fresh
    ``arcade.SpriteList`` each frame and appended ~75 sprites
    without ever calling ``clear()`` on the temp list.  ``append``
    adds the SpriteList to each sprite's ``sprite_lists`` back-
    reference tuple, so the temp list (out of scope after the
    swap restoration) was kept alive by the contained sprites —
    the per-sprite ``sprite_lists`` tuple grew at ~75 entries per
    frame.  Sprite-position updates iterate ``sprite_lists`` to
    invalidate buffers, so after ~60 s every sprite carried
    thousands of stale refs and FPS collapsed below 20.

    Fix: cache ONE SpriteList on the zone and ``clear()``-then-
    refill it each frame.  ``clear()`` removes the back-reference
    cleanly so re-adding the same sprite next frame doesn't
    accumulate.

    These tests pin the cached list IS reused across ticks AND
    that no sprite holds more than one reference to the cached
    list at any time.
    """

    def test_turret_target_list_object_is_stable_across_ticks(self):
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone
        first_id = id(zone._turret_target_list)
        for _ in range(10):
            zone.update(gv, 1 / 60)
        assert id(zone._turret_target_list) == first_id, (
            "cached turret-target list got swapped — "
            "per-frame allocation regression")

    def test_no_back_reference_accumulation(self):
        """After ticking many frames, no sprite that lives in the
        Star Maze should hold MORE THAN ONE reference to the
        cached turret-target list.  Catches the leak that caused
        the sub-20-FPS collapse — without the fix, every sprite
        accumulated +1 reference per frame."""
        from game_view import GameView
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone
        for _ in range(20):
            zone.update(gv, 1 / 60)
        cached = zone._turret_target_list
        for src in (zone._maze_aliens, zone._stalkers,
                    getattr(zone, "_aliens", None) or ()):
            for s in src:
                count = sum(1 for sl in s.sprite_lists
                            if sl is cached)
                assert count <= 1, (
                    f"sprite holds {count} refs to the cached "
                    f"turret-target list — back-reference leak "
                    f"regressed")


class TestTurretProjectileDamagesStalker:
    """End-to-end: spawn a turret + a stalker right next to each
    other; tick the zone for a frame; the turret-projectile
    collision handler should reduce the stalker's HP."""

    def test_stalker_takes_turret_damage(self):
        from game_view import GameView
        from sprites.building import create_building
        from sprites.projectile import Projectile
        gv = GameView(faction="Earth", ship_type="Cruiser",
                       skip_music=True)
        _enter_star_maze(gv)
        zone = gv._zone
        # Pick a stalker, parked at a known location.
        assert len(zone._stalkers) > 0
        st = zone._stalkers[0]
        st.center_x = 6000.0
        st.center_y = 6000.0
        before_hp = st.hp
        # Inject a turret projectile centered on the stalker so
        # collision detection lands on the first frame.
        proj_tex = gv._turret_laser_tex
        proj = Projectile(
            proj_tex, st.center_x, st.center_y,
            heading=0.0, speed=1.0, max_dist=1000.0,
            scale=1.0, damage=20.0)
        gv.turret_projectile_list.append(proj)
        # Tick the zone — update_buildings runs
        # handle_turret_projectile_hits which checks
        # gv.alien_list, which is the combined list during this
        # call.
        zone.update(gv, 1 / 60)
        # Stalker took damage.
        assert st.hp < before_hp, (
            f"stalker HP unchanged after turret projectile hit: "
            f"before={before_hp} after={st.hp}")
